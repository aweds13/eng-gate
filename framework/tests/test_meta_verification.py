"""G7 / G9 / G10 的用例 —— 元验证（拒绝点活性扫描）+ 验证器脆弱性 + 复核面。

★ G7 与 G10 同族（都是「谁来验验证器」），故同文件。
★ 反例钉子：G7（vacuous pass）/ G9（脆弱验证器被改判）/ G10（3 条）。
★ G7 的**现成读数**在 `test_g7_refusal_scan_has_vacuous_pass` 真跑。
"""

from __future__ import annotations

from framework.fitness import (
    ClassifyInput,
    classify_mutable,
    classify_refusal_scan,
    fragile_validator,
    fragile_validator_reordered,
    sample_validator,
    sample_validator_reordered,
    verifier_stable_under_reorder,
)
from framework.gates import Verdict, classify
from framework.review import (
    AuthorityDomain,
    IntegrationResult,
    ReviewConfigError,
    changed_paths,
    check_branch,
    check_full_gate_run,
    check_gate_evidence,
    check_trailers,
    domain_of_manifest_text,
    load_review_config,
    outside_allow,
    outside_domain,
    run_review,
)

# ===========================================================================
# G7 · 拒绝点活性扫描（★ 现成读数）
# ===========================================================================

def test_g7_classify_mutable_equivalent_to_classify():
    """G9 前提：classify_mutable(disable=∅) 与 gates.classify 逐输入等价。"""
    samples = [
        ClassifyInput(ran=False, timed_out=False, exit_code=None, exit_ok=(0,), collected=None),
        ClassifyInput(ran=True, timed_out=True, exit_code=124, exit_ok=(0,), collected=None),
        ClassifyInput(ran=True, timed_out=False, exit_code=0, exit_ok=(0,), collected=0),
        ClassifyInput(ran=True, timed_out=False, exit_code=0, exit_ok=(0,), collected=3),
        ClassifyInput(ran=True, timed_out=False, exit_code=1, exit_ok=(0,), collected=2),
    ]
    for inp in samples:
        _, v_orig, _ = classify(ran=inp.ran, timed_out=inp.timed_out, exit_code=inp.exit_code,
                                exit_ok=inp.exit_ok, collected=inp.collected)
        assert v_orig == classify_mutable(inp)[0]


def test_g7_refusal_scan_has_vacuous_pass():
    """★ G7 现成读数：删掉某拒绝点 ⇒ 本该红却没红（vacuous pass）。

    删掉「空集 ⇒ inconclusive」拒绝点后，collected=0、exit_code=0 的 subject
    （本该 inconclusive）变 pass。
    """
    readings = classify_refusal_scan()
    vacuous = [r for r in readings if r.is_vacuous_pass]
    assert len(vacuous) >= 1
    the_one = [r for r in vacuous if r.site == "empty" and "collected=0" in r.subject]
    assert len(the_one) == 1
    assert the_one[0].original_verdict == "inconclusive"
    assert the_one[0].mutated_verdict == "pass"


def test_g7_refusal_scan_reading_to_dict():
    d = [r for r in classify_refusal_scan() if r.is_vacuous_pass][0].to_dict()
    expected = {
        "site", "subject", "original_verdict", "mutated_verdict",
        "is_vacuous_pass", "detail",
    }
    assert set(d) == expected


def test_g7_empty_site_is_the_live_one():
    inp = ClassifyInput(ran=True, timed_out=False, exit_code=0, exit_ok=(0,), collected=0)
    _, v_full, _ = classify(ran=inp.ran, timed_out=inp.timed_out, exit_code=inp.exit_code,
                            exit_ok=inp.exit_ok, collected=inp.collected)
    v_muted, _ = classify_mutable(inp, disable=frozenset({"empty"}))
    assert v_full == Verdict.INCONCLUSIVE
    assert v_muted == Verdict.PASS


# ===========================================================================
# G9 · 验证器脆弱性自测
# ===========================================================================

