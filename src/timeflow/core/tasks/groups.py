"""分组/多标签领域逻辑（SR-F1.3，AC-6）。

一个任务可归多个分组；分组即组织维度，不改变任务执行逻辑。
对应的 join 表为 task_groups(group_id, task_id)；groups 表存分组名。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def _now() -> str:
    return date.today().isoformat()


def create_group(conn: sqlite3.Connection, name: str) -> str:
    """新建分组，返回分组的 id。同名分组复用（UNIQUE）。"""
    name = name.strip()
    if not name:
        raise ValueError("分组名不能为空")
    row = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
    if row:
        return str(row["id"])
    gid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO groups (id, name, created_at) VALUES (?,?,?)",
        (gid, name, _now()),
    )
    conn.commit()
    return gid


def list_groups(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """列出全部分组及计数（AC-6：分组计数正确）。"""
    rows = conn.execute(
        """
        SELECT g.id, g.name, COUNT(tg.task_id) AS task_count
        FROM groups g
        LEFT JOIN task_groups tg ON tg.group_id = g.id
        GROUP BY g.id, g.name
        ORDER BY g.name
        """
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "task_count": r["task_count"]} for r in rows]


def set_task_groups(conn: sqlite3.Connection, task_id: str, names: list[str]) -> None:
    """把任务关联到一组分组名（按名字解析分组，自动建缺失的）。覆盖式。"""
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
    for name in names:
        gid = create_group(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO task_groups (task_id, group_id) VALUES (?,?)",
            (task_id, gid),
        )
    conn.commit()


def get_task_groups(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """返回任务关联的分组名列表。"""
    rows = conn.execute(
        "SELECT g.name FROM groups g JOIN task_groups tg ON tg.group_id = g.id "
        "WHERE tg.task_id = ? ORDER BY g.name",
        (task_id,),
    ).fetchall()
    return [r["name"] for r in rows]
