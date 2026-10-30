"""pool 的「一分钟里派了几趟」闸 —— 移植自 magpie 的 MaxRPM（卡 A340 / T-AG542）.

★ 语义差别（照抄卡规格，不许含糊）：magpie 计的是**它转发的每一个 HTTP 请求**；
  pool 里一次「派活」背后是**一整个 CLI 会话**（几十到几百次上游请求）。
  ⇒ pool 的「每分钟派几次」与 magpie 的「每分钟请求几次」**不是同一个量**：
  本闸只能防「同一个号被同时/接连轰太多趟」，**防不了 vendor 侧的 RPM 429**
  （那个仍由 ``pool_quota`` 的四态负责；两者方向相反 —— 那个被动记 429，本闸主动数趟数）。
  不写这句话，下一个人会以为加了本闸就不会 429。

★ 算法逐字来自 magpie ``internal/gateway/rpm.go`` 的 ``reserve()``（``:122-138``）——
  **不是「数一数 60 秒里有几个」**，而是：
    ① ``prune``：丢掉 ``<= now - rpmSpan()`` 的前缀（``rpm.go:104-117``）；
    ② ``if len(ts) >= limit: at = ts[len(ts) - limit] + rpmSpan()``；
    ③ ``if d := at.Sub(now); longest > 0 && d > longest { 拒 }``。
  ``rpmSpan()``（``:55``）是 ``rpmWindow``（``:44`` = 一条）加 ``rpmSlack``（``:52`` = 一秒）
  ⇒ **实占 61 秒**。那 1 秒 slack 的理由逐字在源码注释（``rpm.go:46-51``）：
  「A request is counted when it starts to go, but the vendor counts it when it arrives: the first
  on a connection arrives later than the next ones by its dial and TLS handshake, so with the bare
  window the vendor could see one more than the limit in its own minute (TestMaxRPMWaitsForRoomInThe
  Minute went red under CI load, and does every time when the first is held 150ms on its way).」
  ⇒ 丢掉这 1 秒的后果正是「本地放行、上游 429」——
  ``tests/test_pool_rpm.py::test_reverse_rpm_window_without_slack`` 专门钉它。

★ 边界（如实写）：本模块是**纯判据 + 一个派生账本读写**：``decide()`` 不读钟、不读文件、
  不写文件、不 print、不起进程（``stamps`` 由调用方喂）；``wb_dispatch.py`` 负责把它接到占树之前。

★ 「判与写在同一把锁里」和「派活没起来就不占位」怎么同时满足（卡 A340 裁定 1，照 magpie 的做法）：
  magpie 的 ``reserve()``（``rpm.go:122-138``）是**在持锁时就把 ``at`` 追加进 ``l.m[who]``**，
  然后 ``giveBack()``（``:141-154``）在请求没用上时**按值删回去** —— 靠「写 + 失败回滚」，
  不是靠「晚点再写」。本模块照抄这两步：:func:`note_stamp`（写）与 :func:`give_back`（还）。
  ★ 如实说的缺口：magpie 的回滚挂在 ctx 取消上，pool **没有**等价的可取消边界 ——
    进程被强杀 / 异常退出**不会**还，只能等那一趟 61 秒后自己滑出窗口。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import tzinfo

    TZ: tzinfo
else:
    # 双导入是仓内既有口径（`plan.py:15-21` / `model_registry.py:44-50` 同款）：
    # 调用方可能把 `tools/` 放进 sys.path 后 `from pool import rpm`，也可能
    # `from tools.pool import rpm` —— 两种都要能 import。时区**只有这一处**。
    try:
        from pool_accounts import TZ
    except ImportError:  # pragma: no cover —— 只有 tools/ 不在 sys.path 时走这边
        from tools.pool_accounts import TZ  # type: ignore[assignment,no-redef]

__all__ = [
    "LONGEST_WAIT_S",
    "MAX_RPM",
    "STAMPS_REL",
    "WINDOW_S",
    "RpmDecision",
    "RpmError",
    "decide",
    "give_back",
    "load_rpm",
    "note_stamp",
    "now_tz",
    "read_stamps",
]

# 实占窗口：magpie 的 `rpmWindow`(60s) + `rpmSlack`(1s) —— **不是 60**，理由见文件头。
WINDOW_S = 61
# 一个号最多等多久：magpie 的 `rpmLongest`（2 * time.Minute）。等不到就立刻拒，不睡等。
LONGEST_WAIT_S = 120
# 上限：magpie 的 `MaxRPMLimit`（internal/provider/concurrency.go:185）。
MAX_RPM = 10000
# 派生账本（时间戳账）：一行是一**趟派活**，不是一次 HTTP 请求（见文件头）。
STAMPS_REL = ("gates", "diag", "pool-rpm.json")
# 人写配置：0 = 不限（关闸），键是账本的**稳定 id**（`pool_accounts.list_rows` 的那个 id）。
RPM_FILE = "rpm.toml"


class RpmError(ValueError):
    """每分钟闸的配置/账本读写有问题 —— 一律响亮点名，绝不许静默当 0."""


@dataclass(frozen=True, slots=True)
class RpmDecision:
    """一次判定的结果（恰好四项，不含任何建议字段）.

    ``allowed`` 说的是「**现在**能不能派」：``next_at`` 是最近一个能派的时刻，
    ``wait_s`` 是还要等多少秒（``allowed`` 为真时两者分别是 ``now`` 与 ``0.0``）。
    """

    allowed: bool
    next_at: datetime
    wait_s: float
    why: str


def now_tz() -> datetime:
    """带时区的「现在」—— 复用 ``tools/pool_accounts.py`` 的 ``TZ``，不新造第二个时区."""
    return datetime.now(TZ)


def _span() -> timedelta:
    """窗口长度（每次现算：反向钉子会定点改 ``WINDOW_S``，闭包存一份就抓不住）."""
    return timedelta(seconds=WINDOW_S)


def _check_limit(value: object, *, where: str) -> int:
    """0 到 ``MAX_RPM`` 之间，越界点名收到的值；**不许** clamp（人写错了要立刻说）."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RpmError(
            f"{where}：每分钟上限必须是整数（a limit on requests a minute is from "
            f"0 (none) to {MAX_RPM}, not {value!r}）"
        )
    if not 0 <= value <= MAX_RPM:
        raise RpmError(
            f"{where}：每分钟上限越界（a limit on requests a minute is from "
            f"0 (none) to {MAX_RPM}, not {value}）"
        )
    return value


