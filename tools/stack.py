"""一起起、分别停：看门 / timeflow / 工作台页 / 禅道 / Trae 的起停 + 现读（卡 241 · T-G359）。

卡 243（T-G364）：加 `board` 工作台页、修「判活太快」、修 trae 的 timeout 被抢。
卡 253（T-G374）：① 禅道改**命令行起**（mysqld + httpd，起前先探端口、已在听就不重复起）；
② `status` 加 **RSS 账本**（每件一栏 + 合计 + 400 MB 常驻预算，超了显式提示）；
③ 每次起停往 `gates/diag/stack-actions.log` 写**一行**（谁、何时、起了/停了、结果）；
④ `status --json` 给面板读（与文本同一个 `status_data()` 真源）。

卡 A308（T-AG422）：动作留痕带**一键回滚** ——
⑤ 每条动作行追加 `undo=<反动作>` 字段：`start board` ⇒ `undo=stop board`、
   `stop board` ⇒ `undo=start board`（映射的唯一真源是 `UNDO_OF` / `undo_for()`）；
   ★ 字段以「两个空格」与前面的 `OK|FAIL`、后面的 detail 分隔；`undo=` 的值固定是
   `<start|stop> <名>`（组件名没有空格），所以**不用引号**也解析得开；
⑥ 新增 `log` 子命令：`log` 原样打印最近几条，`log --undo` 按日志里的 `undo=` 反推出
   **回滚命令**（**倒序**：后做的先撤），**只打印、不执行**（要执行由人复制粘贴）。

★ 「一起起」的回滚口径（本卡定的，写在这里不另猜）：`start`（不带名）是**逐个组件**
各写一行 `start <名>`，所以「一起起」的回滚天然是**逐个** `undo=stop <名>`，按倒序
执行就等于「逐个停」；日志里**不写** `start-all` / `stop-all` 这种聚合动作 ——
粒度只有「一件」，因为停本来就要分开（见下）。老日志（本卡之前写的）没有 `undo=`
字段，`log --undo` 会**如实点数报出**，**不替它们编命令**。

用户 2026-10-14 令「起可以绑在一起，**停要分开**」。本工具只做五件事（卡 A308 起多一个 `log`）：

- `start`：把**没在跑的**起起来；已在跑的**如实说「已在跑」**、不重复起；
  起完给**有限的等待窗口**（默认 20 秒、每 0.5 秒探一次，卡 243 修「判活太快」），
  等不到就报原话「发起了，但 N 秒内端口 X 还没起来」，**不许谎报「已起」**；
- `stop <名>`：**先核对 pid 身份**（映像是白名单里的那个）再审—— 不对就拒绝并点名；
- `status`：**现读**（真进程表 + 真端口），谁没起就写「没起」，**不静默成功**；
- `list`：这张表本身（名字 / 怎么起 / 怎么判活着 / 白名单）；
- `log [--last N] [--undo]`（卡 A308）：原样打印最近 N 条动作；`--undo` 则按日志里的
  `undo=` 字段反推出**回滚命令**（倒序），**只打印、不执行**。

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
import datetime
import json
import locale
import os
import re
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
#: 卡 253：动作日志（**一行一条**；面板读最近几条，出问题有据可查）。
ACTIONS_LOG = ROOT / "gates" / "diag" / "stack-actions.log"
#: 卡 253：常驻预算（RSS 合计超了就在尾行**显式**提示；不是静默）。
RESIDENT_BUDGET_MB = 400
#: 卡 253：禅道便携版安装根（可用 ZENTAO_ROOT 覆盖）。
ZENTAO_ROOT = Path(os.environ.get("ZENTAO_ROOT", r"D:\zentao\ZenTao"))
#: 卡 A308：**动作 ⇒ 反动作**的唯一真源（`log_action` 写字段、`log --undo` 读字段都认它）。
UNDO_OF: dict[str, str] = {"start": "stop", "stop": "start"}
#: 卡 A308：日志里那一小段（`undo=stop board`）的解析式 —— 值不带空格，所以不用引号。
#: ★ 只认「**两个空格**开头」的字段（字段边界就是两个空格），免得 detail 里恰好写着
#: `undo=…` 时被当成本动作的回滚；老日志「缺字段」的判断也靠这条边界。
_UNDO_RE = re.compile(r"(?:^| {2})undo=(start|stop) (\S+)")
#: 卡 A308：`log --undo` 打印的命令前缀（**可复制执行**的那一半）。
LOG_PROG = "python -X utf8 tools/stack.py"


class Component(NamedTuple):
    """上表的一行。`whitelist` 是**映像白名单**（小写比较）；`ports` 为空表示只看 pid。"""

    name: str
    whitelist: tuple[str, ...]
    ports: tuple[int, ...]
    start: list[str] | None          # 起它的 argv（cwd = ROOT）；None ⇒ 只能手动
    manual: str                      # 不能脚本起时的「手动一步」说明
    #: 卡 253：多进程组件的**后续**启动条目（禅道 = mysqld + httpd）。
    extra_starts: tuple[list[str], ...] = ()
    #: 卡 253：与 `start` + `extra_starts` **逐条对应**的端口（0 = 不探）。
    start_ports: tuple[int, ...] = ()


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
        # ★ 卡 253：禅道已能命令行起 —— 直接拉起便携版自带的 mysqld + httpd
        # （成品 conf 在 bin/*/conf，见 docs/禅道-怎么起.md §3）；ZenPanel 仍可当备用。
        whitelist=("httpd.exe", "mysqld.exe"),
        ports=(80, 3306),
        start=[
            str(ZENTAO_ROOT / "bin" / "mysql" / "bin" / "mysqld.exe"),
            "--defaults-file=" + str(ZENTAO_ROOT / "bin" / "mysql" / "my.ini"),
        ],
        manual="",
        extra_starts=(
            [
                str(ZENTAO_ROOT / "bin" / "apache" / "bin" / "httpd.exe"),
                "-f",
                str(ZENTAO_ROOT / "bin" / "apache" / "conf" / "httpd.conf"),
            ],
        ),
        # ★ 逐条对应：先 mysqld（3306）、后 httpd（80）；起前各探一次，已在听就跳过。
        start_ports=(3306, 80),
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


def undo_for(action: str, name: str) -> str:
    """卡 A308：这个动作的**反动作命令**（`start board` ⇒ `stop board`）。

    ★ 表里没有的动作 ⇒ **抛错**（不返回空串、不假装能回滚）：日志里出现一条
    没有反动作的行，就等于留了个撤不掉的动作 —— 这种事必须在写入时就炸，而不是
    等到回滚那天才发现「这条没有 undo」。
    """
    inverse = UNDO_OF.get(action)
    if inverse is None:
        raise ValueError(f"没有「{action}」的反动作（只认识 {sorted(UNDO_OF)}）")
    return f"{inverse} {name}"


def log_action(actor: str, action: str, name: str, ok: bool, detail: str) -> None:
    """卡 253：把一次起停写进 `gates/diag/stack-actions.log`（**一行一条**）。

    字段（空格分隔，人读）：
    `<本地时间>  <谁>  <start|stop> <组件>  <OK|FAIL>  undo=<反动作>  <结果>`。
    卡 A308：`undo=` 是**反动作命令**（`start board` ⇒ `undo=stop board`），按「两个空格」
    自成一段；`log --undo` 就靠它反推回滚命令。
    ★ 上面那句「反动作」是**机械**的：对 `start` 撞上「已在跑 ⇒ 没动」这种 no-op 行，
    undo 仍是 `stop <组件>` —— detail 里已写明「没动」，执行前看 detail，别盲撤。
    ★ 写不进去也要在 stdout 说一声 —— 不许静默吞（日志是「出问题有据可查」的那条路）。
    """
    undo = undo_for(action, name)  # 先算：算不出就在写盘之前炸，不落一条撤不掉的行
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    verdict = "OK" if ok else "FAIL"
    line = f"{stamp}  {actor or 'cli'}  {action} {name}  {verdict}  undo={undo}  {detail}"
    try:
        ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACTIONS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line.replace("\n", " ") + "\n")
    except OSError as exc:
        print(f"（动作日志写不进去：{type(exc).__name__}: {exc}）")


def recent_actions(limit: int = 5) -> list[str]:
    """卡 253：动作日志最后 `limit` 行（面板显示用）；读不到 ⇒ 空表 + 不假装。"""
    try:
        lines = ACTIONS_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-limit:]


def undo_commands(limit: int = 10) -> tuple[list[str], list[str]]:
    """卡 A308：从动作日志里**反推**回滚命令 —— `(可执行命令表, 缺 undo 字段的原始行)`。

    - **倒序**：后做的先撤（`recent_actions` 给的是正序，这里反过来）——
      一条链上「先起 A 再起 B」要按 B、A 撤，正序撤会把顺序搞反；
    - 命令一律是 `LOG_PROG <反动作>`（`undo=stop board` ⇒
      `python -X utf8 tools/stack.py stop board`），**可复制执行**；
    - 缺 `undo=` 的老日志 ⇒ 进第二个表**原样**交回去，由调用方如实报出，
      **不猜、不补、不编**；
    - 本函数**只读日志**：不调 `start_one` / `stop_one`，一个进程都不碰。
    """
    lines = recent_actions(limit) if limit > 0 else recent_actions(sys.maxsize)
    commands: list[str] = []
    missing: list[str] = []
    for line in reversed(lines):
        found = _UNDO_RE.search(line)
        if found is None:
            missing.append(line)
            continue
        commands.append(f"{LOG_PROG} {found.group(1)} {found.group(2)}")
    return commands, missing


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


def rss_mb(pid: int | None) -> float | None:
    """卡 253：这个 pid 的**真实驻留内存**（MB，读 `tasklist` 的 Mem Usage 列）。

    ★ 这是「内存账本」的唯一读数口：不是常量、不是估算。取不到（进程不在 /
    列解不开）⇒ `None`，由调用方如实写「取不到」，**不拿 0 冒充**。
    """
    if pid is None:
        return None
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding=_console_encoding(),
            errors="replace", **NO_WINDOW,
        )
    except OSError as exc:
        print(f"tasklist 起不来（读 RSS）：{type(exc).__name__}: {exc}")
        return None
    line = next((ln for ln in (done.stdout or "").splitlines() if ln.strip()), "")
    if done.returncode != 0 or not line.startswith('"'):
        return None
    cells = [cell.strip('"') for cell in line.split('","')]
    if len(cells) < 5:
        return None
    mem = cells[-1].strip().upper().replace("K", "").replace(",", "").strip()
    try:
        return round(int(mem) / 1024, 1)
    except ValueError:
        return None


def current_pid(name: str) -> int | None:
    """这件**此刻**对应的 pid：端口属主优先，其次 pid 文件（卡 253 · RSS 账本用）。"""
    comp = COMPONENTS[name]
    for port in comp.ports:
        if port_open(port):
            owner = port_owner(port)
            if owner is not None:
                return owner
    return read_pidfile(name)


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
        # ★ 卡 253：多端口组件（禅道 = MySQL 3306 + Apache 80）**全部**在听才算在跑；
        #   只起一半就报「在跑」会让用户以为页面能开（那是谎报）。
        missing = [p for p in comp.ports if p not in open_ports]
        if missing:
            return False, (
                f"端口 {'、'.join(str(p) for p in missing)} 还没起"
                f"（在听的是 {'、'.join(str(p) for p in open_ports)}）"
            )
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


def start_argvs(comp: Component) -> list[list[str]]:
    """卡 253：这件要起的**全部 argv**（单进程一件；禅道 = mysqld + httpd 两件）。"""
    argvs = [comp.start] if comp.start is not None else []
    return argvs + [list(argv) for argv in comp.extra_starts]


def _launch(name: str, comp: Component) -> int:
    """按表起这个组件；stdout/stderr 灌 `gates/diag/stack/<名>.log`，回最后一个壳 pid。

    ★ 这里**不等**端口（等待窗口在 `start_one`，卡 243）——先落壳 pid，
    活起来之后由 `_adopt_owner_pid` 把 pid 文件换成真端口属主。
    ★ 卡 253：逐条起；**那一条的端口已在听就跳过**（禅道先起 MySQL 再起 Apache，
    其中一个已在跑时不重复起）。跳过的动作也**打印出来**，不静默。
    """
    argvs = start_argvs(comp)
    assert argvs, f"{name} 不能由脚本起（该走 manual 分支）"
    ports = comp.start_ports or (0,) * len(argvs)
    STACK_DIR.mkdir(parents=True, exist_ok=True)
    last_pid = 0
    for argv, port in zip(argvs, ports, strict=False):
        if port and port_open(port):
            print(f"{name}：端口 {port} 已在听 —— 跳过这一条启动（不重复起）")
            continue
        with log_path(name).open("ab") as fh:
            proc = subprocess.Popen(  # noqa: S603 —— argv 是本表写死的，不是外部输入
                argv, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT, env=_child_env(comp), **NO_WINDOW,
            )
        last_pid = proc.pid
        write_pidfile(name, proc.pid)
    return last_pid


def _adopt_owner_pid(name: str, comp: Component) -> None:
    """活起来之后把 pid 文件换成**真端口属主**（cmd 壳的 pid 对 stop 没用）。"""
    for port in comp.ports:
        if port_open(port):
            owner = port_owner(port)
            if owner is not None:
                write_pidfile(name, owner)
                return


def start_one(
    name: str, *, wait_seconds: float = 20.0, poll_seconds: float = 0.5, actor: str = "cli"
) -> int:
    """起一个：已在跑的如实说「已在跑」；不能脚本起的说清手动一步（不假装起了）。

    卡 243 修「判活太快」：起完给**有限的等待窗口**（默认 20 秒、每 0.5 秒探一次
    端口/进程），探到活就报成功；等不到就报原话「发起了，但 N 秒内端口 X 还没起来」
    + 日志路径 —— **不许**把"还在启动中"谎报成"已起"。
    等待窗口是**注入式**的（`wait_seconds=0` 即关掉，判据用），不改常量。
    卡 253：每次动作都往 `stack-actions.log` 写一行（谁 / 何时 / 起了 / 结果）。
    """
    comp = COMPONENTS[name]
    running, detail = alive(name)
    if running:
        print(f"{name}：已在跑（{detail}）")
        log_action(actor, "start", name, True, f"没动（已在跑：{detail}）")
        return 0
    if comp.start is None:
        print(f"{name}：没起，且这件**不能由脚本起** —— {comp.manual}")
        log_action(actor, "start", name, False, "不能由脚本起（已给手动一步）")
        return 1
    try:
        _launch(name, comp)
    except OSError as exc:
        print(f"{name}：起不来 —— {type(exc).__name__}: {exc}")
        log_action(actor, "start", name, False, f"起不来：{type(exc).__name__}: {exc}")
        return 1
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        running, detail = alive(name)
        if running:
            _adopt_owner_pid(name, comp)
            print(f"{name}：已起（{detail}）")
            log_action(actor, "start", name, True, f"已起（{detail}）")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)
    if comp.ports:
        detail = (
            f"发起了，但 {wait_seconds:g} 秒内端口 {comp.ports} 还没起来 —— "
            f"**没活起来**；看 {log_path(name)}"
        )
    else:
        detail = (
            f"发起了，但 {wait_seconds:g} 秒内进程还没站稳（{detail}）—— "
            f"看 {log_path(name)}"
        )
    print(f"{name}：{detail}")
    log_action(actor, "start", name, False, detail)
    return 1


def stop_one(name: str, *, actor: str = "cli") -> int:
    """停一个：**先核对 pid 身份**；身份不符 ⇒ 拒绝点名；进程已不在 ⇒ 清过期文件。

    卡 253：多进程组件（禅道 = mysqld + httpd）把 pid 文件与各端口属主**都**收集起来，
    逐个核对映像再逐个停；任何一个身份不符 ⇒ **整件拒绝**（不误杀别人的进程）。
    """
    comp = COMPONENTS[name]
    path = pidfile_path(name)
    pids: list[int] = []
    pid = read_pidfile(name)
    if pid is not None:
        pids.append(pid)
    for port in comp.ports:
        if port_open(port):
            owner = port_owner(port)
            if owner is not None and owner not in pids:
                pids.append(owner)
    if not pids:
        print(f"{name}：没在跑（没有 pid 记录，也没有在听的端口）")
        log_action(actor, "stop", name, True, "没动（没在跑）")
        return 0
    alive_pids: list[tuple[int, str]] = []
    for candidate in pids:
        img = image_of(candidate)
        if img is None:
            continue
        if img.lower() not in comp.whitelist:
            print(
                f"{name}：拒绝动手 —— pid {candidate} 的映像是 {img}，"
                f"不在白名单 {comp.whitelist} 里（可能误杀别的进程）"
            )
            log_action(actor, "stop", name, False, f"拒绝：pid {candidate} 映像是 {img}")
            return 1
        alive_pids.append((candidate, img))
    if not alive_pids:
        if path.exists():
            path.unlink()
            print(f"{name}：没在跑（pid {pids[0]} 已不存在）；已清掉过期 pid 文件 {path.name}")
            log_action(actor, "stop", name, True, f"没在跑（已清过期 pid 文件 {path.name}）")
        else:
            print(f"{name}：没在跑（pid {pids[0]} 已不存在）")
            log_action(actor, "stop", name, True, "没在跑（pid 已不存在）")
        return 0
    done: list[str] = []
    for candidate, img in alive_pids:
        ok, detail = terminate(candidate)
        if not ok:
            print(f"{name}：停不掉 pid {candidate} —— {detail}")
            log_action(actor, "stop", name, False, f"pid {candidate} 停不掉：{detail}")
            return 1
        done.append(f"pid {candidate}，映像 {img}")
    if path.exists():
        path.unlink()
    print(f"{name}：已停（{'；'.join(done)}）")
    log_action(actor, "stop", name, True, f"已停（{'；'.join(done)}）")
    return 0


def status_data() -> dict:
    """卡 253：现读五件 + **RSS 账本**（每件一栏、合计、常驻预算）—— 文本与 JSON 同一真源。

    RSS 口径：进程在跑才读（`tasklist` 的 Mem Usage）；没起 ⇒ `0.0`（没有进程就是 0 MB）；
    在跑但读不到 ⇒ `None`，**不拿 0 冒充**，合计只加读得到的，并在文本里写明。
    """
    rows: list[dict] = []
    total = 0.0
    unknown: list[str] = []
    for name in COMPONENTS:
        running, detail = alive(name)
        pid = current_pid(name) if running else None
        rss = rss_mb(pid) if running else 0.0
        if running and rss is None:
            unknown.append(name)
        else:
            total += float(rss or 0.0)
        rows.append(
            {
                "name": name,
                "running": running,
                "detail": detail,
                "pid": pid,
                "rss_mb": rss,
            }
        )
    return {
        "ok": True,
        "components": rows,
        "total_rss_mb": round(total, 1),
        "budget_mb": RESIDENT_BUDGET_MB,
        "over_budget": total > RESIDENT_BUDGET_MB,
        "rss_unknown": unknown,
    }


def cmd_start(args: argparse.Namespace) -> int:
    """`start [名]`：没名的全起。"""
    names = [args.name] if getattr(args, "name", None) else list(COMPONENTS)
    rc = 0
    for name in names:
        rc |= start_one(name, actor=getattr(args, "actor", "cli"))
    return rc


def cmd_stop(args: argparse.Namespace) -> int:
    """`stop <名>`：分开停。"""
    return stop_one(args.name, actor=getattr(args, "actor", "cli"))


def cmd_status(args: argparse.Namespace) -> int:
    """`status`：现读，谁没起就写「没起」；每件带 RSS，末尾合计 + 常驻预算。"""
    data = status_data()
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False))
        return 0
    for row in data["components"]:
        flag = "在跑" if row["running"] else "没起"
        rss = "?" if row["rss_mb"] is None else f"{row['rss_mb']:.1f}"
        print(f"{row['name']:9} {flag}：{row['detail']} ｜ RSS {rss} MB")
    total = data["total_rss_mb"]
    line = f"合计 RSS：{total:.1f} MB（常驻预算 {data['budget_mb']} MB）"
    if data["over_budget"]:
        line += f"  ★ 超出常驻预算 {total - data['budget_mb']:.1f} MB"
    print(line)
    if data["rss_unknown"]:
        print(f"★ 取不到 RSS：{'、'.join(data['rss_unknown'])}（合计未计入这几件）")
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


def cmd_log(args: argparse.Namespace) -> int:
    """`log [--last N] [--undo]`：**只看**最近的动作；`--undo` 只打印回滚命令（不执行）。

    卡 A308：`--undo` 不调 `start_one` / `stop_one`，一个进程都不碰 —— 要动手由人
    复制命令去执行（「只打印」是这条子命令的边界，不是没做完）。
    """
    limit = int(getattr(args, "last", 10) or 0)
    scope = "全部" if limit <= 0 else f"最后 {limit} 行"
    if not getattr(args, "undo", False):
        lines = recent_actions(limit) if limit > 0 else recent_actions(sys.maxsize)
        if not lines:
            print(f"动作日志是空的（或读不到）：{ACTIONS_LOG}")
            return 0
        for line in lines:
            print(line)
        return 0
    commands, missing = undo_commands(limit)
    if not commands and not missing:
        print(f"动作日志是空的（或读不到）：{ACTIONS_LOG}")
        return 0
    print("# 回滚命令（**倒序**：后做的先撤）—— 本命令只**打印**，不执行")
    print(f"# 来源：{ACTIONS_LOG}（{scope}）；共 {len(commands)} 条")
    for command in commands:
        print(command)
    if missing:
        print(f"# ★ 有 {len(missing)} 行没有 undo 字段（卡 A308 之前的旧日志）—— 不替它们编命令：")
        for line in missing:
            print(f"#   {line}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="stack.py",
        description="一起起、分别停：看门 / timeflow / 工作台页 / 禅道 / Trae（卡 241/253）",
    )
    # 卡 253：动作日志里的「谁」（面板传 panel；命令行默认 cli）。
    parser.add_argument("--actor", default="cli", help="动作日志里的发起人（默认 cli）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start", help="把没在跑的起起来（已在跑的如实说）")
    p_start.add_argument("name", nargs="?", choices=list(COMPONENTS), help="只起这一件")
    p_start.set_defaults(func=cmd_start)
    p_stop = sub.add_parser("stop", help="停一件（先核对 pid 身份）")
    p_stop.add_argument("name", choices=list(COMPONENTS), help="要停的组件名")
    p_stop.set_defaults(func=cmd_stop)
    p_status = sub.add_parser("status", help="现读五件的死活 + RSS 账本")
    p_status.add_argument("--json", action="store_true", help="给面板读的 JSON（与文本同一真源）")
    p_status.set_defaults(func=cmd_status)
    sub.add_parser("list", help="打出这张表").set_defaults(func=cmd_list)
    # 卡 A308：动作留痕 + 一键回滚（只打印，不执行）。
    p_log = sub.add_parser("log", help="看最近的动作；--undo 打印回滚命令（只打印、不执行）")
    p_log.add_argument(
        "--last", type=int, default=10, help="只看最后 N 行（0 = 全部；默认 10）"
    )
    p_log.add_argument(
        "--undo", action="store_true", help="按日志里的 undo= 反推回滚命令（倒序；不执行）"
    )
    p_log.set_defaults(func=cmd_log)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
