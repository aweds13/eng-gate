r"""台账驱动选测（TIA）：改动文件 → 台账 `test:` 指针 → 只跑该跑的那批（卡 E51 · 段 1 / E36）。

## 为什么是台账，不是覆盖率

本仓的**唯一映射源**是 `docs/traceability.toml`：每条 entry 用 `file:` / `text:` 指向实现、
用 `test:` 指向用例（`test:文件名` 或 `test:文件名::用例名`，文件名口径与
`scripts/audit_progress.py::eval_assertion` 的 `test:` 分支**同一把尺子**：`tests/<文件名>`）。
覆盖率映射（`scripts/tia_map.py`）是另一条可选路径（`TF_TIA=1`），本工具**不引入第二套真相**。

## 三道闸（少跑的全部安全边界）

1. **台账闸**：改动文件在台账里没有任何 entry 指向 ⇒ 判不出 ⇒ **全量**；
   条目读到了但没有 `test:` 指针 ⇒ 选集为空 ⇒ **全量**。
2. **夜间闸**：最近一次夜间全量绿已超过 24 小时（或没有记录） ⇒ **全量**
   （记录由 `tools/wb_nightly.py` 产出，`gates/diag/nightly/nightly-*.json`）。
3. **判据本体闸**：碰了 `scripts/run_gates.py` / `gates/defs/**` / 本工具自身 / pytest 配置
   ⇒ **全量**（改判据的人必须让全量把判据自己检一遍）。

任一条命中都返回 `fallback=True` 并写明原因；**不许静默少跑**。
选测只决定「跑哪些用例」，**不改变 `exit_code` 语义**（不通过仍是不通过）。

## 用法

    python -X utf8 tools/pytest_select.py --changed src/timeflow/core/ledger/ledger.py
    python -X utf8 tools/pytest_select.py --changed-from HEAD^ --json
    python -X utf8 tools/pytest_select.py --replay 20 --json     # 回放判据（最近 20 笔）

`--changed-from <REV>` 取的是**该提交自己的改动面**（`git show --name-only`，与审计 `changed_files`
同口径）。退出码：`0` = 选出了要跑的用例；`1` = 退回全量（这是**正常兜底**，不是错误）；
`2` = 参数/环境读不到（连兜底都判不了）。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent

#: 台账（唯一映射源）。只读，本工具**不写**。
LEDGER_REL = Path("docs") / "traceability.toml"

#: 记账 / 文档层：没有代码用例可跑，不算「漏跑」。全部是这类改动 ⇒ 空选集（`fallback=False`）。
#: 这些目录在审计 ⑫ 里本来就是豁免清单（`docs/**`、`复盘/**`、`gates/**`）。
IGNORE_PREFIXES: tuple[str, ...] = ("docs/", "复盘/", "gates/", ".wt/", "skills/")

#: 判据本体：碰了就**必须全量**（改判据的人不该拿选测省时间）。
JUDGE_BODY_FILES: tuple[str, ...] = (
    "scripts/run_gates.py",
    "tools/pytest_select.py",
    "tools/wb_nightly.py",
    "tests/conftest.py",
    "pyproject.toml",
)
JUDGE_BODY_PREFIXES: tuple[str, ...] = ("gates/defs/",)

#: 回放判据允许的 `fallback` 笔数上限（段 1 判据 1）。
REPLAY_MAX_FALLBACK = 3

#: 合法 fallback 原因里的特征串（只认这几种；出现别的 ⇒ 判据自己不认识，不许算绿）。
#:
#: ★ 卡 E68：这些串**必须由产出方自己引用**（`select()` 的 f-string 里直接用常量拼），
#:   不许照文档手抄话术 —— 手抄必然与产出方脱节。实测：卡 E52 写下的
#:   `台账里没有任何 test: 指针` 从落地那天起就**没有任何产出方**会生成它，
#:   而真正会生成的 `的条目没有 test: 指针` 反而不在表里 ⇒ 回放判据把一笔
#:   正常的台账欠账（T-BG001）判成「原因不认识」，整道门红。
#:   `tests/test_pytest_select.py` 里有钉子逐串核「表里每个串都有产出方会生成」。
JUDGE_BODY_MARK = "判据本体"
LEDGER_NO_ENTRY_MARK = "在台账里没有 entry 指向"
LEDGER_NO_TEST_MARK = "的条目没有 test: 指针"
KNOWN_FALLBACK_MARKS = (JUDGE_BODY_MARK, LEDGER_NO_ENTRY_MARK, LEDGER_NO_TEST_MARK)


def _known_fallback_reason(reason: str) -> bool:
    """这条 fallback 的原因是不是我们认识的那几种。"""
    return any(m in (reason or "") for m in KNOWN_FALLBACK_MARKS)


class LedgerError(RuntimeError):
    """台账读不到 / 读不懂 / 形状不对 —— 一律 fail closed（返回全量，不猜）。"""


@dataclasses.dataclass(frozen=True)
class Selection:
    """一次选测的结论（纯数据；`reason` 会原样打给人看）。"""

    changed: tuple[str, ...]
    tests: tuple[str, ...]
    fallback: bool
    reason: str
    gates: tuple[str, ...] = ()

    @property
    def pytest_args(self) -> list[str]:
        """接在 pytest 后面的参数；回退全量 ⇒ 空（命令逐字不变）。"""
        if self.fallback or not self.tests:
            return []
        # `--no-cov`：只跑几条用例时覆盖率必然不达 70（与 `run_gates.quick_test_job` 同理）。
        return [*self.tests, "--no-cov"]


@dataclasses.dataclass(frozen=True)
class LedgerIndex:
    """台账索引：`sources[源文件] = 该文件所在条目的用例文件`；`entry_tests[条目] = 用例文件`。"""

    sources: dict[str, tuple[str, ...]]
    entry_tests: dict[str, tuple[str, ...]]
    test_files: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ReplayRow:
    rev: str
    task: str
    fallback: bool
    tests: tuple[str, ...]
    expected: tuple[str, ...]
    missing: tuple[str, ...]
    reason: str


@dataclasses.dataclass(frozen=True)
class Replay:
    rows: tuple[ReplayRow, ...]
    fallbacks: int
    ok: bool
    #: 其中「因为碰了判据本体」的那几笔 —— 这是**设计如此**，不该算进覆盖率欠账（卡 E52 修）。
    judge_body_fallbacks: int = 0

    @property
    def coverage_fallbacks(self) -> int:
        """真正说明「台账没登记全」的 fallback 笔数。"""
        return self.fallbacks - self.judge_body_fallbacks


def norm_paths(paths: Iterable[str]) -> list[str]:
    """POSIX 化 + 去 `./` 前缀 + 去重（保序）。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        p = str(raw).replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def test_file_of(pointer: str) -> str | None:
    r"""`test:test_x.py::case` → `tests/test_x.py`（与 `audit_progress` 的 `test:` 分支同口径）。

    就一条规则：**用例名剥掉，文件挂在 `tests/` 下**。不认第二种写法 ——
    两边算出不同文件名就等于台账里有两套真相。
    """
    if not pointer.startswith("test:"):
        return None
    fname = pointer[len("test:"):].partition("::")[0].strip()
    if not fname:
        return None
    return f"tests/{fname}"


