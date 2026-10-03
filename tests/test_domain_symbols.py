"""`tools/domain_symbols.py`（符号级冲突域，卡 188 · 台账号 `T-G288`）的反例钉子 —— 五条起。

为什么要有它：排班器现在只认**文件级**域（`tools/pool/plan.py` 的 `files_intersect()`），
于是「多张待派卡同改一个 2481 行的 `tools/wb_dispatch.py`」只能一张一张串起来。这个零件把判据
下探到**顶层符号**。它错了的代价是**假并行**：两张卡被判「可并行」却在同一个函数里各写各的 →
落地必撞。所以下面每条都朝「会咬」的方向写，**全部跑在临时夹具上**（不拿真队列 / 真文件当夹具）。

| 钉子 | 断言什么 |
|---|---|
| 1 | 文件不相交 ⇒ 可并行 |
| 2 | ★ 同文件不同符号 ⇒ 可并行**但要提醒**（文案含「rebase」「同文件」） |
| 3 | 同文件同符号 ⇒ 串 |
| 4 | 不带 `::` 的老写法 ⇒ 判定与今天 `files_intersect()` **逐字相同**（交叉核真源） |
| 5 | ★ 符号写错 ⇒ **红**（不许静默降级成整文件） |

外加：`symbols_of` / `symbol_ranges` 的形、整文件压过符号级、坏声明、缺文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import domain_symbols as ds  # noqa: E402
from pool import plan as pool_plan  # noqa: E402

# 夹具模块：顶层符号 = ALPHA_CONST（常量）/ alpha / beta（函数）/ Gamma（类）/ delta（异步函数）。
# ★ `Gamma.method` 是**类里**的方法 —— 必须**不算**顶层符号。
MODULE = '''\
"""夹具模块。"""

ALPHA_CONST = 1


def alpha() -> int:
    return ALPHA_CONST


def beta() -> int:
    return 2


class Gamma:
    def method(self) -> int:
        return 3


async def delta() -> None:
    return None
'''

# 另一个文件里也有个 `alpha` —— 用来证明「不同文件的同名符号」一样是「文件不相交」。
OTHER = '''\
def alpha() -> int:
    return 0


def gamma() -> int:
    return 1
'''


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "b.py").write_text(OTHER, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ 零件层


def test_symbols_of_lists_top_level_only(tree: Path) -> None:
    """顶层符号都列出来；类里的方法不算。"""
    assert ds.symbols_of("a.py", root=tree) == {
        "ALPHA_CONST",
        "alpha",
        "beta",
        "Gamma",
        "delta",
    }
    assert "method" not in ds.symbols_of("a.py", root=tree)


def test_symbol_ranges_are_adjacent_and_cover_file(tree: Path) -> None:
    """行区间 = `def x` 到下一个顶层定义之间；相邻不重叠，最后一个到文件末尾。"""
    ranges = ds.symbol_ranges("a.py", root=tree)
    lines = MODULE.splitlines()
    assert lines[ranges["alpha"][0] - 1].startswith("def alpha")
    assert lines[ranges["Gamma"][0] - 1].startswith("class Gamma")
    ordered = sorted(ranges.values())
    for (_, end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
        assert end == next_start - 1
    assert ordered[-1][1] == len(lines)


def test_declared_symbols_names_and_whole_file(tree: Path) -> None:
    """带 `::` → 符号名集合；不带 `::` → 整文件哨兵。"""
    assert ds.declared_symbols("a.py::beta", root=tree) == {"beta"}
    assert ds.declared_symbols("a.py", root=tree) == {ds.WHOLE_FILE}


# ------------------------------------------------------------------ 五条钉子


def test_nail1_disjoint_files_are_parallel(tree: Path) -> None:
    """钉子 1：文件不相交 ⇒ 可并行（哪怕两边符号同名）。"""
    result = ds.overlap("a.py::alpha", "b.py::alpha", root=tree)
    assert result.kind is ds.OverlapKind.DISJOINT
    assert result.parallel is True


def test_nail2_same_file_different_symbol_parallel_with_rebase_warning(tree: Path) -> None:
    """钉子 2：同文件不同符号 ⇒ 可并行，但文案必须提醒「同文件 / rebase」。"""
    result = ds.overlap("a.py::alpha", "a.py::beta", root=tree)
    assert result.kind is ds.OverlapKind.SAME_FILE_DIFFERENT_SYMBOL
    assert result.parallel is True
    text = result.message()
    assert "同文件" in text
    assert "rebase" in text


def test_nail3_same_file_same_symbol_is_serial(tree: Path) -> None:
    """钉子 3：同文件同符号 ⇒ 串。"""
    result = ds.overlap("a.py::alpha", "a.py::alpha", root=tree)
    assert result.kind is ds.OverlapKind.SAME_FILE_SAME_SYMBOL
    assert result.parallel is False


def test_nail4_legacy_paths_match_files_intersect(tree: Path) -> None:
    """钉子 4：不带 `::` 的老写法 ⇒ 判定与今天 `files_intersect()` 逐字相同。

    ★ 交叉核**真源**（`tools/pool/plan.py`），不是自己另写一份"今天的规则"。
    """
    def today_intersects(x: str, y: str) -> bool:
        first = pool_plan.Card(id="X", task="T", title="t", tree="", spec="s", files=(x,))
        second = pool_plan.Card(id="Y", task="T", title="t", tree="", spec="s", files=(y,))
        return bool(pool_plan.files_intersect(first, second))

    for x, y in (("a.py", "a.py"), ("a.py", "b.py")):
        result = ds.overlap(x, y, root=tree)
        assert result.parallel is (not today_intersects(x, y))
        assert (result.kind is ds.OverlapKind.WHOLE_FILE) is today_intersects(x, y)


def test_nail5_unknown_symbol_is_red_not_whole_file(tree: Path) -> None:
    """钉子 5：符号写错 ⇒ 红；**不许**静默当成整文件。"""
    with pytest.raises(ds.UnknownSymbolError) as excinfo:
        ds.declared_symbols("a.py::nope", root=tree)
    assert "nope" in str(excinfo.value)

    # 同一错误也必须从 overlap 这条路上冒出来（否则会"无声地"判成可并行）。
    with pytest.raises(ds.UnknownSymbolError):
        ds.overlap("a.py::nope", "a.py::alpha", root=tree)


# ------------------------------------------------------------------ 边界


def test_whole_file_overrides_symbol_level_same_file(tree: Path) -> None:
    """任一方声明整个文件 ⇒ 压过符号级（串）。"""
    result = ds.overlap("a.py", "a.py::alpha", root=tree)
    assert result.kind is ds.OverlapKind.WHOLE_FILE
    assert result.parallel is False


def test_whole_file_decl_does_not_need_the_file_to_exist(tmp_path: Path) -> None:
    """老写法不读文件 ⇒ 新卡声明「将要新建」的文件照旧能过（向后兼容）。"""
    assert ds.declared_symbols("not/created/yet.py", root=tmp_path) == {ds.WHOLE_FILE}


def test_symbol_declaration_requires_existing_file(tmp_path: Path) -> None:
    """符号级声明要求文件已存在 —— 核不了就红，不猜。"""
    with pytest.raises(ds.UnknownSymbolError):
        ds.declared_symbols("missing.py::alpha", root=tmp_path)


def test_malformed_declaration_is_red(tree: Path) -> None:
    """空路径 / `::` 后没符号 / 两个 `::` ⇒ 坏声明。"""
    for bad in ("", "::alpha", "a.py::", "a.py::alpha::beta"):
        with pytest.raises(ds.BadDeclarationError):
            ds.declared_symbols(bad, root=tree)
