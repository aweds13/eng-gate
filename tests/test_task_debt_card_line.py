"""F 批 · T-F9：债务里建**父任务状态卡**，逾期的子孙**挂在卡下面**。

**口径（用户 2026-09-21 定，原话）**：
> 「可以在债务那里，建个父任务状态卡，然后挂？」

落地：
- 逾期的东西（任务/子任务/子步骤）不再是"一条条平铺的债务"，
  而是**归到"还在手上的那个父任务"**上：父任务一张卡，它逾期的子孙挂在 `steps` 下面
  —— 同一件事（大任务 + 它的某一步过期）在债务里只占**一张卡**；
- 卡的 `overdue_days` = 父任务自己的天数与挂着的步里**最狠的那个**（取最大，**不做折算**）；
- 卡的 `root` = 沿父链上溯到**最高一层还活着的祖先**（完成 / 搁置（取消·待定）/ 归档 / 已删
  的祖先不配当卡 —— "搁置不计债"这条不能被绕过）；整条链都被搁置时，卡就是逾期那一步自己；
- `debt_count` = **卡的张数**（不是逾期条目的条数），账本 / 洞察 / 周结算**共用** `tm.debt_count`。

覆盖：
- 2 层 / 3 层嵌套各挂一次（父卡只一张、子孙都在 `steps` 里、天数取最大）；
- 父任务自己没到点（没截止日）→ 卡的天数来自挂着的步；
- 已搁置/已归档/已完成的祖先不配当卡（停在它下面那一层）；
- 无关的逾期任务各自一张卡；
- **不变式**：`debt_count == len(debt_items)`，且与 `tm.debt_count` 一致；
- 洞察（`insights._cell`）与周结算（`feedback.weekly_summary`）与账本同一个数字（不三处各算一套）；
- **逾期栏不受影响**：`overdue_tasks()` 仍如实列出每一条逾期（债务归卡是"读数"，不是"隐藏"）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core import insights as ins
from timeflow.core import tasks as tm
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "debt.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "debt_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- 归卡


def test_overdue_step_hangs_on_parent_card(conn) -> None:  # type: ignore[no-untyped-def]
    """两步逾期挂在一张父卡下：**卡的张数是 1**（不是 3 条债务）。"""
    top = tm.create_task(conn, "高数作业", due_date=_ago(9))
    mid = tm.create_subtask(conn, top.id, "第 2 题", due_date=_ago(4))
    tm.create_subtask(conn, mid.id, "第 2 题的第 1 小问", due_date=_ago(2))

    cards = tm.debt_groups(conn)
    assert len(cards) == 1
    card = cards[0]
    assert card.root.id == top.id
    assert card.own_days == 9
    assert card.overdue_days == 9  # 取最大，不相加（不做折算）
    assert [(s.task.title, s.overdue_days) for s in card.steps] == [
        ("第 2 题", 4), ("第 2 题的第 1 小问", 2)
    ]
    assert tm.debt_count(conn) == 1


def test_card_days_come_from_steps_when_parent_is_not_late(conn) -> None:  # type: ignore[no-untyped-def]
    """父任务自己没到点（甚至没截止日）：卡照样立，天数来自挂着的步。"""
    top = tm.create_task(conn, "课程设计")  # 没有截止日
    tm.create_subtask(conn, top.id, "画流程图", due_date=_ago(5))

    card = tm.debt_groups(conn)[0]
    assert card.root.id == top.id
    assert card.own_days == 0
    assert card.overdue_days == 5
    assert [s.task.title for s in card.steps] == ["画流程图"]

    item = ledger.summary(conn).debt_items[0]
    assert (item.title, item.due_date, item.overdue_days, item.degree) == ("课程设计", "", 5, "中")


def test_unrelated_overdue_tasks_get_their_own_cards(conn) -> None:  # type: ignore[no-untyped-def]
    """没有父子关系的逾期任务各占一张卡（归卡不是"合并成一个总数"）。"""
    a = tm.create_task(conn, "甲", due_date=_ago(1))
    b = tm.create_task(conn, "乙", due_date=_ago(4))
    tm.create_subtask(conn, b.id, "乙的一步", due_date=_ago(2))

    cards = tm.debt_groups(conn)
    assert [(c.root.title, c.overdue_days, [s.task.title for s in c.steps]) for c in cards] == [
        ("乙", 4, ["乙的一步"]), ("甲", 1, [])
    ]
    assert a.id != b.id


def test_only_intermediate_step_overdue_also_hangs(conn) -> None:  # type: ignore[no-untyped-def]
    """中间层自己逾期、更深一层没到点：中间层挂在顶层卡下（挂了就是挂了，不挑层级）。"""
    top = tm.create_task(conn, "大任务", due_date=_ago(1))
    mid = tm.create_subtask(conn, top.id, "中间层", due_date=_ago(3))
    later = (date.today() + timedelta(days=3)).isoformat()
    tm.create_subtask(conn, mid.id, "更下一层", due_date=later)

    card = tm.debt_groups(conn)[0]
    assert card.root.id == top.id
    assert card.own_days == 1
    assert card.overdue_days == 3  # 中间层更晚
    assert [s.task.title for s in card.steps] == ["中间层"]


# ---------------------------------------------------------------- 谁配当卡


def test_parked_or_archived_ancestor_is_not_a_card(conn) -> None:  # type: ignore[no-untyped-def]
    """搁置（取消·待定）/ 归档 / 已完成的祖先**不配当卡** —— "搁置不计债"不能被绕过。

    项目已经取消，但那一步还欠着：这张卡就是**这一步自己**（它还在手上）。
    """
    for action in ("cancel", "park", "archive"):
        top = tm.create_task(conn, f"被{action}的大任务")
        step = tm.create_subtask(conn, top.id, "还欠着的一步", due_date=_ago(3))
        getattr(tm, f"{action}_task")(conn, top.id)
        cards = [c for c in tm.debt_groups(conn) if c.root.id == step.id]
        assert len(cards) == 1, action  # 卡是那一步自己
        assert cards[0].own_days == 3

    done_parent = tm.create_task(conn, "完成的大任务")
    done_step = tm.create_subtask(conn, done_parent.id, "已完成的步", due_date=_ago(3))
    tm.complete_task(conn, done_step.id)
    tm.complete_task(conn, done_parent.id)
    assert all(c.root.id not in (done_parent.id, done_step.id) for c in tm.debt_groups(conn))


def test_root_survives_deleted_parent(conn) -> None:  # type: ignore[no-untyped-def]
    """父任务被硬删（坏数据）时不炸：那一步自己当卡。"""
    top = tm.create_task(conn, "会被硬删的父")
    step = tm.create_subtask(conn, top.id, "孤儿子步骤", due_date=_ago(2))
    conn.execute("DELETE FROM tasks WHERE id = ?", (top.id,))
    conn.commit()

    cards = tm.debt_groups(conn)
    assert [(c.root.id, c.overdue_days) for c in cards] == [(step.id, 2)]


# ---------------------------------------------------------------- 三处同一个数字


def test_count_and_items_agree_and_shared_everywhere(conn) -> None:  # type: ignore[no-untyped-def]
    """**不变式**：`debt_count == len(debt_items) == tm.debt_count`，
    且洞察（`insights._cell`）与周结算（`feedback`）用的是**同一个**读数。

    以前这三处各自 `len(overdue_tasks())`；归卡之后如果还各算各的，
    就会出现"顶部摘要说 1 项、周结算说 3 项"这种打脸（T-F9 顺手收掉）。
    """
    top = tm.create_task(conn, "大任务", due_date=_ago(8))
    tm.create_subtask(conn, top.id, "第 1 步", due_date=_ago(5))
    tm.create_subtask(conn, top.id, "第 2 步", due_date=_ago(3))
    tm.create_task(conn, "另一件事", due_date=_ago(1))

    summary = ledger.summary(conn)
    assert summary.debt_count == len(summary.debt_items) == tm.debt_count(conn) == 2
    assert ins._cell(conn, date.today().isoformat()).debt_count == 2
    assert fb.self_check(conn, date.today().isoformat())["debt_count"] == 2


def test_overdue_list_still_shows_every_item(conn) -> None:  # type: ignore[no-untyped-def]
    """**逾期栏不受影响**：归卡只是"债务怎么读"，逾期栏仍如实列出每一条逾期的东西。

    逾期栏是干活的地方（每条能「推到明天 / 取消」），债务是读数的地方（"这件事欠了多久"）。
    """
    top = tm.create_task(conn, "大任务", due_date=_ago(6))
    step = tm.create_subtask(conn, top.id, "第 1 步", due_date=_ago(2))

    assert {t.id for t in tm.overdue_tasks(conn)} == {top.id, step.id}
    assert tm.debt_count(conn) == 1  # 债务里只有一张卡


def test_parked_step_does_not_hang_on_the_card(conn) -> None:  # type: ignore[no-untyped-def]
    """把某一步挂成「待定」之后它就不在卡下面了（搁置不计债，对子孙同样成立）。"""
    top = tm.create_task(conn, "大任务", due_date=_ago(6))
    step = tm.create_subtask(conn, top.id, "先放放的一步", due_date=_ago(2))
    assert len(tm.debt_groups(conn)[0].steps) == 1

    tm.park_task(conn, step.id)
    card = tm.debt_groups(conn)[0]
    assert card.steps == []
    assert card.overdue_days == 6  # 只剩父任务自己的天数


# ---------------------------------------------------------------- API / 界面读数


def test_api_summary_exposes_cards_with_steps(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`GET /api/summary` 给的是"卡 + 挂着的步"，界面照它渲染（前端不自己归卡）。"""
    client = _client(tmp_path)
    top = client.post("/api/tasks", json={"title": "高数作业", "due_date": _ago(9)}).json()
    step = client.post(f"/api/tasks/{top['id']}/subtasks",
                       json={"title": "第 2 题", "due_date": _ago(4)}).json()

    summary = client.get("/api/summary").json()
    assert summary["debt_count"] == 1
    assert [(i["title"], i["overdue_days"], i["degree"]) for i in summary["debt_items"]] == [
        ("高数作业", 9, "重")
    ]
    hung = summary["debt_items"][0]["steps"]
    assert [(s["title"], s["overdue_days"], s["degree"]) for s in hung] == [("第 2 题", 4, "中")]
    # 逾期栏（干活的地方）仍旧两条都在 —— 债务归卡不等于把它藏起来
    assert {t["id"] for t in client.get("/api/overdue").json()} == {top["id"], step["id"]}
