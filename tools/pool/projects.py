r"""项目索引（`infra/pool/projects.toml`）的只读读取 + 三条硬判据（卡 120 · T-G232）。

**防什么**：号池 / 派活 / MCP 是**通用层**（跨项目复用），但记忆与规矩是**项目层**。
要让"通用设施服务多个项目"，先得有一张**项目索引**回答"哪些项目、根在哪、记忆入口是啥、
允许派到哪些树"。索引自己没守卫 ⇒ 它会变成新的漂移点，所以这里把三条硬判据**机器化**：

1. **每个项目的 `root` 必须真实存在** —— 宁可拒绝，**不许凭空写路径**（不存在 ⇒ 抛错并点名）；
2. **两个项目不许同一个 `root`** —— 撞了 ⇒ 抛错并**点名两个名字**；
3. **`tree_prefixes` 非空** —— 空的树前缀 = "哪儿都能派" = 没有守卫（⇒ 抛错并点名）。

★ 号池目录**不在本仓**（跨项目复用，在 `jelly_ware/` 下）—— 从本树起**逐级向上**找
`<祖先>/infra/pool/projects.toml`（与 `pool.models.find_pool_dir` 同一手法）；
`TF_PROJECTS_TOML` 可覆盖（测试用临时索引）。★ **找不到 ⇒ 抛错，不猜路径**。

★ 边界（如实写）：本模块**只读**索引 —— 不写、不改、不新增项目（索引只有用户能改）；
也不发现 / 推断"某个项目的记忆入口是哪几份"（`memory_entries` 只**照索引打印**）。
"""

from __future__ import annotations

try:
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root
    except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
        pipe_root = None  # type: ignore[assignment]

import os
import pathlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 索引在号池目录里的相对位置（用它从祖先起定位号池目录）。
INDEX_ANCHOR = ("infra", "pool", "projects.toml")


class ProjectsError(Exception):
    """索引读不了 / 索引本身违规（缺根 / 根不存在 / 两根相撞 / 前缀空）—— 环境或数据坏了。"""


# ================================================================ 定位 / 归一


def _norm(value: object) -> str:
    """路径归一：反斜杠 → 正斜杠、去首尾空白与尾部斜杠（比较用，不碰文件系统）。"""
    return str(value or "").strip().replace("\\", "/").rstrip("/")


def tree_root() -> Path:
    """本文件所在的仓库树（`tools/pool/projects.py` 的上三级）。

    ★ 卡树里回的是**卡树**、主树里回的是主树 —— 反查"主树属于哪个项目"时只问它是不是某
      项目根的**后代**，两种情形都对（见 `find_by_tree`）。
    """
    if pipe_root is None:  # pragma: no cover —— 独立拷贝的树
        return pathlib.Path(__file__).resolve().parents[2]
    return pipe_root.data_root()


def index_path() -> Path:
    """索引文件：`TF_PROJECTS_TOML` 覆盖；否则从本树逐级向上找；找不到 ⇒ 抛错（不猜）。"""
    override = os.environ.get("TF_PROJECTS_TOML", "").strip()
    if override:
        return Path(override)
    base = tree_root()
    for root in (base, *base.parents):
        candidate = root / INDEX_ANCHOR[0] / INDEX_ANCHOR[1] / INDEX_ANCHOR[2]
        if candidate.exists():
            return candidate
    raise ProjectsError(
        f"找不到项目索引（不许猜路径）：从 {base} 起逐级向上都没有 "
        f"{'/'.join(INDEX_ANCHOR)}；用 TF_PROJECTS_TOML 指一份")


# ================================================================ 读 / 校验


def _str_list(value: object) -> list[str]:
    """任意可迭代 → 去空白、保序、非空的字符串列表（认不出 ⇒ 空列表）。"""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _validate(entries: list[dict[str, Any]], where: Path) -> None:
    """三条硬判据 —— 一条不过就抛错并**点名**（谁 / 哪儿）。"""
    by_root: dict[str, str] = {}
    for entry in entries:
        name = entry["id"]
        if not entry["root"]:
            raise ProjectsError(f"项目 {name} 缺 `root`（不许凭空写路径）：{where}")
        root = Path(entry["root"])
        if not root.is_dir():
            raise ProjectsError(
                f"项目 {name} 的 `root` 不存在：{entry['root']}（宁拒不许猜）：{where}")
        key = _norm(root.resolve())
        if key in by_root:
            raise ProjectsError(
                f"两个项目指向同一个 root：{by_root[key]} 与 {name} 都是 {entry['root']}"
                f"（撞了不许派活）：{where}")
        by_root[key] = name
        if not entry["tree_prefixes"]:
            raise ProjectsError(
                f"项目 {name} 的 `tree_prefixes` 是空的"
                f"（空的树前缀 = 哪儿都能派 = 没有守卫）：{where}")


