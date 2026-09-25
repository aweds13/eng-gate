"""非文字对比度 3.0 表（T-G70）的测试 —— 给「不看字也得看得见」的那一层上护栏。

门是什么：`tools/contrast_audit.py` 里的两张表 ——
  · `AA_NONTEXT_PAIRS`（**判据**，WCAG 1.4.11，阈值 3.0）：控制边界 / 状态点 / 勾选圈 /
    图表数据笔 / 逾期红条；
  · `AA_NONTEXT_EXEMPT`（**纯装饰**，只量不判）：分隔线、卡片边、图表网格 / 环轨道 / 空格、
    悬停描边、toast 按钮边框 —— 实测值照打，理由逐条写在表里。
跑法就是门禁那一条：`python -X utf8 tools/contrast_audit.py --strict`
（`run_gates.py` 的 `contrast`）。

测试分三层：
1. **数据层**：拿真 `app.css` 跑一遍 —— 非文字一条都不许低于 3.0；
2. **接地层**：表里的每一行都必须**真在样式表里被这么用过**（防"纸面表"），
   而且**输入框/下拉/文本域的边框一律走 `--border-control`**（防有人把它改回分隔线令牌）；
3. **零件层**：证明它咬得住（把值改回旧的样子必须红）+ 豁免表不许悄悄加行、不许留"假豁免"。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import contrast_audit as ca  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _real() -> tuple[str, dict[str, dict[str, str]]]:
    css = ca.CSS.read_text(encoding="utf-8")
    return css, ca.token_blocks(css)


# ------------------------------------------------------------------ 数据层（真仓库）


def test_real_stylesheet_has_no_nontext_shortfall() -> None:
    """真 `app.css`：非文字这 14 条一条都不许低于 3.0（这是接进门禁的那条判定）。"""
    _, tokens = _real()
    bad = [
        (r.pair.key, r.ratio)
        for r in ca.evaluate(ca.nontext_pairs(), tokens, {})
        if r.ratio < ca.AA_NONTEXT
    ]
    assert bad == [], f"非文字图形低于 3.0：{bad}"


def test_every_nontext_pair_covers_both_themes_at_the_3_0_floor() -> None:
    """非文字表两套主题都要有，而且阈值必须是 3.0（不是 4.5）—— 免得有人"顺手拔高"当文字管。"""
    pairs = ca.nontext_pairs()
    assert {p.theme for p in pairs} == {"light", "dark"}
    assert all(p.minimum == ca.AA_NONTEXT for p in pairs)
    assert all(p.kind == "图形" for p in pairs), "非文字那档的 key 必须带 kind 前缀"


def test_control_boundary_pairs_are_the_ones_whose_only_cue_is_the_border() -> None:
    """★ T-G70 找到的那条真缺陷：**框的底与卡片底同为 `--panel`**，边框是唯一线索。

    这条钉的是"为什么这一对必须在表里"：`--border-control` 对 `--panel` 与 `--bg`
    两对都得在（模态/命令面板里的输入框底是 `--bg`）。少一对就等于那个框没人管。
    """
    keys = {p.key for p in ca.nontext_pairs()}
    assert "light:图形 --border-control on --panel" in keys
    assert "dark:图形 --border-control on --panel" in keys
    assert "light:图形 --border-control on --bg" in keys
    assert "dark:图形 --border-control on --bg" in keys


# ------------------------------------------------------------------ 接地层（从 CSS 真读）


def test_nontext_tokens_are_really_used_as_non_text() -> None:
    """表里的每一行都必须**真在样式表里被当边界/图形用过** —— 防"纸面表"（T-G42 的同一类病：
    一个原子换个写法就整条从表里消失，门会显得是绿的）。"""
    css, _ = _real()
    for fg, _bg, where in ca.AA_NONTEXT_PAIRS:
        pattern = (
            rf"(?:border(?:-\w+)?|background|fill|stroke)\s*:[^;]*var\(\s*{re.escape(fg)}\s*\)"
        )
        assert re.search(pattern, css), f"{fg} 在 app.css 里没有被当边界/图形用过：{where}"


def test_every_form_control_border_uses_the_control_token() -> None:
    """输入框 / 下拉 / 文本域的边框**一律** `--border-control` —— 这是防漂的那一条。

    为什么不是"看一眼注释就算了"：`--border` 与 `--border-control` 只差一个词，
    谁新写一条控件规则时顺手复制上面的 `.card` 就会把边界又变成 1.23。
    解析用门自己的 `_RULE`（不另写一套 CSS 解析器 —— 两套解析器早晚对不上）。
    """
    css, _ = _real()
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    checked = 0
    for selector, body in ca._RULE.findall(stripped):  # noqa: SLF001 —— 故意的：共用门的解析
        sel = selector.strip().replace("\n", " ")
        if not re.search(r"\b(input|select|textarea)\b", sel):
            continue
        for decl in re.findall(r"border(?:-\w+)?\s*:[^;]+", body):
            if "solid var(--" not in decl:
                continue
            checked += 1
            assert "--border-control" in decl, (
                f"{sel} 的边框又写回分隔线令牌了（要 3.0 的控件边界，不是装饰）：{decl.strip()}"
            )
    assert checked >= 6, f"只查到 {checked} 条控件边框 —— 解析器或样式表变味了，别让这条空转"


# ------------------------------------------------------------------ 零件层（证明它咬得住）


def _row_with_control_border(value: str) -> ca.Row:
    css = (
        ":root {\n"
        "  --panel: #ffffff;\n"
        f"  --border-control: {value};\n"
        "}\n\n"
        '[data-theme="dark"] {\n  --panel: #131c2e;\n  --border-control: #63738f;\n}\n'
    )
    tokens = ca.token_blocks(css)
    pair = ca.Pair("light", "--border-control", "--panel", ca.AA_NONTEXT, "测试用", kind="图形")
    rows = ca.evaluate([pair], tokens, {})
    assert len(rows) == 1
    return rows[0]


def test_it_bites_when_the_control_border_falls_back_to_the_decorative_value() -> None:
    """★ 证明它咬得住：把控件边界写回 `--border` 那个值（就是 T-G70 之前的样子）→ 当场红。

    这条是整张表存在的意义。没有它，这张表只是文档 —— 而文档不会在提交前拦人。
    """
    row = _row_with_control_border("#7c8798")  # 现在的值
    assert row.ratio >= ca.AA_NONTEXT
    assert row.verdict == "PASS"

    old = _row_with_control_border("#e2e8f0")  # T-G70 之前：--border 的值
    assert old.ratio < ca.AA_NONTEXT, "1.23 这种值必须被算成不达标"
    assert old.verdict == "NEW", "没登记过的不足 → NEW，门要红"

    darkish = _row_with_control_border("#cbd5e1")  # 连 --border-strong 那档也不够
    assert darkish.ratio < ca.AA_NONTEXT


# ------------------------------------------------------------------ 豁免表（纯装饰）


def test_exempt_rows_are_measured_and_really_below_the_floor() -> None:
    """豁免表里每一条**必须真的低于 3.0**：哪天它够了，就该删行（否则是"假豁免"）。

    这是这张表的活性判据 —— 它跟文字那档的 `FIXED` 是同一个精神：修好了要销账。
    """
    _, tokens = _real()
    rows = ca.evaluate(ca.exempt_pairs(), tokens, {})
    assert rows, "豁免表不该是空的（纯装饰是判出来的，不是删出来的）"
    ok = [(r.pair.key, r.ratio) for r in rows if r.ratio >= ca.AA_NONTEXT]
    assert ok == [], f"这些其实够 3.0，别留在豁免表里（提到 3.0 表，或删行）：{ok}"


def test_exempt_list_is_frozen_so_exempting_is_a_visible_edit() -> None:
    """豁免**不许悄悄加**：条数钉住，加一条就得动这条断言（台账 `[exceptions]` 的同一精神）。

    ★ 豁免比登记更危险：一条"这是装饰"的理由没人复核，就会变成"以后什么都豁免"。
      所以这里连**条数**一起钉 —— 让它至少是个**有痕迹**的动作。
    """
    assert len(ca.AA_NONTEXT_EXEMPT) == 6, "加了豁免条目就要改这条断言（并写进复盘）"
    assert len(ca.exempt_pairs()) == 11, "每条只在自己声明的主题上生成（toast 那条只有暗色）"
    for fg, bg, themes, why in ca.AA_NONTEXT_EXEMPT:
        assert themes and set(themes) <= {"light", "dark"}, f"{fg} on {bg} 的主题写错了"
        assert len(why) >= 20, f"{fg} on {bg} 的豁免理由太短（要能让下一个人复核）：{why!r}"


def test_exempt_rows_are_grounded_in_the_theme_they_claim() -> None:
    """豁免的行必须**对自己那套主题**是真的：那套主题里这两个令牌都存在。

    第一版就在这儿踩过一次：亮色的 toast 底是 `--ink`（9.37，本来就过），只有暗色才退到
    `--panel-2` —— 不写主题就会对着一个**亮色里不存在**的搭配写一行豁免。
    """
    _, tokens = _real()
    for fg, bg, themes, where in ca.AA_NONTEXT_EXEMPT:
        for theme in themes:
            ca.resolve(fg, tokens[theme])  # 令牌不存在 → SystemExit（这就是判据）
            ca.resolve(bg, tokens[theme])
        assert where.strip(), f"{fg} on {bg} 没写理由"
