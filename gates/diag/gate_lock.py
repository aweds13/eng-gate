#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁锁 —— 按端口段分把 + 全局并发上限（铁律 13 的机械化；fork/merge 并行开发必备）。

为什么需要
----------
`scripts/run_gates.py` 里的浏览器门用**固定端口段**（render BASE/BASE+1、ui_flow BASE+10~+13，
默认 BASE=8531）。同一段两条线同时跑门禁 = 互相把服务掐掉 → **假红**
（051 与 I-6 撞过，见 `自动推进表.md` 铁律 13）。

★ 2026-09-27（T-G169，用户原话「不能多几把跨树锁」）：062（T-G156）已把端口按树隔离并实测
两段可**同时**跑真机门，所以「同一时刻整机只许一趟门禁」不再必要。必要条件收敛成两条：
  1. **同一个端口段**不许两趟门禁并行（否则撞端口 → 假红）；
  2. **整机并行趟数**有上限（真正的瓶颈是内存：一趟 17 门要 15–30 个无头 Edge）。
于是锁从「跨树一把」改成「**每段一把 + 全局限额**」：
  - 锁文件按 `TF_GATE_PORT_BASE` 分把（与 `scripts/run_gates.py` 的 `port_base()` 同一口径）：
    **不设 = `gates/diag/gates.lock`（路径逐字不变，向后兼容）**；设了 = `gates/diag/gates-<BASE>.lock`；
    非法/越界值 → WARN 并退回默认段（同 `run_gates.py`）。
  - 新变量 `TF_GATE_MAX_CONCURRENT`（默认 2）：**同时**持锁的段数 ≤ N；=1 即退回「全局串行」旧行为。
    超限时 `acquire` 里等（打印「当前 N 把在跑，等空位」）。空位**随租约一起过期**：
    扫描名额时只数**租约内**的活锁，持有者死了/租约过期 → 名额自动回归，不会泄漏。
  - 上限只保护内存，**不参与**任何「门禁通过与否」的判定。

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

锁文件固定在**主仓**的 `gates/diag/`（用 git 的 common dir 定位，
所以在 `.wt/xxx` 这样的 worktree 里跑也指向同一处）。

用法（在自己那棵树里）
----------------------
    python -P -X utf8 gates/diag/gate_lock.py acquire --card 057 --wait 5400
    python -P -X utf8 scripts/run_gates.py          # 只有拿到锁才跑
    python -P -X utf8 scripts/run_gates.py --seal
    python -P -X utf8 gates/diag/gate_lock.py renew --card 057   # 长任务：定期续租（刷新 mtime）
    python -P -X utf8 gates/diag/gate_lock.py release --card 057

    python -P -X utf8 gates/diag/gate_lock.py status   # 列出每一段的持有者与租约剩余

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

# ★ 卡 148（T-G248）：子进程一律不弹窗 —— flag 与 `tools/pool/no_window.py` **同一真源**。
#   本脚本用 `-P` 跑（铁律 24）时**不**把自身目录放上 sys.path → 显式把仓库 `tools/` 挂上。
for _base in Path(__file__).resolve().parents:
    _tools = _base / "tools"
    if (_tools / "pool" / "no_window.py").is_file():
        if str(_tools) not in sys.path:
            sys.path.insert(0, str(_tools))
        break
from pool.no_window import NO_WINDOW  # noqa: E402 —— 需先挂 sys.path（见上）

GATE_PORTS = (8531, 8532, 8541, 8542, 8543, 8544)
DEFAULT_STALE_AFTER = 10800
DEFAULT_PORT_BASE = 8531
DEFAULT_MAX_CONCURRENT = 2


def segment_base() -> int:
    """锁（与门）的端口段基准。

    ★ T-G169：取段规则与 `scripts/run_gates.py` 的 `port_base()` **同一个口径**：
    **不设 `TF_GATE_PORT_BASE` = 8531**（历史默认，逐字不变）；
    非整数 / 越界（1024..65500 之外）→ 打 WARN 并退回 8531（同 `run_gates.py`）。
    """
    raw = os.environ.get("TF_GATE_PORT_BASE", "").strip()
    if not raw:
        return DEFAULT_PORT_BASE
    try:
        base = int(raw)
    except ValueError:
        print(
            f"[锁] [WARN] TF_GATE_PORT_BASE={raw!r} 不是整数 → 退回默认段 {DEFAULT_PORT_BASE}",
            flush=True,
        )
        return DEFAULT_PORT_BASE
    if not (1024 <= base <= 65500):
        print(
            f"[锁] [WARN] TF_GATE_PORT_BASE={base} 越界（要求 1024..65500）→ 退回默认段 "
            f"{DEFAULT_PORT_BASE}",
            flush=True,
        )
        return DEFAULT_PORT_BASE
    return base


