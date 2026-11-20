r"""号池 MCP 的 HTTP 传输 —— **按路径挂载**（卡 A378 · T-AG666）的测试。

判据表见卡规格 `复盘/卡/卡A378-F59三个自带MCP-server-按路径挂载.md`；这里只写**会失败**的断言。
★ 全部走**真 socket**（`build_server` 起在后台线程），不桩 `http.server`。
★ 导入口径同 `tests/test_pool_mcp_http.py`：先把 `tools/` 挂上 `sys.path`。

## 钉什么

| 判据 | 钉子 |
|---|---|
| 1 | `test_unmounted_path_is_404_and_never_executes`：未挂载 **404**、handle 不执行 |
| 2 | `test_each_mounted_path_has_its_own_limit`：每路径**各自**一个上限 |
| 3 | `test_mounted_path_get_is_still_405_with_allow`：已挂载 GET 仍 405 + `Allow` |
| 4 | `test_single_element_batch_is_still_400_on_mounted_path`：不收 batch |
| 5 | `test_http_layer_still_has_no_shift_literal`：传输层零移位字面量 |
| 6 | `test_three_capability_surfaces_are_absent`：三个能力面**不在**本仓 |
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_mcp  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
from pool import mcp_http  # noqa: E402
from test_pool_mcp import TOOL_NAMES  # noqa: E402 —— 十三项固定名单只有一份

TOKEN = "unit-test-token"

#: magpie 的六个工具名（`_magpie_features.md:507`）；本卡判它们**不在**。
MAGPIE_TOOL_NAMES = (
    "web_search",
    "web_fetch",
    "analyze_image",
    "generate_image",
    "generate_video",
    "generation_result",
)


# ---------------------------------------------------------------- 小工具


class _Stub:
    """记下每一笔 `handle()` 调用，并按预设回一条（`None` = 通知）。"""

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = answer

    def __call__(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(message)
        return self.answer


class _Echo(_Stub):
    """按请求的 `id` 回一条（判 `/big` 那一枪真被执行了、且回的是这笔的回话）。"""

    def __call__(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(message)
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {}}


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
    path: str = "/",
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
        conn.request("POST", path, body=payload, headers=merged)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def _request(
    port: int, method: str, path: str, *, timeout: float = 10.0
) -> tuple[int, dict[str, str], bytes]:
    """不带体的一条请求（GET / DELETE 这类：判路径挂载用）。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request(method, path, headers={"Authorization": f"Bearer {TOKEN}"})
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
    """起一条真服务在后台线程；`port=0` 由内核挑。`mounts` 原样透传。"""
    started: list[tuple[mcp_http._Server, threading.Thread]] = []

    def _start(
        handle: mcp_http.Handle,
        *,
        max_bytes: int = 4096,
        mounts: dict[str, int] | None = None,
        protocols: tuple[str, ...] = ("2025-03-26", "2025-06-18"),
    ) -> int:
        server = mcp_http.build_server(
            handle,
            host="127.0.0.1",
            port=0,
            token=TOKEN,
            max_bytes=max_bytes,
            protocols=protocols,
            mounts=mounts,
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


# ---------------------------------------------------------------- 判据 1：未挂载路径 404


def test_unmounted_path_is_404_and_never_executes(start_server: Any) -> None:
    """未挂载路径 ⇒ 404 且**一次都不执行** —— 今天这笔返回 200 并交给了 handle。"""
    stub = _Stub(_ok())
    port = start_server(stub, mounts={"/": 4096})
    status, _, data = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                            path="/mcp/magpie/not-mine")
    assert status == 404, data
    assert stub.calls == [], "404 的请求体一个字节都不许执行"
    # 先路径、后方法：未挂载路径不论 GET 还是 POST 都是 404（不是 405）
    for method in ("GET", "DELETE", "PUT", "PATCH"):
        status, _, _ = _request(port, method, "/mcp/magpie/not-mine")
        assert status == 404, method
    assert stub.calls == []
    # 已挂载的那条路径照样干活
    assert _post(port, {"jsonrpc": "2.0", "id": 2, "method": "ping"})[0] == 200
    assert len(stub.calls) == 1


# ---------------------------------------------------------------- 判据 2：每路径各自一个上限


