"""界面文案的**上限门**（T-G57）—— 棘轮：≥30 汉字一条都不许、≥20 只许减不许增。

## 为什么要有它

用户两次说过同一件事：界面上不该有"没必要的解释"（`复盘/界面不解释-T-G49.md`）。
清理靠人一次做完了，可**没有任何一层拦着它长回来** —— 下一轮加功能时顺手写一段
「（时间折算只在有真实时长时才算）」就又回去了。这跟对比度、一致性那两道门是同一个病：
**只写在文档里的纪律，第三轮必漂**。

## 判据（跟 `tools/contrast_baseline.toml` / `tools/style_baseline.toml` 同一套精神）

- **硬门**：汉字 ≥ `HARD`（30）的片段，一条都不许 —— 太长基本就是错的（把复盘写进了产品）。
  确有必要（例如契约点名的 evidence 句）要在 `tools/ui_text_baseline.toml` 的 `[known]` 里
  **逐条登记 + 写明理由**，跟台账 `[exceptions]` 一个规矩。
- **棘轮**：汉字 ≥ `RATCHET`（20）的总条数**超过基线** → FAIL；**少于基线** → 提示把数字调下来
  （修一条记一条，跟一致性门"已经好了就提示删掉这一行"同款）。
- **登记项对不上现状** → FAIL（防"把句子改写一下绕过登记"）。

★ **为什么 20–29 那一档不一刀切**：里面混着**报错原话、二次确认问句、契约 evidence**
（那些是"说什么"，不是"怎么用"）—— 一刀切会逼人去删合法文案，那是**造假绿**。
棘轮的作用是"不许再变多"，把它慢慢压下去是后面的活。

用法：
    python -X utf8 tools/ui_text_audit.py            # 报告（给人看）
    python -X utf8 tools/ui_text_audit.py --check    # 门禁用：不通过就退 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_text_scan as scan  # noqa: E402  （口径只写一处：片段怎么算由这把尺子定）

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tools" / "ui_text_baseline.toml"

HARD = 30      # 一条都不许（除登记项）
RATCHET = 20   # 只许减不许增


def load() -> tuple[dict[str, dict[str, str]], int]:
    data = tomllib.loads(BASELINE.read_text(encoding="utf-8"))
    known = {str(k): dict(v) for k, v in (data.get("known") or {}).items()}
    limit = int((data.get("ratchet") or {}).get("count", 0))
    return known, limit


def key_of(count: int, text: str) -> str:
    return f"{count} :: {text}"


def verdicts(
    frag: list[tuple[int, int, str]], known: dict[str, dict[str, str]], limit: int
) -> tuple[list[str], list[str], int, int]:
    """(失败, 提示, ≥20 的条数, ≥30 的条数) —— 判定与打印分开，好让 pytest 直接喂合成数据。"""
    long_hard = [(ln, c, t) for ln, c, t in frag if c >= HARD]
    over = [(ln, c, t) for ln, c, t in frag if c >= RATCHET]
    now = {key_of(c, t) for _, c, t in long_hard}

    fails: list[str] = []
    notes: list[str] = []

    for ln, c, t in sorted(long_hard, key=lambda x: -x[1]):
        if key_of(c, t) not in known:
            fails.append(f"L{ln}  {c} 字：{t}")
    for k in sorted(known):
        if k not in now:
            fails.append(f"登记项对不上现状（改写了或已经删了）：{k}")
    if len(over) > limit:
        fails.append(f"≥{RATCHET} 字的片段 {len(over)} 条 > 基线 {limit} 条（这一档只许减）")
    elif len(over) < limit:
        notes.append(
            f"≥{RATCHET} 字现在 {len(over)} 条 < 基线 {limit} 条 → "
            f"把 tools/ui_text_baseline.toml 的 count 调成 {len(over)}"
        )
    return fails, notes, len(over), len(long_hard)


def main() -> int:
    ap = argparse.ArgumentParser(description="界面文案上限门（棘轮）")
    ap.add_argument("--check", action="store_true", help="门禁模式：有问题就退 1")
    args = ap.parse_args()

    known, limit = load()
    fails, notes, n_over, n_hard = verdicts(scan.fragments(), known, limit)

    print(f"界面文案上限门：≥{RATCHET} 字 {n_over} 条（基线 {limit}）/ "
          f"≥{HARD} 字 {n_hard} 条（硬门，登记 {len(known)} 条）")
    for n in notes:
        print(f"  [提示] {n}")
    if fails:
        print(f"  [FAIL] {len(fails)} 项：")
        for f in fails:
            print(f"    - {f}")
        print("  口径见 docs/specification/conventions.md 的「界面文案」"
              "（空态不解释怎么用；数字口径 ≤8 字；操作标签/单位/状态/报错原话照留）")
        return 1 if args.check else 0
    print("  [OK ] 通过（≥30 一条不多、≥20 没长、登记项都对得上）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
