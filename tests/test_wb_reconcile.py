r"""`tools/wb_reconcile.py` 的判据（卡 A269 · T-AG387）。

两条口径（与工具 docstring 一致，别只测 happy path）：
  ① **stale-pending（红）**：状态不是 done 但已有提交 ⇒ 台账落后于历史；
  ② **stale-done（黄）**：状态 done 但没提交 ⇒ 只报不拒（本仓历史上有 15 张老卡）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import wb_reconcile  # noqa: E402

NL = chr(10)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def _repo(tmp_path: Path, backlog: str) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "workbacklog.toml").write_text(backlog, encoding="utf-8")
    return tmp_path


def _card(cid: str, task: str, status: str) -> str:
    return (f"[[cards]]{NL}id = {cid!r}{NL}task = {task!r}{NL}status = {status!r}{NL}")


def test_pending_but_committed_is_stale_red(tmp_path: Path) -> None:
    """① 状态 pending 但历史里已有这笔 ⇒ 必须点红（这正是 252/260/262 撞的那条）。"""
    root = _repo(tmp_path, _card("A1", "T-GX1", "pending"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x (T-GX1)")
    cards = wb_reconcile.load_cards(root)
    stale_pending, stale_done, accounted = wb_reconcile.check(root, cards)
    assert [x["id"] for x in stale_pending] == ["A1"]
    assert stale_pending[0]["commit"]
    assert stale_done == []
    assert wb_reconcile.main(["--root", str(root)]) == 1


def test_done_without_commit_is_advisory_only(tmp_path: Path) -> None:
    """② 状态 done 但没提交 ⇒ 只报不拒（退出码仍 0）。"""
    root = _repo(tmp_path, _card("A2", "T-GX2", "done"))
    cards = wb_reconcile.load_cards(root)
    stale_pending, stale_done, accounted = wb_reconcile.check(root, cards)
    assert stale_pending == []
    assert [x["id"] for x in stale_done] == ["A2"]
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_consistent_queue_is_green(tmp_path: Path) -> None:
    """③ 一致：pending 没提交、done 有提交 ⇒ 两条都空、退出码 0。"""
    backlog = _card("A3", "T-GX3", "pending") + _card("A4", "T-GX4", "done")
    root = _repo(tmp_path, backlog)
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: y (T-GX4)")
    cards = wb_reconcile.load_cards(root)
    stale_pending, stale_done, accounted = wb_reconcile.check(root, cards)
    assert stale_pending == [] and stale_done == []
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_failed_card_with_commit_is_not_red(tmp_path: Path) -> None:
    """③a **终态不判红**：卡 146 是「被取代」，历史里有正文提到任务号的提交也不算台账落后。

    ★ 2026-10-17 真撞过：A269 的提交正文里有 `T-G246`，对账器把作废的 146 报成 stale-pending。
    """
    root = _repo(tmp_path, _card("A3", "T-GY3", "failed"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x (T-GY0)", "-m", "正文提到 T-GY3")
    cards = wb_reconcile.load_cards(root)
    stale_pending, stale_done, accounted = wb_reconcile.check(root, cards)
    assert stale_pending == []
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_body_mention_is_not_a_commit(tmp_path: Path) -> None:
    """③b **只认标题**：提交正文里提到任务号 ⇒ 不算落地（pending 也不许因此点红）。"""
    root = _repo(tmp_path, _card("A4", "T-GY4", "pending"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x (T-GY0)", "-m", "夹具里提到 T-GY4")
    cards = wb_reconcile.load_cards(root)
    stale_pending, stale_done, accounted = wb_reconcile.check(root, cards)
    assert stale_pending == []
    assert wb_reconcile.main(["--root", str(root)]) == 0

def _batch(root: Path, name: str, state: str, commit: str, declared: list[str]) -> None:
    """造一份批次围栏（`gates/diag/batch/<name>.json`）。"""
    d = root / "gates" / "diag" / "batch"
    d.mkdir(parents=True, exist_ok=True)
    body = {"id": name, "state": state, "declared": declared, "landed": {"commit": commit}}
    (d / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def test_done_card_in_landed_batch_is_accounted_not_yellow(tmp_path: Path) -> None:
    """done 卡没有点名 Task 提交，但它所在的批 `state=landed` ⇒ 认账（蓝），不报黄。

    这是 2026-10-14 `37a079c` 翻 14 张卡用的同一条判据：围栏状态说了算。
    """
    root = _repo(tmp_path, _card("204", "T-G311", "done"))
    _batch(root, "B-BATCH", "landed", "abc1234", ["204"])
    pending, stale, accounted = wb_reconcile.check(root, wb_reconcile.load_cards(root))
    assert not pending and not stale
    assert [x["id"] for x in accounted] == ["204"]
    assert accounted[0]["commit"] == "abc1234"


def test_unlanded_batch_proves_nothing_and_stays_yellow(tmp_path: Path) -> None:
    """批没落地（`state=draft`）就不算证据 —— 不能拿「登记了」冒充「落了」。"""
    root = _repo(tmp_path, _card("205", "T-G312", "done"))
    _batch(root, "B-DRAFT", "draft", "def5678", ["205"])
    pending, stale, accounted = wb_reconcile.check(root, wb_reconcile.load_cards(root))
    assert not pending and not accounted
    assert [x["id"] for x in stale] == ["205"]

