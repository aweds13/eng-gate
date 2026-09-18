"""第 6 步·周结算（OP-15 / SR-F2.5）：按本地周聚合投入/产出/复习/手动投入 + 债务快照。

口径：
- 周 = **周一 → 周日**（本地日期）；`week_of` 传该周任意一天即可定位；
- 全部只读事实层（与 `summary()` 同源），撤销类事实照常扣除；
- 债务取**周日快照**；
- 温和呈现：只给数字与逐日走势 + 一句如实提示，不做目标对标、不告警（约定「温和不施压」）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import review as rv
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _focus(conn: sqlite3.Connection, seconds: float, day: str) -> None:
    facts_mod.record(
        conn, kind="focus.finished", value_num=seconds, occurred_at=f"{day}T10:00:00"
    )


# ---- 周边界 ----

def test_week_start_is_monday() -> None:
    assert ledger.week_start("2026-09-18") == "2026-09-14"  # 周五 → 该周周一
    assert ledger.week_start("2026-09-14") == "2026-09-14"  # 周一 → 自身
    assert ledger.week_start("2026-09-20") == "2026-09-14"  # 周日 → 同一周


def test_week_start_crosses_month_and_year() -> None:
    assert ledger.week_start("2026-10-01") == "2026-09-28"  # 跨月
    assert ledger.week_start("2027-01-01") == "2026-12-28"  # 跨年


def test_week_bounds_and_seven_points(conn: sqlite3.Connection) -> None:
    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert (w.start, w.end) == ("2026-09-14", "2026-09-20")
    assert [p.date for p in w.days] == [
        "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
        "2026-09-19", "2026-09-20",
    ]


# ---- 聚合口径 ----

def test_week_focus_hours_and_daily_points(conn: sqlite3.Connection) -> None:
    _focus(conn, 1800.0, "2026-09-14")  # 30 分钟
    _focus(conn, 900.0, "2026-09-14")
    _focus(conn, 3600.0, "2026-09-18")

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.focus_hours == 1.75  # (1800+900+3600)/3600
    points = {p.date: p.focus_minutes for p in w.days}
    assert points["2026-09-14"] == 45.0
    assert points["2026-09-18"] == 60.0
    assert points["2026-09-15"] == 0.0  # 无记录也占位（便于画走势）
    assert w.active_days == 2


def test_week_excludes_other_weeks(conn: sqlite3.Connection) -> None:
    _focus(conn, 3600.0, "2026-09-13")  # 上周日
    _focus(conn, 3600.0, "2026-09-21")  # 下周一
    _focus(conn, 600.0, "2026-09-16")

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.focus_hours == 0.17  # 只有 600 秒（10 分钟）
    assert w.active_days == 1


def test_week_manual_invest_uses_seconds_and_skips_retracted(conn: sqlite3.Connection) -> None:
    facts_mod.record(
        conn,
        kind="invest.manual",
        subject_type="invest",
        subject_id="e1",
        value_num=1800.0,
        occurred_at="2026-09-16T09:00:00",
    )
    facts_mod.record(
        conn,
        kind="invest.manual",
        subject_type="invest",
        subject_id="e2",
        value_num=600.0,
        occurred_at="2026-09-16T09:30:00",
    )
    facts_mod.record(
        conn,
        kind="invest.retracted",
        subject_type="invest",
        subject_id="e2",
        value_num=600.0,
        occurred_at="2026-09-16T09:40:00",
    )

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.manual_hours == 0.5  # 只算未被撤销的那笔（1800 秒）


def test_week_counts_reviews_and_outputs(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "泰勒")
    facts_mod.record(
        conn,
        kind="review.completed",
        subject_type="review_item",
        subject_id=rid,
        value_num=0.0,
        value_text="泰勒",
        occurred_at="2026-09-17T20:00:00",
    )
    facts_mod.record(
        conn,
        kind="output.manual",
        subject_type="output",
        subject_id="o1",
        value_num=1.0,
        value_text="asset",
        occurred_at="2026-09-17T21:00:00",
    )

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.review_count == 1
    assert w.output_count == 1


def test_week_debt_snapshot_on_sunday(conn: sqlite3.Connection) -> None:
    tm.create_task(conn, "旧账", due_date="2026-09-10")

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.debt_count == 1  # 周日（09-20）仍逾期
    # 任务截止日在该周之后 → 该周周日快照无债务
    early = ledger.weekly_summary(conn, week_of="2026-09-01")
    assert early.debt_count == 0


def test_week_empty_state_is_friendly(conn: sqlite3.Connection) -> None:
    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.focus_hours == 0.0
    assert w.active_days == 0
    assert "随时" in w.steady_note  # 空态温和提示，不施压


def test_steady_note_describes_without_pressure(conn: sqlite3.Connection) -> None:
    for day in ("2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
                "2026-09-18", "2026-09-19", "2026-09-20"):
        _focus(conn, 600.0, day)

    w = ledger.weekly_summary(conn, week_of="2026-09-18")
    assert w.active_days == 7
    assert "稳" in w.steady_note
    for banned in ("目标", "应该", "警告", "失败", "落后"):
        assert banned not in w.steady_note


# ---- API ----

def test_api_weekly_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "w.db")))
    sid = client.post("/api/focus/start", json={"kind": "plain"}).json()["id"]
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800})

    w = client.get("/api/summary/weekly").json()
    assert w["focus_hours"] == 0.5
    assert len(w["days"]) == 7
    assert w["steady_note"]


def test_api_weekly_summary_bad_date(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    assert client.get("/api/summary/weekly?week_of=not-a-date").status_code == 400
    assert client.get("/api/summary/weekly?week_of=2026-09-18").status_code == 200
