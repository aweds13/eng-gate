r"""不变量台账的机器核查器（卡 144 · T-G243）+ 条款台账核查器（卡 162 · T-G262）。

要做什么：把「这套系统的**安全主张**有几条 → 每条由**哪段代码**判 → **反例钉子**在哪 →
现在**覆盖到没覆盖**」变成**机器可查**的一页。台账 `复盘/不变量台账.toml` 一行一条，
本工具逐条核 `judge`（判据在哪）与 `nail`（反例钉子在哪）**真的存在**。

不变量台账的三个子命令：

  --check    逐条核 `judge` 的**路径**与 `nail` 的**测试用例名**真的存在；
             有一行对不上 ⇒ 非零退出并**点名**那一行（台账**不许烂掉**）。
             ★ 只看存在性，**不真跑门禁**、不跑测试（判据若是一句命令，命令只核它所在脚本的路径）。
             ★ missing / partial 是状态、不是错误 ⇒ 有缺口的台账仍通过（别把诚实判成失败）。
  --missing  只列 `missing` / `partial` 的条目 —— 这就是那份「**待验台账**」：每条该有人去关。
  --list     按 `status` 分组打印（人读）。

条款台账的子命令（卡 162 · T-G262）：

  --clauses  核 `复盘/条款台账.toml`：把「只有一句人话」的规矩单独建账，每条要么有机器判据
             （`covered`/`partial`），要么**如实标 `unjudgeable` + 理由**。
             ★ 本卡最关键的一条判据：`status = unjudgeable` 但 `note` 为空 ⇒ **红**
             （「用一句人话糊过去」不许蒙混过关）。
             ★ `unjudgeable` 是诚实态、不是失败 —— 但它**必须带理由**。
             ★ 与不变量台账的差异：状态集合不同（`unjudgeable` 替代 `missing`），
             且 `unjudgeable` 强制要 `note`（`missing` 不强制）。

不变量台账字段（`[[invariant]]` 一条一块）：

    id      台账条号（INV-nn）
    claim   一句人话：什么不许发生
    judge   判据在哪：`<仓库相对路径>` 或 `<路径>::<符号>`；命令写在 note 里、judge 仍指脚本路径
    nail    反例钉子：`tests/<文件>::<用例名>`（★ 卡 159 起也认 `scripts/<自测脚本>::<用例名>`）；
            没有钉子写 `-`，并把 status 标 missing / partial
    status  `covered`（判据 + 钉子都在）/ `partial`（有判据、缺一半）/ `missing`（本仓内无判据）
    note    诚实说明边界

条款台账字段（`[[clause]]` 一条一块）：

    id      条款号（CL-nn），通常对应一条 INV-nn 的「只有人话」那半
    clause  原话 / 出处 §（哪份协议 / 哪条规矩）
    judge   判据落点：`<路径::符号>` 或 `-`（unjudgeable 时写 `-`）
    nail    反例钉子：`tests/…::用例名` 或 `-`
    status  `covered` / `partial` / `unjudgeable`
    note    **为什么机器判不了** —— `unjudgeable` 的必备项（空的要红）

★ 边界（如实写）：本工具**只核指针存在性** —— 不评价 claim 写得对不对、也不证明判据真的有牙
  （「有没有牙」由各自的**反例钉子**证明）。它防的是台账**烂掉**（指向不存在的路径 / 用例名）。
★ 只读：不写文件、不跑门禁、不起进程（除了读自己那份 toml 与测试文件）。

用法：

    python -X utf8 tools/wb_invariants.py --check
    python -X utf8 tools/wb_invariants.py --missing
    python -X utf8 tools/wb_invariants.py --list
    python -X utf8 tools/wb_invariants.py --clauses
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
#: 条款台账（卡 162 · T-G262）：把「只有一句人话」的规矩单独建账。
DEFAULT_CLAUSE_LEDGER = ROOT / "复盘" / "条款台账.toml"

#: 合法的状态值（不变量台账）。★ 卡 164（T-G264）加 `unjudgeable`：本仓内**判不了**的通则
#: （如 INV-62「判据必须问现在」—— 它是评审口味，不是机器能查的子串）。
#: `unjudgeable` 不算错误、不进待验清单 —— 它是**诚实标记**：不许编一个假判据冒充它。
STATUSES = ("covered", "partial", "missing", "unjudgeable")
#: 条款台账的合法状态值（卡 162 · T-G262）：`unjudgeable` 替代 `missing`
#: —— 机器判不了要**如实标 + 给理由**（与上面那份是**两张不同的账**，别混）。
CLAUSE_STATUSES = ("covered", "partial", "unjudgeable")
#: 「本仓内没有」的哨兵（判据或钉子缺一半时写它）。
NONE_MARK = "-"
#: nail 的写法：`tests/<文件>::<用例名>`；★ 卡 159 起也认 `scripts/<自测脚本>::<用例名>`
#: （护栏脚本自己的命名用例，如 `scripts/test_check_layers.py::<case_*>`）；
#: 用例名可带 pytest 参数化后缀 `[...]`。
NAIL_RE = re.compile(r"^(?P<file>(?:tests|scripts)/[^:]+?)::(?P<case>.+)$")


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


def defines_case(text: str, name: str) -> bool:
    """测试文件正文里有没有 `def <name>(` —— 用例级存在性判据的**唯一真源**。

    ★ 卡 159（T-G259）：`scripts/audit_progress.py::eval_assertion` 的 `test:文件::用例名`
    复用这一把尺子（**不许写第二份**）；本模块自己的 nail 核对也走它。
    """
    return _defines(text, name)


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
                    f"{rid} nail 写法不对（要 tests/…或 scripts/…::<用例名>）：{nail}")
            else:
                test_file = root / match.group("file")
                if not test_file.exists():
                    problems.append(f"{rid} nail 测试文件不存在：{match.group('file')}")
                else:
                    name = case_name(match.group("case"))
                    text = test_file.read_text(encoding="utf-8")
                    if not defines_case(text, name):
                        problems.append(
                            f"{rid} nail 用例名在 {match.group('file')} 里找不到："
                            f"{match.group('case')}")
    return problems


def missing_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """只留 `missing` / `partial` 的条目（待验台账）。"""
    return [row for row in rows if str(row.get("status")) in ("missing", "partial")]


# ------------------------------------------------------------------ 条款台账（卡 162 · T-G262）
#
# 与不变量台账的差异：
# - 状态集合不同：`unjudgeable` 替代 `missing`（机器判不了要**如实标 + 给理由**）。
# - `unjudgeable` 强制要 `note`（`missing` 不强制）——「用一句人话糊过去」不许蒙混过关。
# - `clause` 字段替代 `claim`（原话 / 出处 §）；其余字段同名同义。


def load_clauses(path: Path) -> list[dict[str, Any]]:
    """读条款台账，回 `[[clause]]` 的全部条目（**不校验**内容 —— 校验在 `check_clauses`）。"""
    if not path.exists():
        raise LedgerError(f"没有这份条款台账：{path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LedgerError(f"条款台账读不了（TOML 坏了？）：{path}（{exc}）") from exc
    rows = data.get("clause")
    if not isinstance(rows, list) or not rows:
        raise LedgerError(f"条款台账里没有 `[[clause]]` 条目：{path}")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise LedgerError(f"第 {index} 条条款不是表：{row!r}")
        out.append(row)
    return out


def check_clauses(rows: Iterable[dict[str, Any]], root: Path = ROOT) -> list[str]:
    """核条款台账 —— 回一串人话问题（**空列表 = 全过**）。

    ★ 与 `check_entries` 的差异（卡 162 的核心判据）：
      - `status` 必须是 `covered`/`partial`/`unjudgeable` 之一；
      - `unjudgeable` **必须带 `note`**（空就红 —— 这是本卡最关键的一条）；
      - `covered` 必须有 `judge` 与 `nail`（缺一就红）；
      - `partial` 必须有 `judge`（有判据但缺一半 ⇒ nail 可缺）；
      - 任何非哨兵的 `judge` 路径必须存在；任何非哨兵的 `nail` 用例名必须真在测试文件里。
    """
    problems: list[str] = []
    for row in rows:
        rid = str(row.get("id") or "（无 id）")
        status = str(row.get("status") or "").strip()
        judge = str(row.get("judge") or "").strip()
        nail = str(row.get("nail") or "").strip()
        note = str(row.get("note") or "").strip()

        if status not in CLAUSE_STATUSES:
            allowed = "/".join(CLAUSE_STATUSES)
            problems.append(
                f"{rid} status 不合法：{status or '（空）'}（只认 {allowed}）")

        # ★ 本卡最关键的一条：unjudgeable 必须带理由
        if status == "unjudgeable" and not note:
            problems.append(
                f"{rid} status=unjudgeable 但 note 为空 —— "
                "「用一句人话糊过去」不许蒙混：要么给机器判据，要么写清为什么判不了")

        # covered 必须判据 + 钉子都在
        if status == "covered":
            if judge in ("", NONE_MARK):
                problems.append(f"{rid} status=covered 却没有 judge（判据在哪？）")
            if nail in ("", NONE_MARK):
                problems.append(f"{rid} status=covered 却没有 nail（反例钉子在哪？）")

        # partial 必须有判据（nail 可缺）
        if status == "partial" and judge in ("", NONE_MARK):
            problems.append(f"{rid} status=partial 却没有 judge（半覆盖也要指出判据在哪）")

        # 非哨兵 judge ⇒ 路径必须存在
        if judge not in ("", NONE_MARK):
            path = judge_path(judge)
            if not path or not (root / path).exists():
                problems.append(f"{rid} judge 路径不存在：{path or judge}")

        # 非哨兵 nail ⇒ 必须合 tests/…或 scripts/…::<用例名>、文件在、def 在
        if nail not in ("", NONE_MARK):
            match = NAIL_RE.match(nail)
            if not match:
                problems.append(
                    f"{rid} nail 写法不对（要 tests/…或 scripts/…::<用例名>）：{nail}")
            else:
                test_file = root / match.group("file")
                if not test_file.exists():
                    problems.append(f"{rid} nail 测试文件不存在：{match.group('file')}")
                else:
                    name = case_name(match.group("case"))
                    text = test_file.read_text(encoding="utf-8")
                    if not defines_case(text, name):
                        problems.append(
                            f"{rid} nail 用例名在 {match.group('file')} 里找不到："
                            f"{match.group('case')}")
    return problems


def _print_clauses(rows: list[dict[str, Any]]) -> None:
    print(f"=== 条款台账：{len(rows)} 条 ===")
    for status in CLAUSE_STATUSES:
        group = [row for row in rows if str(row.get("status")) == status]
        print(f"-- {status}（{len(group)}）")
        for row in group:
            print(f"  {row.get('id'):<8} {row.get('clause')}")
            if str(row.get("note") or "").strip():
                print(f"          {row.get('note')}")


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
    parser = argparse.ArgumentParser(
        description="不变量台账 + 条款台账的核查器：核判据路径与反例钉子真的存在")
    parser.add_argument("--ledger", default=None,
                        help="台账路径（默认：不变量台账 复盘/不变量台账.toml；"
                             "与 --clauses 同用时指条款台账路径）")
    parser.add_argument("--check", action="store_true",
                        help="逐条核 judge 路径与 nail 用例名（对不上退 1）")
    parser.add_argument("--missing", action="store_true", help="只列 missing / partial（待验台账）")
    parser.add_argument("--list", action="store_true", help="按 status 分组打印")
    parser.add_argument("--clauses", action="store_true",
                        help="核条款台账（复盘/条款台账.toml）：unjudgeable 必须带 note；"
                             "covered 必须有 judge+nail；指针必须存在")
    args = parser.parse_args(argv)
    if not (args.check or args.missing or args.list or args.clauses):
        args.check = True  # 不给子命令 = 默认核一遍不变量台账

    # --clauses 走另一份台账 + 另一套状态集合
    if args.clauses:
        ledger_path = Path(args.ledger) if args.ledger else DEFAULT_CLAUSE_LEDGER
        try:
            rows = load_clauses(ledger_path)
        except LedgerError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        problems = check_clauses(rows)
        if problems:
            for item in problems:
                print(f"[FAIL] {item}", flush=True)
            print(f"[FAIL] {len(problems)} 条对不上 —— 条款台账不许烂掉"
                  "（先修指针，或老实标 unjudgeable + 给理由）", flush=True)
            return 1
        stat = {s: sum(1 for r in rows if str(r.get("status")) == s) for s in CLAUSE_STATUSES}
        print(f"[OK ] 条款台账 {len(rows)} 条全部核过：判据路径与钉子用例名都在、"
              f"unjudgeable 都带理由（covered {stat['covered']} / partial {stat['partial']} / "
              f"unjudgeable {stat['unjudgeable']}；后两类是诚实态、不是错误）", flush=True)
        if args.list:
            _print_clauses(rows)
        return 0

    try:
        rows = load_ledger(Path(args.ledger) if args.ledger else DEFAULT_LEDGER)
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
