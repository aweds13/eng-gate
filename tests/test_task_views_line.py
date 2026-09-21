"""F1 主线 · 段2 · T-B3：三视图 Important / Planned / Flagged（SR-F1.2「提供视图」）。

覆盖：
- schema v7 → v8 加列：`flagged` 布尔位（幂等、老行默认 0=未标记、缺 tasks 表的残缺库不失败）；
- 口径（**定在领域层**，界面不自己筛）：
  - `important` = 优先级「高」（T-B2 的字段，不另造"重要"概念）；
  - `planned`   = **有截止日**；`flagged` = **手动标记位**；
  - 基线同「全部任务」：只隐藏 归档/已删（完成的仍如实显示）；排序同统一口径；
  - 未知视图名 → 领域 ValueError / API 400（**不静默返回全部**，否则会以为筛选生效了）；
- 手动标记：开关幂等翻转、`PATCH flagged` 可写、不发事实不动账本；
- 跨端：`sync.merge_task` 带 flagged，远端没带时保留本地标记。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "view.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v7_db(path: str) -> None:
    """手工造一个 v7 旧库：tasks 有 note/priority、**没有 flagged**。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (7)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1,"
        " note TEXT, priority TEXT DEFAULT '中')"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version,priority)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1,'高')"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v8）

def test_upgrade_v7_adds_flagged_column(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """v7 → v8：补 flagged 列，老行一律 **0（未标记）** —— 不帮用户猜"哪些算标记"。"""
    p = str(tmp_path / "v7.db")
    _make_v7_db(p)

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    row = conn.execute("SELECT title, priority, flagged FROM tasks WHERE id='old1'").fetchone()
    assert row["title"] == "旧任务" and row["priority"] == "高"
    assert int(row["flagged"]) == 0
    conn.close()


def test_upgrade_v8_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v7b.db")
    _make_v7_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        assert cols.count("flagged") == 1
        c.close()


def test_v8_on_fresh_db_and_missing_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "fresh.db"))
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert "flagged" in cols
    conn.close()

    p = str(tmp_path / "broken.db")
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (7)")
    raw.commit()
    raw.close()
    c2 = db_mod.connect(p)  # 缺 tasks 表：跳过加列，不失败
    assert int(c2.execute("SELECT version FROM schema_version").fetchone()["version"]) == (
        db_mod.SCHEMA_VERSION
    )
    c2.close()


# ---------------------------------------------------------------- 智能视图口径

def test_important_is_high_priority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "imp.db"))
    tm.create_task(conn, "高", priority="高")
    tm.create_task(conn, "中")
    tm.create_task(conn, "低", priority="低")

    assert [t.title for t in tm.tasks_in_view(conn, tm.VIEW_IMPORTANT)] == ["高"]
    conn.close()


def test_planned_needs_due_date(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "plan.db"))
    tm.create_task(conn, "有截止", due_date="2030-01-01")
    tm.create_task(conn, "两个都有", due_date="2030-02-01")
    tm.create_task(conn, "没截止", priority="高")

    assert [t.title for t in tm.tasks_in_view(conn, tm.VIEW_PLANNED)] == ["有截止", "两个都有"]
    conn.close()


def test_flagged_view_uses_manual_flag(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "flag.db"))
    a = tm.create_task(conn, "标记我")
    tm.create_task(conn, "别标记")

    assert tm.tasks_in_view(conn, tm.VIEW_FLAGGED) == []
    tm.toggle_flag(conn, a.id)
    assert [t.title for t in tm.tasks_in_view(conn, tm.VIEW_FLAGGED)] == ["标记我"]
    conn.close()


