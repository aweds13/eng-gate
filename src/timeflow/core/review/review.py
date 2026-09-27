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

from timeflow import clock, vocab

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping

    from fsrs import Card, Scheduler

# 复习状态（我们的持久化字段）
STATE_DUE = "due"
STATE_DONE = "done"

# 反馈三态 → fsrs Rating
RATING_REMEMBER = "remember"  # 记得 → Good
RATING_FUZZY = "fuzzy"        # 模糊 → Hard
RATING_FORGOT = "forgot"      # 忘了 → Again

# 三档反馈的**中文标签与顺序**只在后端一处：界面（三态按钮 + 「改判」）
# 从 `GET /api/review/meta` 的 `ratings` 拿，不再各写一份中文表。
RATINGS: tuple[str, ...] = (RATING_REMEMBER, RATING_FUZZY, RATING_FORGOT)
RATING_LABELS: dict[str, str] = {
    RATING_REMEMBER: "记得",
    RATING_FUZZY: "模糊",
    RATING_FORGOT: "忘了",
}

# 反馈三态 → fsrs.Rating 的数值（Good / Hard / Again）—— `rating_to_fsrs` 一处映射
_RATING_TO_FSRS: dict[str, int] = {RATING_REMEMBER: 3, RATING_FUZZY: 2, RATING_FORGOT: 1}

_SOURCES = ("internal", "external")

# 复习形式的**内置兜底**（SR-NF7 / G 批 · T-G1）：真正的词表在 `timeflow/vocab.py` 一处声明 ——
# 用户能在 config.toml 或设置页里加自己的形式（形式只是标签，不改调度、不改卡片长相），
# 所以这里不再是"唯一合法名单"，只是"没配置时的那三种"。
FORM_LABELS: dict[str, str] = dict(vocab.REVIEW_FORMS.builtin)

# 改复习卡时**允许动的字段**（T-C6/T-C7）：排期字段由 FSRS 管，不给人手改。
# 这份名单同时被 API 用来过滤请求体 —— 于是领域里那些"带默认值的参数名"不会被 body 撞上。
EDITABLE_FIELDS = frozenset({"title", "form", "source", "ref_handle"})

SOURCE_LABELS: dict[str, str] = {
    "internal": "本应用内",
    "external": "外部 app（只做调度中枢）",
}


# 建卡时的**默认形式**（T-G1）：问答卡最通用，所以没特别指定就用它。
# 用户若把它从词表里删掉 → 退回"词表第一项"（把想要的排最前就是默认；不猜、不崩）。
DEFAULT_FORM = "qa"


def forms(
    conn: sqlite3.Connection, defaults: Mapping[str, str] | None = None
) -> dict[str, str]:
    """**现在生效**的复习形式词表：本机改过 → config.toml → 内置（见 `vocab.get`）。"""
    return vocab.get(conn, vocab.REVIEW_FORMS, defaults)


def default_form(
    conn: sqlite3.Connection, defaults: Mapping[str, str] | None = None
) -> str:
    """默认形式：`qa` 还在词表里就用它，否则用词表第一项。"""
    current = forms(conn, defaults)
    return DEFAULT_FORM if DEFAULT_FORM in current else next(iter(current))