def test_g9_sample_validator_stable_under_reorder():
    """★ G9 钉子：独立声明重排不改判定。"""
    reading = verifier_stable_under_reorder(
        verifier=sample_validator, reordered=sample_validator_reordered,
        subject={"name": "x", "version": "1.0"}, subject_desc="{name,version}",
        verifier_name="sample_validator",
    )
    assert reading.stable is True


def test_g9_fragile_validator_is_caught():
    """★ G9 反例钉子：脆弱验证器（依赖 dict 顺序）被等价重排改判 ⇒ 钉子有牙。"""
    reading = verifier_stable_under_reorder(
        verifier=fragile_validator, reordered=fragile_validator_reordered,
        subject={"version": "1.0", "name": "x"}, subject_desc="{version,name}",
        verifier_name="fragile_validator",
    )
    assert reading.stable is False


def test_g9_classify_mutable_stable_under_exit_ok_reorder():
    a = ClassifyInput(ran=True, timed_out=False, exit_code=1, exit_ok=(0, 1), collected=2)
    v1, _ = classify_mutable(a)
    b = ClassifyInput(ran=True, timed_out=False, exit_code=1, exit_ok=(1, 0), collected=2)
    v2, _ = classify_mutable(b)
    assert v1 == v2 == Verdict.PASS


# ===========================================================================
# G10 · 复核面（抽空进库 + run_review + 三条反例钉子）
# ===========================================================================

def test_g10_outside_allow_and_domain():
    assert outside_allow(["a/b.py", "c/d.py"], ["a/**"]) == ["c/d.py"]
    assert outside_allow(["a\\b.py"], ["a/**"]) == []
    assert outside_domain(["src/a.py", "tools/b.py"], ["src/**"]) == ["tools/b.py"]


def test_g10_changed_paths():
    text = " M src/a.py\n?? src/new.py\nR  old.py -> new.py\n"
    assert set(changed_paths(text)) == {"src/a.py", "src/new.py", "new.py"}


def test_g10_domain_of_manifest():
    text = '[[member]]\nid = "M-1"\npaths = ["src/**"]\n'
    assert domain_of_manifest_text(text, "M-1") == ["src/**"]
    assert domain_of_manifest_text(text, "M-2") is None


def test_g10_check_trailers():
    body = "s\n\nTask: T-1\nLedger: L-1\nGates: 门禁绿\n"
    assert check_trailers(body)[0] == []
    assert len(check_trailers("s\n")[0]) >= 2


def test_g10_check_gate_evidence_rev_mismatch():
    """G10 钉子②：rev 对不上 ⇒ 红。"""
    payload = {"ok": True, "rev": "wrong", "gates": [{"name": "g1", "exit_code": 0}]}
    out = check_gate_evidence(payload, "abc123")
    assert any("rev" in p and "wrong" in p for p in out)


def test_g10_check_full_gate_run_affected_is_red_with_original():
    """★ G10 反例钉子③：有 affected 块 ⇒ 判红并贴原文。"""
    payload = {
        "tree_scope": "x", "gates": [{"name": "a"}],
        "affected": {"files": ["x.py"], "reason": "部分跑"},
    }
    problems, _, _ = check_full_gate_run(payload, expected_gate_names=["a"], expected_source="t")
    joined = " ".join(problems)
    assert "affected" in joined and "部分跑" in joined


def test_g10_check_full_gate_run_synthetic_only_notes():
    problems, note, _ = check_full_gate_run(
        {"gates": [{"name": "a"}], "affected": {"files": ["x"]}},
        expected_gate_names=["a", "b"], expected_source="t",
    )
    assert problems == [] and note


def test_g10_check_branch_three_states():
    assert check_branch("main", "main", default_branch="main")[0] == []
    assert len(check_branch("dev", "main", default_branch="main")[0]) == 1
    assert check_branch("HEAD", "main", default_branch="main")[0] == []
    assert len(check_branch("HEAD", "release", default_branch="main")[0]) == 1


