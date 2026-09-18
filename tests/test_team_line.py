"""第 10 步·团队域补强：分配可见性与校验（SR-F7.1/F7.2）。

背景（此前缺口）：
- 团队分配表存在、API 也能用，但**任务卡片上看不到「谁负责 / 进展到哪」**——分配出去就沉底了；
- `assign_task` 不校验任务存在、也不校验执行者非空 → 会产生指向不存在任务的分配记录。
本批：`TaskOut.assignments`（任务带分配）+ `team.assignments_for_task()` + 参数校验 + 前端卡片按钮。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import tasks as tm
from timeflow.core import team
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    import sqlite3


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_assign_requires_existing_task(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyError):
        team.assign_task(conn, task_id="nope", assignee="小王", assigner="me")


def test_assign_rejects_blank_assignee(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "写论文")
    with pytest.raises(ValueError):
        team.assign_task(conn, task_id=t.id, assignee="   ", assigner="me")


def test_assignments_for_task(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "写论文")
    other = tm.create_task(conn, "别的事")
    team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me", note="截止周五")
    team.assign_task(conn, task_id=other.id, assignee="小李", assigner="me")

    rows = team.assignments_for_task(conn, t.id)
    assert len(rows) == 1
    assert rows[0]["assignee"] == "小王"
    assert rows[0]["note"] == "截止周五"
    assert rows[0]["status"] == "assigned"


def test_status_machine(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "联调")
    rid = team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me")

    team.update_assignment_status(conn, rid, "in_progress")
    assert team.assignments_for_task(conn, t.id)[0]["status"] == "in_progress"
    team.update_assignment_status(conn, rid, "blocked")
    team.update_assignment_status(conn, rid, "done")
    assert team.assignments_for_task(conn, t.id)[0]["status"] == "done"
    with pytest.raises(ValueError):
        team.update_assignment_status(conn, rid, "bogus")


def test_task_out_carries_assignments(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """任务接口直接带上分配信息 —— 卡片可见，不必另开页面。"""
    client = TestClient(create_app(str(tmp_path / "a.db")))
    tid = client.post("/api/tasks", json={"title": "写论文", "is_myday": True}).json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["assignments"] == []

    aid = client.post(
        "/api/team/assign", json={"task_id": tid, "assignee": "小王", "note": "周五前"}
    ).json()["id"]
    got = client.get(f"/api/tasks/{tid}").json()["assignments"]
    assert len(got) == 1
    assert got[0]["assignee"] == "小王"
    assert got[0]["status"] == "assigned"
    # My Day 列表里同样可见
    assert client.get("/api/mydays").json()[0]["assignments"][0]["id"] == aid

    assert (
        client.patch(f"/api/team/assign/{aid}", json={"status": "in_progress"}).status_code
        == 200
    )
    assert client.get(f"/api/tasks/{tid}").json()["assignments"][0]["status"] == "in_progress"


def test_api_assign_validations(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    tid = client.post("/api/tasks", json={"title": "任务"}).json()["id"]
    assert client.post(
        "/api/team/assign", json={"task_id": "nope", "assignee": "小王"}
    ).status_code == 404
    assert client.post(
        "/api/team/assign", json={"task_id": tid, "assignee": "  "}
    ).status_code == 400
    aid = client.post(
        "/api/team/assign", json={"task_id": tid, "assignee": "小王"}
    ).json()["id"]
    assert client.patch(f"/api/team/assign/{aid}", json={"status": "bogus"}).status_code == 400


def test_team_task_not_counted_as_my_invest(conn: sqlite3.Connection) -> None:
    """约定：分配出去的任务不计个人投入（团队任务只记协调）。"""
    from timeflow.core.ledger import ledger

    t = tm.create_task(conn, "外包出去的事")
    team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me")
    tm.complete_task(conn, t.id)

    assert ledger.summary(conn).invest_hours == 0.0
