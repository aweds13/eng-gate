"""第 2 步·专注线发事实：`focus.finished` → 当日反馈自动累加（FLOW-4 / F4 OP-17）。

覆盖：
- 订阅器把「正常结束」的专注累计进当日 feedback.focus_minutes；
- 只认 `focus.finished`：放弃/中断/暂停不进反馈（与投入口径一致）；
- 幂等：重复发布同一会话不重复计量；
- 读口径收拢：today_focus_minutes 与 summary 均来自 facts，与 feedback 一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import focus as fc
from timeflow.core import tasks as tm
from timeflow.core.focus import subscribers as focus_subscribers
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    facts_mod.clear()
    focus_subscribers.register(c)  # 模拟 app 启动时的接线
    yield c
    c.close()
    facts_mod.clear()


def test_focus_finished_accumulates_daily_feedback(conn: sqlite3.Connection) -> None:
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1800)

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 30.0


def test_focus_finished_accumulates_across_sessions(conn: sqlite3.Connection) -> None:
    for duration in (600, 900):
        sid = fc.start_session(conn, kind=fc.KIND_TOMATO)
        fc.finish_session(conn, sid, duration)

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 25.0  # (600+900)/60
    assert fc.today_focus_minutes(conn) == 25.0


@pytest.mark.parametrize(
    "status",
    [fc.STATUS_PAUSED, fc.STATUS_ABANDONED, fc.STATUS_INTERRUPTED],
)
def test_non_finished_status_does_not_touch_feedback(
    conn: sqlite3.Connection, status: str
) -> None:
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1200, status)

    assert fb.get_feedback(conn) is None  # 未产生投入，不写反馈
    assert fc.today_focus_minutes(conn) == 0.0


def test_feedback_rollup_is_idempotent(conn: sqlite3.Connection) -> None:
    """同一会话重复发布事实（历史回填/重放）不重复计量。"""
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1500)
    facts_mod.publish("focus.finished", {"session_id": sid, "duration_sec": 1500})

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 25.0


def test_feedback_rollup_preserves_user_notes(conn: sqlite3.Connection) -> None:
    """自动累加只动 focus_minutes，不覆盖用户填写的备注（OP-17）。"""
    fb.set_daily_feedback(conn, plan_note="计划A", executed="做了一半", gap_note="拖延")
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1800)

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 30.0
    assert got["plan_note"] == "计划A"
    assert got["executed"] == "做了一半"
    assert got["gap_note"] == "拖延"


def test_feedback_rollup_uses_completion_day(conn: sqlite3.Connection) -> None:
    """跨午夜按完成日归属（F3 OP-4 / SR-F2 R5）：昨日完成的专注不进今天。"""
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1800)
    # 把事实改成昨日完成，重放一次
    conn.execute(
        "UPDATE facts SET occurred_at = ? WHERE kind = 'focus.finished'",
        ("2026-09-17T23:59:00",),
    )
    conn.commit()
    facts_mod.publish(
        "focus.finished",
        {"session_id": sid, "duration_sec": 1800, "occurred_at": "2026-09-17T23:59:00"},
    )

    assert fc.today_focus_minutes(conn) == 0.0
    assert fb.get_feedback(conn, "2026-09-17") is not None
    assert fb.get_feedback(conn, "2026-09-17")["focus_minutes"] == 30.0  # type: ignore[index]


def test_task_bound_focus_counts_in_feedback(conn: sqlite3.Connection) -> None:
    """绑定任务的专注同样计入当日反馈（绑定与否只影响归因，不影响投入口径）。"""
    t = tm.create_task(conn, "写高数")
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN, task_id=t.id)
    fc.finish_session(conn, sid, 900)

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 15.0
    assert len(fc.sessions_by_task(conn, t.id)) == 1


def test_register_is_idempotent(conn: sqlite3.Connection) -> None:
    assert focus_subscribers.register(conn) is False  # fixture 已注册
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 600)

    got = fb.get_feedback(conn)
    assert got is not None
    assert got["focus_minutes"] == 10.0  # 未因重复注册而双计
