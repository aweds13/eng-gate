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


def _fake_worker(record: list[list[str]], rc: int = 0):
    def run(cmd, **kwargs):                       # noqa: ANN001, ANN202
        record.append(list(cmd))
        out = kwargs.get("stdout")
        if out is not None:
            out.write(json.dumps({"type": "system", "subtype": "init", "model": "m",
                                  "tools": ["Read", "Grep"]}, ensure_ascii=False) + "\n")
            out.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Grep", "input": {"pattern": "myday_rank"}}]}},
                ensure_ascii=False) + "\n")
            out.write(json.dumps({"type": "result", "subtype": "success", "result": "复核完了"},
                                 ensure_ascii=False) + "\n")
        return _Done(returncode=rc)
    return run


def test_dry_run_checks_but_does_not_dispatch(sandbox: Path, monkeypatch, capsys) -> None:
    """默认 dry-run：四道检查照跑、命令照印，但**一个子进程都不派**。"""
    record: list[list[str]] = []
    monkeypatch.setattr(wd.subprocess, "run", _fake_worker(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "前置检查全过" in out
    assert record == []


def test_execute_dispatches_and_renders_the_timeline(sandbox: Path, monkeypatch, capsys) -> None:
    """--execute：真派、真落 log、跑完**用状态器把时间线印出来**（主控要的就是这个）。"""
    record: list[list[str]] = []
    monkeypatch.setattr(wd.subprocess, "run", _fake_worker(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "Grep(pattern=myday_rank)" in out        # 时间线渲染出来了
    assert "复核完了" in out
    assert record and "--output-format" in record[0]
    log = sandbox / "gates" / "diag" / "wb-001.jsonl"
    assert log.exists() and "tool_use" in log.read_text(encoding="utf-8")


def test_execute_reports_worker_failure_as_exit_4(sandbox: Path, monkeypatch, capsys) -> None:
    """工人自己失败（退出码非 0）→ 脚本退 4：主控一眼能看出"这一轮不算数"。"""
    monkeypatch.setattr(wd.subprocess, "run", _fake_worker([], rc=1))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 4
    assert "退出码 1" in capsys.readouterr().out


def test_git_dirty_ignores_untracked_files(monkeypatch) -> None:
    """护栏：`git_dirty()` 走的是 `-uno`（未跟踪文件不算）—— 那两个别的窗口的文件不该拦人。"""
    argv_seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):                  # noqa: ANN001, ANN202
        argv_seen.append(list(cmd))
        return _Done(stdout="")

    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    assert wd.git_dirty() == []
    assert argv_seen and "-uno" in argv_seen[0]
