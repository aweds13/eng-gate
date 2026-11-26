"""把「测试里写死的提交 sha」换成**按台账号反查**的锚点（卡 E163 / T-AG699）。

## 为什么需要它

判据里钉一笔历史提交是对的（「那一笔只加了 docstring」「sink 的八个函数以那一笔为基准」），
但**写死 sha** 会把「这笔提交是不是还在」变成判据的一部分。镜像仓（GHA 快照）的历史
被 filter-repo 重写过 ⇒ 同一笔内容、sha 全变 ⇒ 写死的 sha 一律 invalid object name。
2026-11-26 实测：一个镜像 4 条红里有 3 条就是这个原因（eaeb3923 / e3641bb9… / 2051255）。

## 口径

- **先认写死的那个 sha**：只要它在本仓确实是个 git 对象，就用它（源仓行为逐字不变）。
- 认不出来时按 Task: trailer 反查：台账号在台账里唯一，重写历史不会改它。
- 都查不到就**原样返回写死的值** —— 让原来的报错（invalid object name 'eaeb3923'）
  照旧出现，而不是把「查不到」洗成某个看着像对的东西。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def _git(args: list[str], root: Path | None = None) -> subprocess.CompletedProcess:
    base = Path(root) if root is not None else _DEFAULT_ROOT
    return subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(base),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def exists(rev: str, root: Path | None = None) -> bool:
    """探针：这个 rev 在本仓是不是个 git 对象（支持 sha ^path 三种后缀）。"""
    sha = str(rev).split("^")[0].split(":")[0].strip()
    if not sha:
        return False
    return _git(["cat-file", "-e", sha], root).returncode == 0


def find_by_task(task: str, root: Path | None = None) -> str:
    """按 Task: trailer 反查那一笔的**全 sha**；查不到回空串。

    台账号在台账里唯一 ⇒ 同一份内容在重写历史前后指的是同一笔。
    """
    wanted = (task or "").strip()
    if not wanted:
        return ""
    out = _git(
        ["log", "--format=%H%x1f%(trailers:key=Task,valueonly)", "--no-color"],
        root,
    ).stdout or ""
    hits: list[str] = []
    for line in out.splitlines():
        sha, _, trailer = line.partition("\x1f")
        if trailer.strip() == wanted and sha.strip():
            hits.append(sha.strip())
    # 同一台账号被复用（补规格 / 重跑落地）时不止一笔：要**最老**那笔 ——
    # 「那一笔自己的形状」永远锚在第一次落地，后补的提交不该顶替它。
    return hits[-1] if hits else ""


def anchor(recorded: str, task: str, root: Path | None = None) -> str:
    """recorded 在本仓是对象就用它，否则按 task 反查，再不然原样返回 recorded。"""
    if exists(recorded, root):
        return recorded
    found = find_by_task(task, root)
    return found or recorded


def numeric_short_sha(root: Path | None = None) -> str:
    """从当前历史里现取一笔**纯数字**的短 sha（取不到回空串）。

    纯数字短 sha 是 (10/16)**7 约 3.7% 的概率 —— 写死某一笔（2051255）等于断言
    「历史里永远有它」。判据要钉的是「纯数字候选也照样实测」，不是「那一笔还在」。
    """
    out = _git(["log", "--format=%h", "--no-color"], root).stdout or ""
    for tok in (line.strip() for line in out.splitlines()):
        if tok and tok.isdigit():
            return tok
    return ""
