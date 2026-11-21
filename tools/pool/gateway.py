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

F86 ③ 不移植（卡 E143）：pool 的候选池是同一个模型的多个号，窗口是模型属性不是号属性 ⇒
换号装不下还是装不下（见 gateway.py:184 / :597）。按 95% 挑号需要 token 计数，本仓没有分词器。

★ 这里的 classify() 与 pool_quota.classify() **不是一回事**，两处都在仓里、都要留着：
  · pool_quota.classify(status, body: str) 五值（credit/quota/rate/other/auth），照 magpie
    routing.go:391-444，**看自由文案的正则** —— 它要解「429 的正文里说没说余额没了」。
  · 这里的 classify(status, body: bytes|dict|None) 七值，**只看状态码与结构化字段**
    （error.type / error.code 这类枚举值里的 insufficient_quota），**绝不解析自由文案**
    （含中文提示语）。网关每条请求背后都可能是不同上游，正文措辞不可信。

安全口径整段照 tools/pool/mcp_http.py（只绑回环、必须 Bearer、Origin 白名单、请求体上限），
但**换一套 token**：TF_POOL_GATEWAY_TOKEN 与 TF_MCP_HTTP_TOKEN 不共用 —— MCP 那个口子有写权限，
这个口子代所有号发请求，权限不一样就不许借。

★ 入站 Content-Encoding 只判不认（卡 A391）：非空且不是 identity 的一律 415，报文说清
「本网关不解压，请用 identity 重发」。本文件**没有**解压行为，也不 import 任何压缩库 ——
压缩体读进来只会被报成坏 JSON（误诊），所以宁可先明确拒绝。
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
from pool import holds as pool_holds  # noqa: E402 —— 窗口维度的模型过滤（卡 A368）
from pool import lanes as pool_lanes  # noqa: E402
from pool import model_registry as pool_model_registry  # noqa: E402 —— 禁用表判据
from pool import models as pool_models  # noqa: E402
from pool import prompt_parts as pool_prompt_parts  # noqa: E402 —— 分段账（卡 A380）
from pool import route as pool_route  # noqa: E402
from pool import route_log as pool_route_log  # noqa: E402
from pool import rpm as pool_rpm  # noqa: E402
from pool import sink as pool_sink  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from collections.abc import Iterable, Sequence
    from typing import Any

