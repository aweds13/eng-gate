r"""合并队列：**单写者** + 投机预检（卡 E5 · `T-AG447`）。

为什么有它
----------
落地链 ④–⑦（拿锁 → 门禁 → 封存 → 提交 → ff 合流）是**单写者**段：两笔同时进来，
后到的那笔会在 `git merge --ff-only` 那一刻发现「主树已经前进」⇒ rebase、重跑、
甚至白烧一趟门禁。而 ①②③（迁树 → 文书 → sync_counts）与 ③″ 快预检**不占**这个
单写者段，可以**并行做**。

于是：每笔落地先 `enqueue` 拿一个位置；队首直接干，其余继续做自己的 ①②③，
到 ④ 之前再 `wait_turn`。这样「白跑门禁」只可能发生在**投机那部分**，而投机部分
（③″ 快预检，十几秒）在**变队首**时会核对基点，变了就重跑（`respec_required`）——
**投机结果不许复用**。

状态落在 `gates/diag/merge-queue.json`（**gitignored**，本机运行时状态）。
形状：
```json
{"head": {"task": "T-AG999", "tree": ".wt/e28", "base": "<sha>", "at": "…",
          "files": ["tools/pool/landing.py"]},
 "waiting": [{"task": …, "tree": …, "base": …, "at": …, "files": […]}, …]}
```
`files` = 这一笔的**冲突域**（卡 E5：同文件卡**不许同批**，见 `same_file_conflicts` /
`batches`）。没记 `files` 的旧条目照样能读（空集 = 不知道，不拦）。

★ 边界（如实）：本模块**只管状态**（入队 / 队首 / 推进 / 出队 / 投机是否作废）。
  「把下一棵卡树 rebase 到新 HEAD」「重跑 ③″–④」那两步要 git 与落地链，写在
  `tools/pool/landing.py`（那边调本模块的 `advance` / `respec_required`）。
★ 冲突**永远人来判**（卡 E5「不许自动择一」）：本模块不删任何分支、不动工作区。
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import json
import os
import pathlib
import socket
import time

#: `lastgood` 的模块句柄（懒加载；`None` = 还没加载过）。
_LASTGOOD = None


def _lastgood():
    r"""懒加载 `pool.lastgood`（卡 A330 的写盘纪律）。

    ★ 本模块会被**按文件路径** exec（`tests/test_pool_queue.py` 就按路径加载它），那时既没有
    `pool` 包、也不保证 `tools/` 在 `sys.path` 上 ⇒ 三档兜底，最后一档按同级文件路径加载。
    """
    global _LASTGOOD
    if _LASTGOOD is not None:
        return _LASTGOOD
    try:
        from . import lastgood as mod
    except ImportError:
        try:
            from pool import lastgood as mod
        except ImportError:
            here = pathlib.Path(__file__).resolve().with_name("lastgood.py")
            spec = importlib.util.spec_from_file_location("pool_lastgood_by_path", here)
            if spec is None or spec.loader is None:  # pragma: no cover —— 文件被搬走才会到这
                raise
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    _LASTGOOD = mod
    return mod

#: 状态文件（相对仓库根）。`TF_MERGE_QUEUE` 可覆写（测试 / 演练用）。
STATE_REL = ("gates", "diag", "merge-queue.json")

#: 轮询间隔（秒）。`TF_QUEUE_POLL` 可覆写（测试要快）。
DEFAULT_POLL = 2.0

#: 读改写短锁的等待窗口（秒）。卡 E55（`T-AG507`）：与 `tools/gate_pool.py::LOCK_WAIT_S`
#: **必须同值**（同族口径不许漂，钉子 `test_queue_lock_wait_defaults_agree` 守住）。
LOCK_WAIT_S = 30.0


def _root(root: pathlib.Path | None = None) -> pathlib.Path:
    if root is not None:
        return pathlib.Path(root)
    return pathlib.Path(__file__).resolve().parents[2]


def state_path(root: pathlib.Path | None = None) -> pathlib.Path:
    """状态文件路径：`gates/diag/merge-queue.json`（`TF_MERGE_QUEUE` 优先）。"""
    env = os.environ.get("TF_MERGE_QUEUE", "").strip()
    if env:
        return pathlib.Path(env)
    return _root(root).joinpath(*STATE_REL)


def _poll_interval() -> float:
    try:
        return max(0.01, float(os.environ.get("TF_QUEUE_POLL", DEFAULT_POLL)))
    except ValueError:
        return DEFAULT_POLL


class QueueError(RuntimeError):
    """合并队列操作的失败基类（本模块自己一份 —— 不许反向 import `gate_pool`）。"""


class QueueBusy(QueueError):  # noqa: N818 —— 名字就是判据原文「等不到」
    """队列短锁等不到 —— 失败关闭，绝不绕过去无锁写（卡 E139）。

    ★ 卡 E139 推翻 卡 E55 `复盘/卡/卡E55-门禁池队列锁等待过紧.md:48-49` 的原话
      「不许把『等不到就往下写』改成『等不到就抛异常』（记账队列不许变成闸）」：
      实测 `timeout=0.0` 下 10 轮 10 轮丢行 —— 记账队列被并发写坏，记账本身就是错的。
    ★ 与 `tools/gate_pool.py::GatePoolBusy` 同一种结局（都抛、都失败关闭、都不写），
      但各定义各的异常：两族只对齐口径，不互相 import（钉子
      `test_two_families_agree_on_give_up` 用元组断言咬这一条）。
    """


def _write_holder(fd: int) -> None:
    """把「谁持着锁」写进锁文件（`<pid>@<host>`）—— 只为「等不到」的文案能点名。

    ★ 写不进去不算失败：锁已经建成了，「有人占着」的判据是文件存在，不是内容。
    """
    with contextlib.suppress(OSError):
        os.write(fd, f"{os.getpid()}@{socket.gethostname()}".encode())


def _lock_holder(lock: pathlib.Path) -> str:
    """锁文件里写的持有者；读不到 / 没写 ⇒ 明说读不到（不许猜，也不许省掉这一段）。"""
    try:
        text = lock.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return f"读不到持有者（{type(exc).__name__}）"
    if not text:
        return "读不到持有者（锁文件里没写）"
    return f"持有者 {text}"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _empty() -> dict:
    return {"head": None, "waiting": []}


def load(root: pathlib.Path | None = None) -> dict:
    r"""读队列；文件不存在 / 坏了 ⇒ 空队列（**不许**因为队列文件坏了挡住落地）。"""
    p = state_path(root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    head = data.get("head")
    waiting = data.get("waiting")
    return {"head": head if isinstance(head, dict) else None,
            "waiting": [x for x in (waiting or []) if isinstance(x, dict)]}


def _validate_state_text(text: str) -> None:
    r"""判「这份队列快照还能不能当 lastgood」：解得开且顶层是对象（卡 A330）。"""
    if not isinstance(json.loads(text), dict):
        raise ValueError("队列快照顶层应是对象")


def _save(state: dict, root: pathlib.Path | None = None) -> None:
    r"""原子写（tmp + `os.replace`）：别的进程读到的永远是**完整**的一份。

    走 `lastgood.write_atomic`（卡 A330）：旧的好就先顶成 `.bak`（`.bak` 落后一次写）。
    """
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    _lastgood().write_atomic(p, body, validate=_validate_state_text)


@contextlib.contextmanager
def _locked(root: pathlib.Path | None = None, timeout: float = LOCK_WAIT_S):
    r"""读改写期间拿一把**短**锁（`<state>.lock`，`O_CREAT|O_EXCL`）。

    ★ 这**不是**门禁锁（那把保护的是端口/内存，粒度是「整趟门禁」）；这把只保护
      「读队列 → 改 → 写回」这几毫秒，**不许**拿它当单写者的判据（单写者看 `head`）。
    ★ 卡 E139：等不到 ⇒ 抛 `QueueBusy`，一个字节都不写。改前是 `break` 出去照样写
      —— E55 `:48-49` 那句「队列是**记账**，不是闸：卡 E5 要防的是白跑，不是数据一致性」
      **被本卡推翻**：记账队列被并发写坏，记账本身就是错的。等待窗口仍是 `LOCK_WAIT_S`
      （E55 定的 30 s，与 `tools/gate_pool.py::LOCK_WAIT_S` 同值，钉子
      `test_queue_lock_wait_defaults_agree` 守着）。
    ★ 建锁的 `PermissionError` 与 `FileExistsError` 走同一条路：Windows 上持有者正在
      `unlink()` 的那一瞬撞的是 `PermissionError [WinError 5]`，语义与「有人占着」
      相同（卡 E139 判据 2 的同族要求）。
    """
    lock = state_path(root).with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fd = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            _write_holder(fd)  # 建锁之后才知道是谁 —— 只给「等不到」的文案用，不抛
            break
        except (FileExistsError, PermissionError) as exc:
            # ★ 卡 E139：PermissionError 不是「坏了」，是「这一刻有人占着」（见 docstring）。
            if time.time() - t0 >= timeout:
                raise QueueBusy(
                    f"等不到合并队列短锁（等了 {timeout:g}s）：{lock}；{_lock_holder(lock)}。"
                    f"最后一次建锁失败（{type(exc).__name__}: {exc}）。"
                    "别绕过去无锁写 —— 稍后重试，或先查清谁占着这把锁。"
                ) from exc
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(OSError):
                lock.unlink()


def _entry(tree: str, task: str, base: str = "", files: object = ()) -> dict:
    return {"task": task, "tree": tree, "base": base, "at": _now(),
            "files": sorted({_norm(f) for f in (files or ()) if str(f).strip()})}


def _norm(p: object) -> str:
    """POSIX 化 + 去掉 `./` 前缀（冲突域比较用；**不动**开头的点）。"""
    q = str(p).replace("\\", "/")
    while q.startswith("./"):
        q = q[2:]
    return q


def _files_of(entry: dict | None) -> frozenset[str]:
    """这笔卡的**冲突域**（`files` 字段；没记 ⇒ 空集，代表「不知道」而不是「不冲突」）。"""
    return frozenset(_norm(f) for f in ((entry or {}).get("files") or ()) if str(f).strip())


def same_file_conflicts(task: str, *, root: pathlib.Path | None = None) -> list[str]:
    r"""★ 卡 E5（`T-AG447`）· **同文件卡不许同批**：与 `task` 的 `files` 相交的**别人**。

    口径与 `tools/pool/plan.py::files_intersect` 同一条（`files` 是冲突域，同批两卡相交
    = 冲突）。这里只做**记账与点名**，不改单写者语义：相交的那几笔**不许与它并行进同一批**，
    它们在队列里各自占一个位置（`batches()` 可复现这个分组）。
    ★ 没记 `files` 的卡 ⇒ 返回空列表（「不知道」不等于「不冲突」；落地链调用时会传 `--allow`）。
    """
    state = load(root)
    order = ([state["head"]] if state["head"] else []) + state["waiting"]
    me = next((e for e in order if e.get("task") == task), None)
    mine = _files_of(me)
    if me is None or not mine:
        return []
    return [str(e.get("task")) for e in order
            if e is not me and _files_of(e) & mine]


def batches(*, root: pathlib.Path | None = None) -> list[list[str]]:
    r"""把队列按「同批两两 `files` 不相交」切成**批**（顺序即队列顺序）。

    ★ 卡 E5：同文件卡**不许同批** —— 两张卡改同一个文件时，它们必须落在相邻的两批
      （= 串行），不许并排。没记 `files` 的卡按「与本批都不冲突」处理（记账用，不拦）。
    """
    state = load(root)
    order = ([state["head"]] if state["head"] else []) + state["waiting"]
    out: list[list[dict]] = []
    for e in order:
        if out and all(not (_files_of(e) & _files_of(x)) for x in out[-1]):
            out[-1].append(e)
        else:
            out.append([e])
    return [[str(e.get("task")) for e in batch] for batch in out]


def enqueue(tree: str, task: str, *, base: str = "", files: object = (),
            root: pathlib.Path | None = None) -> dict:
    r"""入队（幂等：同一 task 再入队 ⇒ **保持原位**，只刷新 tree/base/files）。

    返回 `position_of()` 的结果：`{"position", "head", "total"}` ——
    `position` 从 **1** 起（1 = 队首；0 = 没排上），`head` 是队首的 task。
    `files`（卡 E5）：这一笔的**冲突域** —— 同文件卡不许同批（见 `same_file_conflicts`）。
    """
    with _locked(root):
        state = load(root)
        all_tasks = state["waiting"] + ([state["head"]] if state["head"] else [])
        if not any(e.get("task") == task for e in all_tasks):
            fresh = _entry(tree, task, base, files)
            if state["head"] is None:
                state["head"] = fresh
            else:
                state["waiting"].append(fresh)
        else:
            for e in all_tasks:
                if e.get("task") == task:
                    e["tree"] = tree
                    if base:
                        e["base"] = base
                    if files:
                        e["files"] = sorted({_norm(f) for f in files if str(f).strip()})
        _save(state, root)
        state = load(root)
    return position_of(task, root=root)


def position_of(task: str, *, root: pathlib.Path | None = None) -> dict:
    r"""这笔落在第几位（`0` = 不在队列里）。返回 `{"position", "head", "total"}`。"""
    state = load(root)
    if state["head"] is not None and state["head"].get("task") == task:
        pos = 1
    else:
        pos = 0
        for i, e in enumerate(state["waiting"], start=2):
            if e.get("task") == task:
                pos = i
                break
    head_task = (state["head"] or {}).get("task")
    total = (1 if head_task else 0) + len(state["waiting"])
    return {"position": pos, "head": head_task, "total": total}


def head(root: pathlib.Path | None = None) -> dict | None:
    """队首（`None` = 没人排队）。"""
    return load(root)["head"]


def is_head(task: str, *, root: pathlib.Path | None = None) -> bool:
    h = head(root)
    return bool(h) and h.get("task") == task


def advance(root: pathlib.Path | None = None) -> dict | None:
    r"""队首干完 ⇒ 出队；下一个自动变队首。返回**新的队首**（没人了 ⇒ `None`）。

    ★ 「干完」只由调用方在 **ff 合流成功之后**调（卡 E5 判据 3）；失败要走 `drop`。
    """
    with _locked(root):
        state = load(root)
        if state["head"] is None:
            return None
        state["head"] = state["waiting"].pop(0) if state["waiting"] else None
        if state["head"] is not None:
            state["head"]["at"] = _now()
        _save(state, root)
        return load(root)["head"]


def drop(task: str, *, root: pathlib.Path | None = None) -> bool:
    r"""把一笔从队列里摘掉（队首被摘 ⇒ 下一个自动顶上来）。返回是否真摘到了。

    ★ 只用于两种情况：① ff 失败、rebase 一次仍失败 ⇒ **需人工**（卡 E5 判据 4）；
      ② 落地已明确放弃（等队列超时 / 白名单停手）。**不许**用它"让路"。
    """
    with _locked(root):
        state = load(root)
        if state["head"] is not None and state["head"].get("task") == task:
            state["head"] = state["waiting"].pop(0) if state["waiting"] else None
            _save(state, root)
            return True
        before = len(state["waiting"])
        state["waiting"] = [e for e in state["waiting"] if e.get("task") != task]
        if len(state["waiting"]) != before:
            _save(state, root)
            return True
        return False


def respec_required(task: str, *, base: str,
                    root: pathlib.Path | None = None) -> bool:
    r"""**投机预检还作数吗** —— 基点变了就作废。

    判据极简：入队时记的 `base` 与此刻要用的 `base`（卡树基点 / 主树 HEAD）不同 ⇒
    这中间主树前进过 / 换过队首 ⇒ 上一趟 ③″ 的结论**不许复用**（卡 E5 判据 3）。
    不在队列里（或没记 base）⇒ `False`（没有投机可谈，不额外要求重跑）。
    """
    state = load(root)
    for e in ([state["head"]] if state["head"] else []) + state["waiting"]:
        if e.get("task") == task:
            old = str(e.get("base") or "")
            return bool(old) and old != base
    return False


def wait_turn(task: str, *, timeout: float = 3600.0,
              root: pathlib.Path | None = None, say=None) -> bool:
    r"""等到自己成为队首（`timeout` 秒内）。`True` = 轮到你了；`False` = 等超时。

    `say` 给一个 `print` 形状的回调（调用方把「排第几位」写进落地日志）；
    只在**位置变化**时打一行（别每 2 秒刷一次屏 —— 那和「没进度」是同一个病）。
    """
    poll = _poll_interval()
    t0 = time.time()
    last = None
    while True:
        info = position_of(task, root=root)
        if info["position"] == 1:
            if say:
                say(f"  [队列] 轮到队首（前面 {info['head'] or '没人'} 已出队）")
            return True
        if info["position"] == 0:
            # 不在队列里（被 drop / 状态文件被清）⇒ 当作轮到自己，别无限等
            if say:
                say("  [队列] ★ 不在队列里（被摘掉或状态被清）⇒ 照常往下走")
            return True
        if info != last and say:
            say(f"  [队列] 排队中：第 {info['position']} 位（共 {info['total']} 笔；"
                f"队首 {info['head']}）")
            last = info
        if time.time() - t0 >= timeout:
            if say:
                say(f"  [队列] ★ 等队首超时（{int(timeout)}s，还排在第 "
                    f"{info['position']} 位）⇒ 停手")
            return False
        time.sleep(min(poll, max(0.0, timeout - (time.time() - t0))))
