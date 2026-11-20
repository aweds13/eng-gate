r"""号池 MCP 的 **Streamable HTTP 传输**（卡 A365 · 台账号 T-AG584）—— 只用标准库。

## 为什么有它

`tools/pool_mcp.py` 原先**只有 stdio**：客户端必须在本机起子进程，手机 / 平板 / 另一台电脑
都接不进来。这一层把**同一条 JSON-RPC 消息**从 HTTP 请求体里取出来，交给**调用方传进来的**
`handle()`，再把回话写成 HTTP 响应 —— **判据一条都不重写**。

★ **不 import `pool_mcp`**（依赖反向注入）：`handle` / `max_bytes` / `protocols` 全是参数。
这样 `pool_mcp` 可以 import 本模块而不成环，本模块也能单独测（桩一个 `handle` 就够）。

## 协议口径（MCP Transports 2025-06-18，逐条落在判据里）

- **Origin（MUST）**：带 `Origin` 的请求必须命中白名单（`TF_MCP_HTTP_ORIGINS` ∪ 本机回环），
  否则 **403 且不执行**。**没有 `Origin` 放行** —— DNS rebinding 靠浏览器发起跨站请求，
  非浏览器客户端不带这个头；要更严就打开 `TF_MCP_HTTP_REQUIRE_ORIGIN=1`（这时没头也 403）。
- **只绑回环（SHOULD）**：只收 `127.0.0.1` / `localhost` / `::1`；别的值**退 2**，
  不给 `0.0.0.0` 开口子（要暴露交给隧道）。
- **鉴权（SHOULD）**：`TF_MCP_HTTP_TOKEN` 不设 ⇒ **拒绝启动**；`Authorization: Bearer <token>`
  用 `hmac.compare_digest` 比对，不符/缺失 ⇒ **401** + `WWW-Authenticate: Bearer`。
- **三态（MUST）**：通知 / 回话（无 `id`）⇒ **202 + 空 body**；request ⇒ **200 +
  `application/json`**；`GET` / `DELETE` ⇒ **405**（本服务不提供 SSE，也没有会话可终止）。
- **版本头（MUST）**：缺 `MCP-Protocol-Version` ⇒ 按 `2025-03-26` 假定（只是放行，不往
  `handle` 里塞）；给了但不在 `protocols` 里 ⇒ **400**。`protocols` 由调用方从 `pool_mcp`
  传进来，**这里不另写一份**。
- **无会话**：**不发** `Mcp-Session-Id`：`handle()` 本来就无状态，发了就要维护"终止后 404"
  那一套，本卡不做。**带了**这个头的请求照样处理（不认识 ≠ 拒收）。
- **有上限**：请求体上限**只**来自调用方 —— 每路径一个（`mounts`），缺省
  `{"/": max_bytes}`（`pool_mcp.MAX_LINE_BYTES`）；超限 ⇒ **413**，**按块读、不把整份吃进内存**。
- **按路径挂载**（卡 A378）：只服务调用方挂上去的路径（缺省 `/`），别的路径 **404 且不执行**
  —— **先路径、后方法**（同 `tools/pool/gateway.py` 的次序）；每条路径**各带自己的上限**，
  数值仍全部由调用方给，这一层一个上限字面量都不写。

**坏消息不打死服务**：非 UTF-8 / 非 JSON / 不是对象一律 **400**（不是 500），
连接关掉、服务继续接下一个。

## 边界（如实写）

- **不提供 SSE**：规范允许只回 `application/json`；要服务端推送事件的那套本卡不做。
- **不收 `Transfer-Encoding: chunked`**（没有 `Content-Length` ⇒ 411）：MCP 客户端都带长度，
  收分块就要自己维护解码状态，本卡不为它加复杂度。
- **无会话**：没有 `Mcp-Session-Id`、没有 `DELETE` 终止、没有断线续传。
"""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from collections.abc import Callable, Iterable, Mapping
    from typing import IO, Any

    Message = dict[str, Any]
    Handle = Callable[[Message], "Message | None"]

#: 默认只绑回环（规范 SHOULD；要暴露交给隧道，不在这里绑全网卡）。
DEFAULT_HOST = "127.0.0.1"
#: 默认端口（与 `wb_dash.py` 的 8787 错开）。
DEFAULT_PORT = 8765

#: `--host` 允许集：只收回环。★ 放宽到这里之外 = 把内网面全打开，卡规格明令禁止。
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Origin 白名单的额外项（逗号分隔）；默认项由实际监听端口现算。
ORIGINS_ENV = "TF_MCP_HTTP_ORIGINS"
#: 设成 `1` ⇒ 没有 `Origin` 头也 403（比规范更严）。
REQUIRE_ORIGIN_ENV = "TF_MCP_HTTP_REQUIRE_ORIGIN"
#: 鉴权 token 的环境变量名（不设 ⇒ 拒绝启动；**没有**默认放行路径）。
TOKEN_ENV = "TF_MCP_HTTP_TOKEN"

