"""SR-F7 团队/AI + SR-F8 备忘录/知识资产 测试（AC 团队/备忘录）。"""

from __future__ import annotations

import pytest

from timeflow.core import memo as memo
from timeflow.core import tasks as tm
from timeflow.core import team as team
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_team_assign_and_status(conn) -> None:
    t = tm.create_task(conn, "做PPT")
    aid = team.assign_task(conn, t.id, assignee="同学A", assigner="me", note="周五交")
    assert aid
    team.update_assignment_status(conn, aid, "in_progress")
    all_a = team.assignments(conn)
    assert all_a[0]["status"] == "in_progress"
    mine = team.assignments(conn, assignee="同学A")
    assert len(mine) == 1 and mine[0]["task_id"] == t.id


def test_team_bad_status(conn) -> None:
    t = tm.create_task(conn, "X")
    aid = team.assign_task(conn, t.id, assignee="B", assigner="me")
    with pytest.raises(ValueError):
        team.update_assignment_status(conn, aid, "bogus")


def test_memo_create_and_list(conn) -> None:
    _ = memo.create_memo(conn, "想到一个数学题", ref_handle="Vault/数学/想法.md")
    memos = memo.list_memos(conn)
    assert len(memos) == 1 and memos[0]["text"] == "想到一个数学题"
    assert memos[0]["ref_handle"] == "Vault/数学/想法.md"


def test_memo_required_text(conn) -> None:
    with pytest.raises(ValueError):
        memo.create_memo(conn, "   ")


def test_ledger_output_invest(conn) -> None:
    oid = memo.add_output_entry(conn, value=1.0, kind="asset", note="数学笔记#3")
    iid = memo.add_invest_entry(conn, value=25.0, kind="focus", note="番茄")
    assert oid and iid
    rows = conn.execute("SELECT axis, kind FROM ledger_entries").fetchall()
    axes = {(r["axis"], r["kind"]) for r in rows}
    assert ("output", "asset") in axes
    assert ("invest", "focus") in axes
