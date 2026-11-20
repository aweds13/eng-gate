"""搜索 API 的 vendor 表、key 串解析、拒绝 → 七值（卡 A372 · F56）。

★ 本模块只做三件事 —— 判据一条都不在这里：
  1. 读 `tools/pool/search-vendors.toml`（vendor 表：base / key_env / key 是否必需 /
     哪些状态码算「余额耗尽」）；
  2. 把一串凭据（`k1,k2,k3` 或换行分隔）解析成 key 列表并去重；
  3. 把上游的状态码翻译成 pool 自己的语言：七值走 `gateway.classify`、rest 秒数走
     `pool_quota.rest_after` 的搜索档、轮转走 `route.rotate`、沉底走 `pool_sink`、
     打码走 `pool_accounts.mask_search_key`。

★ **不许**在这里写第二份 rest 数字表、第二份分类正则，也不许自己算 key 的身份 ——
  key 身份只有 `pool_quota.search_key_id` 一份（判据 2），rest 数字只有 `pool_quota`
  一份（判据 3/6）。本模块里查得到任何一个 rest 秒数都是错的。

★ 为什么要有这一层：搜索 vendor 与号池的「号」不是一回事 —— 一个 vendor 下挂多把 key，
  被拒才换下一把（原件 `internal/gateway/search_api.go:159-160` `if !refused { break }`），
  每把 key 各自 rest（`search_keys.go:41-44` 的 `searchKeyID`）。这些语义底层四件套
  （route / pool_quota / pool_sink / pool_accounts）都已经有了，本模块只是把它们接起来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

import pool_accounts
import pool_quota

from pool import route as pool_route
from pool import sink as pool_sink

#: vendor 表就在本模块旁边（与 rpm.toml / model-registry.toml 同一个体例）。
VENDORS_FILE = Path(__file__).with_name("search-vendors.toml")
#: 没点名 vendor 时的默认值（本仓今天唯一有真端点的一套）。
DEFAULT_VENDOR = "tavily"

#: key 串的分隔：逗号 / 分号 / 空白（含换行）都算。
_SPLIT_RE = re.compile(r"[,;\s]+")


class SearchError(ValueError):
    """vendor 表读不懂 / key 串不可用 —— 命令壳据此退非零，**不带着坏表起服务**。"""


@dataclass(frozen=True, slots=True)
class Vendor:
    """一个搜索 vendor（表里的一段 `[vendor.<id>]`）。

    `out_of_credit` 是该 vendor **自己**的「没钱了」状态码（表里叫 `out_of_credit_status`）；
    「拒绝类」的大集合在 `pool_quota.SEARCH_REFUSED_STATUS`（真源只有那一份），
    这里只补各家多出来的那几个。
    """

    name: str
    base: str = ""
    key_env: str = ""
    key_required: bool = True
    out_of_credit: tuple[int, ...] = ()

    @property
    def has_endpoint(self) -> bool:
        """登记了端点没有（`base` 空 = 没登记，不是「不支持」）。"""
        return bool(self.base)


def _as_status_tuple(raw: Any, *, name: str) -> tuple[int, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise SearchError(f"vendor {name!r} 的 out_of_credit_status 必须是整数列表，拿到 {raw!r}")
    out: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            raise SearchError(f"vendor {name!r} 的 out_of_credit_status 里有非整数：{item!r}")
        out.append(int(item))
    return tuple(out)


def load_vendors(path: Path | str | None = None) -> dict[str, Vendor]:
    """读 vendor 表。读不懂/结构不对 ⇒ `SearchError`（**不猜、不回落成空表**）。"""
    p = Path(path) if path is not None else VENDORS_FILE
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SearchError(f"读不到 vendor 表 {p}：{exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SearchError(f"vendor 表 {p} 不是合法 TOML：{exc}") from exc
    table = raw.get("vendor")
    if not isinstance(table, dict) or not table:
        raise SearchError(f"{p} 里没有 [vendor.<id>] 段 —— 搜索 vendor 表长这样：[vendor.tavily]")
    out: dict[str, Vendor] = {}
    for name, row in table.items():
        if not isinstance(row, dict):
            raise SearchError(f"vendor {name!r} 应该是一张表（[vendor.{name}]）"
                              f"，拿到 {type(row).__name__}")
        key_required = row.get("key_required", True)
        if not isinstance(key_required, bool):
            raise SearchError(f"vendor {name!r} 的 key_required 必须是 true/false"
                              f"，拿到 {key_required!r}")
        out[str(name)] = Vendor(
            name=str(name),
            base=str(row.get("base") or ""),
            key_env=str(row.get("key_env") or ""),
            key_required=key_required,
            out_of_credit=_as_status_tuple(row.get("out_of_credit_status"), name=str(name)),
        )
    return out


def vendor_of(name: str | Vendor | None = None, *,
              table: dict[str, Vendor] | None = None) -> Vendor:
    """按名字取一个 vendor（`None` ⇒ 默认那一个）。表里没有 ⇒ `SearchError` 点名。"""
    if isinstance(name, Vendor):
        return name
    book = load_vendors() if table is None else table
    wanted = DEFAULT_VENDOR if name is None else str(name)
    hit = book.get(wanted)
    if hit is None:
        known = "、".join(sorted(book)) or "（空表）"
        raise SearchError(f"vendor 表里没有 {wanted!r}；登记过的有：{known}")
    return hit


def parse_keys(raw: str | Iterable[str] | None) -> list[str]:
    """把一串凭据解析成 key 列表：逗号/分号/空白分隔，去空、去重、保序。

    ★ 也吃 `TAVILY_API_KEY=tvly-xxx` 这种「名字=值」的形状（只取值那一半）——
      人从 .env 里整行粘过来是最常见的用法，为此报错只会逼人绕路。
    ★ 明文只在这一个函数的返回值里活着：不打印、不落盘（判据 2(b)）。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        pieces: Iterable[str] = _SPLIT_RE.split(raw)
    else:
        pieces = list(raw)
    out: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        text = str(piece).strip().strip('\'"')
        if not text:
            continue
        if "=" in text:
            text = text.split("=", 1)[1].strip().strip('\'"')
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def key_label(index: int, key: str) -> str:
    """`key 2 (tvly-...mnop)` —— 编号从 1 起，key 一律走打码（原件 `keyLabel`）。

    ★ 打码只有 `pool_accounts.mask_search_key` 一份（判据 5）；本函数不自己截串。
    """
    return f"key {int(index) + 1} ({pool_accounts.mask_search_key(key)})"


