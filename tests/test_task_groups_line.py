"""F1 主线 · 段1 · 分组管理（契约 OP-11 / SR-F1.3）。

覆盖：
- 新建/重命名/删除分组；空名、重名、不存在各自的码（400/400/404）；
- 删除分组**不删任务**，只解绑；分类计数正确；
- 任务↔分组 加入/移出（`POST /api/tasks/{id}/group`）—— **F 批 · T-F10 起按分组 id**
  （名字允许重名，名字不再是能认的标识；分组要先建，不会"缺组自建"）；
- 改名到**同一个父下**已存在的分组 = 合并（幂等，不留两个同名组）。
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
    c = db_mod.connect(str(tmp_path / "g.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


# ---------------------------------------------------------------- 领域层
def test_create_and_list_group(conn: sqlite3.Connection) -> None:
    gid = tm.create_group(conn, "学习")
    names = [g["name"] for g in tm.list_groups(conn)]
    assert names == ["学习"]
    assert tm.get_group(conn, gid)["name"] == "学习"


def test_create_group_rejects_empty(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        tm.create_group(conn, "   ")


def test_rename_group(conn: sqlite3.Connection) -> None:
    gid = tm.create_group(conn, "学习")
    got = tm.rename_group(conn, gid, "课业")
    assert got["name"] == "课业"
    assert [g["name"] for g in tm.list_groups(conn)] == ["课业"]


def test_rename_group_rejects_empty_and_missing(conn: sqlite3.Connection) -> None:
    gid = tm.create_group(conn, "学习")
    with pytest.raises(ValueError):
        tm.rename_group(conn, gid, "  ")
    with pytest.raises(KeyError):
        tm.rename_group(conn, "nope", "别的")


def test_rename_into_existing_merges(conn: sqlite3.Connection) -> None:
    """改到**同层**已有的名字 = 合并：不留两个同名组，任务归属跟着过去。"""
    a = tm.create_group(conn, "A")
    b = tm.create_group(conn, "B")
    t = tm.create_task(conn, "任务1")
    tm.toggle_task_group(conn, t.id, b, True)

    merged = tm.rename_group(conn, a, "B")

    assert merged["id"] == b
    assert [g["name"] for g in tm.list_groups(conn)] == ["B"]
    assert tm.tasks_in_group(conn, b) == [t.id]


def test_delete_group_keeps_tasks(conn: sqlite3.Connection) -> None:
    """删除分组只解绑，**任务必须还在**（OP-11 边界）。"""
    gid = tm.create_group(conn, "学习")
    t = tm.create_task(conn, "写高数")
    tm.toggle_task_group(conn, t.id, gid, True)
    assert tm.tasks_in_group(conn, gid) == [t.id]

    unbound = tm.delete_group(conn, gid)

    assert unbound == 1
    assert tm.list_groups(conn) == []
    assert tm.get_task(conn, t.id).title == "写高数"  # 任务没被删
    assert tm.task_group_paths(conn, t.id) == []


def test_toggle_task_group_add_and_remove(conn: sqlite3.Connection) -> None:
    """按 id 加入/移出（T-F10）：返回的是**路径**列表；幂等；不存在的 id → KeyError。"""
    gid = tm.create_group(conn, "学习")
    t = tm.create_task(conn, "任务")
    assert tm.toggle_task_group(conn, t.id, gid, True) == ["学习"]
    assert tm.toggle_task_group(conn, t.id, gid, True) == ["学习"]  # 幂等
    assert tm.toggle_task_group(conn, t.id, gid, False) == []
    with pytest.raises(KeyError):
        tm.toggle_task_group(conn, t.id, "nope", True)


def test_toggle_task_group_rejects_empty_id(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "任务")
    with pytest.raises(ValueError):
        tm.toggle_task_group(conn, t.id, "  ", True)


# ---------------------------------------------------------------- API 层
def test_api_group_crud(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "api.db")))

    created = client.post("/api/groups", json={"name": "学习"})
    assert created.status_code == 201
    gid = created.json()["id"]

    assert client.post("/api/groups", json={"name": "学习"}).status_code == 400  # 同层重名
    assert client.post("/api/groups", json={"name": "  "}).status_code == 400  # 空名

    renamed = client.patch(f"/api/groups/{gid}", json={"name": "课业"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "课业"
    assert client.patch(f"/api/groups/{gid}", json={"name": ""}).status_code == 400
    assert client.patch("/api/groups/nope", json={"name": "x"}).status_code == 404
    assert client.patch(f"/api/groups/{gid}", json={}).status_code == 400

    assert client.delete("/api/groups/nope").status_code == 404
    assert client.delete(f"/api/groups/{gid}").json()["unbound_tasks"] == 0


def test_api_task_group_toggle_and_group_tasks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "t.db")))
    tid = client.post("/api/tasks", json={"title": "写高数", "is_myday": True}).json()["id"]
    gid = client.post("/api/groups", json={"name": "学习"}).json()["id"]

    out = client.post(f"/api/tasks/{tid}/group", json={"group_id": gid, "on": True}).json()
    assert out["groups"] == ["学习"] and out["group_ids"] == [gid]
    card = client.get("/api/tasks").json()[0]
    assert card["groups"] == ["学习"] and card["group_ids"] == [gid]

    assert [t["id"] for t in client.get(f"/api/groups/{gid}/tasks").json()] == [tid]
    assert client.get("/api/groups/nope/tasks").status_code == 404

    out2 = client.post(f"/api/tasks/{tid}/group", json={"group_id": gid, "on": False}).json()
    assert out2["groups"] == []
    assert client.post(f"/api/tasks/{tid}/group", json={"group_id": "nope"}).status_code == 404
    assert client.post("/api/tasks/nope/group", json={"group_id": gid}).status_code == 404
    assert client.post(f"/api/tasks/{tid}/group", json={"group_id": ""}).status_code == 400


def test_api_task_create_or_update_with_unknown_group_is_404(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """任务上的 `groups` 给了不存在的分组 → **404「分组不存在」**，而且**任务不许被留下**（T-G33）。

    这是建渲染验证层的种子数据时当场撞到的：`POST /api/tasks` 带一个不存在的分组 id（传**路径**
    也一样）直接 **500** —— `set_task_groups` 对不存在的分组抛 `KeyError`，而那条路由只接了
    `ValueError`。顺带查出**同族第二处**：`PATCH /api/tasks/{id}` 也抛 `KeyError`，但被
    "任务不存在"那一条接住了 → 明明任务好好的，却报「任务不存在」（**指错对象**）。
    """
    client = TestClient(create_app(str(tmp_path / "g33.db")))
    gid = client.post("/api/groups", json={"name": "学习"}).json()["id"]

    # ① 建任务：不存在的分组 id → 404，且说清是哪个 id
    r = client.post("/api/tasks", json={"title": "写作业", "groups": [gid, "nope"]})
    assert r.status_code == 404, r.text
    assert "分组不存在" in r.json()["detail"] and "nope" in r.json()["detail"]

    # ② 任务**不许**被留下（否则客户端看到报错、库里却多一条，重试就多两条）
    assert [t["title"] for t in client.get("/api/tasks").json()] == []

    # ③ 改任务：同样 404，但**不能**再说"任务不存在"（那是两件事）
    tid = client.post("/api/tasks", json={"title": "写作业", "groups": [gid]}).json()["id"]
    r2 = client.patch(f"/api/tasks/{tid}", json={"groups": ["nope"]})
    assert r2.status_code == 404 and "分组不存在" in r2.json()["detail"]

    # ④ 真的任务不存在时，仍然是老口径（别把两种 404 混成一句）
    r3 = client.patch("/api/tasks/nope", json={"groups": [gid]})
    assert r3.status_code == 404 and r3.json()["detail"] == "任务不存在"


def test_api_group_counts_match_tasks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """分组计数与真实归属一致（AC-6）。"""
    client = TestClient(create_app(str(tmp_path / "c.db")))
    t1 = client.post("/api/tasks", json={"title": "A"}).json()["id"]
    t2 = client.post("/api/tasks", json={"title": "B"}).json()["id"]
    study = client.post("/api/groups", json={"name": "学习"}).json()["id"]
    work = client.post("/api/groups", json={"name": "工作"}).json()["id"]
    for tid in (t1, t2):
        client.post(f"/api/tasks/{tid}/group", json={"group_id": study, "on": True})
    client.post(f"/api/tasks/{t1}/group", json={"group_id": work, "on": True})

    counts = {g["name"]: g["task_count"] for g in client.get("/api/groups").json()}
    assert counts == {"学习": 2, "工作": 1}