def source_path_of(pointer: str) -> str | None:
    """`file:路径` / `text:路径::图案` → 源文件路径（`test:` 不算源文件）。"""
    if pointer.startswith("test:"):
        return None
    kind, _, rest = pointer.partition(":")
    if kind not in {"file", "text"} or not rest:
        return None
    path = rest.partition("::")[0].strip()
    return path or None


#: 计划中的条目（`todo` / `deferred`）**不是映射证据** —— 它们的 `test:` 指针常常还没落地
#: （实测 T-AG494 指着两个不存在的用例文件）。把它们算进映射 ⇒ 每笔都假红退回全量。
#: `done` / `partial` 才是「已实现的部分」，按它们选测。
PLANNED_STATUSES: frozenset[str] = frozenset({"todo", "deferred"})


def ledger_index(data: dict[str, Any]) -> LedgerIndex:
    """把台账编译成索引；形状不对 ⇒ `LedgerError`（不猜、不降级成空索引）。

    - 只认 `done` / `partial` 条目（计划中的条目不是证据，见 `PLANNED_STATUSES`）；
    - `file:` / `text:` 指向 `tests/*.py` 的，**本身也算用例文件**（台账常常这样写，
      不认它就会把「有测试文件、但没有 test: 指针」判成空集）。
    """
    entries = data.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise LedgerError("台账没有 [entries.*]（读不到指针就别猜）")
    sources: dict[str, set[str]] = {}
    entry_tests: dict[str, tuple[str, ...]] = {}
    for eid, entry in entries.items():
        if not isinstance(entry, dict):
            raise LedgerError(f"{eid}: 不是 table")
        if str(entry.get("status")) in PLANNED_STATUSES:
            continue
        evidence = entry.get("evidence") or []
        if not isinstance(evidence, list):
            raise LedgerError(f"{eid}: evidence 不是数组")
        tests: list[str] = []
        paths: list[str] = []
        for item in evidence:
            if not isinstance(item, str) or ":" not in item:
                raise LedgerError(f"{eid}: 证据格式不对 {item!r}")
            one = test_file_of(item)
            if one is not None:
                tests.append(one)
                continue
            path = source_path_of(item)
            if path is None:
                continue
            paths.append(path)
            if path.startswith("tests/") and path.endswith(".py"):
                tests.append(path)
        ordered = tuple(sorted(set(tests)))
        entry_tests[str(eid)] = ordered
        for path in set(paths):
            sources.setdefault(path, set()).update(ordered)
    return LedgerIndex(
        sources={k: tuple(sorted(v)) for k, v in sources.items()},
        entry_tests=entry_tests,
        test_files=tuple(sorted({t for ts in entry_tests.values() for t in ts})),
    )


