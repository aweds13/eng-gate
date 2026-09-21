"""F 批 · T-F4：子步骤可设截止日 + 可推迟 + 主任务卡显示「当前该做哪一步」。

**口径（用户 2026-09-21，`复盘/口径定案-待定清单.md` §1）**：
- 「子步骤也能加 deadline」「对子步骤有一个拖延推迟的效果」
  「子步骤完成前，它变成主任务的一个显现（任务卡里显示一个子步骤）」；
- 子步骤本来就是任务（`parent_id` + `due_date` 字段已有）—— 所以**推迟/尝试失败都走已有动作**，
  本卡不新增状态跃迁，只补界面入口与"当前该做哪一步"这个读数；
- 「当前该做哪一步」= **第一个未完成的子任务**，顺序与 `subtasks()` 一致
  （未完成在前 → 截止日近的在前 → 建得早的在前）；选哪一步由**后端**定，前端不自己挑。

覆盖：
- 建步骤时带截止日（HTTP 层）；改截止日 / 清空截止日；
- `current_step` / `current_step_due`：顺序口径、完成当前步后自动递到下一步、
  全做完 / 没有子步骤 → None；
- **`subtask_view` 与 `subtask_progress` 同口径**（同一份子任务顺序，不许一个说剩 2 步、
  另一个把已完成那步当成"当前"）；
- 「推到明天 / 尝试失败」对步骤可用（它们是任务，走同一套动作）；
- 步骤的截止日**不改变父任务的截止日**（各是各的）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "step.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "step_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- 建模：步骤带截止日


def test_subtask_can_be_created_with_due_date(conn) -> None:  # type: ignore[no-untyped-def]
    """建步骤时就能给截止日（T-F4 的第一件事）。"""
    parent = tm.create_task(conn, "高数作业")
    step = tm.create_subtask(conn, parent.id, "第 1 题", due_date=_in_days(2))

    assert step.due_date == _in_days(2)
    assert tm.subtasks(conn, parent.id)[0].due_date == _in_days(2)
    # 步骤的截止日**不影响父任务**（各是各的）
    assert tm.get_task(conn, parent.id).due_date is None


def test_subtask_due_date_can_be_postponed(conn) -> None:  # type: ignore[no-untyped-def]
    """推迟 = 改这一步的 `due_date`（走已有动作 `update_task`）；清空 = 回到"不设截止日"。"""
    parent = tm.create_task(conn, "写论文")
    step = tm.create_subtask(conn, parent.id, "列提纲", due_date=_in_days(1))

    tm.update_task(conn, step.id, due_date=_in_days(3))  # 推到三天后
    assert tm.get_task(conn, step.id).due_date == _in_days(3)

    tm.update_task(conn, step.id, due_date=None)  # 清空是真的清空
    assert tm.get_task(conn, step.id).due_date is None
    assert tm.overdue_days(tm.get_task(conn, step.id)) == 0  # 没有截止日就不算逾期


# ---------------------------------------------------------------- 当前该做哪一步


def test_current_step_is_the_first_unfinished(conn) -> None:  # type: ignore[no-untyped-def]
    """「当前该做哪一步」= 第一个未完成的（顺序同 `subtasks()`：未完成在前、截止日近的在前）。"""
    parent = tm.create_task(conn, "复习第三章")
    assert tm.current_step(conn, parent.id) is None  # 没有步骤 → 没有"当前"

    first = tm.create_subtask(conn, parent.id, "第 1 步：读课本", due_date=_in_days(1))
    second = tm.create_subtask(conn, parent.id, "第 2 步：做例题", due_date=_in_days(2))
    assert tm.current_step(conn, parent.id).id == first.id  # 截止日近的先做

    tm.complete_task(conn, first.id)
    assert tm.current_step(conn, parent.id).id == second.id  # 完成一步自动递到下一步

    tm.complete_task(conn, second.id)
    assert tm.current_step(conn, parent.id) is None  # 全做完 → 没有"当前"


def test_current_step_skips_done_even_if_its_date_is_earliest(conn) -> None:  # type: ignore[no-untyped-def]
    """已完成的那一步不占"当前"，哪怕它的截止日最早（顺序是"未完成在前"优先）。"""
    parent = tm.create_task(conn, "准备汇报")
    done = tm.create_subtask(conn, parent.id, "已经做完的第一步", due_date=_in_days(0))
    todo = tm.create_subtask(conn, parent.id, "还没开始的第二步", due_date=_in_days(9))
    tm.complete_task(conn, done.id)

    assert tm.current_step(conn, parent.id).id == todo.id


def test_current_step_ignores_undated_ordering_only_by_creation(conn) -> None:  # type: ignore[no-untyped-def]
    """都没截止日时按创建时间 —— 先建的那一步就是当前要做的（与列表显示的顺序一致）。"""
    parent = tm.create_task(conn, "整理笔记")
    a = tm.create_subtask(conn, parent.id, "先建的第一步")
    b = tm.create_subtask(conn, parent.id, "后建的第二步")
    assert tm.current_step(conn, parent.id).id == a.id
    assert [x.id for x in tm.subtasks(conn, parent.id)] == [a.id, b.id]


def test_subtask_view_agrees_with_progress(conn) -> None:  # type: ignore[no-untyped-def]
    """**同口径断言**：`subtask_view` 的 done/total 与 `subtask_progress` 完全一致。

    两者分头写迟早会出现"进度说剩 2 步、当前步骤却指着已完成那一步"这种自相矛盾。
    """
    parent = tm.create_task(conn, "大任务")
    kids = [tm.create_subtask(conn, parent.id, f"第 {i} 步") for i in range(3)]
    tm.complete_task(conn, kids[0].id)

    progress, current = tm.subtask_view(conn, parent.id)
    assert progress == tm.subtask_progress(conn, parent.id) == {"done": 1, "total": 3}
    assert current is not None and current.id == kids[1].id

    tm.complete_task(conn, kids[1].id)
    tm.complete_task(conn, kids[2].id)  # 最后一步 → 父任务自动完成（SR-F1.6 联动）
    assert tm.get_task(conn, parent.id).status == tm.STATUS_DONE
    progress2, current2 = tm.subtask_view(conn, parent.id)
    assert progress2 == {"done": 3, "total": 3}
    assert current2 is None


def test_parent_due_date_and_step_due_date_are_independent(conn) -> None:  # type: ignore[no-untyped-def]
    """父任务与步骤各记各的截止日：改步骤不改父，改父不改步骤。"""
    parent = tm.create_task(conn, "做课程设计", due_date=_in_days(10))
    step = tm.create_subtask(conn, parent.id, "画流程图", due_date=_in_days(2))

    tm.update_task(conn, step.id, due_date=_in_days(5))
    assert tm.get_task(conn, parent.id).due_date == _in_days(10)

    tm.update_task(conn, parent.id, due_date=_in_days(20))
    assert tm.get_task(conn, step.id).due_date == _in_days(5)


# ---------------------------------------------------------------- 步骤上可用的动作


def test_step_supports_tomorrow_and_attempt_failed(conn) -> None:  # type: ignore[no-untyped-def]
    """「推到明天 / 尝试失败」对子步骤可用 —— 步骤本来就是任务，走同一套动作，不另造一套。"""
    parent = tm.create_task(conn, "调通环境")
    step = tm.create_subtask(conn, parent.id, "装依赖", due_date=_in_days(-2))

    tm.update_task(conn, step.id, due_date=_in_days(1))  # ≈「推到明天」
    assert tm.get_task(conn, step.id).due_date == _in_days(1)

    tm.attempt_failed(conn, step.id, "pip 源不通")
    assert tm.attempt_count(conn, step.id) == 1
    assert tm.attempt_notes(conn, step.id) == ["pip 源不通"]
    # 记失败不改状态（T-F3 口径）：建的时候就过期过，字段里存着「逾期」，记完还是它
    assert tm.get_task(conn, step.id).status == step.status


# ---------------------------------------------------------------- API


def test_api_subtask_due_date_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """接口：建步骤带日期 → 改日期 → 清空；每一步的 `TaskOut` 自己带 due_date。"""
    client = _client(tmp_path)
    parent = client.post("/api/tasks", json={"title": "高数作业"}).json()

    step = client.post(f"/api/tasks/{parent['id']}/subtasks",
                       json={"title": "第 1 题", "due_date": _in_days(2)}).json()
    assert step["due_date"] == _in_days(2)

    moved = client.patch(f"/api/tasks/{step['id']}", json={"due_date": _in_days(4)}).json()
    assert moved["due_date"] == _in_days(4)

    cleared = client.patch(f"/api/tasks/{step['id']}", json={"due_date": None}).json()
    assert cleared["due_date"] is None

    steps = client.get(f"/api/tasks/{parent['id']}/subtasks").json()
    assert [(s["title"], s["due_date"]) for s in steps] == [("第 1 题", None)]


def test_api_card_exposes_current_step(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """主任务卡靠 `current_step` / `current_step_due` 显示"当前该做哪一步"（后端算好）。"""
    client = _client(tmp_path)
    parent = client.post("/api/tasks", json={"title": "准备答辩"}).json()
    assert parent["current_step"] is None and parent["subtask_total"] == 0

    client.post(f"/api/tasks/{parent['id']}/subtasks",
                json={"title": "写讲稿", "due_date": _in_days(1)})
    client.post(f"/api/tasks/{parent['id']}/subtasks",
                json={"title": "做 PPT", "due_date": _in_days(3)})

    card = next(t for t in client.get("/api/tasks").json() if t["id"] == parent["id"])
    assert card["subtask_done"] == 0 and card["subtask_total"] == 2
    assert (card["current_step"], card["current_step_due"]) == ("写讲稿", _in_days(1))

    # 完成当前这一步 → 卡片上的"当前"自动递到下一步
    first = [s for s in client.get(f"/api/tasks/{parent['id']}/subtasks").json()
             if s["title"] == "写讲稿"][0]
    client.post(f"/api/tasks/{first['id']}/complete")
    card2 = next(t for t in client.get("/api/tasks").json() if t["id"] == parent["id"])
    assert (card2["current_step"], card2["current_step_due"]) == ("做 PPT", _in_days(3))
    assert card2["subtask_done"] == 1
