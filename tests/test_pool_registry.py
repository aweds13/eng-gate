r"""作业登记（`tools/pool/registry.py` + `tools/wb_registry.py`，卡 108 · T-G205）的测试。

为什么值当测：写面的地基就是这份登记 —— 记错一处（把死租约当活、把活租约清空、坏文件被静默
覆盖）都会让"两个窗口进同一棵树"重新变成看不见的事故。

| 判据 | 判什么 |
|---|---|
| ① 落盘 / 原子写 | 写完能 `json.loads`；坏文件**不静默清空** |
| ② 自动腾位 | TTL 过期 / 日志判死，两种都要能腾位 |
| ③ 守卫串联 | 树冲突 / 域相交 / 门禁锁，经 `reserve` 全都要咬 |
| ④ 边界钉住 | 不登记 pid、不用 `os.kill` 探活、`--files` 查不到就拒 |

★ 一律用 `TF_POOL_REGISTRY` 指临时目录 —— **不往真的 `gates/diag/` 里写**。
"""

from __future__ import annotations

import ast
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_registry  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import jobs, registry  # noqa: E402

NOW = 1_700_000_000.0
TTL = registry.DEFAULT_TTL


@pytest.fixture()
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把登记文件指到临时目录（**绝不动真的 `gates/diag/pool-registry.json`**）。"""
    path = tmp_path / "reg.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(path))
    return path


@pytest.fixture()
def quiet_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """守卫里的门禁锁一律当"空着" —— 测试不依赖真的门禁锁文件。"""
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")


# ================================================================ ① 登记路径 / 主树定位


def test_registry_path_honors_env_override(reg: Path) -> None:
    assert registry.registry_path() == reg


def test_default_registry_path_is_in_the_main_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 默认位置 = **主工作树**的 `gates/diag/pool-registry.json`（不是卡树）。"""
    monkeypatch.delenv("TF_POOL_REGISTRY", raising=False)
    path = registry.registry_path()
    assert path.as_posix().endswith("gates/diag/pool-registry.json")
    # 主树里 `.git` 是**目录**；卡树里是**文件** —— 这正是不用 --show-toplevel 的原因。
    assert (registry.main_tree_root() / ".git").is_dir()


# ================================================================ ⑤ 主树定位不许依赖 cwd（卡 114）


def test_registry_path_does_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 卡 114：进程 cwd 在仓库外（DSH 起 MCP 子进程就是这样）也算得出主树。

    改之前 `main_tree_root()` 的那次 git 走**进程 cwd** ⇒ 在仓库外直接抛 `RegistryError`。
    """
    monkeypatch.delenv("TF_POOL_REGISTRY", raising=False)
    expected = registry.main_tree_root() / "gates" / "diag" / "pool-registry.json"
    elsewhere = tmp_path / "not-a-repo"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert registry.registry_path() == expected


def test_main_tree_root_is_the_repo_root_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 卡 117 钉子：chdir 到临时目录后 `main_tree_root()` 仍等于仓库根；
    再把 `TF_POOL_REGISTRY` 设成临时值 → `registry_path()` **优先用它**（覆盖主树路径）。"""
    monkeypatch.delenv("TF_POOL_REGISTRY", raising=False)
    repo_root = registry.main_tree_root()
    assert (repo_root / ".git").is_dir()  # 主树里 `.git` 是**目录**（卡树里是**文件**）
    elsewhere = tmp_path / "not-a-repo"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert registry.main_tree_root() == repo_root
    override = tmp_path / "custom-registry.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(override))
    assert registry.registry_path() == override


