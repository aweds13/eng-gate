r"""开工切片生成器（`tools/wb_brief.py`）对**开工切片两处误报**的钉子（卡 112 · T-G209）。

为什么值当测：这两处误报今天连着坑了三张卡的工人（108 / 109 / 110），每张白花一轮解释
"我没停工" / "文档和实际不符"。两条判据都要**正例 + 反例**：

| 判据 | 判什么 |
|---|---|
| ① 范围声明 | 有范围声明（白名单/禁区小节 或 点名文件）⇒ **没有**「停工报主控」；都没有 ⇒ **有** |
| ② 两棵树 | 给了 `--cwd` ⇒ `卡树 <路径>` 与 `主仓 <路径>` 两行都在、路径各对；不给 ⇒ 逐字不变 |

★ 不造真 git 装置：临时目录 + `monkeypatch` 桩（`_git` / `_first_line` / `_checkpoint_blocks`）。
★ 一个字节都不写进真的 `gates/diag/`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_brief  # noqa: E402 —— tools/ 已在 sys.path 上

_STOP = "停工报主控"


# ================================================================ 样本（桩，不落盘）


def _spec_named_files() -> str:
    """本套卡的常态：**没有「白名单」小节**，但逐文件点名 + `## 禁区`。"""
    return (
        "# 卡 999 —— 有范围声明（逐文件点名 + 禁区）\n\n"
        "## 你要做的\n\n"
        "1. 只许改 `tools/wb_brief.py` + 新建 `tests/test_wb_brief.py`。\n\n"
        "## 禁区\n\n"
        "- 不许碰 `tools/pool/**`、`src/**`、`docs/**`\n"
        "- **不要** commit / push / 打 tag\n"
    )


def _spec_whitelist_section() -> str:
    """老卡形态：有独立的「白名单」小节（既有行为，回归钉）。"""
    return (
        "# 卡 998 —— 有白名单小节\n\n"
        "## §3 白名单（只能改这些）\n\n"
        "- `tools/wb_dash.py`\n"
        "- `tests/test_wb_dash.py`\n\n"
        "## §1 要做的事\n\n"
        "动手吧。\n"
    )


def _spec_without_scope() -> str:
    """**两个都没有**：既无范围小节，也无逐一点名的文件 / 路径。"""
    return (
        "# 卡 997 —— 没有范围声明\n\n"
        "## 你要做的\n\n"
        "1. 把那个地方弄好看点，别太吵。\n"
        "2. 顺手把文案顺一顺。\n"
    )


# ================================================================ 判据① 范围声明


def test_scope_named_files_no_stop_sentence() -> None:
    """正例：逐文件点名 + 禁区 ⇒ **没有**那句停工话，且摘出「禁区」小节。"""
    out = wb_brief.section_whitelist(_spec_named_files())
    assert _STOP not in out
    assert "不许碰" in out and "commit" in out


def test_scope_whitelist_section_still_extracted() -> None:
    """正例（回归）：有「白名单」小节 ⇒ 照旧原样摘出、不印停工话。"""
    out = wb_brief.section_whitelist(_spec_whitelist_section())
    assert _STOP not in out
    assert "tools/wb_dash.py" in out and "tests/test_wb_dash.py" in out
    assert "§1 要做的事" not in out  # 不越界摘到下一节


def test_no_scope_at_all_keeps_stop_sentence() -> None:
    """反例：既无范围小节、又无点名文件 ⇒ **有**那句停工话。"""
    out = wb_brief.section_whitelist(_spec_without_scope())
    assert _STOP in out


# ================================================================ 判据② 两棵树


@pytest.fixture()
def stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """桩掉外部世界（git / sync_counts / 交接文档），只留 `section_state` 的真实逻辑。"""
    card_tree = tmp_path / "卡树"
    card_tree.mkdir()

    def fake_git(*args: str, where: Path | None = None) -> str:
        root = Path(where) if where else wb_brief.ROOT
        if args[:2] == ("rev-parse", "--short"):
            return "card123" if root == card_tree else "main456"
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "line/card" if root == card_tree else "line/main"
        if args[:2] == ("status", "--porcelain"):
            # 卡树干净；主仓 1 个被跟踪改动 + 1 个外来未跟踪
            return "" if root == card_tree else " M a.py\n?? b.txt\n"
        return ""

    monkeypatch.setattr(wb_brief, "_git", fake_git)
    monkeypatch.setattr(wb_brief, "_first_line", lambda _cmd: "台账分布-桩")
    monkeypatch.setattr(wb_brief, "_checkpoint_blocks", list)
    return card_tree


def test_cwd_prints_both_trees_with_correct_paths(stubbed: Path) -> None:
    """正例：给了 cwd ⇒ `卡树 <路径>` 与 `主仓 <路径>` 两行都在，且数字各归各的树。"""
    text = wb_brief.build(card="112", spec="", master=False, cwd=str(stubbed))
    lines = text.splitlines()
    card_line = [ln for ln in lines if ln.startswith("- 卡树 ") and "HEAD " in ln]
    main_line = [ln for ln in lines if ln.startswith("- 主仓 ") and "HEAD " in ln]
    assert len(card_line) == 1 and len(main_line) == 1
    assert str(stubbed) in card_line[0] and "card123" in card_line[0]
    assert str(wb_brief.ROOT) in main_line[0] and "main456" in main_line[0]
    # 工作区数字各看各的树（卡树 0/0；主仓 1/1）—— 这正是卡 109 / 110 误报的根因
    assert any("卡树 工作区：被跟踪文件改动 0 个（应 0）+ 外来未跟踪 0 个" in ln for ln in lines)
    assert any("主仓 工作区：被跟踪文件改动 1 个（应 0）+ 外来未跟踪 1 个" in ln for ln in lines)


def test_no_cwd_state_is_byte_identical_to_old(stubbed: Path) -> None:
    """反例：不给 cwd ⇒ 现状段与改动前**逐字一致**（三行、顺序、措辞一个字节不差）。"""
    got = wb_brief.section_state()
    want = "\n".join([
        "- HEAD main456 · 分支 line/main",
        "- 台账分布：台账分布-桩",
        "- 工作区：被跟踪文件改动 1 个（应 0）+ 外来未跟踪 1 个",
    ])
    assert got == want
    assert "卡树" not in got and "主仓" not in got


# ==================== ★ 主控补的钉子（2026-10-02，随卡 112 一起）


def test_truncate_suffix_is_counted_in_bytes() -> None:
    """★ 切片有 **6144 字节硬上限** —— 截断后缀的字节数必须**真的从限额里扣掉**。

    来历（卡 112 的工人如实报的既有缺陷）：后缀 `…(已截断)` 是 **14** 字节，而 `_truncate`
    只扣了 **12** ⇒ 截断后最多**超 2**；调用点截断完还补一个 `\\n`（再 +1）⇒ 最多超 3。
    实测全量 126 张卡里最长的那份 = **6146** > 6144。这条钉子把后缀的字节数与"任何输入都不超"
    一起钉住 —— 光看代码是看不出来的（`…` 与三个汉字都是多字节）。
    """
    suffix = wb_brief.CUT_SUFFIX
    assert len(suffix.encode("utf-8")) == 14, "后缀字节数变了 ⇒ 下面那条预算也要跟着改"
    for limit in (40, 200, wb_brief.BRIEF_MAX_BYTES):
        out = wb_brief._truncate("中" * 5000, limit)
        assert len(out.encode("utf-8")) <= limit, (limit, len(out.encode("utf-8")))
        assert out.endswith(suffix)
    # 短于限额 ⇒ 原样返回（不许加后缀、不许动一个字节）
    assert wb_brief._truncate("短", 100) == "短"


def test_build_call_site_budget_includes_the_trailing_newline() -> None:
    """★ 调用点的预算：截断之后补的那个 `\\n` **也在** 6144 里（所以要用 `上限 - 1`）。"""
    text = wb_brief._truncate("中" * 5000, wb_brief.BRIEF_MAX_BYTES - 1) + "\n"
    assert len(text.encode("utf-8")) <= wb_brief.BRIEF_MAX_BYTES
