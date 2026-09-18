"""事实层测试：facts 表读写 + 事件总线 + 与 focus 的最小集成。"""

from __future__ import annotations

import sqlite3

import pytest

from timeflow.core import facts as facts_mod
from timeflow.core import focus as fc
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


# ---- 迁移 ----

def test_schema_version_is_current(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(row["version"]) == db_mod.SCHEMA_VERSION


def test_facts_table_exists(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
    ).fetchone()
    assert row is not None


def test_migration_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """重复连接同一库不应报错，且版本保持 3。"""
    p = str(tmp_path / "t2.db")
    c1 = db_mod.connect(p)
    c1.close()
    c2 = db_mod.connect(p)
    row = c2.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(row["version"]) == db_mod.SCHEMA_VERSION
    c2.close()


def test_upgrade_from_v2_preserves_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """模拟 v2 旧库：应能升级到 v3，且旧数据不丢。"""
    p = str(tmp_path / "old.db")
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (2)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT,"
        " created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.commit()
    raw.close()

    c = db_mod.connect(p)  # 触发 v2 → v3 → v4 升级
    ver = c.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    old = c.execute("SELECT title FROM tasks WHERE id='old1'").fetchone()
    assert old["title"] == "旧任务"  # 旧数据保留
    assert (
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        is not None
    )
    c.close()


def test_upgrade_from_v3_backfills_focus_facts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v3 旧库的历史 focus_sessions 应在升级 v4 时补成 facts（第 1 步前兼容）。"""
    p = str(tmp_path / "backfill.db")
    c = db_mod.connect(p)
    c.execute(
        "INSERT INTO focus_sessions "
        "(id, task_id, kind, started_at, ended_at, duration_sec, status, device_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "s_done", None, "plain", "2026-09-17T20:00:00", "2026-09-17T20:25:00",
            1500, "finished", None, "2026-09-17T20:00:00",
        ),
    )
    c.execute(
        "INSERT INTO focus_sessions "
        "(id, task_id, kind, started_at, ended_at, duration_sec, status, device_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "s_abandon", None, "tomato", "2026-09-17T21:00:00", "2026-09-17T21:05:00",
            300, "abandoned", None, "2026-09-17T21:00:00",
        ),
    )
    c.execute("UPDATE schema_version SET version = 3")
    c.commit()
    c.close()

    c2 = db_mod.connect(p)  # 触发 v3 → v4 回填
    assert facts_mod.count(c2, kind="focus.finished") == 1
    assert facts_mod.count(c2, kind="focus.abandoned") == 1
    done = facts_mod.query(c2, kind="focus.finished")[0]
    assert done["value_num"] == 1500.0
    assert done["extra"]["session_id"] == "s_done"
    assert done["extra"]["migrated"] is True
    assert done["occurred_at"] == "2026-09-17T20:25:00"
    c2.close()

    c3 = db_mod.connect(p)  # 重复连接不应重复插入
    assert facts_mod.count(c3, kind="focus.") == 2
    c3.close()


# ---- store 读写 ----

def test_record_and_query(conn: sqlite3.Connection) -> None:
    fid = facts_mod.record(
        conn,
        kind="focus.finished",
        subject_type="task",
        subject_id="T1",
        value_num=1500.0,
        extra={"session_id": "s1"},
    )
    assert fid
    rows = facts_mod.query(conn, kind="focus.finished")
    assert len(rows) == 1
    assert rows[0]["value_num"] == 1500.0
    assert rows[0]["extra"] == {"session_id": "s1"}
    assert rows[0]["revision"] == 1


def test_query_wildcard(conn: sqlite3.Connection) -> None:
    facts_mod.record(conn, kind="focus.finished", value_num=1)
    facts_mod.record(conn, kind="focus.started", value_num=2)
    facts_mod.record(conn, kind="task.completed", value_num=3)
    assert facts_mod.count(conn, kind="focus.*") == 2
    assert facts_mod.count(conn, kind="focus.") == 2
    assert facts_mod.count(conn, kind="task.completed") == 1


def test_query_by_subject(conn: sqlite3.Connection) -> None:
    facts_mod.record(conn, kind="a.b", subject_type="task", subject_id="T1")
    facts_mod.record(conn, kind="a.b", subject_type="task", subject_id="T2")
    rows = facts_mod.query(conn, subject_type="task", subject_id="T1")
    assert len(rows) == 1


def test_record_rejects_empty_kind(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        facts_mod.record(conn, kind="  ")


def test_latest_by_subject(conn: sqlite3.Connection) -> None:
    facts_mod.record(conn, kind="a.b", subject_type="task", subject_id="T1", value_num=1)
    facts_mod.record(conn, kind="a.b", subject_type="task", subject_id="T1", value_num=2)
    latest = facts_mod.latest_by_subject(conn, "task", "T1")
    assert latest is not None
    assert latest["value_num"] == 2


# ---- 事件总线 ----

def test_publish_sync_and_payload() -> None:
    facts_mod.clear()
    seen: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    facts_mod.subscribe("focus.finished", lambda k, p: seen.append((k, p)))
    n = facts_mod.publish("focus.finished", {"duration_sec": 100})
    assert n == 1
    assert seen == [("focus.finished", {"duration_sec": 100})]


def test_publish_wildcard() -> None:
    facts_mod.clear()
    seen: list[str] = []
    facts_mod.subscribe("focus.*", lambda k, p: seen.append(k))
    facts_mod.publish("focus.finished", {})
    facts_mod.publish("focus.started", {})
    facts_mod.publish("task.completed", {})
    assert seen == ["focus.finished", "focus.started"]


def test_subscriber_error_isolated() -> None:
    """单个订阅者抛异常不应中断其它订阅者（SR-NF6 局部错误隔离）。"""
    facts_mod.clear()
    seen: list[str] = []

    def bad(k: str, p: dict) -> None:  # type: ignore[type-arg]
        raise RuntimeError("boom")

    facts_mod.subscribe("x.*", bad)
    facts_mod.subscribe("x.*", lambda k, p: seen.append(k))
    n = facts_mod.publish("x.y", {})
    assert n == 2  # 两个都被通知
    assert seen == ["x.y"]  # 好的那个仍然执行了
    assert len(facts_mod.errors) == 1
    assert isinstance(facts_mod.errors[0][1], RuntimeError)


def test_publish_no_subscriber_is_safe() -> None:
    facts_mod.clear()
    assert facts_mod.publish("nobody.listens", {}) == 0


def test_unsubscribe() -> None:
    facts_mod.clear()

    def h(k: str, p: dict) -> None:  # type: ignore[type-arg]
        pass

    facts_mod.subscribe("a.b", h)
    assert facts_mod.unsubscribe("a.b", h) is True
    assert facts_mod.unsubscribe("a.b", h) is False
    assert facts_mod.publish("a.b", {}) == 0


# ---- 最小集成：focus 结束时发布事实 ----

def test_finish_session_records_fact(conn: sqlite3.Connection) -> None:
    facts_mod.clear()
    sid = fc.start_session(conn, kind=fc.KIND_TOMATO)
    fc.finish_session(conn, sid, 1500)
    rows = facts_mod.query(conn, kind="focus.finished")
    assert len(rows) == 1
    assert rows[0]["value_num"] == 1500.0
    assert rows[0]["extra"]["session_id"] == sid


def test_finish_session_publishes_with_task(conn: sqlite3.Connection) -> None:
    facts_mod.clear()
    t = tm.create_task(conn, title="带任务的专注")
    got: list[dict] = []  # type: ignore[type-arg]
    facts_mod.subscribe("focus.finished", lambda k, p: got.append(p))
    sid = fc.start_session(conn, kind=fc.KIND_TOMATO, task_id=t.id)
    fc.finish_session(conn, sid, 900)
    assert len(got) == 1
    assert got[0]["task_id"] == t.id
    assert got[0]["duration_sec"] == 900
    # 事实主体应是 task
    rows = facts_mod.query(conn, kind="focus.finished")
    assert rows[0]["subject_type"] == "task"
    assert rows[0]["subject_id"] == t.id


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (fc.STATUS_PAUSED, "focus.paused"),
        (fc.STATUS_ABANDONED, "focus.abandoned"),
        (fc.STATUS_INTERRUPTED, "focus.interrupted"),
    ],
)
def test_finish_session_kind_by_status(conn: sqlite3.Connection, status: str, kind: str) -> None:
    """只有正常结束才发 focus.finished；放弃/中断/暂停不得混入投入口径。"""
    facts_mod.clear()
    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 300, status)
    assert facts_mod.count(conn, kind=kind) == 1
    assert facts_mod.count(conn, kind="focus.finished") == 0
