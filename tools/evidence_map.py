r"""台账证据 ↔ 源文件 的倒排索引 —— "少读"的第一件：改文件之前先问"会碎什么"（T-G108）。

**它解决的是哪一次真事故**（T-G108 的来由，见 `复盘/少读工具-T-G108.md`）：某卡改了
`tools/wb_dash.py` 里 `_state` 的**签名** → 更早的 `T-G93` 台账里那条"整段签名"的证据
**字面失配** → 提交时被 `audit` 红（`_myday_rank_plan` 那次同理，T-G86 受害）。当时的流程是
**事后被打脸**；这个工具让同一句话能**事前**问出来：

    改 tools/wb_dash.py 之前 —— 哪几条台账断言会碎？

★ **求值口径只有一个真源**：直接复用 `scripts/audit_progress.py` 的 `eval_assertion`
（第 154–189 行；它依赖的仓库事实取数在同文件 `routes()/tables()/columns()/declared_actions()/
registered_actions()/views()`）。**不另写一份** —— 本项目一贯规矩：别写第二套口径
（`复盘/外包-卡表与规矩.md` §13 / T-G93 的 `parse_events` 复用就是同一条）。
这样"本工具与 audit 不一致"在结构上就**不可能**发生。

★ **只读**：绝不改台账、绝不改任何文件（`--stale` 会读源码求值，但只读）。

用法：
    python -X utf8 tools/evidence_map.py --file tools/wb_dash.py   # 这个文件上挂着哪些断言
    python -X utf8 tools/evidence_map.py --entry T-G93             # 这张卡挂了哪些断言
    python -X utf8 tools/evidence_map.py --stale                   # 当前已失配的断言（会读源码）
    python -X utf8 tools/evidence_map.py --stat                    # 汇总：总数 / 指向文件 / 已失配
    （附加：--ledger <路径> 指定台账，默认 docs/traceability.toml —— 测试用）
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / "docs" / "traceability.toml"

# 求值口径的唯一真源（见文件头）：把 scripts/ 挂上，直接调审计自己。
sys.path.insert(0, str(ROOT / "scripts"))
import audit_progress  # noqa: E402

FILE_KINDS = ("file", "text", "test")  # 会指向某个仓库路径的三类断言
PATTERN_CLIP = 80                      # 图案最多显示多少字符（人看，不刷屏）
OK, MISS, NOT_RUN = "命中", "失配", "-"


def load_ledger(path: str | Path | None = None) -> dict:
    """读台账（tomllib，只读）。"""
    target = Path(path) if path else DEFAULT_LEDGER
    with target.open("rb") as fh:
        return tomllib.load(fh)


def norm_path(raw: object) -> str:
    """统一成仓库内的 posix 相对路径（比对才稳，Windows 反斜杠 / `./` 都抹平）。"""
    return str(raw).replace("\\", "/").removeprefix("./")


def assertion_path(assertion: str) -> str | None:
    """这条断言指向哪个仓库文件；语义类（route/table/column/ui）返回 None。"""
    kind, sep, rest = assertion.partition(":")
    if not sep:
        return None
    if kind == "file":
        return norm_path(rest)
    if kind == "text":
        path, has_sep, _pattern = rest.partition("::")
        return norm_path(path) if has_sep else None
    if kind == "test":
        return norm_path("tests/" + rest)   # audit 的 test: 解析成 tests/<rest>
    return None


def assertion_pattern(assertion: str) -> str:
    """`text:` 的图案部分（`::` 之后）；其余类型返回空串。"""
    kind, _, rest = assertion.partition(":")
    if kind != "text":
        return ""
    _, sep, pattern = rest.partition("::")
    return pattern if sep else ""


def evaluate(assertion: str) -> tuple[bool, str]:
    """求值 —— 直接调审计的 `eval_assertion`（同一份口径，不可能与它不一致）。"""
    return audit_progress.eval_assertion(assertion)


def _entries(data: dict) -> dict:
    return data.get("entries", {})


def assertions_on_file(data: dict, target: str) -> list[tuple[str, str]]:
    """挂在 `target` 这个文件上的断言 `[(条目 id, 断言原文), …]`（改前先看这一列）。"""
    want = norm_path(target)
    out: list[tuple[str, str]] = []
    for eid in sorted(_entries(data)):
        for assertion in _entries(data)[eid].get("evidence", []):
            if assertion_path(assertion) == want:
                out.append((eid, assertion))
    return out


def entry_assertions(data: dict, eid: str) -> list[str]:
    """某条卡挂的全部断言（原样，含语义类）。"""
    return list(_entries(data).get(eid, {}).get("evidence", []))


def stale_assertions(data: dict) -> list[tuple[str, str, str]]:
    """当前已失配的断言 `[(条目 id, 断言原文, 求值说明), …]`。

    ★ 遍历口径与 `audit_progress.audit_evidence` 一致：**只求值 `status=done`** 的条目
    （`todo/partial/deferred` 的断言本来就没打算成立，报出来是噪音）。
    """
    out: list[tuple[str, str, str]] = []
    for eid in sorted(_entries(data)):
        entry = _entries(data)[eid]
        if str(entry.get("status")) != "done":
            continue
        for assertion in entry.get("evidence", []):
            passed, desc = evaluate(assertion)
            if not passed:
                out.append((eid, assertion, desc))
    return out


def stat(data: dict) -> dict:
    """汇总：条目数 / 断言总数 / 各类型条数 / 指向文件的条数 / 已失配条数。"""
    entries = _entries(data)
    by_kind: Counter[str] = Counter()
    total = 0
    for entry in entries.values():
        for assertion in entry.get("evidence", []):
            total += 1
            by_kind[assertion.partition(":")[0]] += 1
    return {
        "entries": len(entries),
        "done": sum(1 for e in entries.values() if str(e.get("status")) == "done"),
        "total": total,
        "by_kind": dict(by_kind),
        "file_like": sum(by_kind.get(k, 0) for k in FILE_KINDS),
        "stale": len(stale_assertions(data)),
    }


def format_row(eid: str, assertion: str, mark: str) -> str:
    """一行五栏：条目 / 类型 / 路径 / 图案（截断 80）/ 命中与否。"""
    kind, _, rest = assertion.partition(":")
    if kind in FILE_KINDS:
        path = assertion_path(assertion) or "-"
        pattern = assertion_pattern(assertion)
    else:
        path, pattern = "-", rest
    if len(pattern) > PATTERN_CLIP:
        pattern = pattern[: PATTERN_CLIP - 1] + "…"
    return f"{eid} | {kind} | {path} | {pattern or '-'} | {mark}"


def _print_rows(rows: list[tuple[str, str, str]]) -> None:
    if not rows:
        print("  （没有）")
        return
    for eid, assertion, mark in rows:
        line = "  " + format_row(eid, assertion, mark)
        if mark == MISS:
            line += f"  → {evaluate(assertion)[1]}"
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="台账证据 ↔ 源文件 倒排索引（只读）")
    parser.add_argument("--file", help="只列挂在这个仓库文件上的断言")
    parser.add_argument("--entry", help="只列这张台账卡的断言")
    parser.add_argument("--stale", action="store_true", help="只列当前已失配的断言（会读源码求值）")
    parser.add_argument("--stat", action="store_true", help="汇总：总数 / 指向文件 / 已失配")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                        help="台账路径（默认 docs/traceability.toml）")
    args = parser.parse_args(argv)

    try:
        data = load_ledger(args.ledger)
    except OSError as exc:
        print(f"[FAIL] 读不到台账 {args.ledger}：{exc}", file=sys.stderr)
        return 2

    if args.file:
        rows = assertions_on_file(data, args.file)
        print(f"=== 挂在 {norm_path(args.file)} 上的断言（{len(rows)} 条）===")
        _print_rows([(eid, a, OK if evaluate(a)[0] else MISS) for eid, a in rows])
        return 0

    if args.entry:
        assertions = entry_assertions(data, args.entry)
        print(f"=== {args.entry} 挂的断言（{len(assertions)} 条）===")
        _print_rows([(args.entry, a, OK if evaluate(a)[0] else MISS) for a in assertions])
        return 0

    if args.stale:
        rows = stale_assertions(data)
        print(f"=== 当前已失配的断言（{len(rows)} 条；只查 status=done）===")
        _print_rows([(eid, a, MISS) for eid, a, _desc in rows])
        return 0

    # 默认（也含 --stat）：给总览
    s = stat(data)
    print(f"=== 台账证据总览：{args.ledger} ===")
    print(f"  条目：{s['entries']} 条（其中 done {s['done']} 条）")
    print(f"  断言总数：{s['total']}")
    print(f"  指向仓库文件（{'/'.join(FILE_KINDS)}）：{s['file_like']}")
    for kind in sorted(s["by_kind"]):
        print(f"    {kind:<8}{s['by_kind'][kind]}")
    print(f"  已失配（口径同 audit_progress）：{s['stale']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