def test_relative_git_common_dir_resolves_against_git_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 卡 117：git 回**相对**路径时，相对的是**给 git 的那个 cwd**，不是进程 cwd。

    ★ 为什么另起一条：主树里 `--git-common-dir` 回的是相对的 `.git`（在**主工作树根**里
      跑 git 就是这个行为），而卡树里回的是绝对路径 —— 只跑卡树那两条钉子**碰不到**这个
      分支。这里造一个**真**仓库当"树根"（真跑 `git init`），把它当 `registry.py` 所在树，
      再把进程 cwd 挪去别处：老代码用 `Path.cwd()` 解析 `.git` ⇒ 会算成 `<进程 cwd>`（红）。
    """
    fake_root = tmp_path / "fake-repo"
    (fake_root / "tools" / "pool").mkdir(parents=True)
    # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
    # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
    subprocess.run(
        ["git", "init", "-q", str(fake_root)], check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace"
    )
    monkeypatch.setattr(registry, "__file__", str(fake_root / "tools" / "pool" / "registry.py"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # 进程 cwd 远离"树根"
    got = registry.main_tree_root()
    assert os.path.samefile(got, fake_root)  # 相对 `.git` 按"给 git 的 cwd"解析 → 树根
    assert not os.path.samefile(got, elsewhere)  # 老代码会落到进程 cwd（这条就红）


#: 号池 MCP 的十三个只读 + 四个写工具名（写工具要服务端 `POOL_MCP_WRITE=1` 才列）。
POOL_TOOL_NAMES = [
    "pool_plan",
    "job_list",
    "job_status",
    "job_result",
    "lock_status",
    "pool_models",
    # ★ 卡 201（T-G303）：第 10 个只读工具 —— 额度状态按钟表算
    "quota_status",
    "account_status",  # ★ 卡 E45（T-AG496）：账号账本（不探测、不联网）
    "checkin_status",  # ★ 卡 E48（T-AG497）：今日签到读数（读留档，永不触发签到）
    # ★ 卡 213（T-G325）：第 11 个只读工具 —— 工作台读数（调 pipeline_view）
    "workbench_board",
    "task_list",
    "task_status",
    "task_pool",
    "pool_dispatch",
    "pool_cancel",
    "usage_report",  # ★ 卡 A364（T-AG578）：第 5 个写工具 —— 外部用量上报入口
    "task_register",
    "task_claim",
]


def _rpc(proc: subprocess.Popen[str], message: dict) -> dict:
    """发一条 JSON-RPC、读回话（一行一条）—— 端到端钉子自己用的最小客户端。"""
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, "服务端还没回话就关了 stdout（EOF）"
    return json.loads(line)


def test_server_from_foreign_cwd_still_locates_main_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 端到端（卡 114）：真起 `tools/pool_mcp.py`，**子进程 cwd 在仓库外**。

    - `tools/list` ⇒ 18 个工具（13 只读 + 5 写）（顺带钉住"注册环境里 `POOL_MCP_WRITE=1`"）；
    - `tools/call pool_cancel {"card":"999","confirm":"999"}` ⇒ 走"本机登记里没有活租约"的
      正常路径；改之前这里是「算不出主工作树」。

    ★ 不往真 `gates/diag/` 写一个字节：`pool_cancel` 的"没租约"路径只读不写。
    """
    monkeypatch.delenv("TF_POOL_REGISTRY", raising=False)
    env = {k: v for k, v in os.environ.items() if k != "TF_POOL_REGISTRY"}
    env["POOL_MCP_WRITE"] = "1"
    foreign = tmp_path / "not-a-repo"
    foreign.mkdir()
    with (tmp_path / "server-err.txt").open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool_mcp.py")],
            cwd=str(foreign),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            listing = _rpc(proc, {"jsonrpc": "2.0", "id": "t1", "method": "tools/list"})
            assert [t["name"] for t in listing["result"]["tools"]] == POOL_TOOL_NAMES
            reply = _rpc(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": "t2",
                    "method": "tools/call",
                    "params": {
                        "name": "pool_cancel",
                        "arguments": {"card": "999", "confirm": "999"},
                    },
                },
            )
            text = reply["result"]["content"][0]["text"]
            assert "本机登记里没有卡 999 的**活租约**" in text
            assert "算不出主工作树" not in text
        finally:
            proc.kill()  # 自己起的服务自己收尾
            proc.wait(timeout=10)


# ================================================================ ① 落盘 / 原子写


def test_reserve_writes_loadable_json(reg: Path, quiet_lock: None) -> None:
    entry = registry.reserve(
        "108",
        task="T-G205",
        tree=".wt/a",
        files=["a.py"],
        model="m1",
        log="gates/diag/wb-999999.jsonl",
        owner="w1",
        now=NOW,
    )
    assert entry["card"] == "108" and entry["ttl_seconds"] == float(TTL)
    assert reg.exists()
    data = json.loads(reg.read_text(encoding="utf-8"))  # 写完能 json.loads
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["files"] == ["a.py"]
    assert [r["card"] for r in registry.list_reservations(NOW)] == ["108"]


def test_corrupt_registry_is_not_silently_wiped(reg: Path, quiet_lock: None) -> None:
    """★ 选「报错」不选「备份」：坏文件原封不动，人来修时看得见全貌。"""
    broken = "{坏掉的 JSON"
    reg.write_text(broken, encoding="utf-8")
    with pytest.raises(registry.RegistryError):
        registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    assert reg.read_text(encoding="utf-8") == broken  # 一个字都没动
    with pytest.raises(registry.RegistryError):
        registry.list_reservations(NOW)


def test_release_removes_the_lease(reg: Path, quiet_lock: None) -> None:
    registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    assert registry.release("108") is True
    assert registry.list_reservations(NOW) == []
    assert registry.release("108") is False  # 再放一次 → 没动任何东西


