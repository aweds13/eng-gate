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
    keys = _keys(".a { color: var(--text) }\n")
    assert {"interaction:hover", "interaction:focus-visible"} <= keys


def test_present_interaction_states_pass() -> None:
    css = ".a:hover { color: var(--text) }\n.b:focus-visible { outline: 2px solid var(--accent) }\n"
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


def test_hover_and_focus_are_the_registered_headline() -> None:
    """两条最要紧的（互动态全缺）必须在登记表里 —— 它们正是"键盘附加功能"的前置条件。"""
    _, known = _real()
    assert "interaction:hover" in known
    assert "interaction:focus-visible" in known


def test_tool_says_it_cannot_judge_beauty() -> None:
    """工具必须在输出里留那句"不证明好看" —— 免得以后有人拿它当审美结论用。"""
    source = (ROOT / "tools" / "style_audit.py").read_text(encoding="utf-8")
    assert "不证明好看" in source
