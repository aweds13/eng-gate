"""卡 241 · 起停栈（`tools/stack.py`）的判据 —— 卡 241 五条 + 卡 243 五条，每条**先红后绿**。

判据（卡 241 §3）：
1. `stop` 遇到**身份不匹配**的 pid ⇒ **必须拒**并点名（造一个假 pid ⇒ 红）；
2. `stop` 遇到**已经不存在的 pid** ⇒ 如实说「没在跑」+ 清过期文件（不许静默）；
3. `start` 对**已在跑**的组件**不重复起**（造一个假"活着"的桩 ⇒ 断言没起第二个进程）；
4. `status` 对**没起**的组件必须写「没起」（造空环境 ⇒ 断言输出里有"没起"）；
5. 源码里**不许**出现吞异常的写法（`except: pass` / `except Exception: pass`）。

判据（卡 243 §4，T-G364）：
6.  `board`（工作台页）在组件表里、端口 8787、命令指向 `tools/wb_dash.py`；
7.  `status` 在 8787 不通时必须写「没起」（反例：造一个假 LISTEN ⇒ 不许再写没起）；
8.  ★ `start` 的等待窗口=0 ⇒ **必须**报「没活起来」（不许静默成功）；
    给一个会立刻监听的桩 ⇒ 必须报成功 ✓；
9.  ★ `stop board` 身份不符 ⇒ **必须拒**（沿用既有白名单判据）；
10. `trae` 的启动路径**不许**裸调 `timeout`（源码级判据；反例：塞回去 ⇒ 红），
    且给 cmd 子进程的 PATH 只含系统目录（修「GNU timeout 抢了 Windows timeout /t」）。

★ 这些用例**一律 monkeypatch `terminate`**（换成假杀）—— 判据不该真去掐本机进程。
★ 不碰真落盘目录：pid 文件落在 `tmp_path` 下（monkeypatch `stack.STACK_DIR`）。
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import stack  # noqa: E402 —— 需要先挂 tools/


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把运行痕迹目录指到临时目录，并把 `terminate` 换成假杀（绝不真掐进程）。

    卡 253：动作日志也指到临时目录 —— 判据**不往真仓库的日志里写**。
    """
    monkeypatch.setattr(stack, "STACK_DIR", tmp_path / "stack")
    monkeypatch.setattr(stack, "ACTIONS_LOG", tmp_path / "stack-actions.log")
    monkeypatch.setattr(stack, "terminate", lambda pid: (True, f"（假杀 pid {pid}）"))
    return tmp_path / "stack"


def _write_pid(name: str, pid: int) -> None:
    """造一个 pid 文件（不启动任何进程）。"""
    stack.STACK_DIR.mkdir(parents=True, exist_ok=True)
    stack.pidfile_path(name).write_text(str(pid), encoding="utf-8")


def _used_pids() -> set[int]:
    """本机现存 pid 集合（拿一个**真不存在**的 pid 来测"进程已不在"）。"""
    done = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, encoding=stack._console_encoding(),
        errors="replace", **stack.NO_WINDOW,
    )
    used: set[int] = set()
    for line in (done.stdout or "").splitlines():
        cols = [cell.strip('"') for cell in line.split('","')]
        if len(cols) >= 2 and cols[1].isdigit():
            used.add(int(cols[1]))
    return used


def _free_pid() -> int:
    """挑一个**保证没在跑**的 pid。"""
    used = _used_pids()
    candidate = (max(used) if used else 1000) + 1000
    while candidate in used:
        candidate += 1
    return candidate


def test_stop_refuses_when_identity_mismatch(sandbox: Path, capsys: pytest.CaptureFixture) -> None:
    """★ 判据 1：pid 的映像不在白名单 ⇒ **拒绝动手并点名**（造一个假 pid）。"""
    mypid = os.getpid()  # 这个进程的映像是 python.exe，不在 closer 的白名单（bash.exe）
    _write_pid("closer", mypid)
    rc = stack.stop_one("closer")
    out = capsys.readouterr().out
    assert "拒绝" in out, f"身份不符必须拒绝，实际输出：{out!r}"
    assert str(mypid) in out, "拒绝时要**点名**是哪个 pid"
    assert "不在白名单" in out, "要说清为什么拒（映像不在白名单）"
    assert rc == 1
    assert stack.pidfile_path("closer").exists(), "拒绝时不许动 pid 文件"


