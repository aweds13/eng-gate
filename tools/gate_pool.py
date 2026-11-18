r"""云侧门禁池（卡 E42 · `T-AG494`）—— 只标准库。

为什么有它：本机跑一趟全量门禁时 `available_memory_gb()` 实测掉到 0.6–1.0 GB，工人
被挤到没内存；两趟并行还会把 `pytest` 从 341 s 拖到 506 s（卡 E42 §1 的真读数）。
云机（`docs/subsystems/ci/云门禁机.md` §1）跑得慢（同 commit pytest 684.27 s vs 本机
403.46 s），但**不占本机**。所以口径改成：**本机只编排，云机当门禁池**。

本模块只管云那半边（本机编排在 `tools/pool/landing.py` 的 ④）：

1. **槽位**：云机上 N 个独立 checkout，槽位数 = `min(cpu // 4, (avail_gb - 3) // 4)`，
   下限 1（4 vCPU ⇒ 1 槽；8 vCPU ⇒ 2 槽；内存不够 ⇒ 1 槽）。
2. **端口段**：每槽一段 `9200 + slot * 40`（步长 40 ≥ 一趟全量用掉的 20 个端口），
   段与段不重叠。
3. **队列**：`gates/diag/gate-pool-queue.json`，形状对齐 `tools/pool/queue.py`
   （`{"head": …, "waiting": [...]}`）再补 `done` 与 `slots`；**单写者 + 原子替换**
   （tmp + `os.replace`），并发写不丢行。同一槽的并发提交**排队**，不并行。
★ 卡 E120（T-AG629）：「读不到」与「读到空」必须分得开 —— 队列 / 日志 / 播种源 / 槽位 /
  锁 六类静默都改成「说判不了并退非 0 或抛」，**不许**把读不到洗成返回空。
4. **槽锁**：`gates/diag/gate-pool-slot<n>.lock`，语义照 `gates/diag/gate_lock.py`：
   文件 mtime 旧于 `DEFAULT_STALE_AFTER` 视为陈旧可抢，`release` 删文件。
5. **回传校验（fail closed，五条一条都不能松）**：见 `validate_cloud_return`。
   任何一条不满足 ⇒ 判红，**不许**当成功。

★ 不许做的事（卡 E42 §4 逐字）：不把云机慢当理由把默认改回本机；不在云机上跑工人；
  不跳过封存指纹核验；不让云机与本地各跑一半门（档位整体在一边）。
★ 边界（如实写）：本模块**没有**在真云机上跑过（工人这一轮没有云机 SSH，卡规格也明说
  「云机实测由主控做」）。它交付的是：口径 + 原子队列 + 五条校验 + 钉子（假 `host` /
  假回传数据）。`SshTransport` 是唯一碰网络的实现，单测一律注入假 transport。
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

try:  # `tools/` 在 sys.path 上时（脚本与多数钉子）直接导入
    import gate_base  # 派生物差异分类器（卡 E123：MATCH / LEDGER_ONLY / DRIFT，全仓只此一份）
    import gate_verdict  # 三把尺子共用的判据（卡 E63：零门 / 未验证 / 复用来源）
except ModuleNotFoundError:  # pragma: no cover —— 被当包导入时（`from tools import gate_pool`）
    from tools import (
        gate_base,  # type: ignore[no-redef]
        gate_verdict,  # type: ignore[no-redef]
    )

try:  # ★ 写盘纪律（卡 A330）：同上 —— `tools/` 在 sys.path 上时 `pool` 可导；落地桩里退回包路径
    from pool import lastgood
except ModuleNotFoundError:  # pragma: no cover —— 被当包导入时（`from tools import gate_pool`）
    from tools.pool import lastgood  # type: ignore[no-redef]

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Callable

# ---------------------------------------------------------------- 槽位 / 端口段
#: 一槽至少 4 个 vCPU（云机 4 vCPU ⇒ 1 槽；8 vCPU ⇒ 2 槽）。
CPU_PER_SLOT = 4
#: 留给系统 / sshd / 结算的余量（GB）。8 vCPU 16 GiB ⇒ (16-3)//4 = 3 槽，但 CPU 只给 2。
MIN_AVAIL_GB = 3.0
#: 每槽再要 4 GiB（一趟全量 = pytest -n 4 + 两道真浏览器）。
MEM_PER_SLOT_GB = 4.0
#: 端口池起点与每槽步长（一趟全量实际用掉 ≤ 20 个端口，步长 40 留足余量）。
POOL_PORT_BASE = 9200
SLOT_PORT_STRIDE = 40

#: 槽锁陈旧阈值（秒）—— 与 `gates/diag/gate_lock.py` 的 `DEFAULT_STALE_AFTER` 同值。
DEFAULT_STALE_AFTER = 10800.0

#: 队列短锁的等待窗口（秒）。卡 E55（`T-AG507`）：10.0 在这台机器上被调度饥饿打穿过
#: （`avail 0.73 GB / used 95.2%` 时 12 线程抢锁，等满 10 s 就无锁写 ⇒ 丢行）。
#: 临界区实测是毫秒级，30 s 是三倍余量；**与 `tools/pool/queue.py::LOCK_WAIT_S` 必须同值**
#: （钉子 `test_queue_lock_wait_defaults_agree` 守住）。
LOCK_WAIT_S = 30.0

#: 队列文件（相对仓库根）；`TF_GATE_POOL_QUEUE` 可覆写（测试 / 演练）。
QUEUE_REL = ("gates", "diag", "gate-pool-queue.json")

#: `pytest.log` 里 `N passed` 的取法（末行那种 `3303 passed, 1513 warnings in 270.28s`）。
PASSED_MIN_RATIO = 0.95

#: `run_gate.sh` 全量实测 570~1313 s（设计 §4）；超时下限一小时，**不许**更短。
RUN_GATE_MIN_TIMEOUT_S = 3600.0
#: 失败消息里带末尾多少行 —— 40 行输出时要能看见最后一段。
RUN_GATE_TAIL_LINES = 20


def slot_count(cpu_count: int, avail_gb: float) -> int:
    """槽位数 = `min(cpu // 4, (avail_gb - 3) // 4)`，**下限 1**。

    判据（卡 E42 §2.2）：4 vCPU / 15.5 GB ⇒ 1；8 vCPU / 16 GB ⇒ 2；8 vCPU / 6 GB ⇒ 1
    （内存那条把 0 压成 1 —— 一台能跑门禁的机器至少给一个槽，不给 0 等于「永远不跑」）。
    """
    if avail_gb is None:
        # ★ 卡 E120：判不了就明说 —— 槽位数既不是 0 也不是 1，调用方自己决定跳不跳。
        raise ValueError("可用内存判不了（None）⇒ 槽位数算不出来：不许当 0 块，也不许当 1 槽")
    cpu_slots = int(cpu_count) // CPU_PER_SLOT
    mem_slots = int((float(avail_gb) - MIN_AVAIL_GB) // MEM_PER_SLOT_GB)
    return max(1, min(cpu_slots, mem_slots))


def port_base_for(slot: int) -> int:
    """第 `slot` 槽的端口段起点：`9200 + slot * 40`（`slot` 从 0 起）。"""
    if int(slot) < 0:
        raise ValueError(f"槽号不能为负：{slot}")
    return POOL_PORT_BASE + int(slot) * SLOT_PORT_STRIDE


def port_segment(slot: int) -> tuple[int, int]:
    """第 `slot` 槽的端口段 `[起, 止]`（闭区间，长度 = 步长）。"""
    base = port_base_for(slot)
    return base, base + SLOT_PORT_STRIDE - 1


def port_segments(count: int) -> list[tuple[int, int]]:
    """前 `count` 个槽的端口段 —— 钉子核「两两不重叠」直接读它。"""
    if int(count) < 1:
        raise ValueError(f"槽数必须 ≥ 1：{count}")
    return [port_segment(i) for i in range(int(count))]


def port_base_of_slot_choice(slots: list[int]) -> dict[int, int]:
    """`{槽号: 端口段起点}` —— 给落地链挑段用。"""
    return {int(s): port_base_for(int(s)) for s in slots}


# ---------------------------------------------------------------- 时间 / 路径小工具
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _default_queue_path(root: pathlib.Path | None = None) -> pathlib.Path:
    env = os.environ.get("TF_GATE_POOL_QUEUE", "").strip()
    if env:
        return pathlib.Path(env)
    base = pathlib.Path(root) if root is not None else pathlib.Path(__file__).resolve().parents[1]
    return base.joinpath(*QUEUE_REL)


def _empty_state() -> dict:
    return {"head": None, "waiting": [], "done": [], "slots": {}}


def _norm_state(raw: object) -> dict:
    data = raw if isinstance(raw, dict) else {}
    head = data.get("head")
    out = _empty_state()
    out["head"] = head if isinstance(head, dict) else None
    for key in ("waiting", "done"):
        value = data.get(key)
        out[key] = [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
    slots = data.get("slots")
    out["slots"] = {str(k): v for k, v in slots.items()
                    if isinstance(v, dict)} if isinstance(slots, dict) else {}
    return out


def _validate_queue_text(text: str) -> None:
    """判「这份队列快照还能不能当 lastgood」：解得开且顶层是对象（卡 A330）。"""
    if not isinstance(json.loads(text), dict):
        raise ValueError("队列快照顶层应是对象")


def _write_holder(fd: int) -> None:
    """把「谁持着锁」写进锁文件（`<pid>@<host>`）—— 只为「等不到」的文案能点名。

    ★ 写不进去不算失败：锁已经建成了，「有人占着」的判据是文件存在，不是内容。
    """
    with contextlib.suppress(OSError):
        os.write(fd, f"{os.getpid()}@{socket.gethostname()}".encode())


def _lock_holder(lock: pathlib.Path) -> str:
    """锁文件里写的持有者；读不到 / 没写 ⇒ 明说读不到（不许猜，也不许省掉这一段）。

    ★ 与 `tools/pool/ledger.py:37-40`「不读别人的锁文件内容」的差别是时点：这里只在
      已经放弃之后读一次（不再重试、不再动这个文件），最坏只是读到空或抛 OSError。
    """
    try:
        text = lock.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return f"读不到持有者（{type(exc).__name__}）"
    if not text:
        return "读不到持有者（锁文件里没写）"
    return f"持有者 {text}"


# ---------------------------------------------------------------- 队列（单写者 + 原子写）
class GatePoolError(RuntimeError):
    """门禁池操作的失败基类 —— 「读不到」与「等不到锁」同族，但不许互相冒充。

    ★ 卡 E139：两族异常都从这里派生，钉子里用元组断言就能同时咬住「同一族」这件事。
    """


class GatePoolUnreadable(GatePoolError):  # noqa: N818 —— 名字就是判据原文「读不到」
    """队列**读不到**（权限 / 目录冒充 / 坏 JSON）—— 与「队列是空的」不是一回事。

    ★ 卡 E120：四种形态原来都洗成 _empty_state()（与真·空队列逐字相同）；
      后果不是少印一行，是 submit 把空状态写回盘、覆盖掉还在跑的那一条。
    """


class GatePoolBusy(GatePoolError):  # noqa: N818 —— 名字就是判据原文「等不到」
    """队列短锁等不到（到期，或建锁一直被拒）—— 失败关闭，绝不绕过去无锁写。

    ★ 卡 E139：改前 `locked()` 等满就 `break` 出去照样读改写 ⇒ 后写者整份盖掉先写者。
      实测 `PoolQueue(path, timeout=0.0)` + 12 线程 x 5 轮 = 60 次 submit 只剩 5 行；
      全量门禁里红成「丢了行：只看到 [...]」（`gates/diag/land-E128g.log`）。
    ★ 本卡推翻 卡 E55 `复盘/卡/卡E55-门禁池队列锁等待过紧.md:48-49` 那条
      「不许把『等不到就往下写』改成『等不到就抛异常』」：记账队列一旦被并发写坏，
      记账本身就是错的。
    ★ 文案三要素（缺一即红）：等了多久（数值来自实参，不硬编码）/ 锁文件完整路径 /
      谁可能还持着（锁文件里的 `pid@host`；读不到就明说读不到）。
    """


@dataclass
class PoolQueue:
    """云机门禁队列（`gates/diag/gate-pool-queue.json`）。

    ★ **单写者**：`submit` 只在**没有可并行槽**时把条目放进 `waiting`；同一槽上的第二次
      提交一定排队（钉子 `test_same_slot_submissions_queue`）。
    ★ **原子替换**：每次读改写后 `tmp + os.replace`，别的进程读到的永远是完整的一份。
    """

    path: pathlib.Path
    timeout: float = LOCK_WAIT_S

    # ······························································ 读 / 写
    def load(self) -> dict:
        r"""读队列：**文件不存在 ⇒ 空状态**（还没人租，合法）；**读不到 / 坏 JSON ⇒ 抛**。

        ★ 卡 E120：这两种原来走同一个 except (OSError, json.JSONDecodeError)，都返回
        _empty_state() —— 与「队列真的是空的」逐字相同，调用方无从分辨，于是 submit
        把空状态写回盘、覆盖掉还在跑的那一条（两趟占同一槽 + 同一端口段）。
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _empty_state()
        except OSError as exc:
            raise GatePoolUnreadable(
                f"队列读不到（{type(exc).__name__}: {exc}）⇒ 判不了，不许当空队列：{self.path}"
            ) from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GatePoolUnreadable(
                f"队列不是合法 JSON（{exc}）⇒ 判不了，不许当空队列：{self.path}"
            ) from exc
        return _norm_state(raw)

    def save(self, state: dict) -> None:
        """原子写；旧的好就先顶成 `.bak`（卡 A330：`lastgood.write_atomic`）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(_norm_state(state), ensure_ascii=False, indent=2) + "\n"
        lastgood.write_atomic(self.path, body, validate=_validate_queue_text)

    @contextlib.contextmanager
    def locked(self, timeout: float | None = None):
        """读改写期间的短锁（`<队列>.lock`，`O_CREAT|O_EXCL`）；等不到就失败关闭。

        与 `tools/pool/queue.py::_locked` 同一套语义：这把锁保护的是「读 → 改 → 写回」
        这几毫秒，**不是**门禁锁。

        ★ 卡 E139（推翻 E55 的「等满就往下写」）：到期仍建不出锁 ⇒ 抛 `GatePoolBusy`，
        一个字节都不写。改前是 `break` 出去照样读改写，实测 `timeout=0.0` 下 12 线程
        并发 submit 只剩 1 行 —— 后写者把先写者的行整份盖掉。
        ★ 建锁的 `PermissionError` 与 `FileExistsError` 走同一条路：Windows 上持有者
        正在 `unlink()` 的那一瞬，`O_CREAT|O_EXCL` 撞的是 `PermissionError
        [WinError 5]`（锁文件 churn 3 秒里实测 2.46%），语义与「有人占着」相同。
        """
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        wait = self.timeout if timeout is None else float(timeout)
        t0 = time.time()
        fd = None
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                _write_holder(fd)  # 建锁之后才知道是谁 —— 只给「等不到」的文案用，不抛
                break
            except (FileExistsError, PermissionError) as exc:
                # ★ 卡 E139：PermissionError 不是「坏了」，是「这一刻有人占着」（见 docstring）。
                if time.time() - t0 >= wait:
                    raise GatePoolBusy(
                        f"等不到队列短锁（等了 {wait:g}s）：{lock}；{_lock_holder(lock)}。"
                        f"最后一次建锁失败（{type(exc).__name__}: {exc}）。"
                        "别绕过去无锁写 —— 稍后重试，或先查清谁占着这把锁。"
                    ) from exc
                time.sleep(0.02)
        try:
            yield
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:  # 句柄关不掉要说，但别盖掉业务异常
                    print(f"  [队列] 关锁句柄失败（{type(exc).__name__}: {exc}）：{lock}",
                          flush=True)
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    # ★ 卡 E120：原来 suppress 掉就跑 ⇒ 锁文件留着，之后 submit 等满
                    #   LOCK_WAIT_S 再**无锁写**（P10c 实测）。还锁失败必须响。
                    print(f"  [队列] 还锁失败（{type(exc).__name__}: {exc}）⇒ 这把锁会留在盘上，"
                          f"下一次读改写要等满 {wait:.0f}s，仍拿不到就失败关闭"
                          f"（不再无锁写）：{lock}", flush=True)

    # ······························································ 槽 / 提交
    @staticmethod
    def busy_slots(state: dict) -> set[int]:
        """正在占槽的槽号（`waiting` 里的条目不算 —— 它们还没上槽）。"""
        used: set[int] = set()
        running = [x for x in state.get("waiting", []) if x.get("state") == "running"]
        head = state.get("head")
        if isinstance(head, dict) and head.get("state") == "running":
            running.append(head)
        for row in running:
            try:
                used.add(int(row.get("slot")))
            except (TypeError, ValueError) as exc:
                # ★ 卡 E120：原来 suppress 掉就跳过 ⇒ 那个槽被当成空闲（可两趟同槽）。
                raise GatePoolUnreadable(
                    f"队列里一条 running 行的槽号读不懂（slot={row.get('slot')!r}，"
                    f"commit={row.get('commit')!r}）⇒ 判不了哪个槽占着：不许当它没占槽"
                ) from exc
        return used

    @classmethod
    def free_slots(cls, state: dict, n_slots: int) -> list[int]:
        """空闲槽（`0..n_slots-1` 里没被占的），按槽号升序。"""
        busy = cls.busy_slots(state)
        return [s for s in range(int(n_slots)) if s not in busy]

    def submit(self, entry: dict, *, n_slots: int = 1) -> tuple[dict, bool]:
        """提交一次门禁请求。返回 `(队列行, 是否排队)`。

        - 同一 `commit` 已在队列里 ⇒ **幂等**：原样返回那一行（`queued=False` 表示它已上槽）。
        - 有空闲槽 ⇒ 直接上槽（`state="running"`，`head` 空则当队首）。
        - 没有空闲槽 ⇒ 进 `waiting`（`state="waiting"`，`queued=True`）—— **同一槽的并发
          提交被排队，不是并行**。
        """
        commit = str(entry.get("commit") or "")
        if not commit:
            raise ValueError("提交门禁必须带 commit（找回结果靠它）")
        with self.locked():
            state = self.load()
            existing = self.find(commit, state=state)
            if existing is not None:
                return existing, existing.get("state") == "waiting"
            row = dict(entry)
            row.setdefault("at", _now())
            row.setdefault("state", "")
            free = self.free_slots(state, n_slots)
            want = row.get("slot")
            if free and (want is None or int(want) in free):
                slot = int(want) if want is not None else free[0]
                row["slot"] = slot
                row["port_base"] = port_base_for(slot)
                row["state"] = "running"
                if state["head"] is None:
                    state["head"] = row
                else:
                    state["waiting"].append(row)
                self.save(state)
                return row, False
            row.pop("slot", None)
            row["state"] = "waiting"
            state["waiting"].append(row)
            self.save(state)
            return row, True

    def promote(self, *, n_slots: int) -> dict | None:
        """把 `waiting` 里最前面那条放到空出来的槽上；没得放 / 没空槽 ⇒ None。"""
        with self.locked():
            state = self.load()
            if not state["waiting"]:
                return None
            free = self.free_slots(state, n_slots)
            if not free:
                return None
            row = next((x for x in state["waiting"] if x.get("state") == "waiting"), None)
            if row is None:
                return None
            row["slot"] = free[0]
            row["port_base"] = port_base_for(free[0])
            row["state"] = "running"
            row["at"] = _now()
            if state["head"] is None:
                state["head"] = row
                state["waiting"] = [x for x in state["waiting"] if x is not row]
            self.save(state)
            return row

    def mark_done(self, commit: str, *, ok: bool, rev: str, host: str = "",
                  result_dir: str = "", seconds: float = 0.0,
                  port_base: int | None = None) -> dict:
        """把一条标成 `done` —— **必须带 `ok / rev / port_base`**（判据 1）。

        `port_base` 不给就沿用上槽时算的那一段；连那段都没有 ⇒ 抛 ValueError
        （「done 行没有端口段」等于结果对不上是哪一槽的）。
        """
        key = str(commit)
        with self.locked():
            state = self.load()
            row = self.find(key, state=state)
            if row is None:
                raise KeyError(f"队列里没有 commit={key} 的请求（别凭空写 done 行）")
            row["state"] = "done"
            row["done_at"] = _now()
            row["ok"] = bool(ok)
            row["rev"] = str(rev)
            row["host"] = str(host)
            row["result_dir"] = str(result_dir)
            row["seconds"] = round(float(seconds), 2)
            if port_base is None:
                port_base = row.get("port_base")
            if port_base is None:
                raise ValueError(f"commit={key} 的 done 行没有 port_base（对不上是哪一槽）")
            row["port_base"] = int(port_base)
            if state["head"] is row:
                state["head"] = None
            state["waiting"] = [x for x in state["waiting"] if x is not row]
            state["done"].append(row)
            self.save(state)
            return row

    # ······························································ 查找（断连可续）
    def find(self, commit: str, *, state: dict | None = None) -> dict | None:
        """按 `commit` 找回这一趟（`done` 优先，然后 running/waiting）。

        ★ 卡 E42 §2.2「断连可续」：本机 ssh 断了不影响远端继续；重连后**只按 commit**
          找回结果（不按下标、不按 task —— 一次重试会换 task 但 commit 不变）。
        """
        key = str(commit)
        st = self.load() if state is None else state
        rows: list[dict] = ([*st.get("done", []), *st.get("waiting", [])]
                            + ([st["head"]] if st.get("head") else []))
        for row in rows:
            if str(row.get("commit") or "") == key:
                return row
        return None

    def done_row(self, commit: str) -> dict | None:
        """`done` 里的那一行（没有 ⇒ None）。"""
        row = self.find(commit, state=self.load())
        return row if row and row.get("state") == "done" else None


# ---------------------------------------------------------------- 槽锁
def slot_lock_path(lock_dir: pathlib.Path, slot: int) -> pathlib.Path:
    """第 `slot` 槽的锁文件：`gates/diag/gate-pool-slot<n>.lock`。"""
    if int(slot) < 0:
        raise ValueError(f"槽号不能为负：{slot}")
    return pathlib.Path(lock_dir) / f"gate-pool-slot{int(slot)}.lock"


def _lock_age(path: pathlib.Path, now: float | None = None) -> float:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0
    return max(0.0, (time.time() if now is None else float(now)) - mtime)


def acquire_slot_lock(lock_dir: pathlib.Path, slot: int, *, card: str,
                      now: float | None = None,
                      stale_after: float = DEFAULT_STALE_AFTER,
                      timeout: float = 0.0) -> bool:
    """抢槽锁。语义与 `gates/diag/gate_lock.py` 同族：`O_CREAT|O_EXCL` 建文件，
    文件 mtime 旧于 `stale_after` ⇒ 视为陈旧、可清掉重抢；`timeout` 秒内抢不到 ⇒ False。
    """
    path = slot_lock_path(lock_dir, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    warned = False
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _lock_age(path, now) >= stale_after:
                try:
                    path.unlink()
                    continue
                except OSError as exc:
                    # ★ 卡 E120：原来 suppress 掉就 continue ⇒ 撞回 FileExistsError ⇒
                    #   无出口死循环，timeout 形同不存在（P15 实测 timeout=0.5 卡了 8 s）。
                    if not warned:
                        warned = True
                        print(f"  [池] 槽 {slot} 的锁陈旧（{_lock_age(path, now):.0f}s）却删不掉"
                              f"（{type(exc).__name__}: {exc}）⇒ 判不了是谁的锁：{path}",
                              flush=True)
            if time.time() - t0 >= float(timeout):
                return False
            time.sleep(0.02)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"card": card, "slot": int(slot), "pid": os.getpid(), "at": _now()},
                      fh, ensure_ascii=False)
        return True


def release_slot_lock(lock_dir: pathlib.Path, slot: int) -> bool | str:
    """还槽锁 —— **三态**（卡 E120）："no-lock" 本来没锁 / True 真删掉了 / False 删不掉。

    ★ 原来 except OSError: return False 把「本来没锁」与「删不掉」压成同一个 False，
      而调用方（run_cloud_gate 的 finally）连返回值都没接 ⇒ 锁可能一直留在盘上。
    """
    path = slot_lock_path(lock_dir, slot)
    try:
        path.unlink()
    except FileNotFoundError:
        return "no-lock"
    except OSError as exc:
        print(f"  [池] 还槽 {slot} 的锁失败（{type(exc).__name__}: {exc}）"
              f"⇒ 这个槽在别人眼里还占着：{path}", flush=True)
        return False
    return True


# ---------------------------------------------------------------- 回传校验（五条）
def base_drift_category(
    payload_rev: str,
    expected_rev: str,
    payload: dict | None = None,
    *,
    root: pathlib.Path | str | None = None,
    **providers: object,
) -> tuple[str, list[str], str]:
    """① rev 这一条与复核侧**共用**分类器（`tools/gate_base.py`，卡 E123）。

    云侧口径比本机严：**只有 MATCH 放行**。LEDGER_ONLY（基点是真祖先、只差台账）也照记
    —— 云机跑的必须是这一笔的父提交；读数写清差在哪、为什么不算。
    """
    data = payload if isinstance(payload, dict) else {}
    taken: dict[str, object] = dict(gate_base.providers(root)) if root is not None else {}
    taken.update(providers)
    return gate_base.gate_base_drift(
        str(payload_rev or ""), str(expected_rev or ""),
        sealed_at=str(data.get("sealed_at") or ""
        ), **taken,  # type: ignore[arg-type]
    )


def parse_pytest_passed(log_text: str) -> int:
    r"""从 `pytest.log` 里取 `N passed`（取**最后**一条；没有 ⇒ 0）。

    `run_gates` 的 pytest 门输出末尾是 `3303 passed, 1513 warnings in 270.28s (0:04:30)`
    这一形（`gates/last.json` 的 pytest summary 同形）。取不到就是 0 —— 调用方按
    「0 < 95%」判红（**不许**默认当通过）。
    """
    import re

    last = 0
    for match in re.finditer(r"(\d+)\s+passed", log_text or ""):
        last = int(match.group(1))
    return last


def validate_cloud_return(
    payload: dict,
    *,
    expected_rev: str,
    expected_doors: list[str] | tuple[str, ...],
    pytest_passed: int,
    pytest_total: int,
    workspace_clean: bool,
    expect_host: str = "",
    **rev_providers: object,
) -> list[str]:
    r"""云机 `last.json` 回传的**五条 fail-closed 校验**（卡 E42 §2.3 逐条）。

    返回问题清单；**空列表 = 五条全过**。任一条不满足 ⇒ 调用方判红，不许当成功。

    ① `rev == <卡树基点提交>`（云机跑的是不是这一笔的父提交）
    ② `ok is True` 且门数/门名 == 该档应有的那一批（A327 `required_profiles()` 派生）
    ③ `host` 存在且非空（证明真在云机跑的，不是本地冒名）；给了 `expect_host` 还要一致
    ④ `pytest.log` 的 `N passed` ≥ 全量的 95%（防「跑了个子集当全量」）
    ⑤ 云机这一趟**开跑前**清树步确实走完（`run_gate.sh` 2/5 的 `checkout -f` +
       `clean -xfdq`；证据是回传输出里有 3/5 以后的段横幅）。**跑后**工作区必脏
       （补丁已应用），本判据**不**声称跑后干净。
    """
    problems: list[str] = []
    data = payload if isinstance(payload, dict) else {}

    # ① rev == 父提交（分类器只放行 MATCH；LEDGER_ONLY 也记，但把读数说清楚）
    got_rev = str(data.get("rev") or "")
    state, _rows, reading = base_drift_category(got_rev, expected_rev, data, **rev_providers)
    if state != gate_base.MATCH:
        problems.append(f"① rev 对不上：last.json.rev={got_rev or '(空)'}"
                        f" ≠ 期望父提交 {expected_rev or '(空)'} —— {reading}")

    # ② ok + 门数/门名
    want = [str(x) for x in expected_doors]
    rows = data.get("gates") or []
    got = [str(g.get("name")) for g in rows if isinstance(g, dict)]
    not_run = [str(x) for x in (data.get("not_run") or [])]
    if data.get("ok") is not True:
        problems.append(f"② ok 不是 True（last.json.ok={data.get('ok')!r}）")
    if sorted(got) != sorted(want):
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        problems.append(f"② 门数对不上：应有 {len(want)} 道（required_profiles 派生），"
                        f"last.json 只有 {len(got)} 道；少 {missing}；多 {extra}")
    if not_run:
        problems.append(f"② 有门 not_run（未验证 ≠ 通过）：{not_run}")

    # ②′ 卡 E63（T-AG521）：空真 / 零阻断门 / 未验证 / 复用来源 —— 与本地尺子、落地链
    #    调**同一份**判据（`tools/gate_verdict.py`）。这里 `check_host=False`：
    #    ③ 比得更严（非空 + 等于这台云机），别拿两份 host 判据互相打架。
    for one in gate_verdict.judge(data, check_host=False).problems:
        problems.append(f"②′ {one}")

    # ③ host 字段
    host = str(data.get("host") or "")
    if not host.strip():
        problems.append("③ host 字段缺失/为空（证明不了是云机跑的）")
    elif expect_host and host.strip() != str(expect_host).strip():
        problems.append(f"③ host 不是这台云机：last.json.host={host!r} ≠ {expect_host!r}")

    # ④ pytest 用例数 ≥ 全量的 95%
    total = int(pytest_total or 0)
    passed = int(pytest_passed or 0)
    if total <= 0:
        problems.append("④ 不知道全量用例数（没有基线）⇒ 无法核 95%，按红")
    elif passed < total * PASSED_MIN_RATIO:
        need = int(total * PASSED_MIN_RATIO)
        problems.append(f"④ pytest 用例数不够：{passed} passed < 全量 {total} 的 95%"
                        f"（至少要 {need}）—— 像「跑了个子集当全量」")

    # ⑤ 云机工作区干净
    if workspace_clean is not True:
        problems.append("⑤ 云机开跑前清树未确认（回传里没有 3/5 以后的段横幅）")
    return problems


def parse_instant(text: str) -> datetime.datetime | None:
    r"""把 ISO-8601 字符串解成「瞬间」；解不出就 None（**不猜、不补默认值**）。

    带偏移（`+08:00` / `Z`）的原样保留；不带偏移的按「与本机同一墙上时钟」处理 ——
    本仓的 `gates/last.json.at` 就是云机本地时间写的朴素串，而云机与本地同一时区
    （2026-10-29 实测：云机产物 `at=2026-10-29T00:31:14`，本地文件 mtime `00:31:19`）。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