def test_views_hide_archived_and_deleted_but_show_done(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """基线同「全部任务」：完成的**仍显示**（如实），归档/已删隐藏。"""
    conn = db_mod.connect(str(tmp_path / "base.db"))
    done = tm.create_task(conn, "完成的高", priority="高")
    tm.complete_task(conn, done.id)
    archived = tm.create_task(conn, "归档的高", priority="高")
    tm.update_task(conn, archived.id, status=tm.STATUS_ARCHIVED)
    deleted = tm.create_task(conn, "删掉的高", priority="高")
    tm.delete_task(conn, deleted.id)

    assert [t.title for t in tm.tasks_in_view(conn, tm.VIEW_IMPORTANT)] == ["完成的高"]
    conn.close()


def test_view_ordering_follows_unified_rule(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """智能视图也走统一排序（截止日 → 优先级 → 创建时间），不自己另排一套。"""
    conn = db_mod.connect(str(tmp_path / "order.db"))
    tm.create_task(conn, "晚-高", due_date="2030-02-01", priority="高")
    tm.create_task(conn, "早-高", due_date="2030-01-01", priority="高")
    tm.create_task(conn, "无截止-高", priority="高")

    assert [t.title for t in tm.tasks_in_view(conn, tm.VIEW_IMPORTANT)] == [
        "早-高", "晚-高", "无截止-高",
    ]
    conn.close()


def test_unknown_view_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "bad.db"))
    tm.create_task(conn, "随便一个")
    with pytest.raises(ValueError):
        tm.tasks_in_view(conn, "all")  # 不静默返回全部
    conn.close()


# ---------------------------------------------------------------- API

def test_api_view_filter_and_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    client.post("/api/tasks", json={"title": "高", "priority": "高"})
    client.post("/api/tasks", json={"title": "普通", "due_date": "2030-01-01"})

    assert [t["title"] for t in client.get("/api/tasks?view=important").json()] == ["高"]
    assert [t["title"] for t in client.get("/api/tasks?view=planned").json()] == ["普通"]
    assert client.get("/api/tasks?view=flagged").json() == []
    assert client.get("/api/tasks?view=nope").status_code == 400
    assert len(client.get("/api/tasks").json()) == 2  # 不带 view 仍是全部


def test_api_flag_toggle_is_idempotent_flip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "flagapi.db")
    tid = client.post("/api/tasks", json={"title": "任务"}).json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["flagged"] is False

    assert client.post(f"/api/tasks/{tid}/flag").json()["flagged"] is True
    assert [t["title"] for t in client.get("/api/tasks?view=flagged").json()] == ["任务"]
    assert client.post(f"/api/tasks/{tid}/flag").json()["flagged"] is False
    assert client.get("/api/tasks?view=flagged").json() == []
    # PATCH 也能直接写（幂等：写同样的值不报错）
    assert client.patch(f"/api/tasks/{tid}", json={"flagged": True}).json()["flagged"] is True
    assert client.patch(f"/api/tasks/{tid}", json={"flagged": True}).json()["flagged"] is True
    assert client.post("/api/tasks/nope/flag").status_code == 404


def test_flag_is_not_a_fact_and_not_in_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "flagledger.db")
    tid = client.post("/api/tasks", json={"title": "任务", "due_date": "2030-01-01"}).json()["id"]
    before = client.get("/api/summary").json()

    client.post(f"/api/tasks/{tid}/flag")
    assert client.get(f"/api/tasks/{tid}/facts").json() == []
    assert client.get("/api/summary").json() == before


# ---------------------------------------------------------------- 跨端合并

def test_sync_merge_carries_flag_and_keeps_local_when_absent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s.db"))
    tid = tm.create_task(conn, "本地", flagged=True).id

    # ① 远端带了 flagged → 以远端为准
    sync.merge_task(conn, {
        "id": tid, "title": "远端", "flagged": False,
        "updated_at": "2030-01-01T00:00:00", "version": 9,
    })
    assert tm.get_task(conn, tid).flagged is False

    # ② 远端没带这个字段（老客户端）→ 保留本地值，不静默抹掉
    tm.toggle_flag(conn, tid)
    sync.merge_task(conn, {
        "id": tid, "title": "远端二", "updated_at": "2031-01-01T00:00:00", "version": 10,
    })
    got = tm.get_task(conn, tid)
    assert got.title == "远端二"
    assert got.flagged is True
    conn.close()


def test_sync_insert_carries_flag(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s2.db"))
    sync.merge_task(conn, {
        "id": "remote-1", "title": "远端新任务", "flagged": True, "status": "未开始",
        "created_at": "2029-01-01T00:00:00", "updated_at": "2029-01-01T00:00:00", "version": 1,
    })
    assert tm.get_task(conn, "remote-1").flagged is True
    conn.close()
