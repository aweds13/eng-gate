"""卡 E10（T-AG461）：批次并入派活链 —— 钉子（先红后绿）。

钉子（规格 `复盘/卡/卡E10-批次并入派活链.md` §钉子）：
1. 三张文件不相交的待落卡 ⇒ 一批，成员齐全、顺序按队列序。
2. 两张卡同改一个文件 ⇒ 不许同批（拿 E2/E4 同改 `scripts/run_gates.py` 的形状当夹具）。
3. 依赖未满足（B 依赖 A、A 还没落）⇒ B 不许进批，且理由里点名 A。
4. 成员 5 张 ⇒ 拒单，错误里带「上限 4」与依据。
5. `make` 出来的预声明能被 `wb_task.py register` 原样接受（真跑一遍 `_validate_manifest`）。
6. 批次树冲突（两卡树同改一个文件）⇒ `make` 退非零，错误里点名冲突的卡与路径。
另加卡判据 7：`wb_dispatch.py --batch` 的「成员不在名单 / 批已 landed」两道响亮拒绝。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_batch as wb  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
import wb_dispatch as wd  # noqa: E402
import wb_task as wt  # noqa: E402
from pool import plan as pool_plan  # noqa: E402
from pool import task as pool_task  # noqa: E402


# ---------------------------------------------------------------- 夹具
def _card(
    card_id: str, files: list[str], *, depends: tuple[str, ...] = (),
    status: str = "pending", task: str = "", spec: str = "",
) -> pool_plan.Card:
    return pool_plan.Card(
        id=card_id, task=task or f"T-{card_id}", title=f"{card_id} 的卡",
        tree=f".wt/{card_id}", spec=spec, files=tuple(files),
        depends=depends, status=status)


def _backlog(*cards: pool_plan.Card) -> pool_plan.Backlog:
    return pool_plan.Backlog(reviewed="seed", cards=tuple(cards))


def _candidate_env(tmp_path: Path, cards: list[pool_plan.Card]) -> wb.Env:
    for card in cards:
        (tmp_path / card.tree).mkdir(parents=True, exist_ok=True)
    return wb.Env(root=tmp_path, main=tmp_path, batch_dir=tmp_path / "batch")


@pytest.fixture()
def fake_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """候选判据只关心「卡树有没有产物」—— 真 git 留给 make 的两条用例。"""
    monkeypatch.setattr(wb, "card_changes", lambda tree: ["changed.py"])


def _write_queue(root: Path, cards: list[dict]) -> None:
    lines = ["[base]", 'reviewed = "seed"', ""]
    for card in cards:
        lines += [
            "[[cards]]",
            f'id = "{card["id"]}"',
            f'task = "{card.get("task", "T-" + card["id"])}"',
            f'title = "{card["id"]} 的卡"',
            f'tree = "{card.get("tree", ".wt/" + card["id"])}"',
            'spec = ""',
            f'files = {json.dumps(card["files"])}',
            f'depends = {json.dumps(card.get("depends", []))}',
            'risk = "mid"',
            f'status = "{card.get("status", "pending")}"',
            "",
        ]
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text("\n".join(lines), encoding="utf-8")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    done = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert done.returncode == 0, (args, done.stdout, done.stderr)
    return done


def _init_repo(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("config", "user.email", "e10@example.com", cwd=main)
    _git("config", "user.name", "E10", cwd=main)
    _git("config", "core.autocrlf", "false", cwd=main)
    (main / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git("add", "-A", cwd=main)
    _git("commit", "-qm", "seed", cwd=main)
    return main


def _add_card_tree(main: Path, card_id: str, files: dict[str, str]) -> Path:
    tree = main / ".wt" / card_id
    _git("worktree", "add", "-q", "-b", f"card/{card_id}", str(tree), "HEAD", cwd=main)
    for rel, content in files.items():
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tree


@pytest.fixture()
def made_batch(tmp_path: Path) -> tuple[wb.Env, dict[str, Path]]:
    """真 git 仓：两张待落卡（各自一棵卡树、各改一个文件）→ 真 `make` 出一批。"""
    main = _init_repo(tmp_path)
    _write_queue(main, [
        {"id": "E8", "files": ["scripts/a.py"], "tree": ".wt/E8"},
        {"id": "E9", "files": ["tools/b.py"], "tree": ".wt/E9"},
    ])
    _add_card_tree(main, "E8", {"scripts/a.py": "A\n"})
    _add_card_tree(main, "E9", {"tools/b.py": "B\n"})
    env = wb.Env(root=main, main=main, batch_dir=tmp_path / "runtime" / "batch")
    written = wb.make_batch(env, "T-AG461", ["E8", "E9"])
    return env, written


# ---------------------------------------------------------------- 钉子 1-3：plan
def test_plan_packs_three_disjoint_cards_in_queue_order(
    tmp_path: Path, fake_changes: None,
) -> None:
    cards = [
        _card("E8", ["scripts/a.py"]),
        _card("E9", ["tools/b.py"]),
        _card("G1", ["skills/c.md"]),
    ]
    backlog = _backlog(*cards)
    env = _candidate_env(tmp_path, cards)
    candidates, skipped = wb.landing_candidates(env, backlog)
    eligible, blocked = wb.eligible_cards(backlog, candidates)
    groups = wb.pack_landing_batches(backlog, eligible)
    assert not skipped and not blocked
    assert len(groups) == 1
    assert [card.id for card in groups[0]] == ["E8", "E9", "G1"]


def test_same_file_cards_never_share_a_batch(tmp_path: Path, fake_changes: None) -> None:
    cards = [
        _card("E2", ["scripts/run_gates.py"]),
        _card("E4", ["scripts/run_gates.py"]),
    ]
    backlog = _backlog(*cards)
    env = _candidate_env(tmp_path, cards)
    candidates, _skipped = wb.landing_candidates(env, backlog)
    eligible, _blocked = wb.eligible_cards(backlog, candidates)
    groups = wb.pack_landing_batches(backlog, eligible)
    assert [[card.id for card in group] for group in groups] == [["E2"], ["E4"]]
    notes = wb.overlap_notes(backlog, eligible, groups)
    assert any("scripts/run_gates.py" in note for note in notes), notes


def test_dependency_not_met_blocks_and_names_it(tmp_path: Path, fake_changes: None) -> None:
    cards = [
        _card("A", ["a.py"]),
        _card("B", ["b.py"], depends=("A",)),
    ]
    backlog = _backlog(*cards)
    env = _candidate_env(tmp_path, cards)
    candidates, skipped = wb.landing_candidates(env, backlog)
    eligible, blocked = wb.eligible_cards(backlog, candidates)
    assert [card.id for card in eligible] == ["A"]
    assert "A" in blocked["B"] and "还没落" in blocked["B"]
    groups = wb.pack_landing_batches(backlog, eligible)
    output = wb.render_plan_output(groups, eligible, blocked, skipped, [])
    assert "卡 B" in output and "依赖 A" in output, output


# ---------------------------------------------------------------- 钉子 4：上限 4
def test_make_refuses_five_members_with_limit_and_basis(tmp_path: Path) -> None:
    member_ids = ["C1", "C2", "C3", "C4", "C5"]
    _write_queue(tmp_path, [{"id": card_id, "files": [f"{card_id}.py"]}
                            for card_id in member_ids])
    env = wb.Env(root=tmp_path, main=tmp_path, batch_dir=tmp_path / "batch")
    with pytest.raises(wb.BatchPlanError) as excinfo:
        wb.make_batch(env, "T-AG461", member_ids)
    message = str(excinfo.value)
    assert "上限 4" in message
    assert "TFS11" in message and "ACM TSE 2022" in message, message


# ---------------------------------------------------------------- 钉子 5 + 判据 4：make
def test_make_manifest_is_accepted_by_register(
    made_batch: tuple[wb.Env, dict[str, Path]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, written = made_batch
    assert written["tree"].name == "batch461"
    manifest = tomllib.loads(written["manifest"].read_text(encoding="utf-8"))
    # 判据 3：栅栏的校验本体真跑一遍（不是另写一份）
    pool_task._validate_manifest(manifest, "T-AG461")
    # 判据 5：`wb_task.py register` 原样接受
    monkeypatch.setenv("TF_BATCH_DIR", str(env.batch_dir))
    assert wt.main(["register", str(written["manifest"])]) == 0
    assert (env.batch_dir / "T-AG461.json").is_file()
    # 批次树里真的有两条补丁的产物
    assert (written["tree"] / "scripts" / "a.py").read_text(encoding="utf-8") == "A\n"
    assert (written["tree"] / "tools" / "b.py").read_text(encoding="utf-8") == "B\n"


def test_make_writes_traceability_evidence_union(
    made_batch: tuple[wb.Env, dict[str, Path]],
) -> None:
    _env, written = made_batch
    trace = written["tree"] / "docs" / "traceability.d" / "T-AG461.toml"
    data = tomllib.loads(trace.read_text(encoding="utf-8"))
    entry = data["entries"]["T-AG461"]
    assert entry["status"] == "partial"
    assert "file:scripts/a.py" in entry["evidence"]
    assert "file:tools/b.py" in entry["evidence"]


# ---------------------------------------------------------------- 钉子 6：批次树冲突
def test_make_conflict_names_cards_and_path(tmp_path: Path) -> None:
    _write_queue(tmp_path, [
        {"id": "E2", "files": ["scripts/run_gates.py"], "tree": ".wt/E2"},
        {"id": "E4", "files": ["scripts/run_gates.py"], "tree": ".wt/E4"},
    ])
    env = wb.Env(root=tmp_path, main=tmp_path, batch_dir=tmp_path / "batch")
    with pytest.raises(wb.BatchPlanError) as excinfo:
        wb.make_batch(env, "T-AG461", ["E2", "E4"])
    message = str(excinfo.value)
    assert "批次树冲突" in message
    assert "E2" in message and "E4" in message and "scripts/run_gates.py" in message, message


# ---------------------------------------------------------------- 反向钉子（make 侧）
def test_make_refuses_unmet_dependency_and_names_it(tmp_path: Path) -> None:
    """③ depends 未满足不许并批 —— make 侧也必须点名是哪张依赖没落。"""
    _write_queue(tmp_path, [
        {"id": "A", "files": ["a.py"], "tree": ".wt/A"},
        {"id": "B", "files": ["b.py"], "tree": ".wt/B", "depends": ["A"]},
    ])
    env = wb.Env(root=tmp_path, main=tmp_path, batch_dir=tmp_path / "batch")
    with pytest.raises(wb.BatchPlanError) as excinfo:
        wb.make_batch(env, "T-AG461", ["A", "B"])
    message = str(excinfo.value)
    assert "依赖 A" in message and "还没落" in message and "不许进批" in message, message


# ---------------------------------------------------------------- 判据 7：dispatch --batch
def _manifest_text(batch_id: str, members: list[str]) -> str:
    body = "".join(
        f'\n[[member]]\nid = "{member}"\nlayer = "框架层"\npaths = ["x.py"]\n'
        for member in members)
    return (f'id = "{batch_id}"\nwhy = "测试批"\n'
            f'gate_cmd = "python -X utf8 scripts/run_gates.py"\n'
            f'on_complete = ["draft"]\n{body}')


def test_dispatch_batch_refuses_member_not_in_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    (batch_dir / "T-1.toml").write_text(_manifest_text("T-1", ["E8", "E9"]), encoding="utf-8")
    monkeypatch.setenv("TF_BATCH_DIR", str(batch_dir))
    message = wd.batch_gate_problem("T-1", "Z9")
    assert message and "不在批 T-1 的成员名单里" in message and "Z9" in message, message
    assert "读不到可用预声明" in (wd.batch_gate_problem("T-404", None) or "")


def test_dispatch_batch_refuses_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    (batch_dir / "T-1.toml").write_text(_manifest_text("T-1", ["E8", "E9"]), encoding="utf-8")
    (batch_dir / "T-1.json").write_text(json.dumps({
        "id": "T-1", "state": "landed",
        "landed": {"commit": "abc123", "at": "2026-10-25T00:00:00+08:00"},
    }), encoding="utf-8")
    monkeypatch.setenv("TF_BATCH_DIR", str(batch_dir))
    message = wd.batch_gate_problem("T-1", "E8")
    assert message and "已经 landed" in message and "abc123" in message, message


# ---------------------------------------------------------------- 判据 1：三个入口写在 help
def test_help_explains_three_entrypoints() -> None:
    text = wb.build_parser().format_help()
    assert "只读" in text and "写盘" in text and "起门禁" in text
    for name in ("plan", "make", "land"):
        assert name in text
    assert "上限 4" in text
