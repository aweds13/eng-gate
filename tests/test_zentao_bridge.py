"""`tools/zentao_bridge.py`（卡 211 · T-G321）的测试 —— **不连真禅道**。

## 怎么做到「不连真禅道」

起一个**本机桩 HTTP 服务**（`http.server`，127.0.0.1 随机端口）喂假响应，把
`ZENTAO_URL` 指向它。测的仍是桥**真的走 urllib 发 GET、真的解析**这条路 ——
只是对端不是禅道。连不上那条用一个**没人监听**的端口。

## ★ 诚实边界（不假装）

本机**没有在跑的禅道**（见 `docs/zentao-bridge.toml` 的 `[runtime]`：80/8080/8088/8999/3306
全 connection refused）。所以下面这些 fixture **不是**「第 1 步真拉到的响应」，而是照
**安装包里的入口源码**（`app/zentao/api/v1/entries/{projects,executions,tasks}.php`）
的 `send(...)` 形状逐字段抄下来的信封与字段名。真拉到的响应等有活体时再补。

## 判据（卡 211 §3）

字段映射 + 四条反例（连不上 / 401-403 / 坏 JSON / 缺必需字段）+ 幂等（逐字节相同）。
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parent.parent
TOOL = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "zentao_bridge.py")]

# ── 假响应（照入口源码的 send(...) 形状抄；证据见 test 文件头）────────────────
PROJECTS_JSON = json.dumps({
    "page": 1, "total": 1, "limit": 20,
    "projects": [{
        "id": 1, "name": "示例项目", "code": "demo", "model": "scrum", "type": "project",
        "status": "wait", "PM": "admin", "begin": "2026-01-01", "end": "2026-06-30",
        "progress": 0, "openedBy": {"account": "admin", "avatar": "", "realname": "管理员"},
        "openedDate": "2026-01-01T00:00:00Z",
    }],
}, ensure_ascii=False)

EXECUTIONS_JSON = json.dumps({
    "page": 1, "total": 1, "limit": 20,
    "executions": [{
        "id": 11, "name": "迭代一", "project": 1, "code": "", "type": "sprint", "parent": 0,
        "begin": "2026-01-01", "end": "2026-01-14", "status": "doing", "progress": 50,
        "isParent": False, "openedBy": "admin",
    }],
}, ensure_ascii=False)

TASKS_JSON = json.dumps({
    "page": 1, "total": 1, "limit": 20,
    "tasks": [{
        "id": 101, "name": "搭脚手架", "execution": 11, "project": 1, "status": "doing",
        "pri": 3, "assignedTo": {"account": "admin", "avatar": "", "realname": "管理员"},
        "estimate": 8, "consumed": 2, "left": 6, "deadline": "2026-01-10",
    }],
}, ensure_ascii=False)

FULL_ROUTES = {
    "/api.php/v1/projects": (200, PROJECTS_JSON),
    "/api.php/v1/executions": (200, EXECUTIONS_JSON),
    "/api.php/v1/tasks": (200, TASKS_JSON),
}


# ── 桩服务 ──────────────────────────────────────────────────────────────────
def _make_handler(routes: dict, seen: list) -> type:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            seen.append((method, self.path))
            if method != "GET":
                self.send_response(405)
                self.end_headers()
                return
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"404 Not Found"}')
                return
            status, body = route
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 的名字
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def log_message(self, *args: object) -> None:
            pass

    return Handler


@contextlib.contextmanager
def stub_server(routes: dict) -> Iterator[tuple[str, list]]:
    seen: list = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(routes, seen))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://127.0.0.1:{port}", seen
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    """拿一个**没人监听**的本机端口（绑一下即关）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def run_tool(
    args: list[str], base: str | None, token: str | None = "tok",
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ZENTAO_URL", None)
    env.pop("ZENTAO_TOKEN", None)
    if base is not None:
        env["ZENTAO_URL"] = base
    if token is not None:
        env["ZENTAO_TOKEN"] = token
    return subprocess.run(
        [*TOOL, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT), timeout=60,
    )


# ── 1. 字段映射 ─────────────────────────────────────────────────────────────
def test_maps_project_execution_task_fields() -> None:
    with stub_server(FULL_ROUTES) as (base, seen):
        got = run_tool(["--json"], base)
        assert got.returncode == 0, got.stderr
        assert {m for m, _ in seen} == {"GET"}, f"只读桥只许发 GET，实发：{seen}"
    bundle = json.loads(got.stdout)
    assert bundle["ok"] is True
    proj = bundle["projects"][0]
    assert proj["id"] == 1 and proj["name"] == "示例项目" and proj["status"] == "wait"
    assert proj["PM"] == "admin", "用户对象要压成 account"
    exe = bundle["executions"][0]
    assert exe["id"] == 11 and exe["project"] == 1 and exe["isParent"] is False
    task = bundle["tasks"][0]
    assert task["id"] == 101 and task["assignedTo"] == "admin" and task["estimate"] == 8
    assert set(task) == {"id", "name", "execution", "project", "status", "pri",
                         "assignedTo", "estimate", "consumed", "left", "deadline"}


# ── 2. 反例：连不上 ─────────────────────────────────────────────────────────
def test_connect_refused_is_reported_clearly() -> None:
    base = f"http://127.0.0.1:{_closed_port()}"
    got = run_tool(["--report"], base)
    assert got.returncode == 3, f"连不上应退 3，实为 {got.returncode}\n{got.stderr}"
    assert "连不上" in got.stderr and "projects" in got.stderr, got.stderr


# ── 3. 反例：401 / 403 ──────────────────────────────────────────────────────
def test_http_401_is_reported() -> None:
    routes = {"/api.php/v1/projects": (401, '{"error":"Unauthorized"}')}
    with stub_server(routes) as (base, _):
        got = run_tool(["--json"], base)
    assert got.returncode == 4, f"401 应退 4，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "http" and err["step"] == "projects" and "401" in err["detail"]


def test_http_403_is_reported() -> None:
    routes = {"/api.php/v1/projects": (403, '{"error":"Access not allowed"}')}
    with stub_server(routes) as (base, _):
        got = run_tool(["--json"], base)
    assert got.returncode == 4, f"403 应退 4，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    assert "403" in json.loads(got.stdout)["error"]["detail"]


# ── 4. 反例：坏 JSON ────────────────────────────────────────────────────────
def test_bad_json_is_reported() -> None:
    routes = {"/api.php/v1/projects": (200, "<html>not json</html>")}
    with stub_server(routes) as (base, _):
        got = run_tool(["--json"], base)
    assert got.returncode == 5, f"坏 JSON 应退 5，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "badjson" and err["step"] == "projects"


# ── 5. 反例：缺必需字段 ─────────────────────────────────────────────────────
def test_missing_required_field_is_reported() -> None:
    bad = json.dumps({"page": 1, "total": 1, "limit": 20, "projects": [{"id": 2}]})
    routes = {"/api.php/v1/projects": (200, bad)}
    with stub_server(routes) as (base, _):
        got = run_tool(["--json"], base)
    assert got.returncode == 6, f"缺字段应退 6，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "badshape" and "name" in err["detail"]


# ── 6. 幂等：同一份 fixture 连跑两次 --json 逐字节相同 ──────────────────────
def test_json_is_byte_identical_across_runs() -> None:
    with stub_server(FULL_ROUTES) as (base, _):
        first = run_tool(["--json"], base)
        second = run_tool(["--json"], base)
    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout, "同一份输入两次 --json 必须逐字节相同"


# ── 7. 配置缺失：没有 token 也要报清楚（别当成拉到了空）────────────────────
def test_missing_token_is_config_error() -> None:
    with stub_server(FULL_ROUTES) as (base, _):
        got = run_tool(["--json"], base, token=None)
    assert got.returncode == 2, f"缺 token 应退 2，实为 {got.returncode}\n{got.stdout}{got.stderr}"
    err = json.loads(got.stdout)["error"]
    assert err["kind"] == "config" and err["step"] == "token"
