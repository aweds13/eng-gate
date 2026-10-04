r"""压缩文书判据：结构预算 + 指针核对（卡 164 / T-G264 · §17 第 5~6 条）。

文书的读者是下一个干活的人，不是证据档案。所以文书有**结构预算**：
  - 全文 ≤ 60 行（CHECKPOINT 片段）
  - gaps ≤ 6 条，每条 ≤ 3 行
  - changelog 每卡一节，≤ 6 行
  - 老实说 ≤ 4 条
超了 ⇒ 退回并指出超的是哪一节、超多少（**不许只说"太长"**）。

gaps 里每条必须带**指针**（快照 id / 日志路径 / 既有文档 / 提交 sha）——
压缩之所以安全，全靠"压掉的指得出来"；没有这条，压缩就是丢证据。
指针要**真存在**（文件在磁盘上 / sha 在 git 里 / 快照 id 在快照表里）。

★ 落地位置：`tools/pool/stage_card.py` 的 `_selfcheck`（写完文书立刻验）。
  选它不选 `scripts/audit_progress.py` 的理由：`stage_card` 是**收口时写文书**的工具，
  文书刚写完就检查预算最自然（fail fast，别等审计）；`audit_progress` 是提交前审计，
  那时文书已写好、退回要重做。`stage_card` 已有 `_selfcheck`，加预算检查是同一种
  "写后自检"的延伸。本卡只建判据工具 + 钉子；接进 `_selfcheck` 是后续卡的事。

用法：
    from tools.card_doc_budget import check_budget, check_pointers
    problems = check_budget(checkpoint=cp, gaps=gp, changelog=cl)
    problems += check_pointers(gp, root=Path("."))
"""
from __future__ import annotations

import pathlib
import re
import subprocess

MAX_CHECKPOINT_LINES = 60
MAX_GAPS_ITEMS = 6
MAX_GAP_LINES = 3
MAX_CHANGELOG_LINES = 6
MAX_HONEST_ITEMS = 4

_HONEST_HEADER = re.compile(r"\*?\*?\s*★?\s*\*?\*?\s*老实说\s*\*?\*?\s*：?")
_ITEM_NUM = re.compile(r"^\s*(\d+\.|[①-⑳]|[（(]\d+[)）])\s")
_GAP_NUM = re.compile(r"^\s*(\d+\.|[①-⑳]|[（(]\d+[)）]|[-*•·])\s")
_PTR_PATH = re.compile(r"([\w./\\-]+[/\\][\w./\\-]+\.[a-zA-Z]{1,5}(?::\d+)?)")
_PTR_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
_PTR_SNAPSHOT = re.compile(r"\b(snap[-_]?\d+|[A-Z0-9]{8,}-snap)\b", re.IGNORECASE)


def _split_gaps(gaps: str) -> list[list[str]]:
    """把 gaps 原文按编号条目切成「每条 = 它占的源文行列表」。

    编号形态：`1.` / `①` / `(1)` / `-` / `*` / `•` / `·` 开头算新条；
    不以这些开头的非空行**续接当前条**。没有任何编号标记 ⇒ 整段算一条。
    """
    items: list[list[str]] = []
    cur: list[str] = []
    for line in gaps.splitlines():
        if _GAP_NUM.match(line):
            if cur:
                items.append(cur)
            cur = [line]
        elif line.strip():
            if not cur:
                cur = [line]
            else:
                cur.append(line)
    if cur:
        items.append(cur)
    return items or [[gaps]] if gaps.strip() else []


def _split_honest(checkpoint: str) -> list[str]:
    """从 CHECKPOINT 里切出「老实说」后面的编号条目（`1.` / `①` / `(1)` 开头）。"""
    lines = checkpoint.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "老实说" in ln and ("★" in ln or "**" in ln):
            start = i + 1
            break
    if start is None:
        return []
    items: list[str] = []
    cur: list[str] = []
    for ln in lines[start:]:
        if _ITEM_NUM.match(ln):
            if cur:
                items.append("\n".join(cur))
            cur = [ln]
        elif ln.strip():
            if cur:
                cur.append(ln)
    if cur:
        items.append("\n".join(cur))
    return items


