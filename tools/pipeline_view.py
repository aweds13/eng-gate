r"""一份读数（卡 207 · T-G316）—— 只读，唯一读数器。

为什么有它：主控 2026-10-13 定的方案里，**同一批读数会有多个「面」**（会话内的 MCP、
timeflow 视图、禅道）。按本仓教义（「四个面集中到一个点」），必须先有**一个只读读数器**，
否则同一件事各读各的、口径必漂。现在这些读数散在各处（`landing.py` 读队列与台账、
`wb_state.py` 读 HEAD/锁/进程、`wb_dash.py` 读 `wb-*.jsonl`、`wb_flow.py` 读队列算流量、
`pool_mcp.py` 读队列+判决+租约）—— **没有任何一处把它们收成一份**。本工具就是那一份。

一条命令产出一份结构化读数（`--json` 给机器、`--report` 给人读）。**六块**，每块都写清来源：

1. `cards`     —— 队列全貌（来源 `docs/workbacklog.toml`）
2. `gates`     —— 最近一次门禁（来源 `gates/last.json`）
3. `verdicts`  —— 每张卡的判决 / 摘要（来源 `gates/diag/wb-<卡>.verdict.txt` 与 `.report.md`）
4. `leases`    —— 活租约（来源 `gates/diag/pool-registry.json`）
5. `fences`    —— 任务栅栏（来源 `gates/diag/batch/*.toml`）
6. `worktrees` —— 卡树清单（来源 `git worktree list`）

★ **只读**：不杀进程、不占端口、不调 git 的写命令；唯一写的文件是连续块的
  last-good 快照（`gates/diag/pipeline-view-lastgood.json`，gitignore 的 diag 区，卡 249）。
★ **BLOCKS 声明表是唯一口径源**（卡 249 · T-G370）：六块的块名 / 来源 / 缺源标注语 /
  字段清单都在模块级 `BLOCKS` 里，`read_*()` 与 `_report_*()` 都从它取（不许各写一份）；
  `--json` 每块带 `<块>_source` 回声、`--report` 每块头带同一句来源 —— 两个出口对得上。
★ **连续块 vs 静态块**：`BLOCKS` 里 `continuous=True` 的只有 `gates` / `leases` ——
  读数失败时若有上一份好读数（STALE-WHILE-ERROR，快照见 `LASTGOOD_REL`），返回
  上一份好值 + `<块>_stale`（`error_code` + `captured_at`）；墙钟算出的 `stale_for_s`
  只进 `--report`、不进 `--json`（保幂等）。静态块保留「缺什么说什么」：
  null + 声明表标注语，不许一刀切改成 last-good。
★ **缺什么说什么**：来源文件缺失/坏掉 ⇒ 那一块**明确标注**（如 `"gates": null` +
  `"gates_note": "没有 gates/last.json"`），**不许**用空对象冒充、**不许**猜。
★ **不 import 业务代码**（`src/timeflow/**`）；只用标准库 + 读文件 + 调 `git`（带 `NO_WINDOW`）。
★ 幂等：同样的输入连跑两次，`--json` 逐字节相同（**不许**写时间戳/随机序）。

用法：
    python -X utf8 tools/pipeline_view.py --report
    python -X utf8 tools/pipeline_view.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

BACKLOG_REL = Path("docs") / "workbacklog.toml"
GATES_LAST_REL = Path("gates") / "last.json"
DIAG_REL = Path("gates") / "diag"
REGISTRY_REL = DIAG_REL / "pool-registry.json"
BATCH_REL = DIAG_REL / "batch"
# 连续块（gates/leases）的 last-good 快照（卡 249）：失败时「坏读数不许抹掉好读数」。
LASTGOOD_REL = DIAG_REL / "pipeline-view-lastgood.json"

_VERDICT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.verdict\.txt$")
_REPORT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.report\.md$")


# ================================================================ BLOCKS：六块声明表
# ★ 唯一口径源（卡 249 · T-G370）：read_*() 与 _report_*() 都从这张表取
#   （块名、来源、缺源标注语、字段清单）—— 不许再各写一份。
#   --json 的 <块>_source 回声与 --report 每块头的「来源 …」都出自这里。
# ★ continuous=True = 连续监测块：读数失败且有上一份好读数时走 STALE-WHILE-ERROR
#   （快照 LASTGOOD_REL）；False = 静态块（一次性读数）：保留「缺什么说什么」
#   （null + missing_note），不许一刀切改成 last-good。
BLOCKS: tuple[dict, ...] = (
    {"id": "cards", "source": "docs/workbacklog.toml",
     "missing_note": "没有 docs/workbacklog.toml", "continuous": False,
     "fields": ("cards", "cards_reviewed"),
     "row_fields": ("id", "task", "title", "tree", "spec", "files",
                    "depends", "risk", "status")},
    {"id": "gates", "source": "gates/last.json",
     "missing_note": "没有 gates/last.json", "continuous": True,
     "fields": ("gates",),
     "row_fields": ("ok", "rev", "items")},
    {"id": "verdicts", "source": "gates/diag/wb-*.verdict.txt / .report.md",
     "missing_note": "没有 gates/diag 目录", "continuous": False,
     "fields": ("verdicts",),
     "row_fields": ("card", "has_verdict", "verdict_first_line", "has_report")},
    {"id": "leases", "source": "gates/diag/pool-registry.json",
     "missing_note": "没有 gates/diag/pool-registry.json", "continuous": True,
     "fields": ("leases",),
     "row_fields": ("card", "tree", "files", "owner", "at", "ttl_seconds")},
    {"id": "fences", "source": "gates/diag/batch/*.toml",
     "missing_note": "没有 gates/diag/batch 目录", "continuous": False,
     "fields": ("fences",),
     "row_fields": ("id", "on_complete", "members")},
    {"id": "worktrees", "source": "git worktree list",
     "missing_note": "git worktree list 没有输出", "continuous": False,
     "fields": ("worktrees",),
     "row_fields": ("path", "head", "branch", "dirty")},
)

_SRC: dict[str, dict] = {b["id"]: b for b in BLOCKS}


# ================================================================ last-good 快照（卡 249）


#: ★ 卡 249：last-good 快照只在**监测路径**（CLI `main()`）里写；
#: 库调用方（`build_inbox()` 那种只读路径）默认不写 ⇒ 只读硬判据仍然成立 ✓。
_REMEMBER = False


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_lastgood(root: Path) -> dict:
    """读 last-good 快照；没有/坏了 ⇒ 空表（STALE-WHILE-ERROR 退化为「缺什么说什么」）。"""
    try:
        data = json.loads((root / LASTGOOD_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    blocks = data.get("blocks") if isinstance(data, dict) else None
    return blocks if isinstance(blocks, dict) else {}


def _save_lastgood_block(root: Path, bid: str, data: object) -> None:
    """把某连续块的好读数落进快照；写不进去就算了（不许因快照失败而红）。"""
    blocks = dict(_load_lastgood(root))
    blocks[bid] = {"captured_at": _now_iso(), "data": data}
    snap = {"schema": 1, "blocks": blocks}
    try:
        path = root / LASTGOOD_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        pass


def _stale_hit(root: Path, bid: str, error_code: str) -> dict | None:
    """取某连续块的上一份好读数；有 ⇒ {data, stale}，没有 ⇒ None。"""
    hit = _load_lastgood(root).get(bid)
    if not isinstance(hit, dict) or "data" not in hit:
        return None
    return {"data": hit["data"],
            "stale": {"error_code": error_code,
                      "captured_at": str(hit.get("captured_at", ""))}}


def _continuous_out(root: Path, bid: str, payload: object,
                    note: str, error_code: str) -> dict:
    """连续块的统一出口：好读数落快照；坏读数有上一份好值 ⇒ last-good + error_code。"""
    src = _SRC[bid]["source"]
    if payload is not None:
        if _REMEMBER:
            _save_lastgood_block(root, bid, payload)
        return {bid: payload, f"{bid}_source": src}
    hit = _stale_hit(root, bid, error_code)
    if hit is not None:
        return {bid: hit["data"], f"{bid}_stale": hit["stale"], f"{bid}_source": src}
    return {bid: None, f"{bid}_note": note, f"{bid}_source": src}


# ================================================================ 子进程（只读 git）


def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", **NO_WINDOW,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _git(*args: str, cwd: Path | None = None) -> str:
    rc, out = _run_git(*args, cwd=cwd)
    return out.strip() if rc == 0 else ""


# ================================================================ 1. cards


def read_cards(root: Path) -> dict:
    """队列全貌（口径见 ``BLOCKS["cards"]``）。静态块：缺什么说什么。"""
    spec = _SRC["cards"]
    path = root / BACKLOG_REL
    if not path.exists():
        return {"cards": None, "cards_note": spec["missing_note"],
                "cards_source": spec["source"]}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {"cards": None, "cards_note": f"{spec['source']} 坏了：{exc}",
                "cards_source": spec["source"]}
    base = data.get("base")
    reviewed = ""
    if isinstance(base, dict):
        reviewed = str(base.get("reviewed", "")).strip()
    raw_cards = data.get("cards") or []
    cards: list[dict] = []
    for raw in raw_cards:
        if not isinstance(raw, dict):
            continue
        cards.append({
            "id": str(raw.get("id", "")).strip(),
            "task": str(raw.get("task", "")).strip(),
            "title": str(raw.get("title", "")).strip(),
            "tree": str(raw.get("tree", "")).strip(),
            "spec": str(raw.get("spec", "")).strip(),
            "files": list(raw.get("files") or []),
            "depends": list(raw.get("depends") or []),
            "risk": str(raw.get("risk", "mid")).strip(),
            "status": str(raw.get("status", "pending")).strip(),
        })
    return {"cards": cards, "cards_reviewed": reviewed, "cards_source": spec["source"]}


# ================================================================ 2. gates


def read_gates(root: Path) -> dict:
    """最近一次门禁（口径见 ``BLOCKS["gates"]``）。连续块：失败走 STALE-WHILE-ERROR。"""
    spec = _SRC["gates"]
    path = root / GATES_LAST_REL
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _continuous_out(root, "gates", None,
                                   f"{spec['source']} 坏了：{exc}", "source_broken")
        if not isinstance(data, dict):
            return _continuous_out(root, "gates", None,
                                   f"{spec['source']} 结构不对（顶层应是对象）",
                                   "source_broken")
        items: list[dict] = []
        for g in data.get("gates") or []:
            if not isinstance(g, dict):
                continue
            items.append({
                "name": str(g.get("name", "")),
                "exit_code": g.get("exit_code"),
                "seconds": g.get("seconds"),
            })
        payload = {"ok": data.get("ok"), "rev": data.get("rev"), "items": items}
        return _continuous_out(root, "gates", payload, "", "")
    return _continuous_out(root, "gates", None, spec["missing_note"], "source_missing")


# ================================================================ 3. verdicts


def read_verdicts(root: Path) -> dict:
    """每张卡有没有判决 / 判决首行 / 有没有 report（口径见 ``BLOCKS["verdicts"]``）。"""
    spec = _SRC["verdicts"]
    diag = root / DIAG_REL
    if not diag.is_dir():
        return {"verdicts": [], "verdicts_note": spec["missing_note"],
                "verdicts_source": spec["source"]}
    found: dict[str, dict] = {}
    for entry in sorted(diag.iterdir()):
        if not entry.is_file():
            continue
        m = _VERDICT_RE.match(entry.name)
        if m:
            cid = m.group(1)
            row = found.setdefault(cid, _empty_verdict(cid))
            row["has_verdict"] = True
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            row["verdict_first_line"] = text.splitlines()[0] if text.splitlines() else ""
            continue
        m = _REPORT_RE.match(entry.name)
        if m:
            cid = m.group(1)
            row = found.setdefault(cid, _empty_verdict(cid))
            row["has_report"] = True
    verdicts = [found[k] for k in sorted(found)]
    return {"verdicts": verdicts, "verdicts_source": spec["source"]}


def _empty_verdict(cid: str) -> dict:
    return {
        "card": cid,
        "has_verdict": False,
        "verdict_first_line": "",
        "has_report": False,
    }


# ================================================================ 4. leases


def read_leases(root: Path) -> dict:
    """活租约（口径见 ``BLOCKS["leases"]``）。连续块：失败走 STALE-WHILE-ERROR。"""
    spec = _SRC["leases"]
    path = root / REGISTRY_REL
    if not path.exists():
        # 文件不在 = 还没人租 ⇒ 空表是合法读数（既有口径不动），不是失败。
        return {"leases": [], "leases_source": spec["source"]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _continuous_out(root, "leases", None,
                               f"{spec['source']} 坏了：{exc}", "source_broken")
    if not isinstance(data, list):
        return _continuous_out(root, "leases", None,
                               f"{spec['source']} 结构不对（顶层应是数组）",
                               "source_broken")
    leases: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        leases.append({
            "card": str(row.get("card", "")),
            "tree": str(row.get("tree", "")),
            "files": list(row.get("files") or []),
            "owner": str(row.get("owner", "")),
            "at": str(row.get("at", "")),
            "ttl_seconds": row.get("ttl_seconds"),
        })
    return _continuous_out(root, "leases", leases, "", "")


# ================================================================ 5. fences


def read_fences(root: Path) -> dict:
    """任务栅栏（口径见 ``BLOCKS["fences"]``）；坏文件 ⇒ 点名不崩。静态块。"""
    spec = _SRC["fences"]
    batch = root / BATCH_REL
    if not batch.is_dir():
        return {"fences": [], "fences_note": spec["missing_note"],
                "fences_source": spec["source"]}
    fences: list[dict] = []
    broken: list[dict] = []
    for entry in sorted(batch.iterdir()):
        if not entry.is_file() or entry.suffix != ".toml":
            continue
        try:
            man = tomllib.loads(entry.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            broken.append({"file": entry.name, "error": str(exc)})
            continue
        members = man.get("member") or []
        fences.append({
            "id": str(man.get("id", "")),
            "on_complete": list(man.get("on_complete") or []),
            "members": len(members) if isinstance(members, list) else 0,
        })
    result: dict = {"fences": fences, "fences_source": spec["source"]}
    if broken:
        result["fences_broken"] = broken
    return result


# ================================================================ 6. worktrees


def read_worktrees(root: Path) -> dict:
    """卡树清单（口径见 ``BLOCKS["worktrees"]``）；路径 + 分支/HEAD + 是否脏。静态块。"""
    spec = _SRC["worktrees"]
    out = _git("worktree", "list", "--porcelain", cwd=root)
    if not out:
        return {"worktrees": None, "worktrees_note": spec["missing_note"],
                "worktrees_source": spec["source"]}
    worktrees: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                worktrees.append(_finalize_worktree(current))
                current = {}
            continue
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line.startswith("detached"):
            current["branch"] = "(detached HEAD)"
    if current:
        worktrees.append(_finalize_worktree(current))
    return {"worktrees": worktrees, "worktrees_source": spec["source"]}


def _finalize_worktree(wt: dict) -> dict:
    path = wt.get("path", "")
    dirty = False
    if path:
        rc, out = _run_git("status", "--porcelain", cwd=Path(path))
        if rc == 0 and out.strip():
            dirty = True
    return {
        "path": path,
        "head": wt.get("head", ""),
        "branch": wt.get("branch", ""),
        "dirty": dirty,
    }


# ================================================================ 汇总


_READERS: dict[str, object] = {
    "cards": read_cards, "gates": read_gates, "verdicts": read_verdicts,
    "leases": read_leases, "fences": read_fences, "worktrees": read_worktrees,
}


def build_reading(root: Path | None = None, *, remember: bool = False) -> dict:
    """六块收成一份。`remember=True` 才把连续块的好读数落 last-good（默认不写 ⇒ 只读 ✓）。"""
    global _REMEMBER
    if remember:
        _REMEMBER = True
    """一份读数：六块（块的顺序与口径都来自 BLOCKS 声明表，不许另立一份）。"""
    root = Path(root) if root is not None else ROOT
    result: dict = {}
    for spec in BLOCKS:
        result.update(_READERS[spec["id"]](root))
    return result


# ================================================================ 人读报告


def _report(reading: dict) -> str:
    lines: list[str] = []
    _report_cards(lines, reading)
    _report_gates(lines, reading)
    _report_verdicts(lines, reading)
    _report_leases(lines, reading)
    _report_fences(lines, reading)
    _report_worktrees(lines, reading)
    return "\n".join(lines)


def _report_cards(lines: list[str], r: dict) -> None:
    cards = r.get("cards")
    src = _SRC["cards"]["source"]
    if cards is None:
        lines.append(f"[cards] {r.get('cards_note', '没有')}（来源 {src}）")
        return
    lines.append(f"[cards] 队列共 {len(cards)} 张（来源 {src}，"
                 f"基点 {r.get('cards_reviewed', '?')}）：")
    for c in cards:
        lines.append(f"  · {c['id']}（{c['task']}）{c['title'][:40]}"
                     f"  tree={c['tree'] or '(主树)'}  status={c['status']}  risk={c['risk']}")


def _report_gates(lines: list[str], r: dict) -> None:
    gates = r.get("gates")
    src = _SRC["gates"]["source"]
    if gates is None:
        lines.append(f"[gates] {r.get('gates_note', '没有')}（来源 {src}）")
        return
    items = gates.get("items") or []
    lines.append(f"[gates] 最近一次门禁（来源 {src}）："
                 f"rev={gates.get('rev')} ok={gates.get('ok')}  共 {len(items)} 道：")
    for g in items:
        lines.append(f"  · {g['name']}: exit={g['exit_code']}  {g['seconds']}s")
    _report_stale(lines, r, "gates")


def _report_stale(lines: list[str], r: dict, bid: str) -> None:
    """连续块的坏读数标注（STALE-WHILE-ERROR）：墙钟只进 --report，不进 --json。"""
    st = r.get(f"{bid}_stale")
    if not st:
        return
    lines.append(f"  ★ 读数失败（error_code={st.get('error_code')}）："
                 f"以上是上一份好读数（captured_at={st.get('captured_at')}，"
                 f"stale_for_s={_stale_for_s(st)}s）")


def _stale_for_s(st: dict) -> str:
    """上一份好读数距今多少秒；解析不了就如实给「?」。"""
    try:
        t = datetime.fromisoformat(str(st.get("captured_at", "")))
        gap = (datetime.now().astimezone() - t).total_seconds()
        return str(max(0, int(gap)))
    except ValueError:
        return "?"


def _report_verdicts(lines: list[str], r: dict) -> None:
    note = r.get("verdicts_note")
    src = _SRC["verdicts"]["source"]
    if note:
        lines.append(f"[verdicts] {note}（来源 {src}）")
        return
    verdicts = r.get("verdicts") or []
    lines.append(f"[verdicts] 判决（来源 {src}）："
                 f"共 {len(verdicts)} 张卡有产物：")
    for v in verdicts:
        tags = []
        if v["has_verdict"]:
            tags.append("有判决")
        if v["has_report"]:
            tags.append("有摘要")
        first = v["verdict_first_line"][:60] if v["verdict_first_line"] else ""
        suffix = f"  首行：{first}" if first else ""
        lines.append(f"  · {v['card']}: {'、'.join(tags) or '无'}" + suffix)


def _report_leases(lines: list[str], r: dict) -> None:
    leases = r.get("leases")
    src = _SRC["leases"]["source"]
    if leases is None:
        lines.append(f"[leases] {r.get('leases_note', '没有')}（来源 {src}）")
        return
    lines.append(f"[leases] 租约（来源 {src}）：共 {len(leases)} 条：")
    for lc in leases:
        lines.append(f"  · card={lc['card']}  tree={lc['tree']}  owner={lc['owner']}"
                     f"  at={lc['at']}  ttl={lc['ttl_seconds']}s")
    _report_stale(lines, r, "leases")


def _report_fences(lines: list[str], r: dict) -> None:
    note = r.get("fences_note")
    src = _SRC["fences"]["source"]
    if note:
        lines.append(f"[fences] {note}（来源 {src}）")
    else:
        fences = r.get("fences") or []
        lines.append(f"[fences] 任务栅栏（来源 {src}）："
                     f"共 {len(fences)} 个：")
        for f in fences:
            lines.append(f"  · {f['id']}: on_complete={f['on_complete']}"
                         f"  members={f['members']}")
    for b in r.get("fences_broken") or []:
        lines.append(f"  ★ 坏文件：{b['file']}  错误：{b['error']}")


def _report_worktrees(lines: list[str], r: dict) -> None:
    worktrees = r.get("worktrees")
    src = _SRC["worktrees"]["source"]
    if worktrees is None:
        lines.append(f"[worktrees] {r.get('worktrees_note', '没有')}（来源 {src}）")
        return
    lines.append(f"[worktrees] 卡树清单（来源 {src}）："
                 f"共 {len(worktrees)} 棵：")
    for w in worktrees:
        lines.append(f"  · {w['path']}  branch={w['branch']}  head={w['head']}"
                     f"  dirty={'是' if w['dirty'] else '否'}")


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一份读数：六块收成一份（只读，缺什么说什么、幂等）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    parser.add_argument("--report", action="store_true", help="输出人读报告")
    parser.add_argument("--root", default="", help="仓库根（默认本文件推出来）")
    global _REMEMBER
    args = parser.parse_args(argv)
    _REMEMBER = True  # ★ CLI = 监测路径：好读数落 last-good（库调用方不写 ✓）
    root = Path(args.root) if args.root else ROOT
    reading = build_reading(root)
    if args.json:
        print(json.dumps(reading, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_report(reading))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
