r"""speed / pricing / usage_ingest.merged_tokens **永不进派活链**的钉子（卡 A393 · T-AG684）。

## 病

三件东西今天都是「有模块、零生产消费者」：`tools/pool/speed.py` 回答的是「什么情况不许报速度」，
`tools/pool/pricing.py` 连价目表都没有（`Price` 一律由调用方构造），
`tools/pool/usage_ingest.py` 的 `merged_tokens()` 是读端合并器、零调用点。
「零消费者」本身是事实，但事实没有守卫：谁明天在 `tools/wb_dispatch.py` 顶部加一行
`from pool import speed`，`pytest` 会全绿、`ruff` 会全绿、门禁会全绿。
本文件要消灭的正是这个「看不见」—— 把用户会话里反复重申的红线（speed / pricing /
usage_ingest.merged_tokens 不许进派活链：派活顺序、限额判断、路线选择都不许消费它们）
写成可执行的静态判据。决定写在 `docs/decisions/0013-nopin-not-wired.md`。

## 判据判什么

- `test_dispatch_side_imports_never_touch_banned_modules`
  判据 1：派活侧四文件的 import 末段与四个禁名零相交（前提自证 ≥ 60 个顶层模块名）。
- `test_dispatch_chain_never_names_merged_tokens`
  判据 2 ①：派活链五文件的名字级集合里没有 `merged_tokens` / `reported_summary`。
- `test_usage_ingest_importers_stay_in_whitelist`
  判据 2 ②：`usage_ingest` 的 importer 只许落在白名单里，且 MCP 写面必在其中。
- `test_positive_control_is_wb_dispatch_usage_in`
  判据 2 ③ 正对照：活账的分子仍走 `wb_dispatch.usage_in`。
- `test_search_triplet_has_zero_consumers`
  判据 3A：搜索三模块名在 `tools/` + `scripts/` 的 import 集合里恒空。
- `test_adr_exists_and_passes_machine_check`
  判据 5：ADR 0013 在盘、四节齐全、点全九个名字、过真检查器。

## 为什么走 AST

这四个字（`speed` / `pricing` / `merged_tokens`）在本仓**合法地**出现在很多地方：
`tools/pool/route.py` 的别名元组里 `"speed"` 是 FASTEST 的路由**名字**（不是模块）；
`tools/pool/speed.py` 的 docstring 提到 magpie 的 `usage_ingest.go`（另一个仓的同名文件）；
`tools/pool/usage_ingest.py` 自己的注释里就写着 `merged_tokens`。
文本 grep 会把这三处全部误判成「接线了」。所以判据一律只认 `ast.Import` / `ast.ImportFrom`
的模块名与 `_code_names()` 收的 Name / Attribute —— 与 `tests/test_no_window.py:15`、
`tests/test_pool_pricing.py:311`、`tests/test_pool_speed_tells.py:282` 同一个手法。

★ 判据 2 ② 今天是「白名单的子集 + 必含 `tools/pool_mcp.py`」，不是字面上的「相等」：
`tools/pipeline_view.py` 是卡 A392（F43 读端接线）的产物，A392 落之前它还不 import
`usage_ingest`。等 A392 落地，白名单两项都在集合里，这条断言**自动等价于相等**；
在那之前按相等写会红，而红的原因是「隔壁卡还没落」，不是本卡的红。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 判据 1 的扫面：**派活侧四个文件** —— 派活器本体 / 限额判断 / 路线选择 / 网关。
DISPATCH_SIDE = (
    "tools/wb_dispatch.py",
    "tools/pool/limits_check.py",
    "tools/pool/route.py",
    "tools/pool/gateway.py",
)

#: 判据 2 的扫面：派活链 = 上面四份 + 活账薄层（它拿分子）。
SCHEDULING_CHAIN = DISPATCH_SIDE + ("tools/pool/holds_wiring.py",)

#: 判据 1 的禁名：按 import 的**末段**比，三种写法一网打尽。
BANNED_TAILS = frozenset({"speed", "pricing", "usage_ingest", "merged_tokens"})

#: 判据 2 ① 的禁名：名字级（Name / Attribute），不是文本级。
BANNED_NAMES = frozenset({"merged_tokens", "reported_summary"})

#: 判据 2 ② 的白名单：MCP 写面（卡 A364）+ 只读读数面（卡 A392 / F43）。
ALLOWED_IMPORTERS = frozenset({"tools/pool_mcp.py", "tools/pipeline_view.py"})

#: 判据 2 ② 的必含项：MCP 写面 `usage_report` 是今天唯一合法的 importer。
REQUIRED_IMPORTER = "tools/pool_mcp.py"

#: 判据 3A 的三个模块名（保留为库，只钉零消费者 —— 一行代码都不删）。
SEARCH_TRIPLET = frozenset({"search", "searcher", "web_fetch"})

#: 判据 5 的 ADR：编号是今天 `docs/decisions/` 里的下一个空号。
ADR = ROOT / "docs" / "decisions" / "0013-nopin-not-wired.md"

#: 判据 5 ③ 要求 ADR 正文逐字出现的九个名字 —— 没有名字的禁令没法对账。
#: 卡规格那一行列了 8 个（3 个模块文件 + merged_tokens + 4 个派活侧文件），
#: 第 9 个是判据 2 ① 的另一个禁名 reported_summary —— 两个禁名要一起成文才守得住。
NAMED_IN_ADR = (
    "speed.py",
    "pricing.py",
    "usage_ingest.py",
    "merged_tokens",
    "reported_summary",
    "tools/wb_dispatch.py",
    "tools/pool/limits_check.py",
    "tools/pool/route.py",
    "tools/pool/gateway.py",
)

#: 判据 5 ② 的四节（顺序由 `scripts/check_docs.py` 判，这里只判在不在）。
ADR_SECTIONS = ("## 背景与问题", "## 候选方案", "## 决定", "## 把握程度")


# ---------------------------------------------------------------- AST 工具
def _tree(rel: str) -> ast.Module:
    """按仓内相对路径解析一份源码的 AST（不存在就当场红，不许静默跳过）。"""
    path = ROOT / rel
    assert path.is_file(), f"{rel} 不存在 —— 判据空转"
    return ast.parse(path.read_text(encoding="utf-8"), filename=rel)


def _production_files() -> list[Path]:
    """`tools/` + `scripts/` 下的全部 `*.py`（不含 `tests/`、不含 `__pycache__`）。"""
    files = sorted(
        path
        for top in ("tools", "scripts")
        for path in (ROOT / top).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert len(files) > 100, f"扫描范围只扫到 {len(files)} 个文件 —— 判据空转"
    return files


def _import_roots(tree: ast.Module) -> set[str]:
    """import 的**首段**模块名（判据 1 的前提自证用；与卡规格的 30 / 6 / 9 / 19 同口径）。"""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _import_tails(tree: ast.Module) -> set[str]:
    """import 的**末段**模块名（判据 1 的比对项）。

    `import pool.speed` / `from pool.speed import x` / `from pool import speed` 三种写法
    在这里同值 —— ★ 前两种只看 module 就够，**第三种的名字挂在 alias 上**（module 是光秃秃的
    `pool`），所以 ImportFrom 必须把 `module + "." + alias.name` 也收进来。
    只收 module 会让 `from pool import speed` 整条漏网 —— 正是本条判据要钉的那个写法。
    """
    tails: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tails.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            head = "." * node.level + (node.module or "")
            tails.add(head.split(".")[-1])
            for alias in node.names:
                tails.add((head + "." + alias.name).split(".")[-1])
    return tails


def _code_names(tree: ast.Module) -> set[str]:
    """名字级集合（体例照 `tests/test_pool_pricing.py:311`）：只收这四种节点，不收 docstring。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.Attribute):
            root: ast.expr = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _imports_module(tree: ast.Module, name: str) -> bool:
    """这份源码有没有把模块 `name` 接进来 —— 四种写法全覆盖（含相对 import）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if name in alias.name.split("."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if name in (node.module or "").split("."):
                return True
            if name in {alias.name for alias in node.names}:
                return True
    return False


# ---------------------------------------------------------------- 判据 1
def test_dispatch_side_imports_never_touch_banned_modules():
    """判据 1：四个派活侧文件的 import 末段与四个禁名零相交（前提自证在前）。"""
    roots_total = 0
    tails: dict[str, set[str]] = {}
    for rel in DISPATCH_SIDE:
        tree = _tree(rel)
        roots = _import_roots(tree)
        assert roots, f"{rel} 一个 import 都没解析出来 —— 判据空转"
        roots_total += len(roots)
        tails[rel] = _import_tails(tree)
    assert roots_total >= 60, (
        f"四个派活侧文件合起来只有 {roots_total} 个顶层模块名（卡规格要求至少 60）"
        " —— 扫描器退化了，先修它，别信这条绿"
    )

    hits = [
        f"{rel} → {name}"
        for rel, names in tails.items()
        for name in sorted(names & BANNED_TAILS)
    ]
    assert hits == [], (
        "派活侧接进了禁名模块（speed / pricing / usage_ingest / merged_tokens 不许进派活链）："
        + "\n".join(hits)
    )


# ---------------------------------------------------------------- 判据 2 ①
def test_dispatch_chain_never_names_merged_tokens():
    """判据 2 ①：派活链五个文件的名字级集合里没有 `merged_tokens` / `reported_summary`。"""
    hits = []
    for rel in SCHEDULING_CHAIN:
        names = _code_names(_tree(rel))
        assert len(names) > 30, f"{rel} 的名字级集合只有 {len(names)} 个 —— 判据空转"
        hits.extend(f"{rel} → {name}" for name in sorted(names & BANNED_NAMES))
    assert hits == [], (
        "派活链上出现了读端合并器的名字（活账的分子只许来自 wb_dispatch.usage_in）："
        + "\n".join(hits)
    )


# ---------------------------------------------------------------- 判据 2 ②
def test_usage_ingest_importers_stay_in_whitelist():
    """判据 2 ②：接 `usage_ingest` 的文件只许落在白名单里，且 MCP 写面必在其中。

    今天钉的是「子集 + 必含」而不是字面「相等」：白名单的第二项
    `tools/pipeline_view.py` 是卡 A392 的产物，A392 落之前它还不 import；A392 落之后
    这条断言自动等价于相等。理由写在 ADR 0013 的「把握程度」一节。
    """
    importers = set()
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _imports_module(tree, "usage_ingest"):
            importers.add(path.relative_to(ROOT).as_posix())

    outsiders = sorted(importers - ALLOWED_IMPORTERS)
    assert outsiders == [], (
        "白名单之外出现了 usage_ingest 的 importer —— 第三个消费者要先改白名单与 ADR 0013："
        + "\n".join(outsiders)
    )
    assert REQUIRED_IMPORTER in importers, (
        f"{REQUIRED_IMPORTER} 不再 import usage_ingest —— MCP 写面（卡 A364）的接面被拆了？"
    )


# ---------------------------------------------------------------- 判据 2 ③
def test_positive_control_is_wb_dispatch_usage_in():
    """判据 2 ③ 正对照：活账的分子仍走 `wb_dispatch.usage_in`，不是 `merged_tokens`。

    分子被换掉比多接一个 import 更糟 —— 所以这条是「必须还在」，不是「不许出现」。
    """
    tree = _tree("tools/pool/holds_wiring.py")
    found = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_usage_in"):
            continue
        for inner in ast.walk(node):
            is_usage_in = isinstance(inner, ast.ImportFrom) and inner.module == "wb_dispatch"
            if is_usage_in and "usage_in" in {alias.name for alias in inner.names}:
                found = True
    assert found, (
        "tools/pool/holds_wiring.py 的 `_usage_in()` 不再 `from wb_dispatch import usage_in`"
        " —— 分子被换掉了？改这条判据之前先改 ADR 0013"
    )


# ---------------------------------------------------------------- 判据 3A
def test_search_triplet_has_zero_consumers():
    """判据 3A：搜索三模块名在 tools/ + scripts/ 的 import 集合里恒为空集（保留为库）。"""
    hits = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        hits.extend(
            f"{rel} → {name}" for name in sorted(SEARCH_TRIPLET) if _imports_module(tree, name)
        )
    assert hits == [], (
        "有人把搜索三模块接进产品码了（判据 3 立的是「保留为库、零消费者」）："
        + "\n".join(hits)
    )


# ---------------------------------------------------------------- 判据 5
def test_adr_exists_and_passes_machine_check():
    """判据 5：ADR 0013 在盘、文件名合规、四节齐全、点全九个名字、过真检查器。"""
    assert ADR.is_file(), ADR
    assert re.match(r"^([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$", ADR.name), ADR.name

    text = ADR.read_text(encoding="utf-8")
    for section in ADR_SECTIONS:
        assert section in text, f"ADR 缺段落 {section}"
    assert re.search(r"(?m)^Status:[ \t]*Accepted[ \t]*$", text), (
        "ADR 缺「Status: Accepted」"
    )
    assert re.search(r"(?m)^来源:[ \t]*(\S.*)$", text), "ADR 缺「来源:」"

    missing = [name for name in NAMED_IN_ADR if name not in text]
    assert missing == [], "ADR 正文没点这些名字（没有名字的禁令没法对账）：" + "、".join(missing)

    spec = importlib.util.spec_from_file_location(
        "check_docs_393", ROOT / "scripts" / "check_docs.py"
    )
    assert spec is not None and spec.loader is not None
    cd = importlib.util.module_from_spec(spec)
    # 必须先登记进 sys.modules：check_docs 里有 dataclass，exec_module 时
    # dataclasses 会按 cls.__module__ 反查模块，没登记就 AttributeError。
    sys.modules[spec.name] = cd
    spec.loader.exec_module(cd)
    assert cd.check(ROOT).problems == []
