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


def get_group(conn: sqlite3.Connection, group_id: str) -> dict[str, object]:
    """按 id 取分组（不存在抛 KeyError）。"""
    row = conn.execute("SELECT id, name FROM groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise KeyError(f"分组不存在: {group_id}")
    return {"id": row["id"], "name": row["name"]}


def rename_group(conn: sqlite3.Connection, group_id: str, name: str) -> dict[str, object]:
    """重命名分组（OP-11）。改名到已有名字视为与那个分组合并（幂等，不报错）。

    改名为空 → ValueError；分组不存在 → KeyError。
    """
    name = name.strip()
    if not name:
        raise ValueError("分组名不能为空")
    current = get_group(conn, group_id)  # 不存在就抛 KeyError
    if current["name"] == name:
        return current
    dup = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
    if dup and str(dup["id"]) != group_id:
        # 与目标分组重名 → 把本组的任务挪过去，删掉本组（= 合并），避免留下两个同名组
        conn.execute(
            "INSERT OR IGNORE INTO task_groups (task_id, group_id) "
            "SELECT task_id, ? FROM task_groups WHERE group_id = ?",
            (dup["id"], group_id),
        )
        conn.execute("DELETE FROM task_groups WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
        return get_group(conn, str(dup["id"]))
    conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
    conn.commit()
    return get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: str) -> int:
    """删除分组（OP-11）：**只删分组本身与它的关联，不删任务**。返回解绑的任务数。"""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM task_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    unbound = int(row["c"]) if row else 0
    conn.execute("DELETE FROM task_groups WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    return unbound


def groups_of_task(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """任务所属分组名（`get_task_groups` 的别名，语义更直白）。"""
    return get_task_groups(conn, task_id)


def toggle_task_group(
    conn: sqlite3.Connection, task_id: str, name: str, on: bool
) -> list[str]:
    """把任务加入/移出某个分组（按名字，缺分组时自动建）。返回改动后的分组名列表。"""
    name = name.strip()
    if not name:
        raise ValueError("分组名不能为空")
    names = get_task_groups(conn, task_id)
    if on:
        if name not in names:
            names.append(name)
    else:
        names = [n for n in names if n != name]
    set_task_groups(conn, task_id, names)
    return get_task_groups(conn, task_id)


def tasks_in_group(conn: sqlite3.Connection, group_id: str) -> list[str]:
    """某分组下的任务 id（用于"点分组看任务"）。"""
    rows = conn.execute(
        "SELECT task_id FROM task_groups WHERE group_id = ?", (group_id,)
    ).fetchall()
    return [str(r["task_id"]) for r in rows]


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
