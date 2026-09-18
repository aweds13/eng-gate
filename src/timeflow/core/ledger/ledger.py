"""B 系统·轻债务记账（SR-F2.3/2.7）。如实记逾期=债务（计数+天数/程度），不折算时间。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel

from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm

if TYPE_CHECKING:
    import sqlite3


class DebtItem(BaseModel):
    title: str
    due_date: str
    overdue_days: int
    degree: str  # 轻 / 中 / 重


class LedgerSummary(BaseModel):
    debt_count: int
    debt_items: list[DebtItem]
    invest_hours: float
    review_count: int = 0
    output_count: int = 0
    manual_hours: float = 0.0


class DayPoint(BaseModel):
    date: str
    focus_minutes: float


class WeekSummary(BaseModel):
    """周结算（OP-15）：一周内投入/产出/复习/手动投入 + 波动 + 债务快照。

    温和口径：只如实给数字与逐日走势，**不做目标对标、不给告警**。
    """

    start: str  # 周一
    end: str  # 周日
    focus_hours: float
    manual_hours: float
    review_count: int
    output_count: int
    debt_count: int  # 周日快照
    days: list[DayPoint]  # 7 天逐日专注（含 0，便于画走势）
    active_days: int  # 有专注记录的天数
    steady_note: str  # 一句温和提示（不施压）


def week_start(day: str) -> str:
    """该日期所在周的周一（本地日期，ISO）。"""
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def weekly_summary(conn: sqlite3.Connection, week_of: str | None = None) -> WeekSummary:
    """周结算（OP-15）：按本地周（周一→周日）聚合投入/产出/复习/手动投入，附债务快照与温和提示。

    口径与 `summary()` 一致：**全部只读事实层**（`focus.finished` 秒 / `review.completed` 去重 /
    `output.manual` 去重减 `output.retracted` / `invest.manual` 减 `invest.retracted`）。
    债务取**周日快照**（周末仍逾期者），不折算时间。
    """
    start = week_start(week_of or date.today().isoformat())
    start_date = date.fromisoformat(start)
    days = [(start_date + timedelta(days=i)).isoformat() for i in range(7)]
    end = days[-1]

    focus_sec = 0.0
    points: list[DayPoint] = []
    for day in days:
        sec = _focus_seconds(conn, day)
        focus_sec += sec
        points.append(DayPoint(date=day, focus_minutes=round(sec / 60.0, 1)))

    reviews: set[str] = set()
    for day in days:
        reviews |= _review_subjects(conn, day)

    outputs: set[str] = set()
    for day in days:
        outputs |= _output_entries(conn, day)

    manual_sec = sum(_manual_seconds(conn, day) for day in days)
    debt = len(tm.overdue_tasks(conn, end))
    active_days = sum(1 for p in points if p.focus_minutes > 0)

    return WeekSummary(
        start=start,
        end=end,
        focus_hours=round(focus_sec / 3600.0, 2),
        manual_hours=round(manual_sec / 3600.0, 2),
        review_count=len(reviews),
        output_count=len(outputs),
        debt_count=debt,
        days=points,
        active_days=active_days,
        steady_note=_steady_note(active_days, len(points)),
    )


def _steady_note(active_days: int, total_days: int) -> str:
    """一句温和结论：描述事实，不评价、不设目标、不告警（约定「温和不施压」）。"""
    if active_days == 0:
        return "这周还没有专注记录，随时可以从一小段开始。"
    if active_days == total_days:
        return f"这周 {total_days} 天都有专注，节奏很稳。"
    if active_days >= total_days - 2:
        return f"这周有 {active_days} 天在投入，基本连续。"
    return f"这周有 {active_days} 天在投入；断续也照实记，不必补课。"


def _focus_seconds(conn: sqlite3.Connection, day: str) -> float:
    rows = facts_mod.query(
        conn, kind="focus.finished", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    return sum(_num(row["value_num"]) for row in rows)


def _review_subjects(conn: sqlite3.Connection, day: str) -> set[str]:
    from timeflow.core import review as rv

    return rv.reviewed_today(conn, day)


def _output_entries(conn: sqlite3.Connection, day: str) -> set[str]:
    outputs = facts_mod.query(
        conn, kind="output.manual", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    retracted = {
        row["subject_id"]
        for row in facts_mod.query(
            conn, kind="output.retracted", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
        )
    }
    return {row["subject_id"] or row["id"] for row in outputs} - retracted


def _manual_seconds(conn: sqlite3.Connection, day: str) -> float:
    manual = facts_mod.query(
        conn, kind="invest.manual", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    retracted = {
        row["subject_id"]
        for row in facts_mod.query(
            conn, kind="invest.retracted", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
        )
    }
    return sum(_num(row["value_num"]) for row in manual if row["subject_id"] not in retracted)


def _degree(days: int, mild: int, medium: int) -> str:
    """债务程度分档：轻≤mild / 中≤medium / 重>medium（不折算时间）。"""
    if days <= mild:
        return "轻"
    if days <= medium:
        return "中"
    return "重"


def _num(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _manual_invests_today(conn: sqlite3.Connection, day: str) -> list[dict[str, object]]:
    """当日**有效**手动投入事实 = `invest.manual` − 当日 `invest.retracted`。"""
    manual = facts_mod.query(
        conn, kind="invest.manual", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    retracted = {
        row["subject_id"]
        for row in facts_mod.query(
            conn, kind="invest.retracted", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
        )
    }
    return [row for row in manual if row["subject_id"] not in retracted]


def summary(
    conn: sqlite3.Connection, today: str | None = None, mild: int = 3, medium: int = 7
) -> LedgerSummary:
    """顶部轻量摘要（AC-9）：债务项数/程度 + 投入时长 + 复习张数 + 产出条数 + 手动投入。

    投入（invest_hours）= 今日已完成的**专注**事实 / 3600（SR-F2.1 专注=投入；口径不含手动投入）。
    手动投入（manual_hours）= 今日有效 `invest.manual`（value_num=秒）/ 3600 —— **单列**，
    与 invest_hours 分开展示、不合并（2026-09-18 用户确认：手动投入单位=秒）。
    复习投入（review_count）= 今日有效 `review.completed` 主体数（复习完成=投入·维持）。
    产出（output_count）= 今日 `output.manual` 去重减 `output.retracted`
    （产出轴独立，不折算成投入）。
    事实来源：`facts` 表；按 occurred_at 归属当日，只读事实层（R1）。
    """
    t = today or date.today().isoformat()
    items: list[DebtItem] = []
    for task in tm.overdue_tasks(conn, t):
        if task.due_date is None:
            continue
        days = (date.fromisoformat(t) - date.fromisoformat(task.due_date)).days
        items.append(
            DebtItem(
                title=task.title,
                due_date=task.due_date,
                overdue_days=days,
                degree=_degree(days, mild, medium),
            )
        )
    items.sort(key=lambda x: x.overdue_days, reverse=True)
    # 投入：今日已完成的专注事实（第 1 步：读 facts，按完成时刻归属当日）
    finished_today = facts_mod.query(
        conn,
        kind="focus.finished",
        since=f"{t}T00:00:00",
        until=f"{t}T23:59:59",
    )
    invested_sec = sum(float(row["value_num"] or 0) for row in finished_today)
    # 复习投入：今日完成复习的不同卡片数（第 2 步子任务 3；第 5 步起扣除当日已撤销）
    from timeflow.core import review as rv

    review_subjects = rv.reviewed_today(conn, t)
    # 产出（第 5 步产出轴物化）：今日产出事实 - 已撤销的（按 entry_id 去重，独立于投入轴）
    outputs_today = facts_mod.query(
        conn, kind="output.manual", since=f"{t}T00:00:00", until=f"{t}T23:59:59"
    )
    retracted = {
        row["subject_id"]
        for row in facts_mod.query(
            conn, kind="output.retracted", since=f"{t}T00:00:00", until=f"{t}T23:59:59"
        )
    }
    output_entries = {
        row["subject_id"] or row["id"] for row in outputs_today
    } - retracted
    # 手动投入（第 5 步物化）：invest.manual（秒）− invest.retracted；单列，不并入 invest_hours
    manual_sec = sum(_num(row["value_num"]) for row in _manual_invests_today(conn, t))
    return LedgerSummary(
        debt_count=len(items),
        debt_items=items,
        invest_hours=round(invested_sec / 3600.0, 2),
        review_count=len(review_subjects),
        output_count=len(output_entries),
        manual_hours=round(manual_sec / 3600.0, 2),
    )
