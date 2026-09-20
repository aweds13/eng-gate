"""SR-NF13：关键路径日志 + 健康检查 + 调试开关。

口径（`src/timeflow/logs.py` 的约定）：
- 日志是**一行一条 JSON**（好 grep、好统计，不用解析自由文本）；
- **只记"发生了什么"**（事件名 + 关键字段），不记请求正文/备注内容 —— 个人数据不进日志；
- 调试开关**只影响日志级别**，不改变任何业务行为；
- 日志失败**吞掉**（写不进日志不该让主流程挂掉），但也绝不因此改变业务结果；
- `/api/health` 只报能自证的事实（库通不通 / schema 版本 / 条数），**永远能回答**（自己不许 500）。

测试都落在**临时日志路径**上（`TF_LOG_PATH` + `force=True`），不往仓库的 `logs/` 里写。
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from timeflow import logs
from timeflow.api.app import create_app
from timeflow.storage import db as db_mod


@pytest.fixture()
def log_file(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """把日志指到临时文件，并在用例结束后复位（避免污染其它用例的日志配置）。"""
    path = tmp_path / "tf.jsonl"
    monkeypatch.setenv(logs.ENV_LOG_PATH, str(path))
    logs.setup_logging(debug=True, log_path=path, force=True)
    yield path
    monkeypatch.delenv(logs.ENV_LOG_PATH, raising=False)
    logs.setup_logging(debug=False, log_path="off", force=True)


def _lines(path) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- 结构化日志

def test_log_event_writes_one_json_line(log_file) -> None:  # type: ignore[no-untyped-def]
    logs.log_event("unit_test_event", task_id="t1", ms=12.5)
    got = _lines(log_file)
    assert len(got) == 1
    line = got[0]
    assert line["event"] == "unit_test_event" and line["level"] == "INFO"
    assert line["task_id"] == "t1" and line["ms"] == 12.5
    assert isinstance(line["ts"], str) and "T" in line["ts"]


def test_setup_logging_is_idempotent_and_switchable(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """幂等：重复调用不叠加 handler（否则同一句话会被写多遍）；`off` = 只打控制台。"""
    first = logs.setup_logging(debug=False, log_path=tmp_path / "a.jsonl", force=True)
    again = logs.setup_logging(debug=False, log_path=tmp_path / "b.jsonl")
    assert first == again, "第二次调用不该另起一套 handler（幂等）"
    logs.log_event("once")
    assert len(_lines(tmp_path / "a.jsonl")) == 1

    assert logs.setup_logging(debug=False, log_path="off", force=True) is None
    logs.log_event("not_written")
    assert len(_lines(tmp_path / "a.jsonl")) == 1, "off 之后不该再落文件"


def test_debug_switch_only_changes_level(log_file, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(logs.ENV_DEBUG, "1")
    assert logs.debug_enabled() is True
    monkeypatch.setenv(logs.ENV_DEBUG, "no")
    assert logs.debug_enabled() is False
    monkeypatch.setenv(logs.ENV_DEBUG, "YES")
    assert logs.debug_enabled() is True

    logs.setup_logging(debug=False, log_path=log_file, force=True)
    assert logs.logger().level == logging.INFO
    logs.setup_logging(debug=True, log_path=log_file, force=True)
    assert logs.logger().level == logging.DEBUG


def test_file_logger_failure_does_not_raise(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """写不进日志文件 → 退回控制台、**不抛异常**（日志不该挡住启动）。"""
    monkeypatch.setattr(logs.logging, "FileHandler", _boom)
    got = logs.setup_logging(debug=False, log_path=tmp_path / "x.jsonl", force=True)
    assert got is None
    logs.log_event("still_works")  # 不炸


def _boom(*a, **k):  # type: ignore[no-untyped-def]
    raise OSError("拒绝访问")


# ---------------------------------------------------------------- 健康检查

def test_health_reports_facts_not_platitudes(tmp_path, log_file) -> None:  # type: ignore[no-untyped-def]
    c = TestClient(create_app(str(tmp_path / "h.db")))
    got = c.get("/api/health").json()
    assert got["status"] == "ok" and got["database_ok"] is True
    assert got["schema_version"] == db_mod.SCHEMA_VERSION
    assert got["tasks"] == 0 and got["facts"] == 0
    assert got["log_file"] == str(log_file)
    c.post("/api/tasks", json={"title": "一件事"})
    assert c.get("/api/health").json()["tasks"] == 1


def test_health_degrades_instead_of_500(tmp_path, monkeypatch, log_file) -> None:  # type: ignore[no-untyped-def]
    """库出问题时：如实报 `degraded` + 原因，**健康检查自己不许 500**。"""
    from timeflow.api import app as app_mod

    real_connect = db_mod.connect

    class FlakyConn:
        """只在"读 schema_version"时炸 —— 模拟库损坏/被占用，其余照常。"""

        def __init__(self, path: str) -> None:
            self._real = real_connect(path)

        def execute(self, sql: str, *a, **k):  # type: ignore[no-untyped-def]
            if "schema_version" in sql:
                raise RuntimeError("库读不了")
            return self._real.execute(sql, *a, **k)

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._real, name)

    monkeypatch.setattr(app_mod.db, "thread_local", lambda p: FlakyConn(p))
    c = TestClient(create_app(str(tmp_path / "h2.db")))
    got = c.get("/api/health").json()
    assert got["status"] == "degraded"
    assert got["database_ok"] is False and "库读不了" in got["error"]


# ---------------------------------------------------------------- 关键路径日志

def test_write_requests_are_logged_get_is_not(tmp_path, log_file) -> None:  # type: ignore[no-untyped-def]
    """改动类请求记一条（方法/路径/状态/耗时）；GET 不记（读了就记会把日志淹掉）。"""
    c = TestClient(create_app(str(tmp_path / "w.db")))
    c.post("/api/tasks", json={"title": "记一笔"})
    c.get("/api/summary")
    events = [x["event"] for x in _lines(log_file)]
    assert "app_start" in events
    writes = [x for x in _lines(log_file) if x["event"] == "api_write"]
    assert [w["path"] for w in writes] == ["/api/tasks"]
    assert writes[0]["method"] == "POST" and writes[0]["status"] == 200
    assert isinstance(writes[0]["ms"], (int, float))


def test_logs_do_not_carry_user_text(tmp_path, log_file) -> None:  # type: ignore[no-untyped-def]
    """隐私最小化：日志里不该出现用户写的正文（备注/标题）。"""
    c = TestClient(create_app(str(tmp_path / "p.db")))
    c.post("/api/tasks", json={"title": "这是用户写的标题", "note": "这是用户写的备注"})
    body = log_file.read_text(encoding="utf-8")
    assert "这是用户写的标题" not in body and "这是用户写的备注" not in body
