r"""汇总「每笔一个片段」到三个共享文档（卡 107 · T-G203）。

病（用户 2026-10-01 拍板 B 方案）：本仓**每一笔提交**都在**同三个共享文档**的**同一锚点**插入 ——
`docs/changelog.md`（文件头插一节 `## 2026-…`）·
`docs/traceability.toml`（末尾追加 `[entries.<台账号>]`）·
`复盘/交接-重构进度.md`（同一锚点插一段 CHECKPOINT）。两笔并发 ⇒ 第二笔 rebase **必冲突**
（于是"门禁能并行、提交只能串行"）。改成「**每笔一个小文件**」后，作者只动**自己那一个片段**，
由集成者在本工具里**串行合并** ⇒ 零冲突，而封存语义不用缩（仍是整棵提交树）。

片段位置（一个台账号一笔）：
    docs/changelog.d/<台账号>.md       —— 一节 `## 2026-…` + 正文（**原文照搬**，含标题后的空行）
    docs/traceability.d/<台账号>.toml  —— 一段 `[entries."<台账号>"]` 表（其余字段与现文件同形）
    复盘/交接.d/<台账号>.md             —— 一段 `> **…CHECKPOINT…**` 引用块（含末尾 `>` 分隔行）

用法：
    python -X utf8 tools/sync_docs.py             # 把片段汇进三个共享文档（**幂等**）
    python -X utf8 tools/sync_docs.py --check      # 只核对「片段 ↔ 汇总」，不一致退 1 并**点名**
    python -X utf8 tools/sync_docs.py --root DIR   # 换根（测试用；默认 = 本仓根）

★ 硬约束（卡 §禁区）：
  1. 汇总**只插入**片段内容、**绝不改写既有字节** —— 幂等：连跑两次，第二次零 diff；
     片段目录为空 ⇒ 三个共享文档**逐字不变**（sha256 不变）。
  2. 顺序**逐字等于现在的形态**：changelog 新片段接文件头（新→旧）· traceability 新片段接文件尾 ·
     交接新片段按锚点插在第一个 CHECKPOINT 段之前（新→旧）。
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 交接文档里「一段 CHECKPOINT」的行首长这样：`> **2026-10-01 · CHECKPOINT（卡 103 · `T-G199`）…`
CHECKPOINT_ANCHOR_RE = re.compile(r"^\s*>\s*\*\*.*CHECKPOINT")


def _norm(text: str) -> str:
    """逐行去尾部空白 + 去掉首尾空行 —— 判断"片段在不在"就按它比（对编辑器换行差异不敏感）。"""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


def _rel(path: str | Path, root: Path) -> str:
    p = Path(path)
    return p.relative_to(root).as_posix() if p.is_relative_to(root) else p.as_posix()


# ---------------------------------------------------------------- 三种"汇进哪里"的规则


def _merge_changelog(target: str, pending: list[tuple[str, str]]) -> str:
    """新片段按新→旧接在**文件头**（现有形态本来就是新→旧；首行仍是 `## 2026-`）。"""
    prefix = "\n".join(_norm(t) for _n, t in pending)
    return prefix + "\n" + target


def _merge_traceability(target: str, pending: list[tuple[str, str]]) -> str:
    """新 `[entries.*]` 表接在**文件尾**（现有条目的排列就是先来的在上、新条目追加在后）。"""
    base = target.rstrip("\n")
    body = "\n\n".join(_norm(t) for _n, t in pending)
    return base + "\n\n" + body + "\n"


def _handoff_anchor_offset(text: str) -> int:
    """新 CHECKPOINT 该插进去的**字符偏移** = 第一个 CHECKPOINT 段的行首。

    找不到（文档结构异常）→ 接在**末尾**（保底：既不丢内容，也不静默丢片段）。
    """
    pos = 0
    for line in text.splitlines(keepends=True):
        if CHECKPOINT_ANCHOR_RE.match(line):
            return pos
        pos += len(line)
    return len(text)


def _ensure_sep(text: str) -> str:
    """交接文档里两段 CHECKPOINT 之间用一行 `>` 分隔（现文件就是这个约定）。"""
    s = _norm(text)
    return s if s.endswith("\n>") else s + "\n>"


def _merge_handoff(target: str, pending: list[tuple[str, str]]) -> str:
    offset = _handoff_anchor_offset(target)
    prefix = "\n".join(_ensure_sep(t) for _n, t in pending)
    return target[:offset] + prefix + "\n" + target[offset:]


@dataclass(frozen=True)
class Channel:
    """一个"片段目录 → 一个共享文档"的通道。"""

    name: str  # 人话名（报错点名用）
    frag_dir: Path
    target: Path
    suffix: str  # 片段文件名后缀（`.md` / `.toml`）
    order_key: Callable[[str, str], tuple[str, str]]
    reverse: bool  # True = 新的排前面（changelog / 交接）；False = 按名升序（traceability）
    merge: Callable[[str, list[tuple[str, str]]], str]


def _date_key(name: str, text: str) -> tuple[str, str]:
    m = DATE_RE.search(text)
    return (m.group(0) if m else "", name)


def _name_key(name: str, text: str) -> tuple[str, str]:
    return (name, "")


def build_channels(root: Path) -> list[Channel]:
    return [
        Channel("changelog", root / "docs" / "changelog.d", root / "docs" / "changelog.md",
                ".md", _date_key, True, _merge_changelog),
        Channel("traceability", root / "docs" / "traceability.d",
                root / "docs" / "traceability.toml", ".toml",
                _name_key, False, _merge_traceability),
        Channel("交接", root / "复盘" / "交接.d", root / "复盘" / "交接-重构进度.md",
                ".md", _date_key, True, _merge_handoff),
    ]


# ---------------------------------------------------------------- 片段收集 / 汇总 / 核对


def _fragment_files(ch: Channel) -> list[Path]:
    """片段目录里**算数**的文件：指定后缀、非点文件、非 README。

    （`git ls-files --others` 会把 `.gitkeep` 也列出来，这里要把它挡掉。）
    """
    if not ch.frag_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(ch.frag_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(ch.suffix):
            continue
        if p.name.startswith(".") or p.name.lower().startswith("readme"):
            continue
        out.append(p)
    return out


def _collect_pending(ch: Channel, target_norm: str) -> list[tuple[str, str]]:
    """还没汇进汇总文件的片段（按 `order_key` 排好序）。已汇过的（内容已在 target 里）跳过。"""
    out: list[tuple[str, str]] = []
    for p in _fragment_files(ch):
        text = p.read_text(encoding="utf-8")
        norm = _norm(text)
        if norm and norm not in target_norm:
            out.append((str(p), text))
    out.sort(key=lambda item: ch.order_key(Path(item[0]).name, item[1]), reverse=ch.reverse)
    return out


def _read_target(ch: Channel) -> str:
    return ch.target.read_text(encoding="utf-8") if ch.target.exists() else ""


def run(root: Path, *, check: bool) -> int:
    """check=True 只核对；check=False 把待汇总片段写回三个共享文档。返回进程退出码。"""
    if check:
        problems: list[str] = []
        counts: list[str] = []
        for ch in build_channels(root):
            target_norm = _norm(_read_target(ch))
            pending = _collect_pending(ch, target_norm)
            counts.append(f"{ch.frag_dir.name}={len(_fragment_files(ch))}")
            for path, _text in pending:
                problems.append(
                    f"{_rel(path, root)} 的内容没在 {_rel(ch.target, root)} 里"
                    "（跑 `python -X utf8 tools/sync_docs.py` 汇总）"
                )
        if problems:
            print("[FAIL] 片段 ↔ 汇总不一致：手改了汇总却没改片段，或反之 ——")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"[OK ] 片段 ↔ 汇总一致（{', '.join(counts)}）")
        return 0

    changed: list[str] = []
    for ch in build_channels(root):
        target = _read_target(ch)
        pending = _collect_pending(ch, _norm(target))
        if not pending:
            continue
        ch.target.parent.mkdir(parents=True, exist_ok=True)
        merged = ch.merge(target, pending)
        # ★ 主控补（T-G203 集成时）：**行尾跟着目标文件走** —— 这三个共享文档是**纯 CRLF**，
        #   原来写死 newline="\n"，一汇总整份变 LF（_stage_card.py 的行尾断言当场抓住）。
        _raw = ch.target.read_bytes()
        _nl = "\r\n" if b"\r\n" in _raw else "\n"
        ch.target.write_text(merged.replace("\n", _nl), encoding="utf-8", newline="")
        changed.append(f"{_rel(ch.target, root)}（+{len(pending)}）")
    if changed:
        print(f"[OK ] 汇总完成：{' · '.join(changed)}")
    else:
        print("[OK ] 无待汇总片段 —— 三个共享文档逐字不变")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把「每笔一个片段」汇进三个共享文档（卡 107 · T-G203）"
    )
    ap.add_argument("--check", action="store_true",
                    help="只核对「片段 == 汇总」；不一致退 1 并点名（接进门禁用）")
    ap.add_argument("--root", default="", help="仓库根（默认 = 本脚本所在仓；测试可换）")
    args = ap.parse_args()
    root = (Path(args.root).expanduser().resolve() if args.root
            else Path(__file__).resolve().parent.parent)
    return run(root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
