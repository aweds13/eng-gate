"""B 系统·轻债务记账（SR-F2.3/2.7）。如实记逾期=债务（计数+天数/程度），不折算时间。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

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


def _degree(days: int, mild: int, medium: int) -> str:
    if days <= mild:
        return "轻"
    if days <= medium:
        return "中"
    return "重"


def summary(
    conn: sqlite3.Connection, today: str | None = None, mild: int = 3, medium: int = 7
) -> LedgerSummary:
    """顶部轻量摘要（AC-9）：今日债务项数 + 各逾期项天数/程度，投入时长(MVP 暂 0)。"""
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
    return LedgerSummary(debt_count=len(items), debt_items=items, invest_hours=0.0)