#: 版本头的缺省假定（规范：没带就按这个版本理解）。
DEFAULT_PROTOCOL = "2025-03-26"

#: 一次 `read()` 最多要多少字节 —— 超限时只读到上限附近就收手，不把整份请求吃进内存。
CHUNK_BYTES = 64 * 1024

#: 缺省挂载点（卡 A378）：只传 `max_bytes` 的既有调用方 ≡ 只挂这一条路径。
DEFAULT_PATH = "/"


class ConfigError(ValueError):
    """启动参数不能接受（主机不在回环集 / 没有 token）。命令壳据此**退 2**并印理由。"""


class BodyTooLargeError(Exception):
    """请求体超过上限：带**声明的字节数**（文案由 handler 组织）。"""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


#: 卡规格里的名字（`except BodyTooLarge`）。ruff `N818` 要求异常名带 `Error` 后缀 ⇒ 类名带后缀，
#: 再用这个别名把卡规格的名字挂回去。**同一个类**，不是第二个类型（钉子里用别名捕获，删了就红）。
BodyTooLarge = BodyTooLargeError


def split_origins(text: str | None) -> tuple[str, ...]:
    """`TF_MCP_HTTP_ORIGINS` 的逗号分隔值 → 元组（空项丢掉，保持原样比较）。"""
    if not text:
        return ()
    return tuple(item.strip() for item in text.split(",") if item.strip())


def require_origin_from_env(text: str | None) -> bool:
    """`TF_MCP_HTTP_REQUIRE_ORIGIN=1` ⇒ 没有 `Origin` 头也拒。"""
    return (text or "").strip() == "1"


def check_host(host: str) -> str:
    """只放行回环；别的值抛 `ConfigError`（文案里写清为什么不放）。"""
    value = (host or "").strip()
    if value not in ALLOWED_HOSTS:
        raise ConfigError(
            f"--host 只接受 127.0.0.1 / localhost / ::1，收到 {value!r}。"
            "本服务**不绑非回环地址**（不给 0.0.0.0 开口子）：要远程访问，"
            "请用 SSH / frp 这类隧道把它套在回环上。"
        )
    return value