def test_each_mounted_path_has_its_own_limit(start_server: Any) -> None:
    """`/small` 与 `/big` 各自一个上限：同一个 2048 一个 413、一个 200。"""
    stub = _Echo()
    port = start_server(stub, mounts={"/small": 1024, "/big": 4096})
    message = {"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {"pad": ""}}
    pad = 2048 - len(json.dumps(message, ensure_ascii=False).encode())
    message["params"]["pad"] = "x" * pad
    payload = json.dumps(message, ensure_ascii=False).encode()
    assert len(payload) == 2048, len(payload)

    status, _, data = _post(port, payload, path="/small")
    assert status == 413, data
    text = data.decode("utf-8")
    # ★ 413 正文里的数字必须是**该路径自己的**上限（今天两条路径共用同一个数）
    assert "1024" in text, text
    assert "2048" in text, text
    assert stub.calls == []

    status, _, data = _post(port, payload, path="/big")
    assert status == 200, data
    assert json.loads(data)["id"] == 5
    assert len(stub.calls) == 1


# ---------------------------------------------------------------- 判据 3：/ 的既有行为不改


def test_mounted_path_get_is_still_405_with_allow(start_server: Any) -> None:
    """已挂载路径的 GET ⇒ 405 且 `Allow: POST`（与 `/` 的读法同一条）。"""
    port = start_server(_Stub(_ok()), mounts={"/": 4096, "/mcp/magpie/web-search": 4096})
    for path in ("/", "/mcp/magpie/web-search"):
        status, headers, _ = _request(port, "GET", path)
        assert status == 405, path
        assert _header(headers, "Allow") == "POST"


# ---------------------------------------------------------------- 判据 4：不搬 batch / 不加会话


def test_single_element_batch_is_still_400_on_mounted_path(start_server: Any) -> None:
    """已挂载路径上，单元素数组（magpie 的 batch 形状）仍是 400，且一个字节都不执行。"""
    stub = _Stub(_ok())
    port = start_server(stub, mounts={"/": 4096, "/mcp/magpie/web-search": 4096})
    payload = [{"jsonrpc": "2.0", "id": 8, "method": "ping"}]
    for path in ("/", "/mcp/magpie/web-search"):
        status, headers, _ = _post(port, payload, path=path)
        assert status == 400, (path, status)
        assert _header(headers, "Mcp-Session-Id") is None
    assert stub.calls == []
    status, headers, _ = _post(port, {"jsonrpc": "2.0", "id": 9, "method": "ping"},
                               path="/mcp/magpie/web-search")
    assert status == 200
    assert _header(headers, "Mcp-Session-Id") is None
    assert len(stub.calls) == 1


# ---------------------------------------------------------------- 判据 5：上限来源仍只有一处


def test_http_layer_still_has_no_shift_literal() -> None:
    """传输层**零**移位字面量：上限只能由调用方给（判据 2 的反向护栏）。"""
    source = (ROOT / "tools/pool/mcp_http.py").read_text(encoding="utf-8")
    assert "<<" not in source
    assert "32 << 20" not in source
    assert "32<<20" not in source
    # 缺省挂载点就是 "/"，既有调用方（只传 max_bytes）行为不变
    assert mcp_http.DEFAULT_PATH == "/"
    assert dict(mcp_http.mount_table(1024, None)) == {"/": 1024}


# ---------------------------------------------------------------- 判据 6：三个能力面不在


def test_three_capability_surfaces_are_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个能力面钉在「不在」：工具名单、源码缺席、零开放世界标记。"""
    monkeypatch.delenv(pool_mcp.WRITE_ENV, raising=False)
    names = [tool["name"] for tool in pool_mcp.tool_list()]
    assert names == TOOL_NAMES
    assert not any(name in TOOL_NAMES for name in MAGPIE_TOOL_NAMES), names

    # ★ 只认**整名**（词边界）：卡 A385 落的 searcher.py 里写的是上游那个响应类型
    #   `web_search_tool_result`（`server_tool_use` 的配对项，见 gateway 的七值分类），
    #   它是**读到**的名字、不是**注册**的能力面。整名前缀撞车的两件事本来就不同，
    #   拿全文子串扫会把「不许实现搜索」变成「不许提上游协议」，那是另一条判据。
    pattern = re.compile(r"\b(?:web_search|analyze_image|generate_image)\b")
    assert pattern.search('{"name": "web_search"}'), "整名扫不到裸名字 —— 判据失效，不是绿"
    assert not pattern.search("web_search_tool_result"), "词边界失效 —— 判据会被前缀撞红"
    files = [
        path
        for root in ("tools", "src")
        for path in (ROOT / root).rglob("*.py")
        if path.is_file()
    ]
    assert files, "两个根一个 .py 都没扫到 —— 判据失效，不是绿"
    hits = [str(path.relative_to(ROOT)) for path in files
            if pattern.search(path.read_text(encoding="utf-8"))]
    assert hits == []

    assert [tool["name"] for tool in pool_mcp.tool_list()
            if tool.get("annotations", {}).get("openWorldHint")] == []
