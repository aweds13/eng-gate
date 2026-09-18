"""MVP 主链可执行验收（B4）。默认被 -m "not acceptance" 排除。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.storage import db as db_mod


@pytest.mark.acceptance
def test_mvp_journey(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = str(tmp_path / "a.db")
    client = TestClient(create_app(db_path))

    # ① 新建任务
    tid = client.post(
        "/api/tasks",
        json={"title": "写高数", "due_date": "2026-12-31", "is_myday": True},
    ).json()["id"]
    # ② 绑定任务开始专注
    sid = client.post("/api/focus/start", json={"kind": "plain", "task_id": tid}).json()["id"]
    # ③ 正常结束 1800 秒
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800})

    # ④ 摘要投入 = 0.5h
    assert client.get("/api/summary").json()["invest_hours"] == 0.5

    # ⑤ 当日反馈自动累加（第 2 步前断）
    feedback = client.get("/api/feedback").json()
    assert feedback is not None
    assert feedback["focus_minutes"] == 30.0

    # ⑥ 绑定任务累计时长（第 2 步前由 sessions 可读）
    sessions = client.get(f"/api/focus/tasks/{tid}").json()
    assert sum(int(s["duration_sec"] or 0) for s in sessions) == 1800

    # ⑦ 完成任务 → 发 task.completed 事实（第 2 步前断）
    client.post(f"/api/tasks/{tid}/complete")
    conn = db_mod.connect(db_path)
    try:
        assert facts_mod.count(conn, kind="task.completed") == 1
    finally:
        conn.close()


@pytest.mark.acceptance
def test_abandon_not_invest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(str(tmp_path / "b.db")))
    sid = client.post("/api/focus/start", json={"kind": "plain"}).json()["id"]
    client.post(f"/api/focus/{sid}/finish", json={"duration_sec": 1800, "status": "abandoned"})
    assert client.get("/api/summary").json()["invest_hours"] == 0.0
