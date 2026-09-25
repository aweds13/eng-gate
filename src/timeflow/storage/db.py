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
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from timeflow import clock

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解
    from collections.abc import Iterator

SCHEMA_VERSION = 19


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

    ★ 为什么 `commit()` 不是简单转发（T-G71 跨函数事务）：core 里 60 多个函数各自
    `conn.commit()`，而一个 HTTP 处理函数常常要把**两条** core 调用当成一件事
    （建任务 + 挂分组）。所以这里加了一层**延迟提交**：在 `unit_of_work()` 里，
    `commit()` 只记一笔「有写入」，真正提交发生在退出那段的时候 ——
    这就是"跨函数事务"在这套代码里的落点（SQLite 的隐式事务从第一次写就开着）。

    ★★ 延迟标记必须**跟着连接走**（本卡实测踩到，见 `复盘/跨函数事务-T-G71.md` §7）：
    一开始把它当成实例属性（`self._defer`），可这个代理是**全进程一个**、被所有线程共用 ——
    线程 A 进事务后，线程 B 的 `commit()` 也被记成"推迟"，而 A 退出时提交的是 **A 自己的连接**
    （`_conn()` 按线程取），于是 B 那笔写**永远没人提交**：别的连接看不见它、写锁还一直攥着，
    并发下直接 `database is locked`（`tests/test_concurrency.py` 当场抓到）。
    所以它住在 `threading.local()` 里。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()

    @property
    def _defer(self) -> int:
        """当前线程的"正在 unit_of_work 里"层数（>0 = commit 先记账）。"""
        return int(getattr(self._local, "defer", 0))

    @_defer.setter
    def _defer(self, value: int) -> None:
        self._local.defer = value

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
        # ★ `executescript` 会**先隐式提交**（sqlite3 的规定）—— 在 unit_of_work 里用它
        #   等于把事务撕开。本项目没有这样的调用点，所以这里不拦，只留一条实话。
        return self._conn().executescript(script)

    def commit(self) -> None:
        if self._defer:
            return  # 记账推迟到 unit_of_work 退出时（见类注释）
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


def raw_conn(conn: object) -> sqlite3.Connection:
    """拿到"线程代理"背后的**真连接**。

    为什么需要：SQLite 的**在线备份 API**（`Connection.backup`）要求目标是真 Connection，
    而 HTTP 服务里传下来的是 `_ThreadLocalConn` 代理（`_conn` 是个方法，不是属性）。
    真连接原样返回；拿不到就抛错（**不猜、不静默降级**）。
    """
    inner = getattr(conn, "_conn", None)
    if callable(inner):
        real = inner()
        if isinstance(real, sqlite3.Connection):
            return real
    if isinstance(conn, sqlite3.Connection):
        return conn
    raise TypeError(f"拿不到真连接：{type(conn)!r}")