def decide(
    account: str,
    stamps: Sequence[datetime],
    *,
    limit: int,
    now: datetime,
    longest: float = LONGEST_WAIT_S,
) -> RpmDecision:
    """三步逐字对应 magpie 的 ``reserve()``；**纯函数**（不读钟/文件，不 print，不起进程）.

    ``stamps`` 不带时区就按 ``now.tzinfo`` 补（**不假设 UTC**）；带时区的原样用。
    """
    _check_limit(limit, where=f"账号 {account!r} 的每分钟上限")
    tz = now.tzinfo
    given = [s if s.tzinfo is not None else s.replace(tzinfo=tz) for s in stamps]
    if limit == 0:
        return RpmDecision(True, now, 0.0, f"{account}：没开闸（每分钟上限 0 = 不限）")
    span = _span()
    floor = now - span
    # ① prune：`!ts[i].After(now - rpmSpan())` 的前缀全丢（即 <= now - 61s）。
    alive = sorted(s for s in given if s > floor)
    future = [s for s in alive if s > now]
    at = now
    if len(alive) >= limit:
        # ② 倒数第 limit 个 + 61 秒 —— 不是「数一数 60 秒里有几个」。
        at = alive[len(alive) - limit] + span
    wait = (at - now).total_seconds()
    if wait <= 0:
        why = f"{account}：这 {WINDOW_S} 秒里已派 {len(alive)} 趟，上限 {limit} 趟 —— 还有位置"
        return RpmDecision(True, now, 0.0, why)
    why = (
        f"{account}：这 {WINDOW_S} 秒里已派 {len(alive)} 趟，上限 {limit} 趟 —— "
        f"要到 {at.isoformat()} 才有位置（还要等 {wait:.0f} 秒）"
    )
    if longest > 0 and wait > longest:
        # ③ 超过最长等待就立刻拒，不睡等（magpie `rpmLongest`；等不到干等会把派活挂住）。
        why += f"；超过最长等待 {longest:g} 秒 ⇒ 现在就不派"
    if future:
        why += (
            f"；记录里有未来时间（{future[0].isoformat()} 晚于现在 {now.isoformat()}）"
            " ⇒ 按 prune 口径未过期，钟坏了也得拒"
        )
    return RpmDecision(False, at, wait, why)


def load_rpm(path: Path | str | None = None) -> dict[str, int]:
    """读人写的每分钟上限表（``[accounts."<稳定 id>"]``，0 = 不限）.

    文件不存在 ⇒ ``{}``（一条闸都没开）；坏 TOML / 负数 / 超 ``MAX_RPM`` ⇒ :class:`RpmError`
    —— **绝不许静默当 0**（0 = 不限 = 悄悄松开判据）。
    """
    target = Path(path) if path is not None else Path(__file__).resolve().parent / RPM_FILE
    if not target.exists():
        return {}
    try:
        with target.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise RpmError(f"读不懂每分钟闸配置 {target}（坏 TOML）：{exc}") from exc
    except OSError as exc:
        raise RpmError(f"读不了每分钟闸配置 {target}：{exc}") from exc
    accounts = data.get("accounts", {})
    if not isinstance(accounts, dict):
        raise RpmError(f"{target} 里的 [accounts] 必须是张表，不是 {type(accounts).__name__}")
    limits: dict[str, int] = {}
    for name, raw in accounts.items():
        limits[str(name)] = _check_limit(raw, where=f"{target} 里的 [accounts.{name}]")
    return limits


