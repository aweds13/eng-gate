"""卡 A329 · F16 Smart routing：`tools/pool/route.py` 的判据 + `plan.ordered()` 的接线。

每条用例都打在**真判据**上（不是"函数能跑"）：

- `smart_order` 的四层键（soon 逐窗口截到小时 / 空 soon 排后 / lapse 截时比 / left 大在前）；
- 三档分桶（tier 0 全前、tier 1 按 used 升序、tier 2 最后）与 `resting` 沉底；
- `tier()` 越界抛错**不 clamp**；
- `apply_order()` 的 fail-open（非排列 ⇒ 回恒等，不抛）；
- `reset_for()` 跨卡取 `recorded_at` **最新**那条、无记录/坏 JSON ⇒ 未知而**不是 0 秒**；
- `plan.ordered()` 在**一条额度记录都没有**时逐项等于输入顺序（这是"既有排批断言不变"的证明）。

额度状态文件一律写在 `tmp_path` 里（`pool_quota._state_path`），**不碰仓库真 `gates/diag/`**。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_quota  # noqa: E402
from pool import model_registry as pool_model_registry  # noqa: E402
from pool import plan as pool_plan  # noqa: E402
from pool import route as pool_route  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 10, 12, 23, 28, tzinfo=TZ)
T = dt.datetime(2026, 10, 13, 0, 0, tzinfo=TZ)  # 基准时刻：下面全部用 T + nh

# 池默认模型（`Card` 没有 model 字段 ⇒ `ordered()` 只能按池默认排；真注册表里就是它）。
DEFAULT_MODEL = pool_model_registry.default_model_for(pool_model_registry.DEFAULT_POOL).alias


# ---------------------------------------------------------------- 小工具


def _card(cid: str, *, title: str = "样卡", files: tuple[str, ...] = ("a.py",),
          tree: str = "") -> pool_plan.Card:
    return pool_plan.Card(id=cid, task="T-AG531", title=title, tree=tree, spec="", files=files)


def _write_state(root: Path, cards: dict[str, dict[str, dict[str, object]]]) -> Path:
    """按 `pool_quota` 的键形状（卡 → 模型 → 记录）落一份状态文件。"""
    path = pool_quota._state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cards": cards}, ensure_ascii=False), encoding="utf-8")
    return path


def _record(reset_at: str | None, recorded_at: str) -> dict[str, object]:
    return {"reset_at": reset_at, "recorded_at": recorded_at, "kind": "限流"}


# ---------------------------------------------------------------- tier()


def test_tier_matches_magpie_thresholds() -> None:
    """照 magpie `strategies.go:14-29`：≥98 用尽、≥90 快用完、其余有空间（边界都含）。"""
    assert pool_route.USED_SHARE == 98.0
    assert pool_route.LOW_SHARE == 90.0
    assert pool_route.tier(0.0) == 0
    assert pool_route.tier(89.9) == 0
    assert pool_route.tier(90.0) == 1
    assert pool_route.tier(97.9) == 1
    assert pool_route.tier(98.0) == 2
    assert pool_route.tier(100.0) == 2


@pytest.mark.parametrize("share", [-1, -0.1, 101, 100.1])
def test_tier_rejects_out_of_range(share: float) -> None:
    """越界**抛错不 clamp** —— clamp 会把"形状变了"洗成"差一点就满"。"""
    with pytest.raises(pool_route.RouteError):
        pool_route.tier(share)


def test_tier_rejects_nan_and_bool() -> None:
    """NaN / bool 不是"0%"：不知道就把 `known` 置 False，别拿 NaN 冒充数字。"""
    with pytest.raises(pool_route.RouteError):
        pool_route.tier(float("nan"))
    with pytest.raises(pool_route.RouteError):
        pool_route.tier(True)  # bool 是 int 的子类，但"真值"不是"0%" —— 必须炸


# ---------------------------------------------------------------- smart_order()


def test_smart_order_prefers_earliest_reset() -> None:
    """soon 最早的号排最前（T+1h < T+2h < T+3h ⇒ [1, 2, 0]）。"""
    seats = [
        pool_route.Seat(key="a", used=10.0, soon=(T + dt.timedelta(hours=3),)),
        pool_route.Seat(key="b", used=10.0, soon=(T + dt.timedelta(hours=1),)),
        pool_route.Seat(key="c", used=10.0, soon=(T + dt.timedelta(hours=2),)),
    ]
    assert pool_route.smart_order(seats) == [1, 2, 0]


def test_smart_order_truncates_to_the_hour() -> None:
    """`T+1h00m` 与 `T+1h59m` 截到小时后相等 ⇒ **同序**（不因为分钟差重排）。

    ★ 故意把**晚的**放 index 0：不截时它会被排到后面（`[1, 0]`），截到小时后两者相等、
      稳定排序保原序（`[0, 1]`）—— 这样这条用例才真的咬在「截到小时」上。
    """
    early = T + dt.timedelta(hours=1)
    late = T + dt.timedelta(hours=1, minutes=59)
    assert early < late  # 不截时它们是可比的、会换序
    seats = [
        pool_route.Seat(key="late", used=10.0, soon=(late,)),
        pool_route.Seat(key="early", used=10.0, soon=(early,)),
    ]
    assert pool_route.smart_order(seats) == [0, 1]


def test_smart_order_unknown_reset_goes_last() -> None:
    """空 `soon` = 不知道什么时候回来 ⇒ 排在有 `soon` 的**之后**，不排最前、不当 0。"""
    seats = [
        pool_route.Seat(key="unknown", known=False, used=10.0, soon=()),
        pool_route.Seat(key="known", used=10.0, soon=(T + dt.timedelta(hours=9),)),
    ]
    assert pool_route.smart_order(seats) == [1, 0]


def test_smart_order_tier_two_never_before_fine() -> None:
    """`used=99`（tier 2）即使 soon 最早，也只能排在**所有** tier 0 之后。"""
    seats = [
        pool_route.Seat(key="spent", used=99.0, soon=(T + dt.timedelta(hours=1),)),
        pool_route.Seat(key="fine", used=50.0, soon=(T + dt.timedelta(hours=5),)),
    ]
    assert pool_route.smart_order(seats) == [1, 0]


def test_smart_order_tier_one_sits_between_fine_and_spent() -> None:
    """tier 1（快用完）在 tier 0 之后、tier 2 之前 —— 三桶顺序 fine + low + spent。"""
    seats = [
        pool_route.Seat(key="spent", used=99.0, soon=(T + dt.timedelta(hours=1),)),
        pool_route.Seat(key="low", used=95.0, soon=(T + dt.timedelta(hours=1),)),
        pool_route.Seat(key="fine", used=10.0, soon=(T + dt.timedelta(hours=9),)),
    ]
    assert pool_route.smart_order(seats) == [2, 1, 0]


def test_smart_order_resting_sinks_last() -> None:
    """`resting=True`（失败后正在休息）的号沉到最后，哪怕它 soon 最早、used 最低。"""
    seats = [
        pool_route.Seat(key="a", used=10.0, soon=(T + dt.timedelta(hours=2),)),
        pool_route.Seat(key="resting", used=1.0, soon=(T + dt.timedelta(hours=1),), resting=True),
        pool_route.Seat(key="c", used=10.0, soon=(T + dt.timedelta(hours=3),)),
    ]
    assert pool_route.smart_order(seats) == [0, 2, 1]


def test_smart_order_left_breaks_ties_after_reset() -> None:
    """soon / lapse 全相等时，`left` 大的在前；`left is None`（没说余额）排在说了的之后。"""
    seats = [
        pool_route.Seat(key="none", used=10.0, soon=(T + dt.timedelta(hours=1),), left=None),
        pool_route.Seat(key="small", used=10.0, soon=(T + dt.timedelta(hours=1),), left=5.0),
        pool_route.Seat(key="big", used=10.0, soon=(T + dt.timedelta(hours=1),), left=90.0),
    ]
    assert pool_route.smart_order(seats) == [2, 1, 0]


def test_smart_order_empty_is_empty() -> None:
    """空池 ⇒ `[]`，不抛（`max()` 不能被喂空序列）。"""
    assert pool_route.smart_order([]) == []


# ---------------------------------------------------------------- apply_order()


def test_smart_order_non_permutation_falls_open() -> None:
    """`apply_order` 是 magpie `Apply` 的 fail-open：非排列一律回恒等，**不抛**。"""
    assert pool_route.apply_order([2, 0, 1], 3) == [2, 0, 1]
    assert pool_route.apply_order([0, 1], 3) == [0, 1, 2]  # 长度不符
    assert pool_route.apply_order([0, 0, 1], 3) == [0, 1, 2]  # 重复
    assert pool_route.apply_order([0, 1, 3], 3) == [0, 1, 2]  # 越界
    assert pool_route.apply_order([-1, 0, 1], 3) == [0, 1, 2]  # 负数
    assert pool_route.apply_order([0, 1, 2], 0) == []


# ---------------------------------------------------------------- reset_for()


def test_reset_for_picks_latest_record_across_cards(tmp_path: Path) -> None:
    """跨**全部卡**读同一模型，取 `recorded_at` **最大**那条 —— 取 min / 取先见都会红。"""
    _write_state(
        tmp_path,
        {
            "201": {"m-x": _record("2026-10-12T21:00:00+08:00", "2026-10-12T20:00:00+08:00")},
            "202": {"m-x": _record("2026-10-12T23:30:00+08:00", "2026-10-12T22:00:00+08:00")},
        },
    )
    reset_at, recorded_at = pool_route.reset_for("m-x", now=NOW, root=tmp_path)
    assert recorded_at == "2026-10-12T22:00:00+08:00"
    assert reset_at == dt.datetime(2026, 10, 12, 23, 30, tzinfo=TZ)
    assert pool_route.model_until("m-x", now=NOW, root=tmp_path) == reset_at


def test_reset_for_absent_model_is_unknown_not_zero(tmp_path: Path, monkeypatch) -> None:
    """无记录 ⇒ `(None, "")`；且 `ordered()` 把"不知道"的卡排在**有记录之后**。"""
    assert pool_route.reset_for("没人记过这个模型", now=NOW, root=tmp_path) == (None, "")
    assert pool_route.seconds_left(None, now=NOW) is None  # 不当 0 秒

    _write_state(
        tmp_path,
        {"201": {DEFAULT_MODEL: _record("2026-10-13T06:00:00+08:00", "2026-10-12T22:00:00+08:00")}},
    )
    # `model_of()` 只认池默认（Card 没有 model 字段）⇒ 用 title 冒充模型名，把"已知/未知"分开。
    monkeypatch.setattr(pool_plan, "model_of", lambda card, **_kw: card.title)
    unknown = _card("unknown", title="没人记过这个模型")
    known = _card("known", title=DEFAULT_MODEL)
    assert [card.id for card in pool_plan.ordered([unknown, known], now=NOW, root=tmp_path)] == [
        "known",
        "unknown",
    ]


def test_reset_for_broken_file_is_unknown(tmp_path: Path) -> None:
    """坏 JSON / 缺文件 ⇒ 都当"不知道"，**不抛**（排序不能因为一个坏文件整轮停摆）。"""
    path = pool_quota._state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是 json", encoding="utf-8")
    assert pool_route.reset_for("m-x", now=NOW, root=tmp_path) == (None, "")
    missing = tmp_path / "空的树"
    assert pool_route.reset_for("m-x", now=NOW, root=missing) == (None, "")


def test_reset_for_uses_parse_reset_not_a_regex_of_its_own(tmp_path: Path) -> None:
    """`reset_at` 必须过 `pool_quota.parse_reset`（唯一真源）—— 它认的另一种写法也要能解开。"""
    raw = "2026-10-13 06:00:00 UTC+8"
    _write_state(tmp_path, {"201": {"m-x": _record(raw, "2026-10-12T22:00:00+08:00")}})
    parsed = pool_quota.parse_reset(raw)
    assert parsed is not None  # `parse_reset` 认得这种写法（route.py 不许自己写一份正则）
    assert pool_route.reset_for("m-x", now=NOW, root=tmp_path)[0] == parsed


# ---------------------------------------------------------------- ordered() / plan_batches()


def test_ordered_keeps_registration_order_when_nothing_known(tmp_path: Path) -> None:
    """一条额度记录都没有 ⇒ `ordered()` **逐项等于**输入顺序（既有排批断言靠这条）。"""
    cards = [_card("A272"), _card("A271"), _card("022"), _card("108")]
    got = pool_plan.ordered(cards, now=NOW, root=tmp_path)
    assert got == cards
    assert [card.id for card in got] == ["A272", "A271", "022", "108"]


def test_ordered_puts_unknown_after_known_and_soon_first(tmp_path: Path) -> None:
    """有记录时：剩余秒数小的在前（`now` 是钉死的时钟，不吃真实时间）。"""
    _write_state(
        tmp_path,
        {"201": {DEFAULT_MODEL: _record("2026-10-13T01:00:00+08:00", "2026-10-12T20:00:00+08:00")}},
    )
    cards = [_card("A272"), _card("A271")]
    got = pool_plan.ordered(cards, now=NOW, root=tmp_path)
    assert got == cards  # 同模型同剩余 ⇒ 稳定保原序


def test_plan_batches_keeps_registration_order_on_a_clean_tree(tmp_path: Path) -> None:
    """`plan_batches()` 在无额度记录的树上仍按登记序排批 —— 接线不改既有行为。

    ★ 两张卡各占一棵树（`.wt/A` / `.wt/B`）才可能同批：`greedy_pack` 的「树唯一」判据
      不许两卡同树（同一棵工作树只能有一个写者）。这条同时也钉住"三条判据一个字没动"。
    """
    cards = [_card("A", files=("a.py",), tree=".wt/A"), _card("B", files=("b.py",), tree=".wt/B")]
    backlog = pool_plan.Backlog(reviewed="abc1234", cards=tuple(cards))
    batches = pool_plan.plan_batches(backlog, 5, now=NOW, root=tmp_path)
    assert [[card.id for card in batch] for batch in batches] == [["A", "B"]]


def test_plan_batches_still_enforces_the_three_safety_rules(tmp_path: Path) -> None:
    """三条安全判据（limit / 树唯一 / 文件不相交）一个字没动。"""
    backlog = pool_plan.Backlog(
        reviewed="abc1234",
        cards=(
            _card("A", files=("same.py",), tree=".wt/A"),
            _card("B", files=("same.py",), tree=".wt/B"),  # 与 A 撞文件 ⇒ 不同批
            _card("C", files=("c.py",), tree=".wt/A"),  # 与 A 同树 ⇒ 也不同批
        ),
    )
    batches = pool_plan.plan_batches(backlog, 5, now=NOW, root=tmp_path)
    assert [[card.id for card in batch] for batch in batches] == [["A"], ["B", "C"]]
