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
- `soon` 逐窗口比时，**前缀相同则窗口多的在前**（原件 `y.IsZero()` 那条：对方先没窗口 ⇒ 我方先）。
- `resting` 的号沉到最后：对应原件 `Seat.Resting` 的注释 "it rests after a failure now"。
  原件 `Smart` 里并没拿 `Resting` 排位，本卡规格要求沉底 —— 只在本模块里排位，**不做持久化**。
- 没有额度记录 ≠ 立刻可用：`reset_for()` 回 `(None, "")`，调用方必须当"不知道"
  （`pool_quota.status()` 的四态之一就叫 `未记录`，`why` 原文是"没有这条记录 ⇒ 不猜"）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pool_quota

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "LOW_SHARE",
    "USED_SHARE",
    "RouteError",
    "Seat",
    "apply_order",
    "model_until",
    "reset_for",
    "seconds_left",
    "smart_order",
    "tier",
]

# 与 magpie 同名的两个阈值（`strategies.go:15-17`）。判据逐字照抄，别改数：
#   share >= 98（`provider.SpentShare`）⇒ 用尽了；share >= 90 ⇒ 快用完了。
LOW_SHARE = 90.0
USED_SHARE = 98.0

# 比任何真实时钟都远的 aware 时间：`soon` 逐窗口比时给"窗口更少"的那方补位用。
# 补成"永远更晚"就等于原件的 `x.IsZero() ⇒ 对方先`（前缀相同 ⇒ 窗口多的在前）。
_FAR = datetime(9999, 12, 31, 23, 0, tzinfo=timezone.utc)


class RouteError(Exception):
    """排序判据的输入不成立 —— 形状变了就该炸，不许猜、不许 clamp。"""


def tier(share: float) -> int:
    """已用份额 → 档位（0 = 还有余量，1 = 快用完，2 = 用尽了）。

    判据**逐字**是 magpie `internal/routes/strategies.go:15-29` 的
    `switch { case share >= UsedShare: return 2; case share >= LowShare: return 1 }; return 0`。

    ★ `share` 不在 `[0, 100]` ⇒ `RouteError`，**绝不 clamp**：`101` 是"这个数从哪来的"，
      不是"差一点就满"；把它压成 `100` 等于把上游的形状错误洗成一次成功派活。
    """
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
    - `used`：已用份额 `0–100`
      （`// Used is the share of its allowance used that counts the model`）。
    - `soon`：窗口什么时候续（`// Soon is when its windows renew, the biggest first`），可空。
    - `lapse`：`Soon` 打平时的第二判据
      （`// Lapse ... zero when not told. Smart goes by it when Soon ties`）。
    - `resting`：刚失败、正在休息（`// Resting: it rests after a failure now`）。
    - `left` / `left_in`：余额，`None` / `""` = 没人告诉过（`// empty when no balance was told`）。
    """

    key: str
    known: bool = True
    used: float = 0.0
    soon: tuple[datetime, ...] = ()
    lapse: datetime | None = None
    resting: bool = False
    left: float | None = None
    left_in: str = ""


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


def smart_order(seats: Sequence[Seat]) -> list[int]:
    """给号排位，返回**索引排列**（对应 magpie `Smart.Strategy.Order`，`strategies.go:119-169`）。

    排序是**逐级稳定**的，不是拼一个大元组 —— 因为原件就是一串 `sort.SliceStable`，
    每级只在上一级打平时才起作用：

    1. 分三桶：`tier(used) == 2` 进 `spent`、`== 1` 进 `low`、其余进 `fine`；
    2. `fine` 内部逐级稳定排序（优先级低的先排）：`left` 大的在前 → `lapse` 截时比、
       空排后 → `soon` 逐窗口截时比、空排后、窗口多的在前；
    3. `low` 按 `used` 升序、`spent` 按 `used` 升序（原件两处都是 `Used` 升序）；
    4. 拼成 `fine + low + spent`（tier 0 全在前、tier 2 最后）；
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
    for index, seat in enumerate(seats):
        level = tier(seat.used)
        if level == 2:
            spent.append(index)
        elif level == 1:
            low.append(index)
        else:
            fine.append(index)
    # 逐级稳定排序：**优先级低的先排**，后一级只在前一级打平时才动顺序。
    fine.sort(key=lambda i: _left_key(seats[i]))
    fine.sort(key=lambda i: _lapse_key(seats[i]))
    fine.sort(key=lambda i: _soon_key(seats[i], width))
    low.sort(key=lambda i: seats[i].used)
    spent.sort(key=lambda i: seats[i].used)
    order = fine + low + spent
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
