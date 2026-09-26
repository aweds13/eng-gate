"""派活脚本（`tools/wb_dispatch.py`，T-G82）的测试 —— 给"四道前置检查"上护栏。

为什么值当测：这个脚本干的是**别人替我改工作区**这件事。四道检查里任何一道漏了，
后果都不是"报错"而是"悄悄把工作区搅乱 / 白等一轮 / 证据被盖掉"：
  · 脏工作区还派活 → 工人和我的改动混在一起，事后分不清谁动了什么；
  · 没登录还派活 → 白等一轮只拿到一句 Authentication required；
  · log 被覆盖 → 上一轮它到底干了什么，永远说不清。

真执行那条路**还没在真登录下跑过**（CLI 未登录，T-G80）—— 这里用假 runner 钉住
"命令怎么拼、跑完怎么渲染、退出码怎么传"，真机验证留给登录之后。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch as wd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


class _Done:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """一个"像仓库"的临时根：规格在、node 与 CLI 在、工作区干净、登录通。"""
    (tmp_path / "spec.md").write_text("卡规格", encoding="utf-8")
    node = tmp_path / "node.exe"
    cli = tmp_path / "codebuddy"
    node.write_text("", encoding="utf-8")
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (node, cli))
    monkeypatch.setattr(wd, "git_dirty", lambda: [])
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: (True, "登录自检通过"))
    return tmp_path


# ------------------------------------------------------------------ 命令拼装


def test_build_command_carries_the_opening_and_the_stream(sandbox: Path) -> None:
    """派活的命令必须：带上"读哪几张文档 + 哪张卡"的开场白、要 stream-json、要 -y。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "001", "spec.md", "deepseek-v4.1-flash")
    joined = " ".join(cmd)
    assert cmd[0] == str(node) and cmd[1] == str(cli)
    assert cmd[2] == "-p"
    for needle in ("复盘/交接-重构进度.md", "复盘/外包-卡表与规矩.md", "spec.md", "卡号 001"):
        assert needle in cmd[3]
    assert "--output-format stream-json" in joined
    assert "--model deepseek-v4.1-flash" in joined
    assert "--no-session-persistence" in joined and " -y" in joined
    # ★ 开场白**不许**写死某一张卡的约束（写卡要改文件/要提交，只读卡才不许）——
    #   纪律由卡规格带，规格与开场白冲突时按规格执行
    assert "以卡规格为准" in cmd[3]
    assert "不许 git 提交" not in cmd[3]


def test_build_command_grants_bypass_permissions_by_default(sandbox: Path) -> None:
    """★ `-y` 不够：实测工人跑 `python …` 会被"非交互无法确认"挡回来 → 默认要 bypassPermissions。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "001", "spec.md", "m")
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    tight = wd.build_command(node, cli, "001", "spec.md", "m", "acceptEdits")
    assert tight[tight.index("--permission-mode") + 1] == "acceptEdits"


def test_prefers_the_standalone_cli_and_honours_an_override(tmp_path: Path, monkeypatch) -> None:
    """默认优先独立安装的 CLI（带 TUI 那份）；`--cli` 能覆盖；都没有才退回 WorkBuddy 自带那份。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    pkg = tmp_path / "npm" / "node_modules" / "@tencent-ai" / "codebuddy-code" / "bin"
    pkg.mkdir(parents=True)
    standalone = pkg / "codebuddy"
    standalone.write_text("", encoding="utf-8")
    _, picked = wd.paths()
    assert picked == standalone
    _, forced = wd.paths("D:/somewhere/else/codebuddy")
    assert str(forced).replace("\\", "/") == "D:/somewhere/else/codebuddy"


# ------------------------------------------------------------------ 四道前置检查


def test_preflight_refuses_a_missing_spec(sandbox: Path) -> None:
    """没有卡规格就不许派活 —— 不许凭记忆派活（机器可查的一条）。"""
    problems, _ = wd.preflight("001", "没有这张卡.md", force=False, check_auth=True)
    assert any("卡规格文件不存在" in p for p in problems)


def test_preflight_refuses_a_dirty_workspace(sandbox: Path, monkeypatch) -> None:
    """脏工作区 = 一写一读当场失效 → 拦下，并把是哪些文件说出来。"""
    monkeypatch.setattr(wd, "git_dirty", lambda: ["M src/timeflow/api/app.py", "M docs/x.md"])
    called = []
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: called.append(1) or (True, "ok"))
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=True)
    assert any("工作区不干净" in p and "app.py" in p for p in problems)
    assert called == []          # 工作区都不干净了，就不必再去戳登录


