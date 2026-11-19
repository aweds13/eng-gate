r"""限额策略的读法与窗口（卡 A338 · T-AG540；移植 magpie `internal/access/limit.go`）。

**防什么**：pool 今天**没有「钱包」这一层**。`gates/diag/wb-usage.jsonl` 只数 token、
没有账号维、没有金额（写方 `tools/wb_dispatch.py:1430-1454 append_usage_line()` 的
docstring 明写「只数 token，不做金额换算」），于是「这个号这个月还剩多少」只能靠人记。
magpie 用 `Limit` + `Reserve` 挡住的那类事故正是这个：**一把外部 key 在烧我的钱**。

★ **与 `--input-budget` 的语义差别（混了就是假限额）**
（`tools/wb_dispatch.py:219 DEFAULT_INPUT_BUDGET = 25_000_000`，判决在 `:3492-3498`）：

| | 本模块（magpie 的限额） | `--input-budget`（既有） |
|---|---|---|
| 保护什么 | **钱包**（外部 key 的 token / 钱） | 一次任务的时长/成本失控 |
| 什么时候判 | **派活之前**就拒 | 跑起来才 `break` |
| 有没有窗口 | 有（day/week/month/days/hours） | 没有 |
| 累计口径 | 跨派活累计（`pool-spend.jsonl`） | 每次派活 `usage_total` 重置 |
| 算不算失败 | 算出界（拒单，带 `Retry-After`） | 「止损不是失败」 |

同一个 token 数，一个是**预算授权**、一个是**熔断**。把 `input_budget` 改名当限额 = 假限额。

★ **本模块的边界**：只读、不写、不联网、**不看钟**（`now` 一律由调用方注入）。
  钱与 token 的账在 `pool.ledger_spend`，判据在 `pool.limits_check` —— 三份各管一件事，
  `wb_dispatch` / `pool_mcp` 将来只调 `check()`，不许各自再写一份 if。

★ **为什么 `TZ` 写成 `if TYPE_CHECKING: … else: from pool_accounts import TZ`**
  判据 2 要求「一律用 `tools/pool_accounts.TZ`，不许新造时区」，运行时那一半是**真 import**
  （不是抄值、不是新造）。类型那一半让 mypy 不必跟进 `tools/pool_accounts.py:34-42` 那段
  降级 import（`import pipe_root` / `from tools import pipe_root`）—— 顺着那条链 mypy 2.3.1
  会把 `tools/pool/__init__.py` 同时解析成 `pool` 与 `tools.pool`
  （`Source file found twice under different module names`），于是整份检查被「错误阻止」，
  与本文件的类型无关（实测：不 import 它的同形文件 Success）。
  两边指向**同一个对象**：`limits_policy.TZ is pool_accounts.TZ` 由
  `tests/test_pool_limits.py` 的 `pin_03` 钉住。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import tomllib

from pool import limits as _legacy_limits

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import tzinfo

    TZ: tzinfo
else:  # pragma: no cover —— 运行时走这一支（mypy 走上一支，见模块 docstring 末段）
    from pool_accounts import TZ

#: 一个账号最多几条限额（逐字对应 `limit.go:39 const MaxLimits = 5`）。
MAX_LIMITS = 5
#: `days` 周期允许的最大天数（`limit.go:95 MaxDays = 3650`）。
MAX_DAYS = 3650
#: `hours` 周期允许的最大小时数（`limit.go:99 MaxHours = 8760`）。
MAX_HOURS = 8760
#: 认得的周期名（`limit.go:92 Periods`）：前三个是日历窗口，后两个是「从 `since` 起算」。
PERIODS: tuple[str, ...] = ("day", "week", "month", "days", "hours")
#: `cost` 保留几位小数（`limit.go:145 math.Round(v.Cost*1e4)/1e4`）。
COST_ROUND = 4
#: `Limit` 认的键 —— 多一个少一个都抛（少一个可能悄悄变成默认值，那就是松开判据）。
_FIELDS: tuple[str, ...] = ("period", "days", "hours", "tokens", "cost", "cache_reads", "since")

#: 顶层这个键**不是**账号的限额段，是 **F34（卡 A341）** 的模型白名单段
#: （`[accounts."<id>"].models`，读方 `pool.limits.load_limits()` /
#: `wb_dispatch.caller_model_patterns()`）。`load_limits()` 按名字跳过它 —— **只**这一个键。
ACCOUNTS_KEY = "accounts"


class LimitError(ValueError):
    """限额数据说不清 —— **抛**，不许跳过坏条目继续用剩下的（跳过 = 悄悄松开判据）。"""


@dataclass(frozen=True, slots=True)
class Limit:
    """一条限额（逐字对应 `limit.go:21-36` 的 `Limit` 结构）。

    `tokens` / `cost` 都是 0 ⇒ 这条**不算限额**（`limited()` 为假）：对应 magpie
    `limitsOf` 只收 `Limited()` 的那些，零值条目不参与判。
    """

    period: str = "day"
    days: int = 0
    hours: int = 0
    tokens: int = 0
    cost: float = 0.0
    cache_reads: bool = False
    since: datetime | None = None

    def limited(self) -> bool:
        """逐字对应 `limit.go:113`：`Tokens > 0 || Cost > 0`。"""
        return self.tokens > 0 or self.cost > 0


# ================================================================ 归一与校验


def _integer(name: str, value: object, cap: int | None) -> int:
    """整数 + 非负 + 上限；**文案里的数字一律从常量拼**（不写字面量 3650/8760）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitError(f"{name} 必须是整数（收到 {value!r}）")
    if value < 0:
        raise LimitError(f"{name} 不能为负（收到 {value}）")
    if cap is not None and value > cap:
        raise LimitError(f"{name} 超出范围：允许 1~{cap}（收到 {value}）")
    return value


