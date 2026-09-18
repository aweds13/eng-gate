"""第 5 步·手动投入物化：`invest.manual` 事实（秒）+ 撤销（F2 OP-13）。

单位口径（2026-09-18 用户确认）：**秒**，与 `focus.finished` 完全同口径。
账本口径：`manual_hours = 今日有效 invest.manual(秒)/3600`，**单列**，
不并入 `invest_hours`（后者仍只算专注）。

覆盖：事实形态 / 撤销反向事实与幂等 / 负值拒绝 / manual_hours 计算与撤销回退 /
与 invest_hours 分离 / 旧表兼容 / 事件广播 / API 全链路。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import memo
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


# ---- 事实与旧表 ----

def test_add_invest_records_seconds_fact(conn: sqlite3.Connection) -> None:
    eid = memo.add_invest_entry(conn, value=1500.0, kind="focus", note="番茄")

    rows = facts_mod.query(conn, kind="invest.manual")
    assert len(rows) == 1
    fact = rows[0]
    assert fact["subject_type"] == "invest"
    assert fact["subject_id"] == eid
    assert fact["value_num"] == 1500.0  # 秒
    assert fact["value_text"] == "focus"
    assert fact["extra"]["note"] == "番茄"
    # 旧路径仍在（兼容）
    legacy = conn.execute(
        "SELECT axis, kind, value FROM ledger_entries WHERE id = ?", (eid,)
    ).fetchone()
    assert (legacy["axis"], legacy["kind"], legacy["value"]) == ("invest", "focus", 1500.0)


def test_add_invest_publishes_event(conn: sqlite3.Connection) -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    facts_mod.subscribe("invest.manual", lambda _k, p: seen.append(p))
    eid = memo.add_invest_entry(conn, value=600.0, kind="habit")

    assert len(seen) == 1
    assert seen[0]["entry_id"] == eid
    assert seen[0]["seconds"] == 600.0


def test_add_invest_negative_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        memo.add_invest_entry(conn, value=-1.0)
    assert facts_mod.count(conn, kind="invest.manual") == 0


# ---- 撤销 ----

def test_retract_invest_is_reverse_fact(conn: sqlite3.Connection) -> None:
    eid = memo.add_invest_entry(conn, value=1500.0)
    assert memo.retract_invest_entry(conn, eid) is True

    assert facts_mod.count(conn, kind="invest.manual") == 1  # 历史保留
    assert facts_mod.count(conn, kind="invest.retracted") == 1
    assert memo.retract_invest_entry(conn, eid) is False  # 幂等
    assert facts_mod.count(conn, kind="invest.retracted") == 1


def test_retract_unknown_invest_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        memo.retract_invest_entry(conn, "nope")


def test_list_invests_marks_retracted(conn: sqlite3.Connection) -> None:
    a = memo.add_invest_entry(conn, value=600.0, note="A")
    b = memo.add_invest_entry(conn, value=1800.0, note="B")
    memo.retract_invest_entry(conn, a)

    by_id = {r["entry_id"]: r for r in memo.list_invests(conn)}
    assert set(by_id) == {a, b}
    assert by_id[a]["retracted"] is True
    assert by_id[b]["retracted"] is False
    assert by_id[b]["seconds"] == 1800.0
    assert by_id[b]["minutes"] == 30.0


# ---- 账本口径 ----

def test_summary_manual_hours_from_seconds(conn: sqlite3.Connection) -> None:
    memo.add_invest_entry(conn, value=1800.0)  # 30 分钟

    s = ledger.summary(conn)
    assert s.manual_hours == 0.5
    assert s.invest_hours == 0.0  # 专注口径不含手动投入


def test_summary_manual_hours_excludes_retracted(conn: sqlite3.Connection) -> None:
    a = memo.add_invest_entry(conn, value=1800.0)
    memo.add_invest_entry(conn, value=900.0)
    memo.retract_invest_entry(conn, a)

    assert ledger.summary(conn).manual_hours == 0.25


def test_summary_manual_and_focus_kept_separate(conn: sqlite3.Connection) -> None:
    from timeflow.core import focus as fc

    sid = fc.start_session(conn, kind=fc.KIND_PLAIN)
    fc.finish_session(conn, sid, 1800)  # 专注 0.5h
    memo.add_invest_entry(conn, value=900.0)  # 手动 0.25h

    s = ledger.summary(conn)
    assert s.invest_hours == 0.5  # 只算专注
    assert s.manual_hours == 0.25  # 手动单列
    assert s.manual_hours + s.invest_hours == 0.75


def test_summary_manual_zero_without_entries(conn: sqlite3.Connection) -> None:
    assert ledger.summary(conn).manual_hours == 0.0


# ---- API ----

def test_api_invest_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "i.db")))
    eid = client.post(
        "/api/ledger/invest", json={"value": 1500, "kind": "focus", "note": "番茄"}
    ).json()["id"]

    rows = client.get("/api/ledger/invests").json()
    assert [r["entry_id"] for r in rows] == [eid]
    assert rows[0]["seconds"] == 1500
    assert client.get("/api/summary").json()["manual_hours"] == 0.42

    assert client.delete(f"/api/ledger/invest/{eid}").json()["retracted"] is True
    assert client.get("/api/summary").json()["manual_hours"] == 0.0
    assert client.get("/api/ledger/invests").json()[0]["retracted"] is True
    assert client.delete(f"/api/ledger/invest/{eid}").json()["retracted"] is False
    assert client.delete("/api/ledger/invest/nope").status_code == 404


def test_api_invest_negative_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "n.db")))
    assert client.post("/api/ledger/invest", json={"value": -60}).status_code == 400