def forms_settings(
    conn: sqlite3.Connection, defaults: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """给设置页的形式词表描述（现在长什么样 + 能怎么改）。"""
    return vocab.describe(conn, vocab.REVIEW_FORMS, defaults)


def meta(
    conn: sqlite3.Connection, defaults: Mapping[str, str] | None = None
) -> dict[str, object]:
    """复习的可选项（形式 / 执行源）与默认值 —— 供界面渲染，避免中文词表在前后端各写一份。

    `defaults` = config.toml 里的文件级默认（由 API 层传进来，域层不读全局配置）。
    """
    current = forms(conn, defaults)
    return {
        "forms": [{"value": k, "label": v} for k, v in current.items()],
        "sources": [{"value": v, "label": SOURCE_LABELS[v]} for v in _SOURCES],
        # 三档反馈（记得/模糊/忘了）：界面用它渲染三态按钮与「改判」按钮（T-G13）
        "ratings": [{"value": k, "label": RATING_LABELS[k]} for k in RATINGS],
        "default_form": default_form(conn, defaults),
        "default_source": "internal",
    }


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return clock.now_utc()


def _local_date(moment: datetime) -> str:
    """把一个时刻落成**本地日历日期**（T-D12）。

    规格层写着「一律本地时区、本地日期；日界 00:00」（`specification/behaviors.md`），
    而本模块原来是全项目**唯一**用 UTC 落日期的地方（`_now().date()`）：东八区凌晨 0:00~8:00
    建的卡，到期日会存成"昨天" —— 同一个 `review()` 里 `reviewed_on` 用的却是本地
    `date.today()`（T-G62 起改走 `clock.today_iso()`），自相矛盾。**FSRS 的时刻按 UTC 走**
    （它算的是"哪个瞬间"），**落库的日期一律换成我的日历**。
    """
    return moment.astimezone().date().isoformat()


def _scheduler() -> Scheduler:
    from fsrs import Scheduler

    return Scheduler()


def create_item(
    conn: sqlite3.Connection,
    title: str,
    form: str | None = None,
    source: str = "internal",
    ref_handle: str | None = None,
    task_id: str | None = None,
    forms_defaults: Mapping[str, str] | None = None,
) -> str:
    """新建复习卡（SR-F6.2：可由学习任务升级或手动建）。

    `task_id`（T-C5）：不为空时这张卡是"从某个任务升级来的"（弱关联，删任务不级联）。
    `form`（G 批 · T-G1）：合法取值 = **现在生效的形式词表**（用户能自己加），
    不传则用 `default_form()`；不在词表里就拒绝（不静默换成默认形式）。
    """
    title = title.strip()
    if not title:
        raise ValueError("复习卡标题不能为空")
    current = forms(conn, forms_defaults)
    if form is None:
        form = default_form(conn, forms_defaults)
    if form not in current:
        raise ValueError(f"非法复习形式: {form}（现在能用的：{'/'.join(current)}）")
    if source not in _SOURCES:
        raise ValueError(f"非法执行源: {source}")
    if task_id is not None:
        task_id = _check_task(conn, task_id)
    rid = _uid()
    created_on = clock.today_iso()  # 本地日历日（T-D12：原来用 UTC 日期，见 `_local_date`）
    conn.execute(
        "INSERT INTO review_items (id, title, form, source, due_date, interval_days, "
        "ease, reps, lapses, state, ref_handle, task_id, created_at) "
        "VALUES (?,?,?,?,?,?,2.5,0,0,?,?,?,?)",
        (rid, title, form, source, created_on, 0.0, STATE_DUE, ref_handle,
         task_id, created_on),
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


def delete_item(conn: sqlite3.Connection, item_id: str) -> bool:
    """删除一张复习卡（硬删 · F6 OP-26「可逆：可删除」的落地）。

    ★ 与 `memo.delete_memo` 同形（**硬删 + 界面二次确认**，不做回收站/撤销）：
    - 只删 `review_items` 这一行，**不碰** `facts` —— 复习历史流水一个字节都不删；
    - `review_items.task_id` 是单向弱关联（无外键），删卡**不伤任务本体**；
    - 墓碑由 v17 的 DELETE 触发器自动落（`storage/db.py` 的 `SYNC_TOMBSTONE_KEYS` 已含
      `review_items`）→ **不手写** `sync_tombstones`，旧同步包复活不了它。

    幂等：删不存在的 id 不炸；返回**是否真删到了**（`cursor.rowcount > 0`）。
    """
    cur = conn.execute("DELETE FROM review_items WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount > 0


def update_item(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    forms_defaults: Mapping[str, str] | None = None,
    **fields: object,
) -> dict[str, object]:
    """改复习卡的**定义类字段**：标题 / 形式 / 执行源 / 引用句柄（T-C6 + T-C7）。

    只允许 `EDITABLE_FIELDS` 这四个（排期字段由 FSRS 管，不给人手改 —— 手改会与调度器的
    记忆状态打架）；非法值一律拒绝（不静默回落），空句柄 = 清除（存 NULL）。

    `forms_defaults` 是**关键字专用参数**（不放进 `**fields`）：API 层用
    `EDITABLE_FIELDS` 过滤请求体，所以 body 里不可能撞上这个名字。
    """
    updates = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    get_item(conn, item_id)  # 不存在 → KeyError
    if not updates:
        return get_item(conn, item_id)
    if "title" in updates:
        title = str(updates["title"] or "").strip()
        if not title:
            raise ValueError("复习卡标题不能为空")
        updates["title"] = title
    if "form" in updates:
        current = forms(conn, forms_defaults)
        if updates["form"] not in current:
            raise ValueError(
                f"非法复习形式: {updates['form']}（现在能用的：{'/'.join(current)}）"
            )
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
        date.fromisoformat(row["due_date"]), time.min
    ).astimezone(timezone.utc)  # 落库的是本地日历日（T-D12）→ 还原成本地零点再交给 FSRS
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
    mapping = _RATING_TO_FSRS
    if feedback not in mapping:
        raise ValueError(f"非法反馈: {feedback}（能用的：{'/'.join(RATINGS)}）")
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
    next_due = _local_date(new_card.due)  # 本地日历日（T-D12）
    conn.execute(
        "UPDATE review_items SET due_date=?, interval_days=?, ease=?, reps=?, lapses=?, "
        "state=? WHERE id=?",
        (
            next_due,
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
    reviewed_on = clock.today_iso()
    _record_completed_fact(
        conn, item_id=item_id, title=str(row["title"]), feedback=feedback,
        reps=reps, next_due=next_due, reviewed_on=reviewed_on,
        before=before,
    )
    return {
        "id": item_id,
        "due_date": next_due,
        "interval_days": round(float(new_card.stability or 2.5), 4),
        "reps": reps,
        "lapses": lapses,
        "state": STATE_DONE if reps >= 1 else STATE_DUE,
    }


def _pending_last(
    conn: sqlite3.Connection, item_id: str, day: str
) -> dict[str, Any] | None:
    """某卡**当日最近一次「还没被撤销」**的完成事实（没有则 None）。

    撤销（OP-27）与改判（T-G13）用**同一套判据**找"要动的那一次" ——
    分成两份实现就会有一天两边对不上（一个认为有、一个认为没有）。
    """
    undone_ids = {
        str((row["extra"] or {}).get("fact_id")) for row in _undone_facts_for(conn, item_id)
    }
    pending = [
        row
        for row in _completed_facts_for(conn, item_id)
        if str(row["occurred_at"] or "")[:10] == day and str(row["id"]) not in undone_ids
    ]
    return pending[-1] if pending else None


def undo_review(
    conn: sqlite3.Connection, item_id: str, on_date: str | None = None
) -> dict[str, object]:
    """撤销**当日最近一次**复习反馈（F6 OP-27 可逆）。

    - 回退 FSRS 字段到复习前快照（存在 `review.completed` 事实的 extra.before 里）；
    - 追加 `review.undone` 反向事实，不删历史；账本按「完成 − 撤销」计数（同卡当日回到 0）。
    幂等：无当日完成事实、或该次已被撤销 → 直接返回当前卡片状态。
    """
    day = on_date or clock.today_iso()
    item = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    target = _pending_last(conn, item_id, day)
    if target is None:
        return _item_state(item)
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
    assert target is not None  # 到这里一定有"要撤销的那一次"（没有的话上面已经返回了）
    return state


def regrade(
    conn: sqlite3.Connection, item_id: str, feedback: str, on_date: str | None = None
) -> dict[str, object]:
    """把**当日最近一次**复习反馈改成另一档（F6 OP-27 的延伸 · T-G13）。

    做法就是「**撤销这一次** + **按新档重来**」，两步都走**既有的**路径
    （`undo_review` → `review`）：

    - FSRS 从**同一个复习前快照**重新算 —— 于是"改判"与"当时就点另一档"是同一个结果，
      排期不会因为改判而漂移（自己再写一套重算逻辑，两边迟早对不上）；
    - 事实按老规矩留痕：原来那条 `review.completed` **不删**，追加 `review.undone` 指回它，
      再写一条新的 `review.completed` —— 流水上看得出"改过"，不是偷偷抹掉重写；
    - 投入**不会重复计**：账本按「当日有效完成事实（同一张卡只算一次）」计数（`reviewed_today`）；
    - 另记一条 `review.regraded`（从哪一档改到哪一档），便于事后核对。

    拒绝的情况（都是 400 带原话，不静默）：
    - 今天还没复习过这张卡 → "没有可以改判的反馈"；
    - 给的档和原来一样 → "不用改判"（界面上也不会给出同一个档的按钮）。
    """
    day = on_date or clock.today_iso()
    if feedback not in RATINGS:
        raise ValueError(f"非法反馈: {feedback}（能用的：{'/'.join(RATINGS)}）")
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"复习卡不存在: {item_id}")
    target = _pending_last(conn, item_id, day)
    if target is None:
        raise ValueError("今天还没有复习过这张卡，没有可以改判的反馈")
    old = str((target["extra"] or {}).get("feedback") or "")
    if old == feedback:
        raise ValueError(f"和刚才记的一样（{RATING_LABELS.get(feedback, feedback)}），不用改判")
    undo_review(conn, item_id, on_date=day)          # ① 退回复习前的卡片状态（留痕）
    state = review(conn, item_id, feedback)          # ② 按新档走**完全相同**的复习路径
    from timeflow.core import facts as facts_mod

    facts_mod.record(
        conn,
        kind="review.regraded",
        subject_type="review_item",
        subject_id=item_id,
        value_num=0.0,  # 改判不是又一次复习：不折算时间，也不进账目
        value_text=str(row["title"]),
        extra={
            "from": old,
            "to": feedback,
            "fact_id": str(target["id"]),
            "regraded_on": day,
            "next_due": state["due_date"],
        },
        source="desktop",
    )
    facts_mod.publish(
        "review.regraded", {"item_id": item_id, "from": old, "to": feedback, "regraded_on": day}
    )
    return {**state, "regraded_from": old, "regraded_to": feedback}


def reviewed_today_items(
    conn: sqlite3.Connection, day: str | None = None
) -> list[dict[str, object]]:
    """**今天复习过的卡**（带这次记的是哪一档）—— 界面上「改判」的入口靠它。

    只报事实：一张卡一条（当日最近一次"未被撤销"的那次），最近复习的排最前。
    卡被删掉了就不列（不留幽灵条目）。
    """
    from timeflow.core import facts as facts_mod

    d = day or clock.today_iso()
    completed = facts_mod.query(
        conn, kind="review.completed", since=f"{d}T00:00:00", until=f"{d}T23:59:59"
    )
    undone_ids = {
        str((row["extra"] or {}).get("fact_id"))
        for row in facts_mod.query(
            conn, kind="review.undone", since=f"{d}T00:00:00", until=f"{d}T23:59:59"
        )
    }
    latest: dict[str, dict[str, Any]] = {}
    for fact in completed:  # 查询按 occurred_at 正序 → 后写的覆盖先写的 = 最近一次
        if str(fact["id"]) in undone_ids:
            continue
        latest[str(fact["subject_id"] or "")] = fact
    out: list[dict[str, object]] = []
    for item_id, fact in latest.items():
        item = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            continue  # 卡已删：不列
        extra = fact["extra"] or {}
        got = str(extra.get("feedback") or "")
        keys = set(item.keys())
        out.append(
            {
                **_item_state(item),
                "title": item["title"],
                "form": item["form"],
                "source": item["source"],
                "task_id": item["task_id"] if "task_id" in keys else None,
                "feedback": got,
                "feedback_label": RATING_LABELS.get(got, ""),
                "reviewed_at": fact["occurred_at"],
                "fact_id": str(fact["id"]),
            }
        )
    out.sort(key=lambda i: str(i["reviewed_at"]), reverse=True)
    return out


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
        occurred_at=f"{reviewed_on}T{clock.now().strftime('%H:%M:%S')}",
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
    t = today or clock.today_iso()
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
