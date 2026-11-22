r"""队列登记审计 `tools/wb_queue_audit.py` —— 一条**只读**判据（卡 216 · T-G329）。

## 为什么有它

卡 197 收口时主控**当场抓到**：`193`/`194`/`195`/`196` 四张卡**已经落地**，可队列
`docs/workbacklog.toml` 里**根本没有它们的条目** ⇒ 没有 `status` 可翻、没有规格可指、
别的工具（排批 / 冲突判定 / 漂移判据）**都看不见它们**。同类病还有一条：**「一卡一号」**
——登记/收尾提交必须用**自己的簿记号**，否则卡 204 那条「已落却仍 pending」判据会**假阳**。

本工具把这两条做成能跑的东西（与 `wb_plan.py check` 的判据**同向**，但各管一段：那边只看
队列里的卡，这边**从 git 反向看**队列有没有漏收）。

## 判据（两条）

1. **孤儿号**：对 `git log` 里**每一条** `Task: <号>` trailer，若那个号**既不属于队列里任何一张卡、
   也不在台账里**（口径见 §口径（二）），**也不是簿记号**（见 §口径（一））⇒ **点名它**
   （号 + 那笔提交的短 sha + 提交标题）。
2. **一卡一号**：对队列里**每一条**卡，若它的 `task` 号**在 git 里出现在多笔落地笔上** ⇒ **点名**
   （多笔提交共用一号会让人误判"这张卡落了"）。只数**落地笔**，整笔只改台账面的簿记笔不算 ——
   口径见 §口径（三）。

## ★ 口径（一）：什么叫「簿记号」（反向保护①）—— 口径是本卡自己定的，依据如下

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

## ★ 口径（二）：什么叫「台账」—— 判词说「台账没有该任务」，实现就得真读台账

本判据的**判词**原本写的是「提交挂了 `Task:` 但**台账**没有该任务」，可实现只读了队列
（`docs/workbacklog.toml`）。队列只管**卡**，台账 `docs/traceability.toml` 另有一个 `[entries]`
字典，装的是**能被别的判据引用的登记条目**（卡号、规格号 `SR-*`、作业号 `STEP-*`、
台账号 `T-*` 都混在同一本账里）—— 于是大量**合法**的号被判成孤儿（假红）。

口径：

> **台账 = 队列 ∪ `docs/traceability.toml` 的 `[entries]`（含 `docs/traceability.d/*.toml` 分片）。
> 条目必须**带 evidence 指针**才算登记。**

- **只认 evidence 非空的条目**：台账里光有一行标题不算"登记过"——`status=done` 的规矩本来
  就是「必须至少一条证据」；没有证据的条目是欠账，不该替它挡下孤儿判据。
- **分片算同一本账**：`docs/traceability.d/<号>.toml` 是台账的分片形态（与队列分片同源），
  只读总表会漏掉刚落、还没汇总的那一批。
- **读不到不抛**：文件不存在 / 不是合法 TOML / 目录不存在 ⇒ 退回"只读队列"的老口径，
  **不崩**（这条判据要能在卡树、沙箱、新仓里跑）。

**依据（2026-11-22 实测，卡 A394）**：按老实现跑真仓 ⇒ 217 条红；逐条核对后发现
**217/217 都在 `docs/traceability.toml` 的 `[entries]` 里、`status` 全是 `done`、evidence 全非空**，
两本账**都没有**的是 **0 条**。也就是说那 217 条红一条都不是漏登记，全是判据读窄了。
反过来，真孤儿（两本账都没有）照样报 —— 判据只放宽到「台账也算登记」，没有放宽成「都不用登记」。

## ★ 口径（三）：一卡一号只数「落地笔」，簿记笔不算

`multi` 原本数的是「这个 `task` 号出现在**几笔提交**上」。可真仓里有大量**同一张卡分两笔**的
正常做法：一笔落下实现，另一笔**只改台账面**（`docs/changelog.d/<号>.md`、`docs/traceability`、
`复盘/` 下的复盘、`gates/last.json` 这类门禁产物）。这两笔都带同一个号是**对的**，
把它判成"一卡一号破了"是假红。

口径：

> **簿记笔 = 这一笔改的每个文件都落在台账面下**（`docs/` / `复盘/` / `skills/` 前缀，
> 或恰为 `gates/last.json`）。`multi` 只数**落地笔**（剩下的那些）。

- **判定按整笔看**：只要有一笔改了台账面以外的文件（代码 / 测试 / 配置），它就是落地笔。
- **空清单不算簿记笔**：`git show --name-only` 拿不到文件清单（二进制、`--allow-empty`、
  git 跑不了）⇒ **不当簿记笔**，宁可让它参与 `multi` 判据，也不许静默豁免。
- **只对候选号跑 git**：`multi` 候选（同号 ≥2 笔）先去重再**一次性**取文件清单，
  不许每张卡跑一遍 git。

**依据（2026-11-22 实测，卡 A394）**：老口径 29 张 `multi`，剔掉簿记笔后剩 **3 张**
（A289/`T-AG403`、E49/`T-AG499`、E54/`T-AG505` —— 同号两笔**都改了台账面以外**的文件，
是真的一卡两号），剔掉的 26 张每条都含**一笔只改台账面**的提交。
★ 与 §口径（一）的「簿记号」不是一件事：**簿记号看「这个号改没改过队列文件」**（保护孤儿判据），
**簿记笔看「这一笔是不是整笔只改台账面」**（保护 `multi` 判据）。两者判的对象不同（号 vs 笔），
别混用。

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

import tomllib
import wb_plan  # noqa: E402 —— 台账分片（卡 E89）：分片目录 / 分片读法只此一份
from pool.no_window import NO_WINDOW  # noqa: E402 —— 子进程不弹窗的唯一真源（卡 148）
from pool.plan import (  # noqa: E402 —— 队列解析只此一份（卡 106）
    Backlog,
    BacklogError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKLOG = ROOT / "docs" / "workbacklog.toml"
#: 队列文件在仓库里的相对路径 —— 簿记号口径的锚点（见模块 docstring §口径（一））。
QUEUE_RELPATH = "docs/workbacklog.toml"
#: 台账（第二本账）与它的分片目录 —— 孤儿号口径的另一半（见模块 docstring §口径（二））。
LEDGER_RELPATH = "docs/traceability.toml"
LEDGER_SHARD_RELPATH = "docs/traceability.d"
#: 台账面（簿记笔口径，见模块 docstring §口径（三））：整笔只改这里的提交不算落地笔。
LANDING_EXEMPT_DIRS = ("docs/", "复盘/", "skills/")
LANDING_EXEMPT_FILES = frozenset({"gates/last.json"})


def shard_relpath(queue_relpath: str = QUEUE_RELPATH) -> str:
    """队列文件同目录下的分片目录（`docs/workbacklog.toml` ⇒ `docs/backlog`）。

    卡 E89：只按路径取历史的门也得看见分片 —— 否则分片里登记的号会被当成孤儿。
    """
    parent, _, _ = queue_relpath.rpartition("/")
    return f"{parent}/backlog" if parent else "backlog"

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
    #: 台账里**带证据**的条目数（口径见模块 docstring §口径（二））；读不到台账 ⇒ 0。
    ledger: int = 0

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
    raw = _git(repo, "log", "--format=%H", "--", queue_relpath,
               shard_relpath(queue_relpath))
    if raw is None:
        return set()
    touched = {line.strip() for line in raw.splitlines() if line.strip()}
    if not touched:
        return set()
    by_sha = {c.sha: mark for mark, commits in marks.items() for c in commits}
    return {by_sha[sha] for sha in touched if sha in by_sha}


def _has_evidence(entry: object) -> bool:
    """台账条目有没有**证据指针**（`evidence` 列表里至少一个 strip 后非空的串）。

    只认 `evidence`：台账里光有一行标题不算"登记过"（`status=done` 的规矩本来就是
    「必须至少一条证据」）。字段缺失 / 不是列表 / 元素不是字符串 ⇒ 没有证据。
    """
    if not isinstance(entry, dict):
        return False
    evidence = entry.get("evidence")
    if not isinstance(evidence, list):
        return False
    return any(isinstance(item, str) and item.strip() for item in evidence)


def _ledger_entries(path: Path) -> dict[str, object]:
    """读一份台账文件的 `[entries]`（读不到 / 不是合法 TOML ⇒ 空 dict，不抛）。"""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def ledger_marks(root: Path) -> set[str]:
    """台账里**带证据**的条目号集合（口径见模块 docstring §口径（二））。

    台账 = `docs/traceability.toml` 的 `[entries]` ∪ `docs/traceability.d/*.toml` 分片。
    文件不存在 / 解析失败 / 目录不存在 ⇒ 退回已读到的部分（**不抛**，见反向保护②同一精神）。
    """
    out: set[str] = set()
    master = _ledger_entries(root / LEDGER_RELPATH)
    out.update(mark for mark, entry in master.items() if _has_evidence(entry))
    shard_dir = root / LEDGER_SHARD_RELPATH
    if shard_dir.is_dir():
        for shard in sorted(shard_dir.glob("*.toml")):
            out.update(mark for mark, entry in _ledger_entries(shard).items()
                       if _has_evidence(entry))
    return out


def bookkeeping_commits(repo: Path, shas: Sequence[str]) -> set[str]:
    """这些提交里**整笔只改台账面**的那些（= 簿记笔，见模块 docstring §口径（三））。

    `shas` 由调用方去重后一次传入（不许每张卡跑一遍 git）。空清单 / git 跑不了 ⇒ **不算**簿记笔
    （宁可让它参与 `multi` 判据，也不许静默豁免）。
    """
    out: set[str] = set()
    for sha in shas:
        raw = _git(repo, "show", "--name-only", "--format=", "-1", sha)
        if raw is None:
            continue
        files = [line.strip() for line in raw.splitlines() if line.strip()]
        if not files:
            continue
        if all(f.startswith(LANDING_EXEMPT_DIRS) or f in LANDING_EXEMPT_FILES for f in files):
            out.add(sha)
    return out


# ---------------------------------------------------------------- 判据

def audit(backlog: Backlog, repo: Path | None = None,
          queue_relpath: str = QUEUE_RELPATH,
          ledger: set[str] | None = None) -> Audit:
    r"""跑两条判据，返回读数（纯函数，**只读**）。

    `ledger` 不给 ⇒ 自己从 `ledger_marks(repo)` 现算（口径见模块 docstring §口径（二））。

    ★ 三条反向保护：① 簿记号（改过队列文件的号）不当孤儿报；② 没有 git / 空仓 ⇒
      `skipped=True`（不当通过也不当红）；③ 队列里任何 `status` 的卡都照查。
    """
    where = repo or ROOT
    marks = read_task_commits(where)
    if not marks:
        return Audit(skipped=True, cards=len(backlog.cards), marks=0, findings=())
    registered = ledger_marks(where) if ledger is None else ledger
    protected = queue_touch_marks(where, marks, queue_relpath)
    # ★ 用 set 不用 dict：5 组卡共用同一个 task 号时，dict 只会留下最后一张（键集合与 set 相同，
    #   判孤儿的行为不变；改成 set 只为不让后来人以为 queued[mark] 取得到那张卡）。
    queued = {card.task for card in backlog.cards}
    findings: list[Finding] = []
    # ① 孤儿号：git 有量、队列无条目、台账也无条目、且不是簿记号。
    for mark in sorted(marks):
        if mark in queued or mark in protected or mark in registered:
            continue
        findings.append(Finding(kind="orphan", mark=mark, card="", commits=marks[mark]))
    # ② 一卡一号：队列卡的 task 号在 git 里出现多笔**落地笔**（簿记笔不算，§口径（三））。
    candidates = {c.sha for card in backlog.cards
                  for c in marks.get(card.task, ()) if len(marks.get(card.task, ())) > 1}
    booking = bookkeeping_commits(where, sorted(candidates)) if candidates else set()
    for card in backlog.cards:
        commits = marks.get(card.task, ())
        landing = [c for c in commits if c.sha not in booking]
        if len(landing) > 1:
            findings.append(Finding(kind="multi", mark=card.task, card=card.id,
                                    commits=tuple(landing)))
    return Audit(skipped=False, cards=len(backlog.cards), marks=len(marks),
                 findings=tuple(findings), ledger=len(registered))


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
    lines.append(f"[审计] 队列 {result.cards} 张卡；台账 {result.ledger} 个带证据条目；"
                 f"git 里 {result.marks} 个 Task 号。")
    orphans = result.orphans
    multi = result.multi
    if orphans:
        lines.append(f"[漏 ] 孤儿号 {len(orphans)} 个"
                     "（已落、队列与台账都没有条目、且不是登记/收尾簿记号）：")
        lines.extend(_orphan_line(f) for f in orphans)
    if multi:
        lines.append(f"[漏 ] 一卡一号破了 {len(multi)} 张"
                     "（同一个 task 号出现在多笔落地笔上；只改台账面的簿记笔不计）：")
        lines.extend(_multi_line(f) for f in multi)
    if not orphans and not multi:
        lines.append("[OK ] 干净：没有孤儿号、没有一卡多用。")
    if result.ledger == 0:
        lines.append("[提示] 台账（docs/traceability.toml）读不到或没有带证据的条目 ——"
                     " 孤儿判据只按队列判（口径见模块 docstring §口径（二））。")
    return "\n".join(lines)


def to_json(result: Audit) -> str:
    """机器读（`--json`）。"""
    payload = {
        "skipped": result.skipped,
        "clean": result.clean,
        "cards": result.cards,
        "marks": result.marks,
        "ledger": result.ledger,
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
        # 卡 E89：有分片先读分片（口径唯一在 wb_plan）；无分片退回同一条老读法。
        backlog = wb_plan.load_sharded_backlog(
            Path(args.backlog), Path(args.backlog).parent / "backlog")
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
