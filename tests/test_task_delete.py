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