__all__ = [
    "ALLOWED_HOSTS", "Attempt", "BARE_IDS_ENV", "BodyTooLarge", "CHUNK_BYTES",
    "ConfigError", "DEFAULT_HOST", "DEFAULT_PORT", "DEFAULT_PROTOCOL", "KINDS",
    "MAX_BODY_BYTES", "Outcome", "Reply", "ORIGINS_ENV", "REQUIRE_ORIGIN_ENV", "TOKEN_ENV",
    "bare_ids_from_env", "bearer_ok", "build_server", "classify", "check_host",
    "endpoint_protocol", "forward_http", "list_models", "main", "parse_retry_after",
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
# ★ 卡 A386（F85）：裸 id 行 = 只发布读数。**默认关** —— 不设就是今天的行为（逐字节）。
BARE_IDS_ENV = "TF_POOL_GATEWAY_BARE_IDS"
#: 请求体上限：照 pool_mcp.MAX_LINE_BYTES（32 MiB）。
MAX_BODY_BYTES = 32 << 20
CHUNK_BYTES = 64 * 1024
DEFAULT_PROTOCOL = "chat"
PROTOCOL_CHAT = "chat"
PROTOCOL_MESSAGES = "messages"
#: 卡 A372（F56）：搜索 API 的协议名。★ 它**不是**一条 HTTP 路径 —— `PATHS` 仍然是四条，
#: 一个都不多（`tests/test_pool_gateway.py` 钉着）；搜索只在 `route_once` 被注入这个
#: protocol 时才走到「只有被拒才换下一个 key」那一档（立卡人裁决 1）。
PROTOCOL_SEARCH = "search"
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
    route = {"/v1/chat/completions": PROTOCOL_CHAT, "/v1/messages": PROTOCOL_MESSAGES}.get(path, "")
    if route:
        return route
    # 卡 A372：搜索端点只认尾巴（tavily / serper 是 `/search`，brave 是 `/res/v1/web/search`）。
    # ★ 仍然只是「读已登记的串」，不拿 base 拼路径、不发请求（pick_endpoint 的硬边界不变）。
    if path.endswith("/search"):
        return PROTOCOL_SEARCH
    return ""


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
    #: 卡 A372（判据 4）：为什么**没有**继续换下一个候选。只有搜索路径会填
    #: （非拒绝类错误 ⇒ 就地结束）；聊天路径恒为空串 ⇒ 既有调用点一个字都不用改。
    stop_reason: str = ""

    @property
    def streaming(self) -> bool:
        return self.chunks is not None


Forward = "Callable[[str, str, str, bytes], Reply]"


# ---------------------------------------------------------------- 判据 3：干跑能整段走完


def _base_root(root: Path | str | None) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _model_block(pool: str, model: str, base: Path, *, now: dt.datetime) -> tuple[int, str]:
    """模型层的准入 —— 返回 (HTTP 状态码, 拒单文案)；放行是 (0, "")。

    ★ 卡 E105（T-AG614）之前这里只回文案、调用方一律写死 404。现在两档要分开：
    - **404** = 「没有这个模型 / 这份清单不可信」：未批、批准集空、快照过期、找不到号池目录；
    - **403** = 「有这个模型，但你现在不许用」：被禁用表停掉、或禁用表读不懂（不知道 ≠ 空表）。
    口径照抄原件 _ext/magpie-main/internal/gateway/disabled.go：「refused on every route
    before anything is sent upstream, with a 403 in the API's own shape」。

    ★ 禁用判定**排在四个老判定之后**：老判定说的是「这模型在这份批准集里吗」，
    禁用表说的是「这份批准集里的这一条，用户自己关掉了吗」—— 先答前者才谈得上后者。
    ★ 判据只有一份：这里只调 model_registry.assert_not_disabled，不自己读表、不自己 glob。
    """
    pool_dir = pool_models.find_pool_dir(base)
    if pool_dir is None:
        return 404, (f"找不到号池目录（从 {base} 逐级向上找 infra/pool/pool_models.py 都没命中）"
                     "⇒ 不猜模型清单")
    info = pool_models.load_pool_models(pool_dir)
    # ★ 卡 E131 判据 5：清单**读不懂**不算「批准集是空的」—— 前者是坏文件（点名 + 首行），
    #   后者是「用户一条都没批」。同一份坏文件原来在这里裸抛 TOMLDecodeError（H5）。
    for key, what in (("whitelist_error", "模型清单"), ("snapshot_error", "模型快照")):
        item = info.get(key)
        if item is not None:
            return 404, (f"{what}读不懂：{item['file']} 坏了 —— {item['error']} ⇒ 不派活")
    approved = [str(m) for m in info.get("approved") or []]
    if not approved:
        return 404, (f"号池 {pool!r} 的批准集是空的（models.whitelist.toml 没有 approved 条目）"
                     "⇒ 不派活")
    if model not in approved:
        return 404, f"模型 {model!r} 不在批准集里（已批：{', '.join(approved)}）⇒ 未批模型不许用"
    if info.get("snapshot_stale"):
        # ★ 卡 E110（T-AG619）：旧写法在这里**又**接了一遍「⇒ 先重新探测再派活」，
        #   而 note 里本来就带着它 ⇒ 现场文案叠了两遍。现在只说一遍，并把「怎么探」
        #   一并带出（命令与路径都在 pool_models.probe_hint 里现算，不在这里重写）。
        note = str(info.get("snapshot_note") or "").strip()
        if not note:
            note = f"快照过期（{pool_models.probe_hint(pool_dir)}）"
        return 404, f"模型快照不可信：{note}"
    try:
        pool_model_registry.assert_not_disabled(pool, model)
    except pool_model_registry.ModelRegistryError as exc:
        # 禁用 / 禁用表读不懂 ⇒ 403（「有，但不许用」），**在发上游之前**就拒。
        return 403, str(exc)
    return 0, ""


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


def _window(raw: Mapping[str, Any]) -> pool_holds.Window | None:
    """账本里**一个**按窗口的额度段 → `holds.Window`。读不懂就回 `None`（跳过这窗）。

    形状照 `holds.Window`（models 那份容器的字段名），因为它是本仓唯一的窗口容器
    （卡 A334）。`resets_at` 收 `datetime` 或账本里常见的 ISO 字符串 —— 后者走
    `pool_quota.parse_reset()`，**不另立第二个重置时间解析**（route.py:28 的纪律）。

    `used` 是 bool / 非数 ⇒ `None`：一个读不懂用量的窗口不能被当成「用满了」或「用空了」。
    """
    used = raw.get("used")
    if used is not None and (isinstance(used, bool) or not isinstance(used, (int, float))):
        return None
    resets = raw.get("resets_at")
    if isinstance(resets, str):
        resets_at = pool_quota.parse_reset(resets)
    elif isinstance(resets, dt.datetime):
        resets_at = resets
    else:
        resets_at = None
    raw_span = raw.get("span_s")
    span_s = (
        int(raw_span)
        if isinstance(raw_span, (int, float)) and not isinstance(raw_span, bool)
        else 0
    )
    raw_secs = raw.get("reset_secs")
    reset_secs = (
        float(raw_secs)
        if isinstance(raw_secs, (int, float)) and not isinstance(raw_secs, bool)
        else 0.0
    )
    return pool_holds.Window(
        model=str(raw.get("model") or ""),
        span_s=span_s,
        used=None if used is None else float(used),
        resets_at=resets_at,
        reset_secs=reset_secs,
        aside=bool(raw.get("aside")),
        unlimited=bool(raw.get("unlimited")),
        pool=str(raw.get("pool") or ""),
        family=str(raw.get("family") or ""),
    )


def _windows(row: Mapping[str, Any]) -> list[pool_holds.Window]:
    """账本行的 `[account.quota].windows` → 窗口列表（没有这一段就回空表）。

    ★ **数据从哪来（判据 2 要求的事实说明）**：今天的仓外账本
    `infra/pool/accounts.toml` 的 `[account.quota]` 只有 unit / source / observed_at /
    samples，**没有 per-window 段**，所以真数据上这里永远回空表 ⇒ `_seat()` 走老路、
    窗口过滤在全放行状态下什么都不改。本卡只让「有窗口数据时」的判定正确，
    不编造 per-window cap（卡规格「不许做」明写）。

    非 list / 空 list / 每项都读不懂 ⇒ 空表（不是「有窗口但都是空的」）。
    """
    quota = row.get("quota") if isinstance(row.get("quota"), Mapping) else {}
    raw = quota.get("windows") if isinstance(quota, Mapping) else None
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[pool_holds.Window] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        one = _window(item)
        if one is not None:
            out.append(one)
    return out


def _seat(
    row: Mapping[str, Any], model: str = "", *, now: dt.datetime | None = None
) -> pool_route.Seat:
    """账本行 → 一个排序座位。★ **不知道就说不知道**，不伪造成 0%。

    账本里 `[account.quota].used_percent` 缺失 / 不是数值 / 是 bool ⇒ `known=False, used=None`。
    早先这里落的是 `0.0`，于是「没有读数」被当成「用得最少」，smart_order / least_used 会把它
    排到第一位 —— 这正是卡 E95 要修的「不知道被当成知道」；网关这一半只负责**不伪造**。

    「怎么排」由卡 E95 在 tools/pool/route.py 里定，这里**不 catch 遮掩**、也不自己排。
    卡 E107 实测（不再复述旧行为）：`route.tier(None) == pool_route.UNKNOWN_TIER`（== 3），
    **不抛** —— 不知道额度的座落在**最后一档**，`smart` / `usage` / `pace` / `""` 四个分桶策略
    都把它排在所有知道的座**之后**；`order` / `rotate` / `weight` / `free` 不看额度、保列出序。
    ⇒ 交给 `apply_strategy()` 只有这一件事：**不知道的座排在所有知道的之后**。

    ## 窗口维度的模型过滤（卡 A368，判据 2）

    给了 `model` 且这一行**有** `quota.windows` 时，用量改由 `holds.pick()` 定：只在
    「算这个模型的账」的窗口里取最大（`applies()`），**别的模型的窗口不许抬这个模型的
    用量** —— 一个只计 opus 的窗写着 100%，请求 sonnet 时它既不是 100% 也不是 0%，
    而是**这个模型没有窗口读数**。

    ★ 「没有窗口」（`pick()` 回 `None`）**不等于** `used=0.0`：回 `known=False, used=None`
    ⇒ `UNKNOWN_TIER` ⇒ 排在所有知道的座之后。落成 0.0 就是拿「没测过」冒充「用得最少」，
    正是本函数上面那段在防的事。

    ★ 没有 `quota.windows` 段（今天真数据的**全部**情形）⇒ 逐位走老路读
    `used_percent`，行为与本卡之前**一字不差**（`tests/test_pool_gateway.py` 五条钉子钉着）。
    """
    quota = row.get("quota") if isinstance(row.get("quota"), Mapping) else {}
    key = str(row.get("id") or "")
    windows = _windows(row) if model else []
    if windows:
        clock = now if now is not None else dt.datetime.now(dt.timezone.utc)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=dt.timezone.utc)
        best = pool_holds.pick(windows, model, now=clock)
        if best is None or best.used is None:
            # 找不到算这个模型账的窗口 ⇒ 不知道，**不是** 0%。
            return pool_route.Seat(key=key, account=True, known=False, used=None)
        return pool_route.Seat(key=key, account=True, known=True, used=float(best.used))
    used = quota.get("used_percent") if isinstance(quota, Mapping) else None
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        return pool_route.Seat(key=key, account=True, known=False, used=None)
    return pool_route.Seat(key=key, account=True, known=True, used=float(used))


