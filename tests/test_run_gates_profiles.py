"""门禁三档（lang / audit / product）的钉子：不漏、不重、all 等价、lang 不混产品门。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_run_gates():
    target = ROOT / "scripts" / "run_gates.py"
    spec = importlib.util.spec_from_file_location("run_gates_under_test", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_gates_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_run_gates()


def _all_gate_names() -> list[str]:
    return [n for n, _ in rg.COMMON] + [n for n, _ in rg.REAL_PY] + list(rg.BROWSER)


def test_profiles_come_from_gate_defs() -> None:
    """三档的成员必须分别来自三个定义模块，而不是 runner 里再写一遍。"""
    assert rg.GATE_PROFILES["lang"] == tuple(n for n, _ in rg.lang_python.GATES)
    assert rg.GATE_PROFILES["audit"] == tuple(n for n, _ in rg.contract.GATES)
    pt = rg.product_timeflow
    product = tuple(n for n, _ in pt.GATES) + tuple(n for n, _ in pt.REAL) + pt.BROWSER
    assert rg.GATE_PROFILES["product"] == product


def test_three_profiles_are_disjoint_and_cover_all() -> None:
    """联合 == 全量（漏一个就红）；两两无交集（重叠就红）。"""
    seen: dict[str, str] = {}
    for name, members in rg.GATE_PROFILES.items():
        for g in members:
            assert g not in seen, f"门 {g} 同时属于 {seen.get(g)} 与 {name}"
            seen[g] = name
    assert set(seen) == set(_all_gate_names()), "有门没进任何档，或档里有不存在的门"


def test_lang_profile_has_no_product_gate() -> None:
    """`--profile lang` 不许混进任何产品门 —— 那是换产品时要整份替换的部分。"""
    product = set(rg.GATE_PROFILES["product"])
    assert not (set(rg.GATE_PROFILES["lang"]) & product)
    assert not (set(rg.GATE_PROFILES["audit"]) & product)


def test_unknown_profile_raises() -> None:
    """未知档名要响，不许静默跑全量。"""
    import pytest

    with pytest.raises(ValueError):
        rg.build_jobs(quick=False, fast=False, profile="no-such-profile")
