"""跨端同步（SR-F9.2）：LWW（较新者胜）+ 同 id 去重 + 来源标记。对应 AC 同步。

移动端 PWA 离线优先，回电脑网络后异步对齐。原则：**不静默覆盖**——
冲突时以「修改时间戳 + version」判定较新者胜，同时记录冲突日志供提示。
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from timeflow import clock

if TYPE_CHECKING:
    import sqlite3

# 优先级三档（与 `core/tasks/manager.py` 同口径）。这里只做**数据校验**用的常量，
# 不 import 领域层，避免 storage/sync 与 tasks 相互依赖。
_VALID_PRIORITIES = ("高", "中", "低")
_DEFAULT_PRIORITY = "中"
# 任务类型默认档（与 `core/tasks/manager.py` 同口径）：远端没带 task_type 时用它。
_DEFAULT_TASK_TYPE = "普通"


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return clock.now().isoformat(timespec="seconds")


def _to_int(value: object, default: int) -> int:
    """把远端字段安全转 int；None/非数字回退 default。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def newer_is_win(
    local_updated: str, remote_updated: str, local_version: int, remote_version: int
) -> bool:
    """LWW 判定：返回 remote 是否较新。

    version 是跨端同步的可靠递增标记，优先用它判定；version 一致时退化为时间戳。
    （本地任务新建时 updated_at=当前时刻，若只比时间戳，远端稍早但 version 更大也会被
    判败——故 version 优先更符合「谁更新」。）"""
    if remote_version != local_version:
        return remote_version > local_version
    return remote_updated > local_updated


def merge_task(
    conn: sqlite3.Connection,
    remote_task: dict[str, object],
    device_id: str | None = None,
) -> str:
    """把一条远端任务合并进本地（同 id 去重 + LWW）。

    若本地不存在该 id → 插入（来源标记 device_id，用于跨端去重）。
    若存在但远端较新 → 覆盖；否则保留本地。返回 merged（'inserted'/'updated'/'skipped'）。
    """
    tid = str(remote_task["id"])
    local = conn.execute(
        "SELECT updated_at, version, note, priority, flagged, attach, remind_at, task_type, "
        "course_id FROM tasks WHERE id = ?",
        (tid,),
    ).fetchone()
    remote_updated = str(remote_task.get("updated_at") or "")
    remote_version = _to_int(remote_task.get("version"), 1)
    # priority（T-B2）：**不可空、只有三档** —— 远端带了就必须合法（非法值直接拒绝，
    # 不写库也不静默降级）；没带（老客户端/旧快照）则回落默认「中」，覆盖时保留本地已有的值。
    remote_priority = remote_task.get("priority")
    if remote_priority is not None and str(remote_priority) not in _VALID_PRIORITIES:
        raise ValueError(f"非法优先级: {remote_priority}（只能是 高/中/低）")

    if local is None:
        # 本地不存在：插入（来源标记）
        conn.execute(
            "INSERT INTO tasks (id, title, due_date, group_name, repeat_days, parent_id, "
            "is_myday, status, created_at, updated_at, version, note, priority, flagged, attach, "
            "remind_at, task_type, course_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                remote_task.get("title"),
                remote_task.get("due_date"),
                remote_task.get("group_name"),
                remote_task.get("repeat_days"),
                remote_task.get("parent_id"),
                int(bool(remote_task.get("is_myday"))),
                remote_task.get("status", "未开始"),
                remote_task.get("created_at"),
                remote_updated,
                remote_version,
                remote_task.get("note"),
                str(remote_priority or _DEFAULT_PRIORITY),
                int(bool(remote_task.get("flagged"))),
                _remote_attach(remote_task),
                remote_task.get("remind_at"),
                # 类型/课程（T-C12）：老客户端不带这两个字段时回落默认「普通」+ 无课程，
                # 合法值直接写入（本模块不做领域校验 —— 远端非法值由合并方的领域层负责，
                # 这里只保证"带了就写、没带就用默认"，与 priority 同规矩）。
                str(remote_task.get("task_type") or _DEFAULT_TASK_TYPE),
                remote_task.get("course_id"),
            ),
        )
        conn.commit()
        return "inserted"

    local_updated = str(local["updated_at"])
    local_version = int(local["version"])
    if newer_is_win(local_updated, remote_updated, local_version, remote_version):
        # 远端较新，覆盖。
        # 注意 note（T-B1）：**只有远端记录里真的带了 note 才覆盖** ——
        # 老版本客户端/旧快照不带这个字段，直接覆盖会把本地写的备注清空（＝静默数据丢失）。
        # 其余字段沿既有口径（远端说了算）。
        note = remote_task["note"] if "note" in remote_task else local["note"]
        priority = str(remote_priority or local["priority"] or _DEFAULT_PRIORITY)
        # flagged（T-B3）：与 note 同规矩 —— 远端没带这个字段就保留本地的
        # （别把用户自己按的标记抹掉）
        flagged = (
            int(bool(remote_task["flagged"]))
            if "flagged" in remote_task
            else int(bool(local["flagged"]))
        )
        # attach（T-B4）：同规矩 —— 远端没带就保留本地附件列表（别把用户挂的要求链接抹掉）
        attach = _remote_attach(remote_task) if "attach" in remote_task else local["attach"]
        # remind_at（T-B5）：同上（这条提醒是用户自己定的时间，不能被旧快照抹掉）
        remind_at = (
            remote_task["remind_at"] if "remind_at" in remote_task else local["remind_at"]
        )
        # task_type / course_id（T-C12）：与 note/flagged/attach 同规矩 —— 远端没带就保留本地的
        # （老客户端/旧快照不带这两个字段，直接覆盖会把"这是哪门课的作业"抹掉）
        task_type = (
            str(remote_task["task_type"] or _DEFAULT_TASK_TYPE)
            if "task_type" in remote_task
            else (local["task_type"] or _DEFAULT_TASK_TYPE)
        )
        course_id = remote_task["course_id"] if "course_id" in remote_task else local["course_id"]
        conn.execute(
            "UPDATE tasks SET title=?, due_date=?, group_name=?, repeat_days=?, parent_id=?, "
            "is_myday=?, status=?, note=?, priority=?, flagged=?, attach=?, remind_at=?, "
            "task_type=?, course_id=?, updated_at=?, version=? WHERE id=?",
            (
                remote_task.get("title"),
                remote_task.get("due_date"),
                remote_task.get("group_name"),
                remote_task.get("repeat_days"),
                remote_task.get("parent_id"),
                int(bool(remote_task.get("is_myday"))),
                remote_task.get("status", "未开始"),
                note,
                priority,
                flagged,
                attach,
                remind_at,
                task_type,
                course_id,
                remote_updated,
                remote_version,
                tid,
            ),
        )
        conn.commit()
        return "updated"
    return "skipped"


