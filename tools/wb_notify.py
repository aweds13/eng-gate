r"""wb_notify —— 收工回推通道（卡 A297 · T-AG411）：把「收工」变成落盘的、可查的事件。

为什么有它：`wb_dispatch --detach` 派出去的活**没有回推通道**（派活器自己的提示原话就是
「请轮询」），工人收工后没有任何自动记录 —— 不跑 `wb_watch` 就没人知道。靠人记 = 一定漏
（卡 A289 于 2026-10-19 19:24 收工，直到 2026-10-20 巡检才发现；A294 靠用户关机才暴露）。

本工具把「已收工但还没落地」的卡写成一条 JSON 追加到 `gates/diag/notifications.jsonl`，
让面板看得见、让主控不用记。

    python -X utf8 tools/wb_notify.py --once                      # 扫一次，输出新写条数（可 0）
    python -X utf8 tools/wb_notify.py --daemon --interval 60      # 循环扫，写 wb_notify.pid

判据：
  · 已收工 = `gates/diag/wb-<卡>.verdict.txt` 存在且含「判决：」行；
  · 已落地 = `docs/workbacklog.toml`（或分片 `docs/backlog/*.toml`）里该卡 `status == "done"`；
  · 已落地 ⇒ 不产生通知；未落地 ⇒ 产生一条（同卡同判决不重复写 = 幂等）。

★ 只读为主：只读 verdict / backlog，只**追加** `notifications.jsonl`；不动 `wb-*.jsonl` 原始日志、
  不派活、不写仓库其它文件。`--daemon` 只多写一个 `wb_notify.pid`（派活器探活用）。
★ 边界：不判断内容对不对（那是主控复核的事），只把「收工了但没收口」这件事落盘。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# ★ 判据只有一份真源 —— 都在 tools/ 里：backlog 读取走 wb_plan（先分片后总表），
#   卡号匹配口径照抄 pool.jobs（精确正则，别宽 glob —— 卡 029 §2.9 串卡坑）。
from wb_plan import load_sharded_backlog  # noqa: E402 —— 队列读取唯一实现

DIAG_DIR = ROOT / "gates" / "diag"
NOTIFICATIONS_PATH = DIAG_DIR / "notifications.jsonl"
PID_PATH = DIAG_DIR / "wb_notify.pid"

DEFAULT_INTERVAL = 60.0

# 卡号 + 轮次后缀 + .verdict.txt —— 精确匹配（`wb-A297.verdict.txt` / `wb-A297.r2.verdict.txt`）。
# ★ 别用宽 glob `wb-*.verdict.txt`：会串到 `wb-usage.jsonl` 之类（卡 029 §2.9 同源）。
_VERDICT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.verdict\.txt$")
_VERDICT_LINE_RE = re.compile(r"^判决：\s*(.+?)\s*$", re.MULTILINE)
_ENDED_AT_RE = re.compile(r"结束于=(\S+)")


def _latest_verdicts(diag: Path) -> dict[str, Path]:
    """每张卡的**最新**判决文件（`.rN` 轮次也认；按 mtime 取最新）。

    返回 `{卡号: 判决文件}`。读不到 / 目录不在 ⇒ 空 dict。
    """
    latest: dict[str, Path] = {}
    if not diag.is_dir():
        return latest
    for path in diag.iterdir():
        m = _VERDICT_RE.match(path.name)
        if not m:
            continue
        card = m.group(1)
        try:
            mt = path.stat().st_mtime
        except OSError:
            continue
        cur = latest.get(card)
        if cur is None:
            latest[card] = path
            continue
        try:
            cur_mt = cur.stat().st_mtime
        except OSError:
            latest[card] = path
            continue
        if mt > cur_mt:
            latest[card] = path
    return latest


def _parse_verdict(path: Path) -> tuple[str, str] | None:
    """从判决文件取（判决文本, 结束时刻 ISO8601）；读不出「判决：」行 ⇒ None。

    ★ 判决文本 = `判决：` 后那一行的原文（如 `正常收工（工人退出码 0）`）。
    ★ 结束时刻 = 首行 `结束于=<ISO>`；解不出 ⇒ 用文件 mtime 兜底（仍 ISO8601）。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _VERDICT_LINE_RE.search(text)
    if not m:
        return None
    verdict = m.group(1).strip()
    ended_at = ""
    em = _ENDED_AT_RE.search(text)
    if em:
        ended_at = em.group(1).strip()
    if not _is_iso(ended_at):
        # 文件 mtime 兜底（仍给一个能被 Date/isoformat 解析的串）。
        try:
            ended_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            ended_at = datetime.now().isoformat(timespec="seconds")
    return verdict, ended_at


def _is_iso(s: str) -> bool:
    """能否被 `datetime.fromisoformat` 解析（空串 / 半截 ⇒ False）。"""
    if not s:
        return False
    try:
        datetime.fromisoformat(s)
    except ValueError:
        return False
    return True


