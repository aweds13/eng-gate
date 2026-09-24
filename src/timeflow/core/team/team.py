"""团队/AI 协作领域逻辑（SR-F7.1~F7.4）。对应 AC 团队。

管理者/执行者两视角：任务可标注「分配给我 / 我分配」。
不强制执行者装本软件——只需「我知道谁负责什么、进展到哪」；
执行者状态第一版手动为主 + AI 接口（见 `src/api/`，只读+新增）。
团队任务不计个人投入（分配出去的不算我投入，只记协调/分配完成）。

**两个视角 = 同一份分配记录的两种看法**（SR-F7.1 / OP-33，`board()`）：
管理者看「我分配出去的，谁手上有什么」；执行者看「分给我的」。
判据里**没有账号体系** —— 执行者视角靠你自己说「我是谁」（`me` 去空格、不分大小写比对），
工具不猜、也不编一个"当前用户"出来（见 `复盘/团队视角页-T-G12.md`）。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

ROLE_MANAGER = "manager"
ROLE_EXECUTOR = "executor"

# 分配记录的四种状态（SR-F7 详细规格 §2）—— 词表与中文标签只在后端一处，
# 界面用 `GET /api/team/board` 的 `statuses` 渲染（避免前后端各写一份中文）。
ASSIGN_STATUSES: tuple[str, ...] = ("assigned", "in_progress", "done", "blocked")
STATUS_LABELS: dict[str, str] = {
    "assigned": "已分配",
    "in_progress": "进行中",
    "done": "已完成",
    "blocked": "受阻",
}

# 视角（OP-33）：**同一份分配记录，两种看法**，不是两套数据。
VIEW_MANAGER = "manager"
VIEW_EXECUTOR = "executor"
VIEW_LABELS: dict[str, str] = {
    VIEW_MANAGER: "管理者（我分配的）",
    VIEW_EXECUTOR: "执行者（分配给我的）",
}


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
    """给任务标注分配（管理者分给执行者）。返回分配记录 id。

    校验：任务必须存在（否则会在卡片上指向一个不存在的任务）；assignee 非空。
    """
    from timeflow.core import tasks as tm

    tm.get_task(conn, task_id)  # 不存在则 KeyError
    assignee = assignee.strip()
    if not assignee:
        raise ValueError("执行者不能为空")
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
    return [_row(r) for r in rows]


def assignments_for_task(
    conn: sqlite3.Connection, task_id: str
) -> list[dict[str, object]]:
    """某任务的分配记录（供任务卡片直接显示「谁负责 / 进展到哪」，SR-F7.1）。"""
    rows = conn.execute(
        "SELECT * FROM team_assignments WHERE task_id = ? ORDER BY created_at", (task_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def views_meta() -> list[dict[str, str]]:
    """能切的视角（供界面渲染切换按钮，中文只写在这一处）。"""
    return [{"value": k, "label": v} for k, v in VIEW_LABELS.items()]


def board(
    conn: sqlite3.Connection,
    *,
    view: str = VIEW_MANAGER,
    me: str = "",
    status: str | None = None,
) -> dict[str, object]:
    """团队视角页的数据（SR-F7.1 / OP-33）：**同一份分配记录的两种看法**。

    - `manager`：我分配出去的全部记录，按执行者分组 —— "谁手上有什么、进展到哪"；
    - `executor`：只留 `assignee == me` 的记录 —— "分给我的"。

    为什么执行者视角要你填一个名字：本工具**没有账号体系**（执行者就是自由文本），
    所以"我是谁"只能由你说。`me` 去首尾空格、大小写不敏感地比对；
    **没填就不猜** —— 返回空列表 + 一句说明，不报错、不硬塞一个人进去。

    任务被删掉的分配记录**留着**（规格 §4：保留审计或标记失效）：条目上带
    `task_missing=True`，界面如实写"任务已删除"，而不是让这条记录凭空消失。
    计数一律按当前视角范围内的事实算（`counts` 不受 `status` 筛选影响，筛选只是少看几条）。
    """
    if view not in VIEW_LABELS:
        raise ValueError(f"非法视角: {view}（能用的：{'/'.join(VIEW_LABELS)}）")
    if status is not None and status not in ASSIGN_STATUSES:
        raise ValueError(f"非法状态: {status}（能用的：{'/'.join(ASSIGN_STATUSES)}）")
    me_norm = str(me or "").strip()
    # 同一天建的记录 `created_at` 是同一个日期字符串（这一列只存到天），
    # 所以拿 `rowid`（插入顺序）当次级排序 —— 否则每次刷新顺序都可能变（id 是随机的）。
    rows = conn.execute(
        "SELECT a.id, a.task_id, a.assignee, a.assigner, a.note, a.status, a.created_at, "
        "t.title AS task_title, t.due_date AS task_due, t.status AS task_status "
        "FROM team_assignments a LEFT JOIN tasks t ON t.id = a.task_id "
        "ORDER BY a.created_at, a.rowid"
    ).fetchall()
    items = [_board_row(r, deleted_status=_deleted_status()) for r in rows]
    if view == VIEW_EXECUTOR:
        if not me_norm:
            items = []
        else:
            want = me_norm.casefold()
            items = [i for i in items if str(i["assignee"]).strip().casefold() == want]
    counts = {s: 0 for s in ASSIGN_STATUSES}
    for i in items:
        key = str(i["status"])
        if key in counts:
            counts[key] += 1
    shown = items if status is None else [i for i in items if i["status"] == status]
    # 按**执行者名**归组（不是"相邻同名"归组：同一个人可能被交替分配，A/B/A 也得合成一组）。
    # 组内保持记录创建顺序，组与组之间按名字排（不分大小写）—— 每次刷新顺序都一样。
    buckets: dict[str, list[dict[str, object]]] = {}
    for i in shown:
        buckets.setdefault(str(i["assignee"]), []).append(i)
    groups: list[dict[str, object]] = [
        {"assignee": name, "count": len(bucket), "items": bucket}
        for name, bucket in sorted(buckets.items(), key=lambda kv: kv[0].casefold())
    ]
    return {
        "view": view,
        "me": me_norm,
        "status_filter": status or "",
        "views": views_meta(),
        "statuses": [
            {"value": s, "label": STATUS_LABELS[s], "count": counts[s]} for s in ASSIGN_STATUSES
        ],
        "groups": groups,
        "total": len(items),
        "shown": len(shown),
        "note": _board_note(view, me_norm, len(items)),
    }


def _board_note(view: str, me: str, total: int) -> str:
    """视角页顶部那句实话：这一页看的是什么、边界在哪（界面直接显示，不自己造句）。"""
    if view == VIEW_MANAGER:
        return (
            "你分配出去的任务都在这里：谁手上有什么、进展到哪。"
            "分配出去不计投入。"
        )
    if not me:
        return (
            "执行者视角要先说「我是谁」—— 分配记录里的名字是你自己填的自由文本，"
            "工具没有账号体系，不猜你是谁。填一个名字，就能看分给你的那几件。"
        )
    if total == 0:
        return f"没有分给「{me}」的任务。名字要和分配记录里写的一致（空格和大小写无所谓）。"
    return f"分给「{me}」的任务：进展由你自己回报（点下一步动作）。不强制对方装这个软件。"


def _deleted_status() -> str:
    """任务"已删"那个状态词（软删除 = 在回收站）。**词表只有一处**（`core/tasks`），
    这里按需取，不在团队模块里另抄一个字面量 —— 抄一份就会有一天对不上。"""
    from timeflow.core import tasks as tm

    return str(tm.STATUS_DELETED)


def _board_row(r: sqlite3.Row, *, deleted_status: str) -> dict[str, object]:
    """一条分配记录 + 它指向的任务。

    三种情况分得开、都要如实说（规格 §4「任务删除后分配记录保留审计或标记失效」）：
    - 任务在 → 正常显示标题与状态；
    - 任务**软删**（进回收站）→ `task_deleted=True`，界面标"已删除（回收站）"；
    - 任务**彻底删掉** → `task_missing=True`，只剩这条审计记录，标题为 None。
    """
    title = r["task_title"]
    task_status = r["task_status"]
    return {
        "id": r["id"],
        "task_id": r["task_id"],
        "assignee": r["assignee"],
        "assigner": r["assigner"],
        "note": r["note"],
        "status": r["status"],
        "task_title": title,
        "task_due": r["task_due"],
        "task_status": task_status,
        "task_missing": title is None,
        "task_deleted": title is not None and task_status == deleted_status,
        "created_at": r["created_at"],
    }


def _row(r: sqlite3.Row) -> dict[str, object]:
    return {
        "id": r["id"],
        "task_id": r["task_id"],
        "assignee": r["assignee"],
        "assigner": r["assigner"],
        "note": r["note"],
        "status": r["status"],
    }
