"""G8 的用例 —— 假红率 / 漏检率 / 重跑率三字段分开报。

★ 反例钉子：`green_only_degenerate`（只报一个 `ok: true`）把漏检藏住 —— 正常产物三字段齐全。
"""

from __future__ import annotations

from framework.evidence import (
    Metrics,
    Rate,
    RunRecord,
    green_only_degenerate,
    metrics_complete,
    metrics_from_runs,
)
from framework.gates import Verdict


def test_g8_three_rates_computed():
    runs = [
        RunRecord("a", Verdict.FAIL.value, actual_ok=True, attempts=1),
        RunRecord("b", Verdict.PASS.value, actual_ok=False, attempts=1),
        RunRecord("c", Verdict.PASS.value, actual_ok=True, attempts=3),
        RunRecord("d", Verdict.FAIL.value, actual_ok=False, attempts=1),
    ]
    m = metrics_from_runs(runs)
    assert m.false_positive_rate == Rate(1, 2)
    assert m.false_negative_rate == Rate(1, 2)
    assert m.rerun_rate == Rate(1, 4)


def test_g8_to_dict_has_three_fields():
    d = Metrics(Rate(0, 5), Rate(0, 5), Rate(0, 5)).to_dict()
    assert set(d) == {"false_positive_rate", "false_negative_rate", "rerun_rate"}
    for v in d.values():
        assert set(v) == {"numerator", "denominator", "ratio"}


def test_g8_metrics_complete_green():
    assert metrics_complete(metrics_from_runs([RunRecord("a", Verdict.PASS.value, True, 1)])) == []


def test_g8_is_green_requires_data():
    assert Metrics(Rate(0, 0), Rate(0, 0), Rate(0, 0)).is_green() is False


def test_g8_is_green_when_all_zero_with_data():
    assert Metrics(Rate(0, 5), Rate(0, 5), Rate(0, 5)).is_green() is True


def test_g8_ratio_none_when_no_denominator():
    assert Rate(0, 0).ratio is None


def test_g8_degenerate_green_only_is_caught():
    """★ 反例钉子：`green_only_degenerate` 把三个数藏成一个 `ok` —— 漏检被藏住。

    依据 [2302.10594]：只报一个「精确率 99.2%」就把 76.2% 的漏检藏住了。
    """
    runs = [RunRecord("a", Verdict.PASS.value, actual_ok=False, attempts=1)]
    degenerate = green_only_degenerate(runs)
    assert set(degenerate) == {"ok"} and degenerate["ok"] is False
    full = metrics_from_runs(runs).to_dict()
    assert full["false_negative_rate"]["numerator"] == 1  # 漏检没被藏
