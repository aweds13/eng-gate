"""F1/F4/F9 落地用例：跑真门验证产物字段（卡 185 / T-G285）。

- F1：并行度优先 + 降级留痕（产物 parallelism 节）。
- F4：动态读数进输入面（产物 dynamic_reads / input_hash_with_dynamic）。
- F9：覆盖率不许单独当绿（emits==("coverage",) 退出 0 ⇒ inconclusive）。
- 端到端：示例仓跑完的产物过 validate_state（F2/F3/F6/F8 落地）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from framework.config import GateSpec, load
from framework.gates import Verdict, run_gate, run_gates
from framework.selection import SCHEDULED_BUILD, TRIGGERED_STRICT_BUILD, validate_state

FRAMEWORK = Path(__file__).resolve().parents[1]
EXAMPLE = FRAMEWORK / "examples" / "minimal-notes"


def _spec(cmd, **kw) -> GateSpec:
    base = dict(name="t", cmd=tuple(cmd), inputs=(), nail="x::y", reuse="never",
                stage="light", timeout_s=30)
    base.update(kw)
    return GateSpec(**base)


def _copy_example(tmp_path: Path) -> Path:
    dst = tmp_path / "repo"
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns("__pycache__", ".pipe"))
    return dst


# -- F1 · 并行度优先 + 降级留痕 ---------------------------------------------
def test_f1_full_parallel_not_degraded(tmp_path: Path):
    repo = _copy_example(tmp_path)
    cfg = load(repo / "pipeline.toml")
    run = run_gates(cfg)
    state = run.to_dict()
    par = state["parallelism"]
    assert par["degraded"] is False
    assert par["used"] == par["requested"]
    assert par["reason"] == "满并行"


def test_f1_degradation_is_recorded(tmp_path: Path):
    """★ 降级必须留痕：max_concurrent=1 < 配置的 2 ⇒ degraded=True。"""
    repo = _copy_example(tmp_path)
    cfg = load(repo / "pipeline.toml")
    run = run_gates(cfg, max_concurrent=1)
    par = run.to_dict()["parallelism"]
    assert par["degraded"] is True
    assert par["used"] == 1
    assert par["requested"] == 2
    assert "降级" in par["reason"]


# -- F4 · 动态读数进输入面 --------------------------------------------------
def test_f4_dynamic_reads_recorded_in_result(tmp_path: Path):
    """门运行时真读过哪些文件要能被登记并进输入表。"""
    (tmp_path / "secret.json").write_text('{"k": 1}', encoding="utf-8")
    manifest = tmp_path / "reads.json"
    manifest.write_text(json.dumps(["secret.json"]), encoding="utf-8")

    res = run_gate(
        _spec([sys.executable, "-c", "pass"]),
        repo_root=tmp_path, logs_dir=tmp_path / "logs", reads_manifest=manifest,
    )
    assert res.dynamic_reads == ("secret.json",)
    assert res.input_hash_with_dynamic is not None


def test_f4_dynamic_reads_change_the_combined_hash(tmp_path: Path):
    """★ 现场洞见（P2）：render 真读 tools/render_signatures.json 不在输入表里 ⇒
    改它时增量会跳过。动态读数进哈希后，改它 ⇒ 哈希变 ⇒ 不再误跳。"""
    (tmp_path / "dyn.json").write_text('{"v": 1}', encoding="utf-8")
    manifest = tmp_path / "reads.json"
    manifest.write_text(json.dumps(["dyn.json"]), encoding="utf-8")

    res1 = run_gate(
        _spec([sys.executable, "-c", "pass"]),
        repo_root=tmp_path, logs_dir=tmp_path / "logs", reads_manifest=manifest,
    )
    (tmp_path / "dyn.json").write_text('{"v": 2}', encoding="utf-8")
    res2 = run_gate(
        _spec([sys.executable, "-c", "pass"]),
        repo_root=tmp_path, logs_dir=tmp_path / "logs", reads_manifest=manifest,
    )
    assert res1.input_hash_with_dynamic != res2.input_hash_with_dynamic


def test_f4_no_manifest_means_empty_dynamic_reads(tmp_path: Path):
    res = run_gate(_spec([sys.executable, "-c", "pass"]),
                   repo_root=tmp_path, logs_dir=tmp_path / "logs")
    assert res.dynamic_reads == ()


# -- F9 · 覆盖率不许单独当绿 ------------------------------------------------
def test_f9_sole_coverage_is_inconclusive(tmp_path: Path):
    """★ emits==("coverage",) 退出 0 ⇒ inconclusive，不许 pass。"""
    res = run_gate(
        _spec([sys.executable, "-c", "pass"], emits=("coverage",)),
        repo_root=tmp_path, logs_dir=tmp_path / "logs",
    )
    assert res.verdict == Verdict.INCONCLUSIVE.value
    assert "F9" in res.reason


def test_f9_coverage_alongside_junit_is_ok(tmp_path: Path):
    """覆盖率与 junit 并列 ⇒ 不触发 F9（覆盖率只是并列证据之一）。"""
    res = run_gate(
        _spec([sys.executable, "-c", "pass"], emits=("junit", "coverage")),
        repo_root=tmp_path, logs_dir=tmp_path / "logs",
    )
    assert res.verdict != Verdict.INCONCLUSIVE.value or "F9" not in res.reason


# -- 端到端：产物过 validate_state（F2/F3/F6/F8 落地）-----------------------
def test_triggered_build_state_validates(tmp_path: Path):
    repo = _copy_example(tmp_path)
    cfg = load(repo / "pipeline.toml")
    run = run_gates(cfg, build_kind=TRIGGERED_STRICT_BUILD)
    state = run.to_dict()
    assert state["build_kind"] == TRIGGERED_STRICT_BUILD
    assert state["selection"] is not None
    validate_state(state)


def test_scheduled_build_state_has_backstop_and_transitions(tmp_path: Path):
    """scheduled build 产物必须含 backstop（F3）与 transitions（F8）。"""
    repo = _copy_example(tmp_path)
    cfg = load(repo / "pipeline.toml")
    run = run_gates(
        cfg, build_kind=SCHEDULED_BUILD,
        skipped_by_increment=("tests",),
        yesterday_state={"tests": "pass"},
    )
    state = run.to_dict()
    assert "backstop" in state
    assert "transitions" in state
    validate_state(state)
