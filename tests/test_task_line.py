"""第 2 步·任务线发事实：完成 → `task.completed`，撤销 → `task.uncompleted`（F1 OP-5）。

覆盖：
- 完成/撤销各发一条事实，且主体指向任务；
- 幂等：重复完成、重复撤销不重复发；
- 只对「完成 ↔ 非完成」跃迁发**账本**事实；普通状态流转只留 `task.status_changed`（T-F1 起，
  为「任务存档/过去尝试」留痕，但**不进账本**）；
- 完成不折算时间（value_num 为空），投入口径仍由专注事实承担（SR-F2 R2）；
- 账本只从 facts 读，任务事实不得干扰投入口径；
- API 路径 `/complete`、`/uncomplete`、`/facts` 全链路。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.core.academic import academic as ac
from timeflow.core.ledger import ledger
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


# ---- 领域层 ----

def test_complete_task_records_fact(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "写高数")
    done = tm.complete_task(conn, t.id)

    assert done.status == tm.STATUS_DONE
    rows = facts_mod.query(conn, kind="task.completed")
    assert len(rows) == 1
    assert rows[0]["subject_type"] == "task"
    assert rows[0]["subject_id"] == t.id
    assert rows[0]["value_num"] is None  # 完成不估时（SR-F2 R2）
    assert rows[0]["extra"]["from_status"] == tm.STATUS_TODO
    assert rows[0]["extra"]["title"] == "写高数"


def test_complete_task_is_idempotent(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "A")
    tm.complete_task(conn, t.id)
    tm.complete_task(conn, t.id)

    assert facts_mod.count(conn, kind="task.completed") == 1


def test_update_status_to_done_also_records_fact(conn: sqlite3.Connection) -> None:
    """从其它入口（PATCH status）完成，同样发事实，不依赖单一入口。"""
    t = tm.create_task(conn, "B")
    tm.update_task(conn, t.id, status=tm.STATUS_DONE)

    assert facts_mod.count(conn, kind="task.completed") == 1


def test_uncomplete_records_reverse_fact(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "C")
    tm.complete_task(conn, t.id)
    back = tm.uncomplete_task(conn, t.id)

    assert back.status == tm.STATUS_TODO
    assert facts_mod.count(conn, kind="task.completed") == 1
    assert facts_mod.count(conn, kind="task.uncompleted") == 1
    assert facts_mod.count(conn, kind="task.") == 2  # 两条都留痕，不删历史


def test_uncomplete_is_idempotent(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "D")
    tm.uncomplete_task(conn, t.id)  # 未完成 → 空操作
    assert facts_mod.count(conn, kind="task.") == 0

    tm.complete_task(conn, t.id)
    tm.uncomplete_task(conn, t.id)
    tm.uncomplete_task(conn, t.id)
    assert facts_mod.count(conn, kind="task.uncompleted") == 1


def test_uncomplete_can_restore_previous_status(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "E")
    tm.update_task(conn, t.id, status=tm.STATUS_DOING)
    tm.complete_task(conn, t.id)
    back = tm.uncomplete_task(conn, t.id, restore_status=tm.STATUS_DOING)

    assert back.status == tm.STATUS_DOING


def test_uncomplete_rejects_done_restore(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "F")
    tm.complete_task(conn, t.id)
    with pytest.raises(ValueError):
        tm.uncomplete_task(conn, t.id, restore_status=tm.STATUS_DONE)


def test_other_status_changes_record_status_fact_only(conn: sqlite3.Connection) -> None:
    """搁置类状态变化只留 `task.status_changed`，**不进账本**（T-F1 改的口径）。

    口径变更说明（2026-09-21，F 批 · T-F1）：本条以前断言"其它状态变化**一条事实都不记**"。
    用户给的状态机设计要求「过去做过什么/什么时候搁置的要能追溯」（N11 任务存档），
    所以现在会记一条状态变化事实（`task.status_changed`，带 from/to）——
    但**账本口径没变**：债务只看 `overdue_tasks`，这些动作不产生任何账目；
    改普通字段（如 `is_myday`）依旧什么都不记。
    """
    t = tm.create_task(conn, "G")
    tm.update_task(conn, t.id, status=tm.STATUS_DOING)
    tm.update_task(conn, t.id, status=tm.STATUS_CANCELLED)
    tm.update_task(conn, t.id, is_myday=True)

    rows = facts_mod.query(conn, kind="task.", subject_type="task", subject_id=t.id)
    assert [f["kind"] for f in rows] == ["task.status_changed", "task.status_changed"]


def test_publish_task_completed_event(conn: sqlite3.Connection) -> None:
    """完成同时广播事件，供其它线订阅（与专注线一致的接线方式）。"""
    seen: list[dict] = []  # type: ignore[type-arg]
    facts_mod.subscribe("task.completed", lambda _k, p: seen.append(p))
    t = tm.create_task(conn, "H")
    tm.complete_task(conn, t.id)

    assert len(seen) == 1
    assert seen[0]["task_id"] == t.id


def test_task_fact_does_not_pollute_invest(conn: sqlite3.Connection) -> None:
    """任务完成事实不得进入投入时长（投入只认 focus.finished）。"""
    t = tm.create_task(conn, "I")
    tm.complete_task(conn, t.id)

    assert ledger.summary(conn).invest_hours == 0.0
    assert ledger.summary(conn).debt_count == 0


def test_parent_with_unfinished_children_records_no_fact(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "父任务")
    tm.create_task(conn, "子任务", parent_id=parent.id)
    with pytest.raises(ValueError):
        tm.complete_task(conn, parent.id)

    assert facts_mod.count(conn, kind="task.") == 0


# ---- API 全链路 ----

def test_api_complete_uncomplete_and_facts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "a.db")))
    tid = client.post("/api/tasks", json={"title": "写高数", "is_myday": True}).json()["id"]

    done = client.post(f"/api/tasks/{tid}/complete")
    assert done.status_code == 200
    assert done.json()["status"] == tm.STATUS_DONE

    facts = client.get(f"/api/tasks/{tid}/facts").json()
    assert [f["kind"] for f in facts] == ["task.completed"]

    back = client.post(f"/api/tasks/{tid}/uncomplete")
    assert back.status_code == 200
    assert back.json()["status"] == tm.STATUS_TODO

    facts2 = client.get(f"/api/tasks/{tid}/facts").json()
    assert [f["kind"] for f in facts2] == ["task.completed", "task.uncompleted"]


def test_api_uncomplete_unknown_task_404(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    assert client.post("/api/tasks/nope/uncomplete").status_code == 404
    assert client.get("/api/tasks/nope/facts").status_code == 404


# ---- SR-F1.9 ③：task_type 扩「竞赛/活动」（T-G140）----

def test_competition_activity_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """钉子①：能存能取 —— 建一个 `task_type='竞赛'`（及「活动」）→ 读回来不变。"""
    conn = db_mod.connect(str(tmp_path / "t140a.db"))
    for kind in ("竞赛", "活动"):
        t = tm.create_task(conn, title=f"一件{kind}", task_type=kind)
        got = tm.get_task(conn, t.id)
        assert got.task_type == kind
    conn.close()


def test_illegal_type_still_rejected_after_expansion(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """钉子②：扩值后白名单制不变 —— 非法值仍拒绝，不许静默降级成「普通」。"""
    conn = db_mod.connect(str(tmp_path / "t140b.db"))
    with pytest.raises(ValueError, match="非法任务类型"):
        tm.create_task(conn, title="x", task_type="乱写")
    conn.close()


def test_competition_activity_course_pairing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """钉子③：`竞赛`/`活动` 不带课程能建、带课程也能建；「普通」带课程仍被拒。

    它们可能属于某门课，也可能是校级事项 —— 所以两个方向都放行（manager 的配对规则
    只禁「普通」这一档，扩值无需特判）。
    """
    conn = db_mod.connect(str(tmp_path / "t140c.db"))
    cid = ac.create_course(conn, name="程序设计竞赛")
    for kind in ("竞赛", "活动"):
        free = tm.create_task(conn, title=f"校级{kind}", task_type=kind)
        assert free.course_id is None
        bound = tm.create_task(conn, title=f"课内{kind}", task_type=kind, course_id=cid)
        assert bound.course_id == cid
    with pytest.raises(ValueError, match="不挂课程"):
        tm.create_task(conn, title="x", task_type="普通", course_id=cid)
    conn.close()


def test_deferred_badge_only_for_new_types() -> None:
    """钉子④（反向判据）：「逾期不候」轻标签只给 `竞赛`/`活动` —— 防"永远显示"。

    判据读 `src/web/index.html` 里 deferredBadge 的守卫表达式：它必须**恰好**是
    `type==='竞赛'||type==='活动'` 这两个取值（普通/作业/考试/论文/小测 不在列），
    且该徽标必须真的接在任务卡片的 meta 行上。
    """
    html = (Path(__file__).resolve().parents[1] / "src" / "web" / "index.html").read_text(
        encoding="utf-8"
    )
    guard = "(type==='竞赛'||type==='活动')"
    assert guard in html, "deferredBadge 的守卫不是「只认 竞赛/活动」的白名单判据"
    assert "${deferredBadge(t)}" in html, "逾期不候轻标签没有接到任务卡片上"
    # 函数体里不许出现其余四档取值（防"顺手"扩成永远显示）；「普通」只允许作为兜底默认
    body = html.split("function deferredBadge(t){", 1)[1].split("\n}", 1)[0]
    for other in ("作业", "考试", "论文", "小测"):
        assert other not in body, f"deferredBadge 不应给「{other}」出标签"
    assert body.count("普通") == 1 and "||'普通'" in body, "「普通」只许出现在兜底默认里"
