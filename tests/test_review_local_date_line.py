"""D 批 · T-D12：复习卡的日期一律**本地日历**（修掉全项目唯一一处 UTC 落日期）。

**规格依据**（`docs/specification/behaviors.md`）：
> 一律本地时区、本地日期；日界 00:00。

**这个缺陷是怎么露出来的**：门禁在跨过午夜之后跑，`tests/test_review_line.py:186` 挂了 ——
`assert state["due_date"] == date.today().isoformat()` 拿到 `2026-09-21`，
而本地已经是 `2026-09-22`。原因不是那一天的特殊性，而是 `review.py` 里 `_now()` 返回 **UTC**：
东八区 0:00~8:00 期间 `datetime.now(timezone.utc).date()` 还是"昨天"，而同一个 `review()` 里
`reviewed_on` 用的却是本地 `date.today()` —— 一个函数里两套日历。前端早就修过同类问题
（changelog：「`todayISO()` 按本地时区拼串（不用 `toISOString()`，东八区晚上会差一天）」），
后端这处漏了。

**修法**：FSRS 的时刻照旧按 UTC 走（它算的是"哪个瞬间"），**落库/返回的日期一律换成本地日历** ——
`create_item` 的 `due_date`/`created_at`、`review()` 的 `next_due`、`_card_from_row` 把存下的日期
还原成本地零点再交给 FSRS。

覆盖：
- 建卡时"UTC 还是昨天、本地已是今天" → 存的仍是**本地今天**（把 `_now()` 钉死，与钟点无关）；
- `review()` 的 `next_due` 取 FSRS 到期时刻的**本地**日期（用假 scheduler 把时刻钉在 UTC 深夜）；
- **往返不变式**：存进去的日期，从 `_card_from_row` 读回来还是同一天（任何时区都成立）。
"""

from __future__ import annotations

import importlib
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from timeflow.core import facts as facts_mod
from timeflow.core import review as rv
from timeflow.storage import db as db_mod

# 私有助手（`_now` / `_scheduler` / `_card_from_row`）在**子模块**里；包 `__init__` 把
# 同名的 `review`(函数) 摆在了外面，所以不能用 `from ... import review` 取模块对象。
rv_mod = importlib.import_module("timeflow.core.review.review")


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "review_local_date.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def test_create_item_stores_local_calendar_date(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """把 `_now()` 钉在"UTC 还是昨天、本地已经是今天"的时刻：**存的仍是本地今天**。

    老代码（`_now().date()`）在这里会存成昨天 —— 所以这条测试与"跑测试时本机几点"无关。
    """
    yesterday_utc = datetime.combine(
        date.today() - timedelta(days=1), time(23, 0), tzinfo=timezone.utc
    )
    monkeypatch.setattr(rv_mod, "_now", lambda: yesterday_utc)

    rid = rv.create_item(conn, "跨午夜建的卡")
    row = conn.execute(
        "SELECT due_date, created_at FROM review_items WHERE id = ?", (rid,)
    ).fetchone()
    today = date.today().isoformat()
    assert row["due_date"] == today
    assert row["created_at"] == today


def test_review_next_due_uses_local_calendar_date(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`review()` 落库/返回的下次到期日 = FSRS 到期**时刻**的本地日期（不是它的 UTC 日期）。"""
    instant = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)  # UTC 还在 1/1，本地可能已是 1/2

    class _FakeScheduler:
        def review_card(self, card, rating, now):  # type: ignore[no-untyped-def]
            return SimpleNamespace(due=instant, stability=1.0, difficulty=5.0), None

    monkeypatch.setattr(rv_mod, "_scheduler", lambda: _FakeScheduler())
    rid = rv.create_item(conn, "跨午夜复习")
    out = rv.review(conn, rid, rv.RATING_REMEMBER)

    expected = instant.astimezone().date().isoformat()
    assert out["due_date"] == expected
    row = conn.execute("SELECT due_date FROM review_items WHERE id = ?", (rid,)).fetchone()
    assert row["due_date"] == expected
    fact = facts_mod.query(conn, kind="review.completed")[-1]
    assert fact["extra"]["next_due"] == expected  # 事实里那个"下次到期"与卡片一致


def test_card_round_trip_keeps_the_same_day(conn) -> None:  # type: ignore[no-untyped-def]
    """**往返不变式**：存进去的日期，读回 FSRS 的卡上还是同一天（任何时区都成立）。

    这一条钉的是 `_card_from_row`：日期若被当成 UTC 零点解释，东八区读回来就会差一天。
    """
    rid = rv.create_item(conn, "往返")
    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (rid,)).fetchone()
    card = rv_mod._card_from_row(row)
    assert card.due.astimezone().date().isoformat() == row["due_date"]
    assert card.due == datetime.combine(date.fromisoformat(row["due_date"]), time.min).astimezone(
        timezone.utc
    )
