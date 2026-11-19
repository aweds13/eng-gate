r"""窗口登记：把「5 小时窗口」**记下来**，不在点上**起窗**（卡 A370 · T-AG655）。

为什么有它（magpie F28「warm-up：按点启动 5 小时窗口」的移植判断）：本仓要的是 F28 的
**判据**，不是它的**节拍**。`gates/diag/_magpie_scope.md:36` 判 `PORT / landed=no`，而
`grep warm.up|warmup` 在 `tools/` `scripts/` **零命中** —— 「探 → 登记窗口 → 判该不该
warm」这条环断在中间：

- `tools/pool_quota.py` 的四态只由 **429** 派生（`parse_reset()` 拆的是报错文案里的重置
  时刻），`status()` 里**没有**「窗口从哪起、到哪止」；
- `tools/pool_accounts.py` 的 `probe` 只写 `[account.health]` 三键与 `used_percent`，
  **没有任何一处**留下「这个号的重置时刻 / 窗口跨度」（`samples` 项逐字只有
  `{"at", "kind"}`，没有 `reset_at`）；
- 「按点」在本仓被 `tools/pool/checkin.py:57-61` 明文排除（用户定形：不给后台定时、不做
  自动重试），全仓唯一像计划任务的东西只在 `tools/auto_land.py:35-43` 的文档示意里。

所以本模块只做三件事，**一件也不多做**：

1. `window_of_row()` —— 把一条读数（探测行 / 账本 `[account.quota]`）读成 `Window`。
   缺 `resets_at` 或 `span_s` **任一** ⇒ `None`（**不许**拿「5 小时」兜底：跨度只许来自
   `tools/pool/platforms.toml` 的 `window_hours`）；
2. `register()` —— **唯一**写窗口登记表的地方（同目录临时文件 + `os.replace`，抄
   `pool_accounts.save_ledger()`）；每账号每时刻每天只记一次；
3. `window_running()` / `due()` —— 三条**纯函数**判据 + 只看不写的读数面。

★ 三条「窗口没在跑」判据（顺序固定，第 1 条先赢）：

| # | 条件 | 判词 | 理由码 |
|---|---|---|---|
| ① | `resets_at <= now` | 不在跑 | `reset` |
| ② | 有 `used` 且比上次登记**回落** | 窗口重开（在跑） | `usage` |
| ③ | 没有 `used`，且 `resets_at` 晚于「上次跑到的时间」 | 不算启动（不在跑） | `idle` |

**三条都判不出 ⇒ 回 `None`（unknown），不许默认「没在跑」** —— 默认值方向错了：把
「可能正在跑」当成「没跑」，代价是在错的点上发请求。

★ 本模块**不发任何 HTTP**（连请求对象都不构造）、**不装定时器**、**不起后台线程**、
**不 sleep** —— import 面由 `tests/test_pool_warmup.py` 按 ast 钉死（照
`tests/test_pool_quota_line.py:250-270` 的扫法，扫 AST 不扫字符串）。

★ 判据 5 的边界：`pool_quota.status()` 的四态 / `can_dispatch` 三值 / `why` 文案
**一个字都不动**，窗口读数走本模块的 `due`，不进 `status()`。

用法：

    python -X utf8 tools/pool/warmup.py due --json --now 2026-11-19T12:00:00+08:00
    python -X utf8 tools/pool/warmup.py due --at 09:00 --at 17:00 --json
    python -X utf8 tools/pool/warmup.py warm --at 09:00
    python -X utf8 tools/pool/warmup.py register --at 09:00
    python -X utf8 tools/pool/warmup.py status --json

退出码（判据 6）：`0` = 有该 warm 的（或全都不该 warm）；`2` = 环境（账本读不到 / 用法错）；
`3` = 判不出（有 `unknown` 且没有 `due`）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: 账本与留档的时区（与 `pool_accounts.TZ` 同值）。**这里不 import 账本模块**：`status` /
#: `register` 两条命令一个字节都不碰账本，不该为了一个常量把 urllib 拖进 import 面。
TZ = timezone(timedelta(hours=8))

#: `tools/`（本文件上一层）。直跑 `python -X utf8 tools/pool/warmup.py due ...` 时
#: `sys.path[0]` 是 `tools/pool`，`pool` 与 `pool_quota` **都不在** —— 自己挂上，别指望调用方。
_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:  # pragma: no cover —— 包路径与测试里通常已经在
    sys.path.insert(0, str(_TOOLS_DIR))

if __package__:  # 包内导入（`from tools.pool import warmup`、pytest 都走这条）
    from .holds import Window  # noqa: E402 —— 只复用容器；bounds() / estimate() 一个字不动
else:  # pragma: no cover —— 直跑 `python tools/pool/warmup.py`：没有包上下文，只能按裸模块名
    from holds import Window  # noqa: E402

import pool_quota  # noqa: E402 —— 重置时刻的唯一解析真源（parse_reset()，卡 201）

#: 仓库根（本文件往上三层）；测试一律显式给 `root=`，不靠它。
ROOT = Path(__file__).resolve().parent.parent.parent

#: 窗口登记表（派生、可重建、gitignored —— `gates/diag/` 整体在 .gitignore 里）。
#: ★ 这个字面量**全模块只出现这一次**（`tests/test_pool_warmup.py` 按源码计数钉着）。
STATE_REL: tuple[str, ...] = ("gates", "diag", "warm-window.json")

#: 退出码（判据 6）：`2` 同时兜「账本读不到」与「用法错」（argparse 也退 2）。
EXIT_OK, EXIT_ENV, EXIT_UNKNOWN = 0, 2, 3

#: 读数面只认这三个判词（判据 3）：多一个都不许出现。
VERDICTS = ("due", "not-due", "unknown")

#: 三条「窗口没在跑」理由码（判据 3，顺序 = 判序）。
REASON_RESET, REASON_USAGE, REASON_IDLE, REASON_UNKNOWN = "reset", "usage", "idle", "unknown"


class WarmError(ValueError):
    """输入不合规（`--now` / `--at` 认不出、登记行缺账号）。"""


# --------------------------------------------------------------------------
# 判据：把一条读数读成窗口
# --------------------------------------------------------------------------


def window_of_row(row: Mapping[str, object]) -> Window | None:
    """把一条读数（探测行 / 账本 `[account.quota]`）读成 `Window`；读不出就 `None`。

    ★ **两键缺一不可**（判据 1）：`resets_at` 要能被 `pool_quota.parse_reset()` 解析，
      `span_s` 要 > 0 且有限。只给一个 ⇒ `None`。
    ★ **不许兜底**：跨度只能来自平台表 `window_hours`（探测时才折算成 `span_s`）。在这里
      写「没有就给 5 小时」就是把 magpie 的常量偷偷搬进来 —— 那正是本卡禁止的那条。
    ★ 纯函数：不读文件、不读钟、不联网。
    """
    if not isinstance(row, Mapping):
        return None
    raw_reset = row.get("resets_at")
    raw_span = row.get("span_s")
    if raw_reset is None or raw_span is None:
        return None
    resets_at = raw_reset if isinstance(raw_reset, datetime) else _parse_reset(str(raw_reset))
    if resets_at is None:
        return None
    if isinstance(raw_span, bool) or not isinstance(raw_span, (int, float)):
        return None
    if not math.isfinite(raw_span) or raw_span <= 0:
        return None
    used = row.get("used_percent")
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
        used = None
    return Window(
        model=str(row.get("model") or ""),
        span_s=int(round(float(raw_span))),
        used=float(used) if used is not None else None,
        resets_at=resets_at,
        pool=str(row.get("pool") or ""),
        family=str(row.get("family") or ""),
    )


def window_running(
    w: Window,
    now: datetime,
    *,
    prev_used: float | None = None,
    last_seen: datetime | None = None,
) -> tuple[bool | None, str]:
    """窗口**现在**在不在跑 —— 三条判据，顺序固定（判据 3）。

    返回 `(True | False | None, 理由码)`。`None` = 判不出（**不许**当成「没在跑」）。

    | # | 条件 | 返回 |
    |---|---|---|
    | ① | `resets_at <= now` | `(False, "reset")` —— 重置时刻已经过去，窗口结束了 |
    | ② | 有 `used` 且 `< prev_used`（上次登记的读数） | `(True, "usage")` —— 回落 = 窗口重开 |
    | ③ | 没有 `used`，`resets_at` 晚于 `last_seen`（上次跑到的时间） | `(False, "idle")` |
    | — | 有 `used`、没见回落 | `(True, "usage")` —— 有读数且不满足 ① ⇒ 在跑 |
    | — | 没有 `used`、也没有可比的时间 | `(None, "unknown")` |

    `prev_used` / `last_seen` 是**可选**入参（卡规格的签名 `window_running(w, now)` 不动）：
    今天账本里 `used_percent` 只有 codearts 一处会写（卡 E97），「跟谁比」在真数据里还立不
    住 —— 所以生产路径（`due()`）**不传 `prev_used`**，第 ② 支只在构造用例上成立，如实
    写在卡 A370 的「未坐实项 2」里。
    """
    tz = now.tzinfo if now.tzinfo is not None else TZ
    resets_at = _as_aware(w.resets_at, tz)
    if resets_at is not None and resets_at <= now:
        return False, REASON_RESET
    if w.used is not None and prev_used is not None and w.used < prev_used:
        return True, REASON_USAGE
    if w.used is None:
        seen = _as_aware(last_seen, tz)
        if resets_at is not None and seen is not None and seen < resets_at:
            return False, REASON_IDLE
        return None, REASON_UNKNOWN
    return True, REASON_USAGE


def _parse_reset(raw: str) -> datetime | None:
    """重置时刻**只走** `pool_quota.parse_reset()`（全仓唯一真源，见 tools/pool/route.py:25-29）。

    这里再写一份正则就是第二个真源；两个真源对不上的表现不是报错，是「解析成功」的错时刻。
    """
    return pool_quota.parse_reset(raw)


def _as_aware(dt: datetime | None, tz: object) -> datetime | None:
    """`parse_reset()` 可能回 naive（fromisoformat 那一支）—— 统一成带时区再比。"""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=tz)


# --------------------------------------------------------------------------
# 登记表：唯一的写点
# --------------------------------------------------------------------------


def _state_path(root: Path = ROOT) -> Path:
    """登记表的绝对路径（`root` 默认仓库根；测试一律显式给）。"""
    return Path(root).joinpath(*STATE_REL)


def load_state(*, root: Path = ROOT) -> dict[str, dict[str, list[str]]]:
    """读登记表：`{账号: {"YYYY-MM-DD": ["09:00", "17:00"]}}`（判据 4 的形状）。

    **fail-open**（与 `cleared.py` 同一条纪律）：文件不存在 / 坏 JSON / 结构不对 ⇒ 空表。
    方向是想清楚的：空表只会让 `due()` **多列**（多一条建议），绝不会多发请求 —— 本模块
    一个请求都不发，多列的最坏后果是人多看一眼。
    """
    path = _state_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    table: dict[str, dict[str, list[str]]] = {}
    for account, per_day in data.items():
        if not isinstance(account, str) or not isinstance(per_day, dict):
            continue
        days: dict[str, list[str]] = {}
        for day, times in per_day.items():
            if not isinstance(day, str) or not isinstance(times, list):
                continue
            days[day] = [t for t in times if isinstance(t, str) and _is_hhmm(t)]
        if days:
            table[account] = days
    return table


def register(rows: Sequence[Mapping[str, object]], *, now: datetime, root: Path = ROOT) -> Path:
    """把「这些账号在这个时刻登记过」写进登记表 —— **本模块唯一写盘的地方**（判据 1 / 4）。

    `rows` 每一项：`{"account": <账号 id>, "at": "HH:MM"?, "date": "YYYY-MM-DD"?}`
    （`id` 也认，方便直接喂探测行）。`at` 缺省 = `now` 的时刻，`date` 缺省 = `now` 的
    日期。**只记时刻，不记请求、不记结果**（判据 4 逐字）。

    ★ 同 `(账号, 日期, 时刻)` 二次调用：**一个字节都不写**（连 `os.replace` 都不调，mtime
      不动）—— 否则「每账号每时刻每天只记一次」会被一次重跑打成两条。
    ★ 写盘：同目录临时文件 + `os.replace`（抄 `pool_accounts.save_ledger()` 的理由：写坏
      半个文件比不写更糟；临时文件必须同目录，跨盘 `os.replace` 不原子）。
    """
    path = _state_path(root)
    table = load_state(root=root)
    stamp = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")
    changed = False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        account = row.get("account") or row.get("id")
        if not isinstance(account, str) or not account.strip():
            raise WarmError(f"登记行缺账号：{row!r}（要 account 或 id）")
        at = row.get("at") or stamp
        if not isinstance(at, str) or not _is_hhmm(at):
            raise WarmError(f"--at 认不出：{at!r}（要 HH:MM，例如 09:00）")
        day = row.get("date") or today
        if not isinstance(day, str) or not day:
            raise WarmError(f"日期认不出：{day!r}（要 YYYY-MM-DD）")
        times = table.setdefault(account.strip(), {}).setdefault(day, [])
        if at in times:
            continue
        times.append(at)
        times.sort()
        changed = True
    if not changed:
        return path
    body = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".warm-window.", suffix=".tmp", dir=str(path.parent))
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return path


# --------------------------------------------------------------------------
# 读数面：只看不写
# --------------------------------------------------------------------------


def due(
    accounts: Sequence[Mapping[str, object]],
    ats: Sequence[str],
    *,
    now: datetime,
    root: Path = ROOT,
) -> list[dict]:
    """每号一条判词：`{account, ats, verdict, why}`，`verdict` 只许 `due` / `not-due` /
    `unknown`（判据 3 / 6）。

    判序（前两条是**事实**、后三条是**判据** —— 混在一起说会让人以为「没登记」也是窗口的
    结论）：

    1. 今天这些时刻**都登记过** ⇒ `not-due`（每账号每时刻每天只记一次）；
    2. 还**没到点** ⇒ `not-due`；
    3. 账本里没有窗口两键（`window_of_row()` 回 `None`）⇒ `unknown`（先跑 `probe`）；
    4. 窗口**在跑** ⇒ `not-due`（再 warm 是浪费）；
    5. 窗口**没在跑** ⇒ `due`。

    **只读**：不写登记表、不探、不联网。`now` 一律注入（不读真实钟表）。
    """
    table = load_state(root=root)
    today = now.strftime("%Y-%m-%d")
    now_at = now.strftime("%H:%M")
    slots = [str(a) for a in ats]
    out: list[dict] = []
    for acc in accounts:
        if not isinstance(acc, Mapping):
            continue
        account = str(acc.get("id") or "")
        quota = acc.get("quota")
        window = window_of_row(quota if isinstance(quota, Mapping) else {})
        per_day = table.get(account, {})
        verdict, why = _verdict(window, slots, per_day.get(today, []), now, now_at, per_day)
        out.append({"account": account, "ats": slots, "verdict": verdict, "why": why})
    return out


def _verdict(
    window: Window | None,
    slots: list[str],
    done: list[str],
    now: datetime,
    now_at: str,
    per_day: Mapping[str, list[str]],
) -> tuple[str, str]:
    """`due()` 的判序本体（纯函数，不读盘）；理由串把「凭什么」写出来，不许只回一个 due。"""
    if not slots:
        return "unknown", "没给登记时刻（--at）⇒ 不知道按哪个点判"
    pending = [a for a in slots if a not in done]
    if not pending:
        return "not-due", f"今天 {', '.join(slots)} 都登记过了（每账号每时刻每天只记一次）"
    ready = [a for a in pending if a <= now_at]
    if not ready:
        return "not-due", f"还没到点（下一个 {min(pending)}，现在 {now_at}）"
    if window is None:
        return "unknown", (
            "账本里没有 resets_at / span_s 这对键 ⇒ 判不出窗口在不在跑"
            "（先跑 python -X utf8 tools/pool_accounts.py probe）"
        )
    running, reason = window_running(window, now, last_seen=_last_seen(per_day, now))
    if running is None:
        return "unknown", f"窗口判不出（理由 {reason}）：没有 used 读数，也没有可比的登记时刻"
    if running:
        return "not-due", f"窗口正在跑（理由 {reason}）⇒ 再 warm 是浪费"
    return "due", f"到点了（{ready[0]}）且窗口没在跑（理由 {reason}）⇒ 该 warm"


def _last_seen(per_day: Mapping[str, list[str]], now: datetime) -> datetime | None:
    """「上次跑到的时间」= 登记表里最近的一条时刻；一条都没有就 `None`（不猜）。"""
    best: datetime | None = None
    tz = now.tzinfo if now.tzinfo is not None else TZ
    for day, times in per_day.items():
        for at in times:
            if not _is_hhmm(at):
                continue
            try:
                stamp = datetime.fromisoformat(f"{day}T{at}:00").replace(tzinfo=tz)
            except ValueError:
                continue
            if best is None or stamp > best:
                best = stamp
    return best


def _is_hhmm(value: str) -> bool:
    """`HH:MM`（零填充 24 小时制）—— 登记表里只许这种形状，排序也靠它。"""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    hh, mm = value[:2], value[3:]
    return hh.isdigit() and mm.isdigit() and int(hh) < 24 and int(mm) < 60


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _resolve_now(raw: str | None) -> datetime:
    """`--now` 注入「现在」；认不出就抛（与 `pool_quota` 的 `BadNowError` 同款口径）。"""
    if raw is None:
        return datetime.now(TZ).replace(microsecond=0)
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise WarmError(
            f"--now 认不出：{raw!r}（要 ISO-8601，例如 2026-11-17T08:00:00+08:00）"
        ) from exc
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=TZ)


def cmd_due(args: argparse.Namespace) -> int:
    """`due`：只读重放 —— 每号一条判词。不写登记表、不探、不联网。"""
    now = _resolve_now(args.now)
    ats = list(args.at or [now.strftime("%H:%M")])
    accounts, code = _read_accounts(args.root)
    if accounts is None:
        return code
    rows = due(accounts, ats, now=now, root=Path(args.root))
    if args.json:
        print(
            json.dumps(
                {"now": now.isoformat(), "ats": ats, "rows": rows}, ensure_ascii=False, indent=2
            )
        )
    else:
        for row in rows:
            mark = {"due": "[DUE ]", "not-due": "[ -- ]", "unknown": "[ ?? ]"}[row["verdict"]]
            print(f"{mark} {row['account']}: {row['why']}")
    return _exit_code(rows)


def cmd_warm(args: argparse.Namespace) -> int:
    """`warm`：只打印**建议命令**与理由 —— 本模块不发请求（卡 A370 的硬边界）。"""
    now = _resolve_now(args.now)
    ats = list(args.at or [now.strftime("%H:%M")])
    accounts, code = _read_accounts(args.root)
    if accounts is None:
        return code
    rows = due(accounts, ats, now=now, root=Path(args.root))
    for row in rows:
        if row["verdict"] != "due":
            print(f"[SKIP] {row['account']}: {row['why']}")
            continue
        print(f"[DUE ] {row['account']}: {row['why']}")
        print("       建议命令：python -X utf8 tools/pool_accounts.py probe --platform <平台>")
    return _exit_code(rows)


def cmd_register(args: argparse.Namespace) -> int:
    """`register`：把「这个时刻登记过」写进登记表（唯一写点）。"""
    now = _resolve_now(args.now)
    accounts, code = _read_accounts(args.root)
    if accounts is None:
        return code
    ats = list(args.at or [now.strftime("%H:%M")])
    rows = [
        {"account": str(acc.get("id") or ""), "at": at, "date": now.strftime("%Y-%m-%d")}
        for acc in accounts
        for at in ats
    ]
    path = register(rows, now=now, root=Path(args.root))
    print(f"[OK  ] 登记 {len(rows)} 条 → {path}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    """`status`：只看不写 —— 登记表 + 每号每天登记了几个时刻。"""
    table = load_state(root=Path(args.root))
    if args.json:
        print(json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_OK
    if not table:
        print("[ -- ] 登记表还是空的（先跑 register）")
        return EXIT_OK
    for account in sorted(table):
        days = table[account]
        parts = [f"{day}: {', '.join(days[day])}" for day in sorted(days)]
        print(f"[OK  ] {account} —— {'; '.join(parts)}")
    return EXIT_OK


def _read_accounts(root: str) -> tuple[list[dict] | None, int]:
    """读真账本（**懒加载** `pool_accounts`：`register` / `status` 两条命令一个字节都不碰它）。

    ★ 为什么懒加载而不是顶层 import：`pool_accounts` 顶层拉 `urllib` / `socket`，而本模块
      的 import 面被判据 6 钉成「零网络」；顶层 import 会把「它会不会发请求」从一眼可读
      变成要追两层。
    读不到就 `(None, EXIT_ENV)` —— 环境问题退 2，不是「没有该 warm 的」。
    """
    try:
        import pool_accounts as pa  # noqa: PLC0415 —— 懒加载，见 docstring
    except ImportError:
        print("窗口登记：读不到 tools/pool_accounts.py（环境不对）", file=sys.stderr)
        return None, EXIT_ENV
    try:
        ledger = pa.find_ledger()
        data = pa.load_ledger(ledger)
    except pa.LedgerError as exc:
        print(f"窗口登记：账本读不到 —— {exc}", file=sys.stderr)
        return None, EXIT_ENV
    accounts = data.get("account")
    if not isinstance(accounts, list):
        print("窗口登记：账本里没有 [[account]] 表", file=sys.stderr)
        return None, EXIT_ENV
    return [a for a in accounts if isinstance(a, dict)], EXIT_OK


def _exit_code(rows: list[dict]) -> int:
    """判据 6 的退出码：有该 warm 的 ⇒ 0；一条 due 都没有且全是 unknown ⇒ 3；其余 ⇒ 0。"""
    if any(row["verdict"] == "due" for row in rows):
        return EXIT_OK
    if rows and all(row["verdict"] == "unknown" for row in rows):
        return EXIT_UNKNOWN
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(ROOT), help="仓库根（测试显式给）")
    common.add_argument("--now", default=None, help="注入『现在』（ISO-8601；不许靠真实钟表）")
    common.add_argument("--at", action="append", help="登记时刻 HH:MM（可多次）")
    common.add_argument("--json", action="store_true")

    ap = argparse.ArgumentParser(
        prog="warmup.py",
        description="窗口登记：判「该不该 warm」（不发请求、不起定时器）",
        parents=[common],
    )
    subs = ap.add_subparsers(dest="cmd", required=True)
    subs.add_parser("due", parents=[common], help="每号一条判词（只读）")
    subs.add_parser("warm", parents=[common], help="打印建议命令与理由（不发请求）")
    subs.add_parser("register", parents=[common], help="登记这个时刻（唯一的写动作）")
    subs.add_parser("status", parents=[common], help="看登记表（只读）")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "due": cmd_due,
        "warm": cmd_warm,
        "register": cmd_register,
        "status": cmd_status,
    }
    handler = handlers.get(args.cmd or "")
    if handler is None:  # pragma: no cover —— argparse 已经拦掉
        build_parser().print_help()
        return EXIT_ENV
    try:
        return handler(args)
    except WarmError as exc:
        print(f"窗口登记：{exc}", file=sys.stderr)
        return EXIT_ENV


if __name__ == "__main__":
    raise SystemExit(main())
