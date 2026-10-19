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
  merge                       把台账**分片**合并成只读总表（`--execute` 才落盘）

★ 卡 262（T-G383）·分区前缀：多个主控共用一个卡池，卡号会撞（都写 261）。解法是给每个
  主控一个**头编号**（分区前缀）—— 新卡号形如 `A261`（树 `.wt/A261`、分支 `card/A261`）。
  **旧号（纯数字）行为一字不变**。登记表在 `docs/partitions.toml`；台账**分片**住
  `docs/backlog/<分区>.toml`，`check` / `plan` / `dispatch` 读的是**合并后**的队列。
  ★ 分区只解决「号不撞」，**不解决「文件不撞」**：两个分区各写一张卡、都声明同一文件时，
  `check` 照样报「同一文件两个写者」并点名（合并后仍按 `files` 域相交判）。

用法：
    python -X utf8 tools/wb_plan.py check
    python -X utf8 tools/wb_plan.py plan --concurrency 3
    python -X utf8 tools/wb_plan.py worktrees --base 1969b46
    python -X utf8 tools/wb_plan.py dispatch
    python -X utf8 tools/wb_plan.py check --shards docs/backlog
    python -X utf8 tools/wb_plan.py merge --execute

★ 逻辑层已抽到 `tools/pool/plan.py`（卡 106 · T-G202）：CLI 与号池 MCP 共用同一批函数，
  本文件只留**取参数 / 打印 / 会动世界的那一半**（`--execute`）。
★ 边界（如实写）：CLI 侧的速率 / 账号并发**上界未探测** —— 本工具用 `--concurrency` 把这个量
显式摆出来以便观测，但不声称知道它；`worktrees --execute` / `dispatch --execute` 是"会动世界"的
那一半，默认不执行（卡 010 §8 坑 1：别真建树、别真派活）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib
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
    "cmd_check", "cmd_dispatch", "cmd_merge", "cmd_plan", "cmd_stats", "cmd_worktrees",
    "build_parser", "card_prefix", "cross_partition_writers", "dispatch_argv", "files_intersect",
    "find_cycle", "greedy_pack",
    "find_landed_but_pending", "find_gate_drift", "in_flight",
    "load_backlog", "load_partitions", "load_sharded_backlog", "merge_shards",
    "main", "partition_of", "partitions_path", "Partition", "PartitionError", "Partitions",
    "plan_batches",
    "plan_report", "render_dispatch", "render_merged_toml", "render_plan", "shard_dir",
    "split_card_id", "topo_layers", "validate", "validate_partition_naming",
    "worktree_commands",
]

ROOT = Path(__file__).resolve().parent.parent


def settings_concurrency(root: Path | None = None) -> int | None:
    """面板「参数」页写的号池并发度（`tools/settings.toml` 的 `pool_concurrency`）。

    卡 A286：面板上能改的数必须**真的生效** —— 否则那个输入框只是个摆设。
    读不到 / 越界 / 文件不存在 ⇒ None（调用方退回 `DEFAULT_CONCURRENCY`）。
    """
    base = root or ROOT
    path = base / "tools" / "settings.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    value = data.get("pool_concurrency")
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if 1 <= value <= 8 else None

# ================================================================ 卡 262（T-G383）：分区前缀
#
# 多个主控共用一个卡池，卡号会撞（都写 261）。解法：每个主控自带一个**头编号**（分区前缀），
# 新卡号形如 `A261` —— 树 `.wt/A261`、分支 `card/A261`、任务号 `T-AG382`、批号 `A-20261016-1`。
# **旧号（纯数字）行为一字不变**：分区只影响新卡怎么登记、怎么派活、怎么落地。
#
# 登记表住 `docs/partitions.toml`（谁负责 / 负责哪方面 / 树前缀）；台账**分片**住
# `docs/backlog/<分区>.toml`，落地时合并成**只读总表**（`merge`）。
# ★ 分区只解决「号不撞」，**不解决「文件不撞」** —— 两个分区各写一张卡、都声明同一文件时，
#   合并后的 `validate()` 照样报「同一文件两个写者」（见 `cross_partition_writers()`）。

