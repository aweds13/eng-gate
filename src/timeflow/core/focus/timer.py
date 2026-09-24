"""专注计时领域逻辑（SR-F3.1/3.2）。对应 AC 专注。

支持番茄钟(tomato)与普通计时(plain)；可绑定任务（关联 focus_sessions.task_id）；
专注被打断时提供「暂停 / 放弃 / 记中断」三选（status 标记）。
纯领域逻辑：不碰 SQL 细节，storage 层提供连接对象。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from timeflow import clock

if TYPE_CHECKING:
    import sqlite3

KIND_TOMATO = "tomato"
KIND_PLAIN = "plain"

STATUS_ACTIVE = "进行中"
STATUS_FINISHED = "finished"
# ★ 预留、**没有任何入口**：`finish` 接受它、事实表里也有 `focus.paused` 映射，
#   但 app.py 从来没有暂停/继续路由、界面也 0 处 pause/resume —— OP-3b 曾是它的契约，
#   2026-09-23 按用户决定把规格改成现实（中断三选 = 结束 / 放弃 / 记中断），那条契约已删（T-G39）。
#   留着这个常量只为兼容既有数据；真要"暂停/恢复"就新开一张卡（要动计时分段与账目口径）。
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
    return clock.now().isoformat(timespec="seconds")


def active_session(conn: sqlite3.Connection) -> dict[str, object] | None:
    """当前进行中的专注（同一时间只允许一个）；无则 None。

    供前端「重开页面恢复计时」使用（SR-F3 边界：应用关闭/重开可恢复）；
    `device_id` 一并回传，供**跨端镜像**判断"这条是不是我自己开的"（T-G20 / SR-F3.4）——
    老数据这里可能是 None，界面按"自己开的"处理（保持可恢复），不按"别处"处理。
    """
    row = conn.execute(
        "SELECT id, task_id, kind, started_at, device_id FROM focus_sessions "
        "WHERE status = ? ORDER BY started_at DESC LIMIT 1",
        (STATUS_ACTIVE,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "kind": row["kind"],
        "started_at": row["started_at"],
        "device_id": row["device_id"],
    }


# 客户端身份（谁在计时）最长长度：它只是标识，超长没有意义（T-G20）
MAX_DEVICE_LEN = 40


def _clean_device(device_id: object) -> str | None:
    """规整客户端身份：去空格、截断、空白 → None。

    为什么在这层收口：它会被写进库，也会被界面拿来判断"这是不是我自己开的" ——
    脏值（多余空格）或超长值只会让判断出错。这里**不报错**是有意的：
    它是客户端标识，不是用户填的业务字段，拒绝开始专注对用户毫无意义。
    """
    if device_id is None:
        return None
    text = str(device_id).strip()[:MAX_DEVICE_LEN]
    return text or None


def start_session(
    conn: sqlite3.Connection,
    kind: str = KIND_TOMATO,
    task_id: str | None = None,
    device_id: str | None = None,
) -> str:
    """开始一段专注，返回 session id。番茄钟默认时长由前端/配置控制。

    - 落库状态为 `进行中`（OP-3：**不得**直接置 finished，否则未结束的专注会被算进投入）。
    - 已有进行中 session 时拒绝（OP-3 边界：不产生两条并行）。
    - `device_id` = **哪个客户端**在计时（T-G20）：跨端镜像靠它区分"我开的"与"别处开的"。
      注意这不是"数据库主人"那个设备号 —— 两个客户端读到的是同一个主人号，区分不了。
    """
    if kind not in (KIND_TOMATO, KIND_PLAIN):
        raise ValueError(f"非法专注类型: {kind}")
    running = active_session(conn)
    if running is not None:
        raise ValueError(f"已有进行中的专注: {running['id']}")
    sid = uuid.uuid4().hex[:12]
    now = _now()
    conn.execute(
        "INSERT INTO focus_sessions (id, task_id, kind, started_at, status, device_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, task_id, kind, now, STATUS_ACTIVE, _clean_device(device_id), now),
    )
    conn.commit()
    # 开始**不发事实**：投入事实只在结束时产生（focus.finished 等）。
    # 前端需要「正在计时」状态时读 `GET /api/focus/active`；如未来要做跨线联动再引入 focus.started。
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
        "SELECT task_id, kind, started_at, device_id, status FROM focus_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"专注记录不存在: {session_id}")
    if row["status"] != STATUS_ACTIVE:
        return  # 已结束过：幂等，不重复计时长/发事实（OP-4 边界：结束两次幂等）
    conn.execute(
        "UPDATE focus_sessions SET ended_at = ?, duration_sec = ?, status = ? WHERE id = ?",
        (_now(), duration_sec, status, session_id),
    )
    conn.commit()
    # 发布事实（事实层与解读层解耦的起点；订阅者为空时 publish 为空操作，安全）
    from timeflow.core import facts as facts_mod

    task_id = row["task_id"]
    device_id = row["device_id"]
    fact_kind = _END_KIND[status]
    occurred_at = _now()
    facts_mod.record(
        conn,
        kind=fact_kind,
        subject_type="task" if task_id else "focus_session",
        subject_id=task_id or session_id,
        value_num=float(duration_sec),
        extra={
            "session_id": session_id,
            "status": status,
            "kind": row["kind"] or KIND_TOMATO,
            "started_at": row["started_at"],
        },
        occurred_at=occurred_at,
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
            "occurred_at": occurred_at,
            "conn": conn,  # 让订阅者知道该写哪个库（多 app/连接并存不串库）
        },
    )


def today_focus_minutes(conn: sqlite3.Connection, today: str | None = None) -> float:
    """今日累计专注分钟数（第 2 步起：读事实层，`focus.finished` 为唯一口径）。

    保持原有返回精度（秒/60，不四舍五入）以免破坏既有调用方；需要落库/展示时再取整。
    """
    return focus_minutes_from_facts(conn, today or clock.today_iso())


def focus_minutes_from_facts(conn: sqlite3.Connection, day: str) -> float:
    """某日已完成专注分钟数 —— 唯一口径：读事实层 `focus.finished`。

    第 2 步「读口径收拢」：各线不再各自聚合 `focus_sessions`，统一按
    `occurred_at`（完成时刻）归属当日（SR-F2 R5 / F3 OP-4「跨午夜按完成日」）。
    """
    from timeflow.core import facts as facts_mod

    rows = facts_mod.query(
        conn, kind="focus.finished", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    total_sec = sum(float(row["value_num"] or 0) for row in rows)
    return total_sec / 60.0


def sessions_by_task(conn: sqlite3.Connection, task_id: str) -> list[dict[str, object]]:
    """某任务的专注记录（用于把时长归因到任务 + 每日反馈）。

    第 2 步子任务 4（读口径收拢）：改读**事实层**（`focus.*` 中 subject 指向该任务的事实），
    与投入口径同源；返回结构保持向后兼容（id/kind/started_at/duration_sec/status）。
    """
    from timeflow.core import facts as facts_mod

    rows = facts_mod.query(conn, kind="focus.", subject_type="task", subject_id=task_id)
    return [
        {
            "id": str((row["extra"] or {}).get("session_id") or row["id"]),
            "kind": str((row["extra"] or {}).get("kind") or ""),
            "started_at": str(
                (row["extra"] or {}).get("started_at") or row["occurred_at"]
            ),
            "duration_sec": int(float(row["value_num"] or 0)),
            "status": str((row["extra"] or {}).get("status") or ""),
        }
        for row in rows
    ]
