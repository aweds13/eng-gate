r"""`tools/pool/snapshot.py` 的钉子（卡 192 · T-G292）—— 快照挂 ref、能复原、ref 段名安全。

★ 为什么值当测：今晚卡 160 的工人成果被覆盖，靠 `git fsck` 悬空对象才救回 3 份 ——
那是运气。`take_snapshot` 的命根子是「**挂 ref ⇒ 可达 ⇒ gc 不清 ⇒ 镜像带得走**」，
这条链任一环断了，快照就是假的。所以四条钉子分别钉：干净 ⇒ None / 脏 ⇒ 挂 ref /
sha 能复原 / ref 段名不以 `.` 开头（git 拒）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import snapshot  # noqa: E402


def _git(*a: str, cwd: Path) -> str:
    r = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    """建一个临时 git 仓（一个 commit），返回其路径。"""
    d = tmp_path / "repo"
    d.mkdir()
    _git("init", "-q", cwd=d)
    _git("config", "user.email", "t@t", cwd=d)
    _git("config", "user.name", "t", cwd=d)
    (d / "a.txt").write_text("v1\n", encoding="utf-8")
    _git("add", "a.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)
    return d


def test_clean_tree_returns_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert snapshot.take_snapshot(repo, why="测", root=tmp_path) is None


def test_dirty_tree_creates_ref(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("v2\n", encoding="utf-8")  # 制造未提交改动
    ref = snapshot.take_snapshot(repo, why="测", root=tmp_path)
    assert ref is not None
    assert ref.startswith("refs/snapshots/")
    sha = snapshot.snapshot_sha(ref, repo)
    assert sha, f"ref {ref} 指向的 sha 取不到"
    assert _git("cat-file", "-t", sha, cwd=repo) == "commit"  # 是个 commit 对象


def test_snapshot_sha_restores_content(tmp_path: Path) -> None:
    """★ 命根子：打快照 → 改工作区 → 用 sha 把原内容取回来。"""
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("要被救回的内容\n", encoding="utf-8")
    ref = snapshot.take_snapshot(repo, why="落地前", root=tmp_path)
    assert ref is not None
    sha = snapshot.snapshot_sha(ref, repo)
    # 模拟"被覆盖"：改成别的内容
    (repo / "a.txt").write_text("被覆盖了\n", encoding="utf-8")
    assert (repo / "a.txt").read_text(encoding="utf-8") == "被覆盖了\n"
    # 从快照 sha 复原
    _git("checkout", sha, "--", "a.txt", cwd=repo)
    assert (repo / "a.txt").read_text(encoding="utf-8") == "要被救回的内容\n"


def test_ref_name_has_no_leading_dot(tmp_path: Path) -> None:
    """★ 踩过的坑：ref 段名不许以 `.` 开头（`.wt-invgate-…` 被 git 拒）。"""
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    ref = snapshot.take_snapshot(repo, why="测", name=".wt-invgate", root=tmp_path)
    assert ref is not None
    seg = ref[len("refs/snapshots/"):]
    assert not seg.startswith("."), seg


def test_derive_name_strips_leading_dot(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert snapshot.derive_name(repo, root=repo) == "root"
    sub = tmp_path / ".wt" / "invgate"
    sub.mkdir(parents=True)
    assert snapshot.derive_name(sub, root=tmp_path) == "wt-invgate"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