PARTITIONS_REL = ("docs", "partitions.toml")
SHARD_DIR_REL = ("docs", "backlog")
#: 卡号 = 可选的分区前缀（ASCII 大写字母）+ 数字。旧号（纯数字）没有前缀。
CARD_ID_RE = re.compile(r"^(?P<prefix>[A-Z]*)(?P<number>\d+)$")


class PartitionError(BacklogError):
    """分区登记表读不了 / 卡号不属于任何分区 —— 与「排班冲突」分开（前者是登记坏了）。"""


@dataclass(frozen=True)
class Partition:
    """一个分区：前缀（头编号）、负责人、负责方面、树前缀（新卡的树该落在哪）。"""

    prefix: str
    owner: str
    area: str
    tree: str


@dataclass(frozen=True)
class Partitions:
    """分区登记表（`docs/partitions.toml`）的读出来的样子。"""

    legacy_default: str
    legacy_ranges: tuple[tuple[int, int, str], ...]
    by_prefix: dict[str, Partition]


def partitions_path() -> Path:
    """分区登记表路径 —— 从 `ROOT` 现算（测试会 monkeypatch `ROOT`）。"""
    return ROOT.joinpath(*PARTITIONS_REL)


def shard_dir() -> Path:
    """台账**分片**目录（`docs/backlog/`）—— 从 `ROOT` 现算。"""
    return ROOT.joinpath(*SHARD_DIR_REL)


def split_card_id(card_id: str) -> tuple[str, str]:
    """把卡号拆成 `(分区前缀, 号)` —— 旧号（纯数字）的前缀是 `""`。

    只认两种形态：`<前缀字母><数字>`（如 `A261`）与纯数字（如 `261`）。
    其它形态（含 `-`、下划线、空串、中文字符）⇒ 抛 `PartitionError`（**不猜**）。
    """
    m = CARD_ID_RE.match(str(card_id).strip())
    if not m:
        raise PartitionError(
            f"卡号 {card_id!r} 既不是「前缀字母+数字」（如 A261）也不是纯数字（如 261）")
    return m.group("prefix"), m.group("number")


def card_prefix(card_id: str) -> str:
    """卡号的分区前缀；认不出形态 ⇒ `""`（**不抛** —— 别名成员号如 `M-1` / `卡A` 走这条）。"""
    try:
        return split_card_id(card_id)[0]
    except PartitionError:
        return ""


def partition_of(card_id: str, partitions: Partitions | None) -> str:
    """这张卡属于哪个分区 —— 有前缀 ⇒ 前缀；纯数字旧号 ⇒ 按 `[legacy]` 区间 / default。

    认不出卡号形态 ⇒ 抛 `PartitionError`；没有登记表（`partitions is None`）⇒ 旧号回 `""`。
    """
    prefix, number = split_card_id(card_id)
    if prefix:
        return prefix
    if partitions is None:
        return ""
    for low, high, pfx in partitions.legacy_ranges:
        if low <= int(number) <= high:
            return pfx
    return partitions.legacy_default


def load_partitions(path: Path | None = None) -> Partitions | None:
    """读分区登记表 —— 文件不在 ⇒ `None`（调用方按「不判分区」跳过，**不崩**）。

    文件在但坏（TOML 解析不了 / 缺 `prefix`）⇒ 抛 `PartitionError`（**不静默**）。
    """
    target = Path(path) if path is not None else partitions_path()
    if not target.is_file():
        return None
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PartitionError(f"分区登记表读不了：{target}（{exc}）") from exc
    legacy = data.get("legacy") or {}
    ranges: list[tuple[int, int, str]] = []
    for row in legacy.get("ranges") or []:
        ranges.append((int(row["from"]), int(row["to"]), str(row["prefix"]).strip()))
    by_prefix: dict[str, Partition] = {}
    for raw in data.get("partitions") or []:
        pfx = str(raw.get("prefix", "")).strip()
        if not pfx:
            raise PartitionError(f"分区登记缺 `prefix`：{raw!r}")
        by_prefix[pfx] = Partition(
            prefix=pfx,
            owner=str(raw.get("owner", "")).strip(),
            area=str(raw.get("area", "")).strip(),
            tree=str(raw.get("tree", "")).strip(),
        )
    return Partitions(legacy_default=str(legacy.get("default", "")).strip(),
                      legacy_ranges=tuple(ranges), by_prefix=by_prefix)


