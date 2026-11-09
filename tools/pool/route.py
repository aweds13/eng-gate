r"""Smart 路由（从 magpie 移植，卡 A329 · 台账号 T-AG531）—— 只标准库 + 只读，无副作用。

这个模块干的事只有一件：**给「哪个号先上」排个序**。原件是 magpie 的 `Smart` 策略和
`Apply` 兜底，本模块每个判据都能指回一行 Go 代码（改判据前先读那张表）：

| 本模块 | magpie 原件 |
|---|---|
| `LOW_SHARE` / `USED_SHARE` / `tier()` | `internal/routes/strategies.go:14-29`：
  `const ( LowShare = 90; UsedShare = provider.SpentShare )`；`tier` 判据逐字是
  `switch { case share >= UsedShare: return 2; case share >= LowShare: return 1 }; return 0`；
  `UsedShare` 的真值在 `internal/provider/codex_switch.go:109`：`const SpentShare = 98` |
| `Seat` | `internal/routes/routes.go:21+` 的 `type Seat struct`
  （`Key/Known/Used/Soon/Lapse/Resting/Left/LeftIn`）。★ 原件的 `Learns`、`Account`、
  `Credits` **没有**移植：本卡规格的字段清单里没有它们，缺数据就不要装作有判据 |
| `smart_order()` 的三档分桶 + 逐级稳定排序 | `internal/routes/strategies.go:119-169`
  `Smart.Strategy.Order`（`fine/low/spent` 三桶、`sort.SliceStable` 逐级比较、
  `return append(append(fine, low...), spent...)`） |
| `apply_order()` 的 fail-open | `internal/routes/routes.go:143` `func Apply(...)`：
  非排列（长度不符 / 越界 / 重复）一律回 `identity`，**不抛** |
| `reset_for()` / `model_until()` / `seconds_left()` | 本仓自己的额度台账
  （`tools/pool_quota.py`，卡 201/卡 A329 的接线喂料）；magpie 那边没有对应物 ——
  它从网关手里拿现成的 `Soon`/`Used`，我们的"额度什么时候回来"只存在
  `gates/diag/quota-state.json` 里 |

★ 为什么 `reset_for` 放在**这里**、而不是 `tools/pool_quota.py`：另一张卡（**A328**）正在改
  `tools/pool_quota.py`，两卡的域不许相交。本模块对它只**读**（`_state_path` 定位、
  `parse_reset` 解析），一个字都不改它。
★ 解析重置时间**必须**走 `pool_quota.parse_reset`（`tools/pool_quota.py:64`，全仓唯一真源）——
  在 route.py 里再写一份正则就是第二个真源，两边迟早对不上（这是设计稿点名禁止的那条）。

★ 边界（如实写，别猜）：
- `tier()` 的 `share` 不在 `[0, 100]` **抛 `RouteError`，不 clamp** —— clamp 会把"形状变了"
  洗成"差一点就满"，正是额度判断最不该有的那种沉默（`NaN` 同理，它连"差一点"都不是）。
- `soon` / `lapse` 比较**先截到小时**（原件 `Truncate(time.Hour)`）；截完相等就落到下一级键，
  **不为了比出大小而重排**（保住基准顺序 = 保住 prompt cache）。
- 空 `soon` / 空 `lapse` / `left is None` 都是"不知道"，一律**排在知道的人之后**
  （原件 `case x.IsZero()||y.IsZero(): return y.IsZero()` 和
  `told none: after every one that did`）。
- `used is None` 或 `known=False` 同样是「不知道」：`tier(None)` 回 `UNKNOWN_TIER`
  （**不是 0**），四个分桶策略（`smart_order` / `least_used` / `by_pace` / `fastest`）
  一律把这种座排在额度知道的人之后；`known=False` 时 `used` 填了多少都不可信。
- `soon` 逐窗口比时，**前缀相同则窗口多的在前**（原件 `y.IsZero()` 那条：对方先没窗口 ⇒ 我方先）。
- `resting` 的号沉到最后：对应原件 `Seat.Resting` 的注释 "it rests after a failure now"。
  原件 `Smart` 里并没拿 `Resting` 排位，本卡规格要求沉底 —— 只在本模块里排位，**不做持久化**。
- 没有额度记录 ≠ 立刻可用：`reset_for()` 回 `(None, "")`，调用方必须当"不知道"
  （`pool_quota.status()` 的四态之一就叫 `未记录`，`why` 原文是"没有这条记录 ⇒ 不猜"）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pool_quota

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

__all__ = [
    "ALIKE",
    "BUILTIN",
    "FASTEST",
    "FREE_FIRST",
    "FRESH_PACE",
    "LEAST_USED",
    "LOW_SHARE",
    "ORDERED",
    "PACE",
    "PACE_BAND",
    "PROBE_EVERY",
    "REF_TOKENS",
    "MANUAL",
    "ROTATE",
    "ROUTING_ALIASES",
    "RouteError",
    "SMART",
    "Seat",
    "UNKNOWN_TIER",
    "USED_SHARE",
    "WEIGHTED",
    "apply_order",
    "apply_strategy",
    "by_pace",
    "estimate",
    "fastest",
    "first",
    "free_first",
    "identity",
    "least_used",
    "model_until",
    "ordered",
    "parse_routing",
    "reset_for",
    "rotate",
    "round_pick",
    "seconds_left",
    "smart_order",
    "tier",
    "usage_tier",
    "weighted",
]

# 与 magpie 同名的两个阈值（`strategies.go:15-17`）。判据逐字照抄，别改数：
#   share >= 98（`provider.SpentShare`）⇒ 用尽了；share >= 90 ⇒ 快用完了。
LOW_SHARE = 90.0
USED_SHARE = 98.0

# `used` 的第四档：**不知道**（`used is None` 或 `known=False`）。★ 它不是 `0.0`
# 的别名 —— 0 是「真的用了 0%」，这一档是「没量过」，排位必须不同（卡 E95 的理由）。
UNKNOWN_TIER = 3

# 比任何真实时钟都远的 aware 时间：`soon` 逐窗口比时给"窗口更少"的那方补位用。
# 补成"永远更晚"就等于原件的 `x.IsZero() ⇒ 对方先`（前缀相同 ⇒ 窗口多的在前）。
_FAR = datetime(9999, 12, 31, 23, 0, tzinfo=timezone.utc)


class RouteError(Exception):
    """排序判据的输入不成立 —— 形状变了就该炸，不许猜、不许 clamp。"""


def tier(share: float | None) -> int:
    """已用份额 → 档位（0 = 还有余量，1 = 快用完，2 = 用尽了，3 = **不知道**）。

    判据**逐字**是 magpie `internal/routes/strategies.go:15-29` 的
    `switch { case share >= UsedShare: return 2; case share >= LowShare: return 1 }; return 0`。

    ★ 第四档 `UNKNOWN_TIER` 是**本仓加的**：`None` = 「没量过」，它**不是** `0.0`
      （那是「真的用了 0%」）—— 回 `0` 等于把「不知道」洗成「一点没用」，正是本卡要修的那个错。
      `known=False` 的座由上层 `usage_tier()` 先拦成这一档：`tier()` 只看数，不问可信度。

    ★ `share` 不在 `[0, 100]` ⇒ `RouteError`，**绝不 clamp**：`101` 是「这个数从哪来的」，
      不是「差一点就满」；把它压成 `100` 等于把上游的形状错误洗成一次成功派活。
    """
    if share is None:
        return UNKNOWN_TIER
    if isinstance(share, bool) or not isinstance(share, (int, float)):
        raise RouteError(f"used 必须是数字（0–100），拿到 {type(share).__name__}")
    value = float(share)
    if value != value:  # NaN：连"差一点"都不是，不许当 0
        raise RouteError("used 是 NaN —— 不知道就把 known 置 False，别拿 NaN 冒充 0")
    if value < 0.0 or value > 100.0:
        raise RouteError(f"used 必须在 [0, 100]（百分比），拿到 {share!r} —— 不 clamp")
    if value >= USED_SHARE:
        return 2
    if value >= LOW_SHARE:
        return 1
    return 0


@dataclass(frozen=True)
class Seat:
    """一个号的"当下状态"（对应 magpie `internal/routes/routes.go:21+` 的 `Seat`）。

    字段口径（照原件注释，不自己发明）：
    - `key`：号的标识（打印/定位用，不参与排序）。
    - `known`：额度**知不知道**（`// Known: its allowance is known`）。`False` ⇒ 当不知道排。
    - `used`：已用份额 `0–100`；`None` = **没量过**（不是 0）
      （`// Used is the share of its allowance used that counts the model`）。
      `known=False` 时它即便有数也**不可信** ⇒ 按「不知道」排（见 `usage_tier()`）。
    - `soon`：窗口什么时候续（`// Soon is when its windows renew, the biggest first`），可空。
    - `lapse`：`Soon` 打平时的第二判据
      （`// Lapse ... zero when not told. Smart goes by it when Soon ties`）。
    - `resting`：刚失败、正在休息（`// Resting: it rests after a failure now`）。
    - `left` / `left_in`：余额，`None` / `""` = 没人告诉过（`// empty when no balance was told`）。
    - `account` / `learns` / `pace` / `weight` / `tokens` / `free` / `credits` / `ttft` / `tps`：
      F17 追加的九个字段（`Seat` 侧与原件 `routes.go:21+` 对齐），全部带默认值。
      口径见下面每个字段自己的行内注释 —— 特别是 `pace=None` 与 `ttft/tps=0.0`
      都是「没告诉 / 没量过」。
    """

    key: str
    known: bool = True
    used: float | None = None
    soon: tuple[datetime, ...] = ()
    lapse: datetime | None = None
    resting: bool = False
    left: float | None = None
    left_in: str = ""

    # ---- F17 追加的九个字段（全部带默认值，既有构造点一个都不用改）----
    # `account`：这个座位是账号还是 key（原件 `routes.go:21+` 的 `Account`）。
    account: bool = False
    # `learns`：它答完会自己报余额（原件 `Learns`）；这种号不许沉在「不知道」后面，
    # 否则永远轮不到它、永远学不到 —— `by_pace()` 里它也不参与分带。
    learns: bool = False
    # `pace`：这个号每小时还剩多少份额度（原件 `Pace`，`float64`）。
    # ★ pool 侧用 `None` 表示「没人告诉过」，**不是 0**：`0` 是「一点都不剩」，两者排位不同。
    pace: float | None = None
    # `weight`：加权轮转里的权重；原件取 `max(s.Weight, 1)`（`strategies.go:303`）。
    weight: int = 1
    # `tokens`：最近发给它的量（原件 `Tokens`）。★ 原件注释说「按 1 小时半衰期衰减」，
    # 但 magpie 源码里 grep 不到衰减实现 ⇒ pool 侧只收「调用方给好的已衰减值」，本模块不衰减。
    tokens: float = 0.0
    # `free`：这个号跑这个模型不花钱（原件 `Free`）。★ pool 侧没有自动来源
    # （`model_registry.py` 的 `ModelEntry` 没有 `free` 列），只能由调用方传。
    free: bool = False
    # `credits`：额度用尽后还能靠赠金继续（原件 `Credits`）。★ 同样只能由调用方传。
    credits: bool = False
    # `ttft` / `tps`：首字节毫秒数 / 之后每秒输出多少 token（原件 `TTFT`、`TPS`）。
    # ★ `0.0` 在这两个字段上是「**没量过**」，不是「速度是 0」—— 见 `fastest()` 的四堆。
    ttft: float = 0.0
    tps: float = 0.0


def usage_tier(seat: Seat) -> int:
    """这个座**额度**的档位；`UNKNOWN_TIER` = 不知道（`used is None` 或 `known=False`）。

    ★ `known=False` 保护 `used`：`Seat(known=False, used=99.0)` 不许因为 99 大就排到
      「已知 95%」的号后面 —— 那个 99 本身就不可信（`Seat.known` 的字段注释承诺的是
      「`False` ⇒ 当不知道排」，而改动前它只影响 `soon` 那一级）。
    ★ 分桶函数**一律**走这里，别自己写 `tier(seat.used)` —— 漏一支就是「`known=False` 的号
      被 `used` 的大数插队」，这是本卡最容易做错的地方。
    """
    if not seat.known or seat.used is None:
        return UNKNOWN_TIER
    return tier(seat.used)


def _share_key(seat: Seat) -> tuple[int, int, float]:
    """`used` 这一级的排序键：额度知道的在前（按 `used` 升），不知道的**一律**在后。

    形状 `(不知道, 连数都没有, used)`：定长才能跟别的键拼进同一个元组比大小；
    第二项让 `used is None` 沉在「档位不知道、但数还给了」的同伙之后。
    """
    used = 0.0 if seat.used is None else float(seat.used)
    if usage_tier(seat) != UNKNOWN_TIER:
        return (0, 0, used)
    return (1, 1 if seat.used is None else 0, used)


def _trunc(dt: datetime) -> datetime:
    """截到小时（原件 `time.Time.Truncate(time.Hour)`）。时区跟着原值走，不改成 UTC。"""
    return dt.replace(minute=0, second=0, microsecond=0)


def _soon_key(seat: Seat, width: int) -> tuple[object, ...]:
    """`soon` 这一级的排序键：有窗口的在前，逐窗口（截到小时）比，窗口少的补 `_FAR`。

    `width` = 本次排序里最长的窗口数（补位是为了让"前缀相同 ⇒ 窗口多的在前"成立，
    这正是原件 `case x.IsZero()||y.IsZero(): return y.IsZero()` 的效果）。
    """
    if not seat.known or not seat.soon:
        return (1,)
    windows = tuple(_trunc(dt) for dt in seat.soon)
    return (0, *windows, *((_FAR,) * (width - len(windows))))


def _lapse_key(seat: Seat) -> tuple[object, ...]:
    """`lapse` 这一级：截到小时比，没告诉过的排在有值的之后（原件 `y.IsZero()` 那条）。"""
    if seat.lapse is None:
        return (1,)
    return (0, _trunc(seat.lapse))


def _left_key(seat: Seat) -> tuple[object, ...]:
    """`left` 这一级：余额大的在前；`None` 是"没人告诉过" ⇒ 排在有值的之后。"""
    if seat.left is None:
        return (1, 0.0)
    return (0, -float(seat.left))


# ============================================================================
# F17：七种内置路由策略（设计原件 `_ext/_port_design_wave4.md` §F17）
#
# 与 magpie 逐条对齐：`internal/routes/{strategies,round,fastest}.go`。每个策略都是
# 「`Seat` 序列 → 下标排列」的纯函数；状态（rotate 的轮次、weighted 的轮转欠账、fastest 的
# 探测计数）**一律由调用方按 pool 传进来**，本模块自己不落盘 —— 原件是进程内
# `sync.Mutex` + map，pool 的派活一次一个进程，落盘会把「每进程重置」洗成「跨卡继承欠账」。
# ============================================================================

# 常量逐字照抄原件，一个都不许「顺手调」：
#   FRESH_PACE ← `provider/routing.go:499`（`100 / (7 * 24.0)`）
#   REF_TOKENS ← `fastest.go:39`、PROBE_EVERY ← `fastest.go:43`、ALIKE ← `fastest.go:47`
#   PACE_BAND  ← `strategies.go:259` 的 `p < 0.9*top`
FRESH_PACE: float = 100.0 / (7 * 24.0)
REF_TOKENS: int = 200
PROBE_EVERY: int = 5
ALIKE: float = 1.1
PACE_BAND: float = 0.9

# 七个路由名逐字照抄 `provider/routing.go:24-38`。名字是**外部契约**（配置里写的就是这些字），
# 不是内部别名 ⇒ 一个字母都不许改。
ORDERED = "order"
ROTATE = "rotate"
LEAST_USED = "usage"
PACE = "pace"
WEIGHTED = "weight"
FREE_FIRST = "free"
FASTEST = "fast"

BUILTIN: tuple[str, ...] = (ORDERED, ROTATE, LEAST_USED, PACE, WEIGHTED, FREE_FIRST, FASTEST)

#: magpie 的**默认**策略：值就是空串（`routes.go` 里 `if routing == "" { return Smart, true }`）。
#: ★ 它**不在** `BUILTIN` 里 —— 原件的七常量开头就写着「besides the default, smart, in order」
#: （`provider/routing.go:22-40`）。塞进 `BUILTIN` 等于把七项外部契约改成八项（卡 E103）。
SMART = "smart"

#: 手工挑号（原件 `Manual`）：不排位 ⇒ 保持列出顺序。原件也不给它沉底（见 `pool.sink.sinks`）。
MANUAL = "manual"

#: 名称表：规范名 → 别名元组。逐字照 `internal/cli/groups_cli.go:126-146` 的
#: `routingNames`（value, name, also）：规范名自己也算一个写法，空串是 `smart` 的**值**。
#: ★ 这是**外部契约**（运维在命令行敲的就是这些字），少一个别名就是一条静默降级。
ROUTING_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SMART, ("", "default", "auto")),
    (ORDERED, ("ordered", "in-order")),
    (ROTATE, ("in-turn", "round-robin")),
    (LEAST_USED, ("least-used",)),
    (PACE, ("weekly-pace",)),
    (WEIGHTED, ("weighted", "by-weight", "weighted-round-robin", "wrr")),
    (FREE_FIRST, ("free-first", "freest", "no-cost")),
    (FASTEST, ("fastest", "speed", "speed-first")),
    (MANUAL, ("pick", "picked", "pinned")),
)

#: 原件的插件路由形态（`<plugin>/<name>`）。本仓**没有**插件路由 ⇒ 见 `parse_routing`。
_PLUGIN_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9][A-Za-z0-9._-]*")


def parse_routing(name: str) -> str:
    """写法 → 规范名。对应原件 `parseRouting`（`internal/cli/groups_cli.go:155-170`）。

    顺序逐字照原件：`TrimSpace` → 插件名判定 → `ToLower` → 逐条比 `value / name / also`。
    空串 ⇒ `SMART`（原件：查表命中默认策略）。

    ★ **认不出就抛 `RouteError` 并点名**，绝不静默回 `order`：原件在这里是
      `routing %q is not one magpie has` —— 一个不认识的路由名让网关悄悄按列出顺序派活，
      正是卡 E103 要修的那种沉默。**谁负责炸**：启动面（`pool.gateway.build_server` / `main`）；
      请求路径上的 `apply_strategy` 仍然 fail-open（策略坏掉不该把整轮派活停摆）。

    ★ `<plugin>/<name>`：原件交给插件注册表，本仓没有插件路由 ⇒ 抛 `RouteError` 并**明说**
      「原件支持、本仓没有」，不许把它混进「未知名字」那一句里。
    """
    raw = "" if name is None else str(name)
    stripped = raw.strip()
    if _PLUGIN_RE.fullmatch(stripped):
        raise RouteError(
            f"路由名 {raw!r} 是插件路由（<plugin>/<name>）：原件支持，本仓**没有** ⇒ "
            f"用内置的 {', '.join([SMART, *BUILTIN, MANUAL])}")
    low = stripped.lower()
    for canonical, also in ROUTING_ALIASES:
        if low == canonical or low in also:
            return canonical
    raise RouteError(
        f"路由名 {raw!r} 不认识：magpie 没有这个名字。可用的是 "
        f"{', '.join([SMART, *BUILTIN, MANUAL])}（空串 = {SMART}，即原件默认值），"
        f"别名见 route.ROUTING_ALIASES；写错名字不许静默退成 {ORDERED}")


def identity(n: int) -> list[int]:
    """`0..n-1` 的恒等排列（原件 `identity`，`strategies.go:87-93`）。`n <= 0` ⇒ `[]`。"""
    return list(range(n)) if n > 0 else []


def first(best: int, n: int) -> list[int]:
    """把 `best` 提到第 0 位，其余**保列出序**（原件 `First`，`strategies.go:310-316`）。

    ★ 不是旋转：`[0,1,2,3]` 提 `2` ⇒ `[2,0,1,3]`，不是 `[2,3,0,1]`。
    `best <= 0` ⇒ 原样（原件 `if best <= 0 { return idx }`；`-1` = 一个都没挑到）。
    """
    idx = identity(n)
    if best <= 0:
        return idx
    return [best, *idx[:best], *idx[best + 1:]]


def round_pick(pool: str, keys: Sequence[str], weights: Sequence[int],
               rests: Sequence[bool], *, state: dict[str, dict[str, int]]) -> int:
    """平滑加权轮转：这次该挑谁（原件 `Round`，`round.go:27-62`）。

    机制就两步（原件的全部机制）：
    ① 每个参与者 `cur[key] += weight`，`total` = **参与者**的权重和（`rests[i]` 的不计入）；
    ② 取 `cur` 最大者，然后 `cur[赢家] -= total` —— 减法那一步是「平滑」的全部来源，
      少了它就退化成单调增长（`3,1` 会变成 `0,0,0,0`，而不是 `a,a,b,a`）。
    ③ 每次先把**不在 `keys` 里的旧 `cur` 删掉**（原件 `delete(r.cur, k)`）：换了一批号之后，
      同位置的另一个 key 不许继承上一个 key 的欠账。
    并列取**先列出的**那一个（`>` 不是 `>=`）。全部 `rests` ⇒ `-1`（没有可挑的）。
    ★ `state` 是 `pool → {key: cur}`，由调用方持有；本函数不落盘。
    """
    cur = state.setdefault(pool, {})
    on = set(keys)
    for gone in [key for key in cur if key not in on]:
        del cur[gone]
    best = -1
    total = 0
    for i, key in enumerate(keys):
        if rests[i]:
            continue
        cur[key] = cur.get(key, 0) + weights[i]
        total += weights[i]
        if best < 0 or cur[key] > cur[keys[best]]:
            best = i
    if best < 0:
        return -1
    cur[keys[best]] -= total
    return best


def estimate(ttft: float, tps: float, mid: float) -> float:
    """按 `REF_TOKENS` 的回复估还要多久（毫秒）（原件 `Estimate`，`fastest.go:119-128`）。

    三分支逐字：`tps <= 0` ⇒ 用 `mid`（它没报速度 ⇒ 按同组的中位速度算，既不罚也不奖）；
    `mid` 也是 0 ⇒ **只算首字节**；否则 `ttft + REF_TOKENS*1000/tps`。
    """
    if tps <= 0:
        tps = mid
    if tps <= 0:
        return ttft
    return ttft + REF_TOKENS * 1000 / tps


def _by_left(seats: Sequence[Seat]) -> list[int] | None:
    """余额位次（原件 `byLeft`，`strategies.go:42-80`）：返回每个下标的位次，小的在前。

    原件要说清的两件事：
    ① **只在 `left_in` 相同的座位之间比 `left`**：分和别的厂的分不可比，所以每种「单位」
      只在自己那些位次上排，两种单位之间保 `before` 给的相对次序；
    ② `left_in` 没告诉过的座位位次 = `len(seats)`（排在所有告诉过的之后）。
    没有人告诉过余额 ⇒ `None`（原件返回 `nil`，调用方整段跳过）。

    ★ 组内比余额**复用 `_left_key`**：三种比余额的策略（`least_used` / `by_pace` / 既有
      `smart_order`）共用这一份判据，不许各写一份「谁的余额大」。
    ★ 原件第二个参数 `before` 在两个新策略里都是 `fewerTokens`（`tokens` 小的在前），
      所以这里就按 `tokens` 定「两种单位之间」的相对次序；`Smart` 传 `nil` 的那一份
      已经落在 `smart_order()` 里，不走这里。
    """
    told = [i for i, seat in enumerate(seats) if seat.left_in]
    if not told:
        return None
    told.sort(key=lambda i: seats[i].tokens)
    slot: dict[str, list[int]] = {}
    for pos, i in enumerate(told):
        slot.setdefault(seats[i].left_in, []).append(pos)
    place = [len(seats)] * len(seats)
    for positions in slot.values():
        ids = sorted((told[p] for p in positions), key=lambda i: _left_key(seats[i]))
        for k, i in enumerate(ids):
            place[i] = positions[k]
    return place


def ordered(seats: Sequence[Seat]) -> list[int]:
    """按列出顺序试，第一个不行再第二个（原件 `Ordered`，`strategies.go:182`）。

    原件带 `Exact: true`（不重排、只照用），语义就是恒等排列，**任何** `Seat` 取值下都成立。
    """
    return identity(len(seats))


def rotate(seats: Sequence[Seat], *, pool: str, turns: dict[str, int] | None = None) -> list[int]:
    """每个请求从上一个的下一位起转（原件 `Rotate`，`strategies.go:190-196`）。

    起点 = 该 `pool` 的请求计数 `% n`，**先取模再自增**（所以同一个 pool 的第一次是恒等）。
    计数按 pool 分开（`turns` 是 `pool → 次数`）。`n == 0` ⇒ `[]`（原件这里会除零 panic；
    pool 侧空池就回空，不抛）。
    ★ `turns` 由调用方持有，本函数不落盘。
    """
    n = len(seats)
    if n == 0:
        return []
    book = {} if turns is None else turns
    so_far = book.get(pool, 0)
    book[pool] = so_far + 1
    start = so_far % n
    idx = identity(n)
    return idx[start:] + idx[:start]


def least_used(seats: Sequence[Seat]) -> list[int]:
    """用得最少的先（原件 `LeastUsed`，`strategies.go:203-221`）。比较键序**逐字**是：

    ① 两个都在 tier 2（用尽了）且 `credits` 不同 ⇒ **能靠赠金继续的先用**
       （原文就这一句带 `tier`：`if ta == 2 && tb == 2 && sa.Credits != sb.Credits`）；
    ② `used` 升序 —— ★ 额度**不知道**的座（`used is None` / `known=False`）一律排在
       **所有知道的之后**（`_share_key`）：`known=False` 时 `used` 填多少都不可信；
    ③ `_by_left` 的组内位次（余额多的先；没告诉过的在后）；
    ④ `tokens` 升序（原件 `fewerTokens`；本仓没有衰减，`tokens` = 调用方给的已衰减值）。
    全程**稳定**：全打平 ⇒ 保列出序（保 prompt cache 热）。
    """
    place = _by_left(seats)

    def key(index: int) -> tuple[int, int, int, float, int, float]:
        seat = seats[index]
        # ① 原件那一句只在「两个都在 tier 2」时才看 `credits`：能靠赠金继续的先用。
        #    tier 2 以外给同一个中性值 0 —— 那些座的 `used` 一定小于任何 tier 2 的座，
        #    所以②的 `used` 升序已经把它们分开，`credits` 不会跨界插队。
        #    ★ 额度「不知道」的座给 1（与「用尽且没赠金」同值）：它不许插到
        #      「tier 2 但能靠赠金继续」的前面（那一批是 0），也不许插到 tier 0/1 前面。
        level = usage_tier(seat)
        spent_but_granted = level == 2 and not seat.credits
        credits_first = 1 if level == UNKNOWN_TIER or spent_but_granted else 0
        # ② `_share_key`：知道的按 `used` 升序；**不知道的一律排在所有知道的之后**。
        return (credits_first, *_share_key(seat),
                place[index] if place is not None else 0, seat.tokens)

    idx = identity(len(seats))
    idx.sort(key=key)
    return idx


def by_pace(seats: Sequence[Seat]) -> list[int]:
    """每小时还剩得多的先（原件 `Pace`，`strategies.go:243-295`）。

    「还剩多少」= `pace`：一周的量摊到小时。它比「用得少」和「续得早」都准 —— 一个剩 3%、
    一小时后续的号，按「续得早」会排在一个剩 90%、两小时后才续的号前面，那是错的。

    分带（`PACE_BAND`）：把**参与分带的人**的 `pace` 从大到小排，`k == 0` 或
    `p < PACE_BAND*top` 起新的一带，带号递增；同一带里的人视为一样快，按列出序保 prompt cache。
    ★ 参与分带的只有 `usage_tier(seat) == 0 && !learns && pace is not None` 的人
      （原件 `if tier(s.Used) == 0 && !s.Learns`；`None` 不参与）。额度**不知道**的座
      （`used is None` / `known=False`）同样不参与 —— 它不是「还剩得多」，是「判不出来」；
      这种座落在最后一档（`UNKNOWN_TIER`），排在所有知道的之后。
    ★ `pace is None` **不许当 0**：`None` 是「不知道」，`0` 是「一点都不剩」。落位按同族
      规则 —— 不知道的排在告诉过的之后（和 `_left_key` 里 `left is None` 那条一个口径）。
      ★ 这一条是**本仓对原件的偏离**，如实记：原件的 `band` 是 `map`，`None` 的人没进
      `byPace` ⇒ 读缺失键得 `0`，于是「不知道」会被当成「最快那一带」，与 `0` 同档。
      判据 6 明写两者排位必须不同 ⇒ pool 侧在 `band` 之前插一级「知不知情」，其余键序不动。

    主排序键序：`usage_tier` 升（**不知道的 `UNKNOWN_TIER` 恒在最后**）→（tier 2 之间比
    `credits`）→（tier > 0 时 `used` 升，之后直接比 `tokens` —— 原件的 else-if 链在这一支
    不再看 `left`）→（tier == 0 时 `learns` 先、`pace` 知情的先、带号升、余额位次、
    `tokens` 升）。
    """
    place = _by_left(seats)
    pairs: list[tuple[float, int]] = []
    for index, seat in enumerate(seats):
        # ★ 额度「不知道」的座不进分带：pace 再准也判不出它还有没有量
        #   （原件的 `tier(s.Used) == 0` 谓词在 pool 侧换成 `usage_tier(seat) == 0`）。
        if seat.pace is None or usage_tier(seat) != 0 or seat.learns:
            continue
        pairs.append((seat.pace, index))
    pairs.sort(key=lambda pair: -pair[0])
    band: dict[int, int] = {}
    top = 0.0
    for k, (pace, i) in enumerate(pairs):
        if k == 0:
            top = pace
            continue
        # 原件读 `band[byPace[k-1]]`，前一带若没记过，Go 的 map 零值读 0。
        previous = band.get(pairs[k - 1][1], 0)
        if pace < PACE_BAND * top:
            band[i] = previous + 1
            top = pace
        else:
            band[i] = previous

    def key(index: int) -> tuple[int, int, int, int, float, int, int, int, int, float]:
        seat = seats[index]
        level = usage_tier(seat)
        if level == UNKNOWN_TIER:
            # 额度不知道 ⇒ 排在所有知道的之后；同伙之间按 used（给了的话）升、没给的沉底。
            return (level, 0, *_share_key(seat), 0, 0, 0, 0, seat.tokens)
        if level > 0:
            # 原件的 else-if 链：`ta == tb > 0` 且 `used` 也打平时，函数**直接落到**
            # `return sa.Tokens < sb.Tokens`（不再看 `left`）⇒ 后四级一律给中性值。
            credits_first = (0 if seat.credits else 1) if level == 2 else 0
            return (level, credits_first, *_share_key(seat), 0, 0, 0, 0, seat.tokens)
        return (level, 0, 0, 0, 0.0,
                0 if seat.learns else 1,
                0 if seat.pace is not None else 1,
                band.get(index, 0),
                place[index] if place is not None else 0,
                seat.tokens)

    idx = identity(len(seats))
    idx.sort(key=key)
    return idx


def weighted(seats: Sequence[Seat], *, pool: str,
             rounds: dict[str, dict[str, int]] | None = None) -> list[int]:
    """按权重平摊，且**平滑**（原件 `Weighted`，`strategies.go:300-306`）。

    = `first(round_pick(...), n)`：赢家提到第 0 位，其余保列出序（给 failover 留顺序）。
    ★ 不是旋转：`[0,1,2]` 赢家是 1 ⇒ `[1,0,2]`，不是 `[1,2,0]`。
    `weight` 按原件取 `max(weight, 1)`（权重 0 等于没说过）。
    `resting` 的号本轮不参与（它的份由别人按权重分掉，回来了再拿自己的份）。
    ★ `rounds` 由调用方持有（`pool → {key: cur}`），本函数不落盘。
    """
    keys = [seat.key for seat in seats]
    weights = [max(seat.weight, 1) for seat in seats]
    rests = [seat.resting for seat in seats]
    picked = round_pick(pool, keys, weights, rests, state={} if rounds is None else rounds)
    return first(picked, len(seats))


def free_first(seats: Sequence[Seat]) -> list[int]:
    """不花钱的先用（原件 `FreeFirst`，`strategies.go:336-346`）。

    只分**两档**：`free=True` 的全部在前，其余在后；两档内部都保列出序、
    **不做任何再排序** —— 特别是不把「快用完的免费号」推到付钱的后面：
    免费号用完了也不花钱，没理由让位。付费档也不按 Smart 的续期权重排
    （本路由存在的意义就是那档免费的）。
    """
    free = [i for i, seat in enumerate(seats) if seat.free]
    paid = [i for i, seat in enumerate(seats) if not seat.free]
    return free + paid


def fastest(seats: Sequence[Seat], *, pool: str,
            probes: dict[str, dict[str, int]] | None = None) -> list[int]:
    """最近答得最快的先（原件 `Fastest`，`fastest.go:59-117`）。

    四堆，顺序是判据的一部分：`awake + resting + spent`，其中 `awake = fast + unmeasured`。
    分堆优先级：`resting` > `usage_tier(used) == 2`（**知道**且用尽了）> `ttft > 0`（量过）>
    `unmeasured`。★ 额度「不知道」（`used is None` / `known=False`）**不算**用尽（见
    `usage_tier()`），也不许借速度插到知道的号前面：两堆各自把这种座沉到堆内最后。
    量过的按 `estimate()` 升序排，再按「一成之内算一样快」分带（`ALIKE`），带内保列出序 ——
    否则两条差几毫秒的通道会每个请求互换位置。

    ★ 没量过的不能饿死：一直排在量过的后面，它永远轮不到、永远量不到。所以当
      `fast` 与 `unmeasured` **都非空**时，每 `PROBE_EVERY` 次把 `unmeasured` 里下一个
      提到最前面（探测轮次 `turns` 在它们之间轮流，这样「答了但不报速」的号不会一直占着轮次），
      然后计数归零、轮次 +1。**「先加再判」的顺序是判据的一部分**（先归零就永远到不了阈值）。
    ★ 探测计数与轮次都由调用方持有（`probes` 是 `pool → {"n", "turns"}`），本函数不落盘。
    """
    state = {} if probes is None else probes
    fast: list[int] = []
    unmeasured: list[int] = []
    resting: list[int] = []
    spent: list[int] = []
    for i, seat in enumerate(seats):
        if seat.resting:
            resting.append(i)
        elif usage_tier(seat) == 2:  # 「用尽」只对额度**知道**的座成立；不知道的不算 spent
            spent.append(i)
        elif seat.ttft > 0:
            fast.append(i)
        else:
            unmeasured.append(i)
    # ★ 额度「不知道」的座不许借速度插到知道的号前面：量过 / 没量过两堆内部各自把这种座
    #   沉到堆内最后（稳定排序 ⇒ 它们彼此仍保列出序）。堆间次序不动：`resting` / `spent` 是
    #   **已知的坏**（刚失败 / 确定用尽），仍排在 awake 之后。
    unmeasured.sort(key=lambda i: usage_tier(seats[i]) == UNKNOWN_TIER)
    paces = sorted(seats[i].tps for i in fast if seats[i].tps > 0)
    mid = paces[len(paces) // 2] if paces else 0.0
    est = {i: estimate(seats[i].ttft, seats[i].tps, mid) for i in fast}
    fast.sort(key=lambda i: est[i])
    band: dict[int, int] = {}
    top = 0.0
    for k, i in enumerate(fast):
        if k == 0:
            band[i] = 0
            top = est[i]
            continue
        # 原件 `else if band[i] = band[fast[k-1]]; est[i] > alike*top { band[i]++; top = est[i] }`
        band[i] = band[fast[k - 1]]
        if est[i] > ALIKE * top:
            band[i] += 1
            top = est[i]
    fast.sort(key=lambda i: (usage_tier(seats[i]) == UNKNOWN_TIER, band[i], i))
    awake = fast + unmeasured
    if fast and unmeasured:
        book = state.setdefault(pool, {"n": 0, "turns": 0})
        book["n"] += 1
        if book["n"] >= PROBE_EVERY:
            probe = unmeasured[book["turns"] % len(unmeasured)]
            book["n"] = 0
            book["turns"] += 1
            awake = [probe, *[i for i in awake if i != probe]]
    return [*awake, *resting, *spent]


def apply_strategy(name: str, seats: Sequence[Seat], *, pool: str,
                   state: dict[str, Any] | None = None) -> list[int]:
    """按名字跑一个内置策略；**坏掉就 fail-open 回列出顺序，绝不抛**。

    ★ 名字先过 `parse_routing`（卡 E103）：别名 / 大小写 / 首尾空白一律归一，
      空串 = `SMART`（原件默认值）。早先这里对 `smart` 与空串都直接退恒等，
      于是 `--routing smart` 静默等于「按列出顺序」；现在 `smart` 真的走 `smart_order`。
      名字认不出 ⇒ 仍然退恒等（本函数跑在请求路径上，抛一下就是 500）。

    对应原件两处：`routes.Find`（`routes.go:119-131`，找不到 ⇒ `ok=false` ⇒ 调用方按列出
    顺序试）与 `Apply`（`routes.go:143-166`，`defer recover()` 兜 panic + 长度/越界/重复检查
    ⇒ `identity(len(seats))`）。本函数把后者的检查直接交给既有的 `apply_order()`，不重写一份。
    ★ 这是本模块**唯一**允许吞异常的地方：排位是个优化，坏掉的排位不该让整轮派活停摆。
    ★ `state` 一个 dict 装三种状态（`"turns"` / `"rounds"` / `"probes"`），三种都是
      `pool → ...`；调用方跨请求传同一个 dict，轮转/探测的语义才成立。本函数不落盘。
    """
    n = len(seats)
    try:
        canonical = parse_routing(name)
    except RouteError:
        # ★ 请求路径上不抛：名字写坏也只是一次「没有更好的排位」，退列出顺序继续派活。
        #   名字该不该被接受，由启动面（build_server / main）拦 —— 那里才有人看得到。
        return identity(n)
    if canonical == MANUAL:
        return identity(n)
    book: dict[str, Any] = {} if state is None else state
    try:
        # 分派走**模块级名字**（不是一张私有表）：`apply_strategy` 的 fail-open 判据
        # 要能被「一个返回坏排列的假策略」咬住，测试只能替换本模块的公开名字。
        if canonical == SMART:
            got = smart_order(seats)
        elif canonical == ORDERED:
            got = ordered(seats)
        elif canonical == ROTATE:
            got = rotate(seats, pool=pool, turns=book.setdefault("turns", {}))
        elif canonical == LEAST_USED:
            got = least_used(seats)
        elif canonical == PACE:
            got = by_pace(seats)
        elif canonical == WEIGHTED:
            got = weighted(seats, pool=pool, rounds=book.setdefault("rounds", {}))
        elif canonical == FREE_FIRST:
            got = free_first(seats)
        else:
            got = fastest(seats, pool=pool, probes=book.setdefault("probes", {}))
    except Exception:
        return identity(n)
    return apply_order(got, n)


def smart_order(seats: Sequence[Seat]) -> list[int]:
    """给号排位，返回**索引排列**（对应 magpie `Smart.Strategy.Order`，`strategies.go:119-169`）。

    排序是**逐级稳定**的，不是拼一个大元组 —— 因为原件就是一串 `sort.SliceStable`，
    每级只在上一级打平时才起作用：

    1. 分四桶：`usage_tier(seat) == 2` 进 `spent`、`== 1` 进 `low`、`== 0` 进 `fine`；
       `== UNKNOWN_TIER`（`used is None` 或 `known=False`，额度**不知道**）进 `unknown`；
    2. `fine` 内部逐级稳定排序（优先级低的先排）：`left` 大的在前 → `lapse` 截时比、
       空排后 → `soon` 逐窗口截时比、空排后、窗口多的在前；
    3. `low` / `spent` 按 `used` 升序（原件两处都是 `Used` 升序；`_share_key` 对
       已知座给的正是 `(0, 0, used)`，等价）；
    4. 拼成 `fine + low + spent + unknown`（tier 0 全在前、tier 2 其次、**不知道的最后**）；
    5. `resting` 的号**沉到最后**（稳定：两边各自的相对次序都不动）。

    ★ 输入顺序就是"基准顺序"：每一级都稳定 ⇒ 全程打平的那些号**保持原序**（保 prompt cache）。
    ★ `seats` 为空 ⇒ `[]`，不抛（`apply_order` 对空也回 `[]`）。
    """
    n = len(seats)
    if n == 0:
        return []
    width = max(len(seat.soon) for seat in seats)
    fine: list[int] = []
    low: list[int] = []
    spent: list[int] = []
    unknown: list[int] = []
    for index, seat in enumerate(seats):
        level = usage_tier(seat)
        if level == 2:
            spent.append(index)
        elif level == 1:
            low.append(index)
        elif level == UNKNOWN_TIER:
            # 额度**不知道**（used is None 或 known=False）自成一桶，排在所有知道的之后：
            # 它不是「用了 0%」，也不能拿来跟「已经用了 95%」比大小。
            unknown.append(index)
        else:
            fine.append(index)
    # 逐级稳定排序：**优先级低的先排**，后一级只在前一级打平时才动顺序。
    fine.sort(key=lambda i: _left_key(seats[i]))
    fine.sort(key=lambda i: _lapse_key(seats[i]))
    fine.sort(key=lambda i: _soon_key(seats[i], width))
    low.sort(key=lambda i: _share_key(seats[i]))
    spent.sort(key=lambda i: _share_key(seats[i]))
    # 「不知道」这一桶内部也有明确位次：给了数的（仍不可信，但至少能破平）在前，
    # 连数都没有的沉底 —— 与 `least_used` 的 `_share_key` 同一口径。
    unknown.sort(key=lambda i: _share_key(seats[i]))
    order = fine + low + spent + unknown
    # resting 沉底（原件的 Sink 语义；只排位，不写盘）。
    awake = [i for i in order if not seats[i].resting]
    asleep = [i for i in order if seats[i].resting]
    return awake + asleep


def apply_order(order: Sequence[int], n: int) -> list[int]:
    """把策略给的 `order` 落到 `n` 个号上；**不是排列就 fail-open 回 `identity`**。

    对应 magpie `internal/routes/routes.go:143` `Apply`：长度不符 / 越界 / 重复（原件还有
    `defer recover()` 兜 panic）⇒ 一律 `identity(len(seats))`，**不抛**。
    理由：排位是个优化，坏掉的排位不该让整轮派活停摆 —— 退回原序最坏只是慢一点。
    """
    identity = list(range(n)) if n > 0 else []
    try:
        got = list(order)
    except TypeError:
        return identity
    if len(got) != n:
        return identity
    seen = [False] * n
    for item in got:
        if isinstance(item, bool) or not isinstance(item, int):
            return identity
        if item < 0 or item >= n or seen[item]:
            return identity
        seen[item] = True
    return got


def _resolve_root(root: Path | str | None) -> Path:
    """判据根：给了就用给的，没给就跟着 `pool_quota.ROOT`（同一棵树，不另立一个根）。"""
    if root is None:
        return Path(pool_quota.ROOT)
    return Path(root)


def reset_for(model: str, *, now: datetime | str | None = None,
              root: Path | str | None = None) -> tuple[datetime | None, str]:
    """这个模型**最近一次**记录的额度重置时间 ⇒ `(reset_at, recorded_at)`。

    做法（设计稿 §3 的原话）：遍历状态文件里**全部卡**的 `cards[卡][model]`，
    取 `recorded_at` **字符串最大**的那条（`recorded_at` 是
    `datetime.now().astimezone().isoformat()`，带 offset ⇒ 同格式下可直接比大小），
    再用 `pool_quota.parse_reset()` 解析它的 `reset_at`。

    ★ 取 `max` 不是 `min`：额度是"最后知道的算数"，两条记录里较新的那条才反映现状。
    ★ 同一毫秒并列 ⇒ 取先遇到的那条（`>` 而不是 `>=`），并列时"取任一"是允许的。
    ★ 没有记录 / 文件不在 / JSON 坏了 / 形状不对 ⇒ `(None, "")`，**不抛**：调用方必须当
      "不知道"（不许当 0 秒、也不许当余额耗尽）。
    ★ `now` 在这里**不用**：读记录不依赖现在。留着是为了和 `pool_quota.status(now=...)`
      的签名对齐（"还剩多久"由 `seconds_left()` / `status()` 算，本函数只管"记录怎么说"）。
    """
    del now  # 读记录不看现在；见 docstring 最后一条。
    if not model:
        return (None, "")
    path = pool_quota._state_path(_resolve_root(root))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (None, "")
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, dict):
        return (None, "")
    best: dict[str, object] | None = None
    best_at = ""
    for per_card in cards.values():
        if not isinstance(per_card, dict):
            continue
        record = per_card.get(model)
        if not isinstance(record, dict):
            continue
        recorded_at = record.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at:
            continue
        if best is None or recorded_at > best_at:
            best = record
            best_at = recorded_at
    if best is None:
        return (None, "")
    raw = best.get("reset_at")
    return (pool_quota.parse_reset(raw if isinstance(raw, str) else None), best_at)


def model_until(model: str, *, now: datetime | str | None = None,
                root: Path | str | None = None) -> datetime | None:
    """便捷封装：`reset_for(...)` 的第一项（只要"额度什么时候回来"）。"""
    return reset_for(model, now=now, root=root)[0]


def seconds_left(reset_at: datetime | None, *, now: datetime | str | None = None) -> float | None:
    """`reset_at - now` 的秒数；`reset_at is None`（不知道）⇒ `None`，**不当 0**。

    时间归一一律借 `pool_quota` 的两个小工具（`_to_aware` / `_resolve_now`），不在本模块
    重写第三份"naive 算本地时间"的规则。
    """
    if reset_at is None:
        return None
    now_dt = pool_quota._resolve_now(now)
    target = pool_quota._to_aware(reset_at)
    if now_dt.tzinfo is None:
        now_dt = pool_quota._to_aware(now_dt)
    return (target - now_dt).total_seconds()
