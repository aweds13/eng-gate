r"""整窗估算的接线层：账本 + 用量日志 → `Window` → `holds.estimate`（卡 A369 · T-AG654）。

## 为什么有它（F26 的最后一米）

判据层（`tools/pool/holds.py`，卡 A334）与分子（`tools/wb_dispatch.py::usage_in`）
都已经在生产代码里，但**生产侧零 import** —— `holds.estimate()` 的 `why` / `why_text`
没有任何出口，「估不出来」这句话没人读得到。本模块就是那根线：账本的
`[account.quota]` 一行 → 一个 `holds.Window`；`gates/diag/wb-usage.jsonl` 的分子
→ `routed_tokens`；再整窗交给 `holds.estimate()`。

## 硬边界（卡 A369「不许做」逐条）

* **不估 0**：`used_percent` 缺键 ⇒ `Window(used=None)` ⇒ 判据层回 `"-"`；
  本模块不补 `0.0`，也不把 `tokens=0` 与 `why=""` 拼成「整窗就是 0」。
* **不写账本**：`[account.quota].used_percent` 的写入面只归
  `tools/pool_accounts.py::record_probe_result()`（卡 E97）。本模块**一个字节都不写盘**。
* **不造数据**：窗口边界（`reset_at` / `span`）今天在真账本里零来源 ⇒
  缺就是缺（`Window` 留默认值），不按「30 天」或「此刻」编一个出来。
* **零网络、零 sleep**：只读本机文件；`now` 由调用方给（不给才补一次钟）。
* **算式只有一份**：放大比例与五因顺序都在 `holds.estimate()` 里，
  本模块只调用（`tests/test_holds_wiring.py::test_only_one_scale` 用 `ast` 钉着）。

## 三处口径如实记（都不是本模块能自己解决的）

1. **分子只来自 `usage_in()`**（判据 5）：本模块**不打开** `gates/diag/wb-usage.jsonl`
   —— 那份日志的读法、时区（+08:00）、区间 `[start, end)`、模型名归一、dry-run 排除，
   全部是 `tools/wb_dispatch.py::usage_in` 的判据（`ast` 钉子同样盯着：
   本模块连 `json` / `wb_status` 都不 import，想抄也抄不成）。
2. **日志起点来自 `usage_first_at()`**（同一份日志、同一套解析）：`holds.estimate()`
   的 `log` 因要比「窗口起点 vs 日志起点」。拿不到就传 `None`，让判据层自己判，
   本模块不替它编一个起点。
3. **一个号一行**：`model` 取该号批准集的第一条（今天只有 `codearts-1` 非空）。
   同一个号批准了多个模型时，这一格只代表其中一条 ⇒ 数不是「这个号」的总量，
   **别把它当总账**（缺口，进 changelog 的 gaps）。

## 账本位点（为什么锚在读数根上，不锚在 `tools/` 上）

`tools/pool_accounts.py::find_ledger()` 按 `TOOL_ROOT` 向上找 —— 那是「派活器/探测」
的视角。本模块的调用方里有**读数面**（`tools/pipeline_view.py` 的 `--root` 可以指到
任何假仓 / 卡树），跟着 `TOOL_ROOT` 走就会把**宿主机那份真账本**读进一份假仓的读数里 ——
判据跟着宿主目录形状走，正是卡 E49 / E70 禁的那件事。所以这里锚 `root`：
`TF_ACCOUNTS_TOML` > 从 `root` 向上找 `infra/pool/accounts.toml` > 没有（缺什么说什么）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from pool import holds

try:  # 与 tools/pool/*.py 同一套降级：落地桩只拷部分文件，tools/ 不在 sys.path 也不许炸
    import pool_accounts
except ImportError:  # pragma: no cover —— 独立拷贝的树
    from tools import pool_accounts  # type: ignore[no-redef]

if TYPE_CHECKING:
    from collections.abc import Callable

#: 与 `tools/pool_accounts.py:47` 同一口径：本仓的「本地时间」是 +08:00。
TZ = timezone(timedelta(hours=8))

#: 账本锚点（照 `tools/pool_accounts.py::ANCHOR` 的同一串，但**锚在读数根上**）。
LEDGER_ANCHOR: tuple[str, ...] = ("infra", "pool", "accounts.toml")

#: 账本位点的显式覆盖（与 `pool_accounts.find_ledger()` 同一个变量名，语义一致）。
LEDGER_ENV = "TF_ACCOUNTS_TOML"

#: 账本找不到时那句（`tools/pipeline_view.py` 的 `BLOCKS["holds"]["missing_note"]`
#: 与这句**逐字相同** —— 两个出口说同一句话，别一边一个措辞）。
MISSING_LEDGER_NOTE = "没有账号账本（infra/pool/accounts.toml 或 TF_ACCOUNTS_TOML）"

#: 一行里的 `cost` **没有价**（照 `tools/pool/ledger_spend.py` 的 `priced=False` 先例）：
#: `usage_in()` 的金额恒 `0.0`（仓里没有计价表）⇒ 那一格写 `False` 才不会被读成
#: 「花了 0 元」。缺省不写键 = 读成有价 = 把「判不了」洗成「没花钱」，所以每行都显式写。
PRICED = False


@dataclass(frozen=True)
class HoldsReading:
    """一次读数：`rows=None` = 账本读不到（缺什么说什么）；`rows=[]` = 账本在、
    一个号都没有（**也不许静默**，`note` 必须非空）。

    `ledger` 只是位点（绝对路径 / 空串），**不写进读数行** —— 账本在仓外，
    把宿主机路径写进 `--json` 会让同一份读数在两台机器上不同（幂等口径）。
    """

    rows: list[dict] | None
    note: str = ""
    ledger: str = ""


def ledger_path_for(root: Path) -> Path | None:
    """账本位点：显式环境变量 > 从**读数根**向上找锚点 > `None`。

    ★ 锚 `root`（不是 `TOOL_ROOT`）：读数根指到假仓 / 卡树时不许摸到宿主机
      那份真账本（卡 E49 / E70：判据不许跟宿主目录形状绑定）。
    """
    env = (os.environ.get(LEDGER_ENV) or "").strip()
    if env:
        cand = Path(env).expanduser()
        return cand.resolve() if cand.is_file() else None
    start = Path(root).resolve()
    for base in (start, *start.parents):
        anchor = base.joinpath(*LEDGER_ANCHOR)
        if anchor.is_file():
            return anchor
    return None


def model_of(account: dict) -> str:
    """这一格用哪个模型：该号 `approved_models` 的第一条；一条都没有 ⇒ `""`。"""
    models = account.get("approved_models")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _percent(quota: object) -> float | None:
    """`[account.quota].used_percent` → `float | None`（**缺键 = 未观测**，不是 0）。

    ★ 越界 / 非数**不在这里判**：那份判据只有 `tools/pool_accounts.py::_check_used_percent`
      （`load_ledger()` 时已经跑过，坏值当场抛）。这里只做搬运，不做第二套校验。
    """
    if not isinstance(quota, dict):
        return None
    value = quota.get("used_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _moment(value: object) -> datetime | None:
    """账本里的 ISO 时刻 → 带时区的 `datetime`；不是串 / 解不开 ⇒ `None`（不猜）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=TZ)