def merge_shards(directory: Path | None = None) -> Backlog | None:
    """把 `docs/backlog/*.toml` 各分片合并成一份队列；**没有分片 ⇒ `None`**。

    每片都是一份合法的 backlog（有 `[base]` + `[[cards]]`）。卡号重复（含同号同分区）⇒
    `BacklogError`（`卡号重复：<号>`）；`reviewed` 取第一片（分片目录里按文件名排序）。
    """
    folder = Path(directory) if directory is not None else shard_dir()
    shards = sorted(folder.glob("*.toml")) if folder.is_dir() else []
    if not shards:
        return None
    cards: list[Card] = []
    seen: set[str] = set()
    reviewed = ""
    for shard in shards:
        part = load_backlog(shard)
        if not reviewed:
            reviewed = part.reviewed
        for card in part.cards:
            if card.id in seen:
                raise BacklogError(f"卡号重复：{card.id}（分片 {shard.name}）")
            seen.add(card.id)
            cards.append(card)
    return Backlog(reviewed=reviewed, cards=tuple(cards))


def load_sharded_backlog(
    path: Path | None = None, shard_directory: Path | None = None,
) -> Backlog:
    """读队列：**先分片后总表**。

    · 分片目录（默认 `docs/backlog/`）里有 `*.toml` ⇒ 合并它们；
    · 否则退回**总表**（`path`，默认 `docs/workbacklog.toml`）—— **旧行为一字不变**。
    """
    merged = merge_shards(shard_directory)
    if merged is not None:
        return merged
    return load_backlog(Path(path) if path is not None else DEFAULT_BACKLOG)


def cross_partition_writers(backlog: Backlog, partitions: Partitions | None) -> list[str]:
    """★ 卡 262：跨分区「同一文件两个写者」—— 报行（空 = 没有）。

    分区只避免**号**撞，不避免**文件**撞：两个分区各写一张卡、声明同一文件时，
    合并后的 `validate()` 会报「files 相交」，这里再把**分区**点名说清楚。
    同分区的相交交给 `validate()` 自己报，这里不重复。
    """
    active = [card for card in backlog.cards if in_flight(card)]
    out: list[str] = []
    for i, first in enumerate(active):
        pfirst = partition_of(first.id, partitions)
        for second in active[i + 1:]:
            hit = files_intersect(first, second)
            if not hit:
                continue
            psecond = partition_of(second.id, partitions)
            if pfirst and psecond and pfirst == psecond:
                continue          # 同分区：由 validate() 那条报，这里不重复
            out.append(
                f"卡 {first.id}（分区 {pfirst or '?'}）与 {second.id}（分区 {psecond or '?'}）："
                f"files 相交 {sorted(hit)} —— 分区只避免号撞，不避免文件撞")
    return out


