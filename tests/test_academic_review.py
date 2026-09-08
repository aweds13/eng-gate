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
    ac.add_grade(conn, score=90, credits=5)  # 90 → 4.0 * 5 = 20.0
    ac.add_grade(conn, score=70, credits=5)  # 70 → 2.3 * 5 = 11.5
    g, credits = ac.gpa(conn)
    assert credits == 10
    assert round(g, 2) == 3.15


def test_gpa_capped_at_4(conn) -> None:
    """GPA 最高 4.0（不因 95/100 分超上限）。"""
    ac.add_grade(conn, score=100, credits=5)
    ac.add_grade(conn, score=95, credits=5)
    g, _ = ac.gpa(conn)
    assert g == 4.0


def test_grade_point_bands(conn) -> None:
    from timeflow.core.academic.academic import _grade_point

    assert _grade_point(100, "4.0") == 4.0
    assert _grade_point(90, "4.0") == 4.0
    assert _grade_point(85, "4.0") == 3.7
    assert _grade_point(60, "4.0") == 1.0
    assert _grade_point(40, "4.0") == 0.0


def test_gpa_scale_switch(conn) -> None:
    """同一批分数，4.0 制与 5.0 制给出不同绩点（可切换）。"""
    ac.add_grade(conn, score=90, credits=5)
    g4, _ = ac.gpa(conn, "4.0")
    g5, _ = ac.gpa(conn, "5.0")
    assert g4 < g5  # 5.0 制对应绩点更高
    assert g4 == 4.0
    assert g5 == 5.0


def test_gpa_invalid_scale(conn) -> None:
    """非法制式回退到 4.0（bounds 用默认表），不报错。"""
    g, _ = ac.gpa(conn, "3.0")
    assert g == 0.0  # 无成绩


def test_valid_scales(conn) -> None:
    assert set(ac.VALID_GPA_SCALES) == {"4.0", "5.0"}
    assert ac.GPA_SCALES["4.0"][0] == (90, 4.0)
    assert ac.GPA_SCALES["5.0"][0] == (90, 5.0)


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
