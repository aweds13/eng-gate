"""任务管理领域逻辑。对应 SR-F1.1~F1.9（My Day / 状态机 / 分组 / 子任务 / Repeat / 逾期）。

纯领域逻辑，不碰 SQL（sqlite 由 storage 层处理，本层用连接对象）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

from timeflow.core import attach as attach_mod

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

# 优先级（SR-F1.2 / 段2 决策）：只有三档，**默认「中」**；不做 1–5 数字分级，也不做拖拽排序。
PRIORITY_HIGH = "高"
PRIORITY_MID = "中"
PRIORITY_LOW = "低"
VALID_PRIORITIES = (PRIORITY_HIGH, PRIORITY_MID, PRIORITY_LOW)
DEFAULT_PRIORITY = PRIORITY_MID
_PRIORITY_RANK = {PRIORITY_HIGH: 0, PRIORITY_MID: 1, PRIORITY_LOW: 2}

# 排序口径（三处统一：列表 / My Day / 逾期）：**截止日 → 优先级 → 创建时间**；无截止日排最后。
# 写成 SQL 片段是为了让三处用**同一份**口径，避免"各视图各排各的"（那正是 SR-F1.2 要收的口子）。
_ORDER_BY = (
    " ORDER BY due_date IS NULL, due_date,"
    " CASE priority WHEN '高' THEN 0 WHEN '中' THEN 1 WHEN '低' THEN 2 ELSE 1 END,"
    " created_at"
)

# 三个智能视图（SR-F1.3 / T-B3）：口径写在**领域层**，界面只负责显示
# （免得同一套筛选在前端/后端/测试三处各写一遍）。
VIEW_IMPORTANT = "important"
VIEW_PLANNED = "planned"
VIEW_FLAGGED = "flagged"
# 视图 → SQL 条件（取自白名单，不拼用户输入）
_VIEW_WHERE = {
    VIEW_IMPORTANT: "priority = '高'",
    VIEW_PLANNED: "due_date IS NOT NULL",
    VIEW_FLAGGED: "flagged = 1",
}
VALID_VIEWS = tuple(_VIEW_WHERE)


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
    # 备注（SR-F1.4 / T-B1）：人写的说明，列表不显示、详情面板可写（渐进聚焦）。
    # 默认值放在最后，老代码按位置构造 Task 也不会被破坏。
    note: str | None = None
    # 优先级（SR-F1.2 / T-B2）：高/中/低，默认「中」。
    priority: str = DEFAULT_PRIORITY
    # 手动标记（SR-F1.3 / T-B3）：用户自己按的标记位，Flagged 视图就是它。
    flagged: bool = False
    # 附件 / 要求链接（SR-F1.4 / T-B4）：元素 `{target, title}`；打开规则见 core/attach.py。
    attach: list[dict[str, str | None]] = field(default_factory=list)
    # 提醒（SR-F1.4 / T-B5）：本地时间字符串 `YYYY-MM-DDTHH:MM`，可空=不提醒。
    remind_at: str | None = None


def _row_to_task(row: sqlite3.Row) -> Task:
    keys = set(row.keys())
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
        # 缺列兜底：迁移（v6/v7/v8）已保证列存在，但残缺库/手工建的测试库可能没有
        note=row["note"] if "note" in keys else None,
        priority=row["priority"] if "priority" in keys else DEFAULT_PRIORITY,
        flagged=bool(row["flagged"]) if "flagged" in keys else False,
        attach=attach_mod.load_attach(row["attach"]) if "attach" in keys else [],
        remind_at=row["remind_at"] if "remind_at" in keys else None,
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _check_priority(value: object) -> str:
    """优先级只有三档（高/中/低）—— 别的一律拒绝，不静默降级（避免"设了高却没生效"）。"""
    if value not in VALID_PRIORITIES:
        raise ValueError(f"非法优先级: {value}（只能是 高/中/低）")
    return str(value)


# 提醒时间：本地时间字符串 `YYYY-MM-DDTHH:MM`（前端 datetime-local 就是这个形状）。
# 为什么不用 UTC：本项目全部日期口径都是**本地时间**（见 U-07「日期框默认今天」的教训，
# 用 UTC 会在东八区晚上差一天）；提醒要跟着用户的钟表走。
_REMIND_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _check_remind_at(value: object) -> str | None:
    """校验并规整提醒时间。空值 = 清除提醒（存 NULL，不写空串）；非法值拒绝（不猜、不静默忽略）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _REMIND_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    raise ValueError(f"提醒时间格式不对: {value}（要「2026-09-20 08:30」这样的日期+时间）")


