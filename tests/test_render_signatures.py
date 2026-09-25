"""每视图签名（T-G69 / `T-G40 §六` 那条残留）—— **防「三方一致地错」**。

黄金层的判据是"与上一次采的逐字节比"，盲区是：**如果黄金自己是在错的那一刻采的**
（视图串了、采集竞态、页面还没画完），那么渲染层 / 假 DOM 探针 / 行为流层会**一致地**把错的当对。
（T-G40 真撞到过一次：`stats` 冷启动时采到了 `focus` 的残留画面，两份黄金同大小、`rows` 都是 51。）

所以有一份**独立的、手写的**"这屏该有什么"：`tools/render_signatures.json`。
它在两个地方生效：
1. **采集的那一刻**（`tools/render_check.mjs`）：不成立就抛，绝不让错的样子落成黄金
   —— 那才是关键时点；
2. **这里**：判这份表本身合不合格 + 判**已提交的 45 份黄金**逐份满足自己的签名。

## 两边实现的关系（老实说清楚）

判定语义只有四条：`must`（必须出现）/ `forbid`（必须不出现）/ `min_count`（出现次数下限）/
`min_rows`（非表头行数下限）—— 解释只写在 JSON 的 `_why` 里。JS 侧与这里的 Python 侧**各实现一遍**，
因为 Node 没有内置 TOML、而这个项目零依赖；两边都是"子串 + 计数"，语义窄到不会各自演化。
（这正是 `复盘/视觉线地图.md` §6 那条"同一个判定写两遍要挑最窄的写法"的用法。）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SIGNATURES = ROOT / "tools" / "render_signatures.json"
GOLDEN = ROOT / "gates" / "render"

#: 一份清单里"有内容"的行 —— 表头（`#`）与空行不算
def _rows(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def check(view: str, text: str, sig: dict) -> list[str]:
    """按签名核对一份清单（与 `tools/render_check.mjs::checkSignature` 同一套语义）。"""
    problems: list[str] = []
    for pat in sig.get("must", []):
        if pat not in text:
            problems.append(f"找不到「{pat}」")
    for pat in sig.get("forbid", []):
        if pat in text:
            problems.append(f"不该出现的「{pat}」出现了")
    for pat, minimum in sig.get("min_count", {}).items():
        got = text.count(pat)
        if got < minimum:
            problems.append(f"「{pat}」只有 {got} 个（要 ≥ {minimum}）")
    if len(_rows(text)) < sig.get("min_rows", 0):
        problems.append(f"清单只有 {len(_rows(text))} 行（要 ≥ {sig['min_rows']}）")
    return problems


@pytest.fixture(scope="module")
def table() -> dict:
    return json.loads(SIGNATURES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def goldens() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(GOLDEN.glob("*.txt"))}


def test_every_view_has_a_signature(table: dict, goldens: dict[str, str]) -> None:
    """每一屏都要有签名 —— 名单**从黄金文件名推**（不手抄一份视图列表）。"""
    views = {name.split("__", 1)[1].removesuffix(".txt") for name in goldens}
    assert views, "gates/render 里一份黄金都没有？"
    missing = sorted(views - set(table["views"]))
    assert not missing, f"这些屏还没有签名：{missing}"


def test_signatures_are_not_vacuous(table: dict, goldens: dict[str, str]) -> None:
    """签名不许是空话：每屏至少一条 `must`；每条 `must` 还得**有辨识度**。

    判据（后半句很重要）：一个模式要是在**半数以上**的屏里都出现，它就证明不了"这是哪一屏" ——
    那正是"三方一致地错"最爱的形态（到处都有的东西，错了也看不出来）。
    """
    per_view = {name: text for name, text in goldens.items()}
    total = len(per_view)
    hits: dict[str, int] = {}
    for text in per_view.values():
        for pat in {p for sig in table["views"].values() for p in sig.get("must", [])}:
            if pat in text:
                hits[pat] = hits.get(pat, 0) + 1
    for view, sig in table["views"].items():
        assert sig.get("must"), f"{view} 的签名里一条 must 都没有（空签名）"
        for pat in sig["must"]:
            assert hits.get(pat, 0) <= total // 2, (
                f"{view} 的 must「{pat}」在 {hits.get(pat)}/{total} 份清单里都出现 —— 没有辨识度，"
                "证明不了『这屏是哪一屏』"
            )


def test_committed_goldens_satisfy_their_signatures(table: dict, goldens: dict[str, str]) -> None:
    """★ 已经提交的 45 份黄金，逐份满足自己的签名（这是关于"判据自身可信"的断言）。"""
    problems: list[str] = []
    for name, text in goldens.items():
        view = name.split("__", 1)[1].removesuffix(".txt")
        for item in check(view, text, table["views"].get(view, {})):
            problems.append(f"{name}：{item}")
    assert not problems, "黄金与签名不符：\n  - " + "\n  - ".join(problems)


def test_the_check_bites_on_a_wrong_screen(table: dict) -> None:
    """★ 证明它咬得住（零件层）：把"另一屏的清单"喂给 `today` 的签名 → 必须报出来。

    这一条就是"三方一致地错"的机器形态：today 的黄金要是采成了全部任务页的样子，
    签名层的两条（找不到进度环 / 出现了全部任务页的输入框）都要响。
    """
    today_sig = table["views"]["today"]
    wrong = (GOLDEN / "desktop__tasks.txt").read_text(encoding="utf-8")
    problems = check("today", wrong, today_sig)
    assert any("circle.chart-ring-progress" in p for p in problems), problems
    assert any("input#allTitle" in p for p in problems), problems
    # 反证：它对自己的清单是干净的（否则上一行只是"什么都报"）
    right = (GOLDEN / "desktop__today.txt").read_text(encoding="utf-8")
    assert check("today", right, today_sig) == []


def test_min_rows_catches_an_almost_empty_capture(table: dict) -> None:
    """再补一条：几乎空的清单（只采到骨架）也要被 `min_rows` 拦住。"""
    skeleton = (
        "# render-manifest v1 viewport=desktop 1280x900 view=today rows=2\n"
        "html>body\t\t0,0,1280,900\t\n"
    )
    problems = check("today", skeleton, table["views"]["today"])
    assert any("只有" in p for p in problems), problems
