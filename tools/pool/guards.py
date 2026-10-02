r"""自家守卫 —— **纯函数**：吃数据 → 回 `list[str]` 问题。

**防什么**：写面（派活 / 取消）动手前要能回答「这棵树 / 这个冲突域 / 这趟门禁 / **这个项目**，
现在能不能碰」。这里守卫只吃**已经读好的数据**（租约表 / 锁的原文 / 只读项目索引），
回一串人话问题：**不写文件、不 print、不起进程** —— 所以既好测，也能被写面（卡 110）直接复用，
不会变成第二份真源。

**哪几条是我判的**：
- `tree_guard`   —— 一棵树同时只能有一个活租约（主树尤其）。
- `domain_guard` —— 冲突域与任何活租约**相交**就拒，并**点名相交的文件**（相交判据直接用
  `pool.plan.files_intersect`，不另写一份 —— 本仓最忌两份真源）。
- `lock_guard`   —— 门禁锁的原文里，若有锁的 `card` = 本卡 **或** `cwd` 指向本树 ⇒ 拒
  （"这趟门禁还在跑，别动手"）。解析在 `pool.locks.parse_entries`。
- `project_guard` —— **项目守卫（卡 120 · T-G232）**：没登记过的项目 / 树不落在该项目
  `tree_prefixes` 里 / 反查不到 ⇒ 拒。数据来自**只读**的 `pool.projects` 索引。

**哪三条是别人判的（本模块明确"委托"，重写就是第三份真源）**：
- **内存闸** —— `tools/wb_dispatch.py` 的前置检查（`TF_GATE_MIN_FREE_GB`）是唯一实现；
  本模块**没有**任何内存闸函数（测试 `test_pool_guards.py` 钉住这一点）。
- **日志不许覆盖** —— `wb_dispatch` 自己会挑 `wb-<卡>.r2.jsonl` 这种新名字，且写面**不许**给
  `--force`；本模块只加一条最朴素的 `log_guard(path)`：目标已存在 ⇒ 拒。
- **模型白名单** —— `wb_dispatch.MODEL_WHITELIST` 的硬闸门 + `pool.models` 的批准集。

★ 关于时间：`now` 是"现在"（epoch 秒）。守卫只按**租约**判活（`now - at > ttl_seconds` 算死）；
  日志层面的"断了 / 已判决"由 `registry`（有 IO 的那一层）先清一遍再把活的租约递进来 ——
  所以守卫**不 import registry**（不然成环），也不做任何 IO。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pool import locks as pool_locks
from pool import projects as pool_projects
from pool.plan import Card, files_intersect

if TYPE_CHECKING:
    from collections.abc import Iterable


def _norm(path: object) -> str:
    """路径归一：反斜杠 → 正斜杠、去首尾空白与尾部斜杠（比较用，不碰文件系统）。"""
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def _started_at(value: object) -> float | None:
    """把租约的 `at`（ISO8601）转成 epoch 秒；认不出 → `None`（**保守当活**）。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _is_live(reservation: dict, now: float | None) -> bool:
    """这条租约还算活吗 —— 只按 TTL（日志层面的死租约由 registry 先清）。

    ★ 认不出来的输入一律**保守当活**：宁可多拦一次（人会再 release），也别默默放行一个占着树
      的写者。`now is None` 或 `ttl_seconds` 缺失/非数 → 不当死。
    """
    if now is None:
        return True
    ttl = reservation.get("ttl_seconds")
    started = _started_at(reservation.get("at"))
    if not isinstance(ttl, (int, float)) or started is None:
        return True
    return (now - started) <= float(ttl)


def _as_card(card_id: object, files: object) -> Card:
    """把"一串冲突域"包成 `plan.Card`，好把相交判据交给现成的 `files_intersect`。"""
    rows = [str(item) for item in files] if isinstance(files, (list, tuple)) else []
    return Card(id=str(card_id), task="", title="", tree="", spec="", files=tuple(rows))


def _tree_label(tree: object) -> str:
    return _norm(tree) or "（主树）"


# ================================================================ 守卫① 树


def tree_guard(tree: object, reservations: Iterable[dict], now: float | None = None) -> list[str]:
    """一棵树同时只能有一个活租约（主树尤其）—— 空列表 = 没被咬。"""
    want = _norm(tree)
    problems: list[str] = []
    for res in reservations:
        if not _is_live(res, now):
            continue
        if _norm(res.get("tree")) == want:
            problems.append(
                f"树被占：{_tree_label(tree)} 上已有活租约（卡 {res.get('card')}，"
                f"owner={res.get('owner') or '?'}）—— 一棵树同时只能一个写者")
    return problems


# ================================================================ 守卫② 冲突域


def domain_guard(files: Iterable[str], reservations: Iterable[dict],
                 now: float | None = None) -> list[str]:
    """冲突域与任何活租约**相交**就拒，并**点名相交的文件**（空列表 = 没被咬）。

    ★ 空域 = 不与任何东西相交 = 绕过这条守卫 —— 所以调用方（CLI）**不许把查不到的卡猜成空域**。
    """
    request = _as_card("?", list(files))
    problems: list[str] = []
    for res in reservations:
        if not _is_live(res, now):
            continue
        hit = files_intersect(request, _as_card(res.get("card"), res.get("files") or []))
        if hit:
            problems.append(
                f"冲突域相交：与活租约卡 {res.get('card')}（树 {_tree_label(res.get('tree'))}）"
                f"相交文件 {sorted(hit)} —— 同一文件不许两个写者")
    return problems


