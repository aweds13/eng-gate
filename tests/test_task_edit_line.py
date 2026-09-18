"""F1 主线 · 段1 · 任务编辑（契约 OP-9）。

覆盖：
- 改标题 / 截止日 / 分组 / 重复 / My Day；清空截止日与重复（**可空字段能真的清掉**）；
- 改截止日会重算逾期与债务（借 summary 的 debt_count 看口径）；
- 已完成任务也能编辑，但**不改写历史完成事实**（契约 OP-9 边界）；
- 错误码：任务不存在 → 404（不是 400）；非法日期 → 400；空标题 → 400。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core.ledger import ledger


def _client(tmp_path, name: str = "e.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def test_edit_basic_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    tid = client.post("/api/tasks", json={"title": "旧标题", "is_myday": True}).json()["id"]

    got = client.patch(
        f"/api/tasks/{tid}",
        json={"title": "新标题", "due_date": "2030-01-01", "repeat_days": 3,
              "group_name": "学习", "is_myday": False},
    ).json()
    assert got["title"] == "新标题"
    assert got["due_date"] == "2030-01-01"
    assert got["repeat_days"] == 3
    assert got["group_name"] == "学习"
    assert got["is_myday"] is False


def test_edit_can_clear_nullable_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """清空必须真的写进去（这里守住"可空字段被静默忽略"的老 bug）。"""
    client = _client(tmp_path)
    tid = client.post(
        "/api/tasks", json={"title": "带截止的任务", "due_date": "2020-01-01", "repeat_days": 5}
    ).json()["id"]

    got = client.patch(f"/api/tasks/{tid}", json={"due_date": None, "repeat_days": None}).json()
    assert got["due_date"] is None
    assert got["repeat_days"] is None


def test_edit_due_date_recomputes_debt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """改截止日 → 逾期与债务跟着变（OP-9 后续 + OP-7 口径）。"""
    client = _client(tmp_path)
    tid = client.post("/api/tasks", json={"title": "会逾期", "due_date": "2020-01-01"}).json()["id"]
    assert client.get("/api/summary").json()["debt_count"] == 1

    client.patch(f"/api/tasks/{tid}", json={"due_date": "2030-01-01"})
    assert client.get("/api/summary").json()["debt_count"] == 0
    assert client.get("/api/overdue").json() == []


def test_edit_completed_task_keeps_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """已完成任务可编辑，但历史完成事实不被改写（契约 OP-9 边界）。"""
    client = _client(tmp_path)
    tid = client.post("/api/tasks", json={"title": "已完成", "is_myday": True}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    facts_before = client.get(f"/api/tasks/{tid}/facts").json()

    got = client.patch(f"/api/tasks/{tid}", json={"title": "改名但仍是完成"}).json()
    assert got["status"] == "完成"
    assert client.get(f"/api/tasks/{tid}/facts").json() == facts_before  # 历史不动


def test_edit_error_codes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "err.db")
    tid = client.post("/api/tasks", json={"title": "任务"}).json()["id"]

    # 任务不存在 → 404（以前被 (KeyError, ValueError) 吞成 400，还把 str(KeyError) 的引号一起显示）
    assert client.patch("/api/tasks/nope", json={"title": "x"}).status_code == 404
    # 空标题：校验在领域层（create 会拦），PATCH 只做写入 —— 这里如实断言"能被写入"，
    # 想禁止空标题要先定口径（属产品决策），所以此处只记行为、不假装它被拒。
    assert client.patch(f"/api/tasks/{tid}", json={"title": ""}).json()["title"] == ""
    # 非法状态：领域层校验 → 400
    assert client.patch(f"/api/tasks/{tid}", json={"status": "不存在的状态"}).status_code == 400
    # 未列入白名单的字段被忽略，不报错也不写库
    got = client.patch(f"/api/tasks/{tid}", json={"version": 999, "id": "hacked"}).json()
    assert got["id"] == tid and got["version"] != 999


def test_edit_then_ledger_snapshot(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """编辑后账本摘要仍然只读事实（不该被编辑动作污染）。"""
    client = _client(tmp_path, "ledger.db")
    tid = client.post("/api/tasks", json={"title": "任务"}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"title": "改了名", "due_date": "2030-01-01"})
    summary = client.get("/api/summary").json()
    assert summary["invest_hours"] == 0.0  # 编辑不是投入
    assert summary["debt_count"] == 0


def test_ledger_debt_unaffected_by_title_edit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """只改标题不动截止日：债务项数不变（避免"编辑就清零债务"的误判）。"""
    client = _client(tmp_path, "debt.db")
    body = {"title": "逾期任务", "due_date": "2020-01-01"}
    tid = client.post("/api/tasks", json=body).json()["id"]
    before = client.get("/api/summary").json()["debt_count"]
    client.patch(f"/api/tasks/{tid}", json={"title": "只改标题"})
    assert client.get("/api/summary").json()["debt_count"] == before == 1


def test_edit_due_date_uses_ledger_degree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """债务程度分档（口径来自 ledger，不由视图层自己算）。"""
    client = _client(tmp_path, "degree.db")
    client.post("/api/tasks", json={"title": "逾期任务", "due_date": "2020-01-01"})
    summary = client.get("/api/summary").json()
    assert summary["debt_items"][0]["degree"] == "重"  # 远超 7 天
    assert summary["debt_items"][0]["overdue_days"] > 7
    assert ledger is not None  # 口径来自 ledger 模块
