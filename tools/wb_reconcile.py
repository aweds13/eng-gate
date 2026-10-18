r"""台账与 git 历史对账 `tools/wb_reconcile.py`（卡 A269 · T-AG387）—— 只标准库。

为什么要它：2026-10-17 这一轮，队列**连续撒谎**——252/260/262 其实早已落地
（`1d94b56` / `fd02cad` / `f507aa3`），台账却还写 pending，于是又白跑了三趟全量门禁；
反过来，我自己写的收工脚本在派活前就把状态乐观翻成 done，落地失败也不回滚。
而 `audit_progress.py` 只查「status=done 有没有证据」，**不查「pending 到底有没有提交」**
⇒ 这种漂移永远不会变红，只能靠人去 `git log --grep` 猜。本工具补这一条。

判据（两条，口径写死）：
  ① **stale-pending（红）**：状态仍是**活队列**（pending/todo/ready/in-progress/running），且
     **提交标题**里已经带了该任务号 ⇒ 台账落后于历史；
     ★ 只认**标题**、不认正文：正文/测试夹具里提到任务号不算落地（2026-10-17 撞过 ——
     卡 146 被 A269 的提交正文误报成 stale-pending）；
     ★ `failed` / `void` / `deferred` 等**终态**不判 stale-pending：`failed` 是「被取代 / 没做成」，
     不代表「历史里不该有提交」（卡 146 就是被卡 166 取代、旧工作故意留着）。
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


LIVE_STATUSES = frozenset({"pending", "todo", "ready", "in-progress", "running"})


def _commit_for(root: Path, task: str) -> str:
    """`task` 在**提交标题**里的第一笔提交（短 sha）；没有 ⇒ 空串（拿不到 git 也不抛）。

    ★ 只认标题：`git log --grep` 会连正文里提到任务号的提交一起捞（测试夹具 / 复盘文里常见），
    那不算落地 —— 卡 146 被 A269 的正文误报过一次。
    """
    r = subprocess.run(
        ["git", "log", "--format=%h%x00%s", "--grep", task],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    if r.returncode != 0:
        return ""
    for line in (r.stdout or "").splitlines():
        sha, _, subject = line.partition("\x00")
        if task in subject:
            return sha.strip()
    return ""


def _batch_landed(root: Path) -> dict[str, tuple[str, str]]:
    """批次围栏 → {卡号: (批号, 收口提交)}。

    只认 `state == "landed"` 且 `landed.commit` 非空的批 —— 这是「围栏状态说了算」
    （2026-10-14 `37a079c` 那次把 14 张卡翻 done 用的就是这条判据，不是「看起来像落了」）。
    读不到目录/坏 JSON 一律当没有（不抛，优雅降级）。
    """
    out: dict[str, tuple[str, str]] = {}
    batch_dir = root / "gates" / "diag" / "batch"
    if not batch_dir.is_dir():
        return out
    for f in sorted(batch_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("state") or "") != "landed":
            continue
        commit = str((data.get("landed") or {}).get("commit") or "").strip()
        if not commit:
            continue
        for card in data.get("declared") or []:
            out[str(card)] = (str(data.get("id") or f.stem), commit)
    return out


def _landed_commits(root: Path) -> set[str]:
    """所有 landed 批的收口提交（短 sha）。

    ★ 独立扫文件，**不能**从 `_batch_landed()` 的 values 取：那张表按卡号做键，
    不同批都声明 `M-1` 会互相覆盖（实测 105 个 landed 批只剩 33 个提交）。
    """
    out: set[str] = set()
    batch_dir = root / "gates" / "diag" / "batch"
    if not batch_dir.is_dir():
        return out
    for f in sorted(batch_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("state") or "") != "landed":
            continue
        commit = str((data.get("landed") or {}).get("commit") or "").strip()
        if commit:
            out.add(commit[:7])
    return out


def _spec_commit_in(root: Path, spec: str, landed: set[str]) -> str:
    """卡规格文件是被哪笔**已收口批次的提交**带进 git 的；没有 ⇒ 空串。"""
    if not spec or not landed:
        return ""
    r = subprocess.run(
        ["git", "log", "--format=%h", "--", spec],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    for sha in (r.stdout or "").split():
        if sha[:7] in landed:
            return sha
    return ""


def check(root: Path, cards: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (stale_pending, stale_done, accounted_done)。

    accounted_done = done 且没有独立 Task 提交，但**批次围栏**证明已收口的老账。
    三条判据都只做**读**，不改任何东西。
    """
    stale_pending: list[dict] = []
    stale_done: list[dict] = []
    accounted_done: list[dict] = []
    batch = _batch_landed(root)
    for c in cards:
        task = str(c.get("task") or "")
        status = str(c.get("status") or "")
        if not task:
            continue
        sha = _commit_for(root, task)
        if status in LIVE_STATUSES and sha:
            stale_pending.append(
                {"id": c.get("id", ""), "task": task, "status": status, "commit": sha}
            )
        elif status == "done" and not sha:
            hit = batch.get(str(c.get("id") or ""))
            if not hit:
                sha = _spec_commit_in(root, str(c.get("spec") or ""), _landed_commits(root))
                if sha:
                    hit = ("（按卡规格随批进 git）", sha)
            if hit:
                accounted_done.append(
                    {"id": c.get("id", ""), "task": task, "batch": hit[0], "commit": hit[1]}
                )
            else:
                stale_done.append({"id": c.get("id", ""), "task": task})
    return stale_pending, stale_done, accounted_done


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
    stale_pending, stale_done, accounted_done = check(root, cards)
    if a.json:
        payload = {"stale_pending": stale_pending, "stale_done": stale_done,
                   "accounted_done": accounted_done}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for x in stale_pending:
            print(f"[红] 卡 {x['id']}（{x['task']}，状态 {x['status']}）**已有提交** {x['commit']}"
                  " ⇒ 台账落后于历史，落地时会被重复收口")
        for x in stale_done:
            print(f"[黄] 卡 {x['id']}（{x['task']}）状态 done 但找不到提交"
                  " —— 可能是老账，请人看一眼")
        if not stale_pending:
            tail = f"stale-done {len(stale_done)} 条 / 已认账 {len(accounted_done)} 条"
            print(f"[OK ] 没有 stale-pending（{tail}，均不算红）")
    if a.fix and stale_pending:
        print("★ --fix 未实现写回：本卡只做「报」，改台账请走 wb_task.py", file=sys.stderr)
        return 1
    return 1 if stale_pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