def load_ledger(root: Path | None = None) -> dict[str, Any]:
    """读台账；读不到 / TOML 坏 ⇒ `LedgerError`（调用方一律 fail closed）。"""
    base = Path(root) if root is not None else ROOT
    path = base / LEDGER_REL
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerError(f"台账读不到：{path}（{type(exc).__name__}）") from exc
    try:
        data = tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        raise LedgerError(f"台账解析不了：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise LedgerError(f"台账顶层不是 table：{path}")
    return data


def code_paths(paths: Iterable[str]) -> list[str]:
    """改动面里的**代码**文件（记账/文档层不算）。空列表 = 这一笔没有代码改动。"""
    return [p for p in norm_paths(paths) if not p.startswith(IGNORE_PREFIXES)]


def judge_body_hits(paths: Iterable[str]) -> list[str]:
    """改动面里碰了判据本体的文件（空列表 = 没碰）。"""
    hits: list[str] = []
    for p in paths:
        if p in JUDGE_BODY_FILES or p.startswith(JUDGE_BODY_PREFIXES):
            hits.append(p)
    return hits


def nightly_recent(root: Path | None = None, now: dt.datetime | None = None) -> tuple[bool, str]:
    """闸二：问 `tools/wb_nightly`「最近一次夜间全量绿 ≤24 小时吗」。"""
    try:
        import wb_nightly  # 同目录：`tools/` 已在 sys.path（脚本方式）或用下面的兜底
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import wb_nightly  # type: ignore[no-redef]
    return wb_nightly.recent_full_ok(root, now=now)


def _fallback(changed: Iterable[str], reason: str, gate: str) -> Selection:
    return Selection(
        changed=tuple(changed), tests=(), fallback=True, reason=reason, gates=(gate,)
    )


def select(
    changed: Iterable[str],
    *,
    root: Path | None = None,
    ledger: dict[str, Any] | None = None,
    nightly_ok: bool | None = None,
    now: dt.datetime | None = None,
) -> Selection:
    """改动文件 → 用例文件；判不出 ⇒ 全量，并把原因写进 `reason`。

    `nightly_ok` 显式给 `True` 只在**回放历史提交**时用（那些提交没有当日的夜间记录，
    闸二不适用）；正常调用**必须**留 `None`，让闸二自己判。
    """
    base = Path(root) if root is not None else ROOT
    norm = norm_paths(changed)
    # 闸三先判：`gates/defs/**` 同时也是「记账/文档层」前缀，但改它就是改判据本体 ⇒ 必须全量。
    judge = judge_body_hits(norm)
    if judge:
        return _fallback(norm, f"闸三：碰了判据本体 {judge[:5]} ⇒ 全量（宁可多跑）", "judge_body")

    code = code_paths(norm)
    if not code:
        note = (
            "只有记账/文档改动 ⇒ 没有代码用例要跑（全量仍在收口链 ④）"
            if norm
            else "没有改动 ⇒ 空选集（全量仍在收口链 ④）"
        )
        return Selection(changed=tuple(norm), tests=(), fallback=False, reason=note)

    needs_ledger = any(not (p.startswith("tests/") and p.endswith(".py")) for p in code)
    index = None
    if needs_ledger:
        try:
            data = ledger if ledger is not None else load_ledger(base)
            index = ledger_index(data)
        except LedgerError as exc:
            return _fallback(norm, f"闸一：台账读不懂 ⇒ 全量（{exc}）", "ledger")

    if nightly_ok is None:
        ok, why = nightly_recent(base, now=now)
        nightly_ok = ok
        nightly_note = why
    else:
        nightly_note = "回放模式：闸二不适用（历史提交没有当日夜间记录）"
    if not nightly_ok:
        return _fallback(norm, f"闸二：{nightly_note} ⇒ 全量", "nightly")

    chosen: list[str] = []
    unmapped: list[str] = []
    empty_entry: list[str] = []
    for p in code:
        if p.startswith("tests/") and p.endswith(".py"):
            if not (base / p).is_file():
                return _fallback(norm, f"用例文件不存在/已删：{p} ⇒ 全量", "ledger")
            if p not in chosen:
                chosen.append(p)
            continue
        if index is None:  # 只有用例文件改动时不会走到这里；防御：判不出 ⇒ 全量
            return _fallback(norm, f"闸一：没有台账索引却要判 {p} ⇒ 全量", "ledger")
        tests = index.sources.get(p)
        if tests is None:
            unmapped.append(p)
            continue
        if not tests:
            empty_entry.append(p)
            continue
        for t in tests:
            if t not in chosen:
                chosen.append(t)

    if unmapped:
        return _fallback(
            norm,
            f"闸一：{unmapped[:5]} {LEDGER_NO_ENTRY_MARK} ⇒ 判不出 ⇒ 全量",
            "ledger",
        )
    if empty_entry:
        return _fallback(
            norm,
            f"闸一：{empty_entry[:5]} {LEDGER_NO_TEST_MARK} ⇒ 选集为空 ⇒ 全量",
            "ledger",
        )
    missing = [t for t in chosen if not (base / t).is_file()]
    if missing:
        return _fallback(
            norm,
            f"闸一：台账 test: 指针指向不存在的用例文件 {missing[:5]} ⇒ 全量",
            "ledger",
        )
    if not chosen:
        return _fallback(norm, "闸一：选集为空 ⇒ 全量（空集不许伪装成“跑过了”）", "ledger")

    tests = tuple(sorted(chosen))
    return Selection(
        changed=tuple(norm),
        tests=tests,
        fallback=False,
        reason=f"按台账选出 {len(tests)} 个用例文件（串行 + --no-cov）",
    )


def payload(selection: Selection) -> dict[str, object]:
    """`--json` 的固定键（键名是判据，别改名）。"""
    return {
        "changed": list(selection.changed),
        "tests": list(selection.tests),
        "fallback": bool(selection.fallback),
        "reason": selection.reason,
        "gates": list(selection.gates),
    }


# ---------------------------------------------------------------- git 读法（回放判据用）
def _git(args: list[str], root: Path | None = None) -> str:
    base = Path(root) if root is not None else ROOT
    done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(base),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.stdout or ""


def git_changed(rev: str, root: Path | None = None) -> list[str]:
    """`<rev>` 这一笔自己的改动文件（与审计 `changed_files` 同口径：`git show --name-only`）。"""
    out = _git(["show", "--name-only", "--format=", rev], root)
    return [p for p in out.splitlines() if p.strip()]


def git_task(rev: str, root: Path | None = None) -> str:
    """这一笔的 `Task:` trailer（恰好一个台账编号；没有就返回空串）。"""
    return _git(
        ["log", "-1", "--format=%(trailers:key=Task,valueonly)", rev], root
    ).strip()


def log_batch(count: int, root: Path | None = None) -> dict[str, tuple[str, tuple[str, ...]]]:
    """一次 git log 取回最近 count 笔的「Task trailer + 改动文件」，按 rev 建索引。

    ★ 为什么批量（卡 E127 复盘实测）：replay() 原来每笔起**两次**子进程
      （git show --name-only + git log -1 --format=trailers）。Windows 上每次约 0.086 s，
      300 笔 ≈ 600 次 subprocess ≈ 50 s —— 窗口稍放大就贵到没人愿意开。改成一次
      git log -z --name-only 批量读：n=20 0.12 s / n=60 0.22 s / n=100 0.37 s / n=300 0.42 s。
      读数与逐笔两条命令**逐笔逐字一致** —— 由 tests/test_pytest_select.py
      的 test_log_batch_agrees_with_the_per_commit_reads 在真历史上逐笔比对（rev / 文件列表 /
      Task trailer 三样都要相等）。

    记录之间用 NUL 分隔、记录头用  标记 ⇒ 文件名里有空格/引号都不用转义。解析不出来的
    记录**不进**返回值，调用方按「缺的那笔回落到逐笔读」处理（批量只是加速，不是新的真相源）。
    """
    out = _git(
        [
            "log",
            "-z",
            f"-{int(count)}",
            "--name-only",
            "--format=%x01%h%x1f%(trailers:key=Task,valueonly)",
        ],
        root,
    )
    rows: dict[str, tuple[str, tuple[str, ...]]] = {}
    for chunk in out.split("\x01"):
        if not chunk.strip():
            continue
        head, _, rest = chunk.partition("\n")
        rev, _, task = head.partition("\x1f")
        rev = rev.strip()
        if not rev:
            continue
        files = tuple(p.strip() for p in rest.split("\x00") if p.strip())
        # ★ 卡 E163：没有 Task: trailer 的提交，%x1f 后面紧跟的是 -z 的记录分隔符 NUL，
        #   task.strip() 会把 NUL 留下来 ⇒ 与逐笔读的 git_task()（空串）对不上，
        #   判据报「assert '\x00' == ''」。剥掉 NUL 与空白才是「这一笔没有台账号」。
        rows[rev] = (task.strip("\x00 \t\r\n"), files)
    return rows


def replay(
    count: int = 20,
    *,
    root: Path | None = None,
    ledger: dict[str, Any] | None = None,
) -> Replay:
    """回放判据：最近 `count` 笔提交，逐笔算选测并核「台账登记的 test: 指针」有没有漏。

    - 该笔的 `Task:` 条目（以及**指向该笔改动文件**的条目）里的 `test:` 指针必须**全部**落在
      选测集合里（这是「没漏检」的最低要求）；
    - 「该笔登记了哪些 test: 指针」这条只在**该笔有代码改动**时成立：纯记账/文档提交没有
      「该跑哪些用例」这个问题（空集就是空集，全量仍在收口链 ④）；
    - `fallback` 的笔数 ≤ `REPLAY_MAX_FALLBACK`（否则说明台账覆盖率不够，先补台账）。
    """
    base = Path(root) if root is not None else ROOT
    data = ledger if ledger is not None else load_ledger(base)
    index = ledger_index(data)
    revs = [r for r in _git(["log", "--format=%h", f"-{int(count)}"], base).splitlines() if r]
    # 提交顺序仍由上面那条 log --format=%h 定（口径不变）；批量只负责把每笔的
    # 「改动文件 + Task trailer」一次取回。批量里查不到的（解析失败/历史太短）回落到逐笔读。
    batch = log_batch(len(revs), base)
    rows: list[ReplayRow] = []
    for rev in revs:
        if rev in batch:
            task, files = batch[rev]
            changed = list(files)
        else:
            changed = git_changed(rev, base)
            task = git_task(rev, base)
        code = code_paths(changed)
        sel = select(changed, root=base, ledger=data, nightly_ok=True)
        expected: set[str] = set()
        if code:
            if task and task in index.entry_tests:
                expected |= set(index.entry_tests[task])
            for p in code:
                if p.startswith("tests/") and p.endswith(".py"):
                    expected.add(p)  # 改过的用例文件自己就进选集（不按"谁引用它"扩）
                else:
                    expected |= set(index.sources.get(p, ()))
        missing = tuple(sorted(expected - set(sel.tests))) if not sel.fallback else ()
        rows.append(
            ReplayRow(
                rev=rev,
                task=task,
                fallback=sel.fallback,
                tests=sel.tests,
                expected=tuple(sorted(expected)),
                missing=missing,
                reason=sel.reason,
            )
        )
    fallbacks = sum(1 for r in rows if r.fallback)
    judge_body = sum(1 for r in rows if r.fallback and JUDGE_BODY_MARK in r.reason)
    # ★ 判据本体那几笔是「宁可多跑」的设计，不是台账欠账 ⇒ 只把剩下的算成覆盖率欠账。
    #   但**每一笔** fallback 的原因必须是我们认识的那几种，出现没见过的原因 ⇒ 不许算绿。
    unknown = [r for r in rows if r.fallback and not _known_fallback_reason(r.reason)]
    ok = (fallbacks - judge_body) <= REPLAY_MAX_FALLBACK and not unknown and all(
        not r.missing for r in rows
    )
    return Replay(rows=tuple(rows), fallbacks=fallbacks, ok=ok, judge_body_fallbacks=judge_body)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台账驱动选测（卡 E51 / E36）")
    ap.add_argument("--changed", nargs="+", metavar="路径", help="改动文件列表")
    ap.add_argument("--changed-from", metavar="REV", help="由 git 现算该提交的改动面")
    ap.add_argument("--replay", type=int, metavar="N", help="回放最近 N 笔提交（判据用）")
    ap.add_argument("--root", default=None, help="仓库根（默认本文件上一级）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（键名固定）")
    a = ap.parse_args(argv)
    base = Path(a.root) if a.root else ROOT

    if a.replay is not None:
        try:
            result = replay(a.replay, root=base)
        except (LedgerError, OSError) as exc:
            print(f"[FAIL] 台账读不懂 ⇒ 回放判不了：{exc}", file=sys.stderr)
            return 2
        if a.json:
            print(
                json.dumps(
                    {
                        "ok": result.ok,
                        "fallbacks": result.fallbacks,
                        "rows": [dataclasses.asdict(r) for r in result.rows],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for r in result.rows:
                mark = "全量" if r.fallback else f"选 {len(r.tests)}"
                print(f"{r.rev}  {mark}  {r.reason}")
                if r.missing:
                    print(f"   ★ 漏了台账指针：{list(r.missing)}")
            print(f"回放 {len(result.rows)} 笔：fallback {result.fallbacks} 笔"
                  f"（上限 {REPLAY_MAX_FALLBACK}）→ {'通过' if result.ok else '不通过'}")
        return 0 if result.ok else 1

    changed: list[str] = list(a.changed or [])
    if a.changed_from:
        changed += git_changed(a.changed_from, base)
    if not changed:
        print("[FAIL] 没有改动清单：给 --changed 或 --changed-from", file=sys.stderr)
        return 2
    selection = select(changed, root=base)
    if a.json:
        print(json.dumps(payload(selection), ensure_ascii=False, indent=2))
    else:
        print(selection.reason)
        for t in selection.tests:
            print(f"  {t}")
    return 0 if not selection.fallback else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
