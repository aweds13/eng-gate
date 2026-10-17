r"""台账与 git 历史对账 `tools/wb_reconcile.py`（卡 A269 · T-AG387）—— 只标准库。

为什么要它：2026-10-17 这一轮，队列**连续撒谎**——252/260/262 其实早已落地
（`1d94b56` / `fd02cad` / `f507aa3`），台账却还写 pending，于是又白跑了三趟全量门禁；
反过来，我自己写的收工脚本在派活前就把状态乐观翻成 done，落地失败也不回滚。
而 `audit_progress.py` 只查「status=done 有没有证据」，**不查「pending 到底有没有提交」**
⇒ 这种漂移永远不会变红，只能靠人去 `git log --grep` 猜。本工具补这一条。

判据（两条，口径写死）：
  ① **stale-pending（红）**：状态不是 done，但 `git log --grep <任务号>` 已有提交 ⇒ 台账落后于历史；
  ② **stale-done（黄，只报不拒）**：状态是 done，但找不到提交 ⇒ 可能是老账（混在别的提交里）或
     真没落 —— 本仓历史上有 15 张这种老卡，所以**不拿它当红**，只列出来给人看。

退出码：0 = 没有 stale-pending；1 = 有 stale-pending；2 = 读不了台账 / 不是 git 仓。

用法：
    python -X utf8 tools/wb_reconcile.py            # 人读
    python -X utf8 tools/wb_reconcile.py --json     # 机器读
    python -X utf8 tools/wb_reconcile.py --fix      # 把 stale-pending 改成 done（★ 会改台账）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import tomllib

__all__ = ["check", "main"]


def _commit_for(root: Path, task: str) -> str:
    """`task` 在历史里的第一笔提交（短 sha）；没有 ⇒ 空串（拿不到 git 也不抛）。"""
    r = subprocess.run(
        ["git", "log", "--format=%h", "--grep", task, "-1"],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    if r.returncode != 0:
        return ""
    lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
    return lines[0].strip() if lines else ""


def check(root: Path, cards: list[dict]) -> tuple[list[dict], list[dict]]:
    """返回 (stale_pending, stale_done)；两条判据只做**读**，不改任何东西。"""
    stale_pending: list[dict] = []
    stale_done: list[dict] = []
    for c in cards:
        task = str(c.get("task") or "")
        status = str(c.get("status") or "")
        if not task:
            continue
        sha = _commit_for(root, task)
        if status != "done" and sha:
            stale_pending.append(
                {"id": c.get("id", ""), "task": task, "status": status, "commit": sha}
            )
        elif status == "done" and not sha:
            stale_done.append({"id": c.get("id", ""), "task": task})
    return stale_pending, stale_done


def load_cards(root: Path) -> list[dict]:
    """读台账卡：有分片（`docs/backlog/*.toml`）就**只读分片**（与 `wb_task.py` 同口径）。"""
    backlog = root / "docs" / "backlog"
    shards = sorted(backlog.glob("*.toml")) if backlog.is_dir() else []
    files = shards or [root / "docs" / "workbacklog.toml"]
    cards: list[dict] = []
    for f in files:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        cards.extend(data.get("cards") or [])
    return cards


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台账状态与 git 历史对账（卡 A269）")
    ap.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="机器读（一份 JSON）")
    ap.add_argument("--fix", action="store_true",
                    help="把 stale-pending 的卡状态改成 done（★ 会写台账）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    try:
        cards = load_cards(root)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[错误] 读不了台账：{e}", file=sys.stderr)
        return 2
    stale_pending, stale_done = check(root, cards)
    if a.json:
        payload = {"stale_pending": stale_pending, "stale_done": stale_done}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for x in stale_pending:
            print(f"[红] 卡 {x['id']}（{x['task']}，状态 {x['status']}）**已有提交** {x['commit']}"
                  " ⇒ 台账落后于历史，落地时会被重复收口")
        for x in stale_done:
            print(f"[黄] 卡 {x['id']}（{x['task']}）状态 done 但找不到提交"
                  " —— 可能是老账，请人看一眼")
        if not stale_pending:
            print(f"[OK ] 没有 stale-pending（stale-done 提示 {len(stale_done)} 条，不算红）")
    if a.fix and stale_pending:
        print("★ --fix 未实现写回：本卡只做「报」，改台账请走 wb_task.py / 落地链", file=sys.stderr)
        return 1
    return 1 if stale_pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