@contextmanager
def unit_of_work(conn: object, *, what: str = "") -> Iterator[None]:
    """把一段里的**多条 core 调用合成一次提交**（跨函数事务）—— T-G33 的残留在这里收口。

    ## 为什么需要它

    `POST /api/tasks` 是"先 `tm.create_task()`（自己 commit）、再 `tm.set_task_groups()`
    （又自己 commit）"——中间那一步出数据库级错误时，**任务已经落库**：客户端看到报错、
    库里却多一条，重试就多两条。T-G33 当时把"坏分组"这一类**输入错**先验掉了
    （`_require_groups`），但"验完之后再出数据库级错误"这半句只能靠事务，记成了残留。

    ## 它怎么做到

    core 里 60 多个函数各自 `conn.commit()`，而 HTTP 那条路上的 `conn` 是
    `_ThreadLocalConn` 代理 —— 所以在**代理层**把 `commit()` 记下来（`_defer`），
    真正的提交发生在退出这段的时候：成功 → 一次 `commit`；抛异常 → 一次 `rollback`。
    SQLite 的隐式事务从第一次写就开着，所以这几笔写天然是一件事。

    ## 边界（不猜、不静默降级）

    - **只支持 HTTP 那条路**（`thread_local()` 的代理）：真 `sqlite3.Connection` 的 `commit`
      是 C 方法、拦不住 —— 拿它来调这里**直接报错**，不给你一个"以为有事务"的假象
      （与 `raw_conn` 同一条规矩）。
    - 事务覆盖的是**数据库行**，不覆盖系统副作用：`PUT /api/settings/reminder` 那条里
      `set_enabled` 还会注册 Windows 计划任务 —— 那个 SQLite 回滚不了（如实记在复盘里）。
    - `executescript()` 会先隐式提交，等于撕开事务（本项目没有这样的调用点）。
    - 外面的 core 若自己 `rollback()`，回滚的是**整个** unit（这正是"有事就全撤"的语义）。
    """
    proxy = conn if isinstance(conn, _ThreadLocalConn) else None
    if proxy is None:
        raise TypeError(
            "unit_of_work 只支持 HTTP 服务那条路（db.thread_local() 的代理）："
            f"真 Connection 的 commit 拦不住，拿它当事务是假象（收到 {type(conn)!r}；{what}）"
        )
    proxy._defer += 1
    try:
        yield
    except BaseException:
        proxy._defer -= 1
        if proxy._defer == 0:
            proxy._conn().rollback()
        raise
    else:
        proxy._defer -= 1
        if proxy._defer == 0:
            proxy._conn().commit()


