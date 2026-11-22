r"""台账与 git 的派生对账 `tools/wb_reconcile.py`（卡 A318 · T-AG432）—— 只标准库。

历史（卡 A269 · T-AG387 那一版）：读台账的 `status` 字段，找「stale-pending（红）/
stale-done（黄）/ 认账」。卡 A318 起**账本只存计划、状态由 git 派生**（单一事实，
见 `tools/wb_status.py` 模式②），`status` 字段退役 ⇒ 那三个判词跟着退役。
本工具现在是**纯派生视图 + 一条红判据**：

  ① 派生视图：每张卡的状态 = `wb_status.derive_status`（有 `Task:` trailer 的提交
     ⇒ done；批次围栏 landed ⇒ done / awaiting-commit ⇒ awaiting-commit；
     其余 pending）—— 口径只有 wb_status 那一份，这里不另写。
  ② **孤儿号（红）**：git 里挂了 `Task: <号>` 的提交，**队列与台账都没有该条目**
     ⇒ 红、退 1。这正是 A315/A316 事故形状（提交挂了 `Task:`、台账没记）；落地侧
     由 `wb_land.py` 的台账守卫拒落，这里负责**事后**还能被看见。

★ 卡 A394：判词一直写「台账没有该任务」，可实现只读了队列（`docs/workbacklog.toml`）。
  「台账」是**两本账** —— 队列 ∪ `docs/traceability.toml` 的 `[entries]`（含
  `docs/traceability.d` 分片，且**必须有 evidence 指针**才算登记）。2026-11-22 实测：
  按老口径 217 条红，逐条核对后 217/217 都在 traceability 里、status 全 done、
  evidence 全非空，两本账都没有的是 0 条。口径只有一份，写在 `tools/wb_queue_audit.py`
  的模块 docstring §口径（二），本文件只复用 `ledger_marks`（trailer 解析、簿记号判定、
  台账条目判定全复用，不写第二份）。

退出码：0 = 无孤儿号；1 = 有孤儿号（点名）；2 = 读不了台账 / 没有 git（跳过，
不当通过也不当红）。

用法：
    python -X utf8 tools/wb_reconcile.py            # 人读
    python -X utf8 tools/wb_reconcile.py --json     # 机器读
    python -X utf8 tools/wb_reconcile.py --root <仓库根>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import tomllib
import wb_status

__all__ = ["check", "load_cards", "main"]


def load_cards(root: Path) -> list[dict]:
    """读台账卡（计划字段）。真源在 `wb_status.load_cards`，这里留名是给老调用点。"""
    return wb_status.load_cards(root)


def _has_git(root: Path) -> bool:
    """这个目录是不是一个 git 仓（空仓 / 没有 Task 号是两件事，别混）。"""
    done = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    return done.returncode == 0


def check(root: Path) -> tuple[list[dict], list[str], dict]:
    """派生对账（只读）。返回 `(rows, orphans, marks)`：

    · `rows`：`wb_status.derive_status` 的每卡派生状态；
    · `orphans`：git 有 `Task:` 、队列与台账都无条目、且不是簿记号的号（红判据②）；
      两本账的口径见 `wb_queue_audit` 模块 docstring §口径（二）（卡 A394）；
    · `marks`：git 里全部 Task 号表（空 dict ⇒ 没有 git / 空仓，调用方退 2）。
    """
    rows, marks = wb_status.derive_status(root)
    if not marks:
        return rows, [], marks
    orphans = wb_status.orphan_tasks(root, rows, marks)
    return rows, orphans, marks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="台账与 git 的派生对账（卡 A318：状态派生 + 孤儿号升红）")
    ap.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="机器读（一份 JSON）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    try:
        rows, orphans, marks = check(root)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[错误] 读不了台账：{e}", file=sys.stderr)
        return 2
    if not _has_git(root):
        print("[跳过] 没有 git —— 派生对账不当通过也不当红（退 2）。")
        return 2
    if not marks:
        print("[OK ] git 里还没有任何 `Task:` 号（新仓初始态）；台账派生照常。")
    summary = wb_status.derived_summary(rows, marks, orphans)
    if a.json:
        payload = {"root": str(root), "summary": summary, "cards": rows,
                   "orphan_tasks": orphans}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[派生] 卡 {summary['cards']} 张：done {summary['done']} / "
              f"awaiting-commit {summary['awaiting-commit']} / "
              f"pending {summary['pending']}（git 里 Task 号 "
              f"{summary['tasks_in_git']} 个）")
        for mark in orphans:
            print(f"[红] 提交挂了 Task: {mark} 但队列（docs/workbacklog.toml）与台账"
                  "（docs/traceability.toml）都没有该条目"
                  " ⇒ 台账缺条目（A315/A316 事故形状；补登记或定性）")
        if not orphans:
            print("[OK ] 没有孤儿号（git 里的 Task 号都能在队列或台账找到条目，或为簿记号）")
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
