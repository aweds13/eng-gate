"""数据洞察聚合（SR-F2.5/F2.7、SR-F4.2 的可视化数据底座）。

分工（参考 `复盘/写法参考-feat-ui-refactor分支.md` 的取向）：**后端只出数据，前端负责图形**。
本模块不画图、不含 UI 概念，只按天/按分组把事实层聚合好；口径与 `ledger.summary()` 一致
（只读 `facts`；撤销类事实照常扣除；债务不折算时间）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel

from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm

if TYPE_CHECKING:
    import sqlite3

MAX_TREND_DAYS = 90
DEFAULT_TREND_DAYS = 30


class DayInsight(BaseModel):
    """一天的时序点（近 N 天走势用）。"""

    date: str
    focus_minutes: float
    manual_minutes: float = 0.0
    review_count: int = 0
    output_count: int = 0
    habit_done: int = 0
    debt_count: int = 0  # 当日快照：未完成且当时已逾期


class GroupInsight(BaseModel):
    """某个任务分组（领域）的投入分布。"""

    group: str
    focus_hours: float
    manual_hours: float = 0.0
    task_count: int = 0


def daily_insights(
    conn: sqlite3.Connection, days: int = DEFAULT_TREND_DAYS
) -> list[DayInsight]:
    """近 `days` 天（含今天）的逐日时序：专注/手动投入/复习/产出/习惯打卡/债务快照。

    - 归属按事实 `occurred_at` 的本地日期；无记录的日子也返回 0（走势连续）。
    - 习惯打卡读 `habit_logs`（打卡是"发生了什么"的轻记录，不折算投入）。
    - 债务为**当日快照**：`overdue_tasks(day)` 的项数（已删/归档不计）。
    """
    total = max(1, min(int(days), MAX_TREND_DAYS))
    start = date.today() - timedelta(days=total - 1)
    out: list[DayInsight] = []
    for i in range(total):
        day = (start + timedelta(days=i)).isoformat()
        out.append(
            DayInsight(
                date=day,
                focus_minutes=round(_focus_seconds(conn, day) / 60.0, 1),
                manual_minutes=round(_manual_seconds(conn, day) / 60.0, 1),
                review_count=len(_review_subjects(conn, day)),
                output_count=len(_output_entries(conn, day)),
                habit_done=_habit_done(conn, day),
                debt_count=len(tm.overdue_tasks(conn, day)),
            )
        )
    return out


def group_insights(
    conn: sqlite3.Connection, days: int = DEFAULT_TREND_DAYS
) -> list[GroupInsight]:
    """近 `days` 天的投入按任务分组（领域）分布 —— 回答「时间花在哪些方向上」。

    口径与边界：
    - 只统计**绑定了任务**的专注事实（未绑定专注不计入任何分组，避免制造假归因）；
      按 `subject_id`(=task_id) 汇总，再经 `task_groups` 摊到分组。
    - 一个任务可属**多个分组**（SR-F1.3），因此各组之和**可能大于**总投入 —— 这是如实反映，
      不强行归一；前端需注明「可重复计数」。
    - 未归任何分组的任务投入归入「未分组」桶。
    """
    total = max(1, min(int(days), MAX_TREND_DAYS))
    start = (date.today() - timedelta(days=total - 1)).isoformat()
    rows = facts_mod.query(conn, kind="focus.finished", since=f"{start}T00:00:00")
    # task_id → 秒
    per_task: dict[str, float] = {}
    for row in rows:
        if row["subject_type"] != "task" or not row["subject_id"]:
            continue
        tid = str(row["subject_id"])
        value = row["value_num"]
        per_task[tid] = per_task.get(tid, 0.0) + (
            float(value) if isinstance(value, (int, float)) else 0.0
        )

    buckets: dict[str, dict[str, float]] = {}
    for tid, seconds in per_task.items():
        try:
            names = tm.get_task_groups(conn, tid)
        except KeyError:  # 任务被彻底清理：仍如实计入「未分组」
            names = []
        for name in names or ["未分组"]:
            slot = buckets.setdefault(name, {"sec": 0.0, "tasks": 0.0})
            slot["sec"] += seconds
            slot["tasks"] += 1

    # 手动投入无法归因到任务/分组（口径：手动投入不绑定任务）→ 只体现在总投入里
    result = [
        GroupInsight(
            group=name,
            focus_hours=round(slot["sec"] / 3600.0, 2),
            manual_hours=0.0,
            task_count=int(slot["tasks"]),
        )
        for name, slot in buckets.items()
    ]
    result.sort(key=lambda g: g.focus_hours, reverse=True)
    return result


def _focus_seconds(conn: sqlite3.Connection, day: str) -> float:
    rows = facts_mod.query(
        conn, kind="focus.finished", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    return sum(_num(row["value_num"]) for row in rows)


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


def _habit_done(conn: sqlite3.Connection, day: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM habit_logs WHERE date = ? AND done = 1", (day,)
    ).fetchone()
    return int(row["n"] or 0)


def _num(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