def migrate(conn: sqlite3.Connection) -> None:
    """把库升到当前 `SCHEMA_VERSION`（**幂等**）。

    公开版入口：恢复备份后要把老 schema 就地升上来（`storage/backup.py` 用它），
    比在别的模块里直接调 `_migrate` 干净。
    """
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """把库升到当前 `SCHEMA_VERSION`（**幂等**）。

    两条路一起走（T-G9 起）：
    1. **版本链**（`_upgrade`）：按 `schema_version` 逐版补齐 —— **数据回填**（v4/v5 把历史
       专注/已完成任务回填成事实）只在这里跑，因为它们"跑一次就够"且比加列贵；
    2. **结构补齐**（`_ensure_schema`）：v1~v3 与 v6 起的**加列/建表**类迁移**不看版本号**，每次都跑
       （全部幂等、成本是一次 `PRAGMA table_info`）。

    为什么要有第 2 条（这一条是 T-G9 的教训）：`schema_version` 只是**记录**，"列到底在不在"才是
    **事实** —— 老代码的 `_upgrade` 漏了 `if current < 14` / `< 15`，于是 v12 的库升级后表结构缺
    `groups.parent_id`，版本号却已经被写成 15：**版本号撒了谎，而没人看得出来**。
    现在改成"每次连接都按结构清单核一遍"，版本号只用来决定"数据回填跑没跑过"。
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        _create_all(conn)
        conn.commit()
        return
    current = int(row["version"])
    if current > SCHEMA_VERSION:
        # 比程序还新的库（升级程序后又打开旧程序 / 恢复了"未来版本"的备份）：
        # **什么都不动** —— 不补列、不改版本号。它比我新，我"顺手修一下"只会破坏它的结构；
        # 该做的事是**如实报出来**（界面按 schema_version 提示"备份比程序新"）。
        conn.commit()
        return
    before = _schema_fingerprint(conn)
    if current < SCHEMA_VERSION:
        _upgrade(conn, current)
    _ensure_schema(conn)
    if current != SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    after = _schema_fingerprint(conn)
    if after != before:
        _log_schema_healed(conn, current, before, after)
    conn.commit()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _schema_fingerprint(conn: sqlite3.Connection) -> tuple[str, ...]:
    """结构指纹：**所有表的所有列** + 所有表/索引对象名（排序后）。

    用途只有一个：判断"这次连接有没有真的补上什么东西" —— 补了就**如实记一条日志**
    （`schema_healed`），而不是默默改库。指纹不含数据，所以便宜且与内容无关。
    """
    objects = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    parts = [f"{r['type']}:{r['name']}" for r in objects]
    for name in [str(r["name"]) for r in objects if str(r["type"]) == "table"]:
        parts += [f"{name}.{c['name']}" for c in conn.execute(f"PRAGMA table_info({name})")]
    return tuple(sorted(parts))


def _log_schema_healed(
    conn: sqlite3.Connection,
    was: int,
    before: tuple[str, ...],
    after: tuple[str, ...],
) -> None:
    """结构被补齐了 → 记一条结构化日志（**不静默**）。日志写不进去也不该挡住启动。"""
    from timeflow import logs

    added = [item for item in after if item not in set(before)]
    logs.log_event(
        "schema_healed",
        level=30,
        was_version=was,
        to_version=SCHEMA_VERSION,
        added=added[:24],          # 日志给**样例**（够看出补了什么），真实条数在 added_count
        added_count=len(added),
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """**结构补齐**：把"表/列必须在"这件事每次都核一遍（全部幂等、跳过的极快）。

    顺序与新建库一致（建表 → 加列 → 重建约束），这样"从任何历史版本升上来的库"与"新建的库"
    结构相同 —— 这条不变式有测试钉着（`tests/test_migration_heal_line.py`）。
    **不含数据回填**（v4/v5 留在版本链里）。
    """
    _migrate_v1(conn)   # 建表：tasks
    _migrate_v2(conn)   # 建表：groups / task_groups / 各域基础表
    _migrate_v3(conn)   # 建表：facts
    _migrate_v6(conn)   # 加列：tasks.note
    _migrate_v7(conn)   # 加列：tasks.priority
    _migrate_v8(conn)   # 加列：tasks.flagged
    _migrate_v9(conn)   # 加列：attach 两列 + app_settings 表
    _migrate_v10(conn)  # 加列：tasks.remind_at
    _migrate_v11(conn)  # 加列：tasks.task_type / course_id
    _migrate_v12(conn)  # 加列：review_items.task_id
    _migrate_v13(conn)  # 加列：tasks.doing_rank
    _migrate_v14(conn)  # 加列：groups.parent_id
    _migrate_v15(conn)  # 重建：groups 去掉全局 UNIQUE(name)，改"同父下唯一"
    _migrate_v16(conn)  # 加列：tasks.created_by（谁建的：我 / AI）
    _migrate_v17(conn)  # 跨端：六张表的 updated_at + 删除墓碑（触发器，幂等）
    _migrate_v18(conn)  # 建表：school_notices（学校通知的**合作接口**收件箱）
    _migrate_v19(conn)  # 加列：tasks.myday_rank（今天清单的自定义顺序 · T-G79 拖拽）


def _upgrade(conn: sqlite3.Connection, current: int) -> None:
    """**版本链**（历史路径）：只跑"当年那一版"的迁移 —— 数据回填只在这里。

    注意它**不再自己写版本号**（T-G9 起由 `_migrate` 在结构补齐之后统一写），
    免得出现"版本号已经 15、结构还停在 12"这种谎报。
    """
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
    if current < 10:
        _migrate_v10(conn)  # 任务提醒 remind_at（F1 段2 · T-B5 前半）
    if current < 11:
        _migrate_v11(conn)  # 任务类型 + 所属课程（F1/F5 · T-C12）
    if current < 12:
        _migrate_v12(conn)  # 复习卡挂任务血缘（F6 · T-C5）
    if current < 13:
        _migrate_v13(conn)  # 「进行中」的显式顺序（F 批 · T-F1）
    if current < 14:
        _migrate_v14(conn)  # 分组可嵌套：groups.parent_id（F 批 · T-F5）
    if current < 15:
        _migrate_v15(conn)  # 分组名允许重名（F 批 · T-F10）
    if current < 16:
        _migrate_v16(conn)  # 谁建的：我 / AI（G 批 · T-G6）
    if current < 17:
        _migrate_v17(conn)  # 跨端合并所需的 modified 标记 + 删除墓碑（G 批 · T-G8）
    if current < 18:
        _migrate_v18(conn)  # 学校通知的合作接口收件箱（G 批 · T-G14）
    if current < 19:
        _migrate_v19(conn)  # 今天清单的自定义顺序（T-G79 拖拽）



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
    _migrate_v10(conn)  # 同上：remind_at 由本版加列
    _migrate_v11(conn)  # 同上：task_type / course_id 由本版加列
    _migrate_v12(conn)  # 同上：review_items.task_id 由本版加列
    _migrate_v13(conn)  # 同上：tasks.doing_rank 由本版加列
    _migrate_v14(conn)  # 同上：groups.parent_id 由本版加列（分组可嵌套）
    _migrate_v15(conn)  # 同上：groups 去掉全局 UNIQUE(name)（允许重名），改按"同父下唯一"
    _migrate_v16(conn)  # 同上：tasks.created_by 由本版加列（谁建的：我 / AI）
    _migrate_v17(conn)  # 同上：updated_at 六列 + sync_tombstones 表 + 触发器
    _migrate_v18(conn)  # 同上：school_notices 表（学校通知的合作接口收件箱）
    _migrate_v19(conn)  # 同上：tasks.myday_rank 由本版加列（今天清单的顺序）


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
                occurred_at or clock.now().isoformat(timespec="seconds"),
                clock.now().isoformat(timespec="seconds"),
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
    now = clock.now().isoformat(timespec="seconds")
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


def _migrate_v10(conn: sqlite3.Connection) -> None:
    """v10：任务加 `remind_at`（提醒时间，本地时间字符串）—— F1 段2 · T-B5 前半。

    口径：
    - 存**本地时间字符串** `YYYY-MM-DDTHH:MM`（与事实层/展示口径一致，不用 UTC —— 见 U-07 的教训）；
    - 可空 = 不提醒；**清空是真的清空**（存 NULL，不写空串）；
    - 界面按「今天 / 临期 / 已过」标出来（**没开通知也不瞎**）；
    - **系统通知通道属于新增运行时依赖，选型须用户确认后再接**
      （`复盘/段2设计决策-提醒与附件打开方式.md` §八）；本列只负责"什么时候该提醒"这件事本身。
    """
    _add_column_if_missing(conn, "tasks", "remind_at", "remind_at TEXT")


def _migrate_v11(conn: sqlite3.Connection) -> None:
    """v11：任务类型 + 所属课程（SR-F5.4「学校任务带课程标签」· T-C12）。

    口径（用户 2026-09-19 要求：「有的作业任务是课程相关的，能选它是作业类型，然后绑到那门课上」）：
    - `task_type`：`普通` / `作业` / `考试` / `论文` / `小测`（默认 `普通`）；
      **复用 `course_assessments.name` 已有的词表**（考试/作业/论文/小测），不另造一套说法；
    - `course_id`：指向 `courses.id` 的**弱关联**（不建外键、不级联）——
      课程被删时任务不跟着消失，只显示成「课程已删」；老行一律 `普通` + NULL，不猜内容；
    - 两列都走 `_add_column_if_missing`（缺列才加，重复连接/新库老库都安全，缺表跳过不失败）。
    """
    _add_column_if_missing(conn, "tasks", "task_type", "task_type TEXT DEFAULT '普通'")
    _add_column_if_missing(conn, "tasks", "course_id", "course_id TEXT")


def _migrate_v12(conn: sqlite3.Connection) -> None:
    """v12：复习卡挂**任务血缘** `review_items.task_id`（SR-F6.6「由学习任务升级为复习卡」· T-C5）。

    口径：
    - 弱关联（不建外键、删任务不级联）：任务删了，复习卡照旧存在（它已经是独立的一张卡）；
    - 老行一律 NULL（不是从任务升上来的），**不猜**；
    - 幂等加列，缺表跳过不失败。
    """
    _add_column_if_missing(conn, "review_items", "task_id", "task_id TEXT")


def _migrate_v13(conn: sqlite3.Connection) -> None:
    """v13：「进行中」的**显式顺序** `tasks.doing_rank`（F 批 · T-F1）。

    口径（用户 2026-09-21：「我可以自由选择某些任务在进行中……**同时**（多个），可以自己标顺序」）：
    - 「进行中」可以同时有多条，先后由**用户自己定的序号**决定（`1` 最小 = 最靠前）；
    - **不做拖拽**（守段2 决策）：界面用上/下按钮交换序号，数值就是这一件事的顺序；
    - 只有「进行中」的任务才有序号，离开这个状态一律清成 NULL（不留幽灵序号）；
    - 序号由领域层维护（`manager.start_task` / `move_doing`），**不是内容字段**，不暴露给 PATCH；
    - 幂等加列，缺表跳过不失败；老数据全为 NULL（界面按"没排过序"排在最后，不猜）。
    """
    _add_column_if_missing(conn, "tasks", "doing_rank", "doing_rank INTEGER")


def _migrate_v14(conn: sqlite3.Connection) -> None:
    """v14：**分组可嵌套** `groups.parent_id`（N8/N3 + F 批 · T-F5）。

    口径（用户 2026-09-21：「大任务 → 子任务 → 子步骤」
    「或者程序里像文件夹那样，可以嵌套、归在一起」）：
    - `parent_id` 自引用，NULL = 顶层分组；**最多三层**（与任务的嵌套深度同一个上限，
      免得界面里出现无限缩进）；
    - **任务仍可属多个分组**（`task_groups` 不动，SR-F1.3 那条不变）；
    - **分组名仍然全局唯一**（`groups.name` 的 UNIQUE 约束保留）：成员关系本来就是**按名字**存的
      （`get_task_groups` 返回名字、界面按 `data-name` 勾选），如果允许"高数/作业"和"英语/作业"
      同名，同一个名字就指不回是哪一个 —— 要放开得先把成员关系改成按 id，那是另一张卡的事。
      所以子分组名也要唯一，界面里显示**路径**（`高数 / 第三章`）避免歧义；
    - 老数据全为 NULL（都是顶层分组，行为不变）；幂等加列，缺表跳过不失败。

    ⚠️ 上面那条"全局唯一"已被 **v15 放开**（用户 2026-09-21 定「允许重名」）：
    成员关系改按 id 存之后，重名不再有歧义，只保留"同一父下不能重名"。
    """
    _add_column_if_missing(conn, "groups", "parent_id", "parent_id TEXT")


def _migrate_v15(conn: sqlite3.Connection) -> None:
    """v15：分组名**允许重名**（同一父下仍唯一）—— 重建 `groups` 表，去掉全局 `UNIQUE(name)`。

    口径（用户 2026-09-21 定：「允许重名」）：要能有「高数 / 作业」和「英语 / 作业」。
    老约束是 `name TEXT NOT NULL UNIQUE`（全局唯一），而"任务属于哪些分组"当时是**按名字**存的
    （`get_task_groups` 返回名字、界面按 `data-name` 勾选）—— 名字一重复就指不回是哪一个。
    所以这一版**两件事一起做**：去掉全局唯一 + 成员关系改按 **id**（见 `groups.py`）。
    保留下来的约束是**同一父下不能重名**（`COALESCE(parent_id,'')` 上的唯一索引）：
    同层两个一模一样的名字没有任何用处，只会让人选错。

    怎么做：SQLite 改不了约束，只能重建表（`ALTER ... RENAME` + 建新表 + 拷数据 + 删旧表）。
    - 幂等判据：`PRAGMA index_list(groups)` 里还有没有**由 UNIQUE 约束自动生成的索引**
      （`origin='u'`）；重建之后只剩我们自己建的表达式索引（`origin='c'`）→ 再跑一次会跳过。
    - 先确保 `parent_id` 存在（v14 已加；残缺库可能没有），免得拷数据时列不存在。
    - 没有外键约束引用 groups（`task_groups` 只存 id 字符串），重建不影响别处。
    """
    if not _table_exists(conn, "groups"):
        return  # 残缺库：连 groups 表都没有（v2 会建，这里不替它建）
    _add_column_if_missing(conn, "groups", "parent_id", "parent_id TEXT")
    auto = [
        str(r["name"])
        for r in conn.execute("PRAGMA index_list(groups)").fetchall()
        if str(r["origin"]) == "u"
    ]
    if auto:
        conn.execute("ALTER TABLE groups RENAME TO groups_old_v15")
        conn.execute(
            """
            CREATE TABLE groups (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                parent_id   TEXT,
                created_at  TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO groups (id, name, parent_id, created_at) "
            "SELECT id, name, parent_id, created_at FROM groups_old_v15"
        )
        conn.execute("DROP TABLE groups_old_v15")
    # 同层不重名（`COALESCE` 是因为 SQLite 的唯一索引把多个 NULL 当互不相同 ——
    # 不套 COALESCE 的话"两个同名顶层分组"就漏过去了）
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_sibling "
        "ON groups(COALESCE(parent_id, ''), name)"
    )


