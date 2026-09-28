r"""开工切片生成器（卡 078 · T-G173）—— 把「每张卡开场强制读的四份文档」压成一张 ≤6KB 切片。

为什么有它（实测代价，卡 §0）：四份强制读文档合计 693KB ≈ 222,000 tokens
（**交接文档 302KB 已超工具 256KB 上限，读它就是失败**），而卡本身只有 9–25KB ——
每张卡真正需要的只有「现状 + 最新 1 个 CHECKPOINT + 本卡引用的规矩 + 白名单/禁区 + 固化坑页」。

五节固定顺序（卡 §1.1）：
  一 现状（现算，不抄任何文档） 二 最新 1 个 CHECKPOINT 三 本卡引用到的规矩
  四 本卡的白名单 / 禁区 五 固定坑页（见 复盘/口径坑.md）
总长硬上限 6 KB；超了截断并在末行写「…(已截断)」。

用法：
    python -X utf8 tools/wb_brief.py --card 078                 # 工人版 → stdout + brief-078.md
    python -X utf8 tools/wb_brief.py --spec gates/diag/卡078-*.md --out gates/diag/brief-078.md
    python -X utf8 tools/wb_brief.py --master --out gates/diag/brief-主控.md   # 主控版

★ 实现要求（卡 §1.1）：纯标准库、`python -X utf8` 可跑；**不把 302KB 那份整体读进内存再切**
—— 按行流式读到 `CHECKPOINT` 标记处切段（只留命中的那几段）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAG = ROOT / "gates" / "diag"
HANDOFF = ROOT / "复盘" / "交接-重构进度.md"
RULES = ROOT / "复盘" / "外包-卡表与规矩.md"

BRIEF_MAX_BYTES = 6144      # 6 KB 硬上限（卡 §1.1）
CHECKPOINT_MAX_BYTES = 1850  # 第二节单段上限（卡 §1.1 的 2KB 内留出余量给固定节）
RULES_MAX_BYTES = 1750       # 第三节上限（保证前四节 + 坑页塞得进 6KB）

# 固定坑页（卡 §1.4；与 复盘/口径坑.md 同内容 —— 一页判据 + 出处）
PIT_PAGE = "\n".join([
    "1. ★ `last.json` 的「复用」在【顶层 `reused` 字典】，不在每道门里",
    "（每道门只有 exit_code/name/seconds/summary）—— 主控 2026-09-27 查错两次。",
    "2. ★ 完成判据只看**最后一条** agent 轮次（看整段尾部会被上一轮的「完成。」骗）。",
    "3. ★ PowerShell 的 `>` / `Out-File` 写 **UTF-16LE** → `git commit -F` 报 NUL；",
    "写 msg 必须用 python 写 UTF-8。",
    "4. ★ 中文路径一律 `git -c core.quotepath=false`；`gates/diag/` 的脚本用",
    "`python -P -X utf8`（铁律 24）。",
    "5. ★ 「现算」类产物（索引/总表/分布数字）必须在**追加台账条目之后**再算一次（§24.11）。",
    "6. ★ 台账只许在**末尾追加**自己的条目，既有条目一个字不动（铁律 35）。",
    "7. ★ 别 `job_kill` 一个「生了我还要用的外部应用」的作业（子进程会连坐）。",
    "8. ★ 「有没有复用/有没有静默吞活」这类结论，**写进凭证文档前先把字段结构打出来看**。",
])

HEAD_RE = re.compile(r"^(#{1,4})\s*(.*)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return (done.stdout or "").strip()


def _first_line(cmd: list[str]) -> str:
    done = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    for ln in (done.stdout or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def section_state() -> str:
    """一、现状 —— 全部现算，不抄任何文档。"""
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    porc = [ln for ln in _git("status", "--porcelain").splitlines() if ln.strip()]
    tracked = [ln for ln in porc if not ln.startswith("??")]
    untracked = [ln for ln in porc if ln.startswith("??")]
    dist = _first_line([sys.executable, "-X", "utf8", "tools/sync_counts.py", "--check"])
    return "\n".join([
        f"- HEAD {sha} · 分支 {branch}",
        f"- 台账分布：{dist or '(sync_counts --check 没有输出)'}",
        f"- 工作区：被跟踪文件改动 {len(tracked)} 个（应 0）+ 外来未跟踪 {len(untracked)} 个",
    ])


def _is_checkpoint_start(line: str) -> bool:
    """是否是**一段** CHECKPOINT 的开头。

    ★ 不能只看行里有没有 `CHECKPOINT`：正文里也会提到它（本卡自己的 CHECKPOINT 就写了
    「取最后一段 CHECKPOINT」），那会把一段切碎。小节开头长这样：
    `> **2026-09-28 · CHECKPOINT（…）—— …` —— blockquote/标题 + 日期开头。
    """
    if "CHECKPOINT" not in line:
        return False
    if re.match(r"^\s*#{1,4}\s", line):
        return True
    return bool(re.match(r"^\s*>\s*\**\s*\d{4}-\d{2}-\d{2}", line))


def _checkpoint_blocks() -> list[tuple[str, list[str]]]:
    """按行流式扫描交接文档，收集每个 CHECKPOINT 段（不整体读入内存）。"""
    blocks: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    date = ""
    collecting = False
    with HANDOFF.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if _is_checkpoint_start(line):
                if cur:
                    blocks.append((date, cur))
                cur = [line]
                m = DATE_RE.search(line)
                date = m.group(0) if m else ""
                collecting = True
                continue
            if collecting:
                if line.startswith(">") or not line.strip():
                    cur.append(line)
                else:
                    blocks.append((date, cur))
                    cur, collecting = [], False
    if cur:
        blocks.append((date, cur))
    return blocks


def section_checkpoint() -> str:
    """二、最新 1 个 CHECKPOINT —— 按日期取最新那一段（交接文档是新→旧排列）。

    ★ 与卡 §1.1「取最后一段全文」的偏差（如实记）：交接文档**最新一段在文件顶部**
    （2026-09-28 那段在第 5 行），字面的「最后一段」是**最旧**那段（2026-09-26）。
    本工具按**日期最大**取（= 卡 §0 明写的「只取最新那一段」），并列时取出现靠前的。
    """
    blocks = _checkpoint_blocks()
    if not blocks:
        return "(未找到 CHECKPOINT)"
    best_key: tuple[str, int] | None = None
    best_lines: list[str] = []
    for i, (date, lines) in enumerate(blocks):
        key = (date, -i)
        if best_key is None or key > best_key:
            best_key, best_lines = key, lines
    text = "\n".join(best_lines).strip()
    return _truncate(text, CHECKPOINT_MAX_BYTES) + "\n"


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for i, ln in enumerate(lines):
        m = HEAD_RE.match(ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def _extract_section(lines: list[str], heads: list[tuple[int, int, str]],
                     idx: int) -> str:
    start, level, _title = heads[idx]
    end = len(lines)
    for j in range(idx + 1, len(heads)):
        if heads[j][1] <= level:
            end = heads[j][0]
            break
    return "\n".join(lines[start:end]).strip()


def _rule_numbers(title: str) -> set[str]:
    """标题里「铁律 <一串编号>」抽出来的编号集合（如 `铁律 29 / 30 / 31` → {29,30,31}）。"""
    m = re.search(r"铁律\s*([\d\s/、和]+)", title)
    if not m:
        return set()
    return set(re.findall(r"\d+", m.group(1)))


def _tokens(spec_text: str) -> list[str]:
    """从卡规格里抓它引用到的编号（`铁律 N` / `§24.x`），保持出现顺序、去重。"""
    found: list[str] = []
    for m in re.finditer(r"铁律\s*\d+|§?24\.\d+", spec_text):
        tok = m.group(0)
        if tok not in found:
            found.append(tok)
    return found


def _cap_sections(texts: list[str], total: int) -> str:
    """给每个小节分一份额度（尽量每节都露头），最后再按总量兜底截断。"""
    if not texts:
        return ""
    share = max(240, total // len(texts))
    joined = "\n\n".join(_truncate(t, share) for t in texts)
    return _truncate(joined, total)


def _match_sections(heads: list[tuple[int, int, str]], tok: str) -> list[int]:
    """一个编号在规矩文档里可能命中多个标题（如 `铁律 35` 命中空的 §24.10 与正文两份）。"""
    hits: list[int] = []
    m = re.fullmatch(r"§?(24\.\d+)", tok)
    if m:
        want = re.compile(re.escape(m.group(1)) + r"(?!\d)")
        return [idx for idx, (_i, _lvl, title) in enumerate(heads) if want.search(title)]
    n = re.search(r"\d+", tok)
    if n:
        return [idx for idx, (_i, _lvl, title) in enumerate(heads)
                if "铁律" in title and n.group(0) in _rule_numbers(title)]
    return hits


def section_rules(spec_text: str | None) -> str:
    """三、本卡引用到的规矩 —— 只挑卡里出现的编号对应的小节。"""
    if not spec_text:
        return "（主控版：不含单卡引用；固定坑页见第五节）\n"
    tokens = _tokens(spec_text)
    if not tokens:
        return "（卡里没有引用任何编号 → 只看第五节的固定坑页）\n"
    lines = RULES.read_text(encoding="utf-8", errors="replace").splitlines()
    heads = _headings(lines)
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        for idx in _match_sections(heads, tok):
            text = _extract_section(lines, heads, idx).strip()
            body = "\n".join(
                ln for ln in text.splitlines()[1:]
                if ln.strip() and ln.strip() != "---"
            )
            if len(body) < 40:
                continue  # 空壳标题（正文在下面的独立小节里）→ 继续找下一个命中
            key = text.splitlines()[0]
            if key not in seen:
                seen.add(key)
                out.append(text)
                break
    if not out:
        return "（卡里引用的编号在规矩文档里没找到对应小节）\n"
    return _cap_sections(out, RULES_MAX_BYTES) + "\n"


def section_whitelist(spec_text: str | None) -> str:
    """四、本卡的白名单 / 禁区 —— 从卡里「白名单」小节原样摘出（含其后的禁区行）。

    ★ 卡 §1.1 的模板里也出现过一行「本卡的白名单 / 禁区」标题（那只是样张）——
    所以取**最后一个**含「白名单」的标题，且排除以「四、」开头的样张标题。
    """
    if not spec_text:
        return "（主控版：无单卡白名单）\n"
    lines = spec_text.splitlines()
    heads = _headings(lines)
    cands = [idx for idx, (_i, _lvl, title) in enumerate(heads)
             if "白名单" in title and not title.startswith("四、")]
    if not cands:
        return "（卡里没找到「白名单」小节 —— 停工报主控）\n"
    return _extract_section(lines, heads, cands[-1]) + "\n"


def _truncate(text: str, limit: int) -> str:
    """按字节截断（UTF-8 安全），去掉末尾半截，末尾补「…(已截断)」。"""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    cut = raw[:max(0, limit - 12)].decode("utf-8", errors="ignore").rstrip()
    return cut + "…(已截断)"


def find_spec(card: str) -> str:
    """按卡号找规格文件（默认住在 gates/diag/）。"""
    for pat in (f"卡{card}-*.md", f"卡{card}.md", f"*{card}*.md"):
        hits = sorted(DIAG.glob(pat))
        if hits:
            return str(hits[0].relative_to(ROOT)).replace("\\", "/")
    return ""


def build(*, card: str, spec: str, master: bool) -> str:
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    who = "主控" if master else (card or "?")
    spec_text = ""
    if spec:
        p = ROOT / spec
        if p.exists():
            spec_text = p.read_text(encoding="utf-8", errors="replace")
    parts = [
        f"# 开工切片 · {who}  · 生成于 {stamp} · HEAD {sha}",
        "",
        "## 一、现状（现算，不抄任何文档）",
        section_state(),
        "",
        "## 二、最新 1 个 CHECKPOINT",
        section_checkpoint(),
        "## 三、本卡引用到的规矩",
        section_rules(None if master else spec_text),
        "## 四、本卡的白名单 / 禁区",
        section_whitelist(None if master else spec_text),
        "## 五、固定坑页",
        PIT_PAGE,
        "",
    ]
    text = "\n".join(parts)
    raw = text.encode("utf-8")
    if len(raw) > BRIEF_MAX_BYTES:
        text = _truncate(text, BRIEF_MAX_BYTES) + "\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 ≤6KB 开工切片（卡 078 · T-G173）")
    ap.add_argument("--card", default="", help="卡号（如 078）")
    ap.add_argument("--spec", default="", help="卡规格文件（相对仓库根）")
    ap.add_argument("--out", default="", help="写到哪里（默认 gates/diag/brief-<卡号>.md）")
    ap.add_argument("--master", action="store_true", help="主控版（无单卡白名单/引用）")
    args = ap.parse_args()

    card = args.card
    spec = args.spec
    if not args.master and not card and spec:
        m = re.search(r"卡(\d+)", Path(spec).name)
        card = m.group(1) if m else ""
    if not args.master and not spec and card:
        spec = find_spec(card)
    if not args.master and not card:
        print("[FAIL] 得给 --card 或 --spec（或 --master）", file=sys.stderr)
        return 2

    text = build(card=card, spec=spec, master=args.master)
    out = args.out or str(DIAG / (f"brief-{card}.md" if not args.master else "brief-主控.md"))
    out_path = ROOT / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    print(f"\n[brief] {out}（{len(text.encode('utf-8'))} 字节，"
          f"上限 {BRIEF_MAX_BYTES}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
