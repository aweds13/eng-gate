#!/usr/bin/env python
r"""`.wt` 工作树清理器 —— **带判据、默认只看不删**（外包卡 081 · 台账号 `T-G176`）。

为什么有它（卡 081 §0）
----------------------
树是按 `git worktree add .wt/<卡> <底座>` 建的（`tools/wb_plan.py:387`），**卡做完没人收**
→ 只增不减（现测：主树 + 82 棵 = 83 个 worktree、`.wt` 合计 1.48 GB）。肉眼看"哪棵能删"
很危险（`.wt/traegate`、`.wt/vis` 就还有未提交改动）→ 要一台**带判据的机器**，而且
**默认只看不删**：干活的这台机器只**说**哪些可删，真删由主控看完表再决定。

七条判据（★ **全部成立**才算"可删"；任何一条不确定 → **保留**并在表里写原因）
----------------------------------------------------------------------------
  1. 路径在 `<仓库根>/.wt/` 下，且不是主树、不是当前工作树（`git rev-parse --show-toplevel`）。
  2. 它的 tip 已集成：在主树里 `git merge-base --is-ancestor <tip> HEAD` 为真。
  3. 没有未提交的**已跟踪**改动：`git -C <树> status --porcelain` 里不以 `??` 开头的行数为 0。
     （未跟踪的临时文件**不算阻塞**，但计数并在 `--apply` 时一起报出来。）
  4. 没有别的进程在这棵树里 —— 用铁律 28 的**树侧判据**：进程的 cwd == 树根（或在其下）。
     ★★ **不许按进程名判**（铁律 27/28）；本卡**只判"有没有"，不杀任何进程**。
  5. 没有门禁锁被它持有：`gates/diag/gates.lock` / `gates-<BASE>.lock` 的持有者 cwd 不在它里面。
  6. `git worktree list --porcelain` 里它**没有 `locked` 标记**。
  7. 不是"未完工的卡"占用的树：读 backlog（`docs/workbacklog.toml`，现算）→ **`status` 非
     `done`** 的卡占的树一律保留。**不硬编码卡号**；backlog 读坏 → **判不了 → 全部保留**。

★ 判据 2 是"活进主树了"；3/4/5/6 是"现在没在用"；7 是"还没干完"。**缺一不可。**

删前证据留档（卡 083 · 台账号 `T-G178`）
----------------------------------------
★ **没拷走就不许删**。规矩出处：`gates/diag/do_tg120.py` §19.3（同见台账 `T-G120`）——
拆树之前，把 `<树>/gates/diag/wb-*` 拷回**主树** `gates/diag/`（它们会随树一起消失）：
`wb-<卡>.jsonl`（★ 第 1 行 `init` 里带 `model=`，是"这张卡用了哪个模型"的唯一凭证）·
`.report.md` · `.verdict.txt` · `.session.txt` · `.stderr.txt` · `.spec.txt` 等整族（不止这些）。
★ 通配 `wb-*`（**不写死卡号**）；`wb-usage.jsonl` 是**累积台账**，**逐行追加合并、绝不许覆盖**
（主树的既有行一个字节都不改）。任何一份拷不出来 / 合并失败 → **这棵树本轮不删**（宁可保留）。
`--no-rescue` 是显式逃生门（默认**关**，即默认**必须留档**）。

用法
----
    python -X utf8 tools/wt_prune.py                      # dry-run（默认）：打表，一棵不删
    python -X utf8 tools/wt_prune.py --apply              # 才真删；每删前复核七条 + 先留档
    python -X utf8 tools/wt_prune.py --json               # 给主控读的机器可读输出
    python -X utf8 tools/wt_prune.py --min-size 50        # 只看 ≥50 MB 的树
    python -X utf8 tools/wt_prune.py --no-rescue          # ★ 危险：跳过留档（默认不传 = 必须留档）
    python -X utf8 tools/wt_prune.py --root <仓库根>      # 指定仓库根（默认自动定位主仓）

退出码：0 = 正常（dry-run / apply 全部按预期）；
1 = 至少一棵"本应删掉"的树删失败（删失败 **或** 留档失败，都**保留**并打印原因）；
2 = 环境不对（不是 git 仓库 / 读不到 worktree 列表）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MB = 1024 * 1024

# 门禁默认端口段（与 `gates/diag/gate_lock.py:GATE_PORTS` 逐字对齐）——
# 只用于**标注**（哪个占用进程在听门禁端口），不参与杀/不杀判据。
DEFAULT_GATE_PORTS = (8531, 8532, 8541, 8542, 8543, 8544)


# ================================================================ 基础工具


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """跑一条 git。`core.quotepath=false`：中文路径别被八进制转义（铁律 24 的老坑）。"""
    try:
        r = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except OSError:
        return 1, "", "git 不可用"
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _norm(p: object) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _inside(child: object, parent: object) -> bool:
    """`child` 是否等于 `parent` 或在其下（大小写按平台归一；Windows 上大小写不敏感）。"""
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p + os.sep)


def main_root(explicit: str | None = None) -> Path | None:
    """主仓根。`--root` 给了就用它；否则用 `git-common-dir` 定位（在 worktree 里跑也指主仓）。"""
    if explicit:
        p = Path(explicit)
        return p.resolve() if p.exists() else None
    rc, out, _ = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], Path.cwd())
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve().parent
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve()
    return None


def current_worktree() -> Path | None:
    """当前工作树（判据 1 要排除它）。`git rev-parse --show-toplevel` 从 cwd 起算。"""
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    return Path(out.strip()).resolve() if rc == 0 and out.strip() else None


# ================================================================ 大小（不吃权限错误）


def dir_size(path: Path) -> tuple[int, int]:
    """递归求目录下所有文件的 `st_size` 之和（**不用 `du`**：Windows 没有）。

    ★ 铁律/坑：权限错误**跳过并计数**（返回 skipped），不许让一棵读不动的树把整轮打挂。
    软链不追（`follow_symlinks=False`），避免绕圈。
    """
    total = 0
    skipped = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        skipped += 1
        except OSError:
            skipped += 1
    return total, skipped


# ================================================================ worktree 列表


@dataclass
class TreeInfo:
    path: Path
    head: str = ""
    branch: str = ""
    detached: bool = False
    locked: bool = False
    locked_reason: str = ""
    prunable: bool = False


def list_worktrees(root: Path) -> list[TreeInfo]:
    """解析 `git worktree list --porcelain`（`worktree/HEAD/branch/detached/locked/prunable`）。"""
    rc, out, err = _git(["worktree", "list", "--porcelain"], root)
    if rc != 0:
        raise RuntimeError(f"读不到 worktree 列表：{err.strip() or '退出码 ' + str(rc)}")
    trees: list[TreeInfo] = []
    cur: TreeInfo | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = TreeInfo(path=Path(line[len("worktree "):].strip()).resolve())
            trees.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur.head = line[5:].strip()
        elif line.startswith("branch "):
            cur.branch = line[7:].strip()
        elif line == "detached":
            cur.detached = True
        elif line.startswith("locked"):
            cur.locked = True
            cur.locked_reason = line[len("locked"):].strip()
        elif line.startswith("prunable"):
            cur.prunable = True
    return trees


# ================================================================ 进程（判据 4）


def _psutil() -> Any:
    try:
        import psutil  # type: ignore[import-untyped]
        return psutil
    except Exception:
        return None


def scan_processes() -> tuple[dict[str, list[tuple[int, str]]] | None, dict[int, set[int]] | None]:
    """一次扫全部进程：`cwd(规范化) → [(pid, 名字)]` + `pid → {在听的端口}`。

    ★ 判据 4 只认 **cwd**（铁律 28 的树侧判据），**绝不按进程名判**（铁律 27/28）。
    ★ psutil 拿不到 → 返回 `(None, None)` = **判不了 → 保留**（拒绝优于误删）。
    """
    ps = _psutil()
    if ps is None:
        return None, None
    by_cwd: dict[str, list[tuple[int, str]]] = {}
    for proc in ps.process_iter(["pid", "name"]):
        try:
            pid = int(proc.info["pid"])
            cwd = proc.cwd()
        except Exception:
            continue
        if not cwd:
            continue
        try:
            key = _norm(cwd)
        except Exception:
            continue
        by_cwd.setdefault(key, []).append((pid, str(proc.info.get("name") or "")))
    listen: dict[int, set[int]] = {}
    try:
        for conn in ps.net_connections(kind="tcp"):
            if conn.status == ps.CONN_LISTEN and conn.laddr and conn.pid:
                listen.setdefault(int(conn.pid), set()).add(int(conn.laddr.port))
    except Exception:
        pass
    return by_cwd, listen


def occupancy(tree: Path, by_cwd: dict[str, list[tuple[int, str]]],
              listen: dict[int, set[int]]) -> list[tuple[int, str, list[int]]]:
    """这棵树里的进程（cwd == 树根 或在其下）；带它们在听的端口（仅标注）。"""
    hits: list[tuple[int, str, list[int]]] = []
    t = _norm(tree)
    for key, procs in by_cwd.items():
        if key == t or key.startswith(t + os.sep):
            for pid, name in procs:
                hits.append((pid, name, sorted(listen.get(pid, ()))))
    return hits


# ================================================================ 锁（判据 5）


def lock_holders(root: Path) -> list[tuple[str, str, str]]:
    """`gates/diag/gates*.lock` 里每一把锁的 `(文件名, card, cwd)`（读不出的跳过）。"""
    d = root / "gates" / "diag"
    out: list[tuple[str, str, str]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("gates*.lock")):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        cwd = str(info.get("cwd") or "")
        out.append((p.name, str(info.get("card") or ""), cwd))
    return out


# ================================================================ backlog（判据 7）


_WB_PLAN: Any = None


def _load_wb_plan() -> Any:
    """加载兄弟模块 `tools/wb_plan.py`（`tools/` 不是包 → 按路径加载）。

    ★ 必须**先塞进 `sys.modules`** 再 `exec_module` —— 否则 `@dataclass` 求值时
    `sys.modules[cls.__module__]` 是 None（`dataclasses.py` 报 'NoneType' has no __dict__，
    实测踩到）。加载一次后缓存。
    """
    global _WB_PLAN
    if _WB_PLAN is not None:
        return _WB_PLAN
    src = Path(__file__).resolve().parent / "wb_plan.py"
    spec = importlib.util.spec_from_file_location("wb_plan_under_wt_prune", src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _WB_PLAN = mod
    return mod


def backlog_pending_trees(root: Path) -> dict[str, str] | None:
    """未完工卡（`status != done`）占的树：`树路径(规范化) → "卡号(task) status"`。

    ★ 不硬编码卡号：现读 `docs/workbacklog.toml`（**与 `wb_plan.py` 同一口径**）。
    ★ 返回 `None` = **判不了**（backlog 存在但读坏）→ 调用方把判据 7 记成"不确定 → 保留"。
    ★ backlog 文件**不存在** = 没有任何卡占树 → 返回空字典（不是 None）。
    """
    path = root / "docs" / "workbacklog.toml"
    if not path.exists():
        return {}
    try:
        wb = _load_wb_plan()
        backlog = wb.load_backlog(path)
    except Exception:
        return None
    claimed: dict[str, str] = {}
    for card in backlog.cards:
        if card.status == "done":
            continue
        tree = (card.tree or "").strip()
        if not tree:
            continue
        claimed[_norm(root / tree)] = f"{card.id}({card.task}) status={card.status}"
    return claimed


# ================================================================ 判据 1–7 的逐棵树评估


@dataclass
class Verdict:
    name: str
    path: Path
    tip: str
    integrated: bool | None
    tracked_dirty: int | None
    untracked: int | None
    occupied: bool | None
    occupied_note: str = ""
    locked: bool = False
    holds_lock: bool | None = None
    holds_lock_note: str = ""
    size_bytes: int = 0
    size_skipped: int = 0
    deletable: bool = False
    reason: str = ""
    skipped: bool = False
    apply_result: str = ""
    apply_ok: bool = field(default=True)
    rescue_files: int | None = None       # 待留档的每卡独占文件数（None = 没预演 / 不留档）
    rescue_usage_add: int | None = None   # usage 预演：会追加几行（None = 没有 usage 文件）
    rescue_usage_skip: int | None = None  # usage 预演：会跳过几行已存在


def _status_counts(tree: Path) -> tuple[int, int] | None:
    """`(未提交的已跟踪改动数, 未跟踪文件数)`；读不到 → None。`-uall` 逐文件数未跟踪。"""
    rc, out, _ = _git(["status", "--porcelain", "--untracked-files=all"], tree)
    if rc != 0:
        return None
    tracked = untracked = 0
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            untracked += 1
        else:
            tracked += 1
    return tracked, untracked


def judge(tree: TreeInfo, ctx: dict[str, Any]) -> Verdict:
    """判这棵树：**把七条各自的事实都量出来**（表要完整），再按 1→7 取首条失败的当理由。

    ★ 事实先量、后来判 —— 否则一个早退（如判据 2 失败）会让后面的列全是 `-`，表就不完整了。
    """
    root: Path = ctx["root"]
    name = tree.path.relative_to(root).as_posix() if _inside(tree.path, root) else str(tree.path)
    v = Verdict(name=name, path=tree.path, tip=tree.head, integrated=None, tracked_dirty=None,
                untracked=None, occupied=None, locked=tree.locked)

    if not _inside(tree.path, root / ".wt"):
        v.reason = "判据1：不在 <仓库根>/.wt/ 下（或就是主树）"
        return v
    is_current = ctx["current"] is not None and _norm(tree.path) == _norm(ctx["current"])

    # 事实一：tip 是否已集成
    if tree.head:
        rc, _, _ = _git(["merge-base", "--is-ancestor", tree.head, "HEAD"], root)
    else:
        rc = 1
    v.integrated = (rc == 0)
    # 事实二：git status（跟踪改动 + 未跟踪文件）
    counts = _status_counts(tree.path)
    if counts is not None:
        v.tracked_dirty, v.untracked = counts
    # 事实三：进程占用（cwd == 树根 或在其下）
    hits: list[tuple[int, str, list[int]]] = []
    if ctx["by_cwd"] is not None:
        hits = occupancy(tree.path, ctx["by_cwd"], ctx["listen"] or {})
        v.occupied = bool(hits)
        if hits:
            parts = []
            for pid, pname, ports in hits[:3]:
                seg = ("[门禁端口 " + ",".join(str(p) for p in ports) + "]"
                       if any(p in DEFAULT_GATE_PORTS for p in ports)
                       else ("[端口 " + ",".join(str(p) for p in ports) + "]" if ports else ""))
                parts.append(f"pid={pid}({pname}){seg}")
            v.occupied_note = "；".join(parts) + (f" 等 {len(hits)} 个" if len(hits) > 3 else "")
    # 事实四：是否持有门禁锁
    holders = ctx["locks"]
    held = []
    if holders is not None:
        held = [f"{fname}(card={card})" for fname, card, cwd in holders
                if cwd and _inside(cwd, tree.path)]
    if holders is not None:
        v.holds_lock = bool(held)
        v.holds_lock_note = "；".join(held)

    # ---- 按 1→7 判：第一条不成立的就是保留理由 ----
    if is_current:
        v.reason = "判据1：就是当前工作树"
    elif not tree.head:
        v.reason = "判据2：拿不到 tip（HEAD 为空）"
    elif counts is None:
        v.reason = "判据3：读不到 git status（不确定 → 保留）"
    elif not v.integrated:
        v.reason = "判据2：tip 未集成到主树 HEAD"
    elif v.tracked_dirty:
        v.reason = f"判据3：有 {v.tracked_dirty} 个未提交的已跟踪改动"
    elif v.occupied is None:
        v.reason = "判据4：psutil 不可用，判不了有没有进程（不确定 → 保留）"
    elif hits:
        v.reason = f"判据4：树里有进程（{v.occupied_note}）"
    elif v.holds_lock is None:
        v.reason = "判据5：读不到锁目录（不确定 → 保留）"
    elif held:
        v.reason = f"判据5：持有门禁锁 {v.holds_lock_note}"
    elif tree.locked:
        v.reason = "判据6：worktree 被 locked" + (
            f"（{tree.locked_reason}）" if tree.locked_reason else "")
    elif ctx["pending"] is None:
        v.reason = "判据7：backlog 读不了，判不了有没有未完工卡（不确定 → 保留）"
    elif _norm(tree.path) in ctx["pending"]:
        v.reason = f"判据7：未完工卡占着它（{ctx['pending'][_norm(tree.path)]}）"
    else:
        v.deletable = True
    return v


# ================================================================ 表格输出


def _w(text: str) -> int:
    """显示宽度（CJK 记 2 列）—— 好让表对齐。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _w(text))