# ================================================================ ③ 守卫串联（经 reserve）


def test_reserve_bites_on_same_tree(reg: Path, quiet_lock: None) -> None:
    registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("109", tree=".wt/a", files=["b.py"], now=NOW)
    assert any("树被占" in p for p in exc.value.problems)
    assert len(registry.load(reg)) == 1  # 被咬 → 不落盘


def test_reserve_bites_on_intersecting_domain(reg: Path, quiet_lock: None) -> None:
    registry.reserve("108", tree=".wt/a", files=["a.py", "shared.py"], now=NOW)
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("109", tree=".wt/b", files=["shared.py"], now=NOW)
    assert any("shared.py" in p and "冲突域相交" in p for p in exc.value.problems)


def test_reserve_bites_on_running_gate_lock(reg: Path) -> None:
    body = (
        "[锁] 段 base=9034 文件=gate.lock: card=108 pid=999 "
        "起于 2026-10-01 23:37:00（已 12s / 租约剩 10788s；租约内） cwd=D:/eng"
    )
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("108", tree=".wt/a", files=["a.py"], lock_body=body, now=NOW)
    assert any("门禁还在跑" in p for p in exc.value.problems)


def test_reserve_bites_on_existing_log(reg: Path, tmp_path: Path, quiet_lock: None) -> None:
    existing = tmp_path / "wb-108.jsonl"
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("108", tree=".wt/a", files=["a.py"], log=str(existing), now=NOW)
    assert any("不许覆盖" in p for p in exc.value.problems)


def test_reserve_bites_when_lock_cwd_points_at_the_tree(reg: Path) -> None:
    root = registry.main_tree_root()
    body = (
        f"[锁] 段 base=9034 文件=gate.lock: card=999 pid=999 "
        f"起于 2026-10-01 23:37:00（已 12s / 租约剩 10788s；租约内） cwd={root.as_posix()}"
    )
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("108", tree="", files=["a.py"], lock_body=body, now=NOW)  # "" = 主树
    assert any("指向本树" in p for p in exc.value.problems)


# ================================================================ ② 死租约自动腾位


def test_expired_lease_auto_frees_the_tree(reg: Path, quiet_lock: None) -> None:
    registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    late = NOW + TTL + 1
    registry.reserve("109", tree=".wt/a", files=["b.py"], now=late)  # 108 已过期 → 放行
    live = [r["card"] for r in registry.list_reservations(late)]
    assert live == ["109"]
    assert len(registry.load(reg)) == 1  # 过期的那条被清掉了


def test_verdict_log_auto_frees_the_tree(reg: Path, tmp_path: Path, quiet_lock: None) -> None:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-108.jsonl"
    # ★ 登记时日志**还不存在**（log_guard 会拒已存在的 log）；作业跑起来后才落日志与判决。
    registry.reserve("108", tree=".wt/a", files=["a.py"], log=str(log), now=NOW)
    log.write_text("{}", encoding="utf-8")
    log.with_suffix(".verdict.txt").write_text("ok", encoding="utf-8")  # 已判决 = 判死
    registry.reserve("109", tree=".wt/a", files=["b.py"], now=NOW)  # 日志判死 → 放行
    assert [r["card"] for r in registry.list_reservations(NOW)] == ["109"]


def test_stalled_log_auto_frees_the_tree(reg: Path, tmp_path: Path, quiet_lock: None) -> None:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-108.jsonl"
    registry.reserve("108", tree=".wt/a", files=["a.py"], log=str(log), now=NOW)
    log.write_text("{}", encoding="utf-8")
    old = NOW - jobs.STALL_SECONDS - 60
    os.utime(log, (old, old))  # 静默超阈值 = 断了
    assert registry.list_reservations(NOW) == []
    assert registry.prune(NOW) == 1  # 落盘清掉
    assert registry.load(reg) == []