def _order(
    cands: Sequence[Mapping[str, Any]],
    routing: str,
    *,
    pool: str,
    model: str = "",
    now: dt.datetime | None = None,
    turns: dict[str, int] | None = None,
) -> list[int]:
    """候选行 → 送出顺序（下标）。`model` 只用于窗口维度的模型过滤（卡 A368）。

    不给 `model` ⇒ `_seat()` 不碰窗口，逐位等价于本卡之前（向后兼容既有调用点）。
    ★ 卡 A372：`turns` 是 `rotate` 的轮转计数，**由调用方持有**（见下方注释）——
      不传 ⇒ 退回原列顺序，与卡 A372 之前一个字节不差。
    """
    seats = [_seat(row, model, now=now) for row in cands]
    # apply_strategy 的末行就是 route.apply_order（route.py:580）—— 顺序护栏在那一份里，
    # 这里**不重写**：越界/重复/非整数一律退回原列顺序，永不抛（策略写坏也不许 500）。
    # ★ 卡 A372（裁决 5）：rotate 的计数**由调用方持有**（route.rotate 的 turns 口子早就有，
    #   只是没人传 ⇒ so_far 恒 0 ⇒ 恒等排列，缺口 1）。这里把调用方那份 dict 包成
    #   apply_strategy 认的 state 形状（{"turns": …}），**不新建、不落盘** —— 换成一个新
    #   空 dict 就等于每次从 0 开始，轮换会静默退回恒等（那正是本卡要修的）。
    state = None if turns is None else {"turns": turns}
    return pool_route.apply_strategy(routing, seats, pool=pool, state=state)


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
         status: str, started_at: float, parts: Sequence[dict] | None = None) -> bool:
    """落 wb-route.jsonl。★ tried 为空**不落**（append_route 自己不拒，纪律在这里守）。

    `parts` 是**已经算好**的分段账（卡 A380）：本函数只**照传**，不接 body、不自己拆 ——
    拆一次要在调用方（`route_once` 手上有 protocol 与原始 body）做，这里再收一份 body
    等于把正文在内存里多留一份，也把「纯函数只在一处」的边界破了。
    """
    if not attempts:
        return False
    pool_route_log.append_route(card=f"gw:{caller}", attempt=_attempt_no(caller, model, base),
                                asked=model, tried=_tried_entries(attempts), served=served,
                                status=status, started_at=started_at, root=base, parts=parts)
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
               sink_on: bool = True,
               turns: dict[str, int] | None = None) -> Outcome:
    """走完整一条：候选选择 → 沉底 / 每分钟闸 / 并发闸跳过 → 循环尝试 → 落账。

    forward 是**注入的**（签名 (model, account, url, payload) -> Reply）：干跑时给桩，
    整条链路照走不误、一个字节都不出网。真实转发是 forward_http（见下）。

    出口口径（勘察件 §5.5）：
      · 有候选答了 ⇒ 上游原样（流式就逐字节转）
      · 一个候选都没有（未批 / 快照过期） ⇒ 404 + 点名原因（不回 429）
      · 全被收窄挡 ⇒ 403 + 点名「收窄」，不叫「挂了」
      · 全 quota / rate 且知道何时回来 ⇒ 429 + Retry-After（最早回来的秒数）
      · 上游 4xx 非额度类 ⇒ 原样透传 status + body

    ★ 卡 A372（F56）：`protocol=PROTOCOL_SEARCH` 时多一档 —— 只有**被拒**
      （401/402/403/429/432/433）才换下一个 key；非拒绝类错误就地结束，原因写进
      `Outcome.stop_reason`。聊天路径的换号语义**一个字节不动**（立卡人裁决 1）。
    ★ `turns` 是 `rotate` 的轮转计数，**由调用方持有**（服务端就是 `_Server.turns`）；
      不传 ⇒ 每次从头算 ⇒ rotate 恒等（这就是本卡要修的那个缺口，别把默认值当正常路径）。
    """
    base = _base_root(root)
    clock = now if isinstance(now, dt.datetime) else dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=dt.timezone.utc)
    started_at = time.time()

    block_status, blocked = _model_block(pool, model, base, now=clock)
    if blocked:
        return _fail(protocol, block_status, blocked)

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

    for idx in _order(cands, routing, pool=pool, model=model, now=clock, turns=turns):
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
            # 分段账在**落账那一刻**才算（body 只在这一层手上）：说不出来 ⇒ None ⇒ 账里写 null。
            return _served(base, caller=caller, model=model, attempts=attempts,
                           reply=reply, started_at=started_at, seat=seat,
                           parts=pool_prompt_parts.parts_of(protocol, body))
        if (protocol == PROTOCOL_SEARCH
                and int(reply.status) not in pool_quota.SEARCH_REFUSED_STATUS):
            # 判据 4：搜索路径上非拒绝类错误（500 / 超时 / other / 413 / 400…）⇒ **就地结束**。
            # 换下一个 key 只会再多打一次人家，而且把「同一把 key 的错」伪装成「换个人就好了」。
            return _stopped(base, caller=caller, model=model, attempts=attempts, reply=reply,
                            started_at=started_at,
                            reason=(f"上游 {reply.status} 不是拒绝类（{kind}）"
                                    "⇒ 搜索路径就地结束，不换下一个 key"))

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
            if (protocol == PROTOCOL_SEARCH
                    and int(reply.status) in pool_quota.SEARCH_REFUSED_STATUS):
                # 卡 A372：432/433 在七值里落 bad_request，但搜索路径上它是「这家没钱了」
                # ⇒ 换下一个 key（magpie search_keys.go:62-76 把 tavily 432/433 算余额耗尽）。
                continue
            break  # 不换号：换号也装不下 / 是请求本身不对，原样透传
        continue  # server / other ⇒ 换下一个号，不降权

    return _exhausted(protocol, base=base, caller=caller, model=model, attempts=attempts,
                      replies=replies, skipped=skipped, endpoint_missing=endpoint_missing,
                      earliest=earliest, started_at=started_at, clock=clock,
                      parts=pool_prompt_parts.parts_of(protocol, body))


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


