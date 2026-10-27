"""一次性脚本：扫描 复盘/**/*.md，抽取索引所需的元数据 + 结论候选行。
只读，不改任何已有文件。产物：gates/diag/retro_extract.json（诊断产物，不入库）
用法：python -X utf8 scripts/retro/retro_extract.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"

RETRO = ROOT / "复盘"
OUT = DIAG / "retro_extract.json"

CARD_TG = re.compile(r"T-G\d+")
CARD_KA = re.compile(r"卡[A-Z]?\d+")
CARD_AG = re.compile(r"T-AG\d+")
H1 = re.compile(r"^#\s+(.+?)\s*$")
H2 = re.compile(r"^##\s+(.+?)\s*$")
HDR_MARK = re.compile(r"[=＝]{2,}\s*([^\s=＝]{1,12})\s*[=＝]{2,}")  # === 结论 ===
SENT_SPLIT = re.compile(r"[。；;！!？?\n]")

SIGNAL = (
    "结论",
    "根因",
    "教训",
    "判据",
    "决定",
    "定案",
    "不变量",
    "铁律",
    "必须",
    "禁用",
    "不许",
    "只能",
    "不要再",
    "坑",
    "废弃",
    "已废弃",
    "推翻",
    "撤回",
    "作废",
    "失效",
    "更正",
    "实测",
)
NEGATIVE = (
    "废弃",
    "已废弃",
    "作废",
    "撤回",
    "推翻",
    "失效",
    "更正",
    "不再",
    "过时",
    "别再用",
    "反例",
    "假红",
    "误报",
)

STOP = set(
    "的了和是与在也就都要会能可对把被这个那有些为不出上下或者如果那么因为所以但是"
    "一个我们你们他们它这那什么怎么如何可以没有不是就是还是这样那样已经现在以后"
    "问题东西时候比较通过需要应该可能以及一个两个不是这里那里今天明天昨天"
)


def strip_code(text: str) -> str:
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def norm(s: str) -> str:
    s = re.sub(r"[`*_>#|]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip("—-:：·、 ")
    return s


def is_meaningful(s: str) -> bool:
    if len(s) < 10:
        return False
    if s.startswith(("$", "PS ", "C:", "cd ", "python", "pipe ", "git ")):
        return False
    if re.fullmatch(r"[\W\-=~^|/\\]+", s):
        return False
    # 中文占比太低的多半是命令/路径
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return cjk >= 6


def sentence_candidates(text: str) -> list[str]:
    """从正文前 120 行里挑结论型句子，按信号词数量排序。"""
    body = strip_code(text)
    lines = body.splitlines()[:120]
    cands: list[str] = []
    seen = set()

    def add(raw: str, bonus: int):
        s = norm(raw)
        s = re.sub(r"^(结论|根因|教训|判据|决定|定案)\s*[:：]\s*", "", s)
        if not is_meaningful(s):
            return
        if s in seen:
            return
        seen.add(s)
        cands.append((bonus, len(s), s))

    for ln in lines:
        raw = ln.strip()
        if not raw or raw.startswith("|"):
            continue
        # === 结论 === 之类的段落头，取后面紧跟的非空行
        if HDR_MARK.search(raw):
            continue
        hit = [k for k in SIGNAL if k in raw]
        if hit:
            bonus = 40 + 12 * len(hit)
            if any(k in raw for k in ("结论", "定案", "判据", "决定", "铁律", "不变量")):
                bonus += 30
            if re.match(r"^[-*+]\s*|^\d+[.)]\s*", raw):
                bonus += 6
            for part in SENT_SPLIT.split(raw):
                add(part, bonus)

    return [s for _, _, s in sorted(cands, key=lambda t: (-t[0], -t[1]))][:6]


def heading_conclusion(text: str) -> str:
    """=== 结论 === 段落体：取标记之后的第一段实义文字。"""
    lines = strip_code(text).splitlines()
    for i, ln in enumerate(lines):
        m = HDR_MARK.search(ln)
        if not m:
            continue
        label = m.group(1)
        if not any(k in label for k in ("结论", "定案", "根因", "教训", "判据", "决定")):
            continue
        for nxt in lines[i + 1 : i + 6]:
            s = norm(nxt)
            if is_meaningful(s):
                return s
    return ""


def bigrams(text: str) -> Counter:
    c = Counter()
    run = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and ch not in STOP:
            run.append(ch)
        else:
            for i in range(len(run) - 1):
                c[run[i] + run[i + 1]] += 1
            for i in range(len(run) - 2):
                c[run[i] + run[i + 1] + run[i + 2]] += 1
            run = []
    if run:
        for i in range(len(run) - 1):
            c[run[i] + run[i + 1]] += 1
        for i in range(len(run) - 2):
            c[run[i] + run[i + 1] + run[i + 2]] += 1
    return c


def main() -> int:
    files = sorted(RETRO.rglob("*.md"))
    rows = []
    df = Counter()  # 词 -> 出现在多少个文件
    tf = Counter()  # 词 -> 总频次
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"!! {p}: {e}", file=sys.stderr)
            continue
        rel = p.relative_to(ROOT).as_posix()
        st = p.stat()
        lines = text.splitlines()
        h1 = ""
        h2s = []
        for ln in lines[:40]:
            m = H1.match(ln)
            if m and not h1:
                h1 = norm(m.group(1))
            m2 = H2.match(ln)
            if m2 and len(h2s) < 8:
                h2s.append(norm(m2.group(1)))
        title = h1 or norm(h2s[0]) if (h1 or h2s) else p.stem
        body_cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        head = "\n".join(lines[:120])
        wc = bigrams(p.stem + "\n" + title + "\n" + head)
        for w, n in wc.items():
            tf[w] += n
            df[w] += 1
        rows.append(
            {
                "rel": rel,
                "dir": rel.split("/")[1]
                if rel.count("/") >= 2
                else ("复盘(根目录)" if rel.count("/") == 1 else "?"),
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                "year": datetime.fromtimestamp(st.st_mtime).year,
                "bytes": st.st_size,
                "chars": len(text),
                "cjk": body_cjk,
                "lines": len(lines),
                "title": title,
                "h2": h2s,
                "cards": sorted(set(CARD_TG.findall(text)) | set(CARD_AG.findall(text))),
                "卡s": sorted(set(CARD_KA.findall(text) + CARD_KA.findall(p.stem))),
                "sent": sentence_candidates(text),
                "hdr_concl": heading_conclusion(text),
                "neg": any(k in head for k in NEGATIVE),
                "neg_words": sorted({k for k in NEGATIVE if k in head}),
            }
        )

    print(f"files: {len(files)}", file=sys.stderr)
    payload = {
        "root": str(ROOT),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rows": rows,
        "df": dict(df.most_common(400)),
        "tf": dict(tf.most_common(400)),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