def _remote_attach(remote_task: dict[str, object]) -> str:
    """远端记录的 attach → 本库存的 JSON 文本。

    容错：远端可能传列表（JSON 数组）或字符串；坏数据一律收敛成 `[]`
    （**不把坏 JSON 写进库**，也不因此拒绝整条合并）。本模块不 import 领域层，
    所以这里只做 JSON 层面的规整，不做附件语义校验。
    """
    raw = remote_task.get("attach")
    if raw is None:
        return "[]"
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except (TypeError, ValueError):
            return "[]"
    else:
        loaded = raw
    if not isinstance(loaded, list):
        return "[]"
    clean = [
        {"target": str(i["target"]).strip(), "title": (str(i["title"]).strip() or None)
         if i.get("title") else None}
        for i in loaded
        if isinstance(i, dict) and str(i.get("target") or "").strip()
    ]
    return json.dumps(clean, ensure_ascii=False)


def log_conflict(
    conn: sqlite3.Connection,
    entity: str,
    entity_id: str,
    local_ts: str,
    remote_ts: str,
    *,
    result: str = "",
    note: str = "",
) -> None:
    """记录一次同步冲突（供日志/提示，不静默覆盖）。

    主键用随机 id，**不用秒级时间戳** —— 否则同一秒内的两次冲突会撞主键
    （第 10 步由测试发现：原实现 `_now_iso()` 作 id 会 IntegrityError）。
    `result` / `note`（T-G8 起）：说清这次是"覆盖了"还是"保留了本地"、差在哪 ——
    **不静默覆盖**这条要求，光有时间戳是看不出来的。
    """
    conn.execute(
        "INSERT INTO sync_logs (id, entity, entity_id, local_ts, remote_ts, created_at, "
        "result, note) VALUES (?,?,?,?,?,?,?,?)",
        (_uid(), entity, entity_id, local_ts, remote_ts, _now_iso(), result, note[:400]),
    )
    conn.commit()


def status(conn: sqlite3.Connection) -> dict[str, object]:
    """同步状态摘要（OP-40/OP-41 的可观测面）。

    **诚实声明**：这一版能用的是**走文件**的跨端同步（导出/导入同步包，场景 ③，见
    `core/syncpack.py`）；**走网络**的推拉传输（同一 WiFi 直连 ②、手机离线 ①）**尚未实现** ——
    所以这里只报事实，`network_sync` 恒为 False，不谎报"已同步"。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(created_at) AS last FROM sync_logs"
    ).fetchone()
    return {
        "enabled": True,          # 兼容旧字段：文件同步（③）确实可用了
        "file_sync": True,
        "network_sync": False,
        "conflict_logs": int(row["n"] or 0),
        "last_conflict_at": row["last"],
    }
