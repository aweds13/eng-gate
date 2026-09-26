r"""pin_check —— 改字面之前先查谁钉着它（T-G145，只读）。

**为什么有这个工具**（卡 053 §1，同类事故本会话已四次）：改一个「字面」，
而这个字面被别处（测试断言 / 台账证据 / 文档）逐字钉着 —— 措辞打穿过 3 条
`text:` 证据、`DEFAULT_MODEL` 打穿过 T-G85、`TASK_TYPES` 打穿过
tests/test_web_frontend.py:518 的逐字断言。每次都「撞上了才知道」，白费一轮。
仓库里已有 tools/evidence_map.py（按**文件**查谁挂着断言）—— 本工具补另一半：
按**字面**查谁钉着它。

用法：
    python -X utf8 tools/pin_check.py --literal "DEFAULT_MODEL = \"deepseek-v4.1-flash\""
    python -X utf8 tools/pin_check.py --literal \
        "const TASK_TYPES=['普通','作业','考试','论文','小测']"
    python -X utf8 tools/pin_check.py --literal "<字面1>" --literal "<字面2>"
    python -X utf8 tools/pin_check.py --literal "<字面>" --ledger-only

★ 什么时候跑 —— **开工前**：凡要改常量/字面/文案，先 --literal 查一遍；
  **集成前**：改过 src/**、tools/**、docs/** 的卡，逐个查它改动的字面。

★ 只读：读 git ls-files 与工作区文件，只打印报告，不写任何仓库文件。

命中分类：源码（src/**）/ 测试（tests/**）/ 工具（tools/**、scripts/**）/
文档（其余）/ 台账证据（docs/traceability.toml，命中时点名台账号）。
台账按**反转义后**的行匹配：TOML 把 " 存成 \"（转义存账），不反转义就
永远查不到 T-G85 那条 —— 钉子①正是它。

「钉子」标注：命中行里出现断言/证据语境（assert / in / == / includes( /
has( / text:）→ ★ 钉子；其余 → 叙述。宁可少标、不可滥标（卡 053 §7.1）。

退出码：零命中 = 0；有命中但无钉子 = 0；有任何 ★ 钉子命中 = 1
（将来好接门禁）；用法错误 = 2。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_REL = "docs/traceability.toml"

# 「钉子」语境标记（卡 053 §2.3）：命中行出现任一 → ★ 钉子，其余 → 叙述。
# 子串级判据，故意保守 —— 宁可少标、不可滥标（滥标会让零误报检验失去意义）。
PIN_MARKERS = ("assert", " in ", "==", "includes(", "has(", "text:")
CLIP = 120  # 命中行原文最多显示的字符数

# 台账条目头，如 [entries."T-G85"] —— 用来给台账命中点名台账号（卡 053 §7.2）。
ENTRY_RE = re.compile(r'^\[entries\."([^"]+)"\]')


@dataclass
class Hit:
    rel: str  # 仓库相对路径（posix）
    line_no: int
    text: str  # 命中行原文（截断到 CLIP）
    category: str  # 源码/测试/工具/文档/台账证据
    entry: str | None  # 台账号（仅台账命中时有）
    is_pin: bool  # True = ★ 钉子，False = 叙述


def toml_unescape(raw: str) -> str:
    """TOML 基本字符串的行内反转义（台账把 " 存作 \\"，不反转义查不到钉子①）。"""
    s = raw.replace("\\\\", "\x00")
    s = s.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
    return s.replace("\x00", "\\")


def classify(rel: str) -> str:
    if rel == LEDGER_REL:
        return "台账证据"
    if rel.startswith("src/"):
        return "源码"
    if rel.startswith("tests/"):
        return "测试"
    if rel.startswith(("tools/", "scripts/")):
        return "工具"
    return "文档"


def collect_files() -> list[str]:
    """git ls-files —— 只看被跟踪的文件（未跟踪文件本就不该被钉子盯着）。"""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def scan_file(rel: str, literal: str) -> list[Hit]:
    path = ROOT / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []  # 二进制/读不了的文件不参与
    hits: list[Hit] = []
    is_ledger = rel == LEDGER_REL
    entry: str | None = None
    for line_no, raw in enumerate(text.splitlines(), 1):
        if is_ledger:
            m = ENTRY_RE.match(raw.strip())
            if m:
                entry = m.group(1)
        variant = toml_unescape(raw) if is_ledger and "\\" in raw else raw
        if literal in raw:
            matched = raw
        elif literal in variant:
            matched = variant
        else:
            continue
        is_pin = any(marker in raw or marker in variant for marker in PIN_MARKERS)
        hits.append(
            Hit(
                rel=rel,
                line_no=line_no,
                text=matched.strip()[:CLIP],
                category=classify(rel),
                entry=entry if is_ledger else None,
                is_pin=is_pin,
            )
        )
    return hits


def scan_literal(literal: str, files: list[str], ledger_only: bool = False) -> list[Hit]:
    if ledger_only:
        files = [LEDGER_REL]
    hits: list[Hit] = []
    for rel in files:
        hits.extend(scan_file(rel, literal))
    if ledger_only:
        # --ledger-only 只看 text: 证据的命中（卡 053 §2.2）
        hits = [h for h in hits if "text:" in h.text]
    return hits


def render(literal: str, index: int, total: int, hits: list[Hit]) -> None:
    print(f"字面 {index}/{total}: {literal}")
    if not hits:
        print("  零命中")
        return
    ordered = sorted(hits, key=lambda h: (not h.is_pin, h.rel, h.line_no))
    for h in ordered:
        tag = "★ 钉子" if h.is_pin else "叙述"
        where = h.rel if h.entry is None else f"{h.rel}（台账号 {h.entry}）"
        print(f"  {tag} [{h.category}] {where}:{h.line_no}")
        print(f"      {h.text}")
    pins = sum(1 for h in hits if h.is_pin)
    print(f"  小结：命中 {len(hits)} 处（钉子 {pins} / 叙述 {len(hits) - pins}）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="改字面之前先查谁钉着它（只读；有 ★ 钉子命中时退出码 1）",
    )
    parser.add_argument(
        "--literal",
        action="append",
        required=True,
        help="要查的字面（可重复给多个）",
    )
    parser.add_argument(
        "--ledger-only",
        action="store_true",
        help="只看 docs/traceability.toml 里 text: 证据的命中",
    )
    args = parser.parse_args(argv)

    literals = args.literal
    if any(not lit for lit in literals):
        print("字面不能是空串", file=sys.stderr)
        return 2

    try:
        files = collect_files()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git ls-files 失败：{exc}", file=sys.stderr)
        return 2

    total_hits = 0
    total_pins = 0
    for i, literal in enumerate(literals, 1):
        hits = scan_literal(literal, files, ledger_only=args.ledger_only)
        total_hits += len(hits)
        total_pins += sum(1 for h in hits if h.is_pin)
        render(literal, i, len(literals), hits)

    if total_hits == 0:
        print(f"总计：{len(literals)} 个字面全部零命中")
        return 0
    if total_pins:
        print(
            f"总计：命中 {total_hits} 处，其中 ★ 钉子 {total_pins} 处"
            " → 退出码 1（改这些字面前先核对钉子）"
        )
        return 1
    print(f"总计：命中 {total_hits} 处，无钉子 → 退出码 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
