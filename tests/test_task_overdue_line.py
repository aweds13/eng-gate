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
- **T-F8（2026-09-21 用户定案 A）**：未完成、无截止日的 My Day 老任务**算一笔债务**，
  天数**从创建日算起** —— 于是"列进逾期栏的"就一定能算出天数，
  `debt_count == len(debt_items)` 这个不变式成立（以前计数含它、明细跳过它）。
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


def _backdate(conn, task_id: str, stamp: str) -> None:  # type: ignore[no-untyped-def]
    """直接改 `created_at`：`update_task` 的字段白名单里没有它（"什么时候建的"不该被编辑）。"""
    conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (stamp, task_id))
    conn.commit()


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


def test_undated_old_myday_debt_counts_from_created_at(conn) -> None:  # type: ignore[no-untyped-def]
    """无截止日的 My Day 老账**算一笔债务**，天数**从创建日算起**（T-F8 定案 A）。

    它进逾期栏的原因本来就是"昨天没做完"（AC-4），`created_at` 是它身上唯一可用的日期；
    以前这里硬返回 0 → 逾期栏里 1 条、债务明细 0 条（T-F8 登记的那个不一致）。
    """
    old = tm.create_task(conn, "昨天没做完的", is_myday=True)
    _backdate(conn, old.id, _days_ago(4) + "T09:00:00")

    assert [t.id for t in tm.overdue_tasks(conn)] == [old.id]
    assert tm.overdue_days(tm.get_task(conn, old.id)) == 4

    summary = ledger.summary(conn)
    assert [(i.title, i.due_date, i.overdue_days) for i in summary.debt_items] == [
        ("昨天没做完的", "", 4)
    ]
    assert summary.debt_count == len(summary.debt_items) == 1


def test_created_at_days_only_for_stale_myday(conn) -> None:  # type: ignore[no-untyped-def]
    """"从创建日算天数"只给"昨天该做没做"的老账：今天才进 My Day 的、根本不在 My Day 的都 → 0。

    否则每条老的无截止日任务都会挂着"逾期几百天"（那是把"建得早"当成了"欠得久"）。
    """
    fresh = tm.create_task(conn, "今天刚加进 My Day 的", is_myday=True)
    assert tm.overdue_days(fresh) == 0

    old_plain = tm.create_task(conn, "老、但不在 My Day 里")
    _backdate(conn, old_plain.id, "2020-01-01T09:00:00")
    assert tm.overdue_days(tm.get_task(conn, old_plain.id)) == 0
    assert tm.overdue_tasks(conn) == []
    assert ledger.summary(conn).debt_count == 0


def test_parked_stale_myday_stops_being_debt(conn) -> None:  # type: ignore[no-untyped-def]
    """老账挂成「待定」之后就不是债务了（T-F1 的"搁置不计债"对这类任务同样成立）。"""
    task = tm.create_task(conn, "挂着不做的", is_myday=True)
    _backdate(conn, task.id, "2020-01-01T09:00:00")
    assert tm.overdue_days(tm.get_task(conn, task.id)) > 0

    tm.park_task(conn, task.id)
    assert tm.overdue_days(tm.get_task(conn, task.id)) == 0
    assert tm.overdue_tasks(conn) == []


def test_overdue_days_positive_iff_listed(conn) -> None:  # type: ignore[no-untyped-def]
    """**T-F8 不变式**：`overdue_days > 0` ⟺ 在 `overdue_tasks()` 里；`debt_count` = 明细条数。

    混一批各式各样的任务（有/无截止日、今天/过期、My Day/不在、完成/搁置）一起验，
    免得只对着一种情形调好、换个组合又分叉。
    """
    today = date.today().isoformat()
    late = tm.create_task(conn, "有截止日晚三天", due_date=_days_ago(3))
    tm.create_task(conn, "有截止日还没到", due_date=(date.today() + timedelta(days=3)).isoformat())
    tm.create_task(conn, "有截止日就是今天", due_date=today)
    old_myday = tm.create_task(conn, "无截止日的 My Day 老账", is_myday=True)
    tm.create_task(conn, "无截止日、今天才进 My Day", is_myday=True)
    tm.create_task(conn, "无截止日、不在 My Day")
    done = tm.create_task(conn, "完成了的", due_date=_days_ago(3))
    tm.complete_task(conn, done.id)
    parked = tm.create_task(conn, "搁置了的", due_date=_days_ago(3))
    tm.park_task(conn, parked.id)
    _backdate(conn, old_myday.id, "2020-01-01T09:00:00")

    listed = {t.id for t in tm.overdue_tasks(conn)}
    positive = {t.id for t in tm.list_tasks(conn) if tm.overdue_days(t) > 0}
    assert positive == listed == {late.id, old_myday.id}

    summary = ledger.summary(conn)
    assert summary.debt_count == len(summary.debt_items) == 2
    assert [i.title for i in summary.debt_items] == ["无截止日的 My Day 老账", "有截止日晚三天"]


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
