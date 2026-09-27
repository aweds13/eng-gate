"""第 10 步·学业域补强：考核提醒（OP-25）+ 考核项/成绩增删（OP-22/OP-23）。

背景（此前缺口）：
- `upcoming_assessments` 不存在 → 考了试没人提醒；
- `assessments` / `grades` 只有「建」和「列」，**没有删** → 录错了只能留着。
口径：提醒只取**未录成绩**的考核项；`days_until` 负=逾期、0=今天、None=无截止日；
排序「逾期优先 → 无截止日最后」；不强制、不告警（温和）。
加权平均成绩：`Σ(单科学分 × 单科成绩) / Σ单科学分`（百分制原始分加权），
与 `gpa()`（绩点加权）并存、互不替代。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import academic as ac
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def _clear_grades(conn: sqlite3.Connection) -> None:
    """清空成绩，保证加权/GPA 断言不被同文件其它用例的数据污染。"""
    conn.execute("DELETE FROM grades")
    conn.commit()


# ---- 考核提醒 ----

def test_upcoming_orders_overdue_first(conn: sqlite3.Connection) -> None:
    today = date.today()
    cid = ac.create_course(conn, "高数")
    ac.add_assessment(
        conn, cid, "期中考试", due_date=(today + timedelta(days=3)).isoformat(), weight=0.3
    )
    ac.add_assessment(
        conn, cid, "迟交的作业", due_date=(today - timedelta(days=2)).isoformat()
    )
    ac.add_assessment(conn, cid, "没有截止日的论文")

    rows = ac.upcoming_assessments(conn, days=14)
    assert [r["name"] for r in rows] == ["迟交的作业", "期中考试", "没有截止日的论文"]
    assert rows[0]["days_until"] == -2
    assert rows[1]["days_until"] == 3
    assert rows[2]["days_until"] is None
    assert rows[0]["course_name"] == "高数"


def test_upcoming_skips_far_future_and_scored(conn: sqlite3.Connection) -> None:
    today = date.today()
    cid = ac.create_course(conn, "线代")
    ac.add_assessment(conn, cid, "很远的考试", due_date=(today + timedelta(days=60)).isoformat())
    scored = ac.add_assessment(
        conn, cid, "已出分的作业", due_date=(today + timedelta(days=1)).isoformat(), score=95
    )
    assert scored

    rows = ac.upcoming_assessments(conn, days=14)
    assert rows == []  # 远的窗口外、已录成绩的不再提醒


def test_upcoming_window_boundary(conn: sqlite3.Connection) -> None:
    today = date.today()
    cid = ac.create_course(conn, "英语")
    ac.add_assessment(conn, cid, "刚好14天", due_date=(today + timedelta(days=14)).isoformat())
    ac.add_assessment(conn, cid, "第15天", due_date=(today + timedelta(days=15)).isoformat())

    names = [r["name"] for r in ac.upcoming_assessments(conn, days=14)]
    assert names == ["刚好14天"]


def test_upcoming_empty_without_courses(conn: sqlite3.Connection) -> None:
    assert ac.upcoming_assessments(conn) == []


# ---- 增删 ----

def test_delete_assessment(conn: sqlite3.Connection) -> None:
    cid = ac.create_course(conn, "物理")
    aid = ac.add_assessment(conn, cid, "小测", due_date=date.today().isoformat())
    assert len(ac.list_assessments(conn)) == 1

    ac.delete_assessment(conn, aid)
    assert ac.list_assessments(conn) == []
    ac.delete_assessment(conn, aid)  # 幂等


def test_delete_grade_recomputes_gpa(conn: sqlite3.Connection) -> None:
    g1 = ac.add_grade(conn, score=92, credits=3)
    ac.add_grade(conn, score=60, credits=1)
    before = ac.gpa(conn)[0]
    assert before > 3.0

    ac.delete_grade(conn, g1)
    after = ac.gpa(conn)[0]
    assert after == 1.0  # 只剩 60 分那条（1.0 绩点）
    assert ac.gpa(conn)[1] == 1.0  # 学分同步减少
    ac.delete_grade(conn, g1)  # 幂等


# ---- API ----

def test_api_upcoming_and_delete_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "a.db")))
    cid = client.post("/api/courses", json={"name": "高数", "credits": 4}).json()["id"]
    aid = client.post(
        "/api/assessments",
        json={"course_id": cid, "name": "期中", "due_date": "2026-09-20", "weight": 0.3},
    ).json()["id"]

    rows = client.get("/api/assessments/upcoming?days=30").json()
    assert [r["name"] for r in rows] == ["期中"]
    assert rows[0]["course_name"] == "高数"

    assert client.delete(f"/api/assessments/{aid}").status_code == 200
    assert client.get("/api/assessments/upcoming?days=30").json() == []


def test_api_upcoming_days_bounds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    assert client.get("/api/assessments/upcoming?days=-1").status_code == 400
    assert client.get("/api/assessments/upcoming?days=366").status_code == 400
    assert client.get("/api/assessments/upcoming?days=0").status_code == 200


def test_api_delete_grade(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "c.db")))
    gid = client.post("/api/grades", json={"score": 90, "credits": 2}).json()["id"]
    assert client.get("/api/gpa").json()["gpa"] == 4.0

    assert client.delete(f"/api/grades/{gid}").status_code == 200
    assert client.get("/api/gpa").json()["gpa"] == 0.0


# ---- 加权平均成绩（Σ学分×成绩 / Σ学分）----

def test_weighted_average_formula(conn: sqlite3.Connection) -> None:
    """(3×92 + 2×78 + 4×85) / (3+2+4) = 772/9 = 85.78 —— 与手算一致。"""
    _clear_grades(conn)
    ac.add_grade(conn, score=92, credits=3)
    ac.add_grade(conn, score=78, credits=2)
    ac.add_grade(conn, score=85, credits=4)

    avg, credits = ac.weighted_average(conn)
    assert avg == 85.78
    assert credits == 9.0


def test_weighted_average_differs_from_gpa(conn: sqlite3.Connection) -> None:
    """两个口径必须并存且不同：GPA 用绩点加权，加权平均用原始分加权。"""
    _clear_grades(conn)
    ac.add_grade(conn, score=95, credits=1)  # 绩点 4.0
    ac.add_grade(conn, score=61, credits=1)  # 绩点 1.0

    assert ac.gpa(conn, "4.0")[0] == 2.5           # (4.0+1.0)/2
    assert ac.weighted_average(conn)[0] == 78.0    # (95+61)/2


def test_weighted_average_ignores_zero_credits(conn: sqlite3.Connection) -> None:
    """学分为 0 的记录不参与加权（否则会凭空拉低平均）。"""
    _clear_grades(conn)
    ac.add_grade(conn, score=90, credits=2)
    ac.add_grade(conn, score=10, credits=0)

    assert ac.weighted_average(conn) == (90.0, 2.0)


def test_weighted_average_empty(conn: sqlite3.Connection) -> None:
    _clear_grades(conn)
    assert ac.weighted_average(conn) == (0.0, 0.0)


def test_weighted_average_updates_after_delete(conn: sqlite3.Connection) -> None:
    _clear_grades(conn)
    g1 = ac.add_grade(conn, score=100, credits=1)
    ac.add_grade(conn, score=60, credits=1)
    assert ac.weighted_average(conn)[0] == 80.0

    ac.delete_grade(conn, g1)
    assert ac.weighted_average(conn)[0] == 60.0


def test_api_gpa_includes_weighted_average(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "w.db")))
    client.post("/api/grades", json={"score": 92, "credits": 3})
    client.post("/api/grades", json={"score": 78, "credits": 2})

    body = client.get("/api/gpa").json()
    assert body["weighted_average"] == 86.4  # (3×92 + 2×78)/5
    assert body["weighted_credits"] == 5.0
    assert body["gpa"] == 3.6  # (4.0×3 + 3.0×2)/5 —— 92≥90 记 4.0，78≥78 记 3.0
    assert body["scale"] == "4.0"

    five = client.get("/api/gpa?scale=5.0").json()
    assert five["scale"] == "5.0"
    assert five["weighted_average"] == 86.4  # 加权平均成绩与制式无关
    assert client.get("/api/gpa?scale=9.9").status_code == 400


# ---- 录成绩绑课程（T-G151）：只接已有的 course_id 列，GPA 算法不读它 ----

def test_grade_course_binding_does_not_change_gpa(conn: sqlite3.Connection) -> None:
    """绑课与不绑课，GPA / 加权平均逐字相同 —— 界面只是把已有列接上。"""
    _clear_grades(conn)
    cid = ac.create_course(conn, "高数")
    g_unbound = ac.add_grade(conn, score=92, credits=3)
    before = (ac.gpa(conn, "4.0"), ac.weighted_average(conn))
    ac.delete_grade(conn, g_unbound)

    g_bound = ac.add_grade(conn, score=92, credits=3, course_id=cid)
    after = (ac.gpa(conn, "4.0"), ac.weighted_average(conn))
    assert after == before, "绑课程前后 GPA / 加权平均必须逐字相同"
    row = next(r for r in ac.all_grade_rows(conn) if r["id"] == g_bound)
    assert row["course_id"] == cid, "课程要落在 course_id 列上（明细才显示得出课程名）"


def test_api_grade_with_course_id_keeps_gpa(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """API 侧同上：带 course_id 的 POST /api/grades，GPA 不变、明细带回 course_id。"""
    client = TestClient(create_app(str(tmp_path / "g.db")))
    gid = client.post("/api/grades", json={"score": 92, "credits": 3}).json()["id"]
    gpa_before = client.get("/api/gpa").json()
    assert client.delete(f"/api/grades/{gid}").status_code == 200

    cid = client.post("/api/courses", json={"name": "高数", "credits": 4}).json()["id"]
    gid2 = client.post(
        "/api/grades", json={"score": 92, "credits": 3, "course_id": cid}
    ).json()["id"]
    assert client.get("/api/gpa").json() == gpa_before
    rows = client.get("/api/grades").json()
    assert next(r for r in rows if r["id"] == gid2)["course_id"] == cid
