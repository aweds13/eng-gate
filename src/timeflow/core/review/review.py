"""复习间隔重复调度（SR-F6.1~F6.6）。对应 AC 复习。

用现成 Python FSRS 库（fsrs.Scheduler）做间隔重复调度。本模块封装：
- 自动复习卡字段：due_date / ease / state / ref_handle + 自维护 reps/lapses
- 反馈三态映射：记得=Good / 模糊=Hard / 忘了=Again（SR-F6.6 联动接口）
- 到期排序（按算法优先计入 My Day，SR-F6.3）
- 复习形式字段预留（SR-F6.5）、执行源标签（SR-F6.4）

注：fsrs 的 Card 有 stability/difficulty 无 reps/lapses；本模块用自维护的
reps/lapses 记录状态（收到反馈后自行递增，忘了时 lapses+1）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from fsrs import Card, Scheduler

# 复习状态（我们的持久化字段）
STATE_DUE = "due"
STATE_DONE = "done"

# 反馈三态 → fsrs Rating
RATING_REMEMBER = "remember"  # 记得 → Good
RATING_FUZZY = "fuzzy"        # 模糊 → Hard
RATING_FORGOT = "forgot"      # 忘了 → Again

_FORMATS = ("cloze", "qa", "exam")
_SOURCES = ("internal", "external")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scheduler() -> Scheduler:
    from fsrs import Scheduler

    return Scheduler()


def create_item(
    conn: sqlite3.Connection,
    title: str,
    form: str = "qa",
    source: str = "internal",
    ref_handle: str | None = None,
) -> str:
    """新建复习卡（SR-F6.2：可由学习任务升级或手动建）。"""
    title = title.strip()
    if not title:
        raise ValueError("复习卡标题不能为空")
    if form not in _FORMATS:
        raise ValueError(f"非法复习形式: {form}")
    if source not in _SOURCES:
        raise ValueError(f"非法执行源: {source}")
    rid = _uid()
    conn.execute(
        "INSERT INTO review_items (id, title, form, source, due_date, interval_days, "
        "ease, reps, lapses, state, ref_handle, created_at) "
        "VALUES (?,?,?,?,?,?,2.5,0,0,?,?,?)",
        (rid, title, form, source, _now().date().isoformat(), 0.0, STATE_DUE, ref_handle,
         _now().date().isoformat()),
    )
    conn.commit()
    return rid


def _card_from_row(row: sqlite3.Row) -> Card:
    """把 review_items 行转换为 fsrs.Card，用于喂给调度器。"""
    from fsrs import Card, State

    due = datetime.combine(
        date.fromisoformat(row["due_date"]), time.min, tzinfo=timezone.utc
    )
    # state: 已复习过=Review(3)，否则 Learning(1)
    state_int = 3 if int(row["reps"] or 0) > 0 else 1
    return Card(
        card_id=row["id"],
        due=due,
        stability=float(row["interval_days"] or 2.5),
        difficulty=float(row["ease"] or 2.5),
        state=State(state_int),
        step=0,
    )


def review(
    conn: sqlite3.Connection,
    item_id: str,
    feedback: str,
) -> dict[str, object]:
    """按反馈三态复习一张卡，FSRS 推进下一次到期（SR-F6.6）。

    反馈 → Rating：记得=Good / 模糊=Hard / 忘了=Again。
    返回新卡状态、下次到期日、以及给前端展示的 reps/lapses。
    """
    mapping = {"remember": 3, "fuzzy": 2, "forgot": 1}  # Good / Hard / Again
    if feedback not in mapping:
        raise ValueError(f"非法反馈: {feedback}")
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    from fsrs import Rating

    card = _card_from_row(row)
    sched = _scheduler()
    new_card, _log = sched.review_card(card, Rating(mapping[feedback]), _now())
    reps = int(row["reps"] or 0) + 1
    lapses = int(row["lapses"] or 0) + (1 if feedback == RATING_FORGOT else 0)
    conn.execute(
        "UPDATE review_items SET due_date=?, interval_days=?, ease=?, reps=?, lapses=?, "
        "state=? WHERE id=?",
        (
            new_card.due.date().isoformat(),
            round(float(new_card.stability or 2.5), 4),
            round(float(new_card.difficulty or 2.5), 4),
            reps,
            lapses,
            STATE_DONE if reps >= 1 else STATE_DUE,
            item_id,
        ),
    )
    conn.commit()
    # 复习完成 = 投入（维持，SR-F6 R6 / 约定「复习轴」）：发事实，账本只读事实层
    reviewed_on = date.today().isoformat()
    _record_completed_fact(
        conn, item_id=item_id, title=str(row["title"]), feedback=feedback,
        reps=reps, next_due=new_card.due.date().isoformat(), reviewed_on=reviewed_on,
    )
    return {
        "id": item_id,
        "due_date": new_card.due.date().isoformat(),
        "interval_days": round(float(new_card.stability or 2.5), 4),
        "reps": reps,
        "lapses": lapses,
        "state": STATE_DONE if reps >= 1 else STATE_DUE,
    }


def _record_completed_fact(
    conn: sqlite3.Connection,
    item_id: str,
    title: str,
    feedback: str,
    reps: int,
    next_due: str,
    reviewed_on: str,
) -> bool:
    """发 `review.completed` 事实 + 广播事件；同一天同卡只记一次（SR-F6 边界：幂等）。

    复习完成 = 投入（维持）由解读层按事实计数；本函数只负责「如实留痕」。
    """
    from timeflow.core import facts as facts_mod

    already = conn.execute(
        "SELECT 1 FROM facts WHERE kind = 'review.completed' AND subject_id = ? "
        "AND substr(occurred_at, 1, 10) = ? LIMIT 1",
        (item_id, reviewed_on),
    ).fetchone()
    if already is not None:
        return False
    extra = {
        "title": title,
        "feedback": feedback,
        "reps": reps,
        "next_due": next_due,
        "reviewed_on": reviewed_on,
    }
    facts_mod.record(
        conn,
        kind="review.completed",
        subject_type="review_item",
        subject_id=item_id,
        value_num=0.0,  # 复习完成不折算时间（约定：不折算精确时间）
        value_text=title,
        extra=extra,
        occurred_at=f"{reviewed_on}T{datetime.now().strftime('%H:%M:%S')}",
        source="desktop",
    )
    facts_mod.publish(
        "review.completed",
        {"item_id": item_id, "title": title, "feedback": feedback, "reviewed_on": reviewed_on},
    )
    return True


def due_items(
    conn: sqlite3.Connection, today: str | None = None
) -> list[dict[str, object]]:
    """到期复习卡（SR-F6.3）：due_date <= 今天，按算法（重要度+最久未复习）排序。"""
    t = today or date.today().isoformat()
    rows = conn.execute(
        "SELECT * FROM review_items WHERE due_date IS NOT NULL AND due_date <= ? "
        "ORDER BY reps ASC, due_date ASC",
        (t,),
    ).fetchall()
    return [_item_dict(r) for r in rows]


def myday_entries(
    conn: sqlite3.Connection, today: str | None = None
) -> list[dict[str, object]]:
    """到期复习卡转成 My Day 条目（SR-F6.3 / OP-28：到期优先建议进 My Day，不强制）。

    返回结构带 `kind="review"`，供前端与任务条目混排时区分。
    """
    return [{"kind": "review", **item} for item in due_items(conn, today)]


def _item_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "form": row["form"],
        "source": row["source"],
        "due_date": row["due_date"],
        "reps": row["reps"],
        "interval_days": row["interval_days"],
        "ref_handle": row["ref_handle"],
    }
