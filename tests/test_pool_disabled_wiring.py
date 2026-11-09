r"""禁用表的**生产接线**（卡 E105 · T-AG614）—— 三处入口都问同一个判据。

卡 A353（`T-AG566`）把 magpie 的 `disabled.go` 搬成了 `tools/pool/model_registry.py` 里的
`assert_not_disabled`，18 条钉子全绿 —— 但**没有任何生产调用方**：用户在禁用表里写一行，
一个请求都不会被拒。这份文件钉的是「接上了没有、是不是同一个判据、文案有没有还在撒谎」。

| 钉子 | 钉哪一位 |
|---|---|
| `test_every_production_entry_asks_the_same_judge` | 三处各恰一次判据调用 |
| `test_gateway_forwards_the_status_code_not_a_fixed_404` | `if blocked` 分支用状态码变量 |
| `test_gateway_keeps_the_four_old_blocks_at_404` | 四支老判定**仍然** 404 |
| `test_docs_stop_claiming_zero_production_callers` | 不再写「零生产调用方」，模块地图点名三条入口 |

★ 全部只读源码（AST / 文本），不起进程、不写盘。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

JUDGE = "assert_not_disabled"
# 判据只有一份：这三样只许出现在 `model_registry` 里，入口函数体里出现就是第二份判据
SECOND_COPY = ("glob_match", "load_disabled", "match_disabled")
ENTRIES = (
    ("tools/wb_dispatch.py", "main"),
    ("tools/pool/gateway.py", "_model_block"),
    ("tools/pool_mcp.py", "tool_pool_dispatch"),
)


def _func(rel: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel} 里没有函数 {name}（钉子的锚点被改名/删了）")


def _calls(node: ast.AST) -> list[str]:
    """函数体里调用到的**末段名字**：`f()` 记 `f`，`mod.f()` 也记 `f`。

    两种写法都算「问了那个判据」—— 本钉要判的是**问没问同一个判据**，不是 import 风格。
    """
    out: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            out.append(func.id)
        elif isinstance(func, ast.Attribute):
            out.append(func.attr)
    return out


def test_every_production_entry_asks_the_same_judge() -> None:
    """三处入口各问一次 `assert_not_disabled`；谁自己读表 / 自己 glob，就说明判据裂成了两份。"""
    for rel, name in ENTRIES:
        calls = _calls(_func(rel, name))
        assert calls.count(JUDGE) == 1, (
            f"{rel}::{name} 里 {JUDGE} 出现 {calls.count(JUDGE)} 次（应当恰 1 次）："
            "入口必须问那个唯一的判据，不许自己读禁用表"
        )
        for bad in SECOND_COPY:
            assert bad not in calls, (
                f"{rel}::{name} 直接调了 {bad} —— 那是 `model_registry` 的内部件，"
                "在入口里再造一份判据迟早与它漂开"
            )


def test_gateway_forwards_the_status_code_not_a_fixed_404() -> None:
    """网关拿到 `_model_block` 的判定后**按它给的状态码回**：「禁用」是 403，不是 404。"""
    fn = _func("tools/pool/gateway.py", "route_once")
    branches = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name) and node.test.id == "blocked"
    ]
    assert len(branches) == 1, (
        f"route_once 里 `if blocked:` 分支应有且只有一处，实测 {len(branches)}"
    )
    returns = [n for n in ast.walk(branches[0]) if isinstance(n, ast.Return)]
    assert returns, "`if blocked:` 分支里没有 return —— 判了不拦等于没判"
    statuses = [
        arg for ret in returns
        if isinstance(ret.value, ast.Call) and len(ret.value.args) >= 2
        for arg in [ret.value.args[1]]
    ]
    assert statuses, (
        "出口不是 `_fail(协议, 状态码, 原因)` 的形状 ⇒ 锚点变了，先读代码再改钉子"
    )
    for arg in statuses:
        fixed = isinstance(arg, ast.Constant) and arg.value == 404
        assert not fixed, (
            "gateway 的 blocked 出口写死了 404：禁用 / 读不懂禁用表都该是 403"
            "（404 = 「没有这个模型」，403 = 「有，但你现在不许用」）"
        )


def test_gateway_keeps_the_four_old_blocks_at_404() -> None:
    """四支老判定（找不到号池目录 / 批准集空 / 未批 / 快照过期）**仍然** 404 —— 别顺手全改 403。"""
    fn = _func("tools/pool/gateway.py", "_model_block")
    src = ast.unparse(fn)
    for marker in ("找不到号池目录", "批准集是空的", "不在批准集里", "模型快照不可信"):
        assert marker in src, f"`_model_block` 里少了「{marker}」这支（老判定的文案被改了？）"
    four = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert four, "_model_block 一个 return 都没有"
    assert "404" in src, (
        "`_model_block` 里 404 一个字都没有了 —— 要么四支老判定被改成了 403，"
        "要么状态码被挪出了这个函数；两种都不是本卡要的（先读代码再改钉子）"
    )


def test_docs_stop_claiming_zero_production_callers() -> None:
    """接线之后，那两句「零生产调用方」就是撒谎 —— 连同模块地图一起改。"""
    registry = (ROOT / "tools" / "pool" / "model_registry.py").read_text(encoding="utf-8")
    tests = (ROOT / "tests" / "test_pool_disabled.py").read_text(encoding="utf-8")
    for rel, text in (("tools/pool/model_registry.py", registry),
                      ("tests/test_pool_disabled.py", tests)):
        assert "零生产调用方" not in text, (
            f"{rel} 里还写着「零生产调用方」—— 三处入口接上之后这句话就不成立了"
        )
    modules = (ROOT / "docs" / "subsystems" / "pool" / "modules.toml").read_text(encoding="utf-8")
    block = modules.split('name = "model_registry.py"', 1)
    assert len(block) == 2, "模块地图里没有 model_registry.py 这一条（锚点变了）"
    entry = block[1].split("[[module]]", 1)[0]
    for name in ("wb_dispatch", "gateway", "pool_mcp"):
        assert name in entry, f"模块地图的 model_registry 条要点名生产调用方 {name}"
    assert "禁用" in entry, "模块地图的 model_registry 条要提禁用表（它现在不只是注册表）"