def window_from_account(account: dict, *, model: str = "") -> holds.Window:
    """账本的 `[[account]]` → `holds.Window`（**只搬**，一个数都不补）。

    * `used`：缺键 / 不是数 ⇒ `None`（判据层回 `"-"`，绝不当 0）。
    * `resets_at`：`[account.quota].reset_at`（ISO 串）。
    * `span_s`：`[account.quota].span_days × 86400`。
    * `reset_secs` 恒 `0.0`：账本里没有这个键、也没有任何写方 —— 不编一个
      「还剩多少秒」出来（缺口 2 / 未坐实项 2）。

    ★ `reset_at` / `span_days` **今天在真账本里一条都没有**（五个号全缺）⇒
      到这里就是 `resets_at=None, span_s=0` ⇒ 判据层要么回 `"-"`（没 `used`），
      要么回 `clock`（有 `used`、没边界）。两条都是**如实**，不是凑数。
    """
    quota = account.get("quota")
    used = _percent(quota)
    resets_at = _moment(quota.get("reset_at")) if isinstance(quota, dict) else None
    span_s = 0
    span_days = quota.get("span_days") if isinstance(quota, dict) else None
    if (isinstance(span_days, (int, float)) and not isinstance(span_days, bool)
            and span_days > 0):
        span_s = int(round(float(span_days) * 86400))
    return holds.Window(model=model or model_of(account), span_s=span_s,
                        used=used, resets_at=resets_at)


