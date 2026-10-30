r"""配额历史曲线：每读一次额度留一个点（卡 A346 · T-AG548）。

**移植自** magpie `internal/provider/quota_history.go`（`newCycle` / `addPoint` / `prune` /
`pointOf` / `quotaHistKey` 与 `:42-51` 的五个常量）；判据的唯一来源是
`复盘/卡/卡A346-额度曲线要能看出回血.md`。

## 为什么有它

pool 能答「这个号此刻能不能派」，答不出「它在回血还是在掉血」。账本 `[account.quota]` 只有
`observed_at` 与 `samples`（`{"at","kind"}` 两项 —— 只有结论码，没有数量，也没有窗口起止）。
本模块把 magpie 的**容器与判据**搬过来：历史点、回血检测（`new_cycle`）、去抖（`add_point`）、
剪枝（`prune`）。

## 五个缺口（如实说，不许当成已解决）

1. **今天产出空曲线**：`used_percent` 全仓零写方，四个真账号的 `[account.quota]` 也没有窗口
   起止 ⇒ 本卡落地后 `gates/diag/quota-history.json` **不会生成**。这是预期，**不许造假数据**
   （钉子里 `test_real_ledger_produces_no_curve_today` 盯的就是这件事）。验的是判据的判别力，
   不是「曲线真的画出来了」。
2. `holds.estimate()` 的分母仍然缺：本模块只提供「历史点」这个容器，**不**替 `holds` 造数。
3. 不做 magpie 的 `mergeQuotaHist`（跨机合并）：pool 没有多机共用一份曲线的场景。
4. 不做 `SubscriptionQuota` / `LineName()` 那一层展示，也不把 `quota-state.json` 并进曲线
   （那是「现在」，不是「历史」）。
5. `point_of()` 的入参形状照 magpie 的 `QuotaWindow`（`name` / `used` / `family` / `aside` /
   `pool` / `unlimited` / `span` / `resets_at`），**本仓今天没有任何东西产出这个形状**；
   本模块只保证「形状对了就能算对」。

## 与 magpie 的三处出入（如实记）

* `add_point` 的「不比最后一个新」：magpie 只看时刻（`!n.At.After(pts[k-1].At)`），卡规格加了
  「且 `left` 相同」⇒ 这里实现成 `point.at <= last.at and point.left == last.left`。按卡规格。
* `point_of` 不移植 `ResetSecs` 那一支：卡规格给的入参键里没有它，只认 `resets_at` 绝对时刻。
  `start` 也只在 `span > 0` 时写（magpie 的 `windowSpan`）。
* `prune` 用列表推导，等价于 magpie 的二分（入参本就是按 `at` 递增的）。

★ 边界：本模块**纯判定** —— 零网络、零 sleep、不读账本；读盘只经 `root` 参数与 `ENV_HISTORY`，
写盘一律走 `pool.lastgood.write_atomic`（原子替换 + `.bak` 落后一次写），**不用** `write_text`。
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Sequence

# ---------------------------------------------------------------- 常量
#
# 五个数值逐字取自 magpie `internal/provider/quota_history.go:42-51`。★ 都**不是**策略旋钮：
# 它们标定的是「两读之间差多少算回血」，改成可配置就等于换判据。

#: 曲线文件（相对数据根）。`TF_POOL_QUOTA_HISTORY` 可覆写（测试 / 演练用）。
HISTORY_REL: tuple[str, ...] = ("gates", "diag", "quota-history.json")

#: 覆写曲线位置的 env（与 `TF_POOL_SINK` / `TF_MERGE_QUEUE` 同一手法）。
ENV_HISTORY = "TF_POOL_QUOTA_HISTORY"

#: 留多少天（magpie `quotaHistKept`）。
KEPT_DAYS = 45

#: 一个 key 最多留几个点（magpie `quotaHistMax`）。
MAX_POINTS = 6000

#: 两读相隔多久以内算「同一阵」、可以顶掉上一个点（magpie `quotaHistGap`）＝ 5 分钟。
GAP_S = 300

#: 同刻去抖窗口（magpie `quotaHistSame`）＝ 30 秒。
SAME_S = 30

#: 窗口终点漂移容差（magpie `quotaHistSlack`）＝ 5 分钟。
SLACK_S = 300

#: 「剩余百分比涨了多少才算重新注满」。magpie 三处字面量 `5`，这里给一个名字（判据 2）。
REFILL_PCT = 5.0


@dataclass(frozen=True, slots=True)
class QuotaPoint:
    """一次读数落成的点。

    * `at`：读数时刻（unix 秒）。
    * `left`：**剩余**百分比 0–100（不是已用）。
    * `start`：窗口起点（unix 秒）；没有窗口跨度时为 `None`。
    * `resets_at`：窗口终点（unix 秒）；厂商没给 deadline 时为 `None`。
    """

    at: int
    left: float
    start: int | None = None
    resets_at: int | None = None


def new_cycle(a: QuotaPoint, b: QuotaPoint) -> bool:
    r"""`b`（在 `a` 之后读到的）是不是**新的一窗**（而不是同一窗的继续）。

    六支，**顺序即优先级**（照 magpie `:153-177`）：

    1. 两个都没有 `resets_at` ⇒ 只看剩余涨没涨：`b.left > a.left + REFILL_PCT`。
    2. 只有一个有 `resets_at` ⇒ `True`（一个窗开始了，或者结束了）。
    3. `a.resets_at is not None and a.resets_at <= b.at` ⇒ `True`（它的重置时刻已经过了）。
    4. `moved = b.resets_at - a.resets_at`；`rolling = moved > 0 and abs(moved - (b.at - a.at))
       <= SLACK_S` —— 终点跟着读数一起往前挪的是滚动窗，**不是**固定窗的重置。
    5. `not rolling and abs(moved) <= SLACK_S and b.left > a.left + REFILL_PCT` ⇒ `True`：
       手动或厂商重置可以在终点不变的情况下把窗注满（小幅修正不算注满）。
    6. 兜底：`moved > (b.at - a.at + SLACK_S) or moved < -SLACK_S`。

    ★ ④⑤⑥ 只在**两个都有** `resets_at` 时才走到：magpie 的 `moved` 是
      `b.ResetsAt.Sub(a.ResetsAt)`，两边缺一个就没有「漂移」可言（②已经先接了那种情形）。
    """
    if a.resets_at is None and b.resets_at is None:
        return b.left > a.left + REFILL_PCT
    if a.resets_at is None or b.resets_at is None:
        return True
    if a.resets_at <= b.at:
        return True
    moved = b.resets_at - a.resets_at
    gap = b.at - a.at
    rolling = moved > 0 and abs(moved - gap) <= SLACK_S
    if not rolling and abs(moved) <= SLACK_S and b.left > a.left + REFILL_PCT:
        return True
    return moved > gap + SLACK_S or moved < -SLACK_S


def add_point(points: Sequence[QuotaPoint], point: QuotaPoint) -> list[QuotaPoint]:
    """把 `point` 接到 `points` 后面（照 magpie `addPoint` 的三步）—— **不改入参**。

    1. 不比最后一个新（`point.at <= last.at` 且 `point.left == last.left`）⇒ 原样返回。
    2. `k >= 2`：相邻两对都**不是**新周期，且 `flat`（相邻两点 `left` 差 `< 0.05`）或者
       `point.at - p1.at < GAP_S` ⇒ 顶掉最后一个。
    3. `k >= 1` 且 `point.at - last.at < SAME_S` 且 `not new_cycle(last, point)` ⇒ 也顶掉最后一个。
    4. 否则追加。

    ★ 入参是 `Sequence`，返回**新列表** —— 调用方拿着旧的那份照样能用。
    """
    out = list(points)
    k = len(out)
    if k > 0 and point.at <= out[k - 1].at and point.left == out[k - 1].left:
        return out
    if k >= 2:
        p1, p2 = out[k - 2], out[k - 1]
        if not new_cycle(p1, p2) and not new_cycle(p2, point):
            flat = abs(point.left - p2.left) < 0.05 and abs(p2.left - p1.left) < 0.05
            if flat or point.at - p1.at < GAP_S:
                out[k - 1] = point
                return out
    if k >= 1 and point.at - out[k - 1].at < SAME_S and not new_cycle(out[k - 1], point):
        out[k - 1] = point
        return out
    out.append(point)
    return out


def prune(points: Sequence[QuotaPoint], *, now: int) -> list[QuotaPoint]:
    """丢掉 `at < now - KEPT_DAYS*86400` 的，再只留尾部 `MAX_POINTS` 条（照 magpie `prune`）。"""
    cut = now - KEPT_DAYS * 86400
    kept = [p for p in points if p.at >= cut]
    if len(kept) > MAX_POINTS:
        kept = kept[-MAX_POINTS:]
    return kept


def hist_key(scope: str, account: str) -> str:
    """曲线里的 key：`"<scope>|<account 小写>"`（magpie `quotaHistKey` 的小写口径）。"""
    return f"{scope}|{account.lower()}"


def point_of(window: Mapping[str, object], *, at: int) -> QuotaPoint | None:
    """`window` 在 `at`（unix 秒）这次读到的点；**不可画**的窗口回 `None`（照 magpie `pointOf`）。

    跳过的五种：`unlimited` / `aside` 且不是池窗 / `family` 非空 / `name` 空 / `used` 不是数。
    `left = round(max(0, min(100, 100 - used)), 2)`；`resets_at` / `start` 有才写，
    `start = resets_at - span`（只在 `span > 0` 时）。

    ★ 入参形状照 magpie 的 `QuotaWindow`；本仓今天没有产出方（见模块头缺口 5）。
    """
    if not isinstance(window, Mapping):
        return None
    if window.get("unlimited"):
        return None
    if window.get("aside") and not _pool_window(window):
        return None
    if window.get("family"):
        return None
    if not window.get("name"):
        return None
    used = _num(window.get("used"))
    if used is None:
        return None
    left = round(max(0.0, min(100.0, 100.0 - used)), 2)
    resets_at: int | None = None
    start: int | None = None
    reset = _num(window.get("resets_at"))
    if reset is not None:
        resets_at = int(reset)
        span = _num(window.get("span"))
        if span is not None and span > 0:
            start = resets_at - int(span)
    return QuotaPoint(at=int(at), left=left, start=start, resets_at=resets_at)


# ---------------------------------------------------------------- 读盘 / 写盘


def load_history(*, root: pathlib.Path | str | None = None) -> dict[str, list[QuotaPoint]]:
    """读曲线：`{key: [点…]}`。

    **fail-open**：文件不在 / 读不出 / 解不开 / 形状不对 ⇒ `{}`，一条都不抛 —— 曲线是旁路，
    坏了不许把账本那一笔也拖下水。读的时候先读正式的，读不了再读 `.bak`（`lastgood` 的纪律）。
    """
    path = _history_path(root)
    try:
        text, _recovered = _lastgood().read_with_fallback(path, validate=_validate_text)
    except Exception:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[QuotaPoint]] = {}
    for key, items in raw.items():
        if not isinstance(key, str) or not isinstance(items, list):
            continue
        pts = [p for p in (_point_from_json(item) for item in items) if p is not None]
        if pts:
            out[key] = pts
    return out


def save_history(
    hist: Mapping[str, Sequence[QuotaPoint]], *, root: pathlib.Path | str | None = None
) -> pathlib.Path:
    """存曲线，返回写到的路径。

    ★ 一律走 `pool.lastgood.write_atomic()`（原子替换 +`.bak` 落后一次写）；
      **不许** `Path.write_text` / `open(..., "w")` 在这里出现。
    ★ 空列表的 key 不落盘（没有可画的点 = 这一窗没有历史，与 magpie 的 `delete` 同义）。
    """
    path = _history_path(root)
    body = json.dumps(_as_json(hist), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _lastgood().write_atomic(path, body, validate=_validate_text)
    return path


def _pool_window(window: Mapping[str, object]) -> bool:
    """magpie `PoolWindow()`：窗口自己声明了池名（`pool` 非空）才算池窗。"""
    return bool(window.get("pool"))


def _num(raw: object) -> float | None:
    """`int` / `float`（**不是** bool、不是 NaN / ±inf）⇒ 数；其余 ⇒ `None`（不猜成 0）。"""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _history_path(root: pathlib.Path | str | None = None) -> pathlib.Path:
    """曲线文件路径：`ENV_HISTORY` 优先，其次 `<root>/gates/diag/quota-history.json`。"""
    env = os.environ.get(ENV_HISTORY, "").strip()
    if env:
        return pathlib.Path(env)
    base = pathlib.Path(root) if root is not None else pathlib.Path(__file__).resolve().parents[2]
    return base.joinpath(*HISTORY_REL)


def _validate_text(text: str) -> None:
    """判「这份曲线还能不能当 lastgood」：解得开且顶层是对象（卡 A330 的纪律）。"""
    got = json.loads(text)
    if not isinstance(got, dict):
        raise ValueError("曲线的顶层不是对象")


def _point_from_json(raw: object) -> QuotaPoint | None:
    """一条落盘的记录 → `QuotaPoint`；形状不对 ⇒ `None`（坏一条不许拖垮整份）。"""
    if not isinstance(raw, dict):
        return None
    at = _num(raw.get("at"))
    left = _num(raw.get("left"))
    if at is None or left is None:
        return None
    start = _num(raw.get("start"))
    resets_at = _num(raw.get("resets_at"))
    return QuotaPoint(
        at=int(at),
        left=left,
        start=None if start is None else int(start),
        resets_at=None if resets_at is None else int(resets_at),
    )


def _point_to_json(point: QuotaPoint) -> dict[str, object]:
    """`QuotaPoint` → 落盘形状（`None` 的字段不写，读回来还是 `None`）。"""
    out: dict[str, object] = {"at": point.at, "left": point.left}
    if point.start is not None:
        out["start"] = point.start
    if point.resets_at is not None:
        out["resets_at"] = point.resets_at
    return out


def _as_json(hist: Mapping[str, Sequence[QuotaPoint]]) -> dict[str, list[dict[str, object]]]:
    """整份曲线 → 落盘形状（空列表的 key 略去；点按给进来的次序写，不重排）。"""
    out: dict[str, list[dict[str, object]]] = {}
    for key, points in hist.items():
        pts = [_point_to_json(p) for p in points]
        if pts:
            out[str(key)] = pts
    return out


def _lastgood():
    r"""懒加载 `pool.lastgood`（卡 A330 的写盘纪律）—— 三档兜底，与 `pool/queue.py:45` 同法。

    ★ 本模块会被按文件路径 exec（演练 / 独立拷贝的树），那时既没有 `pool` 包、也不保证
      `tools/` 在 `sys.path` 上 ⇒ 最后一档按同级文件路径加载。
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


#: `lastgood` 的模块句柄（懒加载；`None` = 还没加载过）。
_LASTGOOD = None

#: 公开面：判据 1 说「必须有且仅有这些名字」—— `dir()` 里的 `json` / `os` / `pathlib` 这些是
#: import 带进来的，不是本模块给调用方的零件；`__all__` 把边界写死，`from ... import *` 也只出这些。
__all__ = [
    "ENV_HISTORY",
    "GAP_S",
    "HISTORY_REL",
    "KEPT_DAYS",
    "MAX_POINTS",
    "REFILL_PCT",
    "SAME_S",
    "SLACK_S",
    "QuotaPoint",
    "add_point",
    "hist_key",
    "load_history",
    "new_cycle",
    "point_of",
    "prune",
    "save_history",
]
