"""任务领域逻辑单测（对应 AC-1/2/3/4/5/6/7/8）。"""

from __future__ import annotations

import pytest

from timeflow.core import tasks as tm
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_create_and_get(conn) -> None:
    t = tm.create_task(conn, "写数学笔记", due_date="2026-09-01", is_myday=True)
    got = tm.get_task(conn, t.id)
    assert got.title == "写数学笔记"
    assert got.is_myday is True
    assert got.status in (tm.STATUS_TODO, tm.STATUS_OVERDUE)


def test_title_required(conn) -> None:
    with pytest.raises(ValueError):
        tm.create_task(conn, "   ")


def test_update_status(conn) -> None:
    t = tm.create_task(conn, "A")
    t2 = tm.update_task(conn, t.id, status=tm.STATUS_DONE)
    assert t2.status == tm.STATUS_DONE


def test_overdue_detection(conn) -> None:
    t = tm.create_task(conn, "旧作业", due_date="2020-01-01", is_myday=True)
    over = tm.overdue_tasks(conn, "2026-09-08")
    assert any(x.id == t.id for x in over)


def test_myday_add_remove(conn) -> None:
    t = tm.create_task(conn, "A", is_myday=True)
    assert t.id in [x.id for x in tm.myday_tasks(conn)]
    tm.update_task(conn, t.id, is_myday=False)
    assert t.id not in [x.id for x in tm.myday_tasks(conn)]


def test_subtask_parent_auto_complete(conn) -> None:
    p = tm.create_task(conn, "project")
    c1 = tm.create_task(conn, "step1", parent_id=p.id)
    c2 = tm.create_task(conn, "step2", parent_id=p.id)
    tm.complete_task(conn, c1.id)
    with pytest.raises(ValueError):
        tm.complete_task(conn, p.id)  # 还有子任务未完成
    tm.complete_task(conn, c2.id)
    assert tm.complete_task(conn, p.id).status == tm.STATUS_DONE


def test_repeat_generates_next(conn) -> None:
    t = tm.create_task(conn, "daily", due_date="2026-09-01", repeat_days=3)
    tm.update_task(conn, t.id, status=tm.STATUS_DONE)
    assert tm.process_repeats(conn) == 1
