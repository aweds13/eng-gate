"""第 1 步：ledger.summary 从 facts 读投入的测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core.ledger import ledger
from timeflow.storage import db


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_summary_invest_from_finished_fact(conn) -> None:  # type: ignore[no-untyped-def]
    facts_mod.record(
        conn,
        kind="focus.finished",
        value_num=1800.0,
        occurred_at="2026-09-18T10:00:00",
    )
    assert ledger.summary(conn, today="2026-09-18").invest_hours == 0.5


def test_summary_ignores_abandoned_and_other_days(conn) -> None:  # type: ignore[no-untyped-def]
    facts_mod.record(
        conn,
        kind="focus.abandoned",
        value_num=1800.0,
        occurred_at="2026-09-18T10:00:00",
    )
    facts_mod.record(
        conn,
        kind="focus.finished",
        value_num=3600.0,
        occurred_at="2026-09-17T10:00:00",
    )
    assert ledger.summary(conn, today="2026-09-18").invest_hours == 0.0


def test_summary_uses_finish_day(conn) -> None:  # type: ignore[no-untyped-def]
    # 23:50 开始、次日 00:10 结束：按完成时刻计入次日
    facts_mod.record(
        conn,
        kind="focus.finished",
        value_num=1200.0,
        occurred_at="2026-09-18T00:10:00",
    )
    assert ledger.summary(conn, today="2026-09-17").invest_hours == 0.0
    assert ledger.summary(conn, today="2026-09-18").invest_hours == 0.33


def test_summary_api_after_focus_finish(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "api.db")))
    sid = client.post("/api/focus/start", json={"kind": "plain"}).json()["id"]
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800})
    assert client.get("/api/summary").json()["invest_hours"] == 0.5


# ---- 习惯打卡（T-C1）：只报次数，不进投入小时 ----

def test_habit_count_is_reported_but_not_invested(conn) -> None:  # type: ignore[no-untyped-def]
    """用户口径（2026-09-19）：习惯**只报次数**、与投入并排；**不折算成小时**。"""
    from timeflow.core import feedback as fb

    hid = fb.create_habit(conn, "早睡")
    fb.toggle_habit_log(conn, hid, "2026-09-18")
    today = ledger.summary(conn, today="2026-09-18")
    assert today.habit_count == 1
    assert today.invest_hours == 0.0  # 打卡不折算成投入时间（已砍概念）
    assert ledger.summary(conn, today="2026-09-17").habit_count == 0  # 按天归属


def test_habit_count_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "habit.db")))
    hid = client.post("/api/habits", json={"name": "早起"}).json()["id"]
    client.post(f"/api/habits/{hid}/toggle")
    got = client.get("/api/summary").json()
    assert got["habit_count"] == 1 and got["invest_hours"] == 0.0


# ---- 完成收益（T-F6 / N3 口径「完成悬赏 = 收益/储蓄」）----
# 用户 2026-09-21 问「我怎么没看到你开发这个系统」时查出来的缺口：这条口径一直在约定层
# （`conventions.md:20`：储蓄 = 完成悬赏 / 复习完成），但**账本里没有收益读数**。


def test_gain_count_counts_completed_tasks_once(conn) -> None:  # type: ignore[no-untyped-def]
    from timeflow.core import tasks as tm

    a = tm.create_task(conn, title="做成一件")
    tm.complete_task(conn, a.id)
    tm.complete_task(conn, a.id)      # 重复完成（幂等）：只算一笔
    assert ledger.summary(conn).gain_count == 1


def test_gain_count_drops_uncompleted(conn) -> None:  # type: ignore[no-untyped-def]
    """完成又被撤销 → **不算收益**（撤销照扣，与 today_done 同一口径）。"""
    from timeflow.core import tasks as tm

    t = tm.create_task(conn, title="做完又反悔")
    tm.complete_task(conn, t.id)
    tm.uncomplete_task(conn, t.id)
    assert ledger.summary(conn).gain_count == 0


def test_gain_count_ignores_steps(conn) -> None:  # type: ignore[no-untyped-def]
    """**只算任务、不算子步骤**：完成一步是"推进"，不是"收了一笔悬赏"。

    注意：**只有一个步骤时，完成它会把父任务也带成完成**（N10 的联动），所以这里给两个步骤 ——
    只完成其中一个时，父任务还没完成，收益必须是 0。
    """
    from timeflow.core import tasks as tm

    parent = tm.create_task(conn, title="大任务")
    step_a = tm.create_task(conn, title="第一步", parent_id=parent.id)
    tm.create_task(conn, title="第二步", parent_id=parent.id)
    tm.complete_task(conn, step_a.id)
    assert ledger.summary(conn).gain_count == 0, "只完成子步骤不该记成收益"
    assert tm.get_task(conn, parent.id).status != tm.STATUS_DONE, "还剩一步，父任务不该完成"


def test_gain_count_api_and_weekly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "gain.db")))
    tid = client.post("/api/tasks", json={"title": "一件事"}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    assert client.get("/api/summary").json()["gain_count"] == 1
    assert client.get("/api/summary/weekly").json()["gain_count"] == 1
