"""一次性脚本：为每篇复盘抽一句「它解决了什么 / 结论是什么」。
规则（按优先级，命中即停）：
  1) `交接.d/`：取 `**做了什么**：` 那一行；没有就取第一条 bullet。
  2) `=== 结论 ===` / `## 结论` / `## 判决` / `## 定案` 小节的第一句实义文字。
  3) 正文第一段（跳过标题、列表、代码、表格、引用）。
输出 scripts/retro/retro_lines.json：rel -> {line, src}
用法：python -X utf8 scripts/retro/retro_lines.py [--sample N] [--only 前缀]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"
OUT = DIAG / "retro_lines.json"

JUNK = "★☆✓✗△▲※→←〔〕 \t"
CLEAN = [
    (re.compile(r"\*\*|__|`{1,3}"), ""),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^[>\-\*\d\.\)\s|]+"), ""),
    (re.compile(r"[★☆✓✗△▲※|]"), ""),
    (re.compile(r"\s{2,}"), " "),
]
CONCL_H = re.compile(r"^(#{1,4}\s*)?(=+\s*)?(结论|判决|定案|裁决|判据与结论|一句话|总结|根因|教训)")
STOP = re.compile(r"(见|见下|如下|略|待补|TODO|见上文|见前)")

# 首段要跳过的行（含卡规格的样板头）
BOILER = re.compile(
    r"^(\*\*)?(树|成员号|层|base|前置)(\*\*)?[：:]|开局就在这棵树|主控复核后提交|不要 commit|"
    r"^(\*\*)?(不许|★|干完|交付|判据自检|先读)"
)
SKIP = re.compile(r"^(#|\||```|\s*$|[-*+]\s|\d+[\.\)]\s|>|!\[|<)")
INLINE_CONCL = re.compile(r"(\*\*)?(结论|根因|判决|定案)(\*\*)?[：:]\s*(.+)")


def norm(line: str) -> str:
    s = line
    for rx, rep in CLEAN:
        s = rx.sub(rep, s)
    return s.strip(JUNK).strip()


def sentence(s: str, cap: int = 78) -> str:
    s = norm(s)
    if not s:
        return ""
    parts = re.split(r"(?<=[。！？；])", s)
    out = ""
    for p in parts:
        if len(out) + len(p) <= cap:
            out += p
        elif not out:
            out = p[:cap] + "…"
            break
        else:
            break
    return out.strip()


def para_after(ls: list[str], start: int) -> str:
    buf: list[str] = []
    for ln in ls[start:]:
        t = ln.strip()
        if not t:
            if buf:
                break
            continue
        if t.startswith("#"):
            if buf:
                break
            continue
        if SKIP.match(t) or t.startswith("```") or "--evidence" in t or "--claim" in t:
            if buf:
                break
            continue
        if BOILER.search(t):
            continue
        buf.append(t)
        if len("".join(buf)) > 70:
            break
    return " ".join(buf)


def pick(md: str, rel: str) -> tuple[str, str]:
    ls = md.splitlines()
    if rel.startswith("复盘/交接.d/"):
        # 格式：> **日期 · CHECKPOINT（卡 N · T-Gxxx）—— 标题**：  +  > **来路**/**做法**/**
        head = ""
        for ln in ls[:12]:
            if "CHECKPOINT" in ln:
                head = re.sub(r"^[>\s*]+", "", ln)
                head = re.sub(r"^\d{4}-\d{2}-\d{2}\s*·\s*", "", head)
                head = re.sub(r"^CHECKPOINT[（(][^）)]*[）)]\s*[—\-·]*\s*", "", head)
                break
        tail = ""
        for ln in ls[:60]:
            if re.search(r"\*\*(做法|结论|教训|定案|结果)\*\*", ln):
                tail = re.sub(r"^[>\s*]+", "", ln)
                tail = re.sub(r"^\*\*(做法|结论|教训|定案|结果)\*\*[：:]\s*", "", tail)
                break
        if head and tail:
            return sentence(head.strip("：: *"), 52) + " ⇒ " + sentence(tail, 58), "交接.标题+做法"
        if head:
            return sentence(head.strip("：: *"), 96), "交接.标题"
        for ln in ls[:80]:
            if "做了什么" in ln:
                return sentence(re.sub(r"^.*?做了什么\**[：:]\s*", "", ln), 92), "交接.做了什么"
        for ln in ls[:80]:
            if ln.startswith("- "):
                return sentence(ln, 92), "交接.bullet"
        return "", "none"
    # 1) 独立的结论 / 判决 小节
    for i, ln in enumerate(ls):
        h = ln.strip()
        if not (h.startswith("#") or h.startswith("===")):
            continue
        bare = re.sub(r"^[#=\s]+", "", h)
        if not CONCL_H.match(bare):
            continue
        s = sentence(para_after(ls, i + 1))
        if len(s) >= 12 and not STOP.match(s):
            return s, "结论小节"
    # 2) 任意一行里内联的「结论：…」（跳过卡规格里教工人填的那句样板）
    for ln in ls[:60]:
        if "--" in ln or ln.strip().startswith("-"):
            continue
        m = INLINE_CONCL.search(ln)
        if m:
            s = sentence(m.group(4))
            if len(s) >= 12:
                return s, "内联结论"
    # 3) 优先「为什么 / 背景 / 问题」这一节（卡规格与复盘都把动机写在这）
    for i, ln in enumerate(ls):
        if ln.startswith("## ") and re.search(r"为什么|背景|问题|现状|目标|要解决|动机", ln):
            s = sentence(para_after(ls, i + 1))
            if len(s) >= 12:
                return s, "动机节"
    h1 = next((i for i, ln in enumerate(ls) if ln.startswith("# ")), -1)
    for i, ln in enumerate(ls):
        if ln.startswith("## ") and i > h1:
            s = sentence(para_after(ls, i + 1))
            if len(s) >= 12:
                return s, "首个H2"
            break
    if h1 >= 0:
        s = sentence(para_after(ls, h1 + 1))
        if len(s) >= 12:
            return s, "H1首段"
    # 4) 退路：第一条实义行
    for ln in ls:
        t = ln.strip()
        if t and not t.startswith("#") and not SKIP.match(t) and not BOILER.search(t):
            s = sentence(t)
            if len(s) >= 10:
                return s, "首行"
    return "", "none"


def main() -> int:
    d = json.loads((DIAG / "retro_extract.json").read_text(encoding="utf-8"))
    rows = d["rows"]
    out = {}
    miss = []
    for r in rows:
        md = (ROOT / r["rel"]).read_text(encoding="utf-8", errors="replace")
        line, src = pick(md, r["rel"])
        out[r["rel"]] = {"line": line, "src": src}
        if not line:
            miss.append(r["rel"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rows {len(rows)}  miss {len(miss)}")
    for m in miss[:20]:
        print("  MISS", m)
    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1]) if sys.argv[-1].isdigit() else 40
        only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
        k = 0
        for r in rows:
            if only and not r["rel"].startswith(only):
                continue
            o = out[r["rel"]]
            print(f"[{o['src']}] {r['rel'][3:]}  →  {o['line']}")
            k += 1
            if k >= n:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
