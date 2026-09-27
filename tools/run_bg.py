r"""run_bg —— 长命令分离起 + 哨兵轮询（卡 066 / `T-G160`；**只用标准库**）。

**为什么有这个工具**（卡 §1）：工人单次 CLI 调用有 **10 分钟上限**，而本仓全量门禁
实测 **6–7 分钟**（pytest ≈107s / render ≈110s / ui_flow ≈176s / 062 读数）；一旦
「重采黄金 + 再跑一遍」**必越过** 10 分钟 → 调用被掐 → 起过的 `serve.py` / 无头 Edge
变**孤儿** → 下一张卡撞端口 / 撞进程 → 跨树误杀（铁律 27/28）。058 为此烧掉
**37M tokens / 2h15m**，其中一大块就是在跟这个上限搏斗。

**它怎么治**：

    run     —— 用**分离进程**（Windows: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`）
              起命令，`stdout`/`stderr` **都重定向进 `--log`**（同一份，顺序即真实顺序），
              然后**立刻返回**（不 wait、不 join）；打印 `pid=` / `log=` / `rc_file=`，退出码 0。
              ★ 父进程退出**不带走**子进程 —— 这是本工具**唯一**的存在理由（卡 §5 反证 1/2）。
    status  —— 判据**不看端口、不看进程名**，只看**哨兵文件** `<log>.rc`（子进程结束时由
              **包装器**写入退出码；先写临时文件再 `os.replace`，抗「日志还在写」）：
              打印 `state=running` 或 `state=done rc=<N>`，外加「日志静默秒数」（按 log 的 mtime）
              与日志尾 `--tail` 行（默认 20）。

用法：

    python -X utf8 tools/run_bg.py run --log <日志路径> [--cwd <目录>] -- <命令> [参数...]
    python -X utf8 tools/run_bg.py status --log <日志路径> [--tail N]

★ **不用 shell**：一律 `subprocess.Popen(argv_list, ...)` —— 不许 `shell=True`，
  不许把命令拼成一个字符串（Windows 上 shell 会把 `--` 之后的参数重新解释一遍：
  引号地狱 + 注入风险）。`--` 之后的参数**原样**传下去。
★ **不改被测命令本身**：rc 由**外层包装器**（本文件的隐藏子命令 `__wrap__`）落盘，
  被测命令拿不到、也不需要任何新参数（所以能给 `run_gates.py` 原样用）。

退出码（`status` 约定，卡模板里可以直接 `if rc==3 → 门禁红`）：

    running               -> 0
    done rc=0             -> 0
    done rc!=0            -> 3
    用法错 / 日志不存在    -> 2
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import traceback

# Windows 分离标志（卡 §2.1 逐字指定）：新进程组 + 无控制台，父退出不带走子进程。
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008

_RC_SUFFIX = ".rc"

USAGE = """用法：
  python -X utf8 tools/run_bg.py run --log <日志路径> [--cwd <目录>] -- <命令> [参数...]
  python -X utf8 tools/run_bg.py status --log <日志路径> [--tail N]

  run     分离进程起命令，stdout/stderr 进 --log，立刻返回 pid=/log=/rc_file=
  status  按哨兵 <log>.rc 判终态：running(0) / done rc=0(0) / done rc!=0(3)
