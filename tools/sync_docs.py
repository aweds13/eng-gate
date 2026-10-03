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
    python -X utf8 tools/sync_docs.py --check      # 核对「片段 ↔ 汇总」（不一致退 1 并点名）；
                                                   # 另查 changelog 次序，错了报 WARN 并点名两节日期
    python -X utf8 tools/sync_docs.py --root DIR   # 换根（测试用；默认 = 本仓根）

★ 硬约束（卡 §禁区）：
  1. 汇总**只插入**片段内容、**绝不改写既有字节** —— 幂等：连跑两次，第二次零 diff；
     片段目录为空 ⇒ 三个共享文档**逐字不变**（sha256 不变）。
  2. 顺序：traceability 新片段接**文件尾**、交接新片段按锚点插在第一个 CHECKPOINT 段之前
     （这两个通道**没动**）；★ changelog 新片段**按日期插到正确位置**（新的在上、旧的在下；
     **同一天保持已有序**，不搅乱同日次序）—— 卡 126（`T-G224`）改的口径，治「rebase 里本笔
     （更老）被一律插到文件头 ⇒ 老日期压住新日期」（`复盘/口径坑.md` 坑 32 的自动重演）。
     ★ 次序错时 `--check` 报 **WARN 并点名两节日期**，但**不改退出码**（真仓可能有历史倒置，
     硬失败会打穿既有断言
     `tests/test_docs_fragments.py::test_real_repo_is_in_sync_and_merge_is_noop`）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# `python -P -X utf8 tools/sync_docs.py`（-P 不把脚本目录放进 sys.path）也要能 import pool：
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pool.no_window import NO_WINDOW  # noqa: E402  ★ 卡 159 收尾：子进程一律不弹窗（唯一真源）

if TYPE_CHECKING:
    from collections.abc import Callable

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# changelog 里「一节」的行首长这样：`## 2026-10-02 —— …`
CHANGELOG_SECTION_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})", re.MULTILINE)
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


def _changelog_sections(text: str) -> list[tuple[int, str, int]]:
    """目标文件里每个 `## <日期>` 节的 `(起始偏移, 日期, 结束偏移)`，按出现次序。"""
    hits = list(CHANGELOG_SECTION_RE.finditer(text))
    spans: list[tuple[int, str, int]] = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        spans.append((m.start(), m.group(1), end))
    return spans


def _insert_changelog_block(text: str, block: str) -> str:
    """把一节（`block`，已 `_norm`）插进 `text` 的**日期正确位置**（**只插入、不改写既有字节**）。

    规则：新的在上、旧的在下 —— 插到**第一个日期严格更旧**的节之前（`<` 而非 `<=`
    ⇒ 同日**不**插到已有同日节之上，**不搅乱同日次序**）。找不到更旧的节 = 它比所有既有节
    都更旧（或无节）⇒ 接在**末尾**；片段自身无日期 ⇒ 保底接文件头（旧行为）。
    """
    m = DATE_RE.search(block)
    if m is None:
        return (block + "\n" + text) if text else (block + "\n")
    block_date = m.group(0)
    for start, sec_date, _end in _changelog_sections(text):
        if sec_date < block_date:
            return text[:start] + block + "\n" + text[start:]
    if not text:
        return block + "\n"
    tail = text if text.endswith("\n") else text + "\n"
    return tail + block + "\n"


def _merge_changelog(target: str, pending: list[tuple[str, str]]) -> str:
    """新片段**按日期插入**：新的在上、旧的在下（同一天保持传入次序，不搅乱同日次序）。

    旧口径是「一律接文件头」—— rebase 场景里基线已含对方**日期更新**的那节，
    本笔（日期更老）再插到文件头 ⇒ **老日期压在新日期上面**，坑 32 原样重演（且是自动的）。
    """
    text = target
    for _name, raw in pending:  # `pending` 已按新→旧排好；同日保持传入次序
        text = _insert_changelog_block(text, _norm(raw))
    return text


def _changelog_order_problems(rel_name: str, target: str) -> list[str]:
    """changelog 各节是否**新在上、旧在下**；倒置就点名**相邻两节的日期**（只报不阻断）。"""
    spans = _changelog_sections(target)
    out: list[str] = []
    for (_s0, prev_date, _e0), (_s1, cur_date, _e1) in zip(spans, spans[1:], strict=False):
        if cur_date > prev_date:
            out.append(
                f"{rel_name} 次序错：`## {prev_date}`（上）排在 `## {cur_date}`（下）上面"
                " —— 新的应在上面"
            )
    return out


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


# ---------------------------------------------------------------- 反方向核对（卡 159 · T-G259）
# 老的 --check 只查「片段没进汇总」一个方向；这里补另一半：**汇总里有、片段已经没了**。
# ★ 要能区分两种情形（卡 159 原话）：
#   「片段被删了」= git 里跟踪过 / HEAD 里有 / 历史上删过 ⇒ 判红（内容还在汇总、来源却没了）；
#   「本来就是汇总独有」= 片段从未存在（片段机制 T-G203 之前的老账、SR-*/OP-* 这类
#   从不落片段的条目）⇒ 只报一行信息，**不判红**（真仓里这类是多数，判红会打穿既有门）。

_ENTRY_ID_RE = re.compile(r'\[entries\."([^"]+)"\]')
_TG_ID_RE = re.compile(r"T-G(\d+)")