def reminder_state(task: Task, now: datetime | None = None) -> str | None:
    """提醒的**界面口径**（一处定义，卡片/详情/自检都用它）：`over` / `today` / `soon` / `later`。

    - `over`  = 已经到点或过点（该提醒了）；
    - `today` = 今天稍后；
    - `soon`  = 7 天内；
    - `later` = 更远；
    - `None`  = 没设提醒 / 任务已完成（完成后不再催——**不打扰**是基调）。
    为什么放领域层：这是"什么时候算该提醒"的**口径**，写在前端就会和通知通道各算一套。
    """
    if not task.remind_at or task.status in (STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES):
        return None
    now = now or datetime.now()
    try:
        when = datetime.fromisoformat(task.remind_at)
    except ValueError:
        return None
    delta_days = (when.date() - now.date()).days
    if when <= now:
        return "over"
    if delta_days == 0:
        return "today"
    if delta_days <= 7:
        return "soon"
    return "later"


def due_reminders(conn: sqlite3.Connection, now: datetime | None = None) -> list[Task]:
    """到点该提醒的任务（T-B5）：`remind_at <= now` 且任务还"活着"（非完成/取消/归档/已删）。

    按提醒时间正序 —— 越早该提醒的越靠前。**只读**：不改任务、不发事实
    （通知只是"把已知时间说出来"，不改变任何账目）。
    """
    moment = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M")
    rows = conn.execute(
        "SELECT * FROM tasks WHERE remind_at IS NOT NULL AND remind_at <= ? "
        "AND status NOT IN (?,?,?,?) ORDER BY remind_at",
        (moment, STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def create_task(
    conn: sqlite3.Connection,
    title: str,
    due_date: str | None = None,
    group_name: str | None = None,
    repeat_days: int | None = None,
    parent_id: str | None = None,
    is_myday: bool = False,
    note: str | None = None,
    priority: str = DEFAULT_PRIORITY,
    flagged: bool = False,
    attach: list[dict[str, str | None]] | None = None,
    remind_at: str | None = None,
) -> Task:
    """新建任务（AC-1）。校验标题非空；若 due 过去且未完成，初始状态标逾期。"""
    title = title.strip()
    if not title:
        raise ValueError("任务标题不能为空")
    priority = _check_priority(priority)
    remind_at = _check_remind_at(remind_at)
    now = _now()
    task_id = uuid.uuid4().hex[:12]
    status = STATUS_TODO
    if due_date and due_date < _today():
        status = STATUS_OVERDUE
    conn.execute(
        """
        INSERT INTO tasks
        (id, title, due_date, group_name, repeat_days, parent_id, is_myday, status,
         created_at, updated_at, version, note, priority, flagged, attach, remind_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)
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
            note,
            priority,
            int(bool(flagged)),
            attach_mod.dump_attach(attach_mod.load_attach(attach or [])),
            remind_at,
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
    """任务列表（**按统一口径排序**：截止日 → 优先级 → 创建时间）。

    `active_only=True` 时排除「归档 / 已删（软删除）」。
    回收站（`active_only=False`）也走同一排序，让"最近该处理的"排前面。
    """
    sql = "SELECT * FROM tasks"
    params: tuple[object, ...] = ()
    if active_only:
        sql += " WHERE status NOT IN (?,?)"
        params = HIDDEN_STATUSES
    rows = conn.execute(sql + _ORDER_BY, params).fetchall()
    return [_row_to_task(r) for r in rows]


def tasks_in_view(conn: sqlite3.Connection, view: str) -> list[Task]:
    """智能视图（SR-F1.3 / T-B3）：`important` / `planned` / `flagged`。

    口径（**在领域层定死，界面不自己筛**）：
    - `important` = 优先级「高」（T-B2 的字段）；
    - `planned`   = **有截止日**（Planned 的本义是"排进日历的事"）；
    - `flagged`   = **手动标记位**（用户自己按的，不是自动推断"重要"）。
    基线同「全部任务」：只隐藏**归档 / 已删**（完成的仍如实显示），排序同统一口径。
    未知视图名 → ValueError（由 API 转 400），**不静默返回全部**（那会让人以为筛选生效了）。
    """
    if view not in _VIEW_WHERE:
        raise ValueError(f"未知视图: {view}（只能是 {'/'.join(VALID_VIEWS)}）")
    where = _VIEW_WHERE[view]  # 取自白名单字典，不含用户输入
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE status NOT IN (?,?) AND {where}" + _ORDER_BY,  # noqa: S608
        HIDDEN_STATUSES,
    ).fetchall()
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
        "note",
        "priority",
        "flagged",
        "attach",
        "remind_at",
    }
    # 注意：用"键在 payload 里"判断，而不是"值不是 None" ——
    # 否则 `parent_id=None` / `due_date=None` 这类**清空操作**会被静默忽略（实测踩到）。
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_task(conn, task_id)
    if "status" in updates and updates["status"] not in VALID_STATUS:
        raise ValueError(f"非法状态: {updates['status']}")
    if "priority" in updates:
        # 优先级**不可清空**（没有"无优先级"这一态）：非法/None 一律拒绝，不静默变默认值
        _check_priority(updates["priority"])
    if "flagged" in updates:
        # 布尔位统一收敛成 0/1（接口传的是 JSON true/false，这里再收一道，免得写进 1/"1"/None）
        updates["flagged"] = int(bool(updates["flagged"]))
    if "attach" in updates:
        # 附件列表：规整 + 落成 JSON 文本（坏数据在这里被挡下，不让它进库）
        updates["attach"] = attach_mod.dump_attach(attach_mod.load_attach(updates["attach"]))
    if "remind_at" in updates:
        # 提醒时间：空值=清除（NULL）；非法格式拒绝（不静默忽略）
        updates["remind_at"] = _check_remind_at(updates["remind_at"])
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
    """彻底删除（不可逆）。

    只允许删**已删（回收站）里的任务**：这是界面上「彻底删除 / 清空回收站」的入口，
    目的是让回收站不会无限堆积，同时避免误用——活动中的任务必须先走 `delete_task`（软删除）。
    幂等：任务已不存在时什么都不做。
    """
    try:
        current = get_task(conn, task_id)
    except KeyError:
        return
    if current.status != STATUS_DELETED:
        raise ValueError("只有回收站里（已删）的任务才能彻底删除")
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()


def purge_deleted_tasks(conn: sqlite3.Connection) -> int:
    """清空回收站：物理删除所有「已删」任务，返回删除条数（幂等，无已删任务时返回 0）。"""
    rows = conn.execute("SELECT id FROM tasks WHERE status = ?", (STATUS_DELETED,)).fetchall()
    ids = [str(r["id"]) for r in rows]
    for task_id in ids:
        purge_task(conn, task_id)
    return len(ids)


def myday_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """My Day 集合（AC-4）：is_myday=1 且非完成/取消/归档/已删；**按统一口径排序**。"""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE is_myday = 1 AND status NOT IN (?,?,?,?)" + _ORDER_BY,
        (STATUS_DONE, STATUS_CANCELLED, *HIDDEN_STATUSES),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def _sort_key(task: Task) -> tuple[int, str, int, str]:
    """Python 侧排序键 —— 与 `_ORDER_BY` **同口径**（无截止日最后 → 截止日 → 优先级 → 创建时间）。

    为什么要有第二份：逾期栏是"SQL 查出来的 + 无截止日但昨天就该做的 My Day"两拨合并，
    只能先在 SQL 里排、再在 Python 里重排一次；两份口径必须一致，否则逾期栏与列表顺序会打架。
    """
    return (
        1 if task.due_date is None else 0,
        task.due_date or "",
        _PRIORITY_RANK.get(task.priority, 1),
        task.created_at,
    )


def overdue_tasks(conn: sqlite3.Connection, today: str | None = None) -> list[Task]:
    """逾期任务（AC-5）：未完成且 due_date < 今天（不强推，只如实列出）；**按统一口径排序**。

    AC-4 补充：无截止日但**昨日仍未完成的 My Day 任务**也自动移入逾期栏
    （My Day=今天要做的集合，没做完不假装消失）。
    """
    t = today or _today()
    t_date = date.fromisoformat(t)
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date IS NOT NULL AND due_date < ? "
        "AND status NOT IN (?,?,?,?)" + _ORDER_BY,
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
    overdue.sort(key=_sort_key)
    return overdue


# ---------------------------------------------------------------- 子任务（SR-F1.6 / OP-12）
def subtask_progress(conn: sqlite3.Connection, task_id: str) -> dict[str, int]:
    """子任务进度：{done, total}（没有子任务时 total=0）。"""
    rows = conn.execute("SELECT status FROM tasks WHERE parent_id = ?", (task_id,)).fetchall()
    total = len(rows)
    done = sum(1 for r in rows if r["status"] == STATUS_DONE)
    return {"done": done, "total": total}


def subtasks(conn: sqlite3.Connection, task_id: str) -> list[Task]:
    """列出子任务：未完成在前，再按截止日（无截止日最后）；同状态按创建时间。"""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE parent_id = ? "
        "ORDER BY (status = ?) ASC, due_date IS NULL, due_date, created_at",
        (task_id, STATUS_DONE),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def _would_cycle(conn: sqlite3.Connection, task_id: str, parent_id: str) -> bool:
    """把 task_id 挂到 parent_id 下会不会成环（沿父链上溯，撞到自己就是环）。"""
    seen: set[str] = set()
    cursor: str | None = parent_id
    while cursor and cursor not in seen:
        if cursor == task_id:
            return True
        seen.add(cursor)
        row = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (cursor,)).fetchone()
        cursor = str(row["parent_id"]) if row and row["parent_id"] else None
    return False


def _autocomplete_parent(conn: sqlite3.Connection, parent_id: str | None) -> Task | None:
    """子任务全完成时**自动完成父任务**（OP-12 联动）。

    父任务若还有别的未完成子任务，`complete_task` 会抛 ValueError —— 那不是错误，
    只是"还没到时候"，这里静默忽略。
    """
    if not parent_id:
        return None
    progress = subtask_progress(conn, parent_id)
    if progress["total"] == 0 or progress["done"] < progress["total"]:
        return None
    try:
        return complete_task(conn, parent_id)
    except (KeyError, ValueError):
        return None


def create_subtask(
    conn: sqlite3.Connection,
    parent_id: str,
    title: str,
    due_date: str | None = None,
) -> Task:
    """新建子任务（OP-12）。父任务不存在 → KeyError；标题空 → ValueError。

    继承父任务的 My Day 归属（子任务跟着父任务出现在今天的清单里）；
    建完若父任务的子任务已全部完成 → 自动完成父任务。
    """
    parent = get_task(conn, parent_id)
    if not title.strip():
        raise ValueError("子任务标题不能为空")
    child = create_task(
        conn,
        title.strip(),
        due_date=due_date,
        parent_id=parent_id,
        is_myday=parent.is_myday,
    )
    _autocomplete_parent(conn, parent_id)
    return get_task(conn, child.id)


def set_task_parent(
    conn: sqlite3.Connection, task_id: str, parent_id: str | None
) -> Task:
    """改父任务（OP-12 边界：**禁止成环**）。`parent_id=None` 表示脱离父任务。"""
    if parent_id is not None:
        if parent_id == task_id:
            raise ValueError("任务不能作为自己的子任务")
        get_task(conn, parent_id)  # 父任务不存在 → KeyError
        if _would_cycle(conn, task_id, parent_id):
            raise ValueError("不能把任务挂到它自己的子任务下（会成环）")
    return update_task(conn, task_id, parent_id=parent_id)


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
    # 子任务全完成 → 父任务自动完成（OP-12 联动）。
    # 放在最后、并且只在"确实还有父任务"时递归一层 —— 链式向上（子→父→祖父）不会无限递归：
    # 每上一层，`complete_task` 都会先检查那一层的子任务是否全完成。
    if done.parent_id:
        _autocomplete_parent(conn, done.parent_id)
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


def toggle_flag(conn: sqlite3.Connection, task_id: str) -> Task:
    """手动标记开关（T-B3 / Flagged 视图的唯一入口）：翻转 `flagged`，幂等可反复按。

    注意：标记只是"我自己圈出来要留意"，**不发事实、不改状态、不动账本**
    （与「优先级」「备注」同属任务定义，不是"发生了什么"）。
    """
    current = get_task(conn, task_id)
    return update_task(conn, task_id, flagged=not current.flagged)


# ---------------------------------------------------------------- 附件 / 要求链接（SR-F1.4 / T-B4）
def add_attachment(
    conn: sqlite3.Connection,
    task_id: str,
    target: str,
    title: str | None = None,
) -> Task:
    """给任务加一条附件/要求链接（T-B4）。同一个 target 加两次是误操作 → 幂等不加。

    只存引用（网址或本地路径），**不复制文件内容**（对齐 conventions 的存储边界）。
    """
    current = get_task(conn, task_id)
    items = attach_mod.add_attachment_item(current.attach, target, title)
    return update_task(conn, task_id, attach=items)


def remove_attachment(conn: sqlite3.Connection, task_id: str, index: int) -> Task:
    """按下标删一条附件（T-B4）。越界 → ValueError（不静默无操作）。"""
    current = get_task(conn, task_id)
    items = attach_mod.remove_attachment_item(current.attach, index)
    return update_task(conn, task_id, attach=items)


def process_repeats(conn: sqlite3.Connection) -> int:
    """Repeat（AC-8 / OP-8）：为「已完成且设了重复」的任务生成下一次。返回本次生成数。

    口径：
    - 基准是**上次完成时间**（`updated_at`，完成即写）；无截止日的任务不生成（无从推算下一次）。
    - **幂等**：同一任务只生成一次下一次 —— 以 `task.repeat.generated` 事实为准
      （该事实随生成一起写入，既做去重依据，也留下可审计痕迹）。
    - 继承：标题 / 分组 / 重复周期 / 是否 My Day（下一次仍进今天，保持动线连续）
      + **优先级**（T-B2：优先级是"这件事有多要紧"，属于任务定义，不该每周期掉回默认「中」）。
      **备注不继承**（T-B1：备注往往是这一次的具体说明，抄到下一周期会变成误导）。
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
            priority=task.priority,
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
