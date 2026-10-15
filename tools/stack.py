"""一起起、分别停：看门 / timeflow / 工作台页 / 禅道 / Trae 的起停 + 现读（卡 241 · T-G359）。

卡 243（T-G364）：加 `board` 工作台页、修「判活太快」、修 trae 的 timeout 被抢。
用户 2026-10-14 令「起可以绑在一起，**停要分开**」。本工具只做四件事：

- `start`：把**没在跑的**起起来；已在跑的**如实说「已在跑」**、不重复起；
  起完给**有限的等待窗口**（默认 20 秒、每 0.5 秒探一次，卡 243 修「判活太快」），
  等不到就报原话「发起了，但 N 秒内端口 X 还没起来」，**不许谎报「已起」**；
- `stop <名>`：**先核对 pid 身份**（映像是白名单里的那个）再审—— 不对就拒绝并点名；
- `status`：**现读**（真进程表 + 真端口），谁没起就写「没起」，**不静默成功**；
- `list`：这张表本身（名字 / 怎么起 / 怎么判活着 / 白名单）。

边界（卡 241 §4 + 卡 243 §5，一条都不越）
- 起停**只碰下表那五件**（卡 243 起加 `board`）；不碰 `~/.dsh`、不碰 DSH 本体、**不注册计划任务**；
- `stop` 遇到**身份不符**的 pid ⇒ **拒绝动手并点名**（那可能是别人的 python/node）；
  进程已不在 ⇒ 如实说「没在跑」并**清掉过期 pid 文件**（说清做了这件事）；
- 判活着一律**真进程 / 真端口**；拿不到就说拿不到，**不为了"看起来起了"去放宽**；
- trae 走 cmd 包装：给子进程一个**只含系统目录的 PATH**（卡 243）——
  桌面那份启动 cmd 里的 `timeout /t` 因此解析到 System32 的真 timeout.exe，
  不再被 MSYS 的 GNU timeout 抢走；桌面那份 cmd 本身一个字不动。

为什么不用 `os.kill(pid, 0)` 探活：Windows 上 CPython 把它实现成 `OpenProcess` +
`TerminateProcess` ⇒ 会**真把那个进程杀掉**（口径坑 27）。
判活一律 `tasklist`，动手一律 `taskkill`。
"""

from __future__ import annotations

import argparse
import locale
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

# `python -P -X utf8 tools/stack.py` 也要能 import pool（照 tools/dsh_panel.py 的写法）：
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 148：子进程一律不弹窗（唯一真源）

#: 仓库根（本文件在 tools/ 下）。
ROOT = Path(__file__).resolve().parent.parent
#: 运行痕迹目录：pid 文件 + 日志（`gates/diag/**` 本就 gitignore，见 .gitignore）。
STACK_DIR = ROOT / "gates" / "diag" / "stack"


class Component(NamedTuple):
    """上表的一行。`whitelist` 是**映像白名单**（小写比较）；`ports` 为空表示只看 pid。"""

    name: str
    whitelist: tuple[str, ...]
    ports: tuple[int, ...]
    start: list[str] | None          # 起它的 argv（cwd = ROOT）；None ⇒ 只能手动
    manual: str                      # 不能脚本起时的「手动一步」说明


