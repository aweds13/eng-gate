r"""判据面：限额要在**派活之前**拦（卡 A338 · T-AG540；移植 magpie `budget.Reserve` / `Refusal`）。

**防什么**：`tools/wb_dispatch.py:219 DEFAULT_INPUT_BUDGET` 那条是**熔断**（跑起来才
`break`，只看 input，没有窗口，止损不是失败）；本模块是**预算授权**：派活之前就问
「这个号这个窗口还有余量吗」，不够就拒并给出 `Retry-After`（magpie `budget.go:341-430`
`Reserve()` / `:299-315` `Refusal.Error()` / `:318-320` `RetryAfter()`）。

★★ **判据只许写这一份**：`tools/wb_dispatch.py`（占树之前）与 `tools/pool_mcp.py`
   （MCP 面）将来都调 `check()`，**不许各写一份 if** —— 两份真源正是本仓最忌的。

★ 判据顺序（逐字照 `budget.go:204-219` 与 `Binding()` `:257-277`）：
  ① `limits` 空 ⇒ 放行（`:341` 的 `len(ls) == 0 ⇒ 永不过问`）；
  ② **每一条** limit 都要有余量，任一条不够就拒（不是「最宽的那条够就放」）；
  ③ 在飞预留算进去（`spent[i] + inflight >= limit`）；
  ④ `retry_after_s >= 1`；
  ⑤ `binding` 三段优先级：**已花完的优先** → **续期最晚的** → `share()` 最大的。
  ★ 边界用 `>=` 不是 `>`（`st.Tokens >= l.Tokens`）：差一个 token 就放行是只在边界
    出现、人工测不出来的偏差。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pool.limits_policy import Limit, window

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class Verdict:
    """一次判的结论：放不放、卡在第几条、什么时候续上、等多久、为什么。"""

    allowed: bool
    binding: int | None
    reset_at: datetime | None
    retry_after_s: int
    why: str


def share(
    limit: Limit,
    tokens: int,
    cost: float,
    *,
    inflight_tokens: int = 0,
    inflight_cost: float = 0.0,
) -> float:
    """用量 / 上限（`Binding()` 第三段用的就是它）：两条轴里**更满**的那条，1.0 = 刚好花完。"""
    worst = 0.0
    if limit.tokens > 0:
        worst = max(worst, (tokens + inflight_tokens) / limit.tokens)
    if limit.cost > 0:
        worst = max(worst, (cost + inflight_cost) / limit.cost)
    return worst


def retry_after(reset_at: datetime, now: datetime) -> int:
    """`Retry-After` 秒数：向上取整到整秒，且**至少 1 秒**（`budget.go:318-320`）。

    抽成独立函数是为了让「下限 1 秒」可被单测直接咬住 —— 藏在 `check()` 里时
    `max(…, 1)` 那一半在真实窗口下永远走不到（`window()` 的 `reset` 总在 `now` 之后）。
    """
    return max(int((reset_at - now).total_seconds() + 0.999), 1)


def check(
    limits: Sequence[Limit],
    *,
    spent: Mapping[int, tuple[int, float]],
    now: datetime,
    inflight_tokens: int = 0,
    inflight_cost: float = 0.0,
) -> Verdict:
    """派活之前的判：`limits` 每一条都要有余量，任一条不够就拒。

    `spent[i]` 是**第 i 条** limit 在自己窗口里的 `(tokens, cost)`（调用方用
    `pool.limits_policy.window(limits[i], now)` 算窗口、用 `pool.ledger_spend.sums`
    求和后传进来；两边必须用同一个 `now`）。
    """
    if not limits:
        return Verdict(
            allowed=True,
            binding=None,
            reset_at=None,
            retry_after_s=0,
            why="没有声明任何限额 ⇒ 永不过问（budget.go:341）",
        )
    over: list[tuple[int, float, datetime]] = []
    for index, limit in enumerate(limits):
        if not limit.limited():
            continue
        used_tokens, used_cost = spent.get(index, (0, 0.0))
        tokens_over = limit.tokens > 0 and used_tokens + inflight_tokens >= limit.tokens
        cost_over = limit.cost > 0 and used_cost + inflight_cost >= limit.cost
        if not (tokens_over or cost_over):
            continue
        _start, reset = window(limit, now)
        share_of = share(
            limit,
            used_tokens,
            used_cost,
            inflight_tokens=inflight_tokens,
            inflight_cost=inflight_cost,
        )
        over.append((index, share_of, reset))
    if not over:
        return Verdict(
            allowed=True,
            binding=None,
            reset_at=None,
            retry_after_s=0,
            why="每条限额都有余量",
        )
    # ①已花完的（`over` 里全是）→ ②续期最晚的 → ③share() 最大的
    binding, worst_share, reset = max(over, key=lambda item: (item[2], item[1]))
    limit = limits[binding]
    used_tokens, used_cost = spent.get(binding, (0, 0.0))
    detail: list[str] = []
    if limit.tokens > 0 and used_tokens + inflight_tokens >= limit.tokens:
        detail.append(f"tokens {used_tokens}+{inflight_tokens} >= {limit.tokens}")
    if limit.cost > 0 and used_cost + inflight_cost >= limit.cost:
        detail.append(f"cost {used_cost:.4f}+{inflight_cost:.4f} >= {limit.cost}")
    return Verdict(
        allowed=False,
        binding=binding,
        reset_at=reset,
        retry_after_s=retry_after(reset, now),
        why=(
            f"限额已满：第 {binding} 条（period={limit.period}，{'；'.join(detail)}）"
            f"⇒ 派活之前就拒；窗口在 {reset.isoformat()} 续上（share={worst_share:.3f}）"
        ),
    )