def _migrate_v16(conn: sqlite3.Connection) -> None:
    """v16：任务/步骤的**归属** `tasks.created_by` —— 谁建的（`me` / `ai`）· G 批 · T-G6。

    口径（用户 2026-09-21 定，见 `复盘/口径定案-待定清单.md` §2 的**乙案**）：
    AI 接口第一版是**只读 + 新增**，判据从"改不改"换成"**动的是不是你亲手写的东西**"——
    所以 AI **能勾它自己建的**步骤，**不许碰你建的**。这条边界要落成字段，不能靠约定：
    `created_by` 就是那个"谁写的"事实（值域 `me` / `ai`，与 `core/ai.py` 的常量对齐）。

    - 老行一律 `me`（**不猜**：这个库里的东西本来就是你自己建的；AI 接口在此之前不存在）；
    - 默认 `me` 同样意味着"新建任务默认是你建的"，只有 `/api/ai/*` 那条路会写 `ai`；
    - 幂等加列（`_add_column_if_missing`），缺表跳过不失败 —— 与 v6 起各版同一套做法。
    """
    _add_column_if_missing(conn, "tasks", "created_by", "created_by TEXT DEFAULT 'me'")


# 「会被改的表」——v17 给它们补 `updated_at`（跨端合并要靠它判谁新）。
# 为什么是这几张：其余表要么**只增不改**（facts / focus_sessions / grades / courses / memos 的内容
# 没有更新入口 / ledger_entries），要么是**关系行**（task_groups / habit_logs：只有"在不在"，
# 没有"什么时候改的"）；`tasks` 本来就有 `updated_at` + `version`（且它故意维护得更精细：
# 换「进行中」顺序**不动** updated_at，见 T-F1 —— 所以**不给 tasks 加触碰触发器**）。
SYNC_TOUCHED_TABLES = (
    "habits",
    "groups",
    "course_assessments",
    "review_items",
    "team_assignments",
    "feedback_logs",
)