def _summary_unit_ids(ch: Channel, target: str) -> set[str]:
    """汇总文件里每个「片段纪元」单元的台账号（反方向核对用）。

    traceability 按条目头 `[entries."X"]` 取；changelog / 交接按每节**标题行**里
    第一个 `T-Gnnn` 取（每节的自己的台账号约定俗成排在前面）。
    """
    if ch.name == "traceability":
        return set(_ENTRY_ID_RE.findall(target))
    line_re = (re.compile(r"^##.*$", re.MULTILINE) if ch.name == "changelog"
               else re.compile(r"^>.*CHECKPOINT.*$", re.MULTILINE))
    ids: set[str] = set()
    for m in line_re.finditer(target):
        tm = _TG_ID_RE.search(m.group(0))
        if tm:
            ids.add(f"T-G{tm.group(1)}")
    return ids


def _git_fragment_names(root: Path, ch: Channel) -> tuple[set[str], set[str], set[str]]:
    """`(index 跟踪的, HEAD 树里有的, 历史上删过的)` 片段名集合（不带后缀）。

    不是 git 仓库 / git 失败 ⇒ 三个空集（降级：无从判断「被删」，只影响判红那半，
    汇总独有的信息行照报）。
    """
    def _run(*args: str) -> list[str]:
        done = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=root, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, **NO_WINDOW,
        )
        if done.returncode != 0:
            return []
        return [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]

    rel_dir = _rel(ch.frag_dir, root)
    names: set[str] = set()
    out: list[set[str]] = []
    for argv in (
        ("ls-files", "--", rel_dir),  # ls-files 默认就打印文件名（没有 --name-only 这个旗标）
        ("ls-tree", "--name-only", "HEAD", "--", rel_dir),
        ("log", "--diff-filter=D", "--name-only", "--format=", "--", rel_dir),
    ):
        got = {Path(p).name for p in _run(*argv)}
        got = {n[: -len(ch.suffix)] for n in got if n.endswith(ch.suffix)}
        out.append(got)
        names |= got
    return out[0], out[1], out[2]


def _reverse_fragment_problems(ch: Channel, target: str, root: Path) -> tuple[list[str], list[str]]:
    """反方向核对：回 (判红的问题, 只报不红的汇总独有)。"""
    present = {p.stem for p in _fragment_files(ch)}
    tracked, in_head, deleted_ever = _git_fragment_names(root, ch)
    problems: list[str] = []
    solo: list[str] = []
    for uid in sorted(_summary_unit_ids(ch, target)):
        if uid in present:
            continue
        frag = _rel(ch.frag_dir / f"{uid}{ch.suffix}", root)
        if uid in tracked or uid in in_head or uid in deleted_ever:
            problems.append(
                f"{frag} 片段没了，但 {_rel(ch.target, root)} 里还有它的内容"
                " —— 片段被删了（把片段找回来，或把汇总里那段一起撤掉）"
            )
        else:
            solo.append(f"{_rel(ch.target, root)} 里有 {uid}，但没有对应片段"
                        "（本来就是汇总独有：片段纪元（T-G203）前的老账或从不落片段的条目）")
    return problems, solo


def run(root: Path, *, check: bool) -> int:
    """check=True 只核对；check=False 把待汇总片段写回三个共享文档。返回进程退出码。"""
    if check:
        problems: list[str] = []
        warnings: list[str] = []
        solo: list[str] = []
        counts: list[str] = []
        for ch in build_channels(root):
            target = _read_target(ch)
            target_norm = _norm(target)
            pending = _collect_pending(ch, target_norm)
            counts.append(f"{ch.frag_dir.name}={len(_fragment_files(ch))}")
            for path, _text in pending:
                problems.append(
                    f"{_rel(path, root)} 的内容没在 {_rel(ch.target, root)} 里"
                    "（跑 `python -X utf8 tools/sync_docs.py` 汇总）"
                )
            # ★ 卡 159（T-G259）：反方向 —— 汇总里有、片段已经没了。
            #   区分「片段被删了」（判红）与「本来就是汇总独有」（只报一行，不判红）。
            rev_problems, rev_solo = _reverse_fragment_problems(ch, target, root)
            problems.extend(rev_problems)
            solo.extend(rev_solo)
            # ★ 卡 126（T-G224）：changelog 另查**次序**（旧实现只查「片段在不在」，次序错抓不到）。
            if ch.name == "changelog" and target:
                warnings.extend(_changelog_order_problems(_rel(ch.target, root), target))
        for w in warnings:
            print(f"[WARN] {w}")  # ★ 只报、不改退出码（真仓有历史倒置，见模块头）
        for s in solo[:5]:
            print(f"[info] {s}")  # 汇总独有：如实留痕，不判红（见 _reverse_fragment_problems）
        if len(solo) > 5:
            print(f"[info] …另有 {len(solo) - 5} 条「汇总独有」（老账，不判红）")
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
                    help="只核对「片段 == 汇总」；不一致退 1 并点名（接进门禁用）；"
                         "另查 changelog 次序，错了报 WARN 并点名两节日期")
    ap.add_argument("--root", default="", help="仓库根（默认 = 本脚本所在仓；测试可换）")
    args = ap.parse_args()
    root = (Path(args.root).expanduser().resolve() if args.root
            else Path(__file__).resolve().parent.parent)
    return run(root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
