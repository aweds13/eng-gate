"""学业追踪领域逻辑（SR-F5.1~F5.4）。对应 AC 学业。

GPA/学分手动录入；课程档案（学分/考核方式/任课）；学校任务同构合流进 My Day
（多带课程标签+硬约束元数据）。提醒只负责"别忘"，不强制。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

GPA_4_0 = 4.0


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _today() -> str:
    return date.today().isoformat()


# ---- 课程档案（SR-F5.2）----
def create_course(
    conn: sqlite3.Connection,
    name: str,
    credits: float | None = None,
    teacher: str | None = None,
    note: str | None = None,
) -> str:
    name = name.strip()
    if not name:
        raise ValueError("课程名不能为空")
    cid = _uid()
    conn.execute(
        "INSERT INTO courses (id, name, credits, teacher, note, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (cid, name, credits, teacher, note, _today()),
    )
    conn.commit()
    return cid


def list_courses(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute("SELECT * FROM courses ORDER BY name").fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "credits": r["credits"],
            "teacher": r["teacher"],
            "note": r["note"],
        }
        for r in rows
    ]


# ---- 考核项（SR-F5.3）----
def add_assessment(
    conn: sqlite3.Connection,
    course_id: str,
    name: str,
    due_date: str | None = None,
    weight: float | None = None,
    score: float | None = None,
    note: str | None = None,
) -> str:
    aid = _uid()
    conn.execute(
        "INSERT INTO course_assessments (id, course_id, name, due_date, weight, score, note, "
        "created_at) VALUES (?,?,?,?,?,?,?,?)",
        (aid, course_id, name, due_date, weight, score, note, _today()),
    )
    conn.commit()
    return aid


def list_assessments(
    conn: sqlite3.Connection, course_id: str | None = None
) -> list[dict[str, object]]:
    if course_id:
        rows = conn.execute(
            "SELECT * FROM course_assessments WHERE course_id = ? ORDER BY due_date", (course_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM course_assessments ORDER BY due_date").fetchall()
    return [
        {
            "id": r["id"],
            "course_id": r["course_id"],
            "name": r["name"],
            "due_date": r["due_date"],
            "weight": r["weight"],
            "score": r["score"],
            "note": r["note"],
        }
        for r in rows
    ]


# ---- GPA（SR-F5.1）----
def add_grade(
    conn: sqlite3.Connection,
    score: float,
    credits: float,
    course_id: str | None = None,
    term: str | None = None,
) -> str:
    gid = _uid()
    conn.execute(
        "INSERT INTO grades (id, course_id, term, score, credits, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (gid, course_id, term, score, credits, _today()),
    )
    conn.commit()
    return gid


def _grade_point(score: float) -> float:
    """百分制分数 → 4.0 制绩点（中国高校常用分段法，封顶 4.0）。

    90+ → 4.0；85+ → 3.7；82+ → 3.3；78+ → 3.0；75+ → 2.8；
    70+ → 2.3；65+ → 1.8；60+ → 1.0；<60 → 0。
    """
    if score >= 90:
        return 4.0
    if score >= 85:
        return 3.7
    if score >= 82:
        return 3.3
    if score >= 78:
        return 3.0
    if score >= 75:
        return 2.8
    if score >= 70:
        return 2.3
    if score >= 65:
        return 1.8
    if score >= 60:
        return 1.0
    return 0.0


def gpa(conn: sqlite3.Connection) -> tuple[float, float]:
    """加权 GPA（4.0 制，封顶 4.0）与总学分。"""
    total = 0.0
    credit_sum = 0.0
    for r in conn.execute("SELECT score, credits FROM grades").fetchall():
        score = float(r["score"])
        credits = float(r["credits"] or 0)
        credit_sum += credits
        total += _grade_point(score) * credits
    if not credit_sum:
        return (0.0, 0.0)
    return (round(total / credit_sum, 2), credit_sum)


def all_grade_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute("SELECT * FROM grades ORDER BY created_at").fetchall()
    return [
        {
            "id": r["id"],
            "course_id": r["course_id"],
            "term": r["term"],
            "score": r["score"],
            "credits": r["credits"],
        }
        for r in rows
    ]
