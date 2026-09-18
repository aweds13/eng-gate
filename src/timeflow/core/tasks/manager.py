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
STATUS_DELETED = "已删"

VALID_STATUS = {
    STATUS_TODO,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_CANCELLED,
    STATUS_ARCHIVED,
    STATUS_DELETED,
}

# 默认视图（列表 / My Day / 逾期 / 债务）不可见的状态：归档 + 已删（软删除）。
HIDDEN_STATUSES = (STATUS_ARCHIVED, STATUS_DELETED)


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
    """任务列表。`active_only=True` 时排除「归档 / 已删（软删除）」。"""
    sql = "SELECT * FROM tasks"
    params: tuple[object, ...] = ()
    if active_only:
        sql += " WHERE status NOT IN (?,?)"
        params = HIDDEN_STATUSES
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_task(r) for r in rows]


def update_task(conn: sqlite3.Connection, task_id: str, **fields: object) -> Task:
    """更新任务字段（AC-2/AC-3）。只允许白名单字段，version+1，刷新 updated_at。

    第 2 步子任务 2：状态在「完成 ↔ 非完成」之间切换时发事实
    （完成发 `task.completed`，撤销发 `task.uncompleted`），使账本/联动只依赖事实层。
    """
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
    before = get_task(conn, task_id)
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE tasks SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",
        (*updates.values(), _now(), task_id),
    )
    conn.commit()
    after = get_task(conn, task_id)
    if before.status != after.status:
        _publish_status_facts(conn, before, after)
    return after


def _publish_status_facts(conn: sqlite3.Connection, before: Task, after: Task) -> None:
    """状态跃迁 → 事实（仅「完成 ↔ 非完成」与软删除/恢复有跨线语义；其它状态变化不记账）。"""
    from timeflow.core import facts as facts_mod

    if after.status == STATUS_DONE and before.status != STATUS_DONE:
        facts_mod.record(
            conn,
            kind="task.completed",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={
                "title": after.title,
                "due_date": after.due_date,
                "from_status": before.status,
                "completed_on": _today(),
            },
            source="desktop",
        )
        facts_mod.publish(
            "task.completed",
            {"task_id": after.id, "title": after.title, "from_status": before.status},
        )
    elif before.status == STATUS_DONE and after.status != STATUS_DONE:
        facts_mod.record(
            conn,
            kind="task.uncompleted",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "to_status": after.status, "reverted_on": _today()},
            source="desktop",
        )
        facts_mod.publish(
            "task.uncompleted",
            {"task_id": after.id, "title": after.title, "to_status": after.status},
        )
    if after.status == STATUS_DELETED and before.status != STATUS_DELETED:
        facts_mod.record(
            conn,
            kind="task.deleted",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "from_status": before.status, "deleted_on": _today()},
            source="desktop",
        )
        facts_mod.publish(
            "task.deleted",
            {"task_id": after.id, "title": after.title, "from_status": before.status},
        )
    elif before.status == STATUS_DELETED and after.status != STATUS_DELETED:
        facts_mod.record(
            conn,
            kind="task.restored",
            subject_type="task",
            subject_id=after.id,
            value_text=after.title,
            extra={"title": after.title, "to_status": after.status, "restored_on": _today()},
            source="desktop",
        )
        facts_mod.publish(
            "task.restored",
            {"task_id": after.id, "title": after.title, "to_status": after.status},
        )


def delete_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """删除任务（OP-6）：**软删除** —— 置 status=已删、发 `task.deleted` 事实。

    可逆：`restore_task` 撤销软删除。默认视图（列表 / My Day / 逾期 / 债务）都会隐藏已删任务；
    数据与事实历史保留，不物理删除（对齐「可回退」约定 N34）。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_DELETED:
        return current  # 幂等
    return update_task(conn, task_id, status=STATUS_DELETED)


def restore_task(
    conn: sqlite3.Connection,
    task_id: str,
    restore_status: str = STATUS_TODO,
) -> Task:
    """撤销软删除（OP-6 可逆）：置回指定状态并发 `task.restored` 事实（幂等）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_DELETED:
        return current
    if restore_status not in VALID_STATUS or restore_status == STATUS_DELETED:
        raise ValueError(f"非法恢复状态: {restore_status}")
    return update_task(conn, task_id, status=restore_status)


def purge_task(conn: sqlite3.Connection, task_id: str) -> None:
    """彻底删除（不可逆）：仅用于明确的清理场景；常规路径请用 `delete_task`（软删除）。"""
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()


