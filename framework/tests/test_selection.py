"""验证分层 F2/F3/F5/F6/F8/F10/F11 的用例 + 反例钉子（卡 185 / T-G285）。

★ 反例钉子（判据随件走）：故意造一个缺字段 / 跳整棵树 / 缺归因的产物 ⇒ 必须红。
依据见 `复盘/框架-验证分层的行业做法.md` §四。
"""

from __future__ import annotations

import pytest

from framework.selection import (
    ATTR_FLAKY,
    ATTR_RELATED,
    ATTR_UNRELATED_ENV,
    ATTR_UNKNOWN,
    BackstopReport,
    BUILD_KINDS,
    REGRESSION_TEST_WINDOW,
    SCHEDULED_BUILD,
    Selection,
    SelectionError,
    StateValidationError,
    TRIGGERED_STRICT_BUILD,
    Transition,
    backstop_capture,
    classify_failure,
    detect_transitions,
    lint_external_evidence,
    select_gates,
    validate_external_evidence,
    validate_state,
)


# -- F11 · 术语对齐 ---------------------------------------------------------
def test_f11_build_kinds_are_official_words():
    assert TRIGGERED_STRICT_BUILD in BUILD_KINDS
    assert SCHEDULED_BUILD in BUILD_KINDS
    assert REGRESSION_TEST_WINDOW in BUILD_KINDS


def test_f11_select_rejects_non_official_build_kind():
    with pytest.raises(SelectionError, match="F11"):
        select_gates({"a": object()}, build_kind="daily_full")


# -- F2 · 选择面报两个数 ----------------------------------------------------
def test_f2_select_reports_two_numbers():
    sel = select_gates({"a": object(), "b": object(), "c": object()}, only=["a", "b"])
    d = sel.to_dict()
    assert d["total"] == 3
    assert d["chosen"] == ["a", "b"]
    assert d["skipped"] == ["c"]
    assert d["selection_rate"] == round(2 / 3, 4)


def test_f2_select_all_when_only_none():
    sel = select_gates({"a": object(), "b": object()})
    assert sel.chosen == ("a", "b")
    assert sel.skipped == ()


# -- F5 · 粒度：不许跳整棵树（反例钉子）------------------------------------
def test_f5_skip_tree_marker_is_rejected():
    """★ 反例钉子：喂 skip_markers=('skip_tree',) ⇒ 必须抛。"""
    with pytest.raises(SelectionError, match="粒度违例"):
        select_gates({"a": object()}, skip_markers=("skip_tree",))


def test_f5_wildcard_all_is_rejected():
    with pytest.raises(SelectionError, match="整棵树通配"):
        select_gates({"a": object()}, only=["all"])


def test_f5_per_gate_granularity_is_ok():
    sel = select_gates({"a": object(), "b": object()}, only=["a"])
    assert sel.chosen == ("a",)


# -- F3 · 兜底层捕获率 ------------------------------------------------------
def test_f3_backstop_capture_counts_from_skipped():
    class R:
        def __init__(self, name, verdict):
            self.name = name
            self.verdict = verdict

    results = [R("a", "fail"), R("b", "fail"), R("c", "pass")]
    rep = backstop_capture(results, skipped_gates=["a"])
    assert rep.failures_caught == 2
    assert rep.from_skipped == 1
    assert rep.capture_rate() == 0.5


def test_f3_backstop_zero_failures():
    class R:
        def __init__(self, name, verdict):
            self.name = name
            self.verdict = verdict

    rep = backstop_capture([R("a", "pass")], skipped_gates=["a"])
    assert rep.failures_caught == 0 and rep.capture_rate() == 0.0


# -- F6 · 区分无关失败 ------------------------------------------------------
def test_f6_classify_flaky():
    assert classify_failure(gate_name="x", verdict="fail", flaky_known={"x"}) == ATTR_FLAKY


def test_f6_classify_unrelated_env():
    assert classify_failure(
        gate_name="x", verdict="fail",
        changed_files={"src/a.py"}, touched_files={"tools/render_signatures.json"},
    ) == ATTR_UNRELATED_ENV


def test_f6_classify_related():
    assert classify_failure(
        gate_name="x", verdict="fail",
        changed_files={"src/a.py"}, touched_files={"src/a.py"},
    ) == ATTR_RELATED


def test_f6_classify_non_failure_is_unknown():
    assert classify_failure(gate_name="x", verdict="pass") == ATTR_UNKNOWN