COLUMNS = ("树名", "tip", "已集成", "跟踪改动", "未跟踪", "进程占用", "锁", "大小MB",
           "待留档", "裁决", "理由")


def _yn(tri: bool | None) -> str:
    """三态布尔 → 表里的一格（`None` = 判不了）。"""
    return "-" if tri is None else ("是" if tri else "否")


def _dash(value: int | None) -> str:
    return "-" if value is None else str(value)


def _row(cells: list[str]) -> str:
    return " | ".join(cells)


def _rescue_cell(v: Verdict) -> str:
    """「待留档」列：可删的树才显示预演读数；`--no-rescue` 时显示「不留档」。"""
    if not v.deletable:
        return "-"
    if v.rescue_files is None:
        return "不留档"
    if v.rescue_usage_add is None:
        return f"{v.rescue_files}份"
    return f"{v.rescue_files}份+usage追加{v.rescue_usage_add}/跳过{v.rescue_usage_skip}"


def render_table(verdicts: list[Verdict]) -> list[str]:
    head = _row(list(COLUMNS))
    rows = [head, "-" * _w(head)]
    for v in verdicts:
        rows.append(_row([
            v.name,
            v.tip[:7] or "-",
            _yn(v.integrated),
            _dash(v.tracked_dirty),
            _dash(v.untracked),
            _yn(v.occupied),
            "是" if v.locked else _yn(v.holds_lock),
            f"{v.size_bytes / MB:.1f}",
            _rescue_cell(v),
            "可删" if v.deletable else "保留",
            v.reason or "",
        ]))
    return rows


