"""团队/AI 协作领域逻辑（SR-F7.1~F7.4）。对应 AC 团队。

管理者/执行者两视角：任务可标注「分配给我 / 我分配」。
不强制执行者装本软件——只需「我知道谁负责什么、进展到哪」；
执行者状态第一版手动为主 + AI 接口（见 `src/api/`，只读+新增）。
团队任务不计个人投入（分配出去的不算我投入，只记协调/分配完成）。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

ROLE_MANAGER = "manager"
ROLE_EXECUTOR = "executor"


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _today() -> str:
    return date.today().isoformat()


def assign_task(
    conn: sqlite3.Connection,
    task_id: str,
    assignee: str,
    assigner: str,
    note: str | None = None,
) -> str:
    """给任务标注分配（管理者分给执行者）。返回分配记录 id。"""
    rid = _uid()
    conn.execute(
        "INSERT INTO team_assignments (id, task_id, assignee, assigner, note, status, "
        "created_at) VALUES (?,?,?,?,?,?,?)",
        (rid, task_id, assignee, assigner, note, "assigned", _today()),
    )
    conn.commit()
    return rid


def update_assignment_status(
    conn: sqlite3.Connection, assignment_id: str, status: str
) -> None:
    """执行者回报进展（手动为主）。status: assigned / in_progress / done / blocked。"""
    if status not in ("assigned", "in_progress", "done", "blocked"):
        raise ValueError(f"非法状态: {status}")
    conn.execute(
        "UPDATE team_assignments SET status = ? WHERE id = ?", (status, assignment_id)
    )
    conn.commit()


def assignments(
    conn: sqlite3.Connection, assignee: str | None = None
) -> list[dict[str, object]]:
    """列出分配记录，可按执行者过滤（管理者看全局，执行者看我的）。"""
    if assignee:
        rows = conn.execute(
            "SELECT * FROM team_assignments WHERE assignee = ? ORDER BY created_at",
            (assignee,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM team_assignments ORDER BY created_at").fetchall()
    return [
        {
            "id": r["id"],
            "task_id": r["task_id"],
            "assignee": r["assignee"],
            "assigner": r["assigner"],
            "note": r["note"],
            "status": r["status"],
        }
        for r in rows
    ]
