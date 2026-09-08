"""SQLite 存储层 + schema 迁移。对应 SR-F9.1/9.3。

用标准库 sqlite3（轻量、零运维）。数据本地保存，路径来自配置。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        _create_tables(conn)
    conn.commit()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            due_date    TEXT,
            group_name  TEXT,
            repeat_days INTEGER,
            parent_id   TEXT,
            is_myday    INTEGER DEFAULT 0,
            status      TEXT DEFAULT '未开始',
            created_at  TEXT,
            updated_at  TEXT,
            version     INTEGER DEFAULT 1
        )
        """
    )
