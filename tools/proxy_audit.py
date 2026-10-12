r"""proxy_audit —— 代理指标登记表 + 过期对账（**只读**；卡 202 / 台账号 T-G304）。

## 为什么有它（Goodhart 定律）

当一个度量被用作**目标**，它就不再是一个好度量。本项目每天盯的数 ——
卡的 `done` 数 / 门禁绿数 / 文书行数 / 派活成功率 / 队列收敛四数（`tools/wb_flow.py`）——
**全是代理指标**：它们与「真实目标」只有相关、未必有因果，用久了会漂移。

防法不是换指标，是把每个代理**登记在案**（`docs/proxy-map.toml`）并**定期对账**：
登记表写下它代理的真实目标 / 有效性证据 / 上次验证日期 / 最可能的失效模式 / 已知钻空子；
本工具把「哪些代理太久没验证」变成**机器读数** —— 过期条目退非零，逼人重新验证一次。

## 用法

    python -X utf8 tools/proxy_audit.py --check             # 过期条目退非零（默认 30 天）
    python -X utf8 tools/proxy_audit.py --check --days 7    # 覆盖阈值
    python -X utf8 tools/proxy_audit.py --check --days 0    # 零容忍：任何一天前的记录都过期
    python -X utf8 tools/proxy_audit.py --report            # 人读表
    python -X utf8 tools/proxy_audit.py --json              # 机器可读
    python -X utf8 tools/proxy_audit.py --check --map <路径>  # 换登记表（测试用）

## 判据（过期语义，死板、不猜）

  age = 今天 - last_verified（整天）；`age > --days` ⇒ **过期**（overdue = age - --days 天）。
  `--days 0` = 零容忍：只要不是「今天以后验证的」就过期。
  ★ 这里**不猜**「它实际还有效吗」—— 只按登记日期算；代理是否仍有效，要人重新验证。

## 退出码

  `--check`：全新鲜 ⇒ 0；有任一过期 ⇒ 1。
  登记表读不到 / TOML 坏 / 字段缺失 / 日期非法 ⇒ **2 并点名**（**不许**静默当通过）。

★ 只读：不写任何文件，不判断「该不该验证」（那是人的决定）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent

#: 默认登记表。★ 放 `docs/` 不放 `gates/diag/`：后者是 gitignored，规矩住那儿迟早随它一起丢。
DEFAULT_MAP = ROOT / "docs" / "proxy-map.toml"
#: 默认过期阈值（天）。
DEFAULT_DAYS = 30
#: 每条必须写全的字段。
REQUIRED_FIELDS = (
    "id", "metric", "real_goal", "evidence", "last_verified", "failure_mode", "note",
)
#: 合法的失效模式（三型，照用户《优化理论与学习实践》）。
VALID_FAILURE = ("极端", "因果", "对抗")


class MapError(Exception):
    """登记表读不到 / 解析不了 / 字段不合规 —— 消息里**点名**，供退非零时打印。"""


@dataclass(frozen=True)
class ProxyEntry:
    """登记表里的一条代理指标（字段口径见 `docs/proxy-map.toml` 文件头）。"""

    id: str
    metric: str
    real_goal: str
    evidence: str
    last_verified: date
    failure_mode: str
    note: str


# ---------------------------------------------------------------- 读 / 校验登记表


def load_map(path: Path) -> list[ProxyEntry]:
    """读登记表并逐条校验。任何问题 ⇒ 抛 `MapError`（消息点名到具体条目/字段）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MapError(f"登记表读不到：{path}（{exc}）") from exc
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"登记表 TOML 坏了：{path}（{exc}）") from exc

    rows = data.get("proxy")
    if not isinstance(rows, list) or not rows:
        raise MapError(f"登记表里没有 [[proxy]] 条目：{path}")

    entries: list[ProxyEntry] = []
    for i, row in enumerate(rows, 1):
        where = f"第 {i} 条 [[proxy]]"
        if not isinstance(row, dict):
            raise MapError(f"{where} 不是一张表：{row!r}")
        missing = [f for f in REQUIRED_FIELDS if f not in row or str(row[f]).strip() == ""]
        if missing:
            raise MapError(f"{where} 缺字段 {missing}（id={row.get('id', '?')}）")
        try:
            verified = date.fromisoformat(str(row["last_verified"]).strip())
        except ValueError as exc:
            raise MapError(
                f"{where} 的 last_verified 不是 ISO 日期：{row['last_verified']!r}（{exc}）"
            ) from exc
        mode = str(row["failure_mode"]).strip()
        if mode not in VALID_FAILURE:
            raise MapError(
                f"{where} 的 failure_mode={mode!r} 不在 {VALID_FAILURE}（id={row['id']}）"
            )
        entries.append(
            ProxyEntry(
                id=str(row["id"]).strip(),
                metric=str(row["metric"]).strip(),
                real_goal=str(row["real_goal"]).strip(),
                evidence=str(row["evidence"]).strip(),
                last_verified=verified,
                failure_mode=mode,
                note=str(row["note"]).strip(),
            )
        )

    ids = [e.id for e in entries]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        raise MapError(f"id 重复：{dup}")
    return entries


