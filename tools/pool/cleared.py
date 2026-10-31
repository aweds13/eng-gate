r"""清空用量：只加一条「到此为止不算」的标记，账一行不动（卡 A357 · T-AG570）。

对等 magpie `internal/usage/cleared.go`（**整个 F44 只有 `:76-102` 的 `hides` 这一个判据**），
以及它的三处配套：`settings.go:2043-2046` 的 `Covers`、`:2050-2074` 的 `usageCleared`、
`:2078-2095` 的 `ClearUsage`。

★ **为什么是「另立一个面」，不是给既有动作加参数** —— `cleared.go:12-20` 逐字：
  `A clear is kept in settings (settings.UsageCleared) and read over whatever the pages
  count, never written into usage.jsonl: the log keeps every call, so a key's spending
  limit (package budget), the allowances' window holds and the gateway's own reads of it
  (Visit) still count the calls cleared, and the agents' session files and other
  computers' shared days, which magpie can't rewrite, are cleared the same way as its own
  log.`
  一句话：一个号的花费限额、额度窗口的估算、以及账自己的读者 **都还要数那些被清掉的
  调用**；agent 的 session 文件与别的机器上共享的天数 magpie 改不了 —— 所以它改的是
  **读法**，不是账。

★ **可核证据**（`cleared_test.go:78-82`）：同一份日志，页面数 **3** 条、`Visit` 数
  **5** 条，**一个字节都不改**。

★ **两个面不许合并**：账本模块 `pool.ledger_spend` 里另有一个「人显式 reset，把旧账
  搬走」的动作，语义与本模块**相反**（那个会让被清的调用**不再**计入限额）。合并两者
  = 让「只是不想看见」悄悄松开限额。本模块**不 import、不调用**那个动作 —— 判据 14 的
  源码级钉子按 ast 扫本模块的 `Name`/`Attribute`（注释与 docstring 不算数，所以这里
  连那个名字都不写出来）。

★ **判不出来就显出全部**（隐藏是危险方向，与 `tools/pool_quota.py` 的「未记录不当可用」
  是同一条纪律的反面表述）：标记文件不存在 ⇒ `[]`；坏 JSON ⇒ `[]`；单条读不懂 ⇒ 跳过
  那一条。三种错法都只会**多显示**，绝不会多隐藏。

★ **本模块只写一本标记**（`gates/diag/usage-cleared.json`，对应 magpie `settings.json`
  里那个字段），**永不碰** `gates/diag/pool-spend.jsonl`。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import tzinfo

    TZ: tzinfo
else:  # pragma: no cover —— 运行时走这一支（原因见 pool/limits_policy.py 的 docstring 末段）
    from pool_accounts import TZ

#: 仓库根（`tools/pool/cleared.py` 往上三层）；测试一律显式给 `root=`，不靠它。
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
#: 标记文件位址（相对 `root`）。★ 与账**分两份**：账那份一个字节都不动。
CLEARED_REL: tuple[str, ...] = ("gates", "diag", "usage-cleared.json")
#: 两个轴上的「不点名」。★ **两个都空才是全清**（沿用 magpie `UsageClear` 两个字段都空）。
ALL_ACCOUNT = ""
ALL_MODEL = ""
#: 退出码（与 `tools/pool_quota.py` 同款；缺参由 argparse 直接退 2 = `EXIT_USAGE`）。
EXIT_OK, EXIT_USAGE = 0, 2


class ClearError(ValueError):
    """清空用量的输入不合规（点名校验与时间校验；文案见 `add_clear()`）。"""


@dataclass(frozen=True, slots=True)
class Clear:
    """一条「到此为止不算」的标记（对等 magpie `settings.UsageClear` 的三个字段）。"""

    account: str  # "" = 该模型的所有号（对应 magpie 的 Provider==""）
    model: str  # "" 且 account=="" = 全清（对应 magpie 两个都空）
    at: datetime  # aware；毫秒精度不入库，直接存 ISO-8601


def _at(moment: datetime) -> datetime:
    """naive 时间按本仓时区（`pool_accounts.TZ`）解释。

    ★ 与 `ledger_spend._local()` **同口径**，但**照抄不 import** —— 那边要 import 本模块
      的 `hides()`，反向 import 会成环。
    """
    return moment.astimezone(TZ) if moment.tzinfo is not None else moment.replace(tzinfo=TZ)


def clears_path(root: Path | str | None = None) -> Path:
    """标记文件路径：`root`（默认仓库根）下的 `gates/diag/usage-cleared.json`。"""
    base = Path(root) if root is not None else TOOL_ROOT
    return base.joinpath(*CLEARED_REL)


def _mark(raw: object) -> Clear | None:
    """单条标记；任何一个字段读不懂 ⇒ `None`（调用方跳过那一条，不猜、不当全清）。"""
    if not isinstance(raw, dict):
        return None
    row = cast("dict[str, object]", raw)
    account, model, stamp = row.get("account"), row.get("model"), row.get("at")
    if not isinstance(account, str) or not isinstance(model, str) or not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    at = _at(moment)
    if at.timestamp() <= 0:
        return None
    # ★ 读出来**不 trim**：trim 只会让标记更「广」= 多隐藏，那是危险方向。
    return Clear(account=account, model=model, at=at)


def read_clears(*, root: Path | str | None = None) -> list[Clear]:
    """读标记；**判不出来就回 `[]`**（缺文件 / 坏 JSON / 根不是对象 ⇒ 一条都不隐藏）。

    单条读不懂（不是对象、`account`/`model` 不是字符串、`at` 缺失或不是 ISO 时间、时间
    早于纪元）⇒ **跳过那一条**，既不是整份作废、更不是当成全清。三条路都只往「多显示」
    的方向错。
    """
    path = clears_path(root)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    rows = cast("dict[str, object]", parsed).get("clears")
    if not isinstance(rows, list):
        return []
    marks: list[Clear] = []
    for raw in cast("list[object]", rows):
        mark = _mark(raw)
        if mark is not None:
            marks.append(mark)
    return marks


def covers(c: Clear, o: Clear) -> bool:
    """`c` 是否覆盖（吃掉）`o` —— 逐字照 `settings.go:2043-2046` 的 `Covers`。

    Go 原文：`return c.At >= o.At && (c.Provider == "" && c.Model == "" ||
    c.Provider == o.Provider && c.Model == o.Model)`
    """
    c_at_or_later = c.at >= o.at
    c_is_all = c.account == ALL_ACCOUNT and c.model == ALL_MODEL
    same_key = c.account == o.account and c.model == o.model
    return c_at_or_later and (c_is_all or same_key)


def prune(marks: Sequence[Clear]) -> list[Clear]:
    """丢掉被别的标记覆盖的旧标记；**同一个标记的重复项只留第一个**。

    逐字照 `settings.go:2050-2074` 的 `usageCleared`：
    `if j != i && o.At > 0 && o.Covers(c) && (!c.Covers(o) || j < i) { covered = true }`。
    `(!c.Covers(o) || j < i)` 就是那行注释 `// of two the same, the first is kept` ——
    两条**互相**覆盖（= 同一个标记）时，只有**后出现**的那条被丢掉。
    时间早于纪元的标记直接丢掉（Go 的 `if c.At <= 0 { continue }`）。
    """
    out: list[Clear] = []
    for index, mark in enumerate(marks):
        if mark.at.timestamp() <= 0:
            continue
        covered = False
        for other_index, other in enumerate(marks):
            if other_index == index or other.at.timestamp() <= 0:
                continue
            if covers(other, mark) and (not covers(mark, other) or other_index < index):
                covered = True
                break
        if not covered:
            out.append(mark)
    return out


def hides(marks: Sequence[Clear], account: str, model: str, at: datetime) -> bool:
    """这一行算不算「被清掉了」 —— 整个 F44 **只有这一个判据**（`cleared.go:76-102`）。

    ① 空标记 ⇒ `False`（`:77`）；
    ② 全清：取**最新**那条（`:57-58`），`at <= 它` 就隐藏（`:80` 的
       `!r.Time.After(c.all)` —— **闭区间上界**，`at == c.all` 也算被清）；
    ③ 按模型的标记：`model == ""` 跳过（那是全清，已在 ②）；`at > m.at` 跳过（`:85` 的
       `r.Time.After(m.Time())` —— 同样**闭区间**）；号不同跳过；模型逐字相等才算（`:88`）。
       别名归并（`:91-98` 的 `c.alias`）**不移植**：pool 的模型名是字面量，猜别名 = 造
       第二套真源。

    ★ **与 Go 的一处有意差别**（写在判据旁，别让它无声存在）：Go 的 `:85` 是
      `m.Provider != r.Provider` —— provider 轴上 `""` **不算通配**，而真实记录永远有非空
      provider，于是 `Provider=""` 的标记在 Go 里是一条**死标记**（什么都不隐藏）。本仓
      `account` 轴上 `""` 按 `Clear.account` 的注释是「该模型的所有号」，所以这里写成
      `mark.account not in (ALL_ACCOUNT, account)`；否则 `add_clear("", "m", at)` 会是一条
      **收了参数却什么都不做**的空命令 —— 静默无效比多隐藏更难发现。这条差别只会
      **多隐藏**，而它出现在「判得出来」的那一支，与「判不出来就显出全部」不冲突。
    """
    if not marks:
        return False
    moment = _at(at)
    latest_all: datetime | None = None
    for mark in marks:
        if mark.account == ALL_ACCOUNT and mark.model == ALL_MODEL:
            stamp = _at(mark.at)
            if latest_all is None or stamp > latest_all:
                latest_all = stamp
    if latest_all is not None and moment <= latest_all:
        return True
    for mark in marks:
        if mark.model == ALL_MODEL or moment > _at(mark.at):
            continue
        if mark.account not in (ALL_ACCOUNT, account):
            continue
        if model == mark.model:
            return True
    return False


def _write(marks: Sequence[Clear], path: Path) -> None:
    """把标记整份写回（`ensure_ascii=False`、纯 LF、末行带换行）。

    ★ **不搞原子替换**：这份文件坏了**不是**灾难 —— `read_clears()` 回 `[]`（= 一条都不
      隐藏 = 显出全部）。为一份「坏了就自动失效」的旁路标记加写盘纪律，成本大于风险。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "clears": [
            {"account": mark.account, "model": mark.model, "at": mark.at.isoformat()}
            for mark in marks
        ]
    }
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def add_clear(
    account: str, model: str, at: datetime, *, root: Path | str | None = None
) -> list[Clear]:
    """追加一条标记，回**去重后**的全部标记（`prune()` 的口径 = `usageCleared`）。

    ★ **先判后写**：两种不合规的输入都在碰盘之前抛 `ClearError` —— 尤其「点了号却没点
      模型」那条，**文件不得被创建**（半条标记比没有更坏）。
    ★ **永不碰账**：本函数只写 `usage-cleared.json`，`pool-spend.jsonl` 一个字节不动。
    """
    account, model = account.strip(), model.strip()
    if account != ALL_ACCOUNT and model == ALL_MODEL:
        raise ClearError(f"清空 {account!r} 的用量要点名模型")
    if at.tzinfo is None or at.timestamp() <= 0:
        raise ClearError("清空用量要一个时间")
    stamp = _at(at)
    marks = prune([*read_clears(root=root), Clear(account=account, model=model, at=stamp)])
    _write(marks, clears_path(root))
    return marks


