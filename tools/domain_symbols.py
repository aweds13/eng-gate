r"""冲突域从**文件级**细化到**符号级**（卡 188 · 台账号 `T-G288`）—— 只标准库、只读、无副作用。

**它治什么**：`tools/pool/plan.py` 的冲突域是**文件级**的 —— `files_intersect()` 就是两个
`files` 集合的精确实例相交。于是「N 张卡要改同一个 2481 行的 `tools/wb_dispatch.py`」被排班器
当成 N 次冲突，**只能一张一张串起来**（本项目 2026-10-03 现量：10 张待派卡同改
`tools/wb_dispatch.py` + `tests/test_wb_dispatch.py`）。而 git 的合并是**行级**的
（三路合并按行/块，不按文件）—— ⇒ ★ **域检查比 git 的合并粒度还粗**。

本模块把判据下探到 **Python 顶层符号**（函数 / 类 / 模块级常量）与它们的**行区间**
（`def x` 到下一个顶层定义之间），回答一句话：**两份声明到底落在同一个符号里没有**。

四种判定（`overlap()` 的返回）：

| `OverlapKind` | 含义 | 能不能并行 |
|---|---|---|
| `DISJOINT` | 文件不相交 | ✅ 可并行 |
| `SAME_FILE_DIFFERENT_SYMBOL` | 同文件、不同符号 | ✅ 可并行，**但要提醒**（撞了就 `rebase`） |
| `SAME_FILE_SAME_SYMBOL` | 同文件、同符号 | ❌ 串 |
| `WHOLE_FILE` | 至少一方声明**整个文件**（老写法，不带 `::`） | ❌ 串（**行为与今天逐字相同**） |

★ **向后兼容是硬要求**：不写 `::` 的声明 ⇒ 判定与 `files_intersect()` **逐字相同**
（`tests/test_domain_symbols.py` 直接对着 `tools/pool/plan.py` 的真源交叉核）。

★ **本模块只交零件、不接线**：**没有**把它接进 `tools/pool/plan.py` / `tools/wb_plan.py`
（那两个文件已被卡 157/161 占着域，接进来我就成了自己要治的第 N 张串行卡）⇒ 接线是另一张小卡。
设计、迁移口径与风险见 `复盘/域与串行-符号级细化.md`。

★ **判定是概率性的，不是保证**：文本级合并工具会**漏检 75~79% 的语义冲突**
[arXiv:2102.11307] —— 符号不相交只说明**大概率**能并行（轻量 Git 特征预测冲突 98% 精度 /
96% 召回 [arXiv:1907.06274]）；**落地撞了就 `rebase` + 留痕**。这两个数是接线的判据，不是本卡的。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

__all__ = [
    "WHOLE_FILE",
    "BadDeclarationError",
    "DomainSymbolError",
    "Overlap",
    "OverlapKind",
    "UnknownSymbolError",
    "declared_symbols",
    "overlap",
    "symbol_ranges",
    "symbols_of",
]

# 本模块自己的仓库根；只用来把**相对路径**默认解析到本树（测试一律显式传 `root=`）。
REPO_ROOT = Path(__file__).resolve().parent.parent

# 「整个文件」的哨兵符号：Python 标识符不可能是 `*`，所以不会与真符号撞名。
# `declared_symbols()` 对不带 `::` 的声明返回 `{WHOLE_FILE}`。
WHOLE_FILE = "*"


class DomainSymbolError(ValueError):
    """符号级域声明的错误根 —— 都是「这份声明核不出来」，不是「两张卡冲突」。"""


class BadDeclarationError(DomainSymbolError):
    """声明写法坏了（空路径 / `::` 后面没东西 / 一个声明里出现两个 `::`）。"""


class UnknownSymbolError(DomainSymbolError):
    """声明的符号在这份文件里不存在（或文件读不到）。

    ★ 必须**红**、**不许静默降级成「整个文件」** —— 静默降级会把「写错了」伪装成
    「它就该和整文件的多有重叠」，判据当场失去牙口。
    """


class OverlapKind(str, Enum):
    """两份域声明的四种关系（取值就是给人看的字符串）。"""

    DISJOINT = "disjoint"                              # 文件不相交
    SAME_FILE_DIFFERENT_SYMBOL = "same-file-different-symbol"
    SAME_FILE_SAME_SYMBOL = "same-file-same-symbol"
    WHOLE_FILE = "whole-file"                          # 至少一方声明整个文件


@dataclass(frozen=True)
class Overlap:
    """两份声明的判定结果 —— `kind` 是四种之一，另附路径与共同符号供人读/复核。"""

    kind: OverlapKind
    a: str
    b: str
    path: str = ""
    symbols: frozenset[str] = field(default_factory=frozenset)

    @property
    def parallel(self) -> bool:
        """能不能同批并行 —— 只有「文件不相交」与「同文件不同符号」为真。"""
        return self.kind in (
            OverlapKind.DISJOINT,
            OverlapKind.SAME_FILE_DIFFERENT_SYMBOL,
        )

    def message(self) -> str:
        """一句人话结论。

        ★ `SAME_FILE_DIFFERENT_SYMBOL` 的文案里必须出现「rebase」与「同文件」（钉子钉住）。
        """
        if self.kind is OverlapKind.DISJOINT:
            return f"文件不相交（{_decl_path(self.a)} vs {_decl_path(self.b)}）→ 可并行"
        if self.kind is OverlapKind.WHOLE_FILE:
            return (
                f"同一整个文件 {self.path}（老写法，不带 `::`，"
                f"行为与今天逐字相同）→ 必须串行"
            )
        if self.kind is OverlapKind.SAME_FILE_SAME_SYMBOL:
            names = "、".join(sorted(self.symbols))
            return f"同文件同符号 {self.path}::{names} → 必须串行"
        return (
            f"同文件不同符号 {self.path} → 可并行，但同文件落地仍可能撞车："
            f"撞了就 rebase 并留痕"
        )


# ================================================================ 零件


def _resolve(path: str, root: Path | str | None) -> Path:
    """把声明里的路径解析成可读的文件路径（绝对路径原样；相对路径按 `root`，默认本仓根）。"""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    base = Path(root) if root is not None else REPO_ROOT
    return base / candidate


def _decl_path(decl: str) -> str:
    """声明里的文件路径部分（`::` 之前，两侧去空白）。"""
    return decl.partition("::")[0].strip()


def _symbol_names(node: ast.stmt) -> list[str]:
    """一条**顶层语句**贡献的符号名（函数 / 类 / 常量）；不是符号 → 空列表。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def symbol_ranges(path: str, *, root: Path | str | None = None) -> dict[str, tuple[int, int]]:
    """一个 Python 文件的**顶层符号 → `(起始行, 结束行)`**（1 基、闭区间）。

    · 起始行 = 该定义的 `lineno`（`def x` / `class X` / 常量赋值那一行）；
    · 结束行 = **下一个顶层定义的前一行**，最后一个符号到**文件末尾** ——
      即卡里写的「`def x` 到下一个顶层定义之间」；
    · 方法 / 嵌套函数**不算**顶层符号（只看 `tree.body` 的直属语句）。

    ★ 行区间是给「同一个符号 / 行区间」判定用的透明凭证；顶层符号的行区间**两两不相交**
    （结束行取「下一个定义 - 1」），所以「行区间相交」与「符号同名」在顶层是等价的。

    同名顶层符号（运行期最后一次绑定生效）以**最后一个**为准。
    """
    source = _resolve(path, root).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    found: list[tuple[int, str]] = []
    for node in tree.body:
        found.extend((node.lineno, name) for name in _symbol_names(node))
    found.sort(key=lambda item: item[0])
    total = len(source.splitlines())
    ranges: dict[str, tuple[int, int]] = {}
    for index, (start, name) in enumerate(found):
        end = found[index + 1][0] - 1 if index + 1 < len(found) else total
        ranges[name] = (start, end)
    return ranges


