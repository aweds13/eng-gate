r"""整窗估算与「五因」—— magpie `window_holds` 移植进 pool（卡 A334 · T-AG536）。

## 为什么有它

pool 现在能答「这个号此刻是什么态」（`tools/pool_quota.py` 的四态判词），答不出
「**这个窗口**为什么估不出整窗用量」。magpie 那边把这件事拆成一个下限 + 五个因，本模块
照抄那份判据（唯一来源：`复盘/卡/卡A334-整窗估算要有五因.md`）：

| 卡规格 | magpie 出处 | 这里 |
|---|---|---|
| 判据 1 | `internal/provider/window_holds.go:40-50` | `HOLDS_FLOOR` + 五个因串 + 「不估」的 `"-"` |
| 判据 2 | 同文件 `:55-72` `Bounds()` | `bounds()`：`resets_at` > `reset_secs` > 不估；整月按月退 |
| 判据 3 | `internal/usage/window_holds.go:69-91` | `holds_bounds()`：顺序不许调换 |
| 判据 5 | 同文件 `:288-292` | `estimate()`：`scale = 100 / used` |
| 判据 6 | 同文件 `:201` / `:274` / `:276` | `estimate()` 的后三因（后写覆盖先写） |

★ 本模块是**纯判定**：零网络、零 sleep、**不读账本**。账本 / 探测结果 → `Window` 的转换
在调用方（`[account.quota].used_percent` 的**写入**归卡 A333）。所以这里没有任何 IO，
测试可以把 `read_at` / `now` 全钉成常数，一条真实钟表都不用碰。

## 用法

    from pool.holds import Window, estimate

    w = Window(model="glm-5.3-flash", span_s=30 * 24 * 3600, used=25.0,
               resets_at=datetime(2026, 11, 3, tzinfo=TZ))
    for h in estimate([w], routed_tokens=1000, routed_cost=0.5,
                      first_log_at=datetime(2026, 10, 5, tzinfo=TZ), read_at=now):
        print(h.tokens, h.why, h.why_text)

`why` **只放原串**（`low` / `clock` / `log` / `none` / `credits` / `-`）—— 它是判据标识，
测试与日志按原串匹配；人话在 `why_text`。不许把因串翻成中文再存盘。估出来了 `why` 是空串
`""`（**没有因**，不是「不估」）；`"-"` 才是「不估」。

## 与卡规格字面的一处出入（如实记）

判据 3 写 `holds_bounds(...) -> tuple[datetime, datetime, str]`；「不估」时**没有边界可给**，
本实现那两个位置回 `None`（注解 `datetime | None`）。编一个假时间（比如 `(at, at, why)`）
会让调用方拿它去算区间，比回 `None` 糟。
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 判据下限：窗口的「已用比例」低于这个百分数就**不估**（`internal/provider/window_holds.go:40`）。
#: 原文注释逐字：「the least share used a window's whole is reckoned from: below it a percent
#: the vendor rounds is too coarse to scale up」。★ 不许调小「好多算一点」。
HOLDS_FLOOR: float = 5.0

#: 五个因串 —— 原样存盘，不翻译（判据 1）。
HOLDS_LOW = "low"
HOLDS_NO_CLOCK = "clock"
HOLDS_BEFORE_LOG = "log"
HOLDS_NONE_ROUTED = "none"
HOLDS_CREDITS = "credits"

#: 「不估」：没有可估的东西（没有 `used`、区间不含 `read_at`、配额本身读不出来……）。
HOLDS_UNKNOWN = "-"

#: 「估出来了，没有因」—— 与 `"-"` **不是**一回事：`""` 是成功，`"-"` 是不估。
HOLDS_OK = ""

#: 五个因，一处列出（tests 与日志按这批原串匹配）。
HOLDS_CAUSES: tuple[str, ...] = (
    HOLDS_LOW,
    HOLDS_NO_CLOCK,
    HOLDS_BEFORE_LOG,
    HOLDS_NONE_ROUTED,
    HOLDS_CREDITS,
)

#: 判据 2 的「整月窗」口径：`span_s` 恰好 30 天 ⇒ `start` 按**日历**减一月（不是减 30×86400 秒）。
MONTH_SPAN_S: int = 30 * 24 * 3600

#: 每一因的人话（`Holds.why_text` 用）。键必须是上面的原串 —— 少一个键就 KeyError，不兜底。
_WHY_TEXT: dict[str, str] = {
    HOLDS_OK: "估出来了：按已用比例把这段路由用量放大到整窗",
    HOLDS_UNKNOWN: "不估：这一窗没有可估的东西（已用比例读不出来 / 区间不含此刻 / "
    "配额本身读不出来）—— 不猜，也不当 0",
    HOLDS_LOW: f"不估：已用比例低于 {HOLDS_FLOOR}% —— 厂商给的百分比在这个量级上四舍五入太粗，"
    "按它放大会把误差一起放大",
    HOLDS_NO_CLOCK: "不估：没有窗口边界（resets_at 与 reset_secs 都没有）—— 不知道起止就不估整窗",
    HOLDS_BEFORE_LOG: "不估：日志起点晚于窗口起点 —— 这一窗的记录不全，按它放大等于少算",
    HOLDS_NONE_ROUTED: "不估：这段按模型数出来的 token 是 0 —— 没有可放大的分子",
    HOLDS_CREDITS: "不估：这段有按 credits 另付的调用 —— token 比例换算不成立",
}


@dataclass(frozen=True)
class Window:
    """一个「配额窗口」的描述（**由调用方从账本 / 探测结果转过来** —— 本模块不读账本）。

    字段与 magpie 的 `QuotaWindow` 对齐，但只留本卡用得到的：

    * `model`：窗口所属模型（调用方按它取数）。
    * `span_s`：窗口跨度（秒）；等于 `MONTH_SPAN_S` 时 `start` 走日历减一月。
    * `used`：**已用比例（百分数 0~100）**；`None` = 没测到 ⇒ 判据 4 一律 `"-"`，绝不当 0。
    * `resets_at`：窗口终点（绝对时刻），优先于 `reset_secs`。
    * `reset_secs`：距离重置还有多少秒（`> 0` 才算；`end = read_at + reset_secs`）。
    * `aside`：溢出池的窗口。`aside and not pool` ⇒ 归不到窗口 ⇒ 不估。
    * `unlimited`：无限额度 ⇒ 没有整窗可言 ⇒ 不估。
    * `pool`：窗口声明的池名；`""` = 没声明。
    * `family`：家庭号 / 共享号标记（非空即算）⇒ 不估。
    """

    model: str = ""
    span_s: int = 0
    used: float | None = None
    resets_at: datetime | None = None
    reset_secs: float = 0.0
    aside: bool = False
    unlimited: bool = False
    pool: str = ""
    family: str = ""


@dataclass(frozen=True)
class Holds:
    """一个窗口的「整窗估算 + 为什么估不出来」。

    * `tokens` / `cost`：按已用比例放大出来的整窗用量；**不估时是 0**（不是猜出来的数）。
    * `since`：这条估算覆盖的起点（= 窗口的 `start`）；不估 ⇒ `None`。
    * `why`：五个因串之一 / `"-"`（不估）/ `""`（估出来了）。判据标识。
    * `why_text`：同一件事的人话（可翻译，不许反过来当判据）。
    """

    tokens: int = 0
    cost: float = 0.0
    since: datetime | None = None
    why: str = HOLDS_UNKNOWN
    why_text: str = ""


def why_text(why: str) -> str:
    """因串 → 人话。只认那一小撮原串，别的直接 KeyError（不编话兜底）。"""
    return _WHY_TEXT[why]


def _minus_one_month(when: datetime) -> datetime:
    """日历减一月（判据 2 的「整月窗」）：跨年退到 12 月，月末越界（3/31 → 2 月）夹到当月末。"""
    year = when.year - 1 if when.month == 1 else when.year
    month = 12 if when.month == 1 else when.month - 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def bounds(w: Window, read_at: datetime) -> tuple[datetime, datetime] | None:
    """窗口起止（判据 2，照 magpie `Bounds()` `internal/provider/window_holds.go:55-72`）。

    三档，顺序固定：`resets_at` 优先 ⇒ 否则 `reset_secs > 0`（`end = read_at + reset_secs`）
    ⇒ 都没有就 `None`（**不估**，由调用方判 `clock`）。
    `start`：`span_s == 30 天` 走**日历**减一月，否则 `end - span_s`。
    """
    if w.resets_at is not None:
        end = w.resets_at
    elif w.reset_secs > 0:
        end = read_at + timedelta(seconds=w.reset_secs)
    else:
        return None
    if w.span_s == MONTH_SPAN_S:
        return _minus_one_month(end), end
    return end - timedelta(seconds=w.span_s), end


def holds_bounds(
    w: Window, at: datetime, *, pool: str = ""
) -> tuple[datetime | None, datetime | None, str]:
    """判定顺序（判据 3，照 `internal/usage/window_holds.go:69-91`）—— **顺序不许调换**。

    调换的后果在卡规格里：`used=3.0` 且没有重置时间的窗口会从 `low` 变成 `clock`，
    两种「不估」混成一因。

    `pool` 是可选的「被问的池」：magpie 那句 `w.Pool != "" && w.Pool != q.Pool` 需要一个
    外部入参，这里用关键字补上；不给（默认 `""`）就只做窗口自身的判，**不算错**。

    返回 `(start, end, why)`：估得出来 ⇒ `why == ""` 且两个时间非 `None`；
    不估 ⇒ 两个时间 `None`，`why` 是五个因之一或 `"-"`。
    """
    # ① :70-76 —— 无限额度 / 溢出池无名 / 家庭号 / 池不符 / 比例读不出来 ⇒ 不估。
    #    ★ magpie 原句 `q.Error != "" || q.From != "" || q.User == "" || q.Balance != ""`
    #    那四个字段属于**探测响应**，`Window` 里没有对应物 ⇒ 那半截在调用方（账本 → Window）
    #    挡；到这里已经是「读出来了的窗口」，这里挡窗口自身可判的五条。
    if w.unlimited:
        return None, None, HOLDS_UNKNOWN
    if w.aside and not w.pool:
        return None, None, HOLDS_UNKNOWN
    if w.family:
        return None, None, HOLDS_UNKNOWN
    if w.pool and pool and w.pool != pool:
        return None, None, HOLDS_UNKNOWN
    used = w.used
    # ② 判据 4：没有这个数 ⇒ "-"，**绝不当代 0**（NaN / inf 同样不算「有值」）。
    if used is None or not math.isfinite(used):
        return None, None, HOLDS_UNKNOWN
    # ③ :80-81 —— 有值但太小 ⇒ low（不是「没这个数」）。
    if used < HOLDS_FLOOR:
        return None, None, HOLDS_LOW
    # ④ :85 —— 边界拿不到 ⇒ clock。
    got = bounds(w, at)
    if got is None:
        return None, None, HOLDS_NO_CLOCK
    # ⑤ :88 —— 区间不含此刻 ⇒ 不估。
    start, end = got
    if not end > at or not start < at:
        return None, None, HOLDS_UNKNOWN
    return start, end, HOLDS_OK


def estimate(
    windows: Iterable[Window],
    *,
    routed_tokens: int,
    routed_cost: float,
    first_log_at: datetime | None,
    read_at: datetime,
    paid_otherwise: bool = False,
) -> list[Holds]:
    """逐窗算整窗用量（判据 5 / 6，照 `internal/usage/window_holds.go:288-292`）。

    算式逐字照抄：`scale = 100 / used`、`tokens = round(routed_tokens * scale)`、
    `cost = routed_cost * scale`。

    后三因按 magpie 的**赋值顺序**写（后写覆盖先写，不自创优先级）：
    ① `first_log_at is None or first_log_at > start` ⇒ `log`（`:201`）
    ② `routed_tokens <= 0` ⇒ `none`（`:274`）
    ③ `paid_otherwise` ⇒ `credits`（`:276`）

    任一因命中（`why` 非空）时 `tokens` / `cost` **都归 0**：这一窗的数不可信就不报数，
    不许拿一个放大过的假数冒充实测。

    ★ 与 Go 的一处已知差异：`round()` 在 `.5` 上是银行家舍入，`math.Round` 是半远离零。
    规格写的是 `round`，就照 `round` 写（`used` 是整数百分比时几乎不出现 `.5`）—— 备忘，不是判据。
    """
    out: list[Holds] = []
    for w in windows:
        start, _end, why = holds_bounds(w, read_at)
        if start is None or why != HOLDS_OK:
            # 没边界 / 第一段就判死 ⇒ 一个数都不算。
            cause = why or HOLDS_UNKNOWN
            out.append(Holds(why=cause, why_text=why_text(cause)))
            continue
        used = w.used
        if used is None:  # holds_bounds 已挡过；这里只为类型收窄，不是判据
            out.append(Holds(why=HOLDS_UNKNOWN, why_text=why_text(HOLDS_UNKNOWN)))
            continue
        scale = 100 / used
        tokens = round(routed_tokens * scale)
        cost = routed_cost * scale
        cause = HOLDS_OK
        if first_log_at is None or first_log_at > start:
            cause = HOLDS_BEFORE_LOG
        if routed_tokens <= 0:
            cause = HOLDS_NONE_ROUTED
        if paid_otherwise:
            cause = HOLDS_CREDITS
        if cause != HOLDS_OK:
            tokens, cost = 0, 0.0
        out.append(Holds(tokens=tokens, cost=cost, since=start, why=cause,
                         why_text=why_text(cause)))
    return out


__all__ = [
    "HOLDS_BEFORE_LOG",
    "HOLDS_CAUSES",
    "HOLDS_CREDITS",
    "HOLDS_FLOOR",
    "HOLDS_LOW",
    "HOLDS_NONE_ROUTED",
    "HOLDS_NO_CLOCK",
    "HOLDS_OK",
    "HOLDS_UNKNOWN",
    "MONTH_SPAN_S",
    "Holds",
    "Window",
    "bounds",
    "estimate",
    "holds_bounds",
    "why_text",
]
