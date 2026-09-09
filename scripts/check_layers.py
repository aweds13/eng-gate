"""三层对齐检查（护栏）：intent → spec → impl ← taste。

1. 编号闭合：每个 N 都在 spec 追踪里被引用；每个 SR 都在 impl 追踪里有模块（支持范围简写 SR-F1.1~F1.9 / SR-NF1~NF5 / SR-NF6~NF8,NF13~NF15）。
2. 词表护栏：留「已砍概念」则失败；但否定语境（如"不设目标实体""不折算成""砍掉 X"）豁免（那是明确不做的陈述）。

用法：python scripts/check_layers.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INT = ROOT / "docs" / "intention" / "needs.md"
SPEC_TRACE = ROOT / "docs" / "specification" / "traceability.md"
IMPL_TRACE = ROOT / "docs" / "implementation" / "traceability.md"

FORBIDDEN = ["目标实体", "时间折算", "折算成", "学期分账", "Assigned to me"]
NEG = ["不", "无", "砍", "去", "免", "禁", "避免", "杜绝", "不要", "不设"]

N_RE = r"\bN\d+\b"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def extract_n(text: str) -> set[str]:
    return set(re.findall(N_RE, text))


def extract_srs(text: str) -> set[str]:
    """提取 SR 引用，展开范围简写（SR-F1.1~F1.9 / SR-NF1~NF5 / SR-NF6~NF8,NF13~NF15）。"""
    srs: set[str] = set()
    # 范围 F：SR-F{d}.{a}~F{d}.{b}
    for m in re.finditer(r"SR-F(\d+)\.(\d+)~F\d+\.(\d+)", text):
        for i in range(int(m.group(2)), int(m.group(3)) + 1):
            srs.add(f"SR-F{m.group(1)}.{i}")
    # 范围 NF：SR-NF{a}~NF{b}
    for m in re.finditer(r"SR-NF(\d+)~NF(\d+)", text):
        for i in range(int(m.group(1)), int(m.group(2)) + 1):
            srs.add(f"SR-NF{i}")
    # 单项 F / NF
    for m in re.finditer(r"SR-F(\d+)\.(\d+)", text):
        srs.add(f"SR-F{m.group(1)}.{m.group(2)}")
    for m in re.finditer(r"SR-NF(\d+)", text):
        srs.add(f"SR-NF{m.group(1)}")
    return srs


def forbidden_hits(text: str) -> list[str]:
    hits: list[str] = []
    for kw in FORBIDDEN:
        for m in re.finditer(re.escape(kw), text):
            pre = text[max(0, m.start() - 8): m.start()]
            if any(neg in pre for neg in NEG):
                continue
            hits.append(kw)
    return hits


def main() -> int:
    ok = True

    n_ids = extract_n(read(INT))
    spec_n_refs = extract_n(read(SPEC_TRACE))
    spec_srs = extract_srs(read(SPEC_TRACE))
    impl_srs = extract_srs(read(IMPL_TRACE))

    missing_n = {n for n in n_ids if n not in spec_n_refs}
    if missing_n:
        print(f"[FAIL] N 未在 spec 追踪被引用: {sorted(missing_n, key=lambda s: int(s[1:]))}")
        ok = False

    missing_sr = spec_srs - impl_srs
    if missing_sr:
        print(f"[FAIL] SR 未在 impl 追踪有模块: {sorted(missing_sr)}")
        ok = False

    for path in (INT, SPEC_TRACE, IMPL_TRACE):
        hits = forbidden_hits(read(path))
        if hits:
            print(f"[FAIL] 已砍概念残留 {path.name}: {hits}")
            ok = False

    print("THREE-LAYER CHECKS:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
