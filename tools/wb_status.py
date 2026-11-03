r"""WorkBuddy / CodeBuddy CLI 状态器：把 stream-json 事件读成人看的时间线。

为什么有这个工具（2026-09-26，T-G81）：外包模式下**工人 agent 在别的进程里干活**
（`D:\workbuddy\...\cli\bin\codebuddy`），主控与用户都看不见它做了什么 —— 只能事后读它
留下的 log。这个脚本就是那扇窗：把原始 JSONL 事件渲染成

    时间 | 它在说什么 / 它调了哪个工具、动了哪个文件 | 结果

**边界（如实写）**：
  · 它只**读** log，不跑 CLI、不改任何东西（派活是 `tools/workbuddy.ps1` 或主控的直接调用）；
  · 事件形状按 CodeBuddy/Claude-Code 那一族写（`system` / `assistant` / `user` / `result`），
    认得出来的都渲染；**认不出来的一行也不丢**（原样截断打印）—— 所以它不会因为对方升级而
    静默什么都不说；
  · ★ 第一次真派活之后，要用**真 log** 把形状钉成测试（现在只有合成用例，见
    `tests/test_wb_status.py`）。

用法：
    python -X utf8 tools/wb_status.py <log.jsonl> [--tail N] [--repo] [--json]
    # --tail N  只看最后 N 条事件（跑长任务时看进度用）
    # --repo    末尾附一段 `git status --short` + `git log -1`（"它对仓库做了什么"）
    # --json    机器可读的摘要（给主控解析用）

★ 逻辑层已抽到 `tools/pool/jobs.py`（卡 106 · T-G202）：`parse_events` / 渲染 / 三态判据
  与号池 MCP 的 `job_list` / `job_status` **共用同一批函数**。本文件只留**取参数 / 打印**。

====================================================================
模式②（卡 A318 · T-AG432）：**不给 log 参数 ⇒ 派生卡状态**。

    python -X utf8 tools/wb_status.py [--root <仓库根>] [--json]

模式③（卡 A366 · T-AG588）：**`--jobs` ⇒ 在飞作业读数**。

    python -X utf8 tools/wb_status.py --jobs [--root <仓库根>] [--json]

只转发 `pool.jobs.scan_jobs`（`在跑` / `断了` / `已判决` 三态与 `STALL_SECONDS=480`
全在那边算），本工具不重算阈值；面板 `/dsh-panel/pool-jobs` 吃这一条。

口径（单一事实：账本只存计划，状态从这里算）：
  · 有 `Task: <task>` trailer 的提交 ⇒ **done**（只认 trailer 整行，不认正文提及 ——
    卡 146 被正文误报那类假阳在 trailer 口径下天然不成立）；
  · 批次围栏 `gates/diag/batch/*.json`：`landed` ⇒ **done**；`awaiting-commit` ⇒
    **awaiting-commit**（围栏读不到目录就当没有 —— 卡树里没有 `gates/`，优雅降级）；
  · 其余 ⇒ **pending**。
`--json` 的 summary 同时给出 `done` 数与 `tasks_in_git`（git 里出现过的 Task 号数），
两者之差由 `orphan_tasks`（台账无条目、非簿记号的号）点名 —— 判据「done 数 == 提交里
出现过的 task 数」的核对材料就在这一份输出里（白名单理由归迁移文档，不进本工具）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tomllib
from pool.jobs import (
    UnknownLogEncodingError,
    diag_dir,
    parse_events,
    read_log_lines,
    render_json,
    render_timeline,
    scan_jobs,
)
from pool.jobs import clip as _clip
from pool.jobs import tool_line as _tool_line
from wb_queue_audit import queue_touch_marks, read_task_commits

#: 逻辑层在 `pool.jobs`；这里原样转发 `parse_events`（wb_dash 用）与 `_clip` / `_tool_line`
#: （wb_dispatch 用）。`read_log_lines` / `UnknownLogEncodingError` 也转发一份：卡 E75 起
#: 工人日志的读法只有 `pool.jobs` 那一份，`wb_diag` / `wb_dispatch` 经这里拿（少一层环球 import）。
__all__ = ["main", "parse_events", "_clip", "_tool_line", "read_log_lines",
           "UnknownLogEncodingError",
           "load_cards", "derive_status", "derived_summary", "orphan_tasks"]


# ---------------------------------------------------------------- 模式②：派生卡状态

def load_cards(root: Path) -> list[dict]:
    """读台账卡：有分片（`docs/backlog/*.toml`）就**只读分片**（与 `wb_task.py` 同口径）。

    ★ 只取计划字段（`id` / `task` / `spec` …），**不读 `status`** —— 状态由本文件派生，
      台账里那个字段是等着退役的副本（卡 A318）。
    """
    backlog = root / "docs" / "backlog"
    shards = sorted(backlog.glob("*.toml")) if backlog.is_dir() else []
    files = shards or [root / "docs" / "workbacklog.toml"]
    cards: list[dict] = []
    for f in files:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        cards.extend(data.get("cards") or [])
    return cards


def _batch_states(root: Path) -> dict[str, tuple[str, str]]:
    """卡号 ⇒ `(派生状态, 批号)`。只认 `landed` / `awaiting-commit` 两种围栏状态。

    读不到目录 / 坏 JSON 一律当没有（不抛，优雅降级 —— 卡树里没有 `gates/`）。
    一张卡被多批声明时 `landed` 优先（落了的说了算）。
    """
    out: dict[str, tuple[str, str]] = {}
    batch_dir = root / "gates" / "diag" / "batch"
    if not batch_dir.is_dir():
        return out
    mapped_states = {"landed": "done", "awaiting-commit": "awaiting-commit"}
    for f in sorted(batch_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mapped = mapped_states.get(str(data.get("state") or ""))
        if not mapped:
            continue
        batch_id = str(data.get("id") or f.stem)
        for card in data.get("declared") or []:
            cid = str(card)
            if mapped == "done" or cid not in out:
                out[cid] = (mapped, batch_id)
    return out


def derive_status(root: Path) -> tuple[list[dict], dict[str, object]]:
    """每张卡的派生状态 + git 侧的 Task 号表（`(rows, marks)`；只读，不写任何东西）。

    判据优先级：提交 trailer ⇒ done ＞ 围栏 landed ⇒ done ＞ 围栏 awaiting-commit
    ＞ pending。`marks` = `wb_queue_audit.read_task_commits` 的原样读数
    （`{Task号: (Commit, …)}`，trailer 解析只有那一份）。
    """
    cards = load_cards(root)
    marks = read_task_commits(root)
    batches = _batch_states(root)
    rows: list[dict] = []
    for c in cards:
        cid = str(c.get("id") or "")
        task = str(c.get("task") or "")
        commits = marks.get(task) if task else None
        if commits:
            rows.append({"id": cid, "task": task, "status": "done",
                         "via": f"commit {commits[0].short}"})
            continue
        hit = batches.get(cid)
        if hit and hit[0] == "done":
            rows.append({"id": cid, "task": task, "status": "done",
                         "via": f"batch {hit[1]}（landed）"})
        elif hit:
            rows.append({"id": cid, "task": task, "status": "awaiting-commit",
                         "via": f"batch {hit[1]}（awaiting-commit）"})
        else:
            rows.append({"id": cid, "task": task, "status": "pending",
                         "via": ""})
    return rows, marks


def orphan_tasks(root: Path, rows: list[dict], marks: dict[str, object]) -> list[str]:
    """git 里挂了 `Task:` 、台账却没有该任务的号（簿记号除外 —— 口径见 wb_queue_audit）。"""
    queued = {r["task"] for r in rows if r["task"]}
    protected = queue_touch_marks(root, marks)
    return sorted(m for m in marks if m not in queued and m not in protected)


def derived_summary(rows: list[dict], marks: dict[str, object],
                    orphans: list[str]) -> dict:
    return {
        "cards": len(rows),
        "done": sum(1 for r in rows if r["status"] == "done"),
        "awaiting-commit": sum(1 for r in rows if r["status"] == "awaiting-commit"),
        "pending": sum(1 for r in rows if r["status"] == "pending"),
        "tasks_in_git": len(marks),
        "orphan_tasks": len(orphans),
    }


def jobs_summary(rows: list[dict]) -> dict:
    """按 `jobs.classify_job_state` 已算好的 `state` 计数 —— **不重算 480s 阈值**。"""
    counts = {"total": len(rows), "running": 0, "stopped": 0, "verdict": 0, "other": 0}
    marks = {"在跑": "running", "断了": "stopped", "已判决": "verdict"}
    for row in rows:
        counts[marks.get(str(row.get("state", "")), "other")] += 1
    return counts


def jobs_payload(root: Path) -> dict:
    """模式③（卡 A366 · T-AG588）：在飞作业读数 —— 薄壳，判据全在 `pool.jobs.scan_jobs`。"""
    diag = diag_dir(root)
    rows = scan_jobs(diag)
    return {"root": str(root), "diag": str(diag), "summary": jobs_summary(rows),
            "jobs": rows}


def _jobs_main(args: argparse.Namespace) -> int:
    """`--jobs` 入口：`scan_jobs` 的读数原样给（面板 `/dsh-panel/pool-jobs` 吃这条）。"""
    payload = jobs_payload(Path(args.root).resolve())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    counts = payload["summary"]
    print(f"[在飞] 共 {counts['total']} 条：在跑 {counts['running']} / "
          f"断了 {counts['stopped']} / 已判决 {counts['verdict']} / "
          f"其它 {counts['other']}（{payload['diag']}）")
    for row in payload["jobs"]:
        print(f"  · {row.get('card')} {row.get('state')} "
              f"静默 {row.get('age_seconds')}s  {row.get('why')}")
    return 0


def _derived_main(args: argparse.Namespace) -> int:
    """模式②入口：派生当前仓每张卡的状态（`--root` 指定仓库根，默认当前目录）。"""
    root = Path(args.root).resolve()
    try:
        rows, marks = derive_status(root)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[FAIL] 读不了台账：{e}", file=sys.stderr)
        return 2
    orphans = orphan_tasks(root, rows, marks)
    summary = derived_summary(rows, marks, orphans)
    if args.json:
        payload = {"root": str(root), "summary": summary, "cards": rows,
                   "orphan_tasks": orphans}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"[派生] 卡 {summary['cards']} 张：done {summary['done']} / "
          f"awaiting-commit {summary['awaiting-commit']} / pending {summary['pending']}"
          f"（git 里 Task 号 {summary['tasks_in_git']} 个，"
          f"台账无条目 {summary['orphan_tasks']} 个）")
    for r in rows:
        via = f"  ← {r['via']}" if r["via"] else ""
        print(f"  · {r['id']}（{r['task']}）{r['status']}{via}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WorkBuddy/CodeBuddy stream-json 状态器"
                                     "（不给 log ⇒ 卡 A318 派生卡状态）")
    parser.add_argument("log", nargs="?", default=None,
                        help="stream-json 输出文件（.jsonl）；不给 ⇒ 派生卡状态模式")
    parser.add_argument("--tail", type=int, default=0, help="只看最后 N 条事件")
    parser.add_argument("--repo", action="store_true", help="末尾附 git 状态与最新提交")
    parser.add_argument("--json", action="store_true", help="只打印机器可读摘要")
    parser.add_argument("--root", default=".",
                        help="派生模式的仓库根（默认当前目录；log 模式下忽略）")
    parser.add_argument("--jobs", action="store_true",
                        help="模式③：看在飞作业（pool.jobs.scan_jobs 读数；卡 A366）")
    args = parser.parse_args(argv)

    if args.jobs:
        return _jobs_main(args)

    if not args.log:
        return _derived_main(args)

    path = Path(args.log)
    if not path.exists():
        print(f"[FAIL] 找不到 log：{path}", file=sys.stderr)
        return 2
    lines = read_log_lines(path)
    timeline, summary = parse_events(lines)

    if args.json:
        print(render_json(str(path), summary))
        return 0

    sys.stdout.write(render_timeline(str(path), timeline, summary,
                                     tail=args.tail, repo=args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
