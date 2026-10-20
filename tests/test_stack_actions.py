"""卡 A308（T-AG422）· 动作留痕带一键回滚 —— 判据逐条、**先红后绿**。

判据：
1. ★ **每条**日志行都有 `undo=` 字段，且值非空、形如 `<start|stop> <组件>`
   （六条路径都咬：起成功 / 起成 no-op（已在跑）/ 停成功 / 停失败（身份不符）/
   起失败 / 停成 no-op（没在跑）—— FAIL 的行同样要有 undo）；
2. ★ 映射是 `start <名>` ⇒ `undo=stop <名>`、`stop <名>` ⇒ `undo=start <名>`；
3. ★ **undo 反做后状态回到前一态** —— 起完用它撤 ⇒ 回到「没在跑」；
   停完用它撤 ⇒ 回到「在跑」；整条链倒序撤 ⇒ 回到最初那一态；
4. ★ `log --undo` 只**打印**回滚命令、**不执行**（打印前后假机器状态一个字不变）；
5. ★ 倒序：后做的先撤（先起 A 再起 B ⇒ 先撤 B 再撤 A）；
6. ★ 老日志（没有 `undo=` 字段）**如实点数报出**，不替它们编命令；
7. 没有反动作的动作 ⇒ **抛错**，而且**不落**这条撤不掉的行。

★ 一律 monkeypatch：`_launch` / `terminate` / `port_open` / `port_owner` / `image_of` /
  `alive` 全是桩 —— **绝不起停真实服务**；`STACK_DIR` / `ACTIONS_LOG` 指到 `tmp_path`，
  **不往真仓库的日志里写**。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import stack  # noqa: E402 —— 需要先挂 tools/


class FakeMachine:
    """假机器：只记「谁在跑 / 谁的 pid 是多少」，一个真进程都不起。

    ★ 这是本文件「不许起停真实服务」的落点：所有判据只读写这个对象。
    """

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.pids: dict[str, int] = {}
        self.launched: list[str] = []
        self.killed: list[int] = []

    def snapshot(self) -> tuple[set[str], dict[str, int]]:
        """前一态（判「undo 反做后回到原样」用）。"""
        return set(self.running), dict(self.pids)


@pytest.fixture()
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeMachine:
    """把运行痕迹 + 动作日志指到 `tmp_path`，并把所有会碰真机器的函数换成假机器。"""
    fake = FakeMachine()
    monkeypatch.setattr(stack, "STACK_DIR", tmp_path / "stack")
    monkeypatch.setattr(stack, "ACTIONS_LOG", tmp_path / "stack-actions.log")

    def fake_launch(name: str, _comp: object) -> int:
        # pid 按组件名**定死**（不是自增）—— 反做要能回到「同一个 pid」才算回原态
        pid = 9000 + list(stack.COMPONENTS).index(name)
        fake.launched.append(name)
        fake.running.add(name)
        fake.pids[name] = pid
        stack.write_pidfile(name, pid)
        return pid

    def fake_alive(name: str) -> tuple[bool, str]:
        return (name in fake.running, "假机器：在跑" if name in fake.running else "假机器：没起")

    def fake_terminate(pid: int) -> tuple[bool, str]:
        fake.killed.append(pid)
        for name, known in list(fake.pids.items()):
            if known == pid:
                fake.running.discard(name)
                fake.pids.pop(name, None)
                path = stack.pidfile_path(name)
                if path.exists():
                    path.unlink()
        return True, f"（假杀 pid {pid}）"

    monkeypatch.setattr(stack, "_launch", fake_launch)
    monkeypatch.setattr(stack, "alive", fake_alive)
    monkeypatch.setattr(stack, "terminate", fake_terminate)
    monkeypatch.setattr(stack, "port_open", lambda port, *a, **k: False)  # 别碰真端口
    monkeypatch.setattr(stack, "port_owner", lambda port: None)
    monkeypatch.setattr(stack, "image_of", lambda pid: "python.exe")  # board 的白名单映像
    return fake


def _lines() -> list[str]:
    """动作日志的行（读不到 ⇒ 空表，不假装）。"""
    if not stack.ACTIONS_LOG.exists():
        return []
    return [ln for ln in stack.ACTIONS_LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _undo_of(line: str) -> str:
    """这一行里的 undo 值（**自己解**，不借被测的解析器 —— 判据要独立成钉子）。"""
    marker = "undo="
    start = line.index(marker) + len(marker)
    # 值到「两个空格」或行尾为止（字段以两个空格分隔，见 log_action 的说明）
    return line[start:].split("  ", 1)[0].strip()


def _apply_undo(line: str) -> None:
    """按日志里的 undo 值**反做**（调真的 `stop_one` / `start_one`，机器是假的）。"""
    action, name = _undo_of(line).split(" ", 1)
    if action == "stop":
        stack.stop_one(name, actor="pytest")
    elif action == "start":
        stack.start_one(name, wait_seconds=0, actor="pytest")
    else:  # pragma: no cover —— 走到这里说明日志里的 undo 不是 start/stop
        raise AssertionError(f"undo 值不是 start/stop：{line!r}")


# ────────────────────────── 判据 1 / 2：字段本身 ──────────────────────────


def test_every_action_line_has_a_non_empty_undo(
    machine: FakeMachine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 1：六条路径写下的**每一行**都带非空 undo，形如 `<start|stop> <组件>`。"""
    # ① 起成功
    stack.start_one("board", wait_seconds=0, actor="pytest")
    # ② 起成 no-op：已在跑
    stack.start_one("board", wait_seconds=0, actor="pytest")
    # ③ 停成功
    stack.stop_one("board", actor="pytest")
    # ④ 停失败：身份不符（映像是 notepad.exe）
    stack.write_pidfile("timeflow", os.getpid())
    monkeypatch.setattr(stack, "image_of", lambda pid: "notepad.exe")
    stack.stop_one("timeflow", actor="pytest")
    # ⑤ 停成 no-op：没在跑
    stack.stop_one("zentao", actor="pytest")
    # ⑥ 起失败：起不来（OSError）
    def boom(name: str, _comp: object) -> int:
        raise OSError("假机器：起不来")

    monkeypatch.setattr(stack, "_launch", boom)
    stack.start_one("trae", wait_seconds=0, actor="pytest")
    capsys.readouterr()

    lines = _lines()
    assert len(lines) == 6, lines
    for line in lines:
        assert "undo=" in line, f"这一行没有 undo 字段：{line!r}"
        undo = _undo_of(line)
        assert undo, f"undo 是空的：{line!r}"
        action, name = undo.split(" ", 1)
        assert action in {"start", "stop"}, f"undo 的动作不认识：{line!r}"
        assert name in stack.COMPONENTS, f"undo 里的组件不认识：{line!r}"
    # FAIL 的行也要有 undo（撤不掉的动作比失败更糟）
    failed = [ln for ln in lines if "FAIL" in ln]
    assert len(failed) == 2, lines
    assert all(_undo_of(ln) for ln in failed), failed