def _stopped(base: Path, *, caller: str, model: str, attempts: list[Attempt], reply: Reply,
             started_at: float, reason: str) -> Outcome:
    """搜索路径的「非拒绝类错误 ⇒ 就地结束」：上游原样透传 + `stop_reason` + 落账 stopped。

    ★ 为什么要一个专门的出口：判据 4 要的不是「悄悄不换号」，而是**读得出来的那一档**。
      `Outcome.stop_reason` 是本卡新加的唯一可读位（默认空串 ⇒ 聊天路径看不出差别）。
    """
    headers = {k: v for k, v in (reply.headers or {}).items() if k.lower() not in HOP_HEADERS}
    headers["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
    headers.setdefault("Content-Type", "application/json; charset=utf-8")
    logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                  status=pool_route_log.STATUS_STOPPED, started_at=started_at)
    return Outcome(status=int(reply.status), headers=headers, body=reply.body,
                   chunks=reply.chunks, attempts=tuple(attempts), logged=logged,
                   stop_reason=reason)


def _served(base: Path, *, caller: str, model: str, attempts: list[Attempt], reply: Reply,
            started_at: float, seat: str, parts: Sequence[dict] | None = None) -> Outcome:
    headers = {k: v for k, v in (reply.headers or {}).items() if k.lower() not in HOP_HEADERS}
    headers["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
    logged = _log(base, caller=caller, model=model, attempts=attempts,
                  served=f"{seat}/{model}", status=pool_route_log.STATUS_SERVED,
                  started_at=started_at, parts=parts)
    return Outcome(status=int(reply.status), headers=headers, body=reply.body,
                   chunks=reply.chunks, attempts=tuple(attempts), logged=logged)


def _auth_refused_note(attempts: Sequence[Attempt]) -> str:
    """全 auth 失败时的归因前缀（卡 A389 判据 3）：**只用结构化字段**拼，不读 body。

    ★ 为什么带上状态码集合而不是写死 401：403（含 magpie 的 revoked 那一档）也是
      vendor 拒凭据，报文说清是哪几个码，比笼统一句话好核对；单 401 时前缀逐字是
      「全部候选的凭据都被 vendor 拒了（HTTP 401）」（判据 3(a) 钉这串）。
    ★ 这里**不做判断**：叫不叫用本函数由 `_exhausted` 按 `classify()` 的 `KIND_AUTH`
      决定 —— 归因不是新的分类器，换号 / 排序 / 状态码的语义一个字不动。
    """
    codes = sorted({int(a.status) for a in attempts})
    shown = "/".join(str(c) for c in codes) if codes else "401"
    return f"全部候选的凭据都被 vendor 拒了（HTTP {shown}）"


def _exhausted(protocol: str, *, base: Path, caller: str, model: str, attempts: list[Attempt],
               replies: Sequence[Reply], skipped: list[str], endpoint_missing: list[str],
               earliest: dt.datetime | None, started_at: float,
               clock: dt.datetime, parts: Sequence[dict] | None = None) -> Outcome:
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
                      status=pool_route_log.STATUS_QUOTA_BLOCKED, started_at=started_at,
                      parts=parts)
        return _fail(protocol, 429, f"全部候选都是额度/限流类失败：{detail}", headers=headers,
                     attempts=attempts, logged=logged)

    if len(kinds) == 1 and kinds <= {KIND_OVERFLOW, KIND_BAD_REQUEST}:
        # 不换号那两类：最后一次上游的 status + body 原样透传（不包装）。
        reply = replies[-1]
        headers = {k: v for k, v in (reply.headers or {}).items() if k.lower() not in HOP_HEADERS}
        headers["X-Pool-Tried"] = "; ".join(a.label for a in attempts)
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                      status=pool_route_log.STATUS_ALL_FAILED, started_at=started_at, parts=parts)
        return Outcome(status=int(reply.status), headers=headers, body=reply.body,
                       chunks=reply.chunks, attempts=tuple(attempts), logged=logged)

    detail = "；".join(a.label for a in attempts)
    logged = _log(base, caller=caller, model=model, attempts=attempts, served="",
                  status=pool_route_log.STATUS_ALL_FAILED, started_at=started_at, parts=parts)
    if {int(a.status) for a in attempts} <= {401, 403}:
        # 卡 A389（F90 窄口）：唯一的「归因」—— 全 auth 失败时用自己的话说清是**谁的
        # 凭据被拒**，而不是与「上游全 500」「转发抛异常」共用「全部候选都失败了」
        # （那句会被读成「调用方鉴权失败」或「网关坏了」）。
        # ★ 只读 Attempt 的三个结构化字段（seat / model / status），不碰 body、不碰
        #   headers、不做正则、不建关键词表 —— 归因不是第二个分类器：换号与出口状态码
        #   仍全由 classify() 说了算（:755-757 的 continue 才是 401 不出网关的原因）。
        #   这里是**可达才用**：401/403 被结构化 quota 信号改判成 quota 时走的是上面
        #   那条 429，根本到不了这里（classify 的既有优先级，本卡不动）。
        # ★ 状态码不动：401 / 403 进来仍出 502，本卡只改报文。
        return _fail(protocol, 502, f"{_auth_refused_note(attempts)}：{detail}",
                     attempts=attempts, logged=logged)

    return _fail(protocol, 502, f"全部候选都失败了：{detail}", attempts=attempts, logged=logged)


