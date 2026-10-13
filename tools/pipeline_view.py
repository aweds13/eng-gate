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

★ **只读**：不写任何文件、不杀进程、不占端口、不调 git 的写命令。
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
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

BACKLOG_REL = Path("docs") / "workbacklog.toml"
GATES_LAST_REL = Path("gates") / "last.json"
DIAG_REL = Path("gates") / "diag"
REGISTRY_REL = DIAG_REL / "pool-registry.json"
BATCH_REL = DIAG_REL / "batch"

_VERDICT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.verdict\.txt$")
_REPORT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.report\.md$")


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
    """队列全貌（来源 ``docs/workbacklog.toml``）。"""
    path = root / BACKLOG_REL
    if not path.exists():
        return {"cards": None, "cards_note": f"没有 {BACKLOG_REL.as_posix()}"}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {"cards": None, "cards_note": f"{BACKLOG_REL.as_posix()} 坏了：{exc}"}
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
    return {"cards": cards, "cards_reviewed": reviewed}


# ================================================================ 2. gates


def read_gates(root: Path) -> dict:
    """最近一次门禁（来源 ``gates/last.json``）。"""
    path = root / GATES_LAST_REL
    if not path.exists():
        return {"gates": None, "gates_note": f"没有 {GATES_LAST_REL.as_posix()}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"gates": None, "gates_note": f"{GATES_LAST_REL.as_posix()} 坏了：{exc}"}
    raw_gates = data.get("gates") or []
    items: list[dict] = []
    for g in raw_gates:
        if not isinstance(g, dict):
            continue
        items.append({
            "name": str(g.get("name", "")),
            "exit_code": g.get("exit_code"),
            "seconds": g.get("seconds"),
        })
    return {
        "gates": {
            "ok": data.get("ok"),
            "rev": data.get("rev"),
            "items": items,
        }
    }


# ================================================================ 3. verdicts


def read_verdicts(root: Path) -> dict:
    """每张卡有没有判决 / 判决首行 / 有没有 report。"""
    diag = root / DIAG_REL
    if not diag.is_dir():
        return {"verdicts": [], "verdicts_note": f"没有 {DIAG_REL.as_posix()} 目录"}
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
    return {"verdicts": verdicts}


def _empty_verdict(cid: str) -> dict:
    return {
        "card": cid,
        "has_verdict": False,
        "verdict_first_line": "",
        "has_report": False,
    }


# ================================================================ 4. leases


def read_leases(root: Path) -> dict:
    """活租约（来源 ``gates/diag/pool-registry.json``）；不存在 ⇒ 空表。"""
    path = root / REGISTRY_REL
    if not path.exists():
        return {"leases": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"leases": None, "leases_note": f"{REGISTRY_REL.as_posix()} 坏了：{exc}"}
    if not isinstance(data, list):
        return {"leases": None,
                "leases_note": f"{REGISTRY_REL.as_posix()} 结构不对（顶层应是数组）"}
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
    return {"leases": leases}


# ================================================================ 5. fences


def read_fences(root: Path) -> dict:
    """任务栅栏（来源 ``gates/diag/batch/*.toml``）；坏文件 ⇒ 点名不崩。"""
    batch = root / BATCH_REL
    if not batch.is_dir():
        return {"fences": [], "fences_note": f"没有 {BATCH_REL.as_posix()} 目录"}
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
    result: dict = {"fences": fences}
    if broken:
        result["fences_broken"] = broken
    return result


# ================================================================ 6. worktrees


def read_worktrees(root: Path) -> dict:
    """卡树清单（来源 ``git worktree list``）；路径 + 分支/HEAD + 是否脏。"""
    out = _git("worktree", "list", "--porcelain", cwd=root)
    if not out:
        return {"worktrees": None, "worktrees_note": "git worktree list 没有输出"}
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
    return {"worktrees": worktrees}


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


def build_reading(root: Path | None = None) -> dict:
    """一份读数：六块。"""
    root = Path(root) if root is not None else ROOT
    result: dict = {}
    result.update(read_cards(root))
    result.update(read_gates(root))
    result.update(read_verdicts(root))
    result.update(read_leases(root))
    result.update(read_fences(root))
    result.update(read_worktrees(root))
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
    if cards is None:
        lines.append(f"[cards] {r.get('cards_note', '没有')}")
        return
    lines.append(f"[cards] 队列共 {len(cards)} 张（来源 docs/workbacklog.toml，"
                 f"基点 {r.get('cards_reviewed', '?')}）：")
    for c in cards:
        lines.append(f"  · {c['id']}（{c['task']}）{c['title'][:40]}"
                     f"  tree={c['tree'] or '(主树)'}  status={c['status']}  risk={c['risk']}")


def _report_gates(lines: list[str], r: dict) -> None:
    gates = r.get("gates")
    if gates is None:
        lines.append(f"[gates] {r.get('gates_note', '没有')}")
        return
    items = gates.get("items") or []
    lines.append(f"[gates] 最近一次门禁（来源 gates/last.json）："
                 f"rev={gates.get('rev')} ok={gates.get('ok')}  共 {len(items)} 道：")
    for g in items:
        lines.append(f"  · {g['name']}: exit={g['exit_code']}  {g['seconds']}s")


def _report_verdicts(lines: list[str], r: dict) -> None:
    note = r.get("verdicts_note")
    if note:
        lines.append(f"[verdicts] {note}")
        return
    verdicts = r.get("verdicts") or []
    lines.append(f"[verdicts] 判决（来源 gates/diag/wb-*.verdict.txt / .report.md）："
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
    if leases is None:
        lines.append(f"[leases] {r.get('leases_note', '没有')}")
        return
    lines.append(f"[leases] 租约（来源 gates/diag/pool-registry.json）：共 {len(leases)} 条：")
    for lc in leases:
        lines.append(f"  · card={lc['card']}  tree={lc['tree']}  owner={lc['owner']}"
                     f"  at={lc['at']}  ttl={lc['ttl_seconds']}s")


def _report_fences(lines: list[str], r: dict) -> None:
    note = r.get("fences_note")
    if note:
        lines.append(f"[fences] {note}")
    else:
        fences = r.get("fences") or []
        lines.append(f"[fences] 任务栅栏（来源 gates/diag/batch/*.toml）：共 {len(fences)} 个：")
        for f in fences:
            lines.append(f"  · {f['id']}: on_complete={f['on_complete']}  members={f['members']}")
    for b in r.get("fences_broken") or []:
        lines.append(f"  ★ 坏文件：{b['file']}  错误：{b['error']}")


def _report_worktrees(lines: list[str], r: dict) -> None:
    worktrees = r.get("worktrees")
    if worktrees is None:
        lines.append(f"[worktrees] {r.get('worktrees_note', '没有')}")
        return
    lines.append(f"[worktrees] 卡树清单（来源 git worktree list）：共 {len(worktrees)} 棵：")
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
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else ROOT
    reading = build_reading(root)
    if args.json:
        print(json.dumps(reading, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_report(reading))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
