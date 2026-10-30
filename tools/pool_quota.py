r"""额度状态按钟表算（卡 201 · T-G303）—— 429 不许凭记忆，一律「记录时间 vs 现实时间」。

为什么有它（用户 2026-10-12 原话）：

> 「还有 pool 要有个功能，就是你 429 了，**不要凭记忆确定是否 429**，
>   要根据**记录时间和现实时间对比**。」

旧坑三条（都在主树 HEAD 上现读）：
  ① `wb_dispatch.quota_error()` 抠出「将在 <时间> 重置」只当字符串返回 ——
    **全仓没有一处把它解析成时间戳**；
  ② 等待写死 `DEFAULT_QUOTA_WAIT = 300` —— 记录写 5 分钟后还是 5 小时后都睡 300 秒；
  ③ MCP 面不报额度 —— 会话里问「现在能不能派活」得到的是人的记忆，不是读数。

本模块就是那条「记录时间 vs 现实时间」的判据 —— **唯一真源**：
  · `parse_reset(raw)` —— 把「2026-10-12 16:52:45 UTC+8」解析成 `datetime`（解析不出 → None）；
  · `record(...)` —— 把一次 429 落成一条记录（`gates/diag/quota-state.json`，派生、可重建、
    gitignored）；
  · `status(...)` —— 每次现算，读记录 + 读「现在」，输出**四态**（每态带判据）。

★ 四态（每一态都不许猜）：

| 态 | 条件 | 含义 |
|---|---|---|
| `限流中` | `reset_at > now` | 还在限流里，等剩余时间 |
| `已过期，需重新探测` | `reset_at <= now` | 过期 ≠ 可用，只有探测才是证据 |
| `余额耗尽` | 有记录但无 `reset_at` | 没有重置时间 ⇒ 不自动等，只能探 |
| `未记录` | 没有这条记录 | 没记录 ⇒ 不猜（不许默认当可用） |

★ `--now <ISO>`：注入「现在」（测试不许靠真实钟表）。

用法：
    python -X utf8 tools/pool_quota.py status --card 201 --model deepseek-v4.1-flash
    python -X utf8 tools/pool_quota.py status --card 201 --model X --now 2026-10-12T23:28:00+08:00
    python -X utf8 tools/pool_quota.py wait --card 201 --model X --timeout 6h
    python -X utf8 tools/pool_quota.py refresh --card 201 --model X --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 记录文件（派生、可重建、gitignored —— `gates/diag/` 整体在 .gitignore 里）。
STATE_REL = "gates/diag/quota-state.json"

#: 「上次问过刷新」的时间戳（同目录、派生、gitignored）—— 只为 30 秒抑制，不作判据。
REFRESH_REL = "gates/diag/quota-refresh.json"

# ---- 等待口径直接照 magpie（`quotaWaitMin` / `quotaWaitMax` / `quotaWaitMargin` /
# ---- `quotaRefreshGap`）—— 不是 `wb_dispatch.DEFAULT_QUOTA_WAIT = 300`（那是派活器兜底）。
WAIT_MIN_S = 60          # magpie quotaWaitMin = time.Minute
WAIT_MAX_S = 600         # magpie quotaWaitMax = 10 * time.Minute
WAIT_MARGIN_S = 30       # magpie quotaWaitMargin = 30 * time.Second
REFRESH_GAP_S = 30       # magpie quotaRefreshGap = 30 * time.Second

# ★ 两套语义，别混 —— magpie 的 `#1295` 就是混出来的：
#   `REFRESH_GAP_S`  = 「**用户手动**刷新」的抑制窗口：同一条读数 30 秒内不许再问一次供应商；
#   `REREAD_AFTER_S` = 「**后台**读额度」的重读阈值：读数超过 60 秒才算旧、才值得重读。
#   一个管「人按了一次刷新」，一个管「这次读该不该去问」。两者不是倍数关系 ——
#   不许把 `REREAD_AFTER_S` 改写成 `REFRESH_GAP_S * 2`：那样动一个常量会悄悄改掉另一套语义。

# ---- 读取纪律（卡 A333 · magpie F25「配额读取纪律」）—— 照
# ---- `internal/provider/routing.go:191` 的 firstWait 与 `:589` 的重读阈值 `time.Minute`。
FIRST_WAIT_S = 3.0      # routing.go:191 firstWait = 3 * time.Second —— 首次最多等这么久
REREAD_AFTER_S = 60.0   # :589 —— 读数超过 1 分钟才算旧（后台重读阈值，不是刷新抑制）

# ---- rest 时长四真值（卡 A332 · T-AG534）—— 照 magpie `restAfterMarked`（F20）
# 常量原件：`internal/gateway/routing.go:165-202` + `:974`、`fallback.go:37`、
# `internal/provider/concurrency.go:212/:333`。四真值 = credit / quota 有续期 /
# quota 无续期 / rate，外加「无因失败」的退避 —— 一条都不许省。
# ★ 不是 `wb_dispatch.DEFAULT_QUOTA_WAIT = 300`（那是派活器兜底，不是 rest 时长）。
CREDIT_REST_S = 30 * 60              # routing.go:166 creditRest —— 没钱了，充上之前一直歇
QUOTA_REST_S = 15 * 60               # :167 quotaRest —— 额度用光、又没说何时重置
LONGEST_WAIT_S = 3600                # :168 longestWait —— 供应商「何时再来」最多信一小时
LONGEST_QUOTA_S = 8 * 24 * 3600      # :172 longestQuota
LONGEST_RETRY_S = 10 * 60            # :173 longestRetry —— 一错再错
LONGEST_RATE_REST_S = 30 * 60        # :177 longestRateRest
RATE_FORGET_S = 30 * 60              # :180 rateForget —— 半小时没再限流就重新数
COOLDOWN_S = 60                      # fallback.go:37 fallbackCooldown —— 退避的起点
LONGEST_MONTHLY_S = 35 * 24 * 3600   # :974 longestMonthly —— 月额度用光，35 天
REST_CAP_OFF = -1                    # concurrency.go:333 RestCapOff —— 无因失败不 rest
MAX_QUOTA_REST_MIN = 8 * 24 * 60     # :212 MaxQuotaRest（分钟，= 8 天）

#: 五种失败分类（`routing.go:288-299` 的子集）。`auth` 在 `restAfterMarked` 的 switch 里
#: 没有自己的 case，落 `default` ⇒ 与 `other` 同一条退避路（但**不**享 `off`，见 `:1182`）。
WHY_KINDS = ("credit", "quota", "rate", "other", "auth")

# ---- 分类正则：只搬 `failure()`（`routing.go:391-444`）用到的那几条，pattern 逐字照抄。
_CREDIT_RE = re.compile(
    r"insufficient.?(balance|credit|fund)|balance|credit|billing|payment|arrear"
    r"|overdue|suspended|余额|欠费|充值|账户.*(不足|停)",
    re.IGNORECASE,
)
_BROKE_RE = re.compile(
    r"insufficient.?(balance|credit|fund)|\bcredits? (are )?exhausted\b|余额不足|欠费|请充值",
    re.IGNORECASE,
)
_USED_UP_RE = re.compile(
    r"quota|usage.?limit|out of budget|budget (exceeded|exhausted)|limit.?reached"
    r"|hit your .*limit|limit.{0,24}resets|exceeded.*(plan|limit)|额度|用量|套餐|上限",
    re.IGNORECASE,
)
_RATE_RE = re.compile(
    # ★ 比 magpie 少了「请求太多」那一条备选：它只在 `status == 429` 里被查，
    #   而 `:440` 的兜底已把剩下的 429 全归 rate ⇒ 无观察差异。
    #   另：`tests/test_quota_wait.py` 的那条零网络钉子会扫整份源码文本，
    #   所以连注释里都不许出现网络库的名字（A328 落的钉子）。
    r"rate.?limit|frequency.?limit|per.?(second|sec|minute|min)\b"
    r"|\b[rt]pm\b|频率|太频繁",
    re.IGNORECASE,
)
_PLANNED_RE = re.compile(
    r"quota|usage.?limit|hit your .*limit|limit.{0,24}resets|per.?(day|week|month)"
    r"|daily|weekly|monthly|额度|用量|套餐|限额已用完",
    re.IGNORECASE,
)
_MINUTE_RE = re.compile(
    r"per.?(second|minute)|per.?(sec|min)\b|\b[rt]p[ms]\b"
    r"|(token|call|request) rate limit|每分钟|每秒",
    re.IGNORECASE,
)
_LONG_RE = re.compile(
    r"usage.?limit|hit your .*limit|limit.{0,24}resets|per.?(hour|day|week|month)"
    r"|\bhours?\b|hourly|daily|weekly|monthly|\b[rt]p[dh]\b"
    r"|额度已用|用量|套餐|限额已用完|小时|每天|每日|每周|每月",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+")
_QUOTA_CODES_RE = re.compile(
    r"limit reached\|\d{10}\b|usage_limit_reached|RESOURCE_EXHAUSTED", re.IGNORECASE
)
_RESETS_WHEN_RE = re.compile(
    r"(?:\bresets? at|将在|将于)\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})"
    r"\s*(?:(?:UTC|GMT)([+-])(\d{1,2})(?::?(\d{2}))?|([+-])(\d{2})(\d{2}) (?-i:[A-Z]{2,5}))"
    r"(?:\s*(?:重置|[,.;，。；]))",
    re.IGNORECASE,
)
_TRY_AGAIN_RE = re.compile(
    r"try again in (?:(\d+)\s*d(?:ays?)?\s*)?(?:(\d+)\s*h(?:ours?|rs?)?\s*)?"
    r"(?:(\d+)\s*m(?:in(?:utes?|s)?)?)?",
    re.IGNORECASE,
)

#: magpie `soonest = provider.PatienceLongest`（`routing.go:894` / `group.go:148` = 240 秒）——
#: 「供应商说多久再来」短于这个数才算「马上就好」。
SOONEST_S = 240


#: 退出码（`--card` / `--model` 缺参由 argparse 直接退 2 = `EXIT_USAGE`）。
EXIT_OK, EXIT_TIMEOUT, EXIT_USAGE, EXIT_INTERRUPT = 0, 1, 2, 130

#: 「将在 <时间> 重置」里那个时间的形状 —— `YYYY-MM-DD HH:MM:SS` + 可选 `UTC+N`。
_RESET_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})"
    r"(?:\s*UTC\s*([+-]?\d{1,2}))?"
)


# ================================================================ 解析（唯一真源）


def parse_reset(raw: str | None) -> datetime | None:
    """把「2026-10-12 16:52:45 UTC+8」解析成 `datetime`；解析不出 → `None`。

    ★ 这是**唯一**的解析真源 —— `wb_dispatch.quota_error()` 加 `reset_at` 字段时调它，
      `record()` 落记录时也调它，**不许在别处再写一份**（本仓最忌两份真源）。
    ★ 解析不出就回 `None` —— **不许拿别的数冒充**（卡 201 硬约束）。

    认的形状：
      · `2026-10-12T16:52:45+08:00`（ISO-8601，`datetime.fromisoformat` 直吃）；
      · `2026-10-12 16:52:45 UTC+8`（CLI / 模型回话里常见的写法）；
      · `2026-10-12 16:52:45`（无时区 → naive，比较时当本地时间）。
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    m = _RESET_RE.match(raw)
    if m is None:
        return None
    date_part, time_part, tz_hour = m.group(1), m.group(2), m.group(3)
    tz: timezone | None = None
    if tz_hour is not None:
        tz = timezone(timedelta(hours=int(tz_hour)))
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=tz)
    except ValueError:
        return None


