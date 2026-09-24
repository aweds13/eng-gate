"""在**候选 CSS** 的令牌上预演一遍对比度门（人看用；真判定仍由 `contrast_audit.py` 下）。

为什么要有它：视觉线的候选（步 2 起）是一次性覆盖层，不进 `app.css`；可是"候选里的令牌值
换了会不会把某处文字弄糊"是个**能算的事实**，不该等到落地之后才让门去喊。
所以这里直接用**门自己的算法与组合清单**（`contrast_audit.py` 的函数 import 过来），
把候选的令牌块叠在 `app.css` 的令牌上算一遍 —— 算法只有一份，不存在"预演用的算法"。

与门的关系（**别搞混**）：它**不改任何文件、不写 last.json、不参与提交闸**。
候选选定并落进 `app.css` 之后，`python -X utf8 scripts/run_gates.py --fast` 里的 `contrast`
那一步才是判定。这份预演只回答一个问题：**这个候选里有没有新欠账。**

用法：
    python -X utf8 tools/candidate_contrast.py gates/candidates/step2/*.css
    python -X utf8 tools/candidate_contrast.py --baseline            # 只看当前 app.css
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contrast_audit import (  # noqa: E402 —— 先把 tools/ 放进 sys.path 才能 import 同目录模块
    AA_NORMAL,
    CSS,
    MARK,
    Pair,
    badge_pairs,
    declared_pairs,
    dedupe,
    evaluate,
    state_pairs,
    token_blocks,
)

# 候选**新造出来**的搭配：静态表里原来没有（T-G42 撤掉过 `--muted on --panel-2`，
# 因为那时样式表里已经没有这种搭配了）。候选 C 会把"读数的说明文字"放到静音面上，
# 于是这一对重新变成"真会出现的搭配"，必须一起量 —— 不然就是"门看不见的新欠账"。
CANDIDATE_PAIRS: tuple[tuple[str, str, float, str], ...] = (
    ("--muted", "--panel-2", AA_NORMAL, "候选：静音面（读数卡）上的 .meta / .sub"),
)


def run(label: str, overrides_css: str | None, base_css: str) -> int:
    tokens = token_blocks(base_css)
    if overrides_css:
        over = token_blocks(overrides_css)
        tokens = {
            "light": {**tokens["light"], **over["light"]},
            "dark": {**tokens["dark"], **over["dark"]},
        }
    pairs = list(declared_pairs() + badge_pairs(base_css) + state_pairs(base_css))
    pairs += [Pair(t, fg, bg, minimum, where)
              for t in ("light", "dark") for fg, bg, minimum, where in CANDIDATE_PAIRS]
    rows = evaluate(dedupe(pairs), tokens, {})
    bad = [r for r in rows if r.verdict != "PASS"]
    print(f"\n=== {label} —— {len(rows)} 条组合，不达标 {len(bad)} ===")
    for row in rows:
        if row.verdict == "PASS" and not overrides_css:
            continue  # 基线只在有欠账时逐条列，免得刷屏
        print(f"  {row.ratio:>6.2f} / {row.pair.minimum:<4} {MARK[row.verdict]} "
              f"{row.pair.theme}: {row.pair.fg} on {row.pair.bg} —— {row.pair.where}")
    if not bad:
        print("  ✅ 全部达标（含候选新造的 `--muted on --panel-2`）")
    return len(bad)


def main(argv: list[str]) -> int:
    base = CSS.read_text(encoding="utf-8")
    if not argv or argv[0] == "--baseline":
        return 1 if run("当前 app.css（基线）", None, base) else 0
    failed = 0
    for arg in argv:
        path = Path(arg)
        if not path.exists():
            print(f"❌ 找不到 {path}")
            failed += 1
            continue
        failed += run(path.name, path.read_text(encoding="utf-8"), base)
    print("\n（预演用门自己的算法；真判定是 `run_gates.py --fast` 里的 contrast 一步）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
