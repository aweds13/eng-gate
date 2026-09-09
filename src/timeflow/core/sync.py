"""跨端同步（SR-F9.2）：LWW（较新者胜）+ 同 id 去重 + 来源标记。对应 AC 同步。

移动端 PWA 离线优先，回电脑网络后异步对齐。原则：**不静默覆盖**——
冲突时以「修改时间戳 + version」判定较新者胜，同时记录冲突日志供提示。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


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
    local = conn.execute("SELECT updated_at, version FROM tasks WHERE id = ?", (tid,)).fetchone()
    remote_updated = str(remote_task.get("updated_at") or "")
    remote_version = _to_int(remote_task.get("version"), 1)

    if local is None:
        # 本地不存在：插入（来源标记）
        conn.execute(
            "INSERT INTO tasks (id, title, due_date, group_name, repeat_days, parent_id, "
            "is_myday, status, created_at, updated_at, version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
            ),
        )
        conn.commit()
        return "inserted"

    local_updated = str(local["updated_at"])
    local_version = int(local["version"])
    if newer_is_win(local_updated, remote_updated, local_version, remote_version):
        # 远端较新，覆盖
        conn.execute(
            "UPDATE tasks SET title=?, due_date=?, group_name=?, repeat_days=?, parent_id=?, "
            "is_myday=?, status=?, updated_at=?, version=? WHERE id=?",
            (
                remote_task.get("title"),
                remote_task.get("due_date"),
                remote_task.get("group_name"),
                remote_task.get("repeat_days"),
                remote_task.get("parent_id"),
                int(bool(remote_task.get("is_myday"))),
                remote_task.get("status", "未开始"),
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
    """记录一次同步冲突（供日志/提示，不静默覆盖）。"""
    conn.execute(
        "INSERT INTO sync_logs (id, entity, entity_id, local_ts, remote_ts, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (_now_iso(), entity, entity_id, local_ts, remote_ts, _now_iso()),
    )
    conn.commit()
