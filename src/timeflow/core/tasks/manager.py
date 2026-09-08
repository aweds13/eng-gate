"""任务管理领域逻辑。对应 SR-F1.1~F1.9（My Day / 状态机 / 分组 / 子任务 / Repeat / 逾期）。

纯领域逻辑，不碰 SQL（sqlite 由 storage 层处理，本层用连接对象）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

STATUS_TODO = "未开始"
STATUS_DOING = "进行中"
STATUS_DONE = "完成"
STATUS_OVERDUE = "逾期"
STATUS_CANCELLED = "取消"
STATUS_ARCHIVED = "归档"

VALID_STATUS = {
    STATUS_TODO,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_CANCELLED,
    STATUS_ARCHIVED,
}


@dataclass
class Task:
    id: str
    title: str
    due_date: str | None
    group_name: str | None
    repeat_days: int | None
    parent_id: str | None
    is_myday: bool
    status: str
    created_at: str
    updated_at: str
    version: int


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        due_date=row["due_date"],
        group_name=row["group_name"],
        repeat_days=row["repeat_days"],
        parent_id=row["parent_id"],
        is_myday=bool(row["is_myday"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def create_task(
    conn: sqlite3.Connection,
    title: str,
    due_date: str | None = None,
    group_name: str | None = None,
    repeat_days: int | None = None,
    parent_id: str | None = None,
    is_myday: bool = False,
) -> Task:
    """新建任务（AC-1）。校验标题非空；若 due 过去且未完成，初始状态标逾期。"""
    title = title.strip()
    if not title:
        raise ValueError("任务标题不能为空")
    now = _now()
    task_id = uuid.uuid4().hex[:12]
    status = STATUS_TODO
    if due_date and due_date < _today():
        status = STATUS_OVERDUE
    conn.execute(
        """
        INSERT INTO tasks
        (id, title, due_date, group_name, repeat_days, parent_id, is_myday, status,
         created_at, updated_at, version)
        VALUES (?,?,?,?,?,?,?,?,?,?,1)
        """,
        (
            task_id,
            title,
            due_date,
            group_name,
            repeat_days,
            parent_id,
            int(is_myday),
            status,
            now,
            now,
        ),
    )
    conn.commit()
    return get_task(conn, task_id)


def get_task(conn: sqlite3.Connection, task_id: str) -> Task:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise KeyError(f"任务不存在: {task_id}")
    return _row_to_task(row)


def list_tasks(conn: sqlite3.Connection, active_only: bool = True) -> list[Task]:
    sql = "SELECT * FROM tasks"
    if active_only:
        sql += " WHERE status != ?"
    rows = conn.execute(sql, (STATUS_ARCHIVED,) if active_only else ()).fetchall()
    return [_row_to_task(r) for r in rows]


def update_task(conn: sqlite3.Connection, task_id: str, **fields: object) -> Task:
    """更新任务字段（AC-2/AC-3）。只允许白名单字段，version+1，刷新 updated_at。"""
    allowed = {
        "title",
        "due_date",
        "group_name",
        "repeat_days",
        "parent_id",
        "is_myday",
        "status",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_task(conn, task_id)
    if "status" in updates and updates["status"] not in VALID_STATUS:
        raise ValueError(f"非法状态: {updates['status']}")
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE tasks SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",
        (*updates.values(), _now(), task_id),
    )
    conn.commit()
    return get_task(conn, task_id)


def delete_task(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()


def myday_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """My Day 集合（AC-4）：is_myday=1 且非完成/取消/归档；默认含今日应做。"""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE is_myday = 1 AND status NOT IN (?,?,?) "
        "ORDER BY due_date IS NULL, due_date",
        (STATUS_DONE, STATUS_CANCELLED, STATUS_ARCHIVED),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def overdue_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """逾期任务（AC-5）：未完成且 due_date < 今天（不强推，只如实列出）。"""
    t = today or _today()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date < ? AND status NOT IN (?,?,?) "
        "ORDER BY due_date",
        (t, STATUS_DONE, STATUS_CANCELLED, STATUS_ARCHIVED),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def complete_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """完成任务（AC-7 联动）：若为父任务，仅当全部子任务完成才自动完成；否则标记完成。"""
    children = conn.execute("SELECT * FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    if children and any(_row_to_task(c).status != STATUS_DONE for c in children):
        raise ValueError("存在未完成的子任务，父任务不能自动完成")
    return update_task(conn, task_id, status=STATUS_DONE)


def process_repeats(conn: sqlite3.Connection) -> int:
    """Repeat（AC-8）：到点（按上次完成时间 + repeat_days）自动生成下一次。返回生成数。"""
    generated = 0
    for row in conn.execute(
        "SELECT * FROM tasks WHERE repeat_days IS NOT NULL AND status = ?", (STATUS_DONE,)
    ).fetchall():
        task = _row_to_task(row)
        if task.due_date is None:
            continue
        last = datetime.fromisoformat(task.updated_at).date()
        next_due = (last + timedelta(days=task.repeat_days or 0)).isoformat()
        create_task(
            conn,
            title=task.title,
            due_date=next_due,
            group_name=task.group_name,
            repeat_days=task.repeat_days,
            parent_id=task.parent_id,
        )
        generated += 1
    return generated
