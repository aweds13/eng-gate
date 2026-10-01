#!/usr/bin/env python
"""提交流程「七步」收成一条命令 + 硬闸门（T-G192 / 卡 097，轨二 · 机器替代 ⑤）。

## 为什么要它

以前每落一笔提交，人都要**手工**按固定次序敲七步，一天敲六七轮，每一轮都可能漏一步：

    ① 文档件就位（台账 / changelog / 交接 CHECKPOINT）   ← 漏了 → audit 红
    ② python -X utf8 tools/sync_counts.py                ← 漏了 → test_process_tools 红
    ③ python -X utf8 gates/diag/gate_lock.py acquire ... ← 漏了 → 别的树抢端口（假红）
    ④ python -X utf8 scripts/run_gates.py [--no-reuse]   ← 红了【必须不提交】
    ⑤ python -X utf8 scripts/run_gates.py --seal         ← 漏了 → 封存指纹对不上，audit 红
    ⑥ 白名单核对 + git add <显式列表> + commit（四个 trailer）← 漏了 → 带进不该进的文件
    ⑦ python -X utf8 scripts/audit_progress.py + release 锁 ← 漏了 → 锁泄漏到并发上限

本工具把七步收成一条命令，且**每一步都能独立失败并停住** —— 红了就是红了，
**绝不**往下走、**绝不**自动改东西弄绿。

## 用法

    python -X utf8 tools/tf_commit.py --card 097 --task T-G192 \\
        --allow tools/tf_commit.py tests/test_tf_commit.py \\
        --msg-file /tmp/msg.txt [--no-reuse] [--step 3] [--dry-run]

    --step N    只跑到第 N 步为止（便于主控分步复核；N 之后的东西一律不执行）
    --only K    只跑第 K 步（可重复）——「每一步可单跑」
    --skip K    跳过第 K 步（可重复）——「每一步可跳过」
    --dry-run   只打印将执行的确切命令，**一个字节都不改**（不 acquire / 不跑门禁 / 不 add /
                不 commit）

## 硬闸门（每条都有测试钉住）

  * **顺序与硬停**：任一步退非 0 → 立刻停，打印「第 N 步失败 ⇒ 不提交」，
    并在第 ③ 步之后**释放锁**（★ 绝不带着红门禁走到第 ⑥ 步）。
  * **白名单**：`--allow` 是**唯一**允许提交的文件集 —— 暂存区出现白名单外的路径 → 退 2 且点名；
    暂存区空 → 退 3（空集永远满足"全在白名单"，那是假绿灯）；
    ★ **绝不** `git add .` / `git add -A`，只 `git add -- <显式列表>`。
  * **trailer**：提交信息从 `--msg-file`（UTF-8）读，提交前校验四个 trailer
    （`Task:` / `Refs:` / `Ledger:` / `Gates:`）都在，且 `Task:` **恰好一个**编号，否则退 4。
  * **锁的端口段**：从 `TF_GATE_PORT_BASE` 读一次，把**同一个段**同时传给 acquire 与 release。
    ★★ 今天真踩的坑：release 不带同一个段 → 它在默认段（8531）里找锁 → 打印"没有锁，无需释放"
    → **锁泄漏**，泄漏的那把会一直占着「全局并发上限 2」的名额。

## 退出码

    0  七步全过
    1  第 2/4/5/7 步的子命令失败（透传其退出码，门禁红就是 1）
    2  白名单违规（越界 / 含 `.` 或 `-A` 这类整体 add）
    3  暂存区空
    4  trailer 不合格
    5  文档件缺位（改了源码却没带台账/changelog/交接，audit ④ 会红）—— 提前到第 ① 步说

## 测试注入

外部命令统一走 `runner(cmd, cwd, env) -> Result` 这一个口；测试用 `tmp_path` 造假 git 仓库
并把工具命令替成桩（`main(argv, runner=<桩>)`），真 git 原样在假仓库里跑 —— **绝不碰真仓库**。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# 本工具所在的树（worktree 里跑 = 那棵树；与 tools/sync_counts.py 的 ROOT 同口径）
ROOT = Path(__file__).resolve().parent.parent

# 一律 `python -X utf8 ...`（本仓铁律；中文路径/输出在 GBK 控制台会炸）
PY: tuple[str, ...] = (sys.executable, "-X", "utf8")

DEFAULT_PORT_BASE = 8531

# ---- audit ④ 的口径（与 scripts/audit_progress.py **逐字同源**：
#      见其 DOCS_TOUCH / CHECKPOINTS / SRC_PREFIXES 三个常量）
SRC_PREFIXES = ("src/timeflow/", "src/web/")
DOCS_TOUCH = ("docs/traceability.toml", "docs/changelog.md")
CHECKPOINTS = ("复盘/长任务执行协议.md", "复盘/交接-重构进度.md")

TRAILER_KEYS = ("Task", "Refs", "Ledger", "Gates")
_TRAILER_LINE = re.compile(r"^([A-Za-z]+):[ \t]*(.*)$")
_TASK_ID = re.compile(r"^T-G\d+$")

EXIT_OK = 0
EXIT_STEP = 1          # 子命令失败（透传）
EXIT_ALLOW = 2         # 白名单违规
EXIT_EMPTY = 3         # 暂存区空
EXIT_TRAILER = 4       # trailer 不合格
EXIT_DOCS = 5          # 文档件缺位

STEP_NAMES = {
    1: "文档件就位（台账/changelog/交接 CHECKPOINT）",
    2: "sync_counts（刷交接文档里的进度数字）",
    3: "拿门禁锁（gate_lock acquire）",
    4: "跑门禁（run_gates）",
    5: "封存指纹（run_gates --seal）",
    6: "白名单核对 + git add <显式列表> + commit",
    7: "audit（提交后再对账）+ release 锁",
}
ALL_STEPS = tuple(range(1, 8))


@dataclass(frozen=True)
class Result:
    """外部命令的返回：退出码 + 合并后的输出（stdout+stderr）。"""

    code: int
    out: str


def sh(cmd, cwd=None, env=None) -> Result:
    """默认 runner：真跑一个子进程。测试把它换掉即可隔离真仓库。"""
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=(str(cwd) if cwd is not None else None),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return Result(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))


def resolve_port_base(raw: str | None) -> int:
    """把 `TF_GATE_PORT_BASE` 折成一个有效段号（口径同 gate_lock / run_gates）。

    不设 / 非整数 / 越界 → `DEFAULT_PORT_BASE`。★ 折一次、只用这一个值，
    acquire 与 release 都带上它 —— 这就是治「release 找不到锁 → 锁泄漏」的那一手。
    """
    if raw is None or not str(raw).strip():
        return DEFAULT_PORT_BASE
    try:
        base = int(str(raw).strip())
    except ValueError:
        return DEFAULT_PORT_BASE
    if not (1024 <= base <= 65500):
        return DEFAULT_PORT_BASE
    return base


class Flow:
    """七步流程。命令构造与执行共用同一份（保证 --dry-run 打印的就是会执行的）。"""

    def __init__(self, args: argparse.Namespace, runner=sh, repo: Path | None = None) -> None:
        self.args = args
        self.runner = runner
        self.repo = Path(repo) if repo is not None else ROOT
        self.allow: list[str] = list(args.allow or [])
        self.allow_set = set(self.allow)
        self.lock_held = False
        # 端口段只在这里折一次；acquire / gates / seal / release 共用这一个 env
        self.base = resolve_port_base(os.environ.get("TF_GATE_PORT_BASE"))
        self.env = dict(os.environ)
        self.env["TF_GATE_PORT_BASE"] = str(self.base)

    # ---------------------------------------------------------------- 外部命令构造
    def cmd_sync_counts(self) -> list[str]:
        return [*PY, "tools/sync_counts.py"]

    def cmd_acquire(self) -> list[str]:
        return [*PY, "gates/diag/gate_lock.py", "acquire", "--card", self.args.card]

    def cmd_gates(self) -> list[str]:
        cmd = [*PY, "scripts/run_gates.py"]
        if self.args.no_reuse:
            cmd.append("--no-reuse")
        return cmd

    def cmd_seal(self) -> list[str]:
        return [*PY, "scripts/run_gates.py", "--seal"]

    def cmd_audit(self) -> list[str]:
        return [*PY, "scripts/audit_progress.py"]

    def cmd_release(self) -> list[str]:
        return [*PY, "gates/diag/gate_lock.py", "release", "--card", self.args.card]

    def cmd_add(self) -> list[str]:
        # ★ 永远只 `git add -- <显式列表>`，绝不 `.` / `-A`
        return ["git", "-c", "core.quotepath=false", "add", "--", *self.allow]

    def cmd_commit(self) -> list[str]:
        return ["git", "-c", "core.quotepath=false", "commit", "-F", str(self.args.msg_file)]

    def _git(self, args: list[str]) -> Result:
        return self.runner(
            ["git", "-c", "core.quotepath=false", *args],
            self.repo,
            dict(os.environ),
        )

    def _run(self, cmd: list[str], *, with_port_env: bool = False) -> Result:
        env = self.env if with_port_env else dict(os.environ)
        return self.runner(cmd, self.repo, env)

    # ---------------------------------------------------------------- 各步
    def step1(self) -> tuple[int, list[str]]:
        """① 文档件就位 —— 把 audit ④「改了源码却没同步文档」的红提前到这里说。

        口径与 `scripts/audit_progress.py` 逐字一致：`--allow` 里出现 `src/timeflow/` 或
        `src/web/` 的路径时，必须同时带 `docs/traceability.toml` + `docs/changelog.md`
        + 两个 CHECKPOINT 之一。没有源码改动 → 这一步自动通过（不硬塞要求）。
        """
        src = [p for p in self.allow if p.startswith(SRC_PREFIXES)]
        if not src:
            return EXIT_OK, [
                "[1] 文档件就位：--allow 无 src/ 改动 → 台账/changelog/交接 非必需（通过）"
            ]
        missing = [d for d in DOCS_TOUCH if d not in self.allow_set]
        if not any(c in self.allow_set for c in CHECKPOINTS):
            missing.append("复盘/{长任务执行协议,交接-重构进度}.md 之一")
        if missing:
            return EXIT_DOCS, [
                f"[1] ✗ 文档件缺位：--allow 改了源码却缺 {missing}（audit ④ 会红，先补再提交）"
            ]
        return EXIT_OK, ["[1] 文档件就位：源码改动已伴随 台账 + changelog + 交接 CHECKPOINT ✓"]

    def step2(self) -> tuple[int, list[str]]:
        r = self._run(self.cmd_sync_counts())
        return r.code, ["[2] sync_counts", r.out.rstrip()]

    def step3(self) -> tuple[int, list[str]]:
        r = self._run(self.cmd_acquire(), with_port_env=True)
        if r.code == 0:
            self.lock_held = True
        return r.code, [
            f"[3] 拿门禁锁（TF_GATE_PORT_BASE={self.base}）",
            r.out.rstrip(),
        ]

    def step4(self) -> tuple[int, list[str]]:
        r = self._run(self.cmd_gates(), with_port_env=True)
        return r.code, ["[4] 跑门禁", r.out.rstrip()]

    def step5(self) -> tuple[int, list[str]]:
        r = self._run(self.cmd_seal(), with_port_env=True)
        return r.code, ["[5] 封存指纹（--seal）", r.out.rstrip()]

    def step6(self) -> tuple[int, list[str]]:
        lines: list[str] = []
        # (a) 白名单口径自检：拒绝 `.` / `-A` 这类"整体 add"
        bad = self._bad_allow()
        if bad:
            return EXIT_ALLOW, [
                f"[6] ✗ --allow 含禁止项 {bad}：只许显式文件列表，绝不许 git add . / -A"
            ]
        # (b) 只 add 白名单（显式列表）
        r = self._git(["add", "--", *self.allow])
        if r.code != 0:
            return r.code, [f"[6] ✗ git add 失败（退出 {r.code}）", r.out.rstrip()]
        # (c) 核对暂存区
        staged = self._staged()
        if not staged:
            return EXIT_EMPTY, [
                "[6] ✗ 暂存区为空 → 不提交（空集永远满足'全在白名单'，那是假绿灯）"
            ]
        offenders = [p for p in staged if p not in self.allow_set]
        if offenders:
            return EXIT_ALLOW, [
                "[6] ✗ 白名单外路径（退出 2）：" + ", ".join(offenders),
                f"     白名单：{self.allow}",
            ]
        lines.append(f"[6] 白名单核对通过：{len(staged)} 个文件全在白名单内")
        # (d) trailer 校验（提交前）
        code, tlines = self._check_trailers()
        lines.extend(tlines)
        if code != 0:
            return code, lines
        # (e) commit
        r = self._git(["commit", "-F", str(self.args.msg_file)])
        lines.append(f"[6] git commit -F {self.args.msg_file}")
        lines.append(r.out.rstrip())
        return r.code, lines

    def step7(self) -> tuple[int, list[str]]:
        r = self._run(self.cmd_audit(), with_port_env=True)
        code = r.code
        lines = ["[7] audit（提交后对账）", r.out.rstrip()]
        # ★ 无论 audit 红绿，都要释放锁（锁泄漏比 audit 红更贵）
        lines.extend(self._release())
        return code, lines

    # ---------------------------------------------------------------- 辅助
    def _bad_allow(self) -> list[str]:
        bad: list[str] = []
        for p in self.allow:
            glob = p in (".", "..", "") or p.startswith("-") or any(c in p for c in "*?[]")
            if glob or p.endswith(("/", "\\")):
                bad.append(p)
            elif (self.repo / p).is_dir():
                bad.append(p + "/")
        return bad

    def _staged(self) -> list[str]:
        """暂存区里的仓库相对路径（`-z` 免八进制转义，中文路径原样）。"""
        r = self._git(["diff", "--cached", "--name-only", "-z"])
        return [p for p in r.out.split("\0") if p]

    def _check_trailers(self) -> tuple[int, list[str]]:
        path = Path(self.args.msg_file)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return EXIT_TRAILER, [f"[6] ✗ 读不到 --msg-file：{exc}"]
        found: dict[str, list[str]] = {k: [] for k in TRAILER_KEYS}
        for line in text.splitlines():
            m = _TRAILER_LINE.match(line)
            if m and m.group(1) in found:
                found[m.group(1)].append(m.group(2).strip())
        missing = [k for k in TRAILER_KEYS if not found[k]]
        if missing:
            return EXIT_TRAILER, [f"[6] ✗ 提交信息缺 trailer（退出 4）：{missing}"]
        task_lines = found["Task"]
        tokens = [t for t in re.split(r"[\s,/、+]+", " ".join(task_lines)) if t]
        if len(task_lines) != 1 or len(tokens) != 1 or not _TASK_ID.match(tokens[0]):
            return EXIT_TRAILER, [
                f"[6] ✗ `Task:` 不是「恰好一个编号」（退出 4）：{task_lines!r}"
                " —— 多余编号请写进 `Refs:`"
            ]
        if self.args.task and tokens[0] != self.args.task:
            return EXIT_TRAILER, [
                f"[6] ✗ `Task: {tokens[0]}` 与 --task {self.args.task} 不一致（退出 4）"
            ]
        return EXIT_OK, [f"[6] trailer 合格：Task/Refs/Ledger/Gates 都在，Task={tokens[0]}"]

    def _release(self) -> list[str]:
        if not self.lock_held:
            return []
        r = self._run(self.cmd_release(), with_port_env=True)
        self.lock_held = False
        return [f"[锁] release（TF_GATE_PORT_BASE={self.base}）", r.out.rstrip()]

    # ---------------------------------------------------------------- 编排
    def plan(self) -> tuple[int, ...]:
        if self.args.only:
            chosen = [n for n in ALL_STEPS if n in set(self.args.only)]
        else:
            upto = self.args.step if self.args.step is not None else 7
            chosen = [n for n in ALL_STEPS if n <= upto]
        skipped = set(self.args.skip or [])
        return tuple(n for n in chosen if n not in skipped)

    def run_dry(self) -> int:
        print("[dry-run] 以下是将执行的确切命令，一个字节都不改：")
        print(f"[env] TF_GATE_PORT_BASE={self.base}（同一段传给 acquire 与 release）")
        for n in self.plan():
            print(f"[{n}] {STEP_NAMES[n]}")
            for cmd in self._commands_of(n):
                print(f"    $ {_render(cmd)}")
        print("[dry-run] 未 acquire / 未跑门禁 / 未 git add / 未 commit —— 未改动任何字节")
        return EXIT_OK

    def _commands_of(self, n: int) -> list[list[str]]:
        if n == 1:
            return []  # 自检，无外部命令
        if n == 2:
            return [self.cmd_sync_counts()]
        if n == 3:
            return [self.cmd_acquire()]
        if n == 4:
            return [self.cmd_gates()]
        if n == 5:
            return [self.cmd_seal()]
        if n == 6:
            staged = ["git", "diff", "--cached", "--name-only", "-z"]
            return [self.cmd_add(), staged, self.cmd_commit()]
        return [self.cmd_audit(), self.cmd_release()]

    def run(self) -> int:
        if self.args.dry_run:
            return self.run_dry()
        plan = self.plan()
        for n in plan:
            code, lines = getattr(self, f"step{n}")()
            for line in lines:
                if line:
                    print(line)
            if code != 0:
                print(f"第 {n} 步失败 ⇒ 不提交")
                for line in self._release():
                    print(line)
                return code
        if plan == ALL_STEPS:
            print("七步全过 ✅")
        else:
            # ★ 主动截停（--step/--only/--skip）不是"全过" —— 别拿半轮冒充一轮
            ran = ", ".join(map(str, plan))
            print(f"已执行第 {ran} 步 ✅（按 --step/--only/--skip 截断，未走完七步）")
        return EXIT_OK


def _render(cmd: list[str]) -> str:
    out: list[str] = []
    for c in cmd:
        out.append(c if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", c) else f'"{c}"')
    return " ".join(out)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="提交流程七步一条命令 + 硬闸门（T-G192 / 卡 097）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--card", required=True, help="卡号（传给 gate_lock acquire/release）")
    ap.add_argument(
        "--task", default=None, help="任务号（如 T-G192；给了就校验 Task: trailer 与它一致）"
    )
    ap.add_argument("--allow", nargs="+", required=True, help="★ 唯一允许提交的文件集（显式列表）")
    ap.add_argument("--msg-file", required=True, help="提交信息文件（UTF-8，含四个 trailer）")
    ap.add_argument("--no-reuse", action="store_true", help="透传给 run_gates（不信复用记录）")
    ap.add_argument("--step", type=int, default=None, help="只跑到第 N 步为止（1..7）")
    ap.add_argument("--only", type=int, action="append", default=None, help="只跑第 K 步（可重复）")
    ap.add_argument("--skip", type=int, action="append", default=None, help="跳过第 K 步（可重复）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的确切命令，零改动")
    return ap


def main(argv: list[str] | None = None, *, runner=sh, repo: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    for n in [args.step, *(args.only or []), *(args.skip or [])]:
        if n is not None and n not in ALL_STEPS:
            print(f"✗ --step/--only/--skip 只接受 1..7（收到 {n}）")
            return 2
    return Flow(args, runner=runner, repo=repo).run()


if __name__ == "__main__":
    sys.exit(main())
