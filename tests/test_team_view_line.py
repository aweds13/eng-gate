"""G 批 · T-G12 / OP-33：团队视角切换页（SR-F7.1「管理者与执行者两视角可切换」）。

口径（用户 2026-09-23「全做」后按契约直接落地，没有新增需要拍板的东西）：
- **一份分配记录、两种看法** —— 切视角只是换个筛法，不是两套数据、也不复制一份；
- 执行者视角要你给一个名字（`me`）：执行者是自由文本、本工具没有账号体系，
  所以"我是谁"由你说；**没填就不猜**（空列表 + 一句说明，不报错）；
- 任务被删掉的分配记录**保留审计**（规格 §4），条目上标 `task_missing`；
- 状态筛选只是"少看几条"，**不改计数**（计数是当前视角范围内的事实）。
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
    c = db_mod.connect(str(tmp_path / "team-view.db"))
    yield c
    c.close()


def _assign(conn: sqlite3.Connection, title: str, assignee: str, **kw: object) -> str:
    t = tm.create_task(conn, title)
    return team.assign_task(conn, task_id=t.id, assignee=assignee, assigner="me", **kw)  # type: ignore[arg-type]


def test_manager_view_groups_by_assignee(conn: sqlite3.Connection) -> None:
    """管理者视角 = 我分配出去的全部记录，按执行者分组（**不是**"相邻同名"归组）。"""
    _assign(conn, "甲", "小王")
    _assign(conn, "乙", "小李")
    _assign(conn, "丙", "小王")  # 同一个人被交替分配 → 仍要合成一组

    b = team.board(conn, view=team.VIEW_MANAGER)
    assert b["view"] == "manager"
    assert b["total"] == 3 and b["shown"] == 3
    assert [g["assignee"] for g in b["groups"]] == ["小李", "小王"]  # 组间按名字排
    assert [g["count"] for g in b["groups"]] == [1, 2]
    assert [i["task_title"] for i in b["groups"][1]["items"]] == ["甲", "丙"]  # 组内保持创建顺序


def test_manager_view_carries_task_fields(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "写论文", due_date="2030-01-01")
    team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me", note="周五前给初稿")

    item = team.board(conn)["groups"][0]["items"][0]
    assert item["task_title"] == "写论文"
    assert item["task_due"] == "2030-01-01"
    assert item["task_status"] == "未开始"
    assert item["note"] == "周五前给初稿"
    assert item["assigner"] == "me"
    assert item["task_missing"] is False


def test_executor_view_filters_by_me(conn: sqlite3.Connection) -> None:
    """执行者视角只留分给这个名字的；空格与大小写不影响判定。"""
    _assign(conn, "甲", "小王")
    _assign(conn, "乙", "小李")
    _assign(conn, "丙", "Xiao Ming")

    b = team.board(conn, view=team.VIEW_EXECUTOR, me=" 小王 ")
    assert b["me"] == "小王"
    assert b["total"] == 1
    assert [i["task_title"] for i in b["groups"][0]["items"]] == ["甲"]
    assert team.board(conn, view=team.VIEW_EXECUTOR, me="xiao ming")["total"] == 1


def test_executor_view_without_me_does_not_guess(conn: sqlite3.Connection) -> None:
    """没填「我是谁」→ 一行都不给看（空列表 + 说明），**不猜一个人出来**、也不报错。"""
    _assign(conn, "甲", "小王")

    b = team.board(conn, view=team.VIEW_EXECUTOR)
    assert b["me"] == "" and b["total"] == 0 and b["groups"] == []
    assert "我是谁" in str(b["note"])
    assert team.board(conn, view=team.VIEW_EXECUTOR, me="   ")["total"] == 0


def test_executor_view_note_says_no_match(conn: sqlite3.Connection) -> None:
    """"填了名字但没有分给你的" 与 "没填名字" 是两种不同的空态（说明不一样）。"""
    _assign(conn, "甲", "小王")
    b = team.board(conn, view=team.VIEW_EXECUTOR, me="查无此人")
    assert b["total"] == 0
    assert "查无此人" in str(b["note"])


def test_manager_note_says_not_counted_as_my_invest(conn: sqlite3.Connection) -> None:
    """管理者那句实话里必须写明"分配出去的不计个人投入"（约定层口径，不能只写在文档里）。"""
    assert "不计个人投入" in str(team.board(conn)["note"])


def test_status_filter_does_not_change_counts(conn: sqlite3.Connection) -> None:
    """筛选只是"少看几条"：计数按当前视角范围内的事实算，不跟着筛选变。"""
    a = _assign(conn, "甲", "小王")
    _assign(conn, "乙", "小王")
    team.update_assignment_status(conn, a, "blocked")

    b = team.board(conn, status="blocked")
    assert b["status_filter"] == "blocked"
    assert b["shown"] == 1 and b["total"] == 2
    counts = {s["value"]: s["count"] for s in b["statuses"]}
    assert counts == {"assigned": 1, "in_progress": 0, "done": 0, "blocked": 1}
    assert [i["task_title"] for i in b["groups"][0]["items"]] == ["甲"]


def test_soft_deleted_task_is_shown_as_recycled(conn: sqlite3.Connection) -> None:
    """软删（进回收站）≠ 没了：任务还在，标题照显示，只是多标一句"在回收站"。"""
    t = tm.create_task(conn, "扔进回收站的事")
    team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me")
    tm.delete_task(conn, t.id)

    item = team.board(conn)["groups"][0]["items"][0]
    assert item["task_deleted"] is True
    assert item["task_missing"] is False
    assert item["task_title"] == "扔进回收站的事"


def test_assignment_kept_after_task_purged(conn: sqlite3.Connection) -> None:
    """任务被**彻底删掉**之后，分配记录留着做审计（规格 §4），而不是凭空消失。"""
    t = tm.create_task(conn, "会被彻底删掉的事")
    team.assign_task(conn, task_id=t.id, assignee="小王", assigner="me")
    tm.delete_task(conn, t.id)   # 彻底删只能删回收站里的（先软删）
    tm.purge_task(conn, t.id)

    item = team.board(conn)["groups"][0]["items"][0]
    assert item["task_missing"] is True
    assert item["task_title"] is None
    assert item["task_id"] == t.id


def test_rejects_unknown_view_and_status(conn: sqlite3.Connection) -> None:
    """非法视角/非法状态一律拒绝并带上"能用的有哪些"（不静默回落成默认值）。"""
    with pytest.raises(ValueError, match="非法视角"):
        team.board(conn, view="boss")
    with pytest.raises(ValueError, match="非法状态"):
        team.board(conn, status="sleeping")
    # 默认视角是管理者（不传就按管理者看，而不是报错或空页）
    assert team.board(conn)["view"] == team.VIEW_MANAGER


def test_views_meta_writes_chinese_once(conn: sqlite3.Connection) -> None:
    """视角的中文标签由后端给（界面不自己写一份），两个视角都在。"""
    values = [v["value"] for v in team.views_meta()]
    assert values == ["manager", "executor"]
    assert team.board(conn)["views"] == team.views_meta()


def test_api_board_endpoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "board.db")))
    tid = client.post("/api/tasks", json={"title": "写论文", "due_date": "2030-01-01"}).json()["id"]
    client.post("/api/team/assign", json={"task_id": tid, "assignee": "小王", "note": "周五前"})

    mgr = client.get("/api/team/board").json()
    assert mgr["view"] == "manager" and mgr["total"] == 1
    assert mgr["groups"][0]["assignee"] == "小王"
    assert mgr["groups"][0]["items"][0]["task_title"] == "写论文"

    exe = client.get("/api/team/board", params={"view": "executor", "me": "小王"}).json()
    assert exe["total"] == 1
    assert client.get(
        "/api/team/board", params={"view": "executor", "me": "别人"}
    ).json()["total"] == 0

    assert client.get("/api/team/board", params={"view": "boss"}).status_code == 400
    assert client.get("/api/team/board", params={"status": "bogus"}).status_code == 400
    # 状态筛选：参数为空串 = 不筛（前端把"全部"按钮传成空 status）
    assert client.get("/api/team/board", params={"status": ""}).json()["status_filter"] == ""


def test_api_board_needs_no_account(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """这个视图**不引入账号体系**：接口只要一个名字参数，别的什么都不用（不建用户表、不登录）。"""
    client = TestClient(create_app(str(tmp_path / "board2.db")))
    got = client.get("/api/team/board", params={"view": "executor", "me": "小王"}).json()
    assert got["total"] == 0
    assert "我是谁" not in str(got["note"])  # 填了名字就不是"先说你 who"那句
