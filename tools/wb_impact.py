r"""影响面反推 `tools/wb_impact.py`（卡 142 · T-G241）—— 只标准库 + 本仓两处真源。

为什么有它：今晚连续四次「写卡人漏项」（卡 121 / 125 / 120 / 140），共同形态是
**「改了某文件 ⇒ 还有哪些文件会被连带」靠手打、不靠机器算**。本工具把这件事变成一条命令：

    # 改了什么 → 受影响的门 + 钉住这些文件的测试 +（建议的 --allow 与 pytest 目标）
    python -X utf8 tools/wb_impact.py --files tools/pool/task.py

    # 事前防呆：改动面里有没有文件不在卡的声明域里（越界 → 非零退出并点名）
    python -X utf8 tools/wb_impact.py --files tools/pool/task.py --declared "tools/**"

输入（**恰好给一个**）：
    --files <路径…>        显式给改动面
    --card <卡号>          读 `docs/workbacklog.toml` 里该卡的 `files`
    --task <任务号>        读 `gates/diag/batch/<任务>.toml` 全体成员的 `paths`

★ **不写第二份真源**（本仓最忌）：
  - 「门 × 输入」表**只读** `scripts/run_gates.py` 的 `DOOR_INPUTS`（T-G239 · 卡 140），
    本文件**不抄一份** —— 桩掉那张表、本工具输出就跟着变（钉子⑤钉死这条）；
  - 白名单判据**只调** `pool.review.outside_allow()`（卡 106 收敛成的唯一实现）；
  - 「任务预声明」只调 `pool.task.manifest_path()` / `load_manifest()`。
★ 判据方向 = **宁多勿漏**：命中不了任何门输入的路径 ⇒ 由 `run_gates.plan_affected` 判「跑全量」；
  表里**没有**输入映射的门 ⇒ **永远跑**（原样列进输出）。
★ 本工具给出的是**建议**，不是判据 —— 收口仍以 `--allow` 与**全量门禁**为准（原话写进输出）。

★ 边界（如实写，未覆盖）：
  - 测试命中是**文本 grep**（词边界），不是"谁真的 import 了它"的静态分析 ——
    注释 / docstring 里提一句也算命中（宁多勿漏，但也可能多报）；
  - 单字母 / 极短的主干（如 `b.py`）会靠 `stem` 命中大量测试 —— 本工具只列建议、不裁，
    并给每条标**强/弱**（`path`·`module` = 强，只有 `stem` = 弱）；
  - `--card` 只认 `docs/workbacklog.toml` 的 `files`；`--task` 只认 batch 预声明的 `paths`。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
for _extra in (ROOT / "scripts", ROOT / "tools"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import run_gates as rg  # noqa: E402 —— 门 × 输入表唯一真源（只读）
import wb_plan  # noqa: E402 —— 台账分片（卡 E89）：分片目录 / 分片读法只此一份
from pool import review as pool_review  # noqa: E402 —— 白名单判据唯一实现
from pool import task as pool_task  # noqa: E402 —— 任务预声明唯一真源

__all__ = [
    "GatePlan",
    "Impact",
    "Pin",
    "UsageError",
    "all_doors",
    "analyze",
    "check_domain",
    "main",
    "module_name",
    "pinned_tests",
    "plan_gates",
]

#: 由路径推模块名时要剥掉的「源码根」（`src/timeflow/api/app.py` ⇒ `timeflow.api.app`）。
_SOURCE_ROOTS = ("src", "tools", "scripts", "examples", "harness")


class UsageError(Exception):
    """参数 / 取数的失败 ⇒ 退 2（是"我没法算"，不是"分析结论")。"""


# ================================================================ ① 受影响的门


def all_doors() -> tuple[str, ...]:
    """全量门清单（顺序 = `run_gates.build_jobs(False, False)`）。

    ★ **现读真源**，不抄一份 —— 门清单一变（加门 / 改名），本工具跟着变。
    """
    return tuple(name for name, _ in rg.build_jobs(quick=False, fast=False))


@dataclasses.dataclass(frozen=True)
class GatePlan:
    """① 受影响的门（字段名与 `run_gates.AffectedPlan` 对齐，外加 `always` 一份显式拆开）。"""

    inputs: tuple[str, ...]
    always: tuple[str, ...]              # 表里没有输入映射 ⇒ 任何改动都可能影响它 ⇒ 永远跑
    matched: tuple[str, ...]             # 输入命中了该门登记的 glob
    ran: tuple[str, ...]                 # always ∪ matched（全量回退时 = 全部门）
    skipped: tuple[tuple[str, str], ...]
    full_fallback: bool
    note: str


def plan_gates(
    paths: Sequence[str],
    *,
    door_inputs: Mapping[str, tuple[str, ...]] | None = None,
    doors: Sequence[str] | None = None,
) -> GatePlan:
    """按「门 × 输入」表反推该跑哪几道门（复用 `run_gates.plan_affected`，不另立判据）。

    ★ `door_inputs=None` ⇒ **现读** `rg.DOOR_INPUTS`；`doors=None` ⇒ **现读** `all_doors()`。
      所以桩掉 `run_gates` 里那张表、本函数输出就跟着变 —— 这正是"不写第二份真源"的机器判据。
    """
    table = rg.DOOR_INPUTS if door_inputs is None else door_inputs
    names = all_doors() if doors is None else tuple(doors)
    plan = rg.plan_affected(paths, names, door_inputs=table)
    return GatePlan(
        inputs=tuple(plan.inputs),
        always=tuple(d for d in names if d not in table),
        matched=tuple(plan.matched),
        ran=tuple(plan.ran),
        skipped=tuple(plan.skipped),
        full_fallback=plan.full_fallback,
        note=plan.note,
    )


# ================================================================ ② 钉住这些文件的测试


def _norm_path(raw: str) -> str:
    """规范成仓库相对、POSIX 斜杠（去 `./` 前缀与尾部 `/`）—— 与 run_gates 同口径。"""
    p = raw.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def module_name(path: str) -> str | None:
    """由文件路径推**模块导入名**（`tools/pool/task.py` ⇒ `pool.task`）。

    只对 `.py` 有效：剥掉首个源码根（`_SOURCE_ROOTS`），`__init__.py` ⇒ 包名，
    其余去掉 `.py` 后缀、路径分隔符换 `.`。推不出（非 `.py`、剥空了）⇒ `None`。
    """
    if not path.endswith(".py"):
        return None
    parts = path.split("/")
    if parts and parts[0] in _SOURCE_ROOTS:
        parts = parts[1:]
    if not parts:
        return None
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts) if parts else None


def _token_re(token: str) -> re.Pattern[str]:
    """词边界匹配 `token`：前一位不是「词字符 / `.` / `-`」，后一位不是词字符。

    ★ 去噪第一道：`serve` 不吃 `server`、`pool.task` 不吃 `pool.tasks`、
      `task.py` 不吃 `my-task.py`。
    """
    return re.compile(rf"(?<![A-Za-z0-9_.\-]){re.escape(token)}(?![A-Za-z0-9_])")


def forms_for(path: str) -> list[tuple[str, re.Pattern[str]]]:
    """一份改动文件的**三种命中写法**（顺序 = 由强到弱）：`path` > `module` > `stem`。"""
    p = _norm_path(path)
    out: list[tuple[str, re.Pattern[str]]] = [("path", _token_re(p))]
    mod = module_name(p)
    if mod:
        out.append(("module", _token_re(mod)))
    stem = p.rsplit("/", 1)[-1]
    if stem and stem != p:
        out.append(("stem", _token_re(stem)))
    return out


@dataclasses.dataclass(frozen=True)
class Pin:
    """② 一条「某测试钉住某文件」的命中（每（测试 × 文件）一条）。"""

    test: str                    # `tests/...` 相对路径
    file: str                    # 被它提到的改动文件
    forms: tuple[str, ...]       # 命中的写法：path / module / stem

    @property
    def strength(self) -> str:
        """`path` 或 `module` ⇒ strong；只有 `stem` ⇒ weak（列出来但标注）。"""
        return "strong" if ({"path", "module"} & set(self.forms)) else "weak"


def pinned_tests(
    files: Sequence[str],
    *,
    tests_root: Path | None = None,
) -> tuple[Pin, ...]:
    """扫 `tests/**`，找**提到**这些文件的测试（三种写法，见 `forms_for`）。

    ★ 去噪：① 词边界（`_token_re`）；② 每（测试 × 文件）只落一条、把命中写法并进 `forms`；
      ③ **只扫 `tests/**`**（不扫全库）—— 免把 changelog / 复盘里**引述**该文件的地方当命中
      （铁律 36：存在性 grep 必须写清路径域）。
    """
    root = (ROOT / "tests") if tests_root is None else Path(tests_root)
    compiled = {f: forms_for(f) for f in files}
    hits: dict[tuple[str, str], set[str]] = {}
    for tf in sorted(root.rglob("*.py")):
        try:
            rel = tf.relative_to(ROOT).as_posix()
        except ValueError:  # pragma: no cover —— 只在 tests_root 在仓外时走
            rel = tf.as_posix()
        text = tf.read_text(encoding="utf-8", errors="replace")
        for f, forms in compiled.items():
            matched = [name for name, rx in forms if rx.search(text)]
            if matched:
                hits.setdefault((rel, f), set()).update(matched)
    return tuple(
        Pin(test=t, file=f, forms=tuple(sorted(v))) for (t, f), v in sorted(hits.items())
    )


# ================================================================ ③ 建议 / 组装


@dataclasses.dataclass(frozen=True)
class Impact:
    """一次影响面反推的**全部**读数（人读与机器读共用这一份）。"""

    inputs: tuple[str, ...]
    gates: GatePlan
    pins: tuple[Pin, ...]

    @property
    def allow(self) -> tuple[str, ...]:
        """建议的 `--allow`：改动面 ∪ 钉住它们的测试（两者都得能进卡的白名单）。"""
        return tuple(sorted({*self.inputs, *(p.test for p in self.pins)}))

    @property
    def pytest_targets(self) -> tuple[str, ...]:
        """建议的 pytest 目标：钉住这些文件的测试（去重、稳定排序）。"""
        return tuple(sorted({p.test for p in self.pins}))

    def to_payload(self) -> dict[str, object]:
        g = self.gates
        return {
            "inputs": list(self.inputs),
            "gates": {
                "always": list(g.always),
                "matched": list(g.matched),
                "ran": list(g.ran),
                "skipped": [{"name": n, "why": w} for n, w in g.skipped],
                "full_fallback": g.full_fallback,
                "note": g.note,
            },
            "pins": [
                {"test": p.test, "file": p.file, "forms": list(p.forms), "strength": p.strength}
                for p in self.pins
            ],
            "suggestion": {
                "allow": list(self.allow),
                "pytest": list(self.pytest_targets),
                "caveat": "建议，不是判据 —— 收口仍以 --allow 与全量门禁为准",
            },
        }


def analyze(files: Sequence[str]) -> Impact:
    """改动面 ⇒ `Impact`（门 + 测试 + 建议）。"""
    inputs = tuple(p for p in (_norm_path(f) for f in files) if p)
    return Impact(inputs=inputs, gates=plan_gates(inputs), pins=pinned_tests(inputs))


def check_domain(changed: Sequence[str], declared: Sequence[str]) -> list[str]:
    """改动面里**不在**声明域里的文件（越界项）。

    ★ 复用 `pool.review.outside_allow()` —— 本仓白名单判据的**唯一实现**（卡 106 收敛），
      与 `tools/wb_review.py` 事后那条同源，只是本工具把它用在**事前**。
    """
    return pool_review.outside_allow([_norm_path(c) for c in changed], list(declared))


# ================================================================ 取数（--card / --task）


def _queue_files(base: Path) -> list[Path]:
    """队列的来源文件：有分片（`docs/backlog/*.toml`）就用分片，否则总表。

    卡 E89：分片在就是台账的现在时；总表只是合并产物，可能还没合出来。
    """
    shards = wb_plan.shard_files(base / "docs" / "backlog")
    return shards or [base / "docs" / "workbacklog.toml"]


def files_from_backlog(card: str, root: Path | None = None) -> list[str]:
    """`--card <卡号>`：读队列里 `id == 卡号` 那张卡的 `files`。

    卡 E89：队列 = 分片 `docs/backlog/*.toml`（有分片时）或总表 `docs/workbacklog.toml`。
    """
    base = Path(root) if root is not None else ROOT
    for path in _queue_files(base):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for c in data.get("cards", []):
            if str(c.get("id", "")) == str(card):
                return [str(f) for f in c.get("files", [])]
    raise UsageError(f"`docs/workbacklog.toml` 里没有卡 {card}（这张卡是不是已经移出了？）")


def files_from_batch(task: str) -> list[str]:
    """`--task <任务号>`：读 `gates/diag/batch/<任务>.toml` 全体成员的 `paths`（并集）。"""
    man = pool_task.load_manifest(task)
    out: list[str] = []
    for m in man.get("member", []):
        out.extend(str(p) for p in m.get("paths", []))
    return out


def resolve_files(files: Sequence[str] | None, card: str | None, task: str | None) -> list[str]:
    """`--files` / `--card` / `--task` **恰好给一个**，解出改动面。"""
    given = [
        n for n, ok in (("--files", bool(files)), ("--card", bool(card)), ("--task", bool(task)))
        if ok
    ]
    if len(given) != 1:
        raise UsageError("`--files` / `--card` / `--task` 必须**恰好给一个**")
    if files:
        return [_norm_path(f) for f in files]
    if card:
        return files_from_backlog(card)
    assert task is not None
    return files_from_batch(task)


# ================================================================ 渲染 / CLI


def render(impact: Impact) -> str:
    """人读那一段（门集合 / 测试清单 / 建议）。"""
    g = impact.gates
    lines = [f"=== 改动面（{len(impact.inputs)} 条）==="]
    lines += [f"  {p}" for p in impact.inputs] or ["  （空）"]
    lines.append("")
    lines.append(f"=== ① 受影响的门（要跑 {len(g.ran)} 道）===")
    lines.append(f"  [永远跑·无输入映射] {len(g.always)} 道：{'、'.join(g.always)}")
    if g.matched:
        lines.append(f"  [输入命中] {len(g.matched)} 道：{'、'.join(g.matched)}")
    else:
        lines.append("  [输入命中] 无 —— 没有任何路径命中门的输入表")
    lines.append(f"  结论：{g.note}")
    if g.full_fallback:
        lines.append("  ★ 宁多勿漏：无命中 ⇒ **不裁**，落全量")
    lines.append("")
    lines.append(f"=== ② 钉住这些文件的测试（{len(impact.pins)} 条命中）===")
    if impact.pins:
        for p in impact.pins:
            tag = "强" if p.strength == "strong" else "弱"
            lines.append(f"  [{tag}] {p.test}  ← {p.file}  （写法：{'、'.join(p.forms)}）")
    else:
        lines.append("  （tests/ 里没扫到）")
    lines.append("")
    lines.append("=== ③ 建议（★ 只是建议，不是判据 —— 收口仍以 --allow 与全量门禁为准）===")
    allow = " ".join(impact.allow) if impact.allow else "（空）"
    targets = " ".join(impact.pytest_targets) if impact.pytest_targets else "（空）"
    lines.append(f"  --allow：{allow}")
    lines.append(f"  pytest 目标：{targets}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="影响面反推：改了什么 → 受影响的门 + 钉住这些文件的测试 + 建议的白名单",
    )
    ap.add_argument("--files", nargs="+", metavar="路径", help="显式给改动面")
    ap.add_argument("--card", help="读 `docs/workbacklog.toml` 里该卡的 `files`")
    ap.add_argument("--task", help="读 `gates/diag/batch/<任务>.toml` 全体成员的 `paths`")
    ap.add_argument("--declared", nargs="+", metavar="路径",
                    help="卡声明的域（glob）—— 只做越界检查")
    ap.add_argument("--check", action="store_true",
                    help="防呆：改动面里有域外文件 ⇒ 非零退出并点名")
    ap.add_argument("--json", action="store_true", help="只打印机器可读 JSON")
    return ap


def _print_check(files: Sequence[str], declared: Sequence[str], *, as_json: bool) -> int:
    offenders = check_domain(files, declared)
    if as_json:
        print(json.dumps(
            {"ok": not offenders, "offenders": offenders, "declared": list(declared),
             "files": list(files)}, ensure_ascii=False, indent=2,
        ))
    elif offenders:
        print(f"★ 越界：{len(offenders)} 个文件不在声明域里：{'、'.join(offenders)}")
        print(f"  声明域：{'、'.join(declared)}")
    else:
        print(f"[OK] 改动面 {len(files)} 个文件全部落在声明域内")
    return 1 if offenders else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check and args.declared is None:
        print("★ `--check` 需要 `--declared <路径…>`（声明域）")
        return 2
    try:
        files = resolve_files(args.files, args.card, args.task)
    except UsageError as exc:
        print(f"★ {exc}")
        return 2
    except (pool_task.BatchError, FileNotFoundError) as exc:
        print(f"★ 取数失败：{exc}")
        return 2
    if args.check or args.declared is not None:
        assert args.declared is not None
        return _print_check(files, args.declared, as_json=args.json)
    impact = analyze(files)
    if args.json:
        print(json.dumps(impact.to_payload(), ensure_ascii=False, indent=2))
    else:
        print(render(impact))
        print("\n--- JSON（机器读）---")
        print(json.dumps(impact.to_payload(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