def summarize(verdicts: list[Verdict]) -> dict[str, Any]:
    shown = [v for v in verdicts if not v.skipped]
    deletable = [v for v in shown if v.deletable]
    keep = [v for v in shown if not v.deletable]
    return {
        "total": len(shown),
        "skipped": len(verdicts) - len(shown),
        "deletable": len(deletable),
        "keep": len(keep),
        "reclaim_mb": round(sum(v.size_bytes for v in deletable) / MB, 1),
    }


# ================================================================ 删前证据留档（卡 083 · T-G178）
#
# ★ 规矩（`gates/diag/do_tg120.py` §19.3 / 台账 `T-G120`）：拆树之前，把 `<树>/gates/diag/wb-*`
#   拷回**主树** `gates/diag/`（它们会随树一起消失）。**没拷走就不许删**。

RESCUE_GLOB = "wb-*"
USAGE_NAME = "wb-usage.jsonl"


def scan_rescue(src_diag: Path) -> tuple[list[Path], Path | None]:
    """扫 `<树>/gates/diag/wb-*` → `(每卡独占文件列表, usage 文件或 None)`。

    ★ **通配整族**，不写死卡号（卡 081 判据 7 硬编码 → 保护不到东西的教训）。
    ★ `wb-usage.jsonl` 单独拎出来：它是**累积台账**，要**追加合并**不是覆盖。
    ★ 只收 `wb-*` 这一族，别的文件一概不碰（范围越小越好）。
    """
    if not src_diag.is_dir():
        return [], None
    files: list[Path] = []
    usage: Path | None = None
    for p in sorted(src_diag.glob(RESCUE_GLOB)):
        if not p.is_file():
            continue
        if p.name == USAGE_NAME:
            usage = p
        else:
            files.append(p)
    return files, usage