def test_preflight_refuses_to_overwrite_an_existing_log(sandbox: Path) -> None:
    """上一轮的 log 还在 → 不许悄悄盖掉（证据）；显式 --force 才放行。"""
    log = sandbox / "gates" / "diag" / "wb-001.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{}", encoding="utf-8")
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert any("log 已存在" in p for p in problems)
    ok, _ = wd.preflight("001", "spec.md", force=True, check_auth=False)
    assert ok == []


def test_preflight_reports_a_failed_login(sandbox: Path, monkeypatch) -> None:
    """登录没通 → 直接不派活，并给出"去 TUI 敲 /login"这一条人话。"""
    why = "登录没通（Authentication required）"
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: (False, why))
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=True)
    assert any("登录没通" in p for p in problems)


def test_auth_ok_recognises_the_authentication_needle(monkeypatch) -> None:
    """真判据：回话里有那句 Authentication required 就判没登录（别把白等当成"它在想"）。"""
    monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: _Done(
        stdout="", stderr="Authentication required. Please use /login command"))
    ok, why = wd.auth_ok(Path("node"), Path("cli"))
    assert ok is False and "/login" in why


# ------------------------------------------------------------------ 干跑与真跑


EVENTS = [
    json.dumps({"type": "system", "subtype": "init", "model": "m", "tools": ["Read", "Grep"]},
               ensure_ascii=False),
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Grep", "input": {"pattern": "myday_rank"}}]}},
        ensure_ascii=False),
    json.dumps({"type": "result", "subtype": "success", "result": "复核完了"}, ensure_ascii=False),
]