def _period(value: object) -> str:
    if not isinstance(value, str) or value not in PERIODS:
        raise LimitError(f"未知 period：{value!r}；只认 {'、'.join(PERIODS)}")
    return value


def _money(value: object) -> float:
    """`cost`：非负 + 按 `COST_ROUND` 舍入（`math.Round(v*1e4)/1e4` 的 Python 等价）。"""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LimitError(f"cost 必须是数字（收到 {value!r}）")
    cost = float(value)
    if cost < 0:
        raise LimitError(f"cost 不能为负（收到 {cost}）")
    unit = 10.0**COST_ROUND
    return round(cost * unit) / unit


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise LimitError(f"cache_reads 必须是布尔（收到 {value!r}）")
    return value


def _moment(value: object) -> datetime | None:
    """`since`：ISO-8601 字符串或 datetime；naive 按本仓时区（UTC+8）解释。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise LimitError(f"since 不是 ISO-8601 时间：{value!r}（{exc}）") from exc
    else:
        raise LimitError(f"since 必须是 ISO-8601 字符串或 datetime（收到 {type(value).__name__}）")
    return moment.astimezone(TZ) if moment.tzinfo is not None else moment.replace(tzinfo=TZ)


def _local(moment: datetime) -> datetime:
    """naive 时间按本仓时区（`pool_accounts.TZ`）解释，与留档口径一致。"""
    return moment.astimezone(TZ) if moment.tzinfo is not None else moment.replace(tzinfo=TZ)


def parse_limit(raw: Mapping[str, object]) -> Limit:
    """校验 + 归一一条限额；**坏数据一律抛 `LimitError`**（判据 8）。"""
    unknown = tuple(sorted(str(key) for key in raw if key not in _FIELDS))
    if unknown:
        raise LimitError(f"限额里有不认识的键：{'、'.join(unknown)}；只认 {'、'.join(_FIELDS)}")
    period = _period(raw.get("period", "day"))
    days = _integer("days", raw.get("days", 0), MAX_DAYS)
    hours = _integer("hours", raw.get("hours", 0), MAX_HOURS)
    if period == "days" and days < 1:
        raise LimitError(f"period=days 时 days 必须 1~{MAX_DAYS}（收到 {days}）")
    if period == "hours" and hours < 1:
        raise LimitError(f"period=hours 时 hours 必须 1~{MAX_HOURS}（收到 {hours}）")
    return Limit(
        period=period,
        days=days,
        hours=hours,
        tokens=_integer("tokens", raw.get("tokens", 0), None),
        cost=_money(raw.get("cost", 0.0)),
        cache_reads=_flag(raw.get("cache_reads", False)),
        since=_moment(raw.get("since")),
    )


# ================================================================ 窗口


def window(limit: Limit, now: datetime) -> tuple[datetime, datetime]:
    """`(start, reset)`：`start` 是本窗口起点，`reset` 是**下一个**窗口的起点。

    逐字对应 `limit.go:187-222`：

    - `day`   ⇒ 当天 00:00 起，次日 00:00 止；
    - `week`  ⇒ **周一** 00:00 起（`now.isoweekday()` 回退，周一 = 1），7 天后止；
    - `month` ⇒ **1 号** 00:00 起（`now.replace(day=1)`），下月 1 号止；
    - `days` / `hours` ⇒ 从 `since` 起算的等宽滚动窗口：`start = since + k*宽`，
      `reset = start + 宽`（`k` 取使 `start <= now` 的最大整数）。`since is None` ⇒ 抛 ——
      **不许默认「从现在起算」**，那等于每次重启重置窗口。
    """
    local = _local(now)
    if limit.period == "day":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if limit.period == "week":
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - timedelta(days=local.isoweekday() - 1)
        return start, start + timedelta(days=7)
    if limit.period == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        reset = (start + timedelta(days=32)).replace(day=1)
        return start, reset
    if limit.period in ("days", "hours"):
        if limit.since is None:
            raise LimitError(
                f"period={limit.period} 必须给 since；不给 since 就等于每次重启重置窗口"
            )
        base = _local(limit.since)
        width = (
            timedelta(days=limit.days)
            if limit.period == "days"
            else timedelta(hours=limit.hours)
        )
        if width <= timedelta(0):
            raise LimitError(f"period={limit.period} 的窗口宽度必须 > 0（收到 {width}）")
        if local < base:
            return base, base + width
        steps = int((local - base) / width)
        start = base + width * steps
        return start, start + width
    raise LimitError(f"未知 period：{limit.period!r}；只认 {'、'.join(PERIODS)}")


# ================================================================ 读策略


def _rows(account: str, section: object) -> tuple[Mapping[str, object], ...]:
    """一个账号的限额段：`[[账号.limit]]` 数组表，或 `[账号] limit = [...]`（两者解析结果同形）。

    ★ 顶层 `accounts` **不是**账号的限额段：它是 **F34（卡 A341）** 的模型白名单段
      （`[accounts."<id>"].models`），由 `load_limits()` 按名字跳过（见 `_check_accounts()`）。
      跳过的只有那一个键 —— 别的多出来的键照旧抛（判据 5 的 pin_19 靠这条守住）。
    """
    if isinstance(section, dict):
        extra = tuple(sorted(str(key) for key in section if key != "limit"))
        if extra:
            raise LimitError(
                f"账号 {account} 的段里有不认识的键：{'、'.join(extra)}（只认 limit；"
                "模型白名单不在账号的限额段里 —— 那是 F34/卡 A341 的 [accounts.\"<id>\"].models）"
            )
        if "limit" not in section:
            raise LimitError(f"账号 {account} 的段里没有 limit 数组")
        raw_rows: object = section["limit"]
    else:
        raw_rows = section
    if not isinstance(raw_rows, list):
        raise LimitError(f"账号 {account} 的 limit 必须是数组（收到 {type(raw_rows).__name__}）")
    rows: list[Mapping[str, object]] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            raise LimitError(f"账号 {account} 的某条限额不是表（收到 {type(item).__name__}）")
        rows.append(cast("Mapping[str, object]", item))
    return tuple(rows)


def _check_accounts(table: Mapping[str, object]) -> None:
    """顶层 `accounts` 是 **F34（卡 A341）** 的模型白名单段，不是账号的限额段。

    形状裁决 (b)（卡 A367 / T-AG652）：同一份 `limits.toml` 两份 reader —— 限额段留在顶层
    （`[[<id>.limit]]`），`[accounts."<id>"]` 只放 `models`（读方
    `wb_dispatch.caller_model_patterns()`）。本函数只做一件事：**逐段确认那一侧没有被拿来
    写限额**，然后让 `load_limits()` 按名字跳过它。

    为什么不是「不认识的键就当没看见」：放行那一侧等于让「限额段里混着别的东西」变正常态，
    下一份坏文件就再也判不出来了（判据 5 的 pin_19 正是靠「多一个键就抛」守住的）。

    - `accounts` 不是表（例如 `accounts = 1`、`[[accounts]]`）⇒ 抛：那一侧读不懂，
      而「读不懂」在本模块一律是**拒**，不是「没设限额」；
    - 某段不是表，或段里出现 `limit`（= 裁决 (a) 那个形状），或 `models` 与别的键混着
      ⇒ 抛，并在文案里点名它属于哪一侧 —— 让人知道该改哪儿，而不是猜；
    - 段里只有 `models`（或那一段是空表）⇒ 放行。
    """
    if ACCOUNTS_KEY not in table:
        return
    side = table[ACCOUNTS_KEY]
    if not isinstance(side, dict):
        raise LimitError(
            f"{ACCOUNTS_KEY} 必须是表（F34/卡 A341 的模型白名单段 [accounts.\"<id>\"].models），"
            f"收到 {type(side).__name__} —— 读不懂就抛，不许当成「没写」"
        )
    for account, section in side.items():
        if not isinstance(section, dict):
            raise LimitError(
                f"{ACCOUNTS_KEY}.{account} 必须是表（只放 models），收到 {type(section).__name__}"
            )
        if "limit" in section:
            raise LimitError(
                f"{ACCOUNTS_KEY}.{account} 里有 limit —— 那是裁决 (a) 那个形状，本仓选的是 (b)："
                "限额写在顶层 [[<id>.limit]]，[accounts.<id>] 只放 models（F34/卡 A341）"
            )
        extra = tuple(sorted(str(key) for key in section if key != "models"))
        if extra:
            raise LimitError(
                f"{ACCOUNTS_KEY}.{account} 的段里除了 models 还有：{'、'.join(extra)}；"
                "这一侧只认 models（限额请写顶层 [[<id>.limit]]）"
            )


def load_limits(path: Path | str | None = None) -> dict[str, tuple[Limit, ...]]:
    """读策略文件：`{账号: (Limit, ...)}`。

    - **文件不存在 ⇒ `{}`**（= 没设限额 = 今天的行为；**不是**「无限」，也**不抛**，判据 8）；
    - 坏 TOML / 某条越界 / 某账号超过 `MAX_LIMITS` 条 ⇒ **抛 `LimitError`**
      （**不许跳过坏条目继续用剩下的** —— 跳过 = 悄悄松开判据）；
    - `tokens=0 且 cost=0` 的条目**被忽略**（`limited()` 为假）；全篇都是零值的账号
      不进返回值（它等于没声明限额）。

    默认路径跟 `pool.limits.limits_path()` 走（`TF_POOL_LIMITS` 覆盖 > 号池目录下的
    `limits.toml`）—— 位址只由那一处决定，本模块不另发明一份。

    ★ **一份文件两个形状**（形状裁决 (b)，卡 A367 / T-AG652）：顶层每个键是一个账号的**限额段**；
    顶层 `accounts` 是 **F34（卡 A341）** 的模型白名单段（`[accounts."<id>"].models`），
    本函数**按名字跳过**它（`_check_accounts()` 先逐段确认那一侧没被拿来写限额；
    写进去了 / 混了别的键 / 那一侧读不懂 ⇒ 抛）。跳过的**只有** `accounts` 这一个键。
    """
    target = Path(path) if path is not None else _legacy_limits.limits_path()
    if not target.exists():
        return {}
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise LimitError(f"策略文件读不出来：{target}（{exc}）") from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LimitError(f"策略文件不是合法 TOML：{target}（{exc}）") from exc
    _check_accounts(raw)
    out: dict[str, tuple[Limit, ...]] = {}
    for account, section in raw.items():
        if account == ACCOUNTS_KEY:
            continue  # F34/卡 A341 的模型白名单段，不是限额（_check_accounts 已验过那一侧）
        rows = _rows(account, section)
        if len(rows) > MAX_LIMITS:
            raise LimitError(
                f"账号 {account} 声明了 {len(rows)} 条限额，"
                f"超过上限 {MAX_LIMITS}（magpie MaxLimits）"
            )
        kept = tuple(item for item in (parse_limit(row) for row in rows) if item.limited())
        if kept:
            out[account] = kept
    return out