def _usage_in() -> Callable[..., tuple[int, float]]:
    """分子那唯一一份（判据 5）—— **函数级** import，见下。

    ★ 为什么不在模块级 `from wb_dispatch import usage_in`：`wb_dispatch` 模块级
      import 了 `workbench_bridge`，后者 import 了 `pipeline_view`；而读数面
      （`pipeline_view`）又调本模块 ⇒ 模块级直连成环。函数级 import 不是
      「第二份」：拿到的仍是同一个 `usage_in` 函数对象，判据一个字没抄。
    """
    from wb_dispatch import usage_in

    return usage_in


def numerator(model: str, start: datetime, end: datetime, *, root: Path,
              usage_in_fn: Callable[..., tuple[int, float]] | None = None) -> tuple[int, float]:
    """这一窗这一段路由了多少 —— **只调** `tools/wb_dispatch.py::usage_in`（判据 5）。

    时区 +08:00、区间 `[start, end)`、按模型、别名归一、dry-run 排除、读不出来回
    `(0, 0.0)` —— 六条口径全在那份实现里，本函数一条都不复制。

    `model` 为空（这个号没有批准模型）或区间不可用（`end <= start`）⇒
    `(0, 0.0)`：那是「**没有分子**」，不是「分子是 0」—— 判据层据 `used` 与边界
    判「不估」，不会把一个 0 当读数。
    """
    if not model or end <= start:
        return 0, 0.0
    fn = usage_in_fn if usage_in_fn is not None else _usage_in()
    tokens, cost = fn(model, start, end, root=root)
    return int(tokens), float(cost)


def first_log_at(root: Path,
                 *, fn: Callable[..., datetime | None] | None = None) -> datetime | None:
    """`gates/diag/wb-usage.jsonl` 的**日志起点**（只调 `wb_dispatch.usage_first_at`）。

    读不出来 ⇒ `None`（起点未知由判据层判，本模块不编一个时间）。
    """
    if fn is None:
        from wb_dispatch import usage_first_at

        fn = usage_first_at
    try:
        return fn(root=root)
    except (OSError, ValueError):
        return None


def holds_row(account: dict, *, root: Path, now: datetime, model: str = "",
              usage_in_fn: Callable[..., tuple[int, float]] | None = None,
              first_log_fn: Callable[..., datetime | None] | None = None) -> dict:
    """一个号一行：整窗读数 + **为什么估不出来**（原串 `why` + 人话 `why_text`）。

    ★ 边界与因只问 `holds.holds_bounds()`（判据 3 的顺序），数只问
      `holds.estimate()`（判据 5/6 的算式与后三因）。本模块两者都不抄。
    ★ 没有边界（今天五个号都是这样）⇒ **不去碰日志**（分子与起点都不需要）：
      少一次大文件读取，也少一次 `wb_dispatch` 的重 import。
    """
    window = window_from_account(account, model=model)
    start, end, _why = holds.holds_bounds(window, now)
    tokens_in, cost_in, log_at = 0, 0.0, None
    if start is not None and end is not None:
        tokens_in, cost_in = numerator(window.model, start, end, root=root,
                                       usage_in_fn=usage_in_fn)
        log_at = first_log_at(root, fn=first_log_fn)
    estimate = holds.estimate([window], routed_tokens=tokens_in, routed_cost=cost_in,
                              first_log_at=log_at, read_at=now)[0]
    why = estimate.why
    why_text = holds.why_text(why)
    return {
        "account": str(account.get("id") or ""),
        "platform": str(account.get("platform") or ""),
        "model": window.model,
        "used_percent": window.used,
        "why": why,
        "why_text": why_text,
        "tokens": int(estimate.tokens),
        "cost": float(estimate.cost),
        "priced": PRICED,
        "since": estimate.since.isoformat() if isinstance(estimate.since, datetime) else None,
    }