def check_budget(
    *,
    checkpoint: str,
    gaps: str,
    changelog: str,
) -> list[str]:
    """检查文书结构预算。返回问题列表（每条指出哪一节超多少）；空列表 = 合规。

    ★ 不许只说"太长"——每条问题都带**哪一节、超多少**。
    """
    problems: list[str] = []

    cp_lines = checkpoint.splitlines()
    if len(cp_lines) > MAX_CHECKPOINT_LINES:
        problems.append(
            f"checkpoint {len(cp_lines)} 行 > 上限 {MAX_CHECKPOINT_LINES}（超 "
            f"{len(cp_lines) - MAX_CHECKPOINT_LINES} 行）"
        )

    honest = _split_honest(checkpoint)
    if len(honest) > MAX_HONEST_ITEMS:
        problems.append(
            f"老实说 {len(honest)} 条 > 上限 {MAX_HONEST_ITEMS}（超 "
            f"{len(honest) - MAX_HONEST_ITEMS} 条）"
        )

    gap_items = _split_gaps(gaps)
    if len(gap_items) > MAX_GAPS_ITEMS:
        problems.append(
            f"gaps {len(gap_items)} 条 > 上限 {MAX_GAPS_ITEMS}（超 "
            f"{len(gap_items) - MAX_GAPS_ITEMS} 条）"
        )
    for idx, item in enumerate(gap_items, 1):
        if len(item) > MAX_GAP_LINES:
            problems.append(
                f"gaps 第 {idx} 条 {len(item)} 行 > 上限 {MAX_GAP_LINES}（超 "
                f"{len(item) - MAX_GAP_LINES} 行）"
            )

    cl_lines = changelog.splitlines()
    if len(cl_lines) > MAX_CHANGELOG_LINES:
        problems.append(
            f"changelog {len(cl_lines)} 行 > 上限 {MAX_CHANGELOG_LINES}（应每卡一行摘要，超 "
            f"{len(cl_lines) - MAX_CHANGELOG_LINES} 行）"
        )

    return problems


def _find_pointers(text: str) -> list[str]:
    """从一段文本里找出指针（文件路径 / commit sha / 快照 id）。返回去重后的指针串列表。"""
    found: list[str] = []
    for m in _PTR_PATH.finditer(text):
        found.append(m.group(1))
    for m in _PTR_SHA.finditer(text):
        s = m.group(1)
        if any(c in "abcdef" for c in s.lower()):
            found.append(s)
    for m in _PTR_SNAPSHOT.finditer(text):
        found.append(m.group(1))
    seen: set[str] = set()
    out: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _pointer_exists(ptr: str, root: pathlib.Path) -> tuple[bool, str]:
    """验一个指针真的存在。返回 (在不在, 理由)。"""
    if "/" in ptr or "\\" in ptr:
        path_part = ptr.split(":")[0]
        cand = root / path_part
        if cand.is_file():
            return True, f"文件 {path_part}"
        cand2 = pathlib.Path(path_part)
        if not cand2.is_absolute() and cand2.is_file():
            return True, f"文件 {path_part}（相对 cwd）"
        return False, f"文件 {path_part} 不存在"
    if re.fullmatch(r"[0-9a-f]{7,40}", ptr):
        r = subprocess.run(
            ["git", "cat-file", "-e", ptr],
            cwd=str(root), capture_output=True, check=False,
            # ★ 防窗旗（卡 164）：Windows 上别弹控制台窗口（POSIX 上落到 0 = 无操作）。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0:
            return True, f"git 对象 {ptr}"
        return False, f"git 里没有对象 {ptr}"
    if _PTR_SNAPSHOT.fullmatch(ptr):
        snap = root / "gates" / "diag" / "_snapshots.txt"
        if snap.is_file() and ptr in snap.read_text(encoding="utf-8", errors="replace"):
            return True, f"快照 {ptr}"
        where = "不在" if not snap.is_file() else "在但无此 id"
        return False, f"快照 {ptr} 不在 _snapshots.txt（文件{where}）"
    return False, f"不认识的指针形态 {ptr}"


def check_pointers(gaps: str, root: pathlib.Path) -> list[str]:
    """检查 gaps 里每条都带指针且指针真存在。返回问题列表；空列表 = 合规。"""
    problems: list[str] = []
    items = _split_gaps(gaps)
    if not items:
        problems.append("gaps 为空 —— 没有指针也没有边界说明")
        return problems
    for idx, item in enumerate(items, 1):
        text = "\n".join(item)
        ptrs = _find_pointers(text)
        if not ptrs:
            problems.append(f"gaps 第 {idx} 条没有指针（须带文件路径 / commit sha / 快照 id）")
            continue
        for ptr in ptrs:
            ok, why = _pointer_exists(ptr, root)
            if not ok:
                problems.append(f"gaps 第 {idx} 条指针 {ptr} 不存在：{why}")
    return problems


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="检查一份卡文书的结构预算与指针")
    ap.add_argument("--checkpoint-file")
    ap.add_argument("--gaps-file")
    ap.add_argument("--changelog-file")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = pathlib.Path(a.root).resolve()
    cp = pathlib.Path(a.checkpoint_file).read_text(encoding="utf-8") if a.checkpoint_file else ""
    gp = pathlib.Path(a.gaps_file).read_text(encoding="utf-8") if a.gaps_file else ""
    cl = pathlib.Path(a.changelog_file).read_text(encoding="utf-8") if a.changelog_file else ""
    problems = check_budget(checkpoint=cp, gaps=gp, changelog=cl)
    if gp.strip():
        problems += check_pointers(gp, root)
    if problems:
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK（结构预算 + 指针全过）")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
