"""界面文本体检（T-G49）—— 把"渲染出去的说明文字"按长度列出来，给人判、给门用。

## 为什么有它

用户原话：「有些没有必要的解释，你也写进去啊……**这是给人用的**，我知道哪些要用什么。
如果我不知道的话，你可以设计一个小小的用户文档，而不是把那些一大堆解释塞在那里。」

这是**我的**毛病，而且成因很清楚：每加一个功能就顺手在界面上写一段"为什么这样算"
（「不折算成投入时间（时间折算只在有真实时长时才算）」），把复盘写进了产品。
包自己的空态规范只有一句：**一句暗淡的话 + 一个动作**（`.wb-empty`）。

## 判据（机器筛，人再判）

中文连续片段在代码里只有一个来源 —— **界面上给人看的字**（标识符全是 ASCII），
所以直接在 `index.html` 里扫 CJK 连续段，汉字 ≥ `--min`（默认 20）的算候选。

★ **必须先剥注释**（T-G57 修）：这个文件的注释里**大量原文引用界面文案**（「原来写的是『…』」），
而第一版只挡了"整行以 `//`/`/*`/`*` 开头"，注释的**续行**照样混进统计 ——
74 条 20–29 字命中里约 **13 条是这类噪声**。基线里混着噪声，棘轮就是假的。
现在剥三类注释（**块注释跨行跟踪** + 行注释 + HTML 注释），并把注释换成 NUL
（NUL 不在片段字符集里，所以被注释隔开的两段文字不会被粘成一条）。

★ **为什么不做完整的字符串/正则状态机**（第一版就是那么写的，错了）：
`src/web/index.html` 的 `esc()` 里有个正则字面量 `/[&<>"']/g`，**里面同时有 `"` 和 `'`** ——
不懂正则的状态机会在那儿**错位**，之后整片注释被当成"字符串内容"照收
（实测：错位后 ≥30 字的命中从 19 涨到 **38**，多出来的全是注释）。
宁可少做一点也不要错位：这里只做"块注释跨行 + 行注释 + HTML 注释"三件能确定的事，
`//` 前面是 `:` 的不算注释（`http://` 就在代码里）。

**它是诊断，也是上限门**：`tools/ui_text_audit.py` 把它变成棘轮（≥30 汉字一条都不许、
≥20 只许减不许增），登记表 `tools/ui_text_baseline.toml`。

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
FILL = "\x00"   # 注释占位：不在上面的字符集里，能把片段切开


def strip_comments(text: str) -> str:
    """剥三类注释（块注释跨行 / 行注释 / HTML 注释），换成等长 NUL，保留换行。

    为什么是"按行 + 跨行状态"而不是完整词法状态机：见文件头（正则字面量 `/[&<>"']/g` 会让
    不懂正则的状态机错位，错位之后整片注释被当字符串收进来 —— 实测把 ≥30 的命中从 19 涨到 38）。
    """
    out: list[str] = []
    in_block = False
    in_html = False
    for line in text.split("\n"):
        s = line
        if in_html:
            k = s.find("-->")
            if k == -1:
                out.append(FILL * len(s))
                continue
            in_html = False
            s = FILL * (k + 3) + s[k + 3:]
        if in_block:
            k = s.find("*/")
            if k == -1:
                out.append(FILL * len(s))
                continue
            in_block = False
            s = FILL * (k + 2) + s[k + 2:]
        # 同一行里可能有好几处块注释 / HTML 注释
        while True:
            k, h = s.find("/*"), s.find("<!--")
            if k == -1 and h == -1:
                break
            if h != -1 and (k == -1 or h < k):
                j = s.find("-->", h + 4)
                if j == -1:
                    in_html = True
                    s = s[:h] + FILL * (len(s) - h)
                    break
                s = s[:h] + FILL * (j + 3 - h) + s[j + 3:]
                continue
            j = s.find("*/", k + 2)
            if j == -1:
                in_block = True
                s = s[:k] + FILL * (len(s) - k)
                break
            s = s[:k] + FILL * (j + 2 - k) + s[j + 2:]
        # 行注释：`//` 前面是 `:` 的不算（`http://` 就在代码里）
        k = s.find("//")
        while k != -1:
            if k == 0 or s[k - 1] != ":":
                s = s[:k] + FILL * (len(s) - k)
                break
            k = s.find("//", k + 2)
        out.append(s)
    return "\n".join(out)


def fragments(path: Path = INDEX) -> list[tuple[int, int, str]]:
    """(行号, 汉字数, 文本) —— 先剥注释再扫。"""
    out: list[tuple[int, int, str]] = []
    code = strip_comments(path.read_text(encoding="utf-8"))
    for i, line in enumerate(code.split("\n"), start=1):
        for m in RUN.finditer(line):
            text = m.group(0).strip()
            if not text:
                continue
            out.append((i, len(CJK.findall(text)), text))
    return out


def stats() -> dict[int, int]:
    frag = fragments()
    return {n: sum(1 for _, c, _ in frag if c >= n) for n in (14, 18, 20, 25, 30, 35)}


def main() -> int:
    ap = argparse.ArgumentParser(description="界面文本长度体检（诊断 + 上限门的数据源）")
    ap.add_argument("--min", type=int, default=20, help="汉字数下限（默认 20）")
    ap.add_argument("--stat", action="store_true", help="只给长度分布")
    args = ap.parse_args()

    all_frag = fragments()
    print(f"界面中文片段 {len(all_frag)} 条，共 {sum(c for _, c, _ in all_frag)} 个汉字")
    print("分布：" + "  ".join(f"≥{n} → {v} 条" for n, v in stats().items()))
    if args.stat:
        return 0

    hits = sorted([f for f in all_frag if f[1] >= args.min], key=lambda f: -f[1])
    print(f"\n汉字 ≥ {args.min} 的 {len(hits)} 条（按长度倒序）：")
    for lineno, count, text in hits:
        print(f"{count:>3}字  L{lineno:<5} {text}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
