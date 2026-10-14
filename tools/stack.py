"""一起起、分别停：看门 / timeflow / 禅道 / Trae 的起停 + 现读（卡 241 · T-G359）。

用户 2026-10-14 令「起可以绑在一起，**停要分开**」。本工具只做四件事：

- `start`：把**没在跑的**起起来；已在跑的**如实说「已在跑」**、不重复起；
- `stop <名>`：**先核对 pid 身份**（映像是白名单里的那个）再审—— 不对就拒绝并点名；
- `status`：**现读**（真进程表 + 真端口），谁没起就写「没起」，**不静默成功**；
- `list`：这张表本身（名字 / 怎么起 / 怎么判活着 / 白名单）。

边界（卡 241 §4，一条都不越）
- 起停**只碰下表那四件**；不碰 `~/.dsh`、不碰 DSH 本体、**不注册计划任务**（用户选了手动）；
- `stop` 遇到**身份不符**的 pid ⇒ **拒绝动手并点名**（那可能是别人的 python/node）；
  进程已不在 ⇒ 如实说「没在跑」并**清掉过期 pid 文件**（说清做了这件事）；
- 判活着一律**真进程 / 真端口**；拿不到就说拿不到，**不为了"看起来起了"去放宽**。

为什么不用 `os.kill(pid, 0)` 探活：Windows 上 CPython 把它实现成 `OpenProcess` +
`TerminateProcess` ⇒ 会**真把那个进程杀掉**（口径坑 27）。
判活一律 `tasklist`，动手一律 `taskkill`。
"""

from __future__ import annotations

import argparse
import locale
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


#: 组件表（卡 241 §1）。★ 只这四件，别加。
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
        start=["cmd", "/c", "D:\\桌面\\启动Trae-带调试口.cmd"],
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


def _await_port(ports: tuple[int, ...], fallback: int, seconds: float = 10.0) -> int:
    """起完等端口开；开则回**端口属主 pid**，超时回 `fallback`（不谎报"已连上"）。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for port in ports:
            if port_open(port):
                owner = port_owner(port)
                return owner if owner is not None else fallback
        time.sleep(0.3)
    return fallback


def _launch(name: str, comp: Component) -> int:
    """按表起这个组件；stdout/stderr 灌 `gates/diag/stack/<名>.log`，回 pid。"""
    assert comp.start is not None, f"{name} 不能由脚本起（该走 manual 分支）"
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    with log_path(name).open("ab") as fh:
        proc = subprocess.Popen(  # noqa: S603 —— argv 是本表写死的，不是外部输入
            comp.start, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=fh, stderr=subprocess.STDOUT, **NO_WINDOW,
        )
    pid = proc.pid
    if comp.ports:
        pid = _await_port(comp.ports, fallback=proc.pid)
    write_pidfile(name, pid)
    return pid


def start_one(name: str) -> int:
    """起一个：已在跑的如实说「已在跑」；不能脚本起的说清手动一步（不假装起了）。"""
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
    time.sleep(0.5)  # 让子进程有个"站稳"的窗口，免得谎报「已起」
    running, detail = alive(name)
    if running:
        print(f"{name}：已起（{detail}）")
        return 0
    print(f"{name}：起了但**没活起来**（{detail}）—— 看 {log_path(name)}")
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
        description="一起起、分别停：看门 / timeflow / 禅道 / Trae（卡 241 · T-G359）",
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
