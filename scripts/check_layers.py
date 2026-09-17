"""六层对齐检查（护栏）：intention → specification(含 conventions) → contracts → implementation ← taste。

层级（本项目文档体系）：
  intention/        为什么做（N1–N46）
  specification/    必须做到什么（SR-F / SR-NF）+ conventions.md（横切约定）
  contracts/        怎样才算真的做成（interactions 操作闭环 / flows 动线）
  implementation/   哪个模块负责
  taste/            技术品味与红线

检查项：
1. 编号闭合：每个 N 都在 spec 追踪里被引用；每个 SR 都在 impl 追踪里有模块
   （支持范围简写 SR-F1.1~F1.9 / SR-NF1~NF5 / SR-NF6~NF8,NF13~NF15）。
2. 词表护栏：留「已砍概念」则失败；但否定语境（如"不设目标实体"）豁免。
3. 约定层存在性：conventions.md 必须存在，且其规则条目须标注来源 N。
4. 契约层存在性与覆盖：interactions.md / flows.md 必须存在；
   contracts 中引用的 SR 须能在 specification 中找到。
5. 引用完整性：文档中引用的 docs 内相对路径必须真实存在。

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
CONVENTIONS = ROOT / "docs" / "specification" / "conventions.md"
CONTRACTS = ROOT / "docs" / "contracts"
INTERACTIONS = CONTRACTS / "interactions.md"
FLOWS = CONTRACTS / "flows.md"

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


def check_link_integrity() -> list[str]:
    """检查 docs 内文档引用的相对路径是否真实存在。

    路径可能相对「当前文档」或相对「docs/ 根」书写（两种约定都常见），
    故对每个候选路径依次尝试多个基准目录，命中其一即算通过。
    已显式声明"待建/不存在"的目标（见 KNOWN_MISSING）豁免。
    """
    KNOWN_MISSING = {"DESIGN.md", "LEARN.md"}  # 文档中已标注为"待建"，不算断链
    problems: list[str] = []
    docs_root = ROOT / "docs"
    # 匹配形如 `../contracts/flows.md` / `contracts/interactions.md` / `specification/x.md` 的反引号路径
    pattern = re.compile(r"`(\.{0,2}/?[A-Za-z0-9_\-/]+\.md)`")
    for md in docs_root.rglob("*.md"):
        text = read(md)
        for m in pattern.finditer(text):
            rel = m.group(1)
            if rel.startswith("http"):
                continue
            if Path(rel).name in KNOWN_MISSING:
                continue
            # 多基准尝试：相对当前文档 / 相对 docs 根 / 相对仓库根 / 相对 docs 各子目录
            candidates = [
                (md.parent / rel).resolve(),
                (docs_root / rel).resolve(),
                (ROOT / rel).resolve(),
            ]
            # 裸文件名（无目录分隔）时，在 docs 下递归查找同名文件
            if "/" not in rel:
                candidates += [p.resolve() for p in docs_root.rglob(rel)]
            if not any(c.exists() for c in candidates):
                problems.append(f"{md.relative_to(ROOT)} 引用了不存在的 {rel}")
    return problems


def main() -> int:
    ok = True

    # --- 1. 编号闭合 ---
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

    # --- 2. 词表护栏 ---
    for path in (INT, SPEC_TRACE, IMPL_TRACE):
        hits = forbidden_hits(read(path))
        if hits:
            print(f"[FAIL] 已砍概念残留 {path.name}: {hits}")
            ok = False

    # --- 3. 约定层存在性 + 来源 N 标注 ---
    conv_text = read(CONVENTIONS)
    if not conv_text:
        print("[FAIL] 约定层缺失: docs/specification/conventions.md")
        ok = False
    else:
        rule_lines = [
            ln for ln in conv_text.splitlines()
            if ln.strip().startswith("- ") and not ln.strip().startswith("- *")
        ]
        unlabeled = [ln for ln in rule_lines if not extract_n(ln)]
        if unlabeled:
            print(f"[FAIL] 约定层有 {len(unlabeled)} 条规则未标注来源 N（示例: {unlabeled[0][:40]}...）")
            ok = False

    # --- 4. 契约层存在性与 SR 可追溯 ---
    for contract in (INTERACTIONS, FLOWS):
        if not contract.exists():
            print(f"[FAIL] 契约层缺失: {contract.relative_to(ROOT)}")
            ok = False
    if INTERACTIONS.exists() and FLOWS.exists():
        contract_text = read(INTERACTIONS) + read(FLOWS)
        contract_srs = extract_srs(contract_text)
        unknown = contract_srs - spec_srs - impl_srs
        if unknown:
            print(f"[FAIL] 契约层引用了 specification 中不存在的 SR: {sorted(unknown)}")
            ok = False

    # --- 5. 引用完整性 ---
    broken = check_link_integrity()
    if broken:
        for b in broken[:10]:
            print(f"[FAIL] 引用断裂: {b}")
        if len(broken) > 10:
            print(f"       …等共 {len(broken)} 处")
        ok = False

    print("LAYER CHECKS:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