def _empty_ledger(path: Path) -> bool:
    """「零号账本」与「坏账本」分开（只数 `[[account]]` 有几条，不做第二套校验）。

    `pool_accounts.load_ledger()` 对零号账本抛 `LedgerError`（那是它对「空账本」
    的判据，本模块不复制）。但读数面要说清「账本在、只是一个号都没有」——
    它不是「账本读不到」，也不该拿 `null` 静默。
    """
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    accounts = raw.get("account")
    # ★ TOML 里根本没有 [[account]] 时取出来是 None（不是空 list）—— 两种都算「零号」。
    #   只认空 list 会让「账本存在、但一个号都没写」掉进「读不了」那一档（措辞就错了）。
    return not accounts


def read_holds(root: Path, *, now: datetime | None = None,
               ledger_path: Path | None = None, model: str = "",
               usage_in_fn: Callable[..., tuple[int, float]] | None = None,
               first_log_fn: Callable[..., datetime | None] | None = None) -> HoldsReading:
    """账本 → 每个号一行整窗读数。**只读**：零网络、零 sleep、**不写盘**。

    三种结局，**各有各的说法**（不许混成一种）：

    * 账本读不到 ⇒ `rows=None` + `note=MISSING_LEDGER_NOTE`（缺什么说什么）；
    * 账本在、一个号都没有 ⇒ `rows=[]` + 一句为什么（空表 ≠ 没来源）；
    * 账本坏（`used_percent` 越界 / 重复 id / TOML 坏）⇒ **原样抛**
      `pool_accounts.LedgerError`（不洗成「未观测」；判据只有 `_check_used_percent` 一份）。

    `now` 不给才补一次钟（`holds_bounds()` 的「区间含不含此刻」要它）——
    读数里**不落**这个时刻（`--json` 的冷跑/热跑要逐字节相同）。
    """
    path = ledger_path if ledger_path is not None else ledger_path_for(root)
    if path is None:
        return HoldsReading(rows=None, note=MISSING_LEDGER_NOTE)
    try:
        data = pool_accounts.load_ledger(path)
    except pool_accounts.LedgerError:
        if _empty_ledger(path):
            return HoldsReading(
                rows=[],
                note=f"账本里一个号都没有（{Path(path).name} 里没有 [[account]]）"
                     " ⇒ 没有可估的窗口（这不是「整窗 0」）",
                ledger=str(path),
            )
        raise
    accounts = [row for row in (data.get("account") or []) if isinstance(row, dict)]
    moment = now if now is not None else datetime.now(TZ)
    rows = [
        holds_row(account, root=Path(root), now=moment, model=model,
                  usage_in_fn=usage_in_fn, first_log_fn=first_log_fn)
        for account in accounts
    ]
    return HoldsReading(rows=rows, note="", ledger=str(path))


__all__ = [
    "LEDGER_ANCHOR",
    "LEDGER_ENV",
    "MISSING_LEDGER_NOTE",
    "PRICED",
    "TZ",
    "HoldsReading",
    "first_log_at",
    "holds_row",
    "ledger_path_for",
    "model_of",
    "numerator",
    "read_holds",
    "window_from_account",
]
