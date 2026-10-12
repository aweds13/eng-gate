r"""**零风险快照**（卡 192 · T-G292）：把任意工作区压成一个 stash commit 并**挂 ref**
—— 完全不动工作区。

★★ 为什么有它（用户 2026-10-03 17:3x：「**你之前没有留快照保存的吗？**」）：
今晚卡 160 的工人成果被主控工具覆盖，靠 `git fsck` 的**悬空对象**才救回 3 份
—— ★ **那是运气，不是机制**。
⇒ 正确的做法是：**任何"要动别人工作区"的操作之前，先打一个快照**。

★ 为什么用 `git stash create` 而不是 `git stash`：
- `git stash create` → **造一个 commit 对象**（worktree + index 的快照），
  **不修改工作区、不动 index、不写 stash 栈** ⇒ **纯读操作**；
- `git stash` → 会**真的把改动收走**（工作区被清空）⇒ 那正是我们不想干的。

★★ 关键补丁（比 `_snapshot.py` 多的、本模块存在的理由）：
`stash create` 造的 commit **没有任何 ref 指向它**
⇒ **gc 会把它当垃圾清掉**（今晚救命的悬空对象就是这样，只是"还没被 gc"而已）。
⇒ **给每个快照挂一个 ref**：`refs/snapshots/<树>-<时间>`
  ⇒ 变成**可达对象**，于是 `git clone --mirror` / `git push --mirror` **会把它带走** ⇒ 才算真备份。
★ 踩过的坑：ref 段名**不许以 `.` 开头**（`.wt-invgate-…` 被 git 拒）⇒ 会 lstrip 成 `wt-invgate`。

★ 本模块从 `gates/diag/_snapshot.py`（脚本式）抽成**可 import 的函数**，供收口链
（`tools/pool/landing.py`）与攒批器（`gates/diag/_batcher.py`）复用 —— 判据**只有一份真源**。
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "gates" / "diag" / "_snapshots.txt"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          encoding="utf-8", errors="replace")


def derive_name(wt: Path, root: Path | None = None) -> str:
    """从工作区路径派生 ref 段名（`.` / 仓根 → `root`；`.wt/gitbase` → `wt-gitbase`）。

    ★ ref 段名不许以 `.` 开头（git 拒）⇒ lstrip 后仍为空就退 `root`。
    """
    base = root or ROOT
    try:
        rel = wt.resolve().relative_to(base.resolve())
    except ValueError:
        rel = Path(wt.name)
    name = str(rel).replace("\\", "/").strip("/")
    name = "root" if name in (".", "") else name.replace("/", "-").lstrip(".")
    return name or "root"


def take_snapshot(wt: Path, why: str = "", name: str | None = None,
                  root: Path | None = None) -> str | None:
    """对工作区 `wt` 打一个零风险快照；返回**挂上的 ref 全名**（干净则 None）。

    - `git stash create` 造 commit 对象、**不动工作区**；
    - 工作区干净（无改动）⇒ 返回 None（不造 ref、不记台账）；
    - 有改动 ⇒ `git update-ref refs/snapshots/<name>-<时间> <sha>` 挂 ref ⇒ 可达 ⇒ 镜像带得走；
    - 记一行进 `gates/diag/_snapshots.txt`（时间 / 树 / sha / 改动数 / why / ref）。

    ★ 复原：`git checkout <sha> -- <路径>` 或 `git stash apply <sha>`。
    """
    base = root or ROOT
    if not (wt / ".git").exists() and not (wt / ".git").is_file():
        return None
    sha = _run(["git", "stash", "create"], wt).stdout.strip()
    if not sha:
        return None
    state = _run(["git", "-c", "core.quotepath=false", "status", "--porcelain"], wt).stdout.strip()
    n = len([x for x in state.splitlines() if x.strip()])
    seg = name or derive_name(wt, base)
    seg = seg.replace("/", "-").lstrip(".") or "root"
    ref = f"refs/snapshots/{seg}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    r = _run(["git", "update-ref", ref, sha], wt)
    if r.returncode != 0:
        return None
    ledger = base / "gates" / "diag" / "_snapshots.txt"
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%dT%H:%M:%S}\t"
                    f"{seg}\t{sha}\t{n}\t{why}\t{ref}\n")
    except OSError:
        pass
    return ref


def snapshot_sha(ref: str, wt: Path | None = None) -> str:
    """读一个快照 ref 指向的 sha（用来验证"从镜像取回来"）。"""
    r = _run(["git", "rev-parse", "--verify", ref], wt or ROOT)
    return r.stdout.strip() if r.returncode == 0 else ""