def load(path: Path | str | None = None) -> list[dict[str, Any]]:
    """读**全部**项目并逐条校验三条硬判据（不过 ⇒ `ProjectsError`）。

    每个条目归一成统一形状：`id / name / root（正斜杠）/ memory / layers / tree_prefixes /
    queue / ledger / cards`。索引里没有 `[project]` 段 ⇒ 回空列表（还没登记任何项目）。
    """
    target = Path(path) if path is not None else index_path()
    if not target.exists():
        raise ProjectsError(f"项目索引不存在：{target}（不许猜路径）")
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectsError(f"项目索引读不了：{target}（{exc}）") from exc
    raw = data.get("project") or {}
    if not isinstance(raw, dict):
        raise ProjectsError(f"项目索引结构不对（`[project.<名>]` 应是表）：{target}")
    entries: list[dict[str, Any]] = []
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ProjectsError(f"项目 {name} 的条目不是表：{target}")
        entries.append({
            "id": str(name),
            "name": str(body.get("name") or name),
            "root": _norm(body.get("root")),
            "memory": _str_list(body.get("memory")),
            "layers": _str_list(body.get("layers")),
            "tree_prefixes": _str_list(body.get("tree_prefixes")),
            "queue": str(body.get("queue") or ""),
            "ledger": str(body.get("ledger") or ""),
            "cards": str(body.get("cards") or ""),
        })
    _validate(entries, target)
    return entries


def get(name: object, *, rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """按项目名取条目；**没登记过 → `None`**（存在性即授权，由调用方拒）。"""
    want = str(name or "").strip()
    entries = load() if rows is None else rows
    for entry in entries:
        if entry["id"] == want:
            return entry
    return None


# ================================================================ 树 / 记忆


def under_prefix(rel_tree: object, prefixes: Iterable[str]) -> bool:
    """`rel_tree`（相对主树根）是否落在某个树前缀里（前后缀按 `/` 边界判，不误吞同名前缀）。"""
    tree = _norm(rel_tree)
    for raw in prefixes:
        prefix = _norm(raw)
        if not prefix:
            continue
        if tree == prefix or tree.startswith(prefix + "/"):
            return True
    return False


def _is_ancestor(root: Path, here: Path) -> bool:
    """`root` 是 `here` 本身或它的祖先吗（用 realpath 比，认不出 ⇒ False）。"""
    try:
        root_r, here_r = root.resolve(), here.resolve()
    except OSError:
        return False
    return root_r == here_r or root_r in here_r.parents


def find_by_tree(rel_tree: object, *, rows: list[dict[str, Any]] | None = None) -> str | None:
    """反查：这棵树属于哪个**已登记**项目（没有 → `None`）。

    - `rel_tree == ""`（主树）：找 `root` 是**本仓库树祖先**的那个项目
      （卡树 = 主树的后代，也落在这条上）；
    - 否则：找某个项目的 `tree_prefixes` 命中的那个。

    ★ 反查不到**不是**"猜一个"，就是 `None`（调用方据此拒）。
    """
    entries = load() if rows is None else rows
    tree = _norm(rel_tree)
    if tree == "":
        here = tree_root()
        for entry in entries:
            if _is_ancestor(Path(entry["root"]), here):
                return entry["id"]
        return None
    for entry in entries:
        if under_prefix(tree, entry["tree_prefixes"]):
            return entry["id"]
    return None


def memory_entries(name: object, *, rows: list[dict[str, Any]] | None = None) -> list[str]:
    """该项目的**最小记忆入口**（照索引里的 `memory` 列表**原样打印**）。

    ★ 本模块**不新增、不改、不推断** `memory` —— 哪个项目读哪几份只有用户知道。
    没登记过的项目 ⇒ `ProjectsError`（不静默回空）。
    """
    entries = load() if rows is None else rows
    entry = get(name, rows=entries)
    if entry is None:
        known = "、".join(e["id"] for e in entries) or "（一个都没登记）"
        raise ProjectsError(f"没登记过的项目：{str(name or '').strip()}（已登记：{known}）")
    return list(entry["memory"])


__all__ = [
    "INDEX_ANCHOR", "ProjectsError", "find_by_tree", "get", "index_path", "load",
    "memory_entries", "tree_root", "under_prefix",
]
