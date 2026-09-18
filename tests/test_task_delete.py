"""第 5 步·OP-6 软删除 + 撤销（F1 R7）。

覆盖：
- 删除 = 软删除（置「已删」），数据与事实历史保留，可撤销；
- 默认视图全部隐藏已删任务：列表 / My Day / 逾期（债务）/ 分组计数口径不受影响；
- 撤销后回到未开始（可指定 restore_status），重复删除/重复撤销幂等；
- 留 `task.deleted` / `task.restored` 事实；
- API：DELETE → 回收站可见 → POST /restore → 回列表。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import tasks as tm
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


def test_delete_is_soft(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "写高数", is_myday=True)
    got = tm.delete_task(conn, t.id)

    assert got.status == tm.STATUS_DELETED
    row = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (t.id,)).fetchone()
    assert row is not None  # 行还在（未物理删除）
    assert tm.get_task(conn, t.id).title == "写高数"


def test_deleted_task_hidden_from_default_views(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "会消失的任务", due_date="2020-01-01", is_myday=True)
    assert len(tm.overdue_tasks(conn)) == 1
    tm.delete_task(conn, t.id)

    assert [x.id for x in tm.list_tasks(conn)] == []
    assert [x.id for x in tm.myday_tasks(conn)] == []
    assert tm.overdue_tasks(conn) == []
    assert ledger.summary(conn).debt_count == 0  # 已删任务不计债务
    # 但历史仍在（active_only=False 可见）
    assert [x.id for x in tm.list_tasks(conn, active_only=False)] == [t.id]


def test_restore_brings_task_back(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "误删的任务", is_myday=True)
    tm.delete_task(conn, t.id)
    back = tm.restore_task(conn, t.id)

    assert back.status == tm.STATUS_TODO
    assert [x.id for x in tm.myday_tasks(conn)] == [t.id]


def test_restore_can_target_status(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "进行中的任务")
    tm.update_task(conn, t.id, status=tm.STATUS_DOING)
    tm.delete_task(conn, t.id)

    assert tm.restore_task(conn, t.id, restore_status=tm.STATUS_DOING).status == tm.STATUS_DOING


def test_delete_and_restore_are_idempotent(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "重复操作")
    tm.delete_task(conn, t.id)
    tm.delete_task(conn, t.id)
    tm.restore_task(conn, t.id)
    tm.restore_task(conn, t.id)

    assert facts_mod.count(conn, kind="task.deleted") == 1
    assert facts_mod.count(conn, kind="task.restored") == 1


def test_restore_rejects_deleted_target(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "参数校验")
    tm.delete_task(conn, t.id)
    with pytest.raises(ValueError):
        tm.restore_task(conn, t.id, restore_status=tm.STATUS_DELETED)


def test_purge_removes_row(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "彻底删除")
    tm.delete_task(conn, t.id)
    tm.purge_task(conn, t.id)

    with pytest.raises(KeyError):
        tm.get_task(conn, t.id)


def test_purge_only_accepts_deleted_tasks(conn: sqlite3.Connection) -> None:
    """护栏：彻底删除只对回收站里的任务开放，活动任务必须走软删除（避免误删）。"""
    live = tm.create_task(conn, "还在用的任务")
    with pytest.raises(ValueError):
        tm.purge_task(conn, live.id)
    assert tm.get_task(conn, live.id).status == tm.STATUS_TODO  # 没被删掉

    tm.delete_task(conn, live.id)
    tm.purge_task(conn, live.id)  # 软删除之后才允许
    assert tm.list_tasks(conn, active_only=False) == []


def test_purge_unknown_task_is_idempotent(conn: sqlite3.Connection) -> None:
    tm.purge_task(conn, "nope")  # 不抛错


def test_purge_deleted_tasks_clears_recycle_bin(conn: sqlite3.Connection) -> None:
    """清空回收站：只清已删的，活着的任务不受影响。"""
    keep = tm.create_task(conn, "保留")
    a = tm.create_task(conn, "删掉 A")
    b = tm.create_task(conn, "删掉 B")
    tm.delete_task(conn, a.id)
    tm.delete_task(conn, b.id)

    assert tm.purge_deleted_tasks(conn) == 2
    assert [t.id for t in tm.list_tasks(conn, active_only=False)] == [keep.id]
    assert tm.purge_deleted_tasks(conn) == 0  # 幂等


def test_purge_also_clears_group_links(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "带分组的任务")
    tm.set_task_groups(conn, t.id, ["学习"])
    tm.delete_task(conn, t.id)
    tm.purge_task(conn, t.id)

    left = conn.execute("SELECT COUNT(*) AS c FROM task_groups WHERE task_id = ?", (t.id,))
    assert left.fetchone()["c"] == 0  # 不留孤儿关联


def test_api_purge_and_clear_recycle_bin(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "p.db")))
    live = client.post("/api/tasks", json={"title": "活着的"}).json()["id"]
    gone = client.post("/api/tasks", json={"title": "要清的"}).json()["id"]
    client.delete(f"/api/tasks/{gone}")

    # 活动任务不允许彻底删（400），回收站里的可以（幂等：再来一次也 200）
    assert client.delete(f"/api/tasks/{live}/purge").status_code == 400
    assert client.delete(f"/api/tasks/{gone}/purge").status_code == 200
    assert client.delete(f"/api/tasks/{gone}/purge").status_code == 200
    assert client.get("/api/tasks/deleted").json() == []

    # 清空回收站：路由不能被 /{task_id} 抢走（这是声明顺序的回归守卫）
    ids = [client.post("/api/tasks", json={"title": f"清{i}"}).json()["id"] for i in range(2)]
    for tid in ids:
        client.delete(f"/api/tasks/{tid}")
    assert client.post("/api/tasks/purge-deleted").json() == {"purged": 2}
    assert client.post("/api/tasks/purge-deleted").json() == {"purged": 0}
    assert [t["id"] for t in client.get("/api/tasks").json()] == [live]
    assert client.get(f"/api/tasks/{ids[0]}").status_code == 404  # 真的没了


def test_api_delete_restore_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "s.db")))
    tid = client.post("/api/tasks", json={"title": "写高数", "is_myday": True}).json()["id"]

    deleted = client.delete(f"/api/tasks/{tid}").json()
    assert deleted["status"] == tm.STATUS_DELETED
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/mydays").json() == []
    assert [t["id"] for t in client.get("/api/tasks/deleted").json()] == [tid]

    restored = client.post(f"/api/tasks/{tid}/restore").json()
    assert restored["status"] == tm.STATUS_TODO
    assert client.get("/api/tasks/deleted").json() == []

    facts = client.get(f"/api/tasks/{tid}/facts").json()
    assert [f["kind"] for f in facts] == ["task.deleted", "task.restored"]


def test_api_delete_unknown_task_404(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "u.db")))
    assert client.delete("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/restore").status_code == 404