def refused(status: int, *, vendor: str | Vendor | None = None,
            table: dict[str, Vendor] | None = None) -> bool:
    """这个状态码算「被拒」吗 —— 只有被拒才换下一个 key（判据 4 的那一档）。"""
    code = int(status)
    if code in pool_quota.SEARCH_REFUSED_STATUS:
        return True
    if vendor is None:
        return False
    try:
        hit = vendor_of(vendor, table=table)
    except SearchError:
        return False
    return code in hit.out_of_credit


def kind(status: int, body: bytes | str = b"") -> str:
    """上游状态码 → pool 的七值（**调 `gateway.classify`，不重写分类**）。"""
    from pool import gateway  # 惰性导入：gateway 是重模块，且它不反过来依赖本模块

    payload = body if isinstance(body, bytes) else str(body).encode("utf-8")
    return gateway.classify(int(status), payload)


def rest_for(*, vendor: str | Vendor, status: int, retry_after_s: int | None = None,
             reset_at: str | None = None, now: Any = None) -> dict[str, Any]:
    """这一把 key 该 rest 多久 —— 走 `pool_quota.rest_after` 的搜索档（数字不在本模块）。

    `why` 传 `"other"` 是**故意的**：搜索档由 `search_vendor` 决定，秒数与 `by` 全在
    `pool_quota.search_rest_for` 里；这里再按七值猜一遍 why 就是复制第二份判据。
    """
    name = vendor_of(vendor).name if not isinstance(vendor, Vendor) else vendor.name
    return pool_quota.rest_after(why="other", status=int(status), reset_at=reset_at,
                                 search_vendor=name, retry_after_s=retry_after_s, now=now)


def order(keys: Sequence[str], *, pool: str, turns: dict[str, int] | None = None,
          resting: Sequence[bool] | None = None) -> list[int]:
    """key 的轮转顺序：`route.rotate` + `resting_last`（休息的排后，**不丢弃**）。

    `turns` 由调用方持有（`route.rotate` 的 docstring 写着「本函数不落盘」）；
    座位 key 用打码后的 label，所以就算被打印出来也不带明文。
    """
    flags = [bool(x) for x in (resting or ())]
    if len(flags) < len(keys):
        flags.extend([False] * (len(keys) - len(flags)))
    seats = [pool_route.Seat(key=key_label(i, k), resting=flags[i]) for i, k in enumerate(keys)]
    return pool_route.rotate(seats, pool=pool, turns=turns)


def sink_key(vendor: str, index: int) -> str:
    """沉底键：`sink.key_of` 要两段式（卡 A351），这里给 `<vendor>/key N`。"""
    return pool_sink.key_of(str(vendor), f"key {int(index) + 1}")


def sunk(vendor: str, index: int, *, root: Path | str | None = None) -> bool:
    """这一把 key 正在沉底吗（撞过限流的沉底，别再去试）。"""
    return pool_sink.sunk_at(sink_key(vendor, index), root=root) is not None


def sink(vendor: str, index: int, *, root: Path | str | None = None) -> None:
    """把这一把 key 沉底（只有限流类才沉 —— 判定在调用方，用 `pool_sink.should_sink`）。"""
    pool_sink.sink(sink_key(vendor, index), root=root)


def resting_keys(model: str, *, now: Any = None, root: Path | str | None = None) -> dict[str, int]:
    """「现在哪些 key 还在 rest」一次取全：`{key_id: 还要等几秒}`，能用的不列。

    `key_id` 是 `pool_quota.search_key_id` 那种不含明文的身形；秒数 <= 0 视为已经好了。
    """
    import datetime as _dt

    if isinstance(now, _dt.datetime):
        clock = now
    elif isinstance(now, str) and now:
        parsed = pool_quota.parse_reset(now)
        clock = parsed if parsed is not None else _dt.datetime.now(_dt.timezone.utc)
    else:
        clock = _dt.datetime.now(_dt.timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=_dt.timezone.utc)
    out: dict[str, int] = {}
    base = Path(root) if root is not None else pool_quota.ROOT
    for rec in pool_quota.read_search_records(model, root=base):
        rest = rec.get("rest") if isinstance(rec.get("rest"), dict) else {}
        until = pool_quota.parse_reset(str(rest.get("rest_until") or ""))
        if until is None:
            continue
        left = int((until - clock).total_seconds())
        if left > 0:
            out[str(rec.get("key_id") or "")] = left
    return out

