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
                              ★ 卡 204：还查「已落却仍 pending」—— 队列里
                                status=pending 的卡其 task 已在 git log 的 Task:
                                trailer 里 ⇒ 退 1（前提：一卡一号）
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

from pool import registry as pool_registry  # noqa: E402 —— 主树根（树标签的锚点；卡 203）
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
    "find_landed_but_pending", "find_gate_drift", "in_flight", "load_backlog",
    "main", "plan_batches",
    "plan_report", "render_dispatch", "render_plan", "topo_layers", "validate",
    "worktree_commands",
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


def _tree_abs(tree: str) -> str:
    """卡树（相对**主树根**的标签）的**绝对路径**（posix）—— 口径与 `pool.registry` 的树标签一致。

    ★ 卡 203：树标签（`wb_dispatch.worker_tree_label`）就是"相对**主树根**的 posix 路径" ⇒
      绝对路径必须锚在**主树根**上 —— 不能锚在"wb_plan 从哪儿跑"（那样在卡树里会拼成
      `<卡树>/.wt/x`，正好是这个 bug 家族的错法）。主树根算不出（git 不可用）⇒ 退回本文件
      所在树（`ROOT`，通常就是主树）。
    """
    try:
        main_root = pool_registry.main_tree_root()
    except pool_registry.RegistryError:
        main_root = ROOT
    return (main_root / tree).as_posix()


def dispatch_argv(card: Card) -> list[str]:
    """一张卡的派活命令（argv）—— **从主仓跑**（卡 203 换掉了「pushd 进卡树」那套）。

    ★★ 卡 203（T-G307）：旧形态是 `pushd <树>; python tools/wb_dispatch.py …` —— 它有两个病：
      ① `pushd` 让进程 cwd 落到卡树，而跑的是**树里那份**脚本（`ROOT = Path(__file__)…` 于是成了
         卡树）⇒ 派活产物（log / brief / 规格）落进卡树（症状 B），而卡树里没有主仓的
         `gates/diag/`（那是 gitignore 的）；
      ② 不给 `--cwd` ⇒ 租约把「主树」登记成被占（症状 A），可工人在卡树里干活。
      现在：**从主仓**跑（不再 `pushd`）+ 显式 `--cwd <该卡树的绝对路径>` —— 登记树 = 工人树。
    ★ 主树（`tree == ""`）**不给** `--cwd`：从主仓跑时进程 cwd 就是主仓 ⇒ 标签仍是主树（`""`），
      且工人看到的东西逐字不变（卡 166：换法不许改变工人看到的东西）。
    """
    argv = ["python", "-X", "utf8", "tools/wb_dispatch.py",
            "--card", card.id, "--spec", card.spec]
    if card.tree:
        argv += ["--cwd", _tree_abs(card.tree)]
    return [*argv, "--detach", "--execute"]


def render_dispatch(card: Card) -> str:
    """把派活 argv 拼成一整行命令（从**主仓**跑）—— 不再 `pushd`（卡 203）。"""
    return " ".join(dispatch_argv(card))


# ================================================================ 子命令


def _problems_or_exit(backlog: Backlog) -> int:
    problems = validate(backlog)
    if not problems:
        return 0
    print("[FAIL] backlog 不能用：", file=sys.stderr)
    for item in problems:
        print(f"  · {item}", file=sys.stderr)
    return 1


# -------------------------------------------------- 卡 204（T-G311）：已落却仍 pending
def _landed_task_shas(repo: Path | None = None) -> dict[str, list[str]]:
    r"""从 `git log` 取所有提交的 `Task:` trailer → `{task号: [短sha]}`。

    精确匹配整行 `Task: <task号>`（不许 `T-G303` 命中 `T-G3031`）。
    没有 git / 空仓 ⇒ 返回空 dict（优雅跳过，不当通过也不崩）。

    ★ 前提：**一卡一号** —— 登记/收尾提交必须用自己的簿记号；本仓已在这么做。
    """
    cwd = str(repo or ROOT)
    try:
        raw = subprocess.run(
            ["git", "log", "--format=%h%x1f%B%x1e"],
            cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, FileNotFoundError):
        return {}
    if raw.returncode != 0:
        return {}
    result: dict[str, list[str]] = {}
    for chunk in raw.stdout.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, _, body = chunk.partition("\x1f")
        sha = sha.strip()
        if not sha:
            continue
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("Task: "):
                task = line[len("Task: "):].strip()
                if task:
                    result.setdefault(task, []).append(sha)
    return result


