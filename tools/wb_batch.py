r"""批次并入派活链 CLI `tools/wb_batch.py`（卡 E10 · T-AG461）—— 只标准库。

三个入口（`--help` 里也写着这三行）：

    plan    只读：从队列取**待落卡**，算候选批（成员 files 两两不相交 / depends 已满足 / ≤4）
    make    写盘：生成预声明 + 三方文书骨架 + 台账证据并集 + 批次树
    land    起门禁：转发 `wb_land.py --batch <批号>`

**为什么有它**：攒批能力本仓早就有（卡 228 · T-G344：`wb_task.py register` 收多成员预声明、
`wb_land.py --batch` 逐成员按「产物 ∩ 暂存」翻 status），但入口散在三处 —— 预声明手打、
三段文书手写、批次树靠一段 54 行临时脚本（`git add -A` → `git diff --cached --binary` →
`git apply --3way`）。于是「哪些卡已经干完、能合成一批落地」全靠人。本工具把那三件事收成命令。

★ **判据不另写一份**（判据在库里）：
  · 文件相交 = `pool.plan.files_intersect()`；
  · 依赖 = `pool.plan.dependency_path()`（只用于把"为什么拆开"说清）；
  · 分层 = `pool.plan.topo_layers()`；
  · 预声明合法性 = `pool.task._validate_manifest()`（`make` 落盘前**真跑一遍**，见卡判据 3）。
★ 批大小上限 **4** 写在这里（不是文档）：`BATCH_LIMIT`；超限拒单并打印 `LIMIT_WHY`。
★ 边界（如实写）：只治单机（门禁锁本来就全仓一把）；批次失败目前只能人工逐个重跑
  （自动二分是卡 E11）；时间估算用本机实测均值（一趟全量 ≈19 min，pytest 占 1024 s / 约 90%），
  不是"省 N 小时"的营销数。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib

try:
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root
    except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
        pipe_root = None  # type: ignore[assignment]

from pool import plan as pool_plan
from pool import task as pool_task
from pool.review import changed_paths as _parse_changed_paths
from wb_plan import load_sharded_backlog  # 队列读取唯一实现（分片优先、总表兜底）

ROOT = pipe_root.data_root() if pipe_root is not None else Path(__file__).resolve().parents[1]

#: ★ 判据 6：批大小上限**写进工具**（不是文档）。依据见 `LIMIT_WHY`。
BATCH_LIMIT = 4

#: 上限 4 的依据（用户要求"超限拒单并打印依据"）。
LIMIT_WHY = (
    "上限 4：TFS11 用 5；ACM TSE 2022 实测批 4 可免二分地最优；"
    "Shopify 用 8 但只允许同时 3 批在飞"
)

#: 批次预声明里默认的门禁命令（与 T-AG460 那张预声明逐字一致）。
GATE_CMD = "python -X utf8 scripts/run_gates.py"

#: 本机实测：一趟全量门禁 ≈19 min（pytest 1024 s / 约 90%）。只用来算"少跑几趟"，不是承诺。
FULL_GATE_MINUTES = 19

#: 层只是**文书分组用**（预声明里必须写）—— 按域前缀推，推不出就归"框架层"。
_LAYER_RULES: tuple[tuple[str, str], ...] = (
    ("skills/", "技能层"),
    ("docs/", "文档层"),
    ("复盘/", "文档层"),
    ("src/", "源码层"),
    ("examples/", "示例层"),
    ("framework/", "框架层"),
    ("harness/", "框架层"),
)
_LAYER_DEFAULT = "框架层"


class BatchPlanError(Exception):
    """批次规划 / 生成 / 落地交接的错（用法与拒绝分开：拒单理由都在消息里逐条点名）。"""


# ================================================================ 环境（三棵树）
@dataclass(frozen=True)
class Env:
    """一次调用要用的三个位置（显式传，测试才不用碰真仓）。"""

    root: Path       # 队列所在的树（卡树；`docs/workbacklog.toml` 在这儿）
    main: Path       # 主工作树（卡树 `.wt/<卡>`、批次树 `.wt/batch<号>` 都相对它）
    batch_dir: Path  # 预声明目录（默认主树 `gates/diag/batch/`）


def main_tree_root() -> Path:
    """主工作树根 —— 复用 `pool.task.main_tree_root()`（唯一实现，不另算一遍）。"""
    return pool_task.main_tree_root()


def default_env(root: Path | None = None) -> Env:
    """默认环境：队列 = 本文件所在树；主树从 git 算；预声明在主树 `gates/diag/batch/`。"""
    base = Path(root) if root is not None else ROOT
    main = main_tree_root()
    return Env(root=base, main=main, batch_dir=main / "gates" / "diag" / "batch")


def load_queue(root: Path) -> pool_plan.Backlog:
    """读队列：**先分片后总表**（复用 `wb_plan.load_sharded_backlog`，不另写一份）。"""
    return load_sharded_backlog(root / "docs" / "workbacklog.toml", root / "docs" / "backlog")


# ================================================================ 待落卡（plan 的输入）
def card_changes(tree: Path) -> list[str]:
    """卡树里的**实际改动**（含未跟踪）—— 复用 `pool.review.changed_paths` 的解析口径。"""
    if not tree.is_dir():
        return []
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall", "--no-renames"],
        cwd=str(tree), capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode:
        return []
    return _parse_changed_paths((done.stdout or "").rstrip("\r\n"))


def awaiting_commit(env: Env, task: str) -> bool:
    """这张卡的任务状态是不是 `awaiting-commit`（申请已齐、等人补文书）——读不到就 False。"""
    path = env.batch_dir / f"{task}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("state") == "awaiting-commit"


def landing_candidates(
    env: Env, backlog: pool_plan.Backlog,
) -> tuple[list[pool_plan.Card], dict[str, str]]:
    """**待落卡** = `status=pending` 且（卡树有产物 或 任务已是 awaiting-commit）。

    返回 `(候选卡（队列序）, {卡号: 没进候选的原因})`。原因也要给出来 —— 判据 3 要求
    「B 不许进批，且理由里点名 A」，理由不许静默吞掉。
    """
    cards: list[pool_plan.Card] = []
    skipped: dict[str, str] = {}
    for card in backlog.cards:
        if card.status != "pending":
            continue
        if card.tree:
            tree = env.main / card.tree
            if not tree.is_dir():
                skipped[card.id] = f"卡树 {card.tree} 不存在"
                continue
            if card_changes(tree):
                cards.append(card)
                continue
        if awaiting_commit(env, card.task):
            cards.append(card)
            continue
        skipped[card.id] = "卡树没有产物（也没有 awaiting-commit 申请）"
    return cards, skipped


def eligible_cards(
    backlog: pool_plan.Backlog, candidates: list[pool_plan.Card],
) -> tuple[list[pool_plan.Card], dict[str, str]]:
    """依赖已满足的候选（判据：`depends` 里的卡必须 `status=done`）。

    不满足 ⇒ 不让进批，并把**是哪张依赖**写进理由（判据 3：理由里点名 A）。
    """
    by_id = backlog.by_id()
    ok: list[pool_plan.Card] = []
    blocked: dict[str, str] = {}
    for card in candidates:
        unmet: list[str] = []
        for dep in card.depends:
            other = by_id.get(dep)
            if other is None:
                unmet.append(f"{dep}（队列里没有这张卡）")
            elif other.status != "done":
                unmet.append(f"{dep}（status={other.status}）")
        if unmet:
            blocked[card.id] = f"依赖 {'、'.join(unmet)} 还没落"
        else:
            ok.append(card)
    return ok, blocked


def pack_landing_batches(
    backlog: pool_plan.Backlog, cards: list[pool_plan.Card], limit: int = BATCH_LIMIT,
) -> list[list[pool_plan.Card]]:
    """把候选打成落地批：**按拓扑层、层内按队列序贪心**，同批两两 `files` 不相交、≤ limit。

    ★ 相交判据复用 `pool.plan.files_intersect()`（精确集合相交，与 `validate()` 同一条规则）；
      分层复用 `pool.plan.topo_layers()` —— 本工具**不另写一套**。
    ★ 落地批与"并发批"不同：同文件的两张卡哪怕有依赖路径也**不许同批**（一批是一笔提交，
      两个写者仍会互相盖）；依赖只决定**谁先落**（没落的依赖卡会把后手挡在候选外）。
    """
    if limit < 1:
        raise BatchPlanError(f"批大小上限必须 ≥ 1，拿到 {limit}")
    order = {card.id: index for index, card in enumerate(backlog.cards)}
    groups: list[list[pool_plan.Card]] = []
    for layer in pool_plan.topo_layers(cards):
        for card in sorted(layer, key=lambda c: order.get(c.id, 0)):
            for group in groups:
                if len(group) >= limit:
                    continue
                if any(pool_plan.files_intersect(card, other) for other in group):
                    continue
                group.append(card)
                break
            else:
                groups.append([card])
    return groups


def overlap_notes(
    backlog: pool_plan.Backlog, cards: list[pool_plan.Card], groups: list[list[pool_plan.Card]],
) -> list[str]:
    """把「谁跟谁同文件、所以拆开」说清（理由里带有没有依赖路径 —— 复用 dependency_path）。"""
    notes: list[str] = []
    for index, first in enumerate(cards):
        for second in cards[index + 1:]:
            hit = pool_plan.files_intersect(first, second)
            if not hit:
                continue
            if any(first in group and second in group for group in groups):
                continue
            dep = pool_plan.dependency_path(first, second, backlog.cards)
            tail = ("（有依赖路径也拆开：一批是一笔提交，同文件仍是两个写者）" if dep
                    else "（没有依赖路径 ⇒ 必然拆开）")
            notes.append(f"卡 {first.id} 与 {second.id}：同改 {'、'.join(sorted(hit))}{tail}")
    return notes


def render_plan_output(
    groups: list[list[pool_plan.Card]],
    eligible: list[pool_plan.Card],
    blocked: dict[str, str],
    skipped: dict[str, str],
    notes: list[str],
) -> str:
    """`plan` 打印的原文（纯函数 —— 测试直接读它，不靠"看起来对了"）。"""
    lines = [
        f"[计划] 待落 {len(eligible)} 张 → {len(groups)} 批"
        f"（每批 ≤ {BATCH_LIMIT}；判据：files 两两不相交 / depends 已满足）",
    ]
    if not groups:
        lines.append("  （没有可合批的卡：卡树没产物、依赖没落、或都已被批占着）")
    for index, group in enumerate(groups, 1):
        lines.append(f"[批 {index}] {len(group)} 张")
        for card in group:
            lines.append(f"  · 卡 {card.id}（{card.task}）｜树 {card.tree}｜{card.title}")
            lines.append(f"      域：{'、'.join(card.files) or '（空）'}")
        saved = (len(group) - 1) * FULL_GATE_MINUTES
        lines.append(
            f"  [省时] 少跑 {len(group) - 1} 趟全量门禁 ≈ {saved} min"
            f"（本机实测一趟全量 ≈{FULL_GATE_MINUTES} min，pytest 占 1024 s / 约 90%）")
    for note in notes:
        lines.append(f"[拆开] {note}")
    for card_id, why in blocked.items():
        lines.append(f"[没进批] 卡 {card_id}：{why}")
    if skipped:
        lines.append(
            f"[跳过] {len(skipped)} 张 pending 卡没有产物/没有 awaiting-commit 申请："
            f"{'、'.join(skipped)}")
    return "\n".join(lines)


# ================================================================ 预声明 / 台账 / 文书
def _toml(value: object) -> str:
    """TOML 基本字符串 = JSON 字符串（转义同规，中文原样落盘）。"""
    return json.dumps(str(value), ensure_ascii=False)


def layer_for(card: pool_plan.Card) -> str:
    """成员层（只用于文书分组）：按域前缀推；推不出就归"框架层"。"""
    scores: dict[str, int] = {}
    for path in card.files:
        for prefix, layer in _LAYER_RULES:
            if path.startswith(prefix):
                scores[layer] = scores.get(layer, 0) + 1
                break
        else:
            scores[_LAYER_DEFAULT] = scores.get(_LAYER_DEFAULT, 0) + 1
    if not scores:
        return _LAYER_DEFAULT
    # 最多的那层；并列取 _LAYER_RULES 里先出现的（dict 插入序已按 files 顺序，稳定）
    return max(scores, key=lambda name: scores[name])


def render_manifest(
    batch_id: str, cards: list[pool_plan.Card], why: str, gate_cmd: str,
) -> str:
    """预声明的 TOML 原文（顶层 4 键 + 每成员 `id / layer / what / paths`）。"""
    lines = [
        f"id = {_toml(batch_id)}",
        f"why = {_toml(why)}",
        f"gate_cmd = {_toml(gate_cmd)}",
        'on_complete = ["draft"]',
    ]
    for card in cards:
        lines += [
            "",
            "[[member]]",
            f"id = {_toml(card.id)}",
            f"layer = {_toml(layer_for(card))}",
            f"what = {_toml(card.title)}",
            f"paths = [{', '.join(_toml(path) for path in card.files)}]",
        ]
    return "\n".join(lines) + "\n"


def manifest_for(
    batch_id: str, cards: list[pool_plan.Card], why: str, gate_cmd: str,
) -> dict:
    """预声明的内存形状（**落盘前**先过 `pool.task._validate_manifest` —— 判据 3）。"""
    return {
        "id": batch_id,
        "why": why,
        "gate_cmd": gate_cmd,
        "on_complete": ["draft"],
        "member": [
            {"id": card.id, "layer": layer_for(card), "what": card.title,
             "paths": list(card.files)}
            for card in cards
        ],
    }


def _entry_of(root: Path, task: str) -> dict:
    """台账里某张卡的条目（读不到 / 没有 ⇒ 空字典，不崩、不猜）。"""
    path = root / "docs" / "traceability.d" / f"{task}.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    entries = data.get("entries") or {}
    value = entries.get(task) if isinstance(entries, dict) else None
    return value if isinstance(value, dict) else {}


def render_traceability(
    batch_id: str, cards: list[pool_plan.Card], entries: dict[str, dict],
) -> str:
    """台账条目（证据取**并集**：成员 files + 各卡已有 evidence；gaps 合并）。

    ★ 判据 4：审计 ⑫（`scripts/audit_progress.py` 的 `check_claimed_files`）要求
      「本笔改的文件必须都被台账指针指到」⇒ 只并 gaps 不并 evidence 必红。
      这里对每个成员文件都写一条 `file:` 指针。
    """
    evidence: list[str] = []

    def add(item: str) -> None:
        if item and item not in evidence:
            evidence.append(item)

    for card in cards:
        if card.spec:
            add(f"file:{card.spec}")
        for path in card.files:
            add(f"file:{path}")
        for item in (entries.get(card.id) or {}).get("evidence") or []:
            add(str(item))
    gaps: list[str] = [
        f"- **批 {batch_id} 尚未落地**：status=partial；落地后由 "
        f"`wb_land.py --batch {batch_id}` 逐成员按「产物 ∩ 暂存」翻 status。"
    ]
    for card in cards:
        gap = str((entries.get(card.id) or {}).get("gaps") or "").strip()
        gaps.append(f"- 卡 {card.id}（{card.task}）：{gap}" if gap
                    else f"- 卡 {card.id}（{card.task}）：台账没有 gaps（原样合并：空）")
    lines = [
        f"[entries.{_toml(batch_id)}]",
        f"id = {_toml(batch_id)}",
        f"title = {_toml('批 ' + batch_id + '：' + ' + '.join(card.id for card in cards))}",
        'group = "ENGINEERING"',
        'status = "partial"',
        "evidence = [",
        *[f"  {_toml(item)}," for item in evidence],
        "]",
        f"gaps = {_toml(' '.join(gaps))}",
    ]
    return "\n".join(lines) + "\n"


def render_text_skeleton(
    batch_id: str, cards: list[pool_plan.Card], entries: dict[str, dict],
) -> str:
    """`gates/diag/_text_<批号去横线>.md` 的骨架（三段文书；枚举机器填，『为什么』人补）。"""
    lines = [
        f"# 批 {batch_id} 三段文书骨架（机器填枚举；人补『为什么』）",
        "",
        f"> 成员：{'、'.join(card.id for card in cards)}",
        f"> 层：{'、'.join(dict.fromkeys(layer_for(card) for card in cards))}",
        "> ★ 本文件由 `wb_batch.py make` 生成（会重算）；人写的东西别写在这里。",
        "",
        "## 一、这一批改了哪些（机器填）",
        "",
        "| 卡 | 层 | 改了什么 | 碰过的文件 |",
        "|---|---|---|---|",
    ]
    for card in cards:
        lines.append(
            f"| {card.id} | {layer_for(card)} | {card.title} | {'、'.join(card.files)} |")
    lines += [
        "",
        "## 二、台账行（骨架）",
        "",
        "```",
        f"[entries.{_toml(batch_id)}]",
        f"id = {_toml(batch_id)}",
        'title = "（这一批作为一个整体干了什么，一句话）"',
        'group = "ENGINEERING"',
        'status = "done"    # 落地后由人改',
        "evidence = [ … 见 docs/traceability.d/<批号>.toml（证据并集已机器填好） … ]",
        'gaps = "（人写）"',
        "```",
        "",
        "## 三、changelog 节（骨架）",
        "",
        "```",
        f"### {batch_id}（批 {batch_id}：{'、'.join(card.id for card in cards)}）",
        "- 为什么：（★ 人写）",
        "- 改了什么：见上表（机器按成员填好）",
        "- 证据：全量门禁 + 各卡证据（见台账条目）",
        "```",
        "",
        "## 四、成员 gaps（合并，供人写文书）",
        "",
    ]
    for card in cards:
        gap = str((entries.get(card.id) or {}).get("gaps") or "").strip()
        lines.append(f"- 卡 {card.id}：{gap or '（台账没写 gaps）'}")
    return "\n".join(lines) + "\n"


# ================================================================ 批次树（git apply --3way）
def batch_tree_rel(batch_id: str) -> str:
    """批号 → 批次树（相对主树的 posix 路径）：`T-AG461` → `.wt/batch461`。

    与 `.wt/batch460` 同口径：取批号里最后一段数字；没有数字就用批号的字母数字。
    """
    digits = re.findall(r"\d+", batch_id)
    suffix = digits[-1] if digits else re.sub(r"[^0-9A-Za-z]+", "", batch_id)
    return f".wt/batch{suffix}"


def _git_text(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _git_bytes(
    args: list[str], cwd: Path, patch: bytes | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), input=patch, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _tail(raw: bytes | None, limit: int = 300) -> str:
    text = (raw or b"").decode("utf-8", "replace").strip()
    return text[-limit:]


def export_patch(tree: Path, base_rev: str, card_id: str) -> bytes:
    """把一棵卡树的改动导成补丁：`git add -A` → `git diff --cached --binary <主树 HEAD>`。

    ★ 基点取**主树 HEAD**（临时脚本用的是卡树 HEAD）：卡分支上**已提交**的活也算进这一批
      —— 否则"工人小步提交到卡分支"的产物会被静默漏掉。
    """
    staged = _git_text(["add", "-A"], tree)
    if staged.returncode:
        raise BatchPlanError(
            f"卡 {card_id} 的卡树 `git add -A` 失败：{(staged.stderr or '').strip()[-300:]}")
    diff = _git_bytes(["diff", "--cached", "--binary", base_rev], tree)
    if diff.returncode:
        raise BatchPlanError(
            f"卡 {card_id} 导补丁失败（基点 {base_rev[:12]}）：{_tail(diff.stderr)}")
    return diff.stdout


def _conflict_paths(tree: Path, stderr: bytes | None) -> list[str]:
    """合不上时点名路径：先问 git（未合并索引），再从 stderr 的 `patch failed: <path>:N` 兜。"""
    done = _git_text(["diff", "--name-only", "--diff-filter=U"], tree)
    paths = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
    if done.returncode == 0 and paths:
        return paths
    text = (stderr or b"").decode("utf-8", "replace")
    for line in text.splitlines():
        match = re.search(r"patch failed:\s*(.+?):\d+", line)
        if match and match.group(1) not in paths:
            paths.append(match.group(1))
    return paths


def _drop_batch_tree(env: Env, tree: Path, branch: str) -> None:
    """清掉半合的批次树（失败不留半合状态）。"""
    _git_text(["worktree", "remove", "--force", str(tree)], env.main)
    _git_text(["branch", "-D", branch], env.main)


def build_batch_tree(
    env: Env, batch_id: str, patches: list[tuple[pool_plan.Card, bytes]],
) -> Path:
    """在主树 HEAD 上建 `.wt/batch<号>`，逐成员 `git apply --3way`；合不上 ⇒ 退非零并点名。"""
    rel = batch_tree_rel(batch_id)
    tree = env.main / rel
    branch = f"batch/{rel.rsplit('batch', 1)[-1]}"
    if tree.exists():
        raise BatchPlanError(f"批次树已存在：{tree}（先手工收掉它再 make）")
    added = _git_text(["worktree", "add", "-b", branch, str(tree), "HEAD"], env.main)
    if added.returncode:
        raise BatchPlanError(
            f"建批次树失败（git worktree add -b {branch}）："
            f"{(added.stderr or added.stdout or '').strip()[-300:]}")
    try:
        for card, patch in patches:
            if not patch.strip():
                raise BatchPlanError(
                    f"卡 {card.id} 的卡树没有可合的改动（补丁为空）—— 先在卡树里干活")
            done = _git_bytes(["apply", "--3way", "--whitespace=nowarn", "-"], tree, patch)
            if done.returncode:
                conflicts = _conflict_paths(tree, done.stderr)
                raise BatchPlanError(
                    f"批次树合不上：卡 {card.id} 的补丁在 "
                    f"{'、'.join(conflicts) or '（git 没点名路径）'} 冲突"
                    f"（git apply --3way 退 {done.returncode}）：{_tail(done.stderr)}")
    except Exception:
        _drop_batch_tree(env, tree, branch)
        raise
    return tree


# ================================================================ make
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_batch(
    env: Env, batch_id: str, member_ids: list[str] | None, *, why: str = "",
    gate_cmd: str = GATE_CMD,
) -> dict[str, Path]:
    """生成预声明 + 三方文书骨架 + 台账证据并集 + 批次树。

    `member_ids` 不给 ⇒ 用 `plan` 算出来的**第一批**（仍然是人显式说 `make`，批不默认发生）。
    返回写出来的四个位置（调用方打印）。
    """
    backlog = load_queue(env.root)
    by_id = backlog.by_id()
    if member_ids is None:
        cards, _skipped = landing_candidates(env, backlog)
        eligible, _blocked = eligible_cards(backlog, cards)
        groups = pack_landing_batches(backlog, eligible)
        if not groups:
            raise BatchPlanError(
                "没有可合批的待落卡（卡树有产物、或申请已是 awaiting-commit 才进候选）")
        member_ids = [card.id for card in groups[0]]
    ids = list(dict.fromkeys(str(mid).strip() for mid in member_ids if str(mid).strip()))
    if not ids:
        raise BatchPlanError("成员名单是空的（`make <批号> --cards <卡…>` 或先让 plan 有候选）")
    # ★ 判据 6：上限 4 —— 先于任何 git 动作拒单（零副作用）。
    if len(ids) > BATCH_LIMIT:
        raise BatchPlanError(f"成员 {len(ids)} 张超过上限 {BATCH_LIMIT} —— {LIMIT_WHY}")

    cards: list[pool_plan.Card] = []
    for card_id in ids:
        card = by_id.get(card_id)
        if card is None:
            raise BatchPlanError(
                f"队列里没有卡 {card_id}（docs/workbacklog.toml 或分片里找不到）")
        if card.status != "pending":
            raise BatchPlanError(
                f"卡 {card_id} 的 status={card.status}，不是 pending —— 只有待落卡能进批")
        if not card.tree:
            raise BatchPlanError(
                f"卡 {card_id} 在主树（tree 为空）—— 主树卡不能进批（一卡一树，"
                f"批次树要独立 `.wt/batch<号>`）")
        cards.append(card)

    for card in cards:
        unmet = [dep for dep in card.depends
                 if (by_id.get(dep) is None or by_id[dep].status != "done")]
        if unmet:
            raise BatchPlanError(
                f"卡 {card.id} 的依赖 {'、'.join(unmet)} 还没落 ⇒ 不许进批"
                f"（先让依赖卡落地，再合这一批）")

    # ★ 判据 6 的另一种形状：两卡树同改一个文件 ⇒ 批次树合不上（先在这里点名，零副作用）。
    for index, first in enumerate(cards):
        for second in cards[index + 1:]:
            hit = pool_plan.files_intersect(first, second)
            if not hit:
                continue
            dep = pool_plan.dependency_path(first, second, backlog.cards)
            tail = "（有依赖路径也不行：一批是一笔提交，同文件仍是两个写者）" if dep else ""
            raise BatchPlanError(
                f"批次树冲突：卡 {first.id} 与 {second.id} 同改 "
                f"{'、'.join(sorted(hit))}{tail}")

    if not why:
        why = (f"批 {batch_id}：{len(cards)} 张卡（{'、'.join(ids)}）合成一笔落地 —— "
               f"一次全量门禁、一笔提交、一段文书")
    manifest = manifest_for(batch_id, cards, why, gate_cmd)
    # ★ 判据 3：落盘之前**真跑**一遍栅栏的校验（不是另写一份）。
    pool_task._validate_manifest(manifest, batch_id)

    base_rev = (_git_text(["rev-parse", "HEAD"], env.main).stdout or "").strip()
    if not base_rev:
        raise BatchPlanError(f"算不出主树 HEAD（{env.main}）—— 批次树没基点，停手")
    patches = [(card, export_patch(env.main / card.tree, base_rev, card.id)) for card in cards]
    tree = build_batch_tree(env, batch_id, patches)

    entries = {card.id: _entry_of(env.root, card.task) for card in cards}
    trace_rel = f"docs/traceability.d/{batch_id}.toml"
    trace_path = tree / trace_rel
    _write(trace_path, render_traceability(batch_id, cards, entries))

    manifest_path = env.batch_dir / f"{batch_id}.toml"
    _write(manifest_path, render_manifest(batch_id, cards, why, gate_cmd))
    text_path = env.batch_dir.parent / f"_text_{batch_id.replace('-', '')}.md"
    _write(text_path, render_text_skeleton(batch_id, cards, entries))
    return {"manifest": manifest_path, "text": text_path,
            "traceability": trace_path, "tree": tree, "trace_rel": Path(trace_rel)}


# ================================================================ land
def load_manifest(env: Env, batch_id: str) -> dict:
    """读预声明并**过栅栏的同一套校验**（不合法 ⇒ 拒，不带着坏名单去起门禁）。"""
    path = env.batch_dir / f"{batch_id}.toml"
    if not path.is_file():
        raise BatchPlanError(
            f"批 {batch_id} 没有预声明：{path}（先 `wb_batch.py make {batch_id}`）")
    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    pool_task._validate_manifest(manifest, batch_id)
    return manifest


def land_batch(env: Env, batch_id: str, extra: list[str]) -> int:
    """一条命令走到 `wb_land.py --batch <批号>`；缺省参数由预声明/批次树补齐，`extra` 原样透传。"""
    manifest = load_manifest(env, batch_id)
    state_path = env.batch_dir / f"{batch_id}.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
        if isinstance(state, dict) and state.get("state") == "landed":
            landed = state.get("landed") or {}
            raise BatchPlanError(
                f"批 {batch_id} 已经 landed（commit {landed.get('commit', '?')}）—— 不再落地")
    rel = batch_tree_rel(batch_id)
    tree = env.main / rel
    if not tree.is_dir():
        raise BatchPlanError(f"批次树不存在：{tree}（先 `wb_batch.py make {batch_id}`）")
    members = manifest.get("member") or []
    allow: list[str] = []
    evidence: list[str] = [f"docs/traceability.d/{batch_id}.toml"]
    for member in members:
        for path in member.get("paths") or []:
            path = str(path)
            if path not in allow:
                allow.append(path)
            if path not in evidence:
                evidence.append(path)
    title = " ".join(str(manifest.get("why") or batch_id).split())[:80]
    argv = [
        sys.executable, "-X", "utf8", str(env.root / "tools" / "wb_land.py"),
        "--batch", batch_id, "--tree", rel, "--task", batch_id, "--title", title,
        "--evidence", *evidence, "--allow", *allow,
    ]
    argv += [token for token in extra if token != "--"]
    print(f"[跑 ] {' '.join(argv)}", flush=True)
    done = subprocess.run(
        argv, cwd=str(env.main),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return int(done.returncode)


# ================================================================ 子命令
def cmd_plan(env: Env, args: argparse.Namespace) -> int:
    backlog = load_queue(env.root)
    candidates, skipped = landing_candidates(env, backlog)
    eligible, blocked = eligible_cards(backlog, candidates)
    groups = pack_landing_batches(backlog, eligible)
    notes = overlap_notes(backlog, eligible, groups)
    print(render_plan_output(groups, eligible, blocked, skipped, notes))
    return 0


def cmd_make(env: Env, args: argparse.Namespace) -> int:
    written = make_batch(env, args.batch, args.cards, why=args.why, gate_cmd=args.gate_cmd)
    print(f"[写 ] 预声明：{written['manifest']}")
    print(f"[写 ] 三段文书骨架：{written['text']}")
    print(f"[写 ] 台账证据并集：{written['traceability']}")
    print(f"[树 ] 批次树：{written['tree']}（git apply --3way 合了成员补丁）")
    print(f"[下 ] 落地：python -X utf8 tools/wb_batch.py land {args.batch} "
          f"--port-base 9034  # 其余参数透传 wb_land.py")
    return 0


def cmd_land(env: Env, args: argparse.Namespace) -> int:
    return land_batch(env, args.batch, args.rest)


def build_parser() -> argparse.ArgumentParser:
    """三个入口的关系写在 `--help` 里（判据 1）：plan 只读 / make 写盘 / land 起门禁。"""
    parser = argparse.ArgumentParser(
        prog="wb_batch.py",
        description="批次并入派活链：plan（只读挑成员）→ make（写盘生成）→ land（起门禁落地）",
        epilog=(
            "三者关系：\n"
            "  plan  只读，不改任何文件；给 make 挑成员（文件不相交 / 依赖已满足 / ≤4）\n"
            "  make  写盘：预声明的栅栏清单 + 三方文书骨架 + 台账证据并集 + "
            "批次树（.wt/batch<号>）\n"
            "  land  起门禁：转发 `wb_land.py --batch <批号>`（参数透传）\n"
            "★ 批仍要人显式说：make + land 两步都由人敲；派活侧只提供入口。\n"
            f"★ {LIMIT_WHY}。"),
    )
    parser.add_argument("--root", default="", help="队列所在的树（默认 = 本文件所在的树）")
    parser.add_argument("--main", default="", help="主工作树（默认从 git 算）")
    parser.add_argument("--batch-dir", default="",
                        help="预声明目录（默认主树 gates/diag/batch；测试用）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan", help="只读：从队列取待落卡，算候选批（打印成员/文件/预计省时）")
    plan.set_defaults(func=cmd_plan)

    make = sub.add_parser("make", help="写盘：生成预声明 + 三方文书骨架 + 台账证据并集 + 批次树")
    make.add_argument("batch", help="批号（如 T-AG461；批次树落在 .wt/batch<号>）")
    make.add_argument("--cards", nargs="+", default=None,
                      help="成员卡号（不给 = 用 plan 算出的第一批）")
    make.add_argument("--why", default="", help="这一批要干成什么（预声明里的 why）")
    make.add_argument("--gate-cmd", default=GATE_CMD, help=f"集齐后跑的门禁（默认 {GATE_CMD}）")
    make.set_defaults(func=cmd_make)

    land = sub.add_parser("land", help="起门禁：走到 wb_land.py --batch <批号>（参数透传）")
    land.add_argument("batch", help="批号")
    land.add_argument("rest", nargs=argparse.REMAINDER,
                      help="原样透传给 wb_land.py（如 --port-base 9034 --evidence … --allow …）")
    land.set_defaults(func=cmd_land)
    return parser


def _env_from(args: argparse.Namespace) -> Env:
    root = Path(args.root).resolve() if args.root else ROOT
    main = Path(args.main).resolve() if args.main else main_tree_root()
    batch_dir = (Path(args.batch_dir).resolve() if args.batch_dir
                 else main / "gates" / "diag" / "batch")
    return Env(root=root, main=main, batch_dir=batch_dir)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = _env_from(args)
    try:
        return int(args.func(env, args))
    except (BatchPlanError, pool_plan.BacklogError, pool_task.BatchError) as exc:
        print(f"✗ {type(exc).__name__}：{exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
