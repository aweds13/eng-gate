"""F1 主线 · 段1 · 子任务树（契约 OP-12 / SR-F1.6）。

覆盖：
- 建子任务（继承父任务 My Day 归属）；列子任务（未完成在前）；
- 子任务全完成 → **父任务自动完成**；父任务还有未完成子任务时不能被完成；
- 防成环：不能把自己当父、不能挂到自己的子任务下；
- 脱离父任务（parent_id=null）；
- TaskOut 带 subtask_done/subtask_total（父任务卡上直接显示进度）；
- 顺带守住本轮修的 bug：`update_task` 必须真的能**清空**可空字段（due_date/parent_id）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "s.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


# ---------------------------------------------------------------- 领域层
def test_create_subtask_inherits_myday(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "写论文", is_myday=True)
    child = tm.create_subtask(conn, parent.id, "查资料")
    assert child.parent_id == parent.id
    assert child.is_myday is True  # 跟着父任务出现在今天
    assert [t.id for t in tm.subtasks(conn, parent.id)] == [child.id]


def test_create_subtask_validations(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "父")
    with pytest.raises(ValueError):
        tm.create_subtask(conn, parent.id, "   ")
    with pytest.raises(KeyError):
        tm.create_subtask(conn, "nope", "子")


def test_subtasks_unfinished_first(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "父")
    a = tm.create_subtask(conn, parent.id, "A")
    b = tm.create_subtask(conn, parent.id, "B")
    tm.complete_task(conn, b.id)
    assert [t.id for t in tm.subtasks(conn, parent.id)] == [a.id, b.id]  # 未完成在前


def test_all_subtasks_done_autocompletes_parent(conn: sqlite3.Connection) -> None:
    """OP-12 核心联动：最后一个子任务完成 → 父任务自动完成。"""
    parent = tm.create_task(conn, "父任务")
    a = tm.create_subtask(conn, parent.id, "A")
    b = tm.create_subtask(conn, parent.id, "B")

    tm.complete_task(conn, a.id)
    assert tm.get_task(conn, parent.id).status != tm.STATUS_DONE  # 还没到时候

    tm.complete_task(conn, b.id)
    assert tm.get_task(conn, parent.id).status == tm.STATUS_DONE


def test_parent_cannot_complete_with_unfinished_children(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "父任务")
    tm.create_subtask(conn, parent.id, "A")
    with pytest.raises(ValueError):
        tm.complete_task(conn, parent.id)


def test_subtask_created_complete_autocompletes_parent(conn: sqlite3.Connection) -> None:
    """新建时就已完成的情形：先有子任务且都完成，再补一个已完成的子任务不会误完成父任务；
    但如果新建的子任务恰好让"全部完成"成立，父任务也应完成。"""
    parent = tm.create_task(conn, "父任务")
    a = tm.create_subtask(conn, parent.id, "A")
    tm.complete_task(conn, a.id)          # A 完成，父自动完成
    assert tm.get_task(conn, parent.id).status == tm.STATUS_DONE
    b = tm.create_subtask(conn, parent.id, "B")   # 新增未完成子任务
    assert tm.get_task(conn, parent.id).status == tm.STATUS_DONE  # 不会自动撤销完成
    assert b.status != tm.STATUS_DONE


def test_set_task_parent_rejects_cycle(conn: sqlite3.Connection) -> None:
    a = tm.create_task(conn, "A")
    b = tm.create_subtask(conn, a.id, "B")
    c = tm.create_subtask(conn, b.id, "C")

    with pytest.raises(ValueError):
        tm.set_task_parent(conn, a.id, a.id)        # 自己是自己的父
    with pytest.raises(ValueError):
        tm.set_task_parent(conn, a.id, b.id)        # 挂到自己的子任务下（成环）
    with pytest.raises(ValueError):
        tm.set_task_parent(conn, a.id, c.id)        # 挂到孙任务下（成环）
    with pytest.raises(KeyError):
        tm.set_task_parent(conn, a.id, "nope")      # 父任务不存在


def test_set_task_parent_detach(conn: sqlite3.Connection) -> None:
    """脱离父任务：`parent_id=None` 必须真的写进去（这里守住"可空字段被静默忽略"的老 bug）。"""
    parent = tm.create_task(conn, "父")
    child = tm.create_subtask(conn, parent.id, "子")
    got = tm.set_task_parent(conn, child.id, None)
    assert got.parent_id is None
    assert tm.subtasks(conn, parent.id) == []


def test_update_task_can_clear_nullable_fields(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "任务", due_date="2026-01-01")
    assert tm.update_task(conn, t.id, due_date=None).due_date is None


def test_subtask_progress_counts(conn: sqlite3.Connection) -> None:
    parent = tm.create_task(conn, "父")
    assert tm.subtask_progress(conn, parent.id) == {"done": 0, "total": 0}
    a = tm.create_subtask(conn, parent.id, "A")
    tm.create_subtask(conn, parent.id, "B")
    tm.complete_task(conn, a.id)
    assert tm.subtask_progress(conn, parent.id) == {"done": 1, "total": 2}


# ---------------------------------------------------------------- API 层
def test_api_subtask_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "a.db")))
    pid = client.post("/api/tasks", json={"title": "写论文", "is_myday": True}).json()["id"]

    created = client.post(f"/api/tasks/{pid}/subtasks", json={"title": "查资料"})
    assert created.status_code == 201
    sid = created.json()["id"]
    assert created.json()["parent_id"] == pid

    assert [t["id"] for t in client.get(f"/api/tasks/{pid}/subtasks").json()] == [sid]
    assert client.post(f"/api/tasks/{pid}/subtasks", json={"title": " "}).status_code == 400
    assert client.post("/api/tasks/nope/subtasks", json={"title": "x"}).status_code == 404
    assert client.get("/api/tasks/nope/subtasks").status_code == 404

    # 完成子任务 → 父任务自动完成（卡片上的进度字段也跟着变）
    assert client.post(f"/api/tasks/{sid}/complete").json()["status"] == "完成"
    parent = client.get(f"/api/tasks/{pid}").json()
    assert parent["status"] == "完成"
    assert (parent["subtask_done"], parent["subtask_total"]) == (1, 1)
    assert client.get("/api/tasks").json()[0]["subtask_total"] == 1


def test_api_set_parent_cycle_is_400(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    a = client.post("/api/tasks", json={"title": "A"}).json()["id"]
    b = client.post(f"/api/tasks/{a}/subtasks", json={"title": "B"}).json()["id"]

    assert client.post(f"/api/tasks/{a}/parent", json={"parent_id": b}).status_code == 400
    assert client.post("/api/tasks/nope/parent", json={"parent_id": a}).status_code == 404
    # 脱离父任务
    detached = client.post(f"/api/tasks/{b}/parent", json={"parent_id": None}).json()
    assert detached["parent_id"] is None
