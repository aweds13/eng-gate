"""专注计时领域逻辑（SR-F3.1/3.2）。对应 AC 专注。

支持番茄钟(tomato)与普通计时(plain)；可绑定任务（关联 focus_sessions.task_id）；
专注被打断时提供「暂停 / 放弃 / 记中断」三选（status 标记）。
纯领域逻辑：不碰 SQL 细节，storage 层提供连接对象。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

KIND_TOMATO = "tomato"
KIND_PLAIN = "plain"

STATUS_FINISHED = "finished"
STATUS_PAUSED = "paused"
STATUS_ABANDONED = "abandoned"
STATUS_INTERRUPTED = "interrupted"

# 结束状态 → 事实 kind：只有正常结束才算「完成投入」，放弃/中断/暂停各自成 kind。
# 否则第 1 步 ledger 只查 focus.finished 时会把放弃/中断误计入投入（OP-4 / FLOW-3）。
_END_KIND = {
    STATUS_FINISHED: "focus.finished",
    STATUS_PAUSED: "focus.paused",
    STATUS_ABANDONED: "focus.abandoned",
    STATUS_INTERRUPTED: "focus.interrupted",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_session(
    conn: sqlite3.Connection,
    kind: str = KIND_TOMATO,
    task_id: str | None = None,
    device_id: str | None = None,
) -> str:
    """开始一段专注，返回 session id。番茄钟默认时长由前端/配置控制。"""
    if kind not in (KIND_TOMATO, KIND_PLAIN):
        raise ValueError(f"非法专注类型: {kind}")
    sid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO focus_sessions (id, task_id, kind, started_at, status, device_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, task_id, kind, _now(), STATUS_FINISHED, device_id, _now()),
    )
    conn.commit()
    return sid


def finish_session(
    conn: sqlite3.Connection,
    session_id: str,
    duration_sec: int,
    status: str = STATUS_FINISHED,
) -> None:
    """结束一段专注并记时长。

    status 决定事实 kind：正常结束 = focus.finished；暂停/放弃/记中断分别
    落 focus.paused / focus.abandoned / focus.interrupted（只有正常结束计投入）。
    """
    if status not in (STATUS_FINISHED, STATUS_PAUSED, STATUS_ABANDONED, STATUS_INTERRUPTED):
        raise ValueError(f"非法结束状态: {status}")
    if duration_sec < 0:
        raise ValueError("时长不能为负")
    row = conn.execute(
        "SELECT task_id, device_id FROM focus_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    conn.execute(
        "UPDATE focus_sessions SET ended_at = ?, duration_sec = ?, status = ? WHERE id = ?",
        (_now(), duration_sec, status, session_id),
    )
    conn.commit()
    # 发布事实（事实层与解读层解耦的起点；订阅者为空时 publish 为空操作，安全）
    from timeflow.core import facts as facts_mod

    task_id = row["task_id"] if row is not None else None
    device_id = row["device_id"] if row is not None else None
    fact_kind = _END_KIND[status]
    facts_mod.record(
        conn,
        kind=fact_kind,
        subject_type="task" if task_id else "focus_session",
        subject_id=task_id or session_id,
        value_num=float(duration_sec),
        extra={"session_id": session_id, "status": status},
        source="desktop",
        device_id=device_id,
    )
    facts_mod.publish(
        fact_kind,
        {
            "session_id": session_id,
            "task_id": task_id,
            "duration_sec": duration_sec,
            "status": status,
        },
    )


def today_focus_minutes(conn: sqlite3.Connection, today: str | None = None) -> float:
    """今日累计专注分钟数（已完成的，计入投入轴的来源之一）。"""
    t = today or datetime.now().date().isoformat()
    rows = conn.execute(
        "SELECT duration_sec FROM focus_sessions "
        "WHERE status = ? AND substr(started_at,1,10) = ?",
        (STATUS_FINISHED, t),
    ).fetchall()
    return sum(r["duration_sec"] or 0 for r in rows) / 60.0


def sessions_by_task(conn: sqlite3.Connection, task_id: str) -> list[dict[str, object]]:
    """某任务的所有专注记录（用于把时长归因到任务 + 每日反馈）。"""
    rows = conn.execute(
        "SELECT * FROM focus_sessions WHERE task_id = ? ORDER BY started_at", (task_id,)
    ).fetchall()
    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "started_at": r["started_at"],
            "duration_sec": r["duration_sec"],
            "status": r["status"],
        }
        for r in rows
    ]