# -- F8 · 跃迁检测 ----------------------------------------------------------
def test_f8_detect_green_to_red_transition():
    class R:
        def __init__(self, name, verdict):
            self.name = name
            self.verdict = verdict

    today = [R("a", "fail"), R("b", "pass")]
    yesterday = {"a": "pass", "b": "pass"}
    trans = detect_transitions(today, yesterday)
    assert len(trans) == 1
    assert trans[0].gate == "a" and trans[0].frm == "pass" and trans[0].to == "fail"


def test_f8_no_transition_when_yesterday_already_red():
    class R:
        def __init__(self, name, verdict):
            self.name = name
            self.verdict = verdict

    trans = detect_transitions([R("a", "fail")], {"a": "fail"})
    assert trans == []


# -- F10 · 外部证据纪律 -----------------------------------------------------
def test_f10_lint_catches_negation_without_search_terms():
    text = "文献里没有直接测量这一层的实证。"
    violations = lint_external_evidence(text)
    assert len(violations) == 1
    assert "F10" in violations[0]


def test_f10_validate_passes_when_search_terms_attached():
    text = "检索面内未见直接测量的实证文献。"
    validate_external_evidence(text, search_terms=("nightly build", "regression"), scope="arXiv cs.SE top_k=12")


def test_f10_no_violation_when_no_negation_claim():
    text = "这一层有大量工业实测数据。"
    assert lint_external_evidence(text) == []


# ===========================================================================
# ★ 反例钉子：validate_state 咬缺字段（F2/F3/F6/F8）
# ===========================================================================
def _good_triggered_state() -> dict:
    return {
        "schema": "pipe/1",
        "overall": "pass",
        "ok": True,
        "build_kind": TRIGGERED_STRICT_BUILD,
        "selection": {
            "total": 2, "chosen": ["a", "b"], "skipped": [],
            "build_kind": TRIGGERED_STRICT_BUILD, "selection_rate": 1.0,
        },
        "parallelism": {"requested": 4, "used": 4, "degraded": False, "reason": "满并行"},
        "gates": [{"name": "a", "verdict": "pass"}],
    }


def _good_scheduled_state() -> dict:
    s = _good_triggered_state()
    s["build_kind"] = SCHEDULED_BUILD
    s["selection"]["build_kind"] = SCHEDULED_BUILD
    s["backstop"] = {"failures_caught": 0, "from_skipped": 0, "skipped_gates": [], "capture_rate": 0.0}
    s["transitions"] = []
    return s


def test_nail_f2_missing_selection_is_red():
    """★ 反例钉子：产物缺 selection 节 ⇒ 红。"""
    state = _good_triggered_state()
    del state["selection"]
    with pytest.raises(StateValidationError, match="缺 selection"):
        validate_state(state)


def test_nail_f2_selection_missing_key_is_red():
    state = _good_triggered_state()
    del state["selection"]["selection_rate"]
    with pytest.raises(StateValidationError, match="selection 缺键"):
        validate_state(state)


def test_nail_f3_scheduled_missing_backstop_is_red():
    """★ 反例钉子：scheduled build 缺 backstop 节 ⇒ 红。"""
    state = _good_scheduled_state()
    del state["backstop"]
    with pytest.raises(StateValidationError, match="缺 backstop"):
        validate_state(state)


def test_nail_f5_tree_skip_is_red():
    """★ 反例钉子：跳整棵树 ⇒ 红（已在 test_f5，这里再钉一次走 validate 路径外）。"""
    with pytest.raises(SelectionError):
        select_gates({"a": object()}, skip_markers=("skip_subtree",))


def test_nail_f6_failure_missing_attribution_is_red():
    """★ 反例钉子：失败门缺 failure_attribution ⇒ 红。"""
    state = _good_triggered_state()
    state["gates"].append({"name": "b", "verdict": "fail"})
    with pytest.raises(StateValidationError, match="缺 failure_attribution"):
        validate_state(state)


def test_nail_f8_scheduled_missing_transitions_is_red():
    """★ 反例钉子：scheduled build 缺 transitions 节 ⇒ 红。"""
    state = _good_scheduled_state()
    del state["transitions"]
    with pytest.raises(StateValidationError, match="缺 transitions"):
        validate_state(state)


def test_nail_f11_bad_build_kind_in_state_is_red():
    state = _good_triggered_state()
    state["selection"]["build_kind"] = "daily_full"
    with pytest.raises(StateValidationError, match="官方词"):
        validate_state(state)


def test_good_states_validate_clean():
    """正向：合法的 triggered / scheduled 产物都过 validate_state。"""
    validate_state(_good_triggered_state())
    validate_state(_good_scheduled_state())
