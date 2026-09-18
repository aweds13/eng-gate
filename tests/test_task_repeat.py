"""第 5 步·OP-8 重复任务生成下一次（AC-8 / F1 R5）。

覆盖：
- 完成设了重复的任务后**自动**生成下一次（不再是死代码）；
- 基准是**上次完成时间**而非创建时间；
- **只生成一次**：重复完成、重复调用 `process_repeats` 都不产生第二份；
- 继承标题/分组/重复周期/My Day；无截止日的重复任务不生成（无从推算）；
- 生成留 `task.repeat.generated` 事实（可审计）。`task.completed` 计数仍只算完成任务本身。
"""

from __future__ import annotations

from datetime import date, timedelta
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
    c = db_mod.connect(str(tmp_path / "t.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _next_tasks(conn: sqlite3.Connection, title: str) -> list[tm.Task]:
    return [t for t in tm.list_tasks(conn, active_only=False) if t.title == title]


def test_complete_repeat_task_generates_next(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "每日背单词", due_date="2026-12-31", repeat_days=7, is_myday=True)
    tm.create_task(conn, "普通任务")
    tm.complete_task(conn, t.id)

    same_title = _next_tasks(conn, "每日背单词")
    assert len(same_title) == 2  # 原任务 + 下一次
    nxt = [x for x in same_title if x.id != t.id][0]
    assert nxt.status == tm.STATUS_TODO
    assert nxt.repeat_days == 7
    assert nxt.is_myday is True
    # 非重复任务不生成
    assert len(_next_tasks(conn, "普通任务")) == 1


def test_next_due_based_on_completion_time(conn: sqlite3.Connection) -> None:
    """下次截止日 = 上次完成时间 + 周期（不是创建时间 + 周期）。"""
    t = tm.create_task(conn, "周报", due_date="2020-01-01", repeat_days=3)
    tm.complete_task(conn, t.id)

    done = tm.get_task(conn, t.id)
    expected = (
        date.fromisoformat(done.updated_at[:10]) + timedelta(days=3)
    ).isoformat()
    nxt = [x for x in _next_tasks(conn, "周报") if x.id != t.id][0]
    assert nxt.due_date == expected


def test_repeat_generation_is_idempotent(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "每日复盘", due_date="2026-12-31", repeat_days=1)
    tm.complete_task(conn, t.id)
    tm.complete_task(conn, t.id)  # 重复完成（幂等，不再发完成事实）
    tm.process_repeats(conn)  # 再次扫描也不应重复生成

    assert len(_next_tasks(conn, "每日复盘")) == 2
    assert facts_mod.count(conn, kind="task.repeat.generated") == 1
    assert facts_mod.count(conn, kind="task.completed") == 1


def test_repeat_fact_records_lineage(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "每周锻炼", due_date="2026-12-31", repeat_days=7)
    tm.complete_task(conn, t.id)

    rows = facts_mod.query(conn, kind="task.repeat.generated")
    assert len(rows) == 1
    fact = rows[0]
    assert fact["subject_id"] == t.id
    assert fact["extra"]["repeat_days"] == 7
    nxt = tm.get_task(conn, str(fact["extra"]["next_task_id"]))
    assert nxt.title == "每周锻炼"  # 事实指向真实存在的下一次


def test_task_without_due_date_does_not_generate(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "没截止日的重复", repeat_days=7)
    tm.complete_task(conn, t.id)

    assert len(_next_tasks(conn, "没截止日的重复")) == 1
    assert facts_mod.count(conn, kind="task.repeat.generated") == 0


def test_non_repeat_task_generates_nothing(conn: sqlite3.Connection) -> None:
    t = tm.create_task(conn, "一次性任务", due_date="2026-12-31")
    tm.complete_task(conn, t.id)

    assert tm.process_repeats(conn) == 0
    assert facts_mod.count(conn, kind="task.repeat.generated") == 0


def test_api_repeat_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """前端视角：完成重复任务后，My Day 里出现下一次。"""
    client = TestClient(create_app(str(tmp_path / "r.db")))
    tid = client.post(
        "/api/tasks",
        json={"title": "每日高数", "due_date": "2026-12-31", "repeat_days": 2, "is_myday": True},
    ).json()["id"]

    assert client.post(f"/api/tasks/{tid}/complete").json()["status"] == tm.STATUS_DONE
    mydays = client.get("/api/mydays").json()
    assert [t["title"] for t in mydays] == ["每日高数"]  # 新的那一条

    facts = client.get(f"/api/tasks/{tid}/facts").json()
    assert [f["kind"] for f in facts] == ["task.completed", "task.repeat.generated"]