def _done_cards(root: Path) -> set[str]:
    """读 backlog（先分片后总表），返回 `status == "done"` 的卡号集合。

    读不到 / 坏掉 ⇒ 空集合（**绝不**把「读不到」当成「全部已落地」—— 那样会漏通知）。
    """
    try:
        backlog = load_sharded_backlog(
            path=root / "docs" / "workbacklog.toml",
            shard_directory=root / "docs" / "backlog",
        )
    except Exception:  # noqa: BLE001 —— backlog 坏了不拦主流程，只是没法判 done
        return set()
    return {card.id for card in backlog.cards if card.status == "done"}


def _report_rel(verdict: Path) -> str:
    """判决对应的摘要路径（`wb-A289.verdict.txt` → `gates/diag/wb-A289.report.md`）。

    ★ 重试轮也照派：`wb-A289.r2.verdict.txt` → `gates/diag/wb-A289.r2.report.md`。
      通知只**指向**那个位置，不要求文件此刻就在（收口摘要可能还没落盘）。
    """
    name = verdict.name.replace(".verdict.txt", ".report.md")
    return f"gates/diag/{name}"


def _load_existing(path: Path) -> set[tuple[str, str]]:
    """已落盘的通知里 (card, verdict) 对（幂等键）—— 坏行跳过，不让整份文件废掉。"""
    if not path.is_file():
        return set()
    seen: set[tuple[str, str]] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return seen
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("card") and row.get("verdict"):
            seen.add((str(row["card"]), str(row["verdict"])))
    return seen


def scan_once(root: Path | None = None, *,
              diag: Path | None = None,
              out_path: Path | None = None) -> int:
    """扫一次：把「已收工但还没落地」的卡写成一条 JSON 追加到 notifications.jsonl。

    返回本次**新写**的条数（可 0）。幂等：同卡同判决不重复写。done 的卡不产生通知。
    """
    root = Path(root) if root is not None else ROOT
    diag = diag if diag is not None else root / "gates" / "diag"
    out_path = out_path if out_path is not None else diag / "notifications.jsonl"
    verdicts = _latest_verdicts(diag)
    if not verdicts:
        return 0
    done = _done_cards(root)
    seen = _load_existing(out_path)
    new_rows: list[dict[str, str]] = []
    for card, path in verdicts.items():
        if card in done:
            continue  # 已落地 ⇒ 不产生通知（卡 A297 规格）
        parsed = _parse_verdict(path)
        if parsed is None:
            continue  # 没有「判决：」行 ⇒ 不算收工，跳过
        verdict, at = parsed
        key = (card, verdict)
        if key in seen:
            continue  # 同卡同判决已写过 ⇒ 幂等跳过
        new_rows.append({
            "at": at,
            "card": card,
            "verdict": verdict,
            "report": _report_rel(path),
        })
        seen.add(key)
    if not new_rows:
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as out:
        for row in new_rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(new_rows)


# ---------------------------------------------------------------- daemon

def _write_pid(pid_path: Path) -> None:
    """把当前进程 pid 落盘（派活器探活用）。"""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    # 写不了 pid 不拦主流程（最坏只是派活器多起一个，幂等兜底）。
    with contextlib.suppress(OSError):
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")


def daemon_loop(root: Path | None = None, *,
                interval: float = DEFAULT_INTERVAL,
                diag: Path | None = None,
                out_path: Path | None = None,
                pid_path: Path | None = None,
                sleep=time.sleep,
                clock=time.time) -> int:
    """循环 `scan_once`，开头落 pid。Ctrl-C 退 0。"""
    root = Path(root) if root is not None else ROOT
    diag = diag if diag is not None else root / "gates" / "diag"
    out_path = out_path if out_path is not None else diag / "notifications.jsonl"
    pid_path = pid_path if pid_path is not None else diag / "wb_notify.pid"
    _write_pid(pid_path)
    print(f"[wb_notify] daemon 起（pid {os.getpid()}，每 {interval:.0f}s 扫一次）",
          flush=True)
    try:
        while True:
            wrote = scan_once(root, diag=diag, out_path=out_path)
            now = datetime.fromtimestamp(clock()).isoformat(timespec="seconds")
            print(f"[{now}] 新写 {wrote} 条", flush=True)
            sleep(interval)
    except KeyboardInterrupt:
        print("[wb_notify] 收到 Ctrl-C，退出", flush=True)
        return 0
    finally:
        with contextlib.suppress(OSError):
            pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="收工回推通道：把「已收工但还没落地」的卡写成 JSONL（卡 A297 · T-AG411）")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true",
                      help="扫一次，输出新写条数（可 0）")
    mode.add_argument("--daemon", action="store_true",
                      help="循环扫，写 wb_notify.pid（派活器探活用）")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help=f"daemon 轮询间隔（秒，默认 {DEFAULT_INTERVAL:.0f}）")
    ap.add_argument("--root", default=str(ROOT),
                    help="仓库根（默认本文件上两级）")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if args.once:
        wrote = scan_once(root)
        total = len(_load_existing(NOTIFICATIONS_PATH if root == ROOT
                                    else root / "gates" / "diag" / "notifications.jsonl"))
        print(f"[wb_notify] 新写 {wrote} 条（当前共 {total} 条通知）", flush=True)
        return 0
    return daemon_loop(root, interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
