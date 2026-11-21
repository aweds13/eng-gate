"""卡 A392（T-AG683）判据 5：上报账这一支**永远不进派活链**。

背景：`tools/pool/usage_ingest.py` 的 `merged_tokens()` / `reported_summary()` 读的是
「外面报来的用量」。它今天接进的是**只读读数面**（`tools/pipeline_view.py` 的 holds 块）；
派活顺序 / 限额判断 / 路线选择**一个消费者都不许有** —— 上报行没有 `account` 字段（归不了
账号）、`cost` 又是可选的（价不知道），并进限额就是把「漏了上报行的下界」当成「还有余量」。

| 文件 | 为什么在名单里 |
|---|---|
| `tools/wb_dispatch.py` | 派活主闸；限额 spent / unpriced 的唯一生产来源 |
| `tools/pool/limits_check.py` | 限额判据本身（`check()` 只吃两个映射） |
| `tools/pool/holds_wiring.py` | 在 `wb_dispatch` 的派活留痕行上被调用 —— 上报数字不许从这儿流出去 |
| `tools/pool/pricing.py` | 卡规格点名的「不许进派活链」三支之一（另两支 speed / usage_ingest） |

扫描口径照 `tests/test_holds_wiring.py::test_holds_wiring_uses_usage_in`：
`ast.parse` 看 import 名单、`ast.Attribute`、`ast.Call` 的 `func.attr`；再加一条
`assert "usage_ingest" not in src` 覆盖字符串形式的间接引用（`getattr` / `importlib`）。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 四个**不许**出现上报账符号的文件（相对 `tools/`）。
TARGETS = (
    "wb_dispatch.py",
    "pool/limits_check.py",
    "pool/holds_wiring.py",
    "pool/pricing.py",
)

#: 三个禁名：模块名 + 两个公开函数。
FORBIDDEN = ("usage_ingest", "merged_tokens", "reported_summary")


def _source(rel: str) -> str:
    return (ROOT / "tools" / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", TARGETS)
def test_read_face_stays_off_the_dispatch_path(rel: str) -> None:
    """判据 5：这四个文件里零 import、零调用上报账那一支（连字符串提及都不许）。"""
    src = _source(rel)
    tree = ast.parse(src)

    modules: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert not [m for m in modules if "usage_ingest" in m], f"{rel} import 了上报账模块：{modules}"
    assert "usage_ingest" not in imported, f"{rel} from-import 了上报账模块：{imported}"

    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (attrs & set(FORBIDDEN)), f"{rel} 取了上报账的属性：{attrs & set(FORBIDDEN)}"

    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (calls & set(FORBIDDEN)), f"{rel} 调了上报账的函数：{calls & set(FORBIDDEN)}"

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (names & set(FORBIDDEN)), f"{rel} 直接用了上报账的名字：{names & set(FORBIDDEN)}"

    # 字符串形式的间接引用（getattr(mod, "merged_tokens") / importlib）也不许点名
    assert "usage_ingest" not in src, f"{rel} 的源码里出现了 usage_ingest（字符串引用？）"


def test_pipeline_view_is_the_read_face_consumer() -> None:
    """反空转：判据 5 的「零」不能靠**谁都没接**成立 —— 读端必须真有消费者。

    `tools/pipeline_view.py` 的 holds 块是这一支唯一的生产调用方；它少了这个 import，
    上面那条零 import 钉子就退化成「两边都没接」也绿。
    """
    src = (ROOT / "tools" / "pipeline_view.py").read_text(encoding="utf-8")
    assert "usage_ingest" in src, "读数面没接上报账 ⇒ 判据 5 的「零」是空转"
    assert "reported_summary" in src, "读数面没调 reported_summary ⇒ 上报量没人看得到"
