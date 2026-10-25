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
import locale
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch as wd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
import wb_session as wb_session  # noqa: E402 —— 卡 E17：账本要能指到 tmp_path


class _Done:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


#: 沙箱队列：测试里用到的卡号各一条（域各不同）—— 守卫「域从队列真读」要有东西可读。
_SANDBOX_CARD_IDS = ("000", "001", "002", "007", "009", "023")
_SANDBOX_BACKLOG = "[base]\nreviewed = \"sandbox\"\n" + "".join(
    f"""
[[cards]]
id = "{cid}"
task = "T-{cid}"
title = "沙箱卡 {cid}"
tree = ""
spec = "spec.md"
files = ["sandbox-{cid}.md"]
"""
    for cid in _SANDBOX_CARD_IDS
)


@pytest.fixture(autouse=True)
def isolated_session_ledger(tmp_path: Path, monkeypatch) -> Path:
    """★ 卡 E17：`wd.main()` 会调 `wb_session.claim()` 写「卡归窗口」账本，而账本路径
    默认指**真仓** `gates/diag/session-leases.json` ⇒ 本文件的用例会去写真账本、和
    落地链抢同一个文件（Windows 上就是 `WinError 32`）。整份文件统一隔离到 `tmp_path`，
    省得每条 `wd.main()` 用例各记一次。
    """
    ledger = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)
    return ledger


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """一个"像仓库"的临时根：规格在、队列在、登记空、node 与 CLI 在、工作区干净、登录通。"""
    (tmp_path / "spec.md").write_text("卡规格", encoding="utf-8")
    node = tmp_path / "node.exe"
    cli = tmp_path / "codebuddy"
    node.write_text("", encoding="utf-8")
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (node, cli))
    # ★ T-G204：`git_dirty` 现在能收「看哪棵树」这个参数（T-G199），桩要跟着改成可变参 ——
    #   否则一带 `--cwd` 的用例就会 `TypeError: <lambda>() takes 0 positional arguments`。
    monkeypatch.setattr(wd, "git_dirty", lambda *a, **k: [])
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: (True, "登录自检通过"))
    # ★ 卡 102：沙箱要**与宿主内存无关** —— 内存闸的判据（读本机 available）由
    #   `tests/test_mem_guard.py` 用桩专测；这里测的是规格/脏树/log/端口/登录，把它们
    #   从"这台机器此刻有多少可用内存"里摘出来（否则本机内存低时它们会假红）。
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "0")
    # ★ 卡 125：守卫要读**队列**（域）与**作业登记**（活租约），还要看门禁锁原文 —— 全部指到
    #   沙箱里：队列现写、登记用 `TF_POOL_REGISTRY` 覆盖（绝不碰主树那份真登记）、
    #   锁原文用桩（真跑 `gate_lock.py status` 会把宿主的活锁读进来 → 假红）。
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "workbacklog.toml").write_text(_SANDBOX_BACKLOG, encoding="utf-8")
    monkeypatch.setenv("TF_POOL_REGISTRY",
                       str(tmp_path / "gates" / "diag" / "pool-registry.json"))
    # ★ 卡 120（T-G232）接上 `project_guard` 之后，沙箱也得**有一份自己的项目索引**：
    #   几条用例把 `--cwd` 指到**仓外临时目录**、或干脆不给 `--cwd`（= 主树）⇒ 守卫会**正确地**拒
    #   （"这棵树不属于任何已登记项目"）——那是守卫在干活，不是它坏了 ⇒ 这里按 `TF_POOL_REGISTRY`
    #   同款把**索引也隔离到沙箱**：① 沙箱临时目录自己算一个项目（仓外树标签走这条）；
    #   ② ★ **「主树」那条反查用的是 `projects.tree_root()`（真实仓库根，
    #      不受 `wd.ROOT` monkeypatch 影响）**
    #   ⇒ 还得有一条 `root` 是**真实仓库根的祖先**的登记（父目录，真实存在 ⇒ 过 root 校验）。
    real_root = pathlib.Path(wd.__file__).resolve().parents[2]
    projects_toml = tmp_path / "projects.toml"
    projects_toml.write_text(chr(10).join([
        "[project.sandbox]",
        'name = "沙箱"',
        f'root = "{tmp_path.as_posix()}"',
        "memory = []",
        "layers = []",
        # ★ 卡 203：`worker_tree_label(None, …)` 现在按**进程 cwd** 还原 ⇒ 不给 `--cwd` 的用例
        #   会算出**相对**标签（如 `.wt/dtree`）。真索引（infra/pool/projects.toml）的
        #   `tree_prefixes = [".wt/"]` 正是这种相对前缀 —— 沙箱照抄一条，别再只认绝对临时目录。
        f'tree_prefixes = ["{tmp_path.as_posix()}", ".wt/"]',
        'queue = ""',
        'ledger = ""',
        'cards = ""',
        "",
        "[project.sandbox-ancestor]",
        'name = "沙箱（祖先，给主树反查用）"',
        f'root = "{real_root.parent.as_posix()}"',
        "memory = []",
        "layers = []",
        f'tree_prefixes = ["{tmp_path.as_posix()}"]',
        'queue = ""',
        'ledger = ""',
        'cards = ""',
    ]) + chr(10), encoding="utf-8")
    monkeypatch.setenv("TF_PROJECTS_TOML", str(projects_toml))
    monkeypatch.setattr(wd.pool_registry, "read_lock_body", lambda *a, **k: "")
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
    assert " -y" in joined
    # ★ T-G90：不再关会话（关了就没法 `--resume` 续跑），八条铁律改走系统提示
    assert "--no-session-persistence" not in joined
    assert "--append-system-prompt" in joined and "以卡规格为准" in joined
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


def test_preflight_refuses_when_batch_manifest_missing(sandbox: Path) -> None:
    """★ 卡 157（T-G257）派活前置：规格声称了 `B-X` 但预声明缺 ⇒ **拒发**（第一分钟就知道）。

    工人不用再干 28 分钟到最后交申请时才被栅栏咬 —— 派活器在 preflight 里就拦下。
    """
    (sandbox / "spec.md").write_text(
        "# 卡\n\n**成员号**：任务 `B-PREFLIGHT-TEST` 的 **M-1**\n", encoding="utf-8")
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    hit = [p for p in problems if "B-PREFLIGHT-TEST" in p and "预声明" in p and "register" in p]
    assert hit, f"应点名缺的预声明并提示 register，拿到 {problems}"


def test_preflight_passes_when_spec_has_no_batch_claim(sandbox: Path) -> None:
    """★ 卡 157：规格里没声称批次（只读审计型）⇒ preflight **不因这条报**。"""
    (sandbox / "spec.md").write_text("# 对抗审核卡\n\n没有成员号那行\n", encoding="utf-8")
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert not any("声称" in p or "预声明" in p for p in problems), problems


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


# ------------------------------------------------------ ⑤ 端口段体检（卡 095 · 铁律 37）


def test_port_preflight_skips_when_no_segment(sandbox: Path, capsys) -> None:
    """没给端口段 → **跳过**端口体检（不检查也不假装检查），不拒派。"""
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert problems == []
    assert "未给端口段，跳过端口体检" in capsys.readouterr().err


def test_port_preflight_refuses_when_segment_busy(sandbox: Path, monkeypatch) -> None:
    """★ 反例：段内有占用 → 拒派，并**点名**占用者 + 写出铁律 37 出处。"""
    import tf_portcheck
    monkeypatch.setattr(tf_portcheck, "busy_ports",
                        lambda: {9197: "pid=4321 vivoesService_x64.exe"})
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                               port_bases=[9191])
    assert any("9197" in p and "vivoesService_x64.exe" in p for p in problems)
    assert any("铁律 37" in p for p in problems)


def test_port_preflight_passes_when_segment_free(sandbox: Path, monkeypatch) -> None:
    """段内全空闲 → 不拒派（问题清单里没有端口那条）。"""
    import tf_portcheck
    monkeypatch.setattr(tf_portcheck, "busy_ports", lambda: {})
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                               port_bases=[9191])
    assert problems == []


def test_main_refuses_when_env_segment_busy(sandbox: Path, monkeypatch, capsys) -> None:
    """走完整 main：`TF_DISPATCH_PORT_BASE` 给的段内有占用 → 拒派（退 2）并点名。"""
    import tf_portcheck
    monkeypatch.setattr(tf_portcheck, "busy_ports",
                        lambda: {9197: "pid=1 vivoesService_x64.exe"})
    monkeypatch.setenv("TF_DISPATCH_PORT_BASE", "9191")
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--no-preflight"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "9197" in err and "vivoesService_x64.exe" in err and "铁律 37" in err


def test_main_skips_port_check_without_segment(sandbox: Path, monkeypatch, capsys) -> None:
    """走完整 main：没给端口段 → 跳过体检（打印一行），照常 dry-run 通过。

    ★ T-G195：这里**故意**把 `TF_GATE_PORT_BASE` 设成一个"段内有占用"的值 ——
    它是**门禁自己**的端口段（`run_gates.py` 会把它设进每一道门的子进程，含 pytest），
    派活器**绝不能**拿它当自己的端口段，否则门禁内部一起服务就"拒派"，24 条用例全红。
    """
    import tf_portcheck
    monkeypatch.setattr(tf_portcheck, "busy_ports",
                        lambda: {9197: "pid=1 vivoesService_x64.exe"})
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9191")          # ← 门禁那个：必须被无视
    monkeypatch.delenv("TF_DISPATCH_PORT_BASE", raising=False)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--no-preflight"])
    assert wd.main() == 0
    assert "未给端口段，跳过端口体检" in capsys.readouterr().err


def test_cwd_makes_brief_and_spec_paths_absolute(sandbox: Path, monkeypatch, capsys) -> None:
    """★ T-G204：给了 `--cwd` ⇒ 开场白里的 brief/spec 必须是**绝对路径**。

    为什么：`--cwd` 把**工人进程的 cwd** 挪到卡树，而切片/规格是**仓库相对**路径
    （`gates/diag/…` 只存在于主仓）⇒ 相对写法会把工人指到不存在的路径上，
    它只能自己满盘找（卡 106 的工人就是这么找到的 —— 那是运气不是设计）。
    """
    work = sandbox / "cardtree"
    work.mkdir()
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)   # 这条判据由别的用例专测
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--lean", "--cwd", str(work), "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert str(sandbox / "spec.md") in out, "规格没给绝对路径"
    assert str(sandbox / "gates" / "diag" / "brief-001.md") in out, "切片没给绝对路径"
    assert "读 gates/diag/brief-001.md" not in out, "还留着指错路的相对写法"


def test_without_cwd_paths_stay_repo_relative(sandbox: Path, monkeypatch, capsys) -> None:
    """反例：**不给** `--cwd` 时行为逐字不变（仍是仓库相对路径）。"""
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--lean", "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "读 gates/diag/brief-001.md" in out
    assert str(sandbox / "gates" / "diag" / "brief-001.md") not in out


# ---------------------------------------------- 卡 194（T-G294）：白名单路径指卡树


def test_cwd_resolves_domain_files_to_the_card_tree(sandbox: Path, monkeypatch,
                                                    capsys) -> None:
    """★ 卡 194 钉子①：给了 `--cwd` ⇒ 白名单（域）路径必须是**卡树绝对路径**。

    现场根因：`prompt_path()` 一刀切到主仓 ⇒ 工人顺着绝对路径改到主树（卡 151 真发生）。
    """
    work = sandbox / "cardtree"
    work.mkdir()
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--cwd", str(work), "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert str(work / "sandbox-001.md") in out, "域文件没解析成卡树绝对路径"


def test_cwd_keeps_spec_and_brief_on_the_main_tree(sandbox: Path, monkeypatch,
                                                   capsys) -> None:
    """★ 卡 194 钉子②：给了 `--cwd`，规格 / 切片仍指向**主仓**（只读临时件不在卡树里）。"""
    work = sandbox / "cardtree"
    work.mkdir()
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--lean", "--cwd", str(work), "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert str(sandbox / "spec.md") in out, "规格没指向主仓"
    assert str(sandbox / "gates" / "diag" / "brief-001.md") in out, "切片没指向主仓"


def test_without_cwd_no_domain_hint(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 卡 194 钉子③：不给 `--cwd` ⇒ 域提示不出现、行为逐字不变（向后兼容）。"""
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "卡树（--cwd）" not in out, "不给 --cwd 不该出现域提示段"
    assert str(sandbox / "sandbox-001.md") not in out, "不给 --cwd 不该有域绝对路径"


def test_cwd_domain_files_must_not_resolve_to_main_tree(sandbox: Path, monkeypatch,
                                                        capsys) -> None:
    """★ 卡 194 钉子④（反例）：给了 `--cwd`，域文件的主仓绝对路径**不许**出现。

    今天这个 bug 就是白名单路径解析到主仓 ⇒ 工人改到主树。本条故意坏掉 `writable` 分支
    （改回一刀切主仓）会红。
    """
    work = sandbox / "cardtree"
    work.mkdir()
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--cwd", str(work), "--no-preflight"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert str(sandbox / "sandbox-001.md") not in out, "域文件解析到主仓了（卡 194 的 bug）"


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
        wd.session_file_for(log).write_text("sid-test", encoding="utf-8")
        return rc, reason, scene, "sid-test"
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


def test_finish_verdict_names_429_when_quota_error_hits() -> None:
    """★ 卡 151 钉子①：log 里有 429 命中 ⇒ 判决文案出现"429"、不出现"撞 `--max-turns`"，
    且把重置时间原样带出来。故意删掉 429 分流会让本条红。"""
    quota_log = [_quota_result_event(with_reset=True)]
    verdict = wd.finish_verdict(quota_log)
    assert "429" in verdict, "429 命中要点名 429"
    assert "撞 `--max-turns`" not in verdict, "429 命中不许再归到撞 max-turns（那是另一个真因）"
    assert "2026-09-27 07:38" in verdict, "重置时间要原样带出来"


def test_cap_verdict_names_max_turns_and_not_429() -> None:
    """★ 卡 151 钉子②：没有 429、但回合数到顶 ⇒ 判决文案出现 max-turns、不出现 429。
    这是 `cap_verdict()` 的判据（数回合），与 `finish_verdict()` 读 result 事件互补。"""
    verdict = wd.cap_verdict(150, 150)
    assert "max-turns" in verdict, "回合数到顶要写出 max-turns"
    assert "429" not in verdict, "回合数到顶不该提 429（429 在 finish_verdict 那一支）"
    assert "没做完" in verdict


def test_finish_verdict_says_unknown_when_no_quota_no_cap() -> None:
    """★ 卡 151 钉子③：subtype != success + 没有 429 + 回话空 ⇒ 判决文案写「真因未识别」，
    不许默认说是 max-turns（那是猜）。"""
    no_clue = [json.dumps({"type": "result", "subtype": "error_during_execution", "result": ""})]
    verdict = wd.finish_verdict(no_clue)
    assert "真因未识别" in verdict, "两个真因都没命中要写真因未识别"
    assert "撞 `--max-turns`" not in verdict, "不许默认归到撞 max-turns（旧文案）"


def test_finish_verdict_carries_evidence_pointer_in_the_verdict_line() -> None:
    """★ 卡 151 钉子④：判决那句里带得出依据（log 行号 / 字段名）——
    429 现场要点出 result 事件在第几行、命中了哪个字段；真因未识别现场要点出 subtype 与回话。
    删掉依据指针会让本条红（哪怕 429 / 真因未识别 字面还在）。"""
    verdict_429 = wd.finish_verdict([_quota_result_event(with_reset=True)])
    assert "依据" in verdict_429, "429 判决要带依据"
    assert "第 1 行" in verdict_429, "429 判决要点出 log 行号"
    assert "字段" in verdict_429, "429 判决要点出命中字段"

    no_clue = [json.dumps({"type": "result", "subtype": "error_during_execution", "result": ""})]
    verdict_unknown = wd.finish_verdict(no_clue)
    assert "依据" in verdict_unknown, "真因未识别判决也要带依据"
    assert "第 1 行" in verdict_unknown, "真因未识别判决要点出 log 行号"
    assert "subtype=" in verdict_unknown, "真因未识别判决要点出 result 事件的字段"


def test_runner_writes_the_log_and_reports_a_clean_finish(tmp_path: Path) -> None:
    """健康的一轮：逐行落盘、退出码照传、**不掐**（reason 空串 = 正常收工）。"""
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    code, reason, scene, sid = wd.run_worker(_stub(2, 0.1), log, err, timeout=60, max_turns=150,
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
    _, reason, scene, _sid = wd.run_worker(_stub(1, 60), log, err, timeout=120, max_turns=150,
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
    _, reason, _, _sid = wd.run_worker(_stub(wd.REPEAT_NEED + 1, 60), log, err, timeout=120,
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
    rc, reason, _, _sid = wd.run_worker([sys.executable, "-X", "utf8", "-c", code], log, err,
                                        timeout=60, max_turns=240, watchdog=True,
                                        heartbeat_seconds=0)
    assert rc == 0, "这次就是故意让它退 0 的（真机撞上限时也是这样）"
    assert "没跑完" in reason, reason


# ==================================================== 稳定化：续跑 + 铁律进系统提示（T-G90）


def test_iron_rules_go_into_the_system_prompt_not_only_the_opening(sandbox: Path) -> None:
    """★ 铁律走 `--append-system-prompt`：开场白会随上下文压缩越来越远，系统提示还在。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "002", "spec.md", "m")
    rules = cmd[cmd.index("--append-system-prompt") + 1]
    assert rules == wd.IRON_RULES
    for needle in ("以卡规格为准", "越界", "不许假完成", "一写一读", "禁区", "不假装",
                   "小步提交", "不许碰主干", "card/<号>"):
        assert needle in rules, rules


def test_resume_command_continues_the_same_session() -> None:
    """续跑命令：`--resume <id>` + "接着干"的指令 + 同一套铁律 + 别的口径不变。"""
    cmd = wd.resume_command(Path("node"), Path("cli"), "sid-123", "接着干", "m")
    assert cmd[cmd.index("--resume") + 1] == "sid-123"
    assert cmd[cmd.index("-p") + 1] == "接着干"
    assert "--append-system-prompt" in cmd and "--max-turns" in cmd
    assert "--no-session-persistence" not in cmd


def test_session_id_is_picked_up_from_the_events() -> None:
    """会话 id 就在事件里 —— 存下来，中断了才续得上（取最后一个）。"""
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "aaaa"}),
             json.dumps({"type": "result", "subtype": "success", "session_id": "bbbb"})]
    assert wd.session_id_seen(lines) == "bbbb"
    assert wd.session_id_seen(["不是 JSON 的一行"]) == ""
    assert wd.session_file_for(Path("gates/diag/wb-002.jsonl")).name == "wb-002.session.txt"


def test_continuation_prompt_tells_it_not_to_redo_finished_work() -> None:
    """续跑时最贵的错是"重做一遍" —— 指令里必须明说，并把中断现场交给它。"""
    said = wd.continuation_prompt(reason="卡死：8.0 分钟没有新事件", scene="    做 Read(a.py)",
                                  card="002")
    for needle in ("被中断", "同一张卡", "002", "不要重做", "Read(a.py)"):
        assert needle in said, said


def test_should_resume_continues_interruptions_but_not_spinning() -> None:
    """★ 只对「被打断」续跑：空转是原地打转，续跑只会让它接着转（那正是看门狗要掐的）。"""
    assert wd.should_resume("卡死：8 分钟没有新事件", attempts_done=1, retries=1) is True
    assert wd.should_resume("超时：3600 秒到了", attempts_done=1, retries=1) is True
    assert wd.should_resume("空转：最近 12 次里同一件事 9 次", attempts_done=1, retries=1) is False
    assert wd.should_resume("", attempts_done=1, retries=1) is False         # 正常收工，不续
    assert wd.should_resume("卡死", attempts_done=2, retries=1) is False      # 续跑次数用完了