def product_is_from_this_run(
    payload: dict,
    *,
    started_at: str,
    shipped_text: str = "",
    seed_text: str = "",
) -> tuple[bool, str]:
    r"""回传的 `last.json` 是不是**这一趟**跑出来的（卡 E66 · T-AG526）。

    三条独立证据，任一不过即判「不新鲜」（返回 `(False, 原因)`）：

    ① `at` 能解出、且不早于 `started_at`（本趟 4/5 的起跑时刻）；
    ② `at` **缺失/解不出 ⇒ 直接判不新鲜**（fail closed —— 判不出来的时候不许说没事）；
    ③ 给了 `seed_text` 时，产物**不许与播种源逐字相同**。

    ③ 是最硬的一条：`run_gate.sh` 的 2/5 会把上一趟的绿播种到云机同一个路径上，
    云机中途死掉时 5/5 搬回来的就是那份播种 —— 它与本机 `gates/diag/seed-<卡>/last.json`
    **逐字节相同**。这条判据不依赖任何时钟，也不依赖两台机器的表走得准不准。
    """
    data = payload if isinstance(payload, dict) else {}
    at_raw = str(data.get("at") or "")
    at = parse_instant(at_raw)
    if at is None:
        return False, f"② 产物没有可解的 at（at={at_raw!r}）⇒ 证明不了是这一趟写的"
    start = parse_instant(started_at)
    if start is None:
        return False, f"② 起跑时刻不可解（started_at={started_at!r}）⇒ 判不了"
    if at.tzinfo is not None and start.tzinfo is None:
        start = start.replace(tzinfo=at.tzinfo)
    elif start.tzinfo is not None and at.tzinfo is None:
        at = at.replace(tzinfo=start.tzinfo)
    if at < start:
        return False, (f"① 产物 at={at_raw} 早于本趟起跑 {started_at}"
                       f" ⇒ 这是上一趟留下的读数")
    if seed_text and shipped_text and shipped_text.strip() == seed_text.strip():
        return False, "③ 产物与播种源逐字相同 ⇒ 云机没写新读数（这趟没跑出来）"
    return True, ""


