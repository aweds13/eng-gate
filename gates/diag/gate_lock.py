#!/usr/bin/env python
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
    **不设 = `gates/diag/gates.lock`（路径逐字不变，向后兼容）**；
    设了 = `gates/diag/gates-<BASE>.lock`；非法/越界值 → WARN 并退回默认段（同 `run_gates.py`）。
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
  - 否则**等**（不管 pid 活不活）。
    ★ 卡 E16（`T-AG467`）给这一条加了一个**收窄的**例外：租约内 + **同机** + 持有者进程
      **确实已不存在**（`OpenProcess` 只问不杀）⇒ 宽限期满才清（见下面「用法」与 `cmd_acquire`）。
      判不了（跨机 / 无 pid / 探活不可用）⇒ 仍然一律等。

★ 2026-09-27 续租（T-G161）：租约是**从 `acquire` 起算的静态计时**，而跑门禁期间锁文件没人动。
一张反证卡要连跑三趟全量门禁（≈30 分钟）时，旧的 1800s 租约会在它还在跑时到期
（063 现场：11:10 拿锁 → 连跑到 11:41，11:40 租约满，066 按规则把活锁拿走）。
两手一起修：①默认租约 1800s → 10800s；②新增 `renew` 子命令 —— 持有者（或看护）定期调用即
**刷新锁文件 mtime**，于是「多久没动」重新从 0 起算。★ 判据仍是**锁文件 mtime**，不引入 pid 判活；
串行性一点没松（`renew` 只刷 mtime，只有**同卡号**的持有者能续，别人续不了）。

锁文件固定在**主仓**的 `gates/diag/`（用 git 的 common dir 定位，
所以在 `.wt/xxx` 这样的 worktree 里跑也指向同一处）。

★ 卡 E16（`T-AG467`）补的那一处：租约**没到期**但**持有者进程已经不存在**（同机可判）时，
以前只能人肉 `cat` 锁文件 + `--force`。现在 `acquire` 会**再等一个宽限期 `--grace`（默认 60s，
防 pid 复用）**，仍不存在就清掉并打印 `[锁] 清掉死主的锁（card=… pid=… 进程已不存在）`。
★ 租约语义**没松**（T-G169 原意不变）：判据仍是「锁文件里写的租约 + 锁文件 mtime」；
死主清锁只处理「租约内 + 进程已不存在」，跨机 / 锁里没有 pid / 探活不可用 ⇒ **一律不清、只等**。

用法（在自己那棵树里）
----------------------
    python -P -X utf8 gates/diag/gate_lock.py acquire --card 057 --wait 5400
    #   --grace 0 = 关掉死主清理（回到卡 E16 之前的行为）
    python -P -X utf8 gates/diag/gate_lock.py acquire --card 057 --wait 5400 --grace 0
    python -P -X utf8 scripts/run_gates.py          # 只有拿到锁才跑
    python -P -X utf8 scripts/run_gates.py --seal
    python -P -X utf8 gates/diag/gate_lock.py renew --card 057   # 长任务：定期续租（刷新 mtime）
    python -P -X utf8 gates/diag/gate_lock.py release --card 057

    python -P -X utf8 gates/diag/gate_lock.py status   # 列出每一段的持有者与租约剩余
    python -P -X utf8 gates/diag/gate_lock.py status --json   # 同一份读数给机器读（面板路由吃这条）

★ 一定要带 `-P`：`gates/diag/` 里若放了和标准库同名的脚本，会被当模块顶掉（铁律 24）。

