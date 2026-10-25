r"""属性测试（卡 E51 · 段 2 / E37 判据 7）：选测 / 变异报告那几条**纯函数**的不变量。

## 为什么用属性而不是再写几条例子

例子测试只能证明"我给的那几个输入对"；这层要的是**任意输入下都成立**的性质：
路径归一化幂等、`test:` 指针永远落在 `tests/`、映射值一定是用例文件、变异分有界且单调、
独有击杀是击杀的子集且彼此不相交、删除上限的边界方向。

## 口径

- 只跑**纯函数**（不读真台账、不起 git、不跑 pytest、不碰文件系统）；
- `--hypothesis-seed` 可复现：hypothesis 插件自带该参数，失败时会打印可复现的 seed；
- 该文件必须 **≤20 s**：`max_examples` 压在 60 以内，且不用 `tmp_path`（fixture 与 given 不兼容）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent
_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _load(name: str, relpath: str):
    target = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PS = _load("pytest_select_for_props", "tools/pytest_select.py")
MR = _load("mutate_report_for_props", "tools/mutate_report.py")


@_SETTINGS
@given(st.lists(st.text(min_size=1, max_size=40), max_size=8))
def test_norm_paths_is_canonical(parts: list[str]) -> None:
    """归一化后：没有 `./` 前缀、没有反斜杠、无重复，且顺序是输入的保序子序列。"""
    out = PS.norm_paths(parts)
    assert all(not p.startswith("./") for p in out)
    assert all("\\" not in p for p in out)
    assert len(out) == len(set(out))
    assert PS.norm_paths(out) == out


@_SETTINGS
@given(
    # 真文件名不长这样：带冒号/空白的串连一条路径都不是。属性测试只该覆盖**合法输入**
    # 的全域（卡 E51 段 1）：这个字符类含子目录、点号、连字符，排除 `:` 与空白。
    st.from_regex(r"\A[a-zA-Z0-9_./-]{1,40}\Z", fullmatch=True),
    st.one_of(st.none(), st.from_regex(r"\A[a-zA-Z0-9_ ]{1,40}\Z", fullmatch=True)),
)
def test_test_file_of_always_under_tests(fname: str, case: str | None) -> None:
    """`test:文件[::用例名]` 永远算成 `tests/<文件>`（与审计同一把尺子）。"""
    pointer = f"test:{fname}" + (f"::{case}" if case else "")
    got = PS.test_file_of(pointer)
    assert got == f"tests/{fname}"
    assert PS.test_file_of(f"file:{fname}") is None


@_SETTINGS
@given(
    st.dictionaries(
        keys=st.text(min_size=1, max_size=12).filter(lambda s: s and s.strip() == s),
        values=st.lists(
            st.sampled_from(
                [
                    "file:src/a.py",
                    "text:src/b.py::def run",
                    "test:test_a.py",
                    "test:test_b.py::case",
                    "route:GET /api/x",
                    "file:tests/test_c.py",
                ]
            ),
            max_size=5,
        ),
        max_size=6,
        min_size=1,
    )
)
def test_ledger_index_only_maps_to_test_files(entries: dict[str, list[str]]) -> None:
    """索引的每个映射值都是**用例文件**，且都来自 `test_files`（不夹带源文件）。"""
    data = {"entries": {eid: {"status": "done", "evidence": ev} for eid, ev in entries.items()}}
    index = PS.ledger_index(data)
    mapped = {t for tests in index.sources.values() for t in tests}
    assert mapped <= set(index.test_files)
    assert all(t.startswith("tests/") for t in index.test_files)


@_SETTINGS
@given(
    st.lists(
        st.sampled_from(["docs/x.md", "复盘/y.md", "gates/z.json", ".wt/w.txt"]), max_size=6
    )
)
def test_docs_only_never_falls_back(paths: list[str]) -> None:
    """只有记账/文档改动 ⇒ `fallback=False` 且选集为空（不是"漏跑"，也不是"全量"）。"""
    sel = PS.select(paths, ledger={"entries": {}}, nightly_ok=True)
    assert sel.fallback is False
    assert sel.tests == ()
    assert sel.pytest_args == []


@_SETTINGS
@given(st.integers(min_value=0, max_value=500), st.integers(min_value=0, max_value=500))
def test_score_bounds_and_monotone(killed: int, survived: int) -> None:
    """变异分 ∈ [0,100]；存活固定时，杀得越多分不低于原来（总分 0 时是 0，不是满分）。"""
    score = MR.score_of(killed, survived)
    assert 0.0 <= score <= 100.0
    if killed + survived > 0:
        assert MR.score_of(killed + 1, survived) >= score
    else:
        assert score == 0.0


@_SETTINGS
@given(
    st.lists(
        st.tuples(
            st.text(min_size=1, max_size=6),
            st.sampled_from(["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]),
        ),
        max_size=12,
    )
)
def test_unique_kills_subset_and_disjoint(rows: list[tuple[str, str]]) -> None:
    """独有击杀 ⊆ 击杀；且不存在一条变异体同时出现在两份用例的 `unique` 里。"""
    kills: dict[str, set[str]] = {}
    for mid, test in rows:
        kills.setdefault(test, set()).add(mid)
    unique = MR.unique_kills(kills)
    for test, ids in unique.items():
        assert ids <= kills[test]
    owner: dict[str, str] = {}
    for test, ids in unique.items():
        for mid in ids:
            assert mid not in owner, (mid, owner, test)
            owner[mid] = test


@_SETTINGS
@given(
    st.integers(min_value=1, max_value=5000),
    st.floats(min_value=50.0, max_value=100.0),
    st.floats(min_value=0.0, max_value=50.0),
)
def test_delete_budget_boundary(total: int, before: float, delta: float) -> None:
    """删除上限的方向：3% 以内 + 下降 ≤0.5 ⇒ 无问题；超出任一条 ⇒ 必有问题。"""
    allowed = int(total * MR.MAX_DELETE_RATIO)
    assert MR.deletion_problems(total, allowed, before, before) == []
    over_count = MR.deletion_problems(total, allowed + 1, before, before)
    assert over_count
    after = max(0.0, before - delta)
    problems = MR.deletion_problems(total, allowed, before, after)
    if delta <= MR.MAX_SCORE_DROP:
        assert problems == []
    else:
        assert problems
