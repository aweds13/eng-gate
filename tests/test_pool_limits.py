r"""卡 A338 · T-AG540：限额要在**派活之前**拦 —— 钉子。

**为什么值当测**：pool 今天没有「钱包」这一层 —— `gates/diag/wb-usage.jsonl` 只数 token、
没有账号维、没有金额，于是「这个号这个月还剩多少」仓里没人能回答。卡 A338 补上三件事：
策略的读法与窗口（`limits_policy`）、按账号累计的账（`ledger_spend`）、派活前的判
（`limits_check`）。这三件事**都只在边界上错**：差一个 token、差一周、差一个 0.0001
都不会有人在巡检里看出来，所以每条判据都要一根钉子。

★ 本文件钉的 N 件事
  判据 1（形状与常量）      `pin_01` `pin_02`
  判据 2（窗口逐字对应）    `pin_03` `pin_04` `pin_05`
  判据 3（文案从常量拼）    `pin_06`
  判据 4（舍入 + 零值不算限额）`pin_07` `pin_08`
  判据 5（账：追加/求和/忘账）`pin_09` `pin_10` `pin_11` `pin_12`
  判据 6（判：放行/每条余量/在飞/续期）`pin_13` `pin_14` `pin_15` `pin_16`
  判据 7（边界是 `>=` 不是 `>`）`pin_17`
  判据 8（零值方向：读不出回 `{}`/坏数据必抛）`pin_18` `pin_19` `pin_20` `pin_21`
  ★ 反向钉子（每条都指向一种「改一个字符就悄悄松掉」的变异）
      `rev_01` `pin_17` 的 `>=` ⇒ `>`        `rev_02` `sums` 的 `cache_reads` 默认
      `rev_03` `window` 的 `week` 起点         `rev_04` `MAX_LIMITS` 放开
      `rev_05` 坏文件回 `{}` 不抛            `rev_06` `Retry-After` 的 `max(…, 1)`

不靠真实钟表：`NOW` 是写死的 `2026-10-12T23:28:00+08:00`（周一），所有窗口都从它推。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts  # noqa: E402
from pool import ledger_spend, limits_check, limits_policy  # noqa: E402

#: 周一 23:28（+08:00）：跨日、跨周、跨月三条边界都在它附近，最适合钉窗口。
NOW = datetime.fromisoformat("2026-10-12T23:28:00+08:00")
#: 周中（周三）：**只有**从周一起算才会落在 10-12；从周日起算会掉到 10-11。
WEDNESDAY = datetime.fromisoformat("2026-10-14T09:00:00+08:00")


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ============================================================ 判据 1：形状与常量


def test_pin_01_constants_and_dataclass_shape() -> None:
    assert limits_policy.MAX_LIMITS == 5
    assert limits_policy.MAX_DAYS == 3650
    assert limits_policy.MAX_HOURS == 8760
    assert limits_policy.PERIODS == ("day", "week", "month", "days", "hours")
    assert limits_policy.COST_ROUND == 4
    assert issubclass(limits_policy.LimitError, ValueError)
    bare = limits_policy.Limit()
    assert (bare.period, bare.days, bare.hours, bare.tokens) == ("day", 0, 0, 0)
    assert (bare.cost, bare.cache_reads, bare.since) == (0.0, False, None)
    # frozen=True：改不动；slots=True：没有 __dict__（省内存，也防止偷偷加字段）
    with pytest.raises(AttributeError):
        bare.tokens = 1
    assert not hasattr(bare, "__dict__")


def test_pin_02_limited_is_tokens_or_cost_only() -> None:
    assert limits_policy.Limit().limited() is False
    assert limits_policy.Limit(tokens=1).limited() is True
    assert limits_policy.Limit(cost=0.0001).limited() is True
    # 只有 days/hours 而没有 tokens/cost 的条目**不算限额**（没有量可花）
    assert limits_policy.Limit(period="days", days=3).limited() is False


# ============================================================ 判据 2：窗口


def test_pin_03_tz_comes_from_pool_accounts() -> None:
    # 判据 2：一律用 tools/pool_accounts.TZ，不许新造时区 ⇒ 必须是**同一个对象**
    assert limits_policy.TZ is pool_accounts.TZ
    assert ledger_spend.TZ is pool_accounts.TZ
    start, reset = limits_policy.window(limits_policy.Limit(period="day"), NOW)
    assert start.tzinfo is pool_accounts.TZ
    assert reset.tzinfo is pool_accounts.TZ


def test_pin_04_window_week_starts_monday_and_month_on_the_first() -> None:
    week = limits_policy.Limit(period="week")
    start, reset = limits_policy.window(week, WEDNESDAY)
    assert start == _at("2026-10-12T00:00:00+08:00")
    assert reset == _at("2026-10-19T00:00:00+08:00")
    assert start.isoweekday() == 1
    # 周一当天不许回退到上周
    same, _ = limits_policy.window(week, _at("2026-10-12T00:00:00+08:00"))
    assert same == start
    month = limits_policy.Limit(period="month")
    m_start, m_reset = limits_policy.window(month, NOW)
    assert m_start == _at("2026-10-01T00:00:00+08:00")
    assert m_reset == _at("2026-11-01T00:00:00+08:00")
    # 1 月 31 日：续期必须是 2 月 1 日（从 1 号起算，不从「现在 + 32 天」起算）
    jan, feb = limits_policy.window(month, _at("2026-01-31T12:00:00+08:00"))
    assert jan == _at("2026-01-01T00:00:00+08:00")
    assert feb == _at("2026-02-01T00:00:00+08:00")
    # 12 月要跨年
    dec, jan_next = limits_policy.window(month, _at("2026-12-31T23:59:59+08:00"))
    assert dec == _at("2026-12-01T00:00:00+08:00")
    assert jan_next == _at("2027-01-01T00:00:00+08:00")


def test_pin_05_window_day_and_rolling_days_hours() -> None:
    day_start, day_reset = limits_policy.window(limits_policy.Limit(period="day"), NOW)
    assert day_start == _at("2026-10-12T00:00:00+08:00")
    assert day_reset == _at("2026-10-13T00:00:00+08:00")
    ladder = limits_policy.Limit(period="days", days=1, since=_at("2026-10-01T08:00:00+08:00"))
    start, reset = limits_policy.window(ladder, NOW)
    assert start == _at("2026-10-12T08:00:00+08:00")
    assert reset == _at("2026-10-13T08:00:00+08:00")
    hourly = limits_policy.Limit(period="hours", hours=3, since=_at("2026-10-12T00:00:00+08:00"))
    h_start, h_reset = limits_policy.window(hourly, NOW)
    assert h_start == _at("2026-10-12T21:00:00+08:00")
    assert h_reset == _at("2026-10-13T00:00:00+08:00")
    # 还没到 since 时，窗口就是 since 那一窗（不许算出负的步数）
    early = limits_policy.Limit(period="days", days=2, since=_at("2026-10-20T08:00:00+08:00"))
    e_start, e_reset = limits_policy.window(early, NOW)
    assert e_start == _at("2026-10-20T08:00:00+08:00")
    assert e_reset == _at("2026-10-22T08:00:00+08:00")
    # period=days/hours 必须给 since：不给就等于每次重启重置窗口
    with pytest.raises(limits_policy.LimitError, match="since"):
        limits_policy.window(limits_policy.Limit(period="days", days=1), NOW)
    with pytest.raises(limits_policy.LimitError, match="since"):
        limits_policy.window(limits_policy.Limit(period="hours", hours=1), NOW)


# ============================================================ 判据 3：文案从常量拼


def test_pin_06_error_messages_build_numbers_from_constants() -> None:
    with pytest.raises(limits_policy.LimitError) as days:
        limits_policy.parse_limit({"days": limits_policy.MAX_DAYS + 1})
    assert str(limits_policy.MAX_DAYS) in str(days.value)
    assert "3650" in str(days.value)
    assert "1" in str(days.value)
    with pytest.raises(limits_policy.LimitError) as hours:
        limits_policy.parse_limit({"hours": limits_policy.MAX_HOURS + 1})
    assert str(limits_policy.MAX_HOURS) in str(hours.value)
    assert "8760" in str(hours.value)
    with pytest.raises(limits_policy.LimitError) as period:
        limits_policy.parse_limit({"period": "year"})
    for name in limits_policy.PERIODS:
        assert name in str(period.value)
    with pytest.raises(limits_policy.LimitError, match="不能为负"):
        limits_policy.parse_limit({"tokens": -1})
    with pytest.raises(limits_policy.LimitError, match="不能为负"):
        limits_policy.parse_limit({"cost": -0.01})
    with pytest.raises(limits_policy.LimitError, match="必须 1~"):
        limits_policy.parse_limit({"period": "days"})
    with pytest.raises(limits_policy.LimitError, match="必须 1~"):
        limits_policy.parse_limit({"period": "hours"})


# ============================================================ 判据 4：舍入与零值


def test_pin_07_cost_rounds_at_four_digits() -> None:
    assert limits_policy.parse_limit({"cost": 20.00005}).cost == 20.0001
    assert limits_policy.parse_limit({"cost": 0.00004}).cost == 0.0
    assert limits_policy.parse_limit({"cost": 1.00004}).cost == 1.0
    assert limits_policy.parse_limit({"cost": 3}).cost == 3.0


def test_pin_08_zero_value_limit_is_not_a_limit(tmp_path: Path) -> None:
    zero = limits_policy.parse_limit({"period": "month", "tokens": 0, "cost": 0.0})
    assert zero.limited() is False
    # 不限量的条目在判据面**不参与判**（有一百万 token 的花费也照样放行）
    assert limits_check.check([zero], spent={0: (10**9, 10.0)}, now=NOW).allowed is True
    # 读策略时被忽略；全篇零值的账号等于没声明 ⇒ 不进返回值
    path = tmp_path / "limits.toml"
    path.write_text(
        '[[acc1.limit]]\nperiod = "day"\ntokens = 10\n\n'
        '[[acc1.limit]]\nperiod = "month"\ntokens = 0\n\n'
        '[[acc2.limit]]\nperiod = "month"\ntokens = 0\ncost = 0.0\n',
        encoding="utf-8",
    )
    loaded = limits_policy.load_limits(path)
    assert sorted(loaded) == ["acc1"]
    assert len(loaded["acc1"]) == 1
    assert (loaded["acc1"][0].period, loaded["acc1"][0].tokens) == ("day", 10)


# ============================================================ 判据 5：账


def test_pin_09_append_never_overwrites(tmp_path: Path) -> None:
    first = ledger_spend.append(
        "acc1", "A1", "m", input_tokens=1, output_tokens=0, cache_read=0, cost=0.0,
        at=NOW, root=tmp_path,
    )
    second = ledger_spend.append(
        "acc1", "A2", "m", input_tokens=2, output_tokens=0, cache_read=0, cost=0.0,
        at=NOW, root=tmp_path,
    )
    assert first == second == tmp_path.joinpath(*ledger_spend.SPEND_REL)
    assert ledger_spend.SPEND_REL == ("gates", "diag", "pool-spend.jsonl")
    assert ledger_spend.audit(root=tmp_path) == {"lines": 2, "usable": 2, "damaged": 0}
    text = second.read_text(encoding="utf-8")
    assert '"card": "A1"' in text
    assert '"card": "A2"' in text


def test_pin_10_sums_is_half_open_and_cache_read_opt_in(tmp_path: Path) -> None:
    at = _at("2026-10-12T10:00:00+08:00")
    ledger_spend.append(
        "acc1", "A1", "m1", input_tokens=10, output_tokens=5, cache_read=100, cost=0.5,
        at=at, root=tmp_path,
    )
    ledger_spend.append(
        "acc1", "A1", "m1", input_tokens=1, output_tokens=0, cache_read=1000, cost=0.25,
        at=at + timedelta(hours=1), root=tmp_path,
    )
    ledger_spend.append(
        "acc2", "A2", "m1", input_tokens=7, output_tokens=0, cache_read=0, cost=1.0,
        at=at, root=tmp_path,
    )
    start = _at("2026-10-12T00:00:00+08:00")
    end = _at("2026-10-13T00:00:00+08:00")
    # tokens = input + output + cache_write；**默认不含 cache_read**
    assert ledger_spend.sums("acc1", start, end, root=tmp_path) == (16, 0.75, 2)
    assert ledger_spend.sums("acc1", start, end, cache_reads=True, root=tmp_path) == (1116, 0.75, 2)
    assert ledger_spend.sums("acc2", start, end, root=tmp_path) == (7, 1.0, 1)
    # 左闭右开：start 那一刻算，end 那一刻不算
    assert ledger_spend.sums("acc1", start, at, root=tmp_path) == (0, 0.0, 0)
    assert ledger_spend.sums("acc1", at, at + timedelta(hours=1), root=tmp_path) == (15, 0.5, 1)


def test_pin_11_damaged_lines_are_skipped_not_counted_as_zero(tmp_path: Path) -> None:
    path = ledger_spend.append(
        "acc1", "A1", "m", input_tokens=10, output_tokens=0, cache_read=0, cost=0.0,
        at=NOW, root=tmp_path,
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{not json\n")
        handle.write('{"at": "2026-10-12T23:00:00+08:00"}\n')
        handle.write('{"at": "nope", "account": "acc1", "input_tokens": 99}\n')
        handle.write(
            '{"at": "2026-10-12T23:00:00+08:00", "account": "acc1", "input_tokens": "99"}\n'
        )
    start = NOW - timedelta(hours=1)
    end = NOW + timedelta(hours=1)
    # 坏行**跳过**：不许当 0 混进来（当 0 就是把说不清的账算成没花钱）
    assert ledger_spend.sums("acc1", start, end, root=tmp_path) == (10, 0.0, 1)
    assert ledger_spend.audit(root=tmp_path) == {"lines": 5, "usable": 1, "damaged": 4}


def test_pin_12_forget_archives_and_leaves_other_accounts_alone(tmp_path: Path) -> None:
    old = NOW - timedelta(days=40)
    ledger_spend.append(
        "acc1", "A1", "m", input_tokens=1, output_tokens=0, cache_read=0, cost=0.0,
        at=old, root=tmp_path,
    )
    ledger_spend.append(
        "acc1", "A2", "m", input_tokens=2, output_tokens=0, cache_read=0, cost=0.0,
        at=NOW, root=tmp_path,
    )
    ledger_spend.append(
        "acc2", "A3", "m", input_tokens=4, output_tokens=0, cache_read=0, cost=0.0,
        at=old, root=tmp_path,
    )
    assert ledger_spend.forget("acc1", NOW - timedelta(days=1), root=tmp_path) == 1
    assert ledger_spend.audit(root=tmp_path)["lines"] == 2
    wide = (old - timedelta(days=1), NOW + timedelta(days=1))
    assert ledger_spend.sums("acc1", *wide, root=tmp_path) == (2, 0.0, 1)
    assert ledger_spend.sums("acc2", *wide, root=tmp_path) == (4, 0.0, 1)
    archives = sorted(tmp_path.joinpath("gates", "diag").glob("*.forgotten-*.jsonl"))
    assert len(archives) == 1
    assert '"card": "A1"' in archives[0].read_text(encoding="utf-8")
    # 没有更早的行 ⇒ 0（不许凭空造一份空存档）
    assert ledger_spend.forget("acc1", old - timedelta(days=1), root=tmp_path) == 0


# ============================================================ 判据 6/7：判


def test_pin_13_empty_limits_always_let_through() -> None:
    verdict = limits_check.check([], spent={}, now=NOW)
    assert verdict.allowed is True
    assert verdict.binding is None
    assert verdict.reset_at is None
    assert verdict.retry_after_s == 0


def test_pin_14_every_limit_must_have_room() -> None:
    loose = limits_policy.Limit(period="day", tokens=1000)
    tight = limits_policy.Limit(period="month", tokens=10)
    verdict = limits_check.check([loose, tight], spent={0: (1, 0.0), 1: (10, 0.0)}, now=NOW)
    assert verdict.allowed is False
    # 卡在紧的那条，不是「最宽的那条够就放」
    assert verdict.binding == 1
    assert "第 1 条" in verdict.why
    assert verdict.reset_at == _at("2026-11-01T00:00:00+08:00")
    under = limits_check.check([loose, tight], spent={0: (1, 0.0), 1: (9, 0.0)}, now=NOW)
    assert under.allowed is True
    assert under.binding is None


def test_pin_15_inflight_is_reserved_before_dispatch() -> None:
    limit = limits_policy.Limit(period="day", tokens=100)
    assert limits_check.check(
        [limit], spent={0: (70, 0.0)}, now=NOW, inflight_tokens=30
    ).allowed is False
    assert limits_check.check(
        [limit], spent={0: (70, 0.0)}, now=NOW, inflight_tokens=29
    ).allowed is True
    cash = limits_policy.Limit(period="day", cost=1.5)
    assert limits_check.check(
        [cash], spent={0: (0, 1.0)}, now=NOW, inflight_cost=0.5
    ).allowed is False
    assert limits_check.check(
        [cash], spent={0: (0, 1.0)}, now=NOW, inflight_cost=0.49
    ).allowed is True


def test_pin_16_binding_prefers_latest_reset_then_biggest_share() -> None:
    short = limits_policy.Limit(period="day", tokens=10)
    long = limits_policy.Limit(period="month", tokens=10)
    verdict = limits_check.check([short, long], spent={0: (10, 0.0), 1: (10, 0.0)}, now=NOW)
    assert verdict.binding == 1
    assert verdict.reset_at == _at("2026-11-01T00:00:00+08:00")
    # 同一续期时刻 ⇒ 挑 share()（用量/上限）更大的那条
    first = limits_policy.Limit(period="day", tokens=100)
    second = limits_policy.Limit(period="day", tokens=100)
    both = limits_check.check([first, second], spent={0: (100, 0.0), 1: (180, 0.0)}, now=NOW)
    assert both.binding == 1
    assert "share=1.800" in both.why


def test_pin_17_boundary_is_ge_not_gt() -> None:
    limit = limits_policy.Limit(period="day", tokens=100)
    verdict = limits_check.check([limit], spent={0: (100, 0.0)}, now=NOW)
    # 差一个 token 就放行是只在边界出现、人工测不出来的偏差 ⇒ 用 >=
    assert verdict.allowed is False
    assert verdict.binding == 0
    assert "100+0 >= 100" in verdict.why
    assert limits_check.check([limit], spent={0: (99, 0.0)}, now=NOW).allowed is True
    cash = limits_policy.Limit(period="month", cost=2.0)
    assert limits_check.check([cash], spent={0: (0, 2.0)}, now=NOW).allowed is False


# ============================================================ 判据 8：零值方向


def test_pin_18_missing_strategy_file_is_empty_not_infinite(tmp_path: Path) -> None:
    assert limits_policy.load_limits(tmp_path / "nope.toml") == {}
    # 空文件 = 没设限额（今天的行为），不是「无限」也不是抛
    empty = tmp_path / "limits.toml"
    empty.write_text("", encoding="utf-8")
    assert limits_policy.load_limits(empty) == {}


def test_pin_19_bad_data_raises_instead_of_being_skipped(tmp_path: Path) -> None:
    path = tmp_path / "limits.toml"
    path.write_text('this is not toml =\n', encoding="utf-8")
    with pytest.raises(limits_policy.LimitError, match="TOML"):
        limits_policy.load_limits(path)
    # 一条坏的连带整份：**不许跳过坏条目继续用剩下的**（跳一条 = 悄悄松开判据）
    path.write_text(
        '[[acc1.limit]]\nperiod = "day"\ntokens = 10\n\n'
        '[[acc2.limit]]\nperiod = "hours"\nhours = 8761\n',
        encoding="utf-8",
    )
    with pytest.raises(limits_policy.LimitError) as excinfo:
        limits_policy.load_limits(path)
    assert str(limits_policy.MAX_HOURS) in str(excinfo.value)
    path.write_text(
        '[[acc1.limit]]\nperiod = "year"\ntokens = 10\n',
        encoding="utf-8",
    )
    with pytest.raises(limits_policy.LimitError, match="period"):
        limits_policy.load_limits(path)
    path.write_text(
        '[[acc1.limit]]\nperiod = "day"\ntokens = 10\nbogus = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(limits_policy.LimitError, match="bogus"):
        limits_policy.load_limits(path)


def test_pin_20_inline_limits_section_is_read_too(tmp_path: Path) -> None:
    path = tmp_path / "limits.toml"
    path.write_text(
        '[acc9]\nlimit = [{ period = "hours", hours = 2, tokens = 5 }]\n',
        encoding="utf-8",
    )
    loaded = limits_policy.load_limits(path)
    assert (loaded["acc9"][0].period, loaded["acc9"][0].hours) == ("hours", 2)
    assert loaded["acc9"][0].tokens == 5


def test_pin_21_sixth_limit_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "limits.toml"
    rows = "".join(
        f'[[acc1.limit]]\nperiod = "day"\ntokens = {index + 1}\n\n'
        for index in range(limits_policy.MAX_LIMITS)
    )
    path.write_text(rows, encoding="utf-8")
    assert len(limits_policy.load_limits(path)["acc1"]) == limits_policy.MAX_LIMITS
    path.write_text(rows + '[[acc1.limit]]\nperiod = "day"\ntokens = 99\n', encoding="utf-8")
    with pytest.raises(limits_policy.LimitError) as excinfo:
        limits_policy.load_limits(path)
    assert str(limits_policy.MAX_LIMITS) in str(excinfo.value)
    assert "5" in str(excinfo.value)


# ============================================================ ★ 反向钉子


def test_rev_01_token_exactly_used_up_is_refused() -> None:
    """变异 `used + inflight >= limit` ⇒ `>` 时，这一条必须红。"""
    limit = limits_policy.Limit(period="day", tokens=100)
    assert limits_check.check([limit], spent={0: (100, 0.0)}, now=NOW).allowed is False
    assert limits_check.check([limit], spent={0: (101, 0.0)}, now=NOW).allowed is False


def test_rev_02_cache_read_is_not_wallet_spend_by_default(tmp_path: Path) -> None:
    """变异 `sums(…, cache_reads=False)` 默认改 True 时，这一条必须红（行为，不靠读签名）。

    口径来自 `internal/budget/budget.go:69-75`：默认 `tokens = input + output + cache_write`，
    `cache_read` 要 `cache_reads=True` 才加。默认算进去 = 把「命中缓存的便宜量」
    按全价计进钱包，派活会被莫名拒掉。
    """
    ledger_spend.append(
        "acc1", "A1", "m", input_tokens=10, output_tokens=5, cache_read=100, cost=0.0,
        at=NOW, root=tmp_path,
    )
    window = (NOW - timedelta(hours=1), NOW + timedelta(hours=1))
    assert ledger_spend.sums("acc1", *window, root=tmp_path)[0] == 15
    assert ledger_spend.sums("acc1", *window, cache_reads=True, root=tmp_path)[0] == 115


def test_rev_03_week_never_starts_on_sunday() -> None:
    """变异 `week` 起点改周日（`days=isoweekday()`）时，这一条必须红。"""
    start, _ = limits_policy.window(limits_policy.Limit(period="week"), WEDNESDAY)
    assert start.isoweekday() == 1
    assert start.date().isoformat() == "2026-10-12"
    # 周日当天：窗口还是**本**周一开的那个（不是当天）
    sunday, reset = limits_policy.window(
        limits_policy.Limit(period="week"), _at("2026-10-18T12:00:00+08:00")
    )
    assert sunday == _at("2026-10-12T00:00:00+08:00")
    assert reset == _at("2026-10-19T00:00:00+08:00")


def test_rev_04_max_limits_is_not_advisory(tmp_path: Path) -> None:
    """变异 `MAX_LIMITS` 放开放成 500 时，这一条必须红。"""
    assert limits_policy.MAX_LIMITS == 5
    path = tmp_path / "limits.toml"
    path.write_text(
        "".join(
            f'[[acc1.limit]]\nperiod = "day"\ntokens = {index + 1}\n\n' for index in range(6)
        ),
        encoding="utf-8",
    )
    with pytest.raises(limits_policy.LimitError, match="5"):
        limits_policy.load_limits(path)


def test_rev_05_unreadable_file_is_never_silently_empty(tmp_path: Path) -> None:
    """变异「坏文件回 `{}` 而不是抛」时，这一条必须红。"""
    path = tmp_path / "limits.toml"
    path.write_text('[[acc1.limit]]\nperiod = "day"\ntokens = 10\n', encoding="utf-8")
    assert limits_policy.load_limits(path) != {}
    path.write_text("garbage =\n", encoding="utf-8")
    with pytest.raises(limits_policy.LimitError):
        limits_policy.load_limits(path)


def test_rev_06_retry_after_is_never_below_one_second() -> None:
    """变异「去掉 `max(…, 1)`」时，这一条必须红（负秒数会让调用方立刻重试）。"""
    assert limits_check.retry_after(NOW - timedelta(hours=5), NOW) == 1
    assert limits_check.retry_after(NOW, NOW) == 1
    assert limits_check.retry_after(NOW + timedelta(seconds=7, microseconds=400_000), NOW) == 8
    verdict = limits_check.check(
        [limits_policy.Limit(period="day", tokens=1)], spent={0: (1, 0.0)}, now=NOW
    )
    assert verdict.retry_after_s == 1920