def test_g10_review_config_green():
    cfg = load_review_config({
        "who": "pipe review", "what": ["domain", "gate_count", "trailer", "branch", "dirty_tree"],
        "where": "gates/review/{task}.json", "on_fail": "mark_only",
    })
    assert cfg.on_fail == "mark_only"


def test_g10_review_config_rejects_bad():
    try:
        load_review_config({"who": "x", "what": ["nope"], "where": "x", "on_fail": "mark_only"})
        raise AssertionError("[review].what 里的未知项必须报错，但没报")
    except ReviewConfigError:
        pass
    try:
        load_review_config({"who": "x", "what": ["domain"], "where": "x", "on_fail": "halt"})
        raise AssertionError("[review].on_fail 的非法取值必须报错，但没报")
    except ReviewConfigError:
        pass


def _green_result() -> IntegrationResult:
    return IntegrationResult(
        sha="abc123", parent_short="par123",
        commit_body="subject\n\nTask: T-1\nLedger: L-1\nGates: 门禁绿\n",
        changed_files=["src/a.py"], branch="main", dirty=[],
        gates_payload={"ok": True, "rev": "par123", "gates": [{"name": "g1", "exit_code": 0}]},
    )


def _green_domain() -> AuthorityDomain:
    return AuthorityDomain(domain=["src/**"], source="栅栏预声明")


def test_g10_run_review_green():
    r = run_review(
        _green_result(),
        _green_domain(),
        expected_gate_names=["g1"],
        expected_branch="main",
        default_branch="main",
        allow=["src/**"],
    )
    assert r.landed is True and r.exit_code() == 0


def test_g10_nail_no_review_record_not_landed():
    """★ G10 反例钉子①：没有复核记录 ⇒ 不许标 landed。"""
    result = _green_result()
    result = IntegrationResult(
        sha=result.sha, parent_short=result.parent_short, commit_body=result.commit_body,
        changed_files=result.changed_files, branch=result.branch, dirty=result.dirty,
        gates_payload={},
    )
    r = run_review(
        result,
        _green_domain(),
        expected_gate_names=["g1"],
        expected_branch="main",
        default_branch="main",
        allow=["src/**"],
    )
    assert r.landed is False
    assert any("没有复核记录" in p for p in r.problems)
    assert r.exit_code() == 5


def test_g10_nail_rev_mismatch_is_red():
    """★ G10 反例钉子②：rev 对不上 ⇒ 红。"""
    result = _green_result()
    result = IntegrationResult(
        sha=result.sha, parent_short="par123", commit_body=result.commit_body,
        changed_files=result.changed_files, branch=result.branch, dirty=result.dirty,
        gates_payload={"ok": True, "rev": "WRONG", "gates": [{"name": "g1", "exit_code": 0}]},
    )
    r = run_review(
        result,
        _green_domain(),
        expected_gate_names=["g1"],
        expected_branch="main",
        default_branch="main",
        allow=["src/**"],
    )
    assert r.landed is False and r.exit_code() == 1


def test_g10_nail_affected_block_is_red_with_original():
    """★ G10 反例钉子③：部分跑（有 affected 块）⇒ 判红并贴原文。"""
    result = _green_result()
    result = IntegrationResult(
        sha=result.sha, parent_short="par123", commit_body=result.commit_body,
        changed_files=result.changed_files, branch=result.branch, dirty=result.dirty,
        gates_payload={"ok": True, "rev": "par123", "tree_scope": "x",
                       "gates": [{"name": "g1", "exit_code": 0}],
                       "affected": {"files": ["src/x.py"], "reason": "部分跑"}},
    )
    r = run_review(
        result,
        _green_domain(),
        expected_gate_names=["g1"],
        expected_branch="main",
        default_branch="main",
        allow=["src/**"],
    )
    assert r.landed is False
    joined = " ".join(r.problems)
    assert "affected" in joined and "部分跑" in joined
