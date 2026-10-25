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

★ 卡 E38（T-AG492）改了三处口径（每处都是真踩过的静默）：
  1. **按「台账号 + 块类型」替换，不再按标题去重**：以前用「片段内容是不是汇总的子串」
     判断要不要合并，
     改个标题就变成"新内容"⇒ **再追加一块**，旧块留在汇总里 ⇒ 同一个台账号两份（E28 现场：
     `T-AG482` 两份，旧那份还带裸 `.md`，`check_layers` 判引用断裂红，而 `--check` 照样绿）。
     现在先按台账号定位**已有的那一块**（changelog = 标题提到它的 `## ` 节；traceability =
     `[entries."X"]`；交接 = 标题是 CHECKPOINT 且提到它的 `>` 块），找到就**原地换**，找不到才插。
  2. **`--check` 新增「孤儿/重复块」判据**：同一个台账号在汇总里出现多块 ⇒ 判红并点名通道与块数。
     **只对「HEAD 里没有的新增重复」判红** —— 本仓 HEAD 里已有 2 处历史重复（`changelog` 的
     `T-AG389`、交接的 `T-AG401`，都是 E38 之前提交的），它们报 `[WARN]` 并点名；而这份文件
     不在本卡白名单里，工人无权清。**新增一块就红**（不是把判据降级成 info）。
  3. **根的取法改走 `tools/pipe_root.py`**（卡 A326）：`TOOL_ROOT` 只用来找工具自身资源，
     `ROOT = pipe_root.data_root()` 才是**读写选中的那棵树**。
     以前写死 `Path(__file__).parent.parent`
     ⇒ 在卡树里用 `../../tools/sync_docs.py` 跑，改的是**主树**的共享文档
     （E38 现场把主树弄脏过一次）。

★ 硬约束（卡 §禁区）：
  1. 汇总**只插入/原地替换**片段内容、**绝不改写别处的既有字节** —— 幂等：连跑两次，第二次零 diff；
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

# ★ 卡 E38（T-AG492）：工具根 vs 数据根（卡 A326 的 `tools/pipe_root.py`）。
#   写法与 `tools/wb_daily.py:54-55` 一致：能 import 就用 `data_root()`（`PIPE_DATA` > 当前目录
#   （像不像数据根）> 工具所在仓）；拷进别的树 / 没有 pipe_root 时**降级**回工具根（老行为）。
try:
    import pipe_root
except ImportError:  # pragma: no cover —— 独立拷贝的树里没有 pipe_root
    try:
        from tools import pipe_root  # type: ignore[no-redef]
    except ImportError:
        pipe_root = None  # type: ignore[assignment]

#: 工具根：**只**用来找本工具自身资源，不读账本。
TOOL_ROOT = Path(__file__).resolve().parent.parent

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


# ---------------------------------------------------------------- 「块」定位（卡 E38 · T-AG492）
# 病：以前判断「这个片段要不要合并」= 片段内容是不是汇总的子串 ⇒ 改个标题就变成"没合并过"
# ⇒ **再追加一块**，旧块留在汇总里。现在先按台账号找**已有的那一块**，找到就原地换。

#: 台账号（`T-G123` / `T-AG456`）—— 前后不许粘字母数字，免得 `T-G12` 命中 `T-G123`。
_ID_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z-])T-(?:A?G)\d+(?![0-9])")


def _mentions(text: str, uid: str) -> bool:
    """这段文字里有没有**恰好这个**台账号（整词，不是子串）。"""
    return any(m.group(0) == uid for m in _ID_TOKEN_RE.finditer(text))


def _line_starts(text: str) -> list[int]:
    """每行行首的字符偏移 + 一个末端哨兵（长度 = 行数 + 1）。"""
    starts: list[int] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)
    starts.append(pos)
    return starts


def _head_id(line: str) -> str:
    """标题行里**属于这一节/这一块**的台账号 = 那行**最后一个** `T-…` 编号。

    ★ 为什么是最后一个：本仓的写法是「…（台账号）」把本笔的号放在末尾；标题里**提到别的卡**
      （`## … 给 T-AG387 补证据指针（T-AG388）`）若按"出现即算"就会误判成 T-AG387 的块。
    """
    ids = _ID_TOKEN_RE.findall(line)
    return ids[-1] if ids else ""


def _changelog_spans(text: str, uid: str, _first: str = "") -> list[tuple[int, int]]:
    """changelog 里**属于 `uid`** 的 `## ` 节 —— `[(起, 止)]`，按出现次序。"""
    lines = text.splitlines(keepends=True)
    starts = _line_starts(text)
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    out: list[tuple[int, int]] = []
    for i in heads:
        if _head_id(lines[i]) != uid:
            continue
        nxt = next((j for j in heads if j > i), len(lines))
        out.append((starts[i], starts[nxt]))
    return out