def validate_partition_naming(
    backlog: Backlog, partitions: Partitions | None,
) -> list[str]:
    """分区命名判据（**只对新卡=带前缀的卡号生效；旧号一字不变**）：

    ① 带前缀 ⇒ 前缀必须**已在 `docs/partitions.toml` 登记**（没登记 ⇒ 拒）；
    ② 带前缀且有卡树 ⇒ 树名（末段）必须以该分区前缀开头（分区 A 的树如 `.wt/A261`）。
    """
    if partitions is None:
        return []
    known = "、".join(sorted(partitions.by_prefix)) or "无"
    problems: list[str] = []
    for card in backlog.cards:
        try:
            prefix, _ = split_card_id(card.id)
        except PartitionError as exc:
            problems.append(f"卡 {card.id}：{exc}")
            continue
        if not prefix:
            continue                       # 旧号：不判命名（行为一字不变）
        if prefix not in partitions.by_prefix:
            problems.append(
                f"卡 {card.id}：分区 {prefix} 没在 {PARTITIONS_REL[0]}/{PARTITIONS_REL[1]} 登记"
                f"（已登记：{known}）")
            continue
        if card.tree and not Path(card.tree).name.startswith(prefix):
            tree = partitions.by_prefix[prefix].tree
            problems.append(
                f"卡 {card.id}：卡树 {card.tree} 的树名不以分区前缀 {prefix} 开头"
                f"（分区 {prefix} 的树该如 {tree}{card.id}）")
    return problems

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
    ② **只给别名成员**（成员号不是纯卡号，如 `B-DTREE` 的 `M-1`）走 paths 兜底，且必须
      「真有相交且唯一最多」：成员 paths 被**唯一**一张卡**全部**兜住（`M-1` → 卡 203）。
    ★ 卡 234（T-G351）：纯数字成员号（=卡号形态，如 `231`/`234`）**只认 ①** —— 号不在队列里
      就是"对不上"，不许按文件乱兜（旧版"paths ∩ files 取相交最多"哪怕只交 1 个文件、甚至
      多张并列也照取 ⇒ `231` 被乱兜到 done 的卡 164 ⇒ 假漂移 ⇒ 收口被挡）。找不到 ⇒ None。
    """
    if member_id in by_id:
        return by_id[member_id]
    # 卡号形态的成员号（纯数字旧号 / 带分区前缀的新号）不在队列里 ⇒ 认不出，不许按文件乱兜。
    if member_id.isdigit() or card_prefix(member_id):
        return None
    mpaths = set(member_paths or [])
    if not mpaths:
        return None
    best: Card | None = None
    best_n = 0
    tied = False
    for card in by_id.values():
        n = len(mpaths & set(card.files))
        if n > best_n:
            best, best_n, tied = card, n, False
        elif n == best_n and n > 0:
            tied = True
    if best is None or tied or best_n != len(mpaths):   # 没相交 / 并列最多 / 只兜住一部分 ⇒ 不算
        return None
    return best


def find_gate_drift(backlog: Backlog) -> list[str]:
    r"""★ 卡 212（T-G323）：栅栏漂移判据 —— 对每个 `gates/diag/batch/B-*.toml`，
    它的成员在**队列里的 status** 与**栅栏状态**必须一致。

    **「卡已 `done` 而栅栏还 `collecting`（未到终态）」⇒ 红并点名**
    （批号 + 成员号 + 卡号 + 两边各说什么）。

    ★ 反向保护（五条都要）：
      ① 只报 `done` 的卡（`pending`/`running`/`failed` 不报 —— 它们没落地，栅栏等着是对的）；
      ② 成员找不到对应卡 ⇒ 不报，但**打印一行「认不出」**（★ 卡 234：宁可漏报不可假报，
        可不许静默 —— 静默 = 判据证明不了自己看得见）；
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
            if card is None:
                # ★ 卡 234：认不出的成员不报漂移（宁可漏报不可假报），但必须有一行可见输出。
                print(f"[认不出] 批 {gate_id} 成员 {mid}：对不上队列里任何一张卡，不报漂移",
                      file=sys.stderr)
                continue
            if card.status != "done":
                continue
            reports.append(
                f"批 {gate_id} 成员 {mid} → 卡 {card.id}（{card.task}）："
                f"栅栏={state} / 队列=done —— 卡已落地但栅栏未推进")
    return reports


def cmd_check(backlog: Backlog) -> int:
    # ★ 卡 262（T-G383）：分区判据。登记表读不了 ⇒ 拒（不静默）；不在 ⇒ 不判（旧仓 / 测试沙箱）。
    try:
        partitions = load_partitions()
    except PartitionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    # ① 分区命名：带前缀的新卡 ⇒ 前缀已登记 + 树名以分区前缀开头。
    naming = validate_partition_naming(backlog, partitions)
    for line in naming:
        print(f"[FAIL] {line}", file=sys.stderr)
    # ② 跨分区「同一文件两个写者」—— 分区只避免号撞，不避免文件撞。
    #    ★ 先打这一句：`validate()` 会因同一个相交拒单，这里补**分区**那一层，点名两边各属哪个分区。
    cross = cross_partition_writers(backlog, partitions)
    for line in cross:
        print(f"[跨分区] {line}", file=sys.stderr)
    code = _problems_or_exit(backlog)
    if code or naming or cross:
        return 1
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


