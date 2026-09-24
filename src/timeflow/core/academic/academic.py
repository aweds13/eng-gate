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

from timeflow import clock
from timeflow.core import attach as attach_mod

GPA_4_0 = 4.0


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _today() -> str:
    return clock.today_iso()


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
    return [_assessment_row(r) for r in rows]


def _assessment_row(r: sqlite3.Row) -> dict[str, object]:
    keys = set(r.keys())
    return {
        "id": r["id"],
        "course_id": r["course_id"],
        "name": r["name"],
        "due_date": r["due_date"],
        "weight": r["weight"],
        "score": r["score"],
        "note": r["note"],
        # 附件 / 要求链接（SR-F5.3 / T-B4）：与任务**共用同一字段与打开规则**（core/attach.py）
        "attach": attach_mod.load_attach(r["attach"]) if "attach" in keys else [],
    }


def add_assessment_attachment(
    conn: sqlite3.Connection,
    assessment_id: str,
    target: str,
    title: str | None = None,
) -> dict[str, object]:
    """给考核项挂"要求链接/本地文件"（SR-F5.3 / OP-25 侧）：与任务附件同一套规则。

    考核项不存在 → KeyError（由 API 转 404）。
    """
    row = conn.execute(
        "SELECT attach FROM course_assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"考核项不存在: {assessment_id}")
    items = attach_mod.add_attachment_item(attach_mod.load_attach(row["attach"]), target, title)
    _write_attach(conn, assessment_id, items)
    return get_assessment(conn, assessment_id)


def remove_assessment_attachment(
    conn: sqlite3.Connection, assessment_id: str, index: int
) -> dict[str, object]:
    """按下标删一条（越界 ValueError / 考核项不存在 KeyError）。"""
    row = conn.execute(
        "SELECT attach FROM course_assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"考核项不存在: {assessment_id}")
    items = attach_mod.remove_attachment_item(attach_mod.load_attach(row["attach"]), index)
    _write_attach(conn, assessment_id, items)
    return get_assessment(conn, assessment_id)


def _write_attach(
    conn: sqlite3.Connection, assessment_id: str, items: list[dict[str, str | None]]
) -> None:
    conn.execute(
        "UPDATE course_assessments SET attach = ? WHERE id = ?",
        (attach_mod.dump_attach(items), assessment_id),
    )
    conn.commit()


def get_assessment(conn: sqlite3.Connection, assessment_id: str) -> dict[str, object]:
    row = conn.execute(
        "SELECT * FROM course_assessments WHERE id = ?", (assessment_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"考核项不存在: {assessment_id}")
    return _assessment_row(row)


def delete_assessment(conn: sqlite3.Connection, assessment_id: str) -> None:
    """删除考核项（OP-22 可逆）。不存在则视为幂等。"""
    conn.execute("DELETE FROM course_assessments WHERE id = ?", (assessment_id,))
    conn.commit()


def upcoming_assessments(
    conn: sqlite3.Connection, today: str | None = None, days: int = 14
) -> list[dict[str, object]]:
    """临期/逾期考核项（OP-25 课程提醒的数据源）。

    口径：
    - 只取**还没录成绩**的考核项（录了分就算完成，不再提醒）；
    - `days_until` = 截止日 - 今天：负=已逾期；0=今天；正=还有几天；
      **无截止日返回 None**（不猜时间）；
    - 按「逾期优先 → 无截止日最后」排序，供前端温和呈现（不强制、不告警）。
    """
    t = today or _today()
    t_date = date.fromisoformat(t)
    rows = conn.execute(
        "SELECT * FROM course_assessments WHERE score IS NULL ORDER BY due_date IS NULL, due_date"
    ).fetchall()
    course_names = {
        str(r["id"]): str(r["name"])
        for r in conn.execute("SELECT id, name FROM courses").fetchall()
    }
    out: list[dict[str, object]] = []
    for r in rows:
        due = r["due_date"]
        days_until: int | None = None
        if due:
            days_until = (date.fromisoformat(str(due)) - t_date).days
        if days_until is not None and days_until > days:
            continue  # 还早，不打扰
        item = _assessment_row(r)
        item["course_name"] = course_names.get(str(r["course_id"]))
        item["days_until"] = days_until
        out.append(item)
    return out


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


# GPA 制式：可按学校切换（4.0 制 / 5.0 制）。每种是「分数下限 → 绩点」的分段表。
GPA_SCALES: dict[str, list[tuple[float, float]]] = {
    "4.0": [
        (90, 4.0), (85, 3.7), (82, 3.3), (78, 3.0), (75, 2.8),
        (70, 2.3), (65, 1.8), (60, 1.0),
    ],
    "5.0": [
        (90, 5.0), (85, 4.5), (82, 4.0), (78, 3.5), (75, 3.2),
        (70, 2.7), (65, 2.2), (60, 1.5),
    ],
}

VALID_GPA_SCALES = tuple(GPA_SCALES.keys())


def _grade_point(score: float, gpa_scale: str = "4.0") -> float:
    """百分制分数 → 对应制式下的绩点（封顶为该制式满分，如 4.0/5.0）。"""
    bands = GPA_SCALES.get(gpa_scale, GPA_SCALES["4.0"])
    for threshold, point in bands:
        if score >= threshold:
            return point
    return 0.0


def gpa(conn: sqlite3.Connection, gpa_scale: str = "4.0") -> tuple[float, float]:
    """加权 GPA（可按 4.0/5.0 制切换）与总学分。"""
    total = 0.0
    credit_sum = 0.0
    for r in conn.execute("SELECT score, credits FROM grades").fetchall():
        score = float(r["score"])
        credits = float(r["credits"] or 0)
        credit_sum += credits
        total += _grade_point(score, gpa_scale) * credits
    if not credit_sum:
        return (0.0, 0.0)
    return (round(total / credit_sum, 2), credit_sum)


def weighted_average(conn: sqlite3.Connection) -> tuple[float, float]:
    """加权平均成绩 = Σ(单科学分 × 单科成绩) / Σ单科学分（百分制原始分，不换算绩点）。

    与 `gpa()` 的区别：GPA 先把分数映射成绩点再加权；这里**直接用原始百分制分数加权** ——
    两个口径并存，各自代表不同含义，互不替代。

    边界：
    - 学分为 0/负 的记录**不参与**加权（否则会拉低平均，属于脏数据而非真实权重）；
    - 无有效记录返回 (0.0, 0.0)，由界面显示空态。
    """
    total = 0.0
    credit_sum = 0.0
    for r in conn.execute("SELECT score, credits FROM grades").fetchall():
        credits = float(r["credits"] or 0)
        if credits <= 0:
            continue
        total += credits * float(r["score"])
        credit_sum += credits
    if not credit_sum:
        return (0.0, 0.0)
    return (round(total / credit_sum, 2), round(credit_sum, 2))


def delete_grade(conn: sqlite3.Connection, grade_id: str) -> None:
    """删除一条成绩（OP-23 可逆）：GPA 会随之重算。不存在则幂等。"""
    conn.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    conn.commit()


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