def _traceability_spans(text: str, uid: str, _first: str = "") -> list[tuple[int, int]]:
    """traceability 里键为 `uid` 的那张表 —— `[entries."uid"]` 到下一个 `[entries.` 之前。"""
    heads = [m.start() for m in re.finditer(r"(?m)^\[entries\.", text)]
    out: list[tuple[int, int]] = []
    key_re = re.compile(r'^\[entries\."?' + re.escape(uid) + r'"?\]', re.MULTILINE)
    for m in key_re.finditer(text):
        nxt = next((s for s in heads if s > m.start()), len(text))
        out.append((m.start(), nxt))
    return out


def _handoff_blocks(text: str) -> list[tuple[int, int, str]]:
    """交接文档里的「块」—— 两种边界（都是文件自己的结构，不猜）：

    ① 一行只有 `>`（这就是它自己的分隔约定，`_ensure_sep` 写的就是它）；
    ② 一行是 CHECKPOINT 标题（`> **… CHECKPOINT …`）—— 文档开头的引言与第一段之间
       没有 `>` 分隔，只按 ① 切会把引言和第一段粘成一块，于是"这个台账号的块"永远找不到。
    """
    lines = text.splitlines(keepends=True)
    starts = _line_starts(text)
    bounds: list[tuple[int, int]] = []
    cur = 0
    for i, ln in enumerate(lines):
        is_sep = ln.strip() == ">"
        is_head = CHECKPOINT_ANCHOR_RE.match(ln) is not None
        if not (is_sep or is_head):
            continue
        if "".join(lines[cur:i]).strip():
            bounds.append((cur, i))
        cur = i + 1 if is_sep else i
    if "".join(lines[cur:]).strip():
        bounds.append((cur, len(lines)))
    return [(starts[s], starts[e], "".join(lines[s:e])) for s, e in bounds]


def _handoff_spans(text: str, uid: str, first_line: str = "") -> list[tuple[int, int]]:
    """交接文档里属于 `uid` 的块（两种口径，都不猜）：

    ① 首行是 CHECKPOINT 标题且**标题里提到这个台账号**（片段纪元之后的约定）；
    ② 首行与待合并片段的首行**逐字相同**（改标题之前的老块也能认出来，用于原地替换）。
    `first_line` 只在合并时给；`--check` 里给空串 ⇒ 只按 ①（不把"正文提到某编号"的旁块当自己）。
    """
    out: list[tuple[int, int]] = []
    for start, end, body in _handoff_blocks(text):
        first = body.strip().split("\n")[0].strip()
        ids = _ID_TOKEN_RE.findall(first)
        if ("CHECKPOINT" in first and ids and ids[0] == uid) or (
            first_line and first == first_line.strip()
        ):
            out.append((start, end))
    return out


def _locate_block(ch: Channel, text: str, uid: str, first_line: str = "") -> list[tuple[int, int]]:
    """在某个通道的汇总文字里找「属于 `uid` 的块」—— 找不到回 `[]`。"""
    if ch.name == "changelog":
        return _changelog_spans(text, uid, first_line)
    if ch.name == "traceability":
        return _traceability_spans(text, uid, first_line)
    return _handoff_spans(text, uid, first_line)


def _replace_spans(text: str, spans: list[tuple[int, int]], block: str, ch_name: str) -> str:
    """把第一块换成 `block`，**其余重复块删掉**（从后往前改，前面块的偏移不受影响）。

    ★ 为什么连重复块一起删：E38 的现场就是"旧块 + 新块"并存 ⇒ 只换第一块等于没治。
    """
    out = text
    for start, end in reversed(spans[1:]):
        out = out[:start] + out[end:]
    start, end = spans[0]
    sep = "\n\n" if (ch_name == "traceability" and end < len(text)) else "\n"
    return out[:start] + block + sep + out[end:]