# ================================================================ 守卫③ 门禁锁


def _cwd_is_tree(cwd: object, tree: object, root: object) -> bool:
    """锁的 `cwd` 是不是指向要占的那棵树。"""
    got = _norm(cwd)
    if not got:
        return False
    if root is not None:
        want = _norm(str(Path(str(root)) / str(tree))) if _norm(tree) else _norm(root)
        return bool(want) and got == want
    # 没有 root 时退化成后缀匹配（保守：只在树名非空时才可能命中）
    name = _norm(tree)
    return bool(name) and (got == name or got.endswith("/" + name))


def lock_guard(card: object, tree: object, lock_body: str,
               *, root: object = None) -> list[str]:
    """门禁锁在跑吗 —— 锁的 `card` = 本卡，**或** `cwd` 指向本树 ⇒ 拒。

    `root` 给定时，`tree` 按"相对 root"解析后与 `cwd` **精确**比较（推荐）；
    不给 `root` 则退化成后缀匹配。`lock_body` 就是 `gate_lock.py status` 的原文
    （`pool.locks.status_argv()` 跑出来的那段）。
    """
    problems: list[str] = []
    for entry in pool_locks.parse_entries(lock_body or ""):
        base, held, pid = entry["base"], entry["card"], entry["pid"]
        if held == str(card):
            problems.append(
                f"这趟门禁还在跑：锁的 card={held}（段 base={base}，pid={pid}）就是本卡 —— 别动手")
            continue
        if _cwd_is_tree(entry.get("cwd"), tree, root):
            problems.append(
                f"这趟门禁还在跑：锁的 cwd={entry.get('cwd')} 指向本树（段 base={base}，"
                f"card={held}）—— 别动手")
    return problems


# ================================================================ 守卫④（最朴素的一条）日志


def log_guard(path: object) -> list[str]:
    """日志不许覆盖：目标已存在 ⇒ 拒（写面**不许**给 `--force`）。

    ★ 真正的"每轮换个新名字"（`wb-<卡>.r2.jsonl`）是 `wb_dispatch` 自己判的（委托），
      这里只把最朴素的那条（"不许盖"）摆出来。
    """
    if not str(path or "").strip():
        return []
    if Path(str(path)).exists():
        return [f"日志不许覆盖：{path} 已存在 —— 换一个新名字（写面不给 --force）"]
    return []


# ================================================================ 守卫⑤ 项目（卡 120 · T-G232）


def project_guard(tree_rel: object, project: object = None) -> list[str]:
    """项目守卫：**没登记的项目 / 树越界 / 反查不到 ⇒ 拒**（空列表 = 没被咬）。

    ★ 与 `pool.projects` 的三条硬判据配套（存在性即授权，和 MCP 写面同一个思路）：
      ① **没登记过的项目不许派活**（点名已登记的有哪些）；
      ② `tree` 必须落在该项目 `tree_prefixes` 里，越界 ⇒ 拒并**点名允许哪些前缀**；
      ③ 不给 `project` ⇒ 用 `projects.find_by_tree` **反查**；反查不到 ⇒ 拒
         （"这棵树不属于任何已登记项目"）。
    ★ 主树（`tree_rel == ""`）= **项目根本身** ⇒ 放行 —— 它就是这个项目；"越界"的定义是
      "落在本项目的树前缀之外"，不是"不是主树"。
    ★ 索引读不了（找不到 / 本身违规）⇒ **拒**（不猜、不放过）。
    ★ 该函数只**读**只读索引（不写 / 不 print / 不起进程）：问题是返回值，不是异常；
      与同模块另三条同一风格（吃数据 / 回 `list[str]`，只是这条的数据在只读索引里）。
    """
    try:
        entries = pool_projects.load()
    except pool_projects.ProjectsError as exc:
        return [f"项目索引读不了（项目守卫判不了）：{exc}"]
    tree = _norm(tree_rel)
    name = str(project).strip() if project is not None else ""
    if not name:
        found = pool_projects.find_by_tree(tree, rows=entries)
        if not found:
            return [f"这棵树不属于任何已登记项目：{_tree_label(tree)}"
                    f" —— 没登记的树不许派活（先把它登记进项目索引）"]
        name = found
    entry = pool_projects.get(name, rows=entries)
    if entry is None:
        known = "、".join(row["id"] for row in entries) or "（一个都没登记）"
        return [f"没登记过的项目不许派活：{name}（已登记：{known}）"]
    if tree == "":
        owner = pool_projects.find_by_tree("", rows=entries)
        if owner is None or owner == name:
            return []
        return [f"树越界：主树属于项目 {owner}，不是 {name}"]
    if pool_projects.under_prefix(tree, entry["tree_prefixes"]):
        return []
    return [f"树越界：{_tree_label(tree)} 不落在项目 {name} 的树前缀里"
            f"（允许：{'、'.join(entry['tree_prefixes'])}）"]


__all__ = ["domain_guard", "lock_guard", "log_guard", "project_guard", "tree_guard"]