def test_execute_auto_resumes_an_interrupted_run(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 端到端：第 1 次被掐 → **自动带同一会话续跑** → 第 2 次成功。

    这就是"中断不等于白干"：花的是续跑的钱，不是从头再来的钱。
    """
    calls: list[list[str]] = []
    outcomes = [("卡死：8.0 分钟没有新事件 → 已掐", "    做 Read(a.py)"), ("", "")]

    def runner(cmd, log, errlog, **kwargs):        # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, outcomes[len(calls) - 1][0], outcomes[len(calls) - 1][1], "sid-abc"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert len(calls) == 2, "应当续跑一次（被掐 → 接着干）"
    assert "--resume" in calls[1] and calls[1][calls[1].index("--resume") + 1] == "sid-abc"
    assert "不要重做" in calls[1][calls[1].index("-p") + 1]
    assert "续跑" in out
    side = sandbox / "gates" / "diag" / "wb-001.session.txt"
    assert side.read_text(encoding="utf-8") == "sid-abc"


def test_execute_does_not_resume_a_spinning_run(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 空转**不许**自动续跑 —— 否则它就接着转下去，护栏等于没装。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):        # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "空转：最近 12 次工具调用里同一件事出现了 9 次", "    做 Read(a.py)", "sid-x"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 6
    assert len(calls) == 1, "空转只能跑一次，不许自动续跑"
    assert "空转" in capsys.readouterr().err


# ==================================================== 长跑：活过我的窗口 + 状态可查（T-G91）


def test_detached_argv_strips_the_flag_and_marks_the_child() -> None:
    """★ 扔出去跑的子进程 argv：去掉 `--detach`、补内部标记 —— 不然会无限生小进程。"""
    out = wd.detached_argv(["--card", "002", "--spec", "s.md", "--detach", "--execute"])
    assert "--detach" not in out
    assert out[-1] == "--detach-done"
    assert "--card" in out and "002" in out and sys.executable in out
    # ★ T-G92：父进程已经查过登录了，子进程补 `--no-preflight`（恰好一次）
    assert out.count("--no-preflight") == 1


def test_detached_argv_adds_no_preflight_exactly_once() -> None:
    """★ T-G92：子进程补 `--no-preflight`（父进程已做登录自检，省十几秒）—— **恰好一次**。

    输入里已有的（人可能手填）要先去重，否则命令行里会出现两个同名开关。
    """
    once = wd.detached_argv(["--card", "002", "--spec", "s.md", "--detach"])
    assert once.count("--no-preflight") == 1
    twice = wd.detached_argv(["--card", "002", "--no-preflight", "--no-preflight", "--detach"])
    assert twice.count("--no-preflight") == 1
    assert twice[-1] == "--detach-done" and "--detach" not in twice


def test_detached_argv_keeps_the_script_so_the_child_actually_runs() -> None:
    """★ T-G92 真机证据 (b) 逮到的**第二个洞**：argv 少了**脚本路径**。

    `python -X utf8 --card 900 …` 里 python 把 `--card` 当成**自己的**选项 → 子进程其实什么都没跑
    （`Unknown option: --card`）。旧写法只 `[python, -X, utf8, *args]`，**从来没能真扔出去过** ——
    T-G91 的探针只验了 `spawn_detached()` 本身（用自造命令），没走 detach 这条 argv 拼装路。
    ★ T-G95 在解释器开关里补了 `-u`（无缓冲），所以脚本的下标从 3 挪到 4 —— 事实一条没变。
    """
    out = wd.detached_argv(["--card", "900", "--detach"])
    assert out[0] == sys.executable
    assert out[1:4] == ["-X", "utf8", "-u"]
    assert out[4] == str(Path(wd.__file__).resolve()), "解释器开关后面必须是脚本自己"
    assert out[5:7] == ["--card", "900"]


def test_detach_throws_the_work_out_and_returns_immediately(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 长任务/过夜：`--detach` 只需**扔出去**就返回（我的窗口关了它照样跑），前提是检查全过。"""
    seen: list[tuple[list[str], Path]] = []

    def fake_spawn(argv: list[str], log_path: Path) -> int:      # noqa: ANN001
        seen.append((list(argv), log_path))
        return 4242

    monkeypatch.setattr(wd, "spawn_detached", fake_spawn)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "002", "--spec", "spec.md",
                                      "--detach", "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert len(seen) == 1, "应当只扔一次"
    argv, log_path = seen[0]
    assert "--detach-done" in argv and "--detach" not in argv
    assert argv.count("--no-preflight") == 1
    assert log_path.name == "wb-002.dispatch.log"
    assert "4242" in out and "--status" in out and "前置检查全过" in out


def test_detach_runs_preflight_in_the_parent_and_refuses_before_throwing(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★★ T-G92：`--detach` 的前置检查必须在**父进程**里先做完 —— 没过就退 2、绝不 detach。

    旧写法先 detach 再（在子进程里）检查 → 父进程高高兴兴退 0，而检查其实没过；过夜之后
    `--status` 只会说「判决：还没有」，**分不清"没跑"和"跑挂了"**。这一条就是那个洞的补丁。
    """
    thrown: list[list[str]] = []
    monkeypatch.setattr(wd, "spawn_detached",
                        lambda argv, log: thrown.append(list(argv)) or 4242)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "900",
                                      "--spec", "没有这张卡.md", "--detach", "--execute"])
    assert wd.main() == 2
    assert thrown == [], "前置检查没过，一个子进程都不许扔"
    err = capsys.readouterr().err
    assert "前置检查没过" in err and "卡规格文件不存在" in err
    verdict = sandbox / "gates" / "diag" / "wb-900.verdict.txt"
    assert verdict.exists(), "没过也要留痕 —— 过夜后才分得清『没跑』和『跑挂了』"
    body = verdict.read_text(encoding="utf-8")
    assert "前置检查没过" in body and "没派活" in body and "卡规格文件不存在" in body


def test_status_reads_files_only_and_needs_no_spec(tmp_path: Path, monkeypatch, capsys) -> None:
    """★ 一条命令看状态：心跳 / 判决 / 会话 / log 尾巴 —— 只读文件，不碰工人。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    (diag / "wb-002.jsonl").write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    wd.write_heartbeat(diag / "wb-002.jsonl", "[心跳] 已跑 44.0 分钟 | 回合 90")
    wd.verdict_file_for(diag / "wb-002.jsonl").write_text("判决：正常收工（工人退出码 0）\n",
                                                          encoding="utf-8")
    wd.session_file_for(diag / "wb-002.jsonl").write_text("sid-777", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "002", "--status"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    for needle in ("[心跳] 已跑 44.0 分钟", "正常收工", "sid-777", "wb-002.jsonl", "复核完了"):
        assert needle in out, out


def test_status_says_so_when_nothing_ran_yet(tmp_path: Path, monkeypatch) -> None:
    """没派过的卡也要给一句人话（不是崩、不是空白）。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    said = wd.status_report("999")
    assert "还没有" in said and "一个都没有" in said


# -------------------------------------------------- 心跳停滞告警（T-G112 · 架构 C）
#
# 为什么值当测：架构 C 的全部价值就在这条告警上 —— 派活进程被系统杀掉之后，
# 它是唯一的"有人管之前先看得见"。接线一旦掉了（`status_report` 忘了调
# `heartbeat_stall_alert`），`--status` 照样正常输出、谁也发现不了 ——
# 所以每条用例都直接打在接线上，突变检验时拆掉它必须红。


def _running_events() -> list[str]:
    """一段"还在跑"的 log：有事件、没有 result（result 一出现就算收工）。"""
    return [EVENTS[0], EVENTS[1]]


def _ageing(*paths: Path, seconds: float) -> None:
    """把文件 mtime 拨回 `seconds` 秒前 —— 测试里替代"真的等那么久"。"""
    old = time.time() - seconds
    for p in paths:
        os.utime(p, (old, old))


def test_status_alarms_when_nobody_is_watching(tmp_path: Path, monkeypatch) -> None:
    """心跳停 + 日志静默 + 没判决 → ★告警（派活进程被杀 = 没人盯了）。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 已跑 3.0 分钟 | 回合 5")
    _ageing(log, wd.heartbeat_file_for(log), seconds=wd.STALL_SECONDS + 60)
    said = wd.status_report("042")
    assert "★告警" in said, said
    assert "没人盯了" in said, said
    assert "与看门狗底线同一口径" in said, said


def test_status_alarms_without_any_heartbeat(tmp_path: Path, monkeypatch) -> None:
    """没有心跳文件 + 日志静默 + 没判决 → 也告（--heartbeat-seconds 0 或派活器刚起就死）。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    _ageing(log, seconds=wd.STALL_SECONDS + 60)
    said = wd.status_report("042")
    assert "★告警" in said and "没有心跳文件" in said, said


def test_status_does_not_alarm_a_healthy_run(tmp_path: Path, monkeypatch) -> None:
    """心跳新鲜 → 不告警（哪怕还没判决 —— 刚起的前几分钟就是这个样子）。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 已跑 1.0 分钟 | 回合 2")
    assert "★告警" not in wd.status_report("042")


def test_status_does_not_alarm_a_finished_run(tmp_path: Path, monkeypatch) -> None:
    """收工后心跳停止是**正常**的：有判决 / log 里有 result → 都不告警。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    old = wd.STALL_SECONDS + 60
    log = diag / "wb-042.jsonl"                     # 情形 1：有判决文件
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 已跑 44.0 分钟 | 回合 90")
    wd.verdict_file_for(log).write_text("判决：正常收工（工人退出码 0）\n", encoding="utf-8")
    _ageing(log, wd.heartbeat_file_for(log), seconds=old)
    assert "★告警" not in wd.status_report("042"), "有判决还告警 = 把收工当事故"
    log2 = diag / "wb-043.jsonl"                    # 情形 2：log 里已有 result 事件
    log2.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    wd.write_heartbeat(log2, "[心跳] 已跑 44.0 分钟 | 回合 90")
    _ageing(log2, wd.heartbeat_file_for(log2), seconds=old)
    assert "★告警" not in wd.status_report("043"), "有 result 还告警 = 把收工当事故"


def test_status_heartbeat_prefers_the_newest_round(tmp_path: Path, monkeypatch) -> None:
    """续跑时 [心跳] 该显示第 2 轮那份 —— 第 1 轮那份早就停了，别把在跑读成停摆。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 第 1 轮 | 已跑 44.0 分钟")
    _ageing(wd.heartbeat_file_for(log), seconds=600)
    r2 = diag / "wb-042.r2.jsonl"
    r2.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(r2, "[心跳] 第 2 轮 | 已跑 1.0 分钟")
    said = wd.status_report("042")
    assert "第 2 轮" in said and "第 1 轮" not in said, said


# -------------------------------------------------- 假警报 → 有证据的判断（卡 093 · T-G187）
#
# 主控今天亲历：worker 刚起不到一个心跳周期（心跳每 120s 才写一行），而 `--status` 只凭
# 「心跳文件在不在」就喊「派活进程多半已被杀」—— 而工人活得好好的、日志还在长。
# 一个会喊狼来了的状态器会让人误判、甚至**误重派**（撞上正在跑的活）。下面三条钉住：
# ① 刚起必须说"正常"、不许告警；② "心跳真断了"仍然必须告得出来；③ 判据要念证据（时间/进程）。


def test_status_says_just_started_not_dead(tmp_path: Path, monkeypatch) -> None:
    """★ 核心：刚起（有 log、mtime 是刚刚、没有心跳文件、没有判决）→ 说"刚起/正常"，不告警。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")   # mtime = 现在
    said = wd.status_report("042")
    assert "刚起" in said and "正常" in said, said
    assert "★告警" not in said, f"刚起不是事故：{said}"
    assert "多半已被杀" not in said, f"无证据的措辞不许再出现：{said}"


def test_status_still_alarms_when_the_heartbeat_really_died(
        tmp_path: Path, monkeypatch) -> None:
    """★ 不许把告警删掉了事：心跳陈旧 **且** 日志也不再长 → 这一态仍必须告警，并念出判据。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "codebuddy_worker_pids", lambda: [])   # 桩：没有真 worker 也要能跑
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 已跑 3.0 分钟 | 回合 5")
    _ageing(log, wd.heartbeat_file_for(log), seconds=wd.STALL_SECONDS + 60)
    said = wd.status_report("042")
    assert "★告警" in said and "没人盯了" in said, said
    assert "日志最后写" in said and "与看门狗底线同一口径" in said, said   # 判据要念出来
    assert "多半已被杀" not in said, f"改成了有证据的陈述，旧措辞应消失：{said}"


def test_status_alarm_names_the_live_worker_when_the_command_line_finds_it(
        tmp_path: Path, monkeypatch) -> None:
    """进程判据按命令行查：查到**本卡** worker（命令行含 brief-<卡>.md）→ 别急着重派。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "codebuddy_worker_pids",
                        lambda: [(34168, "node.exe ... -p 读 gates/diag/brief-042.md ... -y")])
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    wd.write_heartbeat(log, "[心跳] 已跑 3.0 分钟 | 回合 5")
    _ageing(log, wd.heartbeat_file_for(log), seconds=wd.STALL_SECONDS + 60)
    said = wd.status_report("042")
    assert "★告警" in said and "本卡" in said and "34168" in said, said


def test_status_says_detach_has_no_push_channel_without_a_verdict(
        tmp_path: Path, monkeypatch) -> None:
    """★ 没判决时明说 `--detach` 没有回推通道 + 建议轮询间隔（今天真发生过：收工了没人知）。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    said = wd.status_report("042")
    assert "没有回推通道" in said and "轮询" in said and "--card 042 --status" in said, said


def test_heartbeat_is_written_to_a_file_with_a_timestamp(tmp_path: Path) -> None:
    """心跳落盘：过夜跑时"它最后一次动是什么时候"必须能一眼查到。"""
    log = tmp_path / "wb-002.jsonl"
    wd.write_heartbeat(log, "[心跳] 已跑 1.0 分钟 | 回合 3")
    body = wd.heartbeat_file_for(log).read_text(encoding="utf-8")
    assert "[心跳] 已跑 1.0 分钟" in body and body[:4].isdigit()


def test_verdict_is_written_when_the_run_finishes(sandbox: Path, monkeypatch, capsys) -> None:
    """判决落盘：新窗口（或过夜之后的我）先读这个文件，别的都不用猜。"""
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    verdict = sandbox / "gates" / "diag" / "wb-001.verdict.txt"
    body = verdict.read_text(encoding="utf-8")
    assert "card=001" in body and "正常收工" in body and "sid-test" in body
    capsys.readouterr()


def test_missing_spec_is_a_clean_error_not_a_crash(monkeypatch, capsys) -> None:
    """`--spec` 改成手动校验（因为 --status 不需要它）：漏了要给一句人话 + 退 2。"""
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--execute"])
    assert wd.main() == 2
    assert "--spec" in capsys.readouterr().err


def test_timeout_default_covers_a_long_card() -> None:
    """默认超时够长（卡 002 用了 44 分钟）；★ 而且超时**不是失败** —— 它会掐掉再续跑。"""
    assert wd.DEFAULT_TIMEOUT >= 7200


# ============================================ 看门狗误杀正常的长工具调用（T-G94）
#
# 真机撞到的（不是猜的）：看门狗原来按「日志静默 ≥ 480 秒」判卡死，可是一次工具调用**本来就会
# 静默很久** —— 主树全量 `run_gates.py` 约 4 分钟、冷缓存 worktree 里 `ui_flow` 十几分钟。
# 于是工人只要在卡里跑一次重门禁，就会被自己的看门狗掐掉，理由还写着「卡死」、报告里
# **没有**它当时在跑什么。修法两件：① 识别「在飞」的工具调用（静默是预期）；② 按实测耗时自适应。


def _iso(offset: float) -> str:
    """以"现在"为基准造一个 ISO-8601 UTC 时间戳（`offset` 秒前 = 负值）。"""
    stamp = datetime.now(timezone.utc) + timedelta(seconds=offset)
    return stamp.isoformat().replace("+00:00", "Z")


def _tool_use_event(name: str, *, tid: str, ago: float, inp: dict | None = None) -> str:
    """一条 `assistant`/`tool_use` 事件（带 `__timestamp` —— 主控第一次就读错过这键）。"""
    payload = {"command": "python -X utf8 scripts/run_gates.py"} if inp is None else inp
    return json.dumps({
        "__timestamp": _iso(-ago),
        "type": "assistant",
        "message": {"id": f"m-{tid}", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": payload}]},
    }, ensure_ascii=False)


def _tool_result_event(*, tid: str, ago: float) -> str:
    """一条 `user`/`tool_result` 事件（与 `tool_use` 靠 `id` ↔ `tool_use_id` 配对）。"""
    return json.dumps({
        "__timestamp": _iso(-ago),
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "done"}]},
    }, ensure_ascii=False)


def test_inflight_tool_call_is_not_a_stall() -> None:
    """★ 有工具在飞 + 静默 600 秒 → **健康**（旧写法在这里判卡死 —— 这正是误杀的那条路）。"""
    lines = [_tool_use_event("Bash", tid="t1", ago=610)]        # 610 秒前发起，还没回话
    got = wd.inflight_tool(lines)
    assert got is not None and "Bash" in got[0] and 600 <= got[1] <= 720, got
    assert wd.watchdog_verdict(silent_seconds=600, signatures=["Bash|x"], lines=lines) == ""
    # 老口径（不看 lines）在同一现场判卡死 —— 对照就在这里
    assert "卡死" in wd.watchdog_verdict(silent_seconds=600, signatures=["Bash|x"])


def test_silence_without_any_inflight_call_is_still_a_stall() -> None:
    """★ 证明阈值不是被一味放宽：**没有**在飞的调用时，静默 600 秒仍然卡死。"""
    lines = [_tool_use_event("Bash", tid="t1", ago=900),
             _tool_result_event(tid="t1", ago=800)]              # 已经回话了 → 没有在飞的
    assert wd.inflight_tool(lines) is None
    assert "卡死" in wd.watchdog_verdict(silent_seconds=600, signatures=["Bash|x"], lines=lines)


def test_stub_missing_fields_is_caught_not_silently_skipped() -> None:
    """★★ 卡 164（T-G264 / INV-36）：桩缺 `id` + `__timestamp` ⇒ 判据必须**红**，
    不是\"悄悄跳过让断言恒真\"。

    现场：`_epoch` 保守分支（缺字段 → None）+ `inflight_tool`/`tool_durations` 的
    `if stamp is None: continue` 会跳过残桩 —— 生产里对（半截 log 不许炸），但测试里
    它让断言恒真（桩什么都没喂进去 ⇒ 阈值 == 底线 ⇒ \"阈值没被抬\"绿了）。
    `tool_use_missing_fields` 让测试自检桩完整性：缺字段时非空、完整时空。
    """
    # 残桩：缺 id + 缺 __timestamp
    broken = [json.dumps({"type": "assistant", "message": {"id": "m-x", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "x"}}]}})]
    assert wd.inflight_tool(broken) is None, "缺字段的桩不许假装有在飞的调用"
    missing = wd.tool_use_missing_fields(broken)
    assert missing and "id" in missing[0] and "__timestamp" in missing[0], missing
    # 对照：完整桩 ⇒ missing_fields 空（测试自检会绿）
    full = [_tool_use_event("Bash", tid="t1", ago=10)]
    assert wd.tool_use_missing_fields(full) == []
    assert wd.inflight_tool(full) is not None


def test_threshold_adapts_to_the_longest_completed_call() -> None:
    """★ 跑过一次 300 秒的调用 → 阈值抬到 750 秒（= 2.5 × 最长）：静默 700 健康、800 卡死。

    取**最长**而不是平均、乘 2.5 是留余量 —— 口径是**宁可晚掐、不要误杀**。
    """
    lines = [_tool_use_event("Bash", tid="t1", ago=1000),
             _tool_result_event(tid="t1", ago=700)]              # 一次 300 秒的已完成调用
    assert abs(wd.tool_durations(lines)[0] - 300) < 5
    assert wd.watchdog_verdict(silent_seconds=700, signatures=[], lines=lines) == ""
    killed = wd.watchdog_verdict(silent_seconds=800, signatures=[], lines=lines)
    assert "卡死" in killed and "12.5 分钟" in killed and "5.0 分钟" in killed, killed


def test_inflight_tool_pairs_use_with_result() -> None:
    """配对判据：`tool_use` 有配对 → 不在飞；多一个没配对 → 认出来（取跑得最久的那次）。"""
    paired = [_tool_use_event("Read", tid="a", ago=30),
              _tool_result_event(tid="a", ago=10)]
    assert wd.inflight_tool(paired) is None
    missing = [_tool_use_event("Read", tid="a", ago=30),
               _tool_result_event(tid="a", ago=10),
               _tool_use_event("Grep", tid="b", ago=5)]
    got = wd.inflight_tool(missing)
    assert got is not None and "Grep" in got[0] and got[1] < 60, got


def test_tool_durations_and_inflight_survive_missing_timestamps() -> None:
    """★ 半截 log / 对方改格式 → 缺 `__timestamp` 时**不许炸**，也不许拿它去放大阈值。

    退回保守行为：耗时算不出来就当没有（阈值不放宽），这样宁可早掐一次，不会因为读不到
    时间戳就把卡死判成健康。
    """
    assert wd.tool_durations([]) == []
    assert wd.tool_durations(["不是 JSON 的一行", "{}", ""]) == []      # 不许抛异常
    bare = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x", "name": "Read", "input": {}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}})]
    assert wd.tool_durations(bare) == []                                # 没时间戳 → 空表
    assert wd.inflight_tool(bare) is None                               # 也不算"在飞"
    assert "卡死" in wd.watchdog_verdict(silent_seconds=600, signatures=[], lines=bare)


def test_stall_report_names_the_inflight_tool() -> None:
    """★ 报告必须带现场：它当时在跑什么 / 跑了多久 / 历史上最长一次多久 / 这一次用的阈值。"""
    live = [_tool_use_event("Bash", tid="t1", ago=2000)]                # 在飞、已跑 2000 秒
    said = wd.watchdog_verdict(silent_seconds=wd.BUSY_STALL_SECONDS + 10, signatures=[],
                               lines=live)
    assert "卡死" in said and "Bash" in said, said
    assert "在跑" in said and "30.0 分钟" in said and "阈值" in said
    idle = [_tool_use_event("Bash", tid="s", ago=900),
            _tool_result_event(tid="s", ago=600)]                       # 没有在飞的
    quiet = wd.watchdog_verdict(silent_seconds=800, signatures=[], lines=idle)
    assert "没有在飞的调用" in quiet and "历史最长一次调用 5.0 分钟" in quiet, quiet


def test_zero_output_is_starting_not_stalled_but_the_grace_expires() -> None:
    """★★ T-G260b **启动宽限**的反例钉子（现场：2026-10-03 全量门禁连红两趟，都是这一族）。

    真现场指纹（逐字）：`判决：卡死：0.0 分钟没有新事件（这一次的阈值 0.0 分钟；
    没有在飞的调用；历史最长一次调用：没有记录）` —— ★「**没有记录**」= 快照是空的 =
    判据**什么都还没看见**。它判的不是"静默"，是"还没开始"：
    `Popen` 到第一行落地之间有真实延迟（冷启动 + xdist 满载时 >2 秒），
    而静默计时从进程起来就开始了。

    三条一起钉住（★ 判据**不许被放宽**，只许改判对象）：
      ① 零输出 + 静默 2 秒（阈值也是 2 秒）⇒ **不许**判卡死；
      ② 零输出 + 静默过了宽限 ⇒ **照判卡死**，且报告**点名**是
         "一行输出都还没有"（不许含糊成"没有在飞的调用"）；
      ③ 一旦有第一行 ⇒ 宽限**立刻失效**，口径回到老样子
         （有输出但没在飞 + 静默 3 秒 > 2 秒 ⇒ 卡死）。
    """
    # ① 还在启动：零输出，静默 2 秒，压缩阈值 2 秒 ⇒ 不许掐
    assert wd.watchdog_verdict(silent_seconds=2, signatures=[], stall_seconds=2,
                               lines=[]) == ""
    # ② 宽限过了还零输出 ⇒ 照掐，且必须点名"零输出"（与"没有在飞的调用"区分开）
    said = wd.watchdog_verdict(silent_seconds=wd.STARTUP_GRACE_SECONDS + 1, signatures=[],
                               stall_seconds=2, lines=[])
    assert "卡死" in said, said
    assert "一行输出都还没有" in said, said
    assert "没有在飞的调用" not in said, said
    # ③ 有第一行之后，宽限不再生效：静默 3 秒 > 阈值 2 秒 ⇒ 卡死（老口径，一个字没改）
    after_first_line = ['{"type": "system", "subtype": "init"}']
    assert "卡死" in wd.watchdog_verdict(silent_seconds=3, signatures=[], stall_seconds=2,
                                         lines=after_first_line)
    # ★ 且**不给 lines**（老调用方）时宽限一个字都不许插进来：静默 2 秒 = 阈值 ⇒ 照掐
    assert "卡死" in wd.watchdog_verdict(silent_seconds=2, signatures=[], stall_seconds=2)


