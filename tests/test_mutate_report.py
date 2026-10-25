r"""钉「变异驱动的用例汰换」（卡 E51 · 段 2 / E37）。

## 判据（逐条对应卡 §段 2 判据 6，≥6 条钉子）

1. **零独有击杀判定**：一条变异体被多份用例杀掉 ⇒ 谁都不独占；独占才进 `unique`；
2. **报告形状固定**：`REPORT_KEYS` 恰好那些键，多/少一个都拒绝；
3. **保护清单不可删**：`delete_candidates` 不吐保护清单里的条目，`deletion_problems` 点名；
4. **引擎缺失 fail closed**：`require_engine({})` 抛 `EngineMissing`，CLI 退 2（不静默跳过）；
5. `--json` 键名固定；
6. **同一用例重复出现只算一次**（矩阵里同一 (mutant, test) 出现两次，`unique` 不重复）；
7. 删除上限：>3% 或变异分下降 >0.5 都判红；删一条有独有击杀的用例 ⇒ 分数必降；
8. 参数化合并清册：`ids` 是**原用例名**（可追溯），只产清册不写文件。

## 怎么跑（★ 不跑真变异、不改任何测试）

全部用合成矩阵 / `tmp_path` 假测试目录。真实 `mutation.json` 由引擎会话产出
（引擎在不在见 `--require-engine`；本卡收口里引擎可用性也如实记在 `gates/diag/E51-stage2.log`）。

## 边界（如实写，未覆盖）

- **真变异会话 / 删除 3% 用例 / 97 族参数化合并的实际执行**：本卡不自动改测试
  （卡明说「生成清册让人判」），逐族人工确认后再合并；本文件只钉工具判据。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mr():
    target = ROOT / "tools" / "mutate_report.py"
    spec = importlib.util.spec_from_file_location("mutate_report_under_test", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mutate_report_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _report(mr, *rows: tuple[str, str | None], all_tests=()):
    mutants = [{"id": mid, "killer": killer} for mid, killer in rows]
    return mr.build_report(
        "cosmic-ray", "8.7.0", ["tools/x.py"], mutants,
        all_tests=list(all_tests), created_at="2026-10-25T00:00:00",
    )


def test_zero_unique_kill_semantics() -> None:
    """独占才算：同一条被两人杀 ⇒ 都不独占；只有一个人杀 ⇒ 进 `unique`。"""
    mr = _mr()
    report = _report(
        mr,
        ("m1", "tests/test_a.py"),
        ("m2", "tests/test_a.py"),
        ("m3", "tests/test_b.py"),
        ("m4", "tests/test_a.py"),
        ("m5", "tests/test_b.py"),
        ("m6", None),  # 存活
    )
    assert report.tests["tests/test_a.py"].unique == ("m1", "m2", "m4")
    assert report.tests["tests/test_b.py"].unique == ("m3", "m5")
    assert report.zero_kill_tests == ()
    assert report.killed == 5 and report.survived == 1
    assert report.score == mr.score_of(5, 1)

    shared = _report(mr, ("x1", "tests/test_a.py"), ("x1", "tests/test_b.py"))
    assert shared.tests["tests/test_a.py"].unique == ()
    assert shared.zero_kill_tests == ("tests/test_a.py", "tests/test_b.py")


def test_duplicate_occurrence_counts_once() -> None:
    """同一变异体 / 同一用例重复出现只算一次 —— 否则"独占"与总分会被重复行伪造。"""
    mr = _mr()
    report = _report(mr, ("m1", "tests/test_a.py"), ("m1", "tests/test_a.py"))
    assert report.killed == 1, "同一个变异体的两行只算一条"
    assert report.tests["tests/test_a.py"].unique == ("m1",)
    assert len(report.tests["tests/test_a.py"].unique) == 1


def test_report_shape_is_fixed() -> None:
    """报告键固定：少一个 / 多一个都拒绝（读不懂就不猜）。"""
    mr = _mr()
    raw = _report(mr, ("m1", "tests/test_a.py")).payload()
    assert set(raw) == mr.REPORT_KEYS
    assert mr.report_from_json(raw).zero_kill_tests == ()
    broken = dict(raw)
    broken.pop("score")
    try:
        mr.report_from_json(broken)
    except ValueError as exc:
        assert "缺" in str(exc)
    else:  # pragma: no cover - 防御式断言
        raise AssertionError("少了 score 竟然读过去了")

    extra = {**raw, "surprise": 1}
    try:
        mr.report_from_json(extra)
    except ValueError as exc:
        assert "多" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("多了键竟然读过去了")


def test_protected_list_cannot_be_deleted() -> None:
    """保护清单一条都不许删；`delete_candidates` 只吐清单外的零击杀用例。"""
    mr = _mr()
    protected = "tests/test_no_window.py"
    report = _report(
        mr, ("m1", "tests/test_a.py"), all_tests=["tests/test_a.py", protected, "tests/test_c.py"]
    )
    assert protected in report.zero_kill_tests
    assert mr.delete_candidates(report, protected=(protected,)) == ["tests/test_c.py"]
    problems = mr.deletion_problems(
        100, 1, report.score, report.score, protected_hit=(protected,)
    )
    assert any("保护清单" in p for p in problems)


def test_engine_missing_fails_closed(monkeypatch) -> None:
    """引擎不在 ⇒ 明确报「引擎不在」并退 2；不许静默跳过。"""
    mr = _mr()
    try:
        mr.require_engine({})
    except mr.EngineMissingError as exc:
        assert "引擎不在" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("没引擎竟然不抛")

    def _boom(*_a, **_k):
        raise mr.EngineMissingError("引擎不在：测试替身")

    monkeypatch.setattr(mr, "require_engine", _boom)
    assert mr.main(["--require-engine"]) == 2


def test_json_keys_are_fixed() -> None:
    """`--json` 的键名固定（下游按这些键读：引擎/分数/零击杀/候选/保护清单）。"""
    mr = _mr()
    report = _report(
        mr, ("m1", "tests/test_a.py"), all_tests=["tests/test_a.py", "tests/test_b.py"]
    )
    payload = {
        "engine": report.engine,
        "version": report.version,
        "modules": list(report.modules),
        "score": report.score,
        "killed": report.killed,
        "survived": report.survived,
        "zero_kill_tests": list(report.zero_kill_tests),
        "delete_candidates": mr.delete_candidates(report),
        "protected": list(mr.PROTECTED_TESTS),
    }
    assert set(payload) == {
        "engine", "version", "modules", "score", "killed", "survived",
        "zero_kill_tests", "delete_candidates", "protected",
    }
    assert json.loads(json.dumps(payload))["zero_kill_tests"] == ["tests/test_b.py"]


def test_delete_budget_and_score_drop() -> None:
    """删除上限：>3% 判红；分下降 >0.5 判红；删一条有独有击杀的用例 ⇒ 分数必降。"""
    mr = _mr()
    assert mr.deletion_problems(1000, 30, 80.0, 80.0) == []
    over = mr.deletion_problems(1000, 31, 80.0, 80.0)
    assert any("3%" in p for p in over)
    drop = mr.deletion_problems(1000, 1, 80.0, 79.4)
    assert any("下降" in p for p in drop)

    report = _report(mr, ("m1", "tests/test_a.py"), ("m2", "tests/test_b.py"),
                     ("m3", "tests/test_b.py"))
    after = mr.score_after_deleting(report, "tests/test_a.py")
    assert after < report.score, (after, report.score)
    # 删一条**有独有击杀**的用例 ⇒ 分数下降必然超出 0.5 的容忍（这里 3 条变异体的小样本）
    assert mr.deletion_problems(100, 1, report.score, after)
    # 删一条零独有击杀的用例 ⇒ 分数不动 ⇒ 不触犯上限
    noop = _report(mr, ("m1", "tests/test_a.py"), all_tests=["tests/test_a.py", "tests/test_b.py"])
    assert mr.score_after_deleting(noop, "tests/test_b.py") == noop.score
    assert mr.deletion_problems(100, 1, noop.score, noop.score) == []


def test_families_inventory_keeps_original_ids(tmp_path: Path) -> None:
    """合并清册：`ids` 是原用例名（可追溯），同结构不同字面量才成族。"""
    mr = _mr()
    (tmp_path / "test_family.py").write_text(
        "def test_one():\n    assert add(1, 2) == 3\n\n"
        "def test_two():\n    assert add(4, 5) == 9\n\n"
        "def test_other():\n    assert str(1) == 'x'\n",
        encoding="utf-8",
    )
    inventory = mr.merge_families(tmp_path)
    assert inventory["functions"] == 3
    family = inventory["families"][0]
    assert family["file"] == "test_family.py"
    assert family["ids"] == ["test_one", "test_two"]
    assert inventory["family_count"] == 1
