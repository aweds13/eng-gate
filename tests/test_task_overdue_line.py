"""F 批 · T-F7：修「派生逾期 vs 字段状态」不一致（顺手查出来的缺陷）。

**问题**（2026-09-21 查「悬赏」时顺手查出来的）：
- 只有"**新建时截止日已过**"才会把 `逾期` 写进 `tasks.status`；
- 之后日期走过截止日 → `overdue_tasks()` 靠**派生**把它列进逾期栏、卡片标红，
  但字段值还是「未开始」→ 详情面板一边写「状态 未开始」、一边出现在逾期栏里，
  **同一件事两种说法**。

**修法（本卡决定：走派生，不写回状态）**：
- `tm.overdue_days(task, today)` 成为**唯一**算逾期天数的地方（账本也改用它）；
- 通过 `TaskOut.overdue_days` 给界面，界面照原样显示存储状态 + 单独标「已逾期 N 天」；
- 为什么不写回 `status`：逾期本来就是派生的（`overdue_tasks`、以及 T-F2 的"完成 N 天后进档案"
  都是派生），再搞一套"到点改状态"的写入 = 两套真相 + 要一个定时器（本项目明确避免定时任务）。

覆盖：
- 天数口径：没截止日 / 今天到期 / 未来 → 0；昨天 → 1；完成 / 搁置（取消·待定）/ 归档 / 已删 → 0；
- 「新建时截止日已过」与「后来才过期」两条路**算出来的天数一样**（不再分两套口径）；
- 账本 `debt_items` 与领域层同源（顺手修掉这里自己减日期的那份重复算法）；
- API：`GET /api/tasks` 带 `overdue_days`；
- 未完成但无截止日的 My Day 老任务：列在逾期栏、但天数算不出来 → **不进 `debt_items`**
  （计数与明细的口径不一致已登记 T-F8，不在本卡里偷偷定口径）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "overdue.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "overdue_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- 天数口径


def test_overdue_days_counts_only_past_due_unfinished(conn) -> None:  # type: ignore[no-untyped-def]
    """0 = 没逾期：没截止日 / 今天到期 / 还没到 → 0；过期 N 天 → N。"""
    today = date.today().isoformat()
    none_due = tm.create_task(conn, "没截止日")
    today_due = tm.create_task(conn, "今天到期", due_date=today)
    future = tm.create_task(conn, "还早", due_date=(date.today() + timedelta(days=5)).isoformat())
    late = tm.create_task(conn, "晚了三天", due_date=_days_ago(3))

    assert tm.overdue_days(none_due) == 0
    assert tm.overdue_days(today_due) == 0
    assert tm.overdue_days(future) == 0
    assert tm.overdue_days(late) == 3


def test_overdue_days_is_zero_for_closed_and_parked(conn) -> None:  # type: ignore[no-untyped-def]
    """逾期只对"还在手上的事"有意义：完成 / 搁置（取消·待定）/ 归档 / 已删 → 0。"""
    done = tm.create_task(conn, "完成的", due_date=_days_ago(9))
    tm.complete_task(conn, done.id)
    assert tm.overdue_days(tm.get_task(conn, done.id)) == 0

    cancelled = tm.create_task(conn, "取消的", due_date=_days_ago(9))
    tm.cancel_task(conn, cancelled.id)
    assert tm.overdue_days(tm.get_task(conn, cancelled.id)) == 0

    parked = tm.create_task(conn, "待定的", due_date=_days_ago(9))
    tm.park_task(conn, parked.id)
    assert tm.overdue_days(tm.get_task(conn, parked.id)) == 0

    archived = tm.create_task(conn, "归档的", due_date=_days_ago(9))
    tm.archive_task(conn, archived.id)
    assert tm.overdue_days(tm.get_task(conn, archived.id)) == 0

    gone = tm.create_task(conn, "删掉的", due_date=_days_ago(9))
    tm.delete_task(conn, gone.id)
    assert tm.overdue_days(tm.get_task(conn, gone.id)) == 0


def test_stored_and_derived_overdue_agree(conn) -> None:  # type: ignore[no-untyped-def]
    """两条路（新建时已过期 / 后来才过期）算出的天数**一样** —— 这是修这条缺陷的核心断言。

    以前前者把「逾期」写进字段、后者只在界面上派生，于是同一个任务在两种情形下说法不同。
    """
    born_late = tm.create_task(conn, "建的时候就过期了", due_date=_days_ago(2))
    assert born_late.status == "逾期"  # 字段里存着（建库时的口径，保留不动）
    assert tm.overdue_days(born_late) == 2

    became_late = tm.create_task(conn, "后来才过期", due_date=_days_ago(2))
    tm.update_task(conn, became_late.id, status="未开始")  # 模拟"字段没写逾期"的老数据
    assert tm.get_task(conn, became_late.id).status == "未开始"
    assert tm.overdue_days(tm.get_task(conn, became_late.id)) == 2  # 派生说得一样清楚


# ---------------------------------------------------------------- 账本同源


def test_ledger_debt_items_use_the_same_helper(conn) -> None:  # type: ignore[no-untyped-def]
    """账本的债务明细与领域层**同一个算法**（顺手收掉这里自己减日期的那份重复实现）。"""
    tm.create_task(conn, "晚两天", due_date=_days_ago(2))
    tm.create_task(conn, "晚五天", due_date=_days_ago(5))

    summary = ledger.summary(conn)
    assert [(i.title, i.overdue_days) for i in summary.debt_items] == [("晚五天", 5), ("晚两天", 2)]
    assert summary.debt_count == 2


def test_undated_old_myday_task_is_listed_but_has_no_days(conn) -> None:  # type: ignore[no-untyped-def]
    """无截止日的 My Day 老任务：进逾期栏（AC-4），但**天数算不出来** → 不进债务明细。

    （"逾期栏里有 1 条、债务明细 0 条"这个计数/明细口径不一致已登记 **T-F8**，
    本卡不在这里偷偷替用户定口径。）
    """
    old = tm.create_task(conn, "昨天没做完的", is_myday=True)
    # 直接改 created_at：`update_task` 的字段白名单里没有它（那是"什么时候建的"，不该被编辑）
    conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", ("2020-01-01T09:00:00", old.id))
    conn.commit()
    assert [t.id for t in tm.overdue_tasks(conn)] == [old.id]

    assert tm.overdue_days(tm.get_task(conn, old.id)) == 0
    assert ledger.summary(conn).debt_items == []


# ---------------------------------------------------------------- API


def test_api_exposes_derived_overdue_days(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """界面拿到的 `overdue_days` 由后端算好 —— 前端不自己拿今天去减（免得又一套口径）。"""
    client = _client(tmp_path)
    late = client.post("/api/tasks", json={"title": "晚了四天", "due_date": _days_ago(4)}).json()
    assert late["overdue_days"] == 4

    on_time = client.post("/api/tasks", json={"title": "今天到期"}).json()
    assert on_time["overdue_days"] == 0

    # 搁置之后不再算逾期（待定/取消 = 搁置类，不计债）
    parked = client.post(f"/api/tasks/{late['id']}/park").json()
    assert parked["overdue_days"] == 0
    assert client.get("/api/summary").json()["debt_count"] == 0