def myday_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """My Day 集合（AC-4）：is_myday=1 且非完成/取消/归档/已删；默认含今日应做。"""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE is_myday = 1 AND status NOT IN (?,?,?,?) "
        "ORDER BY due_date IS NULL, due_date",
        (STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def overdue_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """逾期任务（AC-5）：未完成且 due_date < 今天（不强推，只如实列出）。

    AC-4 补充：无截止日但**昨日仍未完成的 My Day 任务**也自动移入逾期栏
    （My Day=今天要做的集合，没做完不假装消失）。
    """
    t = today or _today()
    t_date = date.fromisoformat(t)
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date < ? "
        "AND status NOT IN (?,?,?,?) ORDER BY due_date",
        (t, STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES),
    ).fetchall()
    overdue = [_row_to_task(r) for r in rows]

    # 无 due 但过期的 My Day 任务：加入 My Day 的日期早于今天（用 created_at 日期近似）
    myday_rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NULL AND is_myday = 1 AND status NOT IN (?,?,?,?)",
        (STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES),
    ).fetchall()
    for r in myday_rows:
        task = _row_to_task(r)
        created = date.fromisoformat(task.created_at[:10])
        if created < t_date:
            overdue.append(task)
    overdue.sort(key=lambda x: (x.due_date or x.created_at))
    return overdue


def complete_task(conn: sqlite3.Connection, task_id: str) -> Task:
    """完成任务（AC-7 联动）：若为父任务，仅当全部子任务完成才自动完成；否则标记完成。

    第 2 步：完成时发 `task.completed` 事实（幂等——已完成的重复调用不再发）。
    第 5 步（OP-8）：完成设了重复的任务后，自动生成下一次（只生成一次）。
    """
    current = get_task(conn, task_id)
    if current.status == STATUS_DONE:
        return current
    children = conn.execute("SELECT * FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    if children and any(_row_to_task(c).status != STATUS_DONE for c in children):
        raise ValueError("存在未完成的子任务，父任务不能自动完成")
    done = update_task(conn, task_id, status=STATUS_DONE)
    if done.repeat_days is not None:
        process_repeats(conn)
    return done


def uncomplete_task(
    conn: sqlite3.Connection,
    task_id: str,
    restore_status: str = STATUS_TODO,
) -> Task:
    """撤销完成（OP-5 可逆）：发 `task.uncompleted` 反向事实并恢复状态（幂等）。"""
    current = get_task(conn, task_id)
    if current.status != STATUS_DONE:
        return current
    if restore_status not in VALID_STATUS or restore_status == STATUS_DONE:
        raise ValueError(f"非法恢复状态: {restore_status}")
    return update_task(conn, task_id, status=restore_status)


def process_repeats(conn: sqlite3.Connection) -> int:
    """Repeat（AC-8 / OP-8）：为「已完成且设了重复」的任务生成下一次。返回本次生成数。

    口径：
    - 基准是**上次完成时间**（`updated_at`，完成即写）；无截止日的任务不生成（无从推算下一次）。
    - **幂等**：同一任务只生成一次下一次 —— 以 `task.repeat.generated` 事实为准
      （该事实随生成一起写入，既做去重依据，也留下可审计痕迹）。
    - 继承：标题 / 分组 / 重复周期 / 是否 My Day（下一次仍进今天，保持动线连续）。
    """
    generated = 0
    for row in conn.execute(
        "SELECT * FROM tasks WHERE repeat_days IS NOT NULL AND status = ?", (STATUS_DONE,)
    ).fetchall():
        task = _row_to_task(row)
        if task.due_date is None:
            continue
        if _repeat_already_generated(conn, task.id):
            continue
        last = datetime.fromisoformat(task.updated_at).date()
        next_due = (last + timedelta(days=task.repeat_days or 0)).isoformat()
        next_task = create_task(
            conn,
            title=task.title,
            due_date=next_due,
            group_name=task.group_name,
            repeat_days=task.repeat_days,
            parent_id=task.parent_id,
            is_myday=task.is_myday,
        )
        _record_repeat_generated(conn, task, next_task, next_due)
        generated += 1
    return generated


def _repeat_already_generated(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM facts WHERE kind = 'task.repeat.generated' AND subject_id = ? LIMIT 1",
        (task_id,),
    ).fetchone()
    return row is not None


def _record_repeat_generated(
    conn: sqlite3.Connection,
    task: Task,
    next_task: Task,
    next_due: str,
) -> None:
    """记录「已生成下一次」事实：既是幂等依据，也让重复动线可追溯。"""
    from timeflow.core import facts as facts_mod

    extra = {
        "title": task.title,
        "repeat_days": task.repeat_days,
        "next_task_id": next_task.id,
        "next_due": next_due,
    }
    facts_mod.record(
        conn,
        kind="task.repeat.generated",
        subject_type="task",
        subject_id=task.id,
        value_num=float(task.repeat_days or 0),
        value_text=next_task.id,
        extra=extra,
        source="desktop",
    )
    facts_mod.publish(
        "task.repeat.generated",
        {"task_id": task.id, "next_task_id": next_task.id, "next_due": next_due, **extra},
    )