# ---------------------------------------------------------------- 过期对账


@dataclass(frozen=True)
class CheckRow:
    """一条记录的过期核算结果。"""

    entry: ProxyEntry
    age_days: int
    overdue_days: int
    expired: bool


def audit(entries: Sequence[ProxyEntry], days: int, today: date) -> list[CheckRow]:
    """逐条算 `age = 今天 - last_verified`；`age > days` ⇒ 过期（overdue = age - days）。"""
    rows: list[CheckRow] = []
    for e in entries:
        age = (today - e.last_verified).days
        overdue = age - days
        rows.append(CheckRow(e, age, overdue, overdue > 0))
    return rows


def render_check(rows: Sequence[CheckRow], days: int, today: date) -> str:
    """`--check` 的人读输出：**逐条念出判据** `id | last_verified | 过期多少天 | 阈值`。"""
    lines = [
        f"=== 代理指标过期对账（阈值 {days} 天，今天 {today.isoformat()}）===",
        "判据： id | last_verified | 过期多少天 | 阈值",
    ]
    expired: list[CheckRow] = []
    for r in rows:
        mark = "过期" if r.expired else "新鲜"
        lines.append(
            f"  {r.entry.id} | {r.entry.last_verified.isoformat()} | "
            f"{r.overdue_days} | {days}   [{mark}]"
        )
        if r.expired:
            expired.append(r)
    if expired:
        lines.append(f"[FAIL] {len(expired)} 条过期（阈值 {days} 天）：")
        for r in expired:
            lines.append(
                f"  · {r.entry.id} 过期 {r.overdue_days} 天"
                f"（上次验证 {r.entry.last_verified.isoformat()}，距今 {r.age_days} 天）"
            )
    else:
        lines.append(f"[OK  ] {len(rows)} 条全新鲜（阈值 {days} 天）")
    return "\n".join(lines) + "\n"


def render_report(entries: Sequence[ProxyEntry]) -> str:
    """`--report` 人读表：`id | metric | real_goal | last_verified | failure_mode`（+证据/案）。"""
    lines = [
        "=== 代理指标登记表（--report）===",
        "id | metric | real_goal | last_verified | failure_mode",
    ]
    for e in entries:
        lines.append(
            f"  {e.id} | {e.metric} | {e.real_goal} | "
            f"{e.last_verified.isoformat()} | {e.failure_mode}"
        )
        lines.append(f"      evidence: {e.evidence}")
        lines.append(f"      note: {e.note}")
    return "\n".join(lines) + "\n"


def to_json_obj(rows: Sequence[CheckRow], days: int, today: date) -> dict:
    """`--json`：机器可读（含每条字段 + 过期核算 + 汇总）。"""
    return {
        "today": today.isoformat(),
        "days": days,
        "count": len(rows),
        "expired_count": sum(1 for r in rows if r.expired),
        "ok": all(not r.expired for r in rows),
        "entries": [
            {
                "id": r.entry.id,
                "metric": r.entry.metric,
                "real_goal": r.entry.real_goal,
                "evidence": r.entry.evidence,
                "last_verified": r.entry.last_verified.isoformat(),
                "failure_mode": r.entry.failure_mode,
                "note": r.entry.note,
                "age_days": r.age_days,
                "overdue_days": r.overdue_days,
                "expired": r.expired,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="代理指标登记表 + 过期对账（只读；过期条目退非零）",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="过期条目退非零（默认 30 天）")
    mode.add_argument("--report", action="store_true", help="人读表")
    mode.add_argument("--json", action="store_true", help="机器可读")
    parser.add_argument(
        "--map", default=str(DEFAULT_MAP), help=f"登记表路径（默认 {DEFAULT_MAP.name}）"
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS, help=f"过期阈值天数（默认 {DEFAULT_DAYS}）"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.days < 0:
        print(f"[FAIL] --days 不能为负：{args.days}", file=sys.stderr)
        return 2
    try:
        entries = load_map(Path(args.map))
    except MapError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    today = date.today()
    rows = audit(entries, args.days, today)

    if args.report:
        print(render_report(entries), end="")
        return 0
    if args.json:
        print(json.dumps(to_json_obj(rows, args.days, today), ensure_ascii=False, indent=2))
        return 0
    # --check
    print(render_check(rows, args.days, today), end="")
    return 1 if any(r.expired for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