def test_heartbeat_can_mention_the_inflight_tool_without_dropping_fields() -> None:
    """心跳**可以加**「在跑：<工具>」（有帮助），但现有字段一个都不许删。"""
    line = wd.heartbeat_line(elapsed=610, turns=90, tool_calls=111, files=21, silent_seconds=3,
                             inflight="Bash(command=run_gates.py)")
    assert "在跑 Bash" in line
    for needle in ("已跑 10.2 分钟", "回合 90", "工具 111 次", "碰过文件 21 个", "静默 3 秒"):
        assert needle in line, line


# ====================================== 交接摘要：收工时落一份 1~2 KB 的摘要（T-G95 = 外包卡 006）
#
# 为什么有它（主控写的背景）：主控每收一张卡，最贵的开销不是复核（`wb_review.py` 5 秒），而是
# **读工人那一轮的原始事件流**（卡 005 那轮是 264 行 / 316 KB），而他要的东西（六项回报 / 判决 /
# 计数）只压在末尾。所以派活器**自己**在收工时落一份摘要 —— 主控只读它，永远不必再碰原始 jsonl。
# ★ 口径复用现成的：回合走 `turns_seen()`、工具签名走 `tool_signatures()`、log 摘要走
# `parse_events()` —— 不写第二份。


def _report_lines(*, with_result: bool = True) -> list[str]:
    """造一段像真工人的事件流（含一条 `tool_use` 与可选的 `result`）。"""
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "m", "session_id": "sid-r1"},
                   ensure_ascii=False),
        json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": "tools/wb_dispatch.py"}}]}}, ensure_ascii=False),
    ]
    if with_result:
        lines.append(json.dumps({"type": "result", "subtype": "success",
                                 "result": "卡号：006\n改了什么文件：\n- tools/wb_dispatch.py"},
                                ensure_ascii=False))
    return lines


def test_write_report_carries_the_workers_words_verbatim(tmp_path: Path) -> None:
    """★ 摘要必须把工人的回话**原样**贴进来（主控读的就是它），且中文**不许**被转义成 `\\uXXXX`。"""
    log = tmp_path / "wb-006.jsonl"
    lines = _report_lines()
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wd.write_report(log, card="006", code=0, reason="", scene="", sid="sid-r1", attempts=1,
                    lines=lines, started_at=time.time() - 60)
    report = wd.report_file_for(log)
    assert report.name == "wb-006.report.md", "摘要落在 wb-<卡>.report.md"
    body = report.read_text(encoding="utf-8")
    assert "# 卡 006 的交接摘要" in body
    assert "退出码：0" in body and "正常收工" in body
    assert "sid-r1" in body and "--resume sid-r1" in body
    assert "用时" in body and "回合" in body
    assert "卡号：006" in body and "tools/wb_dispatch.py" in body, "回话原文没被原样贴上"
    assert "1. Read" in body, "最后 10 次工具调用没列出来"
    assert "\\u" not in body, "中文被转义了 —— 主控读不懂"


def test_write_report_says_so_when_there_is_no_result_event(tmp_path: Path) -> None:
    """被打断 / 被杀 / 还在跑 → 整段 log 里没有 `result` 事件：摘要照样落盘，并**写明这一点**。"""
    log = tmp_path / "wb-006.jsonl"
    lines = _report_lines(with_result=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wd.write_report(log, card="006", code=6, reason="卡死：30.0 分钟没有新事件", scene="",
                    sid="sid-r1", attempts=1, lines=lines, started_at=time.time() - 30)
    body = wd.report_file_for(log).read_text(encoding="utf-8")
    assert "没有 result 事件" in body and "被打断" in body
    assert "卡死" in body


def test_write_report_survives_a_truncated_or_empty_stream(tmp_path: Path) -> None:
    """半截 log / 缺字段 / 空事件流 / 没给开始时间 → 一律退回「没有数据」，**绝不抛异常**。

    报告是"事故现场"，它自己炸了就最坏 —— 所以宁可退化成"没有数据"，也不许把主控挡在门外。
    """
    log = tmp_path / "wb-006.jsonl"
    lines = ["不是 JSON 的一行", "{}", json.dumps({"type": "assistant"})]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wd.write_report(log, card="006", code=6, reason="超时：7200 秒到了", scene="", sid="",
                    attempts=2, lines=lines, started_at=None)
    body = wd.report_file_for(log).read_text(encoding="utf-8")
    assert "没有 result 事件" in body and "超时" in body
    assert wd.write_report(log, card="006", code=0, reason="", scene="", sid="",
                           attempts=1, lines=[], started_at=None).exists()


def test_every_exit_path_writes_a_report(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 每一条退出路径都要落一份摘要：正常收工 / 被掐 / 超时 / 撞上限 —— 一个都不能少。"""
    cases = {
        "正常收工": "",
        "空转：最近 12 次工具调用里同一件事出现了 9 次": "空转",
        "超时：7200 秒到了（`--timeout`）": "超时",
        ("没做完：回合数 240 撞到上限 240"
         "（`--max-turns` 到了 CLI 会自己停，退出码仍是 0）"): "没做完",
    }
    for reason, needle in cases.items():
        monkeypatch.setattr(wd, "run_worker", _fake_runner([], reason=reason))
        monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "007", "--spec", "spec.md",
                                          "--execute", "--retry", "0", "--force"])
        wd.main()
        capsys.readouterr()
        report = sandbox / "gates" / "diag" / "wb-007.report.md"
        assert report.exists(), f"「{needle or '正常收工'}」这条路径没落摘要"
        assert needle in report.read_text(encoding="utf-8"), needle


def test_a_retry_round_gets_its_own_report_not_an_overwrite(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 重试的每一轮各落一份摘要：`wb-<卡>.r2.report.md`（**不覆写**第 1 轮 —— 证据不互相盖）。"""
    calls: list[list[str]] = []
    outcomes = [("卡死：30.0 分钟没有新事件 → 已掐", "    做 Read(a.py)"), ("", "")]

    def runner(cmd, log, errlog, **kwargs):            # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, outcomes[len(calls) - 1][0], outcomes[len(calls) - 1][1], "sid-abc"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "007", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    capsys.readouterr()
    first = sandbox / "gates" / "diag" / "wb-007.report.md"
    second = sandbox / "gates" / "diag" / "wb-007.r2.report.md"
    assert first.exists() and second.exists(), "重试的每一轮都要落一份摘要"
    assert "卡死" in first.read_text(encoding="utf-8")
    assert "正常收工" in second.read_text(encoding="utf-8")


def test_status_points_at_the_report_when_there_is_one(
        tmp_path: Path, monkeypatch, capsys) -> None:
    """★ `--status` 在摘要存在时多打一行 `[摘要]`（主控**先看它**，别再去翻 log）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    (diag / "wb-009.jsonl").write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    (diag / "wb-009.report.md").write_text("# 卡 009 的交接摘要\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "009", "--status"])
    assert wd.main() == 0
    assert "[摘要] gates/diag/wb-009.report.md" in capsys.readouterr().out


def test_detached_argv_pins_unbuffered_stdout_exactly_once() -> None:
    """★ 块缓冲那个坑（T-G93 记录在案，主控撞了**三次**）：脱离窗口的子进程必须 `-u`（无缓冲），
    否则 `wb-<卡>.dispatch.log` 会是 **0 字节**、看着像没起来。**恰好一个**，输入里已有的要去重。

    T-G92 的既有事实一条不动：脚本自己在、`--no-preflight` 恰好一个、`--detach` 已去掉、
    以 `--detach-done` 收尾。
    """
    once = wd.detached_argv(["--card", "002", "--spec", "s.md", "--detach", "--execute"])
    assert once[0] == sys.executable
    assert once[1:4] == ["-X", "utf8", "-u"]
    assert once.count("-u") == 1
    twice = wd.detached_argv(["--card", "002", "-u", "--detach"])
    assert twice.count("-u") == 1
    assert str(Path(wd.__file__).resolve()) in once
    assert once.count("--no-preflight") == 1
    assert "--detach" not in once and once[-1] == "--detach-done"


# ================================ 复核 1969b46 挑出的三个缺口（T-G96 = 外包卡 007）
#
# 对抗性复核（`gates/diag/复核-1969b46.md`）挑出、都带复现：
#   ① ★★ 两个**假护栏** —— `run_worker` 里那两行**接线**（`lines=snapshot` 喂看门狗、
#      `inflight=` 喂心跳）单测覆盖 = 0：删掉它们，全套 50 条仍全绿。将来谁改回老样子，
#      CI 全绿而真机上"长调用仍被误杀"的原始病灶**原样复发**。
#   ② 畸形 log（`message` 不是 dict）让 `_tool_use_blocks` 抛 `AttributeError` → 异常**逃出**
#      `run_worker` 的轮询循环 → 看门狗失效、阻塞到工人自退。
#   ③ `2.5 × 历史最长` **无绝对上限**：一次 60 分钟的调用 → 150 分钟才判卡死（漏杀）。
# 另加 §2.4 `kill_tree()` 的 GBK 乱码、§2.5 判决/摘要**按轮落不互相覆写**。


def _stub_timestamped(events: list[dict], sleep_after: float) -> list[str]:
    """桩命令：把 `events` 逐条打上**当前** `__timestamp`（ISO-8601 UTC）再吐出来，然后装死。

    ★ 与既有 `_stub()`（既没 `id` 也没 `__timestamp`、恰好绕开新判据）相对照 —— 这条能真喂到
    「在飞」那条判据上（复核 §2.2 点名的那条缝）。
    """
    payload = json.dumps(events, ensure_ascii=False)
    code = "\n".join([
        "import json, time",
        "from datetime import datetime, timezone",
        f"events = json.loads({payload!r})",
        "for ev in events:",
        "    ev['__timestamp'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')",
        "    print(json.dumps(ev, ensure_ascii=False), flush=True)",
        f"time.sleep({sleep_after})",
        "",
    ])
    return [sys.executable, "-X", "utf8", "-c", code]


def test_runner_does_not_kill_a_worker_with_a_timestamped_inflight_call(tmp_path: Path) -> None:
    """★★ 缺口 ① —— **接线①**：桩吐**带 `__timestamp` 的 `tool_use`** + 静默超过 `--stall-seconds`
    → **不许被掐**（认得出"在飞"，静默是预期的）；心跳里也要出现「在跑 Bash」（**接线②**）。

    ★ 验收硬标准（§2.1）：删 `run_worker` 里的 `lines=snapshot` → 本条**红**（判成卡死）；
    删 `inflight=` → 心跳里没有「在跑」→ 本条**红**。
    """
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    beats: list[str] = []
    stub = _stub_timestamped([{"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash",
         "input": {"command": "python -X utf8 scripts/run_gates.py"}}]}}], sleep_after=30)
    started = time.monotonic()
    _, reason, _, _sid = wd.run_worker(stub, log, err, timeout=6, max_turns=150,
                                       watchdog=True, heartbeat_seconds=1, stall_seconds=2,
                                       poll_seconds=0.2, printer=beats.append)
    elapsed = time.monotonic() - started
    assert "卡死" not in reason, reason
    assert "超时" in reason, reason
    assert elapsed < 20, f"应当跑到 --timeout 6 才停，实际 {elapsed:.1f} 秒"
    assert any("在跑" in b and "Bash" in b for b in beats), f"心跳没带「在跑」：{beats}"


def test_runner_kills_a_quiet_worker_when_nothing_is_inflight(tmp_path: Path) -> None:
    """★★ 缺口 ① 的对偶 —— **已配对完成、无在飞** + 静默超过阈值 → **必须被掐**。

    证明阈值不是被一味放宽：没有在飞的调用时，静默到 `--stall-seconds` 照样判卡死。
    """
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    stub = _stub_timestamped([
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
    ], sleep_after=60)
    started = time.monotonic()
    _, reason, _, _sid = wd.run_worker(stub, log, err, timeout=120, max_turns=150,
                                       watchdog=True, heartbeat_seconds=0, stall_seconds=2,
                                       poll_seconds=0.2)
    elapsed = time.monotonic() - started
    assert "卡死" in reason, reason
    assert elapsed < 30, f"装死 60 秒，掐得太慢了：{elapsed:.1f} 秒"


# 复核 §3.2 的 10 种畸形形状（两种 `message` 不是 dict 的会把判据炸掉）。
_MALFORMED: list[tuple[str, list[str], bool]] = [
    # (名字, 事件行, 期望 inflight 是不是 None)
    ("half", [json.dumps({"__timestamp": _iso(0), "type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 5000"}}]}},
        ensure_ascii=False)], False),
    ("badjson", ["这行不是 JSON", "", "[]"], True),
    ("nostamp", [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}})], True),
    ("cnotlist", [json.dumps({"__timestamp": _iso(0), "type": "assistant",
                              "message": {"content": "不是列表"}}, ensure_ascii=False)], True),
    ("itemstr", [json.dumps({"__timestamp": _iso(0), "type": "assistant",
                             "message": {"content": ["不是 dict"]}}, ensure_ascii=False)], True),
    ("stampnum", [json.dumps({"__timestamp": 12345, "type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}})], True),
    ("noid", [json.dumps({"__timestamp": _iso(0), "type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {}}]}})], False),
    ("inputstr", [json.dumps({"__timestamp": _iso(0), "type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": "不是 dict"}]}},
        ensure_ascii=False)], False),
    ("msgstr", [json.dumps({"__timestamp": _iso(0), "type": "assistant",
                            "message": "我不是 dict"}, ensure_ascii=False)], True),
    ("msgnum", [json.dumps({"__timestamp": _iso(0), "type": "assistant", "message": 7})], True),
]


@pytest.mark.parametrize("name,lines,expect_none", _MALFORMED,
                         ids=[shape[0] for shape in _MALFORMED])
def test_malformed_logs_never_break_the_criteria(name: str, lines: list[str],
                                                 expect_none: bool) -> None:
    """★ 缺口 ② 第一层：10 种畸形形状逐条 —— 判据**不抛异常**、退回保守行为。

    两种 `message` 不是 dict（`msgstr` / `msgnum`）在复核里会抛 `AttributeError`；现在类型判断
    把 `message` 不是 dict 当没有 `content`。既有的守卫（`content` 不是 list / `item` 不是 dict /
    `input` 不是 dict / 缺 `__timestamp`）保持。
    """
    got = wd.inflight_tool(lines)
    assert (got is None) == expect_none, f"{name}: inflight={got}"
    assert wd.tool_durations(lines) == [], f"{name}: 耗时表应当退回空"
    said = wd.watchdog_verdict(silent_seconds=600, signatures=[], lines=lines)
    assert isinstance(said, str), name          # 不抛异常；具体判什么由场景决定


@pytest.mark.parametrize("shape", ["msgstr", "msgnum"])
def test_runner_survives_a_malformed_log_in_the_loop(tmp_path: Path, shape: str) -> None:
    """★ 缺口 ② 经 `run_worker` 的**循环路径**：畸形事件既不许炸看门狗、也不许炸心跳。

    心跳那条路会调用 `tool_signatures()` / `wb_status.parse_events()`（它们也会在 `message`
    不是 dict 时抛）—— 第二层兜底把它们一起接住，退回保守口径继续盯。
    """
    payload = {n: ln for n, ln, _ in _MALFORMED}[shape][0]
    code = "\n".join(["import time", f"print({payload!r}, flush=True)", "time.sleep(60)", ""])
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    _, reason, _, _sid = wd.run_worker([sys.executable, "-X", "utf8", "-c", code], log, err,
                                       timeout=120, max_turns=150, watchdog=True,
                                       heartbeat_seconds=1, stall_seconds=2, poll_seconds=0.2)
    assert "卡死" in reason, reason               # 畸形事件没让看门狗失效


def test_runner_falls_back_when_a_criterion_raises(tmp_path: Path, monkeypatch) -> None:
    """★ 缺口 ② 第二层（更重要）：**判据自己抛异常时不许让看门狗失效**。

    退到"没有在飞 / 没有耗时数据"的保守口径继续盯，并把这次异常**如实记进判决**（不静默吞）。
    """
    def boom(*args, **kwargs):                    # noqa: ANN002, ANN003, ANN202
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(wd, "inflight_tool", boom)
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    stub = _stub_timestamped([{"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]}}],
        sleep_after=60)
    _, reason, _, _sid = wd.run_worker(stub, log, err, timeout=120, max_turns=150,
                                       watchdog=True, heartbeat_seconds=0, stall_seconds=2,
                                       poll_seconds=0.2)
    assert "卡死" in reason, reason
    assert "退回保守口径" in reason, reason       # 异常被如实记下，不是静默吞掉


def test_stall_threshold_is_capped_at_one_hour() -> None:
    """★ 缺口 ③：`2.5 × 历史最长` **封顶** `ADAPTIVE_MAX_SECONDS`（3600），不再无上界。

    边界：`BUSY_STALL_SECONDS = 1800` 仍生效（封顶 3600 > 1800，别把在飞那条压下去）；
    没有历史长调用时老口径 **480 秒一字节不变**。
    """
    assert wd.ADAPTIVE_MAX_SECONDS == 3600
    base = {"stall_seconds": wd.STALL_SECONDS}
    assert wd.stall_threshold_seconds(inflight=None, durations=[], **base) == 480
    assert wd.stall_threshold_seconds(inflight=("Bash(x)", 5.0), durations=[], **base) == 1800
    assert wd.stall_threshold_seconds(inflight=None, durations=[240.0], **base) == 600
    capped = wd.stall_threshold_seconds(inflight=None, durations=[3600.0], **base)
    assert capped == 3600                              # 不是 9000
    assert wd.stall_threshold_seconds(inflight=("Bash(x)", 5.0),
                                      durations=[3600.0], **base) == 3600


def test_threshold_decays_once_a_long_call_falls_out_of_the_window() -> None:
    """★ T-G128（裁定 V2）：阈值只看最近 `REPEAT_WINDOW`(12) 次**已完成**调用里的最长那一次。

    一次 600 秒的长调用**掉出窗口**（其后又完成 12 次短调用）→ 阈值必须回落到
    480 底线，而不是永远按 2.5 × 600 = 1500 算（「一轮内不衰减」的漏杀，规矩 §15）；
    长调用还在窗口内时照样抬得起来（自适应没有被整个删掉）。
    ★ 既有口径一字不动：`ADAPTIVE_MAX_SECONDS`=3600 封顶、在飞抬到 1800、轮次边界照旧。
    """
    def _call(tid: str, *, use_ago: float, result_ago: float) -> list[str]:
        return [_tool_use_event("Bash", tid=tid, ago=use_ago),
                _tool_result_event(tid=tid, ago=result_ago)]

    # 1 条 600s 长调用 + 12 条 ~1s 短调用（共 13 次已完成 —— 长调用刚好掉出最近 12 次）
    lines = _call("long", use_ago=660, result_ago=60)
    for i in range(12):
        lines += _call(f"s{i}", use_ago=4 - 0.01 * i, result_ago=3 - 0.01 * i)
    durations = wd.tool_durations(lines)
    assert len(durations) == 13 and max(durations) >= 599, durations
    threshold = wd.stall_threshold_seconds(stall_seconds=wd.STALL_SECONDS, inflight=None,
                                           durations=durations)
    assert threshold == float(wd.STALL_SECONDS), threshold    # 旧口径在这里 = 1500

    # 对照：长调用还在窗口内（最近 12 次 = 11 短 + 1 长）→ 照样抬到 2.5 × 600 = 1500
    lines_recent = [_tool_use_event("Bash", tid="s", ago=4),
                    _tool_result_event(tid="s", ago=3)] * 11
    lines_recent += _call("long", use_ago=660, result_ago=60)
    durations_recent = wd.tool_durations(lines_recent)
    assert len(durations_recent) == 12 and max(durations_recent) >= 599, durations_recent
    recent = wd.stall_threshold_seconds(stall_seconds=wd.STALL_SECONDS, inflight=None,
                                        durations=durations_recent)
    assert recent == pytest.approx(wd.TOOL_DURATION_FACTOR * 600), recent  # 实测 ≈600.0001s


@pytest.mark.skipif(os.name != "nt", reason="taskkill 是 Windows 的")
def test_kill_tree_decodes_with_the_system_locale(monkeypatch) -> None:
    """★ §2.4：`kill_tree()` 读 `taskkill` 输出改用**系统区域编码**（这台机器 cp936）+ replace。

    ★ 为什么是 `locale.getencoding()` 而不是 `getpreferredencoding(False)`：本仓一律
    `python -X utf8`，后者在 UTF-8 模式下返回 `utf-8`（等于没改）；前者仍回 **cp936**（实测）。
    """
    seen: dict = {}

    def fake_run(cmd, **kwargs):                  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return _Done(stdout="成功: 已终止 PID 1 (属于 PID 2)的进程。")

    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    said = wd.kill_tree(1)
    assert "成功" in said
    assert seen["encoding"] == locale.getencoding()
    assert seen["encoding"] != "utf-8", "cp936 机器上按 utf-8 解就是乱码，这条防的是回退"
    assert seen["errors"] == "replace"


def test_retry_round_verdict_does_not_overwrite_the_first(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ §2.5：第 2 轮的判决**不覆写**第 1 轮的 —— 每轮各自留痕（第 1 轮断了才查得出）。"""
    calls: list[list[str]] = []
    outcomes = [("卡死：30.0 分钟没有新事件 → 已掐", "    做 Read(a.py)"), ("", "")]

    def runner(cmd, log, errlog, **kwargs):        # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, outcomes[len(calls) - 1][0], outcomes[len(calls) - 1][1], "sid-abc"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "007", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    capsys.readouterr()
    first = sandbox / "gates" / "diag" / "wb-007.verdict.txt"
    second = sandbox / "gates" / "diag" / "wb-007.r2.verdict.txt"
    assert first.exists() and second.exists(), "判决应当按轮落"
    first_body = first.read_text(encoding="utf-8")
    assert "卡死" in first_body and "第=1 次" in first_body
    assert "正常收工" in second.read_text(encoding="utf-8")


def test_verdict_records_the_diagnostics_of_each_round(tmp_path: Path) -> None:
    """★ §2.5：每轮要能查到**断在哪** —— 退出码 / 有没有 `result` 事件 / 末事件类型 / log 行数 /
    stderr 末 5 行（复核那轮断了之后这些**全查不到**）。"""
    log = tmp_path / "wb-007.r2.jsonl"
    errlog = tmp_path / "wb-007.r2.stderr.txt"
    lines = [json.dumps({"type": "assistant", "message": {"content": []}})]
    errlog.write_text("第一行\n第二行\n最后一行的线索\n", encoding="utf-8")
    wd.write_verdict(log, card="007", attempts=2, code=6, reason="卡死：没有新事件",
                     sid="sid-2", lines=lines, errlog=errlog)
    body = wd.verdict_file_for(log).read_text(encoding="utf-8")
    assert wd.verdict_file_for(log).name == "wb-007.r2.verdict.txt"
    for needle in ("退出码=6", "有 result 事件=没有", "末事件类型=assistant", "log 行数=1",
                   "stderr 末 5 行", "最后一行的线索", "第=2 次"):
        assert needle in body, body


def test_status_reads_the_latest_round_verdict(tmp_path: Path, monkeypatch, capsys) -> None:
    """★ §2.5：判决按轮落之后，`--status` 仍要**读到最后一轮**（别改成主控读不到）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    (diag / "wb-007.jsonl").write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    first = diag / "wb-007.verdict.txt"
    second = diag / "wb-007.r2.verdict.txt"
    first.write_text("card=007 第=1 次\n判决：卡死：第 1 轮被打断\n", encoding="utf-8")
    second.write_text("card=007 第=2 次\n判决：正常收工（工人退出码 0）\n", encoding="utf-8")
    now = time.time()
    os.utime(first, (now - 100, now - 100))
    os.utime(second, (now, now))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "007", "--status"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "wb-007.r2.verdict.txt" in out and "正常收工" in out
    assert "第 1 轮被打断" not in out


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows 的")
def test_no_window_flag_is_used_for_own_probes(monkeypatch) -> None:
    """★ §2.6：派活器自己发起的 `subprocess`（前置检查那几条）加 `CREATE_NO_WINDOW`。"""
    assert wd.NO_WINDOW.get("creationflags") == subprocess.CREATE_NO_WINDOW
    seen: dict = {}

    def fake_run(cmd, **kwargs):                  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return _Done(stdout="")

    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    wd.git_dirty()
    assert seen.get("creationflags") == subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW 是 Windows 的")
def test_spawn_detached_keeps_detached_but_adds_no_window(tmp_path: Path, monkeypatch) -> None:
    """★ §2.6：`spawn_detached` 在 Windows 上 `DETACHED_PROCESS | CREATE_NO_WINDOW` **一起**给。

    ★ 边界：`DETACHED_PROCESS`（"活过父进程退出"的命根子）必须在，别为了不弹窗把它弄丢。
    """
    seen: dict = {}

    class _P:
        pid = 42

    def fake_popen(argv, **kwargs):               # noqa: ANN001, ANN202
        seen.update(kwargs)
        return _P()

    monkeypatch.setattr(wd.subprocess, "Popen", fake_popen)
    assert wd.spawn_detached(["python", "x.py"], tmp_path / "d.log") == 42
    flags = seen["creationflags"]
    assert flags & subprocess.DETACHED_PROCESS
    assert flags & subprocess.CREATE_NO_WINDOW


# ====================================== 续跑跨轮耗时：每轮阈值只吃本轮 log（T-G111 = 外包卡 023）
#
# 为什么有这一段（盘点 A11 / 复核-1969b46 §7.2，383-385 行）：`--retry` / `--resume` 续跑时
# 重试循环每轮给 `run_worker` 一份**新的** log（第 2 轮起 `wb-<卡>.r{n}.jsonl`），`run_worker`
# 的 `lines` 只由本轮的 `_pump` 喂 —— 按读代码，旧轮的 389 秒长调用**不该**抬高新轮的
# `stall_threshold_seconds`。但复核明说「没跑，没验证」—— 这一段就是把「经过重试循环」
# 的这一层钉住：纯函数层（两份合成 log）+ 真机层（真起两轮子进程、真走 main() 的重试循环）。


def _stub_literal(events: list[dict], sleep_after: float) -> list[str]:
    """桩命令：把 `events` **按字面**吐出来（`__timestamp` 已是给好的值，**不**改写成现在），
    然后装死。

    ★ 与 `_stub_timestamped()`（全部打成「现在」）相对照 —— 要造「3600 秒前发起、刚完成
    的长调用」这种**跨时间**的现场，两个 `__timestamp` 必须由调用方分别给好。
    ★ 卡 023 §7 的坑：`tool_use` 必须带 `id`、事件必须带 `__timestamp`，否则走「认不出
    在飞 / 算不出耗时」的保守路径 = 假绿（复核 1969b46 §2.2 点名过）。
    """
    payload = json.dumps(events, ensure_ascii=False)
    code = "\n".join([
        "import json, time",
        f"events = json.loads({payload!r})",
        "for ev in events:",
        "    print(json.dumps(ev, ensure_ascii=False), flush=True)",
        f"time.sleep({sleep_after})",
        "",
    ])
    return [sys.executable, "-X", "utf8", "-c", code]


def test_threshold_of_a_new_round_is_not_raised_by_the_previous_log() -> None:
    """★ 纯函数层（§2.1）：两份合成 log —— 第 1 轮一次 3600 秒的**已完成**调用，
    第 2 轮只有秒级短调用 → 第 2 轮的阈值**只反映第 2 轮**（几秒，不是 60 分钟封顶）。
    """
    r1 = [_tool_use_event("Bash", tid="old", ago=3600), _tool_result_event(tid="old", ago=1)]
    assert abs(wd.tool_durations(r1)[0] - 3599) < 5          # 第 1 轮那条长调用真在
    r2 = [_tool_use_event("Read", tid="n1", ago=2), _tool_result_event(tid="n1", ago=1)]
    durations = wd.tool_durations(r2)
    assert durations and max(durations) < 60, durations      # 旧轮的 3600 秒没串进来
    threshold = wd.stall_threshold_seconds(stall_seconds=2, inflight=None, durations=durations)
    assert threshold < 60, threshold                         # ≈ max(2, 2.5×1)
    verdict = wd.watchdog_verdict(silent_seconds=600, signatures=[], stall_seconds=2, lines=r2)
    assert "卡死" in verdict and "这一次的阈值 0." in verdict, verdict
    # 对照（写清「串了会长什么样」，不是断言目标）：把旧轮并进 → 阈值顶到 60 分钟封顶
    merged = wd.stall_threshold_seconds(stall_seconds=2, inflight=None,
                                        durations=wd.tool_durations(r1 + r2))
    assert merged == float(wd.ADAPTIVE_MAX_SECONDS)


def test_retry_round_threshold_eats_only_its_own_log(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★★ 真机层（§2.1 + §2.2）：真起两轮子进程、真走 main() 的重试循环 ——
    第 1 轮塞一条 **3600 秒的已完成调用**（它把**自己这一轮**的阈值抬到 60 分钟封顶，所以
    第 1 轮用 `--timeout 12` 掐 —— 超时同样触发续跑，这是 T-G91 定的「超时不是失败」）
    → 自动续跑第 2 轮 → 第 2 轮只有秒级调用，判决里的「这一次的阈值」必须**只反映
    第 2 轮**（几秒级）；若被旧轮抬到 3600 秒，第 2 轮等不到「卡死」、只能再等一个超时。

    ★ 突变检验的靶子（§2.3）：把 `run_worker` 改坏成「第 2 轮从第 1 轮的 lines 起步」
    → 第 2 轮阈值被旧轮抬到 3600 秒 → 判决是「超时」不是「卡死」→ 本条**红**。
    ★ 压缩阈值如实写（T-G94 先例）：`--timeout 12`、`--stall-seconds 5`、`--poll-seconds 0.5`。

    ★★ 计时 flake 处置（卡 164 第 7 条）：本条真起 `Popen`，在 **4 worker 满载**下曾 flake
    （卡 149 第 3 趟：stub 第一行还没落地，看门狗就开跑 ⇒ 阈值 0.0 ⇒ 判「卡死」不是「超时」）。
    处置 = **给足容差**：`stall 2→5` / `poll 0.2→0.5` / `timeout 6→12`，给 stub 落地窗口。
    ★ **这降低 flake 概率，没根治**——根治要钉串行池（不让它和真 `Popen` 钉子挤一个 worker），
    那是后续卡的事。读数（2026-10-03）：1 worker ×3 + 4 worker ×5 全绿。
    """
    r1_events = [
        {"type": "system", "subtype": "init", "session_id": "sid-tg111"},
        json.loads(_tool_use_event("Bash", tid="old", ago=3600)),
        json.loads(_tool_result_event(tid="old", ago=1)),
    ]
    r2_events = [
        json.loads(_tool_use_event("Read", tid="n1", ago=2)),
        json.loads(_tool_result_event(tid="n1", ago=1)),
    ]
    monkeypatch.setattr(wd, "build_command", lambda *a, **k: _stub_literal(r1_events, 120))
    monkeypatch.setattr(wd, "resume_command", lambda *a, **k: _stub_literal(r2_events, 120))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "023", "--spec", "spec.md",
                                      "--execute", "--retry", "1", "--timeout", "12",
                                      "--stall-seconds", "5", "--poll-seconds", "0.5",
                                      "--heartbeat-seconds", "1"])
    started = time.monotonic()
    assert wd.main() == 6                                    # 第 2 轮被掐 → 退 6
    elapsed = time.monotonic() - started
    assert elapsed < 50, f"两轮合计应 ~20 秒（12 超时 + ~5 卡死），实际 {elapsed:.1f} 秒"
    out = capsys.readouterr().out
    assert "续跑" in out                                     # 真走了自动续跑
    v1 = (sandbox / "gates" / "diag" / "wb-023.verdict.txt").read_text(encoding="utf-8")
    v2 = (sandbox / "gates" / "diag" / "wb-023.r2.verdict.txt").read_text(encoding="utf-8")
    assert "超时" in v1, v1            # 第 1 轮：阈值被自己的长调用抬着 → 只能靠超时掐
    assert "卡死" in v2, v2            # 第 2 轮：阈值很小 → 看门狗真掐（不是超时）
    hit = re.search(r"这一次的阈值 ([\d.]+) 分钟", v2)
    assert hit and float(hit.group(1)) * 60 < 60, v2         # 几秒级，不是 60 分钟


