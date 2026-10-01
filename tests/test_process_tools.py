"""流程工具自己的护栏（T-G52）—— 让"报错更准"这件事也被钉住。

T-G52 做的三件都是**流程**上的：TOML 预检说清哪一行、交接文档的台账数字一键刷、
前端热表生成。它们不产品化，但每一样都在消掉**重复踩的坑**，所以同样要有判据 ——
判据是"喂一份坏的进去，它得说出**人话**"（这正是它们存在的唯一理由）。

三条：
1. `scripts/check_toml.py`：坏 TOML → 报出「第 N 行 + 原文 + 常见原因」；真仓库全过。
2. `tools/sync_counts.py`：数字替换只动那五个数；真台账与交接文档一致。
3. `tools/ui_hotmap.py`：视图→函数的映射读得对（`today → renderToday`，且函数真存在）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import check_toml  # noqa: E402 —— 需要先用 sys.path 挂上 scripts/
import sync_counts  # noqa: E402 —— 同上（tools/）
import ui_hotmap  # noqa: E402


def test_toml_preflight_names_the_line(tmp_path: Path) -> None:
    """坏 TOML 必须**指名道姓**（第几行 + 原文 + 常见原因）—— 这条坑一个会话踩了 8 次。"""
    bad = tmp_path / "bad.toml"
    bad.write_text('gaps = "他说"你好""\n', encoding="utf-8")
    problems = check_toml.check_one(bad)
    assert len(problems) == 1, f"应当报 1 个问题：{problems}"
    msg = problems[0]
    assert "第 1 行" in msg and "gaps" in msg, msg
    assert "ASCII 双引号" in msg, "要说出常见原因，不然还得自己想"
    # 反证：好 TOML 不报（否则这道预检会把正常提交也拦下）
    good = tmp_path / "good.toml"
    good.write_text('gaps = "他说「你好」"\n', encoding="utf-8")
    assert check_toml.check_one(good) == []


def test_real_ledger_passes_the_preflight() -> None:
    """真仓库当前必须全过（台账是唯一真源，它坏了两道审计门会一起红）。"""
    assert check_toml.check_all() == []


def test_sync_counts_only_touches_the_numbers() -> None:
    """只替换那五个数字，别的字一个不动（否则会把交接文档写花）。"""
    text = "台账进度：done 1 / partial 2 / todo 3 / deferred 4（共 10 条；**豁免 0 条**）"
    got = {"done": 174, "partial": 2, "todo": 3, "deferred": 3}
    fixed = sync_counts.rewrite(text, got, 182)
    want = "台账进度：done 174 / partial 2 / todo 3 / deferred 3（共 182 条；**豁免 0 条**）"
    assert fixed == want
    assert sync_counts.rewrite(fixed, got, 182) == fixed, "已经是新的就别再改（幂等）"

def test_real_handoff_counts_are_in_sync() -> None:
    """真台账与两份交接文档现在必须一致 —— 不一致就该跑 `tools/sync_counts.py`。"""
    got, total = sync_counts.counts()
    _, total_entries = sync_counts.counts()
    assert sum(got.values()) <= total_entries <= total
    for path in sync_counts.HANDOFFS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert sync_counts.rewrite(text, got, total) == text, \
            f"{path.name} 里的台账分布过期了：跑 python -X utf8 tools/sync_counts.py"


def test_hotmap_reads_the_view_dispatch() -> None:
    """热表要读对「视图 → 函数」，而且要能发现"函数不见了"这种烂锚点。"""
    text = ui_hotmap.INDEX.read_text(encoding="utf-8")
    fns = ui_hotmap.functions(text)
    rows = dict()
    for views, fn in ui_hotmap.dispatch(text):
        for v in views:
            rows[v] = fn
    assert rows.get("today") == "renderToday"
    assert rows.get("setting") == "renderSetting"
    # 三个智能视图共用同一个函数（`renderSmart`）—— 这正是热表要能表达的形状
    assert rows.get("important") == rows.get("planned") == rows.get("flagged")
    for fn in rows.values():
        assert fn in fns, f"热表指向的 {fn} 在 index.html 里找不到定义（锚点烂了）"
    assert len(fns) > 50, "顶层函数数量级不对，函数扫描的正则可能失效了"


def test_toml_preflight_survives_cjk_paths() -> None:
    """★ T-G190：`toml_files()` 必须能读**中文名**的 TOML（`docs/归置-机械码.toml`，T-G182 加的）。

    病：它 `subprocess.run(..., text=True)` **不给 encoding** → 按本机区域编码（这台机器 GBK）解，
    而 `git -c core.quotepath=false` 吐的是**原始 UTF-8 字节** → 读线程抛 UnicodeDecodeError →
    `communicate()` 拿到 None → `.stdout.split()` 报 AttributeError。满仓只有这一个 TOML 名带中文，
    所以它一进库，**pytest 门就红**（而单跑这条测试时若带了 `-X utf8` 反而是绿的 —— 假绿陷阱）。

    判据：那个中文名必须**原样**出现在清单里（编码解错时它根本到不了这一行）。
    """
    names = [p.relative_to(ROOT).as_posix() for p in check_toml.toml_files()]
    assert "docs/归置-机械码.toml" in names, (
        "中文名的 TOML 没出现在清单里 —— 要么它被移走了（那就改这条断言），",
        "要么 git 输出又被按区域编码解了（见本用例 docstring 的 T-G190）。",
        f"现在的清单：{names}",
    )