def _usage_key(line: str) -> tuple[str, str] | None:
    """一行 usage JSONL 的去重键 `(卡, 开始)`；JSON 坏 / 缺键 → None（调用方退化成整行做键）。"""
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    card = str(obj.get("卡") or "")
    start = str(obj.get("开始") or "")
    if not card and not start:
        return None
    return card, start


def _usage_diff(existing_text: str, src_text: str) -> tuple[list[str], int]:
    """`(要追加的行, 跳过的行数)` —— 按 `(卡,开始)` 去重；解析不出键的行退化成整行做键。"""
    seen: set[Any] = set()
    for line in existing_text.splitlines():
        if line.strip():
            k = _usage_key(line)
            seen.add(k if k is not None else line)
    add: list[str] = []
    skipped = 0
    for line in src_text.splitlines():
        if not line.strip():
            continue
        k = _usage_key(line)
        key = k if k is not None else line
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        add.append(line)
    return add, skipped


def merge_usage(dst: Path, src: Path) -> tuple[int, int]:
    """把 `src` 的 usage **逐行追加合并**进 `dst`（按 `(卡,开始)` 去重）。

    返回 `(追加行数, 跳过行数)`。★ **既有行一个字节都不改**（只在文件末尾 append）；
    `dst` 不存在则创建。解析不出键的行退化成用整行做键（宁可重复也不丢）。
    """
    had = dst.exists()
    existing = dst.read_text(encoding="utf-8") if had else ""
    add, skipped = _usage_diff(existing, src.read_text(encoding="utf-8"))
    if add:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("a", encoding="utf-8", newline="") as fh:
            if had and existing and not existing.endswith("\n"):
                fh.write("\n")  # 既有末行没换行 → 补一个，免得和新行粘一起
            fh.write("\n".join(add) + "\n")
    return len(add), skipped


