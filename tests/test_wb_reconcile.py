r"""`tools/wb_reconcile.py` 的派生对账判据（卡 A318 重写）。

A318 之前，对账是「拿台账里的 `status` 字段跟 git 比」，于是同一件事有三份事实
（status / 提交 trailer / 批次围栏）。现在**账本只存计划**：状态全部由
`wb_status.derive_status()` 从 git 派生。

本文件钉住派生口径（别只测 happy path）：

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 提交 trailer ⇒ done | 有 `Task:` 的提交就是已落地 | 派生漏读 trailer |
| ② 没提交 ⇒ pending | 不许拿"登记了"冒充"落了" | 把 pending 当 done |
| ③ 孤儿号 ⇒ 红 | git 有 `Task:`、台账没条目 | 吞掉孤儿（A315/A316 事故形状） |
| ③′ 台账有条目 ⇒ 不红 | 号在台账 `[entries]` 里且带 evidence | 只读队列（A394：217 条假红） |
| ④ 正文提到不算 | 只认标题里的 trailer | 正则扫了整条 commit message |
| ⑤ 围栏 landed ⇒ done | 批收口也是证据 | 只认提交、不认围栏 |
| ⑥ 围栏 draft ⇒ pending | 未落地的批不算证据 | 拿 draft 当 landed |
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


def _card(cid: str, task: str) -> str:
    """一张卡的**计划**（id + task；不再有 status 字段 —— 那是派生出来的）。"""
    return f"[[cards]]{NL}id = {cid!r}{NL}task = {task!r}{NL}"


def _batch(root: Path, name: str, state: str, commit: str, declared: list[str]) -> None:
    """造一份批次围栏（`gates/diag/batch/<name>.json`）。"""
    d = root / "gates" / "diag" / "batch"
    d.mkdir(parents=True, exist_ok=True)
    body = {"id": name, "state": state, "declared": declared, "landed": {"commit": commit}}
    (d / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def _status_of(rows: list[dict], cid: str) -> str:
    hit = next(r for r in rows if r["id"] == cid)
    return str(hit["status"])


def test_commit_trailer_derives_done(tmp_path: Path) -> None:
    """① 历史里有 `Task: T-GX1` 的提交 ⇒ 派生 done，且不报孤儿。"""
    root = _repo(tmp_path, _card("A1", "T-GX1"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x", "-m", "Task: T-GX1")
    rows, orphans, _marks = wb_reconcile.check(root)
    assert _status_of(rows, "A1") == "done"
    assert orphans == []
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_no_commit_derives_pending(tmp_path: Path) -> None:
    """② 只有计划、没有提交 ⇒ pending（不许靠人写 status）。"""
    root = _repo(tmp_path, _card("A2", "T-GX2"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "chore: init")  # 空仓 ⇒ 判据退 2，先给一笔底
    rows, orphans, _marks = wb_reconcile.check(root)
    assert _status_of(rows, "A2") == "pending"
    assert orphans == []
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_orphan_task_is_red(tmp_path: Path) -> None:
    """③ git 里挂了 `Task:`、台账没有条目 ⇒ 孤儿 ⇒ 退 1。

    ★ 这正是 A315/A316 的事故形状：卡落了，台账却没那条。
    """
    root = _repo(tmp_path, _card("A3", "T-GX3"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: y", "-m", "Task: T-GX9")
    rows, orphans, _marks = wb_reconcile.check(root)
    assert "T-GX9" in orphans, orphans
    assert wb_reconcile.main(["--root", str(root)]) == 1


def test_orphan_cleared_by_ledger_entry(tmp_path: Path) -> None:
    """③′ 号**不在队列**、但在台账 `[entries]` 里且带 evidence ⇒ 不是孤儿、退 0。

    ★ 卡 A394：判词一直写「台账没有该任务」，可实现只读了队列 `docs/workbacklog.toml`。
    口径是**两本账**（队列 ∪ `docs/traceability.toml` 的 `[entries]`，必须有 evidence、
    含 `docs/traceability.d` 分片），唯一真源在 `tools/wb_queue_audit.py` 的 docstring。
    反向：把 `wb_status.orphan_tasks` 里的 `ledger_marks` 去掉 ⇒ 这条红（真仓 217 条假红）。
    """
    root = _repo(tmp_path, _card("A5", "T-GX5"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: z", "-m", "Task: T-GX9")
    (root / "docs" / "traceability.toml").write_text(
        f'[entries."T-GX9"]{NL}id = "T-GX9"{NL}status = "done"{NL}'
        f'evidence = ["file:tools/x.py"]{NL}', encoding="utf-8")
    rows, orphans, _marks = wb_reconcile.check(root)
    assert orphans == [], orphans
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_body_mention_is_not_a_commit(tmp_path: Path) -> None:
    """④ **只认 trailer**：正文里提到任务号 ⇒ 不算落地。"""
    root = _repo(tmp_path, _card("A4", "T-GY4"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x (T-GY0)",
         "-m", "夹具里提到 T-GY4，但标题的 trailer 是 T-GY0")
    rows, orphans, _marks = wb_reconcile.check(root)
    assert _status_of(rows, "A4") == "pending"
    assert orphans == []


def test_landed_batch_derives_done(tmp_path: Path) -> None:
    """⑤ 批 `state=landed` ⇒ 派生 done（围栏也是证据）。"""
    root = _repo(tmp_path, _card("204", "T-G311"))
    _batch(root, "B-BATCH", "landed", "abc1234", ["204"])
    rows, orphans, _marks = wb_reconcile.check(root)
    hit = next(r for r in rows if r["id"] == "204")
    assert hit["status"] == "done", hit
    assert "B-BATCH" in hit["via"], hit
    assert orphans == []


def test_draft_batch_proves_nothing(tmp_path: Path) -> None:
    """⑥ 批没落地（`state=draft`）⇒ 仍是 pending。"""
    root = _repo(tmp_path, _card("205", "T-G312"))
    _batch(root, "B-DRAFT", "draft", "def5678", ["205"])
    rows, _orphans, _marks = wb_reconcile.check(root)
    assert _status_of(rows, "205") == "pending"