def _toml_str(value: str) -> str:
    """TOML 基本字符串 = JSON 字符串（转义同规）—— 写 TOML 的字符串一律走它（口径坑 39）。"""
    return json.dumps(str(value), ensure_ascii=False)


def render_merged_toml(backlog: Backlog) -> str:
    """把（合并后的）队列渲染成**只读总表**的 TOML 文本（`merge` 用）。

    ★ 只渲染本仓队列用到的字段（id/task/title/tree/spec/files/depends/risk/status）——
      总表是**生成物**，手写注释不保留（注释留在各分片里）。
    """
    lines = ["[base]", f"reviewed = {_toml_str(backlog.reviewed)}", ""]
    for card in backlog.cards:
        lines.extend([
            "[[cards]]",
            f"id = {_toml_str(card.id)}",
            f"task = {_toml_str(card.task)}",
            f"title = {_toml_str(card.title)}",
            f"tree = {_toml_str(card.tree)}",
            f"spec = {_toml_str(card.spec)}",
            f"files = [{', '.join(_toml_str(f) for f in card.files)}]",
            f"depends = [{', '.join(_toml_str(d) for d in card.depends)}]",
            f"risk = {_toml_str(card.risk)}",
            f"status = {_toml_str(card.status)}",
            "",
        ])
    return "\n".join(lines)


def cmd_merge(folder: Path, out: Path, *, execute: bool) -> int:
    """把台账**分片**合并成只读总表（`merge`）—— 默认只打印，`--execute` 才落盘。"""
    try:
        merged = merge_shards(folder)
    except BacklogError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    if merged is None:
        print(f"[OK ] 没有台账分片（{folder}）—— 总表不变")
        return 0
    text = render_merged_toml(merged)
    if not execute:
        print(text)
        print(f"[dry ] 默认只打印；真要落盘加 --execute（写 {out}）", file=sys.stderr)
        return 0
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"[写 ] 合并 {len(merged.cards)} 张卡 → {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="并发调度器：文件级冲突域 + 拓扑分层 + 同层打包（默认只打印）")
    parser.add_argument("command",
                        choices=("check", "plan", "stats", "worktrees", "dispatch", "merge"),
                        help="要做的动作")
    parser.add_argument("--backlog",
                        help=f"总表文件（默认 {DEFAULT_BACKLOG.name}；有分片时以分片为准）")
    parser.add_argument("--shards",
                        help="台账分片目录（默认 docs/backlog/；各分区各写 <分区>.toml）")
    parser.add_argument("--concurrency", type=int, default=None,
                        help=f"并发上限（默认吃面板参数，再退 {DEFAULT_CONCURRENCY}）")
    parser.add_argument("--base", default="",
                        help="建树的基点提交（默认取 backlog 的 [base].reviewed）")
    parser.add_argument("--execute", action="store_true",
                        help="真执行（建树 / 派活 / merge 落盘）；默认只打印")
    return parser


def _load_backlog_for(args: argparse.Namespace) -> Backlog:
    """`check` / `plan` / `stats` / `worktrees` / `dispatch` 读的队列：先分片、后总表。"""
    shards = Path(args.shards) if args.shards else None
    if args.backlog:
        return load_sharded_backlog(Path(args.backlog), shards)
    return load_sharded_backlog(shard_directory=shards)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.concurrency is None:
        args.concurrency = settings_concurrency() or DEFAULT_CONCURRENCY
    if args.command == "merge":
        folder = Path(args.shards) if args.shards else shard_dir()
        out = Path(args.backlog) if args.backlog else DEFAULT_BACKLOG
        return cmd_merge(folder, out, execute=args.execute)
    try:
        backlog = _load_backlog_for(args)
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
