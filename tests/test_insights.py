"""第 7 步·更细可视化数据底座（SR-F2.7 / SR-F4.2 / OP-19）。

分工：**后端只出数据，前端出图形**（见 `复盘/写法参考-feat-ui-refactor分支.md` 的取向）。
覆盖：
- 逐日时序 `daily_insights`：专注/手动/复习/产出/习惯/债务快照，无记录日也占位；
- 分组分布 `group_insights`：只统计绑定任务的专注，按 task_groups 摊到分组；
  多分组会重复计数（如实）；
- 习惯列表 `list_habits`：补上此前缺失的列表接口（前端不再靠 sessionStorage 记 id）；
- API 与 days 边界（1~90）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import insights
from timeflow.core import tasks as tm
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


def _focus_on(
    conn: sqlite3.Connection, day: str, seconds: float, task_id: str | None = None
) -> None:
    facts_mod.record(
        conn,
        kind="focus.finished",
        subject_type="task" if task_id else "focus_session",
        subject_id=task_id or f"s-{day}",
        value_num=seconds,
        occurred_at=f"{day}T10:00:00",
    )


# ---- 逐日时序 ----

def test_daily_insights_length_and_zero_fill(conn: sqlite3.Connection) -> None:
    rows = insights.daily_insights(conn, days=7)
    assert len(rows) == 7
    assert rows[-1].date == date.today().isoformat()  # 最后一天是今天
    assert all(r.focus_minutes == 0.0 for r in rows)  # 无数据也占位（走势连续）


def test_daily_insights_aggregates_each_axis(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    _focus_on(conn, today, 1800.0)  # 30 分钟
    conn.execute(
        "INSERT INTO habit_logs (habit_id, date, done) VALUES ('h1', ?, 1)", (today,)
    )
    facts_mod.record(
        conn,
        kind="review.completed",
        subject_type="review_item",
        subject_id="r1",
        value_num=0.0,
        occurred_at=f"{today}T11:00:00",
    )
    facts_mod.record(
        conn,
        kind="output.manual",
        subject_type="output",
        subject_id="o1",
        value_num=1.0,
        occurred_at=f"{today}T12:00:00",
    )
    facts_mod.record(
        conn,
        kind="invest.manual",
        subject_type="invest",
        subject_id="i1",
        value_num=600.0,
        occurred_at=f"{today}T13:00:00",
    )
    conn.commit()

    point = insights.daily_insights(conn, days=1)[0]
    assert point.focus_minutes == 30.0
    assert point.manual_minutes == 10.0
    assert point.review_count == 1
    assert point.output_count == 1
    assert point.habit_done == 1


def test_daily_insights_debt_snapshot_per_day(conn: sqlite3.Connection) -> None:
    """债务是逐日快照：截止日当天及之后计入，截止日之前为 0。"""
    today = date.today()
    due = (today - timedelta(days=2)).isoformat()
    tm.create_task(conn, "旧账", due_date=due)

    rows = {r.date: r.debt_count for r in insights.daily_insights(conn, days=5)}
    assert rows[(today - timedelta(days=4)).isoformat()] == 0  # 截止日之前
    assert rows[(today - timedelta(days=1)).isoformat()] == 1  # 截止日之后
    assert rows[today.isoformat()] == 1  # 今天仍欠


def test_daily_insights_respects_retraction(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    facts_mod.record(
        conn,
        kind="invest.manual",
        subject_type="invest",
        subject_id="i9",
        value_num=900.0,
        occurred_at=f"{today}T09:00:00",
    )
    facts_mod.record(
        conn,
        kind="invest.retracted",
        subject_type="invest",
        subject_id="i9",
        value_num=900.0,
        occurred_at=f"{today}T09:30:00",
    )

    assert insights.daily_insights(conn, days=1)[0].manual_minutes == 0.0


# ---- 分组分布 ----

def test_heatmap_length_and_metrics(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    _focus_on(conn, today, 1800.0)
    facts_mod.record(
        conn,
        kind="output.manual",
        subject_type="output",
        subject_id="o1",
        value_num=1.0,
        occurred_at=f"{today}T12:00:00",
    )

    cells = insights.heatmap(conn, days=30)
    assert len(cells) == 30
    assert cells[-1].date == today
    assert cells[-1].focus_minutes == 30.0
    assert cells[-1].output_count == 1
    assert all(c.debt_count == 0 for c in cells)


def test_heatmap_carries_debt_snapshot(conn: sqlite3.Connection) -> None:
    """时间热力图的债务维度：截止日之后逐日点亮。"""
    today = date.today()
    due = (today - timedelta(days=2)).isoformat()
    tm.create_task(conn, "旧账", due_date=due)

    cells = {c.date: c.debt_count for c in insights.heatmap(conn, days=7)}
    assert cells[(today - timedelta(days=4)).isoformat()] == 0
    assert cells[today.isoformat()] == 1


def test_heatmap_caps_at_400(conn: sqlite3.Connection) -> None:
    assert len(insights.heatmap(conn, days=1000)) == insights.MAX_HEATMAP_DAYS


def test_group_insights_buckets_by_group(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    a = tm.create_task(conn, "写论文")
    b = tm.create_task(conn, "刷题")
    tm.set_task_groups(conn, a.id, ["学业"])
    tm.set_task_groups(conn, b.id, ["学业", "竞赛"])
    _focus_on(conn, today, 3600.0, task_id=a.id)
    _focus_on(conn, today, 1800.0, task_id=b.id)

    got = {g.group: g for g in insights.group_insights(conn, days=7)}
    assert got["学业"].focus_hours == 1.5  # 1.0 + 0.5
    assert got["竞赛"].focus_hours == 0.5  # 多分组如实重复计入
    assert got["学业"].task_count == 2
    assert got["竞赛"].task_count == 1


def test_group_insights_ungrouped_bucket(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    t = tm.create_task(conn, "没分类的事")
    _focus_on(conn, today, 1800.0, task_id=t.id)

    got = insights.group_insights(conn, days=7)
    assert [g.group for g in got] == ["未分组"]
    assert got[0].focus_hours == 0.5


def test_group_insights_ignores_unbound_focus(conn: sqlite3.Connection) -> None:
    """未绑定任务的专注不计入任何分组（不制造假归因）。"""
    today = date.today().isoformat()
    _focus_on(conn, today, 3600.0)  # 无 task_id
    assert insights.group_insights(conn, days=7) == []


def test_group_insights_excludes_old_facts(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    t = tm.create_task(conn, "老账")
    tm.set_task_groups(conn, t.id, ["学业"])
    old = (date.today() - timedelta(days=30)).isoformat()
    _focus_on(conn, old, 3600.0, task_id=t.id)
    _focus_on(conn, today, 600.0, task_id=t.id)

    got = insights.group_insights(conn, days=7)
    assert got[0].focus_hours == 0.17  # 只算窗口内的 600 秒


def test_group_insights_sorted_desc(conn: sqlite3.Connection) -> None:
    today = date.today().isoformat()
    small = tm.create_task(conn, "小")
    big = tm.create_task(conn, "大")
    tm.set_task_groups(conn, small.id, ["小类"])
    tm.set_task_groups(conn, big.id, ["大类"])
    _focus_on(conn, today, 600.0, task_id=small.id)
    _focus_on(conn, today, 3600.0, task_id=big.id)

    assert [g.group for g in insights.group_insights(conn, days=7)] == ["大类", "小类"]


# ---- 习惯列表（此前缺失的接口）----

def test_list_habits_with_streak_and_logs(conn: sqlite3.Connection) -> None:
    hid = fb.create_habit(conn, "早睡")
    today = date.today()
    for i in range(3):
        fb.toggle_habit_log(conn, hid, (today - timedelta(days=i)).isoformat())

    rows = fb.list_habits(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == hid
    assert rows[0]["name"] == "早睡"
    assert rows[0]["streak"] == 3
    assert len(rows[0]["logs"]) == 3


def test_list_habits_empty(conn: sqlite3.Connection) -> None:
    assert fb.list_habits(conn) == []


# ---- API ----

def test_api_insights_daily_and_groups(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "i.db")))
    tid = client.post("/api/tasks", json={"title": "写论文", "is_myday": True}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"groups": ["学业"]})
    sid = client.post("/api/focus/start", json={"kind": "plain", "task_id": tid}).json()["id"]
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800})

    daily = client.get("/api/insights/daily?days=7").json()
    assert len(daily) == 7
    assert daily[-1]["focus_minutes"] == 30.0

    groups = client.get("/api/insights/groups?days=7").json()
    assert groups == [{"group": "学业", "focus_hours": 0.5, "manual_hours": 0.0, "task_count": 1}]


def test_api_insights_days_bounds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    assert client.get("/api/insights/daily?days=0").status_code == 400
    assert client.get("/api/insights/daily?days=91").status_code == 400
    assert client.get("/api/insights/groups?days=0").status_code == 400
    assert client.get("/api/insights/daily?days=1").status_code == 200


def test_api_insights_heatmap(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "hm.db")))
    cells = client.get("/api/insights/heatmap?days=14").json()
    assert len(cells) == 14
    assert set(cells[0]) >= {
        "date", "focus_minutes", "manual_minutes", "review_count", "output_count", "debt_count"
    }
    assert client.get("/api/insights/heatmap?days=0").status_code == 400
    assert client.get("/api/insights/heatmap?days=401").status_code == 400
    assert client.get("/api/insights/heatmap?days=365").status_code == 200


def test_api_habits_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "h.db")))
    assert client.get("/api/habits").json() == []
    hid = client.post("/api/habits", json={"name": "早睡"}).json()["id"]
    client.post(f"/api/habits/{hid}/toggle")

    rows = client.get("/api/habits").json()
    assert [r["name"] for r in rows] == ["早睡"]
    assert rows[0]["streak"] == 1


# ---- 学业投入 vs 自学投入（SR-F5.1b / T-C10，2026-09-20 用户定口径）----
# 口径：**只统计"绑定了任务"的专注** —— 挂课程 = 学业、没挂课程 = 自学、
# 未绑定（或任务已被彻底清理）**单列**（不猜它算哪一类）。手动投入不参与。


def test_academic_vs_self_splits_by_course_link(conn: sqlite3.Connection) -> None:
    course = conn.execute(
        "INSERT INTO courses (id, name, credits) VALUES ('c1', '高等数学', 4)"
    )
    course.fetchone()
    conn.commit()
    today = date.today().isoformat()
    school = tm.create_task(conn, title="高数作业", task_type="作业", course_id="c1")
    selfstudy = tm.create_task(conn, title="读闲书")
    _focus_on(conn, today, 3600.0, school.id)      # 1h 学业
    _focus_on(conn, today, 1800.0, selfstudy.id)   # 0.5h 自学

    split = insights.academic_vs_self(conn, days=7)
    assert split.academic_hours == 1.0 and split.self_hours == 0.5
    assert (split.academic_tasks, split.self_tasks) == (1, 1)
    assert split.unbound_hours == 0.0, "都绑了任务，不该有未绑定那部分"


def test_academic_vs_self_keeps_unbound_separate(conn: sqlite3.Connection) -> None:
    """没绑定任务的专注**不归入任何一边** —— 不制造假归因（与 group_insights 同一取向）。"""
    today = date.today().isoformat()
    _focus_on(conn, today, 900.0)                  # 未绑定任务
    split = insights.academic_vs_self(conn, days=7)
    assert split.academic_hours == 0.0 and split.self_hours == 0.0
    assert split.unbound_hours == 0.25, "未绑定专注应单列，别偷偷算进自学"


def test_academic_vs_self_task_purged_counts_as_unbound(conn: sqlite3.Connection) -> None:
    """任务被**彻底清理**后，历史专注仍在、但不猜它属于哪一类 → 计入未绑定。"""
    today = date.today().isoformat()
    task = tm.create_task(conn, title="临时任务")
    _focus_on(conn, today, 600.0, task.id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
    conn.commit()
    split = insights.academic_vs_self(conn, days=7)
    assert split.academic_hours == 0.0 and split.self_hours == 0.0
    assert split.unbound_hours == round(600.0 / 3600.0, 2)


def test_academic_vs_self_ignores_manual_invest(conn: sqlite3.Connection) -> None:
    """手动投入按口径就不绑定任务 → 不参与这张图（否则会和分组图口径打架）。"""
    today = date.today().isoformat()
    facts_mod.record(
        conn, kind="invest.manual", subject_type="invest", subject_id="i1",
        value_num=7200.0, occurred_at=f"{today}T09:00:00",
    )
    split = insights.academic_vs_self(conn, days=7)
    assert (split.academic_hours, split.self_hours, split.unbound_hours) == (0.0, 0.0, 0.0)


def test_api_academic_vs_self_days_bounds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "avs.db")))
    got = client.get("/api/insights/academic-vs-self?days=30")
    assert got.status_code == 200, got.text
    assert set(got.json()) >= {
        "days", "academic_hours", "self_hours", "unbound_hours", "academic_tasks", "self_tasks"
    }
    assert client.get("/api/insights/academic-vs-self?days=0").status_code == 400
    assert client.get("/api/insights/academic-vs-self?days=91").status_code == 400