def _fake_runner(record: list[list[str]], events: list[str] | None = None, rc: int = 0,
                 reason: str = "", scene: str = ""):
    """假 runner：照真 runner 的接口落 log 并回话（真 Popen 那条路由下面的桩命令真跑钉住）。"""
    def run(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        record.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(events or EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return rc, reason, scene
    return run


def test_dry_run_checks_but_does_not_dispatch(sandbox: Path, monkeypatch, capsys) -> None:
    """默认 dry-run：四道检查照跑、命令照印，但**一个子进程都不派**。"""
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "前置检查全过" in out
    assert record == []


def test_execute_dispatches_and_renders_the_timeline(sandbox: Path, monkeypatch, capsys) -> None:
    """--execute：真派、真落 log、跑完**用状态器把时间线印出来**（主控要的就是这个）。"""
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "Grep(pattern=myday_rank)" in out        # 时间线渲染出来了
    assert "复核完了" in out
    assert record and "--output-format" in record[0]
    assert "--max-turns" in record[0] and "--autocompact" in record[0]
    log = sandbox / "gates" / "diag" / "wb-001.jsonl"
    assert log.exists() and "tool_use" in log.read_text(encoding="utf-8")


def test_execute_reports_worker_failure_as_exit_4(sandbox: Path, monkeypatch, capsys) -> None:
    """工人自己失败（退出码非 0）→ 脚本退 4：主控一眼能看出"这一轮不算数"。"""
    monkeypatch.setattr(wd, "run_worker", _fake_runner([], rc=1))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 4
    assert "退出码 1" in capsys.readouterr().out


def test_execute_reports_a_killed_or_unfinished_run_as_exit_6(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 被掐 / 超时 / 撞上限 → 退 **6**，并把现场打到 stderr：这一轮**不算数**，别当成功。"""
    monkeypatch.setattr(wd, "run_worker", _fake_runner(
        [], reason="空转：最近 12 次工具调用里同一件事出现了 5 次", scene="    做 Read(a.py)"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 6
    err = capsys.readouterr().err
    assert "空转" in err and "现场" in err and "Read(a.py)" in err


def test_git_dirty_ignores_untracked_files(monkeypatch) -> None:
    """护栏：`git_dirty()` 走的是 `-uno`（未跟踪文件不算）—— 那两个别的窗口的文件不该拦人。"""
    argv_seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):                  # noqa: ANN001, ANN202
        argv_seen.append(list(cmd))
        return _Done(stdout="")

    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    assert wd.git_dirty() == []
    assert argv_seen and "-uno" in argv_seen[0]


# ============================================================ 反空转三道（T-G88）


def test_max_turns_default_leaves_room_for_a_real_card() -> None:
    """★ 标定口径：`--max-turns` 数的是**工具调用回合** —— 卡 002 实测 111 次工具调用
    （含工具调用的 assistant 消息 88 条）。`result` 里的 `num_turns`(=319) 是**另一个**计数器，
    照它定上限会把上限放到天上（这一条就是那两次差点犯错的护栏）。"""
    assert wd.max_turns_default(read_only=False) == wd.DEFAULT_MAX_TURNS_WRITE
    assert wd.max_turns_default(read_only=True) == wd.DEFAULT_MAX_TURNS_READONLY
    assert wd.DEFAULT_MAX_TURNS_WRITE >= 2 * 111, "卡 002 就用了 111 次工具调用，上限得留足余量"
    assert wd.DEFAULT_MAX_TURNS_READONLY < wd.DEFAULT_MAX_TURNS_WRITE


def test_build_command_carries_the_cap_and_the_compaction_window(sandbox: Path) -> None:
    """① 回合上限与上下文窗口都要真进命令行；`--effort` **不许**出现（= 保持默认 High）。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "001", "spec.md", "m", max_turns=42, autocompact="1m")
    assert cmd[cmd.index("--max-turns") + 1] == "42"
    assert cmd[cmd.index("--autocompact") + 1] == "1m"
    assert "--effort" not in cmd


def test_turns_are_counted_per_message_not_per_event() -> None:
    """回合按 `message.id` 去重：同一条回合发几条事件（文本 + 工具）只算一个。"""
    def ev(mid: str, *, tool: bool) -> str:
        content = ([{"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}] if tool
                   else [{"type": "text", "text": "嗯"}])
        return json.dumps({"type": "assistant", "message": {"id": mid, "content": content}})

    lines = [ev("m1", tool=False), ev("m1", tool=True), ev("m2", tool=True), "不是 JSON 的一行"]
    assert wd.turns_seen(lines) == 2
    # 对方改格式、不带 id → 退回"数事件"（会多算，所以只用来预警，不用来卡人）
    no_id = [json.dumps({"type": "assistant", "message": {"content": []}})] * 3
    assert wd.turns_seen(no_id) == 3


def test_repeat_signal_catches_consecutive_and_alternating_repeats() -> None:
    """② 空转：连着来 5 次算，A,B,A,B… 交替到 5 次也算（按窗口计数，不数末尾连续）。"""
    assert wd.repeat_signal(["Read|x"] * 5) == (5, "Read|x")
    # 窗口里每种只有 4 次 → 不算（★ 注意口径：判的是**最近 window 次里**的计数，
    # 所以"前面重复过、后来换了别的"不算数 —— 它现在不在原地打转了）
    spread = ["Read|x"] * 4 + ["Grep|y"] * 4 + ["Write|z"] * 4
    assert wd.repeat_signal(spread) is None
    alt = wd.repeat_signal(["Read|x", "Grep|y"] * 5)                      # 交替 5 次
    assert alt is not None and alt[0] == 5
    assert wd.repeat_signal([]) is None                                   # 一次都没调


def test_watchdog_speaks_up_on_stall_and_on_spin_only() -> None:
    """看门狗两条判据：静默到阈值 → 卡死；窗口内重复到阈值 → 空转；健康时**一句话不说**。"""
    healthy = ["Read|x", "Grep|y", "Write|z"] * 4     # 各 4 次，都没到阈值
    assert wd.watchdog_verdict(silent_seconds=1, signatures=healthy) == ""
    stall = wd.watchdog_verdict(silent_seconds=wd.STALL_SECONDS, signatures=healthy)
    assert "卡死" in stall and "分钟" in stall
    spin = wd.watchdog_verdict(silent_seconds=1, signatures=["Read|x"] * wd.REPEAT_NEED)
    assert "空转" in spin and "Read|x" in spin


def test_cap_verdict_calls_a_capped_run_unfinished() -> None:
    """★★ 撞上限时 CLI **自己停、退出码仍是 0** —— 必须由我们判一句"没做完"，否则腰斩被当成功。"""
    assert wd.cap_verdict(149, 150) == ""
    assert "没做完" in wd.cap_verdict(150, 150)


def test_heartbeat_line_says_what_the_controller_wants_to_know() -> None:
    """③ 心跳：一眼看出"它在动 + 跑到哪了"，不用去翻 log。"""
    line = wd.heartbeat_line(elapsed=610, turns=90, tool_calls=111, files=21, silent_seconds=3)
    for needle in ("已跑 10.2 分钟", "回合 90", "工具 111 次", "碰过文件 21 个", "静默 3 秒"):
        assert needle in line


def _stub(events: int, sleep_after: float) -> list[str]:
    """桩子命令：吐 `events` 条**一模一样**的工具调用、再吐一条成功的 `result`，然后装死。"""
    code = "\n".join([
        "import json, sys, time",
        "ev = {'type': 'assistant', 'message': {'id': 'm', 'content': [",
        "    {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}}]}}",
        f"for _ in range({events}):",
        "    print(json.dumps(ev), flush=True)",
        "res = {'type': 'result', 'subtype': 'success', 'result': '干完了'}",
        "print(json.dumps(res), flush=True)",
        f"time.sleep({sleep_after})",
        "",
    ])
    return [sys.executable, "-X", "utf8", "-c", code]


def test_finish_verdict_catches_a_capped_run_though_the_exit_code_is_zero() -> None:
    """★★ 真机实测（T-G89 探针）：撞 `--max-turns` 时 CLI 给的是
    `subtype = error_during_execution` + **空回话**，而**进程退出码仍是 0** ——
    只看退出码会把"腰斩"当成功，所以必须读 `result` 事件。"""
    capped = [json.dumps({"type": "result", "subtype": "error_during_execution", "result": ""})]
    assert "没跑完" in wd.finish_verdict(capped)
    assert "error_during_execution" in wd.finish_verdict(capped)
    assert "回话是空的" in wd.finish_verdict(
        [json.dumps({"type": "result", "subtype": "success", "result": ""})])
    assert "没有 `result` 事件" in wd.finish_verdict([json.dumps({"type": "assistant"})])
    good = [json.dumps({"type": "result", "subtype": "success", "result": "干完了"})]
    assert wd.finish_verdict(good) == ""


def test_runner_writes_the_log_and_reports_a_clean_finish(tmp_path: Path) -> None:
    """健康的一轮：逐行落盘、退出码照传、**不掐**（reason 空串 = 正常收工）。"""
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    code, reason, scene = wd.run_worker(_stub(2, 0.1), log, err, timeout=60, max_turns=150,
                                        watchdog=True, heartbeat_seconds=0)
    assert (code, reason, scene) == (0, "", "")
    # 2 条工具事件 + 1 条 result —— 真工人也是这么收尾的
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 3
    assert tmp_path.joinpath("w.err").exists()


def test_runner_kills_a_stalled_worker_and_reports_the_scene(tmp_path: Path) -> None:
    """★ 真掐一条：工人吐一条事件然后装死 → 看门狗按阈值**掐掉整棵进程树**并报现场。

    三道护栏里只有这条"会动刀"，所以必须真跑 —— 假 runner 证明不了它真能把它停住。
    """
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    beats: list[str] = []
    started = time.monotonic()
    _, reason, scene = wd.run_worker(_stub(1, 60), log, err, timeout=120, max_turns=150,
                                     watchdog=True, heartbeat_seconds=1, stall_seconds=2,
                                     poll_seconds=0.2, printer=beats.append)
    elapsed = time.monotonic() - started
    assert "卡死" in reason, reason
    assert elapsed < 30, f"装死 60 秒，掐得太慢了：{elapsed:.1f} 秒"
    assert any("心跳" in b for b in beats), f"心跳没打：{beats}"
    assert "file_path=a.py" in scene, scene       # 现场里带着它最后那步（主控据此看卡在哪）


def test_runner_kills_a_spinning_worker_even_though_it_is_not_silent(tmp_path: Path) -> None:
    """★ 空转也真掐：它**一直在动**（日志不静默），只是原地重复同一件事 —— 静默判据抓不到它。"""
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    _, reason, _ = wd.run_worker(_stub(wd.REPEAT_NEED + 1, 60), log, err, timeout=120,
                                 max_turns=150, watchdog=True, heartbeat_seconds=0,
                                 stall_seconds=120, poll_seconds=0.2)
    assert "空转" in reason, reason


def test_runner_reports_a_truncated_run_as_unfinished(tmp_path: Path) -> None:
    """★ 退出码 0 但 stream 说 `error_during_execution` → runner 必须报「没跑完」（退 6）。

    这就是"腰斩"最危险的那一面：进程**高高兴兴退 0**，而它其实什么都没交出来。
    """
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    code = ("import json\n"
            "print(json.dumps({'type': 'result', 'subtype': 'error_during_execution',"
            " 'result': ''}))\n")
    rc, reason, _ = wd.run_worker([sys.executable, "-X", "utf8", "-c", code], log, err,
                                  timeout=60, max_turns=240, watchdog=True, heartbeat_seconds=0)
    assert rc == 0, "这次就是故意让它退 0 的（真机撞上限时也是这样）"
    assert "没跑完" in reason, reason
