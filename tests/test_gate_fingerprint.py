"""核「封存指纹」会不会咬（T-G179 · 卡 084 §1.2 / §1.3）。

## 为什么有这张测试

`gates/last.json.tree` 曾经是**一整列没人查、且每笔都错**的凭证：`scripts/run_gates.py:349`
把临时索引写死在 `ROOT/.git` 下，而 linked worktree 里 `.git` 是**文件** → `read-tree` 失败 →
回退成"底座提交的 tree"；再加上 `gates/last.json` 自己在那棵树里（自指），于是 5 棵树的
`last.tree` 全是底座那棵树（卡 §0 实测钉死）。

本卡把它定义成「除 `gates/**` 外、即将提交的内容」的 tree 哈希 —— 一个**可复现的固定点**。
这条口径的两个要害（缺一即"注释"）：
  ① **会咬**：`gates/**` 之外改一个字节 → 指纹**必须变**；
  ② 是固定点：gates/** 里随便改（含 last.json 它自己）→ 指纹不许变（否则自指、追不上）。

## 怎么验

`tree_without_gates()` 要**真 git**（read-tree/add/write-tree），所以在 `tmp_path` 里
`git init` 造一个**真临时仓库**跑，不碰本仓库、不跑任何门。

## 边界（如实写，未覆盖）

- 不测"linked worktree 里 read-tree 不再失败"这条 —— 那要再造一棵 linked worktree，
  且它属于 §3 的手工自测（卡 §3.1），这里只钉"摘 gates 成为固定点"这条**定义**。
- 不测 `wb_verify` 的封存指纹行本身（它读 `HEAD:gates/last.json`，要一笔真提交）——
  那条由门禁收口时 `tools/wb_verify.py` 跑出（卡 §1.3）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=root, env=_GIT_ENV,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert done.returncode == 0, f"git {args} 失败：{done.stderr}"
    return done.stdout.strip()


def _seed(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(root: Path) -> None:
    """一个**真**临时 git 仓库（`tree_without_gates` 要真 git），已有一笔提交。"""
    _git(root, "init", "-q")
    _seed(root, "src/a.txt", "A")
    _seed(root, "gates/last.json", '{"tree":"x"}')
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def test_fingerprint_sees_changes_outside_gates(tmp_path: Path) -> None:
    """★ 会咬：`gates/**` 之外改一个字节 → 指纹**必须变**（否则这条判据是注释）。"""
    _init_repo(tmp_path)
    before = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)

    _seed(tmp_path, "src/a.txt", "B")  # 只改 gates 外的文件

    after = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)
    assert before and after and before != after


def test_fingerprint_ignores_gates_changes(tmp_path: Path) -> None:
    """★ 固定点：`gates/**` 里改（含 `gates/last.json` 它自己）→ 指纹**不许变**。

    这一条就是"自指悖论"的解药：指纹不含门禁产物，写完它自己也不变、追得上。
    """
    _init_repo(tmp_path)
    before = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)

    _seed(tmp_path, "gates/last.json", '{"tree":"写着指纹的自己"}')
    _seed(tmp_path, "gates/render/golden.txt", "新黄金")

    after = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)
    assert before == after


def test_old_rev_still_has_gates_stripped(tmp_path: Path) -> None:
    """★ 会咬：`rev` **不是 HEAD** 时也必须真的把 `gates/` 摘掉（2026-10-28 实测踩到）。

    病灶：`read-tree <旧 rev>` 建出来的临时索引里，`gates/` 下的条目与工作区、HEAD
    都不一致（`gates/last.json` 每趟都被改写），`git rm --cached` 于是以
    「staged content different from both the file and the HEAD」**拒删**并退 1。
    后果不是"少摘一个文件"，而是 `write-tree` 返回**整棵树**（含 gates/）——
    封存指纹退化成"完整提交树"，自指的那条定义被悄悄换掉。

    ⇒ 必须带 `-f`。这条钉子钉的就是它：拿**上一笔提交**当 rev，指纹仍不许含 gates/。
    """
    _init_repo(tmp_path)
    before_head = _git(tmp_path, "rev-parse", "HEAD")  # 上一笔（gates/ 里的内容与它不同）

    _seed(tmp_path, "gates/last.json", '{"tree":"新一趟写进去的，与上一笔不一致"}')
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "第二笔：只动 gates/")

    fingerprint = rg.tree_without_gates(tmp_path, before_head, exclude_gates=True)
    full = rg.tree_without_gates(tmp_path, before_head, exclude_gates=False)

    assert fingerprint and full
    # ① 摘干净了：与"完整树"必须不同
    assert fingerprint != full, "rev 不是 HEAD 时 gates/ 没被摘掉 —— 封存指纹变成完整树的别名"
    # ② 而且等于"上一笔减去 gates/"的那棵树（不是 HEAD，不是工作区）
    expect = _git(tmp_path, "rev-parse", f"{before_head}^{{tree}}")
    gates_tree = _git(tmp_path, "rev-parse", f"{before_head}:gates")
    assert full == expect
    assert fingerprint != gates_tree
    ls = _git(tmp_path, "ls-tree", "-r", "--name-only", fingerprint)
    assert not [ln for ln in ls.splitlines() if ln.startswith("gates/")], (
        f"指纹里还留着 gates/ 条目：{ls}"
    )


def test_fingerprint_is_not_the_full_tree(tmp_path: Path) -> None:
    """指纹**不等于**完整提交的 tree（`exclude_gates=False` 时才是完整树）——"""
    _init_repo(tmp_path)
    fingerprint = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True)
    full = rg.tree_without_gates(tmp_path, "HEAD", include_worktree=True, exclude_gates=False)

    assert fingerprint and full
    assert fingerprint != full
    assert full == _git(tmp_path, "rev-parse", "HEAD^{tree}")  # 干净树上完整树 == HEAD^{tree}