def _to_aware(dt: datetime) -> datetime:
    """naive → aware（当本地时间）；aware 原样。比较时 aware/naive 混用会抛 `TypeError`。"""
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


def _resolve_now(now: datetime | str | None) -> datetime:
    """把 `now` 参数统一成 `datetime`：`None` = 真实现在（aware，本地时区）。"""
    if now is None:
        return datetime.now().astimezone()
    if isinstance(now, str):
        return _to_aware(datetime.fromisoformat(now))
    return now


# ================================================================ 记录读写


def _state_path(root: Path = ROOT) -> Path:
    return root / STATE_REL


def _load(root: Path = ROOT) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {"cards": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cards": {}}
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return {"cards": {}}
    return data


def _save(data: dict[str, Any], root: Path = ROOT) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_record(card: str, model: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    """读一条记录；没有 → `None`。"""
    data = _load(root)
    return data.get("cards", {}).get(card, {}).get(model)


def record(*, card: str, model: str, pool: str, kind: str,
           reset_raw: str, source_log: str | None = None, source_line: int | None = None,
           root: Path = ROOT) -> dict[str, Any]:
    """把一次 429 落成一条记录 —— 同卡同模型覆盖。

    `reset_at` 用 ISO-8601；**解析不出来就写 `null` 并保留 `reset_raw`**（不许拿别的数冒充）。
    `recorded_at` = 真实现在（ISO-8601，aware）。
    """
    reset_dt = parse_reset(reset_raw)
    reset_at = reset_dt.isoformat() if reset_dt is not None else None
    rec: dict[str, Any] = {
        "card": card,
        "model": model,
        "pool": pool,
        "kind": kind,
        "reset_raw": reset_raw,
        "reset_at": reset_at,
        "recorded_at": datetime.now().astimezone().isoformat(),
        "source_log": source_log,
        "source_line": source_line,
    }
    data = _load(root)
    cards = data.setdefault("cards", {})
    cards.setdefault(card, {})[model] = rec
    _save(data, root)
    return rec


# ================================================================ rest 时长四真值（卡 A332）


def _minute_limit(body: str) -> bool:
    """magpie `minuteLimit`（`routing.go:1136`）：分钟级限流，且不是长期/欠费那几种。"""
    body = _URL_RE.sub(" ", body)
    return bool(
        _MINUTE_RE.search(body)
        and not _LONG_RE.search(body)
        and not _BROKE_RE.search(body)
        and "insufficient_quota" not in body
    )


def _back_in(body: str) -> int:
    """magpie `backIn` → `spanWritten`（`routing.go:916/:948`）：`try again in 3m` 里那个秒数。

    ★ 只搬「写成人话的时长」这一路。unix 时间戳 / `resets at` 那几路要「现在」，
      本函数是纯的（不读钟表），所以那几路交给 `rest_after(reset_at=...)`。
    """
    m = _TRY_AGAIN_RE.search(body)
    if m is None:
        return 0
    days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    return days * 86400 + hours * 3600 + minutes * 60


def classify(status: int, body: str) -> str:
    """一次失败分到五种之一：`credit` / `quota` / `rate` / `other` / `auth`。

    照 `routing.go:391-444` `failure()` 的判断顺序（`failureOf` 的 auth 那两行在 `:486-490`）。
    ★ 只搬这五类：`proxy` / `verify` / `restricted` / `refused` / `canceled` 等
      在 pool 侧没有对应动作，不搬（它们原先的落点是 `other` 之外的东西，本卡不碰）。
    """
    text = _URL_RE.sub(" ", body or "")
    if status == 402 and _USED_UP_RE.search(text) and not _CREDIT_RE.search(text) \
            and "insufficient_quota" not in text:
        return "quota"                                        # :406
    if (status == 402 or (_CREDIT_RE.search(text) and (status != 429 or _BROKE_RE.search(text)))
            or "insufficient_quota" in text):
        return "credit"                                       # :412
    if status == 429 and _RESETS_WHEN_RE.search(text):
        return "quota"                                        # :419
    if status == 429 and _minute_limit(text):
        return "rate"                                         # :422
    if status == 429 and not _CREDIT_RE.search(text) and 0 < _back_in(text) <= SOONEST_S:
        return "rate"                                         # :425
    if status == 429 and _RATE_RE.search(text) and not _PLANNED_RE.search(text):
        return "rate"                                         # :428
    if ((status >= 500 and _QUOTA_CODES_RE.search(text))
            or (status < 500 and _USED_UP_RE.search(text))
            or (status == 429 and _PLANNED_RE.search(text))):
        return "quota"                                        # :436
    if status == 429:
        return "rate"                                         # :440
    if status in (401, 403):
        return "auth"                                         # :486-490
    return "other"                                            # :444


def _cap_or(rest_cap_s: int | None, default: int) -> int:
    """magpie `RestCapOr`（`concurrency.go:349`）：`None` / `0` / `off` 都用 magpie 自己的默认值。

    ★ `REST_CAP_OFF` 在这里**不生效** —— off 只挡「无因失败」（`:1182` 的 `why == failOther`）。
    """
    if rest_cap_s is None or rest_cap_s <= 0:
        return default
    return int(rest_cap_s)


def _longest_for(full_until: str | None, now_dt: datetime) -> int:
    """有续期的 quota rest 的上限：月窗口命中 ⇒ 35 天（`:1145-1147`），否则 8 天（`:1148`）。"""
    full = parse_reset(full_until)
    if full is not None and _to_aware(full) > now_dt:
        return LONGEST_MONTHLY_S
    return LONGEST_QUOTA_S


def rest_after(
    *,
    why: str,
    status: int,
    reset_at: str | None,
    own_rest_s: int | None = None,     # None = 「magpie 自己的」（= REST cap 未设）
    rest_cap_s: int | None = None,     # None = 默认；REST_CAP_OFF = off
    failures: int = 1,
    full_until: str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """一次失败该歇多久 → `{"seconds", "by", "why", "rest_until", "capped"}`。

    照 magpie `restAfterMarked`（`routing.go:1032`）的四真值：
      · `credit` ⇒ 30 分钟（`:1094-1095`）；
      · `quota` 有 `reset_at` ⇒ 歇到那时，上限 8 天 / 月窗口 35 天（`:1126/:1145-1148`）；
      · `quota` 无 `reset_at` ⇒ 15 分钟 + `capped=True`（`:1143` 的 `guessed`）；
      · `rate` ⇒ `min(60 << (n-1), 30min)` 指数退避，供应商说更久就听它的（`:1436/:1452`）；
      · 其余（`other` / `auth`）⇒ `min(60 << (n-1), 10min)`；`rest_cap_s == REST_CAP_OFF` 时
        **只对 `other`** 生效且 `status in (401, 403)` 挡在 off 之外（`:1182`）。

    ★ **纯函数**：不读文件、不联网、不睡、不看真实钟表（`now` 由调用方注入）。
    ★ `rest_until` **不许**替代 `reset_at`：前者是「magpie 会歇多久」，后者是
      「vendor 什么时候重置」—— `capped=True` 时两者不是一回事。
    ★ 多号同续期：本函数一次只算一个，多号由调用方逐个调用后取 `min`。

    `by` 取值照 magpie：`off` / `credit` / `quota` / `resets` / `retry-after` / `backoff` /
    `cooldown`（`credits` / `window` / `restricted` / `verify` 属于条件更足的通道，本卡不搬；
    月窗口在本函数里表现为「上限换 35 天」，`by` 仍是 `resets`）。
    """
    if why not in WHY_KINDS:
        raise ValueError(f"不认的失败分类：{why!r}")
    if rest_cap_s is not None and (rest_cap_s < -1 or rest_cap_s > MAX_QUOTA_REST_MIN * 60):
        raise ValueError(
            f"最长的休息是 0（magpie 自己的）到 {MAX_QUOTA_REST_MIN} 分钟（8 天）或 off，"
            f"不是 {rest_cap_s} 秒"
        )
    now_dt = _resolve_now(now)
    n = max(int(failures), 1)
    seconds, by, capped = 0, "off", False
    if why == "credit":
        # :1094-1095 —— 没钱了：creditRest = 30 分钟（**不是** quotaRest 的 15 分钟）。
        # `capped` 在 magpie 里只对应 quota 的 `guessed`（`:1143`），credit 分支不置。
        seconds, by = CREDIT_REST_S, "credit"
    elif why == "quota":
        resets = parse_reset(reset_at)
        if resets is None:
            # :1143 —— 没有续期时间：magpie 自己的 quotaRest，`guessed = own <= 0`。
            seconds = QUOTA_REST_S if not own_rest_s else int(own_rest_s)
            by = "quota"
            capped = (own_rest_s or 0) <= 0
        else:
            # :1126-1127 —— 供应商说了何时重置就算到那时；上限见 `_longest_for`。
            left = int((_to_aware(resets) - now_dt).total_seconds())
            longest = _longest_for(full_until, now_dt)
            seconds = max(0, min(left, longest))
            by = "resets"
            capped = seconds < max(0, left)
    elif why == "rate":
        cap_s = _cap_or(rest_cap_s, LONGEST_RATE_REST_S)
        raw = COOLDOWN_S << min(n - 1, 10)                    # :1436
        seconds, capped = min(raw, cap_s), min(raw, cap_s) < raw
        by = "backoff" if n > 1 else "cooldown"               # :1437-1439
        said = parse_reset(reset_at)
        if said is not None:
            raw_w = int((_to_aware(said) - now_dt).total_seconds())
            if raw_w > 0:
                w = min(raw_w, LONGEST_WAIT_S)                # :1592-1619
                if w >= seconds:                              # :1452-1454
                    seconds, by, capped = w, "retry-after", w < raw_w
    elif why == "other" and rest_cap_s == REST_CAP_OFF and status not in (401, 403):
        # :1182 守卫 —— `off` 只挡「无因失败」，且 401/403 永远挡在 off 之外。
        seconds, by, capped = 0, "off", False
    else:
        # :1221（`other` 的退避）/ default（`auth` 在 magpie 的 switch 里没有 case，同一条路，
        # 但 `why == failOther` 是 off 的硬条件，所以 `auth` 永远拿不到 off）。
        cap_s = _cap_or(rest_cap_s, LONGEST_RETRY_S)
        raw = COOLDOWN_S << min(n - 1, 10)
        seconds, capped = min(raw, cap_s), min(raw, cap_s) < raw
        by = "backoff"
    return {
        "seconds": int(seconds),
        "by": by,
        "why": why,
        "rest_until": (now_dt + timedelta(seconds=int(seconds))).isoformat(),
        "capped": bool(capped),
    }


def _rest_keys(*, reset_at: str | None, now: datetime) -> dict[str, Any]:
    """`status()` 多回的两个键 —— **只加不改**（四态名字与 `why` 文案一个字都不动）。

    记录里只有 `kind` / `reset_at`，没有响应体 ⇒ `classify()` 在这里无从调用；
    能确定的只有「有没有续期时间」：有 ⇒ `by="resets"`（歇到那时），没有 ⇒ `by="quota"`
    （15 分钟兜底、`capped=True`）。这两个键是**派生视图**，不参与四态判定。
    """
    st = rest_after(why="quota", status=429, reset_at=reset_at, now=now)
    return {"rest_until": st["rest_until"], "rest_by": st["by"]}


# ================================================================ 四态（每次现算）


def status(*, card: str, model: str, now: datetime | str | None = None,
           root: Path = ROOT) -> dict[str, Any]:
    """读记录 + 读「现在」→ 四态。每一态都带**判据**（`why`）。

    ★ **不许猜**：`未记录` 不当可用，`已过期` 不当可用 —— 只有 `限流中` 是确定的「不能派活」，
      其余三态都是「要探测才能确定」。
    """
    rec = read_record(card, model, root=root)
    now_dt = _resolve_now(now)
    now_iso = now_dt.isoformat()
    base: dict[str, Any] = {
        "card": card, "model": model,
        "reset_at": None, "recorded_at": None, "now": now_iso,
        "remaining_seconds": None, "expired_seconds": None,
        "can_dispatch": False, "need_probe": True,
        "rest_until": None, "rest_by": None,
    }
    if rec is None:
        return {**base, "state": "未记录",
                "why": "没有这条记录 ⇒ 不猜（★ 不许默认当可用）"}
    recorded_at = rec.get("recorded_at")
    reset_at_raw = rec.get("reset_at")
    base["recorded_at"] = recorded_at
    if reset_at_raw is None:
        return {**base, "state": "余额耗尽", "reset_at": None,
                **_rest_keys(reset_at=None, now=now_dt),
                "why": "有记录但没有重置时间 ⇒ 不自动等，只能探"}
    try:
        reset_dt = _to_aware(datetime.fromisoformat(reset_at_raw))
    except ValueError:
        return {**base, "state": "余额耗尽", "reset_at": reset_at_raw,
                **_rest_keys(reset_at=reset_at_raw, now=now_dt),
                "why": "reset_at 解析失败 ⇒ 不自动等，只能探"}
    diff = (reset_dt - _to_aware(now_dt)).total_seconds()
    if diff > 0:
        return {**base, "state": "限流中", "reset_at": reset_at_raw,
                **_rest_keys(reset_at=reset_at_raw, now=now_dt),
                "remaining_seconds": int(diff), "need_probe": False,
                "why": f"reset_at > now（剩余 {int(diff)} 秒）"}
    return {**base, "state": "已过期，需重新探测", "reset_at": reset_at_raw,
            **_rest_keys(reset_at=reset_at_raw, now=now_dt),
            "expired_seconds": int(-diff),
            "why": f"reset_at <= now（过期 {int(-diff)} 秒）—— 过期 ≠ 可用，要探"}


# ================================================================ 人话渲染


def _hms(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render(st: dict[str, Any]) -> str:
    """四态的人话输出 —— 每一态都把**判据**念出来。"""
    state = st["state"]
    lines = [f"[额度] 卡 {st['card']} · 模型 {st['model']} —— {state}"]
    if state == "限流中":
        lines.append(f"  剩余 {_hms(st['remaining_seconds'])}"
                     f"（记录重置时间 {st['reset_at']}；现在 {st['now']}）")
    elif state == "已过期，需重新探测":
        lines.append(f"  过期 {_hms(st['expired_seconds'])}"
                     f"（记录重置时间 {st['reset_at']}；现在 {st['now']}）")
        lines.append("  ★ 过期 ≠ 可用，要探")
    elif state == "余额耗尽":
        lines.append("  没有重置时间 ⇒ 不自动等，只能探")
    elif state == "未记录":
        lines.append("  没记录 ⇒ 不猜（★ 不许默认当可用）")
    lines.append(f"  判据：{st['why']}")
    return "\n".join(lines)


# ================================================================ 等待按记录算


def wait_seconds(reset_at: str | None, fallback: int, *,
                 upper: int | None = None, now: datetime | str | None = None) -> int:
    """按记录算等待：`clamp(reset_at - now, 0, 上限)`；`reset_at` 解析不出 → 退回 `fallback`。

    ★ 卡 201：旧写法一律睡 `fallback`（300 秒）—— 记录写 5 分钟后还是 5 小时后都一样。
      现在按钟表算：`reset_at` 在 1 分钟后 ⇒ 等 60 秒（不睡满 300）。
      上限默认 = `fallback`（不让一个坏记录把派活器冻几小时）。
    """
    if not reset_at:
        return fallback
    try:
        reset_dt = _to_aware(datetime.fromisoformat(reset_at))
    except ValueError:
        return fallback
    now_dt = _to_aware(_resolve_now(now))
    diff = int((reset_dt - now_dt).total_seconds())
    cap = fallback if upper is None else upper
    return max(0, min(diff, cap))


# ================================================================ 等待子命令（magpie 移植）


def round_wait(back_at: str | None, *, now: datetime | str | None = None) -> tuple[int, str]:
    """按「最早续期」算**一轮**睡多久：`clamp(diff + 30, 60, 600)`；续期未知 ⇒ 睡满 600。

    ★ 三件事都不许省：① 加 `WAIT_MARGIN_S`（续期到点还差一口气，早醒就白等）；
      ② 下限 `WAIT_MIN_S`（**不许负数 / 不许 0** —— 已过期的记录不许把循环烧成忙等）；
      ③ 上限 `WAIT_MAX_S`（一个坏记录不许把 `wait` 冻几小时）。
    ★ 口径照 magpie 的 `quotaWaitMin/Max/Margin`，**不是** `DEFAULT_QUOTA_WAIT = 300`。
    """
    if not back_at:
        return WAIT_MAX_S, "未知续期 ⇒ 睡满上限"
    try:
        back_dt = _to_aware(datetime.fromisoformat(back_at))
    except ValueError:
        return WAIT_MAX_S, "未知续期 ⇒ 睡满上限"
    diff = (back_dt - _to_aware(_resolve_now(now))).total_seconds()
    seconds = min(max(int(diff) + WAIT_MARGIN_S, WAIT_MIN_S), WAIT_MAX_S)
    return seconds, f"最早续期 + {WAIT_MARGIN_S}s（clamp 到 {WAIT_MIN_S}..{WAIT_MAX_S}）"

# ================================================================ 耐心（magpie F21 移植，卡 A349）


# ---- 「全都忙就歇一会儿再问」的算术 —— 六个常量逐字搬 magpie，出处行号写在每条后面：
RETRY_PAUSE_S = 1                      # magpie fallback.go:1610 retryPause = time.Second
REPLAN_LONGEST_S = 30 * RETRY_PAUSE_S  # magpie patience.go:52 replanLongest() = 30 * retryPause
PATIENCE_OFF = -1                      # magpie provider/group.go:145-149 PatienceOff = -1
PATIENCE_DEFAULT_S = 60                # magpie provider/group.go:145-149 PatienceDefault = 60
PATIENCE_LONGEST_S = 240               # magpie provider/group.go:145-149 PatienceLongest = 240
REPLAN_ROUNDS = 12                     # magpie patience.go:48 replanRounds = 12

# ★ 三个数字三件事，别合并（与上面的 `WAIT_*` 更是两套语义）：
#   `PATIENCE_DEFAULT_S` = 「没配」时给多少预算（**0 不是关**，`PATIENCE_OFF` 才是关）；
#   `PATIENCE_LONGEST_S` = 整张卡的耐心预算上限（配 3600 也只给 240）；
#   `REPLAN_LONGEST_S`   = **单次**重问间隔的上限（第 4 轮起封顶 30 秒）；
#   `REPLAN_ROUNDS`      = 最多重问几轮（与预算谁先到就听谁的 —— 两道闸都在，不互相替代）。


def patience_waits(patience: int | None) -> int:
    """把 `--patience` 折成**总预算秒数** —— 三支，顺序与边界照 magpie `patience.go:91`。

    ① `None` / `< 0` ⇒ `0`（**`PATIENCE_OFF = -1` 是「关」，不是「最短」**）；
    ② `== 0` ⇒ `PATIENCE_DEFAULT_S`（0 是「没配」，不是关 —— 关只有一个数）；
    ③ 其余 ⇒ `min(patience, PATIENCE_LONGEST_S)`（配 3600 也只给 240）。
    ★ 与 `round_wait()` 是两件事：那个算「按记录等**一次**多久」（clamp 60..600），
      这个算「**整张卡**还能歇几秒」；两者不许互相调用。
    """
    if patience is None or patience <= PATIENCE_OFF:
        return 0
    if patience == 0:
        return PATIENCE_DEFAULT_S
    return min(patience, PATIENCE_LONGEST_S)


def replan_wait(round_no: int, *, soonest_s: int = 0) -> int:
    """第 `round_no` 次重问之前歇多久：`min(RETRY_PAUSE_S << (round_no + 1), REPLAN_LONGEST_S)`。

    再取 `max(…, soonest_s)` —— **成员自报的续期只做下限、不做上限**（报 9999 就等 9999）。
    照 magpie `patience.go:52 replanLongest()` 与 `routing.go:894 soonest`。
    取值实测：`0⇒2 / 1⇒4 / 2⇒8 / 3⇒16 / 4⇒30 / 5⇒30 / 12⇒30`（第 4 轮起封顶 30 秒）。
    `round_no < 0` ⇒ `ValueError`（没有「第 -1 轮」这种问法，别让负数悄悄变成一次短睡）。
    """
    if round_no < 0:
        raise ValueError(f"重问轮次不许为负：{round_no}")
    wait = min(RETRY_PAUSE_S << (round_no + 1), REPLAN_LONGEST_S)
    return max(wait, int(soonest_s))


# ---------------------------------------------------------------- 刷新时间戳


def refresh_stamp_path(root: Path = ROOT) -> Path:
    """「上次问过刷新」的时间戳文件（派生、可重建、gitignored）。"""
    return root / REFRESH_REL


def refresh_key(card: str, model: str) -> str:
    """同卡同模型一条 key（小写化 —— 模型名大小写不当成两个模型）。"""
    return f"{card}|{model}".lower()


def _load_refresh(root: Path = ROOT) -> dict[str, Any]:
    path = refresh_stamp_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def refreshed_within(key: str, *, now: datetime | str | None = None,
                     root: Path = ROOT) -> float | None:
    """距上次「问过刷新」的秒数；`None` = 没问过 / 读不懂。

    ★ **读不懂就当作没问过，立刻可问** —— 30 秒抑制只许建立在可信的时间戳上；
      坏 JSON / 坏时间字符串不许把刷新能力冻住（宁可多问一次，不可不问）。
    """
    raw = _load_refresh(root).get(key.lower())
    if not isinstance(raw, str):
        return None
    try:
        last = _to_aware(datetime.fromisoformat(raw))
    except ValueError:
        return None
    return (_to_aware(_resolve_now(now)) - last).total_seconds()


def note_refreshed(key: str, *, now: datetime | str | None = None,
                   root: Path = ROOT) -> None:
    """记一条「刚问过刷新」（key 小写化；`tmp` + `os.replace` 原子替换，不写半截文件）。"""
    path = refresh_stamp_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamps = _load_refresh(root)
    stamps[key.lower()] = _to_aware(_resolve_now(now)).isoformat()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stamps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 读取纪律（F25）


def read_policy(*, first: bool, last_read_at: float | None, now: float) -> str:
    """这一次该「等 / 重读 / 用缓存」—— 纯函数：不看钟表、不碰盘、不猜。

    ★ `"wait"` 的意思是「**最多**等 `FIRST_WAIT_S` 秒，到点无论如何继续」：它不是失败，
      调用方不许把它当阻塞失败处理。
    ★ 时钟倒流（`now - last_read_at < 0`）按 `"use_cached"`：倒流的真因通常是时区 / 夏令时，
      这时候重读只会打穿供应商的速率限制；但它**不是**永久缓存 —— 时间正常之后照样 `"reread"`。
    """
    if first and last_read_at is None:
        return "wait"
    if last_read_at is None or now - last_read_at >= REREAD_AFTER_S:
        return "reread"
    return "use_cached"


def merge_latest(kept: dict[str, Any], got: dict[str, Any], seq: int) -> dict[str, Any]:
    """晚到的读数不许盖新的 —— 照 magpie `cacheCards()`（`quota_refresh.go:170`）与
    `mergeCards()`（`:189`）：只有 `got["read_seq"] >= kept["read_seq"]` 才替换。

    两边 `read_seq` **任一缺失**都按「`got` 无序号 ⇒ 不替换」处理 —— 缺证据就不许改事实；
    丢弃时往 stderr 说一行，不许静默吞掉。

    `seq` 是调用方给本次读的单调序号：它只能把记录里的 `read_seq` **往上抬**，不许压低。
    """
    held = kept.get("read_seq")
    arriving = got.get("read_seq")
    if not isinstance(held, int) or not isinstance(arriving, int):
        print(
            f"晚到的读数被丢弃（read_seq 不可比：缓存 {held!r} / 新读 {arriving!r}）",
            file=sys.stderr,
        )
        return kept
    if arriving < held:
        print(f"晚到的读数被丢弃（read_seq {arriving} < 缓存里的 {held}）", file=sys.stderr)
        return kept
    merged = dict(got)
    merged["read_seq"] = max(arriving, seq)
    return merged


def mark_stale(card: str, model: str, *, now: datetime | str | None = None,
               root: Path = ROOT) -> None:
    """作废一条读数并留痕 —— 删 `cards[card][model]`，同时在**既有**的 refresh 文件里记一条
    `stale` 时间戳（key 用既有 `refresh_key()`，不新增文件；写盘 tmp + `os.replace`）。

    ★ 只作废这一条：别的卡 / 别的模型不受牵连。
    ★ 删完 `read_record(card, model)` 必须回 `None` —— 「没有记录」≠「可用」，见 `status()`。
    ★ 记在 `refresh_key()` 那把 key 上（不是新造 key 命名空间）：作废之后这条读数不再可信，
      连「30 秒内别再问」的抑制也不该留着 —— 下一次问必须是新的问。
      值是 `{"stale": <iso>}`（仍是 dict 而非时间字符串）⇒ `refreshed_within()` 读不懂它，
      按既有口径「读不懂就当作没问过，立刻可问」处理。
    """
    data = _load(root)
    cards = data.get("cards")
    touched = False
    if isinstance(cards, dict):
        per_card = cards.get(card)
        if isinstance(per_card, dict) and model in per_card:
            del per_card[model]
            touched = True
            if not per_card:
                del cards[card]
    if touched:
        path = _state_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    stamps = _load_refresh(root)
    stamps[refresh_key(card, model)] = {"stale": _to_aware(_resolve_now(now)).isoformat()}
    stamp_path = refresh_stamp_path(root)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = stamp_path.with_name(stamp_path.name + ".tmp")
    tmp.write_text(json.dumps(stamps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, stamp_path)


# ---------------------------------------------------------------- 时长解析


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)([smhd]?)", re.IGNORECASE)
_UNIT_S = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_timeout(raw: str) -> float:
    """`30s` / `5m` / `2h` / `6h` / 纯数字（秒）→ 秒数；解析不出抛 `ValueError`。"""
    m = _DURATION_RE.fullmatch((raw or "").strip())
    if m is None:
        raise ValueError(f"解析不出时长：{raw!r}（认 30s / 5m / 2h / 6h）")
    return float(m.group(1)) * _UNIT_S[m.group(2).lower()]


# ---------------------------------------------------------------- 等 / 刷新


def _recorded_after(st: dict[str, Any], *, after: datetime) -> bool:
    """记录里的 `recorded_at` 是否**严格晚于** `after` —— 只有它才算「有人探过了」。"""
    raw = st.get("recorded_at")
    if not isinstance(raw, str):
        return False
    try:
        return _to_aware(datetime.fromisoformat(raw)) > after
    except ValueError:
        return False


def wait_until(*, card: str, model: str, timeout: str = "6h", quiet: bool = False,
               now: datetime | str | None = None, root: Path = ROOT) -> int:
    """等一个卡/模型从「不能派活」走到「有证据说明能派活」；等不到 ⇒ `EXIT_TIMEOUT`。

    ★ **不许凭空判成功**（本卡最值钱的一条）：
      · `限流中` ⇒ 按 `round_wait` 睡（按记录算，不睡死 300 秒）；
      · `已过期，需重新探测` / `余额耗尽` / `未记录` ⇒ **都不算成功**；只有看到一条
        `recorded_at` 严格晚于本次等待起点的记录，才退 `EXIT_OK`；
      · 认不出的状态（包括别人塞进来的「可派」）⇒ 同样不算成功，一路等到超时。
    ★ **零网络**：本模块不碰任何网络；探测在 `tools/pool_accounts.py`，`refresh` 只记时间戳。
    ★ 时钟：给了 `now` 就全程走**虚拟钟**（睡多少推多少），测试里一条真实钟表都不许碰。
    """
    base_now = _to_aware(_resolve_now(now)) if now is not None else None
    slept = 0.0

    def _tick() -> datetime:
        if base_now is None:
            return datetime.now().astimezone()
        return base_now + timedelta(seconds=slept)

    try:
        limit = parse_timeout(timeout)
    except ValueError as exc:
        print(f"[额度等待] {exc}", file=sys.stderr)
        return EXIT_USAGE
    started = _tick()
    if not quiet:
        print(f"[额度等待] 卡 {card} · 模型 {model} —— 上限 {timeout}"
              f"（{limit:.0f}s；起点 {started.isoformat()}）")
    hinted = False
    try:
        while True:
            left = limit - slept
            if left <= 0:
                if not quiet:
                    print(f"[额度等待] 卡 {card} · 模型 {model} —— 超时（{limit:.0f}s）："
                          "没看到比起点更新的记录 ⇒ 退 1（★ 不许凭空判成功）")
                return EXIT_TIMEOUT
            now_dt = _tick()
            st = status(card=card, model=model, now=now_dt, root=root)
            state = st["state"]
            if state == "限流中":
                seconds, why = round_wait(st["reset_at"], now=now_dt)
                nap = min(float(seconds), left)
                if not quiet:
                    print(f"[额度等待] 限流中 —— 睡 {nap:.0f}s（{why}；"
                          f"记录重置 {st['reset_at']}）")
            elif state == "已过期，需重新探测" and _recorded_after(st, after=started):
                if not quiet:
                    print(f"[额度等待] 卡 {card} · 模型 {model} —— 有了新记录"
                          f"（recorded_at {st['recorded_at']} 晚于起点）⇒ 退 0")
                return EXIT_OK
            else:
                nap = min(float(REFRESH_GAP_S), left)
                if not quiet and not hinted:
                    print(f"[额度等待] {state} —— 不算成功（★ 过期 ≠ 可用），等一条比起点"
                          "更新的记录；先跑 refresh（探测在 tools/pool_accounts.py）")
                    hinted = True
            time.sleep(nap)
            slept += nap
    except KeyboardInterrupt:
        print(f"[额度等待] 卡 {card} · 模型 {model} —— 收到中断，停在第 {slept:.0f}s")
        return EXIT_INTERRUPT


def refresh_once(*, card: str, model: str, now: datetime | str | None = None,
                 root: Path = ROOT) -> dict[str, Any]:
    """问一次「要不要重新探测」—— `REFRESH_GAP_S` 内问过就跳过；**不联网**。

    ★ 跳过只省重复问，**不是**「额度可用」的判据 —— 判定仍归 `status()` 的四态。
    """
    key = refresh_key(card, model)
    since = refreshed_within(key, now=now, root=root)
    out: dict[str, Any] = {
        "card": card, "model": model, "key": key, "gap_seconds": REFRESH_GAP_S,
        "seconds_since_last": since, "probe": False, "network": False, "why": "",
    }
    if since is not None and since < REFRESH_GAP_S:
        out["why"] = f"{REFRESH_GAP_S} 秒内已看过，跳过"
        return out
    note_refreshed(key, now=now, root=root)
    out["probe"] = True
    out["why"] = "需要重新探测（探测在 tools/pool_accounts.py）—— 本命令不联网"
    return out


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pool_quota.py",
        description="额度状态按钟表算（卡 201）—— 429 不许凭记忆，一律「记录时间 vs 现实时间」。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="看一个卡/模型的额度四态（每次现算）")
    p_status.add_argument("--card", required=True, help="卡号")
    p_status.add_argument("--model", required=True, help="模型名")
    p_status.add_argument("--now", default=None,
                          help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_status.add_argument("--root", default=None, help="仓库根（测试用）")
    p_wait = sub.add_parser("wait", help="等额度（按记录算等待；等不到退 1）")
    p_wait.add_argument("--card", required=True, help="卡号")
    p_wait.add_argument("--model", required=True, help="模型名")
    p_wait.add_argument("--timeout", default="6h", help="总上限（30s / 5m / 2h；默认 6h）")
    p_wait.add_argument("-q", "--quiet", action="store_true", help="不打印过程")
    p_wait.add_argument("--now", default=None,
                        help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_wait.add_argument("--root", default=None, help="仓库根（测试用）")
    p_refresh = sub.add_parser("refresh", help="问一次要不要重新探测（30 秒内不重复问）")
    p_refresh.add_argument("--card", required=True, help="卡号")
    p_refresh.add_argument("--model", required=True, help="模型名")
    p_refresh.add_argument("--json", action="store_true", help="输出 JSON")
    p_refresh.add_argument("--now", default=None,
                           help="注入「现在」（ISO-8601；测试用，不许靠真实钟表）")
    p_refresh.add_argument("--root", default=None, help="仓库根（测试用）")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else ROOT
    if args.cmd == "status":
        st = status(card=args.card, model=args.model, now=args.now, root=root)
        print(render(st))
        return EXIT_OK
    if args.cmd == "wait":
        return wait_until(card=args.card, model=args.model, timeout=args.timeout,
                          quiet=args.quiet, now=args.now, root=root)
    if args.cmd == "refresh":
        out = refresh_once(card=args.card, model=args.model, now=args.now, root=root)
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"[额度刷新] 卡 {out['card']} · 模型 {out['model']} —— {out['why']}")
        return EXIT_OK
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
