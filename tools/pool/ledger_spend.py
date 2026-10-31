r"""pool 的花费记账（卡 A338 · T-AG540；对等 magpie `internal/budget`）。

**防什么**：`gates/diag/wb-usage.jsonl` 有 token 数但**没有账号维、没有金额**，于是
「这个号这个月还剩多少」仓里没人能回答。本模块给出**唯一**一份按账号累计的账：
`gates/diag/pool-spend.jsonl`，一行一次派活。

★ **不内置价目表**：价格是外部事实，内置一份就等于在仓里埋一个会过期的常量。
  `cost` 一律由调用方给（与 `tools/wb_dispatch.py:1430-1454 append_usage_line()`
  的既有纪律一致：「数和金额都由调用方给」）。本模块只做**记账与求和**，不做估算。

★ **口径逐字抄 `internal/budget/budget.go:69-75`**：
  `tokens = input + output + cache_write`；**默认不含** `cache_read`（`cache_reads=True` 才加）。

★ **坏行口径**：读写都**不许整份崩**。`sums()` 遇到坏行（不是 JSON、缺 `at`/`account`、
  `at` 不是 ISO 时间、数值字段不是数）**跳过并如实不计** —— 绝不当 0 混进累加
  （当 0 = 把说不清的账算成没花钱）。跳过了多少用 `audit()` 看得到。
  `forget()` 同理：**删不掉判不出的东西**，判不出的行一律留着。

★ **不自动忘账**：`forget()` 只在人显式 `reset` 时调 —— 判据路径里自动忘账 = 自动松开限额。

★ **有价 / 无价**：`Entry.priced` 只是这行账**有没有价**的标记（缺省 `True`，老行照样算有价），
  钱的数仍然只有 `cost` 一个来源、仍然由调用方给。`unpriced()` 数「没有价」的行 —— 它是提问，
  不是估算：本模块**仍然不算钱**（算术在 `tools/pool/pricing.py`，两边互不调用）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pool.cleared import Clear, hides

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import tzinfo

    TZ: tzinfo
else:  # pragma: no cover —— 运行时走这一支（原因见 pool/limits_policy.py 的 docstring 末段）
    from pool_accounts import TZ

#: 仓库根（`tools/pool/ledger_spend.py` 往上三层）；测试一律显式给 `root=`，不靠它。
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
#: 账文件位址（相对 `root`）。★ 另开一份，**不改** `wb-usage.jsonl` 的形状（它有两个读者）。
SPEND_REL: tuple[str, ...] = ("gates", "diag", "pool-spend.jsonl")
#: 一行里认的数字字段（`cache_write` 今天 `append()` 恒写 0，读方必须容忍它缺席）。
_COUNTERS: tuple[str, ...] = ("input_tokens", "output_tokens", "cache_write", "cache_read")


@dataclass(frozen=True, slots=True)
class Entry:
    """一行可用的账（`at` 已解析、数值已核过类型）。"""

    at: datetime
    account: str
    input_tokens: int
    output_tokens: int
    cache_write: int
    cache_read: int
    cost: float
    model: str = ""  # 清空用量要按模型清（F44）；缺席 = ""，不判整行坏
    priced: bool = True  # 有价/无价（F42）；缺席 = True（老行都是有价的老口径）


def _local(moment: datetime) -> datetime:
    """naive 时间按本仓时区（`pool_accounts.TZ`）解释，与留档口径一致。"""
    return moment.astimezone(TZ) if moment.tzinfo is not None else moment.replace(tzinfo=TZ)


def spend_path(root: Path | str | None = None) -> Path:
    """账文件路径：`root`（默认仓库根）下的 `gates/diag/pool-spend.jsonl`。"""
    base = Path(root) if root is not None else TOOL_ROOT
    return base.joinpath(*SPEND_REL)


def _lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()]


def _number(row: dict[str, object], key: str) -> int | None:
    """取一个计数；缺席 = 0，但**类型不对就判整行坏**（不是当 0）。"""
    value = row.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _entry(line: str) -> Entry | None:
    """解析一行；判不出来 ⇒ `None`（调用方跳过并计数，不崩、不当 0）。"""
    try:
        parsed: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    row = cast("dict[str, object]", parsed)
    account = row.get("account")
    stamp = row.get("at")
    if not isinstance(account, str) or not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    counters: dict[str, int] = {}
    for key in _COUNTERS:
        count = _number(row, key)
        if count is None:
            return None
        counters[key] = count
    raw_cost = row.get("cost", 0.0)
    if isinstance(raw_cost, bool) or not isinstance(raw_cost, int | float):
        return None
    priced = row.get("priced", True)
    if not isinstance(priced, bool):
        return None
    return Entry(
        at=_local(moment),
        account=account,
        input_tokens=counters["input_tokens"],
        output_tokens=counters["output_tokens"],
        cache_write=counters["cache_write"],
        cache_read=counters["cache_read"],
        cost=float(raw_cost),
        model=raw_model if isinstance(raw_model := row.get("model"), str) else "",
        priced=priced,
    )


def append(
    account: str,
    card: str,
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cost: float,
    at: datetime,
    root: Path | str | None = None,
) -> Path:
    """**追加**一行（永不覆盖：`open("a")`，绝不 `open("w")`）；返回写到的路径。"""
    path = spend_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": _local(at).isoformat(),
        "account": account,
        "card": card,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cache_write": 0,
        "cache_read": int(cache_read),
        "cost": float(cost),
    }
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
    return path


def sums(
    account: str,
    start: datetime,
    end: datetime,
    *,
    cache_reads: bool = False,
    root: Path | str | None = None,
    clears: Sequence[Clear] | None = None,
) -> tuple[int, float, int]:
    """`(tokens, cost, calls)`：只算 `start <= at < end`（**左闭右开**）里该账号的行。

    `tokens = input + output + cache_write`，`cache_reads=True` 才 `+ cache_read`
    （`budget.go:69-75`）。坏行**跳过**（不当 0）；文件不存在 ⇒ `(0, 0.0, 0)`。
    """
    path = spend_path(root)
    if not path.exists():
        return 0, 0.0, 0
    low = _local(start)
    high = _local(end)
    tokens = 0
    cost = 0.0
    calls = 0
    for line in _lines(path):
        entry = _entry(line)
        if entry is None or entry.account != account:
            continue
        if clears is not None and hides(clears, entry.account, entry.model, entry.at):
            continue  # ★ 只有显式给 clears 才过滤（clears=None = magpie 的 Visit 面）
        if not low <= entry.at < high:
            continue
        tokens += entry.input_tokens + entry.output_tokens + entry.cache_write
        if cache_reads:
            tokens += entry.cache_read
        cost += entry.cost
        calls += 1
    return tokens, cost, calls


def unpriced(
    account: str, start: datetime, end: datetime, *, root: Path | str | None = None
) -> int:
    """`start <= at < end`（**左闭右开**，与 `sums()` 同口径）里该账号**没有价**的行数。

    「没有价」= 那一行的 `priced` 是 `False`（老行没有这个键 ⇒ 缺省 `True`，算有价）。
    口径照 `sums()`：坏行**跳过**（不当「有价」也不当「无价」，只是不计）；文件不存在 ⇒ `0`。

    ★ 只**数**，不估：本模块仍然不算钱（算术在 `tools/pool/pricing.py`）。返回 0 时调用方
      **不许**打印 `"0 calls unpriced"` —— 一行「0 条无价」除了噪声什么都不是。
    """
    path = spend_path(root)
    if not path.exists():
        return 0
    low = _local(start)
    high = _local(end)
    missing = 0
    for line in _lines(path):
        entry = _entry(line)
        if entry is None or entry.account != account or entry.priced:
            continue
        if not low <= entry.at < high:
            continue
        missing += 1
    return missing


def audit(*, root: Path | str | None = None) -> dict[str, int]:
    """坏行清点 `{"lines", "usable", "damaged"}` —— `sums()` 跳过多少，这里才看得见。"""
    path = spend_path(root)
    if not path.exists():
        return {"lines": 0, "usable": 0, "damaged": 0}
    lines = _lines(path)
    usable = sum(1 for line in lines if _entry(line) is not None)
    return {"lines": len(lines), "usable": usable, "damaged": len(lines) - usable}


def forget(account: str, before: datetime, *, root: Path | str | None = None) -> int:
    """把**该账号**早于 `before` 的行另存到 `<名>.forgotten-<stamp>.jsonl` 并从账里删掉。

    返回删了几行。**只在人显式 `reset` 时调**：判据路径里自动忘账 = 自动松开限额。
    判不出的行与别的账号的行一律留着（删不掉判不出的东西）。stamp 取自 `before`，不看钟。
    """
    path = spend_path(root)
    if not path.exists():
        return 0
    cut = _local(before)
    keep: list[str] = []
    moved: list[str] = []
    for line in _lines(path):
        entry = _entry(line)
        if entry is not None and entry.account == account and entry.at < cut:
            moved.append(line)
            continue
        keep.append(line)
    if not moved:
        return 0
    archive = path.with_name(f"{path.stem}.forgotten-{cut.strftime('%Y%m%dT%H%M%S')}.jsonl")
    with archive.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(moved) + "\n")
    body = "\n".join(keep)
    staging = path.with_name(f"{path.name}.rewrite")
    staging.write_text(body + "\n" if body else "", encoding="utf-8", newline="\n")
    staging.replace(path)
    return len(moved)