def preview_usage(dst: Path, src: Path) -> tuple[int, int]:
    """**只读**预演一次合并（不落盘）：`(会追加的行数, 会跳过的行数)`。"""
    existing = dst.read_text(encoding="utf-8") if dst.exists() else ""
    add, skipped = _usage_diff(existing, src.read_text(encoding="utf-8"))
    return len(add), skipped


def rescue_tree(root: Path, tree: Path) -> tuple[bool, str, int, int]:
    """把这棵树的证据拷回**主树** `gates/diag/`。返回 `(是否成功, 报告行, 待拷份数, 追加行数)`。

    - 每卡独占 `wb-<卡>.*` → 拷到 `<root>/gates/diag/`；**目标已存在则不覆盖**（跳过并计数）；
      目标同名位置竟是**目录** → 算**冲突失败**（不覆盖、不硬写）。
    - `wb-usage.jsonl` → **逐行追加合并**（绝不覆盖主树那份）。
    - ★ 任何一份拷不出来 / usage 合并失败 → **成功=False**（调用方据此**不删这棵树**）。
    """
    src_diag = tree / "gates" / "diag"
    dst_diag = root / "gates" / "diag"
    files, usage = scan_rescue(src_diag)
    copied = skipped = 0
    usage_add = usage_skip = 0
    try:
        dst_diag.mkdir(parents=True, exist_ok=True)
        for f in files:
            dst = dst_diag / f.name
            if dst.exists():
                if dst.is_dir():
                    msg = f"留档失败：目标 {dst.name} 是同名目录（不覆盖）"
                    return False, msg, copied, usage_add
                skipped += 1
                print(f"[rescue]   已存在→跳过 {f.name}")
                continue
            shutil.copy2(f, dst)
            copied += 1
        if usage is not None:
            usage_add, usage_skip = merge_usage(dst_diag / usage.name, usage)
    except OSError as exc:
        return False, f"留档失败：{exc}", copied, usage_add
    line = (f"[rescue] {tree} → 拷了 {copied} 份（跳过 {skipped} 份已存在）；"
            f"usage 追加 {usage_add} 行（跳过 {usage_skip} 行已存在）")
    print(line)
    return True, line, len(files), usage_add


