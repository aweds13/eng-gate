r"""卡粘性：同一张卡第二次派活别换号（卡 A345 · `T-AG547`）。

**移植自** magpie `internal/gateway/affinity.go` 的两层：`Stick`（谁答过这张卡）与
`Why`（为什么留 / 为什么走）。原件里这两层是为了**命中 vendor 的前缀缓存**；本仓不转发
协议请求、没有缓存可命中，所以这里省的只是「把整段卡规格与上下文重发一遍」的 token 与
重新理解卡的时间 —— **收益比原件小一个量级**（见文末「边界」）。

对应关系（逐条点名来处，别凭印象改）：

- `STICK_KEEP_S = 24 * 3600` ← `affinity.go:71` 的 `stickKeep = 24 * time.Hour`
- `STICKS_KEPT = 512` ← `affinity.go:73` 的 `sticksKept = 512`
- `note()` 的修剪 ← `affinity.go:287` 的 `saveSticks()`：**按 `at` 倒序**取前 `STICKS_KEPT` 条
  （不是按卡号字典序 —— 要的是「最近」，不是「最小」）
- `stick_for()` / `note()` 的 fail-open ← `tools/pool/route.py:210 apply_order()` 的同一条纪律：
  粘性是省钱的优化，判不了就当没有，**不许**因此拦派活
- `choose()` 的四支 ← `affinity.go:527-577` 的 `affine()` 里与 pool 对得上的那几条：
  `!had ⇒ "first"`、`at < 0 ⇒ "gone"`、`Used >= SpentShare ⇒ "spent"`、
  `time.Since(at) > keep ⇒ "cold"`

## 为什么 `choose()` 是个纯函数

判据只写一遍（照 `pool.route.tier()` / `pool.rpm.decide()` 的体例）：
`tools/wb_dispatch.py` 只负责「读记录 → 调 `choose()` → 把结论接到 `args.account` 上」，
不自己再判一遍「这个号还能不能用」。这样这些判定能用 `tmp_path` 当 root 纯函数地钉住。

## `Why` 的两组

`REASONS_KEEP`（记录里的号可以再用一次）与 `REASONS_LEAVE`（别用它，正常挑号）**不相交**，
并集等于本模块全部 `WHY_*` 常量（钉子 `test_reasons_keep_and_leave_are_disjoint`）。

★ `WHY_FIRST = "first"` 归「保留」看着别扭，但原件就是这么分的：magpie 的 `Kept=false`
配 `Why="first"` 意思是「**第一次，没人答过**」—— 当时没有旧号可用，而「下次回来接着用它
的记录」这件事从这一刻才成立。本卡语义完全一样：首次派活记下 `why="first"`，第二次派活
读到它 ⇒ 该走「用记录里的号」这条路。

## 边界（如实写，别当承诺读）

- **收益比 magpie 小一个量级**：pool 没有 `cache_read + cache_write` 这种派活前证据，
  原件 `affinity.go:51` 的 `cacheWorth = 1024` 那道闸门**明确不搬**
  （`gates/diag/wb-usage.jsonl` 里的 `cache_read` 是**事后**数，拿它当派活判据就是拿果推因）。
- **不搬四个路由态**（`strict` / `resting` / `spent` / `main`）：它们读的是
  `planned.order[i].Rest` / `Order[i].Fallback` / `SpentShareOf(p.Routing)`，pool 的
  `apply_order()` 是另一个形状。本模块只有自己的 `spent`（= `used_percent >= USED_SHARE`，
  `USED_SHARE` 从 `tools/pool/route.py:75` **取**，不硬编码 98）。
- **不做跨机同步**：原件有 davsync 合并，pool 只治单机（`tools/pool/task.py` 文件头立过）。
- **`session` 只是记事本**：记下「当时用的是哪个会话」，**不保证**下次自动 `--resume`。
- **账本查不到就 `gone`**：`--account` 的取值口径一旦变化（例如从 profile 名改成稳定 id），
  旧记录会集体 `gone`，第一次派活重建一次即恢复 —— 这是可接受的降级，但别当没发生。
- 状态落 `gates/diag/pool-sticky.json`（**gitignored** 的运行状态，不是台账，不进 `docs/`）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pool import lastgood
from pool.route import USED_SHARE

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Sequence

__all__ = [
    "ENV_STICKY",
    "REASONS_KEEP",
    "REASONS_LEAVE",
    "STICKS_KEPT",
    "STICKY_REL",
    "STICK_KEEP_S",
    "WHY_CARD",
    "WHY_COLD",
    "WHY_FIRST",
    "WHY_GONE",
    "WHY_OFF",
    "WHY_SESSION",
    "WHY_SPENT",
    "Stick",
    "age_text",
    "choose",
    "note",
    "stick_for",
    "sticky_path",
]

#: 状态文件（相对仓库根）。`TF_POOL_STICKY` 可覆写（测试 / 演练用）。
STICKY_REL: tuple[str, ...] = ("gates", "diag", "pool-sticky.json")

#: 覆写状态文件位置的 env（与 `TF_POOL_SINK` / `TF_POOL_REGISTRY` 同一手法）。
ENV_STICKY = "TF_POOL_STICKY"

#: 记录活多久：逐字抄 magpie `affinity.go:71` 的 `stickKeep = 24 * time.Hour`，**不许改数**。
STICK_KEEP_S = 24 * 3600

#: 最多留多少条：逐字抄 magpie `affinity.go:73` 的 `sticksKept = 512`，**不许改数**。
STICKS_KEPT = 512

#: 仓库根（`tools/pool/sticky.py` → `tools/pool` → `tools` → 仓库根），与 `sink.py:53` 同式。
TOOL_ROOT = Path(__file__).resolve().parents[2]

# `Why` 的七种取值（照 `affinity.go:97-104` 的注释逐个对上）。
WHY_SESSION = "session"
WHY_CARD = "card"
WHY_FIRST = "first"
WHY_OFF = "off"
WHY_GONE = "gone"
WHY_SPENT = "spent"
WHY_COLD = "cold"

#: 记号还能再用一次的理由（`WHY_FIRST` 的口径见文件头：第一次，没人答过）。
REASONS_KEEP: tuple[str, ...] = (WHY_SESSION, WHY_CARD, WHY_FIRST)

#: 记号不该再用的理由（留着记录是为了让判决说得清「为什么这次换了号」）。
REASONS_LEAVE: tuple[str, ...] = (WHY_OFF, WHY_GONE, WHY_SPENT, WHY_COLD)


@dataclass
class Stick:
    """一张卡的粘性记录（字段照 magpie 的 `savedStick`，**不许多塞**）。

    `at` 是 epoch 秒（照 `savedStick.At`）；`why` 是「**上次**留下的理由」，
    不是「这次为什么用它」—— 后者由 `choose()` 现算。
    """

    card: str
    account: str = ""
    tree: str = ""
    session: str = ""
    model: str = ""
    at: float = 0.0
    why: str = WHY_FIRST


def _root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return TOOL_ROOT


def sticky_path(root: Path | None = None) -> Path:
    """状态文件路径：`gates/diag/pool-sticky.json`（`TF_POOL_STICKY` 优先）。"""
    env = os.environ.get(ENV_STICKY, "").strip()
    if env:
        return Path(env)
    return _root(root).joinpath(*STICKY_REL)


def _warn(msg: str) -> None:
    print(f"[sticky] {msg}", file=sys.stderr)


def _text(item: dict, name: str) -> str:
    value = item.get(name, "")
    return value if isinstance(value, str) else ""


def _parse(key: str, item: object) -> Stick | None:
    """一条记录校验；形状不对 ⇒ `None` 并在 stderr 说一句（不许静默洗成别的号）。"""
    if not isinstance(item, dict):
        _warn(f"坏值：卡 {key!r} 的记录不是对象 ⇒ 当作没有")
        return None
    raw_at = item.get("at", 0.0)
    if isinstance(raw_at, bool) or not isinstance(raw_at, (int, float)):
        _warn(f"坏值：卡 {key!r} 的 at={raw_at!r} 不是数字 ⇒ 当 0.0（那时就已经过期了）")
        raw_at = 0.0
    why = _text(item, "why") or WHY_FIRST
    if why not in REASONS_KEEP and why not in REASONS_LEAVE:
        _warn(f"坏值：卡 {key!r} 的 why={why!r} 不在枚举里 ⇒ 当作没有")
        return None
    return Stick(
        card=_text(item, "card") or key,
        account=_text(item, "account"),
        tree=_text(item, "tree"),
        session=_text(item, "session"),
        model=_text(item, "model"),
        at=float(raw_at),
        why=why,
    )


def _load(root: Path | None = None) -> dict[str, Stick]:
    r"""读状态；不存在 / 坏 JSON / 形状不对 ⇒ 空表（**不抛**），且**不重写**那个文件。

    只读这一侧一律「回空 + 不落盘」：顺手把别人的坏文件洗成合法的空壳，等于把
    「记录被写坏过」这件事藏起来（照 `sink.py:88-113` 的 `_load`）。
    """
    path = sticky_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("stick")
    if not isinstance(raw, dict):
        return {}
    box: dict[str, Stick] = {}
    for key, item in raw.items():
        stick = _parse(key, item)
        if stick is not None and stick.card:
            box[stick.card] = stick
    return box


def _validate(text: str) -> None:
    """判「旧的这份还能不能当 lastgood」：能不能当 JSON 读回来。"""
    json.loads(text)


def stick_for(
    card: str, *, now: float | None = None, root: Path | None = None
) -> Stick | None:
    r"""这张卡上次是谁答的 —— 判不了就 `None`（fail-open，**绝不抛**）。

    判据 4 的四条「当没有」：过期（`now - at > STICK_KEEP_S`）/ 文件不存在 / JSON 坏 /
    形状不对 / `account == ""`。理由同 `tools/pool/route.py:210 apply_order()`：
    粘性是省钱的优化，判不了就当没有，**不许**因此拦派活。
    """
    if not isinstance(card, str) or not card:
        return None
    stick = _load(root).get(card)
    if stick is None or not stick.account:
        return None
    stamp = time.time() if now is None else float(now)
    if stamp - stick.at > STICK_KEEP_S:
        return None
    return stick


def choose(
    stick: Stick | None, accounts: Sequence[dict], *, now: float | None = None
) -> tuple[str, str]:
    r"""记录里的号还能不能用：回 `(号, why)`，号是空串 ⇒ 别用，正常挑号。

    `accounts` 是账本里 `[[account]]` 的原始 dict 列表（`pool_accounts.load_ledger()` 的
    `data["account"]`）——**不是** `list_rows()` 的结果，那个不回 `used_percent`。

    判据 7 的三道复查（顺序固定，先便宜后贵）：仍 active → `used_percent < USED_SHARE`
    → 记录里的 `why` 属「保留」。任何一条不过 ⇒ 回 `("", 走开理由)`，**不拦派活**。

    ★ `used_percent` 缺省（`[account.quota]` 里没有这个键）⇒ **当未知、不判 spent**：
      `tools/pool_accounts.py:190-205` 明确允许缺这个键，把「没观测过」读成「用尽了」
      就是把一次能跑的派活凭空拦掉。
    """
    if stick is None or not stick.account:
        return ("", WHY_FIRST)
    stamp = time.time() if now is None else float(now)
    if stamp - stick.at > STICK_KEEP_S:
        return ("", WHY_COLD)
    if stick.why not in REASONS_KEEP:
        return ("", stick.why)
    hit = next(
        (acc for acc in accounts if isinstance(acc, dict) and acc.get("id") == stick.account),
        None,
    )
    if hit is None or hit.get("state") != "active":
        return ("", WHY_GONE)
    quota = hit.get("quota")
    used = (quota if isinstance(quota, dict) else {}).get("used_percent")
    if isinstance(used, (int, float)) and not isinstance(used, bool) and float(used) >= USED_SHARE:
        return ("", WHY_SPENT)
    return (stick.account, stick.why)


def note(stick: Stick, *, root: Path | None = None) -> Path:
    r"""记下「这张卡这次是谁答的」，回落的路径；落盘走 `lastgood.write_atomic`。

    修剪照 `affinity.go:287 saveSticks()`：先扔掉过期的（`now - at > STICK_KEEP_S`），
    再**按 `at` 倒序**取前 `STICKS_KEPT` 条。**不许**按卡号字典序剪 —— 要的是「最近」。
    """
    if not isinstance(stick, Stick) or not stick.card:
        raise ValueError("note() 要一条带卡号的 Stick")
    stamp = time.time()
    box = _load(root)
    box[stick.card] = stick
    fresh = [item for item in box.values() if stamp - item.at <= STICK_KEEP_S]
    fresh.sort(key=lambda item: item.at, reverse=True)
    kept = fresh[:STICKS_KEPT]
    path = sticky_path(root)
    body = json.dumps(
        {"stick": {item.card: asdict(item) for item in kept}},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    lastgood.write_atomic(path, body, validate=_validate)
    return path


def age_text(seconds: float) -> str:
    """人的读法：`1 天 2 小时` / `3 小时 12 分` / `12 分 5 秒` / `5 秒`（判据 11 的 `<龄>`）。"""
    left = max(0, int(seconds))
    days, left = divmod(left, 24 * 3600)
    hours, left = divmod(left, 3600)
    minutes, secs = divmod(left, 60)
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"
