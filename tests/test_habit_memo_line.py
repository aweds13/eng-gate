"""第 10 步·习惯与备忘录补强：习惯改名/删除（契约 OP-18）+ 备忘录转任务/删除（SR-F8 R2）。

背景（此前缺口）：
- 习惯只有「新建 + 打卡」——建错了删不掉、起错名改不了；
- 备忘录只能新增与列表——随手记的想法**无法变成任务**（SR-F8 R2 明确要求「可顺手建成任务」）。
口径：删除习惯一并删打卡记录（避免孤立历史在热力图上制造无法解释的格子）；删除备忘录不连坐任务。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import feedback as fb
from timeflow.core import memo
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


# ---- 习惯改名/删除 ----

def test_rename_habit(conn: sqlite3.Connection) -> None:
    hid = fb.create_habit(conn, "早睡")
    fb.update_habit(conn, hid, "  早睡早起  ")

    rows = fb.list_habits(conn)
    assert rows[0]["name"] == "早睡早起"  # 去空格
    assert rows[0]["id"] == hid


def test_rename_habit_rejects_blank(conn: sqlite3.Connection) -> None:
    hid = fb.create_habit(conn, "早睡")
    with pytest.raises(ValueError):
        fb.update_habit(conn, hid, "   ")


def test_delete_habit_removes_logs(conn: sqlite3.Connection) -> None:
    hid = fb.create_habit(conn, "早睡")
    today = date.today()
    for i in range(3):
        fb.toggle_habit_log(conn, hid, (today - timedelta(days=i)).isoformat())
    assert fb.habit_logs(conn, hid) != []

    fb.delete_habit(conn, hid)
    assert fb.list_habits(conn) == []
    assert fb.habit_logs(conn, hid) == []  # 打卡记录一并清掉
    left = conn.execute("SELECT COUNT(*) AS n FROM habit_logs").fetchone()
    assert int(left["n"]) == 0
    fb.delete_habit(conn, hid)  # 幂等


def test_delete_one_habit_keeps_other(conn: sqlite3.Connection) -> None:
    a = fb.create_habit(conn, "早睡")
    b = fb.create_habit(conn, "跑步")
    fb.toggle_habit_log(conn, a)
    fb.toggle_habit_log(conn, b)

    fb.delete_habit(conn, a)
    rows = fb.list_habits(conn)
    assert [r["name"] for r in rows] == ["跑步"]
    assert rows[0]["logs"]  # 另一个习惯的打卡没被误删


# ---- 备忘录转任务 / 删除 ----

def test_memo_to_task_keeps_memo_and_links(conn: sqlite3.Connection) -> None:
    mid = memo.create_memo(conn, "给数学笔记补一节泰勒展开")
    tid = memo.memo_to_task(conn, mid, due_date="2026-12-31", is_myday=True)

    task = tm.get_task(conn, tid)
    assert task.title == "给数学笔记补一节泰勒展开"
    assert task.due_date == "2026-12-31"
    assert task.is_myday is True
    # 备忘录保留，并记下关联任务
    row = [m for m in memo.list_memos(conn) if m["id"] == mid][0]
    assert row["text"] == "给数学笔记补一节泰勒展开"
    assert row["task_id"] == tid


def test_memo_to_task_defaults_to_today(conn: sqlite3.Connection) -> None:
    mid = memo.create_memo(conn, "随手冒出的想法")
    tid = memo.memo_to_task(conn, mid)
    assert tm.get_task(conn, tid).is_myday is True


def test_memo_to_task_unknown_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        memo.memo_to_task(conn, "nope")


def test_delete_memo_keeps_linked_task(conn: sqlite3.Connection) -> None:
    mid = memo.create_memo(conn, "临时想法")
    tid = memo.memo_to_task(conn, mid)

    memo.delete_memo(conn, mid)
    assert memo.list_memos(conn) == []
    assert tm.get_task(conn, tid).title == "临时想法"  # 任务不连坐
    memo.delete_memo(conn, mid)  # 幂等


# ---- API ----

def test_api_habit_rename_delete(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "h.db")))
    hid = client.post("/api/habits", json={"name": "早睡"}).json()["id"]

    assert client.patch(f"/api/habits/{hid}", json={"name": "早睡早起"}).status_code == 200
    assert [h["name"] for h in client.get("/api/habits").json()] == ["早睡早起"]
    assert client.patch(f"/api/habits/{hid}", json={"name": "  "}).status_code == 400

    assert client.delete(f"/api/habits/{hid}").status_code == 200
    assert client.get("/api/habits").json() == []


def test_api_memo_to_task_and_delete(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "m.db")))
    mid = client.post("/api/memos", json={"text": "写一篇复盘"}).json()["id"]

    moved = client.post(f"/api/memos/{mid}/to-task", json={"is_myday": True}).json()
    assert client.get(f"/api/tasks/{moved['task_id']}").json()["title"] == "写一篇复盘"
    assert client.post("/api/memos/nope/to-task").status_code == 404

    assert client.delete(f"/api/memos/{mid}").status_code == 200
    assert client.get("/api/memos").json() == []


# ---- 打卡直接算投入（T-G164）：可选分钟，留空与老行为逐字相同 ----

def test_habit_toggle_blank_writes_no_ledger(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """留空 → 与老行为逐字相同：habit_logs +1、ledger_entries 零新增。"""
    client = TestClient(create_app(str(tmp_path / "h1.db")))
    hid = client.post("/api/habits", json={"name": "早睡"}).json()["id"]

    r = client.post(f"/api/habits/{hid}/toggle")
    assert r.json() == {"done": True, "entry_id": None}

    con = db_mod.connect(str(tmp_path / "h1.db"))
    try:
        logs = con.execute("SELECT COUNT(*) AS n FROM habit_logs WHERE done=1").fetchone()
        ledger = con.execute("SELECT COUNT(*) AS n FROM ledger_entries").fetchone()
    finally:
        con.close()
    assert int(logs["n"]) == 1
    assert int(ledger["n"]) == 0


def test_habit_toggle_with_minutes_writes_one_invest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """填 30 → habit_logs +1 且**另写一条** axis=invest / kind=habit（秒口径，与专注同口径）。"""
    client = TestClient(create_app(str(tmp_path / "h2.db")))
    hid = client.post("/api/habits", json={"name": "跑步"}).json()["id"]

    body = client.post(f"/api/habits/{hid}/toggle?invest_minutes=30").json()
    assert body["done"] is True and body["entry_id"]

    con = db_mod.connect(str(tmp_path / "h2.db"))
    try:
        row = con.execute(
            "SELECT axis, kind, value FROM ledger_entries WHERE id=?", (body["entry_id"],)
        ).fetchone()
        logs = con.execute("SELECT COUNT(*) AS n FROM habit_logs WHERE done=1").fetchone()
    finally:
        con.close()
    assert int(logs["n"]) == 1
    assert (row["axis"], row["kind"]) == ("invest", "habit")
    assert float(row["value"]) == 1800.0  # 30 分钟 = 1800 秒

    # 「今日手动投入」同一统计入口：流水里看得到、合计 +30
    rows = client.get("/api/ledger/invests").json()
    assert [x["minutes"] for x in rows if not x["retracted"]] == [30.0]


def test_habit_invest_retractable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """打卡写的那条投入走既有撤销路：撤销后合计回退到 0。"""
    client = TestClient(create_app(str(tmp_path / "h3.db")))
    hid = client.post("/api/habits", json={"name": "阅读"}).json()["id"]
    eid = client.post(f"/api/habits/{hid}/toggle?invest_minutes=30").json()["entry_id"]

    assert client.delete(f"/api/ledger/invest/{eid}").json()["retracted"] is True
    rows = client.get("/api/ledger/invests").json()
    assert rows[0]["retracted"] is True
    assert [x for x in rows if not x["retracted"]] == []