def main(argv: list[str] | None = None) -> int:
    """子命令 `list` / `add`；`--root` 两个子命令都认，`--now` 只 `add` 认。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help="仓库根（默认本文件的仓库）")
    ap = argparse.ArgumentParser(prog="cleared", description="清空用量：只写标记，账一行不动")
    ap.add_argument("--root", help="仓库根（默认本文件的仓库）")
    subs = ap.add_subparsers(dest="cmd", required=True)
    subs.add_parser("list", parents=[common], help="列出标记")
    adder = subs.add_parser("add", parents=[common], help="追加一条标记")
    adder.add_argument("--account", default=ALL_ACCOUNT, help="号 id（不点名 = 所有号）")
    adder.add_argument("--model", default=ALL_MODEL, help="模型名（两个都不点名 = 全清）")
    adder.add_argument("--now", help="标记时刻（ISO-8601；缺省取现在）")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = args.root
    if args.cmd == "list":
        for mark in read_clears(root=root):
            print(f"{mark.at.isoformat()}  account={mark.account!r}  model={mark.model!r}")
        return EXIT_OK
    try:
        at = _at(datetime.fromisoformat(args.now)) if args.now else datetime.now(TZ)
        marks = add_clear(args.account, args.model, at, root=root)
    except ClearError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"[FAIL] 时间读不懂：{args.now!r}（{exc}）", file=sys.stderr)
        return EXIT_USAGE
    print(f"[OK  ] 已加标记，现在共 {len(marks)} 条")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
