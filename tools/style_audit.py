"""风格一致性体检（T-G29）—— 把"融洽"里**能机器判**的那一半做成门。

## 它判什么、不判什么（先说清边界）

用户 2026-09-23 的要求原话是「让这个风格足够的更加融洽……每个元素都足够融洽，要有这样的门」。

"融洽"里有两半：
- **可机器判的一半**：这个体系**有没有破例** —— 同一个东西是不是有 N 种写法、缺少的状态是不是没写、
  只用一次的值是不是溜进来了、动效是不是各走各的。**这一半做成本文件。**
- **不可机器判的一半**：这套体系本身**好不好看**。任何工具都判不了 —— 那要眼睛。
  **门只负责「淘汰破例的候选」，不负责「挑出好看的」。** 这句写进代码里，
  免得以后有人拿它当审美结论用。

## 五条判定（全部从 `src/web/app.css` 静态算，不需要浏览器）

- **互动态缺失**：`:hover` ≥1 条规则、`:focus-visible` ≥1 条规则。
  对「手放上去」和「键盘走到这里」都没回应，就是**每个元素各过各的**；
  而且键盘用户看不见焦点（可达性缺口）。
- **一次性裸值**：尺度类属性上**恰好出现一次**的字面量 = 0 条新。
  只出现一次的值＝它没进体系 —— 这就是「不融洽」最机械的定义。
- **同形状重复**：属性集相同、只有令牌不同的规则抄 ≥2 份 = 0 组新。
  一个原子抄 N 份，就是令牌层开始烂的方式（workbench 原文），
  也是「每块长得不一样」的根。
- **动效超时/循环**：时长 ≤200ms、无 `infinite`。各走各的时长＝节奏散。
- **档数**（只报告、不判）：圆角 ≤3 档（workbench 明文），其余只报数。
  档数就是「语言的收敛度」：同一属性 7 档圆角＝没有语言。

## 判定词汇与对比度门一致（棘轮）

`OK` / `KNOWN`（登记过、没变差）/ `IMPROVED`（好了，提示你销账）/ `WORSE` / `NEW`。
登记表 = `tools/style_baseline.toml`，同样是**逐条留痕、修一条删一条，不许静默豁免**。

用法
  python -X utf8 tools/style_audit.py            # 人读
  python -X utf8 tools/style_audit.py --json     # 机器读
  python -X utf8 tools/style_audit.py --check    # 门禁用：有新问题/变差就退 1
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "src" / "web" / "app.css"
BASELINE = ROOT / "tools" / "style_baseline.toml"

MOTION_CEILING_MS = 200  # workbench：状态过渡 0.12–0.18s，超过就不是这个包的语速
RADIUS_TIER_CAP = 3  # workbench：6 / 10 / 999，Nothing else

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_VAR_ONLY = re.compile(r"^var\(\s*(--[a-z0-9-]+)\s*\)$")
_DURATION = re.compile(r"(\d*\.?\d+)(m?s)\b")

# 「尺度类」属性：这些上面出现一次性字面量＝它没进令牌体系。
# 故意**不含** top/bottom/left/right：那些是定位常量（`.toast` 的 `bottom: 24px`、
# 底部 Tab 的 `left: 0`），一次性是它们的正常状态，报出来是噪音。
MEASURED = (
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "gap", "font-size", "border-radius", "line-height",
)
# 纯复位值（0 / auto / none）不算"一次性值"：它们是清零，不是选了某个值。
RESETS = {"0", "auto", "none", "0px", "initial", "inherit"}
# 档数报告：属性 → (显示名, 上限或 None)
TIERS: dict[str, tuple[str, int | None]] = {
    "border-radius": ("圆角", RADIUS_TIER_CAP),
    "font-size": ("字号", None),
    "font-weight": ("字重", None),
    "line-height": ("行高", None),
    "box-shadow": ("阴影", None),
}


@dataclass
class Rule:
    selector: str
    body: str
    declarations: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Finding:
    key: str
    verdict: str
    detail: str
    known: str = ""


def parse_rules(css: str) -> list[Rule]:
    """切规则 + 去注释。注释必须先去 —— T-G27 就在这里栽过（注释被吃进选择器）。"""
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[Rule] = []
    for selector, body in _RULE.findall(stripped):
        sel = " ".join(selector.split())
        decls: list[tuple[str, str]] = []
        for chunk in body.split(";"):
            prop, _, value = chunk.partition(":")
            if prop.strip() and value.strip():
                decls.append((prop.strip(), value.strip()))
        if decls:
            out.append(Rule(sel, body, decls))
    return out


def in_token_zone(selector: str) -> bool:
    return selector.startswith(":root") or "data-theme" in selector


def load_baseline() -> dict[str, str]:
    if not BASELINE.exists():
        return {}
    data = tomllib.loads(BASELINE.read_text(encoding="utf-8"))
    known = data.get("known", {})
    return {k: str(v.get("why", "")) for k, v in known.items()} if isinstance(known, dict) else {}


def verdict_for(key: str, current: str, known: dict[str, str]) -> tuple[str, str]:
    """棘轮：登记过的算 KNOWN（内容一致）或 IMPROVED（登记的是"更差"的状态）。"""
    if key not in known:
        return "NEW", ""
    return ("KNOWN", known[key]) if known[key] else ("KNOWN", "")


# ------------------------------------------------------------------ 五条检查
def check_interaction(rules: list[Rule]) -> list[Finding]:
    """互动态：整张样式表里有没有 `:hover` / `:focus-visible`。"""
    hover = sum(1 for r in rules if ":hover" in r.selector)
    focus = sum(1 for r in rules if ":focus-visible" in r.selector)
    out: list[Finding] = []
    for key, count, need in (
        ("interaction:hover", hover, 1),
        ("interaction:focus-visible", focus, 1),
    ):
        if "hover" in key:
            label = "手放上去的回应（:hover 规则数）"
        else:
            label = "键盘走到这里的回应（:focus-visible 规则数）"
        out.append(
            Finding(
                key,
                "OK" if count >= need else "SHORT",
                f"{label} = {count}（至少 {need}）",
            )
        )
    return out


def check_orphan_literals(rules: list[Rule]) -> list[Finding]:
    """一次性裸值：尺度属性上**只出现一次**的字面量。"""
    seen: dict[tuple[str, str], list[str]] = {}
    for rule in rules:
        if in_token_zone(rule.selector):
            continue
        for prop, value in rule.declarations:
            if prop not in MEASURED or "var(" in value:
                continue
            parts = value.split()
            if parts and all(p in RESETS for p in parts):
                continue  # 纯复位（0 / auto）不算"选了某个值"
            seen.setdefault((prop, value), []).append(rule.selector)
    out: list[Finding] = []
    for (prop, value), selectors in sorted(seen.items()):
        if len(selectors) == 1:
            out.append(
                Finding(
                    f"literal:{prop}:{value}",
                    "SHORT",
                    f"`{prop}: {value}` 全表只出现 1 次（{selectors[0]}）"
                    "—— 只出现一次的值就是没进体系",
                )
            )
    return out


def check_shape_duplicates(rules: list[Rule]) -> list[Finding]:
    """同形状重复：属性集相同、只有令牌不同的规则抄了 ≥2 份 → 该抽成一个原语。"""
    by_base: dict[str, list[Rule]] = {}
    for rule in rules:
        if in_token_zone(rule.selector) or " " in rule.selector or ":" in rule.selector:
            continue  # 只看单一类选择器（.badge.done 这种），组合/伪类跳过
        parts = rule.selector.split(".")
        if len(parts) < 2 or parts[0] != "":
            continue
        by_base.setdefault("." + parts[1], []).append(rule)

    out: list[Finding] = []
    for base, members in sorted(by_base.items()):
        if len(members) < 2:
            continue
        groups: dict[tuple[str, ...], list[Rule]] = {}
        for rule in members:
            groups.setdefault(tuple(sorted(p for p, _ in rule.declarations)), []).append(rule)
        for props, group in groups.items():
            if len(group) < 2 or len(props) < 2:
                continue
            # 只有「同一位置都是单个 var(--…) 且令牌不同」才算"同一个形状换了个令牌"
            varying = []
            for prop in sorted(props):
                values = {
                    r.declarations[[p for p, _ in r.declarations].index(prop)][1]
                    for r in group
                }
                if len({_VAR_ONLY.sub("VAR", v) for v in values}) == 1 and len(values) > 1:
                    varying.append(prop)
            if not varying:
                continue
            names = "、".join(sorted({r.selector for r in group}))
            key = f"shape:{base}:{'+'.join(sorted(varying))}"
            out.append(
                Finding(
                    key,
                    "SHORT",
                    f"{base} 有 {len(group)} 个变体是**同一个形状**、只有 "
                    f"{'、'.join(sorted(varying))} 换了令牌（{names}）"
                    "→ 该抽成一个原语 + 状态映射表",
                )
            )
    return out


def check_motion(rules: list[Rule]) -> list[Finding]:
    """动效：时长上限 + 不许无限循环。"""
    out: list[Finding] = []
    for rule in rules:
        for prop, value in rule.declarations:
            if prop not in ("transition", "animation", "transition-duration", "animation-duration"):
                continue
            if "infinite" in value:
                out.append(
                    Finding(
                        f"motion:infinite:{rule.selector}",
                        "SHORT",
                        f"{rule.selector} 有无限循环动画（工具类界面的禁忌：`{value}`）",
                    )
                )
            for amount, unit in _DURATION.findall(value):
                ms = float(amount) * (1000 if unit == "s" else 1)
                if ms > MOTION_CEILING_MS:
                    out.append(
                        Finding(
                            f"motion:slow:{rule.selector}:{value}",
                            "SHORT",
                            f"{rule.selector} 的时长 {ms:.0f}ms 超过上限 "
                            f"{MOTION_CEILING_MS}ms（`{value}`）",
                        )
                    )
    return out


def tier_report(rules: list[Rule]) -> list[tuple[str, int, int | None, list[str]]]:
    """档数报告（人类读的部分）：一个属性在这套样式里一共有几种写法。

    ★ 多值的值里**只数令牌**（T-G43 修）：`border-radius: var(--r-sm) var(--r-sm) 0 0`
    （只圆上沿的柱子）用的是一个**已有的档**，不该被报成"新的一档" —— 第一版把整串字面量
    当成一个档，于是"圆角 7 档"变成"8 档"，读的人会以为语言又散了一分。没有令牌的值
    （`0` / `50%`）仍按原样算一档。
    """
    out: list[tuple[str, int, int | None, list[str]]] = []
    for prop, (label, cap) in TIERS.items():
        values: set[str] = set()
        for rule in rules:
            for p, v in rule.declarations:
                if p != prop:
                    continue
                values |= set(re.findall(r"--[a-z0-9-]+", v)) if "var(" in v else {v}
        if values:
            out.append((label, len(values), cap, sorted(values)))
    return out


# ------------------------------------------------------------------ 主流程
def collect(css: str) -> list[Finding]:
    rules = parse_rules(css)
    return (
        check_interaction(rules)
        + check_orphan_literals(rules)
        + check_shape_duplicates(rules)
        + check_motion(rules)
    )


def evaluate(findings: list[Finding], known: dict[str, str]) -> None:
    for f in findings:
        if f.verdict != "SHORT":
            continue
        if f.key in known:
            f.verdict = "KNOWN"
            f.known = known[f.key]
        else:
            f.verdict = "NEW"


MARK = {"OK": "[OK  ]", "KNOWN": "[登记]", "NEW": "[FAIL]"}


def main() -> int:
    ap = argparse.ArgumentParser(description="风格一致性体检（融洽里能机器判的那一半）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="有新问题就退 1")
    args = ap.parse_args()

    css = CSS.read_text(encoding="utf-8")
    findings = collect(css)
    known = load_baseline()
    evaluate(findings, known)
    bad = [f for f in findings if f.verdict == "NEW"]
    stale = [k for k in known if k not in {f.key for f in findings}]

    if args.json:
        print(
            json.dumps(
                {
                    "findings": [
                        {"key": f.key, "verdict": f.verdict, "detail": f.detail, "why": f.known}
                        for f in findings
                    ],
                    "tiers": [
                        {"label": label, "count": n, "cap": cap, "values": values}
                        for label, n, cap, values in tier_report(parse_rules(css))
                    ],
                    "new": len(bad),
                    "stale_baseline_rows": stale,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("=== 一致性判定 ===")
    for f in findings:
        print(f"{MARK[f.verdict]} {f.detail}")
        if f.known:
            print(f"        （登记理由：{f.known}）")

    print("\n=== 档数报告（语言的收敛度；不判、只报数）===")
    for label, n, cap, values in tier_report(parse_rules(css)):
        over = f"  ← 超过上限 {cap}" if cap is not None and n > cap else ""
        shown = "、".join(v.replace("--", "") for v in values)
        print(f"  {label:<4} {n} 档{over}：{shown}")

    if stale:
        print("\n=== 登记表里这些已经对不上现状了，删掉 ===")
        for key in stale:
            print(f"  {key}")

    if bad:
        print(
            f"\n风格一致性体检 FAIL —— {len(bad)} 条没登记过"
            "（要么改回去，要么写进 style_baseline.toml）："
        )
        for f in bad:
            print(f"  {f.key}")
        return 1
    print(
        f"\n风格一致性体检 PASS（没有新问题；登记在案 "
        f"{sum(1 for f in findings if f.verdict == 'KNOWN')} 条已知欠账）"
    )
    print("说明：这只证明「体系里没有新的破例」，**不证明好看** —— 好看要眼睛。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
