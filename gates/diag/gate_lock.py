#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁串行锁 —— 铁律 13 的机械化（fork/merge 并行开发必备）。

为什么需要
----------
`scripts/run_gates.py` 里的浏览器门用**固定端口**（render 8531/8532、ui_flow 8541~8544）。
两条线同时跑门禁 = 互相把服务掐掉 → **假红**（051 与 I-6 撞过，见 `自动推进表.md` 铁律 13）。
fork/merge 并行时每条树都要跑门禁，所以用一把**跨树共享**的文件锁把「跑门禁」那一段串起来。

租约（lease）而不是 pid
-----------------------
★★ 2026-09-27 踩过一次：第一版把「建锁进程的 pid 还活着吗」当僵尸判据 —— **错的**。
`acquire` 与 `run_gates` 往往是**两次不同的进程调用**，建锁那个进程一退出，
pid 立刻就"死"了，锁看着像僵尸 → 下一张卡把**正在跑门禁的活锁**偷走 → 又撞端口。
现在改成**按锁文件的年龄**（租约）判：
  - 锁比 `--stale-after`（默认 10800s = 3 小时）旧 → 视为陈旧，清掉重拿（会大声打印）；
  - 否则一律**等**（不管 pid 活不活）。

★ 2026-09-27 续租（T-G161）：租约是**从 `acquire` 起算的静态计时**，而跑门禁期间锁文件没人动。
一张反证卡要连跑三趟全量门禁（≈30 分钟）时，旧的 1800s 租约会在它还在跑时到期
（063 现场：11:10 拿锁 → 连跑到 11:41，11:40 租约满，066 按规则把活锁拿走）。
两手一起修：①默认租约 1800s → 10800s；②新增 `renew` 子命令 —— 持有者（或看护）定期调用即
**刷新锁文件 mtime**，于是「多久没动」重新从 0 起算。★ 判据仍是**锁文件 mtime**，不引入 pid 判活；
串行性一点没松（`renew` 只刷 mtime，只有**同卡号**的持有者能续，别人续不了）。

锁文件固定在**主仓**的 `gates/diag/gates.lock`（用 git 的 common dir 定位，
所以在 `.wt/xxx` 这样的 worktree 里跑也指向同一把锁）。

用法（在自己那棵树里）
----------------------
    python -P -X utf8 gates/diag/gate_lock.py acquire --card 057 --wait 5400
    python -P -X utf8 scripts/run_gates.py          # 只有拿到锁才跑
    python -P -X utf8 scripts/run_gates.py --seal
    python -P -X utf8 gates/diag/gate_lock.py renew --card 057   # 长任务：定期续租（刷新 mtime）
    python -P -X utf8 gates/diag/gate_lock.py release --card 057

    python -P -X utf8 gates/diag/gate_lock.py status

★ 一定要带 `-P`：`gates/diag/` 里若放了和标准库同名的脚本，会被当模块顶掉（铁律 24）。

退出码：0 = 拿到锁/正常；3 = 等到超时；4 = 释放时锁不是你的（用 --force 才强解）；
5 = 续租时锁不是你的（别人的锁续不了）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

GATE_PORTS = (8531, 8532, 8541, 8542, 8543, 8544)
DEFAULT_STALE_AFTER = 10800


def gate_ports() -> tuple[int, ...]:
    """锁要报告的"门禁端口段"。

    ★ T-G156 配合端口隔离：设了 `TF_GATE_PORT_BASE` 就跟它平移（口径同
    `scripts/run_gates.py`：render BASE/BASE+1、ui_flow BASE+10..+13）；
    **不设 = 历史的 8531/8532/8541~8544，逐字不变**。锁本身仍是**跨树一把**
    （BASE 只影响"报哪些端口忙"，不放松串行）。
    """
    raw = os.environ.get("TF_GATE_PORT_BASE", "").strip()
    if not raw:
        return GATE_PORTS
    try:
        base = int(raw)
    except ValueError:
        return GATE_PORTS
    return (base, base + 1, base + 10, base + 11, base + 12, base + 13)


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (out.stdout or "").strip()


def main_root() -> Path:
    """主仓根（worktree 里跑也返回主仓根）。"""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        return Path(common).resolve().parent
    return Path(_git("rev-parse", "--show-toplevel") or ".").resolve()


def lock_path() -> Path:
    d = main_root() / "gates" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    return d / "gates.lock"


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age(p: Path) -> float:
    try:
        return max(0.0, time.time() - p.stat().st_mtime)
    except OSError:
        return 0.0


def _ports_busy() -> list[str]:
    """门禁端口有没有人在听（只报，不掐）。★ T-G156：端口段跟随 `TF_GATE_PORT_BASE`。"""
    hits: list[str] = []
    for port in gate_ports():
        try:
            s = socket.socket()
            s.settimeout(0.2)
            busy = s.connect_ex(("127.0.0.1", port)) == 0
            s.close()
            if busy:
                hits.append(str(port))
        except Exception:
            pass
    return hits