def gate_ports() -> tuple[int, ...]:
    """锁要报告的"门禁端口段"。

    ★ T-G156 配合端口隔离：设了 `TF_GATE_PORT_BASE` 就跟它平移（口径同
    `scripts/run_gates.py`：render BASE/BASE+1、ui_flow BASE+10..+13）；
    **不设 = 历史的 8531/8532/8541~8544，逐字不变**。
    ★ T-G169：BASE 现在同时决定**用哪把锁**（`lock_path()`）——同一段共用一把，跨段各拿各的。
    """
    base = segment_base()
    if base == DEFAULT_PORT_BASE:
        return GATE_PORTS
    return (base, base + 1, base + 10, base + 11, base + 12, base + 13)


def max_concurrent() -> int:
    """全局并发上限：**同时**持锁的段数 ≤ N（`TF_GATE_MAX_CONCURRENT`，默认 2）。

    ★ T-G169：默认 2（保守：机器 15.2 GB 内存、常驻只剩 1–3 GB）；=1 即退回「全局串行」旧行为；
    ≤0 / 非整数 → WARN 退回默认。上限只保护内存，**不参与**门禁通过与否的判定。
    """
    raw = os.environ.get("TF_GATE_MAX_CONCURRENT", "").strip()
    if not raw:
        return DEFAULT_MAX_CONCURRENT
    try:
        n = int(raw)
    except ValueError:
        print(
            f"[锁] [WARN] TF_GATE_MAX_CONCURRENT={raw!r} 不是整数 → 退回默认 {DEFAULT_MAX_CONCURRENT}",
            flush=True,
        )
        return DEFAULT_MAX_CONCURRENT
    if n < 1:
        print(
            f"[锁] [WARN] TF_GATE_MAX_CONCURRENT={n} < 1 不合法 → 退回默认 {DEFAULT_MAX_CONCURRENT}",
            flush=True,
        )
        return DEFAULT_MAX_CONCURRENT
    return n


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        **NO_WINDOW,
    )
    return (out.stdout or "").strip()


def main_root() -> Path:
    """主仓根（worktree 里跑也返回主仓根）。"""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        return Path(common).resolve().parent
    return Path(_git("rev-parse", "--show-toplevel") or ".").resolve()


def lock_dir() -> Path:
    """全部段锁所在目录（由 `lock_path()` 派生）。

    ★ 测试把 `lock_path` monkeypatch 到临时目录时，这里**自动跟着隔离** ——
    不然 status / 名额扫描会去读真锁目录，混进别人卡的锁（真踩过：lease 测试的
    断言被 docsync1 的锁行污染）。
    """
    d = lock_path().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path() -> Path:
    """本段锁文件的路径。

    ★ T-G169 锁按端口段分把：**不设 `TF_GATE_PORT_BASE` → 仍是 `gates/diag/gates.lock`**
    （路径逐字不变：台账/文档/别的卡里写死的路径都还成立）；
    设了 BASE → `gates/diag/gates-<BASE>.lock`（BASE 非法时 `segment_base()` 已退回默认段）。
    """
    base = segment_base()
    name = "gates.lock" if base == DEFAULT_PORT_BASE else f"gates-{base}.lock"
    d = main_root() / "gates" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def all_lock_paths() -> list[Path]:
    """`gates/diag/` 下全部锁文件（各段一把：gates.lock + gates-<BASE>.lock）。

    ★ 从 `lock_path().parent` 派生（不直接走 `main_root()`）—— 测试隔离的同一个口。
    """
    return sorted(lock_path().parent.glob("gates*.lock"))


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