def _platform_endpoints() -> dict[str, list[str]]:
    """读 platforms.toml 的 chat_urls（只放端点，不放凭据）。"""
    table = pool_accounts.load_platforms()
    out: dict[str, list[str]] = {}
    for name, row in table.items():
        urls = row.get("chat_urls") if isinstance(row, dict) else None
        out[str(name)] = [str(u) for u in (urls or [])]
    return out


def _window_entries() -> list[pool_model_registry.ModelEntry]:
    """读注册表拿窗口字段；**注册表读不出来就当成「一条都不知道」**（不抛）。

    ★ 卡 E143：/v1/models 是只读读数面，注册表坏了不该让整条路径 500 —— 窗口这一维
      退化成「不知道」，模型清单本身照旧发布（清单的真源不是注册表）。
    """
    try:
        return pool_model_registry.load_registry()
    except pool_model_registry.ModelRegistryError:
        return []


def _window_of(name: str, entries: Sequence[pool_model_registry.ModelEntry],
               ) -> pool_model_registry.ModelEntry | None:
    """按 alias / id 找那一条（码道条目 alias == id；CodeBuddy 两列今天也相同）。"""
    for entry in entries:
        if entry.alias == name or entry.id == name:
            return entry
    return None


def _models_note(base: str, unknown: int) -> str:
    """顶层 note + 「有 N 条模型的窗口未知」（N 也照说 —— 0 是读数，不是省略）。

    ★ 卡 A383（F95）：**签名一个字都不动**，也不改这一句的旧输出 —— 卡 E143 的证据指针
      钉的就是这一行原文；禁用那两句由下面的 _disabled_note 单独产出、并列拼接。
    """
    tail = (f"有 {unknown} 条模型的窗口未知（context_window = null，"
            f"回复上限按 {pool_model_registry.UNKNOWN_MAX_OUTPUT} 发）")
    return f"{base}；{tail}" if base else tail


