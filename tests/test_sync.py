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
    sync.log_conflict(
        conn, "task", "abc", "t1", "t2", result="覆盖（远端较新）", note="title: a → b"
    )
    row = conn.execute("SELECT entity_id, result, note FROM sync_logs").fetchone()
    assert row and row["entity_id"] == "abc"
    # T-G8 起：冲突要写清"为什么"（不静默覆盖这条要求，光有时间戳是看不出来的）
    assert row["result"] == "覆盖（远端较新）" and row["note"] == "title: a → b"


# ---- 同步状态（OP-40/OP-41 可观测面，第 10 步；T-G8 更新口径）----

def test_status_reports_what_works_and_what_does_not(conn) -> None:
    """**只报事实**：走文件的同步（③）可用了，走网络的（①②）还没有 —— 分开报，不谎报。

    口径变更（T-G8，2026-09-22）：这一条原来断言 `enabled is False`（那时候跨端什么都没有）。
    ③ 落地后 `enabled` 不再能表达实情 —— 一个布尔说不清"文件能用、网络没做"，
    所以改成 `file_sync` / `network_sync` 两个事实字段（旧字段保留给老界面）。
    """
    st = sync.status(conn)
    assert st["file_sync"] is True
    assert st["network_sync"] is False
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
    assert st["file_sync"] is True and st["network_sync"] is False
    assert st["device_id"]                      # 设备号：导出包与 LWW 打平都用它
    assert "走文件" in st["note"]
    assert client.get("/api/sync/logs").json() == []