def read_body(stream: IO[bytes], *, max_bytes: int, length: int) -> bytes:
    """按 `chunk` 读请求体；声明长度就超限 ⇒ 立刻 `BodyTooLarge`（**一个字节都不读**）。

    ★ 判据 7 的钉子就在这里：`length > max_bytes` 时直接抛；正常路径也只用
    `min(CHUNK_BYTES, 剩余)` 的**有界** `read()` —— 不许出现"整份 `read()`"。
    """
    if length < 0:
        raise ValueError(f"Content-Length 不能是负数：{length}")
    if length > max_bytes:
        raise BodyTooLarge(length)
    parts: list[bytes] = []
    total = 0
    while total < length:
        chunk = stream.read(min(CHUNK_BYTES, length - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:  # 防御：声明长度撒谎时也停在上限附近
            raise BodyTooLarge(total)
        parts.append(chunk)
    return b"".join(parts)


def bearer_ok(header: str | None, token: str) -> bool:
    """`Authorization: Bearer <token>` 的比对 —— ★ 一律 `hmac.compare_digest`（不用裸等号）。"""
    if not header:
        return False
    scheme, _, value = header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return False
    return hmac.compare_digest(value.strip().encode("utf-8"), token.encode("utf-8"))


def mount_table(max_bytes: int, mounts: Mapping[str, int] | None) -> Mapping[str, int]:
    """把调用方给的挂载映射归一成**冻结**的「路径 → 上限」表（卡 A378）。

    `mounts is None` ⇒ `{DEFAULT_PATH: max_bytes}` —— 只传 `max_bytes` 的既有调用方
    行为一字不变（`tests/test_pool_mcp_http.py` 的 25 条全打 `/`）。
    ★ 上限的**数字全部来自调用方**：这一层连一个上限字面量都不写（判据 5）。
    """
    if mounts is None:
        return MappingProxyType({DEFAULT_PATH: int(max_bytes)})
    table: dict[str, int] = {}
    for raw_path, raw_limit in mounts.items():
        path = urlsplit(raw_path).path.rstrip("/") or DEFAULT_PATH
        limit = int(raw_limit)
        if limit <= 0:
            raise ConfigError(f"路径 {raw_path!r} 的请求体上限必须为正数，收到 {raw_limit!r}。")
        if path in table:
            raise ConfigError(f"路径 {path!r} 挂了两次（归一化之后撞了）。")
        table[path] = limit
    if not table:
        raise ConfigError("mounts 不能是空表：至少挂一条路径（缺省用 / → max_bytes）。")
    return MappingProxyType(table)


class _Handler(BaseHTTPRequestHandler):
    """一条请求 → 一次判定 → 一条回话；所有协议细节都在这一层。"""

    protocol_version = "HTTP/1.1"
    server_version = "pool-mcp-http/1.0"

    # ---------------------------------------------------------------- 工具

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802 —— 基类约定
        logger = getattr(self.server, "request_log", None)
        if logger is not None:
            logger(f"[pool_mcp --http] {self.address_string()} {fmt % args}")

    def _send(
        self,
        status: int,
        body: bytes = b"",
        *,
        content_type: str | None = None,
        headers: Iterable[tuple[str, str]] = (),
    ) -> None:
        """统一出口：`Content-Length` 一律显式（HTTP/1.1 keep-alive 的硬要求）。"""
        self.send_response(status)
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _fail(self, status: int, text: str, *, headers: Iterable[tuple[str, str]] = ()) -> None:
        self._send(
            status,
            (text + "\n").encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            headers=headers,
        )

    def _path(self) -> str:
        """这条请求的**挂载键**（卡 A378）：去掉 query / 末尾斜杠，空 ⇒ `/`。"""
        return urlsplit(self.path).path.rstrip("/") or DEFAULT_PATH

    def _mount_limit(self) -> int | None:
        """已挂载 ⇒ 该路径**自己的**上限；未挂载 ⇒ 回一条 404 并 `None`。

        次序照 `tools/pool/gateway.py` 的 `_dispatch`：**先路径、后方法**
        —— 未挂载的路径不论 GET / POST 都是 404，不落到 405 上。
        """
        path = self._path()
        mounts = getattr(self.server, "mounts", {})
        if path not in mounts:
            self._fail(
                404,
                f"没有这条路径：{path!r}。本服务只服务调用方挂上去的路径"
                f"（{'、'.join(sorted(mounts)) or '无'}）。",
            )
            return None
        return int(mounts[path])

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            # 没有 Origin ⇒ 不是浏览器发起的跨站请求，默认放行；要更严就开 REQUIRE_ORIGIN。
            return not getattr(self.server, "require_origin", False)
        return origin.strip() in getattr(self.server, "allowed_origins", frozenset())

    def _accept_allowed(self) -> bool:
        accept = self.headers.get("Accept")
        if not accept:  # RFC 9110：没有 Accept 等价于 */*
            return True
        low = accept.lower()
        return "application/json" in low or "text/event-stream" in low

    def _version_allowed(self) -> bool:
        version = self.headers.get("MCP-Protocol-Version")
        if not version:  # 缺省按 DEFAULT_PROTOCOL 假定（只是放行，不改 handle 的入参）
            return True
        return version.strip() in getattr(self.server, "protocols", ())

    # ---------------------------------------------------------------- 方法

    def do_POST(self) -> None:  # noqa: N802 —— 基类约定
        max_bytes = self._mount_limit()
        if max_bytes is None:
            return
        if not self._origin_allowed():
            self._fail(
                403,
                "来源不被允许：带 Origin 的请求必须命中本机回环或 TF_MCP_HTTP_ORIGINS。",
            )
            return
        if not bearer_ok(self.headers.get("Authorization"), getattr(self.server, "token", "")):
            self._fail(
                401,
                "需要鉴权：带 Authorization: Bearer <TF_MCP_HTTP_TOKEN>。",
                headers=(("WWW-Authenticate", "Bearer"),),
            )
            return
        if not self._accept_allowed():
            self._fail(
                406,
                "本服务只回 application/json（不提供 SSE）：Accept 要么含它，要么别带。",
            )
            return
        if not self._version_allowed():
            version = self.headers.get("MCP-Protocol-Version")
            self._fail(400, f"不认识的 MCP-Protocol-Version：{version!r}。")
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self.close_connection = True
            self._fail(411, "需要 Content-Length（本服务不收 Transfer-Encoding: chunked）。")
            return
        try:
            raw = read_body(self.rfile, max_bytes=max_bytes, length=length)
        except BodyTooLarge as exc:
            # 声明就超限 ⇒ 一个字节都没读；把连接关掉，免得残余字节被当成下一条请求。
            self.close_connection = True
            self._fail(
                413,
                f"请求体太大：{exc.size} 字节 > 上限 {max_bytes} 字节（{max_bytes >> 20} MiB）。",
            )
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self.close_connection = True
            self._fail(400, "请求体不是 UTF-8。")
            return
        try:
            message = json.loads(text)
        except ValueError:
            self._fail(400, "请求体不是合法 JSON。")
            return
        if not isinstance(message, dict):
            self._fail(400, "JSON-RPC 消息必须是对象。")
            return
        try:
            answer = self.server.handle(message)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 —— 协议边界：异常只换一条错误回话
            answer = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"服务端处理这条消息时出错：{type(exc).__name__}: {exc}",
                },
            }
        if answer is None:  # 通知 / 回话：202 + 空 body（规范三态）
            self._send(202)
            return
        body = json.dumps(answer, ensure_ascii=False).encode("utf-8")
        self._send(200, body, content_type="application/json")

    def do_GET(self) -> None:  # noqa: N802 —— 基类约定
        if self._mount_limit() is None:
            return
        self._fail(
            405,
            "本服务不提供 SSE（GET 流），请用 POST 发 JSON-RPC。",
            headers=(("Allow", "POST"),),
        )

    def do_DELETE(self) -> None:  # noqa: N802 —— 基类约定
        if self._mount_limit() is None:
            return
        self._fail(
            405,
            "本服务无会话可终止（不发 Mcp-Session-Id）。",
            headers=(("Allow", "POST"),),
        )

    def do_PUT(self) -> None:  # noqa: N802 —— 基类约定
        if self._mount_limit() is None:
            return
        self._fail(405, "只收 POST。", headers=(("Allow", "POST"),))

    def do_PATCH(self) -> None:  # noqa: N802 —— 基类约定
        if self._mount_limit() is None:
            return
        self._fail(405, "只收 POST。", headers=(("Allow", "POST"),))


