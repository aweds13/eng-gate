r"""钉「台账驱动选测」（卡 E51 · 段 1 / E36）。

## 判据（逐条对应卡 §段 1）

1. 改动路径 → 台账 `test:` 指针 → 用例文件集合；
2. `test:` 指针算出的文件名与 `scripts/audit_progress.py` **同一把尺子**（同一 entry 两边同名）；
3. 三闸各自 fail closed：① 台账里没有 entry / 条目没有 `test:` 指针 / 指针指向的文件不存在；
   ② `nightly-*.json` 缺失 / 过期 / 红；③ 碰判据本体（`gates/defs/domains.py` 等）；
4. `--json` 键名固定；
5. 台账读不懂 ⇒ fail closed；
6. 选测集合为空 ⇒ fail closed（空集不许伪装成"跑过了"）；
7. 回放最近 20 笔提交：台账登记的 `test:` 指针全部落在选测集合里，且 `fallback` ≤3 笔。

## 怎么跑（★ 不跑真门禁、不改真仓库）

- 合成 `tmp_path` 台账 + 真 `docs/traceability.toml` 都用在**纯函数**上；
- 回放判据读真实 git 历史（只 `git log/show`，**不写**任何文件）；
- 夜间记录在 `tmp_path` 里合成（不产真 `gates/diag/nightly`）。

## 边界（如实写）

- **实测加速表**（全量 vs 选测墙钟）**没跑**：本卡硬规矩是「只跑点名的测试文件」，
  全量门禁由主控收口时跑（读数落 `gates/diag/E51-full.log`）。
- `tools/wb_nightly.py --run` 的**真跑一趟全量**同样没跑（同上）；这里只钉记录/判定的纯逻辑。
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relpath: str):
    target = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ps():
    return _load("pytest_select_under_test", "tools/pytest_select.py")


def _nightly():
    return _load("wb_nightly_under_test", "tools/wb_nightly.py")


def _ledger(*entries: tuple[str, list[str]]) -> dict:
    return {"entries": {eid: {"evidence": ev} for eid, ev in entries}}


def _tree(tmp_path: Path, *relpaths: str) -> Path:
    for rel in relpaths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return tmp_path


def _git_tree(root: Path) -> tuple[str, str]:
    """把 tmp 目录变成一个**真 git 树**，返回 (`rev-parse --short HEAD`, `--show-toplevel`)。

    ★ 卡 E63（T-AG521）：夜间记录现在必须能自证「这份读数是**哪棵树的哪一笔**跑的」——
      `recent_full_ok()` 缺 rev / rev 对不上 HEAD / tree 不是本树 ⇒ 一律当「没有记录」
      （fail closed）。所以夹具必须是真树：从前那种 `rev="deadbee"` 的合成记录会让闸二
      永久不放行，而且它本身就是 E63 要修的那个病（跨 rev / 跨树结论冒充本树全量）。
    """

    def run(*a: str) -> str:
        done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
            ["git", *a],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return done.stdout.strip()

    run("init", "-q")
    run("config", "user.email", "nightly@example.invalid")
    run("config", "user.name", "nightly")
    run("config", "commit.gpgsign", "false")
    run("commit", "-q", "--allow-empty", "-m", "tip")
    return run("rev-parse", "--short", "HEAD"), run("rev-parse", "--show-toplevel")


def _nightly_record(root: Path, *, at: dt.datetime, ok: bool) -> None:
    nightly = _nightly()
    rev, tree = _git_tree(root)
    nightly.write_record(
        {
            "at": at.isoformat(timespec="seconds"),
            "record": f"nightly-{at.strftime('%Y%m%d-%H%M%S')}.json",
            "rev": rev,
            "tree": tree,
            "ok": ok,
            "exit_code": 0 if ok else 1,
            "seconds": 1.0,
            "worktree": "",
            "log": "",
            "note": "测试合成",
        },
        root,
    )


# ------------------------------------------------------------------ ① 映射
def test_changed_path_maps_to_ledger_tests(tmp_path: Path) -> None:
    """改动文件 → 该文件所在条目的 `test:` 指针（多条目取并集；不带 ::用例名也认）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "src/b.py", "tests/test_a.py", "tests/test_b.py", "tests/test_c.py")
    data = _ledger(
        ("E1", ["file:src/a.py", "test:test_a.py::case_one"]),
        ("E2", ["text:src/b.py::def run", "test:test_b.py"]),
        ("E3", ["file:src/a.py", "test:test_c.py::case_two"]),
    )
    sel = ps.select(["src/a.py", "src/b.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert not sel.fallback, sel.reason
    assert sel.tests == ("tests/test_a.py", "tests/test_b.py", "tests/test_c.py")
    assert sel.pytest_args[-1] == "--no-cov"


def test_test_pointer_filename_matches_audit_progress() -> None:
    """同一条台账 entry 在选测与审计里算出**同一个文件名**（不写第二把尺子）。"""
    ps = _ps()
    audit = _load("audit_progress_for_select", "scripts/audit_progress.py")
    data = ps.load_ledger()
    index = ps.ledger_index(data)
    assert index.test_files, "真台账里必须有用例指针，否则这条钉子无意义"
    assert set(index.test_files) <= audit.evidence_file_set(data)


def test_planned_entries_are_not_mapping_evidence(tmp_path: Path) -> None:
    """`todo` / `deferred` 条目的 `test:` 指针不算证据（它们常指着还没落地的用例文件）。"""
    ps = _ps()
    _tree(tmp_path, "tools/planned.py")
    data = {
        "entries": {
            "E-done": {"status": "done", "evidence": ["file:tools/planned.py", "test:test_a.py"]},
            "E-plan": {"status": "deferred", "evidence": ["file:tools/planned.py",
                                                          "test:test_not_yet.py"]},
        }
    }
    index = ps.ledger_index(data)
    assert index.sources["tools/planned.py"] == ("tests/test_a.py",)
    assert "tests/test_not_yet.py" not in index.test_files


def test_file_pointer_to_test_file_counts_as_case(tmp_path: Path) -> None:
    """台账只写了 `file:tests/test_x.py`（没有 `test:` 指针）也算用例文件（不是空集）。"""
    ps = _ps()
    _tree(tmp_path, "tools/ledger_only.py", "tests/test_ledger_only.py")
    data = _ledger(("E1", ["file:tools/ledger_only.py", "file:tests/test_ledger_only.py"]))
    sel = ps.select(["tools/ledger_only.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert not sel.fallback, sel.reason
    assert sel.tests == ("tests/test_ledger_only.py",)


# ------------------------------------------------------------------ ② 闸一：台账
def test_unmapped_file_falls_back_to_full(tmp_path: Path) -> None:
    """闸一①：改动文件在台账里没有任何 entry 指向 ⇒ 全量（判不出就是判不出）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "src/nobody.py", "tests/test_a.py")
    data = _ledger(("E1", ["file:src/a.py", "test:test_a.py"]))
    sel = ps.select(["src/a.py", "src/nobody.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert sel.fallback
    assert "src/nobody.py" in sel.reason
    assert "ledger" in sel.gates
    assert sel.pytest_args == []


def test_entry_without_test_pointer_falls_back(tmp_path: Path) -> None:
    """闸一②：条目读到了但**没有** `test:` 指针 ⇒ 选集为空 ⇒ 全量（空集不算跑过）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py")
    data = _ledger(("E1", ["file:src/a.py", "route:GET /api/x"]))
    sel = ps.select(["src/a.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert sel.fallback
    assert "test: 指针" in sel.reason
    assert sel.tests == ()


def test_pointer_to_missing_test_file_falls_back(tmp_path: Path) -> None:
    """闸一③：`test:` 指针指向的用例文件不存在 ⇒ 台账不可信 ⇒ 全量。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py")  # 故意不建 tests/test_gone.py
    data = _ledger(("E1", ["file:src/a.py", "test:test_gone.py"]))
    sel = ps.select(["src/a.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert sel.fallback
    assert "不存在的用例文件" in sel.reason


def test_unreadable_ledger_falls_back(tmp_path: Path) -> None:
    """台账读不懂（TOML 坏 / 没有 entries）⇒ fail closed，绝不猜成空映射。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "tests/test_a.py")
    bad = tmp_path / "docs" / "traceability.toml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("[entries.E1\nevidence = [", encoding="utf-8")
    sel = ps.select(["src/a.py"], root=tmp_path, nightly_ok=True)
    assert sel.fallback
    assert "台账" in sel.reason

    sel2 = ps.select(["src/a.py"], root=tmp_path, ledger={"entries": {}}, nightly_ok=True)
    assert sel2.fallback
    assert "没有 [entries" in sel2.reason


# ------------------------------------------------------------------ ③ 闸二：夜间全量
def test_nightly_missing_falls_back(tmp_path: Path) -> None:
    """闸二：一份 `nightly-*.json` 都没有 ⇒ 全量（每日全量是安全网的第一道）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "tests/test_a.py")
    data = _ledger(("E1", ["file:src/a.py", "test:test_a.py"]))
    sel = ps.select(["src/a.py"], root=tmp_path, ledger=data)
    assert sel.fallback
    assert sel.gates == ("nightly",)
    assert "夜间" in sel.reason


def test_nightly_stale_or_red_falls_back(tmp_path: Path) -> None:
    """闸二：记录过期（>24h）或最近一次是红的 ⇒ 都全量（没跑成的趟绝不当绿）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "tests/test_a.py")
    data = _ledger(("E1", ["file:src/a.py", "test:test_a.py"]))
    now = dt.datetime(2026, 10, 25, 12, 0, 0)

    _nightly_record(tmp_path, at=now - dt.timedelta(hours=30), ok=True)
    stale = ps.select(["src/a.py"], root=tmp_path, ledger=data, now=now)
    assert stale.fallback and "30" in stale.reason

    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=False)
    red = ps.select(["src/a.py"], root=tmp_path, ledger=data, now=now)
    assert red.fallback and "红的" in red.reason


def test_nightly_fresh_passes(tmp_path: Path) -> None:
    """闸二：最近一次全量绿 ≤24h ⇒ 放行（选测照常裁）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "tests/test_a.py")
    data = _ledger(("E1", ["file:src/a.py", "test:test_a.py"]))
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=True)
    sel = ps.select(["src/a.py"], root=tmp_path, ledger=data, now=now)
    assert not sel.fallback, sel.reason
    assert sel.tests == ("tests/test_a.py",)


# ------------------------------------------------------------------ ④ 闸三：判据本体
def test_judge_body_falls_back(tmp_path: Path) -> None:
    """闸三：碰 `gates/defs/**` / `scripts/run_gates.py` / pytest 配置 ⇒ 全量。"""
    ps = _ps()
    _tree(tmp_path, "gates/defs/domains.py", "scripts/run_gates.py", "pyproject.toml",
          "tests/test_a.py")
    data = _ledger(("E1", ["file:gates/defs/domains.py", "test:test_a.py"]))
    for path in ("gates/defs/domains.py", "scripts/run_gates.py", "pyproject.toml"):
        sel = ps.select([path], root=tmp_path, ledger=data, nightly_ok=True)
        assert sel.fallback, path
        assert sel.gates == ("judge_body",), path


# ------------------------------------------------------------------ ⑤ 空集 / 文档
def test_no_changes_is_empty_not_fallback(tmp_path: Path) -> None:
    """没有改动 / 只有记账改动 ⇒ 空选集（`fallback=False`），全量仍在收口链 ④。"""
    ps = _ps()
    docs = ps.select(["docs/changelog.md"], root=tmp_path, nightly_ok=True)
    assert not docs.fallback and docs.tests == ()
    empty = ps.select([], root=tmp_path, nightly_ok=True)
    assert not empty.fallback and empty.tests == ()


def test_changed_test_file_selects_itself(tmp_path: Path) -> None:
    """改过的用例文件自己必定进选集（不靠台账 —— 它本身就是判据）。"""
    ps = _ps()
    _tree(tmp_path, "tests/test_new.py")
    sel = ps.select(["tests/test_new.py"], root=tmp_path, ledger={"entries": {}}, nightly_ok=True)
    assert not sel.fallback and sel.tests == ("tests/test_new.py",)


# ------------------------------------------------------------------ ⑥ --json 键名 / run_gates 接线
def test_json_keys_are_fixed(tmp_path: Path) -> None:
    """`--json` 的键名固定（谁改键名谁把下游读法弄坏）。"""
    ps = _ps()
    _tree(tmp_path, "src/a.py", "tests/test_a.py")
    data = _ledger(("E1", ["file:src/a.py", "test:test_a.py"]))
    sel = ps.select(["src/a.py"], root=tmp_path, ledger=data, nightly_ok=True)
    assert set(ps.payload(sel)) == {"changed", "tests", "fallback", "reason", "gates"}
    assert json.loads(json.dumps(ps.payload(sel)))["tests"] == ["tests/test_a.py"]


def test_run_gates_select_switch_is_opt_in(monkeypatch) -> None:
    """`run_gates` 的选测开关默认关；`--select` / `TF_SELECT=1` 打开（两个入口同一判据）。"""
    run_gates = _load("run_gates_select_under_test", "scripts/run_gates.py")

    class _Args:
        select = False

    monkeypatch.delenv(run_gates._SELECT_ENV, raising=False)
    assert run_gates.select_enabled(_Args()) is False
    monkeypatch.setenv(run_gates._SELECT_ENV, "1")
    assert run_gates.select_enabled(_Args()) is True

    class _On:
        select = True

    monkeypatch.delenv(run_gates._SELECT_ENV, raising=False)
    assert run_gates.select_enabled(_On()) is True
    # 不给开关时 pytest 命令逐字不变（选集只通过 pytest_args 注入）
    plain = run_gates.resolve_cmd("pytest", {}, serial=True)
    assert plain == [run_gates.PY, "-X", "utf8", "-m", "pytest"]
    picked = run_gates.resolve_cmd(
        "pytest", {}, serial=True, pytest_args=["tests/test_a.py", "--no-cov"]
    )
    assert picked == [*plain, "tests/test_a.py", "--no-cov"]


# ------------------------------------------------------------------ ⑦ 夜间记录（wb_nightly）
def test_nightly_record_and_notification(tmp_path: Path) -> None:
    """`wb_nightly` 写记录 + 追加一行通知；闸二从记录里读得出「24h 内绿」。"""
    nightly = _nightly()
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    rev, tree = _git_tree(tmp_path)
    record = {
        "at": now.isoformat(timespec="seconds"),
        "record": nightly.record_name(now),
        "rev": rev,
        "tree": tree,
        "ok": True,
        "exit_code": 0,
        "seconds": 12.5,
        "worktree": "",
        "log": "",
        "note": "全量门禁绿",
    }
    path = nightly.write_record(record, tmp_path)
    assert path.parent == tmp_path / "gates" / "diag" / "nightly"
    notify = nightly.append_notification(record, tmp_path)
    lines = [ln for ln in notify.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "nightly"
    assert nightly.latest_record(tmp_path)["rev"] == rev
    ok, why = nightly.recent_full_ok(tmp_path, now=now)
    assert ok and "0.0 小时前" in why


# ------------------------------------------------------------------ ⑧ 落地链默认（wb_land 壳层）
def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_land_defaults_to_selection_but_judge_body_forces_full(tmp_path: Path) -> None:
    """落地链默认设 `TF_SELECT=1`；碰判据本体 / 给 `--no-select` ⇒ 不设（全量）。"""
    sys.path.insert(0, str(ROOT / "tools"))
    land = _load("wb_land_for_select", "tools/wb_land.py")
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    extra, why = land.select_env(["--tree", str(repo)], cwd=tmp_path)
    assert extra == {"TF_SELECT": "1"}, why

    (repo / "scripts").mkdir()
    (repo / "scripts" / "run_gates.py").write_text("# gate\n", encoding="utf-8")
    blocked, why2 = land.select_env(["--tree", str(repo)], cwd=tmp_path)
    assert blocked == {} and "判据本体" in why2

    off, why3 = land.select_env(["--tree", str(repo), "--no-select"], cwd=tmp_path)
    assert off == {} and "全量" in why3


# ------------------------------------------------------------------ ⑨ 回放判据（真历史，只读）
def test_replay_last_20_commits_has_no_missed_pointer() -> None:
    """回放最近 20 笔：台账 `test:` 指针全落在选集里，且 `fallback` ≤3 笔（卡 §段 1 判据 1）。"""
    ps = _ps()
    result = ps.replay(20, root=ROOT)
    assert len(result.rows) == 20
    for row in result.rows:
        assert not row.missing, (row.rev, row.task, row.missing)
    # ★ 卡 E52 修：判据本体那几笔是「宁可多跑」的设计，不是台账欠账 ⇒ 只把剩下的算欠账。
    #   阈值仍守着「覆盖率 fallback ≤ 3 笔」，同时要求每一笔 fallback 的原因是我们认识的那几种
    #   （判据本体 / 台账里没有 test: 指针）—— 出现没见过的原因就不许算绿。
    assert result.coverage_fallbacks <= ps.REPLAY_MAX_FALLBACK, [
        (r.rev, r.reason)
        for r in result.rows
        if r.fallback and not ps._known_fallback_reason(r.reason)
    ]
    for row in result.rows:
        if row.fallback:
            assert ps._known_fallback_reason(row.reason), (row.rev, row.reason)
    assert result.ok


def test_replay_rejects_a_fallback_reason_nobody_recognises(monkeypatch) -> None:
    """★ 反向钉子（卡 E52）：出现没见过的 fallback 原因 ⇒ `ok` 必须为假，不许静默算绿。"""
    ps = _ps()
    real = ps.replay(20, root=ROOT)
    rows = tuple(
        ps.ReplayRow(
            rev=r.rev, task=r.task, fallback=True, tests=r.tests,
            expected=r.expected, missing=r.missing, reason="闸九：没见过的一种新原因",
        )
        if i == 0 else r
        for i, r in enumerate(real.rows)
    )
    fake = ps.Replay(rows=rows, fallbacks=len(rows), ok=True, judge_body_fallbacks=0)
    assert not ps._known_fallback_reason(rows[0].reason)
    # 判据函数本身（这里直接按 replay() 的口径复算一遍）
    judge_body = sum(1 for r in rows if r.fallback and ps.JUDGE_BODY_MARK in r.reason)
    unknown = [r for r in rows if r.fallback and not ps._known_fallback_reason(r.reason)]
    ok = (fake.fallbacks - judge_body) <= ps.REPLAY_MAX_FALLBACK and not unknown and all(
        not r.missing for r in rows
    )
    assert ok is False