def _default_root() -> Path:
    """本模块自己推出来的树根（``tools/pool/rpm.py`` 往上三层）；调用方给了 ``root`` 就用它的."""
    return Path(__file__).resolve().parents[2]


def _stamps_path(root: Path | None) -> Path:
    base = _default_root() if root is None else Path(root)
    return base.joinpath(*STAMPS_REL)


def read_stamps(*, root: Path | None = None) -> dict[str, list[datetime]]:
    """读派生账本 ``gates/diag/pool-rpm.json``（键 = 账号稳定 id，值 = ISO 时刻数组）.

    文件不存在 ⇒ ``{}``；坏 JSON / 非表 / 坏时刻 ⇒ :class:`RpmError`（坏账本按「判不了」处理，
    不许当成「没派过」—— 那等于悄悄松开判据）。
    """
    target = _stamps_path(root)
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RpmError(f"读不懂每分钟闸账本 {target}：{exc}") from exc
    if not isinstance(raw, dict):
        raise RpmError(f"{target} 必须是张表（账号 id → 时刻数组），不是 {type(raw).__name__}")
    stamps: dict[str, list[datetime]] = {}
    for name, values in raw.items():
        if not isinstance(values, list):
            raise RpmError(f"{target} 里 {name!r} 的值必须是时刻数组")
        try:
            stamps[str(name)] = [datetime.fromisoformat(str(v)) for v in values]
        except ValueError as exc:
            raise RpmError(f"{target} 里 {name!r} 有时刻读不成 ISO：{exc}") from exc
    return stamps


def _write_stamps(target: Path, stamps: dict[str, list[datetime]]) -> None:
    """原子写（本仓文本一律纯 CRLF：``newline="\\r\\n"`` 让内建 open 自己翻译）."""
    payload = {name: [s.isoformat() for s in items] for name, items in sorted(stamps.items())}
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(body)
        fh.write("\n")
    os.replace(tmp, target)


def note_stamp(account: str, at: datetime, *, root: Path | None = None) -> None:
    """记一趟派活 —— **必须与判定在同一把锁里**（判完就写，占树没成再用 :func:`give_back` 还）.

    ★ 顺序是判据的一部分：对应 magpie ``reserve()`` 里「持锁时就把 ``at`` 追加进去」
      （``rpm.go:122-138``）。判之前写 ⇒ 一次中断白占一个分钟位；判之后不写 ⇒ 两个窗口双双放行。
    """
    if not account:
        raise RpmError("记一趟派活要有账号稳定 id（空字符串记不进去）")
    target = _stamps_path(root)
    stamps = read_stamps(root=root)
    stamps.setdefault(account, []).append(at if at.tzinfo is not None else at.replace(tzinfo=TZ))
    _write_stamps(target, stamps)


def give_back(account: str, at: datetime, *, root: Path | None = None) -> None:
    """把某一趟**还回去** —— 对应 magpie 的 ``giveBack``（``internal/gateway/rpm.go:141-154``）.

    语义逐条照那个函数（**不是**「删最后一条」）：
      · 在 ``stamps[account]`` 里**从后往前找第一个 ``== at``** 删掉（按值删）；
      · 找不到 ⇒ 什么也不做（幂等：重复还、还没记过的号都不许抛）；
      · 删空了 ⇒ 把这个号整条从表里删掉再落盘 —— 账本里**不留空数组**
        （空数组会被下一位读者当成「有记录但没时刻」，比没有更难查）。

    ``at`` 不带时区就按 :data:`TZ` 补（与 :func:`note_stamp` 同口径）。调用方负责持锁。
    """
    if not account:
        raise RpmError("还一趟派活要有账号稳定 id（空字符串还不了）")
    path = _stamps_path(root)
    stamps = read_stamps(root=root)
    items = stamps.get(account)
    if not items:
        return
    target = at if at.tzinfo is not None else at.replace(tzinfo=TZ)
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if (item if item.tzinfo is not None else item.replace(tzinfo=TZ)) == target:
            del items[index]
            break
    else:
        return
    if not items:
        del stamps[account]
    _write_stamps(path, stamps)