def _bare_rows(rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """裸 id 行 = 尾段唯一的那几条（其余照原样一条）。

    ★ 卡 A386（F85）：只有**尾段唯一**才列 —— 两条 pa/x 与 pb/x 指向不同 entry，
      列一条 x 就是替人猜「是哪一个」，所以不列，只把条数报成读数。
      返回 (追加行, 因重名未列的**裸 id 条数**)；追加行除 id 外与被指向的那一条逐键相同。
    """
    tails: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("id") or "")
        if "/" not in name:
            continue
        tails.setdefault(name.rsplit("/", 1)[1], []).append(row)
    extra: list[dict[str, Any]] = []
    skipped = 0
    for tail in sorted(tails):
        owners = tails[tail]
        if len(owners) > 1:
            skipped += 1   # 裸 id 的条数（不是被它挡住的原行条数）
            continue
        bare = dict(owners[0])
        bare["id"] = tail
        extra.append(bare)
    return extra, skipped

def _disabled_note(disabled_unknown: int, disabled_hit: int) -> str:
    """禁用两态的条数（N 也照说）—— 「拒绝维度」与上面「窗口未知」并列，谁也不覆盖谁。"""
    return (f'有 {disabled_unknown} 条模型的禁用状态未知（disabled = "?"）'
            f"；{disabled_hit} 条被禁用（请求会 403）")