def _lease_of(p: Path, info: dict, fallback: int) -> int:
    """这把锁自己的租约（acquire 时写进锁文件；旧格式锁回退用调用者给的值）。"""
    raw = info.get("lease")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _active_locks(stale_default: int) -> list[tuple[Path, dict, float]]:
    """目录里全部**租约内**的活锁（含本段）。

    ★ T-G169 空位随租约一起过期：只数 `age ≤ 租约` 的锁 —— 持有者死了/租约过期，
    它占的名额自动回归，不会出现「空位泄漏导致永远等不到」。
    """
    out: list[tuple[Path, dict, float]] = []
    for p in all_lock_paths():
        info = _read(p)
        age = _age(p)
        if age <= _lease_of(p, info, stale_default):
            out.append((p, info, age))
    return out


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
        blocked = ""
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "card": card,
                        "pid": os.getpid(),
                        "cwd": str(Path.cwd()),
                        "base": segment_base(),
                        "lease": stale_after,
                        "at": datetime.now().isoformat(timespec="seconds"),
                    },
                    fh,
                    ensure_ascii=False,
                )
            # ★ T-G169 全局并发上限：先创建、再重扫全目录（计数含自己刚创建的这把）。
            #   超限就自删退回等空位 —— 计数发生在创建之后，所以不会超卖；
            #   名额只数租约内的活锁，持有者过期 → 空位自动回归（_active_locks）。
            active = _active_locks(stale_after)
            limit = max_concurrent()
            if len(active) > limit:
                try:
                    p.unlink()
                except OSError:
                    pass
                holders = ", ".join(
                    f"{info.get('card')}({pl.name})" for pl, info, _ in active
                )
                blocked = (
                    f"当前 {len(active)} 把在跑（上限 {limit}）：{holders}，等空位"
                )
            else:
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
                        "[锁] ★ 警告：门禁端口已被占用：" + ", ".join(busy)
                        + "（可能是上一轮的遗留服务）",
                        flush=True,
                    )
                print(
                    f"[锁] 现在可以跑 scripts/run_gates.py；跑完立刻 release。"
                    f"（全局 {len(active)}/{limit} 把在跑）",
                    flush=True,
                )
                return 0
        except FileExistsError:
            info = _read(p)
            age = _age(p)
            # ★ T-G169：陈旧判定以**持有者写进锁文件的租约**为准（旧格式锁没有 lease
            #   字段才回退等待者的 stale_after）。等的人拿个短 --stale-after 就把
            #   别人的活锁清走 = 063 现场的翻版（铁律 25/29 的保证收紧，不是放松）。
            holder_lease = _lease_of(p, info, stale_after)
            if age > holder_lease:
                try:
                    p.unlink()
                    print(
                        f"[锁] 清掉陈旧锁（已 {int(age)}s 未动 > 租约 {holder_lease}s；"
                        f"原 card={info.get('card')} pid={info.get('pid')} 起于 {info.get('at')}）",
                        flush=True,
                    )
                    continue
                except OSError:
                    pass
            blocked = (
                f"本段锁被占：card={info.get('card')} pid={info.get('pid')}"
                f"（已 {int(age)}s）"
            )
        waited = time.time() - t0
        if waited >= wait:
            print(f"[锁] ★ 等超时（{wait}s）——{blocked}", flush=True)
            return 3
        if waited - printed >= 60:
            printed = waited
            busy = _ports_busy()
            print(
                f"[锁] 等门禁锁 {int(waited)}s… {blocked}"
                f"（端口{'忙:' + ','.join(busy) if busy else '空'}）",
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
    """看锁：**列出每一段**的持有者与租约剩余（T-G169：从"只看一把"改成扫全部段）。"""
    locks = all_lock_paths()
    if not locks:
        print("[锁] 空着（没有任何段的锁）", flush=True)
    for p in locks:
        info = _read(p)
        age = int(_age(p))
        lease = _lease_of(p, info, stale_after)
        remain = lease - age
        base = info.get("base", DEFAULT_PORT_BASE)
        print(
            f"[锁] 段 base={base} 文件={p.name}: card={info.get('card')}"
            f" pid={info.get('pid')} 起于 {info.get('at')}"
            f"（已 {age}s / 租约剩 {remain}s；"
            f"{'★ 超过租约，可被清' if age > lease else '租约内'}）"
            f" cwd={info.get('cwd')}",
            flush=True,
        )
    print(
        "[锁] ★ 别看 pid 判活：acquire 与 run_gates 是两次进程调用，pid 正常就会是死的。",
        flush=True,
    )
    active = _active_locks(stale_after)
    limit = max_concurrent()
    print(
        f"[锁] 全局并发上限 TF_GATE_MAX_CONCURRENT={limit}，当前租约内 {len(active)} 把在跑",
        flush=True,
    )
    busy = _ports_busy()
    print(
        "[锁] 本段门禁端口占用（base=" + str(segment_base()) + "）："
        + (", ".join(busy) if busy else "全空"),
        flush=True,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="门禁锁（按端口段分把 + 全局并发上限；按租约判陈旧，T-G169）"
    )
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
