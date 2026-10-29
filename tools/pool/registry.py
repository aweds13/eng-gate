r"""作业登记：谁占了哪棵树 / 哪个冲突域 —— 全窗口共用一份（卡 108 · T-G205）。

**防什么**：写面（派活 / 取消）的第一块地基不是 MCP，而是「**谁占了哪棵树 / 哪个冲突域**」。
从前**没有任何地方记着这件事**：两个窗口各派一张卡进同一棵树，双方都不知道（真发生过：卡 100 /
102 的工人**跑进主树**里改东西，见 `复盘/口径坑.md` 坑 20）。这里把租约登记成一份 JSON，
让「先查再占」成为可能。

**登记位置 = 主工作树的 `gates/diag/pool-registry.json`**（**全窗口共用一份**）。
- ★ 怎么找主树：`git rev-parse --git-common-dir` → 它的**父目录**就是主工作树根。
- ★★ **不许**用 `git rev-parse --show-toplevel` 代替：那在卡树里回的是**卡树**（卡树里也有
  `gates/diag/`，而且是 gitignore 的），写进去就等于没写。
- 允许环境变量 `TF_POOL_REGISTRY` 覆盖（测试与"换一台机器"要用）。

**原子写**：选「同目录 `tmp` + `os.replace`」。理由：`os.replace` 在**同一文件系统**上是原子的 ——
读者要么看到**旧的整份**、要么看到**新的整份**，绝不会读到写了一半的半截 JSON（并发窗口读时不会
`json.JSONDecodeError`）；把 `tmp` 放在同一目录就保证是同一文件系统（跨盘的 `os.replace` 不原子）。

**坏文件不静默清空**：读到坏 JSON → 抛 `RegistryError`，**不动**原文件。
（在「报错」与「备份」里**选报错**：坏文件原封不动留在原地，人来修时看得见全貌，比悄悄搬走更好定位。）

**边界（如实写）**：
- ★ 本模块**不登记 pid**，判活只用「租约 + 日志」。
- ★★ **绝对不许用 `os.kill(pid, 0)` 探活**：Windows 上 CPython 的 `os.kill` 走 `TerminateProcess`
  —— 那不是探活，那是**把真在跑的进程杀掉**。所以这里连 pid 都不记。
- **死租约判据** = ① `now - at > ttl_seconds`，**或** ② 该卡的作业日志已被判「断了 / 已判决」
  （复用 `tools/pool/jobs.py` 的 `scan_jobs` / `classify_job_state`，**不另写一套**）。
- 本模块只做**登记**：不派活、不跑门禁、不 import `wb_dispatch`（派活是卡 109 / 110）。
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pool import guards, jobs, lastgood, projects
from pool import locks as pool_locks

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: 租约默认活多久（秒）—— 6 小时，够一张卡连跑几趟门禁。
DEFAULT_TTL = 21600

#: 登记文件的相对位置（相对主工作树根）。
REGISTRY_REL = ("gates", "diag", "pool-registry.json")

#: 判"断了 / 已判决"用的两态（其余态 = 还活着）。
_DEAD_STATES = ("断了", "已判决")


class RegistryError(Exception):
    """登记文件读不了 / 算不出主树 —— 环境或文件坏了（与"守卫咬"分开）。"""


class GuardError(Exception):
    """守卫拦下了这条租约 —— `problems` 里逐条点名。"""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


# ================================================================ 主树定位 / 登记路径


def main_tree_root() -> Path:
    """主工作树根 = `git rev-parse --git-common-dir` 的**父目录**。

    ★ 卡树里 `--git-common-dir` 回的是主仓的 `.git`（如 `D:/.../engineering/.git`），父目录就是
      主工作树；而 `--show-toplevel` 会回卡树本身 —— 所以只用前者。

    ★ 卡 114（T-G211）：这次 `git` 必须显式给 `cwd=` —— 服务可能被别的程序（如 DSH 起
      MCP 子进程）从**任意 cwd** 拉起，那是进程 cwd、不在仓库里，git 会报错、算不出主树。
      这里用**从本文件推出来的仓库根**（`tools/pool/registry.py` 的上三级）：存在就给它，
      取不到（被拆散 / 装包了）才退回 `None`（保持旧行为：走进程 cwd）。卡树里那个根 =
      卡树，它同样是 git 工作树 ⇒ `--git-common-dir` 照样回主仓的 `.git` ⇒ 父目录仍是
      主工作树（卡 108 设计的语义不变）。

    ★★ 卡 117（T-G215）：`--git-common-dir` 回的可能是**相对路径** —— 在**主工作树根**
      里跑 git 时它回 `.git`（在卡树 / 子目录里跑才回绝对路径）。相对路径相对的是
      **"给 git 的那个 cwd"**（即这里的 `tree_root`），**不是进程 cwd**。老写法用
      `Path.cwd()` 解析 ⇒ 进程 cwd 一旦不是仓库根（卡 114 那条钉子的场景、DSH 起 MCP
      子进程也一样），主工作树就被算成 `<进程 cwd>/gates/diag/…`（主树里实测就这么错的）。
      所以这里按 `git_cwd` 解析；只有拿不到 `git_cwd`（被拆散 / 装包了）才退回 `Path.cwd()`。
    """
    tree_root = Path(__file__).resolve().parents[2]
    git_cwd = tree_root if tree_root.is_dir() else None
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(git_cwd) if git_cwd is not None else None,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise RegistryError(f"算不出主工作树（跑不了 git：{exc}）") from exc
    raw = (done.stdout or "").strip()
    if done.returncode or not raw:
        raise RegistryError("算不出主工作树：`git rev-parse --git-common-dir` 没回路径")
    common = Path(raw)
    if not common.is_absolute():
        # ★ 相对路径相对的是**给 git 的那个 cwd**（`git_cwd`），不是进程 cwd（卡 117）。
        common = (git_cwd or Path.cwd()) / common
    return common.resolve().parent


def registry_path() -> Path:
    """登记文件的真实路径：`TF_POOL_REGISTRY` 若设了就用它，否则主树下的 `gates/diag/…`。"""
    override = os.environ.get("TF_POOL_REGISTRY", "").strip()
    if override:
        return Path(override)
    return main_tree_root() / Path(*REGISTRY_REL)


def default_owner() -> str:
    """这条租约的 owner（窗口）：`TF_WINDOW_ID`，没有就 `<hostname>:<pid>`。"""
    window = os.environ.get("TF_WINDOW_ID", "").strip()
    if window:
        return window
    return f"{socket.gethostname()}:{os.getpid()}"


# ================================================================ 读 / 写（原子）


def _validate_registry_text(text: str) -> None:
    """判「这份登记还能不能当 lastgood」：能解析且顶层是数组（卡 A330）。

    ★ 把 `json.JSONDecodeError` 归一成 `ValueError`：后者能被单参复刻，兜底失败时才能
    把「`.bak` 也坏了」拼进消息里而不丢异常类型（`JSONDecodeError` 要三个参数）。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, list):
        raise RegistryError("登记文件结构不对（顶层应是数组）")


