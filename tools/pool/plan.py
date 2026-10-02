r"""队列 / 冲突域 / 排批（从 `tools/wb_plan.py` 抽，卡 106 · T-G202）—— 只标准库、只读、无副作用。

**防什么**：并发时两张卡在**同一个文件 / 同一棵树**上同时写 —— 合并必冲突、audit 会因为两份台账
条目互相盖而红，而且要到收口那一刻才发现。这里把"谁和谁能同时跑"做成纯函数：文件级冲突域 +
拓扑分层 + 同层贪心打包，拒绝任何会冲突的组合。

本模块是 `wb_plan.py` 的**逻辑层**：数据模型（`Card` / `Backlog`）、冲突判据（`validate`）、
排批（`topo_layers` / `greedy_pack` / `plan_batches`）、计划渲染（`render_plan`）与一条
"跑一条命令会印什么"的纯函数（`plan_report`）。CLI 的打印 / 取参数仍留在 `wb_plan.py`。
搬进来时**语义一字未改**（`wb_plan.py` 里那一整段连同注释原样迁到这里）。
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[2]
DIAG = ROOT / "gates" / "diag"
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

# ★ 卡 127（T-G225）：`files` 里**不许**出现的通配字符。`files_intersect()` 是**精确**集合相交，
#   若某张卡把域写成 `tools/pool/*.py` 这类通配，它与**任何**精确路径都不相交 ⇒ 两张卡明明
#   改同一批文件却互不报冲突，**静默绕过**冲突域检查。所以这里在字段层直接拒单（见 `validate`）。
WILDCARD_CHARS = ("*", "?", "[")


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
    """两张卡的冲突域**相交部分** —— 空集 = 可以同批跑。

    ★ 卡 127（T-G225）口径注：这里的匹配是**精确**的（字符串集合相交，`tools/pool/*.py`
    不是任何一个真实路径的字符串 ⇒ 恒不相交）。**栅栏那一侧**（`tools/pool/task.py` 的
    `check_domain`）用的是 `fnmatch`，而 `fnmatch` 的 `*` **跨目录分隔符** —— **两处不是
    同一套语义**（`*` 跨 `/` 在 one 侧算命中、在另一侧不算）。本卡只在**队列侧**禁通配
    （见 `validate` ⑧），**不**改 `task.py`：栅栏侧由另一张卡治；在那之前，两套语义的分歧
    以这里这段为**唯一口径记录**（别再各写一份）。
    """
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


def in_flight(card: Card) -> bool:
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
    ⑤ 依赖成环；⑥ `files` 为空；⑦ `risk`/`status` 取值非法；⑧ `files` 条目含通配字符
    （`*` `?` `[` —— 卡 127 / T-G225：通配会让这张卡与谁都不相交 ⇒ 静默绕过冲突域检查）。

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
            if any(ch in path for ch in WILDCARD_CHARS):
                problems.append(
                    f"卡 {card.id}：files 条目 {path} 含通配字符（`*` `?` `[`）"
                    f"—— 域必须是**精确路径**（`files_intersect()` 是精确匹配，"
                    f"通配会让这张卡与谁都不相交 ⇒ 静默绕过冲突域检查）")
        for dep in card.depends:
            if dep not in ids:
                problems.append(f"卡 {card.id}：depends 指向不存在的卡 {dep}")
        if card.risk not in VALID_RISK:
            problems.append(f"卡 {card.id}：risk={card.risk!r} 不是 {VALID_RISK} 之一")
        if card.status not in VALID_STATUS:
            problems.append(f"卡 {card.id}：status={card.status!r} 不是 {VALID_STATUS} 之一")
    active = [card for card in cards if in_flight(card)]
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
    queue = [card for card in backlog.cards if in_flight(card)]
    out: list[list[Card]] = []
    for layer in topo_layers(queue):
        out.extend(greedy_pack(layer, limit))
    return out


# ================================================================ 渲染 / "跑一条命令会印什么"


def render_plan(batches: Sequence[Sequence[Card]]) -> str:
    lines: list[str] = []
    for i, batch in enumerate(batches, 1):
        lines.append(f"第 {i} 批（{len(batch)} 张，可同时跑）")
        for card in batch:
            tree = card.tree or "（主树）"
            lines.append(f"  · 卡 {card.id}（{card.task}）｜树 {tree}｜{card.title}")
            lines.append(f"      域：{'、'.join(card.files) or '（空）'}")
    return "\n".join(lines)


def find_spec(card: str) -> str:
    """按卡号找规格文件 —— 返回**仓库相对 posix 路径**；找不到 → `""`。

    ★ 卡 116：先在 **`复盘/卡/`**（搬进 git、随仓库分发）里找，找不到再**退回** `gates/diag/`
    （历史 / 尚未搬进 git 的卡仍能解析出来）—— **行为向后兼容**。
    ★ 从 `wb_brief.py` 搬来（卡 106）："某张卡的规格文件在哪"属于**卡域**，是只读查文件，
    放这里让开工切片生成器与号池工具共用同一处（不再各写一份 glob）。
    ★ 卡 127（T-G225）：卡号匹配改成**边界精确** —— 只认 `卡<号>-…` / `卡<号>.md` / `卡<号>_…`
    （`卡<号>` 之后必须是分隔符 `-`/`_`/`.` 或文件名结尾）。旧实现第三档 `*{card}*.md` 是
    **乱兜**：`12` 会命中 `卡112-…` / `卡120-…`（GLM 审查 2.11，按字母序取先）。现在去掉乱兜，
    找不到就**如实返回 `""`**（不猜一张最像的）。
    """
    card = card.strip()
    if not card:
        return ""
    # `卡<号>` 之后：要么直接 `.md`，要么跟一个分隔符（- _ .）再接任意后缀。
    pattern = re.compile(rf"^卡{re.escape(card)}(?:[-_.].*)?\.md$")
    for root in (ROOT / "复盘" / "卡", DIAG):
        if not root.is_dir():
            continue
        hits = sorted(path for path in root.glob("*.md") if pattern.match(path.name))
        if hits:
            return str(hits[0].relative_to(ROOT)).replace("\\", "/")
    return ""


def plan_report(backlog: Backlog, limit: int = DEFAULT_CONCURRENCY) -> tuple[int, str, str]:
    """`wb_plan.py plan` 会印什么 —— 返回 `(退出码, stdout, stderr)` 的**原样文本**（纯函数）。

    ★ 为什么要有它：CLI 的 `cmd_plan()` 与号池 MCP 的 `pool_plan` 工具要给出**逐字相同**的
    计划文本；把"打印字符串"抽成纯函数，两处就不会各写一份（`wb_dispatch` 那条命令拼装仍归 CLI）。
    """
    problems = validate(backlog)
    if problems:
        err = "[FAIL] backlog 不能用：\n" + "".join(f"  · {p}\n" for p in problems)
        return 1, "", err
    batches = plan_batches(backlog, limit)
    out = (f"[计划] 并发上限 {limit}；{len(backlog.cards)} 张卡 → {len(batches)} 批\n"
           f"{render_plan(batches)}\n")
    return 0, out, ""
