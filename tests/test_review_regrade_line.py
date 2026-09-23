"""G 批 · T-G13：复习「改判」——把今天记错的那一档改成另一档（F6 OP-27 可逆的延伸）。

口径（契约 OP-27「可逆：可撤销本次反馈」的**下一小步**，没有新增需要拍板的东西）：
- 「改判」= **撤销这一次 + 按新档重来**，两步都走既有路径 ——
  FSRS 从**同一个复习前快照**重算，所以"改判"与"当时就点另一档"是**同一个结果**；
- 原事实**不删**（追加 `review.undone` 指回它 + 新的 `review.completed`），
  另记一条 `review.regraded`；
- **投入不重复计**（账本按"当日有效完成事实、同卡只算一次"）；
- 拒绝的情况都 **400 带原话**：今天没复习过 / 给的档和原来一样 / 非法档。
"""

from __future__ import annotations

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
    c = db_mod.connect(str(tmp_path / "regrade.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _facts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = facts_mod.query(conn, kind="review.")
    counts: dict[str, int] = {}
    for r in rows:
        counts[str(r["kind"])] = counts.get(str(r["kind"]), 0) + 1
    return counts


def test_regrade_equals_pressing_the_other_button(conn: sqlite3.Connection) -> None:
    """**这张卡的核心判据**：改判成"忘了" ≡ 当时就点"忘了"（排期、次数、遗忘次数全一样）。"""
    fresh = rv.create_item(conn, "直接点忘了")
    straight = rv.review(conn, fresh, rv.RATING_FORGOT)

    other = rv.create_item(conn, "先记得再改判")
    rv.review(conn, other, rv.RATING_REMEMBER)
    got = rv.regrade(conn, other, rv.RATING_FORGOT)

    assert got["due_date"] == straight["due_date"]
    assert got["interval_days"] == straight["interval_days"]
    assert got["reps"] == straight["reps"]
    assert got["lapses"] == straight["lapses"]
    assert got["regraded_from"] == rv.RATING_REMEMBER
    assert got["regraded_to"] == rv.RATING_FORGOT
    # 卡上的字段也真的落库了（不是只改了返回值）
    card = rv.get_item(conn, other)
    assert card["due_date"] == straight["due_date"] and card["reps"] == straight["reps"]


def test_regrade_keeps_both_reviews_in_the_history(conn: sqlite3.Connection) -> None:
    """改判**不抹掉**原来那次：流水里看得见"记过记得→撤销→按忘了重来→改判"。"""
    rid = rv.create_item(conn, "泰勒展开")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.regrade(conn, rid, rv.RATING_FUZZY)

    assert _facts(conn) == {
        "review.completed": 2,   # 原来那次 + 改判后的那次
        "review.undone": 1,      # 原来那次被撤销（指回它的 id）
        "review.regraded": 1,    # 改判痕迹（从哪一档到哪一档）
    }
    regraded = facts_mod.query(conn, kind="review.regraded")[0]
    assert regraded["extra"]["from"] == rv.RATING_REMEMBER
    assert regraded["extra"]["to"] == rv.RATING_FUZZY
    first_fact = facts_mod.query(conn, kind="review.completed")[0]
    assert regraded["extra"]["fact_id"] == str(first_fact["id"])
    assert regraded["value_num"] == 0.0  # 改判不是又一次复习：不折算时间


def test_regrade_does_not_double_count_invest(conn: sqlite3.Connection) -> None:
    """改判不算"又复习了一次"：同日同卡在账本里始终只算一次。"""
    rid = rv.create_item(conn, "洛必达")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    assert ledger.summary(conn).review_count == 1

    rv.regrade(conn, rid, rv.RATING_FORGOT)
    assert ledger.summary(conn).review_count == 1
    rv.regrade(conn, rid, rv.RATING_FUZZY)   # 接二连三改判也只算一次
    assert ledger.summary(conn).review_count == 1
    assert ledger.summary(conn).invest_hours == 0.0


def test_regrade_twice_ends_where_one_press_would(conn: sqlite3.Connection) -> None:
    """连续改判：每次都从**复习前**的快照重算，不会一次比一次漂。"""
    fresh = rv.create_item(conn, "直接点模糊")
    straight = rv.review(conn, fresh, rv.RATING_FUZZY)

    rid = rv.create_item(conn, "连改两次")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.regrade(conn, rid, rv.RATING_FORGOT)
    got = rv.regrade(conn, rid, rv.RATING_FUZZY)

    assert got["due_date"] == straight["due_date"]
    assert got["reps"] == straight["reps"] and got["lapses"] == straight["lapses"]
    # 这张卡：3 条 completed（第一次 + 两次改判各一条）+ 2 条 undone + 2 条 regraded；
    # 另外那条对照卡自己也有 1 条 completed（所以总数是 4）。
    assert _facts(conn) == {
        "review.completed": 4, "review.undone": 2, "review.regraded": 2,
    }
    mine = [
        f for f in facts_mod.query(conn, kind="review.completed")
        if str(f["subject_id"]) == rid
    ]
    assert len(mine) == 3


def test_regrade_needs_a_review_today(conn: sqlite3.Connection) -> None:
    """今天没复习过 → 拒绝并说清原因（**不**凭空造一次复习出来）。"""
    rid = rv.create_item(conn, "从没复习")
    with pytest.raises(ValueError, match="没有可以改判的反馈"):
        rv.regrade(conn, rid, rv.RATING_FORGOT)
    assert _facts(conn) == {}
    assert rv.get_item(conn, rid)["reps"] == 0

    # 复习完又撤销掉 → 也不该能改判（那一次已经不算数了）
    rv.review(conn, rid, rv.RATING_REMEMBER)
    rv.undo_review(conn, rid)
    with pytest.raises(ValueError, match="没有可以改判的反馈"):
        rv.regrade(conn, rid, rv.RATING_FORGOT)
    assert _facts(conn) == {"review.completed": 1, "review.undone": 1}


def test_regrade_rejects_the_same_rating(conn: sqlite3.Connection) -> None:
    """改成一样的档没有意义：拒绝（界面也不会给同一个档的按钮），卡片一个字节都不动。"""
    rid = rv.create_item(conn, "改了个寂寞")
    before = rv.review(conn, rid, rv.RATING_REMEMBER)
    with pytest.raises(ValueError, match="不用改判"):
        rv.regrade(conn, rid, rv.RATING_REMEMBER)
    assert rv.get_item(conn, rid)["due_date"] == before["due_date"]
    assert _facts(conn) == {"review.completed": 1}


def test_regrade_rejects_unknown_rating_and_missing_card(conn: sqlite3.Connection) -> None:
    rid = rv.create_item(conn, "傅里叶")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    with pytest.raises(ValueError, match="非法反馈"):
        rv.regrade(conn, rid, "perfect")
    with pytest.raises(KeyError):
        rv.regrade(conn, "nope", rv.RATING_FORGOT)


def test_reviewed_today_items_carry_the_rating(conn: sqlite3.Connection) -> None:
    """「今天复习过的」列表：带上这次记的是哪一档（界面靠它显示与改判）。"""
    rid = rv.create_item(conn, "泰勒展开")
    assert rv.reviewed_today_items(conn) == []

    rv.review(conn, rid, rv.RATING_FORGOT)
    got = rv.reviewed_today_items(conn)
    assert len(got) == 1
    assert got[0]["id"] == rid and got[0]["title"] == "泰勒展开"
    assert got[0]["feedback"] == rv.RATING_FORGOT
    assert got[0]["feedback_label"] == rv.RATING_LABELS[rv.RATING_FORGOT]
    assert got[0]["due_date"] == rv.get_item(conn, rid)["due_date"]

    rv.regrade(conn, rid, rv.RATING_REMEMBER)          # 改判后列表跟着变
    assert rv.reviewed_today_items(conn)[0]["feedback"] == rv.RATING_REMEMBER

    rv.undo_review(conn, rid)                          # 撤销后就不该再出现在"今天复习过的"里
    assert rv.reviewed_today_items(conn) == []


def test_reviewed_today_items_skips_deleted_card(conn: sqlite3.Connection) -> None:
    """卡被删掉后，事实还在但列表里不留幽灵条目。"""
    rid = rv.create_item(conn, "会被删的卡")
    rv.review(conn, rid, rv.RATING_REMEMBER)
    conn.execute("DELETE FROM review_items WHERE id = ?", (rid,))
    conn.commit()
    assert rv.reviewed_today_items(conn) == []


def test_meta_exposes_the_three_ratings(conn: sqlite3.Connection) -> None:
    """三档中文只在后端一处：`meta.ratings` 给界面用（顺序 = 记得/模糊/忘了）。"""
    ratings = rv.meta(conn)["ratings"]
    assert [r["value"] for r in ratings] == list(rv.RATINGS)
    assert [r["label"] for r in ratings] == ["记得", "模糊", "忘了"]


def test_api_regrade_and_today(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "rg.db")))
    rid = client.post("/api/review/items", json={"title": "傅里叶"}).json()["id"]

    assert client.get("/api/review/today").json() == []
    client.post(f"/api/review/{rid}/review", json={"feedback": "remember"})
    today = client.get("/api/review/today").json()
    assert today[0]["id"] == rid and today[0]["feedback_label"] == "记得"
    assert client.get("/api/summary").json()["review_count"] == 1

    # 改成一样的档 → 400（说"不用改判"）；改成另一档 → 200
    same = client.post(f"/api/review/{rid}/regrade", json={"feedback": "remember"})
    assert same.status_code == 400 and "不用改判" in same.json()["detail"]
    got = client.post(f"/api/review/{rid}/regrade", json={"feedback": "forgot"})
    assert got.status_code == 200
    assert got.json()["regraded_to"] == "forgot"
    assert client.get("/api/review/today").json()[0]["feedback_label"] == "忘了"
    assert client.get("/api/summary").json()["review_count"] == 1  # 投入不重复计

    assert client.post("/api/review/nope/regrade", json={"feedback": "fuzzy"}).status_code == 404
    assert client.post(f"/api/review/{rid}/regrade", json={"feedback": "bogus"}).status_code == 400
    # 今天没复习过的卡也能拒绝（走同一条 400 通道）
    other = client.post("/api/review/items", json={"title": "另一张"}).json()["id"]
    never = client.post(f"/api/review/{other}/regrade", json={"feedback": "fuzzy"})
    assert never.status_code == 400 and "没有可以改判的反馈" in never.json()["detail"]
