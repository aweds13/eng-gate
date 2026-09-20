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
from typing import TYPE_CHECKING, Any

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

# 复习形式的界面标签（口径**只在后端定一处**：前端拿 meta 渲染，不自己写死一份中文，
# 免得两边词表分叉）。`form` 字段本身早在 v2 就建好了（SR-F6.7），这里补的是"能被选择/被读到"。
FORM_LABELS: dict[str, str] = {
    "cloze": "挖空",
    "qa": "问答卡",
    "exam": "真题",
}
SOURCE_LABELS: dict[str, str] = {
    "internal": "本应用内",
    "external": "外部 app（只做调度中枢）",
}


def meta() -> dict[str, object]:
    """复习的可选项（形式 / 执行源）与默认值 —— 供界面渲染，避免中文词表在前后端各写一份。"""
    return {
        "forms": [{"value": v, "label": FORM_LABELS[v]} for v in _FORMATS],
        "sources": [{"value": v, "label": SOURCE_LABELS[v]} for v in _SOURCES],
        "default_form": "qa",
        "default_source": "internal",
    }


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
    task_id: str | None = None,
) -> str:
    """新建复习卡（SR-F6.2：可由学习任务升级或手动建）。

    `task_id`（T-C5）：不为空时这张卡是"从某个任务升级来的"（弱关联，删任务不级联）。
    """
    title = title.strip()
    if not title:
        raise ValueError("复习卡标题不能为空")
    if form not in _FORMATS:
        raise ValueError(f"非法复习形式: {form}")
    if source not in _SOURCES:
        raise ValueError(f"非法执行源: {source}")
    if task_id is not None:
        task_id = _check_task(conn, task_id)
    rid = _uid()
    conn.execute(
        "INSERT INTO review_items (id, title, form, source, due_date, interval_days, "
        "ease, reps, lapses, state, ref_handle, task_id, created_at) "
        "VALUES (?,?,?,?,?,?,2.5,0,0,?,?,?,?)",
        (rid, title, form, source, _now().date().isoformat(), 0.0, STATE_DUE, ref_handle,
         task_id, _now().date().isoformat()),
    )
    conn.commit()
    return rid


def _check_task(conn: sqlite3.Connection, task_id: object) -> str | None:
    """校验"来源任务"存在（拒绝拼错的 id，不写进库）；空值 = 不是从任务升上来的。"""
    if task_id is None:
        return None
    text = str(task_id).strip()
    if not text:
        return None
    row = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (text,)).fetchone()
    if row is None:
        raise ValueError(f"任务不存在: {text}")
    return text


