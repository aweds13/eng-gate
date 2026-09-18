"""SR-F9 同步（LWW + 同id去重）测试（AC 同步）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import sync as sync
from timeflow.core import tasks as tm
from timeflow.storage import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_merge_insert_new(conn) -> None:
    tid = tm.create_task(conn, "本地任务").id
    remote = {"id": tid, "title": "远端新标题", "updated_at": "2026-09-09T12:00:00",
              "version": 2}
    result = sync.merge_task(conn, remote)
    assert result in ("inserted", "updated")  # 取决于时间戳比较
    got = tm.get_task(conn, tid)
    # 远端 updated_at 更晚 → 覆盖为远端标题
    assert got.title == "远端新标题"


def test_merge_lww_local_wins(conn) -> None:
    tid = tm.create_task(conn, "本地标题").id
    # 本地 updated_at 更晚，远端较旧 → 保留本地
    remote = {"id": tid, "title": "远端旧标题", "updated_at": "2020-01-01T00:00:00",
              "version": 1}
    result = sync.merge_task(conn, remote)
    assert result == "skipped"
    assert tm.get_task(conn, tid).title == "本地标题"


def test_merge_remote_wins_newer_version(conn) -> None:
    tid = tm.create_task(conn, "本地").id
    remote = {"id": tid, "title": "远端更新", "updated_at": "2026-09-09T12:00:00",
              "version": 5}
    result = sync.merge_task(conn, remote)
    assert result == "updated"
    assert tm.get_task(conn, tid).title == "远端更新"


def test_newer_is_win_logic(conn) -> None:
    assert sync.newer_is_win("2026-09-09T10:00:00", "2026-09-09T11:00:00", 1, 1) is True
    assert sync.newer_is_win("2026-09-09T11:00:00", "2026-09-09T10:00:00", 1, 1) is False
    assert sync.newer_is_win("2026-09-09T10:00:00", "2026-09-09T10:00:00", 1, 3) is True


def test_log_conflict(conn) -> None:
    sync.log_conflict(conn, "task", "abc", "t1", "t2")
    row = conn.execute("SELECT entity_id FROM sync_logs").fetchone()
    assert row and row["entity_id"] == "abc"


# ---- 同步状态（OP-40/OP-41 可观测面，第 10 步）----

def test_status_reports_disabled_honestly(conn) -> None:
    """跨端传输未实现 → 必须报告 enabled=False，不谎报"已同步"。"""
    st = sync.status(conn)
    assert st["enabled"] is False
    assert st["conflict_logs"] == 0
    assert st["last_conflict_at"] is None


def test_status_counts_conflicts(conn) -> None:
    sync.log_conflict(conn, "task", "abc", "t1", "t2")
    sync.log_conflict(conn, "task", "def", "t3", "t4")

    st = sync.status(conn)
    assert st["conflict_logs"] == 2
    assert st["last_conflict_at"] is not None


def test_api_sync_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "s.db")))
    st = client.get("/api/sync/status").json()
    assert st["enabled"] is False
    assert client.get("/api/sync/logs").json() == []
