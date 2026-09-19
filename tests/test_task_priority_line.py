"""F1 主线 · 段2 · T-B2：任务优先级 `priority` + 三处排序统一（SR-F1.2）。

覆盖：
- schema v6 → v7 加列：幂等、旧行补默认「中」（不猜）、缺 tasks 表的残缺库不失败；
- 口径：三档 高/中/低，默认「中」；**非法值一律拒绝**（不静默降级）、
  **不可清空**（没有"无优先级"态）；
- 排序统一：`list_tasks` / `myday_tasks` / `overdue_tasks` 一律
  **截止日 → 优先级 → 创建时间**，无截止日排最后（逾期栏两条来源合并后仍守同一口径）；
- 优先级不是事实：改它不发 facts、不动账本（投入/债务/产出都不变）；
- Repeat 继承优先级（优先级属于任务定义，不该每周期掉回默认）；
- 跨端：`sync.merge_task` 带 priority，远端没带时保留本地值，非法值拒绝。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "prio.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v6_db(path: str) -> None:
    """手工造一个 v6 旧库：tasks 有 note、**没有 priority**（模拟升级前的真实库）。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (6)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1, note TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v7）

def test_upgrade_v6_adds_priority_column_with_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v6 → v7：补 priority 列，旧行落默认「中」（**不猜**，不按日期远近偷偷标高标低）。"""
    p = str(tmp_path / "v6.db")
    _make_v6_db(p)

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    row = conn.execute("SELECT title, priority FROM tasks WHERE id='old1'").fetchone()
    assert row["title"] == "旧任务"
    assert row["priority"] == tm.PRIORITY_MID
    conn.close()


def test_upgrade_v7_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v6b.db")
    _make_v6_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        assert cols.count("priority") == 1
        c.close()


def test_v7_on_fresh_db_has_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "fresh.db"))
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "priority" in cols
    assert db_mod.SCHEMA_VERSION >= 7  # v7 引入 priority
    conn.close()


def test_v7_missing_tasks_table_does_not_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "broken.db")
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (6)")
    raw.commit()
    raw.close()

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    conn.close()


def test_row_without_priority_column_does_not_crash() -> None:
    """缺列兜底：老 row 读出来是默认「中」，不是崩。

    注意边界：**排序路径要求列存在**（`list_tasks` 的 ORDER BY 会引用它）——
    列由 v7 迁移保证；这里的兜底是给 `get_task`/不含排序的读取路径用的，
    不假装"没迁移也能用列表"（那会让"迁移失败"变成静默错序）。
    """
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT, group_name TEXT,"
        " repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0, status TEXT,"
        " created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('x','老行','未开始','2026-01-01','2026-01-01',1)"
    )
    assert tm.get_task(raw, "x").priority == tm.PRIORITY_MID
    raw.close()


# ---------------------------------------------------------------- 三档与默认值

def test_default_priority_is_mid(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "d.db"))
    assert tm.create_task(conn, "没写优先级").priority == tm.PRIORITY_MID
    conn.close()


def test_invalid_priority_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """非法优先级不许静默降级（否则用户"设了高"却没生效，最难查）。"""
    conn = db_mod.connect(str(tmp_path / "bad.db"))
    with pytest.raises(ValueError):
        tm.create_task(conn, "任务", priority="紧急")
    t = tm.create_task(conn, "任务")
    with pytest.raises(ValueError):
        tm.update_task(conn, t.id, priority="特高")
    with pytest.raises(ValueError):
        tm.update_task(conn, t.id, priority=None)  # 不可清空：没有"无优先级"这一态
    assert tm.get_task(conn, t.id).priority == tm.PRIORITY_MID  # 失败的改动没落库
    conn.close()


def test_api_priority_roundtrip_and_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    tid = client.post("/api/tasks", json={"title": "写论文", "priority": "高"}).json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["priority"] == "高"

    assert client.patch(f"/api/tasks/{tid}", json={"priority": "低"}).json()["priority"] == "低"
    assert client.patch(f"/api/tasks/{tid}", json={"priority": "紧急"}).status_code == 400
    assert client.patch(f"/api/tasks/{tid}", json={"priority": None}).status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "priority": "urgent"}).status_code == 400
    # 拒绝之后仍是上一次成功写入的值
    assert client.get(f"/api/tasks/{tid}").json()["priority"] == "低"


# ---------------------------------------------------------------- 排序统一

def test_list_tasks_order_due_then_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """截止日优先于优先级；同一截止日按 高→中→低；无截止日排最后。"""
    conn = db_mod.connect(str(tmp_path / "order.db"))
    tm.create_task(conn, "早-低", due_date="2030-01-01", priority="低")
    tm.create_task(conn, "晚-高", due_date="2030-02-01", priority="高")
    tm.create_task(conn, "同日-低", due_date="2030-03-01", priority="低")
    tm.create_task(conn, "同日-高", due_date="2030-03-01", priority="高")
    tm.create_task(conn, "无截止-高", priority="高")

    assert [t.title for t in tm.list_tasks(conn)] == [
        "早-低", "晚-高", "同日-高", "同日-低", "无截止-高",
    ]
    conn.close()


def test_myday_order_matches_list_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "myday.db"))
    tm.create_task(conn, "今天-低", due_date="2030-03-01", priority="低", is_myday=True)
    tm.create_task(conn, "今天-高", due_date="2030-03-01", priority="高", is_myday=True)
    tm.create_task(conn, "没进今天-高", due_date="2030-03-01", priority="高")

    assert [t.title for t in tm.myday_tasks(conn)] == ["今天-高", "今天-低"]
    conn.close()


def test_overdue_order_due_then_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "over.db"))
    tm.create_task(conn, "逾期-低", due_date="2020-01-01", priority="低")
    tm.create_task(conn, "逾期-高", due_date="2020-01-01", priority="高")
    tm.create_task(conn, "更早-高", due_date="2019-01-01", priority="高")

    assert [t.title for t in tm.overdue_tasks(conn)] == ["更早-高", "逾期-高", "逾期-低"]
    conn.close()


def test_overdue_merged_with_myday_still_ordered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """逾期栏是"SQL 查出的逾期 + 无截止日但昨天该做的 My Day"两拨合并 —— 合并后仍守同一口径。"""
    conn = db_mod.connect(str(tmp_path / "merge.db"))
    tm.create_task(conn, "逾期-中", due_date="2020-01-01")
    no_due = tm.create_task(conn, "无截止-高", priority="高", is_myday=True)
    conn.execute(
        "UPDATE tasks SET created_at = ? WHERE id = ?", ("2020-01-01T09:00:00", no_due.id)
    )
    conn.commit()

    assert [t.title for t in tm.overdue_tasks(conn)] == ["逾期-中", "无截止-高"]
    conn.close()


def test_priority_is_not_a_fact_and_not_in_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "ledger.db")
    tid = client.post("/api/tasks", json={"title": "任务", "due_date": "2030-01-01"}).json()["id"]
    before = client.get("/api/summary").json()

    client.patch(f"/api/tasks/{tid}", json={"priority": "高"})
    assert client.get(f"/api/tasks/{tid}/facts").json() == []
    assert client.get("/api/summary").json() == before


def test_repeat_inherits_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "repeat.db"))
    t = tm.create_task(
        conn, "每周复盘", due_date="2026-12-31", repeat_days=7, priority="高"
    )
    tm.complete_task(conn, t.id)

    same = [x for x in tm.list_tasks(conn, active_only=False) if x.title == "每周复盘"]
    assert len(same) == 2
    nxt = [x for x in same if x.id != t.id][0]
    assert nxt.priority == "高"  # 优先级属于任务定义，不该每周期掉回默认


# ---------------------------------------------------------------- 跨端合并

def test_sync_merge_carries_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s.db"))
    tid = tm.create_task(conn, "本地").id
    remote = {
        "id": tid, "title": "远端", "priority": "高",
        "updated_at": "2030-01-01T00:00:00", "version": 9,
    }
    assert sync.merge_task(conn, remote) == "updated"
    assert tm.get_task(conn, tid).priority == "高"
    conn.close()


def test_sync_merge_without_priority_keeps_local(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s2.db"))
    tid = tm.create_task(conn, "本地", priority="高").id
    remote = {"id": tid, "title": "远端", "updated_at": "2030-01-01T00:00:00", "version": 9}
    assert sync.merge_task(conn, remote) == "updated"
    got = tm.get_task(conn, tid)
    assert got.title == "远端"  # 其余字段照旧
    assert got.priority == "高"  # 优先级不被静默打回默认
    conn.close()


def test_sync_merge_rejects_invalid_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s3.db"))
    tid = tm.create_task(conn, "本地").id
    remote = {
        "id": tid, "title": "远端", "priority": "超急",
        "updated_at": "2030-01-01T00:00:00", "version": 9,
    }
    with pytest.raises(ValueError):
        sync.merge_task(conn, remote)
    assert tm.get_task(conn, tid).priority == tm.PRIORITY_MID  # 非法值没有写进库
    conn.close()


def test_sync_insert_without_priority_uses_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s4.db"))
    remote = {
        "id": "remote-1", "title": "远端新任务", "status": "未开始",
        "created_at": "2029-01-01T00:00:00", "updated_at": "2029-01-01T00:00:00", "version": 1,
    }
    assert sync.merge_task(conn, remote) == "inserted"
    assert tm.get_task(conn, "remote-1").priority == tm.PRIORITY_MID
    conn.close()
