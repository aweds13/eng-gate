"""对比度审美门（T-G27）的测试 —— 给"新加的护栏"也上护栏。

门是什么：`tools/contrast_audit.py` + `tools/contrast_baseline.toml`。
它量的是**字在底上看不看得清**（WCAG 对比度），是本项目第一条**不需要浏览器**的审美门。
判定是**棘轮**：现状已登记的 18 条欠账不算通过；出现**没登记过**的不足、
或登记过的**变差**，才 FAIL。

测试分两层：
1. **零件层**：喂合成数据，钉住"什么样的输入该判成什么"（真仓库里造不出"变差"来验）；
2. **数据层**：拿**真 `app.css` + 真登记表**跑一遍，断言当前没有新欠账 —— 顺带把
   "这张表与真组合一一对应、没有僵尸行"也钉住，以后谁改令牌把字改糊，这里先红。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import contrast_audit as ca  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

# ------------------------------------------------------------------ 零件层


def test_contrast_extremes_and_known_values() -> None:
    """公式对着 WCAG 的定义：黑白 21、同色 1，并钉几个已知值。"""
    assert ca.contrast("#000000", "#ffffff") == 21.0
    assert ca.contrast("#ffffff", "#ffffff") == 1.0
    # workbench 包里自己标的：白字 on #2f6feb 是 4.57（跟它文档里的数字对上）
    assert ca.contrast("#ffffff", "#2f6feb") == 4.57
    # 三字节简写要认
    assert ca.contrast("#fff", "#000") == ca.contrast("#ffffff", "#000000")


def test_mix_over_composites_like_color_mix() -> None:
    """18% 状态色铺在白卡上：合成结果必须等于手算的 0.18*c + 0.82*base。"""
    assert ca.mix_over("#22c55e", "#ffffff", 0.18) == "#d7f5e2"
    assert ca.mix_over("#000000", "#ffffff", 0.0) == "#ffffff"
    assert ca.mix_over("#000000", "#ffffff", 1.0) == "#000000"


def test_token_blocks_resolve_nested_var() -> None:
    """`--toast-bg: var(--text)` 这种一层套一层要能解到字面色值（T-G27 修 `.toast` 就是靠它）。"""
    css = (
        ":root {\n  --a: #123456;\n  --b: var(--a);\n}\n\n"
        '[data-theme="dark"] {\n  --b: #ffffff;\n}\n'
    )
    tokens = ca.token_blocks(css)
    assert ca.resolve("--b", tokens["light"]) == "#123456"
    assert ca.resolve("--b", tokens["dark"]) == "#ffffff"


def _pair(theme: str = "light", fg: str = "--x", bg: str = "--y") -> ca.Pair:
    return ca.Pair(theme, fg, bg, ca.AA_NORMAL, "测试用")


def _run(ratio_fg: str, ratio_bg: str, known: dict[str, dict[str, object]]) -> ca.Row:
    tokens = {
        "light": {"--x": ratio_fg, "--y": ratio_bg},
        "dark": {"--x": ratio_fg, "--y": ratio_bg},
    }
    rows = ca.evaluate([_pair()], tokens, known)
    assert len(rows) == 1
    return rows[0]


def test_new_shortfall_is_a_failure_not_a_pass() -> None:
    """没登记过的不足 → NEW（门禁要红）。这一条是整个门存在的前提。"""
    row = _run("#999999", "#ffffff", {})
    assert row.verdict == "NEW"
    assert row.ratio < ca.AA_NORMAL


def test_registered_shortfall_is_known_and_not_a_failure() -> None:
    """登记过、且没有变差 → KNOWN（不红）。"""
    row = _run("#999999", "#ffffff", {"light:--x on --y": {"ratio": 2.85}})
    assert row.verdict == "KNOWN"


def test_registered_pair_that_gets_worse_is_a_failure() -> None:
    """登记过但**悄悄改坏了** → WORSE（门禁要红）。这是棘轮的牙齿。"""
    row = _run("#bbbbbb", "#ffffff", {"light:--x on --y": {"ratio": 2.85}})
    assert row.verdict == "WORSE"


def test_registered_pair_that_now_passes_is_flagged_for_deletion() -> None:
    """登记过、现在已经达标 → FIXED（提示删行，**不红** —— 否则修好了反而提交不了）。"""
    row = _run("#000000", "#ffffff", {"light:--x on --y": {"ratio": 1.9}})
    assert row.verdict == "FIXED"


def test_eps_tolerates_rounding_noise() -> None:
    """登记值比实测只高 0.01（四舍五入噪声）不算"变差" —— 否则每次浮点抖动都会红。"""
    measured = ca.contrast("#999999", "#ffffff")
    tokens = {"light": {"--x": "#999999", "--y": "#ffffff"}}
    known = {"light:--x on --y": {"ratio": measured + 0.01}}
    row = ca.evaluate([_pair()], tokens, known)[0]
    assert row.verdict == "KNOWN"
    # 反过来：真的差下去（超过 EPS）必须红
    known_bad = {"light:--x on --y": {"ratio": measured + 0.5}}
    assert ca.evaluate([_pair()], tokens, known_bad)[0].verdict == "WORSE"


# ------------------------------------------------------------------ 数据层（真仓库）


def _real() -> tuple[list[ca.Pair], dict[str, dict[str, str]], dict[str, dict[str, object]]]:
    css = ca.CSS.read_text(encoding="utf-8")
    return ca.declared_pairs() + ca.badge_pairs(css), ca.token_blocks(css), ca.load_baseline()


def test_real_stylesheet_has_no_new_or_worse_contrast_shortfall() -> None:
    """真 `app.css` + 真登记表：0 条新欠账、0 条变差（这是接进门禁的那条判定）。"""
    pairs, tokens, known = _real()
    bad = [r for r in ca.evaluate(pairs, tokens, known) if r.verdict in {"NEW", "WORSE"}]
    assert bad == [], (
        f"出现没登记的对比度不足（要么改回去，要么写进 contrast_baseline.toml）：{bad}"
    )


def test_baseline_rows_all_match_a_real_pair() -> None:
    """登记表里**没有僵尸行**：每一条 key 都对应一个真组合（`--strict` 迟早要靠这个清空）。"""
    pairs, _, known = _real()
    keys = {p.key for p in pairs}
    assert set(known) <= keys, f"登记表里有对不上任何组合的行：{sorted(set(known) - keys)}"


def test_dark_theme_is_fully_clean() -> None:
    """暗色主题一条欠账都不该有（登记表 18 条**全是亮色**）—— 防止有人偷偷给暗色也开口子。"""
    pairs, tokens, known = _real()
    dark_bad = [
        r
        for r in ca.evaluate(pairs, tokens, known)
        if r.pair.theme == "dark" and r.ratio < r.pair.minimum
    ]
    assert dark_bad == [], f"暗色出现不达标：{[r.pair.key for r in dark_bad]}"


def test_badge_shortfalls_are_actually_detected() -> None:
    """回归守卫：`.badge.done/.doing/.hard` 那三条「色块里同色写字」必须被抓到。

    第一版漏掉了 done/doing —— 因为选择器正则把**注释**也算进了选择器
    （`.badge.done` 头上正好有一行注释，`.badge.hard` 头上没有，所以只抓到它）。
    这条用例钉住"三块都要在"，不然那种漏抓会静悄悄地回来。
    """
    pairs, tokens, known = _real()
    keys = {p.key for p in pairs}
    for token in ("--ok", "--accent", "--danger"):
        assert f"light:{token} on mix({token} 18% over --card)" in keys
    ratios = {r.pair.key: r.ratio for r in ca.evaluate(pairs, tokens, known)}
    assert ratios["light:--ok on mix(--ok 18% over --card)"] < 2.0  # 最糟的那条，1.96
