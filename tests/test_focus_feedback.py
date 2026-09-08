"""SR-F3 专注计时 + SR-F4 反馈/习惯 测试（AC 专注/反馈）。"""

from __future__ import annotations

import pytest

from timeflow.core import feedback as fb
from timeflow.core import focus as fc
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_start_plain_session(conn) -> None:
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    assert sid
    fc.finish_session(conn, sid, 1500, fc.STATUS_FINISHED)
    assert fc.today_focus_minutes(conn) == 25.0


def test_session_invalid_kind(conn) -> None:
    with pytest.raises(ValueError):
        fc.start_session(conn, kind="bogus")


def test_focus_bind_task(conn) -> None:
    from timeflow.core import tasks as tm

    t = tm.create_task(conn, "写高数")
    sid = fc.start_session(conn, task_id=t.id)
    fc.finish_session(conn, sid, 600, fc.STATUS_FINISHED)
    sessions = fc.sessions_by_task(conn, t.id)
    assert len(sessions) == 1 and sessions[0]["duration_sec"] == 600


def test_interrupt_status(conn) -> None:
    sid = fc.start_session(conn, kind=fc.KIND_TOMATO)
    fc.finish_session(conn, sid, 300, fc.STATUS_INTERRUPTED)
    assert fc.today_focus_minutes(conn) == 0.0  # 中断不计入完成投入


def test_habit_toggle_and_streak(conn) -> None:
    hid = fb.create_habit(conn, "早睡")
    assert fb.toggle_habit_log(conn, hid, "2026-09-08") is True
    assert fb.toggle_habit_log(conn, hid, "2026-09-09") is True
    assert fb.habit_streak(conn, hid, "2026-09-09") == 2
    assert fb.toggle_habit_log(conn, hid, "2026-09-09") is False
    assert fb.habit_streak(conn, hid, "2026-09-09") == 0


def test_daily_feedback_upsert(conn) -> None:
    fb.set_daily_feedback(
        conn, "2026-09-09", plan_note="计划A", executed="做了一半", gap_note="拖延"
    )
    g = fb.get_feedback(conn, "2026-09-09")
    assert g and g["plan_note"] == "计划A"
    fb.set_daily_feedback(conn, "2026-09-09", gap_note="改了差距")
    g2 = fb.get_feedback(conn, "2026-09-09")
    assert g2["gap_note"] == "改了差距"


def test_guard_default_block(conn) -> None:
    cfg = fc.GuardConfig(block_by_default=True, allowed={"微信"})
    assert fc.is_allowed(cfg, "微信") is True
    assert fc.is_allowed(cfg, "微博") is False


def test_do_not_disturb_window(conn) -> None:
    cfg = fc.GuardConfig(dnd_windows=["22:00-07:00"])
    assert fc.is_do_not_disturb(cfg, 23 * 60) is True   # 23:00
    assert fc.is_do_not_disturb(cfg, 8 * 60) is False   # 08:00
