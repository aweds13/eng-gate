"""每日反馈 + 习惯打卡 + 自检（SR-F4.1/4.2/4.3）。对应 AC 反馈。

每日反馈：记录"计划 vs 执行"差距（plan_note/executed/gap_note），专注时长自动计入。
习惯打卡：以时间热力图呈现，纳入 B 系统同一套可视化。
自检：消费 B 账本数据（投入/产出/债务趋势）作为体检依据，温和不施压。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return date.today().isoformat()


# ---- 每日反馈（SR-F4.1）----
def set_daily_feedback(
    conn: sqlite3.Connection,
    on_date: str | None = None,
    plan_note: str | None = None,
    executed: str | None = None,
    gap_note: str | None = None,
    focus_minutes: float | None = None,
) -> None:
    """录入/更新某日反馈。日期为主键，重复录入即覆盖。"""
    d = on_date or _today()
    cur = conn.execute("SELECT focus_minutes FROM feedback_logs WHERE date = ?", (d,)).fetchone()
    merged_min = focus_minutes if focus_minutes is not None else (
        cur["focus_minutes"] if cur else 0
    )
    conn.execute(
        "INSERT INTO feedback_logs (date, plan_note, executed, gap_note, "
        "focus_minutes, created_at) "  # noqa: E501
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET plan_note=excluded.plan_note, "
        "executed=excluded.executed, gap_note=excluded.gap_note, "
        "focus_minutes=excluded.focus_minutes",
        (d, plan_note, executed, gap_note, merged_min or 0, _now()),
    )
    conn.commit()


def get_feedback(conn: sqlite3.Connection, on_date: str | None = None) -> dict[str, object] | None:
    d = on_date or _today()
    row = conn.execute("SELECT * FROM feedback_logs WHERE date = ?", (d,)).fetchone()
    if row is None:
        return None
    return {
        "date": row["date"],
        "plan_note": row["plan_note"],
        "executed": row["executed"],
        "gap_note": row["gap_note"],
        "focus_minutes": row["focus_minutes"],
    }


# ---- 习惯打卡（SR-F4.2）----
def create_habit(conn: sqlite3.Connection, name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("习惯名不能为空")
    hid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO habits (id, name, created_at) VALUES (?,?,?)", (hid, name, _now())
    )
    conn.commit()
    return hid


def toggle_habit_log(conn: sqlite3.Connection, habit_id: str, on_date: str | None = None) -> bool:
    """打卡/取消打卡某习惯，返回新状态。"""
    d = on_date or _today()
    row = conn.execute(
        "SELECT done FROM habit_logs WHERE habit_id = ? AND date = ?", (habit_id, d)
    ).fetchone()
    if row:
        new = not bool(row["done"])
        conn.execute(
            "UPDATE habit_logs SET done = ? WHERE habit_id = ? AND date = ?",
            (int(new), habit_id, d),
        )
    else:
        new = True
        conn.execute(
            "INSERT INTO habit_logs (habit_id, date, done) VALUES (?,?,1)", (habit_id, d)
        )
    conn.commit()
    return bool(new)


def habit_streak(conn: sqlite3.Connection, habit_id: str, today: str | None = None) -> int:
    """当前连续打卡天数（从今天往前数，断了即止）。"""
    from datetime import date, timedelta

    t = today or _today()
    days = 0
    cur = date.fromisoformat(t)
    while True:
        row = conn.execute(
            "SELECT done FROM habit_logs WHERE habit_id = ? AND date = ?",
            (habit_id, cur.isoformat()),
        ).fetchone()
        if row is None or not bool(row["done"]):
            break
        days += 1
        cur = cur - timedelta(days=1)
    return days


def habit_logs(conn: sqlite3.Connection, habit_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT date FROM habit_logs WHERE habit_id = ? AND done = 1 ORDER BY date", (habit_id,)
    ).fetchall()
    return [r["date"] for r in rows]


# ---- 自检（SR-F4.3）----
def self_check(conn: sqlite3.Connection, today: str | None = None) -> dict[str, object]:
    """自检：消费 B 账本数据。返回投入/产出/债务的轻量趋势（温和呈现，不告警）。"""
    t = today or _today()
    # 本周（近 7 天）专注分钟
    focus = conn.execute(
        "SELECT SUM(duration_sec) FROM focus_sessions "
        "WHERE status = 'finished' AND substr(started_at,1,10) >= ?",
        (_week_start(t),),
    ).fetchone()
    # 逾期任务数（债务）
    from timeflow.core import tasks as tm

    debt = len(tm.overdue_tasks(conn, t))
    # 本周习惯打卡数
    habit_done = conn.execute(
        "SELECT COUNT(*) FROM habit_logs WHERE date >= ? AND done = 1", (_week_start(t),)
    ).fetchone()
    return {
        "week_focus_minutes": round((focus["SUM(duration_sec)"] or 0) / 60.0, 1),
        "debt_count": debt,
        "week_habit_done": int(habit_done["COUNT(*)"] or 0),
    }


def _week_start(today: str) -> str:
    from datetime import date, timedelta

    d = date.fromisoformat(today)
    return (d - timedelta(days=d.weekday())).isoformat()
