"""前端热表（T-G52 / L8）—— 「改这个视图的文案或结构，去哪个函数、哪几行」。

## 为什么有它

`复盘/视觉线地图.md` 解决了"改颜色 / 间距该动哪几处、哪道门会惊动"，但没解决
**"这句话在哪个函数里"**。`src/web/index.html` 有 3500 行，改一处空态文案也得先翻半天 ——
这笔税每张界面卡都要付一次。所以把它**生成**出来（不手写，手写的会烂）：

- 视图 → render 函数：从 `render(name)` 里那串 `if(name==='x')return paint(renderY)` 现读；
- 每个 render 函数的**行区间**：从它自己的 `function` 行到下一个顶层 `function`；
- 区间内的说明文本（`.sub` / `.meta` / `.hint`）、空态调用（`emptyState(`）、
  动作（`data-action=`）数量。

**它是索引，不是判据**：不进门禁，也不判"文案长不长"（那是 `tools/ui_text_scan.py` 的事）。

    python -X utf8 tools/ui_hotmap.py                 # 打到屏幕
    python -X utf8 tools/ui_hotmap.py --write          # 写进 复盘/前端热表.md
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "src" / "web" / "index.html"
OUT = ROOT / "复盘" / "前端热表.md"

DISPATCH = re.compile(r"if\(([^)]*)\)return paint\((?:m=>)?(\w+)")
VIEWNAME = re.compile(r"'([a-z]+)'")
DEF = re.compile(r"^(?:async )?function (\w+)\(", re.M)
SUBS = re.compile(r'class="(?:sub|meta|hint)')


def functions(text: str) -> dict[str, tuple[int, int]]:
    """函数名 → (起始行, 结束行)。结束行 = 下一个顶层 `function` 之前的那一行。"""
    hits = [(m.start(), m.group(1)) for m in DEF.finditer(text)]
    starts = [text[: pos].count("\n") + 1 for pos, _ in hits]
    out: dict[str, tuple[int, int]] = {}
    for i, (_, name) in enumerate(hits):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else text.count("\n") + 1
        out[name] = (starts[i], end)
    return out


def dispatch(text: str) -> list[tuple[list[str], str]]:
    """`render(name)` 里的分发：([视图名…], 函数名)。三个智能视图共用 `renderSmart`。"""
    out: list[tuple[list[str], str]] = []
    for m in DISPATCH.finditer(text):
        views = VIEWNAME.findall(m.group(1))
        if views:
            out.append((views, m.group(2)))
    return out


def body(text: str, span: tuple[int, int]) -> str:
    return "\n".join(text.split("\n")[span[0] - 1: span[1]])


def _counts(src: str) -> tuple[int, int, int]:
    """(说明文本处数, 空态处数, 动作处数) —— 规模感，不是判据。"""
    return len(SUBS.findall(src)), src.count("emptyState("), src.count("data-action=")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成前端热表（视图 → 函数 → 行区间）")
    ap.add_argument("--write", action="store_true", help=f"写进 {OUT.relative_to(ROOT)}")
    args = ap.parse_args()

    text = INDEX.read_text(encoding="utf-8")
    fns = functions(text)
    rows = dispatch(text)

    lines = [
        "# 前端热表（`tools/ui_hotmap.py` 生成，别手改）",
        "",
        "改某个视图的文案 / 结构 / 空态 → 从这张表直接跳到函数与行区间。",
        "行号会随编辑漂，**函数名是稳定的锚点**；数字是「这个函数里有多少处」的规模感。",
        "",
        "| 视图 | 函数 | 行区间 | 规模 | `.sub/.meta/.hint` | `emptyState(` | `data-action=` |",
        "|---|---|---|---|---|---|---|",
    ]
    unmapped = set(fns) - {f for _, f in rows}
    for views, fn in rows:
        span = fns.get(fn)
        if span is None:
            lines.append(f"| {'/'.join(views)} | {fn} | ❌ 找不到定义 | | | | |")
            continue
        subs, empties, actions = _counts(body(text, span))
        size = span[1] - span[0] + 1
        lines.append(
            f"| {'/'.join(views)} | `{fn}` | {span[0]}–{span[1]} | {size} 行"
            f" | {subs} | {empties} | {actions} |"
        )

    lines += [
        "",
        "## 会拼标记的函数（卡片 / 面板 / 提示条 / 墙）—— 改文案与结构多半在这里",
        "",
        "只列**体内出现 `class=`** 的那些（其余是纯逻辑辅助，改视觉不用看）：",
        "",
        "| 函数 | 行区间 | 规模 | 说明文本 | `emptyState(` | `data-action=` |",
        "|---|---|---|---|---|---|",
    ]
    marks = [fn for fn in sorted(unmapped, key=lambda f: fns[f])
             if 'class="' in body(text, fns[fn])]
    for fn in marks:
        span = fns[fn]
        subs, empties, actions = _counts(body(text, span))
        lines.append(
            f"| `{fn}` | {span[0]}–{span[1]} | {span[1] - span[0] + 1} 行"
            f" | {subs} | {empties} | {actions} |"
        )

    lines += [
        "",
        f"（共 {len(fns)} 个顶层函数，其中 {len(marks)} 个会拼标记；生成自 `src/web/index.html`）",
        "",
    ]
    table = "\n".join(lines)

    if args.write:
        OUT.write_text(table, encoding="utf-8")
        print(f"[OK ] 写进 {OUT.relative_to(ROOT)}（{len(fns)} 个函数 / {len(marks)} 个拼标记）")
        return 0
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
