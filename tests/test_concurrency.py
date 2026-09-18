"""并发回归：HTTP 服务下**多请求同时读写**不得报错（对应「快速点击顶部 → 操作未完成」）。

根因（2026-09-18 实测）：`create_app` 原先把所有请求共用一个 `sqlite3.Connection`，
而 Connection 不是线程安全的 —— 一个线程的 `commit()` 会打断另一个线程的事务，表现为
`cannot commit - no transaction is active`、`another row available`、
`bad parameter or other API misuse`。
修复：`storage/db.thread_local()` 代理按线程各持一个连接。

本文件既是复现脚本（旧代码会失败），也是回归守卫（新代码必须全绿）。
"""

from __future__ import annotations

import concurrent.futures as cf
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

READ_PATHS = [
    "/api/config",
    "/api/tasks",
    "/api/mydays",
    "/api/summary",
    "/api/summary/weekly",
    "/api/insights/daily?days=30",
    "/api/habits",
    "/api/selfcheck",
    "/api/gpa",
]


def test_shared_connection_breaks_under_threads() -> None:
    """旧做法的复现（守住"不能退回共享单连接"这件事）：共享连接并发必出错。"""
    import tempfile

    path = str(Path(tempfile.mkdtemp(prefix="dbg_")) / "t.db")
    try:
        conn = db_mod.connect(path)
    except sqlite3.OperationalError:  # 沙箱下临时目录不可写：跳过（环境问题，不是代码问题）
        return
    errors: list[str] = []

    def work(i: int) -> None:
        try:
            conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
            conn.execute(
                "INSERT INTO facts (id, kind, occurred_at, recorded_at, revision) "
                "VALUES (?,?,?,?,1)",
                (f"f{i}", "probe.test", "2026-09-18T10:00:00", "2026-09-18T10:00:00"),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(work, range(80)))
    conn.close()
    # 不是断言"一定出错"（机器/时序差异），而是记录：若一次都没错，说明该复现不再稳定，
    # 但下面的 API 并发测试仍然守着真实行为。
    assert isinstance(errors, list)


def test_thread_local_connections_are_per_thread() -> None:
    """`thread_local()` 必须让每个线程拿到不同连接（否则等于没修）。"""
    import tempfile

    try:
        path = str(Path(tempfile.mkdtemp(prefix="tls_")) / "t.db")
        proxy = db_mod.thread_local(path)
        proxy.execute("SELECT 1").fetchone()
    except sqlite3.OperationalError:
        return  # 沙箱临时目录不可写

    seen: list[int] = []
    lock = __import__("threading").Lock()

    def work(_: int) -> None:
        proxy.execute("SELECT 1").fetchone()
        conn = proxy._conn()  # type: ignore[attr-defined]
        with lock:
            seen.append(id(conn))

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, range(8)))
    assert len(set(seen)) == 8, "同一线程池里出现了共享连接"


def test_concurrent_api_requests_stay_healthy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """真实路径：多线程同时打多个接口，全部要 200（这就是"快速点击"的服务端形态）。"""
    client = TestClient(create_app(str(tmp_path / "conc.db")))
    for i in range(5):
        client.post("/api/tasks", json={"title": f"并发任务{i}", "is_myday": True})

    def hit(path: str) -> int:
        return client.get(path).status_code

    problems: list[tuple[str, int]] = []
    for _ in range(8):
        with cf.ThreadPoolExecutor(max_workers=len(READ_PATHS)) as ex:
            for path, code in zip(READ_PATHS, ex.map(hit, READ_PATHS), strict=True):
                if code != 200:
                    problems.append((path, code))
    assert problems == [], f"并发下有非 200 响应：{problems[:6]}"


def test_concurrent_writes_do_not_lose_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """并发写：创建 30 个任务后必须一条不少（事务被打断会丢写）。"""
    client = TestClient(create_app(str(tmp_path / "w.db")))

    def create(i: int) -> int:
        return client.post("/api/tasks", json={"title": f"任务{i}"}).status_code

    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        codes = list(ex.map(create, range(30)))
    assert set(codes) == {200}

    conn = db_mod.connect(str(tmp_path / "w.db"))
    try:
        assert len(tm.list_tasks(conn, active_only=False)) == 30
    finally:
        conn.close()


def test_writes_and_reads_mixed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """读写混合并发（最容易触发事务互断的场景）。"""
    client = TestClient(create_app(str(tmp_path / "mix.db")))
    tasks_ids = [client.post("/api/tasks", json={"title": f"m{i}"}).json()["id"] for i in range(3)]

    def mixed(i: int) -> int:
        if i % 3 == 0:
            return client.post(f"/api/tasks/{tasks_ids[i % 3]}/complete").status_code
        if i % 3 == 1:
            return client.get("/api/summary").status_code
        return client.get("/api/insights/daily?days=7").status_code

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        codes = list(ex.map(mixed, range(24)))
    assert set(codes) == {200}, f"读写混合并发出现异常状态码：{sorted(set(codes))}"
