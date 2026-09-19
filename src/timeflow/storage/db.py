"""SQLite 存储层 + schema 版本化迁移。对应 SR-F9.1/9.3。

用标准库 sqlite3（轻量、零运维）。数据本地保存，路径来自配置。
迁移机制：SCHEMA_VERSION 只增不减；connect() 时逐版本升级到目标版本。

**并发约定（2026-09-18 修）**：sqlite3 的 Connection 不是线程安全的——多线程共用同一个连接时，
一个线程的 `commit()` 会打断另一个线程正在进行的事务，表现为
`cannot commit - no transaction is active`、`another row available`、
`bad parameter or other API misuse` 等
（实测：并发 80 次读写有 16 次异常；真机上表现为「快速点击顶部导航 → 操作未完成」）。
因此 `thread_local(db_path)` 返回的代理**按线程各持一个连接**，路由代码无需改动。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 9


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


class _ThreadLocalConn:
    """按线程分发连接的代理：路由代码继续用 `conn.execute(...)`，但每个线程各自持有连接。

    这样既修掉并发下的事务互相打断，又不需要改动任何路由签名与测试（最小侵入）。
    用途限定在「多线程服务共享一个 conn 变量」的场景；单线程脚本用 `connect()` 即可。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self._db_path)
            self._local.conn = conn
        return conn

    def execute(self, *args: object, **kwargs: object) -> sqlite3.Cursor:
        cur = self._conn().execute(*args, **kwargs)  # type: ignore[arg-type]
        return cur

    def executemany(self, *args: object, **kwargs: object) -> sqlite3.Cursor:
        cur = self._conn().executemany(*args, **kwargs)  # type: ignore[arg-type]
        return cur

    def executescript(self, script: str) -> sqlite3.Cursor:
        return self._conn().executescript(script)

    def commit(self) -> None:
        self._conn().commit()

    def rollback(self) -> None:
        self._conn().rollback()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def cursor(self) -> sqlite3.Cursor:
        return self._conn().cursor()

    def __getattr__(self, name: str) -> object:
        # 其余属性（如 row_factory / in_transaction）透传给当前线程的连接
        return getattr(self._conn(), name)


def thread_local(db_path: str) -> sqlite3.Connection:
    """给多线程 HTTP 服务用的连接：**每个线程一个 Connection**（见模块开头并发约定）。

    返回类型标注为 Connection 以便路由代码与 mypy 不用感知代理细节。
    """
    return _ThreadLocalConn(db_path)  # type: ignore[return-value]


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
    if current < 3:
        _migrate_v3(conn)  # 事实层（facts）——事实与解读分离的地基
    if current < 4:
        _migrate_v4(conn)  # 历史 focus_sessions 回填为 facts（第 1 步前兼容旧数据）
    if current < 5:
        _migrate_v5(conn)  # 历史已完成任务回填 task.completed 事实（第 3 步）
    if current < 6:
        _migrate_v6(conn)  # 任务备注 note（F1 段2 · T-B1）
    if current < 7:
        _migrate_v7(conn)  # 任务优先级 priority（F1 段2 · T-B2）
    if current < 8:
        _migrate_v8(conn)  # 任务手动标记 flagged（F1 段2 · T-B3）
    if current < 9:
        _migrate_v9(conn)  # 附件/要求链接 attach + 应用设置表（F1/F5 段2 · T-B4）
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _create_all(conn: sqlite3.Connection) -> None:
    _migrate_v1(conn)
    _migrate_v2(conn)
    _migrate_v3(conn)
    _migrate_v4(conn)  # 新库 focus_sessions 为空，此处为空操作
    _migrate_v5(conn)  # 新库 tasks 为空，此处为空操作
    _migrate_v6(conn)  # 新库也要走一遍：v1 的 tasks 建表语句保持历史原样，note 由本版加列
    _migrate_v7(conn)  # 同上：priority 由本版加列
    _migrate_v8(conn)  # 同上：flagged 由本版加列
    _migrate_v9(conn)  # 新库也要走一遍：attach 两列与 app_settings 表


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


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v3：事实层（facts）——事实与解读分离的地基。

    事实 = 与心智模型无关的「发生了什么」（见 复盘/事实层架构设计复盘.md）：
    - kind 为自由字符串（"域.动作"），加新事实类型不改表；
    - 高频值放 value_num/value_text（可索引），罕见字段放 extra(JSON) 兜底；
    - revision/supersedes 为修正机制预留（MVP 不实现逻辑）。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id           TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            subject_type TEXT,
            subject_id   TEXT,
            value_num    REAL,
            value_text   TEXT,
            extra        TEXT,
            occurred_at  TEXT NOT NULL,
            recorded_at  TEXT NOT NULL,
            source       TEXT,
            device_id    TEXT,
            revision     INTEGER DEFAULT 1,
            supersedes   TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_facts_kind_time ON facts(kind, occurred_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_type, subject_id)"
    )


