"""事实读写（facts 表）。

事实 = 与心智模型无关的「发生了什么」。本模块只负责**存取事实**，
不做任何「算成账目/指标」的解读（那是 ledger 的职责）。

对应 SR-F9.1（可扩展多域）与约定层「数据分流」（计算型走结构化）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record(
    conn: sqlite3.Connection,
    kind: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    value_num: float | None = None,
    value_text: str | None = None,
    extra: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    source: str | None = None,
    device_id: str | None = None,
) -> str:
    """记一条事实，返回 fact id。

    - kind：事实类型，自由字符串，建议 "域.动作"（如 focus.finished）。
    - occurred_at：事实**发生**时间；缺省取当前时刻。
    - extra：罕见/结构化字段（JSON 兜底），不用于查询主路径。
    """
    if not kind or not kind.strip():
        raise ValueError("事实 kind 不能为空")
    fid = _uid()
    now = _now()
    conn.execute(
        """
        INSERT INTO facts
        (id, kind, subject_type, subject_id, value_num, value_text, extra,
         occurred_at, recorded_at, source, device_id, revision, supersedes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,1,NULL)
        """,
        (
            fid,
            kind.strip(),
            subject_type,
            subject_id,
            value_num,
            value_text,
            json.dumps(extra, ensure_ascii=False) if extra else None,
            occurred_at or now,
            now,
            source,
            device_id,
        ),
    )
    conn.commit()
    return fid


def query(
    conn: sqlite3.Connection,
    kind: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """按条件查事实（按发生时间升序）。

    kind 支持前缀通配：传 "focus.*" 等价于 kind LIKE 'focus.%'；
    传 "focus." 亦作前缀处理。
    """
    sql = "SELECT * FROM facts WHERE 1=1"
    params: list[Any] = []
    if kind:
        if kind.endswith("*"):
            sql += " AND kind LIKE ?"
            params.append(kind[:-1] + "%")
        elif kind.endswith("."):
            sql += " AND kind LIKE ?"
            params.append(kind + "%")
        else:
            sql += " AND kind = ?"
            params.append(kind)
    if subject_type:
        sql += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id:
        sql += " AND subject_id = ?"
        params.append(subject_id)
    if since:
        sql += " AND occurred_at >= ?"
        params.append(since)
    if until:
        sql += " AND occurred_at <= ?"
        params.append(until)
    sql += " ORDER BY occurred_at, recorded_at"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_dict(r) for r in rows]


def count(
    conn: sqlite3.Connection,
    kind: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> int:
    """统计事实条数。"""
    sql = "SELECT COUNT(*) AS n FROM facts WHERE 1=1"
    params: list[Any] = []
    if kind:
        if kind.endswith("*"):
            sql += " AND kind LIKE ?"
            params.append(kind[:-1] + "%")
        elif kind.endswith("."):
            sql += " AND kind LIKE ?"
            params.append(kind + "%")
        else:
            sql += " AND kind = ?"
            params.append(kind)
    if subject_type:
        sql += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id:
        sql += " AND subject_id = ?"
        params.append(subject_id)
    row = conn.execute(sql, tuple(params)).fetchone()
    return int(row["n"] or 0)


def latest_by_subject(
    conn: sqlite3.Connection, subject_type: str, subject_id: str
) -> dict[str, Any] | None:
    """取某主体最新一条事实（修正机制启用后，此处应过滤被 supersede 的）。"""
    rows = query(conn, subject_type=subject_type, subject_id=subject_id, limit=None)
    if not rows:
        return None
    return rows[-1]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = {
        "id": row["id"],
        "kind": row["kind"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "value_num": row["value_num"],
        "value_text": row["value_text"],
        "extra": json.loads(row["extra"]) if row["extra"] else None,
        "occurred_at": row["occurred_at"],
        "recorded_at": row["recorded_at"],
        "source": row["source"],
        "device_id": row["device_id"],
        "revision": row["revision"],
        "supersedes": row["supersedes"],
    }
    return d
