"""每日反馈 + 习惯打卡 + 自检（SR-F4.1/4.2/4.3）。对应 AC 反馈。

每日反馈：记录"计划 vs 执行"差距（plan_note/executed/gap_note），专注时长自动计入。
习惯打卡：以时间热力图呈现，纳入 B 系统同一套可视化。
自检：消费 B 账本数据（投入/产出/债务趋势）作为体检依据，温和不施压。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
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


def upsert_focus_minutes(conn: sqlite3.Connection, on_date: str, minutes: float) -> None:
    """把某日专注分钟写入 `feedback_logs`（只动 focus_minutes，不碰备注字段）。

    由专注线订阅器在 `focus.finished` 时调用（FLOW-4：不靠前端传参）。
    备注列写 NULL，仅当该日尚无记录时创建行；已有记录时保留备注。
    """
    conn.execute(
        "INSERT INTO feedback_logs (date, plan_note, executed, gap_note, focus_minutes, "
        "created_at) VALUES (?,NULL,NULL,NULL,?,?) "
        "ON CONFLICT(date) DO UPDATE SET focus_minutes=excluded.focus_minutes",
        (on_date, float(minutes), _now()),
    )
    conn.commit()


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


def update_habit(conn: sqlite3.Connection, habit_id: str, name: str) -> None:
    """重命名习惯（重名允许但提示由前端负责；空名拒绝）。"""
    name = name.strip()
    if not name:
        raise ValueError("习惯名不能为空")
    conn.execute("UPDATE habits SET name = ? WHERE id = ?", (name, habit_id))
    conn.commit()


def delete_habit(conn: sqlite3.Connection, habit_id: str) -> None:
    """删除习惯及其打卡记录（幂等）。

    取舍：打卡历史一并删除 —— 习惯被删掉后，孤立的历史打卡没有归属，
    留着只会在热力图上制造无法解释的格子。删除前由前端二次确认。
    """
    conn.execute("DELETE FROM habit_logs WHERE habit_id = ?", (habit_id,))
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()


def list_habits(conn: sqlite3.Connection, today: str | None = None) -> list[dict[str, object]]:
    """全部习惯 + 连续天数 + 最近 90 天打卡日期（供列表与日历热力图，SR-F4.2 / OP-19）。

    之前只有「按 id 查单个」，前端只能把 id 存在 sessionStorage 里，刷新即丢；
    这里补上列表，使习惯在界面上可稳定呈现与切换。
    """
    t = today or _today()
    since = (date.fromisoformat(t) - timedelta(days=89)).isoformat()
    rows = conn.execute("SELECT id, name, created_at FROM habits ORDER BY created_at").fetchall()
    out: list[dict[str, object]] = []
    for row in rows:
        hid = str(row["id"])
        logs = [
            r["date"]
            for r in conn.execute(
                "SELECT date FROM habit_logs WHERE habit_id = ? AND done = 1 AND date >= ? "
                "ORDER BY date",
                (hid, since),
            ).fetchall()
        ]
        out.append(
            {
                "id": hid,
                "name": row["name"],
                "streak": habit_streak(conn, hid, t),
                "logs": logs,
            }
        )
    return out


# ---- 自检（SR-F4.3）----
def self_check(conn: sqlite3.Connection, today: str | None = None) -> dict[str, object]:
    """自检：消费 B 账本数据。返回投入/产出/债务的轻量趋势（温和呈现，不告警）。

    第 2 步子任务 4（读口径收拢）：本周专注分钟改读**事实层**（`focus.finished`），
    不再直接聚合 `focus_sessions`——事实层是唯一投入出口。
    """
    t = today or _today()
    # 本周（近 7 天）专注分钟：读 facts，按完成时刻归属（与 summary 同口径）
    from timeflow.core import focus as fc

    week_start = _week_start(t)
    days = [
        (date.fromisoformat(week_start) + timedelta(days=i)).isoformat() for i in range(7)
    ]
    week_minutes = sum(
        fc.focus_minutes_from_facts(conn, d) for d in days if d <= t
    )
    # 逾期任务数（债务）
    from timeflow.core import tasks as tm

    debt = len(tm.overdue_tasks(conn, t))
    # 本周习惯打卡数
    habit_done = conn.execute(
        "SELECT COUNT(*) FROM habit_logs WHERE date >= ? AND done = 1", (week_start,)
    ).fetchone()
    return {
        "week_focus_minutes": round(week_minutes, 1),
        "debt_count": debt,
        "week_habit_done": int(habit_done["COUNT(*)"] or 0),
    }


def _week_start(today: str) -> str:
    d = date.fromisoformat(today)
    return (d - timedelta(days=d.weekday())).isoformat()