# ================================================================ 主流程


def make_context(root: Path, current: Path | None) -> dict[str, Any]:
    """一次把判据要用的事实都扫出来（进程 / 锁 / backlog）；`judge` 从这个 dict 取。"""
    by_cwd, listen = scan_processes()
    return {
        "root": root,
        "current": current,
        "by_cwd": by_cwd,
        "listen": listen,
        "locks": lock_holders(root),
        "pending": backlog_pending_trees(root),
    }


def collect(root: Path, current: Path | None, min_size_mb: float) -> list[Verdict]:
    trees = list_worktrees(root)
    ctx = make_context(root, current)
    out: list[Verdict] = []
    for t in trees:
        v = judge(t, ctx)
        if v.reason.startswith("判据1：不在"):
            continue  # 不在 .wt/ 下的压根不是本卡的活（含主树）
        size, skipped = dir_size(v.path)
        v.size_bytes, v.size_skipped = size, skipped
        if min_size_mb > 0 and size < min_size_mb * MB:
            v.skipped = True
            v.reason = f"小于 --min-size {min_size_mb} MB（跳过）"
        out.append(v)
    out.sort(key=lambda v: v.size_bytes, reverse=True)
    return out


def recheck_apply(root: Path, path: Path) -> Verdict:
    """`--apply` 的**第二拍**：从零把七条判据再判一遍（两拍之间状态可能变了）。"""
    trees = {_norm(t.path): t for t in list_worktrees(root)}
    t = trees.get(_norm(path))
    if t is None:
        v = Verdict(name=str(path), path=path, tip="", integrated=None, tracked_dirty=None,
                    untracked=None, occupied=None)
        v.reason = "第二拍：worktree 已不在列表里"
        return v
    return judge(t, make_context(root, current_worktree()))