def _first_line(block: str) -> str:
    """块的首行（去空白）—— 交接通道用它认"改标题之前的老块"。"""
    return block.strip().split("\n")[0].strip() if block.strip() else ""


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

    ★ 卡 E38（T-AG492）：**这个台账号已经有一节就原地换**（改标题不再追加第二份）。
    """
    text = target
    for name, raw in pending:  # `pending` 已按新→旧排好；同日保持传入次序
        block = _norm(raw)
        spans = _changelog_spans(text, Path(name).stem, _first_line(block))
        if spans:
            text = _replace_spans(text, spans, block, "changelog")
            continue
        text = _insert_changelog_block(text, block)
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


_TRACE_KEY_RE = re.compile(r'^\[entries\.("?)([^"\]]+)\1\]', re.M)


def _trace_key(text: str) -> str | None:
    """片段里的台账键（`[entries."T-G370"]` → `T-G370`）；不是台账片段 → None。"""
    m = _TRACE_KEY_RE.search(text)
    return m.group(2) if m else None


def _merge_traceability(target: str, pending: list[tuple[str, str]]) -> str:
    """新 `[entries.*]` 表接在**文件尾**；★ 已有同名条目就**原地替换**（卡 A268）。

    为什么替换：以前只会「末尾追加」，而同一张卡的片段会被重放（⓪ 回退后重跑、或
    上一趟已写进汇总又重来）⇒ 汇总里出现两个 `[entries."X"]` ⇒ TOML 直接报
    `Cannot declare ('entries', 'X') twice`，把整个落地拦住（252/260/262 都撞过）。

    ★ 卡 E38（T-AG492）：定位与替换统一走 `_traceability_spans`（键就是台账号，
      顺手把同键的重复表一起收掉 —— 重复表 TOML 直接解析失败，留着只有坏处）。
    """
    out = target.rstrip("\n")
    for name, t in pending:
        body = _norm(t).rstrip("\n")
        uid = _trace_key(body) or Path(name).stem
        spans = _traceability_spans(out, uid)
        if spans:
            out = _replace_spans(out, spans, body, "traceability").rstrip("\n")
            continue
        out = out + "\n\n" + body
    return out + "\n"


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
    """新 CHECKPOINT 插在第一个 CHECKPOINT 段之前；★ 卡 E38：这个台账号已有块就**原地换**。"""
    text = target
    for name, raw in pending:
        body = _norm(raw)  # 不含末尾那行 `>`（分隔行由文件自己留着）
        spans = _handoff_spans(text, Path(name).stem, _first_line(body))
        if spans:
            text = _replace_spans(text, spans, body, "handoff")
            continue
        offset = _handoff_anchor_offset(text)
        text = text[:offset] + _ensure_sep(raw) + "\n" + text[offset:]
    return text


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


def _head_target_text(ch: Channel, root: Path) -> str:
    """HEAD 里这份汇总文件的原文（判「新增的重复块」用）；取不到 / 不是 git 仓 ⇒ 空串。

    空串的含义是**「HEAD 里一块也没有」** ⇒ 任何重复块都算新增、判红（fail closed：
    拿不准时按"新问题"处理，不按"老账"放过）。
    """
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", "show", f"HEAD:{_rel(ch.target, root)}"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, **NO_WINDOW,
    )
    return done.stdout if done.returncode == 0 else ""


def _duplicate_block_problems(ch: Channel, target: str, root: Path) -> tuple[list[str], list[str]]:
    """同一个台账号在汇总里出现**多块** ⇒ 回 `(判红, 只报不红)`（卡 E38 新增判据）。

    ★ 治的是 E28 那条静默：`--check` 以前只查「片段在不在汇总里」，改标题后留下的
      **旧块照绿**（新块也在 ⇒ 子串判断照样通过）⇒ 同一个台账号两份，谁都不知道。
    口径（**不许降级成 info**）：
      · 块数 > HEAD 里的块数 ⇒ 新增的孤儿块，**判红**并点名通道 / 台账号 / 块数；
      · 块数 > 1 但 HEAD 里本来就是这么多 ⇒ 历史欠账，报 `[WARN]`（本仓现存 2 处：
        changelog 的 `T-AG389`、交接的 `T-AG401`，都在这张卡之前提交；清它们要动
        `docs/**` / `复盘/交接-重构进度.md`，不在本卡白名单）。
    """
    problems: list[str] = []
    warnings: list[str] = []
    head_text = _head_target_text(ch, root)
    for frag in _fragment_files(ch):
        uid = frag.stem
        got = _locate_block(ch, target, uid)
        if len(got) <= 1:
            continue
        had = len(_locate_block(ch, head_text, uid)) if head_text else 0
        where = f"{_rel(ch.target, root)} 里 `{uid}` 有 {len(got)} 块（应 1 块）"
        if len(got) > max(had, 1):
            problems.append(
                f"{where} —— 孤儿块（同一台账号被追加了第二份：改标题后旧块没换掉？"
                "把多余的块删掉，或把片段改回与汇总一致）")
        else:
            warnings.append(f"{where} —— HEAD 里就是这样（历史欠账，非本笔新增；清掉后本行消失）")
    return problems, warnings


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
            # ★ 卡 E38（T-AG492）：同一条台账号在汇总里出现多块 ——
            #   新增的判红，HEAD 里就有的报 WARN。
            dup_problems, dup_warns = _duplicate_block_problems(ch, target, root)
            problems.extend(dup_problems)
            warnings.extend(dup_warns)
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
            print("[FAIL] 片段 ↔ 汇总不一致：没汇总 / 手改了汇总没改片段 / 同一台账号多块 ——")
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


def _default_root() -> Path:
    """默认读写的那棵树（卡 E38）：`pipe_root.data_root()` —— `PIPE_DATA` > 当前目录 > 工具根。

    ★ 以前写死 `Path(__file__).parent.parent` ⇒ 在卡树里用 `../../tools/sync_docs.py` 跑，
      改的是**主树**（E38 现场把主树弄脏过一次）。没有 `pipe_root` 的独立拷贝树里降级回工具根。
    """
    return pipe_root.data_root() if pipe_root is not None else TOOL_ROOT


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把「每笔一个片段」汇进三个共享文档（卡 107 · T-G203）"
    )
    ap.add_argument("--check", action="store_true",
                    help="只核对「片段 == 汇总」；不一致退 1 并点名（接进门禁用）；"
                         "另查 changelog 次序与「同一台账号多块」，错了报 WARN 并点名")
    ap.add_argument("--root", default="", help="仓库根（默认 = pipe_root 选中的那棵树；测试可换）")
    args = ap.parse_args()
    root = (Path(args.root).expanduser().resolve() if args.root else _default_root())
    return run(root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