def list_models(*, root: Path | str | None = None,
                bare_ids: bool | None = None, pool: str = "") -> dict[str, Any]:
    """GET /v1/models 的数据：批准集 + 快照状态 + 窗口读数 + 禁用读数。**不联网、不写快照。**

    ★ 卡 E143（F86 ①）：每条 data 带 context_window / max_output_tokens / limits_source。
      不知道就是 null + 按 UNKNOWN_MAX_OUTPUT（model_registry 那一处）发；
      **不许**填一个「看着合理」的数（128k / 200k / 1m）。

    ★ 卡 A386（F85）：bare_ids=True 才在既有行**之后**追加一圈裸 id 行（只发布读数，
      不接请求）。关着时输出与今天逐字节相同 —— 这是默认值，也是判据 1。
      bare_ids=None（不传）⇒ 按 `BARE_IDS_ENV` 现算，与命令壳同一条判据
      （`bare_ids_from_env` 那一处）；HTTP 面不信 env，只信服务建好时那一刻的读数。
    ★ 卡 A383（F95）：「列出来的必须能用」。每条 data 带第七键 disabled（**拒绝维度**），
      判据是 pool_model_registry.model_disabled —— 与准入面 _model_block 的
      assert_not_disabled **同一份**；这里只问、不抛（读面必须 fail-soft，照 _window_entries）。
      三态：null = 没禁用 / "?" = 不知道（当禁用处理）/ 其它 = 命中的原样 pattern。
      被禁用的条目**一条都不删**（清单的真源是批准集），只加标注 —— 否则 403 时无处可查。
    ★ pool 是**维度**不是可选项：空则落 model_registry.DEFAULT_POOL（与准入侧同一个默认）。
    """
    if bare_ids is None:   # 直调方（验收 ③）不经过命令壳 ⇒ 这里按同一处判据现算
        bare_ids = bare_ids_from_env(os.environ.get(BARE_IDS_ENV))
    base = _base_root(root)
    which = (pool or pool_model_registry.DEFAULT_POOL).strip()
    pool_dir = pool_models.find_pool_dir(base)
    if pool_dir is None:
        return {"object": "list", "data": [], "note": "找不到号池目录 ⇒ 不猜模型清单"}
    info = pool_models.load_pool_models(pool_dir)
    # ★ 卡 E131 判据 5：坏文件是读数 —— data 空 + note 点名 + models_source_broken 带原文，
    #   不许把 TOMLDecodeError 直接抛到 BaseHTTPRequestHandler（H4）。
    broken = info.get("whitelist_error") or info.get("snapshot_error")
    if broken is not None:
        return {"object": "list", "data": [], "snapshot_at": info.get("snapshot_at"),
                "snapshot_stale": bool(info.get("snapshot_stale")),
                "note": (f"{broken['file']} 坏了 —— {broken['error']}"
                         " ⇒ 模型清单读不懂，不当成空清单，也不猜"),
                "models_source_broken": broken}
    entries = _window_entries()
    data: list[dict[str, Any]] = []
    unknown = 0
    disabled_unknown = 0
    disabled_hit = 0
    for name in info.get("approved") or []:
        entry = _window_of(str(name), entries)
        context_window = entry.context_window if entry is not None else None
        max_output = entry.max_output if entry is not None else None
        if context_window is None:
            unknown += 1
        # 拒绝维度：命中原样 pattern / UNKNOWN（不知道 ⇒ 当禁用处理）/ None（没禁用）。
        disabled = pool_model_registry.model_disabled(which, str(name))
        if disabled == pool_model_registry.UNKNOWN:
            disabled_unknown += 1
        elif disabled is not None:
            disabled_hit += 1
        data.append({
            "id": str(name), "object": "model", "owned_by": "pool",
            "context_window": context_window,   # None = 不知道（JSON null，不填假数）
            "max_output_tokens": (max_output if max_output is not None
                                  else pool_model_registry.UNKNOWN_MAX_OUTPUT),
            "limits_source": ("registry" if (context_window is not None
                                             or max_output is not None) else "unknown"),
            "disabled": disabled,               # None / "?" / 原样 pattern（三态，不洗）
        })
    note_bits = [_models_note(str(info.get("snapshot_note") or ""), unknown),
                 _disabled_note(disabled_unknown, disabled_hit)]
    if bare_ids:
        extra, skipped = _bare_rows(data)
        data = [*data, *extra]
        note_bits.append(f"有 {skipped} 条裸 id 因重名未列")
    return {"object": "list", "data": data, "snapshot_at": info.get("snapshot_at"),
            "snapshot_stale": bool(info.get("snapshot_stale")),
            "note": "；".join(bit for bit in note_bits if bit)}


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