def find_landed_but_pending(backlog: Backlog, repo: Path | None = None) -> list[str]:
    r"""★ 卡 204（T-G311）：已落却仍 pending —— 队列里 `status=pending` 的卡，
    其 `task` 号出现在 `git log` 的 `Task:` trailer 里 ⇒ 报「已落却仍 pending」。

    返回报告行列表（空 = 没问题），每行**点名卡号 + 那笔提交的短 sha**。

    ★ 前提（写进 docstring/--help）：**一卡一号** —— 登记/收尾提交必须用自己的
      簿记号；本仓已在这么做。

    ★ 反向保护（三条都要）：
      ① 不许把 `done`/`failed`/`running` 的卡报成错（只看 `pending`）；
      ② 不许把队列里没有条目的已落卡牵进来（只看队列里的 `pending` 卡）；
      ③ 没有 git 时优雅跳过（返回空列表，不当通过也不崩）。
    """
    landed = _landed_task_shas(repo)
    if not landed:
        return []
    reports: list[str] = []
    for card in backlog.cards:
        if card.status != "pending":
            continue
        shas = landed.get(card.task)
        if shas:
            reports.append(
                f"卡 {card.id}：已落却仍 pending（task={card.task}，提交 {shas[0]}）")
    return reports


# -------------------------------------------------- 卡 212（T-G323）：栅栏漂移
def _match_member_to_card(
    member_id: str, member_paths: list[str], by_id: dict[str, Card],
) -> Card | None:
    r"""把栅栏成员对应到 backlog 卡（与 `pool.task.find_gates_for_member` 同口径，方向相反）。

    ① 成员号 == 卡 id ⇒ 直接（`B-20261014` 的 `210`/`211`/`212`）；
    ② 成员 `paths` ∩ 卡 `files` 非空 ⇒ 取相交最多的那张（`B-DTREE` 的 `M-1` → 卡 203）。
    找不到 ⇒ None。
    """
    if member_id in by_id:
        return by_id[member_id]
    mpaths = set(member_paths or [])
    if not mpaths:
        return None
    best: Card | None = None
    best_n = 0
    for card in by_id.values():
        n = len(mpaths & set(card.files))
        if n > best_n:
            best, best_n = card, n
    return best


def find_gate_drift(backlog: Backlog) -> list[str]:
    r"""★ 卡 212（T-G323）：栅栏漂移判据 —— 对每个 `gates/diag/batch/B-*.toml`，
    它的成员在**队列里的 status** 与**栅栏状态**必须一致。

    **「卡已 `done` 而栅栏还 `collecting`（未到终态）」⇒ 红并点名**
    （批号 + 成员号 + 卡号 + 两边各说什么）。

    ★ 反向保护（五条都要）：
      ① 只报 `done` 的卡（`pending`/`running`/`failed` 不报 —— 它们没落地，栅栏等着是对的）；
      ② 成员找不到对应卡 ⇒ 不报（可能还没派活 / 成员号不是卡号且 paths 不相交）；
      ③ 栅栏已到终态（`awaiting-commit` / `landed` / `timeout`）⇒ 不报；
      ④ 只读成员不参与放行 ⇒ 不报；
      ⑤ 没有栅栏目录 / 单个栅栏坏了 ⇒ 优雅跳过（不崩、不当通过也不当红）。
    """
    try:
        from pool.task import batch_dir, load_manifest, read_json, state_path
    except Exception:  # pragma: no cover - pool.task 不在时优雅跳过
        return []
    try:
        bd = batch_dir()
    except Exception:  # pragma: no cover - git 不可用时优雅跳过
        return []
    if not bd.is_dir():
        return []
    by_id: dict[str, Card] = {card.id: card for card in backlog.cards}
    reports: list[str] = []
    for toml in sorted(bd.glob("B-*.toml")):
        gate_id = toml.stem
        sp = state_path(gate_id)
        if not sp.is_file():
            continue
        try:
            st = read_json(sp)
            man = load_manifest(gate_id)
        except Exception:  # pragma: no cover - 坏栅栏跳过
            continue
        state = st.get("state", "")
        if state in ("awaiting-commit", "landed", "timeout"):
            continue
        for mem in man.get("member") or []:
            if mem.get("read_only"):
                continue
            mid = mem.get("id", "")
            card = _match_member_to_card(mid, mem.get("paths") or [], by_id)
            if card is None or card.status != "done":
                continue
            reports.append(
                f"批 {gate_id} 成员 {mid} → 卡 {card.id}（{card.task}）："
                f"栅栏={state} / 队列=done —— 卡已落地但栅栏未推进")
    return reports


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
    # ★ 卡 204（T-G311）：已落却仍 pending —— 队列里 pending 的卡其 task 已在 git log 里 ⇒ 红。
    #   前提：一卡一号（登记/收尾提交必须用自己的簿记号；本仓已在这么做）。
    landed = find_landed_but_pending(backlog)
    for line in landed:
        print(f"[FAIL] {line}", file=sys.stderr)
    if landed:
        return 1
    # ★ 卡 212（T-G323）：栅栏漂移 —— 卡已 done 而栅栏还 collecting ⇒ 红。
    #   判据盯的是「真仓库的栅栏」（gates/diag/batch/B-*.toml）与「队列里的 status」是否一致。
    #   反向保护：只报 done 的卡 / 成员找不到卡不报 / 终态不报 / 只读不报 / 没栅栏优雅跳过。
    drift = find_gate_drift(backlog)
    for line in drift:
        print(f"[FAIL] {line}", file=sys.stderr)
    if drift:
        return 1
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
