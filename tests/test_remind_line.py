"""F1 主线 · 段2 · T-B5（前半）：任务提醒 `remind_at`（SR-F1.4a「Remind me」）。

覆盖：
- schema v9 → v10 加列：幂等、老行 NULL（不提醒）、缺 tasks 表的残缺库不失败；
- 时间口径：**本地时间** `YYYY-MM-DDTHH:MM`（datetime-local 的形状），空格分隔也接受并归一；
  空 = 清除（NULL，不写空串）；非法格式拒绝（400 / ValueError），**不静默忽略**；
- 界面口径 `reminder_state`：`over`（到点/过点）/ `today` / `soon`（7 天内）/ `later`；
  **完成后不再催**（None）——不打扰是基调；
- 数据源 `due_reminders`：只取 `remind_at <= now` 且任务还活着的（排除完成/取消/归档/已删），
  按时间正序；
- 只读口径：提醒不发 facts、不动账本；
- 跨端：`sync.merge_task` 带 remind_at，远端没带时保留本地值；
- **不含**：系统通知通道（属新增运行时依赖，选型待用户确认；
  见 `复盘/段2设计决策-提醒与附件打开方式.md` §八）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


def _client(tmp_path, name: str = "remind.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _make_v9_db(path: str) -> None:
    """手工造一个 v9 旧库：tasks 有 attach、**没有 remind_at**。"""
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (9)")
    raw.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, due_date TEXT,"
        " group_name TEXT, repeat_days INTEGER, parent_id TEXT, is_myday INTEGER DEFAULT 0,"
        " status TEXT, created_at TEXT, updated_at TEXT, version INTEGER DEFAULT 1,"
        " note TEXT, priority TEXT DEFAULT '中', flagged INTEGER DEFAULT 0, attach TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id,title,status,created_at,updated_at,version)"
        " VALUES ('old1','旧任务','未开始','2026-01-01','2026-01-01',1)"
    )
    raw.commit()
    raw.close()


# ---------------------------------------------------------------- 迁移（v10）

def test_upgrade_v9_adds_remind_at(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v9.db")
    _make_v9_db(p)

    conn = db_mod.connect(p)
    ver = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert int(ver["version"]) == db_mod.SCHEMA_VERSION
    assert tm.get_task(conn, "old1").remind_at is None  # 老行不猜一个提醒时间出来
    conn.close()


def test_upgrade_v10_is_idempotent_and_missing_table_ok(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = str(tmp_path / "v9b.db")
    _make_v9_db(p)
    for _ in range(3):
        c = db_mod.connect(p)
        cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(tasks)").fetchall()]
        assert cols.count("remind_at") == 1
        c.close()

    broken = str(tmp_path / "broken.db")
    raw = sqlite3.connect(broken)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (9)")
    raw.commit()
    raw.close()
    c2 = db_mod.connect(broken)
    assert int(c2.execute("SELECT version FROM schema_version").fetchone()["version"]) == (
        db_mod.SCHEMA_VERSION
    )
    c2.close()


# ---------------------------------------------------------------- 时间口径

def test_create_and_clear_remind_at(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "d.db"))
    t = tm.create_task(conn, "开会", remind_at="2026-09-20 08:30")  # 空格分隔也接受
    assert t.remind_at == "2026-09-20T08:30"  # 统一归一成 datetime-local 形状
    assert tm.update_task(conn, t.id, remind_at="").remind_at is None  # 空 = 清除
    assert tm.update_task(conn, t.id, remind_at="2026-09-21T07:00").remind_at == "2026-09-21T07:00"
    assert tm.update_task(conn, t.id, remind_at=None).remind_at is None
    conn.close()


def test_invalid_remind_at_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "bad.db"))
    with pytest.raises(ValueError):
        tm.create_task(conn, "任务", remind_at="明天早上")  # 不给模糊时间蒙混过关
    with pytest.raises(ValueError):
        tm.create_task(conn, "任务", remind_at="2026-09-20")  # 只给日期不行：提醒要具体到时间
    t = tm.create_task(conn, "任务")
    with pytest.raises(ValueError):
        tm.update_task(conn, t.id, remind_at="2026/09/20 08:30")
    assert tm.get_task(conn, t.id).remind_at is None  # 校验失败没有落库
    conn.close()


def test_api_remind_roundtrip_and_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    tid = client.post(
        "/api/tasks", json={"title": "写作业", "remind_at": "2030-01-01T09:00"}
    ).json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["remind_at"] == "2030-01-01T09:00"

    assert client.patch(
        f"/api/tasks/{tid}", json={"remind_at": "2030-01-02T10:00"}
    ).json()["remind_at"] == "2030-01-02T10:00"
    assert client.patch(f"/api/tasks/{tid}", json={"remind_at": None}).json()["remind_at"] is None
    assert client.patch(f"/api/tasks/{tid}", json={"remind_at": "明天"}).status_code == 400


# ---------------------------------------------------------------- 界面口径

def test_reminder_state_buckets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "state.db"))
    now = datetime(2026, 9, 20, 12, 0)
    over = tm.create_task(conn, "过点", remind_at="2026-09-20T09:00")
    today = tm.create_task(conn, "今天晚些", remind_at="2026-09-20T18:00")
    soon = tm.create_task(conn, "三天后", remind_at="2026-09-23T09:00")
    later = tm.create_task(conn, "下个月", remind_at="2026-10-20T09:00")
    none = tm.create_task(conn, "没设提醒")

    assert tm.reminder_state(over, now) == "over"
    assert tm.reminder_state(today, now) == "today"
    assert tm.reminder_state(soon, now) == "soon"
    assert tm.reminder_state(later, now) == "later"
    assert tm.reminder_state(none, now) is None
    conn.close()


def test_completed_task_stops_reminding(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """完成后不再催（不打扰）：完成/取消/归档/已删都不再有提醒状态。"""
    conn = db_mod.connect(str(tmp_path / "done.db"))
    now = datetime(2026, 9, 20, 12, 0)
    t = tm.create_task(conn, "任务", remind_at="2026-09-20T09:00")
    assert tm.reminder_state(t, now) == "over"
    tm.complete_task(conn, t.id)
    assert tm.reminder_state(tm.get_task(conn, t.id), now) is None
    assert tm.due_reminders(conn, now) == []
    conn.close()


def test_due_reminders_only_alive_and_ordered(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "due.db"))
    now = datetime(2026, 9, 20, 12, 0)
    late = tm.create_task(conn, "早该提醒", remind_at="2026-09-19T09:00")
    just = tm.create_task(conn, "刚到", remind_at="2026-09-20T12:00")
    tm.create_task(conn, "还没到", remind_at="2026-09-21T09:00")
    cancelled = tm.create_task(conn, "取消的", remind_at="2026-09-19T08:00")
    tm.update_task(conn, cancelled.id, status=tm.STATUS_CANCELLED)
    deleted = tm.create_task(conn, "删掉的", remind_at="2026-09-19T07:00")
    tm.delete_task(conn, deleted.id)

    assert [t.id for t in tm.due_reminders(conn, now)] == [late.id, just.id]
    conn.close()


def test_reminders_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "api.db")
    client.post("/api/tasks", json={"title": "早", "remind_at": "2026-09-19T09:00"})
    client.post("/api/tasks", json={"title": "晚", "remind_at": "2030-01-01T09:00"})

    due = client.get("/api/reminders/due?now=2026-09-20T12:00").json()
    assert [t["title"] for t in due] == ["早"]
    assert client.get("/api/reminders/due?now=乱写").status_code == 400

    allr = client.get("/api/reminders").json()
    assert {r["title"] for r in allr} == {"早", "晚"}
    assert all("state" in r for r in allr)
    conn_states = {r["title"]: r["state"] for r in allr}
    assert conn_states["晚"] in ("soon", "later")


def test_remind_is_not_a_fact_and_not_in_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "ledger.db")
    tid = client.post("/api/tasks", json={"title": "任务", "due_date": "2030-01-01"}).json()["id"]
    before = client.get("/api/summary").json()

    client.patch(f"/api/tasks/{tid}", json={"remind_at": "2030-01-01T08:00"})
    client.get("/api/reminders/due?now=2030-01-02T00:00")  # 读一下也不该产生记录
    assert client.get(f"/api/tasks/{tid}/facts").json() == []
    assert client.get("/api/summary").json() == before


def test_repeat_does_not_inherit_remind(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """下一次**不继承提醒**：提醒是"这一次什么时候叫我"，抄到下一周期会变成乱响。"""
    conn = db_mod.connect(str(tmp_path / "repeat.db"))
    t = tm.create_task(
        conn, "每周交周报", due_date="2026-12-31", repeat_days=7, remind_at="2026-12-31T09:00"
    )
    tm.complete_task(conn, t.id)
    same = [x for x in tm.list_tasks(conn, active_only=False) if x.title == "每周交周报"]
    nxt = [x for x in same if x.id != t.id][0]
    assert nxt.remind_at is None
    conn.close()


def test_sync_merge_carries_remind_and_keeps_local_when_absent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "sync.db"))
    tid = tm.create_task(conn, "本地", remind_at="2030-01-01T09:00").id

    sync.merge_task(conn, {
        "id": tid, "title": "远端", "remind_at": "2031-01-01T09:00",
        "updated_at": "2030-06-01T00:00:00", "version": 9,
    })
    assert tm.get_task(conn, tid).remind_at == "2031-01-01T09:00"

    sync.merge_task(conn, {
        "id": tid, "title": "远端二", "updated_at": "2030-07-01T00:00:00", "version": 10,
    })
    got = tm.get_task(conn, tid)
    assert got.title == "远端二"
    assert got.remind_at == "2031-01-01T09:00"  # 老客户端没带这个字段 → 保留本地提醒
    conn.close()