退出码：0 = 拿到锁/正常；3 = 等到超时；4 = 释放时锁不是你的（用 --force 才强解）；
5 = 续租时锁不是你的（别人的锁续不了）。
"""
from __future__ import annotations

import argparse
import contextlib
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

#: ★ 卡 E16（T-AG467）：死主宽限期 —— 判「同机 + pid 不存在 + 租约未过期」之后**再等**
#: 这么多秒才清（防 pid 复用）。`--grace 0` 关掉（回到卡 E16 之前的行为）。
DEFAULT_GRACE = 60

#: 等锁的轮询间隔（秒）。宽限期内的那一轮会缩短到「离宽限到期还差多少」，
#: 免得为了等 60s 宽限白转四圈 15s（判据仍以宽限期本身为准，不是这个数）。
POLL_INTERVAL = 15.0


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
            f"[锁] [WARN] TF_GATE_MAX_CONCURRENT={raw!r} 不是整数"
            f" → 退回默认 {DEFAULT_MAX_CONCURRENT}",
            flush=True,
        )
        return DEFAULT_MAX_CONCURRENT
    if n < 1:
        print(
            f"[锁] [WARN] TF_GATE_MAX_CONCURRENT={n} < 1 不合法"
            f" → 退回默认 {DEFAULT_MAX_CONCURRENT}",
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


def _pid_alive(pid: object) -> bool | None:
    r"""持有者进程还活着吗：`True` 活着 / `False` 已不存在 / `None` **判不了**。

    ★★ 坑 27：Windows 上**不许**用 `os.kill(pid, 0)` 探活 —— CPython 把它实现成
      `OpenProcess` + `TerminateProcess`，那一行会**真的把持有者的门禁进程杀掉**
      （退出码 0，看起来还像探活成功）。这里 Windows 走 `OpenProcess`，**只问不杀**：
        · 拿不到句柄：`ERROR_INVALID_PARAMETER(87)` = 没这个 pid ⇒ 死；
          `ERROR_ACCESS_DENIED(5)` 等其它错 = 有进程但问不了 ⇒ **当活着**（跨权限失败不算死）。
        · 拿到句柄：`GetExitCodeProcess == STILL_ACTIVE(259)` ⇒ 活着。
      ② POSIX 上 `os.kill(pid, 0)` 是**真探活**（该平台没有那个坑），照用。
    ★ `None` 一律**不清锁**：拿不准时宁可等（卡 E16「不许在跨机/判不了身份时清锁」）。
    """
    try:
        n = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.OpenProcess(0x1000, False, n)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            err = ctypes.get_last_error()
            return err != 87                          # 87 = 没这个 pid；别的都当活着
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return int(code.value) == 259            # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(n, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def liveness_text(info: dict) -> str:
    """给 status / 体检用的一句：`活着` / `已不存在` / `not verified（原因）`。"""
    pid = info.get("pid")
    if pid is None:
        return "not verified（锁文件里没有 pid 字段）"
    alive = _pid_alive(pid)
    if alive is None:
        return "not verified（进程探活不可用）"
    return "活着" if alive else "已不存在"


def _same_machine(info: dict) -> bool:
    """这把锁是不是**本机**写的。锁文件里没有 `host`（卡 E16 之前的旧锁）⇒ 当本机。"""
    host = str(info.get("host") or "")
    return not host or host == socket.gethostname()


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


def cmd_acquire(card: str, wait: int, stale_after: int, grace: int = DEFAULT_GRACE) -> int:
    r"""拿锁（拿不到就等）。★ 卡 E16（T-AG467）：三种「静默」各修一处。

    1. **等锁有进度**：每 60s 打一行 `[锁] 等门禁锁 Ns… <谁占着>`（消费方要**流式**读，
       见 `tools/pool/landing.py::acquire_gate_lock`：不流式 ⇒ 这些行全被 `capture_output` 吞掉）；
    2. **死主自动清**：`FileExistsError` 时除了看租约，再看持有者**进程是否还活着**。
       判定「同机 + pid 不存在 + 租约未过期」⇒ **再等宽限期 `grace`**（默认 60s，防 pid 复用），
       仍不存在（且锁文件里还是那个 pid）才清掉并打印
       `[锁] 清掉死主的锁（card=… pid=… 进程已不存在）`；
    3. **判不了就不清**：跨机（`host` 不同）/ 锁里没有 `pid` / 探活不可用 ⇒ **保持原样等待**，
       并在报行里明说「判不了持有者身份」。

    ★ 租约语义**一字不动**（T-G169：陈旧判定以锁文件里写的租约为准）：`age > 租约` 那一支
      仍在最前面、行为不变；死主清锁只处理「租约**内**但进程已不存在」这一种。
    """
    p = lock_path()
    t0 = time.time()
    printed = 0.0
    dead_since: float | None = None      # 这个 pid 第一次被判「不存在」的时刻
    dead_pid: int | None = None
    unverified_said = False
    while True:
        blocked = ""
        nap = POLL_INTERVAL
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "card": card,
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
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
                # 超卖了就退回自己这把（自删失败也无所谓：下一轮会按过期清掉）。
                with contextlib.suppress(OSError):
                    p.unlink()
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
            # ★ 卡 E16：租约内仍然要问一句「持有者还活着吗」—— 但**只在同机能判**时。
            pid_raw = info.get("pid")
            pid = int(pid_raw) if isinstance(pid_raw, int) or str(pid_raw or "").isdigit() else None
            if not _same_machine(info):
                blocked += f"；持有者在另一台机器（{info.get('host')}）⇒ 判不了，只等"
                dead_pid, dead_since = None, None
            elif pid is None:
                blocked += "；判不了持有者身份（锁文件里没有 pid）⇒ 不清，只等"
                if not unverified_said:
                    print("[锁] 判不了持有者身份（锁文件里没有 pid 字段）⇒ 清不了，只能等",
                          flush=True)
                    unverified_said = True
                dead_pid, dead_since = None, None
            elif grace <= 0:
                dead_pid, dead_since = None, None      # --grace 0 ⇒ 回到卡 E16 之前的行为
            else:
                alive = _pid_alive(pid)
                if alive is True:
                    dead_pid, dead_since = None, None
                elif alive is None:
                    blocked += "；判不了持有者身份（进程探活不可用）⇒ 不清，只等"
                    dead_pid, dead_since = None, None
                else:
                    now = time.time()
                    if dead_pid != pid or dead_since is None:
                        dead_pid, dead_since = pid, now
                    waited_dead = now - dead_since
                    blocked += (f"；持有者进程 {pid} 已不存在"
                                f"（宽限 {int(waited_dead)}/{grace}s）")
                    if waited_dead >= grace:
                        # 再确认一次：① 进程确实还不存在（防 pid 复用）
                        #              ② 锁文件里还是**这个** pid（防别人在这期间换过锁）
                        again = _read(p)
                        if _pid_alive(pid) is False and again.get("pid") == pid:
                            try:
                                p.unlink()
                                print(
                                    f"[锁] 清掉死主的锁（card={again.get('card')} pid={pid}"
                                    f" 进程已不存在；宽限 {grace}s 已满）",
                                    flush=True,
                                )
                                dead_pid, dead_since = None, None
                                continue
                            except OSError:
                                pass
                    nap = max(0.1, min(POLL_INTERVAL, grace - waited_dead))
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
        # ★ 睡不过期：宁可多转几圈，也不许「本来 wait 已经到了还多睡一轮」
        #   （判据是 `--wait`，不是轮询间隔；宽限期那一支已经把 nap 压到离到期还差多少）。
        time.sleep(max(0.1, min(nap, wait - waited)))


def cmd_release(card: str, force: bool) -> int:
    r"""放锁。★ 卡 E16（`T-AG467`）：**不再只看当前 cwd 的端口段**。

    病灶（`tools/tf_commit.py:41` 记过原话）：锁按段分把（`gates-<base>.lock`），而
    `release` 只认 `lock_path()` 那一把 ⇒ 在另一段 / 另一棵树里跑 `release --card X`
    得到「没有锁，无需释放」退 0，真正的那把锁还挂在那里（人只能 `cat` 锁 + `--force`，
    它还会白占一个全局并发名额）。
    现在先扫**全部段**：
      ① 你的卡就在某段 ⇒ 逐个释放并点出段号；
      ② 你的卡哪段都不在、但别的段有锁 ⇒ **点名持有者**（段 / card / pid）并退 4
         （不许把「锁在别的段」静默说成「没有锁」）；
      ③ 当前段那把不是你的 ⇒ `--force` 语义不变（人工兜底），不加就退 4 并点名。
    ★ 判据仍是「锁文件里的 `card` 是不是你」；租约语义一字不动（本函数不看租约）。
    """
    holders = [(p, _read(p)) for p in all_lock_paths()]
    mine = [(p, info) for p, info in holders if info.get("card") == card]
    if mine:
        rc = 0
        for p, info in mine:
            try:
                p.unlink()
            except OSError as exc:
                print(f"[锁] 删不掉 {p.name}：{exc}", flush=True)
                rc = 4
                continue
            print(f"[锁] 已释放（card={card} 段 base={info.get('base')} 文件={p.name}）",
                  flush=True)
        return rc
    if not holders:
        print("[锁] 没有锁，无需释放", flush=True)
        return 0
    for p, info in holders:
        print(
            f"[锁] ★ {card} 不是这把锁的持有者：段 base={info.get('base')}"
            f" 文件={p.name} card={info.get('card')} pid={info.get('pid')}",
            flush=True,
        )
    cur = lock_path()
    if force and cur.exists():
        try:
            cur.unlink()
        except OSError as exc:
            print(f"[锁] 删不掉：{exc}", flush=True)
            return 4
        print(f"[锁] ★ 已强解当前段那把（card={card} 并非持有者；--force 人工兜底）",
              flush=True)
        return 0
    print("[锁] ★ 不释放别人的锁；确要强解当前段那把加 --force", flush=True)
    return 4


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


def _status_payload(stale_after: int) -> dict:
    """把锁读数拼成 dict（`--json` 用）—— 人读文本与 JSON 吃**同一份**数据，不各算一遍。

    ★ 卡 A366（T-AG588）：面板要读「现在能不能跑门禁」，判据仍只在本文件里；
    面板只转发，不重算陈旧阈值、不重算并发上限。
    """
    locks = all_lock_paths()
    rows = []
    for p in locks:
        info = _read(p)
        age = int(_age(p))
        lease = _lease_of(p, info, stale_after)
        rows.append({
            "file": p.name,
            "base": info.get("base", DEFAULT_PORT_BASE),
            "card": info.get("card"),
            "pid": info.get("pid"),
            "at": info.get("at"),
            "cwd": info.get("cwd"),
            "age_seconds": age,
            "lease_seconds": lease,
            "remain_seconds": lease - age,
            "expired": age > lease,
            "holder": liveness_text(info),
        })
    return {
        "ok": True,
        "empty": not rows,
        "locks": rows,
        "note": "★ 别看 pid 判活：acquire 与 run_gates 是两次进程调用，pid 正常就会是死的。",
        "max_concurrent": max_concurrent(),
        "active": len(_active_locks(stale_after)),
        "port_base": segment_base(),
        "ports_busy": _ports_busy(),
    }


def cmd_status(stale_after: int, as_json: bool = False) -> int:
    """看锁：**列出每一段**的持有者与租约剩余（T-G169：从"只看一把"改成扫全部段）。"""
    payload = _status_payload(stale_after)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    if payload["empty"]:
        print("[锁] 空着（没有任何段的锁）", flush=True)
    for row in payload["locks"]:
        print(
            f"[锁] 段 base={row['base']} 文件={row['file']}: card={row['card']}"
            f" pid={row['pid']} 起于 {row['at']}"
            f"（已 {row['age_seconds']}s / 租约剩 {row['remain_seconds']}s；"
            f"{'★ 超过租约，可被清' if row['expired'] else '租约内'}）"
            f" 持有者进程={row['holder']}"
            f" cwd={row['cwd']}",
            flush=True,
        )
    print(f"[锁] {payload['note']}", flush=True)
    print(
        f"[锁] 全局并发上限 TF_GATE_MAX_CONCURRENT={payload['max_concurrent']}，"
        f"当前租约内 {payload['active']} 把在跑",
        flush=True,
    )
    print(
        "[锁] 本段门禁端口占用（base=" + str(payload["port_base"]) + "）："
        + (", ".join(payload["ports_busy"]) if payload["ports_busy"] else "全空"),
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
    a.add_argument(
        "--grace",
        type=int,
        default=DEFAULT_GRACE,
        help=f"判出「同机 + 持有者进程已不存在 + 租约未过期」后再等多少秒才清锁"
             f"（默认 {DEFAULT_GRACE}s，防 pid 复用；=0 关掉，回到卡 E16 之前的行为）",
    )
    r = sub.add_parser("release", help="放锁")
    r.add_argument("--card", required=True)
    r.add_argument("--force", action="store_true")
    n = sub.add_parser("renew", help="续租（刷新锁文件 mtime；只有当前持有者同卡号才允许）")
    n.add_argument("--card", required=True)
    s = sub.add_parser("status", help="看锁")
    s.add_argument("--stale-after", type=int, default=DEFAULT_STALE_AFTER)
    s.add_argument(
        "--json",
        action="store_true",
        help="机器读：把同一份读数打成 JSON（面板读 /dsh-panel/pool-locks 吃这条）",
    )
    ns = ap.parse_args()
    if ns.cmd == "acquire":
        return cmd_acquire(ns.card, ns.wait, ns.stale_after, ns.grace)
    if ns.cmd == "release":
        return cmd_release(ns.card, ns.force)
    if ns.cmd == "renew":
        return cmd_renew(ns.card)
    return cmd_status(ns.stale_after, ns.json)


if __name__ == "__main__":
    sys.exit(main())
