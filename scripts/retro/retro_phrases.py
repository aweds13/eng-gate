"""一次性脚本：从 587 篇复盘的「操作性句子」里挖反复出现的主张（频次按**文档数**算）。
流程：
  1) 抽句：含 must/禁/先…再/否则 等祈使标记的句子，或标题行。
  2) 归一：去数字、去卡号、去引号、压空白。
  3) 计数：同一归一串出现在多少个文件里（doc frequency）。
输出 scripts/retro/retro_phrases.json + 控制台 top 表。
用法：python -X utf8 scripts/retro/retro_phrases.py [--top 120] [--grep 关键词]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"
OUT = DIAG / "retro_phrases.json"

MARK = re.compile(
    r"必须|不许|不要|别|一律|禁止|只能|否则|先.{1,12}再|务必|切记|千万|"
    r"不能|不得|应当|约定|铁律|判据是|结论是|根因是|坑在于"
)
NOISE = [
    (r"T-AG?\d+", ""),
    (r"卡\s*A?\d+", ""),
    (r"外包卡\s*\d+[ab]?", ""),
    (r"\d{4}-\d{2}-\d{2}", ""),
    (r"`[^`]{0,40}`", ""),
    (r"[★☆✓✗△▲※→←|]", ""),
    (r"[“”\"'「」『』*]", ""),
    (r"[\s　]{2,}", " "),
    (r"^[\s\-—:：·]+", ""),
]


def norm(s: str) -> str:
    for pat, rep in NOISE:
        s = re.sub(pat, rep, s)
    return s.strip(" -—:：·。，,；;、")


def sentences(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        t = ln.strip()
        if not t or t.startswith("```"):
            continue
        t = re.sub(r"^(#+|>|\d+[\.\)]|[-*+])\s*", "", t)
        if len(t) < 8:
            continue
        for p in re.split(r"(?<=[。！？；])", t):
            p = p.strip()
            if 8 <= len(p) <= 120:
                out.append(p)
    return out


def main() -> int:
    d = json.loads((DIAG / "retro_extract.json").read_text(encoding="utf-8"))
    df: Counter = Counter()
    where: dict[str, list[str]] = defaultdict(list)
    for r in d["rows"]:
        text = (ROOT / r["rel"]).read_text(encoding="utf-8", errors="replace")
        seen = set()
        for s in sentences(text):
            if not MARK.search(s):
                continue
            n = norm(s)
            if len(n) < 10 or n in seen:
                continue
            seen.add(n)
            df[n] += 1
            where[n].append(r["rel"])
    OUT.write_text(
        json.dumps({"df": df.most_common(), "where": where}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 120
    pat = sys.argv[sys.argv.index("--grep") + 1] if "--grep" in sys.argv else None
    n = 0
    for s, c in df.most_common():
        if pat and not re.search(pat, s):
            continue
        print(f"{c:3d}  {s}")
        n += 1
        if n >= top:
            break
    print(f"\nunique {len(df)}   total {sum(df.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
