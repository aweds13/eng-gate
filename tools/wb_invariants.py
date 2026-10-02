r"""不变量台账的机器核查器（卡 144 · T-G243）。

要做什么：把「这套系统的**安全主张**有几条 → 每条由**哪段代码**判 → **反例钉子**在哪 →
现在**覆盖到没覆盖**」变成**机器可查**的一页。台账 `复盘/不变量台账.toml` 一行一条，
本工具逐条核 `judge`（判据在哪）与 `nail`（反例钉子在哪）**真的存在**。

三个子命令：

  --check    逐条核 `judge` 的**路径**与 `nail` 的**测试用例名**真的存在；
             有一行对不上 ⇒ 非零退出并**点名**那一行（台账**不许烂掉**）。
             ★ 只看存在性，**不真跑门禁**、不跑测试（判据若是一句命令，命令只核它所在脚本的路径）。
             ★ missing / partial 是状态、不是错误 ⇒ 有缺口的台账仍通过（别把诚实判成失败）。
  --missing  只列 `missing` / `partial` 的条目 —— 这就是那份「**待验台账**」：每条该有人去关。
  --list     按 `status` 分组打印（人读）。

台账字段（`[[invariant]]` 一条一块）：

    id      台账条号（INV-nn）
    claim   一句人话：什么不许发生
    judge   判据在哪：`<仓库相对路径>` 或 `<路径>::<符号>`；命令写在 note 里、judge 仍指脚本路径
    nail    反例钉子：`tests/<文件>::<用例名>`；没有钉子写 `-`，并把 status 标 missing / partial
    status  `covered`（判据 + 钉子都在）/ `partial`（有判据、缺一半）/ `missing`（本仓内无判据）
    note    诚实说明边界

★ 边界（如实写）：本工具**只核指针存在性** —— 不评价 claim 写得对不对、也不证明判据真的有牙
  （「有没有牙」由各自的**反例钉子**证明）。它防的是台账**烂掉**（指向不存在的路径 / 用例名）。
★ 只读：不写文件、不跑门禁、不起进程（除了读自己那份 toml 与测试文件）。

用法：

    python -X utf8 tools/wb_invariants.py --check
    python -X utf8 tools/wb_invariants.py --missing
    python -X utf8 tools/wb_invariants.py --list
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "复盘" / "不变量台账.toml"

#: 合法的状态值。
STATUSES = ("covered", "partial", "missing")
#: 「本仓内没有」的哨兵（判据或钉子缺一半时写它）。
NONE_MARK = "-"
#: nail 的写法：`tests/<文件>::<用例名>`（用例名可带 pytest 参数化后缀 `[...]`）。
NAIL_RE = re.compile(r"^(?P<file>tests/[^:]+?)::(?P<case>.+)$")


class LedgerError(Exception):
    """台账读不了 / 结构不对（环境或数据坏了）—— 与「某条对不上」分开。"""


def load_ledger(path: Path) -> list[dict[str, Any]]:
    """读台账，回 `[[invariant]]` 的全部条目（**不校验**内容 —— 校验在 `check_entries`）。"""
    if not path.exists():
        raise LedgerError(f"没有这份台账：{path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LedgerError(f"台账读不了（TOML 坏了？）：{path}（{exc}）") from exc
    rows = data.get("invariant")
    if not isinstance(rows, list) or not rows:
        raise LedgerError(f"台账里没有 `[[invariant]]` 条目：{path}")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise LedgerError(f"第 {index} 条不是表：{row!r}")
        out.append(row)
    return out


def judge_path(judge: str) -> str:
    """从 `judge` 里取**路径部分**：`路径::符号` 取路径、`路径 命令` 取第一个词。

    ★ 命令只核路径 —— 所以 `scripts/run_gates.py 跑全量门禁` 会核 `scripts/run_gates.py` 在不在。
    """
    head = str(judge or "").split("::", 1)[0]
    words = head.split()
    return words[0] if words else ""


def case_name(case: str) -> str:
    """去掉 pytest 参数化后缀 `[...]`，拿裸用例名（`test_nail[x]` → `test_nail`）。"""
    return str(case or "").split("[", 1)[0].strip()


def _defines(text: str, name: str) -> bool:
    """测试文件里有没有 `def <name>(`（用词边界，避免 `test_a` 命中 `test_ab`）。"""
    return re.search(rf"\bdef\s+{re.escape(name)}\s*\(", text) is not None


def check_entries(rows: Iterable[dict[str, Any]], root: Path = ROOT) -> list[str]:
    """逐条核 `judge` 的路径与 `nail` 的用例名 —— 回一串人话问题（**空列表 = 全过**）。

    ★ 每一步校验的存在性：
      - `status` 必须是 `covered`/`partial`/`missing` 之一；
      - `judge` 非哨兵 ⇒ 它的路径必须存在；
      - `nail` 非哨兵 ⇒ 必须合 `tests/<文件>::<用例名>`、文件在、`def <用例名>(` 在；
      - `covered` 不许缺 judge 或 nail（缺了就不是 covered）。
    """
    problems: list[str] = []
    for row in rows:
        rid = str(row.get("id") or "（无 id）")
        status = str(row.get("status") or "").strip()
        judge = str(row.get("judge") or "").strip()
        nail = str(row.get("nail") or "").strip()

        if status not in STATUSES:
            allowed = "/".join(STATUSES)
            problems.append(f"{rid} status 不合法：{status or '（空）'}（只认 {allowed}）")

        if judge in ("", NONE_MARK):
            if status == "covered":
                problems.append(f"{rid} status=covered 却没有 judge（判据在哪？）")
        else:
            path = judge_path(judge)
            if not path or not (root / path).exists():
                problems.append(f"{rid} judge 路径不存在：{path or judge}")

        if nail in ("", NONE_MARK):
            if status == "covered":
                problems.append(f"{rid} status=covered 却没有 nail（反例钉子在哪？）")
        else:
            match = NAIL_RE.match(nail)
            if not match:
                problems.append(
                    f"{rid} nail 写法不对（要 tests/<文件>::<用例名>）：{nail}")
            else:
                test_file = root / match.group("file")
                if not test_file.exists():
                    problems.append(f"{rid} nail 测试文件不存在：{match.group('file')}")
                else:
                    name = case_name(match.group("case"))
                    text = test_file.read_text(encoding="utf-8")
                    if not _defines(text, name):
                        problems.append(
                            f"{rid} nail 用例名在 {match.group('file')} 里找不到："
                            f"{match.group('case')}")
    return problems


def missing_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """只留 `missing` / `partial` 的条目（待验台账）。"""
    return [row for row in rows if str(row.get("status")) in ("missing", "partial")]


def counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    return {status: sum(1 for row in rows if str(row.get("status")) == status)
            for status in STATUSES}


def _print_missing(rows: list[dict[str, Any]]) -> None:
    picked = missing_rows(rows)
    print(f"=== 待验台账（missing / partial）：{len(picked)} 条 ===")
    if not picked:
        print("  （没有 missing / partial 条目）")
        return
    for row in picked:
        print(f"  [{row.get('status')}] {row.get('id')} —— {row.get('claim')}")
        if str(row.get("note") or "").strip():
            print(f"          {row.get('note')}")


def _print_list(rows: list[dict[str, Any]]) -> None:
    print(f"=== 不变量台账：{len(rows)} 条 ===")
    for status in STATUSES:
        group = [row for row in rows if str(row.get("status")) == status]
        print(f"-- {status}（{len(group)}）")
        for row in group:
            print(f"  {row.get('id'):<8} {row.get('claim')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="不变量台账核查器：核判据路径与反例钉子真的存在")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                        help="台账路径（默认 复盘/不变量台账.toml）")
    parser.add_argument("--check", action="store_true",
                        help="逐条核 judge 路径与 nail 用例名（对不上退 1）")
    parser.add_argument("--missing", action="store_true", help="只列 missing / partial（待验台账）")
    parser.add_argument("--list", action="store_true", help="按 status 分组打印")
    args = parser.parse_args(argv)
    if not (args.check or args.missing or args.list):
        args.check = True  # 不给子命令 = 默认核一遍

    try:
        rows = load_ledger(Path(args.ledger))
    except LedgerError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    if args.check:
        problems = check_entries(rows)
        if problems:
            for item in problems:
                print(f"[FAIL] {item}", flush=True)
            print(f"[FAIL] {len(problems)} 条对不上 —— 台账不许烂掉"
                  "（先修指针，或老实标 missing / partial）", flush=True)
            return 1
        stat = counts(rows)
        print(f"[OK ] 台账 {len(rows)} 条全部核过：判据路径与钉子用例名都在"
              f"（covered {stat['covered']} / partial {stat['partial']} / "
              f"missing {stat['missing']}；后两类是状态、不是错误）", flush=True)
        if not (args.missing or args.list):
            return 0

    if args.missing:
        _print_missing(rows)
    if args.list:
        _print_list(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