def test_live_log_keeps_the_lease(reg: Path, tmp_path: Path, quiet_lock: None) -> None:
    """反例：日志还在跑（新 mtime、无判决）→ 租约**不许**被误清。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    log = diag / "wb-108.jsonl"
    registry.reserve("108", tree=".wt/a", files=["a.py"], log=str(log), now=NOW)
    log.write_text("{}", encoding="utf-8")
    assert [r["card"] for r in registry.list_reservations(NOW)] == ["108"]


# ================================================================ ④ 边界钉住


def test_reservation_has_no_pid_and_no_os_kill(reg: Path, quiet_lock: None) -> None:
    entry = registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    assert "pid" not in entry  # ★ 不登记 pid
    # ★ 绝不用 os.kill 探活：Windows 上 CPython 的 os.kill 走 TerminateProcess（会杀进程）。
    #   看**代码**里有没有 `.kill(` 这个调用（不看文档字符串 —— 那里正好在讲这条禁令）。
    tree = ast.parse(Path(registry.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "kill"]
    assert calls == []


def test_default_owner_prefers_window_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_WINDOW_ID", "win-7")
    assert registry.default_owner() == "win-7"
    monkeypatch.delenv("TF_WINDOW_ID", raising=False)
    assert ":" in registry.default_owner()  # 回退 <hostname>:<pid>


# ================================================================ ⑤ 租约带 project（卡 120）


def test_reservation_writes_project_from_the_tree(
    reg: Path, quiet_lock: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 租约里**真的写了** `project`（写进去再读回来核）—— 按树从项目索引反查。"""
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    entry = registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    assert entry["project"] == "engineering"
    assert json.loads(reg.read_text(encoding="utf-8"))[0]["project"] == "engineering"


def test_reservation_honours_an_explicit_project(reg: Path, quiet_lock: None) -> None:
    entry = registry.reserve("108", tree=".wt/a", files=["a.py"], project="whatever", now=NOW)
    assert entry["project"] == "whatever"


def test_reservation_project_empty_when_index_is_unreadable(
    reg: Path, quiet_lock: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """索引读不了 ⇒ `project` 留空（附注而已，**不拖垮登记**）。"""
    monkeypatch.setenv("TF_PROJECTS_TOML", str(tmp_path / "没有这份.toml"))
    entry = registry.reserve("108", tree=".wt/a", files=["a.py"], now=NOW)
    assert entry["project"] == ""


def test_cli_list_shows_the_project(
    reg: Path, quiet_lock: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    assert wb_registry.main(["reserve", "--card", "108", "--tree", ".wt/a", "--files", "a.py"]) == 0
    capsys.readouterr()
    assert wb_registry.main(["list"]) == 0
    assert "项目 engineering" in capsys.readouterr().out


# ================================================================ ④ CLI：list/check/reserve/release


def test_cli_list_is_empty_not_fake(reg: Path, capsys: pytest.CaptureFixture) -> None:
    assert wb_registry.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "空着" in out and "条活租约" not in out


def test_cli_reserve_check_release_round_trip(
    reg: Path, quiet_lock: None, capsys: pytest.CaptureFixture
) -> None:
    assert wb_registry.main(["reserve", "--card", "108", "--tree", ".wt/a", "--files", "a.py"]) == 0
    capsys.readouterr()
    # 干跑：同一棵树 → 被咬（退 1，逐条点名）
    assert wb_registry.main(["check", "--card", "109", "--tree", ".wt/a", "--files", "b.py"]) == 1
    err = capsys.readouterr().err
    assert "树被占" in err
    # 换棵树 → 全过（退 0）
    assert wb_registry.main(["check", "--card", "109", "--tree", ".wt/b", "--files", "b.py"]) == 0
    capsys.readouterr()
    # --json 能出活租约
    assert wb_registry.main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["card"] for r in rows] == ["108"]
    assert wb_registry.main(["release", "--card", "108"]) == 0


def test_cli_unknown_card_without_files_is_refused(
    reg: Path, quiet_lock: None, capsys: pytest.CaptureFixture
) -> None:
    """★ `--files` 不给且 backlog 查不到 → 拒（退 2），**别猜成空域**。"""
    assert wb_registry.main(["check", "--card", "999999"]) == 2
    assert "没有冲突域" in capsys.readouterr().err


def test_cli_reserve_without_files_falls_back_to_backlog(
    reg: Path, quiet_lock: None, capsys: pytest.CaptureFixture
) -> None:
    """backlog 里真实存在的卡（022）→ `--files` 不给也能查出域。"""
    code = wb_registry.main(["reserve", "--card", "022", "--tree", ".wt/smoke"])
    out = capsys.readouterr().out
    assert code == 0 and "已登记" in out
    entry = json.loads(reg.read_text(encoding="utf-8"))[0]
    assert "src/timeflow/core/tasks/manager.py" in entry["files"]


def test_cli_ttl_and_at_are_recorded(
    reg: Path, quiet_lock: None, capsys: pytest.CaptureFixture
) -> None:
    assert (
        wb_registry.main(
            ["reserve", "--card", "108", "--tree", ".wt/a", "--files", "a.py", "--ttl", "60"]
        )
        == 0
    )
    capsys.readouterr()
    entry = json.loads(reg.read_text(encoding="utf-8"))[0]
    assert entry["ttl_seconds"] == 60.0
    datetime.datetime.fromisoformat(entry["at"])  # at 是合法 ISO8601