"""


def _rc_path(log_abs: str) -> str:
    return log_abs + _RC_SUFFIX


def _fail(message: str) -> None:
    """用法/参数错 → 明确报错（人话、非 traceback）并退出码 2。"""
    sys.stderr.write(f"[run_bg] {message}\n")
    raise SystemExit(2)


def _split_at_dash(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        _fail("缺少 `--` 分隔符：`... [选项] -- <命令> [参数...]`")
    i = argv.index("--")
    return argv[:i], argv[i + 1 :]


def _detach_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True  # POSIX 等价物：setsid
    return kwargs


# --------------------------------------------------------------------------- run


def cmd_run(argv: list[str]) -> int:
    opts, command = _split_at_dash(argv)
    parser = argparse.ArgumentParser(prog="run_bg run", add_help=False)
    parser.add_argument("--log", required=True)
    parser.add_argument("--cwd", default=None)
    ns = parser.parse_args(opts)

    if not command:
        _fail("`--` 之后没有命令")

    log_abs = os.path.abspath(ns.log)
    cwd = os.path.abspath(ns.cwd) if ns.cwd else None
    if cwd is not None and not os.path.isdir(cwd):
        _fail(f"--cwd 不是目录：{cwd}")

    # 日志先建出来（truncate）+ 清掉旧哨兵：status 从这一刻起可读，且不会误读上一次的 rc。
    # ★ 只在这里**开一下再关**（判可写 + 截断）：真正持有日志句柄的是包装器 —— 见 §7.1 那个坑，
    #   DETACHED_PROCESS 的子进程**不把重定向过的 std 句柄再传下去**，孙进程 stdout=None 会丢输出。
    try:
        open(log_abs, "wb").close()
    except OSError as exc:
        _fail(f"--log 不可写：{log_abs}（{exc}）")
    rc_abs = _rc_path(log_abs)
    try:
        os.remove(rc_abs)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - 罕见（权限/占用）
        _fail(f"旧的哨兵文件删不掉：{rc_abs}（{exc}）")

    wrapper = [
        sys.executable,
        "-X",
        "utf8",
        os.path.abspath(__file__),
        "__wrap__",
        "--log",
        log_abs,
    ]
    if cwd is not None:
        wrapper += ["--cwd", cwd]
    wrapper += ["--", *command]

    try:
        proc = subprocess.Popen(
            wrapper,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_detach_kwargs(),
        )
    except OSError as exc:
        _fail(f"起分离进程失败：{exc}")

    print(f"pid={proc.pid}")
    print(f"log={log_abs}")
    print(f"rc_file={rc_abs}")
    return 0


# ------------------------------------------------------------------------ wrap


def cmd_wrap(argv: list[str]) -> int:
    """隐藏子命令：**在外层**跑真命令并落哨兵。不改被测命令、不给它加参数。

    ★ 自己**显式**把日志句柄交给被测命令（不靠 std 继承，见 cmd_run 里的坑注）。
    """
    opts, command = _split_at_dash(argv)
    parser = argparse.ArgumentParser(prog="run_bg __wrap__", add_help=False)
    parser.add_argument("--log", required=True)
    parser.add_argument("--cwd", default=None)
    ns = parser.parse_args(opts)

    log_abs = os.path.abspath(ns.log)
    cwd = os.path.abspath(ns.cwd) if ns.cwd else None
    rc = 70
    with open(log_abs, "ab") as out:
        try:
            rc = _run_foreground(command, cwd, out)
        except BaseException:  # pragma: no cover - 兜底：异常也留痕并落 rc
            out.write("[run_bg] 包装器异常：\n".encode())
            out.write(traceback.format_exc().encode())
            out.flush()
            rc = 70
    _write_rc(log_abs, rc)
    return 0


def _run_foreground(command: list[str], cwd: str | None, out) -> int:
    # stdout/stderr **显式**指向同一个日志句柄 —— 同一份、顺序即真实顺序。
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdout=out, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        out.write(f"[run_bg] 命令不存在：{command[0]}\n".encode())
        return 127
    except OSError as exc:
        out.write(f"[run_bg] 无法启动命令 {command[0]!r}：{exc}\n".encode())
        return 126
    return proc.wait()


def _write_rc(log_abs: str, rc: int) -> None:
    # 先写临时文件再原子替换：status 永远读不到半截（卡 §7.4）。
    target = _rc_path(log_abs)
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"{int(rc)}\n")
    os.replace(tmp, target)


# ---------------------------------------------------------------------- status


def cmd_status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="run_bg status", add_help=False)
    parser.add_argument("--log", required=True)
    parser.add_argument("--tail", type=int, default=20)
    ns = parser.parse_args(argv)

    log_abs = os.path.abspath(ns.log)
    if not os.path.isfile(log_abs):
        _fail(f"日志不存在：{log_abs}")

    rc = _read_rc(log_abs)
    idle = max(0.0, time.time() - os.path.getmtime(log_abs))
    lines = _tail_lines(log_abs, max(0, ns.tail))

    if rc is None:
        print("state=running")
    else:
        print(f"state=done rc={rc}")
    print(f"log={log_abs}")
    print(f"rc_file={_rc_path(log_abs)}")
    print(f"idle_seconds={idle:.1f}")
    print(f"tail_lines={len(lines)}")
    for line in lines:
        print(line)

    if rc is None or rc == 0:
        return 0
    return 3


def _read_rc(log_abs: str) -> int | None:
    """读哨兵；文件不在 / 还空着 / 半截 → None（= 还在跑，不崩，卡 §7.6）。"""
    try:
        with open(_rc_path(log_abs), encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _tail_lines(path: str, n: int) -> list[str]:
    if n <= 0:
        return []
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        block = 8192
        data = b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(block, size)
            size -= step
            fh.seek(size)
            data = fh.read(step) + data
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


# ------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write(USAGE)
        return 2
    if args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    mode, rest = args[0], args[1:]
    if mode == "run":
        return cmd_run(rest)
    if mode == "status":
        return cmd_status(rest)
    if mode == "__wrap__":
        return cmd_wrap(rest)
    _fail(f"未知子命令：{mode}（只认 run / status）")
    return 2  # pragma: no cover - _fail 已抛 SystemExit


if __name__ == "__main__":
    raise SystemExit(main())
