"""跨端同步（SR-F9.2）：LWW（较新者胜）+ 同 id 去重 + 来源标记。对应 AC 同步。

移动端 PWA 离线优先，回电脑网络后异步对齐。原则：**不静默覆盖**——
冲突时以「修改时间戳 + version」判定较新者胜，同时记录冲突日志供提示。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# 优先级三档（与 `core/tasks/manager.py` 同口径）。这里只做**数据校验**用的常量，
# 不 import 领域层，避免 storage/sync 与 tasks 相互依赖。
_VALID_PRIORITIES = ("高", "中", "低")
_DEFAULT_PRIORITY = "中"


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
        "SELECT updated_at, version, note, priority FROM tasks WHERE id = ?", (tid,)
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
            "is_myday, status, created_at, updated_at, version, note, priority) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
        conn.execute(
            "UPDATE tasks SET title=?, due_date=?, group_name=?, repeat_days=?, parent_id=?, "
            "is_myday=?, status=?, note=?, priority=?, updated_at=?, version=? WHERE id=?",
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
                remote_updated,
                remote_version,
                tid,
            ),
        )
        conn.commit()
        return "updated"
    return "skipped"


def log_conflict(
    conn: sqlite3.Connection, entity: str, entity_id: str, local_ts: str, remote_ts: str
) -> None:
    """记录一次同步冲突（供日志/提示，不静默覆盖）。

    主键用随机 id，**不用秒级时间戳** —— 否则同一秒内的两次冲突会撞主键
    （第 10 步由测试发现：原实现 `_now_iso()` 作 id 会 IntegrityError）。
    """
    conn.execute(
        "INSERT INTO sync_logs (id, entity, entity_id, local_ts, remote_ts, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (_uid(), entity, entity_id, local_ts, remote_ts, _now_iso()),
    )
    conn.commit()


def status(conn: sqlite3.Connection) -> dict[str, object]:
    """同步状态摘要（OP-40/OP-41 的可观测面）。

    **诚实声明**：本软件提供的是「接受远端记录 + LWW 合并 + 冲突留痕」的语义；
    真正的跨端传输流程（谁在何时推拉、频率、鉴权）**尚未实现**，
    因此 `enabled` 恒为 False，不谎报"已同步"。这里只报告事实：冲突日志条数与最近时间。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(created_at) AS last FROM sync_logs"
    ).fetchone()
    return {
        "enabled": False,
        "conflict_logs": int(row["n"] or 0),
        "last_conflict_at": row["last"],
    }
