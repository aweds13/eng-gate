"""长命令跑法：边跑边落日志、边报心跳。

为什么有这个工具：后台跑长命令时如果写成 `python x.py | tail -3`，
管道会把所有输出攒到进程结束才吐一次，中途看作业输出永远是空的，
看起来像「卡死」。本工具把子进程输出逐行写进日志文件，并且每隔
`--every` 秒在**自己的 stdout** 打一行心跳（含最后一行输出），
所以后台作业的输出是**增量可读**的。

用法：
    python -X utf8 tools/run_logged.py --log gates/diag/land-A302.log -- \
        python -X utf8 tools/wb_land.py --card A302 ...

退出码 = 子进程退出码（原样透传，不吞）；子进程**起不来**时回 `EXIT_NOT_FOUND`
（127），并点名是哪个 token —— 不打印 traceback，也不猜。

## 为什么要先解析 argv[0]（卡 E102 · T-AG611）

`Popen(["npm", "--version"])` 在 Windows 上抛
`FileNotFoundError: [WinError 2] 系统找不到指定的文件。` —— `npm` 在 PATH 里
只有 `npm.CMD`，而 CreateProcess 不做 PATHEXT 解析。所以本工具先 `shutil.which`
解析，再分两路起：

- **普通程序**（`.exe` / `.com` / 无后缀）⇒ `Popen([resolved, *args])`：
  参数**原样**到达子进程（`&`、`^`、引号都不经过 shell）。
- **批处理**（`.cmd` / `.bat`）⇒ 必须过 cmd：整行自己加引号后交给
  `%COMSPEC% /d /s /c "<整行>"`。★ 这类目标的 `%VAR%` 会被 cmd 展开 ——
  那是 cmd 对批处理的固有语义，这里不偷偷改写参数（实测直接
  `Popen([resolved, "a&b"])` 会把 `a&b` 拆成两条命令，那才是真的改了参数）。
**解析不到** ⇒ `ProgramNotFoundError`，由 `main` 响亮地点名，回 127。

心跳循环按 `POLL_SLICE` 的步长轮询、每到 `--every` 才打一行 —— 短命令不必
等满一个心跳周期才收工。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

TAIL_LINES = 6
#: 批处理后缀：只有它们必须过 cmd（Windows 上 PATHEXT 里其余都是可执行映像）。
BATCH_SUFFIXES = (".cmd", ".bat")
#: 子进程起不来时的退出码：127 = 命令没起来，跟子进程自己的退出码分开。
EXIT_NOT_FOUND = 127
#: 轮询步长上限：短命令不必等满一个 --every 才收工。
POLL_SLICE = 0.2
#: 一行里出现这些字符就必须整段加引号（cmd 会在这里断词 / 解释）。
_CMD_SPECIAL = ' \t&|<>^()"%!;=,'


class ProgramNotFoundError(Exception):
    """`argv[0]` 在 PATH 和文件系统里都找不到 —— 报名字，不猜路径。"""

    def __init__(self, name: str) -> None:
        super().__init__(f"找不到可执行文件：{name}")
        self.name = name


def _pathext() -> tuple[str, ...]:
    """PATHEXT 的小写形式（带点）；环境里没有就给 Windows 的默认值。"""
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return tuple(part.strip().lower() for part in raw.split(os.pathsep) if part.strip())


def _has_path(name: str) -> bool:
    """argv[0] 自带路径吗（分隔符或盘符）。"""
    return "/" in name or "\\" in name or bool(os.path.dirname(name))


def resolve_program(name: str) -> str | None:
    """把 argv[0] 解析成真实存在的文件路径；解析不出回 None。

    自带路径的就按路径找（没后缀时再按 PATHEXT 补），裸名交给 `shutil.which`
    （它已经会按 PATHEXT 展开 —— `which("npm")` ⇒ `...\\npm.CMD`）。
    """
    if not name:
        return None
    if _has_path(name):
        direct = Path(name)
        if direct.is_file():
            return str(direct)
        if not direct.suffix:
            for suffix in _pathext():
                candidate = direct.with_name(direct.name + suffix)
                if candidate.is_file():
                    return str(candidate)
        return None
    return shutil.which(name)


def needs_cmd_shell(resolved: str) -> bool:
    """这个目标是不是批处理（⇒ 必须过 cmd，不能直接 exec）。"""
    if os.name != "nt":
        return False
    return resolved.lower().endswith(BATCH_SUFFIXES)


def quote_for_cmd(part: str) -> str:
    """给 cmd 那一行里的一个参数加引号：没特殊字符就原样，否则整段加引号、内部引号翻倍。"""
    if part and not any(ch in part for ch in _CMD_SPECIAL):
        return part
    return '"' + part.replace('"', '""') + '"'


def cmd_line(argv: Sequence[str]) -> str:
    """把 argv 拼成 `cmd /d /s /c "<整行>"` —— 外层那对引号由 `/s` 剥掉，内层原样。"""
    comspec = os.environ.get("COMSPEC") or "cmd.exe"
    inner = " ".join(quote_for_cmd(part) for part in argv)
    return f'{comspec} /d /s /c "{inner}"'


def prepare_command(cmd: Sequence[str]) -> tuple[str | list[str], str]:
    """→ (交给 Popen 的形态, 一句话说明怎么起的)。

    普通程序给 argv 列表（Popen 自己拼命令行，参数逐字节原样）；批处理给一整行
    字符串（字符串形态下 Windows 才把它原样交给 CreateProcess —— 先拼成列表再让
    Python 重新加引号，含空格的 .cmd 路径会被双层引号弄坏）。
    """
    if not cmd:
        raise ProgramNotFoundError("")
    resolved = resolve_program(cmd[0])
    if resolved is None:
        raise ProgramNotFoundError(cmd[0])
    rest = list(cmd[1:])
    if needs_cmd_shell(resolved):
        return cmd_line([resolved, *rest]), f"过 cmd（批处理）：{resolved}"
    return [resolved, *rest], f"直接 exec：{resolved}"


def _reader(stream, log_path: Path, state: dict) -> None:
    """把子进程输出逐行落盘，并把最后一行留在 state 里给心跳用。"""
    with log_path.open("a", encoding="utf-8", errors="replace") as fh:
        for line in stream:
            fh.write(line)
            fh.flush()
            text = line.rstrip("\n")
            if text:
                state["last"] = text
        state["eof"] = True


def _fail(log_path: Path, message: str, name: str) -> int:
    """起不来：打一行人话 + 落进日志 + 回 EXIT_NOT_FOUND（不打印 traceback）。"""
    print(message, flush=True)
    print(f"[完] 退出码={EXIT_NOT_FOUND} 没跑起来 日志={log_path}", flush=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(message + "\n")
        if name:
            fh.write(f"（找不到的是：{name}）\n")
    return EXIT_NOT_FOUND


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑长命令：日志逐行落盘 + 定时心跳")
    parser.add_argument("--log", required=True, help="日志文件路径（追加写）")
    parser.add_argument("--every", type=float, default=15.0, help="心跳间隔秒数，默认 15")
    parser.add_argument("--tail", type=int, default=TAIL_LINES, help="结束时回放最后几行，默认 6")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="-- 之后是要跑的命令")
    args = parser.parse_args(argv)

    # ★ 只剥**开头**那个分隔符：命令自己的 -- 参数（pytest -- --collect-only）要留着。
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("[用法] 缺命令：python tools/run_logged.py --log <文件> -- <命令...>", flush=True)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    state: dict = {"last": "", "eof": False}

    with log_path.open("a", encoding="utf-8", errors="replace") as head:
        head.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} 起跑：{' '.join(cmd)} ===\n")
        head.flush()

    try:
        prepared, how = prepare_command(cmd)
    except ProgramNotFoundError as exc:
        msg = f"★ 起不来：{exc}（PATH 里没有，也没有同名 .exe/.cmd/.bat）"
        return _fail(log_path, msg, exc.name)

    print(f"[起] {how}", flush=True)
    try:
        proc = subprocess.Popen(
            prepared,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return _fail(log_path, f"★ 起不来：{' '.join(cmd)} ⇒ {exc}", cmd[0])

    assert proc.stdout is not None
    reader = threading.Thread(target=_reader, args=(proc.stdout, log_path, state), daemon=True)
    reader.start()

    print(f"[跑] {log_path} | 心跳 {args.every:g}s | pid={proc.pid}", flush=True)
    beat = time.time()
    while proc.poll() is None:
        time.sleep(min(max(args.every, 0.01), POLL_SLICE))
        now = time.time()
        if now - beat >= args.every:
            beat = now
            elapsed = int(now - started)
            last = state.get("last", "")
            print(f"[心跳] {elapsed}s | {last[:120]}", flush=True)

    reader.join(timeout=5)
    code = proc.returncode or 0
    elapsed = int(time.time() - started)
    print(f"[完] 退出码={code} 用时={elapsed}s 日志={log_path}", flush=True)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.tail :]:
        print(f"  {line}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
