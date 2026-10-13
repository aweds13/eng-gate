r"""队列登记审计 `tools/wb_queue_audit.py` —— 一条**只读**判据（卡 216 · T-G329）。

## 为什么有它

卡 197 收口时主控**当场抓到**：`193`/`194`/`195`/`196` 四张卡**已经落地**，可队列
`docs/workbacklog.toml` 里**根本没有它们的条目** ⇒ 没有 `status` 可翻、没有规格可指、
别的工具（排批 / 冲突判定 / 漂移判据）**都看不见它们**。同类病还有一条：**「一卡一号」**
——登记/收尾提交必须用**自己的簿记号**，否则卡 204 那条「已落却仍 pending」判据会**假阳**。

本工具把这两条做成能跑的东西（与 `wb_plan.py check` 的判据**同向**，但各管一段：那边只看
队列里的卡，这边**从 git 反向看**队列有没有漏收）。

## 判据（两条）

1. **孤儿号**：对 `git log` 里**每一条** `Task: <号>` trailer，若那个号**不属于队列里任何一张卡**
   （也不是簿记号，见下）⇒ **点名它**（号 + 那笔提交的短 sha + 提交标题）。
2. **一卡一号**：对队列里**每一条**卡，若它的 `task` 号**在 git 里出现在多笔提交上** ⇒ **点名**
   （多笔提交共用一号会让人误判"这张卡落了"）。

## ★ 口径：什么叫「簿记号」（反向保护①）—— 口径是本卡自己定的，依据如下

本工具保护**「登记/收尾型的台账号」**（如 `T-G305`/`T-G306`/`T-G309`/`T-G310`/`T-G312`/`T-G315`/
`T-G324` 这类**不含卡的**台账号）**不被当成"漏登记"报错**。口径：

> **一个 `Task:` 号若被**至少一笔提交改过队列文件本身**（默认 `docs/workbacklog.toml`），
> 就认它是「簿记号」，不是卡号。**

**依据**：本仓的两类提交在**改的文件**上是天然分开的 ——
  · **登记/收尾**型（`docs(队列): 登记…` / `docs(tools): 队列收尾…`）**干的就是改队列文件**
    （新增卡条目、把 `status` 翻成 `done`），所以它们的号会**改到 `docs/workbacklog.toml`**；
  · **卡的落地**型（`feat…` / `fix…`）改的是**这张卡自己的域**（代码 / 测试 / 那份复盘），
    **一般不碰队列文件**。

实测对得上：卡 216 点名的七个例子（`T-G305`/`T-G306`/`T-G309`/`T-G310`/`T-G312`/`T-G315`/`T-G324`）
加攒批收口 `T-G319` 全都改过 `docs/workbacklog.toml`；而 `T-G293`/`T-G294`/`T-G295`/`T-G296`
（卡 193~196 的落地）**一个都没碰过它**。
★ 这条口径是**自动**的（不靠一张手维护的名单，新登记提交天然被保护）；代价是一条**已知边界**：
若哪天有一张卡自己的域就含 `docs/workbacklog.toml`（如卡 197/216 这类队列维护卡），本工具会
把它的号也当簿记号 —— 但那种卡**本来就在队列里**，不会落到"孤儿"那一支，无影响。

## 其余两条反向保护

② **没有 git / 空仓 ⇒ 优雅跳过**（不崩、**不当通过也不当红**，退出码 2）。
③ 队列里 `status` 是**任何值**的卡都照查 —— 这不是"落地状态"判据，是**条目存在性**判据。

## 退出码

  `0` = 干净（没有孤儿号、没有一卡多用）；`1` = 有漏（点名了）；`2` = 跳过（没有 git / 空仓）。

## 用法

    python -X utf8 tools/wb_queue_audit.py            # 人读（默认）
    python -X utf8 tools/wb_queue_audit.py --report   # 同上，显式
    python -X utf8 tools/wb_queue_audit.py --json     # 机器读（JSON）
    python -X utf8 tools/wb_queue_audit.py --repo .   # 指定仓库（默认本工具所在树）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pool.no_window import NO_WINDOW  # noqa: E402 —— 子进程不弹窗的唯一真源（卡 148）
from pool.plan import (  # noqa: E402 —— 队列解析只此一份（卡 106）
    Backlog,
    BacklogError,
    load_backlog,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKLOG = ROOT / "docs" / "workbacklog.toml"
#: 队列文件在仓库里的相对路径 —— 簿记号口径的锚点（见模块 docstring §口径）。
QUEUE_RELPATH = "docs/workbacklog.toml"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_SKIPPED = 2


@dataclass(frozen=True)
class Commit:
    """一笔提交（审计只需要这三样）。"""

    sha: str          # 全 sha
    short: str        # 短 sha
    subject: str      # 标题


@dataclass(frozen=True)
class Finding:
    """一条漏。`kind`：`orphan`（孤儿号）/ `multi`（一卡一号破了）。"""

    kind: str
    mark: str                    # Task 号
    card: str                    # 卡号（孤儿号没有卡 ⇒ ""）
    commits: tuple[Commit, ...]


@dataclass(frozen=True)
class Audit:
    """一次审计的读数。`skipped=True` ⇒ 没有 git / 空仓（不当通过也不当红）。"""

    skipped: bool
    cards: int
    marks: int
    findings: tuple[Finding, ...]

    @property
    def orphans(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == "orphan")

    @property
    def multi(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == "multi")

    @property
    def clean(self) -> bool:
        return not self.skipped and not self.findings


# ---------------------------------------------------------------- git（只读）

def _git(repo: Path, *args: str) -> str | None:
    """跑一条 git（只读）。跑不了 / 非零退出 ⇒ `None`（调用方据此优雅跳过）。"""
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", **NO_WINDOW,
        )
    except (OSError, FileNotFoundError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def read_task_commits(repo: Path) -> dict[str, tuple[Commit, ...]]:
    r"""`git log` 里所有 `Task:` trailer ⇒ `{号: (Commit, …)}`（保提交次序）。

    精确匹配整行 `Task: <号>`（不许 `T-G303` 命中 `T-G3031`）。
    没有 git / 空仓 / 读不出 ⇒ 返回空 dict（调用方据此优雅跳过）。
    """
    raw = _git(repo, "log", "--format=%H%x1f%h%x1f%s%x1f%b%x1e")
    if raw is None:
        return {}
    out: dict[str, list[Commit]] = {}
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        full, short, subject, body = parts[0], parts[1], parts[2], parts[3]
        if not full.strip():
            continue
        commit = Commit(sha=full.strip(), short=short.strip(), subject=subject.strip())
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("Task: "):
                mark = line[len("Task: "):].strip()
                bucket = out.setdefault(mark, [])
                # 同一笔提交里重复写同一个号不算「多笔」——按 sha 去重，免得造出假的一卡一号。
                if mark and (not bucket or bucket[-1].sha != commit.sha):
                    bucket.append(commit)
    return {mark: tuple(commits) for mark, commits in out.items()}


def queue_touch_marks(repo: Path, marks: dict[str, tuple[Commit, ...]],
                      queue_relpath: str = QUEUE_RELPATH) -> set[str]:
    """改过队列文件的那些提交所带的 `Task:` 号集合（= 簿记号候选，见模块 docstring §口径）。

    没有 git / 队列文件从未被提交过 / 读不出 ⇒ 空集（不保护任何号，但也不会崩）。
    """
    raw = _git(repo, "log", "--format=%H", "--", queue_relpath)
    if raw is None:
        return set()
    touched = {line.strip() for line in raw.splitlines() if line.strip()}
    if not touched:
        return set()
    by_sha = {c.sha: mark for mark, commits in marks.items() for c in commits}
    return {by_sha[sha] for sha in touched if sha in by_sha}


# ---------------------------------------------------------------- 判据

def audit(backlog: Backlog, repo: Path | None = None,
          queue_relpath: str = QUEUE_RELPATH) -> Audit:
    r"""跑两条判据，返回读数（纯函数，**只读**）。

    ★ 三条反向保护：① 簿记号（改过队列文件的号）不当孤儿报；② 没有 git / 空仓 ⇒
      `skipped=True`（不当通过也不当红）；③ 队列里任何 `status` 的卡都照查。
    """
    marks = read_task_commits(repo or ROOT)
    if not marks:
        return Audit(skipped=True, cards=len(backlog.cards), marks=0, findings=())
    protected = queue_touch_marks(repo or ROOT, marks, queue_relpath)
    queued = {card.task: card for card in backlog.cards}
    findings: list[Finding] = []
    # ① 孤儿号：git 有量、队列无条目、且不是簿记号。
    for mark in sorted(marks):
        if mark in queued or mark in protected:
            continue
        findings.append(Finding(kind="orphan", mark=mark, card="", commits=marks[mark]))
    # ② 一卡一号：队列卡的 task 号在 git 里出现多笔。
    for card in backlog.cards:
        commits = marks.get(card.task, ())
        if len(commits) > 1:
            findings.append(Finding(kind="multi", mark=card.task, card=card.id,
                                    commits=commits))
    return Audit(skipped=False, cards=len(backlog.cards), marks=len(marks),
                 findings=tuple(findings))


# ---------------------------------------------------------------- 渲染

def _orphan_line(finding: Finding) -> str:
    head = finding.commits[0]
    shas = "、".join(c.short for c in finding.commits)
    return (f"  · {finding.mark}  提交 {shas}「{head.subject}」"
            f"（队列里没有这个号）")


def _multi_line(finding: Finding) -> str:
    shas = "、".join(c.short for c in finding.commits)
    return (f"  · 卡 {finding.card}（task={finding.mark}）被 {len(finding.commits)} 笔"
            f"提交共用：{shas}")


def render_report(result: Audit) -> str:
    """人读文本（`--report`）。"""
    lines: list[str] = []
    if result.skipped:
        lines.append("[跳过] 没有 git / 空仓 —— 队列登记审计不当通过也不当红（反向保护②）。")
        return "\n".join(lines)
    lines.append(f"[审计] 队列 {result.cards} 张卡；git 里 {result.marks} 个 Task 号。")
    orphans = result.orphans
    multi = result.multi
    if orphans:
        lines.append(f"[漏 ] 孤儿号 {len(orphans)} 个（已落、队列无条目、且不是登记/收尾簿记号）：")
        lines.extend(_orphan_line(f) for f in orphans)
    if multi:
        lines.append(f"[漏 ] 一卡一号破了 {len(multi)} 张（同一个 task 号出现在多笔提交上）：")
        lines.extend(_multi_line(f) for f in multi)
    if not orphans and not multi:
        lines.append("[OK ] 干净：没有孤儿号、没有一卡多用。")
    return "\n".join(lines)


def to_json(result: Audit) -> str:
    """机器读（`--json`）。"""
    payload = {
        "skipped": result.skipped,
        "clean": result.clean,
        "cards": result.cards,
        "marks": result.marks,
        "orphans": [
            {"mark": f.mark, "shas": [c.sha for c in f.commits],
             "short_shas": [c.short for c in f.commits], "subject": f.commits[0].subject}
            for f in result.orphans
        ],
        "multi": [
            {"card": f.card, "task": f.mark, "shas": [c.sha for c in f.commits],
             "short_shas": [c.short for c in f.commits]}
            for f in result.multi
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="队列登记审计：已落的卡不许没有条目 + 一卡一号（只读）")
    parser.add_argument("--backlog", default=str(DEFAULT_BACKLOG),
                        help=f"队列文件（默认 {DEFAULT_BACKLOG.name}）")
    parser.add_argument("--repo", default=str(ROOT), help="仓库根（默认本工具所在树）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="输出 JSON（给机器）")
    group.add_argument("--report", action="store_true", help="输出人读文本（默认）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        backlog = load_backlog(Path(args.backlog))
    except BacklogError as exc:
        print(f"[FAIL] 队列读不了：{exc}", file=sys.stderr)
        return EXIT_FINDINGS
    result = audit(backlog, repo=Path(args.repo))
    if args.json:
        print(to_json(result))
    else:
        print(render_report(result))
    if result.skipped:
        return EXIT_SKIPPED
    return EXIT_CLEAN if result.clean else EXIT_FINDINGS


if __name__ == "__main__":
    raise SystemExit(main())
