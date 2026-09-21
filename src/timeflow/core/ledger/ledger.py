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
    habit_count: int = 0
    # 产出**按两类分开报**（T-C4 / 2026-09-19 用户决定："分两行显示"）：数据里本来就有 `kind`
    # （`kpi`=学校 KPI / `asset`=知识资产），只是以前被合成一个总数。**不拆轴、不折算**，
    # 只把同一份产出事实分组显示；`output_count` 仍是总数（三者的关系在 today_done 里同源）。
    output_kpi: int = 0
    output_asset: int = 0
    # 完成收益（T-F6 / 2026-09-21 用户决定：补上这个读数）。
    # 口径来自 `needs.md:34` 的贯穿口径「**完成悬赏 = 收益/储蓄**」与 `conventions.md:20`
    # 「储蓄 = 完成悬赏 / 复习完成（维持）」—— 但直到这次之前，账本里**只有债务/投入/复习/产出**，
    # 没有"收益"这个读数**（用户问"我怎么没看到你开发这个系统"时查出来的缺口）。
    # 口径：当日 `task.completed` 事实按 task id 去重、且任务**现在仍是「完成」**（撤销照扣）、
    # **只算任务不算子步骤**（完成一步是推进，不是"收了一笔悬赏"）。
    gain_count: int = 0


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
    # 本周习惯打卡次数（T-C1）：同 LedgerSummary.habit_count —— 只报次数，不折算成小时
    habits_done: int = 0
    # 本周完成收益（T-F6）：同 LedgerSummary.gain_count 的口径（去重 + 撤销照扣 + 只算任务）
    gain_count: int = 0
    # 均衡度指标（T-C3 / SR-F2.6「波动/空档」）：**只出数字 + 一句温和描述**，不设目标、不告警。
    # 波动 = 逐日专注分钟的**标准差**（与 `days[].focus_minutes` 同单位，分钟；全 0 时为 0）；
    # 空档 = 本周**最长连续 0 天**数（0 = 每天都动了）。
    focus_variation_minutes: float = 0.0
    longest_gap_days: int = 0
    rhythm_note: str = ""


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

    gains: set[str] = set()          # 完成收益（T-F6）：完成悬赏 = 收益/储蓄（N3 口径）
    for day in days:
        gains |= _gained_subjects(conn, day)

    manual_sec = sum(_manual_seconds(conn, day) for day in days)
    debt = len(tm.overdue_tasks(conn, end))
    active_days = sum(1 for p in points if p.focus_minutes > 0)
    variation, gap = _rhythm(points)

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
        habits_done=sum(_habit_done_count(conn, day) for day in days),
        gain_count=len(gains),
        focus_variation_minutes=variation,
        longest_gap_days=gap,
        rhythm_note=_rhythm_note(variation, gap, active_days),
    )


def _rhythm(points: list[DayPoint]) -> tuple[float, int]:
    """均衡度（T-C3）：`(逐日专注分钟的总体标准差, 最长连续 0 天)`。

    为什么用标准差 + 最长空档这两个：**波动**回答"是不是忽多忽少"，**空档**回答"断没断过"。
    都用分钟/天数这类**不折算**的原始单位（守「不折算时间」的红线）；全 0 周返回 (0.0, 7)。
    """
    minutes = [p.focus_minutes for p in points]
    if not minutes:
        return 0.0, 0
    mean = sum(minutes) / len(minutes)
    variation = (sum((m - mean) ** 2 for m in minutes) / len(minutes)) ** 0.5
    longest = run = 0
    for m in minutes:
        run = run + 1 if m <= 0 else 0
        longest = max(longest, run)
    return round(variation, 1), longest


def _rhythm_note(variation: float, gap: int, active_days: int) -> str:
    """把波动/空档说成一句**温和**的话：描述事实、不评价、不设目标、不告警（约定「温和不施压」）。"""
    if active_days == 0:
        return "这周还没有专注记录，随时可以从一小段开始。"
    if gap >= 2:
        return f"这周最长有连续 {gap} 天没有专注；空档也照实记，不必补课。"
    if variation >= 45:
        return "这周每天都动了，只是每天长短差得多 —— 长有长的样子，短也算数。"
    if variation >= 15:
        return "这周投入有点起伏，总体是接着的。"
    return "这周投入比较平稳。"


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


