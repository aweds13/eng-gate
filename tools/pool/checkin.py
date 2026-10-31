"""拉取式手动签到（卡 E48 / T-AG497）。

**写动作只在这个模块里** —— 卡 §2 的静态扫描就扫这里：除本文件之外，任何模块都不许
构造 POST/DELETE 到平台签到端点。

形态由用户定形（m11666）：不给后台定时、不做自动重试，只有用户开口时跑一次。
所以本模块的每条路径都遵守三条硬规矩（卡 §3）：

1. **幂等**：先读状态/活动列表，已领直接 ``already-claimed``，绝不重发领取请求；
   各平台的判据按 ``tools/pool/platforms.toml`` 写死，不搞「统一当成没领过就领」。
2. **一次一不重试**：串行、每号一次；429/5xx 记 ``uncertain`` 就停，不连环打。
3. **每次动作留痕**：调用方（``tools/pool_accounts.py``）把结论码写进留档与账本。

结论码六态（抄参考实现的 ``ClaimOutcome``）：``claimed`` / ``already-claimed`` /
``inactive`` / ``not-supported`` / ``uncertain`` / ``failed``。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from datetime import tzinfo

# ---------------------------------------------------------------- 结论码

CLAIMED = "claimed"
ALREADY_CLAIMED = "already-claimed"
INACTIVE = "inactive"
NOT_SUPPORTED = "not-supported"
UNCERTAIN = "uncertain"
FAILED = "failed"

KINDS: tuple[str, ...] = (CLAIMED, ALREADY_CLAIMED, INACTIVE, NOT_SUPPORTED, UNCERTAIN, FAILED)

#: 需要人看（其余四态都是正常结论，不算故障 —— 卡 §3 的表）。
NEEDS_HUMAN: frozenset[str] = frozenset({UNCERTAIN, FAILED})

# ---------------------------------------------------------------- 依赖注入

#: 一次 HTTP 调用的抽象：``fetch(method, url, headers, body) -> (status, text)``。
#: 传假 fetcher 就能在测试里回放任意响应形状（卡 §4 的钉子全靠它）。
Fetcher = Callable[[str, str, Mapping[str, str] | None, bytes | None], tuple[int, str]]

TIMEOUT_S = 30.0

# ---------------------------------------------------------------- 复查判据的常量
#
# ★ 只移植**判据**，不移植**触发方式**：magpie 那边由每分钟一次的后台节拍自己复查
#   （`workbuddy_checkin.go:565-593 keepCheckedIn`）；pool 的形状是「人开口一次」
#   （见本文件 :1-16），所以这里只留判据 —— 没有循环、没有定时器、没有后台线程。

#: 几点之前「已经签过了」不算数（magpie `checkinSureHour`，`workbuddy_checkin.go:147`）。
#: 来历见 `:140-147` 与 issue `#3326`：北京日刚过零点时六家全回「already claimed」，
#: 10:54 再问才是真签到 —— 上午那句「已签过」说的大概率是**昨天**。
#: ★ 不许改成可配置：magpie 侧是 `const`，这个值来自那次事故的读数，不是策略旋钮。
CHECKIN_SURE_HOUR = 12
#: 上午的「已签过」多久复查一次（magpie `wbCheckinEvery`，`:53`）＝ 30 分钟。
RECHECK_EVERY_S = 30 * 60
#: 失败 / 没定论的重问间隔（magpie `wbCheckinRetry`，`:56`）＝ 30 分钟（在线恒此值）。
RETRY_AFTER_S = 30 * 60
#: 离线退避的起点（magpie `wbCheckinSoon`，`:87`）＝ 1 分钟；按次数翻倍、封顶 `RETRY_AFTER_S`。
RETRY_FLOOR_S = 60

#: 只有「活动类」平台要按时复查（magpie `checkin.go:105-110` + `qoder_checkin.go:289`）。
#: 平台清单的真源是 `tools/pool/platforms.toml`；这里**只列要复查的**，没列 = 不复查。
RECHECK_PLATFORMS: frozenset[str] = frozenset({"qoder"})


@dataclass(slots=True)
class Outcome:
    """一个号的一次签到结论。"""

    kind: str
    message: str = ""
    code: int = 0
    credit: float = 0.0
    unit: str = ""
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"未知结论码：{self.kind}（只认 {', '.join(KINDS)}）")

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"kind": self.kind}
        if self.message:
            data["message"] = self.message
        if self.code:
            data["code"] = self.code
        if self.credit:
            data["credit"] = self.credit
        if self.unit:
            data["unit"] = self.unit
        if self.extra:
            data["extra"] = dict(self.extra)
        return data

    @property
    def summary(self) -> str:
        """一行给人看的说明。"""
        bits = []
        if self.credit:
            bits.append(f"+{_fmt(self.credit)} {self.unit}".strip())
        if self.message:
            bits.append(self.message)
        return "；".join(bits)


def _fmt(value: float) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


# ---------------------------------------------------------------- 复查判据（纯函数）
#
# 三个函数都是**纯判据**：不读钟（`now` 必须传进来）、不读文件、不发网络。
# `timezone` 由调用方给（全仓真源是 `tools/pool_accounts.py` 的 `TZ`），本文件不另造时区。


def provisional(outcome: Outcome, *, at: datetime, now: datetime, timezone: tzinfo) -> bool:
    """这句「已经签过了」算不算数？不算数 ⇒ 要复查（magpie `provisional()`，`:160-173`）。

    三件事同时成立才是「上午那句不可信」：
      ① 结论是「说已经签过」那一类（`ALREADY_CLAIMED` / `INACTIVE`）—— `CLAIMED` 是真签到，
         不在此列；`NOT_SUPPORTED` / `UNCERTAIN` / `FAILED` 说的根本不是「签过了」；
      ② `at` 与 `now` 是**同一个时区日**（跨天 ⇒ 那句说的是昨天，不归这里判）；
      ③ `now` 还没到 `CHECKIN_SURE_HOUR`（中午之前）。

    `at` / `now` 必须带时区：naive ⇒ `ValueError`（时区只有一个真源，绝不猜）。
    """
    if at.tzinfo is None or now.tzinfo is None:
        raise ValueError("provisional 的时刻必须带时区（naive 不许猜时区）")
    if outcome.kind not in (ALREADY_CLAIMED, INACTIVE):
        return False
    stamp = at.astimezone(timezone)
    moment = now.astimezone(timezone)
    if stamp.date() != moment.date():
        return False
    return moment.hour < CHECKIN_SURE_HOUR


def retry_after_s(*, offline: bool, tries: int) -> int:
    """`FAILED` 之后多久再问一次（magpie `retryAfter()`，`:201-206`）。

    在线恒 `RETRY_AFTER_S`（30 分钟，别打快）；离线按次数指数退避：
    `min(RETRY_AFTER_S, RETRY_FLOOR_S << min(tries, 5))` ⇒ 1/2/4/8/16 分钟，
    第 5 次起封顶 30 分钟。`tries < 0` ⇒ `ValueError`。
    """
    if tries < 0:
        raise ValueError(f"tries 不许为负：{tries}")
    if not offline:
        return RETRY_AFTER_S
    return min(RETRY_AFTER_S, RETRY_FLOOR_S << min(tries, 5))


def due_for_recheck(
    last: Outcome | None,
    *,
    at: datetime | None,
    now: datetime,
    timezone: tzinfo,
    platform: str,
    offline: bool = False,
    tries: int = 0,
) -> tuple[bool, str]:
    """现在该不该再问一次签到 —— `(要不要问, 为什么)`（magpie `settled()`，`:190-195`）。

    **顺序即优先级**，先命中的那条说了算：
      ① 从没问过 ⇒ 问：`(True, "从没问过")`；
      ② 平台根本没有签到接口 ⇒ 不问：`(False, "平台不支持签到")`（`NOT_SUPPORTED` 不是故障）；
      ③ `at` 不是今天 ⇒ 跨天了，问：`(True, "跨天了")`；
      ④ 上次 `FAILED` 且过了 `retry_after_s()` ⇒ 问：`(True, "失败到期重问")`；
      ⑤ 上次 `UNCERTAIN` 且过了 `RETRY_AFTER_S` ⇒ 问：`(True, "没定论，复查窗口到了")`；
      ⑥ 上次那句是「上午的已签过」且过了 `RECHECK_EVERY_S` ⇒ 问（本卡的主角）：
         `(True, "上午的「已签过」不可信，复查窗口到了")`；
      ⑦ 活动类平台（`RECHECK_PLATFORMS`）过了一个复查窗口 ⇒ 问：
         `(True, "活动类平台复查窗口到了")`；
      ⑧ 其余 ⇒ 不问：`(False, "当日已定案")`。

    `now` 必须带时区（naive ⇒ `ValueError`）。`at` 缺 / naive ⇒ 当「从没问过」：
    复查签到是幂等动作，比「时刻坏了就永远不复查」安全。
    ★ 纯判据：不读钟、不读文件、不发网络。
    """
    if now.tzinfo is None:
        raise ValueError("due_for_recheck 的 now 必须带时区（naive 不许猜时区）")
    if last is None:
        return True, "从没问过"
    if last.kind == NOT_SUPPORTED:
        return False, "平台不支持签到"
    if at is None or at.tzinfo is None:
        return True, "从没问过"
    moment = now.astimezone(timezone)
    stamp = at.astimezone(timezone)
    if stamp.date() != moment.date():
        return True, "跨天了"
    elapsed = (moment - stamp).total_seconds()
    if last.kind == FAILED and elapsed >= retry_after_s(offline=offline, tries=tries):
        return True, "失败到期重问"
    if last.kind == UNCERTAIN and elapsed >= RETRY_AFTER_S:
        return True, "没定论，复查窗口到了"
    if provisional(last, at=at, now=now, timezone=timezone) and elapsed >= RECHECK_EVERY_S:
        return True, "上午的「已签过」不可信，复查窗口到了"
    if platform in RECHECK_PLATFORMS and elapsed >= RECHECK_EVERY_S:
        return True, "活动类平台复查窗口到了"
    return False, "当日已定案"


# ---------------------------------------------------------------- 默认 fetcher


def http_fetch(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = TIMEOUT_S,
) -> tuple[int, str]:
    """真发一次请求。**不重试、不跟随二次提交** —— 重试会破坏「一次一不重试」。"""
    request = urllib.request.Request(  # noqa: S310 —— 端点来自能力表常量，不是用户输入
        url,
        data=body,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也是「有响应」，交给上层判结论码
        return int(exc.code), exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # 网络不明 => uncertain（卡 §3：结果未知不许重放）
        raise NetworkError(str(exc)) from exc


class NetworkError(RuntimeError):
    """网络层失败（与「上游明确报错」不同：这类记 uncertain）。"""


# ---------------------------------------------------------------- 小工具


def _read_str(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    return value if isinstance(value, str) else ""


def _read_ident(source: Mapping[str, object], key: str) -> str:
    """标识符字段：服务端有时下发数字（实测 codearts 的 ``campaignId`` 是 1）。"""
    value = source.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _read_scalar(source: Mapping[str, object], key: str) -> object:
    """原样取标量（``campaignId`` 实测是数字，串成字符串可能被服务端拒）。"""
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int, float)):
        return value
    return None


def _read_num(source: Mapping[str, object], key: str) -> float:
    value = source.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _read_bool(source: Mapping[str, object], key: str) -> bool:
    value = source.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _read_record(source: Mapping[str, object], key: str) -> dict[str, object]:
    value = source.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _json_or_none(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _describe_http(status: int, text: str) -> str:
    """把非 2xx 整理成**带服务端原因**的说明（华为网关的 error_msg 是排查的唯一线索）。"""
    parsed = _json_or_none(text) or {}
    detail = " ".join(
        part for part in (_read_str(parsed, "error_code"), _read_str(parsed, "error_msg")) if part
    )
    if not detail:
        detail = text.strip()[:200]
    return f"HTTP {status}：{detail}" if detail else f"HTTP {status}"


def _classify_transport(status: int, text: str) -> Outcome | None:
    """把「不该继续」的响应统一成结论码；可以继续时返回 None。"""
    if status == 429 or status >= 500:
        # 限流/上游抖动：结果未知 => uncertain，且**不许重试**
        return Outcome(UNCERTAIN, message=_describe_http(status, text), code=status)
    if status == 404:
        return Outcome(NOT_SUPPORTED, message="上游没有这个接口（HTTP 404）", code=status)
    if status in (401, 403):
        return Outcome(UNCERTAIN, message=_describe_http(status, text), code=status)
    if status >= 400:
        return Outcome(FAILED, message=_describe_http(status, text), code=status)
    return None


# ---------------------------------------------------------------- 华为云签名


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_hex(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def sign_huawei(
    ak: str,
    sk: str,
    security_token: str,
    method: str,
    url: str,
    body: bytes = b"",
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """华为云 ``SDK-HMAC-SHA256`` 签名（照 ``src/sign.ts`` 逐字移植）。

    与参考实现的四点一致（任何一点偏了都会 401）：

    1. URI 必须以 ``/`` 结尾；query 不进 path；
    2. 日期头是 ``YYYYMMDDTHHMMSSZ``；
    3. 参与签名的头按名字排序，canonical request 里**空行**分隔头块与 SignedHeaders；
    4. 直接拿 SK 当 HMAC 密钥，**不做** kDate/kSigning 派生（华为老式 SDK 签名）。
    """
    parsed = urlparse(url)
    uri = parsed.path or "/"
    if not uri.endswith("/"):
        uri += "/"
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    payload_hash = _sha256_hex(body)
    headers: dict[str, str] = {
        "host": parsed.netloc,
        "x-sdk-date": stamp,
        "x-sdk-content-sha256": payload_hash,
        "x-security-token": security_token,
    }
    if method.upper() != "GET":
        headers["content-type"] = "application/json"
    signed = sorted(headers)
    canonical = "\n".join(
        [
            method.upper(),
            uri,
            parsed.query,
            "\n".join(f"{key}:{headers[key]}" for key in signed),
            "",
            ";".join(signed),
            payload_hash,
        ]
    )
    string_to_sign = f"SDK-HMAC-SHA256\n{stamp}\n{_sha256_hex(canonical.encode())}"
    signature = _hmac_hex(sk.encode(), string_to_sign.encode())
    headers["Authorization"] = (
        f"SDK-HMAC-SHA256 Access={ak},SignedHeaders={';'.join(signed)},Signature={signature}"
    )
    return headers


# ---------------------------------------------------------------- codearts

CODEARTS_BASE = "https://snap-access.cn-north-4.myhuaweicloud.com"
CODEARTS_PACKAGE_PATH = "/snap-manager/v1/statistics/plugin"
CODEARTS_DELIVERY_PATH = "/v1/ops/delivery"
CODEARTS_CLAIM_PATH = "/v1/ops/claim"
CODEARTS_CONFIRM_PATH = "/v1/ops/confirm"
CODEARTS_CHANNEL = "IDE"
CODEARTS_DAILY_TYPE = "USER_LOGIN"
#: 已领取/已确认/已核销 —— 这三种状态才算「今天已领」，其余不可领取是「不在活动内」。
CODEARTS_CLAIMED_STATUSES = frozenset({"CLAIMED", "CONFIRMED", "CONSUMED"})
#: **签名后**追加的头（绝不进 canonical request，进了就 401 APIG.0301）。
CODEARTS_EXTRA_HEADERS = {"Agent-Type": "PromptCenter", "X-Language": "zh-cn"}
CODEARTS_TOTAL_METRIC = "usageTotalPackageCredit"
CODEARTS_CREDIT_METRICS = frozenset(
    {
        CODEARTS_TOTAL_METRIC,
        "usageBasicPackageCredit",
        "usageOnDemandPackageCredit",
        "usageBonusPackageCredit",
    }
)


@dataclass(slots=True)
class CodeArtsCredential:
    ak: str
    sk: str
    security_token: str = ""


def _codearts_request(
    method: str,
    url: str,
    credential: CodeArtsCredential,
    fetcher: Fetcher,
    body: bytes | None = None,
) -> tuple[int, str]:
    headers = sign_huawei(
        credential.ak, credential.sk, credential.security_token, method, url, body or b""
    )
    headers.pop("host", None)  # 运行时自己带，手工设置会被拒
    headers.update(CODEARTS_EXTRA_HEADERS)
    return fetcher(method, url, headers, body)


def _codearts_unwrap(status: int, text: str) -> tuple[dict[str, object] | None, Outcome | None]:
    """解包两种信封：``ops/*`` 是 ``{code,message,data}``，``statistics`` 是裸对象。"""
    early = _classify_transport(status, text)
    if early is not None:
        return None, early
    parsed = _json_or_none(text)
    if parsed is None:
        return None, Outcome(FAILED, message="响应不是 JSON 对象")
    if isinstance(parsed.get("code"), int) and not isinstance(parsed.get("code"), bool):
        code = int(parsed["code"])  # type: ignore[arg-type]
        if code != 0:
            message = _read_str(parsed, "message") or _read_str(parsed, "msg") or f"业务码 {code}"
            return None, Outcome(FAILED, message=message, code=code)
        data = parsed.get("data")
        if isinstance(data, dict):
            return dict(data), None
        return None, Outcome(FAILED, message="响应缺少 data 字段")
    return parsed, None


def codearts_account(
    credential: CodeArtsCredential, fetcher: Fetcher
) -> tuple[dict[str, object] | None, Outcome | None]:
    """读账户/套餐信息（只读）。返回 ``(package, 失败结论)``。"""
    status, text = _codearts_request(
        "GET", CODEARTS_BASE + CODEARTS_PACKAGE_PATH, credential, fetcher
    )
    return _codearts_unwrap(status, text)


def codearts_activities(
    credential: CodeArtsCredential, fetcher: Fetcher
) -> tuple[list[dict[str, object]] | None, Outcome | None]:
    """读活动列表（只读）。"""
    url = f"{CODEARTS_BASE}{CODEARTS_DELIVERY_PATH}?channel={CODEARTS_CHANNEL}"
    status, text = _codearts_request("GET", url, credential, fetcher)
    data, failure = _codearts_unwrap(status, text)
    if failure is not None:
        return None, failure
    assert data is not None
    items = data.get("items")
    if not isinstance(items, list):
        return None, Outcome(FAILED, message="响应缺少 items 字段")
    return [dict(item) for item in items if isinstance(item, dict)], None


def codearts_summary(credential: CodeArtsCredential, fetcher: Fetcher) -> Outcome:
    """``--probe`` 用的只读结论：积分账户？今天领没领？（**不发任何写请求**）"""
    package, failure = codearts_account(credential, fetcher)
    if failure is not None:
        return failure
    assert package is not None
    pkg = _read_record(package, "package")
    if not _read_bool(pkg, "is_credit_package"):
        reason = "Token 计费账户" if _read_bool(pkg, "is_token_package") else "非积分计费账户"
        return Outcome(INACTIVE, message=f"{reason}，不在积分活动范围")

    activities, failure = codearts_activities(credential, fetcher)
    if failure is not None:
        return failure
    assert activities is not None
    daily = next(
        (item for item in activities if _read_str(item, "type") == CODEARTS_DAILY_TYPE), None
    )
    if daily is None:
        return Outcome(INACTIVE, message="活动列表里没有每日签到")
    if _read_bool(daily, "claimable"):
        amount = _read_num(daily, "benefitAmount") or _read_num(daily, "amount")
        return Outcome(INACTIVE, message=f"可领取（{_fmt(amount)} 积分待领）")
    status_text = _read_str(daily, "status")
    if status_text in CODEARTS_CLAIMED_STATUSES:
        return Outcome(ALREADY_CLAIMED, message="今天已领取")
    return Outcome(INACTIVE, message=f"当前不可领取（status={status_text}）")


def claim_codearts(
    credential: CodeArtsCredential, fetcher: Fetcher, *, apply: bool = True
) -> Outcome:
    """codearts 每日签到的完整流程（卡 §4.1）。

    判定顺序每一步对用户含义都不同：查不到账户 ⇒ ``failed``；Token 账户 ⇒
    ``inactive``；找不到每日签到活动 ⇒ ``inactive``；已领 ⇒ ``already-claimed``；
    领取失败 ⇒ ``failed``；成功 ⇒ ``claimed``（``id != null`` 时补 confirm）。
    """
    if not apply:
        return codearts_summary(credential, fetcher)

    package, failure = codearts_account(credential, fetcher)
    if failure is not None:
        return Outcome(
            failure.kind, message=f"账户信息查询失败：{failure.message}", code=failure.code
        )
    assert package is not None
    pkg = _read_record(package, "package")
    if not _read_bool(pkg, "is_credit_package"):
        reason = "Token 计费账户" if _read_bool(pkg, "is_token_package") else "非积分计费账户"
        return Outcome(INACTIVE, message=f"{reason}，不在积分活动范围")

    activities, failure = codearts_activities(credential, fetcher)
    if failure is not None:
        return Outcome(
            failure.kind, message=f"活动列表查询失败：{failure.message}", code=failure.code
        )
    assert activities is not None
    daily = next(
        (item for item in activities if _read_str(item, "type") == CODEARTS_DAILY_TYPE), None
    )
    if daily is None:
        return Outcome(INACTIVE, message="活动列表里没有每日签到")
    if not _read_bool(daily, "claimable"):
        status_text = _read_str(daily, "status")
        if status_text in CODEARTS_CLAIMED_STATUSES:
            return Outcome(ALREADY_CLAIMED, message="今天已领取")
        return Outcome(INACTIVE, message=f"当前不可领取（status={status_text}）")
    campaign_id = _read_scalar(daily, "campaignId")
    if campaign_id in (None, ""):
        return Outcome(FAILED, message="活动缺少 campaignId，无法领取")

    body = json.dumps({"campaignId": campaign_id, "channel": CODEARTS_CHANNEL}).encode()
    status, text = _codearts_request(
        "POST", CODEARTS_BASE + CODEARTS_CLAIM_PATH, credential, fetcher, body
    )
    data, failure = _codearts_unwrap(status, text)
    if failure is not None:
        return Outcome(FAILED, message=f"领取失败：{failure.message}", code=failure.code)
    assert data is not None

    benefit_id = data.get("id")
    if benefit_id is not None:
        # 服务端要求确认：漏了这一步积分停在「待确认」不入账。
        # 确认失败**不改判**成 failed —— 积分已进待确认态，报失败会让人重复点。
        status, text = _codearts_request(
            "POST",
            CODEARTS_BASE + CODEARTS_CONFIRM_PATH,
            credential,
            fetcher,
            json.dumps({"campaignId": campaign_id}).encode(),
        )
        confirm_failure = _classify_transport(status, text)
        if confirm_failure is not None:
            return Outcome(
                CLAIMED,
                message=f"已领取，但确认失败（{confirm_failure.message}）—— 积分停在待确认",
                credit=_claim_credit(data, daily),
                unit="积分",
                extra={"confirm_failed": True},
            )

    return Outcome(
        CLAIMED,
        message="领取成功",
        credit=_claim_credit(data, daily),
        unit="积分",
        extra={"campaign_id": campaign_id},
    )


def _claim_credit(data: Mapping[str, object], daily: Mapping[str, object]) -> float:
    """本次发放积分：领取响应优先，回退活动条目；都没有就如实记 0（不臆造 1000）。"""
    for key in ("benefitAmount", "credit", "credits", "creditAmount", "amount"):
        value = _read_num(data, key)
        if value:
            return value
    for key in ("benefitAmount", "amount", "creditAmount"):
        value = _read_num(daily, key)
        if value:
            return value
    return 0.0


# ---------------------------------------------------------------- 腾讯系 / qoder / trae / minimax

WORKBUDDY_BASE = "https://copilot.tencent.com"
WORKBUDDY_STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
WORKBUDDY_CLAIM_PATH = "/v2/billing/meter/daily-checkin"
WORKBUDDY_UNIT = "点"

QODER_BASE = "https://openapi.qoder.com.cn"
QODER_CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"
QODER_UNIT = "credits"

TRAE_BASE = "https://api.trae.cn"
TRAE_STATUS_PATH = "/trae/api/v2/ug/checkin_credits/status"
TRAE_CLAIM_PATH = "/trae/api/v2/ug/checkin_credits/claim"
TRAE_UNIT = "credits"

MINIMAX_BASE = "https://api.minimax.chat"
MINIMAX_STATUS_PATH = "/minimax-cloud/api/v1/signin/status"
MINIMAX_CLAIM_PATH = "/minimax-cloud/api/v1/signin/claim"
MINIMAX_UNIT = "积分"
MINIMAX_CLAIMED_STATUS = 3  # is_today && status === 3 才是「今天已领」


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def claim_workbuddy(token: str, fetcher: Fetcher, *, apply: bool = True) -> Outcome:
    """腾讯 WorkBuddy：状态端点 404 ⇒ ``not-supported``（上游确实没这能力，不是故障）。"""
    status, text = fetcher("GET", WORKBUDDY_BASE + WORKBUDDY_STATUS_PATH, _bearer(token), None)
    early = _classify_transport(status, text)
    if early is not None:
        return early
    payload = _json_or_none(text) or {}
    data = _read_record(payload, "data") or payload
    if _read_bool(data, "checked_in") or _read_bool(data, "checkedIn"):
        return Outcome(ALREADY_CLAIMED, message="今天已领")
    if not apply:
        return Outcome(INACTIVE, message="今天还没领（可领）")
    status, text = fetcher("POST", WORKBUDDY_BASE + WORKBUDDY_CLAIM_PATH, _bearer(token), b"{}")
    early = _classify_transport(status, text)
    if early is not None:
        return Outcome(FAILED, message=f"领取失败：{early.message}", code=early.code)
    payload = _json_or_none(text) or {}
    data = _read_record(payload, "data") or payload
    credit = _read_num(data, "amount") or _read_num(data, "credit") or _read_num(data, "points")
    return Outcome(CLAIMED, message="领取成功", credit=credit, unit=WORKBUDDY_UNIT)


def claim_qoder(token: str, fetcher: Fetcher, *, apply: bool = True) -> Outcome:
    """qoder：``campaigns`` → ``claim``；**领取成功后列表仍非空**，不能拿空列表判已领。"""
    status, text = fetcher("GET", QODER_BASE + QODER_CAMPAIGNS_PATH, _bearer(token), None)
    early = _classify_transport(status, text)
    if early is not None:
        return early
    payload = _json_or_none(text) or {}
    items = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("items")
    campaigns = (
        [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    )
    claimable = [
        item
        for item in campaigns
        if _read_bool(item, "claimable")
        or _read_str(item, "status").upper() in {"CLAIMABLE", "AVAILABLE", "ENTRY"}
    ]
    if not claimable:
        if campaigns:
            return Outcome(ALREADY_CLAIMED, message="今天已领")
        return Outcome(INACTIVE, message="今天没有可领活动")
    if not apply:
        return Outcome(INACTIVE, message=f"可领取（{len(claimable)} 个活动待领）")

    total = 0.0
    for item in claimable:
        campaign_id = _read_ident(item, "campaignId") or _read_ident(item, "id")
        if not campaign_id:
            return Outcome(FAILED, message="活动缺少 campaignId，无法领取")
        status, text = fetcher(
            "POST",
            f"{QODER_BASE}{QODER_CAMPAIGNS_PATH}/{campaign_id}/claim",
            _bearer(token),
            b"",
        )
        early = _classify_transport(status, text)
        if early is not None:
            return Outcome(FAILED, message=f"领取失败：{early.message}", code=early.code)
        payload = _json_or_none(text) or {}
        total += _read_num(payload, "credit") or _read_num(_read_record(payload, "data"), "credit")
    return Outcome(CLAIMED, message="领取成功", credit=total, unit=QODER_UNIT)


def claim_trae(token: str, fetcher: Fetcher, *, apply: bool = True) -> Outcome:
    """Trae：cookie/bearer 两步；额度单位 credits。"""
    status, text = fetcher("GET", TRAE_BASE + TRAE_STATUS_PATH, _bearer(token), None)
    early = _classify_transport(status, text)
    if early is not None:
        return early
    payload = _json_or_none(text) or {}
    data = _read_record(payload, "data") or payload
    if _read_bool(data, "claimed") or _read_bool(data, "checked_in"):
        return Outcome(ALREADY_CLAIMED, message="今天已领")
    if not apply:
        return Outcome(INACTIVE, message="今天还没领（可领）")
    status, text = fetcher("POST", TRAE_BASE + TRAE_CLAIM_PATH, _bearer(token), b"{}")
    early = _classify_transport(status, text)
    if early is not None:
        return Outcome(FAILED, message=f"领取失败：{early.message}", code=early.code)
    payload = _json_or_none(text) or {}
    data = _read_record(payload, "data") or payload
    credit = _read_num(data, "credits") or _read_num(data, "credit")
    return Outcome(CLAIMED, message="领取成功", credit=credit, unit=TRAE_UNIT)


def claim_minimax(
    token: str, fetcher: Fetcher, *, apply: bool = True, timezone_id: str = "Asia/Shanghai"
) -> Outcome:
    """minimax：``timezone_id`` 必填 query；业务码在 ``base_resp.status_code``，
    HTTP 200 也可能是业务失败（卡 §4.5 的钉子）。"""
    query = f"?timezone_id={timezone_id}"
    status, text = fetcher("GET", MINIMAX_BASE + MINIMAX_STATUS_PATH + query, _bearer(token), None)
    early = _classify_transport(status, text)
    if early is not None:
        return early
    payload = _json_or_none(text) or {}
    base = _read_record(payload, "base_resp")
    if int(_read_num(base, "status_code")) != 0:
        return Outcome(
            FAILED,
            message=_read_str(base, "status_msg") or "业务码非 0",
            code=int(_read_num(base, "status_code")),
        )
    data = _read_record(payload, "data") or payload
    if _read_bool(data, "is_today") and int(_read_num(data, "status")) == MINIMAX_CLAIMED_STATUS:
        return Outcome(ALREADY_CLAIMED, message="今天已领")
    if not apply:
        return Outcome(INACTIVE, message="今天还没领（可领）")
    status, text = fetcher("POST", MINIMAX_BASE + MINIMAX_CLAIM_PATH + query, _bearer(token), b"{}")
    early = _classify_transport(status, text)
    if early is not None:
        return Outcome(FAILED, message=f"领取失败：{early.message}", code=early.code)
    payload = _json_or_none(text) or {}
    base = _read_record(payload, "base_resp")
    if int(_read_num(base, "status_code")) != 0:
        return Outcome(
            FAILED,
            message=_read_str(base, "status_msg") or "业务码非 0",
            code=int(_read_num(base, "status_code")),
        )
    data = _read_record(payload, "data") or payload
    credit = _read_num(data, "points")
    return Outcome(CLAIMED, message="领取成功", credit=credit, unit=MINIMAX_UNIT)


# ---------------------------------------------------------------- 分派


def platform_supports_claim(platform: Mapping[str, object]) -> bool:
    """能力表里 ``claim_flow`` 为空 ⇒ 上游没有签到（``not-supported``，不算故障）。"""
    flow = platform.get("claim_flow")
    return isinstance(flow, list) and bool(flow)


def claim_for_platform(
    platform_name: str,
    platform: Mapping[str, object],
    tokens: Sequence[str],
    fetcher: Fetcher,
    *,
    apply: bool = True,
) -> Outcome:
    """按能力表分派到具体平台的领取客户端。**凭据缺失一律 uncertain，不猜。**"""
    if not platform_supports_claim(platform):
        return Outcome(NOT_SUPPORTED, message="上游没有签到接口（不是故障）")

    try:
        if platform_name == "codearts":
            if len(tokens) < 2 or not tokens[0] or not tokens[1]:
                return Outcome(UNCERTAIN, message="缺 AK/SK（设 TF_CODEARTS_AK / TF_CODEARTS_SK）")
            credential = CodeArtsCredential(
                tokens[0], tokens[1], tokens[2] if len(tokens) > 2 else ""
            )
            return claim_codearts(credential, fetcher, apply=apply)
        if not tokens or not tokens[0]:
            env = platform.get("token_env") or "（能力表没写 token_env）"
            return Outcome(UNCERTAIN, message=f"账本只存指针，没有凭据可发（要真跑请设 {env}）")
        token = tokens[0]
        if platform_name == "workbuddy":
            return claim_workbuddy(token, fetcher, apply=apply)
        if platform_name == "qoder":
            return claim_qoder(token, fetcher, apply=apply)
        if platform_name == "trae":
            return claim_trae(token, fetcher, apply=apply)
        if platform_name == "minimax":
            return claim_minimax(token, fetcher, apply=apply)
        return Outcome(
            NOT_SUPPORTED, message=f"{platform_name} 还没实现领取客户端（卡 §4 逐个打穿）"
        )
    except NetworkError as exc:
        # 网络不明 => uncertain，**不重放**
        return Outcome(UNCERTAIN, message=f"网络不明：{exc}")


def _account_discovery_off() -> bool:
    """问一次闸（判据那一份在 `tools/pool_accounts.py`，这里只问、不重写）。

    lazy import：`pool_accounts` 与 `checkin` 互相用，模块级 import 会成环。
    """
    try:
        import pool_accounts
    except ImportError:  # 以 `tools.pool.checkin` 被导入时（tools/ 不在 sys.path 上）
        from tools import pool_accounts
    return bool(pool_accounts.discovery_off())


def tokens_from_env(platform: Mapping[str, object], environ: Mapping[str, str]) -> list[str]:
    """按 ``token_env``（多个用 ``/`` 分隔）取凭据，缺的位置留空串。"""
    if _account_discovery_off():
        return []
    names = str(platform.get("token_env") or "")
    return [environ.get(name.strip(), "") for name in names.split("/") if name.strip()]
