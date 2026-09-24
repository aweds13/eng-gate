"""界面文案上限门（T-G57）的测试 —— 尺子怎么数、门怎么判。

分两半，都是"不跑真界面也能证明"的：
  · **尺子**：剥注释的三条边界（行注释 / 跨行块注释 / HTML 注释剥掉；
    `http://` 与字符串里的中文留下）。
    这一半是必需的 —— 第一版尺子用"看行首"糊过去，注释**续行**全被算成界面文案
    （19 条 → 38 条假账）；第二版用字符串/正则状态机，又被 `/[&<>"']/g`
    这个正则字面量**弄错位**（同样是 38 条）。
  · **门**：≥30 字未登记 → FAIL；登记项被改写 → FAIL；≥20 字超过基线 → FAIL；低于基线 → 只是提示。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import ui_text_audit as audit  # noqa: E402
import ui_text_scan as scan  # noqa: E402


def test_strip_comments_keeps_ui_text_and_drops_comment_text() -> None:
    src = (
        "// 这是行注释里的中文，不算界面文案\n"
        "const a = '这是字符串里的中文，算界面文案';\n"
        "/* 这是块注释\n   它的续行也是注释，不算 */\n"
        "const url = 'http://127.0.0.1:8531/';  // 行内的注释也不该算\n"
        "<!-- HTML 注释里的中文不算\n     续行也不算 -->\n"
        "<div>这是标记里的中文</div>\n"
    )
    code = scan.strip_comments(src)
    gone_all = (
        "这是行注释里的中文",
        "它的续行也是注释",
        "行内的注释也不该算",
        "HTML 注释里的中文",
        "续行也不算",
    )
    for gone in gone_all:
        assert gone not in code, f"注释没剥干净：{gone}"
    for kept in ("这是字符串里的中文", "http://127.0.0.1:8531/", "这是标记里的中文"):
        assert kept in code, f"该留的没留下：{kept}"
    # 行号不能漂（注释换成等长 NUL、换行照留）
    assert len(code.split("\n")) == len(src.split("\n"))
    # NUL 不在片段字符集里 —— 被注释隔开的两段文字不许被粘成一条
    assert "\x00" in code


def test_verdicts_are_a_ratchet_not_a_blanket_ban() -> None:
    long_one = "把复盘写进产品的典型句子就是这一条它长得离谱而且没有任何理由留在界面上"  # 34 字
    frag = [(7, len(long_one), long_one)]

    fails, notes, over, hard = audit.verdicts(frag, {}, 0)
    assert hard == 1 and over == 1
    assert any("L7" in f for f in fails), "未登记的 ≥30 字没有 FAIL"
    assert not notes

    # 登记了就该放行（但基线也得跟着抬起来，否则棘轮那条还是会红）
    known = {audit.key_of(len(long_one), long_one): {"why": "契约点名的 evidence 句"}}
    fails, _, _, _ = audit.verdicts(frag, known, 1)
    assert fails == []

    # 把句子改写一个字：登记项对不上现状 → FAIL（防"改写绕过登记"）
    tweaked = long_one[:-1] + "呢"
    fails, _, _, _ = audit.verdicts([(7, len(tweaked), tweaked)], known, 1)
    assert any("对不上现状" in f for f in fails)

    # 合规的长句数与基线的关系：多了红、少了只是提示
    short = [(1, 20, "一二三四五六七八九十一二三四五六七八九十")]
    fails, notes, over, _ = audit.verdicts(short, {}, 0)
    assert any("只许减" in f for f in fails)
    fails, notes, _, _ = audit.verdicts(short, {}, 3)
    assert fails == [] and any("调成 1" in n for n in notes)


def test_real_repo_passes_the_gate() -> None:
    """真仓库当前状态必须过门（这条红了，就是又把长句写回界面了 —— 或者是尺子坏了）。"""
    known, limit = audit.load()
    fails, notes, n_over, n_hard = audit.verdicts(scan.fragments(), known, limit)
    assert fails == [], f"界面文案上限门不通过：{fails}"
    assert not notes, f"基线该调了（修好的话就把数字调小）：{notes}"
    # ≥30 那一档现在**全部是登记过的待办**（T-G57 逐条清）。门的设计保证"清了却忘了删登记行"
    # 会 FAIL（登记项对不上现状）—— 所以这张表是待办清单，不是豁免。
    assert n_hard <= len(known)
    assert n_over == limit