def test_stop_clears_stale_pid_file(sandbox: Path, capsys: pytest.CaptureFixture) -> None:
    """★ 判据 2：pid 已不存在 ⇒ 说「没在跑」+ **清掉过期 pid 文件**（不许静默）。"""
    stale = _free_pid()
    assert stale not in _used_pids(), "挑到的 pid 竟然在跑，用例前提不成立"
    _write_pid("closer", stale)
    rc = stack.stop_one("closer")
    out = capsys.readouterr().out
    assert "没在跑" in out, f"进程已不在要说「没在跑」，实际输出：{out!r}"
    assert "已清掉过期 pid 文件" in out, "要**说清**清文件这件事（不许静默）"
    assert rc == 0
    assert not stack.pidfile_path("closer").exists(), "过期 pid 文件必须被清掉"


def test_start_does_not_double_start(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 3：已在跑 ⇒ 不重复起（幂等；断言没起第二个进程）。"""
    monkeypatch.setattr(stack, "alive", lambda name: (True, "桩：已在跑"))
    launched: list[str] = []
    monkeypatch.setattr(stack, "_launch", lambda name, comp: launched.append(name) or 1234)
    rc = stack.start_one("closer")
    out = capsys.readouterr().out
    assert "已在跑" in out, f"已在跑要如实说，实际输出：{out!r}"
    assert launched == [], "已在跑就不许再起第二个进程"
    assert rc == 0


def test_status_says_not_started_in_empty_env(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 4：空环境 ⇒ `status` 必须写「没起」（不静默成功）。"""
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(stack, "image_of", lambda pid: None)
    rc = stack.cmd_status(None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "没起" in out, f"没起必须写出来，实际输出：{out!r}"
    for name in stack.COMPONENTS:
        assert name in out, f"status 少了组件 {name}"


def test_source_has_no_swallowed_exceptions() -> None:
    """★ 判据 5：源码里不许有 `except: pass` / `except Exception: pass`（异常要说到 stdout）。"""
    src = (ROOT / "tools" / "stack.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                offenders.append(node.lineno)
    assert offenders == [], f"这些 except 在吞异常（只 pass）：{offenders}"


# ────────────────────────── 卡 243 · T-G364 ──────────────────────────


def test_board_in_component_table() -> None:
    """★ 判据 6：`board` 在组件表里、端口 8787、命令指向 `tools/wb_dash.py`。"""
    comp = stack.COMPONENTS["board"]
    assert comp.name == "board"
    assert comp.ports == (8787,), f"board 的判活端口应是 8787，实际 {comp.ports}"
    assert comp.start is not None, "board 必须能脚本起（manual 留空）"
    assert "wb_dash.py" in " ".join(comp.start), f"board 的命令要指向 wb_dash.py：{comp.start}"
    assert comp.whitelist == ("python.exe",), (
        f"board 的 pid 白名单应是 python.exe：{comp.whitelist}"
    )
    assert comp.manual == "", "board 能脚本起，manual 必须留空"


def test_status_board_not_started_and_fake_listen(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 7：8787 不通 ⇒ status 写「没起」；反例：假 LISTEN ⇒ 不许再写没起。"""
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(stack, "image_of", lambda pid: None)
    stack.cmd_status(None)
    out = capsys.readouterr().out
    board_line = next(ln for ln in out.splitlines() if ln.split()[0] == "board")
    assert "没起" in board_line, f"8787 不通必须写「没起」，实际：{board_line!r}"

    # 反例：造一个假的 LISTEN（8787 通、属主映像是 python.exe）⇒ 不许再写「没起」
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: True)
    monkeypatch.setattr(stack, "port_owner", lambda port: 4321)
    monkeypatch.setattr(stack, "image_of", lambda pid: "python.exe")
    stack.cmd_status(None)
    out = capsys.readouterr().out
    board_line = next(ln for ln in out.splitlines() if ln.split()[0] == "board")
    assert "没起" not in board_line, f"假 LISTEN 之下不许再写「没起」：{board_line!r}"
    assert "在跑" in board_line, f"假 LISTEN 之下要报在跑：{board_line!r}"


def test_start_zero_wait_reports_not_alive(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 8：start 的等待窗口=0 且没活 ⇒ **必须**报「没活起来」（不许静默成功）。"""
    monkeypatch.setattr(stack, "alive", lambda name: (False, "桩：没活"))
    monkeypatch.setattr(stack, "_launch", lambda name, comp: 12345)
    rc = stack.start_one("board", wait_seconds=0)
    out = capsys.readouterr().out
    assert rc == 1, f"没活起来必须回非零，实际 rc={rc}"
    assert "发起了，但" in out, f"要报原话「发起了，但 N 秒内…」：{out!r}"
    assert "还没起来" in out, f"要说清端口没起来：{out!r}"
    assert "没活起来" in out, f"不许静默成功，要点破「没活起来」：{out!r}"
    assert "8787" in out, f"要点名是哪个端口：{out!r}"
    assert str(stack.log_path("board")) in out, f"要给日志路径：{out!r}"


def test_start_with_instant_listener_reports_success(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 8 反例：给一个会**立刻监听**的桩 ⇒ start 必须报成功（即使窗口=0）。"""
    calls = {"n": 0}

    def fake_alive(name: str) -> tuple[bool, str]:
        calls["n"] += 1
        # 第一次（起之前的现读）：没活；之后（起完一探）：立刻活了
        return (calls["n"] > 1, "桩：立刻监听")

    monkeypatch.setattr(stack, "alive", fake_alive)
    monkeypatch.setattr(stack, "_launch", lambda name, comp: 12345)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)  # 别碰真端口
    rc = stack.start_one("board", wait_seconds=0)
    out = capsys.readouterr().out
    assert rc == 0, f"立刻监听的桩必须报成功，实际 rc={rc}，输出：{out!r}"
    assert "已起" in out, f"要报「已起」：{out!r}"


def test_stop_board_refuses_identity_mismatch(
    sandbox: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 9：`stop board` 遇到映像不在白名单（python.exe 之外）⇒ **必须拒**并点名。"""
    stranger = 4777
    _write_pid("board", stranger)
    monkeypatch.setattr(stack, "image_of", lambda pid: "notepad.exe")
    rc = stack.stop_one("board")
    out = capsys.readouterr().out
    assert "拒绝" in out, f"身份不符必须拒绝，实际输出：{out!r}"
    assert str(stranger) in out, "拒绝时要**点名**是哪个 pid"
    assert "python.exe" in out, "要说清白名单是什么"
    assert rc == 1
    assert stack.pidfile_path("board").exists(), "拒绝时不许动 pid 文件"


def test_trae_launch_code_has_no_bare_timeout() -> None:
    """★ 判据 10a：启动代码里不许出现裸 `timeout`（会被 MSYS 的 GNU timeout 抢走）。

    只咬**命令形态**的裸调（字面量就是 timeout / timeout.exe / timeout …）；
    socket 的 `timeout=` 参数名不算（那是 Python 关键字参数，不是子进程命令）。
    """
    src = (ROOT / "tools" / "stack.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip().lower()
            if value in {"timeout", "timeout.exe"} or value.startswith("timeout "):
                offenders.append(node.value)
    assert offenders == [], f"启动代码里出现了裸 timeout（会被 GNU timeout 抢）：{offenders}"


def test_trae_child_env_restricted_to_system32() -> None:
    """★ 判据 10b：cmd 包装的组件（trae）拿到的 PATH **只含系统目录** —— 桌面那份 cmd
    里的 `timeout /t` 会因此解析到 System32 的真 timeout.exe，不再被 MSYS 抢。"""
    env = stack._child_env(stack.COMPONENTS["trae"])
    assert env is not None, "cmd 包装的组件必须拿到受限 PATH"
    expected = str(Path(os.environ.get("SYSTEMROOT", r"C:\\Windows")) / "System32")
    assert env["PATH"].lower() == expected.lower(), f"PATH 要只含 System32：{env['PATH']!r}"
    # 非 cmd 包装的组件不受影响（board 直接 python 起，继承环境即可）
    assert stack._child_env(stack.COMPONENTS["board"]) is None


# ────────────────────────── 卡 253 · T-G374 ──────────────────────────
# 禅道命令行起 / RSS 账本 / 动作日志 / 「探端口才算起来」。


def test_zentao_can_be_started_from_command_line() -> None:
    """★ 卡 253：禅道由两条写死的 argv 起（mysqld + httpd），逐条对应端口。"""
    comp = stack.COMPONENTS["zentao"]
    argvs = stack.start_argvs(comp)
    assert len(argvs) == 2, argvs
    assert "mysqld.exe" in " ".join(argvs[0]) and "--defaults-file=" in " ".join(argvs[0])
    assert "httpd.exe" in " ".join(argvs[1]) and "-f" in argvs[1]
    assert comp.start_ports == (3306, 80), comp.start_ports
    assert comp.manual == "", "禅道已能命令行起，manual 必须留空"


def test_launch_skips_a_service_whose_port_is_already_listening(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 卡 253：起前先探端口 —— 3306 已在听 ⇒ 只起 httpd，不重复起 mysqld。"""
    started: list[list[str]] = []

    class FakeProc:
        def __init__(self, argv, **_kwargs) -> None:
            self.pid = 4000 + len(started)
            started.append(list(argv))

    monkeypatch.setattr(stack.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: port == 3306)
    stack._launch("zentao", stack.COMPONENTS["zentao"])
    out = capsys.readouterr().out
    assert len(started) == 1, started
    assert "httpd.exe" in " ".join(started[0]), started
    assert "3306 已在听" in out, out


def test_start_judges_by_real_port_not_by_launch(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 b 正例：起过之后**端口真开**才报「已起」。"""
    state = {"launched": False}

    def fake_launch(name: str, _comp: object) -> int:
        state["launched"] = True
        stack.write_pidfile(name, os.getpid())
        return os.getpid()

    monkeypatch.setattr(stack, "_launch", fake_launch)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: state["launched"])
    monkeypatch.setattr(stack, "port_owner", lambda port: os.getpid())
    monkeypatch.setattr(stack, "image_of", lambda pid: "python.exe")
    rc = stack.start_one("board", wait_seconds=0.1, poll_seconds=0.01)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "已起" in out and "8787" in out, out


def test_start_never_reports_started_when_port_probe_is_short_circuited(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 b 反例：把端口探测短路（永远 False）⇒ 起过也不许报「已起」。"""
    monkeypatch.setattr(stack, "_launch", lambda name, comp: 12345)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(stack, "image_of", lambda pid: None)
    rc = stack.start_one("board", wait_seconds=0)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "发起了，但" in out and "还没起来" in out, out
    assert "已起" not in out, out


def test_status_prints_rss_for_every_component_and_a_total(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 内存账本：每件一栏 RSS + 末尾合计；合计 = 各项之和（±5 MB）。"""
    rss = {"closer": 10.0, "timeflow": 20.0, "board": 30.0, "zentao": 40.0, "trae": 50.0}
    monkeypatch.setattr(stack, "alive", lambda name: (True, "桩：在跑"))
    # 按组件名映射一个 pid（1..5），RSS 由 pid 反查 —— 每件必须是**独立读数**。
    monkeypatch.setattr(stack, "current_pid", lambda name: list(rss).index(name) + 1)
    monkeypatch.setattr(stack, "rss_mb", lambda pid: list(rss.values())[pid - 1])
    rc = stack.cmd_status(None)
    out = capsys.readouterr().out
    assert rc == 0
    lines = out.splitlines()
    assert sum("RSS" in ln for ln in lines) == len(stack.COMPONENTS) + 1, out
    values = [float(re.search(r"RSS ([\d.]+) MB", ln).group(1)) for ln in lines if "｜ RSS" in ln]
    assert len(values) == len(stack.COMPONENTS)
    total = float(re.search(r"合计 RSS：([\d.]+) MB", out).group(1))
    assert abs(sum(values) - total) <= 5, (values, total)


def test_rss_is_really_read_from_the_process_table() -> None:
    """★ 反例：RSS 短路成常量 ⇒ 这里必红（活进程有数、不存在的 pid 必须 None）。"""
    own = stack.rss_mb(os.getpid())
    assert own is not None and own > 0, own
    assert stack.rss_mb(_free_pid()) is None, "不存在的 pid 不许回一个数（说明不是真读）"


def test_status_warns_when_resident_budget_is_exceeded(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 卡 253：合计超 400 MB ⇒ 尾行**显式**提示（不是静默）。"""
    monkeypatch.setattr(stack, "alive", lambda name: (True, "桩：在跑"))
    monkeypatch.setattr(stack, "current_pid", lambda name: 1)
    monkeypatch.setattr(stack, "rss_mb", lambda pid: 500.0)
    stack.cmd_status(None)
    out = capsys.readouterr().out
    assert "合计 RSS" in out and "超出常驻预算" in out, out


def test_start_and_stop_write_one_line_each_to_the_action_log(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 d：起/停各写**一行**（谁、何时、起了/停了、结果）到 stack-actions.log。"""
    monkeypatch.setattr(stack, "_launch", lambda name, comp: 12345)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)
    monkeypatch.setattr(stack, "image_of", lambda pid: None)
    stack.start_one("board", wait_seconds=0, actor="pytest")
    capsys.readouterr()
    stack.stop_one("board", actor="pytest")
    capsys.readouterr()
    lines = stack.ACTIONS_LOG.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, lines
    assert "pytest" in lines[0] and "start board" in lines[0] and "FAIL" in lines[0], lines[0]
    assert "pytest" in lines[1] and "stop board" in lines[1] and "OK" in lines[1], lines[1]
    assert all("T" in ln.split()[0] for ln in lines), lines  # 带时间戳
