"""卡 E95 · 判据 1/2：「不知道」与「知道」分开（`tools/pool/route.py` 的 `used` / `tier()`）。

钉子打在**行为**上：

- `Seat.used` 缺省是 `None`（没量过），**不是** `0.0`（真的用了 0%）；
- `tier(None)` 不抛、回 `UNKNOWN_TIER`；`tier(0.0)` 仍回 0 —— 两者必须不同档；
- 四个读 `used` 的分桶策略（`smart_order` / `least_used` / `by_pace` / `fastest`）：
  额度**不知道**的座排在所有知道的之后（卡规格判据 1 的钉子：m95 必须在前）；
- `known=False` 让 `used` 不可信：`Seat(known=False, used=99.0)` **不按 99 排** ——
  `usage_tier()` 回 `UNKNOWN_TIER`（不是「用尽」档），`fastest()` 把它放进 awake 而不是
  spent，四个策略里它的位次与它被填的那个数**无关**（判据 2）。

★ 判据 2 的读法：「不许因为 `used` 大就排到已知 95% 的号后面」= 它落后**不许来自那个数**
  （那个数不可信 ⇒ 不参与比较）。位次本身仍是「不知道排在已知之后」（判据 1），两者不矛盾：
  `[未知, 已知 95%]` 的结论对未知那座填任何 `used` 都一样。所以这里用「与填什么无关」
  钉判据 2，而不是把「不知道」提到已知前面 —— 后者会推翻判据 1 的钉子。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import route as pool_route  # noqa: E402

Seat = pool_route.Seat

#: 判据 1 的钉子：`never` 从没量过、`m95` 已知 95%。★ m95 必须在前（当前实现是反的）。
NEVER = {"key": "never", "known": False}
M95 = {"key": "m95", "used": 95.0}

#: 四个**读 `used`** 的策略（另外三个 ordered/rotate/weighted/free_first 不读它）。
BUCKETED = ("smart_order", "least_used", "by_pace", "fastest")


def order_of(name: str, seats: list[object]) -> list[int]:
    """按名字跑一个分桶策略（`fastest` 要 pool 关键字，其余不要）。"""
    if name == "smart_order":
        return pool_route.smart_order(seats)
    if name == "least_used":
        return pool_route.least_used(seats)
    if name == "by_pace":
        return pool_route.by_pace(seats)
    return pool_route.fastest(seats, pool="p")


# ---------------------------------------------------------------- 判据 1：缺省是「不知道」

def test_used_defaults_to_none_not_zero() -> None:
    """`Seat(key=...)` 不给 `used` ⇒ `None`；`0.0` 是「真的用了 0%」，两个不同的意思。"""
    seat = Seat(key="never")
    assert seat.used is None
    assert Seat(key="zero", used=0.0).used == 0.0


def test_tier_none_is_the_unknown_tier_and_does_not_raise() -> None:
    assert pool_route.tier(None) == pool_route.UNKNOWN_TIER
    assert pool_route.UNKNOWN_TIER not in (0, 1, 2)
    # 不知道 ≠ 0：不许静默当 0（否则 `tier(None)` 与 `tier(0.0)` 不可分辨）。
    assert pool_route.tier(None) != pool_route.tier(0.0)


def test_usage_tier_turns_known_false_into_unknown() -> None:
    assert pool_route.usage_tier(Seat(key="never")) == pool_route.UNKNOWN_TIER
    assert pool_route.usage_tier(Seat(key="zero", used=0.0)) == 0
    assert pool_route.usage_tier(Seat(key="spent", used=99.0)) == 2
    # 判据 2：known=False ⇒ 这个数不可信 ⇒ 不是「用尽」。
    untrusted = Seat(key="untrusted", known=False, used=99.0)
    assert pool_route.usage_tier(untrusted) == pool_route.UNKNOWN_TIER


@pytest.mark.parametrize("bad", [float("nan"), True, False, 101.0, -0.1, "95"])
def test_tier_still_rejects_what_is_not_a_share(bad: object) -> None:
    """放松 `None` 不许顺手放松别的：越界 / bool / NaN / 非数字照旧抛，不 clamp。"""
    with pytest.raises(pool_route.RouteError):
        pool_route.tier(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 判据 1：钉子（四个策略）

def test_smart_order_puts_the_known_seat_first() -> None:
    assert pool_route.smart_order([Seat(**NEVER), Seat(**M95)]) == [1, 0]


def test_least_used_puts_the_known_seat_first() -> None:
    assert pool_route.least_used([Seat(**NEVER), Seat(**M95)]) == [1, 0]


def test_by_pace_puts_the_known_seat_first() -> None:
    assert pool_route.by_pace([Seat(**NEVER), Seat(**M95)]) == [1, 0]


def test_fastest_puts_the_known_seat_first() -> None:
    assert pool_route.fastest([Seat(**NEVER), Seat(**M95)], pool="p") == [1, 0]


def test_smart_order_lists_every_known_tier_before_the_unknown() -> None:
    """知道的三档（0 / 90+ / 98+）都排在「不知道」前面；不知道排最后自成一位。"""
    seats = [
        Seat(key="never"),
        Seat(key="fresh", used=0.0),
        Seat(key="low", used=95.0),
        Seat(key="spent", used=99.0),
    ]
    assert pool_route.smart_order(seats) == [1, 2, 3, 0]


def test_the_unknown_bucket_is_the_tail_of_the_order() -> None:
    """不知道的自成一桶、整桶在尾：知道的先，剩下两位都是不知道（内部次序不另作规定）。"""
    seats = [
        Seat(key="no-number", known=False),
        Seat(key="has-number", known=False, used=42.0),
        Seat(key="known", used=1.0),
    ]
    got = pool_route.smart_order(seats)
    assert got[0] == 2
    assert sorted(got[1:]) == [0, 1]


def test_unknown_never_jumps_ahead_of_a_spent_seat_with_credits() -> None:
    """「不知道」不许插到「tier 2 但能靠赠金继续」的前面 —— 那一批仍算知道（判据 1 的方向）。"""
    unknown = Seat(key="never")
    granted = Seat(key="granted", used=99.0, credits=True)
    assert pool_route.least_used([unknown, granted]) == [1, 0]
    assert pool_route.by_pace([unknown, granted]) == [1, 0]


def test_every_known_order_is_unchanged_when_all_shares_are_known() -> None:
    """回归：全都知道的时候，位次仍是老口径（`used` 升序）。"""
    seats = [Seat(key="a", used=10.0), Seat(key="b", used=20.0)]
    assert pool_route.least_used(seats) == [0, 1]
    assert pool_route.smart_order(seats) == [0, 1]


# ---------------------------------------------------------------- 判据 2：known=False 保护 used

def test_known_false_moves_a_measured_seat_out_of_the_spent_heap() -> None:
    """`used=99.0` + `known=False` 不许被读成「用尽」：它在 awake（量过），不在 spent。"""
    untrusted = Seat(key="untrusted", known=False, used=99.0, ttft=10.0)
    spent = Seat(key="spent", used=99.0)
    assert pool_route.fastest([spent, untrusted], pool="p") == [1, 0]
    # 对照：同样的数、`known=True` ⇒ 两座都用尽 ⇒ 保列出序（这就是「按数排」的样子）。
    trusted = Seat(key="trusted", used=99.0, ttft=10.0)
    assert pool_route.fastest([Seat(key="spent", used=99.0), trusted], pool="p") == [0, 1]


@pytest.mark.parametrize("name", BUCKETED)
@pytest.mark.parametrize("used", [0.0, 50.0, 95.0, 99.0, 100.0])
def test_known_false_position_does_not_depend_on_the_number(name: str, used: float) -> None:
    """判据 2：位次与填的那个数无关（与 `used=None` 逐位相同）⇒ 那个大数不是它落后的理由。"""
    baseline = order_of(name, [Seat(**NEVER), Seat(**M95)])
    given = order_of(name, [Seat(key="never", known=False, used=used), Seat(**M95)])
    assert baseline == given == [1, 0]
