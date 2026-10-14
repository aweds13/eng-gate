"""卡 241 · 起停栈（`tools/stack.py`）的判据 —— 五条，每条**先红后绿**。

判据（卡 241 §3）：
1. `stop` 遇到**身份不匹配**的 pid ⇒ **必须拒**并点名（造一个假 pid ⇒ 红）；
2. `stop` 遇到**已经不存在的 pid** ⇒ 如实说「没在跑」+ 清过期文件（不许静默）；
3. `start` 对**已在跑**的组件**不重复起**（造一个假"活着"的桩 ⇒ 断言没起第二个进程）；
4. `status` 对**没起**的组件必须写「没起」（造空环境 ⇒ 断言输出里有"没起"）；
5. 源码里**不许**出现吞异常的写法（`except: pass` / `except Exception: pass`）。

★ 这些用例**一律 monkeypatch `terminate`**（换成假杀）—— 判据不该真去掐本机进程。
★ 不碰真落盘目录：pid 文件落在 `tmp_path` 下（monkeypatch `stack.STACK_DIR`）。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import stack  # noqa: E402 —— 需要先挂 tools/


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把运行痕迹目录指到临时目录，并把 `terminate` 换成假杀（绝不真掐进程）。"""
    monkeypatch.setattr(stack, "STACK_DIR", tmp_path / "stack")
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
