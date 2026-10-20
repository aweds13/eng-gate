r"""`tools/_repo.py` 的钉子（卡 A306 · T-AG420）—— 根解析的**唯一实现**。

为什么值当测：根偏一寸，`tools/` 里所有工具的读数就全偏 —— 而且偏得**看不出来**（读数自洽地
指向另一棵树）。所以三条解析链各钉一条：显式 > git 顶层 > 本文件上级；另外把 `tools/pipe.cmd`
那只薄壳也**真跑一遍**（`shift` 会连 `%0` 一起移，`%~dp0` 取早了就指到别处 —— 已经真踩过一次）。

★ 只造临时目录 + `git init`，**不碰真仓、不连网、不动世界**。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import _repo  # noqa: E402 —— 需要先把 tools/ 挂上

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="没有 git：这条判据问的就是它")
needs_windows = pytest.mark.skipif(os.name != "nt", reason="pipe.cmd 是 Windows 批处理")


def _init(directory: Path) -> Path:
    subprocess.run([GIT or "git", "init", "-q", str(directory)], check=True,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    return directory


# ------------------------------------------------------------------ 1. 三条解析链


@needs_git
def test_explicit_root_wins_over_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """显式 `--root` **说了算**：当前目录在别的 git 仓里，也不许被 `--show-toplevel` 抢走。"""
    here = _init(tmp_path / "here")
    other = tmp_path / "other"        # ★ 故意**不是** git 仓：显式给了就得认，不回头问 git
    other.mkdir()
    monkeypatch.chdir(here)
    assert _repo.repo_root(other) == other.resolve()
    assert _repo.repo_root(str(other)) == other.resolve()   # 字符串同价（CLI 就传字符串）


@needs_git
def test_git_toplevel_from_a_subdirectory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没给显式 ⇒ 问 git：在**子目录**里跑也要回到仓根（不是「我躺的那一格」）。"""
    repo = _init(tmp_path / "repo")
    (repo / "tools").mkdir()
    monkeypatch.chdir(repo / "tools")
    assert _repo.repo_root() == repo.resolve()
    assert _repo.git_toplevel() == repo.resolve()


@needs_git
def test_fallback_is_the_directory_above_tools(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """不在任何 git 仓里 ⇒ 退回「本文件上一级」，**不抛**（工具得能起来）。"""
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    monkeypatch.chdir(plain)
    if _repo.git_toplevel() is not None:
        pytest.skip(f"测试临时目录落在 git 仓里（{plain}）—— 这条问的是「算不出」")
    assert _repo.repo_root() == TOOLS.parent


def test_blank_explicit_means_not_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空串 / 空白等于没给（CLI 的 `--root ""` 不许解析成当前目录）。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.setattr(_repo, "git_toplevel", lambda cwd=None: None)
    assert _repo.repo_root("") == TOOLS.parent
    assert _repo.repo_root("   ") == TOOLS.parent


# ------------------------------------------------------------------ 2. 薄壳真跑一遍


@needs_windows
@needs_git
def test_pipe_cmd_forwards_to_the_tool(tmp_path: Path) -> None:
    """`pipe.cmd wb_daily --root <空仓>` ⇒ 真转发到 `python -X utf8 tools/wb_daily.py`。

    ★ 钉两件事：① 参数**原样**透传（`--root` 后面那串路径含空格也算原样）；② 退出码不吞。
      从前那只壳在 `shift` 之后才取 `%~dp0` —— `%0` 跟着移，路径指到别处，这里当场咬。
    """
    repo = _init(tmp_path / "empty repo")        # ★ 目录名带空格：顺带钉引号
    argv = f'"{TOOLS / "pipe.cmd"}" wb_daily --root "{repo}"'
    done = subprocess.run(argv, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "还没有卡池" in done.stdout, done.stdout


@needs_windows
def test_pipe_cmd_rejects_unknown_tool(tmp_path: Path) -> None:
    """工具名不存在 ⇒ 当场说清、退 2（不退 0 装成功，也不让 python 扔一屏 traceback）。"""
    argv = f'"{TOOLS / "pipe.cmd"}" no_such_tool_xyz'
    done = subprocess.run(argv, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert "no such tool" in done.stdout.lower(), done.stdout
