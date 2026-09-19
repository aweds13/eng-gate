"""F1 主线 · 段2 · T-B1：任务备注 `note`（SR-F1.4 的「备注」）。

覆盖：
- schema v5 → v6 加列：**幂等**（重复连接不报错、不重复加列）、旧数据保留、
  缺 tasks 表的残缺库不失败；
- 领域/API：建任务可带备注、PATCH 可写、**可清空**（null）、改别的字段不会顺手抹掉备注；
- 边界（对齐 OP-9）：已完成任务可改备注但**不改写历史完成事实**；
- 口径：备注是沉淀型内容，**不发 facts、不进账本**（账本只读事实层）；
- 交互约定：`_row_to_task` 遇到没有 note 列的老 row 也不崩（缺列兜底）；
- 跨端：`sync.merge_task` 会带上 note，但**远端记录没带 note 时不许清空本地备注**（不静默丢数据）。
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "note.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v5_db(path: str) -> None:
    """手工造一个 v5 旧库：tasks 没有 note 列（模拟升级前的真实库）。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (5)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v6）

def test_upgrade_v5_adds_note_column_and_keeps_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v5 → v6：补一列 note，旧行数据不丢，值为 NULL（不猜内容）。"""
    p = str(tmp_path / "v5.db")
    _make_v5_db(p)

    conn = db_mod.connect(p)  # 触发 v5 → v6
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION == 6
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "note" in cols
    row = conn.execute("SELECT title, note FROM tasks WHERE id='old1'").fetchone()
    assert row["title"] == "旧任务"
    assert row["note"] is None
    conn.close()


def test_upgrade_v6_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """重复连接不许重复加列 / 不许报 duplicate column。"""
    p = str(tmp_path / "v5b.db")
    _make_v5_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        assert cols.count("note") == 1
        c.close()


def test_v6_on_fresh_db_has_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """新库也要有 note（v1 建表语句保持历史原样，靠 v6 加列）。"""
    conn = db_mod.connect(str(tmp_path / "fresh.db"))
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "note" in cols
    conn.close()


def test_v6_missing_tasks_table_does_not_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """残缺库（没有 tasks 表）升级时跳过加列，不抛异常（与 v5 同规矩）。"""
    p = str(tmp_path / "broken.db")
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (5)")
    raw.commit()
    raw.close()

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == 6
    conn.close()


def test_row_without_note_column_does_not_crash() -> None:
    """缺列兜底：拿不到 note 列的老 row 也要能读出 Task（note=None）。"""
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
    got = tm.list_tasks(raw)
    assert len(got) == 1 and got[0].note is None
    raw.close()


# ---------------------------------------------------------------- 领域 / API

def test_create_and_read_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    tid = client.post(
        "/api/tasks", json={"title": "写课程报告", "note": "要求见课程网站第 3 页"}
    ).json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["note"] == "要求见课程网站第 3 页"
    # 列表里也带 note 字段（渲染与否由界面决定：卡片不显示、详情才显示）
    listed = client.get("/api/tasks").json()
    assert listed[0]["note"] == "要求见课程网站第 3 页"


def test_patch_note_and_clear_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """能写、能改、**能清空**（空备注存 null，不留空串）。"""
    client = _client(tmp_path, "clear.db")
    tid = client.post("/api/tasks", json={"title": "任务"}).json()["id"]
    assert client.patch(f"/api/tasks/{tid}", json={"note": "先记一句"}).json()["note"] == "先记一句"
    assert client.patch(f"/api/tasks/{tid}", json={"note": "改一句"}).json()["note"] == "改一句"
    assert client.patch(f"/api/tasks/{tid}", json={"note": None}).json()["note"] is None


def test_patch_other_fields_keeps_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """改别的字段不许顺手抹掉备注（老 bug 是"清空被忽略"，反过来"没提也被清"同样要防）。"""
    client = _client(tmp_path, "keep.db")
    tid = client.post("/api/tasks", json={"title": "任务", "note": "留着"}).json()["id"]
    got = client.patch(f"/api/tasks/{tid}", json={"title": "改标题"}).json()
    assert got["title"] == "改标题" and got["note"] == "留着"


def test_note_edit_on_completed_task_keeps_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """已完成任务可补备注，但历史完成事实不被改写（契约 OP-9 边界）。"""
    client = _client(tmp_path, "done.db")
    tid = client.post("/api/tasks", json={"title": "已完成"}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    before = client.get(f"/api/tasks/{tid}/facts").json()

    got = client.patch(f"/api/tasks/{tid}", json={"note": "复盘一句"}).json()
    assert got["status"] == "完成" and got["note"] == "复盘一句"
    assert client.get(f"/api/tasks/{tid}/facts").json() == before


def test_note_is_not_a_fact_and_not_in_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """备注是沉淀型内容：不发事实、不动账本（投入/债务/产出都不该变）。"""
    client = _client(tmp_path, "ledger.db")
    tid = client.post("/api/tasks", json={"title": "任务", "due_date": "2030-01-01"}).json()["id"]
    summary_before = client.get("/api/summary").json()

    client.patch(f"/api/tasks/{tid}", json={"note": "写了一大段备注" * 10})
    assert client.get(f"/api/tasks/{tid}/facts").json() == []
    assert client.get("/api/summary").json() == summary_before


def test_note_written_for_past_due_does_not_change_debt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """给逾期任务写备注不会改债务（债务只看截止日与状态）。"""
    client = _client(tmp_path, "debt.db")
    tid = client.post("/api/tasks", json={"title": "逾期", "due_date": "2020-01-01"}).json()["id"]
    before = client.get("/api/summary").json()["debt_count"]
    client.patch(f"/api/tasks/{tid}", json={"note": "为什么没做完"})
    assert client.get("/api/summary").json()["debt_count"] == before == 1


def test_domain_create_task_with_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """领域层直接调用也要支持 note（前端不是唯一入口）。"""
    conn = db_mod.connect(str(tmp_path / "d.db"))
    task = tm.create_task(conn, "带备注", note="API 之外也能写")
    assert task.note == "API 之外也能写"
    assert tm.get_task(conn, task.id).note == "API 之外也能写"
    conn.close()


# ---------------------------------------------------------------- 跨端合并

def test_sync_merge_carries_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s.db"))
    tid = tm.create_task(conn, "本地任务").id

    remote = {
        "id": tid,
        "title": "远端标题",
        "note": "远端备注",
        "updated_at": "2030-01-01T00:00:00",
        "version": 9,
    }
    assert sync.merge_task(conn, remote) == "updated"
    assert tm.get_task(conn, tid).note == "远端备注"
    conn.close()


def test_sync_merge_without_note_key_keeps_local_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """远端记录里没有 note（老客户端/旧快照）时，**不许把本地备注清空**。"""
    conn = db_mod.connect(str(tmp_path / "s2.db"))
    tid = tm.create_task(conn, "本地任务", note="本地辛苦写的备注").id

    remote = {"id": tid, "title": "远端标题", "updated_at": "2030-01-01T00:00:00", "version": 9}
    assert sync.merge_task(conn, remote) == "updated"
    got = tm.get_task(conn, tid)
    assert got.title == "远端标题"  # 其余字段照旧：远端说了算
    assert got.note == "本地辛苦写的备注"  # 备注不被静默抹掉
    conn.close()


def test_sync_merge_insert_carries_note(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """本地没有这条任务时，插入也要带上远端备注。"""
    conn = db_mod.connect(str(tmp_path / "s3.db"))
    remote = {
        "id": "remote-1",
        "title": "远端新任务",
        "note": "远端备注",
        "status": "未开始",
        "created_at": "2029-01-01T00:00:00",
        "updated_at": "2029-01-01T00:00:00",
        "version": 1,
    }
    assert sync.merge_task(conn, remote) == "inserted"
    assert tm.get_task(conn, "remote-1").note == "远端备注"
    conn.close()
