"""第 2 步·复习线发事实：`review.completed` + 到期进 My Day（F6 OP-27 / OP-28）。

覆盖：
- 复习完成发一条 `review.completed` 事实（主体=卡片、不折算时间、带上反馈与下次到期）；
- 同日同卡只记一条（SR-F6 边界：重复完成幂等），且不重复推进账目；
- 账本只读事实层：`review_count` 计今日不同卡片，`invest_hours` 仍只认专注；
- 到期卡可并入 My Day（OP-28，不强制）。
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import review as rv
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


# ---- 事实 ----

def test_review_records_completed_fact(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "泰勒展开")
    result = rv.review(conn, rid, rv.RATING_REMEMBER)

    rows = facts_mod.query(conn, kind="review.completed")
    assert len(rows) == 1
    fact = rows[0]
    assert fact["subject_type"] == "review_item"
    assert fact["subject_id"] == rid
    assert fact["value_num"] == 0.0  # 不折算时间
    assert fact["extra"]["feedback"] == rv.RATING_REMEMBER
    assert fact["extra"]["next_due"] == result["due_date"]


def test_review_publishes_event(conn: sqlite3.Connection) -> None:
    seen: list[dict] = []  # type: ignore[type-arg]
    facts_mod.subscribe("review.completed", lambda _k, p: seen.append(p))
    rid = rv.create_item(conn, "洛必达法则")
    rv.review(conn, rid, rv.RATING_FUZZY)

    assert len(seen) == 1
    assert seen[0]["item_id"] == rid
    assert seen[0]["feedback"] == rv.RATING_FUZZY


def test_same_card_same_day_records_one_fact(conn: sqlite3.Connection) -> None:
    """重复完成同一张卡：推进 FSRS 但当日只留一条投入事实（幂等口径）。"""
    rid = rv.create_item(conn, "矩阵秩")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.review(conn, rid, rv.RATING_FORGOT)

    assert facts_mod.count(conn, kind="review.completed") == 1


def test_two_cards_record_two_facts(conn: sqlite3.Connection) -> None:
    a = rv.create_item(conn, "A")
    b = rv.create_item(conn, "B")
    rv.review(conn, a, rv.RATING_REMEMBER)
    rv.review(conn, b, rv.RATING_FUZZY)

    assert facts_mod.count(conn, kind="review.completed") == 2


# ---- 账本口径 ----

def test_summary_counts_reviews_not_hours(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "微分方程")
    rv.review(conn, rid, rv.RATING_REMEMBER)

    s = ledger.summary(conn)
    assert s.review_count == 1
    assert s.invest_hours == 0.0  # 复习不折算成小时（不折算精确时间）


def test_summary_review_count_distinct_cards(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "C")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.review(conn, rid, rv.RATING_REMEMBER)

    assert ledger.summary(conn).review_count == 1


def test_summary_without_reviews_is_zero(conn: sqlite3.Connection) -> None:
    assert ledger.summary(conn).review_count == 0


# ---- 到期进 My Day ----

def test_due_items_to_myday_entries(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "级数收敛")
    entries = rv.myday_entries(conn)

    assert len(entries) == 1
    assert entries[0]["kind"] == "review"
    assert entries[0]["id"] == rid


def test_learning_card_stays_due_until_graduated(conn: sqlite3.Connection) -> None:
    """FSRS 学习阶段的卡当天仍到期（会继续留在 My Day），但账目只计一次。"""
    rid = rv.create_item(conn, "格林公式")
    rv.review(conn, rid, rv.RATING_REMEMBER)

    assert [e["id"] for e in rv.myday_entries(conn)] == [rid]
    assert ledger.summary(conn).review_count == 1


def test_graduated_card_leaves_myday(conn: sqlite3.Connection) -> None:
    """连续「记得」直到 FSRS 排到未来 → 不再进 My Day。"""
    rid = rv.create_item(conn, "斯托克斯公式")
    for _ in range(4):
        rv.review(conn, rid, rv.RATING_REMEMBER)

    assert rv.due_items(conn) == []
    assert rv.myday_entries(conn) == []
    assert ledger.summary(conn).review_count == 1  # 当日仍只算一次


# ---- API ----

def test_api_review_facts_and_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "a.db")))
    rid = client.post("/api/review/items", json={"title": "傅里叶级数"}).json()["id"]

    assert client.get(f"/api/review/{rid}/facts").json() == []

    client.post(f"/api/review/{rid}/review", json={"feedback": "remember"})
    facts = client.get(f"/api/review/{rid}/facts").json()
    assert [f["kind"] for f in facts] == ["review.completed"]
    assert client.get("/api/summary").json()["review_count"] == 1


def test_api_review_facts_unknown_404(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    assert client.get("/api/review/nope/facts").status_code == 404


def test_api_mydays_include_reviews(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "c.db")))
    client.post("/api/review/items", json={"title": "到期卡"})

    assert client.get("/api/mydays").json() == []  # 默认不含（不强制）
    items = client.get("/api/mydays?include_reviews=1").json()
    assert len(items) == 1
    assert items[0]["kind"] == "review"
    assert items[0]["title"] == "到期卡"


def test_api_mydays_mixes_tasks_and_reviews(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "d.db")))
    client.post("/api/tasks", json={"title": "写高数", "is_myday": True})
    client.post("/api/review/items", json={"title": "到期卡"})

    items = client.get("/api/mydays?include_reviews=1").json()
    assert len(items) == 2
    assert {i.get("kind", "task") for i in items} == {"task", "review"}


# ---- 撤销本次反馈（第 5 步 · F6 OP-27 可逆）----

def test_undo_review_restores_card_and_accounting(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "泰勒展开")
    after = rv.review(conn, rid, rv.RATING_REMEMBER)
    assert ledger.summary(conn).review_count == 1
    assert after["reps"] == 1

    state = rv.undo_review(conn, rid)
    assert state["reps"] == 0
    assert state["due_date"] == date.today().isoformat()  # 回到复习前的到期日
    assert ledger.summary(conn).review_count == 0  # 账目一并回退
    facts = facts_mod.query(conn, kind="review.")
    assert {f["kind"] for f in facts} == {"review.completed", "review.undone"}


def test_undo_review_is_idempotent(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "洛必达")
    rv.review(conn, rid, rv.RATING_FUZZY)
    rv.undo_review(conn, rid)
    rv.undo_review(conn, rid)

    assert facts_mod.count(conn, kind="review.undone") == 1
    assert ledger.summary(conn).review_count == 0


def test_undo_review_without_completion_is_noop(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "从未复习")
    state = rv.undo_review(conn, rid)
    assert state["reps"] == 0
    assert facts_mod.count(conn, kind="review.undone") == 0


def test_review_after_undo_counts_again(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "重新复习")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.undo_review(conn, rid)
    rv.review(conn, rid, rv.RATING_FORGOT)

    assert ledger.summary(conn).review_count == 1
    assert rv.due_items(conn)  # 卡片仍在到期列表里（学习阶段）


def test_api_undo_review(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "u.db")))
    rid = client.post("/api/review/items", json={"title": "傅里叶"}).json()["id"]
    client.post(f"/api/review/{rid}/review", json={"feedback": "remember"})
    assert client.get("/api/summary").json()["review_count"] == 1

    assert client.post(f"/api/review/{rid}/undo").status_code == 200
    assert client.get("/api/summary").json()["review_count"] == 0
    assert client.post("/api/review/nope/undo").status_code == 404
