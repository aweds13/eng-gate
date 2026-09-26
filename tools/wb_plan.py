r"""并发调度器 `tools/wb_plan.py`（外包卡 010 · 台账号 T-G99）—— 只标准库。

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
  worktrees [--base <sha>]    打印建树命令（`--execute` 才真建）
  dispatch [--concurrency N]  打印派活命令（`--execute` 才真派）

用法：
    python -X utf8 tools/wb_plan.py check
    python -X utf8 tools/wb_plan.py plan --concurrency 3
    python -X utf8 tools/wb_plan.py worktrees --base 1969b46
    python -X utf8 tools/wb_plan.py dispatch

★ 边界（如实写）：CLI 侧的速率 / 账号并发**上界未探测** —— 本工具用 `--concurrency` 把这个量
显式摆出来以便观测，但不声称知道它；`worktrees --execute` / `dispatch --execute` 是"会动世界"的
那一半，默认不执行（卡 010 §8 坑 1：别真建树、别真派活）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKLOG = ROOT / "docs" / "workbacklog.toml"
DEFAULT_CONCURRENCY = 2

# ---------------------------------------------------------------- 冲突域常量（卡 010 §2.4 写死）
# ★ 受保护共享文件集：作者（工人）一律**不许碰**。它们是**跨卡共享**的 —— 台账 / changelog /
#   两张交接文档 / 两个门禁产物；并发时两张卡都写同一个 → 合并必冲突，audit 也会因为两份条目
#   互相盖而红。所以规划器在这里**拒单**（backlog 里某卡的 files 只要含其中一个就报错）。
PROTECTED_FILES = frozenset({
    "docs/traceability.toml",
    "docs/changelog.md",
    "复盘/交接-重构进度.md",
    "复盘/新窗口交接卡.md",
    "gates/last.json",
    "gates/reuse.json",
})

VALID_RISK = ("low", "mid", "high")          # high 才派对抗性复核
VALID_STATUS = ("pending", "running", "done", "failed")
# ★ T-G119：只有这两种参与「冲突判定」与「排批」—— done/failed 是历史，
#   它们占过的文件与树都**已经释放**（backlog 是**队列**，不是「全部已排班」）。
ACTIVE_STATUS = ("pending", "running")


class BacklogError(Exception):
    """backlog 文件读不了 / 字段缺失 —— 与「排班冲突」分开：前者是文件坏了，后者是安排不合法。"""


# ================================================================ 数据模型


@dataclass(frozen=True)
class Card:
    """一张卡的域声明（backlog 的一行）。`files` 就是它的**冲突域**。"""

    id: str
    task: str
    title: str
    tree: str
    spec: str
    files: tuple[str, ...]
    depends: tuple[str, ...] = ()
    risk: str = "mid"
    status: str = "pending"


@dataclass(frozen=True)
class Backlog:
    reviewed: str
    cards: tuple[Card, ...]

    def by_id(self) -> dict[str, Card]:
        return {card.id: card for card in self.cards}


# ================================================================ 读 backlog


def _require(mapping: dict, key: str, where: str) -> object:
    if key not in mapping:
        raise BacklogError(f"{where} 缺字段 `{key}`")
    return mapping[key]


def _as_str_tuple(value: object, where: str, key: str) -> tuple[str, ...]:
    """读一个字符串数组；**去重保序**（同一份域里写两遍不算两次冲突）。"""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise BacklogError(f"{where} 的 `{key}` 必须是字符串数组，拿到 {type(value).__name__}")
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _load_card(raw: object, index: int, seen: set[str]) -> Card:
    if not isinstance(raw, dict):
        raise BacklogError(f"第 {index} 张卡不是一张表（[[cards]]）")
    cid = str(_require(raw, "id", f"第 {index} 张卡")).strip()
    where = f"卡 {cid}"
    if not cid:
        raise BacklogError(f"第 {index} 张卡的 `id` 是空的")
    if cid in seen:
        raise BacklogError(f"卡号重复：{cid}")
    seen.add(cid)
    return Card(
        id=cid,
        task=str(_require(raw, "task", where)).strip(),
        title=str(_require(raw, "title", where)).strip(),
        tree=str(_require(raw, "tree", where)).strip(),          # "" = 主树
        spec=str(_require(raw, "spec", where)).strip(),
        files=_as_str_tuple(_require(raw, "files", where), where, "files"),
        depends=_as_str_tuple(raw.get("depends", []), where, "depends"),
        risk=str(raw.get("risk", "mid")).strip(),
        status=str(raw.get("status", "pending")).strip(),
    )


def load_backlog(path: Path = DEFAULT_BACKLOG) -> Backlog:
    """读 backlog —— 文件坏了就抛 `BacklogError`（清楚地说哪一行哪一格）；不合法（冲突）另判。"""
    if not path.exists():
        raise BacklogError(f"backlog 文件不存在：{path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BacklogError(f"backlog 不是合法 TOML：{exc}") from exc
    base = data.get("base")
    if not isinstance(base, dict) or not str(base.get("reviewed", "")).strip():
        raise BacklogError("缺 [base] 段或 base.reviewed（已复核的基点提交）")
    raw_cards = data.get("cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        raise BacklogError("缺 [[cards]] 段（至少一张卡）")
    seen: set[str] = set()
    cards = tuple(_load_card(raw, i + 1, seen) for i, raw in enumerate(raw_cards))
    return Backlog(reviewed=str(base["reviewed"]).strip(), cards=cards)


# ================================================================ 冲突域判据


def files_intersect(a: Card, b: Card) -> set[str]:
    """两张卡的冲突域**相交部分** —— 空集 = 可以同批跑。"""
    return set(a.files) & set(b.files)


def find_cycle(cards: Sequence[Card]) -> list[str] | None:
    """找一条依赖环（返回环上的卡号、首尾相接）；没有环 → `None`。

    只认**存在的卡之间**的边（指向不存在的卡是另一条错，④ 单独报）。
    """
    ids = {card.id for card in cards}
    graph = {card.id: [dep for dep in card.depends if dep in ids] for card in cards}
    white, gray, black = 0, 1, 2
    color = dict.fromkeys(graph, white)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = gray
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == gray:
                return [*stack[stack.index(nxt):], nxt]
            if color[nxt] == white:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = black
        return None

    for node in graph:
        if color[node] == white:
            found = visit(node)
            if found:
                return found
    return None


def _in_flight(card: Card) -> bool:
    """这张卡还需不需要排班（`pending` / `running`）。"""
    return card.status in ACTIVE_STATUS


def _reachable(start: str, deps: dict[str, set[str]]) -> set[str]:
    """从 `start` 沿 `depends` 走，能到达的所有卡号（含传递；有 `seen` 兜环）。"""
    seen: set[str] = set()
    stack = [start]
    while stack:
        for nxt in deps.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def dependency_path(a: Card, b: Card, cards: Sequence[Card]) -> bool:
    """`a`、`b` 之间有没有**依赖路径**（任一方向、含传递）。

    ★ 为什么这能救「同域两卡」：有依赖路径时 `topo_layers()` 会把被依赖的那张放在**更早的层**，
    而 `greedy_pack()` **不跨层**打包 → 两张卡**不可能落进同一批** → 同文件不会有两个同时的写者。
    """
    deps = {card.id: set(card.depends) for card in cards}
    return b.id in _reachable(a.id, deps) or a.id in _reachable(b.id, deps)


def validate(backlog: Backlog) -> list[str]:
    """拒单清单（空 = 这份 backlog 能用）。

    字段类（**所有卡都要过**）：② `files` 含受保护共享文件；④ `depends` 指向不存在的卡；
    ⑤ 依赖成环；⑥ `files` 为空；⑦ `risk`/`status` 取值非法。

    冲突类（★ **只判"还在队列里"的卡**，即 `pending` / `running`）：
    ① 两卡 `files` 相交 **且两者之间没有依赖路径**；③ 两卡用同一棵树。

    ★ T-G119 的两处语义更正（两条都是真撞出来的）：
      · **`done` / `failed` 不参与冲突判定** —— 它们占过的文件与树**已经释放**；
        从前把整份 backlog 当「全部已排班」，于是**已完成的卡会与待派卡报「同一文件两个写者」**。
      · **同域两卡只要**有依赖路径**就允许共存** —— `topo_layers()` 会把被依赖的放更早的层、
        `greedy_pack()` 又不跨层，所以它们**不可能同批**；从前一律拒单，装不下
        队列里的「同域串行」（例：024 与 029 都要改 `wb_dispatch.py`）。
    """
    problems: list[str] = []
    cards = backlog.cards
    ids = {card.id for card in cards}
    for card in cards:
        if not card.files:
            problems.append(f"卡 {card.id}：files 为空（没有域声明 → 没法判断冲突）")
        for path in card.files:
            if path in PROTECTED_FILES:
                problems.append(
                    f"卡 {card.id}：files 含受保护共享文件 {path}（作者一律不许碰）")
        for dep in card.depends:
            if dep not in ids:
                problems.append(f"卡 {card.id}：depends 指向不存在的卡 {dep}")
        if card.risk not in VALID_RISK:
            problems.append(f"卡 {card.id}：risk={card.risk!r} 不是 {VALID_RISK} 之一")
        if card.status not in VALID_STATUS:
            problems.append(f"卡 {card.id}：status={card.status!r} 不是 {VALID_STATUS} 之一")
    active = [card for card in cards if _in_flight(card)]
    for i, first in enumerate(active):
        for second in active[i + 1:]:
            hit = files_intersect(first, second)
            if hit and not dependency_path(first, second, cards):
                problems.append(
                    f"卡 {first.id} 与 {second.id}：files 相交 {sorted(hit)}"
                    f"（同一文件两个写者；要共存就给其中一张写 `depends`）")
    tree_owner: dict[str, str] = {}
    for card in active:
        owner = tree_owner.get(card.tree)
        if owner is not None:
            label = card.tree or "（主树）"
            problems.append(
                f"卡 {card.id} 与 {owner}：用了同一棵树 {label}（一棵树只能一个写者）")
        else:
            tree_owner[card.tree] = card.id
    cycle = find_cycle(cards)
    if cycle:
        problems.append("依赖成环：" + " → ".join(cycle))
    return problems


# ================================================================ 排班：拓扑分层 + 同层打包


def topo_layers(cards: Sequence[Card]) -> list[list[Card]]:
    """按 `depends` 拓扑**分层**：没有依赖的在第 0 层；某卡在第 k 层 = 它的依赖都在 < k 层。

    层号取**最长路径**（不是最短）：一张卡既依赖第 0 层的 A 又依赖第 1 层的 B，它必须在
    **第 2 层**（等 B 做完）—— 取最短会把它提前到会跟 B 同批。菱形依赖（A→B、A→C、B→D、C→D）
    下 D 落在第 2 层。成环 → 抛 `BacklogError`（`validate()` 已经拦过，这是防御）。
    """
    by_id = {card.id: card for card in cards}
    children: dict[str, list[str]] = {card.id: [] for card in cards}
    indegree: dict[str, int] = {}
    for card in cards:
        existing = [dep for dep in dict.fromkeys(card.depends) if dep in by_id]
        indegree[card.id] = len(existing)
        for dep in existing:
            children[dep].append(card.id)
    order: list[str] = []
    ready = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
    while ready:
        cid = ready.popleft()
        order.append(cid)
        for child in sorted(children[cid]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(cards):
        raise BacklogError("依赖成环（拓扑排序不完整）—— check 本该先拦下它")
    level = dict.fromkeys(order, 0)
    for cid in order:
        for child in children[cid]:
            level[child] = max(level[child], level[cid] + 1)
    layers: list[list[Card]] = []
    for cid in order:
        lv = level[cid]
        while len(layers) <= lv:
            layers.append([])
        layers[lv].append(by_id[cid])
    return layers


def greedy_pack(cards: Sequence[Card], limit: int) -> list[list[Card]]:
    """同层内**贪心打包**：每批 ≤ `limit` 张；同批内两两 `files` 不相交、树不重复。

    放不进任何已有批就开新批。所以"同层三卡但两两相交"会各占一批 —— 冲突域是硬约束，
    并发上限只是第二约束。
    """
    if limit < 1:
        raise BacklogError(f"并发上限必须 ≥ 1，拿到 {limit}")
    batches: list[list[Card]] = []
    trees: list[set[str]] = []
    for card in cards:
        for batch, used_trees in zip(batches, trees, strict=True):
            if len(batch) >= limit:
                continue
            if card.tree in used_trees:
                continue
            if any(files_intersect(card, other) for other in batch):
                continue
            batch.append(card)
            used_trees.add(card.tree)
            break
        else:
            batches.append([card])
            trees.append({card.tree})
    return batches


def plan_batches(backlog: Backlog, limit: int = DEFAULT_CONCURRENCY) -> list[list[Card]]:
    """**待派队列**的批次 = 逐层贪心打包（批次不跨层：依赖靠层保证顺序）。

    ★ T-G119：只排 `pending` / `running` —— `done` / `failed` 是历史、不进批次。
    （`depends` 指向已完成卡也没关系：`topo_layers()` 对"不在集合里的依赖"是忽略的。）
    """
    queue = [card for card in backlog.cards if _in_flight(card)]
    out: list[list[Card]] = []
    for layer in topo_layers(queue):
        out.extend(greedy_pack(layer, limit))
    return out


# ================================================================ 渲染 / 命令拼装


def render_plan(batches: Sequence[Sequence[Card]]) -> str:
    lines: list[str] = []
    for i, batch in enumerate(batches, 1):
        lines.append(f"第 {i} 批（{len(batch)} 张，可同时跑）")
        for card in batch:
            tree = card.tree or "（主树）"
            lines.append(f"  · 卡 {card.id}（{card.task}）｜树 {tree}｜{card.title}")
            lines.append(f"      域：{'、'.join(card.files) or '（空）'}")
    return "\n".join(lines)


def worktree_commands(backlog: Backlog, base: str) -> list[tuple[Card, str]]:
    """每张非主树卡的建树命令；主树那张卡**不建树**（卡 010 §3.2）。"""
    return [(card, f"git worktree add {card.tree} {base}")
            for card in backlog.cards if card.tree and _in_flight(card)]


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
    active = [card for card in backlog.cards if _in_flight(card)]
    print(f"[队列] 待派 {len(active)} 张 / 其它 {len(backlog.cards) - len(active)} 张"
          f"（★ 只有待派的参与冲突判定与排批）")
    return 0


def cmd_plan(backlog: Backlog, limit: int) -> int:
    code = _problems_or_exit(backlog)
    if code:
        return code
    batches = plan_batches(backlog, limit)
    print(f"[计划] 并发上限 {limit}；{len(backlog.cards)} 张卡 → {len(batches)} 批")
    print(render_plan(batches))
    return 0


def cmd_stats(backlog: Backlog, limit: int) -> int:
    """队列全貌（只读）：待派 / 其它 / 批次 / 最大一批 / 占用的树。

    ★ 一条命令看全貌 —— 别让人去数文件（"少读"的精神）。
    """
    code = _problems_or_exit(backlog)
    if code:
        return code
    active = [card for card in backlog.cards if _in_flight(card)]
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
