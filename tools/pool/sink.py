r"""Sink 沉底：429 且「还有配额」的候选沉到次序末尾（卡 A331 · `T-AG533`）。

**移植自** magpie `internal/gateway/{sink.go,routing.go,fallback.go}`（设计原件
`_ext/_port_design_quota_routing.md` 的 `## F19 Sink 沉底` 一节，`:629-801`）：

- `sink(key, now)`（`sink.go:43`）→ `sink()`：记一次沉底，`n` 单调递增；同 key 再沉 ⇒ 刷新
- `unsink(key)`（`:53`）→ `unsink()`：只擦**精确**那个 key
- `unsinkAll(key)`（`:61`）→ `unsink_all()`：擦 `k == key || k.startswith(key + "/")`
- `sunkAt(c)`（`:74-82`）→ `sunk_at()`：**先** `<account>/<model>`（模型级）**再** `<account>`
- `sinkOrder(n, at)`（`:94-117`）→ `sink_order()`：未沉在前（保原序），沉者按沉序
- `sinkLast(cs)`（`routing.go:1701`）→ `sink_last()`：按上面的序重排一串条目
- `sinks(on, routing)`（`sink.go:87-89`）→ `sinks()`：`on` 且不是 rotate / weighted / manual
- `routing.go:1149-1161` 的 kind 分支 → `should_sink()`：只有「限流」才沉，余额耗尽绝不沉

★ 边界（如实写，别当承诺读）：
  · **「还有配额却 429」这一前提本仓证明不了** —— 逐字见 `sink()` 的 docstring；
  · 状态落 `gates/diag/pool-sink.json`（**gitignored** 的运行状态，不是台账，不许进 `docs/`）；
  · **不做 TTL / 到期自动 unsink**：magpie 的 sink 自己也不带到期时间（`unsink` 只有手动或重启
    才发生）。加 TTL 会变成另一种语义 —— 那已经是 F20 的 rest，不是本卡；
  · 本模块**不接线**任何派活流程：`tools/wb_dispatch.py` 一行不改（那是另一张卡）；
  · 读改写**不做跨进程互斥**：两个进程同时沉，可能拿到同一个 `n`。这只影响它俩彼此的先后，
    不影响「沉者排在未沉者之后」这条主判据。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

T = TypeVar("T")

#: 状态文件（相对仓库根）。`TF_POOL_SINK` 可覆写（测试 / 演练用）。
SINK_REL: tuple[str, ...] = ("gates", "diag", "pool-sink.json")

#: 覆写状态文件位置的 env（与 `TF_MERGE_QUEUE` / `TF_POOL_REGISTRY` 同一手法）。
ENV_SINK = "TF_POOL_SINK"

#: 429 的两类，逐字取自 `tools/wb_dispatch.py::quota_error` 的 `kind` 口径。
KIND_RATE = "限流"
KIND_BALANCE = "余额耗尽"


def _root(root: pathlib.Path | None = None) -> pathlib.Path:
    if root is not None:
        return pathlib.Path(root)
    return pathlib.Path(__file__).resolve().parents[2]


def sink_path(root: pathlib.Path | None = None) -> pathlib.Path:
    """状态文件路径：`gates/diag/pool-sink.json`（`TF_POOL_SINK` 优先）。"""
    env = os.environ.get(ENV_SINK, "").strip()
    if env:
        return pathlib.Path(env)
    return _root(root).joinpath(*SINK_REL)


def _empty() -> dict:
    return {"n": 0, "m": {}}


def _warn(msg: str) -> None:
    print(f"[sink] {msg}", file=sys.stderr)


def _entry(key: str, raw: object) -> dict | None:
    r"""一条记录校验：`n` 非正整数 ⇒ 该 key 视为从未沉，并在 stderr 说一句（不许静默）。"""
    if not isinstance(raw, dict):
        _warn(f"坏值：{key!r} 的记录不是对象 ⇒ 视为从未沉")
        return None
    seq = raw.get("n")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
        _warn(f"坏值：{key!r} 的 seq={seq!r} 不是正整数 ⇒ 视为从未沉")
        return None
    at = raw.get("at")
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        _warn(f"坏值：{key!r} 的 at={at!r} 不是数字 ⇒ 当 0.0（at 只用于展示，不参与判据）")
        at = 0.0
    return {"n": int(seq), "at": float(at)}


def _load(root: pathlib.Path | None = None) -> dict:
    r"""读状态；不存在 / 坏 JSON / 形状不对 ⇒ 空（**不抛**），且**不重写**那个文件。

    写时才建（照 `tools/pool_quota.py:119-130` 的坏 JSON → 空 口径；但 sink 的坏文件更危险，
    所以只读这一侧一律「回空 + 不落盘」，不许顺手把别人的文件洗成合法的空壳）。
    """
    p = sink_path(root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    raw_m = data.get("m")
    if not isinstance(raw_m, dict):
        return _empty()
    m: dict[str, dict] = {}
    for key, raw in raw_m.items():
        entry = _entry(key, raw)
        if entry is not None:
            m[key] = entry
    counter = data.get("n")
    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        counter = 0
    # 手写过的文件可能外面那个 n 落后于内部最大 seq —— 取大者，保证下一次 sink 的 n 仍递增。
    return {"n": max([counter, *(item["n"] for item in m.values())]), "m": m}


def _save(state: dict, root: pathlib.Path | None = None) -> pathlib.Path:
    """原子落盘：同目录 `tmp` + `os.replace`（读者只看到旧整份或新整份）。"""
    p = sink_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    body = json.dumps(
        {"n": state["n"], "m": state["m"]}, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    tmp.write_text(body, encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return p


def _lookup(m: dict[str, dict], key: str) -> tuple[int, float] | None:
    """先按 `key`（模型级 `<account>/<model>`）查，再按 `<account>` 查（照 `sink.go:74-82`）。"""
    hit = m.get(key)
    if hit is None and "/" in key:
        hit = m.get(key.partition("/")[0])
    if hit is None:
        return None
    return (int(hit["n"]), float(hit["at"]))


def sink(key: str, now: float | None = None, *, root: pathlib.Path | None = None) -> int:
    r"""记一次沉底，返回序号 n（单调递增，从 1 开始）。重复沉同 key ⇒ 序号刷新（照 sink.go:43-48）。

    ★ **本仓没有 magpie `c.full()` 的等价物** ⇒ 『有配额却 429』这一前提是**假定**成立、由调用方
      保证，**不算已核实**。magpie 在 `internal/gateway/routing.go:1149-1161` 拿
      `c.full(now).IsZero()`（本窗用量没满）当沉的前置条件；pool 连本窗用量读数都没有
      （`tools/pool/registry.py` 只有 `model` 字段，`:319`，无用量），所以这里**只做记账**：
      谁该沉由调用方判，本函数不复查、也不可能复查。

    `at` 只用于展示：排序只看 `n`（magpie 的 `sinkOrder` 也只比 `n`），所以时钟倒流不影响次序。
    """
    state = _load(root)
    state["n"] = int(state["n"]) + 1
    at = time.time() if now is None else float(now)
    state["m"][key] = {"n": state["n"], "at": at}
    _save(state, root)
    return state["n"]


def sunk_at(key: str, *, root: pathlib.Path | None = None) -> tuple[int, float] | None:
    """→ (n, at) 或 None。key 先按 <model> 查，再按 <account> 查（照 sink.go:74-82）。"""
    return _lookup(_load(root)["m"], key)


def unsink(key: str, *, root: pathlib.Path | None = None) -> None:
    """擦掉**精确**这一个 key（照 `sink.go:53`）；连带模型级那几条要 `unsink_all()`。"""
    state = _load(root)
    if key not in state["m"]:
        return
    del state["m"][key]
    _save(state, root)


def unsink_all(prefix: str, *, root: pathlib.Path | None = None) -> int:
    r"""擦掉 `prefix` 与它下面所有 `<prefix>/…`，返回删掉几个（照 `sink.go:61-69`）。"""
    state = _load(root)
    m = state["m"]
    doomed = [k for k in m if k == prefix or k.startswith(prefix + "/")]
    for k in doomed:
        del m[k]
    if doomed:
        _save(state, root)
    return len(doomed)


def sink_order(
    n: int, key_of: Callable[[int], str], *, root: pathlib.Path | None = None
) -> list[int]:
    """照 sink.go:94-117：seq==0 在前（保原序），其余按 seq 升序稳定排。

    ★ key 必须写成两段式 `(0, 0) if seq[i] == 0 else (1, seq[i])` —— 把「从未沉」与「沉过」分成
      两段；单段写法一旦退化（例如整条 `key=lambda i: 0`）就变成「不排序」，而那样在
      「只沉了 k1」的场景里恰好给出另一种序，钉子就再也分辨不出来了（见
      `tests/test_pool_sink.py::test_reverse_sink_order_without_seq`）。

    ★ `key_of` 抛错 ⇒ **传播**（fail-fast）：状态文件坏了若静默 fail-open，会把「已沉」洗成
      「没沉」，正好反向。
    """
    m = _load(root)["m"]
    seq: list[int] = []
    for i in range(n):
        hit = _lookup(m, key_of(i))
        seq.append(0 if hit is None else hit[0])
    idx = list(range(n))
    idx.sort(key=lambda i: (0, 0) if seq[i] == 0 else (1, seq[i]))
    return idx


def sink_last(
    items: Sequence[T], key_of: Callable[[T], str], *, root: pathlib.Path | None = None
) -> list[T]:
    """整串按 `sink_order` 重排：沉过的挪到后面（照 `routing.go:1701-1707` 的 `sinkLast`）。"""
    order = sink_order(len(items), lambda i: key_of(items[i]), root=root)
    return [items[i] for i in order]


def sinks(on: bool, routing: str) -> bool:
    """照 sink.go:87-89：on and routing not in ("rotate", "weighted") and routing != "manual"。"""
    return bool(on) and routing not in ("rotate", "weighted") and routing != "manual"


def should_sink(kind: str | None, routing: str, *, on: bool = True) -> bool:
    r"""这一次 429 该不该沉：**只有「限流」这类才沉**（照 `routing.go:1149-1161`）。

    `kind` 取 `tools/wb_dispatch.py::quota_error` 的 `kind`（`"限流"` / `"余额耗尽"`，`:1524`）。
    `failQuota` / `failCredit` 分支（`routing.go:1096-1148`）里**没有任何 `sink(` 调用** ——
    余额耗尽沉下去就再也不会回来（它不会自己恢复），那是把候选永久烧掉，所以这里硬拦。
    """
    return sinks(on, routing) and kind == KIND_RATE
