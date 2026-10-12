r"""并发调度器 CLI `tools/wb_plan.py`（外包卡 010 · 台账号 T-G99）—— 只标准库。

为什么有它（用户 2026-09-26 要的「管理架构」，卡 010 §1）：并发现在是**手工**的 —— 主控脑子里
记着「哪张卡碰哪些文件、哪棵树空着」，靠记性避免冲突，卡数一多必出事。这一版把规则做成能跑的
调度器：**文件级冲突域 + 拓扑分层 + 同层贪心打包**，拒绝任何会冲突的组合。

角色（详见 `复盘/并发架构-T-G99.md` §角色）：
  · 规划者 P（主控）：盘点 / 选题 / 写卡（含域声明）/ 定基点 / 排批 / 复核 / 验收。
  · 作者 W（工人 ×N）：一棵树一张卡；只碰自己的域；只跑轻门。
  · 集成者 I（工人或主控 ×1）：串行收口（cherry-pick → 合并台账片段 → 共享文件 →
    全量门禁 → seal → 一次集成提交）。
  · 复核者 R（工人只读）：对高风险卡做对抗性证伪。
  · 盘点者 S（工人只读）：挖「还剩哪些活」，分类 A/B/C/D。

子命令（默认都只**打印**，不建树、不派活）：
  check                       只校验 backlog，不输出批次；不合法 → 退 1
  plan [--concurrency N]      拓扑分层 + 同层贪心打包，输出批次（默认 N=2）
  stats                       队列全貌（待派 / 其它 / 批数 / 最大一批 / 占用的树）
  worktrees [--base <sha>]    打印建树命令（`--execute` 才真建）
  dispatch [--concurrency N]  打印派活命令（`--execute` 才真派）

用法：
    python -X utf8 tools/wb_plan.py check
    python -X utf8 tools/wb_plan.py plan --concurrency 3
    python -X utf8 tools/wb_plan.py worktrees --base 1969b46
    python -X utf8 tools/wb_plan.py dispatch

★ 逻辑层已抽到 `tools/pool/plan.py`（卡 106 · T-G202）：CLI 与号池 MCP 共用同一批函数，
  本文件只留**取参数 / 打印 / 会动世界的那一半**（`--execute`）。
★ 边界（如实写）：CLI 侧的速率 / 账号并发**上界未探测** —— 本工具用 `--concurrency` 把这个量
显式摆出来以便观测，但不声称知道它；`worktrees --execute` / `dispatch --execute` 是"会动世界"的
那一半，默认不执行（卡 010 §8 坑 1：别真建树、别真派活）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pool.plan import (
    ACTIVE_STATUS,
    BATCH_CLAIM_RE,
    DEFAULT_BACKLOG,
    DEFAULT_CONCURRENCY,
    PROTECTED_FILES,
    VALID_RISK,
    VALID_STATUS,
    Backlog,
    BacklogError,
    Card,
    audit_batch_claims,
    batch_manifest_path,
    extract_batch_claim,
    files_intersect,
    find_cycle,
    greedy_pack,
    in_flight,
    load_backlog,
    plan_batches,
    plan_report,
    render_plan,
    topo_layers,
    validate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 逻辑层已搬到 `pool.plan`；这里**原样转发**给既有调用方（测试 / 别的工具）—— 名字一个不少。
__all__ = [
    "ACTIVE_STATUS", "DEFAULT_BACKLOG", "DEFAULT_CONCURRENCY", "PROTECTED_FILES",
    "VALID_RISK", "VALID_STATUS", "Backlog", "BacklogError", "Card",
    "BATCH_CLAIM_RE", "audit_batch_claims", "batch_manifest_path", "extract_batch_claim",
    "cmd_check", "cmd_dispatch", "cmd_plan", "cmd_stats", "cmd_worktrees",
    "build_parser", "dispatch_argv", "files_intersect", "find_cycle", "greedy_pack",
    "in_flight", "load_backlog", "main", "plan_batches", "plan_report", "render_dispatch",
    "render_plan", "topo_layers", "validate", "worktree_commands",
]

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 渲染 / 命令拼装


def worktree_commands(backlog: Backlog, base: str) -> list[tuple[Card, str]]:
    """每张非主树卡的建树命令；主树那张卡**不建树**（卡 010 §3.2）。

    ★★ 卡 192（T-G292）：建树用 **`-b card/<号>`**（卡分支），**不是 detached HEAD** ——
    detached 的提交没有 ref ⇒ `clone --mirror` 带不走、`gc` 会清掉（今晚卡 160 丢东西的根因）。
    卡分支让工人"小步提交到本卡分支"成为可能，且提交**有 ref** ⇒ 镜像带得走。
    ★ 向后兼容：已有的 detached 卡树不会重建（树已存在 git 自拒，行为不变）；
    若 `card/<号>` 分支已存在（如旧卡 037），`cmd_worktrees` 会退回 checkout 形式。
    """
    return [(card, f"git worktree add -b card/{card.id} {card.tree} {base}")
            for card in backlog.cards if card.tree and in_flight(card)]


def dispatch_argv(card: Card) -> list[str]:
    """一张卡的派活命令（argv）—— 模板照卡 010 §3.2；**从它自己的树里跑**。"""
    return ["python", "-X", "utf8", "tools/wb_dispatch.py",
            "--card", card.id, "--spec", card.spec, "--detach", "--execute"]


def render_dispatch(card: Card) -> str:
    base = " ".join(dispatch_argv(card))
    return f"pushd {card.tree}; {base}" if card.tree else base


# ================================================================ 子命令


def _problems_or_exit(backlog: Backlog) -> int:
    problems = validate(backlog)
    if not problems:
        return 0
    print("[FAIL] backlog 不能用：", file=sys.stderr)
    for item in problems:
        print(f"  · {item}", file=sys.stderr)
    return 1


def cmd_check(backlog: Backlog) -> int:
    code = _problems_or_exit(backlog)
    if code:
        return code
    print(f"[OK ] backlog 校验通过：{len(backlog.cards)} 张卡，无冲突"
          f"（基点 {backlog.reviewed}）")
    active = [card for card in backlog.cards if in_flight(card)]
    print(f"[队列] 待派 {len(active)} 张 / 其它 {len(backlog.cards) - len(active)} 张"
          f"（★ 只有待派的参与冲突判定与排批）")
    # ★ 卡 157（T-G257）：批次自洽提醒（只报不拒）—— done 卡历史欠账 / 孤儿预声明 / 没声称批次的卡。
    notes = audit_batch_claims(backlog)
    for note in notes:
        print(f"[提醒] {note}", file=sys.stderr)
    # ★ 卡 157（T-G257）：`depends` 字段没有任何消费端（grep depends 在派活器 / 守卫 / 本工具
    #   零命中）—— 真正把同文件卡串起来的是 `files` 域相交（`plan_batches` 排批）。`depends` 只是
    #   人读的规划字段，不拦派活。选了 (b)：降级成注释，并在 check 里输出一行说明（不接进派活前置，
    #   那是 (a)，风险更高）。
    print("[说明] depends 仅规划用，不拦派活（同文件卡靠 files 域相交串批，不靠 depends）",
          file=sys.stderr)
    return 0


def cmd_plan(backlog: Backlog, limit: int) -> int:
    code, out, err = plan_report(backlog, limit)
    if err:
        sys.stderr.write(err)
    if out:
        sys.stdout.write(out)
    return code


def cmd_stats(backlog: Backlog, limit: int) -> int:
    """队列全貌（只读）：待派 / 其它 / 批次 / 最大一批 / 占用的树。

    ★ 一条命令看全貌 —— 别让人去数文件（"少读"的精神）。
    """
    code = _problems_or_exit(backlog)
    if code:
        return code
    active = [card for card in backlog.cards if in_flight(card)]
    batches = plan_batches(backlog, limit)
    biggest = max((len(batch) for batch in batches), default=0)
    trees = sorted({card.tree or "（主树）" for card in active})
    print(f"[统计] 队列共 {len(backlog.cards)} 张：待派 {len(active)}"
          f" / 其它（done/failed）{len(backlog.cards) - len(active)}")
    print(f"[统计] 并发上限 {limit} → {len(batches)} 批；最大一批 {biggest} 张")
    print(f"[统计] 待派占用的树：{'、'.join(trees) or '（无）'}")
    return 0


def cmd_worktrees(backlog: Backlog, base: str, *, execute: bool) -> int:
    commands = worktree_commands(backlog, base)
    if not commands:
        print("[OK ] 没有需要建树的卡（全在主树）")
        return 0
    for card, command in commands:
        print(f"[建树] 卡 {card.id}：{command}")
    if not execute:
        print(f"[dry ] 默认不执行；真要建树加 --execute（基点 {base}）")
        return 0
    for card, command in commands:
        print(f"[跑 ] 卡 {card.id}：{command}")
        done = subprocess.run(command.split(), cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        # ★ 卡 192：`card/<号>` 分支已存在（如旧卡 037）⇒ 退回 checkout 形式（向后兼容）
        if done.returncode != 0 and "already exists" in (done.stderr or ""):
            fallback = f"git worktree add {card.tree} card/{card.id}"
            print(f"  ↳ card/{card.id} 已存在 ⇒ 退回 checkout：{fallback}")
            done = subprocess.run(fallback.split(), cwd=str(ROOT), capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                  text=True, encoding="utf-8", errors="replace")
        body = (done.stdout or "") + (done.stderr or "")
        print(body.strip() or f"（退出码 {done.returncode}）")
    return 0


def cmd_dispatch(backlog: Backlog, limit: int, *, execute: bool) -> int:
    batches = plan_batches(backlog, limit)
    for i, batch in enumerate(batches, 1):
        print(f"[批 {i}] {len(batch)} 张：{'、'.join(card.id for card in batch)}")
        for card in batch:
            print(f"  {render_dispatch(card)}")
    if not execute:
        print("[dry ] 默认只打印；真要派活加 --execute（会真起工人）")
        return 0
    for batch in batches:
        for card in batch:
            tree = ROOT / card.tree if card.tree else ROOT
            print(f"[派 ] 卡 {card.id}（cwd {tree}）")
            done = subprocess.run(dispatch_argv(card), cwd=str(tree), text=True,
                                  encoding="utf-8", errors="replace")
            if done.returncode:
                print(f"[FAIL] 卡 {card.id} 派活器退出码 {done.returncode}", file=sys.stderr)
                return done.returncode
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="并发调度器：文件级冲突域 + 拓扑分层 + 同层打包（默认只打印）")
    parser.add_argument("command",
                        choices=("check", "plan", "stats", "worktrees", "dispatch"),
                        help="要做的动作")
    parser.add_argument("--backlog", default=str(DEFAULT_BACKLOG),
                        help=f"backlog 文件（默认 {DEFAULT_BACKLOG.name}）")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"并发上限（默认 {DEFAULT_CONCURRENCY}）")
    parser.add_argument("--base", default="",
                        help="建树的基点提交（默认取 backlog 的 [base].reviewed）")
    parser.add_argument("--execute", action="store_true",
                        help="真执行（建树 / 派活）；默认只打印 —— 别真建树、别真派活")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        backlog = load_backlog(Path(args.backlog))
    except BacklogError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if args.command == "check":
        return cmd_check(backlog)
    if args.command == "plan":
        return cmd_plan(backlog, args.concurrency)
    if args.command == "stats":
        return cmd_stats(backlog, args.concurrency)
    if args.command == "worktrees":
        return cmd_worktrees(backlog, args.base or backlog.reviewed, execute=args.execute)
    return cmd_dispatch(backlog, args.concurrency, execute=args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
