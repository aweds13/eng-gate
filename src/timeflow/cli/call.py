"""取数层：**进程内调 HTTP 边界**（不起服务、不占端口）。

为什么不直接调 `core/`（少一层看起来更简单）：`api/app.py` 是**唯一的边界** ——
参数校验（`days` 越界 = 400）、字段形状、错误码都在那里。CLI 直接调 core 就得把那些
再写一遍，那正是"四个面各写一遍"的老路（T-G30 §4.2）。

所以这里走的是**同一个 `create_app()`、同一套路由**，只把 socket 换成直接调用 ASGI 应用：
- 不起 uvicorn、不绑端口（不会和正在跑的窗口抢 8520）；
- 库路径与桌面端同源（`config.toml` 里那个；`--db` 可覆盖）；
- 只读命令发的是 `GET`，所以不存在"写到一半"的问题。

## 环境错也要翻译（T-G66）

"只读"不只是"不发写请求"，还包括**不留副作用**：库文件不存在时**拒绝工作**，不替用户建一个空库
（打错路径就会得到一份"看起来正常"的空数据），也不把 `sqlite3` 的栈丢给用户。
三类都翻成 `DatabaseError`（带稳定 code，退 3）：`db_missing` / `db_unopenable`。

**诚实记两条边界**：① 局域网配对门在这条路上不生效（来源写死回环，而回环本来就是放行的那一类）；
② 这里不经过真实网络栈，如果哪天有中间件依赖 `request.url` 的 host/port 细节，行为可能与真机不同
—— 目前没有任何中间件这样用。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

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


class DatabaseError(RuntimeError):
    """库本身有问题（不存在 / 打不开 / 不是数据库）—— 环境错，退 3。

    为什么单独一类、还要带 `code`：这是**用户能自己修**的那类错，所以要一句"怎么办"，
    而且要**稳定的机器码**（脚本/AI 靠它分派），不是一坨栈。
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _is_environment_error(exc: BaseException) -> bool:
    """这个异常是"环境坏了"还是"代码有 bug"？

    只把两族算环境错：`OSError`（权限/路径/磁盘）与 `sqlite3.*`
    （库损坏、不是数据库、结构不对）。其余一律**原样抛出** —— 代码 bug 不该被
    伪装成"你的库有问题"，那会把排查方向带偏。

    为什么按 `__module__` 判而不是 import sqlite3：CLI 这一层**不许碰数据库**
    （`tests/test_cli_line.py` 扫 import 钉着这条），这里只翻译错误、不开库。
    """
    return isinstance(exc, OSError) or type(exc).__module__.split(".")[0] == "sqlite3"


def _as_environment_error(exc: BaseException, db_path: str) -> DatabaseError:
    """把环境错翻成 `DatabaseError`（带上那句话与怎么办）。"""
    return DatabaseError(
        "db_unopenable",
        f"库打不开：{db_path}（{type(exc).__name__}: {exc}）"
        " —— 如果是文件坏了，用设置页的「备份与恢复」换一个备份。",
    )


async def _exchange(app: Any, scope: dict[str, Any], body: bytes = b"") -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


def _scope(
    method: str, path: str, query: str, body: bytes = b""
) -> dict[str, Any]:
    headers: list[tuple[bytes, bytes]] = [(b"host", b"127.0.0.1")]
    if body:
        headers += [(b"content-type", b"application/json")]
        headers += [(b"content-length", str(len(body)).encode())]
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
        "headers": headers,
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


def call_route(
    db_path: str,
    route: str,
    params: dict[str, str] | None = None,
    *,
    path_params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    """按命令表里的 `"GET /api/…"` 调一次，返回解析后的 JSON。

    三处参数各去各的地方（**不猜**）：`params` → query、`path_params` → URL 里的 `{名字}`、
    `body` → JSON body（写操作用）。错误一律抛 `ApiError` / `DatabaseError` ——
    CLI 层把它们翻成稳定错误码与退出码。
    """
    method, _, raw_path = route.partition(" ")
    path = raw_path
    for name, value in (path_params or {}).items():
        path = path.replace("{" + name + "}", quote(str(value), safe=""))
    if "{" in path:  # 路径参数没给全：这是**用法错**（在真发请求之前拦住）
        missing = path[path.index("{") + 1 : path.index("}")]
        raise ValueError(f"这条路由要一个路径参数 {missing}")
    query = urlencode({k: v for k, v in (params or {}).items() if v != ""})
    payload = b""
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    # ★ 只读命令**不许建库**：库不存在就说库不存在。
    #   不查这一下会怎样（T-G66 真踩到）：打错路径 → SQLite 默默建一个空库 →
    #   回一份"看起来正常"的空数据（0 分钟 / 0 项），而用户以为在看自己的账。
    #   一个"只读"命令还留下一个文件副作用 —— 两件都不该发生。
    #   ★ T-G65：写命令**同样**要过这一关 —— "我要写"不等于"你可以替我建一个空库"：
    #     路径打错时宁可退 3，也不要凭空造一份新数据出来。
    if not Path(db_path).is_file():
        raise DatabaseError(
            "db_missing",
            f"库文件不存在：{db_path} —— 先运行 timeflow 开一次窗口建库，或用 --db 指向已有的库。",
        )
    # `allow_lan=False`：CLI 是本机读写，不该因为库里开了局域网而变成"对外服务"
    # ★ 两处都要兜：库是**懒连接**的（`db.thread_local` 在第一次用到时才真打开），
    #   所以"文件不是数据库"这类错常常在**请求里**才炸出来，而不是在 create_app 那一步
    #   —— 第一版只兜了 create_app，实测照样把 `sqlite3.DatabaseError` 的栈丢给用户。
    messages: list[dict[str, Any]] = []
    try:
        app = create_app(db_path, allow_lan=False)
        scope = _scope(method.upper(), path, query, payload)
        messages = asyncio.run(_exchange(app, scope, payload))
    except Exception as exc:  # noqa: BLE001 —— 只有 _is_environment_error 为真时才翻译
        if _is_environment_error(exc):
            raise _as_environment_error(exc, db_path) from exc
        raise
    status, raw = _body(messages)
    if status >= 400:
        raise ApiError(status, _detail(raw))
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))