def test_undo_is_the_mechanical_inverse(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 2：`start board` ⇒ `undo=stop board`；`stop board` ⇒ `undo=start board`。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    stack.stop_one("board", actor="pytest")
    capsys.readouterr()
    lines = _lines()
    assert len(lines) == 2, lines
    assert "start board" in lines[0], lines[0]
    assert _undo_of(lines[0]) == "stop board", lines[0]
    assert "stop board" in lines[1], lines[1]
    assert _undo_of(lines[1]) == "start board", lines[1]
    # 映射只有一个真源：`undo_for` 与日志里的字段必须同口径
    assert stack.undo_for("start", "board") == "stop board"
    assert stack.undo_for("stop", "board") == "start board"


def test_action_without_an_inverse_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 判据 7：没有反动作的动作 ⇒ **抛错**，而且**不落**这条撤不掉的行。"""
    monkeypatch.setattr(stack, "ACTIONS_LOG", tmp_path / "stack-actions.log")
    with pytest.raises(ValueError, match="反动作"):
        stack.log_action("pytest", "restart", "board", True, "假动作")
    assert _lines() == [], "算不出 undo 就不许落盘（哪怕日志文件已存在）"


# ────────────────────────── 判据 3：反做回原态 ──────────────────────────


def test_undo_of_start_returns_to_not_running(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 3a：起完按 undo 撤 ⇒ 回到「没在跑」（与起之前**一模一样**）。"""
    before_running, before_pids = machine.snapshot()
    stack.start_one("board", wait_seconds=0, actor="pytest")
    assert machine.running == {"board"}, "前提：这一笔真把它起了（假机器）"
    capsys.readouterr()

    _apply_undo(_lines()[-1])
    capsys.readouterr()
    assert machine.running == before_running, "undo 之后必须回到没在跑"
    assert machine.pids == before_pids, "undo 之后 pid 账也该回到前一态"
    assert not stack.pidfile_path("board").exists(), "停完不留过期 pid 文件"


def test_undo_of_stop_returns_to_running(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 3b：停完按 undo 撤 ⇒ 回到「在跑」（同一个 pid，不是随便起一个）。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    capsys.readouterr()
    before_running, before_pids = machine.snapshot()

    stack.stop_one("board", actor="pytest")
    capsys.readouterr()
    assert machine.running == set(), "前提：这一笔真把它停了（假机器）"

    _apply_undo(_lines()[-1])
    capsys.readouterr()
    assert machine.running == before_running, "undo 之后必须回到在跑"
    assert machine.pids == before_pids, "undo 之后 pid 账也该回到前一态"


def test_undo_chain_restores_the_original_state(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 3 + 5：起两个再停一个，**按倒序**逐条 undo ⇒ 回到最初那一态。"""
    before_running, before_pids = machine.snapshot()
    stack.start_one("board", wait_seconds=0, actor="pytest")
    stack.start_one("timeflow", wait_seconds=0, actor="pytest")
    stack.stop_one("board", actor="pytest")
    capsys.readouterr()
    assert machine.running == {"timeflow"}, "前提：三笔之后只剩 timeflow"

    for line in reversed(_lines()):  # ★ 倒序撤：最后一条先撤
        _apply_undo(line)
    capsys.readouterr()
    assert machine.running == before_running, "整条链撤完必须回到最初那一态"
    assert machine.pids == before_pids, "整条链撤完 pid 账也要回原样"


# ────────────────────────── 判据 4：只打印、不执行 ──────────────────────────


def test_log_undo_only_prints(machine: FakeMachine, capsys: pytest.CaptureFixture) -> None:
    """★ 判据 4：`log --undo` 只打印命令，**不动**机器（打印前后状态一个字不变）。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    capsys.readouterr()
    before_running, before_pids = machine.snapshot()

    rc = stack.cmd_log(argparse.Namespace(last=10, undo=True))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "python -X utf8 tools/stack.py stop board" in out, out
    assert "不执行" in out, f"要写明这条命令只打印、不执行：{out!r}"
    assert machine.running == before_running, "log --undo 绝不许动手停服务"
    assert machine.pids == before_pids, "log --undo 绝不许动 pid 账"
    assert machine.killed == [], f"log --undo 调了 terminate：{machine.killed}"
    assert machine.launched == ["board"], f"log --undo 又起了东西：{machine.launched}"


def test_log_without_undo_prints_the_raw_lines(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """`log`（不带 --undo）原样打印最近的几行，方便看现场。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    capsys.readouterr()
    rc = stack.cmd_log(argparse.Namespace(last=5, undo=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert _lines()[0] in out, out


def test_log_undo_is_reversed_so_the_last_action_is_undone_first(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 5：打印顺序是**倒序**（后做的先撤），不是日志的正序。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    stack.start_one("timeflow", wait_seconds=0, actor="pytest")
    capsys.readouterr()

    stack.cmd_log(argparse.Namespace(last=10, undo=True))
    out = capsys.readouterr().out
    commands = [ln for ln in out.splitlines() if ln.startswith("python -X utf8")]
    assert len(commands) == 2, out
    assert commands[0].endswith("stop timeflow"), (
        f"先撤的必须是**最后**做的那笔（timeflow）：{commands}"
    )
    assert commands[1].endswith("stop board"), commands


def test_cli_wires_the_log_subcommand(
    machine: FakeMachine, capsys: pytest.CaptureFixture
) -> None:
    """`stack.py log` / `log --undo --last N` 真经 CLI 走通（子命令注册没漏）。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    stack.start_one("timeflow", wait_seconds=0, actor="pytest")
    capsys.readouterr()

    rc = stack.main(["log", "--undo", "--last", "1"])
    out = capsys.readouterr().out
    assert rc == 0, out
    commands = [ln for ln in out.splitlines() if ln.startswith("python -X utf8")]
    assert commands == ["python -X utf8 tools/stack.py stop timeflow"], commands

    rc = stack.main(["log", "--last", "1"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "start timeflow" in out and "undo=stop timeflow" in out, out


# ────────────────────────── 判据 6：老日志不猜 ──────────────────────────


def test_legacy_lines_without_undo_are_reported_not_faked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """★ 判据 6：没有 `undo=` 的老日志 ⇒ **如实点数报出**，不替它编命令。"""
    log = tmp_path / "stack-actions.log"
    monkeypatch.setattr(stack, "ACTIONS_LOG", log)
    legacy = "2026-01-01T00:00:00+08:00  cli  start board  OK  已起（老日志，没有 undo）"
    modern = "2026-01-02T00:00:00+08:00  cli  stop board  OK  undo=start board  已停（pid 1）"
    log.write_text(f"{legacy}\n{modern}\n", encoding="utf-8")

    rc = stack.cmd_log(argparse.Namespace(last=10, undo=True))
    out = capsys.readouterr().out
    assert rc == 0, out
    commands = [ln for ln in out.splitlines() if ln.startswith("python -X utf8")]
    assert commands == ["python -X utf8 tools/stack.py start board"], commands
    assert "没有 undo 字段" in out, f"老日志要说清（不静默跳过）：{out!r}"
    assert "1 行" in out, f"要**点数**报出有几行：{out!r}"
    assert legacy in out, "要原样带出那一行，人才知道缺哪条"
    assert "不替它们编命令" in out, out


def test_a_detail_that_mentions_undo_is_not_mistaken_for_the_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """字段边界是**两个空格**：detail 里恰好写着 ` undo=…` 不算这一行的回滚。"""
    log = tmp_path / "stack-actions.log"
    monkeypatch.setattr(stack, "ACTIONS_LOG", log)
    tricky = (
        "2026-01-03T00:00:00+08:00  cli  start board  OK  "
        "结果里提到 undo=stop board 但不是字段"
    )
    log.write_text(tricky + "\n", encoding="utf-8")

    commands, missing = stack.undo_commands(10)
    assert commands == [], f"detail 里的 undo=… 被误当成字段：{commands}"
    assert missing == [tricky], missing


def test_undo_commands_is_a_pure_read(
    machine: FakeMachine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """`undo_commands()` 只读日志：一个 start/stop 都不调，`--last` 也真按行数取。"""
    stack.start_one("board", wait_seconds=0, actor="pytest")
    capsys.readouterr()
    called: list[str] = []
    monkeypatch.setattr(stack, "start_one", lambda *a, **k: called.append("start") or 0)
    monkeypatch.setattr(stack, "stop_one", lambda *a, **k: called.append("stop") or 0)

    commands, missing = stack.undo_commands(10)
    assert commands == ["python -X utf8 tools/stack.py stop board"], commands
    assert missing == [], missing

    stack.log_action("pytest", "start", "timeflow", True, "第二笔")
    assert stack.undo_commands(1)[0] == ["python -X utf8 tools/stack.py stop timeflow"]
    everything = stack.undo_commands(0)[0]
    assert len(everything) == 2, everything
    assert everything[-1].endswith("stop board"), "last=0 ⇒ 全部，含最早那笔（start board）"
    assert called == [], f"undo_commands 不该动手：{called}"


def test_empty_log_says_so_instead_of_printing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """空日志 ⇒ 如实说「空的」，不静默成功、不假装有命令。"""
    monkeypatch.setattr(stack, "ACTIONS_LOG", tmp_path / "nope" / "stack-actions.log")
    rc = stack.cmd_log(argparse.Namespace(last=10, undo=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "空的" in out, f"空日志要说出来：{out!r}"
    assert "python -X utf8" not in out, "没有动作就不许打印任何命令"
