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
MAX_HEATMAP_DAYS = 400  # 一年多一点（含闰年与对齐周一起点）
DEFAULT_HEATMAP_DAYS = 365


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


class HeatmapCell(BaseModel):
    """时间热力图的一天（SR-NF3 / N32：债务/储蓄「曲线 + 时间热力图」，也用于投入与产出）。"""

    date: str
    focus_minutes: float
    manual_minutes: float = 0.0
    review_count: int = 0
    output_count: int = 0
    debt_count: int = 0


class AcademicSplit(BaseModel):
    """学业投入 vs 自学投入（SR-F5.1b / T-C10：与自学时间线对照）。

    口径（2026-09-20 用户定）：**只统计"绑定了任务"的专注** ——
    挂了课程的任务 = 学业投入，挂了任务但没挂课程 = 自学投入，
    未绑定任务（或任务已被彻底清理）的专注**单列** —— 不猜它算哪一类（不制造假归因）。
    手动投入不参与（它按口径就不绑定任务，见 `group_insights`）。
    """

    days: int
    academic_hours: float
    self_hours: float
    unbound_hours: float = 0.0
    academic_tasks: int = 0
    self_tasks: int = 0


def heatmap(conn: sqlite3.Connection, days: int = DEFAULT_HEATMAP_DAYS) -> list[HeatmapCell]:
    """近 `days` 天的**逐日多指标**（时间热力图的原始数据）。

    一天一格，五个可切换维度：专注分钟 / 手动投入分钟 / 复习张数 / 产出条数 / **当日债务快照**。
    与 `daily_insights()` 同口径（只读 facts；习惯不计入此处，习惯有独立的日历热力图）。
    """
    total = max(1, min(int(days), MAX_HEATMAP_DAYS))
    start = date.today() - timedelta(days=total - 1)
    return [
        _cell(conn, (start + timedelta(days=i)).isoformat()) for i in range(total)
    ]


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
        cell = _cell(conn, day)
        out.append(
            DayInsight(
                date=day,
                focus_minutes=cell.focus_minutes,
                manual_minutes=cell.manual_minutes,
                review_count=cell.review_count,
                output_count=cell.output_count,
                habit_done=_habit_done(conn, day),
                debt_count=cell.debt_count,
            )
        )
    return out


def academic_vs_self(
    conn: sqlite3.Connection, days: int = DEFAULT_TREND_DAYS
) -> AcademicSplit:
    """近 `days` 天「学业投入 vs 自学投入」（SR-F5.1b / T-C10）。

    为什么这样切：**"学业"不等于"任何学习"** —— 只有明确挂到某门课上的任务才算学业投入；
    其余挂任务的专注算自学；没绑定任务的专注**单列**（如实、不归因，与 `group_insights` 同一取向）。
    不折算、不设目标、不做"学业应占多少"的建议（守温和红线）。
    """
    total = max(1, min(int(days), MAX_TREND_DAYS))
    start = (date.today() - timedelta(days=total - 1)).isoformat()
    rows = facts_mod.query(conn, kind="focus.finished", since=f"{start}T00:00:00")

    per_task: dict[str, float] = {}
    unbound = 0.0
    for row in rows:
        seconds = _num(row["value_num"])
        if row["subject_type"] != "task" or not row["subject_id"]:
            unbound += seconds          # 没绑定任务：不归入任何一类
            continue
        tid = str(row["subject_id"])
        per_task[tid] = per_task.get(tid, 0.0) + seconds

    academic = self_study = 0.0
    academic_tasks = self_tasks = 0
    for tid, seconds in per_task.items():
        try:
            task = tm.get_task(conn, tid)
        except KeyError:               # 任务被彻底清理：不猜它属于哪一类
            unbound += seconds
            continue
        if task.course_id:
            academic += seconds
            academic_tasks += 1
        else:
            self_study += seconds
            self_tasks += 1
    return AcademicSplit(
        days=total,
        academic_hours=round(academic / 3600.0, 2),
        self_hours=round(self_study / 3600.0, 2),
        unbound_hours=round(unbound / 3600.0, 2),
        academic_tasks=academic_tasks,
        self_tasks=self_tasks,
    )


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


def _cell(conn: sqlite3.Connection, day: str) -> HeatmapCell:
    """一天的多指标（`daily_insights` 与 `heatmap` 共用，避免口径分叉）。"""
    return HeatmapCell(
        date=day,
        focus_minutes=round(_focus_seconds(conn, day) / 60.0, 1),
        manual_minutes=round(_manual_seconds(conn, day) / 60.0, 1),
        review_count=len(_review_subjects(conn, day)),
        output_count=len(_output_entries(conn, day)),
        # 债务 = **卡的张数**（T-F9：父任务一张卡、逾期的子孙挂在下面）——
        # 与账本/周结算同一个读数（`tm.debt_count`），三处各算一套就会互相打脸
        debt_count=tm.debt_count(conn, day),
    )


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
