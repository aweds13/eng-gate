"""界面文本体检（T-G49）—— 把"渲染出去的说明文字"按长度列出来，给人判、给门用。

## 为什么有它

用户原话：「有些没有必要的解释，你也写进去啊……**这是给人用的**，我知道哪些要用什么。
如果我不知道的话，你可以设计一个小小的用户文档，而不是把那些一大堆解释塞在那里。」

这是**我的**毛病，而且成因很清楚：每加一个功能就顺手在界面上写一段"为什么这样算"
（「不折算成投入时间（时间折算只在有真实时长时才算）」），把复盘写进了产品。
包自己的空态规范只有一句：**一句暗淡的话 + 一个动作**（`.wb-empty`）。

## 判据（机器筛，人再判）

中文连续片段在代码里只有一个来源 —— **界面上给人看的字**（标识符全是 ASCII），
所以直接在 `index.html` 里扫 CJK 连续段，汉字 ≥ `--min`（默认 20）的算候选，
并排掉整行是注释的那些（行首 `//` / `/*` / `*`）。

**它是诊断，不是判"文案好坏"**：太长不一定错（口径说明要如实），
但"一句话都装不下"基本就是错的。清完之后它可以升级成一条**上限门**（棘轮），
免得过几天又长回来 —— 那一步要等清理落地、允许表稳定之后再做（见 `复盘/界面不解释-T-G49.md` §5）。

用法：
    python -X utf8 tools/ui_text_scan.py              # 默认 ≥20 汉字，全部列出来
    python -X utf8 tools/ui_text_scan.py --min 30      # 只看最长的那一批
    python -X utf8 tools/ui_text_scan.py --stat        # 只给长度分布
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "src" / "web" / "index.html"

# 一段「界面文本」：汉字打头结尾，中间允许中文标点、字母数字与常见符号（代码符号不算）
RUN = re.compile(
    r"[\u4e00-\u9fff][\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
    r"A-Za-z0-9 %.,:;()/·\-]*[\u4e00-\u9fff。！？]"
)
CJK = re.compile(r"[\u4e00-\u9fff]")


def fragments(path: Path) -> list[tuple[int, int, str]]:
    """(行号, 汉字数, 文本) —— 跳过整行注释。"""
    out: list[tuple[int, int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        head = line.lstrip()
        if head.startswith("//") or head.startswith("/*") or head.startswith("*"):
            continue
        for m in RUN.finditer(line):
            text = m.group(0).strip()
            out.append((i, len(CJK.findall(text)), text))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="界面文本长度体检（诊断）")
    ap.add_argument("--min", type=int, default=20, help="汉字数下限（默认 20）")
    ap.add_argument("--stat", action="store_true", help="只给长度分布")
    args = ap.parse_args()

    all_frag = fragments(INDEX)
    print(f"界面中文片段 {len(all_frag)} 条，共 {sum(c for _, c, _ in all_frag)} 个汉字")
    print("分布：" + "  ".join(f"≥{n} → {sum(1 for _, c, _ in all_frag if c >= n)} 条"
                             for n in (14, 18, 20, 25, 30, 35)))
    if args.stat:
        return 0

    hits = sorted([f for f in all_frag if f[1] >= args.min], key=lambda f: -f[1])
    print(f"\n汉字 ≥ {args.min} 的 {len(hits)} 条（按长度倒序）：")
    for lineno, count, text in hits:
        print(f"{count:>3}字  L{lineno:<5} {text}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