def load(path: Path | str | None = None) -> list[dict]:
    """读登记文件的全部条目；文件不存在 → `[]`；**坏文件 → 抛错，不清空**。

    冷启动读到坏文件时先读 `.bak`（卡 A330 / magpie F77 的 `internal/lastgood`）：恢复会往
    stderr 打一行；两边都坏才抛 `RegistryError`，消息里写明 `.bak` 也坏了。坏文件一个字都不动。
    """
    target = Path(path) if path is not None else registry_path()
    if not target.exists() and not lastgood.backup_path(target).exists():
        return []
    if target.exists() and not target.read_text(encoding="utf-8").strip():
        return []  # 旧语义：空文件当空账（空 ≠ 坏，不走兜底）
    try:
        text, _recovered = lastgood.read_with_fallback(
            target,
            validate=_validate_registry_text,
            log=lambda msg: print(msg, file=sys.stderr),
        )
    except RegistryError:
        raise  # 结构不对 / 两边都坏 —— 消息里已带 `.bak` 的实情
    except Exception as exc:
        raise RegistryError(
            f"登记文件坏了，**不清空**：{target}（{exc}）—— 请人工修好或删掉再重试") from exc
    data = json.loads(text)
    return [row for row in data if isinstance(row, dict)]


def save(reservations: Iterable[dict], path: Path | str | None = None) -> Path:
    """原子落盘：旧的好就先顶成 `.bak`，再同目录 `tmp` + `os.replace`。返回真实路径。"""
    target = Path(path) if path is not None else registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(list(reservations), ensure_ascii=False, indent=2) + "\n"
    lastgood.write_atomic(target, body, validate=_validate_registry_text)
    return target