def cmd_acquire(card: str, wait: int, stale_after: int) -> int:
    p = lock_path()
    t0 = time.time()
    printed = 0.0
    while True:
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "card": card,
                        "pid": os.getpid(),
                        "cwd": str(Path.cwd()),
                        "at": datetime.now().isoformat(timespec="seconds"),
                    },
                    fh,
                    ensure_ascii=False,
                )
            busy = _ports_busy()
            print(f"[锁] 拿到了（card={card} pid={os.getpid()}）文件={p}", flush=True)
            expire = datetime.now() + timedelta(seconds=stale_after)
            print(
                f"[锁] 租约到期：{expire.strftime('%Y-%m-%d %H:%M:%S')}"
                f"（{stale_after}s 后）—— 到期前记得 release，或让它自己续租"
                f"（renew --card {card}）。",
                flush=True,
            )
            if busy:
                print(
                    "[锁] ★ 警告：门禁端口已被占用：" + ", ".join(busy) + "（可能是上一轮的遗留服务）",
                    flush=True,
                )
            print("[锁] 现在可以跑 scripts/run_gates.py；跑完立刻 release。", flush=True)
            return 0
        except FileExistsError:
            info = _read(p)
            age = _age(p)
            if age > stale_after:
                try:
                    p.unlink()
                    print(
                        f"[锁] 清掉陈旧锁（已 {int(age)}s 未动 > {stale_after}s；"
                        f"原 card={info.get('card')} pid={info.get('pid')} 起于 {info.get('at')}）",
                        flush=True,
                    )
                    continue
                except OSError:
                    pass
            waited = time.time() - t0
            if waited >= wait:
                print(
                    f"[锁] ★ 等超时（{wait}s）——现持有者 card={info.get('card')} "
                    f"pid={info.get('pid')} 起于 {info.get('at')}（已 {int(age)}s）",
                    flush=True,
                )
                return 3
            if waited - printed >= 60:
                printed = waited
                busy = _ports_busy()
                print(
                    f"[锁] 等门禁锁 {int(waited)}s… 持有者 card={info.get('card')} "
                    f"pid={info.get('pid')}（已 {int(age)}s；端口{'忙:' + ','.join(busy) if busy else '空'}）",
                    flush=True,
                )
            time.sleep(15)


def cmd_release(card: str, force: bool) -> int:
    p = lock_path()
    if not p.exists():
        print("[锁] 没有锁，无需释放", flush=True)
        return 0
    info = _read(p)
    if info.get("card") != card and not force:
        print(
            f"[锁] ★ 锁不是你的（持有者 card={info.get('card')} pid={info.get('pid')}）；"
            f"确要强解加 --force",
            flush=True,
        )
        return 4
    try:
        p.unlink()
    except OSError as exc:
        print(f"[锁] 删不掉：{exc}", flush=True)
        return 4
    print(f"[锁] 已释放（card={card}）", flush=True)
    return 0


def cmd_renew(card: str) -> int:
    """续租：把锁文件 mtime 刷成现在（「多久没动」重新从 0 起算）。

    ★ T-G161：只有**当前持有者同卡号**才允许续 —— 别人的锁续不了（返回 5，且**不动**原锁）。
    判据仍是锁文件 mtime，不引入 pid 判活；也不改变「谁能拿锁」，串行没松。
    """
    p = lock_path()
    if not p.exists():
        print("[锁] 没有锁，无从续租", flush=True)
        return 4
    info = _read(p)
    if info.get("card") != card:
        print(
            f"[锁] ★ 续租被拒：锁持有者是 card={info.get('card')}，不是 {card}"
            f"（别人的锁续不了；原锁未动）",
            flush=True,
        )
        return 5
    try:
        os.utime(p, None)
    except OSError as exc:
        print(f"[锁] 续租失败：{exc}", flush=True)
        return 4
    print(
        f"[锁] 已续租（card={card}）—— 锁文件 mtime 已刷新，age={int(_age(p))}s",
        flush=True,
    )
    return 0


def cmd_status(stale_after: int) -> int:
    p = lock_path()
    if not p.exists():
        print("[锁] 空着", flush=True)
    else:
        info = _read(p)
        age = int(_age(p))
        print(
            f"[锁] 被占：card={info.get('card')} pid={info.get('pid')} 起于 {info.get('at')}"
            f"（已 {age}s；{'★ 超过租约，可被清' if age > stale_after else '租约内'}）"
            f" cwd={info.get('cwd')}",
            flush=True,
        )
        print("[锁] ★ 别看 pid 判活：acquire 与 run_gates 是两次进程调用，pid 正常就会是死的。", flush=True)
    busy = _ports_busy()
    print("[锁] 门禁端口占用：" + (", ".join(busy) if busy else "全空"), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="门禁串行锁（跨树共享，按租约判陈旧）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("acquire", help="拿锁（拿不到就等）")
    a.add_argument("--card", required=True)
    a.add_argument("--wait", type=int, default=5400, help="最多等多少秒（默认 5400）")
    a.add_argument(
        "--stale-after",
        type=int,
        default=DEFAULT_STALE_AFTER,
        help=f"锁多久没动算陈旧（默认 {DEFAULT_STALE_AFTER}s）",
    )
    r = sub.add_parser("release", help="放锁")
    r.add_argument("--card", required=True)
    r.add_argument("--force", action="store_true")
    n = sub.add_parser("renew", help="续租（刷新锁文件 mtime；只有当前持有者同卡号才允许）")
    n.add_argument("--card", required=True)
    s = sub.add_parser("status", help="看锁")
    s.add_argument("--stale-after", type=int, default=DEFAULT_STALE_AFTER)
    ns = ap.parse_args()
    if ns.cmd == "acquire":
        return cmd_acquire(ns.card, ns.wait, ns.stale_after)
    if ns.cmd == "release":
        return cmd_release(ns.card, ns.force)
    if ns.cmd == "renew":
        return cmd_renew(ns.card)
    return cmd_status(ns.stale_after)


if __name__ == "__main__":
    sys.exit(main())