def items_for_task(conn: sqlite3.Connection, task_id: str) -> list[dict[str, object]]:
    """某任务升级出来的复习卡（按创建时间正序）——"这件事我做成卡了吗"。"""
    rows = conn.execute(
        "SELECT * FROM review_items WHERE task_id = ? ORDER BY created_at", (task_id,)
    ).fetchall()
    return [_item_dict(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: str) -> dict[str, object]:
    """单张复习卡（不存在 → KeyError，由 API 转 404）。"""
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    return _item_dict(row)


def update_item(conn: sqlite3.Connection, item_id: str, **fields: object) -> dict[str, object]:
    """改复习卡的**定义类字段**：标题 / 形式 / 执行源 / 引用句柄（T-C6 + T-C7）。

    只允许这四个（排期字段由 FSRS 管，不给人手改 —— 手改会与调度器的记忆状态打架）；
    非法值一律拒绝（不静默回落），空句柄 = 清除（存 NULL）。
    """
    allowed = {"title", "form", "source", "ref_handle"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    get_item(conn, item_id)  # 不存在 → KeyError
    if not updates:
        return get_item(conn, item_id)
    if "title" in updates:
        title = str(updates["title"] or "").strip()
        if not title:
            raise ValueError("复习卡标题不能为空")
        updates["title"] = title
    if "form" in updates and updates["form"] not in _FORMATS:
        raise ValueError(f"非法复习形式: {updates['form']}")
    if "source" in updates and updates["source"] not in _SOURCES:
        raise ValueError(f"非法执行源: {updates['source']}")
    if "ref_handle" in updates:
        raw = updates["ref_handle"]
        text = "" if raw is None else str(raw).strip()
        updates["ref_handle"] = text or None  # 空 = 清除（存 NULL，不写空串）
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE review_items SET {sets} WHERE id = ?", (*updates.values(), item_id))
    conn.commit()
    return get_item(conn, item_id)


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
    事实 extra 里带**复习前的卡片快照**，供「撤销本次反馈」精确回退（F6 OP-27 可逆）。
    """
    mapping = {"remember": 3, "fuzzy": 2, "forgot": 1}  # Good / Hard / Again
    if feedback not in mapping:
        raise ValueError(f"非法反馈: {feedback}")
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    from fsrs import Rating

    before = _item_snapshot(row)
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
        before=before,
    )
    return {
        "id": item_id,
        "due_date": new_card.due.date().isoformat(),
        "interval_days": round(float(new_card.stability or 2.5), 4),
        "reps": reps,
        "lapses": lapses,
        "state": STATE_DONE if reps >= 1 else STATE_DUE,
    }


def undo_review(
    conn: sqlite3.Connection, item_id: str, on_date: str | None = None
) -> dict[str, object]:
    """撤销**当日最近一次**复习反馈（F6 OP-27 可逆）。

    - 回退 FSRS 字段到复习前快照（存在 `review.completed` 事实的 extra.before 里）；
    - 追加 `review.undone` 反向事实，不删历史；账本按「完成 − 撤销」计数（同卡当日回到 0）。
    幂等：无当日完成事实、或该次已被撤销 → 直接返回当前卡片状态。
    """
    day = on_date or date.today().isoformat()
    rows = [
        row
        for row in _completed_facts_for(conn, item_id)
        if str(row["occurred_at"] or "")[:10] == day
    ]
    item = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    done_ids = {str(row["id"]) for row in rows}
    undone_ids = {
        str((row["extra"] or {}).get("fact_id"))
        for row in _undone_facts_for(conn, item_id)
        if str(row["occurred_at"] or "")[:10] == day
    }
    pending = [row for row in rows if str(row["id"]) not in undone_ids]
    if not pending:
        return _item_state(item)
    target = pending[-1]
    before = (target["extra"] or {}).get("before") or {}
    if before:
        conn.execute(
            "UPDATE review_items SET due_date=?, interval_days=?, ease=?, reps=?, lapses=?, "
            "state=? WHERE id=?",
            (
                str(before.get("due_date") or item["due_date"]),
                float(before.get("interval_days") or 0),
                float(before.get("ease") or 2.5),
                int(before.get("reps") or 0),
                int(before.get("lapses") or 0),
                str(before.get("state") or STATE_DUE),
                item_id,
            ),
        )
        conn.commit()
    item = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    state = _item_state(item)
    raw_reps = state["reps"]
    reps_value = float(raw_reps) if isinstance(raw_reps, (int, float)) else 0.0
    from timeflow.core import facts as facts_mod

    extra = {
        "entry_id": item_id,
        "fact_id": str(target["id"]),
        "kind": item_id,
        "value": state["reps"],
        "restored": before,
        "undone_on": day,
    }
    facts_mod.record(
        conn,
        kind="review.undone",
        subject_type="review_item",
        subject_id=item_id,
        value_num=reps_value,
        value_text=str(item["title"]),
        extra=extra,
        source="desktop",
    )
    facts_mod.publish("review.undone", {"item_id": item_id, "fact_id": str(target["id"]), **extra})
    assert done_ids  # 显式表达：仅在确认存在当日完成事实后才写撤销事实
    return state


def _item_snapshot(row: sqlite3.Row) -> dict[str, object]:
    """复习前的卡片快照（供撤销精确回退）。"""
    return {
        "due_date": row["due_date"],
        "interval_days": float(row["interval_days"] or 0),
        "ease": float(row["ease"] or 2.5),
        "reps": int(row["reps"] or 0),
        "lapses": int(row["lapses"] or 0),
        "state": row["state"] or STATE_DUE,
    }


def _item_state(row: sqlite3.Row) -> dict[str, object]:
    """当前卡片状态（供 API 返回）。"""
    state = _item_snapshot(row)
    return {
        "id": row["id"],
        "due_date": state["due_date"],
        "interval_days": state["interval_days"],
        "reps": state["reps"],
        "lapses": state["lapses"],
        "state": state["state"],
    }


def _completed_facts_for(conn: sqlite3.Connection, item_id: str) -> list[dict[str, Any]]:
    from timeflow.core import facts as facts_mod

    return facts_mod.query(
        conn, kind="review.completed", subject_type="review_item", subject_id=item_id
    )


def _undone_facts_for(conn: sqlite3.Connection, item_id: str) -> list[dict[str, Any]]:
    from timeflow.core import facts as facts_mod

    return facts_mod.query(
        conn, kind="review.undone", subject_type="review_item", subject_id=item_id
    )


def _record_completed_fact(
    conn: sqlite3.Connection,
    item_id: str,
    title: str,
    feedback: str,
    reps: int,
    next_due: str,
    reviewed_on: str,
    before: dict[str, object] | None = None,
) -> bool:
    """发 `review.completed` 事实 + 广播事件；同一天同卡只记一次（SR-F6 边界：幂等）。

    复习完成 = 投入（维持）由解读层按事实计数；本函数只负责「如实留痕」。
    `extra.before` 存复习前快照，供 `undo_review` 精确回退。
    """
    from timeflow.core import facts as facts_mod

    # 当日已有「未被撤销」的完成事实 → 幂等跳过；已撤销的那次不算，可以重新复习入账
    completed = _completed_facts_for(conn, item_id)
    undone_ids = {
        str((row["extra"] or {}).get("fact_id")) for row in _undone_facts_for(conn, item_id)
    }
    for row in completed:
        if str(row["occurred_at"] or "")[:10] != reviewed_on:
            continue
        if str(row["id"]) not in undone_ids:
            return False
    extra = {
        "title": title,
        "feedback": feedback,
        "reps": reps,
        "next_due": next_due,
        "reviewed_on": reviewed_on,
        "before": before or {},
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


def reviewed_today(conn: sqlite3.Connection, day: str) -> set[str]:
    """某日「有效复习」的卡片 id 集合 = 当日 `review.completed` − 当日已撤销（`review.undone`）。

    账本用它计 `review_count`（同一张卡当日只算一次）。
    """
    from timeflow.core import facts as facts_mod

    completed = facts_mod.query(
        conn, kind="review.completed", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    undone = facts_mod.query(
        conn, kind="review.undone", since=f"{day}T00:00:00", until=f"{day}T23:59:59"
    )
    undone_fact_ids = {
        str((row["extra"] or {}).get("fact_id")) for row in undone
    }
    return {
        str(row["subject_id"] or row["id"])
        for row in completed
        if str(row["id"]) not in undone_fact_ids
    }


def myday_entries(
    conn: sqlite3.Connection, today: str | None = None
) -> list[dict[str, object]]:
    """到期复习卡转成 My Day 条目（SR-F6.3 / OP-28：到期优先建议进 My Day，不强制）。

    返回结构带 `kind="review"`，供前端与任务条目混排时区分。
    """
    return [{"kind": "review", **item} for item in due_items(conn, today)]


def _item_dict(row: sqlite3.Row) -> dict[str, object]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "title": row["title"],
        "form": row["form"],
        "source": row["source"],
        "due_date": row["due_date"],
        "reps": row["reps"],
        "interval_days": row["interval_days"],
        "ref_handle": row["ref_handle"],
        # 来源任务（T-C5）：老库/老行没有这一列或为 NULL → None（**不猜**）
        "task_id": row["task_id"] if "task_id" in keys else None,
    }
