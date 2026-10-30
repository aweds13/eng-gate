r"""每账号并发闸的**数据面**：读 `lanes.toml`，回"这个账号最多几张"（卡 A339）。

**防什么**：同一个号（`accounts.toml` 里的稳定 id）同时派好几张卡，会一起撞 vendor 的限流、
也会一起抢本机的内存与端口。判据本身（数有几张、到没到上限）在
`pool.guards.lane_guard`（纯函数，不读文件）；本模块只负责**把策略读出来**。

**为什么与 `guards` 分开**：`pool/guards.py` 的文件头逐字写着"不写文件、不 print、不起
进程"。把 `open()` 塞进去就破了那条规矩。所以：**读 TOML 只在这里**，`guards.lane_guard`
只收 `limit` / `queue` 两个整数。

**与 magpie 的关系（照抄形状，不是照抄理由）**：magpie 的每账号并发闸（`concurrency.go`）防的是
"同一个 key 打太多 → 429"；pool 这边若不设限，**真正的瓶颈是本机内存**（`gates/diag/gate_lock.py`
原文：一趟 17 门要 15–30 个无头 Edge）。常量与边界照抄 magpie，理由各是各的 —— 见文件内注释。

**坏文件不静默当空**：文件不存在 ⇒ `{}`（没配 = 没闸，这是"没要求"）；文件**在但读不懂**
（TOML 语法坏 / 某段不是整数 / 值越界）⇒ 抛 `LanesError`。★ 这两件事**必须分开**：
把坏的当空 = 悄悄松开一条判据，正是本仓最忌的那种"判不出来就放行"。

**边界（如实写）**：
- 本模块**不判活**（死租约由 `registry` 先清）、**不写文件**、**不起进程**、**不联网**。
- 键是 `accounts.toml` 的**稳定 id**（`tools/pool_accounts.py` 的 `list_rows` 排序键
  `(platform, id)`，例如 `codearts-1`），**不是** email / 用户名 —— 后者会变，租约里存不住。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomllib

#: `lanes.toml` 的相对位置（相对仓库根）。
LANES_REL = "tools/pool/lanes.toml"

#: 一个账号最多几张（逐字照抄 magpie `concurrency.go:41-47` 的 `maxConcurrency`）。
MAX_LIMIT = 1000

#: 队列上限的上界（同上 `maxQueueLimit`）。★ 本卡**不实现排队**，这个值只是"读进来不拒"。
MAX_QUEUE_LIMIT = 10000

#: 等多久的上界（同上 `maxQueueWait`），单位秒。★ 同上：留给下一张卡，本卡只做越界检查。
MAX_QUEUE_WAIT = 3600

#: 默认段的段名（`[default]`）。
DEFAULT_SECTION = "default"

#: 账号段的段名（`[accounts."<稳定 id>"]`）。
ACCOUNTS_SECTION = "accounts"


class LanesError(ValueError):
    """`lanes.toml` 读不了 / 内容不合法 —— **绝不是**"没配"（没配是空字典）。"""


@dataclass(frozen=True, slots=True)
class Lane:
    """一个账号的闸：`limit` 张同时在跑，`queue` 个能在门口等，`wait` 秒等到就走。

    ★ `limit == 0` = **不限**（magpie `concurrency.go:82` 同义：0 是"关掉闸"，不是"一个都不许"）。
    ★ `queue` 在本仓目前**只进文案**：pool 的派活是同步的，没有"在等"这个状态，
      所以它表达的是"允许多少个派活进程在闸门口等"，判据仍按 `limit` 算（见 `lane_guard`）。
    """

    limit: int = 0
    queue: int = 0
    wait: int = 0


def lanes_path(start: Path | str | None = None) -> Path:
    """`lanes.toml` 的绝对路径：`start`（默认仓库根）下的 `LANES_REL`。"""
    root = Path(start) if start is not None else Path(__file__).resolve().parents[2]
    return root / LANES_REL


def _as_int(value: object, *, where: str) -> int:
    """TOML 里的值必须是整数；`bool` 不算（Python 里 `True` 是 `int`，得挡掉）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise LanesError(f"{where} 必须是整数，读到的是 {type(value).__name__}：{value!r}")
    return int(value)


