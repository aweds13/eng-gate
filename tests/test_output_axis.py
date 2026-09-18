"""第 5 步·产出轴物化：`output.manual` 事实 + 撤销（F2 §4 定案 / F8 OP-38）。

覆盖：
- 手动产出既写旧表 `ledger_entries`（兼容），也发事实 `output.manual`（新路径）；
- 撤销追加 `output.retracted` 反向事实，不删历史，幂等；
- 账本 `output_count` 计「今日产出事实 − 已撤销」，且与投入轴（invest_hours）完全分开；
- 负值拒绝；不存在记录 404；
- API：记录 / 列表 / 撤销全链路。
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


# ---- 领域层 ----

def test_output_entry_records_fact(conn: sqlite3.Connection) -> None:
    eid = memo.add_output_entry(conn, value=1.0, kind="asset", note="数学笔记#3")

    rows = facts_mod.query(conn, kind="output.manual")
    assert len(rows) == 1
    fact = rows[0]
    assert fact["subject_type"] == "output"
    assert fact["subject_id"] == eid
    assert fact["value_num"] == 1.0
    assert fact["value_text"] == "asset"
    assert fact["extra"]["note"] == "数学笔记#3"
    # 旧路径仍在（兼容）
    legacy = conn.execute("SELECT axis, kind FROM ledger_entries WHERE id = ?", (eid,)).fetchone()
    assert (legacy["axis"], legacy["kind"]) == ("output", "asset")


def test_output_publishes_event(conn: sqlite3.Connection) -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    facts_mod.subscribe("output.manual", lambda _k, p: seen.append(p))
    eid = memo.add_output_entry(conn, value=2.5, kind="kpi")

    assert len(seen) == 1
    assert seen[0]["entry_id"] == eid
    assert seen[0]["kind"] == "kpi"


def test_output_negative_value_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        memo.add_output_entry(conn, value=-1.0)
    assert facts_mod.count(conn, kind="output.manual") == 0


def test_retract_output_is_reverse_fact(conn: sqlite3.Connection) -> None:
    eid = memo.add_output_entry(conn, value=1.0, kind="asset")
    assert memo.retract_output_entry(conn, eid) is True

    assert facts_mod.count(conn, kind="output.manual") == 1  # 历史保留
    assert facts_mod.count(conn, kind="output.retracted") == 1
    assert memo.retract_output_entry(conn, eid) is False  # 幂等
    assert facts_mod.count(conn, kind="output.retracted") == 1


def test_retract_unknown_entry_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        memo.retract_output_entry(conn, "nope")


def test_list_outputs_marks_retracted(conn: sqlite3.Connection) -> None:
    a = memo.add_output_entry(conn, value=1.0, kind="asset", note="A")
    b = memo.add_output_entry(conn, value=2.0, kind="kpi", note="B")
    memo.retract_output_entry(conn, a)

    rows = memo.list_outputs(conn)
    by_id = {r["entry_id"]: r for r in rows}
    assert set(by_id) == {a, b}
    assert by_id[a]["retracted"] is True
    assert by_id[b]["retracted"] is False
    assert by_id[b]["value"] == 2.0


# ---- 账本口径 ----

def test_summary_counts_output_separately_from_invest(conn: sqlite3.Connection) -> None:
    memo.add_output_entry(conn, value=3.0, kind="asset")

    s = ledger.summary(conn)
    assert s.output_count == 1
    assert s.invest_hours == 0.0  # 产出不折算成投入
    assert s.review_count == 0


def test_summary_output_count_excludes_retracted(conn: sqlite3.Connection) -> None:
    a = memo.add_output_entry(conn, value=1.0)
    memo.add_output_entry(conn, value=1.0)
    memo.retract_output_entry(conn, a)

    assert ledger.summary(conn).output_count == 1


def test_summary_output_zero_without_entries(conn: sqlite3.Connection) -> None:
    assert ledger.summary(conn).output_count == 0


# ---- API ----

def test_api_output_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "o.db")))
    eid = client.post(
        "/api/ledger/output", json={"value": 1.0, "kind": "asset", "note": "笔记"}
    ).json()["id"]

    rows = client.get("/api/ledger/outputs").json()
    assert [r["entry_id"] for r in rows] == [eid]
    assert client.get("/api/summary").json()["output_count"] == 1

    assert client.delete(f"/api/ledger/output/{eid}").json()["retracted"] is True
    assert client.get("/api/summary").json()["output_count"] == 0
    assert client.get("/api/ledger/outputs").json()[0]["retracted"] is True

    assert client.delete(f"/api/ledger/output/{eid}").json()["retracted"] is False  # 幂等
    assert client.delete("/api/ledger/output/nope").status_code == 404


def test_api_output_negative_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "n.db")))
    assert client.post("/api/ledger/output", json={"value": -1}).status_code == 400
