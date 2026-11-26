"""写死 sha 的锚点 + 批量取数不把 NUL 当台账号（卡 E163 · T-AG699）。

## 为什么有它（2026-11-26 两个真红）

镜像仓（aweds13/eng-gate）的历史被 filter-repo 重写过：**内容一字不改，sha 全变**。
那棵树上四条红的根因是两类：

1. 判据里**写死**一笔历史 sha（eaeb3923 / e3641bb9… / 2051255）⇒ 镜像里
   fatal: invalid object name。判据钉的本来是「那一笔的形状」，不是「那个 sha 还在」。
2. tools/pytest_select.py::log_batch 把 -z 的记录分隔符当成了台账号：没有
   Task: trailer 的提交，%x1f 后面紧跟的就是 \x00 ⇒ task == "\x00"，而逐笔读的
   git_task() 回空串 ⇒ assert '\x00' == ''。源仓最近几笔**每笔都有** trailer，
   所以这个 bug 只在重写过 / 没有 trailer 的历史上才露头。

## 判什么

- anchor()：本仓是对象 ⇒ 原样返回写死的值（源仓行为逐字不变）；不是对象 ⇒ 按
  Task: trailer 反查；都查不到 ⇒ **原样返回**（让原来的报错照旧出现，不洗白）。
- find_by_task()：同一台账号不止一笔时取**最老**那笔（补规格 / 重跑落地不该顶替它）。
- numeric_short_sha()：从**当前**历史现取一笔纯数字短 sha，而不是钉住某一笔。
- log_batch()：没有 trailer 的提交，台账号必须是空串 —— 与 git_task() 逐笔一致。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import git_anchor
from tools import pytest_select as ps

ROOT = Path(__file__).resolve().parent.parent

#: 谁也认不出来的 sha —— 用它证明「查不到时**原样返回**」，而不是被洗成某个看着像对的值。
GHOST = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _git(args: list[str], cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout


def _commit(repo: Path, msg: str, path: str, text: str) -> str:
    """往夹具仓里写一个文件并提交；返回这笔的全 sha。"""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
          "commit", "-q", "-m", msg], repo)
    return _git(["rev-parse", "HEAD"], repo).strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """一个两笔提交的夹具仓：第一笔带 Task trailer，第二笔**不带**。"""
    _git(["init", "-q", "-b", "main"], tmp_path)
    _commit(tmp_path, "first\n\nTask: T-AG900\n", "a.txt", "a\n")
    _commit(tmp_path, "second without trailer\n", "b.txt", "b\n")
    return tmp_path


# ------------------------------------------------------------------ 锚点


def test_anchor_keeps_the_recorded_sha_when_it_is_an_object() -> None:
    """源仓行为逐字不变：写死的那笔还在 ⇒ 必须原样用写死的值。"""
    rev = _git(["log", "--format=%h", "-1"], ROOT).strip()
    assert rev, "拿不到 git 历史 ⇒ 这条判据判不了"
    assert git_anchor.anchor(rev, "T-NOSUCH-TASK", ROOT) == rev


def test_anchor_falls_back_to_the_task_trailer(repo: Path) -> None:
    """写死的 sha 不在（镜像仓）⇒ 按 Task trailer 反查，拿到那一笔的全 sha。"""
    first = _git(["rev-parse", "HEAD^"], repo).strip()
    assert git_anchor.anchor(GHOST, "T-AG900", repo) == first
    assert git_anchor.anchor("eaeb3923", "T-AG900", repo) == first


def test_anchor_returns_the_recorded_value_when_nothing_matches(repo: Path) -> None:
    """查不到就**原样返回** —— 让 invalid object name 照旧出现，不把查不到洗成绿。"""
    assert git_anchor.anchor(GHOST, "T-NOSUCH-TASK", repo) == GHOST
    assert git_anchor.exists(GHOST, repo) is False


def test_find_by_task_prefers_the_oldest_commit(repo: Path) -> None:
    """同一台账号不止一笔时取**最老**那笔：后补的提交不许顶替「那一笔自己的形状」。"""
    oldest = _git(["rev-parse", "HEAD^"], repo).strip()
    _commit(repo, "late addendum\n\nTask: T-AG900\n", "c.txt", "c\n")
    newest = _git(["rev-parse", "HEAD"], repo).strip()
    assert newest != oldest
    assert git_anchor.find_by_task("T-AG900", repo) == oldest
    assert git_anchor.find_by_task("T-NOSUCH-TASK", repo) == ""


def test_numeric_short_sha_is_a_real_object() -> None:
    """纯数字短 sha 是 (10/16)**7 约 3.7% 的概率 —— 判据要现取，不能钉住某一笔。"""
    sha = git_anchor.numeric_short_sha(ROOT)
    if not sha:
        pytest.skip("本仓历史里没有纯数字短 sha —— 这条判据的前提不成立")
    assert sha.isdigit()
    assert git_anchor.exists(sha, ROOT)


# ------------------------------------------------- 批量取数不把 NUL 当台账号


def test_log_batch_reads_a_missing_trailer_as_empty_task(repo: Path) -> None:
    """★ 回归：没有 Task: trailer 的提交，台账号必须是空串（不是记录分隔符）。

    病根：git log -z 在 %x1f 之后紧跟 \x00；task.strip() 不剥 NUL ⇒ task == "\x00"，
    与逐笔读的 git_task()（空串）对不上。源仓最近几笔每笔都有 trailer，所以这条 bug
    只在重写过 / 没有 trailer 的历史上露头（镜像 4 条红之一）。
    """
    revs = [r for r in _git(["log", "--format=%h", "-2"], repo).splitlines() if r]
    assert len(revs) == 2, revs
    batch = ps.log_batch(2, repo)
    for rev in revs:
        assert rev in batch, rev
        task, files = batch[rev]
        assert "\x00" not in task, (rev, repr(task))
        assert task == ps.git_task(rev, repo), rev
        assert list(files) == ps.git_changed(rev, repo), rev
    # 最新那笔确实没有 trailer ⇒ 空串；它上一笔有 ⇒ 台账号照旧读出来。
    assert batch[revs[0]][0] == ""
    assert batch[revs[1]][0] == "T-AG900"
