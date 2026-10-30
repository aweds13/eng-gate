"""卡 A341（T-AG543 · F34）：caller 模型白名单**只收窄**的八条钉子。

判据来源：`复盘/卡/卡A341-一个号只能调哪些模型.md` 的钉子表 —— 八个用例名**逐字同名**。
本文件**不写**任何 ruff 豁免注释（派活铁律），所以 `tools/` 的路径注入走模块级普通语句、
模块导入走 `importlib.import_module()`（不是 import 语句 ⇒ 不触发 ruff 的 E402）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

mr = importlib.import_module("pool.model_registry")
wd = importlib.import_module("wb_dispatch")

narrow_for_caller = mr.narrow_for_caller
clean_caller_patterns = mr.clean_caller_patterns


def test_narrow_empty_patterns_passes_through() -> None:
    """`patterns = ()` ⇒ 原样返回 `tuple(allowed)`（照 magpie `Restricted()`「空 = 不受限」）。"""
    allowed = ("a/x", "b/z", "c/*/y")
    assert narrow_for_caller("codebuddy", allowed, ()) == allowed
    assert narrow_for_caller("codebuddy", (), ()) == ()
    # list 进来也要变成 tuple 原样回去（逐字，不改一条）
    assert narrow_for_caller("codebuddy", ["a/x", "b/z"], []) == ("a/x", "b/z")


def test_narrow_is_subset_never_wider() -> None:
    """8 组固定用例：任何 patterns 下结果都**只能**是 allowed 的子集。"""
    cases: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("a/x", "a/y", "b/z"), ("a/*",)),
        (("a/x",), ("*",)),
        (("*", "a/x"), ("a/*",)),
        (("codebuddy/a", "codebuddy/a/b"), ("codebuddy/*",)),
        (("a/x", "b/z"), ("A/X", "NOPE/*")),
        ((), ("a/*",)),
        (("a/x",), ("x", "y")),
        (("p/m-1", "p/m-2", "q/m-3"), ("p/*", "q/m-3")),
    ]
    for allowed, patterns in cases:
        got = narrow_for_caller("codebuddy", allowed, patterns)
        assert set(got) <= set(allowed), (allowed, patterns, got)
        # 顺序也照 allowed 走（不许重排、不许插队）
        assert list(got) == [m for m in allowed if m in set(got)], (allowed, patterns, got)


def test_narrow_glob_crosses_slash() -> None:
    """`*` **跨斜杠**（照 magpie `compileGlob`：`(?is)^` + `.*` + `$`）。"""
    # 卡规格钉子逐字：`("codebuddy/*",)` 命中 `codebuddy/a/b`（`*` 跨斜杠，原样匹配就中）
    assert narrow_for_caller(
        "codebuddy", ("codebuddy/a/b",), ("codebuddy/*",)) == ("codebuddy/a/b",)
    # 多段通配也能跨斜杠
    assert narrow_for_caller("codebuddy", ("a/x/y/z",), ("a/*/z",)) == ("a/x/y/z",)
    # ★ 剥掉 `codebuddy/` 之后剩下的裸 `*` 也会命中**带斜杠**的别名（`other/a/b`）——
    #   这是 2026-10-30 用户裁定「池前缀可省」的直接后果（见 `narrow_for_caller` docstring），
    #   结果仍然 ⊆ `allowed`，不是放宽；照实钉在这里，免得日后被当成 bug「修掉」。
    got = narrow_for_caller(
        "codebuddy", ("codebuddy/a/b", "codebuddy/a", "other/a/b"), ("codebuddy/*",))
    assert got == ("codebuddy/a/b", "codebuddy/a", "other/a/b")


def test_narrow_case_insensitive() -> None:
    """第一层（caller 收窄）大小写不敏感（照 magpie `strings.EqualFold`）。"""
    assert narrow_for_caller("codebuddy", ("a/x",), ("A/X",)) == ("a/x",)
    assert narrow_for_caller("codebuddy", ("A/X",), ("a/x",)) == ("A/X",)
    assert narrow_for_caller("codebuddy", ("a/x/y",), ("A/*/Y",)) == ("a/x/y",)


def test_narrow_unmatched_yields_empty_tuple() -> None:
    """命不中就**全禁**（空元组），且**不是**「没设限」的语义。"""
    got = narrow_for_caller("codebuddy", ("a/x", "b/z"), ("不存在/*",))
    assert got == ()
    assert got != ("a/x", "b/z"), "空结果不许退回「不收窄」——那等于放宽"
    # 对照：同样两个模型，不给 patterns 才是「不收窄」
    assert narrow_for_caller("codebuddy", ("a/x", "b/z"), ()) == ("a/x", "b/z")


def test_clean_patterns_rejects_no_slash_and_over_500() -> None:
    """`clean_caller_patterns()`：形状与两条上限越界 ⇒ 抛，**不许**静默丢。"""
    with pytest.raises(mr.ModelRegistryError) as no_slash:
        clean_caller_patterns(["a"])
    assert "/" in str(no_slash.value)

    many = [f"p/m{i}" for i in range(501)]
    with pytest.raises(mr.ModelRegistryError) as too_many:
        clean_caller_patterns(many)
    assert "500" in str(too_many.value)

    # 边界另一侧：正好 500 条要收
    assert len(clean_caller_patterns(many[:500])) == 500
    # `/a` 与 `a/` 非法
    for bad in ("/a", "a/", "a/b/"):
        with pytest.raises(mr.ModelRegistryError):
            clean_caller_patterns([bad])
    # 单条超 300 字符非法（301 字符，含 `/`）
    with pytest.raises(mr.ModelRegistryError):
        clean_caller_patterns(["p/" + "m" * 299])
    assert len(clean_caller_patterns(["p/" + "m" * 298])[0]) == 300
    # trim + 不区分大小写去重（保留第一次出现的写法）
    assert clean_caller_patterns(["  a/x  ", "A/X", "b/*/y"]) == ("a/x", "b/*/y")
    # `a/*/x` 合法（`*` 跨斜杠）
    assert clean_caller_patterns(["a/*/x"]) == ("a/*/x",)


def test_two_layers_have_different_case_rules() -> None:
    """两层大小写口径**故意不同**：第二层逐字、第一层不敏感 —— 不许被「统一」掉。"""
    # 第二层：`model_rejected()` 逐字 ⇒ 只差大小写也拒
    rejected = wd.model_rejected("CodeBuddy/X")
    assert rejected
    assert "未授权模型" in rejected

    # 拿一个真实在册的模型，把它改成全大写：第二层必须拒，第一层必须命中
    sample = next(
        (m for m in wd.effective_allowed_models("codebuddy") if m.upper() != m), None)
    assert sample is not None, "codebuddy 池里至少要有一个带字母的模型"
    shouted = sample.upper()
    assert wd.model_rejected(shouted, "codebuddy"), "第二层是逐字的，改大小写必须拒"
    assert narrow_for_caller("codebuddy", (sample,), (shouted,)) == (sample,), \
        "第一层是不区分大小写的，改大小写必须仍然命中"


def test_pool_prefix_is_optional_in_pattern() -> None:
    """池前缀可省：`codebuddy/glm-5.3` 命中裸名 `glm-5.3`；`codebuddy/*` 命中全部裸名。

    用户裁定（2026-10-30）：不放宽 `clean_caller_patterns()` 的 `/` 规则（那是 magpie
    `CleanModels` 的合规边界），改 `narrow_for_caller()` 的匹配侧 —— 每条 pattern 额外剥掉
    **恰好等于当前池**的前缀再匹配一次。
    """
    bare = wd.effective_allowed_models("codebuddy")
    assert bare and all("/" not in name for name in bare), bare

    exact = [name for name in bare if name == "glm-5.3"]
    if not exact:
        exact = [bare[0]]
    assert narrow_for_caller("codebuddy", tuple(bare), (f"codebuddy/{exact[0]}",)) == tuple(exact)

    assert narrow_for_caller("codebuddy", tuple(bare), ("codebuddy/*",)) == tuple(bare)
    # 前缀剥离也要大小写不敏感
    assert narrow_for_caller("codebuddy", tuple(bare), ("CodeBuddy/*",)) == tuple(bare)
    # glob 在前缀之后照样跨斜杠
    assert narrow_for_caller("codebuddy", ("a/x/y",), ("codebuddy/a/*",)) == ("a/x/y",)


def test_other_pools_prefix_never_matches() -> None:
    """**只剥当前池自己的前缀**：`codearts/…` 写在 `codebuddy` 账号下 ⇒ 不跨池命中。"""
    bare = wd.effective_allowed_models("codebuddy")
    assert narrow_for_caller("codebuddy", tuple(bare), ("codearts/deepseek*",)) == ()
    assert narrow_for_caller("codebuddy", tuple(bare), ("codearts/*",)) == ()
    # 反向也一样：`codebuddy/…` 在 codearts 池里不许命中
    codearts = wd.effective_allowed_models("codearts")
    assert narrow_for_caller("codearts", tuple(codearts), ("codebuddy/*",)) == ()


def test_pool_prefix_alone_matches_nothing() -> None:
    """剥完是空串（pattern 就是 `codebuddy/`）⇒ 不命中，**不许**退化成「全命中」。"""
    bare = wd.effective_allowed_models("codebuddy")
    got = narrow_for_caller("codebuddy", tuple(bare), ("codebuddy/",))
    assert got == ()
    assert got != tuple(bare), "空尾不许变成全命中 —— 那就是放宽"


def test_reverse_narrow_cannot_widen() -> None:
    """反向钉子：把收窄改成「命不中就保留」（白名单翻黑名单）⇒ 本用例必须红。"""
    allowed = ("a/x", "b/z")
    got = narrow_for_caller("codebuddy", allowed, ("a/*",))
    assert got == ("a/x",)
    assert "b/z" not in got
    assert got != allowed