class _Server(ThreadingHTTPServer):
    """把判据需要的东西挂在 server 上（handler 用 `self.server.xxx` 读）。"""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        handle: Handle,
        token: str,
        origins: Iterable[str] = (),
        require_origin: bool = False,
        max_bytes: int,
        protocols: Iterable[str],
        mounts: Mapping[str, int] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(address, _Handler)
        self.handle = handle
        self.token = token
        self.require_origin = require_origin
        self.max_bytes = max_bytes
        self.mounts = mount_table(max_bytes, mounts)
        self.protocols = frozenset(protocols)
        self.request_log = log
        port = int(self.server_address[1])
        loops = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        extra = {item.strip() for item in origins if item and item.strip()}
        self.allowed_origins = frozenset(loops | extra)


def build_server(
    handle: Handle,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str,
    origins: Iterable[str] = (),
    max_bytes: int,
    protocols: Iterable[str],
    require_origin: bool = False,
    mounts: Mapping[str, int] | None = None,
    log: Callable[[str], None] | None = None,
) -> _Server:
    """建好但**不跑**（测试用它在后台线程里起一条真 socket）。

    ★ 没有 token ⇒ `ConfigError`：**不给"无鉴权"留默认路径**（判据 4）。
    """
    if not token:
        raise ConfigError(
            "TF_MCP_HTTP_TOKEN 没有设：本服务不为「无鉴权」留默认路径。"
            "先设一个随机串（python -c \"import secrets;print(secrets.token_urlsafe(32))\"），"
            "客户端带 Authorization: Bearer <同一个串>。"
        )
    if not max_bytes or max_bytes <= 0:
        raise ConfigError(f"请求体上限必须为正数，收到 {max_bytes!r}。")
    return _Server(
        (check_host(host), int(port)),
        handle=handle,
        token=token,
        origins=origins,
        require_origin=require_origin,
        max_bytes=max_bytes,
        protocols=protocols,
        mounts=mounts,
        log=log,
    )


def serve_http(
    handle: Handle,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str,
    origins: Iterable[str] = (),
    max_bytes: int,
    protocols: Iterable[str],
    require_origin: bool = False,
    mounts: Mapping[str, int] | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    """起服务并**一直阻塞**（Ctrl+C 收工回 0）。`port=0` ⇒ 由内核分配。"""
    server = build_server(
        handle,
        host=host,
        port=port,
        token=token,
        origins=origins,
        max_bytes=max_bytes,
        protocols=protocols,
        require_origin=require_origin,
        mounts=mounts,
        log=log,
    )
    bound = int(server.server_address[1])
    if log is not None:
        log(f"[pool_mcp --http] 监听 http://{host}:{bound}/（只收 POST；Bearer 鉴权；Ctrl+C 停）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover —— 交互收工
        pass
    finally:
        server.server_close()
    return 0
