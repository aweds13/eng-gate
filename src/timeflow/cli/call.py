"""取数层：**进程内调 HTTP 边界**（不起服务、不占端口）。

为什么不直接调 `core/`（少一层看起来更简单）：`api/app.py` 是**唯一的边界** ——
参数校验（`days` 越界 = 400）、字段形状、错误码都在那里。CLI 直接调 core 就得把那些
再写一遍，那正是"四个面各写一遍"的老路（T-G30 §4.2）。

所以这里走的是**同一个 `create_app()`、同一套路由**，只把 socket 换成直接调用 ASGI 应用：
- 不起 uvicorn、不绑端口（不会和正在跑的窗口抢 8520）；
- 库路径与桌面端同源（`config.toml` 里那个；`--db` 可覆盖）；
- 只读命令发的是 `GET`，所以不存在"写到一半"的问题。

**诚实记两条边界**（见复盘 §6）：① 局域网配对门在这条路上不生效（来源写死回环，
而回环本来就是放行的那一类）；② 这里不经过真实网络栈，如果哪天有中间件依赖
`request.url` 的 host/port 细节，行为可能与真机不同 —— 目前没有任何中间件这样用。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlencode

from timeflow.api.app import create_app

# 来源写死回环：与桌面窗口自己走回环同一个口径（CLI 是本机读，不是给别人连的服务）
LOCAL_CLIENT = ("127.0.0.1", 0)
LOCAL_SERVER = ("127.0.0.1", 8520)


class ApiError(RuntimeError):
    """边界回了一个错误状态码（4xx/5xx）—— 带上状态码，CLI 才能给稳定错误码。"""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


async def _exchange(app: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


def _scope(method: str, path: str, query: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "client": LOCAL_CLIENT,
        "server": LOCAL_SERVER,
        "root_path": "",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "headers": [(b"host", b"127.0.0.1")],
    }


def _body(messages: list[dict[str, Any]]) -> tuple[int, bytes]:
    status = 0
    chunks: list[bytes] = []
    for message in messages:
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            raw = message.get("body") or b""
            chunks.append(raw if isinstance(raw, bytes) else bytes(raw))
    return status, b"".join(chunks)


def _detail(raw: bytes) -> str:
    """从错误响应体里取那句人话（FastAPI 的形状是 `{"detail": …}`）。"""
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except ValueError:
        return text or "（没有响应体）"
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return text


def call_route(db_path: str, route: str, params: dict[str, str] | None = None) -> Any:
    """按命令表里的 `"GET /api/…"` 调一次，返回解析后的 JSON。

    错误一律抛 `ApiError`（带状态码）—— CLI 层把它翻成稳定错误码与退出码。
    """
    method, _, path = route.partition(" ")
    query = urlencode({k: v for k, v in (params or {}).items() if v != ""})
    # `allow_lan=False`：CLI 是本机读，不该因为库里开了局域网而变成"对外服务"
    app = create_app(db_path, allow_lan=False)
    messages = asyncio.run(_exchange(app, _scope(method.upper(), path, query)))
    status, raw = _body(messages)
    if status >= 400:
        raise ApiError(status, _detail(raw))
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))
