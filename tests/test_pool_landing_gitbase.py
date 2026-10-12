r"""`tools/pool/landing.py` 的卡 192（T-G292）钉子 —— 主干保护 + 镜像路径。

★ 钉的两条都是"结构性保护"：
- `main_tree_offenders`：主树跟踪文件的改动且不在白名单 ⇒ 列出来（收口链前置拒）；
- `mirror_remote`：镜像路径不许写死（环境变量优先 / 相对 ROOT 探测默认 / 都没有 ⇒ None）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import landing  # noqa: E402


def _git(*a: str, cwd: Path) -> str:
    r = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    _git("init", "-q", cwd=d)
    _git("config", "user.email", "t@t", cwd=d)
    _git("config", "user.name", "t", cwd=d)
    (d / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=d)
    _git("commit", "-q", "-m", "init", cwd=d)
    return d


# ---------------------------------------------------------------- main_tree_offenders


def test_clean_main_tree_has_no_offenders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(landing, "ROOT", repo)
    assert landing.main_tree_offenders([]) == []


def test_offender_in_allow_is_not_offender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """白名单里的改动不算 offender（--tree . 时工人产物在主树、且在 --allow 里 ⇒ 放行）。"""
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
    monkeypatch.setattr(landing, "ROOT", repo)
    assert landing.main_tree_offenders(["tracked.txt"]) == []


def test_offender_outside_allow_is_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 主树有跟踪文件的改动且不在白名单 ⇒ 列出来（拒）。"""
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
    monkeypatch.setattr(landing, "ROOT", repo)
    offenders = landing.main_tree_offenders(["别的文件.py"])
    assert len(offenders) == 1
    assert "tracked.txt" in offenders[0]


def test_untracked_files_are_not_offenders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未跟踪文件不算（-uno）—— 用户自己的笔记常躺在仓库根。"""
    repo = _repo(tmp_path)
    (repo / "用户的笔记.md").write_text("x\n", encoding="utf-8")  # 未跟踪
    monkeypatch.setattr(landing, "ROOT", repo)
    assert landing.main_tree_offenders([]) == []


# ---------------------------------------------------------------- mirror_remote


def test_mirror_remote_env_var_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    mirror = tmp_path / "mirror.git"
    mirror.mkdir()
    monkeypatch.setattr(landing, "ROOT", repo)
    monkeypatch.setenv("TF_MIRROR_REMOTE", str(mirror))
    assert landing.mirror_remote() == mirror


def test_mirror_remote_env_var_missing_path_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(landing, "ROOT", repo)
    monkeypatch.setenv("TF_MIRROR_REMOTE", str(tmp_path / "不存在.git"))
    assert landing.mirror_remote() is None


def test_mirror_remote_default_relative_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 不写死绝对路径：默认位置 = ROOT.parent.parent / backup-engineering.git。"""
    repo = _repo(tmp_path)
    monkeypatch.setattr(landing, "ROOT", repo)
    monkeypatch.delenv("TF_MIRROR_REMOTE", raising=False)
    default = repo.parent.parent / "backup-engineering.git"
    default.mkdir(exist_ok=True)
    assert landing.mirror_remote() == default


def test_mirror_remote_nothing_configured_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(landing, "ROOT", repo)
    monkeypatch.delenv("TF_MIRROR_REMOTE", raising=False)
    # 确保默认位置不存在
    default = repo.parent.parent / "backup-engineering.git"
    if default.exists():
        import shutil
        shutil.rmtree(default)
    assert landing.mirror_remote() is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