#: 组件表（卡 241 §1；卡 243 §1 起加 `board` 工作台页，共五件）。
COMPONENTS: dict[str, Component] = {
    "closer": Component(
        name="closer",
        whitelist=("bash.exe",),
        ports=(),
        start=["bash", "gates/diag/_closer_watch.sh"],
        manual="",
    ),
    "timeflow": Component(
        name="timeflow",
        whitelist=("python.exe",),
        ports=(8520,),
        start=[sys.executable, "-X", "utf8", "tools/serve.py"],
        manual="",
    ),
    "board": Component(
        name="board",
        # 卡 243：工作台页（tools/wb_dash.py，默认 127.0.0.1:8787），能脚本起。
        whitelist=("python.exe",),
        ports=(8787,),
        start=[sys.executable, "-X", "utf8", "tools/wb_dash.py"],
        manual="",
    ),
    "zentao": Component(
        name="zentao",
        # ★ 本机实测：ZenPanel 是 GUI，Apache/MySQL 由它渲染 conf 后拉起 ⇒ 不脚本起。
        whitelist=("httpd.exe", "mysqld.exe"),
        ports=(80, 3306),
        start=None,
        manual=(
            "禅道要 ZenPanel（GUI）手动起：装到 D:\\zentao\\ 后双击 "
            "D:\\zentao\\ZenTao\\ZenTao.exe，在面板里点启 Apache 与 MySQL"
            "（见 docs/禅道-怎么起.md §3）。本工具**不假装起了**。"
        ),
    ),
    "trae": Component(
        name="trae",
        # 卡表写的是 Trae.exe；★ 本机实测映像是 "Trae CN.exe"（监听 9333，pid 22340）
        # ⇒ 两个都收（主控若要逐字执行请删掉 "trae cn.exe"）。
        whitelist=("trae.exe", "trae cn.exe", "node.exe"),
        ports=(9333,),
        # 卡 243：显式 cmd.exe（配合 `_child_env` 的受限 PATH，见模块头）。
        start=["cmd.exe", "/c", "D:\\桌面\\启动Trae-带调试口.cmd"],
        manual="",
    ),
}


def _console_encoding() -> str:
    """`tasklist` / `taskkill` / `netstat` 输出按**系统区域编码**解（这台 cp936）。

    ★ 照 `tools/pool_mcp.py::_console_encoding`（口径坑 31）：本仓一律 `-X utf8`，
    所以 **不能**用 `locale.getpreferredencoding(False)`（它会回 utf-8，等于没修）；
    `locale.getencoding()` 才回系统区域编码。解不开的字节走 `errors="replace"`。
    """
    return (locale.getencoding() if hasattr(locale, "getencoding")
            else locale.getpreferredencoding(False)) or "utf-8"


def pidfile_path(name: str) -> Path:
    """`gates/diag/stack/<名>.pid`。"""
    return STACK_DIR / f"{name}.pid"


def log_path(name: str) -> Path:
    """`gates/diag/stack/<名>.log`（起进程时 stdout/stderr 往这里灌）。"""
    return STACK_DIR / f"{name}.log"


def read_pidfile(name: str) -> int | None:
    """读 pid 文件；没有 / 读不出整数 ⇒ `None`（**不当作"没在跑"**，由探活决定）。"""
    path = pidfile_path(name)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        print(f"{name}：pid 文件读不出（{type(exc).__name__}: {exc}）—— 当作没有 pid 记录")
        return None


def write_pidfile(name: str, pid: int) -> None:
    """落 `gates/diag/stack/<名>.pid`（运行痕迹）。"""
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    pidfile_path(name).write_text(str(int(pid)), encoding="utf-8")


