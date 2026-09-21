"""分组/多标签领域逻辑（SR-F1.3，AC-6 / N8，F 批 · T-F5 起可嵌套）。

一个任务可归多个分组；分组即组织维度，不改变任务执行逻辑。
对应的 join 表为 task_groups(group_id, task_id)；groups 表存分组名与 `parent_id`（自引用）。

嵌套口径（用户 2026-09-21：「或者程序里像文件夹那样，可以嵌套、归在一起」）：
- `parent_id` NULL = 顶层分组；**最多 `MAX_GROUP_DEPTH`（3）层**；
- **禁成环**（把父分组挂到自己的子分组下 → ValueError）；
- **名字允许重名**（用户 2026-09-21 追加定案「允许重名」）：只要求**同一父下不重名**
  —— 于是可以有「高数 / 作业」和「英语 / 作业」；
  为了做到这件事，任务与分组的关联**改成按 id**（`task_groups.group_id` 本来就是 id，
  变的是上面这层 API 不再用名字当标识）；界面显示**路径**（`高数 / 作业`）就够分辨了。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# 分组最多三层（与任务的「大任务 → 子任务 → 子步骤」同一个上限：界面不做无限缩进）
MAX_GROUP_DEPTH = 3


def _now() -> str:
    return date.today().isoformat()


def _find_sibling(conn: sqlite3.Connection, name: str, parent_id: str | None) -> str | None:
    """同一个父下有没有同名分组（有 → 返回它的 id）。**跨父不算重名**（T-F10 允许重名）。"""
    row = conn.execute(
        "SELECT id FROM groups WHERE name = ? AND COALESCE(parent_id, '') = COALESCE(?, '')",
        (name, parent_id),
    ).fetchone()
    return str(row["id"]) if row else None


def _parent_of(conn: sqlite3.Connection, group_id: str) -> str | None:
    row = conn.execute("SELECT parent_id FROM groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        return None
    return str(row["parent_id"]) if row["parent_id"] else None


def group_depth(conn: sqlite3.Connection, group_id: str) -> int:
    """分组层数：顶层 = 1（沿 `parent_id` 上溯；数据坏成环时停在 `MAX_GROUP_DEPTH+1` 不空转）。"""
    depth = 1
    cursor = _parent_of(conn, group_id)
    seen = {group_id}
    while cursor and cursor not in seen and depth <= MAX_GROUP_DEPTH:
        seen.add(cursor)
        depth += 1
        cursor = _parent_of(conn, cursor)
    return depth


def group_path(conn: sqlite3.Connection, group_id: str) -> str:
    """分组路径（`高数 / 第三章`）—— 分组名全局唯一，但嵌套之后**光看名字分不清是哪一层**。"""
    names: list[str] = []
    cursor: str | None = group_id
    seen: set[str] = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        row = conn.execute(
            "SELECT id, name, parent_id FROM groups WHERE id = ?", (cursor,)
        ).fetchone()
        if row is None:
            break
        names.append(str(row["name"]))
        cursor = str(row["parent_id"]) if row["parent_id"] else None
    return " / ".join(reversed(names))


def _would_cycle(conn: sqlite3.Connection, group_id: str, parent_id: str | None) -> bool:
    """把 group_id 挂到 parent_id 下会不会成环（沿父链上溯，撞到自己就是环）。"""
    cursor = parent_id
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor == group_id:
            return True
        seen.add(cursor)
        cursor = _parent_of(conn, cursor)
    return False


def create_group(conn: sqlite3.Connection, name: str, parent_id: str | None = None) -> str:
    """新建分组（`parent_id=None` = 顶层），返回分组 id。

    - **同一个父下**同名分组复用（"没有就建、有就用"的老方便，界面勾选分组时会自动建）；
      **换个父就是另一个分组**（T-F10 允许重名）——不会把别处的同名分组悄悄搬过来。
    - 父分组不存在 → KeyError；超过 `MAX_GROUP_DEPTH` 层 → ValueError（不静默截断）。
    """
    name = name.strip()
    if not name:
        raise ValueError("分组名不能为空")
    if parent_id is not None:
        get_group(conn, parent_id)  # 不存在就抛 KeyError
        if group_depth(conn, parent_id) >= MAX_GROUP_DEPTH:
            raise ValueError(
                f"分组最多 {MAX_GROUP_DEPTH} 层："
                f"不能在「{group_path(conn, parent_id)}」下再建子分组"
            )
    same = _find_sibling(conn, name, parent_id)
    if same:
        return same
    gid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO groups (id, name, parent_id, created_at) VALUES (?,?,?,?)",
        (gid, name, parent_id, _now()),
    )
    conn.commit()
    return gid


def list_groups(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """列出全部分组（**按树的前序**：父在子前）及计数、层数与路径。

    为什么要一次给全：分组计数（AC-6）、嵌套缩进、路径消歧义都要用同一份数据；
    让界面自己拼树意味着"父在子前"这套顺序要在前端再写一遍。
    """
    rows = conn.execute(
        """
        SELECT g.id, g.name, g.parent_id, COUNT(tg.task_id) AS task_count
        FROM groups g
        LEFT JOIN task_groups tg ON tg.group_id = g.id
        GROUP BY g.id, g.name, g.parent_id
        """
    ).fetchall()
    by_id = {str(r["id"]): r for r in rows}
    children: dict[str | None, list[str]] = {}
    for r in rows:
        pid = str(r["parent_id"]) if r["parent_id"] else None
        children.setdefault(pid, []).append(str(r["id"]))

    out: list[dict[str, object]] = []

    def walk(parent: str | None, prefix: str, depth: int, guard: set[str]) -> None:
        for gid in sorted(children.get(parent, []), key=lambda x: str(by_id[x]["name"])):
            if gid in guard:  # 坏数据成环：跳过，不无限递归
                continue
            row = by_id[gid]
            name = str(row["name"])
            path = f"{prefix} / {name}" if prefix else name
            out.append({
                "id": gid,
                "name": name,
                "parent_id": parent,
                "depth": depth,
                "path": path,
                "task_count": int(row["task_count"] or 0),
            })
            walk(gid, path, depth + 1, guard | {gid})

    walk(None, "", 1, set())
    return out


def get_group(conn: sqlite3.Connection, group_id: str) -> dict[str, object]:
    """按 id 取分组（不存在抛 KeyError）。带上父/层数/路径，界面与校验共用一份。"""
    row = conn.execute(
        "SELECT id, name, parent_id FROM groups WHERE id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"分组不存在: {group_id}")
    parent = str(row["parent_id"]) if row["parent_id"] else None
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": parent,
        "depth": group_depth(conn, group_id),
        "path": group_path(conn, group_id),
    }


def set_group_parent(
    conn: sqlite3.Connection, group_id: str, parent_id: str | None
) -> dict[str, object]:
    """把分组挂到另一个分组下（`parent_id=None` = 移到顶层）—— 嵌套的"移进去/移出来"。

    三条硬校验（全部 ValueError，**不静默**）：
    - 父分组不存在 → KeyError；
    - **成环**（挂到自己或自己的子孙下）；
    - 移动之后**整棵子树**会超过 `MAX_GROUP_DEPTH` 层（按"子树最高几层"算，不是只看自己）。
    幂等：本来就在那儿 → 原样返回。
    """
    get_group(conn, group_id)  # 不存在就抛 KeyError
    if parent_id is not None:
        get_group(conn, parent_id)
        if parent_id == group_id:
            raise ValueError("分组不能挂到自己下面")
        if _would_cycle(conn, group_id, parent_id):
            raise ValueError("这样会成环：目标分组在这个分组自己的下面")
        subtree = _subtree_height(conn, group_id)
        if group_depth(conn, parent_id) + subtree > MAX_GROUP_DEPTH:
            raise ValueError(
                f"分组最多 {MAX_GROUP_DEPTH} 层：这棵子树有 {subtree} 层，"
                f"挂到「{group_path(conn, parent_id)}」下就超了"
            )
    if _parent_of(conn, group_id) == parent_id:
        return get_group(conn, group_id)
    conn.execute("UPDATE groups SET parent_id = ? WHERE id = ?", (parent_id, group_id))
    conn.commit()
    return get_group(conn, group_id)


def _subtree_height(conn: sqlite3.Connection, group_id: str) -> int:
    """以 group_id 为根的子树有几层（只算自己 = 1）。"""
    kids = conn.execute(
        "SELECT id FROM groups WHERE parent_id = ?", (group_id,)
    ).fetchall()
    if not kids:
        return 1
    return 1 + max(_subtree_height(conn, str(k["id"])) for k in kids)


def rename_group(conn: sqlite3.Connection, group_id: str, name: str) -> dict[str, object]:
    """重命名分组（OP-11）。改成**同一个父下**已有的名字 = 与那个分组合并（幂等，不报错）。

    改名为空 → ValueError；分组不存在 → KeyError。
    T-F10（允许重名）之后：改成一个"别处（别的父下）已经有的名字"**是允许的**（就是重名），
    只有**同层撞名**才触发合并。
    嵌套相关的两条边界：**有子分组的分组不能"合并"进别的组**（子分组会失去父，
    变成悄悄上浮）；**不能合并进自己的子孙**（成环）。两条都 ValueError，不静默乱改。
    """
    name = name.strip()
    if not name:
        raise ValueError("分组名不能为空")
    current = get_group(conn, group_id)  # 不存在就抛 KeyError
    if current["name"] == name:
        return current
    dup = _find_sibling(conn, name, current["parent_id"])  # type: ignore[arg-type]
    if dup and dup != group_id:
        target = dup
        if _would_cycle(conn, group_id, target):
            raise ValueError("不能合并进自己的子分组（会成环）")
        if _has_children(conn, group_id):
            raise ValueError(
                f"「{current['name']}」下面还有子分组，不能合并进「{name}」——"
                "先把子分组移走或删掉"
            )
        if group_depth(conn, target) + _subtree_height(conn, group_id) > MAX_GROUP_DEPTH:
            raise ValueError(f"合并后会超过 {MAX_GROUP_DEPTH} 层，先整理一下层级")
        # 与目标分组重名 → 把本组的任务挪过去，删掉本组（= 合并），避免留下两个同名组
        conn.execute(
            "INSERT OR IGNORE INTO task_groups (task_id, group_id) "
            "SELECT task_id, ? FROM task_groups WHERE group_id = ?",
            (target, group_id),
        )
        conn.execute("DELETE FROM task_groups WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
        return get_group(conn, target)
    conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
    conn.commit()
    return get_group(conn, group_id)


def _has_children(conn: sqlite3.Connection, group_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM groups WHERE parent_id = ? LIMIT 1", (group_id,)).fetchone()
    return row is not None


def delete_group(conn: sqlite3.Connection, group_id: str) -> int:
    """删除分组（OP-11）：**只删分组本身与它的关联，不删任务**。返回解绑的任务数。

    嵌套之后多一条边界：**有子分组时拒绝**（ValueError，带子分组数）——
    级联删掉别人看不见的几层，比"要求先处理子分组"更容易出事（用户只点了一次删除）。
    """
    get_group(conn, group_id)  # 不存在就抛 KeyError
    kids = conn.execute(
        "SELECT COUNT(*) AS c FROM groups WHERE parent_id = ?", (group_id,)
    ).fetchone()
    if kids and int(kids["c"]):
        raise ValueError(f"这个分组下面还有 {int(kids['c'])} 个子分组，先把它们移走或删掉")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM task_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    unbound = int(row["c"]) if row else 0
    conn.execute("DELETE FROM task_groups WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    return unbound


def groups_of_task(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """任务所属分组的**路径**（`task_group_paths` 的别名，语义更直白）。"""
    return task_group_paths(conn, task_id)


def toggle_task_group(
    conn: sqlite3.Connection, task_id: str, group_id: str, on: bool
) -> list[str]:
    """把任务加入/移出某个分组（**按分组 id** —— T-F10 起名字可以重名，名字不能再当标识）。

    分组不存在 → KeyError（不静默建一个"差不多"的分组出来）。返回改动后的**路径**列表。
    """
    gid = str(group_id or "").strip()
    if not gid:
        raise ValueError("要指定分组 id")
    get_group(conn, gid)  # 不存在就抛 KeyError
    current = task_group_ids(conn, task_id)
    if on:
        if gid not in current:
            current.append(gid)
    else:
        current = [x for x in current if x != gid]
    set_task_groups(conn, task_id, current)
    return task_group_paths(conn, task_id)


def tasks_in_group(conn: sqlite3.Connection, group_id: str) -> list[str]:
    """某分组下的任务 id（用于"点分组看任务"）。"""
    rows = conn.execute(
        "SELECT task_id FROM task_groups WHERE group_id = ?", (group_id,)
    ).fetchall()
    return [str(r["task_id"]) for r in rows]


def set_task_groups(conn: sqlite3.Connection, task_id: str, group_ids: list[str]) -> None:
    """把任务关联到一组分组（**按 id**，覆盖式）。

    分组不存在 → KeyError（先 `create_group` 再关联是调用方的事 —— 不在这里偷偷建，
    免得一个笔误就多出一个分组）。
    """
    ids: list[str] = []
    for gid in group_ids:
        key = str(gid or "").strip()
        if not key:
            continue
        get_group(conn, key)  # 不存在就抛 KeyError
        if key not in ids:
            ids.append(key)
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
    for gid in ids:
        conn.execute(
            "INSERT OR IGNORE INTO task_groups (task_id, group_id) VALUES (?,?)",
            (task_id, gid),
        )
    conn.commit()


def task_group_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """任务所属分组 id 列表（按路径排序）—— 界面勾选状态就靠它。"""
    rows = conn.execute(
        "SELECT g.id, g.name, g.parent_id FROM groups g JOIN task_groups tg ON tg.group_id = g.id "
        "WHERE tg.task_id = ?",
        (task_id,),
    ).fetchall()
    items = [(str(r["id"]), group_path(conn, str(r["id"]))) for r in rows]
    return [gid for gid, _ in sorted(items, key=lambda x: x[1])]


def task_group_paths(conn: sqlite3.Connection, task_id: str) -> list[str]:
    """任务所属分组的**路径**列表（`高数 / 作业`）—— 重名之后名字分不清是哪一层，
    路径才是能认的那一个（同一父下不重名 ⇒ 路径唯一）。"""
    return [group_path(conn, gid) for gid in task_group_ids(conn, task_id)]


def task_group_entries(conn: sqlite3.Connection, task_id: str) -> list[dict[str, object]]:
    """任务所属分组：`[{id, name, path}]`（按路径排序）—— 界面同时要 id（勾选）与路径（显示）。"""
    out: list[dict[str, object]] = []
    for gid in task_group_ids(conn, task_id):
        g = get_group(conn, gid)
        out.append({"id": gid, "name": g["name"], "path": g["path"]})
    return out