def do_apply(root: Path, verdicts: list[Verdict], rescue: bool = True) -> int:
    """真删：每棵**先复核七条**、**再留档证据**，最后用**不带 `--force`** 的 `git worktree remove`。

    ★ 留档失败（或 `rescue=False` 时按显式逃生门跳过）→ 该树**保留**并计失败。
    """
    failed = 0
    removed: list[str] = []
    kept: list[str] = []
    print("\n=== --apply：开始真删（每棵先复核七条 + 留档证据，且不用 --force）===")
    for v in verdicts:
        if not v.deletable:
            continue
        again = recheck_apply(root, v.path)
        if not again.deletable:
            v.deletable = False
            v.reason = f"apply-复核未过 → 保留（{again.reason}）"
            kept.append(f"{v.name}（复核未过：{again.reason}）")
            continue
        if rescue:
            ok, line, _n_files, _n_add = rescue_tree(root, v.path)
            if not ok:
                v.deletable = False
                v.apply_result = "留档失败"
                v.apply_ok = False
                failed += 1
                v.reason = f"apply：{line} → 保留"
                kept.append(f"{v.name}（{v.reason}）")
                continue
        rc, out, err = _git(["worktree", "remove", str(v.path)], root)
        if rc == 0:
            v.apply_result = "已删"
            removed.append(v.name)
        else:
            v.apply_result = "删失败"
            v.apply_ok = False
            failed += 1
            v.reason = f"apply：git worktree remove 失败（{(err or out).strip()[:200]}）→ 保留"
            kept.append(f"{v.name}（{v.reason}）")
    print(f"[apply] 删了 {len(removed)} 棵" + ("：" + "、".join(removed) if removed else ""))
    print(f"[apply] 留住 {len(kept)} 棵" + ("：" + "；".join(kept) if kept else ""))
    if failed:
        print(f"[apply] ★ {failed} 棵本应删掉的树删失败（已保留，原因见上）")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="`.wt` 工作树清理器：七条判据、默认只看不删（T-G176）")
    ap.add_argument("--apply", action="store_true", help="才真删；默认只看不删（dry-run）")
    ap.add_argument("--json", action="store_true", help="机器可读输出（给主控读）")
    ap.add_argument("--min-size", type=float, default=0.0, metavar="MB",
                    help="只看 ≥ 这个大小的树（MB；默认 0 = 全看）")
    ap.add_argument("--root", default=None, help="仓库根（默认自动定位主仓）")
    ap.add_argument("--no-rescue", action="store_true",
                    help="★ 危险：跳过「删前证据留档」（默认不传 = 必须留档）")
    ns = ap.parse_args(argv)

    if ns.no_rescue:
        print("★★★ 警告：--no-rescue 已开 —— 本轮**不留档**：树里的 wb-*.jsonl"
              "（第 1 行含 model=，是「这张卡用了哪个模型」的唯一凭证）与 wb-usage.jsonl "
              "会随树一起**永久消失**、事后从仓库里查不出来。", file=sys.stderr)

    root = main_root(ns.root)
    if root is None:
        print("[FAIL] 定位不到仓库根（不是 git 仓库？）", file=sys.stderr)
        return 2
    try:
        verdicts = collect(root, current_worktree(), ns.min_size)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    summary = summarize(verdicts)
    shown = [v for v in verdicts if not v.skipped]

    # ★ 留档预演（干跑也看得见）：可删的树各要留档几份 —— 「待留档」列
    if not ns.no_rescue:
        for v in verdicts:
            if v.deletable:
                files, usage = scan_rescue(v.path / "gates" / "diag")
                v.rescue_files = len(files)
                if usage is not None:
                    v.rescue_usage_add, v.rescue_usage_skip = preview_usage(
                        root / "gates" / "diag" / usage.name, usage)

    if ns.json:
        payload = {
            "root": str(root),
            "mode": "apply" if ns.apply else "dry-run",
            "trees": [
                {
                    "name": v.name, "tip": v.tip, "integrated": v.integrated,
                    "tracked_dirty": v.tracked_dirty, "untracked": v.untracked,
                    "occupied": v.occupied, "occupied_note": v.occupied_note,
                    "locked": v.locked, "holds_lock": v.holds_lock,
                    "size_mb": round(v.size_bytes / MB, 1), "size_skipped": v.size_skipped,
                    "deletable": v.deletable, "reason": v.reason, "skipped": v.skipped,
                    "rescue_files": v.rescue_files,
                    "rescue_usage_add": v.rescue_usage_add,
                    "rescue_usage_skip": v.rescue_usage_skip,
                }
                for v in verdicts
            ],
            "summary": summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        mode = "APPLY（真删）" if ns.apply else "DRY-RUN（只看不删）"
        print(f"=== .wt 工作树清理器 · {mode} · 仓库根 {root} ===")
        print("（判据：①在 .wt 下非主树非当前树 ②tip 已集成 ③无未提交跟踪改动 "
              "④无进程占用 ⑤无门禁锁 ⑥无 locked ⑦非未完工卡）")
        print("（删前留档：把 <树>/gates/diag/wb-* 拷回主树 gates/diag/；"
              "wb-usage.jsonl 追加合并；拷不出来就不删。--no-rescue 才跳过）")
        if ns.no_rescue:
            print("（★ --no-rescue：本轮不留档 —— 会丢掉模型凭证与 usage 台账）")
        if ns.min_size > 0:
            print(f"（--min-size {ns.min_size} MB：{summary['skipped']} 棵更小的树已跳过）")
        for line in render_table(shown):
            print(line)
        print(f"\n汇总：可删 {summary['deletable']} 棵 / 保留 {summary['keep']} 棵 / "
              f"可释放 {summary['reclaim_mb']} MB")

    code = 0
    if ns.apply:
        code = do_apply(root, verdicts, rescue=not ns.no_rescue)
        if not ns.json:
            n_removed = sum(1 for v in verdicts if v.apply_result == "已删")
            n_left = sum(1 for v in verdicts if v.deletable and v.apply_result != "已删")
            print(f"\n--- apply 后汇总：已删 {n_removed} 棵 / 未删 {n_left} 棵 ---")
    return code


if __name__ == "__main__":
    sys.exit(main())
