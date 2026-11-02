r"""号池 MCP 的 **HTTP 传输**（卡 A365 · T-AG584）测试 —— 八条判据各至少一条钉子。

判据表见卡规格 `复盘/卡/卡A365-MCP只能在同机stdio里用.md`；这里只写**会失败**的断言。
★ 全部走**真 socket**（`build_server` 起在后台线程 / 子进程真起服务），不桩 `http.server`。
★ 导入口径同 `tests/test_pool_mcp.py`：先把 `tools/` 挂上 `sys.path`。
"""

from __future__ import annotations

import ast
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_mcp  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
from pool import mcp_http  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起子进程必须带（卡 148）

TOKEN = "unit-test-token"
E2E_TOKEN = "e2e-token-9527"


# ---------------------------------------------------------------- 小工具


class _Stub:
    """记下每一笔 `handle()` 调用，并按预设回一条（`None` = 通知）。"""

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = answer

    def __call__(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(message)
        return self.answer


def _ok(mid: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": {}}


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _post(
    port: int,
    body: object,
    *,
    token: str | None = TOKEN,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, str], bytes]:
    payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    merged = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    merged.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", "/", body=payload, headers=merged)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def _free_port() -> int:
    """由内核分配一个空口（卡 E73：不许写死端口）。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def start_server():
    """起一条真服务在后台线程；`port=0` 由内核挑。"""
    started: list[tuple[mcp_http._Server, threading.Thread]] = []

    def _start(
        handle: mcp_http.Handle,
        *,
        max_bytes: int = 4096,
        origins: tuple[str, ...] = (),
        require_origin: bool = False,
        protocols: tuple[str, ...] = ("2025-03-26", "2025-06-18"),
    ) -> int:
        server = mcp_http.build_server(
            handle,
            host="127.0.0.1",
            port=0,
            token=TOKEN,
            origins=origins,
            max_bytes=max_bytes,
            protocols=protocols,
            require_origin=require_origin,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return int(server.server_address[1])

    yield _start
    for server, thread in started:
        server.shutdown()
        server.server_close()
        thread.join(5)


# ---------------------------------------------------------------- 判据 1：判据只许一份


def test_handle_is_injected_not_reimplemented(start_server: Any) -> None:
    message = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    stub = _Stub({"jsonrpc": "2.0", "id": 7, "result": {"echo": True}})
    port = start_server(stub)
    status, headers, data = _post(port, message)
    assert status == 200
    assert _header(headers, "Content-Type") == "application/json"
    assert stub.calls == [message], "HTTP 层必须把原样消息交给传进来的 handle，不自己分发"
    assert json.loads(data) == {"jsonrpc": "2.0", "id": 7, "result": {"echo": True}}


def test_http_module_does_not_import_pool_mcp() -> None:
    tree = ast.parse((ROOT / "tools/pool/mcp_http.py").read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert not any("pool_mcp" in name for name in modules), modules


# ---------------------------------------------------------------- 判据 2：Origin


def test_origin_not_in_whitelist_is_403_and_never_executes(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub, origins=("http://example.test",))
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"Origin": "http://evil.test"})
    assert status == 403
    assert stub.calls == [], "403 的请求体一个字节都不许执行"


def test_origin_whitelisted_and_loopback_are_allowed(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub, origins=("http://example.test",))
    assert _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 headers={"Origin": "http://example.test"})[0] == 200
    assert _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                 headers={"Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert _post(port, {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                 headers={"Origin": f"http://localhost:{port}"})[0] == 200
    assert len(stub.calls) == 3


def test_missing_origin_is_allowed_unless_required(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    assert _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 200
    port = start_server(stub, require_origin=True)
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert status == 403, "TF_MCP_HTTP_REQUIRE_ORIGIN=1 时没头也必须拒"
    assert len(stub.calls) == 1


# ---------------------------------------------------------------- 判据 3：只绑回环


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "*"])
def test_build_server_rejects_non_loopback(host: str) -> None:
    with pytest.raises(mcp_http.ConfigError):
        mcp_http.build_server(
            _Stub(_ok()), host=host, port=0, token=TOKEN, max_bytes=1024,
            protocols=("2025-03-26",),
        )


def test_cli_rejects_non_loopback_host() -> None:
    env = {**os.environ, "TF_MCP_HTTP_TOKEN": TOKEN}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool_mcp.py"),
         "--http", "--host", "0.0.0.0", "--port", "0"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, **NO_WINDOW,
    )
    assert proc.returncode == 2
    assert "回环" in proc.stderr


# ---------------------------------------------------------------- 判据 4：鉴权


def test_build_server_requires_token() -> None:
    with pytest.raises(mcp_http.ConfigError) as info:
        mcp_http.build_server(
            _Stub(_ok()), port=0, token="", max_bytes=1024, protocols=("2025-03-26",),
        )
    assert "TF_MCP_HTTP_TOKEN" in str(info.value)


def test_cli_refuses_to_start_without_token() -> None:
    env = {key: value for key, value in os.environ.items() if key != "TF_MCP_HTTP_TOKEN"}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool_mcp.py"),
         "--http", "--port", "0"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, **NO_WINDOW,
    )
    assert proc.returncode == 2
    assert "TF_MCP_HTTP_TOKEN" in proc.stderr
    assert "Authorization: Bearer" in proc.stderr


def test_missing_or_wrong_token_is_401(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    status, headers, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)
    assert status == 401
    assert _header(headers, "WWW-Authenticate") == "Bearer"
    assert _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"}, token="wrong")[0] == 401
    assert stub.calls == []
    assert _post(port, {"jsonrpc": "2.0", "id": 3, "method": "ping"})[0] == 200
    assert len(stub.calls) == 1


def test_bearer_comparison_uses_compare_digest() -> None:
    """★ 语义钉（不是行为钉）：`bearer_ok` 的函数体里必须是 `hmac.compare_digest`，
    且**不许**出现 `==`（AST 的 `Compare(Eq)` —— docstring 里提一句不算数）。"""
    source = (ROOT / "tools/pool/mcp_http.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    bearer = next(node for node in funcs if node.name == "bearer_ok")
    body_source = ast.get_source_segment(source, bearer) or ""
    assert "hmac.compare_digest" in body_source
    equalities = [
        node for node in ast.walk(bearer)
        if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq) for op in node.ops)
    ]
    assert equalities == [], "Bearer 比对不许用裸等号（必须 hmac.compare_digest）"


# ---------------------------------------------------------------- 判据 5：三态与 GET


def test_notification_is_202_with_empty_body(start_server: Any) -> None:
    stub = _Stub(None)
    port = start_server(stub)
    status, headers, data = _post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202
    assert data == b""
    assert _header(headers, "Content-Length") == "0"
    assert _header(headers, "Content-Type") is None
    assert len(stub.calls) == 1


def test_request_is_200_json(start_server: Any) -> None:
    port = start_server(_Stub(_ok(9)))
    status, headers, data = _post(port, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert status == 200
    assert _header(headers, "Content-Type") == "application/json"
    assert json.loads(data)["id"] == 9


def test_get_and_delete_are_405(start_server: Any) -> None:
    port = start_server(_Stub(_ok()))
    for method in ("GET", "DELETE"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, "/")
            response = conn.getresponse()
            assert response.status == 405, method
            assert _header(dict(response.getheaders()), "Allow") == "POST"
            response.read()
        finally:
            conn.close()


def test_accept_without_json_or_sse_is_406(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"Accept": "text/html"})
    assert status == 406
    assert stub.calls == []


# ---------------------------------------------------------------- 判据 6：版本头


def test_missing_version_header_is_assumed_and_known_one_passes(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    assert _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 200
    assert _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                 headers={"MCP-Protocol-Version": "2025-03-26"})[0] == 200
    assert len(stub.calls) == 2


def test_unknown_version_header_is_400(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"MCP-Protocol-Version": "1999-01-01"})
    assert status == 400
    assert stub.calls == []


# ---------------------------------------------------------------- 判据 7：无会话 / 上限 / 坏消息


def test_no_session_header_in_response(start_server: Any) -> None:
    port = start_server(_Stub(_ok()))
    _, headers, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert _header(headers, "Mcp-Session-Id") is None


def test_request_with_session_header_is_still_processed(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"Mcp-Session-Id": "abc123"})
    assert status == 200, "不认识 ≠ 拒收"
    assert len(stub.calls) == 1


def test_declared_oversize_body_is_413_and_not_read(start_server: Any) -> None:
    stub = _Stub(_ok())
    port = start_server(stub, max_bytes=1024)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("POST", "/")
        conn.putheader("Authorization", f"Bearer {TOKEN}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(1024 + 1))
        conn.endheaders()  # ★ 一个字节也不发：实现若"整份 read()"就会挂住，这里 5 秒超时判红
        response = conn.getresponse()
        assert response.status == 413
        response.read()
    finally:
        conn.close()
    assert stub.calls == []


def test_read_body_is_chunked_never_whole() -> None:
    class _Stream:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload
            self.calls: list[int | None] = []

        def read(self, size: int | None = None) -> bytes:
            self.calls.append(size)
            chunk, self.payload = self.payload[:size], self.payload[size:]
            return chunk

    stream = _Stream(b"x" * 1000)
    assert mcp_http.read_body(stream, max_bytes=4096, length=1000) == b"x" * 1000
    assert stream.calls
    assert all(size is not None and size <= mcp_http.CHUNK_BYTES for size in stream.calls)


def test_read_body_does_not_touch_stream_when_declared_too_large() -> None:
    class _NeverRead:
        def read(self, size: int | None = None) -> bytes:
            raise AssertionError("声明就超限时不许读请求体")

    with pytest.raises(mcp_http.BodyTooLarge):
        mcp_http.read_body(_NeverRead(), max_bytes=1024, length=1025)


@pytest.mark.parametrize("payload", [b"\xff\xfe", b"{", b"[]"])
def test_bad_body_is_400_and_service_continues(start_server: Any, payload: bytes) -> None:
    stub = _Stub(_ok())
    port = start_server(stub)
    status, _, _ = _post(port, payload)
    assert status == 400, payload
    assert stub.calls == []
    status, _, _ = _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert status == 200


def test_http_layer_has_no_second_copy_of_the_32mib_literal() -> None:
    source = (ROOT / "tools/pool/mcp_http.py").read_text(encoding="utf-8")
    assert "32 << 20" not in source
    assert "32<<20" not in source


# ---------------------------------------------------------------- 判据 8：端到端真跑


def _wait_ready(proc: subprocess.Popen[str], port: int, deadline: float = 20.0) -> None:
    end = time.time() + deadline
    while time.time() < end:
        if proc.poll() is not None:
            _, err = proc.communicate(timeout=5)
            raise AssertionError(f"服务提前退出 rc={proc.returncode}\n{err}")
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError("服务 20 秒内没起来")


@pytest.fixture
def real_http() -> Any:
    """真起子进程 `pool_mcp.py --http --port <内核分配的空口>`。"""
    port = _free_port()
    env = {
        key: value for key, value in os.environ.items()
        if key not in ("POOL_MCP_WRITE", "TF_MCP_HTTP_ORIGINS", "TF_MCP_HTTP_REQUIRE_ORIGIN")
    }
    env["TF_MCP_HTTP_TOKEN"] = E2E_TOKEN
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pool_mcp.py"),
         "--http", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **NO_WINDOW,
    )
    try:
        _wait_ready(proc, port)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:  # pragma: no cover —— 兜底
            proc.kill()
            proc.wait(5)


def test_real_socket_initialize_list_and_call(real_http: int, monkeypatch: Any) -> None:
    monkeypatch.delenv("POOL_MCP_WRITE", raising=False)
    port = real_http
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "a365", "version": "1"}},
    }
    status, headers, data = _post(port, init, token=E2E_TOKEN)
    assert status == 200
    assert (_header(headers, "Content-Type") or "").startswith("application/json")
    assert _header(headers, "Mcp-Session-Id") is None
    text = data.decode("utf-8")
    answer = json.loads(text)
    assert answer["id"] == 1
    expected = pool_mcp.handle(init)
    assert expected is not None
    assert answer["result"]["instructions"] == expected["result"]["instructions"]
    assert "号池" in text, "中文必须原样回来（乱码时这里会红）"

    status, _, data = _post(port, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            token=E2E_TOKEN)
    assert status == 200
    listed = json.loads(data)["result"]["tools"]
    assert len(listed) == len(pool_mcp.tool_list()), "tools/list 的个数要与 stdio 口径一致"

    call = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "job_list", "arguments": {}},
    }
    status, _, data = _post(port, call, token=E2E_TOKEN)
    assert status == 200
    answer = json.loads(data)
    assert answer["id"] == 3
    assert "error" not in answer
    assert answer["result"]["content"][0]["text"].strip()
