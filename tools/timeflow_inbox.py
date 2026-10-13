r"""timeflow 收件箱（卡 222 · T-G336）—— 只读：把「该我做的事」汇成一份视图。

为什么有它（方案 W4）：让待办**在用户已经在的地方**看得见（DSH 的终端 / timeflow 的使用场景），
而不是要人再开一个工具、再去数文件。

## 形态，以及为什么是这个形态

★ 侦察过 `src/timeflow/**`（结论见卡 222 的回报）后再定的：它是**零依赖、本地优先**的个人
时间/学习工具（模型 = 任务 / 子任务 / 复习卡 / 专注 / 备忘 / 产出流水 / …），它**不读本仓的
协作状态**，而且用户早先拍过两条口径：**精力 / 情绪不建模**、**OKR 不进系统**。

本卡要看的「待收口的批 / 待复核的卡 / 待翻 status 的卡」全是**本仓工程侧**的读数 —— 把它们
塞进 timeflow 的模型，等于让一个 pip 包去读仓库状态（跨层），还得**新造实体**。所以形态选：
**仓库侧一个只读脚本**（本文件），在 DSH 里 / 终端里直接跑 —— **`src/timeflow/**` 一个字不改**。

## 数据源：一份读数，不重造

★ 读数**只有一份**：`tools/pipeline_view.py`（卡 207）的 `build_reading()`（六块：cards / gates /
verdicts / leases / fences / worktrees）。本工具**只**把它翻成三桶，不另读队列、不另读判决。

唯一的**补读**：批的**状态**（`gates/diag/batch/<批>.json` 的 `state` / `claims`）—— 因为
pipeline_view 的 `fences` 块**只数成员、不带状态**，而「收没收口」正是状态说了算。读的是
pipeline_view 已经点名的**同一个目录**（路径口径直接用它的 `BATCH_REL`，不另立一份）。

三桶（都只读）：

1. **待收口的批** —— 还没 `landed` 的栅栏（`ready/gating/awaiting-commit` = 齐了该收口；
   `collecting` = 还缺卡；`timeout` = 判死要人管）；
2. **待复核的卡** —— 有判决产物（`verdicts` 块）**且**队列 `status` 还没翻成 `done` 的卡；
3. **待翻 status 的卡** —— 队列里 `status` 还是 `pending` 的卡。

★ **只读**：不写任何文件、不派活、不改别人的实体、不 import `src/timeflow/**`。
★ **缺什么说什么**：来源文件缺失 / 坏掉 ⇒ 那一桶**明确标注**（如 `batches.note`），
  **不许**用空对象冒充、**不许**猜。
★ **默认根 = 主工作树根**（卡 203 的口径：不许拿 `--show-toplevel` 当主树），
  所以「从哪棵树跑」都不改变读数 —— `--root` 可覆盖（测试用）。
★ **幂等**：同样的输入连跑两次，`--json` 逐字节相同（不写时间戳、不写随机序）。

用法：
    python -X utf8 tools/timeflow_inbox.py --report
    python -X utf8 tools/timeflow_inbox.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:  # 直跑脚本时 tools/ 已在 sys.path；被 import 时补上
    sys.path.insert(0, str(_TOOLS))

import pipeline_view  # noqa: E402,I001 —— 同一份读数（卡 207），不重造

#: 队列里算「已经翻篇」的状态；别的都要人看一眼。
DONE_STATUS = "done"

#: 队列里「还没派 / 还在飞」的状态 —— 桶 C 收的就是这一档。
PENDING_STATUS = "pending"

#: 批状态里「已经齐了、在等人收口」的那几个（`pool/pool/task.py` 的状态机）。
AWAITING_STATES = ("ready", "gating", "awaiting-commit")


def _default_root() -> Path:
    """默认读数根 = **主工作树根**（卡 203：不用 `--show-toplevel`，它在卡树里回卡树）。

    复用 `tools/pool/registry.py::main_tree_root`（那份口径已经在跑），算不出（没 git 等）⇒
    退回本文件所在树 —— 如实降级、不崩。
    """
    try:
        from pool import registry as pool_registry
    except ImportError:  # pragma: no cover —— 被拆散 / 装包了才走这条
        return ROOT
    try:
        return pool_registry.main_tree_root()
    except (pool_registry.RegistryError, OSError):  # pragma: no cover —— 环境异常才走
        return ROOT


# ================================================================ 桶 A：待收口的批


def _batch_state(root: Path, batch_id: str) -> dict | None:
    """批状态（`gates/diag/batch/<批>.json`）—— pipeline_view 的 `fences` 不带这一列。

    ★ 只读；读不到（文件缺 / JSON 坏 / 顶层不是对象）⇒ `None`（**不猜**）。
    """
    path = root / pipeline_view.BATCH_REL / f"{batch_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _missing_members(state: dict) -> list[str]:
    """还缺哪些卡 —— 照 `tools/pool/task.py` 的口径：成功申请 ∪ 豁免 ∪ 只读，都不算缺。"""
    declared = [str(m) for m in (state.get("declared") or [])]
    read_only = {str(m) for m in (state.get("read_only") or [])}
    waived = {str(m) for m in (state.get("waived") or [])}
    ok = {str(m) for m, kind in (state.get("claims") or {}).items() if kind == "success"}
    return [m for m in declared if m not in read_only and m not in ok and m not in waived]


def _action(batch_id: str, case: str) -> str:
    """这一批现在要做的动作（人读一句话；不代跑、只打印）。"""
    if case in AWAITING_STATES:
        return f"跑 `python -X utf8 tools/wb_land.py --batch {batch_id}`"
    if case == "timeout":
        return f"`python -X utf8 tools/wb_task.py waive|extend {batch_id} …`（判死要人显式处理）"
    if case == "collecting":
        return "等卡交成送申请（齐了才自动放行）"
    return "看 `python -X utf8 tools/wb_task.py status " + batch_id + "`"


def read_batches(root: Path, reading: dict) -> dict:
    """桶 A：待收口的批 —— 来源 pipeline_view 的 `fences` 块 + 批状态文件。"""
    note = str(reading.get("fences_note") or "")
    fences = reading.get("fences")
    if fences is None:
        return {"open": [], "landed": 0, "note": note or "fences 块没读出来"}
    opened: list[dict] = []
    without_state: list[str] = []
    landed = 0
    for fence in sorted(fences, key=lambda f: str(f.get("id", ""))):
        batch_id = str(fence.get("id", ""))
        state = _batch_state(root, batch_id)
        if state is None:
            without_state.append(batch_id)
            continue
        case = str(state.get("state") or "")
        if case == "landed":
            landed += 1
            continue
        read_only = {str(m) for m in (state.get("read_only") or [])}
        ok = {str(m) for m, kind in (state.get("claims") or {}).items() if kind == "success"}
        opened.append({
            "id": batch_id,
            "state": case,
            "awaiting": case in AWAITING_STATES,
            "need": state.get("need"),
            "done": len(ok - read_only),
            "missing": _missing_members(state),
            "action": _action(batch_id, case),
            "why": str(state.get("why") or ""),
            "members": fence.get("members"),
        })
    result: dict = {"open": opened, "landed": landed}
    if without_state:
        result["without_state"] = without_state
    if note:
        result["note"] = note
    return result


# ================================================================ 桶 B：待复核的卡


def read_review(reading: dict) -> dict:
    """桶 B：待复核的卡 —— 有判决、队列 `status` 还没翻成 `done`。

    来源 `verdicts` 块（判决产物在不在）+ `cards` 块（队列 status）—— 两块都出自 pipeline_view。
    """
    note = str(reading.get("verdicts_note") or "")
    verdicts = reading.get("verdicts")
    cards = reading.get("cards")
    if verdicts is None:
        return {"cards": [], "note": note or "verdicts 块没读出来"}
    if cards is None:
        return {"cards": [], "note": "没有队列（cards 块：`docs/workbacklog.toml` 缺）"
                                     " ⇒ 判不出哪张的 status 还没翻完（不猜）"}
    status = {str(c.get("id", "")): str(c.get("status", "")) for c in cards}
    rows: list[dict] = []
    orphans = 0
    for verdict in sorted(verdicts, key=lambda v: str(v.get("card", ""))):
        card = str(verdict.get("card", ""))
        if not verdict.get("has_verdict"):
            continue
        if card not in status:  # 判决在，队列里没有这张卡（元卡 / 审计卡 / 已消失）—— 不编
            orphans += 1
            continue
        if status[card] == DONE_STATUS:
            continue
        rows.append({
            "card": card,
            "status": status[card],
            "has_report": bool(verdict.get("has_report")),
            "verdict_first_line": str(verdict.get("verdict_first_line") or ""),
        })
    result: dict = {"cards": rows, "orphans": orphans}
    if note:
        result["note"] = note
    return result


# ================================================================ 桶 C：待翻 status 的卡


def read_status_flip(reading: dict) -> dict:
    """桶 C：待翻 status 的卡 —— 队列里 `status` 还是 `pending` 的卡（来源 `cards` 块）。

    ★ 本桶**只**按队列 status 列；它是否**已落地**在这里**判不出**（那要 `git log` 的
      `Task:` trailer，属 `tools/wb_plan.py check` 那个另一个面）—— 不在这里重造一份。
    """
    cards = reading.get("cards")
    if cards is None:
        return {"cards": [], "note": str(reading.get("cards_note") or "没有队列（cards 块）")}
    rows = [
        {
            "card": str(c.get("id", "")),
            "task": str(c.get("task", "")),
            "title": str(c.get("title", "")),
            "tree": str(c.get("tree", "")),
            "risk": str(c.get("risk", "")),
        }
        for c in cards
        if str(c.get("status", "")) == PENDING_STATUS
    ]
    rows.sort(key=lambda r: r["card"])
    return {
        "cards": rows,
        "note": "只按队列 status 列；『是否已落地』不在这里判"
                "（跑 `python -X utf8 tools/wb_plan.py check` 看『已落却仍 pending』）",
    }


# ================================================================ 汇总 / 渲染


def build_inbox(root: Path | None = None) -> dict:
    """收件箱：一份读数（pipeline_view 六块）+ 三桶（批 / 复核 / 翻 status）。"""
    resolved = Path(root) if root is not None else _default_root()
    reading = pipeline_view.build_reading(resolved)
    return {
        "root": resolved.as_posix(),
        "reading": "tools/pipeline_view.py（卡 207）的一份读数：六块",
        "batches": read_batches(resolved, reading),
        "review": read_review(reading),
        "status_flip": read_status_flip(reading),
    }


def _render_batches(lines: list[str], block: dict) -> None:
    open_batches = block.get("open") or []
    if not open_batches and block.get("note"):
        lines.append(f"[待收口的批] {block['note']}")
        return
    lines.append(
        f"[待收口的批] 还没收口 {len(open_batches)} 个"
        f"（已 landed {block.get('landed', 0)} 个）；"
        f"来源 pipeline_view.fences + 批状态 gates/diag/batch/<批>.json：")
    for row in open_batches:
        if row["awaiting"]:
            mark = "★齐了·该收口"
        elif row["state"] == "timeout":
            mark = "★判死"
        else:
            mark = "还缺"
        left = "、".join(row["missing"]) or "（齐了）"
        lines.append(
            f"  · {row['id']}  [{mark}] state={row['state']}  "
            f"{row['done']}/{row['need']}  还缺：{left}  动作：{row['action']}")
    if block.get("without_state"):
        lines.append(f"  · 没有批状态文件（不猜）：{'、'.join(block['without_state'])}")
    if block.get("note"):
        lines.append(f"  · {block['note']}")


def _render_review(lines: list[str], block: dict) -> None:
    rows = block.get("cards") or []
    if not rows and block.get("note"):
        lines.append(f"[待复核的卡] {block['note']}")
        return
    lines.append(
        f"[待复核的卡] {len(rows)} 张（有判决、队列 status 还没翻成 done）；"
        f"来源 pipeline_view.verdicts + cards：")
    for row in rows:
        tag = "有摘要" if row["has_report"] else "缺摘要"
        first = row["verdict_first_line"][:56]
        lines.append(f"  · 卡{row['card']}  status={row['status']}  {tag}  首行：{first}")
    if block.get("orphans"):
        lines.append(
            f"  · 另有 {block['orphans']} 张卡有判决但队列里没有条目"
            f"（元卡 / 审计卡 ⇒ 判不出，不展开）")
    if block.get("note"):
        lines.append(f"  · {block['note']}")


def _render_status_flip(lines: list[str], block: dict) -> None:
    rows = block.get("cards") or []
    if not rows and block.get("note"):
        lines.append(f"[待翻 status 的卡] {block['note']}")
        return
    lines.append(
        f"[待翻 status 的卡] {len(rows)} 张队列 status 还是 pending；"
        f"来源 pipeline_view.cards：")
    for row in rows:
        lines.append(
            f"  · 卡{row['card']}（{row['task']}）tree={row['tree'] or '(主树)'}"
            f"  risk={row['risk']}  {row['title'][:40]}")
    if block.get("note"):
        lines.append(f"  · {block['note']}")


def render(inbox: dict) -> str:
    """人读报告：三桶 + 各自的来源与缺口。"""
    lines = [f"[收件箱] 根 {inbox['root']} · 读数来源：{inbox['reading']}"]
    _render_batches(lines, inbox["batches"])
    _render_review(lines, inbox["review"])
    _render_status_flip(lines, inbox["status_flip"])
    return "\n".join(lines)


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="timeflow 收件箱（只读）：该我做的事 —— "
                    "待收口的批 / 待复核的卡 / 待翻 status 的卡")
    parser.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    parser.add_argument("--report", action="store_true", help="输出人读报告（默认）")
    parser.add_argument("--root", default="", help="仓库根（默认 = 主工作树根）")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else _default_root()
    inbox = build_inbox(root)
    if args.json:
        print(json.dumps(inbox, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render(inbox))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
