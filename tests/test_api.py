"""API 单测（对应 AC-1/2/5/9/10）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "t.db")))


def test_health(client) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_create_and_summary(client) -> None:
    r = client.post(
        "/api/tasks", json={"title": "作业", "due_date": "2020-01-01", "is_myday": True}
    )
    assert r.status_code == 200
    assert r.json()["id"]
    s = client.get("/api/summary").json()
    assert s["debt_count"] == 1


def test_complete_and_mydays(client) -> None:
    tid = client.post("/api/tasks", json={"title": "A", "is_myday": True}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    assert client.get("/api/mydays").json() == []


def test_rejects_blank_title(client) -> None:
    assert client.post("/api/tasks", json={"title": "  "}).status_code == 400
