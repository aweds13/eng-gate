"""第一版缺口测试：AC-6 多分组 + AC-4 无due移入逾期。"""

from __future__ import annotations

import pytest

from timeflow.core import tasks as tm
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_task_multi_groups(conn) -> None:
    """AC-6：任务可归多个分组，且分组计数正确。"""
    t = tm.create_task(conn, "数学视频", is_myday=True)
    tm.set_task_groups(conn, t.id, ["主线", "自媒体"])
    assert set(tm.get_task_groups(conn, t.id)) == {"主线", "自媒体"}

    groups = {g["name"]: g["task_count"] for g in tm.list_groups(conn)}
    assert groups["主线"] == 1
    assert groups["自媒体"] == 1


def test_group_name_unique_reuse(conn) -> None:
    """同名分组不复建，复用同 id。"""
    g1 = tm.create_group(conn, "财务")
    g2 = tm.create_group(conn, "财务")
    assert g1 == g2


def test_overdue_myday_no_due_moves(conn) -> None:
    """AC-4：无截止日但昨日未完成的 My Day 任务，今日自动移入逾期栏。"""
    t = tm.create_task(conn, "昨日待办", is_myday=True)
    # 模拟昨日创建：把 created_at 改到昨天
    conn.execute(
        "UPDATE tasks SET created_at = ? WHERE id = ?",
        ("2026-09-08T23:00:00", t.id),
    )
    conn.commit()
    assert t.id in [x.id for x in tm.overdue_tasks(conn, "2026-09-09")]


def test_myday_today_not_overdue(conn) -> None:
    """今日创建的 My Day 任务不进逾期栏。"""
    t = tm.create_task(conn, "今日待办", is_myday=True)
    assert t.id not in [x.id for x in tm.overdue_tasks(conn, "2026-09-09")]
