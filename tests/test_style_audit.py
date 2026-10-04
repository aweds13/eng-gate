"""风格一致性体检（T-G29）的测试 —— 给"融洽里能机器判的那一半"上护栏。

门是什么：`tools/style_audit.py` + `tools/style_baseline.toml`。
它判的是**体系里有没有破例**（重复形状 / 一次性值 / 缺互动态 / 动效越界），
**不判"好不好看"**（那要眼睛—— 这句话工具自己会打出来，测试也钉住它别被删掉）。

两层：
1. **零件层**：喂合成 CSS，钉住"什么样的输入该报什么"；
2. **数据层**：拿真 `app.css` 跑一遍，断言 0 条新问题 + 登记表无僵尸行。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import style_audit as sa  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

# ------------------------------------------------------------------ 零件层


def _keys(css: str) -> set[str]:
    """只取**出问题**的那些（`collect` 同时也会返回判为 OK 的条目）。"""
    return {f.key for f in sa.collect(css) if f.verdict == "SHORT"}


def test_shape_duplicate_is_detected() -> None:
    """同一形状、只有令牌不同 → 必须抓到（`.badge` 那 4 份就是这么回事）。"""
    css = (
        ".badge { color: var(--muted) }\n"
        ".badge.done { background: var(--ok); color: var(--ok) }\n"
        ".badge.doing { background: var(--accent); color: var(--accent) }\n"
    )
    assert "shape:.badge:background+color" in _keys(css)


def test_different_shape_is_not_flagged() -> None:
    """属性集不同 → 不算"同一个形状抄了几份"，不该报。"""
    css = (
        ".x.a { background: var(--ok); color: var(--ok) }\n"
        ".x.b { background: var(--ok) }\n"
    )
    assert not {k for k in _keys(css) if k.startswith("shape:")}


def test_orphan_literal_detected_but_resets_and_tokens_are_not() -> None:
    """只出现一次的裸值要报；纯复位（0/auto）与 var() 不算。"""
    css = (
        ".a { gap: 2px }\n"
        ".b { margin: 0 auto }\n"
        ".c { padding: 0 }\n"
        ".d { gap: var(--sp-1) }\n"
        ".e { gap: 4px }\n"
        ".f { gap: 4px }\n"
    )
    keys = _keys(css)
    assert "literal:gap:2px" in keys  # 只出现一次 → 报
    assert "literal:gap:4px" not in keys  # 出现两次 → 不报
    assert not {k for k in keys if k.startswith("literal:margin")}  # 复位
    assert not {k for k in keys if k.startswith("literal:padding")}  # 复位
    assert not {k for k in keys if "sp-1" in k}  # 令牌


def test_missing_interaction_states_are_detected() -> None:
    """整表没有 `:hover` / `:focus-visible` → 两条都要报（现在的真实现状）。"""
    keys = _keys(".a { color: var(--ink) }\n")
    assert {"interaction:hover", "interaction:focus-visible"} <= keys


def test_present_interaction_states_pass() -> None:
    css = ".a:hover { color: var(--ink) }\n.b:focus-visible { outline: 2px solid var(--accent) }\n"
    keys = _keys(css)
    assert "interaction:hover" not in keys
    assert "interaction:focus-visible" not in keys


def test_motion_over_ceiling_and_infinite_are_detected() -> None:
    css = (
        ".a { transition: opacity .35s }\n"
        ".b { animation: spin 1s infinite }\n"
        ".c { transition: opacity .18s }\n"
    )
    keys = _keys(css)
    assert any(k.startswith("motion:slow:") for k in keys)
    assert any(k.startswith("motion:infinite:") for k in keys)
    assert not any(":.c:" in k for k in keys if k.startswith("motion"))  # 0.18s 在限内


def test_tier_report_counts_values() -> None:
    css = ":root {\n  --r-a: 6px;\n}\n.a { border-radius: var(--r-a) }\n.b { border-radius: 50% }\n"
    labels = {row[0]: row for row in sa.tier_report(sa.parse_rules(css))}
    assert labels["圆角"][1] == 2  # r-a + 50%
    assert labels["圆角"][2] == sa.RADIUS_TIER_CAP


def test_comments_do_not_leak_into_selectors() -> None:
    """回归守卫：T-G27 在对比度门上栽过 —— 注释被吃进选择器会让规则**悄悄漏检**。"""
    css = (
        "/* 说明 */\n"
        ".badge.done { background: var(--ok); color: var(--ok) }\n"
        ".badge.doing { background: var(--accent); color: var(--accent) }\n"
    )
    assert "shape:.badge:background+color" in _keys(css)


# ------------------------------------------------------------------ 数据层（真仓库）


def _real() -> tuple[list[sa.Finding], dict[str, str]]:
    findings = sa.collect(sa.CSS.read_text(encoding="utf-8"))
    known = sa.load_baseline()
    sa.evaluate(findings, known)
    return findings, known


def test_real_stylesheet_has_no_new_incoherence() -> None:
    """真 `app.css` + 真登记表：0 条新问题（这是接进门禁的那条判定）。"""
    findings, _ = _real()
    new = [f.key for f in findings if f.verdict == "NEW"]
    assert new == [], f"出现没登记的一致性破例（要么改回去，要么写进 style_baseline.toml）：{new}"


def test_baseline_rows_all_match_a_real_finding() -> None:
    """登记表里**没有僵尸行**：每条 key 都对应一个真问题。"""
    findings, known = _real()
    keys = {f.key for f in findings}
    assert set(known) <= keys, f"登记表里有对不上现状的行：{sorted(set(known) - keys)}"


def test_hover_and_focus_are_no_longer_the_registered_headline() -> None:
    """T-G45 销账：`:hover` / `:focus-visible` 已经**真有**了 —— 不许再登记回去。

    方向是反着钉的：登记表只能变短。这两条曾经是"每个元素各过各的"最大的来源，
    也是「键盘优先做成附加功能」的前置条件（没有可见焦点，键盘用户根本不知道自己走到哪）。
    所以一旦退回去，这里要红 —— 不是靠人记得。
    """
    css = sa.CSS.read_text(encoding="utf-8")
    findings = {f.key: f.verdict for f in sa.collect(css)}
    for key in ("interaction:hover", "interaction:focus-visible"):
        assert findings.get(key) == "OK", f"{key} 又缺了（互动态那节被删了？）"
    _, known = _real()
    assert not {"interaction:hover", "interaction:focus-visible"} & set(known), (
        "已经修好的互动态又被登记成欠账了 —— 登记表只能变短"
    )


def test_tool_says_it_cannot_judge_beauty() -> None:
    """工具必须在输出里留那句"不证明好看" —— 免得以后有人拿它当审美结论用。"""
    source = (ROOT / "tools" / "style_audit.py").read_text(encoding="utf-8")
    assert "不证明好看" in source


# ==================================================================
# 卡 162 · T-G262 —— 悬停几何位移（INV-71）的反例钉子
# ==================================================================
#
# 包的原话：悬停只许动 background / border / color —— 不许位移、不许换行。
# 判据：`tools/style_audit.py::check_hover_motion` —— 扫 `:hover` 规则的属性集，
# 只许出现不改变几何的属性；出现 transform / margin / padding / height / flex / display 等 ⇒ 红。
# ★ 真实样式表若本来就有位移 ⇒ 如实报，不改样式迁就判据（改法另立卡）。


def test_hover_motion_bites_on_transform() -> None:
    """★ 反例钉子（先红）：`:hover` 改 `transform` ⇒ 必须报红。

    突变证明有牙：把 `check_hover_motion` 从 `collect` 里删掉 ⇒ 本用例当场红
    （坏样例不再被报）。
    """
    css = ".card:hover { transform: translateY(-2px); color: var(--accent) }"
    keys = _keys(css)
    assert any(k.startswith("hover:motion:") for k in keys), (
        "带 transform 的 :hover 没被抓到 —— 判据没牙"
    )
    # 点名那个坏属性
    assert "hover:motion:.card:hover:transform" in keys


def test_hover_motion_bites_on_each_geometry_property() -> None:
    """每种改变几何的属性都要咬（不只是 transform）—— 卡规格点名的全测一遍。"""
    forbidden = (
        ("transform", "translateY(-2px)"),
        ("margin", "4px"),
        ("margin-top", "4px"),
        ("padding", "4px"),
        ("padding-top", "4px"),
        ("height", "40px"),
        ("width", "40px"),
        ("flex", "1"),
        ("display", "block"),
        ("position", "absolute"),
        ("top", "0"),
        ("left", "0"),
        ("border-radius", "8px"),
        ("border-top-width", "2px"),
        ("border", "2px solid var(--accent)"),  # 简写可能含 width
        ("font-size", "16px"),
        ("line-height", "1.5"),
        ("gap", "8px"),
    )
    for prop, value in forbidden:
        css = f".x:hover {{ {prop}: {value} }}"
        keys = _keys(css)
        assert any(k.startswith("hover:motion:") for k in keys), (
            f"`:hover` 改 `{prop}` 没被抓到 —— 漏检改变几何的属性"
        )


def test_hover_motion_allows_non_geometry_properties() -> None:
    """不改几何的属性（background / border-color / color / opacity 等）⇒ 不报。"""
    css = (
        ".card:hover {\n"
        "  background: var(--accent);\n"
        "  background-color: var(--muted);\n"
        "  color: var(--ink);\n"
        "  border-color: var(--accent);\n"
        "  border-top-color: var(--accent);\n"
        "  border-style: solid;\n"
        "  opacity: .9;\n"
        "  box-shadow: 0 2px 8px var(--shadow);\n"
        "  outline: 2px solid var(--accent);\n"
        "  cursor: pointer;\n"
        "  text-decoration: underline;\n"
        "}\n"
    )
    keys = _keys(css)
    bad = [k for k in keys if k.startswith("hover:motion:")]
    assert not bad, f"不该报 hover:motion —— 这些属性不改几何：{bad}"


def test_hover_motion_ignores_non_hover_rules() -> None:
    """非 `:hover` 规则（如 `.x { transform: ... }`）不在本判据范围 —— 不报。"""
    css = ".card { transform: translateY(-2px) }\n.card:hover { color: var(--accent) }"
    keys = _keys(css)
    assert not any(k.startswith("hover:motion:") for k in keys), (
        "非 :hover 规则不该被 hover 判据咬"
    )


def test_real_stylesheet_hover_keeps_geometry_still() -> None:
    """★ 真样式表（`src/web/app.css`）的 `:hover` 规则不许改几何 —— 这是 INV-71 的真东西。

    若真实样式表本来就有 hover 位移 ⇒ 如实报（判据不能为了过而漏检），
    主控另立卡改样式 —— 本测试钉的是「判据在真东西上跑出来的状态」。
    """
    css = sa.CSS.read_text(encoding="utf-8")
    keys = _keys(css)
    hover_motion = [k for k in keys if k.startswith("hover:motion:")]
    if hover_motion:
        # 如实报：真样式表有 hover 几何位移 ⇒ 点名哪条，让主控另立卡改样式
        raise AssertionError(
            "真样式表有 :hover 改了几何属性（不改样式迁就判据，改法另立卡）："
            f"{hover_motion}"
        )
    # 绿：真样式表的 :hover 只动 background/border/color
