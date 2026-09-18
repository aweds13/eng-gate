"""B 系统·轻债务记账（SR-F2.3/2.7）。如实记逾期=债务（计数+天数/程度），不折算时间。"""

from __future__ import annotations

from datetime import date
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


def _degree(days: int, mild: int, medium: int) -> str:
    if days <= mild:
        return "轻"
    if days <= medium:
        return "中"
    return "重"


def summary(
    conn: sqlite3.Connection, today: str | None = None, mild: int = 3, medium: int = 7
) -> LedgerSummary:
    """顶部轻量摘要（AC-9）：今日债务项数 + 各逾期项天数/程度，投入时长 + 复习投入张数 + 产出条数。

    投入（invest_hours）= 今日已完成的专注事实 / 3600（SR-F2.1 专注=投入）。
    复习投入（review_count）= 今日不同的 `review.completed` 主体数（复习完成=投入·维持；
    同一天同卡只算一次，对应 SR-F6 边界「重复完成幂等」）。
    产出（output_count）= 今日 `output.manual` 去重后减去 `output.retracted`
    （产出轴独立，不折算成投入）。
    事实来源：`facts` 表；按 occurred_at（完成时刻）归属当日，只读事实层（R1）。
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
    return LedgerSummary(
        debt_count=len(items),
        debt_items=items,
        invest_hours=round(invested_sec / 3600.0, 2),
        review_count=len(review_subjects),
        output_count=len(output_entries),
    )