def image_of(pid: int) -> str | None:
    """`tasklist` 拿这个 pid 的**映像名**；拿不到 ⇒ `None`（判不出，不当作"没在跑"）。"""
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding=_console_encoding(),
            errors="replace", **NO_WINDOW,
        )
    except OSError as exc:
        print(f"tasklist 起不来：{type(exc).__name__}: {exc}")
        return None
    line = next((ln for ln in (done.stdout or "").splitlines() if ln.strip()), "")
    if done.returncode != 0 or not line.startswith('"'):
        return None
    return line[1:line.index('"', 1)]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """真连一下 `host:port`（真端口，不是"我觉得它在"）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def port_owner(port: int) -> int | None:
    """`netstat -ano` 拿监听该端口的 pid；拿不到 ⇒ `None`。"""
    try:
        done = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, encoding=_console_encoding(),
            errors="replace", **NO_WINDOW,
        )
    except OSError as exc:
        print(f"netstat 起不来：{type(exc).__name__}: {exc}")
        return None
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] == str(port):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def terminate(pid: int) -> tuple[bool, str]:
    """`taskkill /F /T /PID <n>`（★ 绝不 `os.kill`，见模块头）。"""
    try:
        done = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            capture_output=True, text=True, encoding=_console_encoding(),
            errors="replace", **NO_WINDOW,
        )
    except OSError as exc:
        return False, f"taskkill 起不来：{type(exc).__name__}: {exc}"
    return done.returncode == 0, ((done.stdout or "") + (done.stderr or "")).strip()


def alive(name: str) -> tuple[bool, str]:
    """**现读**：这件现在活着吗？（真进程表 + 真端口）⇒ `(活着吗, 说人话的细节)`。"""
    comp = COMPONENTS[name]
    pid = read_pidfile(name)
    img = image_of(pid) if pid is not None else None

    if comp.ports:
        open_ports = [p for p in comp.ports if port_open(p)]
        if not open_ports:
            if pid is not None and img is not None:
                return False, f"pid {pid} 在，但端口 {comp.ports} 都连不上"
            return False, "端口都不通，也没有活的 pid"
        ports_txt = "、".join(str(p) for p in open_ports)
        who = img
        if who is None:
            owner = port_owner(open_ports[0])
            who = image_of(owner) if owner is not None else None
        if who is not None and who.lower() not in comp.whitelist:
            return True, f"端口 {ports_txt}；★ 映像是 {who}，不在白名单 {comp.whitelist}"
        tail = f"；映像 {who}" if who else "；取不到映像"
        return True, f"端口 {ports_txt}{tail}"

    if pid is None:
        return False, "无 pid 记录"
    if img is None:
        return False, f"pid {pid} 已不在"
    if img.lower() not in comp.whitelist:
        return True, f"pid {pid}；★ 映像是 {img}，不在白名单 {comp.whitelist}"
    return True, f"pid {pid}，映像 {img}"


def _child_env(comp: Component) -> dict[str, str] | None:
    """cmd 包装的组件（trae）⇒ 给子进程一个**只含系统目录**的 PATH（卡 243）。

    桌面那份启动 cmd 里的 `timeout /t` 之前被 MSYS 的 GNU timeout 抢走
    （PATH 里有 Git 的 usr/bin，GNU timeout 排在前面）。修法是改**我们怎么调它**：
    子进程 PATH 只留 `%SystemRoot%\\System32`，`timeout.exe` 仍解析得到（它就在那），
    GNU timeout 不在。桌面那份 cmd 本身**一个字不动**（那是用户的资产）。
    非 cmd 包装的组件回 `None`（= 继承本进程环境）。
    """
    assert comp.start is not None, "_child_env 只对能脚本起的组件有意义"
    if Path(comp.start[0]).name.lower() != "cmd.exe":
        return None
    env = dict(os.environ)
    system_root = Path(os.environ.get("SYSTEMROOT", r"C:\\Windows"))
    env["PATH"] = str(system_root / "System32")
    return env


def _launch(name: str, comp: Component) -> int:
    """按表起这个组件；stdout/stderr 灌 `gates/diag/stack/<名>.log`，回壳 pid。

    ★ 这里**不等**端口（等待窗口在 `start_one`，卡 243）——先落壳 pid，
    活起来之后由 `_adopt_owner_pid` 把 pid 文件换成真端口属主。
    """
    assert comp.start is not None, f"{name} 不能由脚本起（该走 manual 分支）"
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    with log_path(name).open("ab") as fh:
        proc = subprocess.Popen(  # noqa: S603 —— argv 是本表写死的，不是外部输入
            comp.start, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=fh, stderr=subprocess.STDOUT, env=_child_env(comp), **NO_WINDOW,
        )
    write_pidfile(name, proc.pid)
    return proc.pid


def _adopt_owner_pid(name: str, comp: Component) -> None:
    """活起来之后把 pid 文件换成**真端口属主**（cmd 壳的 pid 对 stop 没用）。"""
    for port in comp.ports:
        if port_open(port):
            owner = port_owner(port)
            if owner is not None:
                write_pidfile(name, owner)
                return


def start_one(
    name: str, *, wait_seconds: float = 20.0, poll_seconds: float = 0.5
) -> int:
    """起一个：已在跑的如实说「已在跑」；不能脚本起的说清手动一步（不假装起了）。

    卡 243 修「判活太快」：起完给**有限的等待窗口**（默认 20 秒、每 0.5 秒探一次
    端口/进程），探到活就报成功；等不到就报原话「发起了，但 N 秒内端口 X 还没起来」
    + 日志路径 —— **不许**把"还在启动中"谎报成"已起"。
    等待窗口是**注入式**的（`wait_seconds=0` 即关掉，判据用），不改常量。
    """
    comp = COMPONENTS[name]
    running, detail = alive(name)
    if running:
        print(f"{name}：已在跑（{detail}）")
        return 0
    if comp.start is None:
        print(f"{name}：没起，且这件**不能由脚本起** —— {comp.manual}")
        return 1
    try:
        _launch(name, comp)
    except OSError as exc:
        print(f"{name}：起不来 —— {type(exc).__name__}: {exc}")
        return 1
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        running, detail = alive(name)
        if running:
            _adopt_owner_pid(name, comp)
            print(f"{name}：已起（{detail}）")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)
    if comp.ports:
        print(
            f"{name}：发起了，但 {wait_seconds:g} 秒内端口 {comp.ports} "
            f"还没起来 —— **没活起来**；看 {log_path(name)}"
        )
    else:
        print(
            f"{name}：发起了，但 {wait_seconds:g} 秒内进程还没站稳"
            f"（{detail}）—— 看 {log_path(name)}"
        )
    return 1


def stop_one(name: str) -> int:
    """停一个：**先核对 pid 身份**；身份不符 ⇒ 拒绝点名；进程已不在 ⇒ 清过期文件。"""
    comp = COMPONENTS[name]
    path = pidfile_path(name)
    pid = read_pidfile(name)
    if pid is None:
        owner = None
        for port in comp.ports:
            if port_open(port):
                owner = port_owner(port)
                if owner is not None:
                    break
        if owner is None:
            print(f"{name}：没在跑（没有 pid 记录，也没有在听的端口）")
            return 0
        pid = owner
    img = image_of(pid)
    if img is None:
        if path.exists():
            path.unlink()
            print(f"{name}：没在跑（pid {pid} 已不存在）；已清掉过期 pid 文件 {path.name}")
        else:
            print(f"{name}：没在跑（pid {pid} 已不存在）")
        return 0
    if img.lower() not in comp.whitelist:
        print(
            f"{name}：拒绝动手 —— pid {pid} 的映像是 {img}，"
            f"不在白名单 {comp.whitelist} 里（可能误杀别的进程）"
        )
        return 1
    ok, detail = terminate(pid)
    if ok and path.exists():
        path.unlink()
    if ok:
        print(f"{name}：已停（pid {pid}，映像 {img}）")
        return 0
    print(f"{name}：停不掉 —— {detail}")
    return 1


def cmd_start(args: argparse.Namespace) -> int:
    """`start [名]`：没名的全起。"""
    names = [args.name] if getattr(args, "name", None) else list(COMPONENTS)
    rc = 0
    for name in names:
        rc |= start_one(name)
    return rc


def cmd_stop(args: argparse.Namespace) -> int:
    """`stop <名>`：分开停。"""
    return stop_one(args.name)


def cmd_status(args: argparse.Namespace) -> int:
    """`status`：现读，谁没起就写「没起」。"""
    del args
    for name in COMPONENTS:
        running, detail = alive(name)
        flag = "在跑" if running else "没起"
        print(f"{name:9} {flag}：{detail}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """`list`：把这四件的表打出来。"""
    del args
    for comp in COMPONENTS.values():
        how = " ".join(comp.start) if comp.start else "（只能手动 —— 见 status/start 的说明）"
        ports = "、".join(str(p) for p in comp.ports) if comp.ports else "（只看 pid）"
        print(f"{comp.name:9} 起：{how}")
        print(f"{'':9} 判活：端口 {ports}；白名单 {comp.whitelist}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="stack.py",
        description="一起起、分别停：看门 / timeflow / 工作台页 / 禅道 / Trae（卡 241；卡 243）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start", help="把没在跑的起起来（已在跑的如实说）")
    p_start.add_argument("name", nargs="?", choices=list(COMPONENTS), help="只起这一件")
    p_start.set_defaults(func=cmd_start)
    p_stop = sub.add_parser("stop", help="停一件（先核对 pid 身份）")
    p_stop.add_argument("name", choices=list(COMPONENTS), help="要停的组件名")
    p_stop.set_defaults(func=cmd_stop)
    sub.add_parser("status", help="现读四件的死活").set_defaults(func=cmd_status)
    sub.add_parser("list", help="打出这张表").set_defaults(func=cmd_list)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