# 「删了就删了」的表 —— v17 给它们挂**删除墓碑触发器**：任何一行被硬删就留一条墓碑，
# 于是"从另一台机器的旧包导入"不会把它**复活**（这是用户最容易觉得"同步在骗我"的一类事）。
# 关系表用复合键（`task_groups` / `habit_logs` 主键是两列），墓碑的 `entity_id` 用 `|` 拼起来。
SYNC_TOMBSTONE_KEYS: dict[str, str] = {
    "tasks": "OLD.id",
    "memos": "OLD.id",
    "habits": "OLD.id",
    "habit_logs": "OLD.habit_id || '|' || OLD.date",
    "groups": "OLD.id",
    "task_groups": "OLD.task_id || '|' || OLD.group_id",
    "course_assessments": "OLD.id",
    "grades": "OLD.id",
    "review_items": "OLD.id",
    "team_assignments": "OLD.id",
}


def _migrate_v17(conn: sqlite3.Connection) -> None:
    """v17：跨端合并要的两样东西 —— **「什么时候改的」** 与 **「什么时候删的」**（G 批 · T-G8）。

    背景（口径见 `复盘/口径定案-待定清单.md` §3：先做 ③ 合并机制）：跨端合并的判据是
    "谁新谁旧"，而全库只有 `tasks` 有 `updated_at`/`version` —— 别的表改了名字、改了成绩、
    复习推进了间隔，**库里没有任何痕迹说明它变过**。于是 v17 补两件事：

    1. **`updated_at`**（六张会被改的表，`SYNC_TOUCHED_TABLES`）：
       - 老行回填 `COALESCE(created_at, 现在)`（**不猜**：能考证的最早时间就是它）；
       - 之后由**触发器**在每次 UPDATE 后自动写当前时间 —— 为什么用触发器而不是逐个改代码：
         更新入口散在 habits/groups/review/team/feedback 五六个模块里（十几处），
         **靠"记得每处都加"必然漏**（T-G9 刚教过这一课：判据要能自证，不能靠记性）；
         一个声明式的地方管全部，而且**将来新加的更新路径自动也被管住**。
       - **不给 `tasks` 挂触碰触发器**：它自己维护 `updated_at` + `version`，而且有一条**故意**的
         例外 —— 调整「进行中」顺序**不动** `updated_at`（T-F1："换顺序不是内容变了"）。
       2. **`sync_tombstones`**（删除墓碑）+ 各表的 **DELETE 触发器**：硬删一行就留一条墓碑。
          没有它的话，"在 A 机器上彻底删掉的东西"会被 B 机器的旧包**原样带回来** ——
          用户只会觉得同步在骗他。

    **触发器不会自激**：SQLite 的 `recursive_triggers` 默认关闭，但这里**显式**把它关掉
    （`PRAGMA recursive_triggers = OFF`）—— 不把正确性押在"默认值大概是关的"上面。
    """
    conn.execute("PRAGMA recursive_triggers = OFF")
    # ① 加列 + 回填（**必须在建触发器之前**：否则回填那次 UPDATE 会被触发器改写成"现在"）
    for table in SYNC_TOUCHED_TABLES:
        _add_column_if_missing(conn, table, "updated_at", "updated_at TEXT")
        if _table_exists(conn, table):
            conn.execute(
                f"UPDATE {table} SET updated_at = COALESCE(created_at, updated_at, "
                "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')) "
                "WHERE updated_at IS NULL OR updated_at = ''"
            )
    # ② 墓碑表 + 冲突日志的两个说明列（**不静默覆盖**要写清"为什么"：
    #    旧表只有 local_ts/remote_ts，看不出这次是"覆盖了"还是"保留了本地"）
    _add_column_if_missing(conn, "sync_logs", "result", "result TEXT")
    _add_column_if_missing(conn, "sync_logs", "note", "note TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_tombstones (
            entity      TEXT NOT NULL,          -- 表名（'tasks' / 'habit_logs' / …）
            entity_id   TEXT NOT NULL,          -- 主键；关系表用 'a|b' 拼两列
            deleted_at  TEXT NOT NULL,
            PRIMARY KEY (entity, entity_id)
        )
        """
    )
    # ③ 触碰触发器（改了就算改过；**新插入的行也要有值** —— 否则新建的 habit/成绩
    #    在跨端比较里是"没有时间"，只能当最旧处理）
    for table in SYNC_TOUCHED_TABLES:
        if not _table_exists(conn, table):
            continue
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_touch_insert "
            f"AFTER INSERT ON {table} FOR EACH ROW "
            "BEGIN "
            f"  UPDATE {table} SET updated_at = "
            "COALESCE(NEW.created_at, strftime('%Y-%m-%dT%H:%M:%S','now','localtime')) "
            "  WHERE rowid = NEW.rowid AND (NEW.updated_at IS NULL OR NEW.updated_at = ''); "
            "END"
        )
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_touch "
            f"AFTER UPDATE ON {table} FOR EACH ROW "
            "BEGIN "
            f"  UPDATE {table} SET updated_at = "
            "strftime('%Y-%m-%dT%H:%M:%S','now','localtime') "
            "  WHERE rowid = NEW.rowid; "
            "END"
        )
    # ④ 删除墓碑触发器（删了就留痕，免得被旧包复活）
    for table, key_expr in SYNC_TOMBSTONE_KEYS.items():
        if not _table_exists(conn, table):
            continue
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_tombstone "
            f"AFTER DELETE ON {table} FOR EACH ROW "
            "BEGIN "
            "  INSERT INTO sync_tombstones (entity, entity_id, deleted_at) "
            f"  VALUES ('{table}', {key_expr}, "
            "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')) "
            "  ON CONFLICT(entity, entity_id) DO UPDATE SET "
            "    deleted_at = excluded.deleted_at; "
            "END"
        )


def _migrate_v18(conn: sqlite3.Connection) -> None:
    """v18：**学校通知的合作接口**收件箱（SR-F10.1 / G 批 · T-G14）。

    规格 `docs/specification/domains/F10-notify.md` 的定位是：监测（网站/公众号/群聊/考试网站）
    由**独立脚本**去做，**主工具只提供合作接口**、不抓取、不新增对外依赖。所以这一版建的是
    一张**收件箱**：外部脚本把抓到的通知投递进来（`POST /api/notify/school`），
    主工具负责去重、来源标记、看、以及"转成任务/提醒"——**不负责去网上拿**。

    两处刻意的设计：
    - `fingerprint` **唯一**：去重靠数据库约束，不靠调用方自觉（同一个来源同一条通知重复投递
      只留一行；带了 `external_id` 的就是"对方系统里的那一条"，标题改了也只更新同一行）；
    - `extra` 存**不认识的多余字段**（JSON）：规格写着"接口契约未定、字段保持扩展位，不写死"——
      于是脚本先多加一个字段不会丢，等哪天真需要再提升成正式列。

    `updated_at` 也一并给上（第一版只有 status/task_id 会变）—— 将来若要跨端同步，
    判新旧的那一列已经在了，不必再来一次迁移。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS school_notices (
            id           TEXT PRIMARY KEY,
            source       TEXT NOT NULL,
            external_id  TEXT,
            fingerprint  TEXT NOT NULL UNIQUE,
            title        TEXT NOT NULL,
            url          TEXT,
            summary      TEXT,
            at           TEXT,
            due_date     TEXT,
            received_at  TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'new',
            task_id      TEXT,
            extra        TEXT,
            updated_at   TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_school_notices_received "
        "ON school_notices(received_at)"
    )


def _migrate_v19(conn: sqlite3.Connection) -> None:
    """v19：**今天清单（My Day）的自定义顺序** `tasks.myday_rank`（T-G79）。

    口径（用户 2026-09-25 在两张预演图上选了 **B 真拖拽**）：

    - 「今天做什么」的先后由**用户自己拖**出来（`myday_rank` 小的排前面）；
    - **没排过序的（NULL）排在排过序的后面**，它们之间仍按原来的统一口径
      （截止日 → 优先级 → 创建时间）—— 也就是"你拖过的那几条按你排的走，
      新加进今天的排在后面"，不猜顺序；
    - 拖一次会把**当前清单整体规整成 1..N**（与 `doing_rank` 那套同一做法），
      于是"先拖谁后拖谁"不会因为中间插进来一条而错位；
    - 只有**在今天的**任务才有序号：移出今天一律清成 NULL（不留幽灵序号）；
    - 序号由领域层维护（`manager.place_myday` / `manager.move_myday`），
      **不是内容字段**，不进 `update_task` 的字段白名单；
    - 幂等加列，缺表跳过不失败；老数据全为 NULL。
    """
    _add_column_if_missing(conn, "tasks", "myday_rank", "myday_rank INTEGER")

