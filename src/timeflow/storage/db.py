"""SQLite 存储层 + schema 版本化迁移。对应 SR-F9.1/9.3。

用标准库 sqlite3（轻量、零运维）。数据本地保存，路径来自配置。
迁移机制：SCHEMA_VERSION 只增不减；connect() 时逐版本升级到目标版本。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


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
        _create_all(conn)
    else:
        current = int(row["version"])
        if current < SCHEMA_VERSION:
            _upgrade(conn, current)
    conn.commit()


def _upgrade(conn: sqlite3.Connection, current: int) -> None:
    """逐版本迁移到 SCHEMA_VERSION。每版只做增量、幂等（CREATE IF NOT EXISTS）。"""
    if current < 2:
        _migrate_v2(conn)  # 多分组 + F3–F8 基础表
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _create_all(conn: sqlite3.Connection) -> None:
    _migrate_v1(conn)
    _migrate_v2(conn)


def _migrate_v1(conn: sqlite3.Connection) -> None:
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


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v2：多分组关联表 + F3–F8 基础域表（习惯/专注/学业/复习/备忘录/产出流水）。"""
    # 多分组（SR-F1.3，AC-6）：tasks 与 groups 多对多
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            created_at  TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_groups (
            task_id     TEXT NOT NULL,
            group_id    TEXT NOT NULL,
            PRIMARY KEY (task_id, group_id)
        )
        """
    )

    # 专注记录（SR-F3，AC 专注）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id          TEXT PRIMARY KEY,
            task_id     TEXT,
            kind        TEXT NOT NULL,          -- tomato / plain
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            duration_sec INTEGER,
            status      TEXT NOT NULL DEFAULT 'finished',  -- finished/paused/abandoned/interrupted
            device_id   TEXT,
            created_at  TEXT
        )
        """
    )

    # 习惯打卡（SR-F4，AC 习惯）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_logs (
            habit_id    TEXT NOT NULL,
            date        TEXT NOT NULL,
            done        INTEGER DEFAULT 1,
            PRIMARY KEY (habit_id, date)
        )
        """
    )

    # 每日反馈 + 自检（SR-F4，AC 反馈）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_logs (
            date        TEXT PRIMARY KEY,
            plan_note   TEXT,
            executed    TEXT,
            gap_note    TEXT,
            focus_minutes REAL DEFAULT 0,
            created_at  TEXT
        )
        """
    )

    # 学业：课程档案 + 考核项 + GPA（SR-F5，AC 学业）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            credits     REAL,
            teacher     TEXT,
            note        TEXT,
            created_at  TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS course_assessments (
            id          TEXT PRIMARY KEY,
            course_id   TEXT NOT NULL,
            name        TEXT NOT NULL,          -- 考试/作业/论文/小测
            due_date    TEXT,
            weight      REAL,
            score       REAL,
            note        TEXT,
            created_at  TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grades (
            id          TEXT PRIMARY KEY,
            course_id   TEXT,
            term        TEXT,
            score       REAL,
            credits     REAL,
            created_at  TEXT
        )
        """
    )

    # 复习卡（SR-F6，AC 复习）——FSRS 调度字段预留
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_items (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            form        TEXT DEFAULT 'qa',      -- cloze / qa / exam
            source      TEXT DEFAULT 'internal',-- internal / external
            due_date    TEXT,
            interval_days REAL,
            ease        REAL DEFAULT 2.5,
            reps        INTEGER DEFAULT 0,
            lapses      INTEGER DEFAULT 0,
            state       TEXT DEFAULT 'due',     -- due / learning / review / done
            ref_handle  TEXT,                    -- Vault 路径 / KB-id 引用句柄（SR-F8）
            created_at  TEXT
        )
        """
    )

    # 备忘录（SR-F8，AC 备忘录）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memos (
            id          TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            ref_handle  TEXT,
            task_id     TEXT,
            created_at  TEXT
        )
        """
    )

    # B 系统产出/投入流水（SR-F2，AC 记账）——轻债务现有 ledger.py 用任务算，此处落产出流水
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id          TEXT PRIMARY KEY,
            axis        TEXT NOT NULL,          -- invest / output
            kind        TEXT NOT NULL,          -- focus / habit / task_done / kpi / asset / review
            value       REAL,
            date        TEXT,
            note        TEXT,
            ref_handle  TEXT,
            created_at  TEXT
        )
        """
    )

    # 团队/AI 分配记录（SR-F7）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_assignments (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            assignee    TEXT NOT NULL,
            assigner    TEXT NOT NULL,
            note        TEXT,
            status      TEXT DEFAULT 'assigned',
            created_at  TEXT
        )
        """
    )

    # 同步冲突日志（SR-F9.2）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_logs (
            id          TEXT PRIMARY KEY,
            entity      TEXT NOT NULL,
            entity_id   TEXT NOT NULL,
            local_ts    TEXT,
            remote_ts   TEXT,
            created_at  TEXT
        )
        """
    )