def symbols_of(path: str, *, root: Path | str | None = None) -> set[str]:
    """一个 Python 文件的**顶层符号名**集合（`symbol_ranges()` 的键，卡里签名的 `set[str]`）。"""
    return set(symbol_ranges(path, root=root))


def declared_symbols(decl: str, *, root: Path | str | None = None) -> set[str]:
    """解析一条域声明 → 它覆盖的符号名集合。

    · `"tools/wb_dispatch.py::main"` → `{"main"}`（★ 会**核对 `main` 真是顶层符号**，
      文件里没有就抛 `UnknownSymbolError` —— 不许静默当成整文件）；
    · `"tools/wb_dispatch.py"`（**不带 `::`**，整个文件）→ `{WHOLE_FILE}`
      （★ **不读文件**：新卡常声明**将要新建**的文件，向后兼容要求它照旧能过）。
    """
    decl = decl.strip()
    path, sep, raw_name = decl.partition("::")
    path = path.strip()
    if not path:
        raise BadDeclarationError(f"声明没有文件路径：{decl!r}")
    if not sep:
        return {WHOLE_FILE}
    name = raw_name.strip()
    if not name:
        raise BadDeclarationError(f"声明的 `::` 后面没有符号名：{decl!r}")
    if "::" in name:
        raise BadDeclarationError(f"一个声明只认一个 `::`：{decl!r}")
    try:
        known = symbols_of(path, root=root)
    except FileNotFoundError as exc:
        raise UnknownSymbolError(f"符号级声明要求文件已存在：{path!r}（{exc}）") from exc
    if name not in known:
        raise UnknownSymbolError(
            f"文件 {path!r} 里没有顶层符号 {name!r}；现有顶层符号：{sorted(known)}"
        )
    return {name}


def overlap(a: str, b: str, *, root: Path | str | None = None) -> Overlap:
    """判两份域声明的关系 → `Overlap`（四种之一）。

    判定顺序：① 路径不同 → `DISJOINT`；② 同路径、任一方声明**整个文件** → `WHOLE_FILE`；
    ③ 同路径、符号集合有交集 → `SAME_FILE_SAME_SYMBOL`；④ 其余 → `SAME_FILE_DIFFERENT_SYMBOL`。

    ★ `WHOLE_FILE` 放在「同符号」之前：**老写法（整文件）必须盖住**任何符号级细化 ——
    这样「不带 `::`」的判定与今天的 `files_intersect()` 逐字相同。
    """
    covered_a = declared_symbols(a, root=root)
    covered_b = declared_symbols(b, root=root)
    path_a = _decl_path(a)
    path_b = _decl_path(b)
    if path_a != path_b:
        return Overlap(OverlapKind.DISJOINT, a, b)
    if WHOLE_FILE in covered_a or WHOLE_FILE in covered_b:
        return Overlap(OverlapKind.WHOLE_FILE, a, b, path=path_a)
    shared = frozenset(covered_a & covered_b)
    if shared:
        return Overlap(OverlapKind.SAME_FILE_SAME_SYMBOL, a, b, path=path_a, symbols=shared)
    return Overlap(OverlapKind.SAME_FILE_DIFFERENT_SYMBOL, a, b, path=path_a)