# ================================================ 卡 029（T-G114）：模型白名单硬闸门（§2.4）
#
# 用户 2026-09-26 令：「黑名单锁死吧，就是只有白名单里面的模型，名字，带模型的名字，你才能调用」
# → 默认拒绝：表外模型**拒单**（退出码 2、不起进程、不建 log、不改树）。拒单测试必须是
# **可重复的用例**（卡 §7.5），不许只写「逻辑上会拒」。


def test_model_whitelist_is_locked_and_default_is_the_first_entry() -> None:
    """白名单只有两项、顺序 = 默认优先；DEFAULT_MODEL 取第 1 项（用户 2026-09-26 令）。"""
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")
    assert wd.DEFAULT_MODEL == wd.MODEL_WHITELIST[0] == "deepseek-v4.1-flash"
    assert wd.next_whitelist_model("deepseek-v4.1-flash") == "glm-5.3-flash"
    assert wd.next_whitelist_model("glm-5.3-flash") is None      # 最后一个 → 全挂就停的判据


def test_one_off_model_is_allowed_but_stays_out_of_the_rotation(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """★ 2026-10-02（卡 124 / `T-G222`，**同日晚按用户令撤回**）：**一次性授权 ≠ 改轮换口径**。

    用户 2026-10-02 授权 `glm-5.3`（**不带 flash**）做**一次**外部审查；★ 同日晚用户令
    **「GLM5.3 用完就撤。」** ⇒ 名额已清空（`ONE_OFF_MODELS == ()`），`glm-5.3` 回到**默认拒绝**。
    这条钉子把三件事**钉开**：
      ① 闸门查的是**允许集**（能不能调），轮换只走 `MODEL_WHITELIST`（坏了按什么顺序换）；
      ② **撤销之后**：`glm-5.3` 与任何表外模型**一视同仁**（被拒），而轮换链**一个字没动**；
      ③ **机制还在**（不是被删掉）：往 `ONE_OFF_MODELS` 里填一个名字 ⇒ 闸门放行它、
         而它**仍不进轮换链** —— 将来要再放行谁，填一处即可。
    ★ 反证：若有人图省事把 `glm-5.3` 直接塞进 `MODEL_WHITELIST`，上面那条
    `test_model_whitelist_is_locked_and_default_is_the_first_entry` 与本条的第 ② 段**立刻红**。
    ★ 卡 138：`model_rejected` 现在也读**外部开关文件** → 这条钉子把开关**隔离**掉（指到不存在的
      路径），否则真文件被打开时「撤了就是撤了」这句会跟着环境变，钉不住。
    """
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(tmp_path / "absent.toml"))
    # ① 轮换链**没变**：名单仍两项，末尾仍是 glm-5.3-flash → 停
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")
    assert wd.next_whitelist_model("deepseek-v4.1-flash") == "glm-5.3-flash"
    assert wd.next_whitelist_model("glm-5.3-flash") is None
    # ② ★ 撤了就是撤了：名额空 ⇒ glm-5.3 被拒（与表外模型一视同仁），名单里的两个照放
    assert wd.ONE_OFF_MODELS == (), "用户令：GLM5.3 用完就撤"
    assert wd.model_rejected("glm-5.3") != "", "撤了之后 glm-5.3 必须回到默认拒绝"
    assert wd.model_rejected("glm-5.3-flash") == ""
    assert wd.model_rejected("kimi-k3-1") != ""
    assert "glm-5.3" not in wd.ALLOWED_MODELS
    assert wd.next_whitelist_model("glm-5.3") is None
    # ③ 机制仍在：临时往一次性名单里填一个 ⇒ 闸门放行，且**轮换链仍不动**（用完不该长留）
    #   ★ 卡 166：ALLOWED_MODELS 现在是 PEP 562 __getattr__（自动 = 注册表 codebuddy 段
    #   ∪ ONE_OFF_MODELS），改 ONE_OFF_MODELS 它就跟着变 —— 不再手动 setattr
    #   ALLOWED_MODELS（那会与 __getattr__ 残留交互）。
    monkeypatch.setattr(wd, "ONE_OFF_MODELS", ("glm-5.3",))
    assert wd.model_rejected("glm-5.3") == ""
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")
    assert wd.next_whitelist_model("glm-5.3-flash") is None


def _name_outside_the_effective_allowed_set() -> str:
    """★ 卡 174（T-G274）：**现算**一个「确实表外」的模型名 —— 不再写死某个具体名字。

    病：样本写死（现场是 `kimi-k3-1`）⇒ 用户 2026-10-03 在**仓外**开关文件里把它打开，
    它就不再表外，用例在**一行代码都没改**时自己变红。做法：拿**有效允许集**
    （名单常量 ∪ 开关文件里打开的），在它之外挑一个名字 —— 用户打开哪个，这名字都还在表外。
    """
    allowed = set(wd.effective_allowed_models())
    name = "no-such-model-anywhere"
    suffix = 0
    while name in allowed:
        suffix += 1
        name = f"no-such-model-anywhere-{suffix}"
    assert name not in allowed, "现算的表外样本仍落在允许集里（算法坏了）"
    return name


def test_model_gate_refuses_an_unknown_model_with_zero_side_effects(
        sandbox: Path, tmp_path, monkeypatch, capsys) -> None:
    """★★ 拒单实测（可重复用例）：表外模型 → 退 2、**不起进程**、**不建 log**、**不写判决**。

    ★ 卡 174（T-G274）：两处**自控输入面**，让用例不再依赖机器状态：
      ① 样本**现算**（`_name_outside_the_effective_allowed_set()`）—— 不写死名字，
         用户改仓外开关文件也不会把这个样本变成「表内」；
      ② 开关**读取**打到 tmp 夹具上（空开关文件）—— 沙箱真的封闭，
         不再读真机那份 `infra/pool/model-switches.toml`（它在本仓外、`sandbox` 隔离不到）。
    """
    _point_switches(tmp_path, "", monkeypatch)          # 夹具：空开关 ⇒ 允许集 = 名单常量
    outsider = _name_outside_the_effective_allowed_set()
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--model", outsider, "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "未授权模型，已拒绝派活" in err and outsider in err
    assert "deepseek-v4.1-flash" in err and "glm-5.3-flash" in err, "要列出白名单"
    assert record == [], "一个子进程都不许起"
    assert not (sandbox / "gates" / "diag" / "wb-000.jsonl").exists(), "不许建 log"
    assert not (sandbox / "gates" / "diag" / "wb-000.verdict.txt").exists(), "不许写判决"


def test_switch_on_model_is_dispatched_through_the_gate(
        sandbox: Path, tmp_path, monkeypatch, capsys) -> None:
    """★ 卡 174（T-G274）正向钉子：开关里写 `X = true` ⇒ X **必须真被派出去**（证明开关真的生效）。

    这是上面那条拒单用例的**另一半**：那半钉「表外被拒」，这半钉「开关里开的放行」——
    合起来才说明闸门读的**就是**这个自控的输入面。
    ★ 开关夹具在 tmp 里（沙箱封闭），不读真机那份 `infra/pool/model-switches.toml`。
    """
    opened = "switched-on-third-party-model"
    assert opened not in wd.MODEL_WHITELIST, "样本不能是名单里的（否则证明不了开关在起作用）"
    _point_switches(tmp_path, f'[switch]\n"{opened}" = true\n', monkeypatch)
    assert wd.model_rejected(opened) == "", "开关开了就必须放行"
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000", "--spec", "spec.md",
                                      "--model", opened, "--execute", "--force"])
    assert wd.main() == 0
    capsys.readouterr()
    assert record, "开关开了就要真派出去"
    assert record[0][record[0].index("--model") + 1] == opened, "派出去的正是开关里的那个名字"


def test_switch_missing_or_broken_still_refuses_by_default(
        sandbox: Path, tmp_path, monkeypatch, capsys) -> None:
    """★ 卡 174（T-G274）正向钉子：开关**读不到 / 坏掉** ⇒ 默认拒绝**不变**（黑名单锁死那条令）。

    · **读不到**（夹具文件不存在）⇒ 空开关、不报错 —— 表外照拒（不是「读不到就当全开」）；
    · **坏掉**（值不是布尔）⇒ `SwitchFileError` 响亮失败、退 2、点名 —— **也不放行**。
    两半都要求**零副作用**（一个子进程都不许起）。
    """
    outsider = "switched-off-third-party-model"
    assert outsider not in wd.MODEL_WHITELIST
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))

    monkeypatch.setenv("TF_MODEL_SWITCHES", str(tmp_path / "absent.toml"))   # 读不到
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--model", outsider, "--execute"])
    assert wd.main() == 2
    assert "未授权模型，已拒绝派活" in capsys.readouterr().err, "读不到开关 ≠ 放行"

    _point_switches(tmp_path, f'[switch]\n"{outsider}" = "yes"\n', monkeypatch)   # 坏掉
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--model", outsider, "--execute"])
    assert wd.main() == 2
    broken_err = capsys.readouterr().err
    assert "模型开关文件" in broken_err and outsider in broken_err, "坏文件要点名"
    assert record == [], "拒单必须零副作用（一个子进程都不许起）"