_END_KIND_BY_STATUS = {
    "finished": "focus.finished",
    "paused": "focus.paused",
    "abandoned": "focus.abandoned",
    "interrupted": "focus.interrupted",
}


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """v4：把历史 focus_sessions 幂等回填为 facts。

    第 1 步 ledger 改读 facts 后，v3 之前的旧专注记录不能归零；
    这里只回填 focus 这一域，其余域仍按重构第 3 步迁移。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='focus_sessions'"
        ).fetchone()
        is None
    ):
        return  # 极端旧库 / 残缺库：无 focus_sessions 表，跳过回填
    rows = conn.execute(
        "SELECT id, task_id, started_at, ended_at, duration_sec, status, device_id "
        "FROM focus_sessions"
    ).fetchall()
    if not rows:
        return
    existing: set[str] = set()
    for fact in conn.execute("SELECT extra FROM facts WHERE kind LIKE 'focus.%'").fetchall():
        raw = fact["extra"]
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        sid = payload.get("session_id")
        if sid:
            existing.add(str(sid))
    for row in rows:
        sid = str(row["id"])
        if sid in existing:
            continue
        status = row["status"] or "finished"
        kind = _END_KIND_BY_STATUS.get(status, "focus.finished")
        occurred_at = row["ended_at"] or row["started_at"]
        extra = json.dumps(
            {"session_id": sid, "status": status, "migrated": True},
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT INTO facts
            (id, kind, subject_type, subject_id, value_num, value_text, extra,
             occurred_at, recorded_at, source, device_id, revision, supersedes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,1,NULL)
            """,
            (
                uuid.uuid4().hex[:12],
                kind,
                "task" if row["task_id"] else "focus_session",
                row["task_id"] or sid,
                float(row["duration_sec"] or 0),
                None,
                extra,
                occurred_at or datetime.now().isoformat(timespec="seconds"),
                datetime.now().isoformat(timespec="seconds"),
                "migration:v4",
                row["device_id"],
            ),
        )


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """v5：把历史**已完成**任务幂等回填为 `task.completed` 事实（重构第 3 步）。

    背景：第 2 步起「完成」由事实驱动，旧库里已完成的任务没有对应事实；
    若不回填，旧数据的完成记录在新口径下会「看起来没发生过」。
    口径（对齐 A-001 / 约定）：
    - 完成不估时 ⇒ `value_num=NULL`、`value_text=标题`；
    - 归属时间取 `updated_at`（完成时的最后写入时刻），无则退回 `created_at`；
    - `extra.migrated=True` 标明来源，便于与人/机新记录区分。
    幂等：按 `subject_id` 跳过已存在的 `task.completed` 事实。

    复习（`review_items`）**不在本版回填**：该表只有聚合的 reps/lapses，没有逐次复习时间戳，
    按迁移规则「不伪造时间」记为缺口（见 `复盘/缺口处理与假设台账.md` A-015）。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        is None
    ):
        return  # 极端旧库 / 残缺库：无 tasks 表，跳过长任务回填
    # 真实旧库可能缺列（如 v1 的 tasks 没有 due_date）：只取实际存在的列
    columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    selected = ", ".join(
        col
        for col in ("id", "title", "due_date", "updated_at", "created_at")
        if col in columns
    )
    rows = conn.execute(
        f"SELECT {selected} FROM tasks WHERE status = ?",  # noqa: S608 —— 列名取自白名单
        ("完成",),
    ).fetchall()
    if not rows:
        return
    existing: set[str] = set()
    for fact in conn.execute(
        "SELECT subject_id FROM facts WHERE kind = 'task.completed'"
    ).fetchall():
        if fact["subject_id"]:
            existing.add(str(fact["subject_id"]))
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        tid = str(row["id"])
        if tid in existing:
            continue
        keys = set(row.keys())
        title = row["title"] if "title" in keys else tid
        due_date = row["due_date"] if "due_date" in keys else None
        occurred_at = (
            (row["updated_at"] if "updated_at" in keys else None)
            or (row["created_at"] if "created_at" in keys else None)
            or now
        )
        extra = json.dumps(
            {"title": title, "due_date": due_date, "migrated": True},
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT INTO facts
            (id, kind, subject_type, subject_id, value_num, value_text, extra,
             occurred_at, recorded_at, source, device_id, revision, supersedes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,1,NULL)
            """,
            (
                uuid.uuid4().hex[:12],
                "task.completed",
                "task",
                tid,
                None,
                title,
                extra,
                occurred_at,
                now,
                "migration:v5",
                None,
            ),
        )


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """v6：任务加 `note`（备注）列 —— F1 段2 · T-B1（SR-F1.4 的「备注」）。

    口径：
    - **向后兼容的加列**（不改已有列、不动数据）：老库补一列，新库照常建；
    - **幂等**：先查 `PRAGMA table_info`，已有该列就什么都不做（重复连接/迁移都安全）；
    - 缺 tasks 表的残缺库直接跳过，不失败（与 v5 同规矩）。
    - 备注是**沉淀型内容**（人写的说明），不是计算型事实 —— 因此**不发 facts**
      （账本口径只认 facts，见 conventions「事实/解读分离」）。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        is None
    ):
        return  # 极端旧库 / 残缺库：无 tasks 表，跳过加列
    columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "note" in columns:
        return  # 幂等：新库（或已迁移过的库）直接返回
    conn.execute("ALTER TABLE tasks ADD COLUMN note TEXT")


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """v7：任务加 `priority`（优先级：高/中/低）—— F1 段2 · T-B2（SR-F1.2）。

    口径（段2 决策已定案）：
    - 三档 **高 / 中 / 低**，**默认「中」**（不给"无优先级"这种第四态，免得排序时又要想怎么排）；
    - 排序统一为 **截止日 → 优先级 → 创建时间**（无截止日排最后，见 `manager._ORDER_BY`）；
    - **不加 1–5 数字分级、不做拖拽排序**（拖拽要前端持久化顺序，属独立任务）。
    迁移性质：向后兼容加列、幂等（已有列就跳过）、缺 tasks 表的残缺库跳过；
    老行由 `DEFAULT '中'` 补齐，**不猜**（不按截止日远近偷偷标高低）。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        is None
    ):
        return  # 极端旧库 / 残缺库：无 tasks 表，跳过加列
    columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "priority" in columns:
        return  # 幂等
    conn.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT '中'")


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """v8：任务加 `flagged`（手动标记位）—— F1 段2 · T-B3（SR-F1.3 的 Flagged 视图）。

    口径（段2 决策）：
    - **手动标记**（用户自己按的），不是自动推断的"重要"——所以是个布尔位，`0/1`，默认 `0`；
    - 三个智能视图里：Important=**高优先级**、Planned=**有截止日**、Flagged=**本标记位**（T-B3）。
    迁移性质：向后兼容加列、幂等、缺 tasks 表的残缺库跳过；老行一律 `0`（**不猜**，不帮用户标）。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        is None
    ):
        return  # 极端旧库 / 残缺库：无 tasks 表，跳过加列
    columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "flagged" in columns:
        return  # 幂等
    conn.execute("ALTER TABLE tasks ADD COLUMN flagged INTEGER DEFAULT 0")


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """给已存在的表加列（缺列才加）。表不存在 / 列已在 → 返回 False，不报错。

    迁移脚本的通用小工具：加列必须**幂等**（重复连接、新库老库都要安全），
    且不能假设表一定存在（残缺库/极端旧库要跳过而不是崩）。
    """
    if (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is None
    ):
        return False
    columns = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    return True


def _migrate_v9(conn: sqlite3.Connection) -> None:
    """v9：附件 / 要求链接 `attach`（任务 + 学业考核项共用同一字段）+ 应用设置表 —— T-B4。

    口径（`复盘/段2设计决策-提醒与附件打开方式.md` §三）：
    - 附件 = JSON 数组文本，元素 `{target, title}`（网址或本地路径 + 可选标题）；
    - **任务与考核项用同一个字段名与同一套打开规则**（SR-F5.3 的"跳转要求"与任务的"附件"是一件事，
      分成两套只会让规则各写一遍）；
    - `app_settings`：通用 key/value 表 —— 第一个用户是「附件打开方式 / 直接打开白名单」，
      这两项必须**存在服务端**（不能由前端请求参数决定，否则任何网页都能要求"直接打开"）。
    老行一律 NULL（没有附件），不猜内容；缺表跳过不失败。
    """
    _add_column_if_missing(conn, "tasks", "attach", "attach TEXT")
    _add_column_if_missing(conn, "course_assessments", "attach", "attach TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT
        )
        """
    )