def _as_lane(section: object, *, where: str) -> Lane:
    """把一段 TOML 读成 `Lane`；越界 / 缺类型 ⇒ `LanesError`（**不夹到边界上**）。"""
    if not isinstance(section, dict):
        raise LanesError(f"{where} 必须是一段表，读到的是 {type(section).__name__}")
    known = {"limit", "queue", "wait"}
    unknown = sorted(str(key) for key in section if key not in known)
    if unknown:
        raise LanesError(f"{where} 有认不识的键：{'、'.join(unknown)}"
                         f"（只认 {'、'.join(sorted(known))}）")
    limit = _as_int(section.get("limit", 0), where=f"{where}.limit")
    queue = _as_int(section.get("queue", 0), where=f"{where}.queue")
    wait = _as_int(section.get("wait", 0), where=f"{where}.wait")
    if limit < 0 or limit > MAX_LIMIT:
        raise LanesError(f"{where}.limit = {limit} 越界（允许 0..{MAX_LIMIT}；0 = 不限）")
    if queue < 0 or queue > MAX_QUEUE_LIMIT:
        raise LanesError(f"{where}.queue = {queue} 越界（允许 0..{MAX_QUEUE_LIMIT}）")
    if wait < 0 or wait > MAX_QUEUE_WAIT:
        raise LanesError(f"{where}.wait = {wait} 越界（允许 0..{MAX_QUEUE_WAIT} 秒）")
    return Lane(limit=limit, queue=queue, wait=wait)


def load_lanes(path: Path | str | None = None) -> dict[str, Lane]:
    """读 `lanes.toml`：回 `{账号 id: Lane}`（外加 `"default"` 那个键）。

    - 文件**不存在** ⇒ `{}`（没配 = 没闸；调用方 `lane_for` 会退成全不限）。
    - 文件**在但坏**（TOML 语法 / 段不是表 / 值不是整数 / 越界）⇒ `LanesError`。
      ★ 绝不返回 `{}` —— 那就等于"配置文件坏了 ⇒ 悄悄松开判据"。
    """
    target = Path(path) if path is not None else lanes_path()
    if not target.exists():
        return {}
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise LanesError(f"lanes 配置读不了（{target}）：{exc} —— 修好它，别当没配") from exc

    lanes: dict[str, Lane] = {}
    known_sections = {DEFAULT_SECTION, ACCOUNTS_SECTION}
    unknown = sorted(str(key) for key in raw if key not in known_sections)
    if unknown:
        raise LanesError(f"lanes 配置有认不识的段：{'、'.join(unknown)}"
                         f"（只认 [{DEFAULT_SECTION}] 与 [{ACCOUNTS_SECTION}.<id>]）")
    if DEFAULT_SECTION in raw:
        lanes[DEFAULT_SECTION] = _as_lane(raw[DEFAULT_SECTION], where=f"[{DEFAULT_SECTION}]")
    accounts = raw.get(ACCOUNTS_SECTION, {})
    if not isinstance(accounts, dict):
        raise LanesError(f"[{ACCOUNTS_SECTION}] 必须是一段表，读到的是 {type(accounts).__name__}")
    for account in accounts:
        name = str(account).strip()
        if not name:
            raise LanesError(f"[{ACCOUNTS_SECTION}] 里有一段的账号 id 是空的")
        lanes[name] = _as_lane(accounts[account], where=f"[{ACCOUNTS_SECTION}.{name}]")
    return lanes


def lane_for(account: object, lanes: dict[str, Lane] | None = None) -> Lane:
    """这个账号用哪把闸：账号段 > `[default]` > 全不限（`Lane()`）。

    ★ 账号没配 ⇒ 退到 `[default]`；`[default]` 也没有 ⇒ `Lane(limit=0)` = **不限**。
      这是"没要求就不设限"，与"配置坏了"是两件事（坏的那条在 `load_lanes` 抛）。
    """
    rows = lanes or {}
    name = str(account or "").strip()
    if name and name in rows:
        return rows[name]
    return rows.get(DEFAULT_SECTION, Lane())


__all__ = [
    "ACCOUNTS_SECTION", "DEFAULT_SECTION", "LANES_REL", "MAX_LIMIT", "MAX_QUEUE_LIMIT",
    "MAX_QUEUE_WAIT", "Lane", "LanesError", "lane_for", "lanes_path", "load_lanes",
]
