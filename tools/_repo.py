r"""仓库根解析 `tools/_repo.py`（卡 A306 · T-AG420）—— **唯一实现**，别的工具都来这儿取。

为什么有它（用户口径：同一份 `tools/` 服务**所有**仓库，维护一处）：以前每个工具各自写
`ROOT = Path(__file__).resolve().parent.parent` —— 那等于说「根 = 我躺的那棵树」：工具换个仓用 /
被拷到别处，根就跟着跑偏，而且每加一个工具就多一份同样的代码。

## 口径（顺序不能换）

1. **显式**（`--root <路径>`）—— 调用者说了算；相对路径按**当前目录**解析，统一回绝对路径；
2. **`git rev-parse --show-toplevel`** —— 问**当前目录**所在的 git 工作树（不在仓里 / 没装 git
   ⇒ 跳过，不抛）；
3. **本文件上一级**（`tools/` 的父目录）—— 最后兜底，**不抛**：工具必须还能起来，缺什么由
   调用方如实说（这里不许假装算出来了）。

## 与 `pool.task.main_tree_root()` / `pool.registry.main_tree_root()` 的分工（别混用）

那两个问的是「**主工作树**在哪」—— 池状态（租约 / 栅栏 / 批）住那儿，走 `--git-common-dir`，
**卡树里必须回主树**。本函数问的是「**仓根**」，走 `--show-toplevel`，在卡树里回**卡树自己**。
两者只在**主树里**同值。口诀：读池状态用前者，读写「这个仓自己的文件」用本函数。

★ Windows：起 `git` 一律带防窗旗（`tests/test_no_window.py` 会咬没有它的子进程）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_toplevel(cwd: str | Path | None = None) -> Path | None:
    """`git rev-parse --show-toplevel` 的结果（绝对路径）；算不出 ⇒ `None`（**不抛**）。

    ★ `cwd` 不给 = 当前进程的目录。★ 失败一律回 `None`：不在仓里、没装 git、git 自己报错，
      都是「算不出」，不是「根是空」—— 由 `repo_root()` 决定怎么兜底。
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, ValueError):
        return None
    if done.returncode != 0:
        return None
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line:
            return Path(line).resolve()
    return None


def repo_root(explicit: str | Path | None = None) -> Path:
    """仓库根：显式 > `git rev-parse --show-toplevel` > 本文件上一级（`tools/` 的父目录）。

    ★ 显式给了就当数（**不**再问 git：调用者在说「就是这个仓」）；空串 / `None` 等于没给。
    ★ 兜底那支永远成功 —— 本模块**不抛**，工具不该因为定位根就起不来。
    """
    if explicit is not None:
        text = str(explicit).strip()
        if text:
            return Path(text).expanduser().resolve()
    found = git_toplevel()
    if found is not None:
        return found
    return Path(__file__).resolve().parent.parent