def test_model_gate_applies_to_resume_and_detached_too(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 所有入口都过闸：--resume / --detach 都要带 --model → 一并在 main() 门口拦下。"""
    thrown: list[list[str]] = []
    monkeypatch.setattr(wd, "spawn_detached",
                        lambda argv, log: thrown.append(list(argv)) or 1)
    for extra in (["--resume", "sid-1"], ["--detach", "--execute"]):
        monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                          "--spec", "spec.md", "--model", "hy4-preview", *extra])
        assert wd.main() == 2, extra
        capsys.readouterr()
    assert thrown == [], "--detach 也要先过白名单闸"


def test_model_gate_passes_both_whitelisted_models(sandbox: Path, monkeypatch, capsys) -> None:
    """白名单里的两项都能真派出去，且命令里带的就是那个模型。"""
    for model in wd.MODEL_WHITELIST:
        record: list[list[str]] = []
        monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
        monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                          "--model", model, "--execute", "--force"])
        assert wd.main() == 0
        capsys.readouterr()
        assert "--model" in record[0] and record[0][record[0].index("--model") + 1] == model


# ================================================ 卡 138（T-G236）：外部模型开关文件
#
# 用户要「按一下就 true/false」的开关 ⇒ 开关做**数据**（infra/pool/model-switches.toml），
# 派活器只读、**只做加法**（名单是下限）、**不进 429 轮换链**。
# ★ 坏文件**报错点名**、不静默当空；★ 各钉子都用 `TF_MODEL_SWITCHES` 指到临时文件
#   （**不碰 infra 那份真文件**）。


def _point_switches(tmp_path: Path, body: str, monkeypatch) -> Path:  # noqa: ANN001
    path = tmp_path / "model-switches.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    return path


def test_switch_on_allows_model_but_keeps_it_out_of_the_rotation(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """① 开关开 ⇒ 放行；★ 但仍**不进轮换链**（轮换只走 `MODEL_WHITELIST`）。"""
    _point_switches(tmp_path, '[switch]\n"glm-5.3" = true\n', monkeypatch)
    assert wd.model_rejected("glm-5.3") == ""
    assert wd.next_whitelist_model("glm-5.3-flash") is None      # 开关不开新的轮换格
    assert wd.next_whitelist_model("glm-5.3") is None
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")  # 常量没动


def test_switch_off_still_rejects(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """② 开关关（false）⇒ 被拒。"""
    _point_switches(tmp_path, '[switch]\n"glm-5.3" = false\n', monkeypatch)
    assert wd.model_rejected("glm-5.3") != ""


def test_no_switch_file_behaves_exactly_as_before(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """③ 文件不存在 ⇒ 空、其它行为与今天逐字相同（名单两个照放、表外照拒）。"""
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(tmp_path / "absent.toml"))
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")
    for model in wd.MODEL_WHITELIST:
        assert wd.model_rejected(model) == ""
    assert wd.model_rejected("glm-5.3") != ""
    assert wd.model_rejected("kimi-k2.7") != ""


def test_broken_switch_file_is_named_not_silently_ignored(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """④ 坏文件 ⇒ 报错并点名路径与行号（★ 不是静默当空）。"""
    path = _point_switches(tmp_path, '[switch]\n"glm-5.3" = "yes"\n', monkeypatch)
    with pytest.raises(wd.SwitchFileError) as excinfo:
        wd.model_rejected("glm-5.3")
    message = str(excinfo.value)
    assert str(path) in message and "第 2 行" in message and "glm-5.3" in message, message


def test_broken_switch_file_makes_dispatch_fail_loudly(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """④ 走真入口也一样：坏开关文件 → 退 2、**点名**、**不起进程**（零副作用）。"""
    path = _point_switches(tmp_path, '[switch]\n"glm-5.3" = "yes"\n', monkeypatch)
    spawned: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(spawned))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000", "--model", "glm-5.3"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert str(path) in err and "第 2 行" in err
    assert spawned == [], "坏开关文件也要在起进程之前拦下"


def test_switch_is_purely_additive(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑤ ★ 开关只做加法：写 `kimi-k2.7=true` ⇒ 它被放行；**名单里那两个不因此被关**。"""
    _point_switches(tmp_path, '[switch]\n"kimi-k2.7" = true\n', monkeypatch)
    assert wd.model_rejected("kimi-k2.7") == ""
    for model in wd.MODEL_WHITELIST:
        assert wd.model_rejected(model) == "", "名单是下限，开关不许把它关掉"
    assert wd.ALLOWED_MODELS == wd.MODEL_WHITELIST, "常量一个字没动（开关是加法）"


# ================================================ 卡 167（T-G267）：--effort 透传
#
# ★ 用户 2026-10-03 令：「思考等级为 MAX」—— CLI 支持 --effort 六档，但派活器从前
#   **刻意不传**（两处注释写着「保持默认 High」，2026-09-26 的口径）。本卡加一条透传：
#   给了才传，不给 = 逐字不变。值域以 CLI 2.158.0 的 --help 为准（6 档）。


def test_effort_is_passed_through_when_given(sandbox: Path, monkeypatch, capsys) -> None:
    """① --effort max ⇒ 命令行里真出现 --effort max（build_command 与 dry-run 摘要都有）。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "001", "spec.md", "deepseek-v4.1-flash", effort="max")
    assert cmd[cmd.index("--effort") + 1] == "max", "build_command 要真把 --effort max 塞进去"
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--effort", "max"])
    assert wd.main() == 0
    assert "--effort max" in capsys.readouterr().out, "dry-run 的 [cmd] 摘要里要能看到 --effort max"


def test_effort_is_absent_when_not_given(sandbox: Path, monkeypatch, capsys) -> None:
    """② 不给 --effort ⇒ 命令行里没有 --effort（逐字与今天一致 = CLI 默认 High）。"""
    node, cli = wd.paths()
    cmd = wd.build_command(node, cli, "001", "spec.md", "deepseek-v4.1-flash")
    assert "--effort" not in cmd, "不给 effort ⇒ 命令里不许出现 --effort"
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md"])
    assert wd.main() == 0
    assert "--effort" not in capsys.readouterr().out, "[cmd] 摘要里也不许冒出 --effort"


def test_effort_gate_refuses_an_unknown_level_with_zero_side_effects(
        sandbox: Path, monkeypatch, capsys) -> None:
    """③ --effort 玄学 ⇒ 退 2、不起进程、不建 log、不写判决、点名合法值（照 --model 闸门那套）。"""
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000", "--spec", "spec.md",
                                      "--effort", "玄学", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "未授权的思考等级" in err and "玄学" in err
    for level in wd.EFFORT_LEVELS:                       # 点名每一个合法值（值域以常量为准）
        assert level in err, f"拒单要点名合法值 {level}"
    assert record == [], "一个子进程都不许起"
    assert not (sandbox / "gates" / "diag" / "wb-000.jsonl").exists(), "不许建 log"
    assert not (sandbox / "gates" / "diag" / "wb-000.verdict.txt").exists(), "不许写判决"


def test_effort_is_carried_into_resume_command() -> None:
    """④ 续跑（--resume）也带 --effort，否则续跑那一轮掉回 High；不给则续跑命令也没有。"""
    node, cli = wd.paths()
    cmd = wd.resume_command(node, cli, "sid-1", "接着干", "deepseek-v4.1-flash",
                            "bypassPermissions", effort="max")
    assert cmd[cmd.index("--effort") + 1] == "max"
    plain = wd.resume_command(node, cli, "sid-1", "接着干", "deepseek-v4.1-flash",
                              "bypassPermissions")
    assert "--effort" not in plain


def test_effort_help_is_built_from_the_constants(monkeypatch) -> None:
    """⑤ help 文本里的值域与常量同源（改常量即改 help，写死就咬 —— 与 --max-turns 同款）。"""
    helps = {a.dest: (a.help or "") for a in wd.build_parser()._actions}
    for level in wd.EFFORT_LEVELS:
        assert level in helps["effort"], f"help 里要列出 {level}"
    assert str(len(wd.EFFORT_LEVELS)) in helps["effort"], "help 里的档数也要从常量来"
    monkeypatch.setattr(wd, "EFFORT_LEVELS", ("minimal", "low", "super"))   # 突变检验
    after = {a.dest: (a.help or "") for a in wd.build_parser()._actions}
    assert "super" in after["effort"] and "max" not in after["effort"]
    assert str(3) in after["effort"]


# ================================================ 卡 029（T-G114）：429 / 额度三拍（§2.5）
#
# ★ 429 长得像成功：subtype=error_during_execution + 空回话 + **退出码 0** —— 判据必须读
# result 事件本身，不许看退出码。限流（带重置时间）与余额耗尽（没有）**分开记**。


def _quota_result_event(*, with_reset: bool) -> str:
    errors = {"status": 429, "code": 6004, "category": "quota",
              "message": "使用量已超出频率限制"}
    if with_reset:
        errors["message"] += "，将在 2026-09-27 07:38 重置"
    return json.dumps({"type": "result", "subtype": "error_during_execution",
                       "result": "", "errors": errors}, ensure_ascii=False)


def test_quota_error_tells_rate_limit_from_exhaustion() -> None:
    """限流（带「将在 <时间> 重置」）与余额耗尽（没有）分开记；健康 log → None。"""
    limited = wd.quota_error([_quota_result_event(with_reset=True)])
    assert limited is not None and limited["kind"] == "限流"
    assert "2026-09-27 07:38" in limited["reset"]
    broke = wd.quota_error([_quota_result_event(with_reset=False),
                            json.dumps({"type": "result", "subtype": "error_during_execution",
                                        "result": "额度已用尽"})])
    assert broke is not None and broke["kind"] == "余额耗尽" and broke["reset"] == ""
    assert wd.quota_error(EVENTS) is None, "健康的 result 不许误报"
    assert wd.quota_error(["不是 JSON 的一行", "{}"]) is None    # 畸形 log 不许炸


def test_quota_run_waits_probes_then_switches_to_the_next_whitelisted_model(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 三拍实测：429 → 等（--quota-wait 0）→ 探仍挂 → **按白名单顺序**换 ② 重派。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        events = [_quota_result_event(with_reset=True)] if len(calls) == 1 else EVENTS
        log.write_text("\n".join(events) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"

    probes: list[str] = []
    monkeypatch.setattr(wd, "run_worker", runner)

    def fake_probe(node, cli, model, timeout=120):   # noqa: ANN001, ANN202
        probes.append(model)
        return False, "额度仍挂（使用量已超出频率限制）"

    monkeypatch.setattr(wd, "quota_probe_ok", fake_probe)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    captured = capsys.readouterr()
    assert len(calls) == 2, "429 → 探挂 → 换模型重派，共两轮"
    assert probes == ["deepseek-v4.1-flash"], "先探当前模型（极小代价），别拿整卡当探测"
    m1 = calls[0][calls[0].index("--model") + 1]
    m2 = calls[1][calls[1].index("--model") + 1]
    assert (m1, m2) == ("deepseek-v4.1-flash", "glm-5.3-flash"), "按白名单顺序换，不许跳表外"
    assert "检出 429" in captured.err and "限流" in captured.err, captured.err
    assert "2026-09-27 07:38" in captured.err, "重置时间要原样带出来"


def test_quota_probe_ok_continues_the_same_model(sandbox: Path, monkeypatch, capsys) -> None:
    """等完探测通过 → **同一模型**接着干（刚才只是被限流了一会儿）。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        events = [_quota_result_event(with_reset=True)] if len(calls) == 1 else EVENTS
        log.write_text("\n".join(events) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (True, "探测通过"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    assert len(calls) == 2
    models = [c[c.index("--model") + 1] for c in calls]
    assert models == ["deepseek-v4.1-flash"] * 2, "探测通过就不该换模型"


def test_quota_all_exhausted_stops_with_exit_7(sandbox: Path, monkeypatch, capsys) -> None:
    """★★ 全挂就停（用户原话：「都有问题的话，就直接把任务停下来」）→ 退 **7**、不再自动重试。

    判决里要有**每个模型**的重置时间与这次烧掉的 token。就算 --retry 给到 5，也不许靠它续。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join([
            json.dumps({"type": "result", "subtype": "error_during_execution", "result": "",
                        "usage": {"input_tokens": 1000, "output_tokens": 10},
                        "errors": {"status": 429, "code": 6004, "category": "quota",
                                   "message": "额度已用尽，将在 2026-09-27 07:38 重置"}}),
        ]) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0", "--retry", "5"])
    assert wd.main() == 7
    err = capsys.readouterr().err
    assert "任务停下" in err and "退出码 7" in err
    assert len(calls) == 2, "两个白名单模型各试一轮就停，不许靠 --retry 空撞"
    stop = (sandbox / "gates" / "diag" / "wb-001.r2.verdict.txt").read_text(encoding="utf-8")
    assert "额度判决" in stop and "deepseek-v4.1-flash" in stop and "glm-5.3-flash" in stop
    assert "2,000" in stop and "input tokens" in stop, "要写这次一共烧了多少 token"


# ================================================ 卡 045（T-G136）：额度检测误判 + 续跑封顶
#
# ★ 真撞现场（2026-09-26）：只读复核卡 R029 第 1 轮**成功收工**（pytest 104 passed），
#   但回话正文提到「429」（复核清单里就有「429 当成功」这条）→ 旧判据把 `result` 正文一起扫、
#   名单里有裸 "429" → 判「余额耗尽」→ 等 300s → 探针通过 → 照样续跑 → 白跑 3 轮。
#   自毒：卡 029 自己的提交信息就写着「429 三拍」，任何 `git log` 都会中招。


def _success_result_event(words: str) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": words}, ensure_ascii=False)


def test_quota_error_ignores_a_successful_round_that_mentions_429() -> None:
    """★ 钉子①（今天 R029 真撞的回归）：正常成功 + 非空回话 → 一律不算额度错（候选闸门）。"""
    words = ("复核完了：pytest 104 passed。清单第 5 条「429 当成功」不适用；"
             "git log 显示上一条提交信息里写着「+429 三拍+」。")
    assert wd.quota_error([_success_result_event(words)]) is None, \
        "成功回话里出现「429」这个字符串不许判额度 —— 探针还通过呢"


def test_quota_error_never_matches_bare_needles_in_the_words() -> None:
    """★ 候选闸门放进来的事件，正文也**只允许完整中文短语**；裸 429/quota/6004 不许扫正文。"""
    tricky = json.dumps(
        {"type": "result", "subtype": "error_during_execution", "is_error": True,
         "result": "git log 显示 +429 三拍+，正文里还有 quota 与 6004 这两个词", "errors": None},
        ensure_ascii=False)
    assert wd.quota_error([tricky]) is None, "裸 needle 不许匹配回话正文"
    hit = wd.quota_error([json.dumps(
        {"type": "result", "subtype": "error_during_execution", "is_error": True,
         "result": "正文写着：额度已用尽", "errors": None}, ensure_ascii=False)])
    assert hit is not None and hit["kind"] == "余额耗尽", "完整中文短语仍然抓得住（双向）"
    assert "result" in hit["why"] and "额度已用尽" in hit["why"], \
        "要写清命中的字段与 needle（可观测性：下次误判一眼看出是谁骗了它）"


def test_quota_resume_is_capped_by_retry_and_stops_with_exit_7(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 钉子③：每轮都报额度错 → 续跑**停在 `--retry` 界上**并留下退出码 7 的判决，不许无界。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(_quota_result_event(with_reset=True) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (True, "探测通过"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0", "--retry", "1"])
    assert wd.main() == 7
    assert len(calls) == 2, "第 1 轮续跑在界内；第 2 轮再报额度 → 到界，停（旧代码会无限续）"
    err = capsys.readouterr().err
    assert "到界" in err and "退出码 7" in err
    stop = (sandbox / "gates" / "diag" / "wb-001.r2.verdict.txt").read_text(encoding="utf-8")
    assert "额度续跑到界" in stop and "deepseek-v4.1-flash" in stop, "判决写清撞了什么"


def test_probe_overrides_a_lying_discriminator_when_the_round_really_succeeded(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 卡 045 §2.4：探针通过 + 这一轮正常成功有非空回话 → **按成功收下**，不再续跑。

    判别器用 monkeypatch 假装误报（闸门修好之后真判别器不会再对正常成功开火），
    钉的是「矛盾时以探针为准」这条兜底路本身。"""
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(_success_result_event("复核完了：pytest 104 passed。"
                                             "第 5 条 429 当成功：不适用") + "\n",
                       encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", "sid-1"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(wd, "quota_error",
                        lambda lines: {"kind": "余额耗尽", "reset": "", "why": "（假装误报）"})
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (True, "探测通过"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    err = capsys.readouterr().err
    assert "误判？（探针通过但判别器报额度）→ 按成功收下" in err
    assert len(calls) == 1, "按成功收下就不许再续跑"


# ================================================ 卡 029（T-G114）：用量落账 + 防空烧预算（§2.6）


def test_usage_line_is_appended_and_status_shows_it(sandbox: Path, monkeypatch, capsys) -> None:
    """每轮跑完往 wb-usage.jsonl 追加一行（数来自 CLI 的 result.usage）；--status 打本卡 + 累计。"""
    events = [json.dumps({"type": "result", "subtype": "success", "result": "干完了",
                          "usage": {"input_tokens": 1234, "output_tokens": 56,
                                    "cache_read_input_tokens": 1200}}, ensure_ascii=False)]
    monkeypatch.setattr(wd, "run_worker", _fake_runner([], events=events))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    rows = [json.loads(ln) for ln in (sandbox / "gates" / "diag" / "wb-usage.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1
    row = rows[0]
    for key in ("卡", "模型", "轮次", "开始", "结束", "用时分钟", "input_tokens",
                "output_tokens", "cache_read", "退出码", "判决"):
        assert key in row, key
    assert row["input_tokens"] == 1234 and row["cache_read"] == 1200, "数要从 CLI 的 usage 拿"
    said = wd.status_report("001")
    assert "[用量]" in said and "本卡 1 轮" in said and "1,234" in said, said
    assert "累计（所有卡）" in said, said


def test_input_budget_stops_the_run_without_auto_resume(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 超预算 → 止损掐掉（这**不是**失败），就算 --retry 还有名额也不许自动续跑。"""
    events = [json.dumps({"type": "result", "subtype": "success", "result": "干完了",
                          "usage": {"input_tokens": 3_000_000}}, ensure_ascii=False)]
    calls: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(events) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", "sid-x"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--retry", "5",
                                      "--input-budget", "1000000"])
    assert wd.main() == 6
    err = capsys.readouterr().err
    assert "预算用尽" in err and "止损" in err
    assert len(calls) == 1, "预算用尽不许自动续跑"
    verdict = (sandbox / "gates" / "diag" / "wb-001.verdict.txt").read_text(encoding="utf-8")
    assert "预算判决" in verdict


# ================================================ 卡 029（T-G114）：过期判决 A+C（§2.1）


def test_real_run_archives_stale_verdict_and_report_but_dry_run_does_not(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ A（根因）：真开跑那一刻旧判决/摘要改名 .stale（只归档不删）；★ dry-run 不许归档。"""
    diag = sandbox / "gates" / "diag"
    diag.mkdir(parents=True)
    stale_verdict = diag / "wb-001.verdict.txt"
    stale_report = diag / "wb-001.report.md"
    stale_verdict.write_text("判决：前置检查没过 → 没派活\n", encoding="utf-8")
    stale_report.write_text("# 卡 001 的交接摘要\n", encoding="utf-8")
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md"])
    assert wd.main() == 0                                   # dry-run
    assert stale_verdict.exists() and stale_report.exists(), "dry-run 不许归档"
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0                                   # 真开跑
    stale = (diag / "wb-001.verdict.txt.stale")
    assert stale.exists() and "前置检查没过" in stale.read_text(encoding="utf-8"), \
        "只归档、不删（证据留档）"
    assert (diag / "wb-001.report.md.stale").exists()
    fresh = (diag / "wb-001.verdict.txt").read_text(encoding="utf-8")
    assert "正常收工" in fresh, "新一轮的判决落在原位（归档的是旧的）"


def test_detach_archives_stale_verdict_in_the_parent_before_return(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★★ 卡 164（T-G264）：`--force --detach --execute` 时**父进程**归档旧判决 ——
    在 detach return **之前**，不是之后。

    旧写法把 archive_stale_artifacts 放在 detach return 之后（原 line 2473）⇒ 父进程
    return 0 时旧判决还在原位 ⇒ 子进程起来到归档之间有时序窗口，谁读判决都读到旧的
    （146 现场：23:10「没派活」旧判决冒充当前状态到 23:40 真跑完）。这条钉子把归档
    **钉在 return 之前**：父进程 return 后旧判决已经是 `.stale`。
    """
    diag = sandbox / "gates" / "diag"
    diag.mkdir(parents=True)
    stale_verdict = diag / "wb-002.verdict.txt"
    stale_verdict.write_text("判决：前置检查没过 → 没派活\n", encoding="utf-8")
    monkeypatch.setattr(wd, "spawn_detached",
                        lambda argv, log: 4242)              # 不真起子进程
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "002", "--spec", "spec.md",
                                      "--detach", "--execute", "--force"])
    assert wd.main() == 0                                     # 父进程扔出去就返回
    out = capsys.readouterr().out
    assert "[归档]" in out, "父进程 return 前必须归档（detach 路径）"
    assert (diag / "wb-002.verdict.txt.stale").exists(), "旧判决已改名 .stale"
    assert not (diag / "wb-002.verdict.txt").exists(), "原位不该再有旧判决"


def test_verdict_carries_round_and_start_and_end_timestamps(
        sandbox: Path, monkeypatch) -> None:
    """★ 卡 164（T-G264）：判决带**轮次 + 开始时刻 + 结束时刻** ——
    读的人要能判「这是不是当前这一轮」（旧判决冒充当前状态的现场就是它）。
    """
    diag = sandbox / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-007.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    began = time.time() - 60
    vf = wd.write_verdict(log, card="007", attempts=2, code=0, reason="正常收工",
                          sid="sid-abc", lines=["{}"], errlog=log.with_suffix(".stderr.txt"),
                          started_at=began)
    text = vf.read_text(encoding="utf-8")
    assert "第=2 次" in text, "判决必须带轮次"
    assert "开始于=" in text and "结束于=" in text, "判决必须带开始与结束时刻"
    assert "sid-abc" in text


def test_status_warns_when_the_verdict_is_older_than_the_log(
        tmp_path: Path, monkeypatch) -> None:
    """★ C（兜底）：log 比最新判决新 → 醒目告警「它描述的不是当前这一轮」；判决新 → 不告警。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-042.jsonl"
    log.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    verdict = wd.verdict_file_for(log)
    verdict.write_text("判决：前置检查没过 → 没派活\n", encoding="utf-8")
    _ageing(verdict, seconds=600)                           # 判决旧、log 新
    assert "判决比日志旧" in wd.status_report("042")
    _ageing(log, seconds=1200)                              # 对照：判决比 log 新 → 不告警
    assert "判决比日志旧" not in wd.status_report("042")


# ================================================ 卡 029（T-G114）：--status 串卡（§2.9）


def test_status_does_not_confuse_card_42_with_card_421(tmp_path: Path, monkeypatch) -> None:
    """★ R024 实测的既有 bug：宽 glob `wb-42*` 会把 wb-421.jsonl 当卡 42 的 → 必须精确匹配。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    mine = diag / "wb-42.jsonl"                             # 卡 42：还在跑（没有 result）
    mine.write_text("\n".join(_running_events()) + "\n", encoding="utf-8")
    other = diag / "wb-421.jsonl"                           # 卡 421：已收工，且更新
    other.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    (diag / "wb-421.verdict.txt").write_text("card=421 判决：正常收工\n", encoding="utf-8")
    _ageing(mine, seconds=60)
    said = wd.status_report("42")
    assert "wb-421" not in said, f"串卡了：\n{said}"
    assert "wb-42.jsonl" in said and "还没见到 result" in said, said


# ================================================ 卡 029（T-G114）：规格指纹（§2.7）


def test_resume_with_changed_spec_prepends_the_read_spec_notice(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 规格改过再续跑 → 提示词最前面硬塞「先读规格」+ 醒目告警 + 新指纹写回（不许拒单）。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(calls))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                      "--spec", "spec.md", "--execute"])
    assert wd.main() == 0                                   # 第 1 次真开跑 → 记指纹
    capsys.readouterr()
    spec_note = sandbox / "gates" / "diag" / "wb-001.spec.txt"
    assert spec_note.exists() and "sha256=" in spec_note.read_text(encoding="utf-8")
    (sandbox / "spec.md").write_text("卡规格（改过了：新增 §2.10）", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--force", "--resume", "sid-test"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "规格已变" in out, out
    prompt = calls[-1][calls[-1].index("-p") + 1]
    assert "规格文件已更新" in prompt and "先用 Read 打开" in prompt, prompt
    assert prompt.startswith("★★ 规格文件已更新"), "必须塞在提示词最前面"
    assert "sha256=" in spec_note.read_text(encoding="utf-8"), "新指纹要写回"


def test_resume_without_a_fingerprint_file_passes_the_old_way(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 边界：没有 wb-<卡>.spec.txt 的老卡 → 放行并提示「无指纹，按老规矩」，不许拒单。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(calls))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--resume", "sid-old"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "无规格指纹" in out and "放行" in out, out
    prompt = calls[-1][calls[-1].index("-p") + 1]
    assert "规格文件已更新" not in prompt


# ================================================ 卡 029（T-G114）：续跑放行脏工作区（§2.10）


def test_fresh_dispatch_still_refuses_a_dirty_tree(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 非续跑保持原判据（必须干净）—— 那是「一写一读」的护栏，不许松。"""
    monkeypatch.setattr(wd, "git_dirty",
                        lambda: ["M src/a.py", "M docs/b.md", "?? 未跟踪的不算", " M docs/c.md"])
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 2
    assert "工作区不干净" in capsys.readouterr().err


def test_resume_allows_a_dirty_tree_prints_it_and_warns_outside_allow(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 续跑不适用「必须干净」：porcelain 原文照打 + 「★ 续跑：…继续」→ 放行；
    不在 --allow 白名单里的脏文件 → 醒目告警（可能是别的卡串了树）。"""
    dirty = [" M src/a.py", "M docs/b.md"]
    monkeypatch.setattr(wd, "git_dirty", lambda: dirty)
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(calls))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--resume", "sid-1", "--allow", "src/**"])
    assert wd.main() == 0
    err = capsys.readouterr().err
    assert "★ 续跑：工作区带着 2 个未提交改动（上一轮的活），继续" in err
    assert "M src/a.py" in err and "git status --porcelain 原文" in err, "原文要照打"
    assert "不在 --allow 白名单" in err and "docs/b.md" in err, "越界的要醒目告警"
    assert "工作区不干净" not in err, "续跑不许再按旧判据拒"


# ================================================ 卡 029（T-G114）：时间戳解析健壮性（§2.3）


def test_epoch_four_shapes_are_deterministic_and_never_raise() -> None:
    """★ 四种形状行为确定、绝不抛：Z 串 → epoch；naive → None（保守）；非法 → None；缺 → None。"""
    z = wd._epoch("2026-09-26T10:00:00Z")
    assert z is not None
    assert abs(z - wd._epoch("2026-09-26T10:00:00+00:00")) < 1, "Z 与 +00:00 同一个时刻"
    assert wd._epoch("2026-09-26T10:00:00") is None, "naive → 保守退回（不猜时区）"
    assert wd._epoch("不是时间") is None
    assert wd._epoch("2026-13-99T99:00:00Z") is None, "越界字段 → None，不许抛"
    assert wd._epoch("") is None and wd._epoch(None) is None and wd._epoch(12345) is None
    assert wd._epoch("  2026-09-26T10:00:00Z  ") is not None, "首尾空白要容住"


def test_port_bases_come_from_the_dispatch_var_not_the_gate_one(monkeypatch) -> None:
    """★ T-G195：端口段**只认 `TF_DISPATCH_PORT_BASE`，绝不认 `TF_GATE_PORT_BASE`**。

    为什么（真回归）：`TF_GATE_PORT_BASE` 是**门禁自己**的端口段，`run_gates.py` 会把它设进
    **每一道门**的子进程环境（**含 pytest**）。读了它，门禁内一旦真有门起了服务
    （`render`/`ui_flow`/`lf1_live`/`web_live` 在 `BASE..BASE+16` 上听），`preflight()` 就会
    把「门禁自己的服务」当成「段被占」→ 拒派 → 本文件 24 条用例全红（2026-10-01 实测）。
    """
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9034")        # 门禁会设的那个：不许当自己的
    monkeypatch.delenv("TF_DISPATCH_PORT_BASE", raising=False)
    assert wd._resolve_port_bases(None) == []

    monkeypatch.setenv("TF_DISPATCH_PORT_BASE", "9034, 9074")
    assert wd._resolve_port_bases(None) == [9034, 9074]
    assert wd._resolve_port_bases([8080]) == [8080]       # CLI 优先

    monkeypatch.setenv("TF_DISPATCH_PORT_BASE", "不是数字")
    assert wd._resolve_port_bases(None) is None           # 给错要当场说，不静默


# ================================================== 卡 103（T-G199）：派活器 --cwd
#
# 病（工人自己报的）：`wb_dispatch.py` 用 `cwd=ROOT`（**主仓**）把工人拉起来 ⇒ 工人会话 cwd
# 落在主仓，唯一护栏是切片里那句「工作树：.wt/xxx」—— 卡 100 / 卡 102 连着两口没 cd，直接
# 在主仓改了文件。这一卡把「工人必须在卡树里干活」从一句软话变成**接口 + 判据**。


def test_worker_process_starts_in_the_given_cwd(tmp_path: Path, monkeypatch) -> None:
    """★ `--cwd` 真透传到工人进程（`Popen(cwd=…)`）；**不给时逐字不变**（仍是仓库根）。"""
    seen: dict = {}

    class _FakeProc:
        pid = 12345

        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = iter([])          # 没输出 → 读线程立刻收工

        def wait(self, timeout: float | None = None) -> int:      # noqa: ARG002
            return 0

        def poll(self) -> int:
            return 0

    def fake_popen(argv, **kwargs):         # noqa: ANN001, ANN202
        seen.clear()
        seen.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(wd.subprocess, "Popen", fake_popen)
    tree = tmp_path / "cardtree"
    tree.mkdir()
    wd.run_worker([sys.executable, "-X", "utf8", "-c", "pass"], tmp_path / "l.jsonl",
                  tmp_path / "e.txt", timeout=60, max_turns=150, watchdog=False,
                  heartbeat_seconds=0, worker_cwd=tree)
    assert Path(seen["cwd"]) == tree, "给了 --cwd 就必须是它（工人的 cwd）"

    # 反例：不给 --cwd → 工人 cwd 仍是仓库根（老行为逐字不变）
    wd.run_worker([sys.executable, "-X", "utf8", "-c", "pass"], tmp_path / "l2.jsonl",
                  tmp_path / "e2.txt", timeout=60, max_turns=150, watchdog=False,
                  heartbeat_seconds=0)
    assert Path(seen["cwd"]) == wd.ROOT, "不给 --cwd 时不许偷偷挪窝"


def test_preflight_with_cwd_refuses_a_dirty_card_tree_and_names_it(
        sandbox: Path, monkeypatch) -> None:
    """★ 给了 --cwd：脏检查看**工人要干活的那棵树** —— 卡树脏 → 拒派并**点名是哪棵树**。"""
    worker = sandbox / "cardtree"
    worker.mkdir()
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)             # noqa: ARG005
    monkeypatch.setattr(wd, "git_dirty",
                        lambda cwd=None: ([" M tools/x.py"] if Path(cwd) == worker else []))
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                               worker_cwd=worker)
    assert problems, "卡树脏了必须拒派"
    assert "工作区不干净" in problems[0]
    assert str(worker) in problems[0], "要点名是哪棵树，别只说『不干净』"


def test_preflight_with_cwd_passes_when_card_tree_is_clean_even_if_main_is_dirty(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 卡树干净 + 主仓脏 → **放行**（主仓状态只当提示打出来）—— 反例式证明"不再被主仓挡住"。"""
    worker = sandbox / "cardtree"
    worker.mkdir()
    main_dirty = [" M docs/主控的文档.md", " M docs/台账.md"]
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)             # noqa: ARG005
    monkeypatch.setattr(wd, "git_dirty",
                        lambda cwd=None: ([] if Path(cwd) == worker else main_dirty))
    capsys.readouterr()
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                               worker_cwd=worker)
    assert problems == [], "主仓自己的文档改动不该挡住派活（今天为此白 stash 过一次）"
    err = capsys.readouterr().err
    assert "主仓状态" in err and "只提示" in err, "主仓状态要当提示打出来"
    assert str(worker) in err, "工人干活树是哪棵要打出来"


def test_cwd_not_a_git_worktree_is_a_clean_exit_2(sandbox: Path, monkeypatch, capsys) -> None:
    """★ `--cwd` 指到非 git 工作树 → 明确报错退 2（不静默当干净）。"""
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: False)            # noqa: ARG005
    monkeypatch.setattr(wd, "git_dirty", lambda cwd=None: [])              # noqa: ARG005
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--cwd", str(sandbox / "不是工作树")])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "不是 git 工作树" in err, "不是工作树要当场说清"


def test_brief_first_line_hardens_the_worker_cwd(tmp_path: Path) -> None:
    """★ `wb_brief.py --cwd`：切片**第一行**就是那句硬话（不再靠一句软软的「工作树：…」）。"""
    import wb_brief as wb  # 本文件只白名单追加用例；wb_brief 在此单独导入

    tree = str(tmp_path.resolve())
    text = wb.build(card="001", spec="", master=False, cwd=tree)
    first = text.splitlines()[0]
    assert first.startswith("★")
    assert "你必须" in first and f"cd {tree}" in first
    assert "在别的树" in first and "这一轮作废" in first

    # 反例：不给 --cwd → 第一行仍是老的表头（逐字不变）
    plain = wb.build(card="001", spec="", master=False)
    assert plain.splitlines()[0].startswith("# 开工切片")


# ================================================ 卡 109（T-G206）：两份真源钉死成一份
#
# ★ 为什么放这里（本卡让在 `tests/test_wb_dispatch.py` 末尾与新建 `tests/test_pool_dedup.py`
#   之间二选一）：候选理由——① 本文件已经在测 `wb_dispatch` 的**行为**，而这条判据测的是
#   `wb_dispatch` 里那两个函数的**来路**（结构），同文件里"行为 + 结构"一起看最省事；
#   ② **不新造文件名** —— 卡 108 正在同一片区域（`tools/pool/**`）加文件，新文件名有撞名风险。
#   （`test_pool_lib.py` 里已有的"三处入口结论一致"是**行为**判据，与本卡的**结构**判据互补。）

_POOL_DEDUP_FILES = ("wb_dispatch.py", "tf_stage_guard.py")
_POOL_DEDUP_NAMES = frozenset({"_outside_allow", "card_artifacts", "outside_allow"})


def test_dedup_outside_allow_and_card_artifacts_are_the_same_object() -> None:
    """★ 卡 109：判据是**同一个对象**，不是"长得像"。

    为什么值当测：卡 106 把"三处副本"收敛进 `tools/pool/`，但只改了 `wb_review.py` ——
    `wb_dispatch._outside_allow` / `wb_dispatch.card_artifacts` / `tf_stage_guard.outside_allow`
    三处**副本还在**（正是本仓最忌的"两份真源"：判据一漂，白名单就越界、产物就串卡）。
    删副本不够 —— 得钉死"同一个对象"，否则换个窗口又会各写一份。
    """
    import pool.jobs
    import pool.review
    import tf_stage_guard

    assert wd.outside_allow is pool.review.outside_allow, "越界判据必须与 pool.review 是同一个对象"
    assert tf_stage_guard.outside_allow is pool.review.outside_allow, \
        "tf_stage_guard 只许 `from … import`，不许另有一份"
    assert wd.card_artifacts is pool.jobs.card_artifacts, "产物定位必须与 pool.jobs 是同一个对象"


def test_dedup_no_local_defs_of_those_names_in_tools() -> None:
    """★ 卡 109：源码里**不许再出现**那些名字的 `def`（`from … import` 可以，`def` 不行）。

    为什么值当测：`is` 那条只能证明**现在**是同一个对象 —— 有人在文件下面再 `def` 一份，
    名字被后定义的顶掉，判据当场分叉。这条把病灶**直接点在源码上**（AST），
    顺手也管住 `tf_stage_guard.py`（它只该 import）。
    """
    import ast

    for name in _POOL_DEDUP_FILES:
        src = (ROOT / "tools" / name).read_text(encoding="utf-8")
        defs = {n.name for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        offenders = defs & _POOL_DEDUP_NAMES
        assert not offenders, f"{name} 里又长出了本地 def：{sorted(offenders)}"


# ---------------------------------------------- 默认派活器接守卫与登记（卡 125 · T-G223）
#
# 为什么值当测：`wb_dispatch --execute` 是项目自认的**默认派活入口**（唯一每天真在跑的那条路）。
# 从前它不 import 守卫 / 登记 ⇒ 别的窗口看不见这个活、一树两写者不会被咬（GLM-5.3 审查 2.1）。
# 下面六条**反例钉子**各钉一处；每条都"故意坏掉会红"（把接线拆掉/把判据写死，对应那条立刻红）。


def _reserve(card: str, *, tree: str, files: list[str]) -> None:
    """在**沙箱登记**（`TF_POOL_REGISTRY`）上占一条活租约 —— 用真 `pool.registry.reserve`。"""
    wd.pool_registry.reserve(card, tree=tree, files=files, lock_body="")


def test_guard_problems_pass_in_a_clean_sandbox(sandbox: Path) -> None:
    """正例（反空转）：干净的沙箱里四条守卫**全过** —— 证明下面几条不是"永远在咬"。"""
    assert wd.guard_problems("001", None) == []


def test_guard_refuses_a_second_dispatch_on_the_same_tree(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """① 同一棵树第二次派活被拒 —— 第一次 reserve 之后，第二次前置检查必须 FAIL 并点名"树被占"。

    ★ 卡 203：不给 `--cwd` 的标签现在按**进程 cwd** 还原 —— 这条用例**从主树跑**（cwd = 沙箱根）
    才拿得到主树标签（`""`），与占着的 `tree=""` 同树 ⇒ 咬。
    """
    monkeypatch.setattr(wd.pool_registry, "main_tree_root", lambda: sandbox)
    monkeypatch.chdir(sandbox)
    _reserve("777", tree="", files=["别的东西.md"])
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert any("树被占" in p and "777" in p for p in problems), problems


def test_guard_refuses_a_domain_intersection_and_names_the_file(sandbox: Path) -> None:
    """② 冲突域相交被拒 —— 另一个活租约拿着同一文件 ⇒ FAIL 并**点名相交的文件**。"""
    _reserve("777", tree=".wt/other", files=["sandbox-001.md"])
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert any("冲突域相交" in p and "sandbox-001.md" in p for p in problems), problems


def test_guard_refuses_while_the_gate_lock_is_held(sandbox: Path, monkeypatch) -> None:
    """③ 门禁锁在跑被拒 —— 用**桩**喂一份 `gate_lock.py status` 形态的锁原文（不去真抢锁）。"""
    body = ("[锁] 段 base=9034 文件=D:/x/gates.lock: card=001 pid=4242 "
            "起于 2026-10-02T10:00:00（已 12s / 租约剩 10688s；租约内） cwd=D:/x\n")
    monkeypatch.setattr(wd.pool_registry, "read_lock_body", lambda *a, **k: body)
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert any("这趟门禁还在跑" in p and "base=9034" in p for p in problems), problems


def test_guard_refuses_a_card_missing_from_the_queue(sandbox: Path) -> None:
    """④ 查不到域的卡被拒 —— 队列里没有这张卡 ⇒ FAIL，且**不是**当成空域放行（别猜空域）。"""
    problems, _ = wd.preflight("404", "spec.md", force=False, check_auth=False)
    assert any("队列里没有卡 404" in p and "别猜空域" in p for p in problems), problems


def test_execute_reserves_then_releases_the_tree(sandbox: Path, monkeypatch, capsys) -> None:
    """⑤ 收工之后租约不见了 —— 真跑一次（假工人）走完全流程：跑时占着、收工后不在登记里。"""
    during: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        during.append([str(r.get("card")) for r in wd.pool_registry.list_reservations()])
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        wd.session_file_for(log).write_text("sid-test", encoding="utf-8")
        return 0, "", "", "sid-test"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    assert during == [["001"]], f"跑工人的那一刻必须占着租约，实测 {during}"
    assert wd.pool_registry.list_reservations() == [], "收工之后租约必须已经不在了"
    assert "[还树] 租约已释放" in capsys.readouterr().out


def test_dry_run_does_not_reserve_the_tree(sandbox: Path, monkeypatch) -> None:
    """反例（卡规格明写）：**dry-run 不许占树** —— 只读的干跑不能改状态。"""
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md"])
    assert wd.main() == 0
    assert wd.pool_registry.list_reservations() == []


def test_worker_tree_label_is_main_tree_or_relative(sandbox: Path) -> None:
    """树标签口径与登记一致：主树 = ""；卡树 = 相对主树根的 posix 路径（**给了 `--cwd`** 时）。"""
    root = sandbox
    assert wd.worker_tree_label(root, root) == ""
    assert wd.worker_tree_label(root / ".wt" / "x", root) == ".wt/x"
    outside = root.parent / "别的地方"
    assert wd.worker_tree_label(outside, root) == outside.as_posix()


def test_worker_tree_label_none_uses_the_process_cwd(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 203（T-G307）：**不给 `--cwd`** 时按**进程 cwd** 还原标签 —— 老行为是**一律 `''`**。

    为什么钉住：老的「一律 `''`」= 从卡树里跑也把**主树**登记成被占，而工人在卡树里干活
    （症状 A：197/201/202 三张卡都被自己那条 `tree: ""` 租约挡过）。这条是**行为变化**的显式用例。
    """
    root = sandbox
    (root / ".wt" / "x").mkdir(parents=True)
    monkeypatch.chdir(root / ".wt" / "x")
    assert wd.worker_tree_label(None, root) == ".wt/x"           # 老行为是 ""


def test_worker_tree_label_none_from_the_main_tree_is_empty(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 203 反例：从**主仓**跑（不给 `--cwd`）⇒ 标签仍是 `''`（不许把主树误标成卡树）。"""
    root = sandbox
    monkeypatch.chdir(root)
    assert wd.worker_tree_label(None, root) == ""


def test_execute_without_cwd_from_a_card_tree_registers_that_tree(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 203 端到端（桩 CLI，不真调模型）：**从卡树里**派一次（不给 `--cwd`）⇒
    租约登记的 `tree` **等于该卡树标签**（不是 `''`）—— 症状 A 的正面回归钉。"""
    root = sandbox
    monkeypatch.setattr(wd.pool_registry, "main_tree_root", lambda: root)
    card_tree = root / ".wt" / "x"
    card_tree.mkdir(parents=True)
    monkeypatch.chdir(card_tree)
    during: list[list[str]] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        during.append([str(r.get("tree")) for r in wd.pool_registry.list_reservations()])
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        wd.session_file_for(log).write_text("sid-test", encoding="utf-8")
        return 0, "", "", "sid-test"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    assert during == [[".wt/x"]], f"从卡树跑 ⇒ 租约登记该卡树标签，实测 {during}"
    assert wd.pool_registry.list_reservations() == [], "收工之后租约必须已经不在了"


def test_max_turns_help_is_built_from_the_constants(monkeypatch) -> None:
    """⑥ 帮助文本的数字 = 常量（改常量不同步改帮助就红）—— 帮助**从常量拼出来**，写死就咬。"""
    helps = {a.dest: (a.help or "") for a in wd.build_parser()._actions}
    assert str(wd.DEFAULT_MAX_TURNS_WRITE) in helps["max_turns"]
    assert str(wd.DEFAULT_MAX_TURNS_READONLY) in helps["max_turns"]
    assert str(wd.DEFAULT_MAX_TURNS_READONLY) in helps["read_only"]
    # ★ 突变检验：把常量改掉，帮助必须跟着变（旧版写死"150 / 60" → 这一条当场红）。
    monkeypatch.setattr(wd, "DEFAULT_MAX_TURNS_WRITE", 111)
    monkeypatch.setattr(wd, "DEFAULT_MAX_TURNS_READONLY", 7)
    after = {a.dest: (a.help or "") for a in wd.build_parser()._actions}
    assert "111" in after["max_turns"] and "7" in after["max_turns"]
    assert "7" in after["read_only"]


def test_already_reserved_skips_the_guards_but_not_the_rest(
        sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 125 修订：`--already-reserved` **只**跳过守卫与占/还树；别的前置照走（两读数）。

    读数一：不带开关 → 已有活租约的树被拒（守卫照走）。
    读数二：带开关 → **不因那条租约**被拒；但**别的毛病照咬**（规格不在 → 仍拒）。
    ★ 卡 203：从**主树跑**（cwd = 沙箱根）才拿得到主树标签（`""`）与占着的 `tree=""` 同树。
    """
    monkeypatch.setattr(wd.pool_registry, "main_tree_root", lambda: sandbox)
    monkeypatch.chdir(sandbox)
    _reserve("777", tree="", files=["别的东西.md"])
    strict, _ = wd.preflight("001", "spec.md", force=False, check_auth=False)
    assert any("树被占" in p for p in strict), strict                  # 读数一
    relaxed, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                              already_reserved=True)
    assert relaxed == [], relaxed                                     # 读数二
    still, _ = wd.preflight("001", "没有这张卡.md", force=False, check_auth=False,
                            already_reserved=True)
    assert any("卡规格文件不存在" in p for p in still), still          # 只跳过守卫


def test_main_with_already_reserved_leaves_the_registry_untouched(
        sandbox: Path, monkeypatch, capsys) -> None:
    """带 `--already-reserved` 走完整 --execute：**不占也不还**（登记里仍只有调用方那条）。"""
    _reserve("777", tree="", files=["别的东西.md"])
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--already-reserved"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "--already-reserved" in out and "不占、不还" in out
    assert [r["card"] for r in wd.pool_registry.list_reservations()] == ["777"]
    assert "[还树]" not in out                         # 还树归调用方（MCP），这里没还
    assert record, "工人还是要派出去的（只是不占树）"


# ---------------------------------------------- 掐工人要还租约（卡 141 · T-G240）
#
# 为什么值当测：2026-10-02 真咬过 —— `.wt/projguard` 的工人被 `kill_tree` 掐掉，**租约没还**，
# 二十多分钟后另一张卡（同域）被域守卫当场拒（主控只能**手工** `registry.release('120')`）。
# 退出路径那几条靠 `atexit` 兜底（卡 118 给门禁锁那套）；但**强杀**（`kill -9` / 进程被外部
# 杀掉）时 `atexit` 根本不跑 ⇒ 还得靠 `pool.registry` 的死租约判据 —— 它的第二条要**租约里有 log**。
# 下面六条钉子各钉一处，每条都"故意坏掉会红"。

_LEASE_SUBPROCESS = r'''
import pathlib, sys
tools_dir = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(tools_dir))
import wb_dispatch as wd
wd.ROOT = root
wd.paths = lambda *a, **k: (root / "node.exe", root / "codebuddy")
wd.git_dirty = lambda *a, **k: []
wd.auth_ok = lambda *a, **k: (True, "登录自检通过")

def boom(cmd, log, errlog, **kw):
    (root / "reached_runner.txt").write_text("到了工人这一步\n", encoding="utf-8")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    raise RuntimeError("模拟派活器异常早退（工人半路炸了）")

wd.run_worker = boom
sys.argv = ["wb_dispatch.py", "--card", "001", "--spec", "spec.md", "--execute"]
wd.main()
'''


def _entry(card: str, *, tree: str, files: list[str], log: str = "") -> dict:
    """手工造一条租约条目（绕过 `reserve`）—— "租约还在、写它的进程已经没了"就是这个样子。

    ★ `at` 用**现在**（租约没过期）—— 这样用例判的就**只有**"日志判死"这一条，不是 TTL。
    """
    return {"card": card, "task": "", "tree": tree, "files": files, "project": "",
            "pool": "", "model": "", "log": log, "owner": "test",
            "at": datetime.now().isoformat(timespec="seconds"),
            "ttl_seconds": float(wd.pool_registry.DEFAULT_TTL),
            "note": ""}


def _diag(sandbox: Path) -> Path:
    d = sandbox / "gates" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_lease_log_for_skips_an_existing_log(sandbox: Path) -> None:
    """接线的前置：log 不存在 → 登记；**已存在** → 不登记（否则 `log_guard` 拦死 `--force`）。"""
    log = _diag(sandbox) / "wb-001.jsonl"
    assert wd.lease_log_for(log) == log.as_posix(), "log 不存在 ⇒ 必须登记（绝对 posix 路径）"
    log.write_text("", encoding="utf-8")
    assert wd.lease_log_for(log) == "", "log 已存在 ⇒ 不许塞（会被守卫拒）→ 退回 TTL 兜底"


def test_execute_registers_the_log_in_the_lease(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 接线（拆掉 → 这条红）：真跑一次 `--execute`，**跑的那一刻**那条租约必须带着 log。

    为什么必须带：不带 log 的租约只剩 TTL 一条判据 ⇒ 强杀之后要白占树 6 小时（卡 141 的现场）。
    """
    seen: list[dict] = []

    def runner(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        seen.extend(wd.pool_registry.list_reservations())
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", "sid-test"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    assert [r["card"] for r in seen] == ["001"], seen
    registered = seen[0]["log"]
    assert registered, "租约必须带上 log（否则强杀那条路只能等 6 小时 TTL）"
    assert registered.endswith("wb-001.jsonl"), registered
    assert "日志判死" in capsys.readouterr().out       # 也说出来给读日志的人看


def test_a_stale_log_lease_is_not_listed_and_prune_clears_it(sandbox: Path) -> None:
    """④ **强杀那条路**：工人进程早没了、日志也不动了 ⇒ `list_reservations()` 不当它是活的。"""
    log = _diag(sandbox) / "wb-003.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    old = time.time() - (wd.STALL_SECONDS + 60)
    os.utime(log, (old, old))                          # 日志"早就没动静了"（> STALL_SECONDS）
    wd.pool_registry.save([_entry("003", tree=".wt/dead", files=["sandbox-003.md"],
                                  log=log.as_posix())])
    assert wd.pool_registry.list_reservations() == [], "日志判死 ⇒ 不许再当活租约"
    assert wd.pool_registry.prune() == 1, "prune 要能把它清掉"


def test_a_live_log_lease_is_not_cleared(sandbox: Path) -> None:
    """⑤ 反例（不许误清）：同一条租约、log **刚写过** ⇒ 它必须还在（"宁可多拦一次"）。"""
    log = _diag(sandbox) / "wb-002.jsonl"
    log.write_text("{}\n", encoding="utf-8")           # mtime = 现在 ⇒ 还在跑
    wd.pool_registry.save([_entry("002", tree=".wt/live", files=["sandbox-002.md"],
                                  log=log.as_posix())])
    assert [r["card"] for r in wd.pool_registry.list_reservations()] == ["002"]
    assert wd.pool_registry.prune() == 0


def test_watchdog_kill_returns_the_lease(sandbox: Path, monkeypatch) -> None:
    """①② 看门狗把工人掐掉（`kill_tree`）之后，**租约也要还** —— 真跑一次（假工人被判卡死）。"""
    monkeypatch.setattr(wd, "run_worker", _fake_runner([], reason="卡死：9.0 分钟没有新事件"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--retry", "0"])
    assert wd.main() == 6
    assert wd.pool_registry.list_reservations() == [], "掐掉之后租约必须已还"


def test_budget_stop_returns_the_lease(sandbox: Path, monkeypatch) -> None:
    """③ 预算止损（另一条"提前 break"的退出路径）同样要还租约。"""
    events = [json.dumps({"type": "result", "subtype": "success", "result": "干完了",
                          "usage": {"input_tokens": 3_000_000}}, ensure_ascii=False)]
    monkeypatch.setattr(wd, "run_worker", _fake_runner([], events=events))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--input-budget", "1000000"])
    assert wd.main() == 6
    assert wd.pool_registry.list_reservations() == []


def test_the_lease_is_returned_even_when_the_dispatcher_raises(sandbox: Path) -> None:
    """③ **任何异常早退**都要还租约 —— 靠 `atexit` 兜底（`main()` 里那条收尾根本走不到）。

    ★ 为什么必须**子进程**真跑：`atexit` 只在**解释器退出**时跑；进程内抛异常时它还没跑，
      就地断言会假红。子进程炸了（退出码非 0）而登记里没有卡 001 = 兜底真生效。
    """
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", _LEASE_SUBPROCESS,
                           str(ROOT / "tools"), str(sandbox)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode != 0, f"这个子进程本来就该炸：\n{done.stdout}\n{done.stderr}"
    assert (sandbox / "reached_runner.txt").exists(), "没跑到工人那一步 ⇒ 这条用例没咬到点上"
    assert "[还树] 租约已释放" in done.stdout, done.stdout + done.stderr
    assert wd.pool_registry.list_reservations() == [], "异常早退之后租约必须已还（atexit 兜底）"


def test_release_is_idempotent_and_does_not_touch_others(sandbox: Path) -> None:
    """⑥ 重复还租约幂等：还两次不报错、也不误删别人的（★ 不许放宽守卫的反面：别误伤）。"""
    wd.pool_registry.save([_entry("001", tree=".wt/x", files=["sandbox-001.md"]),
                           _entry("002", tree=".wt/y", files=["sandbox-002.md"])])
    assert wd.pool_registry.release("001") is True
    assert wd.pool_registry.release("001") is False, "已经没了 ⇒ 空操作，不许报错"
    assert [r["card"] for r in wd.pool_registry.list_reservations()] == ["002"]


# ------------------------------------------------ 卡树基点过期（卡 135 · T-G233）
#
# 为什么值当测：收口会把卡树那份文件**拷回主树**；卡树基点比主树旧、主树又恰好改过同一份文件时，
# 这一步就是**静默覆盖**（本轮真咬：`.wt/mcpclaim` 的 `pool_mcp.py` 盖掉了 B-FIX1 的改动 →
# `test_dispatch_argv_is_pinned_and_reserves_first` 当场红）。下面四条各钉一处，每条"故意坏掉会红"。


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"git {args} 真跑失败了：{done.stderr}"
    return (done.stdout or "").strip()


def _stale_scene(tmp_path: Path, *, changed: list[str]) -> tuple[Path, Path, str, str]:
    """造一对真仓库：主树从基点 `A` 前进到 `B`（`changed` 里的文件被改），卡树停在 `A`。

    ★ 这是**真 git**（不是桩）：判据吃的是 `rev-parse` / `diff --name-only` / `log --oneline`，
      用桩喂不出"基点漂了"这件事。卡树用**真 worktree**（`git worktree add --detach`），
      与真链路一致（`.wt/<卡>` 就是 this）。
    """
    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "sandbox-001.md").write_text("v0\n", encoding="utf-8")
    (repo / "别的.md").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A：基点")
    a = _git(repo, "rev-parse", "HEAD")
    card = tmp_path / "cardtree"
    _git(repo, "worktree", "add", "-q", "--detach", str(card), a)
    if changed:
        for name in changed:
            (repo / name).write_text("v1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "B：基点之后主树又改了 " + "、".join(changed))
    b = _git(repo, "rev-parse", "HEAD")
    return repo, card, a, b


def test_stale_base_refuses_and_names_the_file_and_commit(sandbox: Path) -> None:
    """① 真过期：基点之后主树改了**本卡域里的文件** ⇒ 拒，且点名那个文件与那笔提交。"""
    repo, card, a, b = _stale_scene(sandbox, changed=["sandbox-001.md"])
    problem = wd.stale_base_problem("001", card, main_root=repo)
    assert problem is not None, "域里的文件被改过，判据必须咬"
    assert "sandbox-001.md" in problem, problem            # 点名文件
    assert "B：基点之后主树又改了" in problem, problem       # 点名提交
    assert a[:12] in problem and b[:12] in problem, problem


def test_stale_base_passes_when_only_out_of_domain_files_moved(sandbox: Path) -> None:
    """② 别误伤（最重要）：基点之后主树**只改了域外文件** ⇒ 放行（多批并行时很常见）。"""
    repo, card, _a, _b = _stale_scene(sandbox, changed=["别的.md"])
    assert wd.stale_base_problem("001", card, main_root=repo) is None


def test_stale_base_passes_when_the_heads_are_the_same(sandbox: Path) -> None:
    """③ `A == B` ⇒ 放行（卡树就在主树当前 HEAD 上，无过期可言）。"""
    repo, card, a, b = _stale_scene(sandbox, changed=[])
    assert a == b
    assert wd.stale_base_problem("001", card, main_root=repo) is None


def test_stale_base_skips_when_the_base_cannot_be_computed(sandbox: Path, capsys) -> None:
    """④ 算不出基点（cwd 不是 git 树）⇒ 打印"算不出基点，跳过"并**继续**（不是拒）。"""
    plain = sandbox / "not-a-repo"
    plain.mkdir()
    assert wd.stale_base_problem("001", plain, main_root=sandbox / "main") is None
    err = capsys.readouterr().err
    assert "算不出基点" in err and "跳过" in err, err


def test_preflight_wires_the_stale_base_check(sandbox: Path, monkeypatch) -> None:
    """接线：`preflight` 真把这条判据接上了（拆掉接线 → 这条红；判据本身由上面四条专测）。"""
    repo, card, _a, _b = _stale_scene(sandbox, changed=["sandbox-001.md"])
    monkeypatch.setattr(wd.pool_registry, "main_tree_root", lambda: repo)
    monkeypatch.setattr(wd, "is_git_worktree", lambda p: True)
    problems, _ = wd.preflight("001", "spec.md", force=False, check_auth=False,
                               worker_cwd=card)
    assert any("卡树基点过期" in p for p in problems), problems


# ============================================ 多号 profile：--account（卡 149 · T-G249）
#
# 为什么值当测：`--account` 让工人跑在**另一个号**的家目录里。判错方向只有一种，但后果很重 ——
# 「**看着成了其实用错号**」（本仓最恨的假绿）。下面每条各钉一处，每条"故意坏掉会红"：
#   ① 给了 ⇒ 工人环境里**真有**那六个变量（值来自 profile 的输出）；
#   ② 不给 ⇒ 环境**逐字不变**（`worker_env=None`，且租约 note 一字不改）；
#   ③ profile 不存在 ⇒ **拒派并点名**（含可用清单），**绝不退回默认号**；
#   ④ **没有第二份真源**：桩换一组值 ⇒ 派活器跟着变；本仓源码里**不许**出现那份清单；
#   ⑤ 留痕：租约 note / 派活日志里**看得见**那个 profile 名。
#
# ★ 那六个变量名只出现在**这份测试**里 —— 它是**钉子**，不是实现的一部分。

#: 判据用的六项（`codebuddy_accounts.py::profile_env` 的口径）。
_ACCOUNT_KEYS = ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA",
                 "WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR")


def _demo_vars(*, userprofile: str = "C:/profiles/demo/home") -> dict[str, str]:
    """一组像样的 profile 环境变量（桩输出用）。"""
    return {
        "USERPROFILE": userprofile,
        "HOME": userprofile,
        "APPDATA": "C:/profiles/demo/appdata",
        "LOCALAPPDATA": "C:/profiles/demo/localappdata",
        "WORKBUDDY_CONFIG_DIR": "C:/profiles/demo/wb",
        "CODEBUDDY_CONFIG_DIR": "C:/profiles/demo/cb",
    }


def _account_stub(tmp_path: Path, profiles: dict[str, dict[str, str]]) -> Path:
    """造一个假号池工具（照 `codebuddy_accounts.py` 的三种输出形状，含 bash/pwsh 两段）。

    ★ 用它替换**真源**：能改的一组值 ⇒ 证明派活器是**调**那份工具，而不是抄它的清单。
    """
    script = tmp_path / "fake_codebuddy_accounts.py"
    script.write_text(
        "import sys\n"
        f"PROFILES = {profiles!r}\n"
        "\n"
        "args = sys.argv[1:]\n"
        'if args[:2] == ["profile", "check"]:\n'
        "    if args[2] not in PROFILES:\n"
        '        print("✗ 没有这个 profile：" + args[2])\n'
        "        sys.exit(2)\n"
        "    sys.exit(0)\n"
        'if args[:2] == ["profile", "env"]:\n'
        "    env = PROFILES.get(args[2], {})\n"
        '    print("# profile " + args[2])\n'
        "    for k in env:\n"
        '        print(k + "=" + env[k])\n'
        '    print("")\n'
        '    print("# bash")\n'
        "    for k in env:\n"
        '        print(\'export \' + k + \'="\' + env[k] + \'"\')\n'
        '    print("")\n'
        '    print("# powershell")\n'
        "    for k in env:\n"
        '        print(\'$env:\' + k + \' = "\' + env[k] + \'"\')\n'
        "    sys.exit(0)\n"
        'if args[:1] == ["list"]:\n'
        '    print("账号根目录：tmp")\n'
        "    for name in PROFILES:\n"
        '        print("  · " + name + "（1 件）")\n'
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8")
    return script


def _capture_worker(seen: dict) -> object:
    """假 runner：把**收到的 kwargs**（含 `worker_env`）记下来，再照常落 log 回话。"""
    def run(cmd, log, errlog, **kwargs):              # noqa: ANN001, ANN202
        seen.update(kwargs)
        seen["cmd"] = list(cmd)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        wd.session_file_for(log).write_text("sid-test", encoding="utf-8")
        return 0, "", "", "sid-test"
    return run


def _spy_reserve(monkeypatch) -> dict:
    """记下 `pool_registry.reserve` 收到的 kwargs（留痕判据用它看 `note`）。"""
    seen: dict = {}
    real = wd.pool_registry.reserve

    def spy(card, **kwargs):                          # noqa: ANN001, ANN202
        seen.update(kwargs)
        return real(card, **kwargs)

    monkeypatch.setattr(wd.pool_registry, "reserve", spy)
    return seen


def _account_argv(monkeypatch, *extra: str) -> None:
    """把 `main()` 要读的 argv 摆好（`--account` 系列用例共用；用 monkeypatch ⇒ 自动还原）。"""
    monkeypatch.setattr(sys, "argv",
                        ["wb_dispatch.py", "--card", "001", "--spec", "spec.md", *extra])


def test_account_injects_the_profile_env_into_the_worker(
        sandbox: Path, monkeypatch, capsys) -> None:
    """① 给了 `--account` ⇒ 工人环境里**真有**那六个变量，值来自那份工具的**输出**。"""
    vars_ = _demo_vars()
    assert set(_ACCOUNT_KEYS) <= set(vars_), "桩要覆盖那六项（判据自检）"
    stub = _account_stub(sandbox, {"demo": vars_, "other": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    seen: dict = {}
    monkeypatch.setattr(wd, "run_worker", _capture_worker(seen))
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 0
    env = seen["worker_env"]
    assert env is not None, "给了 --account 就必须给工人一份环境"
    for key, val in vars_.items():
        assert env[key] == val, f"{key} 没并进去：{env.get(key)!r}"
    # ★ 只并那六项：bash / pwsh 两段不能被解析出假 key（`export X=…` / `$env:X = …`）
    for bogus in ("export USERPROFILE", "$env:USERPROFILE", "export HOME"):
        assert bogus not in env, f"解析器把 {bogus!r} 也当成变量了"
    out = capsys.readouterr().out
    assert "[账号] profile「demo」" in out


def test_without_account_the_worker_env_and_the_note_are_untouched(
        sandbox: Path, monkeypatch) -> None:
    """② 不给 `--account` ⇒ 环境**逐字不变**（`worker_env=None`）+ 租约 note 一字不改。"""
    seen: dict = {}
    monkeypatch.setattr(wd, "run_worker", _capture_worker(seen))
    note = _spy_reserve(monkeypatch)
    _account_argv(monkeypatch, "--execute")
    assert wd.main() == 0
    assert seen["worker_env"] is None, "不给 --account 时不许给工人另塞环境（= 继承真家目录）"
    assert note["note"] == "spec=spec.md", f"租约 note 被改了：{note['note']!r}"


def test_missing_profile_refuses_and_names_it(sandbox: Path, monkeypatch, capsys) -> None:
    """③ profile 不存在 ⇒ **拒派并点名**（列出可用 profile），**一个工人都别起**。"""
    stub = _account_stub(sandbox, {"demo": _demo_vars(), "other": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    dispatched: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(dispatched))
    _account_argv(monkeypatch, "--account", "nope", "--execute")
    assert wd.main() == 2, "profile 不存在必须拒派（退 2），不许退回默认号"
    err = capsys.readouterr().err
    assert "nope" in err and "拒绝派活" in err, err
    assert "demo" in err and "other" in err, f"要列出可用 profile：{err}"
    assert dispatched == [], "拒派时一个工人都不能起"


def test_account_values_follow_the_tool_not_a_local_copy(
        sandbox: Path, monkeypatch) -> None:
    """④a **调**不是**抄**：桩换一组值 ⇒ 派活器跟着变。"""
    stub = _account_stub(sandbox, {"demo": _demo_vars(userprofile="D:/别的号/home")})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    seen: dict = {}
    monkeypatch.setattr(wd, "run_worker", _capture_worker(seen))
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 0
    assert seen["worker_env"]["USERPROFILE"] == "D:/别的号/home", \
        "派活器没跟着那份工具的输出变 —— 说明它抄了一份本地清单"


def test_no_local_copy_of_the_profile_list_in_the_dispatcher(sandbox: Path) -> None:
    """④b 本仓源码里**不许**出现那份清单（否则就是第二份真源，两份一漂就会用错号）。

    ★ 钉哪三个：`LOCALAPPDATA` / `WORKBUDDY_CONFIG_DIR` / `CODEBUDDY_CONFIG_DIR` ——
      **任何**对本卡的复制都必然带上它们，而今天它们在 `wb_dispatch.py` 里出现 0 次。
    ★ 为什么不一并钉 `USERPROFILE` / `APPDATA` / `HOME`：前者 `paths()` 早就用了（与本卡无关），
      `HOME` 出现在**解释那段机制**的注释里 —— 那**不是**清单，钉它只会误伤自己的注释。
    """
    src = pathlib.Path(wd.__file__).read_text(encoding="utf-8")
    for key in ("LOCALAPPDATA", "WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR"):
        assert key not in src, f"wb_dispatch.py 里出现了 profile 清单项 {key}（那是第二份真源）"
    assert "PROFILE_ENV_KEYS" not in src
    # ★ 另一半：机制必须是**通用**的 `KEY=VALUE` 解析（不是一张写死的 key 清单）。
    assert hasattr(wd, "_ENV_LINE_RE"), "解析器不见了 —— 通用解析是'只调不抄'的关键"


def test_account_is_recorded_in_the_lease_note_and_the_log(
        sandbox: Path, monkeypatch, capsys) -> None:
    """⑤ 留痕：租约 note 与派活日志里**看得见**那个 profile 名。"""
    stub = _account_stub(sandbox, {"demo": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    note = _spy_reserve(monkeypatch)
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 0
    assert "account=demo" in note["note"], f"租约没记下 profile：{note.get('note')!r}"
    assert "[账号]" in capsys.readouterr().out


def _env_dump_stub(dump: Path) -> list[str]:
    """桩命令：吐一条成功的 result，再把自己的环境 dump 到 `dump`。"""
    code = ("import json, os\n"
            "print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'ok'}))\n"
            f"open({str(dump)!r}, 'w', encoding='utf-8').write(json.dumps(dict(os.environ)))\n")
    return [sys.executable, "-X", "utf8", "-c", code]


def test_runner_hands_the_injected_env_to_the_child(tmp_path: Path, monkeypatch) -> None:
    """真 Popen：`worker_env` 是**整份替换**（不是叠加）—— 桩把子进程环境打出来核对。"""
    monkeypatch.setenv("PROBE_PARENT_ONLY", "yes")
    dump = tmp_path / "env.json"
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    env = {k: os.environ[k] for k in ("PATH", "SystemRoot", "TEMP", "TMP") if k in os.environ}
    env["MARKER"] = "profile-xyz"
    rc, reason, _scene, _sid = wd.run_worker(_env_dump_stub(dump), log, err, timeout=60,
                                             max_turns=150, watchdog=True, heartbeat_seconds=0,
                                             worker_env=env)
    assert (rc, reason) == (0, ""), (rc, reason)
    child = json.loads(dump.read_text(encoding="utf-8"))
    assert child.get("MARKER") == "profile-xyz", "工人没拿到注入的环境"
    assert "PROBE_PARENT_ONLY" not in child, "给的是整份环境，不该顺便继承父进程的"


def test_runner_without_worker_env_inherits_the_parent(tmp_path: Path, monkeypatch) -> None:
    """`worker_env` 不给（默认 None）⇒ `Popen(env=None)` = **逐字继承**父进程环境。"""
    monkeypatch.setenv("PROBE_PARENT_ONLY", "yes")
    dump = tmp_path / "env.json"
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    rc, reason, _scene, _sid = wd.run_worker(_env_dump_stub(dump), log, err, timeout=60,
                                             max_turns=150, watchdog=True, heartbeat_seconds=0)
    assert (rc, reason) == (0, ""), (rc, reason)
    child = json.loads(dump.read_text(encoding="utf-8"))
    assert child.get("PROBE_PARENT_ONLY") == "yes", "不给 worker_env 必须继承父进程环境"


# ============================================ F1-F4 判据修复（卡 190 · T-G290）
#
# ★ 来自一次不同族模型的独立检查（卡 189）：--account 整条链路"工人的号真的换了吗"
#   从生产到测试没有任何一环判"对不对"。这组钉子逐条补判据，每条"故意坏掉会红"：
#   · F1 登录自检判错对象（两半）：探针要用 profile 环境 + 要用的那个 --model；
#   · F2 生产路径零判据：派活前跑一次子进程侧读数（不再"自己打印自己"）；
#   · F3 存在性冒充可用性：profile check 退 0 ≠ 号可用 —— 由 F1 的 auth_ok 用 profile 环境治；
#   · F4 解析契约手抄：值带引号 = 真源漂移 ⇒ 响亮拒（不静默收连引号的值）。
#   · F5（④b 清单钉是文本存在性判据）并入 F4 备注：防抄有效、不验行为 —— 这组钉子验行为。


def test_auth_ok_probe_uses_the_given_env(monkeypatch) -> None:
    """F1 第一半（单元）：auth_ok 收到 env ⇒ 探针用这个 env 发（不是父进程环境）。"""
    seen: dict = {}

    def spy_run(*a, **k):
        seen.update(k)
        return _Done(stdout="连接成功", stderr="")

    monkeypatch.setattr(wd.subprocess, "run", spy_run)
    probe_env = {"PATH": "x", "MARKER": "profile-xyz"}
    ok, _ = wd.auth_ok(Path("node"), Path("cli"), env=probe_env)
    assert ok
    assert seen.get("env") is probe_env, "探针没用给定的 env —— 还是父进程环境（F1 第一半）"


def test_auth_ok_probe_carries_the_model_when_given(monkeypatch) -> None:
    """F1 第二半（单元）：auth_ok 收到 model ⇒ 探针命令带 --model
    （判的是那个模型桶，不是 CLI 默认模型）。"""
    calls: list[list[str]] = []

    def spy_run(*a, **k):
        calls.append(list(a[0]))
        return _Done(stdout="连接成功", stderr="")

    monkeypatch.setattr(wd.subprocess, "run", spy_run)
    ok, _ = wd.auth_ok(Path("node"), Path("cli"), model="glm-5.2")
    assert ok
    cmd = calls[0]
    assert "--model" in cmd and "glm-5.2" in cmd, f"探针没带 --model glm-5.2：{cmd}"


def test_account_auth_uses_the_profile_env_and_model(sandbox: Path, monkeypatch) -> None:
    """F1 集成：给了 --account --model ⇒ auth_ok 收到 profile 环境 + 那个 model（判对对象）。"""
    stub = _account_stub(sandbox, {"demo": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    seen: dict = {}

    def spy_auth(*a, **k):
        seen.update(k)
        return (True, "登录自检通过")

    monkeypatch.setattr(wd, "auth_ok", spy_auth)
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    _account_argv(monkeypatch, "--account", "demo", "--model", "glm-5.2", "--execute")
    assert wd.main() == 0
    assert seen.get("env") is not None, "auth_ok 没收到 env —— 探的还是父进程环境（F1 第一半）"
    assert seen["env"].get("USERPROFILE") == _demo_vars()["USERPROFILE"], "env 里没有 profile 变量"
    assert seen.get("model") == "glm-5.2", "auth_ok 没收到 model —— 探的还是默认模型桶（F1 第二半）"


def test_account_refuses_when_the_profile_login_fails(sandbox: Path, monkeypatch,
                                                       capsys) -> None:
    """F3：auth_ok 用 profile 环境发探针失败 ⇒ 拒派（存在性 ≠ 可用性；号得真能登录）。

    ★ F1/F3 并案：profile check 退 0 只代表目录在；"号可用"由 auth_ok 用 profile 环境发探针判。
    """
    stub = _account_stub(sandbox, {"demo": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))

    def spy_auth(*a, **k):
        if k.get("env") and k["env"].get("USERPROFILE") == _demo_vars()["USERPROFILE"]:
            return (False, "登录没通（profile 的号没登录）")
        return (True, "登录自检通过")

    monkeypatch.setattr(wd, "auth_ok", spy_auth)
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 2, "profile 的号没登录必须拒派（F3），不许探默认号绿就放行"
    err = capsys.readouterr().err
    assert "登录" in err or "没通" in err, err


def test_dispatch_probes_the_account_env_from_the_child_side(sandbox: Path, monkeypatch,
                                                             capsys) -> None:
    """F2a 生产侧读数：派活前用 worker_env 起子进程读自己的环境回话 —— 不再"自己打印自己"。"""
    stub = _account_stub(sandbox, {"demo": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "[账号自检]" in out, "没跑子进程侧读数 probe —— 生产路径零判据（F2）"


def test_the_seam_account_env_to_real_child_holds(tmp_path: Path, monkeypatch) -> None:
    """F2b 接缝真通：真 account_env（桩脚本）+ 真 run_worker（真 Popen）
    → 子进程真拿到 profile 变量。

    ★ F2 的核心钉子：以前接缝（account_env 输出 → main 合成 → Popen）在"真输出 + 真子进程"
    组合下从未同时成立过 —— main 层桩只验到 kwargs，run_worker 层真 Popen 钉喂的是手工 env。
    这条把两端都写真：能抓住 run_worker 没把 env 传给 Popen（接缝断）。
    """
    stub = _account_stub(tmp_path, {"demo": _demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    account_vars = wd.account_env("demo")
    base = {k: os.environ[k] for k in ("PATH", "SystemRoot", "TEMP", "TMP") if k in os.environ}
    worker_env = {**base, **account_vars}
    dump = tmp_path / "env.json"
    log, err = tmp_path / "w.jsonl", tmp_path / "w.err"
    rc, reason, _scene, _sid = wd.run_worker(_env_dump_stub(dump), log, err, timeout=60,
                                             max_turns=150, watchdog=True, heartbeat_seconds=0,
                                             worker_env=worker_env)
    assert (rc, reason) == (0, ""), (rc, reason)
    child = json.loads(dump.read_text(encoding="utf-8"))
    for key, val in account_vars.items():
        assert child.get(key) == val, \
            f"子进程没拿到 {key}={val!r}（拿到 {child.get(key)!r}）—— 接缝断了"


def test_a_profile_value_with_quotes_is_refused(sandbox: Path, monkeypatch,
                                                capsys) -> None:
    """F4：真源漂移（值带引号）⇒ 响亮拒，不静默收连引号的值。

    ★ F5 并入：④b 清单钉是文本存在性判据（防抄有效、不验行为）；这条验**行为** ——
      正则 `^KEY=(.*)$` 贪婪，真源某天输出 `KEY="v"` 会连引号收成 `"v"`，这里当场拒。
    """
    bad_vars = _demo_vars()
    bad_vars["USERPROFILE"] = '"C:/带引号/home"'
    stub = _account_stub(sandbox, {"demo": bad_vars})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    _account_argv(monkeypatch, "--account", "demo", "--execute")
    assert wd.main() == 2, "值带引号必须拒派（F4），不许静默收连引号的值"
    err = capsys.readouterr().err
    assert "引号" in err or "拒" in err, err


# ============================================================ 卡 154（T-G254）
#   登录自检三态 + 重试一次 —— 派活器自检分得清「真没登录」与「探失败」。
#   来路：当晚同一个家、同一份 Cookies，派活器三次把「探失败」（超时/起不来/非零退出/空输出）
#   当成「没登录」⇒ 假红三次（不派活 + 白等 + 换号重试 + 白花额度）。
#   修法：三态（OK / NEEDS_LOGIN / INCONCLUSIVE）+ 重试一次 + 两次都失败给两条出路。
#   ★ 四条钉子用桩（stub auth_ok），不许真发请求打真实号池（卡规格禁区）。


def _auth_sequence(seq: list[tuple[bool, str]]):
    """桩 auth_ok：按 seq 顺序逐次返回（用完就停，多调一次直接抛 —— 防偷偷多发探针）。"""
    it = iter(seq)

    def spy(*a, **k):
        try:
            return next(it)
        except StopIteration as exc:                       # noqa: TRY004
            raise AssertionError("auth_ok 被多调了一次（不该重试那么多）") from exc
    return spy


def test_card154_nail1_real_not_logged_in_reports_not_login_not_probe_fail(
        sandbox: Path, monkeypatch, capsys) -> None:
    """① 真没登录 ⇒ 拦住，且报的是「没登录」（不是「探失败」）。

    ★ 反例钉子：把 NEEDLE 命中错判成「探失败」⇒ 这条红（消息里会冒「探失败」/「没能得出结论」）。
    """
    monkeypatch.setattr(wd, "AUTH_RETRY_BACKOFF_SECONDS", 0)   # 真没登录不重试，但保险置零
    monkeypatch.setattr(wd, "auth_ok", _auth_sequence([
        (False, "登录没通（Authentication required）→ 先在 TUI 里敲 /login（T-G80）"),
    ]))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                      "--spec", "spec.md", "--execute"])
    assert wd.main() == 2, "真没登录必须拦派（NEEDS_LOGIN）"
    err = capsys.readouterr().err
    assert "登录没通" in err or "Authentication required" in err, err
    # ★ 关键反例：不许把「真没登录」报成「探失败」/「没能得出结论」
    assert "探失败" not in err, f"真没登录被错报成探失败：{err}"
    assert "没能得出结论" not in err, f"真没登录被错报成「没能得出结论」：{err}"


def test_card154_nail2_probe_failed_reports_inconclusive_not_not_login(
        sandbox: Path, monkeypatch, capsys) -> None:
    """② 探失败（超时/非零退出/空输出）⇒ 不许报「没登录」，报的是「没能得出结论」。

    ★ 反例钉子：把「探失败」错判成「没登录」⇒ 这条红（消息里冒「登录没通」）。
    """
    monkeypatch.setattr(wd, "AUTH_RETRY_BACKOFF_SECONDS", 0)   # 重试但不睡
    monkeypatch.setattr(wd, "auth_ok", _auth_sequence([
        (False, "探失败：探针超时（180s）—— 可能是机器换页/CLI 起不来"),
        (False, "探失败：探针超时（180s）—— 可能是机器换页/CLI 起不来"),
    ]))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                      "--spec", "spec.md", "--execute"])
    assert wd.main() == 2, "探失败（两次都没结论）也必须拦派 —— 不许静默放行"
    err = capsys.readouterr().err
    assert "没能得出结论" in err, f"探失败应报「没能得出结论」：{err}"
    assert "探失败" in err, f"消息应带「探失败」标签让人能定位：{err}"
    # ★ 关键反例：不许把「探失败」报成「没登录」
    assert "登录没通" not in err, f"探失败被错报成「没登录」：{err}"


def test_card154_nail3_first_fail_then_success_allows_dispatch(
        sandbox: Path, monkeypatch, capsys) -> None:
    """③ 先失败后成功（重试拿到会话）⇒ 放行 —— 这是当晚的真现场。

    ★ 反例钉子：不重试 / 把第一次「探失败」当终局拒派 ⇒ 这条红（main() != 0）。
    """
    monkeypatch.setattr(wd, "AUTH_RETRY_BACKOFF_SECONDS", 0)   # 重试但不睡
    monkeypatch.setattr(wd, "auth_ok", _auth_sequence([
        (False, "探失败：探针超时（180s）—— 第一次探失败"),
        (True, "登录自检通过"),
    ]))
    record: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _fake_runner(record))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                      "--spec", "spec.md", "--execute"])
    assert wd.main() == 0, "先失败后成功（重试拿到会话）必须放行 —— 这是当晚真现场"
    out = capsys.readouterr().out
    assert record and "--output-format" in record[0], "重试拿到会话后应真派活"
    assert "复核完了" in out  # fake_runner 落的回话 —— 确认真走到了派活这一步


def test_card154_nail4_both_fail_prompts_two_ways_out_not_silent(
        sandbox: Path, monkeypatch, capsys) -> None:
    """④ 两次都失败 ⇒ 明确提示两条出路（/login 或 --no-preflight），不静默。

    ★ 反例钉子：两次都失败时静默按「没登录」处理 / 只给一条出路 ⇒ 这条红。
    """
    monkeypatch.setattr(wd, "AUTH_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(wd, "auth_ok", _auth_sequence([
        (False, "探失败：探针超时（180s）—— 第一次"),
        (False, "探失败：自检没拿到预期回话（退出码 1）—— 第二次"),
    ]))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001",
                                      "--spec", "spec.md", "--execute"])
    assert wd.main() == 2, "两次都失败必须拦派（不许静默放行自己担）"
    err = capsys.readouterr().err
    # ★ 两条出路都得在消息里 —— 缺一条 = 没把选择权交给人
    assert "/login" in err, f"两次都失败应提示 /login 出路：{err}"
    assert "--no-preflight" in err, f"两次都失败应提示 --no-preflight 出路：{err}"
    assert "没能得出结论" in err, f"应明说「没能得出结论」（不是静默按没登录处理）：{err}"
# ================================================ 卡 163 INV-39：派活前清死租约
def test_dispatch_prunes_dead_leases_before_reserving(sandbox: Path, monkeypatch,
                                                      capsys) -> None:
    """★ 卡 163 INV-39：派活前先清死租约 —— 下一位能直接拿到树，不需要人工 registry.release。

    造一个"日志已死"的租约（日志静默超 STALL_SECONDS）⇒ 派活时 prune 清掉它 + 说清清了什么。
    """
    dead_log = _diag(sandbox) / "wb-dead.jsonl"
    dead_log.write_text("{}\n", encoding="utf-8")
    old = time.time() - (wd.STALL_SECONDS + 60)
    os.utime(dead_log, (old, old))
    wd.pool_registry.save([_entry("dead", tree=".wt/dead", files=["sandbox-001.md"],
                                  log=dead_log.as_posix())])

    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0

    out = capsys.readouterr().out
    assert "清租" in out, "派活前必须说清清了什么"
    rows = wd.pool_registry.load()
    assert not any(r["card"] == "dead" for r in rows), "死租约必须被清掉"


# ================================================ 卡 163 INV-40：续跑不覆盖第 1 轮证据
def test_resume_does_not_overwrite_first_round_evidence(sandbox: Path, monkeypatch) -> None:
    """★ 卡 163 INV-40：续跑时第 1 轮的证据不许被覆盖 —— 从已有轮次+1 开始。

    造一个 wb-001.jsonl（第 1 轮证据）+ 会话文件 ⇒ --resume auto 续跑时从 r2 起，
    wb-001.jsonl 原封不动。
    """
    diag = _diag(sandbox)
    log = diag / "wb-001.jsonl"
    log.write_text("第一轮证据\n", encoding="utf-8")
    (diag / "wb-001.session.txt").write_text("sid-test", encoding="utf-8")

    seen_logs: list[str] = []

    def runner(cmd, log_k, errlog, **kwargs):          # noqa: ANN001, ANN202
        seen_logs.append(log_k.name)
        log_k.parent.mkdir(parents=True, exist_ok=True)
        log_k.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", "sid-test"

    monkeypatch.setattr(wd, "run_worker", runner)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--resume", "auto"])
    assert wd.main() == 0

    assert "wb-001.r2.jsonl" in seen_logs, f"续跑必须从 r2 开始（不覆盖第 1 轮）：{seen_logs}"
    assert log.read_text(encoding="utf-8") == "第一轮证据\n", "第 1 轮证据不许被覆盖"


# ================================================ 卡 156（T-G256）：旧判决冒充当前状态


def test_archive_succeeds_even_when_stale_already_exists(
        sandbox: Path, monkeypatch, capsys) -> None:
    """★ 卡 156 钉子①：归档第二次也成功 —— 造已存在 `.stale` 的现场 ⇒ 再归档 ⇒ 旧判决被挪进
    唯一名（不撞、不丢），**且打印了它**。这条直接钉真因：Windows 上 rename 撞已存在
    不再静默失败。"""
    diag = sandbox / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-001.verdict.txt").write_text("判决：前置检查没过 → 没派活\n", encoding="utf-8")
    (diag / "wb-001.report.md").write_text("# 卡 001 的交接摘要\n", encoding="utf-8")
    # 第一次归档留下的 .stale（已在现场）—— 旧写法到这里第二次 rename 就撞已存在、静默失败
    (diag / "wb-001.verdict.txt.stale").write_text("更早一次的判决\n", encoding="utf-8")
    (diag / "wb-001.report.md.stale").write_text("更早一次的摘要\n", encoding="utf-8")
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    out = capsys.readouterr().out
    assert "[归档]" in out, "归档成功必须出声（钉子①：打印了它）"
    # 旧判决被挪进带时间戳的唯一名，没撞、没丢
    archived = list(diag.glob("wb-001.verdict.*.stale"))
    assert archived, "旧判决应被归档进唯一名（wb-001.verdict.<ts>.stale）"
    assert any("前置检查没过" in p.read_text(encoding="utf-8") for p in archived), "归档的是旧判决"
    # 更早那份 .stale 还在（没被覆盖）—— 唯一名不丢历史归档
    assert (diag / "wb-001.verdict.txt.stale").read_text(encoding="utf-8") == "更早一次的判决\n"
    # 新一轮的判决落在原位
    assert "正常收工" in (diag / "wb-001.verdict.txt").read_text(encoding="utf-8"), \
        "新一轮判决落在原位（归档的是旧的）"


def test_archive_failure_is_not_silent(tmp_path: Path, monkeypatch) -> None:
    """★ 卡 156 钉子②：归档失败要出声 —— 桩一个不可 rename 的现场 ⇒ failed 带文件名 + 原因，
    不是 `except OSError: continue` 那种静默吞。"""
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-001.verdict.txt").write_text("旧判决\n", encoding="utf-8")

    def _boom(self, target):            # noqa: ANN001 —— 桩：模拟只读目录 / 目标被占
        raise OSError("rename 被桩拒绝")
    monkeypatch.setattr(Path, "rename", _boom)
    moved, failed = wd.archive_stale_artifacts("001")
    assert moved == [], "rename 全被桩拒绝 ⇒ 没有成功归档的"
    assert failed, "归档失败必须进 failed（不许静默吞）"
    assert any("wb-001.verdict.txt" in f for f in failed), "failed 要点名哪件没归成"
    assert any("rename 被桩拒绝" in f for f in failed), "failed 要带原因"


def test_main_reports_archive_failures_to_stderr(sandbox: Path, monkeypatch, capsys) -> None:
    """★ 卡 156 钉子②（main 端）：归档失败 ⇒ stderr 有 [归档失败] —— 与「没有旧件可归档」
    （什么都不打印）长得不一样，主控才分得清。"""
    monkeypatch.setattr(wd, "archive_stale_artifacts",
                        lambda card: ([], [f"wb-{card}.verdict.txt：rename 被桩拒绝"]))
    monkeypatch.setattr(wd, "run_worker", _fake_runner([]))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute"])
    assert wd.main() == 0
    err = capsys.readouterr().err
    assert "[归档失败]" in err, "归档失败必须打到 stderr（不许与「没有旧件」长得一样）"
    assert "wb-001.verdict.txt" in err, "stderr 要点名哪件没归成"


# ---------------------------------------------------------------- 卡 196（T-G296）：内置 node 不许

def test_resolve_node_prefers_current_marker(tmp_path: Path) -> None:
    """★ 卡 196 钉子①：`versions/current`（**内容为版本名的小文件**）优先 —— 机器升版本后不再断。"""
    versions = tmp_path / ".workbuddy" / "binaries" / "node" / "versions"
    (versions / "22.22.2-6").mkdir(parents=True)
    (versions / "22.22.2-6" / "node.exe").write_text("x", encoding="utf-8")
    (versions / "22.22.2-3").mkdir(parents=True)
    (versions / "22.22.2-3" / "node.exe").write_text("x", encoding="utf-8")
    (versions / "current").write_text("22.22.2-6", encoding="utf-8")

    got = wd._resolve_node(tmp_path)
    assert got == versions / "22.22.2-6" / "node.exe", got


def test_resolve_node_falls_back_to_newest_and_then_pinned(tmp_path: Path) -> None:
    """★ 卡 196 钉子②：没有 `current` ⇒ 扫 `versions/*/node.exe` 取**最新**；
    连 versions 目录都没有 ⇒ 退回旧的写死路径（宁可报错，也不静默换一个不存在的）。"""
    versions = tmp_path / ".workbuddy" / "binaries" / "node" / "versions"
    (versions / "22.22.2-6").mkdir(parents=True)
    (versions / "22.22.2-6" / "node.exe").write_text("x", encoding="utf-8")
    (versions / "22.22.2-4").mkdir(parents=True)
    (versions / "22.22.2-4" / "node.exe").write_text("x", encoding="utf-8")
    assert wd._resolve_node(tmp_path) == versions / "22.22.2-6" / "node.exe"

    empty = tmp_path / "nohome"
    empty.mkdir()
    assert wd._resolve_node(empty) == empty / wd.NODE_REL_FALLBACK


def test_host_injected_config_env_is_stripped_for_every_test(monkeypatch) -> None:
    """卡 E49：宿主注入的仓外配置必须被 `tests/conftest.py` 摘掉。

    云机 pass8 上 `test_account_auth_uses_the_profile_env_and_model` 红在
    「模型注册表不存在：C:/infra/pool/models.whitelist.toml」—— 那是 `run_gate.sh` 注入的
    `TF_MODEL_REGISTRY`（云机有、本机没有），跟着环境渗进了判据。摘掉之后，需要它的用例
    自己 `monkeypatch.setenv`（`sandbox` 夹具就是这么干的）。
    """
    import os

    import conftest as _conftest  # 判据就钉在那个夹具上：删了它，这条必红

    keys = ("TF_PROJECTS_TOML", "TF_MODEL_REGISTRY", "TF_MODEL_WHITELIST", "TF_POOL_CFG_DIR")
    for key in keys:  # 假装宿主刚刚注入了这四个（云机的样子）
        monkeypatch.setenv(key, "C:/infra/pool/x.toml")
    _conftest.strip_host_config_env(monkeypatch)  # 夹具本体调的就是它
    for key in keys:
        assert os.environ.get(key) is None, f"{key} 没被摘掉 —— 注入会换掉判据的对象"