def gates_on_line(*, gate_on: str, host: str = "") -> str:
    """落地笔的 `Gates-on:` 行（卡 E42 §2.1）——`cloud@<host>` 或 `local`。"""
    if gate_on == "cloud":
        return f"Gates-on: cloud@{host or '(未知云机)'}"
    return "Gates-on: local"


def check_gates_on_trailer(body: str, *, expect: str) -> str:
    r"""`Gates-on:` 与实际对不对得上（空串 = 对得上，否则一句问题）。

    规则：必须**恰好一行**；`cloud` 那一支必须带 `@<host>`；`local` 那一支必须是裸 `local`。
    """
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip().startswith("Gates-on:")]
    if len(lines) != 1:
        return f"`Gates-on:` 必须恰好一行，现在 {len(lines)} 行：{lines}"
    got = lines[0].split(":", 1)[1].strip()
    want = expect.split(":", 1)[1].strip()
    if got != want:
        return f"`Gates-on:` 与实际不符：trailer={got!r}，实际={want!r}"
    if got.startswith("cloud") and "@" not in got:
        return f"`Gates-on: cloud` 必须带云机名（cloud@<host>），现在是 {got!r}"
    return ""


# ---------------------------------------------------------------- 基线（用例数）
def baseline_path(root: pathlib.Path) -> pathlib.Path:
    """`gates/diag/pytest_baseline.json` —— 「全量用例数」的落盘基线。"""
    return pathlib.Path(root) / "gates" / "diag" / "pytest_baseline.json"