def _gained_subjects(conn: sqlite3.Connection, day: str) -> set[str]:
    """当日「完成收益」的主体（T-F6；N3 口径：**完成悬赏 = 收益/储蓄**）。

    口径与 `today_done()` **同一处**（避免两处各算各的）：
    - 当日 `task.completed` 事实，**按 task id 去重**（完成→撤销→再完成只算一笔）；
    - 只算任务**现在仍是「完成」**的 —— 完成又被撤销的**不算收益**（撤销照扣）；
    - **只算任务、不算子步骤**：完成一个步骤是"推进"，不是"收了一笔悬赏"。
    """
    rows = facts_mod.query(
        conn, kind="task.completed", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    out: set[str] = set()
    for row in rows:
        tid = str(row["subject_id"] or "")
        if not tid:
            continue
        info = conn.execute(
            "SELECT parent_id, status FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
        if info is None or info["status"] != tm.STATUS_DONE or info["parent_id"]:
            continue
        out.add(tid)
    return out


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


def _habit_done_count(conn: sqlite3.Connection, day: str) -> int:
    """当天打卡次数（**只报次数**，不折算投入时间 —— T-C1 口径）。"""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM habit_logs WHERE date = ? AND done = 1", (day,)
    ).fetchone()
    return int(row["n"] or 0)


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
        # 逾期天数**只在领域层算一处**（T-F7）：这里以前自己再减一次日期，
        # 于是"详情面板说未开始、账本说逾期 3 天"这种口径分叉就有机会发生。
        days = tm.overdue_days(task, t)
        if days <= 0:
            continue  # 无截止日（但昨天就该做的 My Day 任务）：列在逾期栏，但没有"几天"可算
        items.append(
            DebtItem(
                title=task.title,
                due_date=task.due_date or "",
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
    # 产出的两类（T-C4）：只按 `value_text` 的 kind 分组统计**有效**条目（已撤销的不算）
    kpi_set = {
        row["subject_id"] or row["id"] for row in outputs_today if row["value_text"] == "kpi"
    } - retracted
    asset_set = {
        row["subject_id"] or row["id"] for row in outputs_today if row["value_text"] == "asset"
    } - retracted
    # 手动投入（第 5 步物化）：invest.manual（秒）− invest.retracted；单列，不并入 invest_hours
    manual_sec = sum(_num(row["value_num"]) for row in _manual_invests_today(conn, t))
    # 习惯打卡（T-C1）：只报**次数**，与投入并排显示；**不折算成小时**（已砍概念）
    habits = _habit_done_count(conn, t)
    return LedgerSummary(
        debt_count=len(items),
        debt_items=items,
        invest_hours=round(invested_sec / 3600.0, 2),
        review_count=len(review_subjects),
        output_count=len(output_entries),
        manual_hours=round(manual_sec / 3600.0, 2),
        habit_count=habits,
        output_kpi=len(kpi_set),
        output_asset=len(asset_set),
        gain_count=len(_gained_subjects(conn, t)),
    )


# ---------------------------------------------------------------- 今天做成了什么（T-C11）
# 用户要求（2026-09-19 原话要点）：
#   "大任务很难一天之内全部推进完……所以我感觉你突出我完成那些步骤也是很重要，
#    希望能看到自己完成哪些子步骤。"
# 所以这里给的不是"还剩多少"，而是**已经做成了什么**：完成的任务 / 完成的步骤（按父任务分组
# 并带父任务进度）/ 产出按两类分组。**全部只读事实层**，数字与明细同源（不新造派生表）。
class DoneTask(BaseModel):
    id: str
    title: str
    completed_at: str


class DoneStep(BaseModel):
    id: str
    title: str
    parent_id: str
    parent_title: str | None
    completed_at: str


class DoneParent(BaseModel):
    """完成步骤所属的父任务 + 进度（"大任务推进到哪了"）。"""

    id: str
    title: str | None
    done_today: int  # 今天完成的步数
    done_total: int  # 该父任务已完成的步数（含以前）
    total_steps: int  # 该父任务共几步


class DoneOutput(BaseModel):
    entry_id: str
    kind: str
    value: float
    note: str | None
    occurred_at: str
    retracted: bool


class TodayDone(BaseModel):
    date: str
    tasks: list[DoneTask]
    steps: list[DoneStep]
    parents: list[DoneParent]
    outputs: list[DoneOutput]
    output_kpi: int
    output_asset: int


def _title_of(conn: sqlite3.Connection, task_id: str) -> str | None:
    """任务标题（宽进严出）：查不到就 None —— 父任务被硬删了也不该让整页报错。"""
    row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return None if row is None else str(row["title"])


def _step_progress(conn: sqlite3.Connection, parent_id: str) -> tuple[int, int]:
    """父任务的步骤进度 `(已完成, 共几步)`。"""
    rows = conn.execute(
        "SELECT status FROM tasks WHERE parent_id = ?", (parent_id,)
    ).fetchall()
    total = len(rows)
    done = sum(1 for r in rows if r["status"] == tm.STATUS_DONE)
    return done, total


def today_done(conn: sqlite3.Connection, day: str | None = None) -> TodayDone:
    """今天做成了什么（T-C11）：完成的**任务** / 完成的**步骤**（按父任务分组+进度）/ 产出分两类。

    口径（**只读**，一处定义，界面不自己算）：
    - 任务与步骤都来自今日 `task.completed` 事实，**按 task id 去重**（完成→撤销→再完成只算一条）；
    - 只算**现在仍是「完成」**的：今天完成又被撤销的，不算"做成了"（数字不许比明细多）；
    - 有 `parent_id` 的进 `steps`（子步骤），没有的进 `tasks`；
    - `parents` 是这些步骤所属的父任务（含"今天完成几步 / 已推进几步 / 共几步"）；
    - `outputs` 来自今日 `output.manual`（已撤销的**如实列出并标记**，但不计入两类条数）。
    """
    d = day or date.today().isoformat()
    rows = facts_mod.query(
        conn, kind="task.completed", since=f"{d}T00:00:00", until=f"{d}T23:59:59"
    )
    seen: dict[str, str] = {}  # task_id → 最近一次完成时刻
    for row in rows:
        tid = str(row["subject_id"] or "")
        if tid:
            seen[tid] = str(row["occurred_at"] or "")

    tasks: list[DoneTask] = []
    steps: list[DoneStep] = []
    parents: dict[str, DoneParent] = {}
    for tid, when in sorted(seen.items(), key=lambda kv: kv[1]):
        row = conn.execute(
            "SELECT id, title, parent_id, status FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
        if row is None or row["status"] != tm.STATUS_DONE:
            continue  # 已撤销完成 / 任务已被硬删：不算"今天做成了"
        parent_id = row["parent_id"]
        if not parent_id:
            tasks.append(DoneTask(id=tid, title=str(row["title"]), completed_at=when))
            continue
        pid = str(parent_id)
        steps.append(
            DoneStep(
                id=tid,
                title=str(row["title"]),
                parent_id=pid,
                parent_title=_title_of(conn, pid),
                completed_at=when,
            )
        )
        done_total, total_steps = _step_progress(conn, pid)
        entry = parents.get(pid)
        if entry is None:
            parents[pid] = DoneParent(
                id=pid,
                title=_title_of(conn, pid),
                done_today=1,
                done_total=done_total,
                total_steps=total_steps,
            )
        else:
            entry.done_today += 1

    from timeflow.core import memo as memo_mod

    outputs = [
        DoneOutput(
            entry_id=str(o["entry_id"]),
            kind=str(o["kind"] or ""),
            value=_num(o["value"]),
            note=None if o["note"] is None else str(o["note"]),
            occurred_at=str(o["occurred_at"]),
            retracted=bool(o["retracted"]),
        )
        for o in memo_mod.list_outputs(conn, d)
    ]
    live = [o for o in outputs if not o.retracted]
    return TodayDone(
        date=d,
        tasks=tasks,
        steps=steps,
        parents=list(parents.values()),
        outputs=outputs,
        output_kpi=sum(1 for o in live if o.kind == "kpi"),
        output_asset=sum(1 for o in live if o.kind == "asset"),
    )
