"""号池网关：把号池里的号按**同协议**直通给调用方（卡 E94）。

对等 magpie 的 internal/gateway/gateway.go 的一小块 —— 只搬「选号 → 转发 → 换号 → 留痕」
这条链。**不搬**它的协议翻译层（forwardOnce / ir.go / decoderFor）：
客户端说 Chat 就只往 Chat 端点发，说 Messages 就只往 Messages 端点发，SSE 逐字节转发。

四条硬边界（勘察件 gates/diag/magpie-gateway-recon.md 的 §5.1 / §6.1）：
1. **不做协议翻译**：上游只回流式、调用方要非流式 ⇒ 400 拒绝并说明，绝不自己攒流。
2. **不做凭据发现**：凭据只按 platforms.toml 的 token_env 从环境变量取 —— 不翻 cookie / 目录 /
   钥匙串。拿不到就是拿不到，不猜。
3. **不做定时器**：没有后台线程；沉底 / 每分钟闸 / 并发闸都是每次请求现读现算。
4. **不复制判据**：沉底问 sink.should_sink / sunk_at，每分钟闸问 rpm.decide，并发闸问
   guards.lane_guard，收窄问 guards.account_guard，定序问 route.apply_strategy
   （它末行就是 route.apply_order）。

★ 这里的 classify() 与 pool_quota.classify() **不是一回事**，两处都在仓里、都要留着：
  · pool_quota.classify(status, body: str) 五值（credit/quota/rate/other/auth），照 magpie
    routing.go:391-444，**看自由文案的正则** —— 它要解「429 的正文里说没说余额没了」。
  · 这里的 classify(status, body: bytes|dict|None) 七值，**只看状态码与结构化字段**
    （error.type / error.code 这类枚举值里的 insufficient_quota），**绝不解析自由文案**
    （含中文提示语）。网关每条请求背后都可能是不同上游，正文措辞不可信。

安全口径整段照 tools/pool/mcp_http.py（只绑回环、必须 Bearer、Origin 白名单、请求体上限），
但**换一套 token**：TF_POOL_GATEWAY_TOKEN 与 TF_MCP_HTTP_TOKEN 不共用 —— MCP 那个口子有写权限，
这个口子代所有号发请求，权限不一样就不许借。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlsplit

# tools/ 上 sys.path（本文件在 tools/pool/ 下，直接 python tools/pool/gateway.py 跑时
# 只有 tools/pool/ 被加进去，from pool import … 会 ImportError）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pool_accounts  # noqa: E402 —— tools/ 已在 sys.path 上
import pool_quota  # noqa: E402

from pool import guards as pool_guards  # noqa: E402
from pool import lanes as pool_lanes  # noqa: E402
from pool import models as pool_models  # noqa: E402
from pool import route as pool_route  # noqa: E402
from pool import route_log as pool_route_log  # noqa: E402
from pool import rpm as pool_rpm  # noqa: E402
from pool import sink as pool_sink  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from collections.abc import Iterable, Sequence
    from typing import Any

__all__ = [
    "ALLOWED_HOSTS", "Attempt", "BodyTooLarge", "CHUNK_BYTES", "ConfigError", "DEFAULT_HOST",
    "DEFAULT_PORT", "DEFAULT_PROTOCOL", "KINDS", "MAX_BODY_BYTES", "Outcome", "Reply",
    "ORIGINS_ENV", "REQUIRE_ORIGIN_ENV", "TOKEN_ENV", "bearer_ok", "build_server", "classify",
    "check_host", "endpoint_protocol", "forward_http", "list_models", "main", "parse_retry_after",
    "pick_endpoint", "require_origin_from_env", "resolve_token", "route_once", "serve_http",
    "split_origins",
]

# ---------------------------------------------------------------- 常量

DEFAULT_HOST = "127.0.0.1"
#: 与 pool_mcp --http 的 8765 错开：两个服务面不许抢同一个端口。
DEFAULT_PORT = 8766
#: 只认回环。**没有例外**：不给 0.0.0.0 开口子（远程访问走 SSH / frp 隧道）。
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: 独立的 token —— 不复用 TF_MCP_HTTP_TOKEN（那个口子有写权限）。
TOKEN_ENV = "TF_POOL_GATEWAY_TOKEN"
ORIGINS_ENV = "TF_POOL_GATEWAY_ORIGINS"
REQUIRE_ORIGIN_ENV = "TF_POOL_GATEWAY_REQUIRE_ORIGIN"
#: 请求体上限：照 pool_mcp.MAX_LINE_BYTES（32 MiB）。
MAX_BODY_BYTES = 32 << 20
CHUNK_BYTES = 64 * 1024
DEFAULT_PROTOCOL = "chat"
PROTOCOL_CHAT = "chat"
PROTOCOL_MESSAGES = "messages"
#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。
PATHS: dict[str, tuple[str, str]] = {
    "/v1/chat/completions": ("POST", PROTOCOL_CHAT),
    "/v1/messages": ("POST", PROTOCOL_MESSAGES),
    "/v1/models": ("GET", ""),
    "/v1/pool/routes": ("GET", ""),
}
#: 逐跳头：上游的值不许原样带出去（Length / 连接语义归本服务自己管）。
HOP_HEADERS = frozenset({"content-length", "transfer-encoding", "connection", "keep-alive"})


class ConfigError(ValueError):
    """启动参数 / 配置不能接受 —— 命令壳据此退非零，**不带着坏配置起服务**。"""


class BodyTooLargeError(Exception):
    """请求体超过上限（带 .size，方便报「N 字节 > 上限 M 字节」）。"""

    def __init__(self, size: int) -> None:
        super().__init__(f"请求体 {size} 字节超过上限")
        self.size = size


#: 卡规格上的名字（与 mcp_http.BodyTooLarge 同形：同一件事故一个叫法）。
BodyTooLarge = BodyTooLargeError


# ---------------------------------------------------------------- 判据 1：失败分类（只有这一份）

KIND_RATE = "rate"
KIND_QUOTA = "quota"
KIND_AUTH = "auth"
KIND_OVERFLOW = "overflow"
KIND_SERVER = "server"
KIND_BAD_REQUEST = "bad_request"
KIND_OTHER = "other"

Kind = Literal["rate", "quota", "auth", "overflow", "server", "bad_request", "other"]
#: 七值闭集：**不许发明第八个**（卡 E94 判据 1）。
KINDS: tuple[Kind, ...] = (
    KIND_RATE, KIND_QUOTA, KIND_AUTH, KIND_OVERFLOW, KIND_SERVER, KIND_BAD_REQUEST, KIND_OTHER,
)
#: 结构化「余额没了」的枚举值 —— 只认这些**整串相等**的字段值，不做子串匹配。
QUOTA_CODES = frozenset({
    "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached", "insufficient_balance",
})


def _as_object(body: bytes | bytearray | str | dict | None) -> dict | None:
    """把 body 解成一个对象；解不出就 None。**只有 JSON 结构化字段才算数。**"""
    if body is None:
        return None
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        try:
            text = bytes(body).decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(body, str):
        text = body
    else:
        return None
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _structured_quota(obj: dict | None) -> bool:
    """只看结构化字段：error.type / error.code（以及顶层同名字段）。**不碰 message。**"""
    if not isinstance(obj, dict):
        return False
    err = obj.get("error")
    for box in (err if isinstance(err, dict) else {}, obj):
        for key in ("type", "code", "reason", "status"):
            value = box.get(key)
            if isinstance(value, str) and value.strip().lower() in QUOTA_CODES:
                return True
    return False


def classify(status: int, body: bytes | dict | None = None) -> Kind:
    """一次上游失败分到七值之一。**纯函数**：同输入同输出，不读环境变量、不写盘、不读钟表。

    判据（卡 E94 判据 1，照勘察件 §5.5 的方案 B）：
      · 402，或结构化字段里写着 insufficient_quota ⇒ quota（余额没了）
      · 429 ⇒ rate（撞限流）
      · 401 / 403 ⇒ auth
      · 413 ⇒ overflow（上下文/请求体超窗 —— 不换号，换号也装不下）
      · >= 500 ⇒ server
      · 其余 4xx ⇒ bad_request
      · 其它 ⇒ other

    ★ 顺序有意如此：**结构化 quota 信号比状态码更具体**。真实世界里 429 配
      insufficient_quota 就是余额耗尽（OpenAI 系就这么回），照 rate 处理会白等一个 reset。
    ★ 绝不解析自由文案：正文写「额度用完了」「余额不足」都只是 bad_request / server ——
      网关背后可能是任意上游，措辞不可信，只认枚举值。
    """
    if isinstance(status, bool) or not isinstance(status, int):
        raise TypeError(f"status 必须是整数，收到 {status!r}")
    obj = _as_object(body)
    if status == 402 or _structured_quota(obj):
        return KIND_QUOTA
    if status == 429:
        return KIND_RATE
    if status in (401, 403):
        return KIND_AUTH
    if status == 413:
        return KIND_OVERFLOW
    if status >= 500:
        return KIND_SERVER
    if 400 <= status < 500:
        return KIND_BAD_REQUEST
    return KIND_OTHER


def parse_retry_after(raw: str | None, *, now: dt.datetime) -> dt.datetime | None:
    """Retry-After 解析：整数秒或 HTTP 日期。**判空用 is not None —— 0 是合法值**（立刻可回）。"""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return now + dt.timedelta(seconds=max(0, int(text)))
    except ValueError:
        pass
    try:
        stamp = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if stamp is None:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- 端点：空就是没登记，不猜


def endpoint_protocol(url: str) -> str:
    """只看 URL 的路径尾巴判协议。认不出回空串 —— **不猜、不试、不发请求**。"""
    try:
        path = urlsplit(str(url)).path.rstrip("/").lower()
    except ValueError:
        return ""
    return {"/v1/chat/completions": PROTOCOL_CHAT, "/v1/messages": PROTOCOL_MESSAGES}.get(path, "")


def pick_endpoint(urls: Sequence[str] | None, protocol: str, *,
                  platform: str) -> tuple[str | None, str]:
    """从平台的 chat_urls 里挑一个**同协议**端点。挑不到回 (None, 点名原因)。

    ★ 另一种做法是「拿 base_urls 拼一个路径试试」—— **禁止**：base_urls 是站点根
      （额度/签到页所在），不是 chat 端点；试着发就是伪造能力。
    """
    clean = tuple(str(u).strip() for u in (urls or ()) if str(u).strip())
    if not clean:
        return None, (f"这个平台没登记 chat 端点：平台 {platform!r} 的 chat_urls 是空的"
                      "（空 = 没登记，不是不支持）")
    for url in clean:
        if endpoint_protocol(url) == protocol:
            return url, ""
    return None, (f"平台 {platform!r} 登记了端点，但没有 {protocol} 协议的端点："
                  "本网关只做同协议直通，不做协议翻译")


# ---------------------------------------------------------------- 一次尝试 / 一次答复的形状


@dataclass(frozen=True, slots=True)
class Attempt:
    """一次真实的尝试。**粒度 = (号, 模型)** —— 换号不动模型（照 magpie gateway.go:2659）。"""

    seat: str
    model: str
    kind: Kind | None
    started_at: float
    status: int = 0
    why: str = ""

    @property
    def label(self) -> str:
        """给 X-Pool-Tried 用：<号>/<模型>[: 原因]。只有号与原因，没有 prompt、没有凭据。"""
        base = f"{self.seat}/{self.model}"
        return base if self.kind is None else f"{base}: {self.why or self.kind}"


@dataclass(slots=True)
class Reply:
    """上游的一次答复。chunks 非空 = 流式（SSE）—— 逐字节转发，不解析、不改写。"""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    chunks: Iterable[bytes] | None = None

    @property
    def streaming(self) -> bool:
        return self.chunks is not None


@dataclass(slots=True)
class Outcome:
    """交给 HTTP 面的一次结果：要么整块 body，要么 chunks（流）。"""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    chunks: Iterable[bytes] | None = None
    attempts: tuple[Attempt, ...] = ()
    logged: bool = False

    @property
    def streaming(self) -> bool:
        return self.chunks is not None


Forward = "Callable[[str, str, str, bytes], Reply]"


# ---------------------------------------------------------------- 判据 3：干跑能整段走完


def _base_root(root: Path | str | None) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _model_block(pool: str, model: str, base: Path, *, now: dt.datetime) -> str:
    """模型层的准入：未批 / 快照过期都**不进循环**（回了就是 404，不回 429）。"""
    pool_dir = pool_models.find_pool_dir(base)
    if pool_dir is None:
        return (f"找不到号池目录（从 {base} 逐级向上找 infra/pool/pool_models.py 都没命中）"
                "⇒ 不猜模型清单")
    info = pool_models.load_pool_models(pool_dir)
    approved = [str(m) for m in info.get("approved") or []]
    if not approved:
        return f"号池 {pool!r} 的批准集是空的（models.whitelist.toml 没有 approved 条目）⇒ 不派活"
    if model not in approved:
        return f"模型 {model!r} 不在批准集里（已批：{', '.join(approved)}）⇒ 未批模型不许用"
    if info.get("snapshot_stale"):
        note = str(info.get("snapshot_note") or "快照过期")
        return f"模型快照不可信：{note} ⇒ 先重新探测再派活"
    return ""


def _ledger_rows(base: Path, ledger: Mapping[str, Any] | None) -> list[dict]:
    if ledger is not None:
        rows = ledger.get("account") if isinstance(ledger, Mapping) else None
        return [dict(row) for row in (rows or [])]
    data = pool_accounts.load_ledger(pool_accounts.find_ledger())
    return [dict(row) for row in (data.get("account") or [])]


def _candidates(rows: Sequence[Mapping[str, Any]], model: str, *, pool: str, caller: str,
                scopes: Mapping[tuple[str, str], object] | None) -> tuple[list[dict], list[str]]:
    """候选 = state==active 且批了这个模型 且平台已知 且过得了收窄。只删不加。"""
    keep: list[dict] = []
    why: list[str] = []
    table = scopes if scopes is not None else {}
    for row in rows:
        seat = str(row.get("id") or "").strip()
        if not seat:
            continue
        state = str(row.get("state") or "")
        if state != "active":
            why.append(f"{seat}：state={state!r}（不是 active）")
            continue
        approved = [str(m) for m in (row.get("approved_models") or [])]
        if not approved:
            why.append(f"{seat}：approved_models 是空的（空 = 这个号不许派活）")
            continue
        if model not in approved:
            why.append(f"{seat}：没批这个模型（{model!r} 不在它的 approved_models 里）")
            continue
        if row.get("_platform_known") is False:
            why.append(f"{seat}：平台不在 tools/pool/platforms.toml 里")
            continue
        problems = pool_guards.account_guard(seat, table, card=str(caller or ""), project="",
                                             pool=pool)
        if problems:
            why.append(f"{seat}：{'；'.join(problems)}")
            continue
        keep.append(dict(row))
    return keep, why


def _seat(row: Mapping[str, Any]) -> pool_route.Seat:
    """账本行 → 一个排序座位。★ **不知道就说不知道**，不伪造成 0%。

    账本里 `[account.quota].used_percent` 缺失 / 不是数值 / 是 bool ⇒ `known=False, used=None`。
    早先这里落的是 `0.0`，于是「没有读数」被当成「用得最少」，smart_order / least_used 会把它
    排到第一位 —— 这正是卡 E95 要修的「不知道被当成知道」；网关这一半只负责**不伪造**。

    「不知道怎么排」由卡 E95 在 tools/pool/route.py 里定：当前 `route.tier()` 拿到 None 会抛
    RouteError，`route.apply_strategy()` 的 fail-open 于是退回原列顺序。这是**已知且可接受**的
    中间态（宁可回列出顺序，也不许拿假读数排），这里**不 catch 遮掩**、也不自己排。
    """
    quota = row.get("quota") if isinstance(row.get("quota"), Mapping) else {}
    used = quota.get("used_percent") if isinstance(quota, Mapping) else None
    key = str(row.get("id") or "")
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        return pool_route.Seat(key=key, account=True, known=False, used=None)
    return pool_route.Seat(key=key, account=True, known=True, used=float(used))


def _order(cands: Sequence[Mapping[str, Any]], routing: str, *, pool: str) -> list[int]:
    seats = [_seat(row) for row in cands]
    # apply_strategy 的末行就是 route.apply_order（route.py:580）—— 顺序护栏在那一份里，
    # 这里**不重写**：越界/重复/非整数一律退回原列顺序，永不抛（策略写坏也不许 500）。
    return pool_route.apply_strategy(routing, seats, pool=pool)


def _error_body(protocol: str, kind: str, message: str) -> bytes:
    """按调用方协议给错误体形状（只影响**错误**的形状，不做业务翻译）。"""
    if protocol == PROTOCOL_MESSAGES:
        payload: dict[str, Any] = {"type": "error",
                                   "error": {"type": kind, "message": message}}
    else:
        payload = {"error": {"type": kind, "message": message}}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


_ERROR_KIND = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "invalid_request_error",
    429: "rate_limit_error",
}


def _fail(protocol: str, status: int, message: str, *,
          headers: Mapping[str, str] | None = None, attempts: Sequence[Attempt] = (),
          logged: bool = False) -> Outcome:
    merged = dict(headers or {})
    merged.setdefault("Content-Type", "application/json; charset=utf-8")
    if attempts:
        merged["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
    return Outcome(status=status, headers=merged,
                   body=_error_body(protocol, _ERROR_KIND.get(status, "api_error"), message),
                   attempts=tuple(attempts), logged=logged)


def _tried_entries(attempts: Sequence[Attempt]) -> list[dict]:
    return [{"model": a.model, "fail": a.seat if a.kind is None else f"{a.seat}：{a.why or a.kind}"}
            for a in attempts]


def _attempt_no(caller: str, model: str, base: Path) -> int:
    rows, _bad = pool_route_log.read_routes(card=f"gw:{caller}", root=base)
    return 1 + sum(1 for row in rows if str(row.get("asked") or "") == model)


def _log(base: Path, *, caller: str, model: str, attempts: Sequence[Attempt], served: str,
         status: str, started_at: float) -> bool:
    """落 wb-route.jsonl。★ tried 为空**不落**（append_route 自己不拒，纪律在这里守）。"""
    if not attempts:
        return False
    pool_route_log.append_route(card=f"gw:{caller}", attempt=_attempt_no(caller, model, base),
                                asked=model, tried=_tried_entries(attempts), served=served,
                                status=status, started_at=started_at, root=base)
    return True


def route_once(*, pool: str, model: str, caller: str, forward: Forward,
               protocol: str = PROTOCOL_CHAT, routing: str = "order", body: bytes = b"",
               now: dt.datetime | None = None, root: Path | str | None = None,
               endpoints: Mapping[str, Sequence[str]] | None = None,
               rpm_limits: Mapping[str, int] | None = None,
               stamps: Mapping[str, Sequence[dt.datetime]] | None = None,
               reservations: Sequence[Mapping[str, Any]] = (),
               ledger: Mapping[str, Any] | None = None,
               scopes: Mapping[tuple[str, str], object] | None = None,
               sink_on: bool = True) -> Outcome:
    """走完整一条：候选选择 → 沉底 / 每分钟闸 / 并发闸跳过 → 循环尝试 → 落账。

    forward 是**注入的**（签名 (model, account, url, payload) -> Reply）：干跑时给桩，
    整条链路照走不误、一个字节都不出网。真实转发是 forward_http（见下）。

    出口口径（勘察件 §5.5）：
      · 有候选答了 ⇒ 上游原样（流式就逐字节转）
      · 一个候选都没有（未批 / 快照过期） ⇒ 404 + 点名原因（不回 429）
      · 全被收窄挡 ⇒ 403 + 点名「收窄」，不叫「挂了」
      · 全 quota / rate 且知道何时回来 ⇒ 429 + Retry-After（最早回来的秒数）
      · 上游 4xx 非额度类 ⇒ 原样透传 status + body
    """
    base = _base_root(root)
    clock = now if isinstance(now, dt.datetime) else dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=dt.timezone.utc)
    started_at = time.time()

    blocked = _model_block(pool, model, base, now=clock)
    if blocked:
        return _fail(protocol, 404, blocked)

    rows = _ledger_rows(base, ledger)
    cands, narrow_why = _candidates(rows, model, pool=pool, caller=caller, scopes=scopes)
    if not cands:
        detail = "；".join(narrow_why) or "账本里一个号都没有"
        return _fail(protocol, 403 if narrow_why else 404,
                     f"没有可用的号：{detail}")

    endpoints = endpoints if endpoints is not None else _platform_endpoints()
    rpm_map = dict(rpm_limits) if rpm_limits is not None else pool_rpm.load_rpm()
    stamp_map = dict(stamps) if stamps is not None else pool_rpm.read_stamps(root=base)
    lanes_map = pool_lanes.load_lanes()

    attempts: list[Attempt] = []
    replies: list[Reply] = []
    skipped: list[str] = []
    endpoint_missing: list[str] = []
    earliest: dt.datetime | None = None

    for idx in _order(cands, routing, pool=pool):
        row = cands[idx]
        seat = str(row.get("id") or "")
        platform = str(row.get("platform") or "")
        key = pool_sink.key_of(seat, model)
        if pool_sink.sinks(sink_on, routing) and pool_sink.sunk_at(key, root=base) is not None:
            skipped.append(f"{seat}：沉底中（这个号这个模型刚撞过限流）")
            continue
        lane = pool_lanes.lane_for(seat, lanes_map)
        busy = pool_guards.lane_guard(seat, reservations, limit=lane.limit, queue=lane.queue)
        if busy:
            skipped.append(f"{seat}：{'；'.join(busy)}")
            continue
        decision = pool_rpm.decide(seat, stamp_map.get(seat, ()),
                                   limit=int(rpm_map.get(seat, 0) or 0), now=clock)
        if not decision.allowed:
            skipped.append(f"{seat}：{decision.why}")
            continue
        url, why = pick_endpoint(endpoints.get(platform, ()), protocol, platform=platform)
        if url is None:
            endpoint_missing.append(why)
            continue

        pool_rpm.note_stamp(seat, clock, root=base)
        try:
            reply = forward(model, seat, url, body)
        except Exception as exc:  # noqa: BLE001 —— 转发抛什么都不能把网关打挂
            text = json.dumps({"error": {"type": "api_error", "message": f"转发时抛了：{exc}"}},
                              ensure_ascii=False).encode("utf-8")
            reply = Reply(status=502, headers={"Content-Type": "application/json"}, body=text)
        replies.append(reply)
        kind = None if 200 <= int(reply.status) < 300 else classify(int(reply.status),
                                                                   None if reply.streaming
                                                                   else reply.body)
        attempts.append(Attempt(seat=seat, model=model, kind=kind, started_at=time.time(),
                                status=int(reply.status),
                                why=_why(reply) if kind is not None else ""))
        if kind is None:
            return _served(base, caller=caller, model=model, attempts=attempts,
                           reply=reply, started_at=started_at, seat=seat)
        if kind == KIND_RATE:
            if pool_sink.should_sink(pool_sink.KIND_RATE, routing, on=sink_on):
                pool_sink.sink(key, root=base)
            when = parse_retry_after(_header(reply.headers, "retry-after"), now=clock)
            earliest = when if earliest is None or when < earliest else earliest
            continue
        if kind == KIND_QUOTA:
            when = parse_retry_after(_header(reply.headers, "retry-after"), now=clock)
            earliest = when if earliest is None or when < earliest else earliest
            pool_quota.record(card=f"gw:{caller}", model=model, pool=pool,
                              kind=pool_sink.KIND_BALANCE,
                              reset_raw=when.isoformat() if when is not None else "", root=base)
            continue
        if kind == KIND_AUTH:
            # 换号，**不写沉底**（auth 不是限流），也不去写账本的 health —— 写账本是别的模块的事。
            continue
        if kind in (KIND_OVERFLOW, KIND_BAD_REQUEST):
            break  # 不换号：换号也装不下 / 是请求本身不对，原样透传
        continue  # server / other ⇒ 换下一个号，不降权

    return _exhausted(protocol, base=base, caller=caller, model=model, attempts=attempts,
                      replies=replies, skipped=skipped, endpoint_missing=endpoint_missing,
                      earliest=earliest, started_at=started_at, clock=clock)


def _why(reply: Reply) -> str:
    text = ""
    if not reply.streaming:
        try:
            text = reply.body.decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 —— 只是给日志用的摘要，解不出就不给
            text = ""
    text = " ".join(text.split())
    return f"上游 {reply.status}" + (f"：{text}" if text else "")


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            return str(value)
    return None


def _served(base: Path, *, caller: str, model: str, attempts: list[Attempt], reply: Reply,
            started_at: float, seat: str) -> Outcome:
    headers = {k: v for k, v in (reply.headers or {}).items() if k.lower() not in HOP_HEADERS}
    headers["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
    logged = _log(base, caller=caller, model=model, attempts=attempts,
                  served=f"{seat}/{model}", status=pool_route_log.STATUS_SERVED,
                  started_at=started_at)
    return Outcome(status=int(reply.status), headers=headers, body=reply.body,
                   chunks=reply.chunks, attempts=tuple(attempts), logged=logged)


def _exhausted(protocol: str, *, base: Path, caller: str, model: str, attempts: list[Attempt],
               replies: Sequence[Reply], skipped: list[str], endpoint_missing: list[str],
               earliest: dt.datetime | None, started_at: float,
               clock: dt.datetime) -> Outcome:
    if not attempts:
        detail = "；".join(endpoint_missing or skipped) or "一个候选都没试到"
        if endpoint_missing:
            first = endpoint_missing[0]
            status = 403 if "没登记 chat 端点" in first else 400
            return _fail(protocol, status, detail)
        return _fail(protocol, 429, f"全部候选都被跳过，一个都没试：{detail}")

    kinds = {a.kind for a in attempts}
    all_quota_like = kinds <= {KIND_RATE, KIND_QUOTA}
    if all_quota_like:
        headers: dict[str, str] = {}
        if earliest is not None:
            seconds = max(0, int((earliest - clock).total_seconds()))
            headers["Retry-After"] = str(seconds)
        detail = "；".join(a.label for a in attempts)
        logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                      status=pool_route_log.STATUS_QUOTA_BLOCKED, started_at=started_at)
        return _fail(protocol, 429, f"全部候选都是额度/限流类失败：{detail}", headers=headers,
                     attempts=attempts, logged=logged)

    if len(kinds) == 1 and kinds <= {KIND_OVERFLOW, KIND_BAD_REQUEST}:
        # 不换号那两类：最后一次上游的 status + body 原样透传（不包装）。
        reply = replies[-1]
        headers = {k: v for k, v in (reply.headers or {}).items() if k.lower() not in HOP_HEADERS}
        headers["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                      status=pool_route_log.STATUS_ALL_FAILED, started_at=started_at)
        return Outcome(status=int(reply.status), headers=headers, body=reply.body,
                       chunks=reply.chunks, attempts=tuple(attempts), logged=logged)

    detail = "；".join(a.label for a in attempts)
    logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                  status=pool_route_log.STATUS_ALL_FAILED, started_at=started_at)
    return _fail(protocol, 502, f"全部候选都失败了：{detail}", attempts=attempts, logged=logged)


def _platform_endpoints() -> dict[str, list[str]]:
    """读 platforms.toml 的 chat_urls（只放端点，不放凭据）。"""
    table = pool_accounts.load_platforms()
    out: dict[str, list[str]] = {}
    for name, row in table.items():
        urls = row.get("chat_urls") if isinstance(row, dict) else None
        out[str(name)] = [str(u) for u in (urls or [])]
    return out


def list_models(*, root: Path | str | None = None) -> dict[str, Any]:
    """GET /v1/models 的数据：批准集（唯一权威）+ 快照状态。**不联网、不写快照。**"""
    base = _base_root(root)
    pool_dir = pool_models.find_pool_dir(base)
    if pool_dir is None:
        return {"object": "list", "data": [], "note": "找不到号池目录 ⇒ 不猜模型清单"}
    info = pool_models.load_pool_models(pool_dir)
    data = [{"id": m, "object": "model", "owned_by": "pool"} for m in info.get("approved") or []]
    return {"object": "list", "data": data, "snapshot_at": info.get("snapshot_at"),
            "snapshot_stale": bool(info.get("snapshot_stale")),
            "note": str(info.get("snapshot_note") or "")}


# ------------------------------------------------- 真实转发（今天走不到：chat_urls 全空）


def resolve_token(platform: str, *,
                  platforms: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """按 platforms.toml 的 token_env 从 env 取令牌。取不到就报，**不去翻文件/cookie/钥匙串**。"""
    table = platforms if platforms is not None else pool_accounts.load_platforms()
    row = table.get(platform) or {}
    kind = str((row or {}).get("auth_kind") or "")
    if kind != "bearer":
        raise ConfigError(
            f"平台 {platform!r} 的 auth_kind={kind!r}：本网关只做 bearer 直通"
            "（sdk-hmac-sha256 / cookie / file / dir / none 一条都不搬）⇒ 先别登记它的 chat 端点。")
    raw = str((row or {}).get("token_env") or "")
    names = [n.strip() for n in raw.replace(";", "/").split("/") if n.strip()]
    if not names:
        raise ConfigError(f"平台 {platform!r} 的 platforms.toml 没写 token_env"
                          "⇒ 本网关不做凭据发现。")
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise ConfigError(f"平台 {platform!r} 的凭据不在 env 里（{' / '.join(names)} 全空）"
                      "⇒ 不猜、不读文件。")


def _account_platform(account: str) -> str:
    data = pool_accounts.load_ledger(pool_accounts.find_ledger())
    for row in data.get("account") or []:
        if str(row.get("id") or "") == account:
            return str(row.get("platform") or "")
    raise ConfigError(f"账本里没有号 {account!r} ⇒ 不知道往哪个平台的端点发。")


def _iter_stream(resp: Any) -> Iterable[bytes]:
    try:
        while True:
            piece = resp.read(CHUNK_BYTES)
            if not piece:
                return
            yield piece
    finally:
        # 关流失败不该盖住已经转发出去的数据
        with contextlib.suppress(Exception):
            resp.close()


def forward_http(model: str, account: str, url: str, payload: bytes, *,
                 timeout: float = 120.0) -> Reply:
    """真发一次上游请求。★ 今天 chat_urls 全空 ⇒ **生产上走不到这里，未真机验证**。

    只做同协议：payload 原样发（不改写 stream / 不搬家字段），回来的 SSE 直接给 chunks。
    """
    try:
        token = resolve_token(_account_platform(account))
    except ConfigError as exc:
        return Reply(status=403, headers={"Content-Type": "application/json; charset=utf-8"},
                     body=json.dumps({"error": {"type": "permission_error",
                                                "message": str(exc)}},
                                     ensure_ascii=False).encode("utf-8"))
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 —— 端点来自 platforms.toml
    except urllib.error.HTTPError as exc:
        return Reply(status=int(exc.code), headers=dict(exc.headers or {}),
                     body=exc.read() or b"")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        message = f"上游连不上：{exc}"
        return Reply(status=502, headers={"Content-Type": "application/json; charset=utf-8"},
                     body=json.dumps({"error": {"type": "api_error", "message": message}},
                                     ensure_ascii=False).encode("utf-8"))
    headers = dict(resp.headers or {})
    ctype = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if ctype.startswith("text/event-stream"):
        return Reply(status=int(resp.status), headers=headers, chunks=_iter_stream(resp))
    body = resp.read()
    with contextlib.suppress(Exception):
        resp.close()
    return Reply(status=int(resp.status), headers=headers, body=body)


# ---------------------------------------------------------------- 判据 4：HTTP 面（四条，默认关）


def split_origins(text: str | None) -> tuple[str, ...]:
    """逗号分隔的 Origin 白名单；空项丢掉。"""
    if not text:
        return ()
    return tuple(item.strip() for item in text.split(",") if item.strip())


def require_origin_from_env(text: str | None) -> bool:
    """TF_POOL_GATEWAY_REQUIRE_ORIGIN=1 ⇒ 连**没带 Origin** 的请求也拒。"""
    return (text or "").strip() == "1"


def check_host(host: str) -> str:
    """只绑回环。**不为 0.0.0.0 开口子**（远程访问请套隧道）。"""
    value = (host or "").strip()
    if value not in ALLOWED_HOSTS:
        raise ConfigError(
            f"--host 只接受 127.0.0.1 / localhost / ::1，收到 {value!r}。"
            "本服务**不绑非回环地址**（不给 0.0.0.0 开口子）：要远程访问，"
            "请用 SSH / frp 这类隧道把它套在回环上。")
    return value


def read_body(stream: Any, *, max_bytes: int, length: int) -> bytes:
    """按 Content-Length 读请求体；超限**一个字节都不多读**。"""
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
        parts.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge(total)
    return b"".join(parts)


def bearer_ok(header: str | None, token: str) -> bool:
    """Authorization: Bearer <token> 比对 —— **常量时间**（hmac.compare_digest），不用裸等号。"""
    if not header:
        return False
    scheme, _, value = header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return False
    return hmac.compare_digest(value.strip().encode("utf-8"), token.encode("utf-8"))


def origin_allowed(origin: str | None, server: Any) -> bool:
    if not origin:
        return not bool(getattr(server, "require_origin", False))
    return origin.strip() in server.allowed_origins


def _close_chunks(chunks: Iterable[bytes] | None) -> None:
    close = getattr(chunks, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pool-gateway/1.0"

    # —— 基础件（照 mcp_http.py:152-212） ——
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 —— 基类就叫这个
        log = getattr(self.server, "request_log", None)
        if log is not None:
            log(f"[pool-gateway] {self.address_string()} {fmt % args}")

    def _send(self, status: int, body: bytes = b"", *, content_type: str | None = None,
              headers: Any = ()) -> None:
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        for name, value in headers:
            if str(name).lower() != "content-type":
                self.send_header(str(name), str(value))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _fail(self, status: int, text: str, *, kind: str = "invalid_request_error",
              headers: Any = (), protocol: str = PROTOCOL_CHAT) -> None:
        payload = _error_body(protocol, kind, text)
        self._send(status, payload, content_type="application/json; charset=utf-8",
                   headers=headers)

    def _gate(self) -> bool:
        """Origin + Bearer 两道。过了回 True；没过已经回过响应。"""
        if not origin_allowed(self.headers.get("Origin"), self.server):
            self._fail(403, f"来源不被允许：带 Origin 的请求必须命中本机回环或 {ORIGINS_ENV}。",
                       kind="permission_error")
            return False
        if not bearer_ok(self.headers.get("Authorization"), str(self.server.token)):
            self._fail(401, f"缺 Bearer 令牌或令牌不对：客户端要带 Authorization: Bearer "
                            f"<{TOKEN_ENV} 的值>。", kind="authentication_error",
                       headers=(("WWW-Authenticate", "Bearer"),))
            return False
        return True

    # —— 四条路径 ——
    def do_GET(self) -> None:  # noqa: N802 —— 基类协议要求这个大小写
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._fail(405, "本网关只有 POST /v1/chat/completions、POST /v1/messages、"
                        "GET /v1/models、GET /v1/pool/routes 四条路径。",
                   headers=(("Allow", "GET, POST"),))

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        spec = PATHS.get(path)
        if spec is None:
            self._fail(404, f"没有这条路径：{path!r}。本网关只有四条："
                            "POST /v1/chat/completions、POST /v1/messages、"
                            "GET /v1/models、GET /v1/pool/routes。", kind="not_found_error")
            return
        want, protocol = spec
        if method != want:
            self._method_not_allowed()
            return
        if not self._gate():
            return
        if method == "POST":
            self._post(protocol)
        else:
            self._get(path)

    def _post(self, protocol: str) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self.close_connection = True
            self._fail(411, "没有 Content-Length：本网关不收 chunked 请求体"
                            "（要发就写 Content-Length）。", protocol=protocol)
            return
        max_bytes = int(getattr(self.server, "max_bytes", MAX_BODY_BYTES))
        try:
            payload = read_body(self.rfile, max_bytes=max_bytes, length=length)
        except BodyTooLarge as exc:
            self.close_connection = True
            self._fail(413, f"请求体太大：{exc.size} 字节 > 上限 {max_bytes} 字节"
                            f"（{max_bytes >> 20} MiB）。", protocol=protocol)
            return
        try:
            obj = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._fail(400, "请求体不是 UTF-8 的 JSON 对象。", protocol=protocol)
            return
        if not isinstance(obj, dict):
            self._fail(400, "请求体必须是 JSON 对象（拿不到 model 就不许猜）。", protocol=protocol)
            return
        model = obj.get("model")
        if not isinstance(model, str) or not model.strip():
            self._fail(400, "payload 里没有 model（非空字符串）—— 不让网关替你猜模型。",
                       protocol=protocol)
            return
        caller = str(self.headers.get("X-Pool-Caller") or "gateway").strip() or "gateway"
        want_stream = bool(obj.get("stream"))
        outcome = route_once(pool=str(getattr(self.server, "pool", "") or ""),
                             model=model.strip(), caller=caller,
                             forward=self.server.forward, protocol=protocol,
                             routing=str(getattr(self.server, "routing", "order") or "order"),
                             body=payload, root=getattr(self.server, "root", None))
        self._emit(outcome, want_stream=want_stream, protocol=protocol)

    def _get(self, path: str) -> None:
        if path == "/v1/models":
            data = list_models(root=getattr(self.server, "root", None))
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(200, body, content_type="application/json; charset=utf-8")
            return
        query = parse_qs(urlsplit(self.path).query)
        try:
            limit = int((query.get("limit") or ["50"])[0])
        except ValueError:
            limit = 50
        limit = max(1, min(500, limit))
        rows, bad = pool_route_log.read_routes(root=getattr(self.server, "root", None))
        body = json.dumps({"data": rows[-limit:], "bad_lines": bad, "total": len(rows)},
                          ensure_ascii=False).encode("utf-8")
        self._send(200, body, content_type="application/json; charset=utf-8")

    # —— 出口：整块 / 流 ——
    def _emit(self, outcome: Outcome, *, want_stream: bool, protocol: str) -> None:
        headers = [(k, v) for k, v in (outcome.headers or {}).items()
                   if k.lower() not in HOP_HEADERS]
        if outcome.chunks is not None:
            if not want_stream:
                _close_chunks(outcome.chunks)
                self._fail(400, "上游只回流式（SSE），调用方要非流式 ⇒ 本网关**不做攒流翻译**"
                                "（不移植 magpie 的 forwardOnce / decoderFor）："
                                "请带 \"stream\": true 再问一次。", protocol=protocol)
                return
            self._stream(int(outcome.status), headers, outcome.chunks)
            return
        content_type = str(outcome.headers.get("Content-Type")
                           or "application/json; charset=utf-8")
        self._send(int(outcome.status), outcome.body, content_type=content_type,
                   headers=headers)

    def _stream(self, status: int, headers: Any, chunks: Iterable[bytes]) -> None:
        self.send_response(status)
        if not any(str(name).lower() == "content-type" for name, _ in headers):
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        for name, value in headers:
            self.send_header(str(name), str(value))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for piece in chunks:
                if piece:
                    self.wfile.write(piece)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _close_chunks(chunks)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, forward: Forward = forward_http,
                 token: str, origins: Sequence[str] = (), require_origin: bool = False,
                 max_bytes: int = MAX_BODY_BYTES, pool: str = "codebuddy",
                 routing: str = "order", root: Path | str | None = None, log: Any = None) -> None:
        super().__init__(address, _Handler)
        self.forward = forward
        self.token = token
        self.require_origin = bool(require_origin)
        self.max_bytes = int(max_bytes)
        self.pool = pool
        self.routing = routing
        self.root = root
        self.request_log = log
        port = int(self.server_address[1])
        loops = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        extra = {str(o).strip() for o in origins if str(o).strip()}
        self.allowed_origins = frozenset(loops | extra)


def build_server(forward: Forward = forward_http, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, token: str, origins: Sequence[str] = (),
                 require_origin: bool = False, max_bytes: int = MAX_BODY_BYTES,
                 pool: str = "codebuddy", routing: str = "order",
                 root: Path | str | None = None, log: Any = None) -> _Server:
    """建服务。**没有 token 就不建** —— 不为「无鉴权」留默认路径。"""
    if not token:
        raise ConfigError(
            f"{TOKEN_ENV} 没有设：本网关不为「无鉴权」留默认路径。先设一个随机串"
            "（python -c \"import secrets;print(secrets.token_urlsafe(32))\"），"
            "客户端带 Authorization: Bearer <同一个串>。"
            "★ 不复用 TF_MCP_HTTP_TOKEN：那个口子有写权限，这个口子代所有号发请求。")
    if not max_bytes or int(max_bytes) <= 0:
        raise ConfigError(f"请求体上限必须为正数，收到 {max_bytes!r}。")
    # ★ 卡 E103：启动面**不许 fail-open**。名字写错就在这里炸（退 2、一个端口都不绑），
    #   而不是让运维以为在用 smart、实际上按列出顺序派活派一整晚。
    #   归一后写进 self.routing：下游（sink / 日志）只认一种写法。
    try:
        routing = pool_route.parse_routing(routing)
    except pool_route.RouteError as exc:
        raise ConfigError(f"路由名起不来：{exc}") from None
    return _Server((check_host(host), int(port)), forward=forward, token=token,
                   origins=origins, require_origin=require_origin, max_bytes=int(max_bytes),
                   pool=pool, routing=routing, root=root, log=log)


def serve_http(forward: Forward = forward_http, *, host: str = DEFAULT_HOST,
               port: int = DEFAULT_PORT, token: str, origins: Sequence[str] = (),
               require_origin: bool = False, max_bytes: int = MAX_BODY_BYTES,
               pool: str = "codebuddy", routing: str = "order",
               root: Path | str | None = None, log: Any = None) -> int:
    """起服务并阻塞。**默认关**：只有显式调用（main）才会监听，import 不动任何端口。"""
    server = build_server(forward, host=host, port=port, token=token, origins=origins,
                          require_origin=require_origin, max_bytes=max_bytes, pool=pool,
                          routing=routing, root=root, log=log)
    bound = int(server.server_address[1])
    if log is not None:
        log(f"[pool-gateway] 监听 http://{check_host(host)}:{bound}/（只绑回环；Bearer 鉴权；"
            "四条路径；Ctrl+C 停）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """命令壳。★ 没有 TF_POOL_GATEWAY_TOKEN ⇒ 打印原因并退 2，**一个端口都不绑**。"""
    parser = argparse.ArgumentParser(prog="pool-gateway",
                                     description="号池网关：同协议直通（只绑回环）")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--pool", default="codebuddy")
    parser.add_argument("--routing", default="order",
                        help="选号策略：order（默认）/ smart（= 空串，magpie 默认）/"
                             " manual / usage / pace / weight / free / fast；"
                             "别名见 pool.route.ROUTING_ALIASES")
    parser.add_argument("--origin", action="append", default=[],
                        help="额外允许的 Origin（可重复）")
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "").strip()
    origins = tuple(args.origin) + split_origins(os.environ.get(ORIGINS_ENV))
    require_origin = require_origin_from_env(os.environ.get(REQUIRE_ORIGIN_ENV))
    try:
        # ★ 卡 E103：先归一、再起服务 —— 不认识的名字在这里就退 2，**一个端口都不绑**。
        routing = pool_route.parse_routing(args.routing)
    except pool_route.RouteError as exc:
        print(f"[pool-gateway] 起不来：{exc}", file=sys.stderr, flush=True)
        return 2
    try:
        return serve_http(host=args.host, port=args.port, token=token, origins=origins,
                          require_origin=require_origin, pool=args.pool, routing=routing,
                          log=lambda line: print(line, file=sys.stderr, flush=True))
    except ConfigError as exc:
        print(f"[pool-gateway] 起不来：{exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