def read_pytest_baseline(root: pathlib.Path) -> int:
    """读基线（`{"passed": N}`）；读不到 / 坏了 ⇒ 0（调用方判红，不猜）。

    优先级由调用方定：`TF_PYTEST_BASELINE` 环境变量 > 本文件 > 上一趟 `gates/last.json`。
    """
    env = os.environ.get("TF_PYTEST_BASELINE", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            return 0
    try:
        data = json.loads(baseline_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    with contextlib.suppress(TypeError, ValueError):
        return int((data or {}).get("passed") or 0)
    return 0


def write_pytest_baseline(root: pathlib.Path, passed: int, *, rev: str = "") -> None:
    """把这一趟实测的用例数写成基线（只在**五条校验全过**之后调）。"""
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"passed": int(passed), "rev": str(rev), "at": _now()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- run_gate 的失败消息
def _output_tail(text: str, lines: int = RUN_GATE_TAIL_LINES) -> str:
    """输出末尾 `lines` 行（空行不算；空输出给一句话，不留空串）。"""
    rows = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(rows[-lines:]) if rows else "(没有输出)"


def _last_segment(text: str) -> str:
    """stdout 里**最后一条** `=== N/5 …` 段横幅（脚本用它指认卡在哪一段）。"""
    rows = [line.strip() for line in str(text or "").splitlines()
            if line.strip().startswith("=== ") and "/5" in line]
    return rows[-1] if rows else "(没有段横幅)"


def _failure_text(rc: int, output: str) -> str:
    return (f"云门禁没跑成（run_gate.sh 退 {rc}，卡在 {_last_segment(output)}）：\n"
            f"{_output_tail(output)}")


def _read_back(tree: pathlib.Path, rc: int,
               output: str) -> tuple[dict, dict[str, str]]:
    """读回传：`<tree>/gates/last.json` + `<tree>/gates/logs/*.log`。

    ★ exit 9（产物陈旧）时脚本会**主动删掉** `last.json` —— 所以 rc 不是 0/1 的分支
      根本不该走到这里；这里读不到就抛，绝不拿上一趟的残留冒充这一趟。
    """
    last = pathlib.Path(tree) / "gates" / "last.json"
    try:
        payload = json.loads(last.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CloudUnreachable(
            f"云门禁退 {rc} 但卡树里没有可读的 gates/last.json"
            f"（{type(exc).__name__}: {exc}）：\n{_output_tail(output)}") from exc
    if not isinstance(payload, dict):
        raise CloudUnreachable(
            f"回传的 gates/last.json 不是对象（{type(payload).__name__}）")
    logs: dict[str, str] = {}
    log_dir = pathlib.Path(tree) / "gates" / "logs"
    if log_dir.is_dir():
        for path in sorted(log_dir.glob("*.log")):
            try:
                logs[path.name] = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                # ★ 卡 E120：原来 continue ⇒ 读不到的那份静默消失，而 _write_back 见 logs
                #   里没有它就不写也不删 ⇒ 卡树里留上一趟的旧日志冒充这一趟。
                print(f"  [回传] 这份日志读不到（{type(exc).__name__}: {exc}）"
                      f"⇒ 不算这一趟的产物：{path}", flush=True)
    return payload, logs


# ---------------------------------------------------------------- 传输（唯一碰网络的一层）
class CloudUnreachable(RuntimeError):  # noqa: N818 —— 名字就是判据原文「云机不可达」
    """云机不可达 —— 落地链据此**退 2 并明说**，绝不回落到本机。"""


@dataclass
class SshTransport:
    """真云机传输：ssh + scp（`scripts/cloud/run_gate.sh` 的口径）。

    ★ 单测**一律**注入假 transport（假 `host` / 假回传数据）；本类不在任何钉子路径上。
    """

    host: str
    user: str = "administrator"
    key: str = str(pathlib.Path.home() / ".ssh" / "id_ed25519_cloud")
    repo: str = "C:/eng"
    #: 主仓根（可选注入；不给就 `git -C <tree> rev-parse --git-common-dir` 现算）。
    main_root: pathlib.Path | str | None = None
    #: `subprocess.run` 注入点（**只许单测**；不给就是真的 `subprocess.run`）。
    runner: Callable[..., subprocess.CompletedProcess] | None = None

    def _ssh(self, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
        cmd = ["ssh", "-i", self.key, "-o", "BatchMode=yes",
               "-o", f"ConnectTimeout={int(timeout)}",
               f"{self.user}@{self.host}", *args]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout + 5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def reachable(self, timeout: float = 8.0) -> bool:
        """云机可达吗 —— 先 TCP 22，再问一句 python 版本（省得「端口开着但机没起」）。"""
        if not self.host:
            return False
        try:
            with socket.create_connection((self.host, 22), timeout=timeout):
                pass
        except OSError:
            return False
        try:
            done = self._ssh("python -V", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0

    def _run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        runner = self.runner or subprocess.run
        return runner(argv, **kwargs)

    def _main_root(self, tree: pathlib.Path) -> pathlib.Path:
        """主仓根 = `--git-common-dir` 的父目录（worktree 共用同一个 `.git`）。"""
        if self.main_root is not None:
            return pathlib.Path(self.main_root)
        done = self._run(
            ["git", "-C", str(tree), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        common = str(getattr(done, "stdout", "") or "").strip()
        if int(getattr(done, "returncode", 1)) != 0 or not common:
            raise CloudUnreachable(
                f"算不出主仓根（git -C {tree} rev-parse 退 "
                f"{getattr(done, 'returncode', '?')}）⇒ run_gate.sh 找不到 scripts/cloud")
        return pathlib.Path(common).parent

    def _gate_env(self) -> dict[str, str]:
        """`run_gate.sh` 需要的环境：连接地址 + `TF_PROJECTS_TOML`；**不注入**模型注册表。"""
        env = dict(os.environ)
        env["CLOUD_HOST"] = f"{self.user}@{self.host}"
        projects = str(env.get("TF_PROJECTS_TOML") or "").strip()
        if not projects:
            raise CloudUnreachable(
                "没有配置 `TF_PROJECTS_TOML`（run_gate.sh 会因缺它退 2）⇒ 云门禁没跑成")
        env["TF_PROJECTS_TOML"] = projects
        # ★ 卡 E82：绝不把本机的模型注册表带给云机（注了会让 5 条用例集体红）。
        env.pop("TF_MODEL_REGISTRY", None)
        return env

    def run_gate(self, entry: dict, tree: pathlib.Path) -> dict[str, Any]:
        r"""在云机上跑一趟门禁并回传 `last.json` + `gates/logs/*.log`。

        薄封装 `scripts/cloud/run_gate.sh`：**不重写**五段流程（脚本固化 26 条静态钉子）。

        · argv = `bash scripts/cloud/run_gate.sh <Path(tree).name> <port_base>` ——
          第 1 个位置参数是 `.wt` 下的**目录名**（历史卡号 ≠ 目录名），第 2 个是槽端口段；
        · cwd = 主仓根（脚本里的 `scripts/run_gates.py`、`.wt/$card`、seed 目录都相对它）；
        · rc 0/1 = **跑到了**（1 = 门红）⇒ 正常返回三键；rc 2..9 = 没跑成 ⇒ 抛。

        ★ `workspace_clean` 的可用证据只有「脚本走到 3/5 以后」——那说明 2/5 的
          `checkout -f` + `clean -xfdq`（开跑前清树）成功了。**跑后**工作区必脏
          （补丁已应用），本类不声称「跑完还干净」；跑后残留仍未验证（设计 §7）。
        """
        tree = pathlib.Path(tree)
        if not str(self.host or "").strip():
            raise CloudUnreachable(
                "没有配置云机连接地址（SshTransport.host 为空）⇒ 云门禁没跑成")
        port_base = str(entry.get("port_base") or "").strip()
        if not port_base:
            raise CloudUnreachable("entry 缺 port_base（run_gate.sh 第 2 个参数没给）")
        env = self._gate_env()
        root = self._main_root(tree)
        try:
            budget = float(entry.get("timeout") or 0.0)
        except (TypeError, ValueError):
            budget = 0.0
        timeout = max(RUN_GATE_MIN_TIMEOUT_S, budget)
        argv = ["bash", "scripts/cloud/run_gate.sh", tree.name, port_base]
        try:
            proc = self._run(
                argv, cwd=str(root), env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise CloudUnreachable(
                f"云门禁超时（{timeout:.0f}s 还没回来）⇒ 云门禁没跑成") from exc
        except OSError as exc:
            raise CloudUnreachable(
                f"起不了 scripts/cloud/run_gate.sh（{type(exc).__name__}: {exc}）") from exc

        output = "\n".join(x for x in (proc.stdout, proc.stderr) if x)
        rc = int(proc.returncode)
        if rc not in (0, 1):
            # 2..9 = 没跑成（缺配置 / 缺 seed / 应用补丁失败 / HEAD 不对 / pip / 陈旧）。
            raise CloudUnreachable(_failure_text(rc, output))
        payload, logs = _read_back(tree, rc, output)
        reached_clean = any(marker in output for marker in
                            ("=== 3/5", "=== 4/5", "=== 5/5"))
        return {"payload": payload, "logs": logs, "workspace_clean": reached_clean}


@dataclass
class FakeTransport:
    """假云机（**只许单测**）：`reachable` / 回传数据全从一份 JSON 来。

    卡 E42 判据 2 明写「用假的 `host` / 假回传数据做单测」—— 真云机实测由主控做。
    JSON 形状（`TF_GATE_CLOUD_FAKE` 指向它）：
    ```json
    {"reachable": true,
     "payload": {"rev": "…", "ok": true, "host": "fake-cloud", "gates": [{"name": "pytest"}]},
     "pytest_log": "3303 passed in 270s", "workspace_clean": true,
     "logs": {"pytest.log": "…"}}
    ```
    `run_gate` 抛 `CloudUnreachable` 当 `reachable` 为假（与真 transport 同一支）。
    """

    data: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | pathlib.Path) -> FakeTransport:
        return cls(data=json.loads(pathlib.Path(path).read_text(encoding="utf-8")))

    def reachable(self) -> bool:
        return bool(self.data.get("reachable", True))

    def run_gate(self, entry: dict, tree: pathlib.Path) -> dict[str, Any]:
        if not self.reachable():
            raise CloudUnreachable("假云机设为不可达（reachable=false）")
        logs = dict(self.data.get("logs") or {})
        if "pytest_log" in self.data and "pytest.log" not in logs:
            logs["pytest.log"] = str(self.data["pytest_log"])
        return {"payload": dict(self.data.get("payload") or {}), "logs": logs,
                "workspace_clean": self.data.get("workspace_clean", True)}


@dataclass
class CloudResult:
    """一趟云门禁的结果（落地链只读它，不自己解释 `last.json`）。"""

    ok: bool
    problems: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    host: str = ""
    pytest_passed: int = 0
    pytest_total: int = 0
    workspace_clean: bool = False
    seconds: float = 0.0
    port_base: int = 0
    slot: int = 0
    logs: dict[str, str] = field(default_factory=dict)


def _write_back(wt: pathlib.Path, payload: dict, logs: dict[str, str]) -> pathlib.Path:
    r"""把云机回传的 `last.json` 与 `gates/logs/*.log` 写进卡树（只读回传，不反向写云机）。

    ★ 卡 E120：回传里**没有**的那份日志要从卡树里删掉 —— 否则上一趟的 pytest.log
      会在原地冒充这一趟（下游 tools/pool/landing.py 与 tools/failure_group.py 正是
      拿它当入口）。原来 if logs: 只在有回传时才建目录写，从不清理。
    """
    gates = pathlib.Path(wt) / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    target = gates / "last.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    log_dir = gates / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    keep = {pathlib.Path(str(name)).name for name in logs}
    for old in sorted(log_dir.glob("*.log")):
        if old.name in keep:
            continue
        try:
            old.unlink()
        except OSError as exc:
            print(f"  [回传] 上一趟的日志删不掉（{type(exc).__name__}: {exc}）"
                  f"⇒ 它会在原地冒充这一趟：{old}", flush=True)
        else:
            print(f"  [回传] 这一趟没有这份日志 ⇒ 删掉上一趟的：{old.name}", flush=True)
    for name, text in logs.items():
        path = log_dir / pathlib.Path(str(name)).name
        path.write_text(str(text), encoding="utf-8", newline="\n")
    return target


def run_cloud_gate(
    *,
    wt: pathlib.Path,
    card: str,
    task: str,
    commit: str,
    transport: Any,
    host: str,
    expected_doors: list[str] | tuple[str, ...],
    expect_host: str = "",
    pytest_total: int,
    queue: PoolQueue,
    n_slots: int = 1,
    lock_dir: pathlib.Path | None = None,
    clock: Callable[[], float] = time.time,
) -> CloudResult:
    r"""编排一趟云门禁：**可达性 → 上槽 → 跑 → 回传 → 五条校验**。

    ★ 云机不可达 ⇒ `CloudUnreachable`（落地链退 2 并明说，**不回落本机**）。
    ★ 同一槽已有请求 ⇒ 进 `waiting`（等前面的完再上槽；本函数**不**并行抢同一槽）。
    ★ 五条校验任一不过 ⇒ `CloudResult.ok=False`，问题清单原样带回（落地链判红）。
    """
    if not host:
        raise CloudUnreachable("没有配置云机（`TF_GATE_CLOUD_HOST`）⇒ 云机不可达，未跑门禁")
    try:
        up = bool(transport.reachable())
    except Exception as exc:  # transport 自己的异常也算不可达（不许把「探不通」当通）
        raise CloudUnreachable(f"云机不可达（探测抛 {type(exc).__name__}: {exc}）") from exc
    if not up:
        raise CloudUnreachable(f"云机 {host} 不可达（TCP 22 / ssh 都没通）⇒ 未跑门禁")

    entry = {"task": task, "card": card, "commit": commit, "host": host}
    try:
        row, queued = queue.submit(entry, n_slots=n_slots)
    except GatePoolUnreadable as exc:
        # ★ 卡 E120：队列读不到就**不许**提交（原来会拿空状态写回盘、覆盖还在跑的那条）。
        raise CloudUnreachable(
            f"云门禁队列读不到 ⇒ 这一趟不能跑（不许当空队列覆盖）：{exc}") from exc
    if queued:
        print(f"  [池] 槽都占着 ⇒ 排到 waiting（共 {len(queue.load()['waiting'])} 条在等）",
              flush=True)
        row = queue.promote(n_slots=n_slots) or row
    slot = int(row.get("slot") or 0)
    port_base = int(row.get("port_base") or port_base_for(slot))
    lock_dir = (pathlib.Path(lock_dir) if lock_dir is not None
                else pathlib.Path(wt) / "gates" / "diag")
    if not acquire_slot_lock(lock_dir, slot, card=card, timeout=0.0):
        print(f"  [池] 槽 {slot} 的锁被占着 ⇒ **停手**（不并行抢同一槽）", flush=True)
        raise CloudUnreachable(f"云机槽 {slot} 的锁被占着（等下一趟或人工收锁）")

    t0 = clock()
    try:
        artifacts = transport.run_gate({**row, "port_base": port_base}, pathlib.Path(wt))
    finally:
        freed = release_slot_lock(lock_dir, slot)
        if freed is False:
            print(f"  [池] ★ 槽 {slot} 的锁没还掉 ⇒ 下一趟会以为它还被占着"
                  f"（人工删掉 {slot_lock_path(lock_dir, slot)}）", flush=True)
    seconds = max(0.0, clock() - t0)

    payload = dict((artifacts or {}).get("payload") or {})
    logs = dict((artifacts or {}).get("logs") or {})
    pytest_log = str(logs.get("pytest.log") or (artifacts or {}).get("pytest_log") or "")
    passed = parse_pytest_passed(pytest_log)
    clean = bool((artifacts or {}).get("workspace_clean"))
    problems = validate_cloud_return(
        payload, expected_rev=commit, expected_doors=expected_doors,
        pytest_passed=passed, pytest_total=int(pytest_total or 0),
        workspace_clean=clean, expect_host=expect_host,
        root=pathlib.Path(wt))
    result = CloudResult(
        ok=not problems, problems=problems, payload=payload,
        host=str(payload.get("host") or ""), pytest_passed=passed,
        pytest_total=int(pytest_total or 0), workspace_clean=clean,
        seconds=round(seconds, 2), port_base=port_base, slot=slot, logs=logs)
    result_dir = str((pathlib.Path(wt) / "gates" / "diag" / "pool" / card).resolve())
    queue.mark_done(commit, ok=result.ok, rev=str(payload.get("rev") or ""),
                    host=result.host or host, result_dir=result_dir,
                    seconds=result.seconds, port_base=port_base)
    if payload:
        _write_back(pathlib.Path(wt), payload, logs)
    return result


#: `python tools/gate_pool.py status|slots` —— 只读自查（运维用；不改任何文件）。
def main(argv: list[str] | None = None) -> int:
    # ★ 卡 E120（问题 8）：三元两支原来写反 —— 形参给了反而取 sys.argv[1:]，
    #   没给则 list(None) 直接炸 ⇒ 进程内 main([...]) 只能拿到帮助 + rc 0。
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("用法：python -X utf8 tools/gate_pool.py status [--root <树>]\n"
              "  status  打印队列（head / waiting / done）与各槽端口段\n"
              "  slots   打印槽位计算：slot_count(cpu, avail_gb)")
        return 0
    root = pathlib.Path(argv[argv.index("--root") + 1]) if "--root" in argv else None
    if argv[0] == "status":
        q = PoolQueue(_default_queue_path(root))
        try:
            state = q.load()
        except GatePoolUnreadable as exc:
            # ★ 卡 E120：原来四形全印一份空队列 + rc 0 ⇒ 运维看不出「读不到」。
            print(f"[读不到] {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"path": str(q.path), "head": state["head"],
                          "waiting": state["waiting"], "done": state["done"]},
                         ensure_ascii=False, indent=2))
        return 0
    if argv[0] == "slots":
        cpu = os.cpu_count() or 1
        try:
            from scripts.run_gates import available_memory_gb  # noqa: PLC0415
            avail = available_memory_gb()
        except Exception as exc:
            # ★ 卡 E120：原来 or 0.0 + except 都印 0.0 —— 那是**编出来的读数**
            #   （真·内存耗尽也是 0.0），人和机器都分不出「量不出来」。
            print(f"cpu={cpu} avail_gb=unknown ⇒ 判不了（读不到可用内存："
                  f"{type(exc).__name__}: {exc}）⇒ 不算槽数", file=sys.stderr)
            return 2
        if avail is None:
            print(f"cpu={cpu} avail_gb=unknown ⇒ 判不了（available_memory_gb() 返回 None，"
                  f"上游口径是「跳过这道闸」）⇒ 不算槽数", file=sys.stderr)
            return 2
        n = slot_count(cpu, float(avail))
        print(f"cpu={cpu} avail_gb={float(avail):.1f} ⇒ {n} 槽；端口段 {port_segments(n)}")
        return 0
    if argv[0] == "check-product-fresh":
        # 卡 E66（T-AG526）：bash 侧只调这一支，不在 shell 里写时间比较。
        rest = argv[1:]
        if not rest:
            print("用法：gate_pool.py check-product-fresh <last.json> "
                  "--started-at <ISO> [--seed <seed.json>]", file=sys.stderr)
            return 2
        target = pathlib.Path(rest[0])
        started = rest[rest.index("--started-at") + 1] if "--started-at" in rest else ""
        seed = pathlib.Path(rest[rest.index("--seed") + 1]) if "--seed" in rest else None
        try:
            shipped_text = target.read_text(encoding="utf-8")
            payload = json.loads(shipped_text)
        except (OSError, ValueError) as exc:
            print(f"[stale] 读不出产物：{exc}", file=sys.stderr)
            return 3
        seed_text = ""
        if seed is not None:
            try:
                seed_text = seed.read_text(encoding="utf-8")
            except OSError as exc:
                # ★ 卡 E120：原来吞成空串 ⇒ ③（与播种源逐字相同）整条短路 ⇒
                #   **证据越不可得，结论越绿**（P3 实测 A 判 stale、B 判 fresh）。
                print(f"[stale] 播种源读不到（{type(exc).__name__}: {exc}）"
                      f"⇒ 判不了是不是这一趟：{seed}", file=sys.stderr)
                return 3
        fresh, why = product_is_from_this_run(
            payload, started_at=started, shipped_text=shipped_text, seed_text=seed_text)
        if not fresh:
            print(f"[stale] {why}", file=sys.stderr)
            return 3
        print(f"[fresh] at={payload.get('at')} ≥ {started}")
        return 0
    print(f"未知子命令：{argv[0]}（只认 status / slots / check-product-fresh）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