def bare_ids_from_env(text: str | None) -> bool:
    """TF_POOL_GATEWAY_BARE_IDS=1 ⇒ /v1/models 在批准集行之后追加裸 id 行。默认关。

    **只有 "1" 是开**（""/0/true/yes/空白 一律关）—— 与 require_origin_from_env 同款。
    """
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
        # 入站编码只判不认（卡 A391）：本文件没有任何解压代码，压缩体读进来只会被
        # 报成坏 JSON（误诊），所以凡声明了非 identity 的编码，一律在读体之前 415。
        declared = ",".join(self.headers.get_all("Content-Encoding") or [])
        codings = [c.strip().lower() for c in declared.split(",") if c.strip()]
        if any(c != "identity" for c in codings):
            self.close_connection = True
            self._fail(415, "本网关不解压：Content-Encoding 只接受 identity，"
                            f"收到 {declared.strip()}。请用 identity 重发。",
                       kind="api_error", protocol=protocol)
            return
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
                             body=payload, root=getattr(self.server, "root", None),
                             turns=getattr(self.server, "turns", None))
        self._emit(outcome, want_stream=want_stream, protocol=protocol)

    def _get(self, path: str) -> None:
        if path == "/v1/models":
            data = list_models(root=getattr(self.server, "root", None),
                               bare_ids=bool(getattr(self.server, "bare_ids", False)),
                               pool=str(getattr(self.server, "pool", "") or ""))
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
                 routing: str = "order", root: Path | str | None = None,
                 bare_ids: bool = False, log: Any = None) -> None:
        super().__init__(address, _Handler)
        self.forward = forward
        self.token = token
        self.require_origin = bool(require_origin)
        self.max_bytes = int(max_bytes)
        self.pool = pool
        self.routing = routing
        self.root = root
        self.bare_ids = bool(bare_ids)
        self.request_log = log
        # ★ 卡 A372（立卡人裁决 5）：rotate 的轮转计数**由服务端持有**，route_once 从这里取。
        #   不改 route_once 的调用面（既有两个调用点一个字不用动）；进程活着就一直在转，
        #   重启归零 —— 搜索 key 的轮转没有跨进程语义要求（原件也是内存计数）。
        self.turns: dict[str, int] = {}
        port = int(self.server_address[1])
        loops = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        extra = {str(o).strip() for o in origins if str(o).strip()}
        self.allowed_origins = frozenset(loops | extra)


def build_server(forward: Forward = forward_http, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, token: str, origins: Sequence[str] = (),
                 require_origin: bool = False, max_bytes: int = MAX_BODY_BYTES,
                 pool: str = "codebuddy", routing: str = "order",
                 root: Path | str | None = None, bare_ids: bool = False,
                 log: Any = None) -> _Server:
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
                   pool=pool, routing=routing, root=root, bare_ids=bare_ids, log=log)


def serve_http(forward: Forward = forward_http, *, host: str = DEFAULT_HOST,
               port: int = DEFAULT_PORT, token: str, origins: Sequence[str] = (),
               require_origin: bool = False, max_bytes: int = MAX_BODY_BYTES,
               pool: str = "codebuddy", routing: str = "order",
               root: Path | str | None = None, bare_ids: bool = False,
               log: Any = None) -> int:
    """起服务并阻塞。**默认关**：只有显式调用（main）才会监听，import 不动任何端口。"""
    server = build_server(forward, host=host, port=port, token=token, origins=origins,
                          require_origin=require_origin, max_bytes=max_bytes, pool=pool,
                          routing=routing, root=root, bare_ids=bare_ids, log=log)
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
    bare_ids = bare_ids_from_env(os.environ.get(BARE_IDS_ENV))
    try:
        # ★ 卡 E103：先归一、再起服务 —— 不认识的名字在这里就退 2，**一个端口都不绑**。
        routing = pool_route.parse_routing(args.routing)
    except pool_route.RouteError as exc:
        print(f"[pool-gateway] 起不来：{exc}", file=sys.stderr, flush=True)
        return 2
    try:
        return serve_http(host=args.host, port=args.port, token=token, origins=origins,
                          require_origin=require_origin, pool=args.pool, routing=routing,
                          bare_ids=bare_ids,
                          log=lambda line: print(line, file=sys.stderr, flush=True))
    except ConfigError as exc:
        print(f"[pool-gateway] 起不来：{exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