# ================================================================ 死租约判据


def _started_at(value: object) -> float | None:
    """租约的 `at`（ISO8601 或 epoch）→ epoch 秒；认不出 → `None`。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _log_dead(reservation: dict, now: float, log_base: Callable[[], Path]) -> bool:
    """这条租约的日志被判「断了 / 已判决」了吗（复用 `jobs.scan_jobs`，不另写一套）。"""
    raw = str(reservation.get("log") or "").strip()
    if not raw:
        return False
    log_path = Path(raw)
    if not log_path.is_absolute():
        log_path = log_base() / log_path
    if not log_path.exists():
        return False
    for row in jobs.scan_jobs(log_path.parent, now=now):
        if row["log"] == log_path.name:
            return row["state"] in _DEAD_STATES
    return False


def is_dead(reservation: dict, now: float, *, log_base: Callable[[], Path]) -> bool:
    """死租约判据：TTL 过期 **或** 日志判死（两个都要问）。"""
    ttl = reservation.get("ttl_seconds")
    started = _started_at(reservation.get("at"))
    if isinstance(ttl, (int, float)) and started is not None and (now - started) > float(ttl):
        return True
    return _log_dead(reservation, now, log_base)


def _log_base_for(path: Path) -> Callable[[], Path]:
    """相对日志路径按主树根解析（延迟到真要用了才跑 git）。"""
    def resolve() -> Path:
        try:
            return main_tree_root()
        except RegistryError:
            return path.resolve().parent
    return resolve


def _log_probe(log: object, log_base: Callable[[], Path]) -> Path | None:
    """把租约里的 `log`（相对路径）解析成绝对路径；没给 → `None`。"""
    raw = str(log or "").strip()
    if not raw:
        return None
    probe = Path(raw)
    return probe if probe.is_absolute() else log_base() / probe


# ================================================================ 登记 / 释放 / 列 / 清


def list_reservations(now: float | None = None, path: Path | str | None = None) -> list[dict]:
    """列**活**租约（死的不出现，但不落盘 —— 只读）。"""
    target = Path(path) if path is not None else registry_path()
    stamp = time.time() if now is None else now
    log_base = _log_base_for(target)
    return [row for row in load(target) if not is_dead(row, stamp, log_base=log_base)]


def prune(now: float | None = None, path: Path | str | None = None) -> int:
    """清死租约并落盘；返回清掉几条（没死的原样保留，没死就**不写**）。"""
    target = Path(path) if path is not None else registry_path()
    stamp = time.time() if now is None else now
    log_base = _log_base_for(target)
    rows = load(target)
    live = [row for row in rows if not is_dead(row, stamp, log_base=log_base)]
    removed = len(rows) - len(live)
    if removed:
        save(live, target)
    return removed


def _lock_root(path: Path) -> Path:
    """给 `lock_guard` 用的仓库根：登记文件住在 `<root>/gates/diag/` 时取上两级。"""
    resolved = path.resolve()
    if resolved.name == "pool-registry.json" and len(resolved.parents) >= 3:
        return resolved.parents[2]
    try:
        return main_tree_root()
    except RegistryError:
        return resolved.parent


def read_lock_body(path: Path | str | None = None) -> str:
    """跑一次 `gate_lock.py status`（**只读**）拿锁的原文；跑不了 → 空串（不编造）。"""
    root = _lock_root(Path(path)) if path is not None else _lock_root(registry_path())
    try:
        done = subprocess.run(
            pool_locks.status_argv(), cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return ""
    return (done.stdout or "") + (done.stderr or "")


def _resolve_project(tree: str, project: str) -> str:
    """租约的 `project`（卡 120）：显式给的优先；没给就按树**反查**（查不到 ⇒ 空，不猜）。

    ★ `project` 是**附注**（"这棵树属于谁"），不是放行判据 —— 所以索引读不了时**留空**，
      不因此拖垮登记（守卫该咬的地方在 `pool.guards.project_guard`）。
    """
    if str(project).strip():
        return str(project).strip()
    try:
        return projects.find_by_tree(tree) or ""
    except projects.ProjectsError:
        return ""


def reserve(card: str, *, task: str = "", tree: str = "", files: Iterable[str] = (),
            project: str = "", pool: str = "", model: str = "", log: str = "", note: str = "",
            owner: str | None = None, ttl_seconds: float = DEFAULT_TTL,
            now: float | None = None, path: Path | str | None = None,
            lock_body: str | None = None) -> dict:
    """登记一条租约：**先读全部 → 清死租约 → 过守卫 → 再落盘**（原子）。

    过的守卫 = 树（`tree_guard`）+ 冲突域（`domain_guard`）+ 门禁锁（`lock_guard`）
    + 日志不许覆盖（`log_guard`，给了 `log` 才查）。
    ★ 卡 120：租约里记下 `project`（占树时定下来）—— 不给则按 `tree` 反查（`_resolve_project`）。
    守卫咬 → `GuardError`（`problems` 逐条点名）；环境 / 文件坏 → `RegistryError`；
    两者都**不落盘**。`lock_body` 不给就现跑一次 `gate_lock.py status`。
    """
    target = Path(path) if path is not None else registry_path()
    stamp = time.time() if now is None else now
    log_base = _log_base_for(target)

    rows = load(target)                                    # 坏文件 → 这里就抛，绝不覆盖
    live = [row for row in rows if not is_dead(row, stamp, log_base=log_base)]
    body = lock_body if lock_body is not None else read_lock_body(target)
    probe = _log_probe(log, log_base)
    problems = [
        *guards.tree_guard(tree, live, stamp),
        *guards.domain_guard(files, live, stamp),
        *guards.lock_guard(card, tree, body, root=_lock_root(target)),
        *(guards.log_guard(probe) if probe is not None else []),
    ]
    if problems:
        raise GuardError(problems)

    entry = {
        "card": str(card),
        "task": str(task),
        "tree": str(tree),
        "files": [str(item) for item in files],
        "project": _resolve_project(str(tree), project),
        "pool": str(pool),
        "model": str(model),
        "log": str(log),
        "owner": owner or default_owner(),
        "at": datetime.datetime.fromtimestamp(stamp).isoformat(timespec="seconds"),
        "ttl_seconds": float(ttl_seconds),
        "note": str(note),
    }
    save([*live, entry], target)
    return entry


def release(card: str, path: Path | str | None = None) -> bool:
    """放掉这张卡的租约（活的死的都清）；返回是否真删掉了东西。"""
    target = Path(path) if path is not None else registry_path()
    rows = load(target)
    kept = [row for row in rows if str(row.get("card")) != str(card)]
    if len(kept) == len(rows):
        return False
    save(kept, target)
    return True


__all__ = [
    "DEFAULT_TTL", "REGISTRY_REL", "GuardError", "RegistryError",
    "default_owner", "is_dead", "list_reservations", "load", "main_tree_root",
    "prune", "read_lock_body", "registry_path", "release", "reserve", "save",
]
