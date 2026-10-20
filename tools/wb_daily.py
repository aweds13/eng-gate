r"""今日一页（卡 220 · T-G334）—— **只读**，一条命令回答「现在该做什么」。

为什么有它：主控 2026-10-13 一天里**七次**靠人肉挂 `sleep` 看守等工人（还漏过一次）；
而用户定的节奏是「**攒批提交，一日一次**」—— 两件都**依赖人记得**。本仓的教义：
**没装牙的规矩 = 话**。本工具把「今天该做什么」变成一条**只读命令**，一屏说完：

    · 待派几张（来源 `docs/workbacklog.toml` 的 `status = "pending"`）
    · 在飞几张（租约，来源 `gates/diag/pool-registry.json`）
    · 哪些批到了 `awaiting-commit`（来源 `gates/diag/batch/<批>.json` 的 `state`）
    · 哪些卡已落却没翻 status（已落批的成员 vs 队列里的 `status`）
    · 内存够不够跑门禁（读**门禁自己那一套**，来源 `scripts/run_gates.py`）

★ **不另造读数**：上面六块里的四块一律调 `tools/pipeline_view.py --json`（卡 207 的**那份真源**）
  —— 本工具**只**做「取那六块 + 补两处它没有的（批状态 / 内存）」。
  批状态是补的：`pipeline_view` 的 `fences` 只给「**有哪些批**」（`id`/`on_complete`/`members`），
  不给 `state`；状态住同目录的 `<批>.json` ⇒ 本工具拿 `fences` 的批号去读那一处。
★ **只读**：不写任何文件、不杀进程、不占端口、不调 git 的写命令、不起 DSH 插件。
★ **缺什么说什么**：读不到就**如实报**（如 `pipeline_view` 挂了 ⇒ 点它的出口码与首行 stderr），
  **不许**用空对象冒充、**不许**猜。
★ 池状态（租约 / 批状态）住**主工作树**的 `gates/diag/`（`pool.task.main_tree_root()` 那条约定，
  `wb_plan.py` / `wb_task.py` 都照它）；所以默认去**主树**读，`--root` 可覆盖。

用法：
    python -X utf8 tools/wb_daily.py             # 今天的一页（人读）
    python -X utf8 tools/wb_daily.py --json      # 今天的一页（机器读）
    python -X utf8 tools/wb_daily.py --root <树>  # 换个真源
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:  # 直接跑 `tools\wb_daily.py`：`tools/` 在 sys.path[0]（正常入口）
    import _repo
except ImportError:  # `python -m tools.wb_daily`：包形态，同目录模块得带上前缀 —— 别崩
    from tools import _repo

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_VIEW = ROOT / "tools" / "pipeline_view.py"
DIAG_REL = Path("gates") / "diag"
BATCH_REL = DIAG_REL / "batch"
REGISTRY_REL = DIAG_REL / "pool-registry.json"
#: 卡池住哪：总表 + 分片目录（「有没有卡池」按这两处任意一处有就算有，口径同 `wb_plan`）。
POOL_REL = Path("docs") / "workbacklog.toml"
SHARDS_REL = Path("docs") / "backlog"
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

#: 终态的 status：这两种之外的卡才算「还没翻」。
DONE_STATUS = ("done", "failed")


# ================================================================ 真源定位


def main_tree_root() -> Path:
    """主工作树根（池状态住那儿）—— 唯一实现对 `pool.task.main_tree_root()`。

    ★ 算不出（跑不了 git / 不在仓里）⇒ 退回 `_repo.repo_root()`（本文件所在的树），
      并在读数里如实记一句。
    """
    try:
        from pool import task as _task  # noqa: PLC0415 —— 唯一实现，别另写一份
    except ImportError:
        return _repo.repo_root()
    try:
        return _task.main_tree_root()
    except Exception:  # noqa: BLE001 —— 定位失败只该退树，不该让「一页」打不出来
        return _repo.repo_root()


def resolve_root(explicit: str | None = None) -> Path:
    """一页的**真源根**：显式 `--root`（走 `_repo.repo_root()` 归一成绝对路径）> 主工作树。

    ★ 为什么默认**不是** `_repo.repo_root()`：池状态（租约 / 栅栏 / 批）住在**主工作树**，
      而卡树里 `git rev-parse --show-toplevel` 回的是卡树自己（见 `tools/_repo.py` 头的分工）
      ⇒ 无参数时仍走 `main_tree_root()`，**行为一字不变**；`--root` 才由调用者说了算。
    """
    if explicit is not None and str(explicit).strip():
        return _repo.repo_root(explicit)
    return main_tree_root()


def pool_state(root: Path) -> tuple[bool, str]:
    """这棵树**有没有卡池** —— 总表（`docs/workbacklog.toml`）或分片（`docs/backlog/*.toml`）。

    返回 `(有卡池?, 一句人话)`。空目录 `git init` 之后跑本工具 ⇒ `(False, "还没有卡池 …")`：
    那不是错，是「这棵树还没登记任何卡」—— 得明说，不能让人看一页空表猜。
    """
    if (root / POOL_REL).is_file():
        return True, ""
    if any((root / SHARDS_REL).glob("*.toml")):
        return True, ""
    return False, (f"还没有卡池（没有 {POOL_REL.as_posix()} / {SHARDS_REL.as_posix()}/*.toml）")


# ================================================================ 六块读数（调 pipeline_view）


def read_pipeline(root: Path) -> tuple[dict | None, str]:
    """一份读数（六块）—— 一律调 `tools/pipeline_view.py --json`。

    返回 `(读数, 空串)` 或 `(None, 一句人话)`；**不**吞掉失败原因。
    """
    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(PIPELINE_VIEW), "--json", "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", **NO_WINDOW,
        )
    except OSError as exc:
        return None, f"起不来 pipeline_view：{exc}"
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        return None, f"pipeline_view 退 {done.returncode}：{lines[0] if lines else '（没输出）'}"
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        return None, f"pipeline_view 的 --json 不是 JSON：{exc}"
    if not isinstance(data, dict):
        return None, "pipeline_view 的 --json 顶层不是对象"
    return data, ""


# ================================================================ 批状态（补的那一处）


def read_batch_states(root: Path, ids: list[str]) -> tuple[dict[str, dict], list[str]]:
    """批状态：`gates/diag/batch/<批>.json` 的 `state` / `declared` / 成功申请。

    ★ 批号取自 `pipeline_view` 的 `fences`（**不**自己去扫目录 —— 那份清单只有一个来源）。
    ★ 读不到 / 坏掉的批**点名**（返回 notes），**不**静默跳过。
    """
    states: dict[str, dict] = {}
    notes: list[str] = []
    batch = root / BATCH_REL
    for tid in ids:
        path = batch / f"{tid}.json"
        if not path.exists():
            notes.append(f"{tid}：没有 {BATCH_REL.as_posix()}/{tid}.json")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(f"{tid}：{tid}.json 坏了（{exc}）")
            continue
        if not isinstance(data, dict):
            notes.append(f"{tid}：{tid}.json 顶层不是对象")
            continue
        claims = data.get("claims") if isinstance(data.get("claims"), dict) else {}
        declared = [str(x) for x in (data.get("declared") or [])]
        states[tid] = {
            "state": str(data.get("state", "")),
            "declared": declared,
            "ok": sorted([str(k) for k, v in claims.items() if v == "success"]),
        }
    return states, notes


# ================================================================ 内存（补的那一处）


def memory_reading() -> dict:
    """内存够不够跑门禁 —— 读**门禁自己那一套**（`scripts/run_gates.py`），别写第二份。

    ★ 模块头写明「不许依赖 `psutil`」；这里也只 import 它自己的读数函数（不自己写 ctypes）。
    ★ 读不到 ⇒ `gb = None` + 一句 note（**不**当「够」）。
    """
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import run_gates  # noqa: PLC0415 —— 唯一实现（门禁的内存闸）
    except Exception as exc:  # noqa: BLE001
        return {"gb": None, "threshold": None, "note": f"读不到 run_gates 的内存读数：{exc}"}
    try:
        gb = run_gates.available_memory_gb()
        threshold = run_gates.gate_min_free_gb()
    except Exception as exc:  # noqa: BLE001
        return {"gb": None, "threshold": None, "note": f"run_gates 读内存抛错：{exc}"}
    return {"gb": gb, "threshold": threshold, "note": ""}


def _memory_verdict(mem: dict) -> str:
    """"够 / 不够 / 读不到" —— 拿不准则说读不到，**不**猜。"""
    gb, threshold = mem.get("gb"), mem.get("threshold")
    if gb is None or threshold is None:
        return f"读不到（{mem.get('note') or '没有读数'}）"
    if float(threshold) <= 0:
        return f"可用 {gb:.1f} GB，闸已关（阈值 {threshold:g}）⇒ 放行"
    if float(gb) < float(threshold):
        return (f"可用 {gb:.1f} GB < 闸 {threshold:g} GB ⇒ **不够**跑门禁"
                "（可 `TF_PYTEST_WORKERS=1`）")
    return f"可用 {gb:.1f} GB ≥ 闸 {threshold:g} GB ⇒ 够跑门禁"


# ================================================================ 今天的一页


def build_page(root: Path) -> dict:
    """把一页读成结构化数据（**缺什么留 note**，绝不编）。"""
    reading, note = read_pipeline(root)
    has_pool, pool_note = pool_state(root)
    page: dict = {
        "today": datetime.date.today().isoformat(),
        "root": str(root),
        "has_pool": has_pool,
        "pool_note": pool_note,
        "pipeline": reading,
        "pipeline_note": note,
        "batch_notes": [],
        "memory": memory_reading(),
        "to_dispatch": None,
        "to_dispatch_note": "",
        "leases": None,
        "leases_note": "",
        "waiting": [],
        "collecting": [],
        "stale": [],
        "stale_unknown": [],
        "gates": None,
        "todo": [],
    }
    if reading is None:
        page["to_dispatch_note"] = note
        page["leases_note"] = note
        page["batch_notes"] = [note]
        return page

    _fill_cards(page, reading)
    _fill_leases(page, reading, root)
    _fill_batches(page, reading, root)
    gates = reading.get("gates")
    if isinstance(gates, dict):
        page["gates"] = {
            "ok": gates.get("ok"),
            "rev": gates.get("rev"),
            "count": len(gates.get("items") or []),
        }
    page["todo"] = _todo(page)
    return page


def _fill_cards(page: dict, reading: dict) -> None:
    """待派 = `status = "pending"`；读不到 ⇒ 留 pipeline/pipeline_view 的原话。"""
    cards = reading.get("cards")
    if cards is None:
        page["to_dispatch"] = None
        page["to_dispatch_note"] = str(reading.get("cards_note", "读不到队列"))
        return
    page["to_dispatch"] = [c["id"] for c in cards if c.get("status") == "pending"]
    page["cards_reviewed"] = reading.get("cards_reviewed", "")


def _fill_leases(page: dict, reading: dict, root: Path) -> None:
    """在飞 = 租约；`[]` 与「文件不在」要说清（别让空表冒充「没有在飞」）。"""
    leases = reading.get("leases")
    if leases is None:
        page["leases"] = None
        page["leases_note"] = str(reading.get("leases_note", "读不到租约"))
        return
    page["leases"] = [
        {"card": str(lc.get("card", "")), "tree": str(lc.get("tree", "")),
         "owner": str(lc.get("owner", "")), "at": str(lc.get("at", "")),
         "ttl_seconds": lc.get("ttl_seconds")}
        for lc in leases
    ]
    if not page["leases"] and not (root / REGISTRY_REL).exists():
        page["leases_note"] = f"没有 {REGISTRY_REL.as_posix()}（按 0 条算）"


def _fill_batches(page: dict, reading: dict, root: Path) -> None:
    """批状态 + 「已落却没翻 status」。"""
    fences = reading.get("fences")
    if fences is None or reading.get("fences_note"):
        page["batch_notes"] = [str(reading.get("fences_note", "读不到批清单"))]
        return
    ids = [str(f.get("id", "")) for f in fences if f.get("id")]
    states, notes = read_batch_states(root, ids)
    page["batch_notes"] = notes
    cards = reading.get("cards") or []
    status = {c["id"]: c.get("status") for c in cards}
    landed: list[str] = []
    for tid in sorted(states):
        row = states[tid]
        item = {"id": tid, "state": row["state"], "ok": row["ok"],
                "declared": row["declared"]}
        if row["state"] == "awaiting-commit":
            page["waiting"].append(item)
        elif row["state"] == "collecting":
            page["collecting"].append(item)
        elif row["state"] == "landed":
            landed.extend(row["ok"])
    for cid in sorted(set(landed)):
        if cid not in status:
            page["stale_unknown"].append(cid)
        elif status[cid] not in DONE_STATUS:
            page["stale"].append({"card": cid, "status": status[cid]})


def _todo(page: dict) -> list[str]:
    """「今天该做」—— 只据读到的数说话，没有就不说。"""
    out: list[str] = []
    waiting = page.get("waiting") or []
    if waiting:
        first = waiting[0]
        out.append(f"{len(waiting)} 个批等到提交（先收 {first['id']}：补『为什么』→ 提交）")
    stale = page.get("stale") or []
    if stale:
        ids = "/".join(s["card"] for s in stale)
        out.append(f"{len(stale)} 张已落却没翻 status（{ids}）⇒ 把 status 翻成 done")
    todo_le = page.get("to_dispatch") or []
    if todo_le and not waiting and not stale:
        out.append(f"没有批等着收口 ⇒ 队列里 {len(todo_le)} 张可接着派")
    leases = page.get("leases")
    if leases is not None and not leases and todo_le:
        out.append("当前没有租约在飞 ⇒ 无人占树，可直接派活")
    return out


# ================================================================ 人读的一页


def render(page: dict) -> str:
    lines = [f"=== 今日一页 · 卡 220 定时巡检 · {page['today']} ===",
             f"真源：{page['root']}"]
    if not page.get("has_pool", True):
        lines.append(f"[卡池] ★ {page.get('pool_note') or '还没有卡池'}")
    if page.get("pipeline_note"):
        lines.append(f"[读数] ★ 读不到：{page['pipeline_note']}（其余各块按「没有」处理）")
    _render_cards(lines, page)
    _render_leases(lines, page)
    _render_batches(lines, page)
    _render_memory(lines, page)
    _render_gates(lines, page)
    todo = page.get("todo") or []
    if todo:
        lines.append("⇒ 今天该做：")
        lines.extend(f"  · {t}" for t in todo)
    else:
        lines.append("⇒ 今天该做：（读数里没读出要办的事）")
    return "\n".join(lines)


def _render_cards(lines: list[str], page: dict) -> None:
    todo = page.get("to_dispatch")
    if todo is None:
        lines.append(f"[待派] ★ 读不到：{page.get('to_dispatch_note') or '没有读数'}")
        return
    if not todo:
        lines.append("[待派] 0 张")
        return
    base = page.get("cards_reviewed") or "?"
    ids = " ".join(todo)
    lines.append(f"[待派] {len(todo)} 张（来源 docs/workbacklog.toml，基点 {base}）：{ids}")


def _render_leases(lines: list[str], page: dict) -> None:
    leases = page.get("leases")
    if leases is None:
        lines.append(f"[在飞] ★ 读不到：{page.get('leases_note') or '没有读数'}")
        return
    tail = f"（{page['leases_note']}）" if page.get("leases_note") else ""
    lines.append(f"[在飞] {len(leases)} 条租约{tail}（来源 gates/diag/pool-registry.json）：")
    for lc in leases:
        lines.append(f"  · 卡 {lc['card'] or '?'} → {lc['tree'] or '(不明)'}"
                     f"  owner={lc['owner']}  at={lc['at']}  ttl={lc['ttl_seconds']}s")


def _render_batches(lines: list[str], page: dict) -> None:
    for n in page.get("batch_notes") or []:
        lines.append(f"[批] ★ {n}")
    waiting = page.get("waiting") or []
    if waiting:
        lines.append(f"[批·等到提交] {len(waiting)} 个"
                     "（来源 gates/diag/batch/<批>.json 的 state=awaiting-commit）：")
        for b in waiting:
            lines.append(f"  · {b['id']}（{len(b['ok'])}/{len(b['declared'])} 齐）"
                         f" ← 该补『为什么』并提交")
    else:
        lines.append("[批·等到提交] 0 个")
    collecting = page.get("collecting") or []
    if collecting:
        lines.append(f"[批·还在收集] {len(collecting)} 个（state=collecting）：")
        for b in collecting:
            ids = " ".join(b["declared"]) or "?"
            lines.append(f"  · {b['id']}（{len(b['ok'])}/{len(b['declared'])}：{ids}）")
    _render_stale(lines, page)


CARD_ID_RE = re.compile(r"^(?:[A-Z]+\d+|\d+)$")


def _card_key(cid: str) -> str:
    """卡号归一：批次围栏里写 `M-1`、队列里写 `M1`，是同一个人。"""
    return str(cid).replace("-", "").strip()


def _render_stale(lines: list[str], page: dict) -> None:
    stale = page.get("stale") or []
    unknown = page.get("stale_unknown") or []
    if not stale and not unknown:
        lines.append("[已落没翻 status] 0 张")
        return
    if stale:
        body = " ".join(f"{s['card']}({s['status']})" for s in stale)
        lines.append(f"[已落没翻 status] {len(stale)} 张：{body}")
    if unknown:
        reshaped = [u for u in unknown if CARD_ID_RE.match(str(u).strip())]
        members = [u for u in unknown if not CARD_ID_RE.match(str(u).strip())]
        if reshaped:
            lines.append(f"  ★ 另有 {len(reshaped)} 个已落批成员不在队列里：{' '.join(reshaped)}")
        if members:
            body = " ".join(members)
            lines.append(f"  · 历史批成员 {len(members)} 个（无卡号，不进队列）：{body}")


def _render_memory(lines: list[str], page: dict) -> None:
    lines.append(f"[内存] {_memory_verdict(page.get('memory') or {})}"
                 "（来源 scripts/run_gates.py 的内存闸）")


def _render_gates(lines: list[str], page: dict) -> None:
    gates = page.get("gates")
    if gates is None:
        lines.append("[门禁] ★ 读不到最近一次门禁（没有 gates/last.json 或坏了）")
        return
    lines.append(f"[门禁] 最近一次 rev={gates['rev']} ok={gates['ok']}"
                 f"（{gates['count']} 道，来源 gates/last.json）")


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="今日一页：只读，回答「现在该做什么」（卡 220）")
    parser.add_argument("--root", default="",
                        help="真源树（默认 = 主工作树；池状态住那儿）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    args = parser.parse_args(argv)
    root = resolve_root(args.root)
    page = build_page(root)
    if args.json:
        print(json.dumps(page, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render(page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
