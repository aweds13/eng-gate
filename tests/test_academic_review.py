"""SR-F5 学业追踪 + SR-F6 复习FSRS 测试（AC 学业/复习）。"""

from __future__ import annotations

import pytest

from timeflow.core import academic as ac
from timeflow.core import review as rv
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_course_and_assessment(conn) -> None:
    cid = ac.create_course(conn, "高等数学", credits=5.0, teacher="王老师")
    ac.add_assessment(conn, cid, "期中考试", due_date="2026-10-01", weight=0.4)
    courses = ac.list_courses(conn)
    assert courses[0]["name"] == "高等数学"
    ass = ac.list_assessments(conn, cid)
    assert ass[0]["name"] == "期中考试" and ass[0]["weight"] == 0.4


def test_gpa_calculation(conn) -> None:
    ac.add_grade(conn, score=90, credits=5)  # 90 → (90/20)*5 = 22.5
    ac.add_grade(conn, score=70, credits=5)  # 70 → (70/20)*5 = 17.5
    g, credits = ac.gpa(conn)
    assert credits == 10
    assert round(g, 2) == 4.0  # (22.5+17.5)/10 = 4.0


def test_review_fsrs_advances(conn) -> None:
    rid = rv.create_item(conn, "微积分定义")
    due0 = rv.due_items(conn)
    assert len(due0) == 1 and due0[0]["reps"] == 0
    result = rv.review(conn, rid, rv.RATING_REMEMBER)
    assert result["reps"] == 1
    assert result["interval_days"] > 0


def test_review_feedback_mapping(conn) -> None:
    rid = rv.create_item(conn, "单词")
    r_good = rv.review(conn, rid, rv.RATING_REMEMBER)
    _ = rv.review(conn, rid, rv.RATING_FUZZY)
    r_forgot = rv.review(conn, rid, rv.RATING_FORGOT)
    # 忘了会重置/降间隔，interval 应小于稳定后的 Good
    assert r_forgot["interval_days"] <= r_good["interval_days"]


def test_review_bad_feedback(conn) -> None:
    rid = rv.create_item(conn, "X")
    with pytest.raises(ValueError):
        rv.review(conn, rid, "bogus")


def test_review_bad_form(conn) -> None:
    with pytest.raises(ValueError):
        rv.create_item(conn, "X", form="bogus")
