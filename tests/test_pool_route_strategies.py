"""卡 A352 · F17 七种内置路由策略：`tools/pool/route.py` 的判据。

每条用例都打在**真判据**上（不是"函数能跑"）：

- `BUILTIN` 恰好七项、逐字等于 magpie 的七个路由名（`provider/routing.go:24-38`）；
- `ordered` 恒等（原件的 `Exact: true`）；`rotate` 按 pool 计数循环左移；
- `least_used` / `by_pace` 的键序（`tier` → `used` → 余额位次 → `tokens`，`pace` 分带）；
- `round_pick` 的平滑加权轮转（`3,1` 走 `a,a,b,a`）、全 resting ⇒ `-1`、换 keys 清旧账；
- `weighted` = `first(round_pick(...))`（赢家提到第 0 位，**不是旋转**）；
- `free_first` 只分两档、档内不再排序；
- `estimate` 的三条分支；`fastest` 的四堆顺序与「每 `PROBE_EVERY` 次给没量过的一次机会」；
- `apply_strategy` 的 fail-open（未知名字 / 非置换 / 越界一律回恒等且**不抛**）。

对照物是 magpie `internal/routes/{strategies,round,fastest}.go` 的逐字取证（见设计原件
`_ext/_port_design_wave4.md` §F17）。状态（`turns` / `rounds` / `probes`）**一律由调用方传**，
模块自己不落盘 ⇒ 每个用例都自己持有一份新状态，互不串味。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

pool_route = importlib.import_module("pool.route")
Seat = pool_route.Seat


# ---------------------------------------------------------------- 小工具

def seats_of(*specs: dict[str, object]) -> list[object]:
    """`seats_of({"key": "a", "used": 10}, ...)` ⇒ `Seat` 列表（省得每行写一遍 `Seat`）。"""
    return [Seat(**spec) for spec in specs]


def plain(n: int) -> list[object]:
    """`n` 个全默认的座位（只给 key）—— 键序全靠调用方另给的字段。"""
    return seats_of(*({"key": f"s{i}"} for i in range(n)))


# ---------------------------------------------------------------- 1. BUILTIN

def test_builtin_is_exactly_seven_in_magpie_order() -> None:
    """`BUILTIN` 恰好 7 项，且**逐字**等于 magpie 的七个路由名。

    判据是「逐字元组 + 长度」，不是「至少包含」：多一个少一个、改一个字母都红。
    对应 `strategies.go:350-357` 的 `Builtin`（七项）与 `provider/routing.go:24-38` 的字符串。
    """
    assert pool_route.BUILTIN == ("order", "rotate", "usage", "pace", "weight", "free", "fast")
    assert len(pool_route.BUILTIN) == 7
    assert len(set(pool_route.BUILTIN)) == 7
    # 七个名字常量与元组内容必须是同一份真源（不是抄两遍）。
    assert pool_route.BUILTIN == (
        pool_route.ORDERED,
        pool_route.ROTATE,
        pool_route.LEAST_USED,
        pool_route.PACE,
        pool_route.WEIGHTED,
        pool_route.FREE_FIRST,
        pool_route.FASTEST,
    )


# ---------------------------------------------------------------- 2. ordered

@pytest.mark.parametrize(
    "seats",
    [
        pytest.param([], id="empty"),
        pytest.param(plain(3), id="all-defaults"),
        pytest.param(seats_of(*({"key": f"s{i}", "resting": True} for i in range(3))),
                     id="all-resting"),
        pytest.param(seats_of({"key": "a", "pace": None, "used": 100.0},
                              {"key": "b", "pace": 0.0, "used": 99.0},
                              {"key": "c", "pace": 1e9, "known": False}),
                     id="pace-none-and-extremes"),
        pytest.param(seats_of({"key": "a", "tokens": 1e18, "weight": 0, "free": True,
                               "credits": True, "ttft": 1e9, "tps": 0.0, "learns": True},
                              {"key": "b", "tokens": 0.0, "weight": 99, "left": 0.0,
                               "left_in": "usd"}),
                     id="tokens-huge"),
    ],
)
def test_ordered_is_identity_under_every_seat_shape(seats: list[object]) -> None:
    """`ordered` 恒等排列，**任何** `Seat` 取值下都成立（原件 `Exact: true` 的语义）。

    `Exact: true` 的意思是「就按这个顺序试，别重排」⇒ 不论座位长什么样都不许动顺序。
    """
    assert pool_route.ordered(seats) == list(range(len(seats)))


# ---------------------------------------------------------------- 3. rotate

def test_rotate_shifts_one_step_per_request() -> None:
    """`rotate` 用「该 pool 的请求计数 `% n`」做起点的循环左移；计数按 pool 分开。

    原件 `strategies.go:190-196`：`n := turns.m[pool] % len(seats); turns.m[pool]++` 之后
    `append(identity(len(seats))[n:], identity(n)...)` —— **先取模再自增**，所以第一次是恒等。
    """
    turns: dict[str, int] = {}
    three = plain(3)
    first = pool_route.rotate(three, pool="p", turns=turns)
    second = pool_route.rotate(three, pool="p", turns=turns)
    third = pool_route.rotate(three, pool="p", turns=turns)
    assert first == [0, 1, 2]
    assert second == first[1:] + first[:1]
    assert third == second[1:] + second[:1]
    # 换了 pool 名 ⇒ 自己的计数从 0 起（不许继承别的 pool 的轮次）。
    assert pool_route.rotate(three, pool="q", turns=turns) == [0, 1, 2]
    # 空池：回 [] 而不是除零。
    assert pool_route.rotate([], pool="p", turns=turns) == []


# ---------------------------------------------------------------- 4-5. least_used

def test_least_used_orders_by_used_then_tokens() -> None:
    """`used` 升序；`used` 打平才看 `tokens`（小的先）。

    原件 `strategies.go:206-220` 的比较序：`used` 升 → `byLeft` 位次 → `tokens` 升。
    """
    seats = seats_of(
        {"key": "a", "used": 50.0, "tokens": 1.0},
        {"key": "b", "used": 10.0, "tokens": 900.0},
        {"key": "c", "used": 50.0, "tokens": 5.0},
        {"key": "d", "used": 50.0, "tokens": 2.0},
    )
    # used 10 的 b 最前；其余三个 used 相同 ⇒ 按 tokens 升序：a(1) → d(2) → c(5)。
    assert pool_route.least_used(seats) == [1, 0, 3, 2]


def test_least_used_keeps_listed_order_when_everything_ties() -> None:
    """全打平 ⇒ 恒等排列（咬「稳定排序」：保列出序 = 保 prompt cache 热）。"""
    assert pool_route.least_used(plain(4)) == [0, 1, 2, 3]
    assert pool_route.least_used([]) == []


def test_least_used_spent_seats_go_after_seats_with_room() -> None:
    """用尽了的（`tier == 2`）排在还有余量的人之后 —— 咬 `tier` 这一级确实在场。

    ★ 如实记：这条咬不住原件的 `tier==2 && credits` 分支（见下一条）。
    """
    seats = seats_of({"key": "spent", "used": 99.0}, {"key": "room", "used": 10.0})
    assert pool_route.least_used(seats) == [1, 0]


def test_least_used_tier_two_credits_seats_go_first() -> None:
    """两个都用尽了时，**能靠赠金继续的先用**（原件 `strategies.go:207-209` 那一句）。

    ★ 这是判据 4 的①那一级，也是设计原件 §6「缺口 2」点名「咬不住」的那一段：pool 侧
      今天**没有 `credits` 的上游来源**（`hold` 五因里那个 `credits` 是上报值，不是剩余赠金），
      所以这条钉子只钉住「字段在、判据在」——调用方真传了 `credits=True` 时行为正确；
      没人传的时候它什么也不影响。缺口如实留着，不假装有来源。
    """
    seats = seats_of(
        {"key": "no-credit", "used": 98.5},
        {"key": "has-credit", "used": 99.0, "credits": True},
    )
    # 靠赠金的那个 `used` 更大 —— 只按 `used` 升序会给出 [0,1]，只有 credits 这一级能翻成 [1,0]。
    assert pool_route.least_used(seats) == [1, 0]
    # 两个都有赠金 ⇒ 回到 used 升序（credits 相同不比）。
    both = seats_of({"key": "a", "used": 99.0, "credits": True},
                    {"key": "b", "used": 98.5, "credits": True})
    assert pool_route.least_used(both) == [1, 0]


# ---------------------------------------------------------------- 6-7. by_pace

def test_by_pace_bands_within_a_tenth() -> None:
    """`pace` 从大到小排；`p < PACE_BAND*top` 起新的一带，同一带里保列出序。

    ★ 参数表里必须有 `0.85`：只用 `(1.00, 0.95, 0.80)` 时，把 `PACE_BAND` 从 `0.9`
      改成 `0.8` **不会红** —— `0.95` 落在两个阈值都能过的区间，而 `0.80` 与 `0.8*1.00`
      严格相等（`0.80 < 0.8` 为假）也仍在同一带，于是两种阈值给出同一个排列。这是**假牙**。
      `0.85` 补上以后两种阈值必然给出不同排列：
      `0.85 < 0.9*1.00` 为真（下一带），而 `0.85 < 0.8*1.00` 为假（同一带）。
    """
    # 先咬最锋利的一处：0.85 必须先被 0.9 判成「下一带」，才能越过列在它前面的 0.95。
    pair = seats_of({"key": "slow", "pace": 0.85}, {"key": "fast", "pace": 0.95})
    assert pool_route.by_pace(pair) == [1, 0]
    # 连同 0.95（两阈值都过）与 0.80（两阈值都不过）一起看整段分带。
    group = seats_of(
        {"key": "p080", "pace": 0.80},
        {"key": "p085", "pace": 0.85},
        {"key": "p095", "pace": 0.95},
        {"key": "p100", "pace": 1.00},
    )
    # 带号：1.00 与 0.95 同带（带 0），0.85 与 0.80 同带（带 1）⇒ 靠后的两个先被提上来。
    assert pool_route.by_pace(group) == [2, 3, 0, 1]


def test_by_pace_none_is_unknown_not_zero() -> None:
    """`pace is None`（不知道）与 `pace = 0.0`（一点都不剩）排位必须**不同**。

    ★ 池侧口径：`None` 排在「告诉过的人」之后（与 `_left_key` 里 `left is None` 同族），
      所以同一份列出序在两种取值下结果不同 —— 若把 `None` 当 0，两者就同档、退化成恒等。
    """
    unknown = seats_of({"key": "unknown", "pace": None}, {"key": "zero", "pace": 0.0})
    assert pool_route.by_pace(unknown) == [1, 0]  # 告诉过的（0.0）在前
    # 反过来的列出序：仍按「知情在前」⇒ 不是恒等。
    swapped = seats_of({"key": "zero", "pace": 0.0}, {"key": "unknown", "pace": None})
    assert pool_route.by_pace(swapped) == [0, 1]
    # `None` 不许被当成 0 参与分带：一个 None + 一个 0 与一个 0.5 的三人序里，
    # None 必须落在最后（若当 0 就会与 0.0 同带、保列出序）。
    trio = seats_of({"key": "half", "pace": 0.5}, {"key": "unknown", "pace": None},
                    {"key": "zero", "pace": 0.0})
    assert pool_route.by_pace(trio) == [0, 2, 1]


# ---------------------------------------------------------------- 8-10. round_pick

def test_round_pick_three_and_one_go_a_a_b_a() -> None:
    """平滑加权轮转：`weights=(3,1)` 连续四次是 `0,0,1,0`（原件注释 `3 and 1 go a, a, b, a…`）。

    减 `total` 那一步是「平滑」的全部机制：少了它 `cur` 单调增长，四次会变成 `0,0,0,0`。
    断言的是**序列**而不是「第 0 位是 0」—— 单调增长跑不掉。
    """
    state: dict[str, dict[str, int]] = {}
    picks = [
        pool_route.round_pick("p", ("a", "b"), (3, 1), (False, False), state=state)
        for _ in range(4)
    ]
    assert picks == [0, 0, 1, 0]


def test_round_pick_all_resting_returns_minus_one() -> None:
    """全部 `rests=True` ⇒ `-1`（没有可挑的；原件 `if best < 0 { return -1 }`）。"""
    state: dict[str, dict[str, int]] = {}
    assert pool_route.round_pick("p", ("a", "b"), (1, 1), (True, True), state=state) == -1
    # 空 keys 同样是「没有可挑的」。
    assert pool_route.round_pick("p", (), (), (), state=state) == -1
    # 有一个没 resting ⇒ 只挑它，`resting` 的权重不计入 total。
    assert pool_route.round_pick("p", ("a", "b"), (5, 1), (True, False), state=state) == 1


def test_round_pick_forgets_keys_no_longer_listed() -> None:
    """`keys` 换一批之后旧 key 的 `cur` 必须被清掉（原件 `delete(r.cur, k)`）。

    不清就会让「新 key 继承同位置上一个 key 的欠账」—— 一个刚上线的号会白等好几轮。
    """
    state: dict[str, dict[str, int]] = {}
    assert pool_route.round_pick("p", ("a", "b"), (1, 1), (False, False), state=state) == 0
    assert state["p"]["a"] == -1  # a 被收了 2 的账（total = 1+1）
    # b 赢了这一轮：b 的 cur 已经是 0；再换一批 keys。
    got = pool_route.round_pick("p", ("c", "b"), (1, 1), (False, False), state=state)
    assert "a" not in state["p"]  # 旧 key 的欠账被清掉
    assert state["p"] == {"b": 0, "c": 1}  # c 从 0 起算（+1 之后是 1），没继承 a 的 -1
    assert got == 1


# ---------------------------------------------------------------- 11. weighted

def test_weighted_hoists_winner_and_keeps_the_rest_listed() -> None:
    """`weighted` = `first(round_pick(...))`：赢家提到第 0 位，其余**保列出序**。

    ★ 不是旋转：三个号、赢家是 1 时结果是 `[1,0,2]`，不是 `[1,2,0]`。
    """
    rounds: dict[str, dict[str, int]] = {}
    three = plain(3)
    assert pool_route.weighted(three, pool="p", rounds=rounds) == [0, 1, 2]
    # 第二轮：等价加权，赢家轮到 1 ⇒ 提到第 0 位，其余（0 与 2）保列出序。
    assert pool_route.weighted(three, pool="p", rounds=rounds) == [1, 0, 2]
    # 直接对上共享件：结果第 0 位就是同一份状态下 `round_pick` 的赢家（去掉该轮作用后）。
    fresh: dict[str, dict[str, int]] = {}
    winner = pool_route.round_pick("q", ("x", "y", "z"), (1, 1, 1), (False, False, False),
                                   state=fresh)
    assert pool_route.weighted(seats_of({"key": "x"}, {"key": "y"}, {"key": "z"}),
                               pool="q", rounds={}) == pool_route.first(winner, 3)
    # `resting` 的号本轮不参与（它的份由别人按权重分掉）。
    resting = seats_of({"key": "a", "resting": True}, {"key": "b"})
    assert pool_route.weighted(resting, pool="r", rounds={}) == [1, 0]


# ---------------------------------------------------------------- 12. free_first

def test_free_first_only_sorts_one_tier() -> None:
    """只分两档：`free=True` 全在前，其余按列出序在后；**档内不再排序**。

    特别咬「不许把快用完的免费号推到付钱的后面」：免费号用完了也不花钱。
    """
    seats = seats_of(
        {"key": "paid-a", "used": 10.0},
        {"key": "free", "used": 99.0, "free": True},
        {"key": "paid-b", "used": 0.0},
    )
    assert pool_route.free_first(seats) == [1, 0, 2]
    # 两个免费号：保列出序（不是按 used 排）。
    two_free = seats_of({"key": "f-spent", "used": 100.0, "free": True},
                        {"key": "f-fresh", "used": 0.0, "free": True})
    assert pool_route.free_first(two_free) == [0, 1]
    # 没有免费的 ⇒ 恒等（本路由在无免费模型的池上等于 `order`）。
    assert pool_route.free_first(plain(3)) == [0, 1, 2]


# ---------------------------------------------------------------- 13-14. estimate

def test_estimate_falls_back_to_first_token_alone() -> None:
    """`tps <= 0` ⇒ 用 `mid`；`mid` 也是 0 ⇒ **只算首字节**（不是 0）。"""
    assert pool_route.estimate(120.0, 0.0, 0.0) == 120.0
    # tps 负数同样是「没量过」。
    assert pool_route.estimate(120.0, -5.0, 0.0) == 120.0


def test_estimate_uses_ref_tokens_and_mid_pace() -> None:
    """有速度 ⇒ `ttft + REF_TOKENS*1000/tps`；没报速度 ⇒ 用同组中位速度替。"""
    assert pool_route.estimate(100.0, 0.0, 200.0) == 1100.0  # 100 + 200*1000/200
    assert pool_route.estimate(100.0, 200.0, 0.0) == 1100.0  # 自己的速度优先于 mid
    assert pool_route.estimate(0.0, 0.0, 200.0) == 1000.0  # 首字节 0 也算


# ---------------------------------------------------------------- 15-16. fastest

def test_fastest_puts_resting_and_spent_behind_awake() -> None:
    """四堆顺序是 `awake + resting + spent`，`awake = fast + unmeasured`。

    分堆优先级（原件 `fastest.go:59-77` 的 `switch`）：`resting` > `tier==2` > `ttft>0` > 没量过。
    """
    seats = seats_of(
        {"key": "resting", "resting": True},
        {"key": "unmeasured"},
        {"key": "fast", "ttft": 80.0, "tps": 50.0},
        {"key": "spent", "used": 99.0, "ttft": 10.0, "tps": 100.0},
    )
    assert pool_route.fastest(seats, pool="p", probes={}) == [2, 1, 0, 3]
    # 量过的两人：`estimate` 小的在前（不求速度时用 mid，两人都有 tps ⇒ 各按自己算）。
    two = seats_of({"key": "slow", "ttft": 100.0, "tps": 10.0},
                   {"key": "quick", "ttft": 100.0, "tps": 200.0})
    assert pool_route.fastest(two, pool="p", probes={}) == [1, 0]


def test_fastest_probe_gives_the_unmeasured_a_turn_every_five() -> None:
    """`fast` 与 `unmeasured` 都非空时，每 `PROBE_EVERY` 次把没量过的下一个提到最前。

    ★ **这个 5 来自 `ProbeEvery = 5`，不许改**：这里连调 5 次正好撞上阈值；
      改成调 6 次这条钉子就再也咬不住「先归零再判断」那种改坏法（第 5 次不提前、
      第 6 次才提），整条判据会退化成假牙。要改阈值就同步改这里的次数与设计原件。
    """
    seats = seats_of(
        {"key": "fast", "ttft": 90.0, "tps": 40.0},
        {"key": "cold-a"},
        {"key": "cold-b"},
    )
    probes: dict[str, dict[str, int]] = {}
    seen = [pool_route.fastest(seats, pool="p", probes=probes) for _ in range(5)]
    assert seen[:4] == [[0, 1, 2]] * 4  # 前四次：量过的在前，没量过的按列出序
    assert seen[4] == [1, 0, 2]  # 第 5 次：没量过的第一个被提到位置 0
    assert probes["p"] == {"n": 0, "turns": 1}  # 计数归零、轮次 +1
    # 再数 5 次 ⇒ 轮到下一个没量过的（探测轮次在它们之间轮，不给同一个号第二次机会）。
    for _ in range(4):
        pool_route.fastest(seats, pool="p", probes=probes)
    assert pool_route.fastest(seats, pool="p", probes=probes) == [2, 0, 1]
    # 只有一类非空时不探测（没人可比，别白转轮次）。
    only_fast = seats_of({"key": "fast", "ttft": 90.0})
    again: dict[str, dict[str, int]] = {}
    for _ in range(5):
        pool_route.fastest(only_fast, pool="p", probes=again)
    assert again == {}


# ---------------------------------------------------------------- 17-19. apply_strategy

def test_apply_strategy_unknown_name_falls_open() -> None:
    """名字不在 `BUILTIN` ⇒ 返回恒等且**不抛**（原件 `routes.Find` 的 `ok=false`）。"""
    two = plain(2)
    assert pool_route.apply_strategy("nope", two, pool="p") == [0, 1]
    assert pool_route.apply_strategy("", two, pool="p") == [0, 1]
    assert pool_route.apply_strategy("nope", [], pool="p") == []


def test_apply_strategy_rejects_non_permutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """策略返回非置换（`[0,0]`）⇒ 退回恒等且没抛（原件 `Apply` 的长度/重复检查）。"""
    monkeypatch.setattr(pool_route, "ordered", lambda _seats: [0, 0])
    assert pool_route.apply_strategy(pool_route.ORDERED, plain(2), pool="p") == [0, 1]


def test_apply_strategy_rejects_out_of_range_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """策略返回越界下标（`[0,5]`，n=2）⇒ 退回恒等且没抛。"""
    monkeypatch.setattr(pool_route, "least_used", lambda _seats: [0, 5])
    assert pool_route.apply_strategy(pool_route.LEAST_USED, plain(2), pool="p") == [0, 1]
    # 长度不符也退（`[0]` 对 2 个号）。
    monkeypatch.setattr(pool_route, "least_used", lambda _seats: [0])
    assert pool_route.apply_strategy(pool_route.LEAST_USED, plain(2), pool="p") == [0, 1]
    # 策略自己抛 ⇒ 同样退恒等（原件 `defer recover()` 那一条）。
    def boom(_seats: object) -> list[int]:
        raise RuntimeError("策略炸了")

    monkeypatch.setattr(pool_route, "least_used", boom)
    assert pool_route.apply_strategy(pool_route.LEAST_USED, plain(2), pool="p") == [0, 1]


# ---------------------------------------------------------------- 20. 全局网

@pytest.mark.parametrize(
    "name",
    [
        pool_route.ORDERED,
        pool_route.ROTATE,
        pool_route.LEAST_USED,
        pool_route.PACE,
        pool_route.WEIGHTED,
        pool_route.FREE_FIRST,
        pool_route.FASTEST,
    ],
)
def test_every_strategy_returns_a_permutation_of_its_input(name: str) -> None:
    """七个策略在**极端取值**的座位序列上都必须回一个真排列（`sorted(result) == range(n)`）。

    这是全局网：任何策略写错（漏人、重复、越界）都兜得住。
    座位里同时放 `pace=None`、`0`、极大值、全 resting、用尽、没量过 —— 每条分叉都过一遍。
    """
    tricky = seats_of(
        {"key": "a", "used": 0.0, "pace": None, "tokens": 1e18, "ttft": 0.0},
        {"key": "b", "used": 100.0, "pace": 0.0, "tokens": 0.0, "ttft": 1e9, "tps": 0.0},
        {"key": "c", "used": 98.0, "pace": 1e9, "tokens": 5.0, "weight": 0, "free": True},
        {"key": "d", "used": 90.0, "pace": 0.5, "resting": True, "learns": True},
        {"key": "e", "used": 89.9, "pace": 1.0, "left": 0.0, "left_in": "usd",
         "credits": True, "ttft": 12.0, "tps": 3.0, "weight": 9},
    )
    state: dict[str, object] = {}
    got = pool_route.apply_strategy(name, tricky, pool="p", state=state)
    assert sorted(got) == list(range(len(tricky)))
    # 空池对每个策略都得回 []（不是抛、也不是 [0]）。
    assert pool_route.apply_strategy(name, [], pool="p", state=state) == []
