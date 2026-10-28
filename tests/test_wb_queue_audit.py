r"""队列登记审计（`tools/wb_queue_audit.py`，卡 216 · T-G329）的测试。

为什么值当测：这条判据治的是卡 197 当场抓到的那类病 —— **已落的卡没有队列条目**
（`193`/`194`/`195`/`196` 落在地上、队列里一行都没有 ⇒ 没有 status 可翻、别的工具都看不见它们），
加上「一卡一号」破了会让人误判"这张卡落了"。判错的两个方向都贵：漏报 ⇒ 卡继续隐身；
误报 ⇒ 把登记/收尾提交当成漏登记、天天假红。

★ 六条钉子（含反例）：① 孤儿号 ⇒ 红并点名（号 + 短 sha + 标题）；② 簿记号 ⇒ **不许**报错；
③ 一号多用 ⇒ 红；④ 干净仓 ⇒ 绿；⑤ 没有 git ⇒ 优雅跳过；⑥ 一批孤儿 ⇒ **全列出来**（证明它数得清）。
另加：done 卡也照查（反向保护③）、CLI 两种输出 + 退出码。
★ 只造**假仓 + 假队列**（`git init` + 临时 TOML），不起服务、不碰真仓库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_queue_audit  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
from pool.plan import Card  # noqa: E402 —— 造最小卡用（Card 是队列的数据模型）

# ---------------------------------------------------------------- 夹具

def _mk_card(cid: str, *, task: str = "T-G9x", status: str = "pending") -> Card:
    """一张最小卡（只填审计要用的字段）。"""
    return Card(id=cid, task=task, title="样卡", tree="", spec="",
                files=("a.py",), risk="low", status=status)


def _backlog(*cards: Card) -> wb_queue_audit.Backlog:
    return wb_queue_audit.Backlog(reviewed="abc1234", cards=tuple(cards))


def _git_init(tmp_path: Path) -> Path:
    """造一个空 git 仓。"""
    repo = tmp_path / "gitrepo"
    repo.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "nail@example.invalid"],
                ["git", "config", "user.name", "nail"],
                ["git", "config", "commit.gpgsign", "false"]):
        # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
        # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
        subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace")
    return repo


def _commit(repo: Path, task: str, *, subject: str = "test", path: str = "f.txt") -> str:
    """造一笔含 `Task:` trailer 的提交；`path` 决定它改了哪个文件（簿记号钉子用）。

    返回短 sha。
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(task + "\n", encoding="utf-8")
    # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
    # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
    subprocess.run(["git", "add", "-A"], cwd=str(repo), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    subprocess.run(["git", "commit", "-q", "-m", f"{subject}\n\nTask: {task}"],
                   cwd=str(repo), env=env, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    done = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=str(repo), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return (done.stdout or "").strip()


# ------------------------------------------------ ① 孤儿号 ⇒ 红并点名

def test_orphan_mark_is_reported(tmp_path: Path) -> None:
    """① 号在 git 里、队列里没有、又不是簿记号 ⇒ 红并点名（号 + 短 sha + 标题）。"""
    repo = _git_init(tmp_path)
    sha = _commit(repo, "T-G999", subject="feat: 一张没登记的卡")
    result = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert not result.skipped and not result.clean
    assert len(result.orphans) == 1, result
    finding = result.orphans[0]
    assert finding.mark == "T-G999"
    assert finding.commits[0].short == sha
    assert "没登记的卡" in finding.commits[0].subject


def test_many_orphans_are_all_listed(tmp_path: Path) -> None:
    """⑥ 反例：一批孤儿号 ⇒ **全列出来**（证明它数得清，不是只报第一条）。"""
    repo = _git_init(tmp_path)
    marks = ["T-G901", "T-G902", "T-G903", "T-G904", "T-G905"]
    for mark in marks:
        _commit(repo, mark, path=f"{mark}.txt")
    result = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert sorted(f.mark for f in result.orphans) == sorted(marks), result.orphans


# ------------------------------------------------ ② 簿记号 ⇒ 不许报错

def test_queue_touching_mark_is_not_reported(tmp_path: Path) -> None:
    """② 簿记号（改过队列文件的号）⇒ **不许**当"漏登记"报错（反向保护①）。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G777", subject="docs(队列): 登记一张新卡",
            path=wb_queue_audit.QUEUE_RELPATH)
    result = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert result.orphans == (), result.orphans


def test_same_mark_touching_queue_is_protected(tmp_path: Path) -> None:
    """② 同一条口径的结构钉：号是否被保护，取决于它有没有改过队列文件。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G777", path="plain.txt")             # 没碰队列 ⇒ 孤儿
    plain = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert [f.mark for f in plain.orphans] == ["T-G777"]
    repo2 = _git_init(tmp_path / "r2")
    _commit(repo2, "T-G777", path=wb_queue_audit.QUEUE_RELPATH)  # 碰了队列 ⇒ 簿记号
    touched = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo2)
    assert touched.orphans == (), touched.orphans


# ------------------------------------------------ ③ 一号多用 ⇒ 红

def test_multi_commit_marks_are_reported(tmp_path: Path) -> None:
    """③ 队列卡的 task 号出现在多笔提交上 ⇒ 红并点名卡号 + 各笔 sha。"""
    repo = _git_init(tmp_path)
    first = _commit(repo, "T-G888", path="a.txt")
    second = _commit(repo, "T-G888", path="b.txt")
    result = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert len(result.multi) == 1, result
    finding = result.multi[0]
    assert finding.card == "007" and finding.mark == "T-G888"
    assert {c.short for c in finding.commits} == {first, second}


def test_done_card_is_still_checked(tmp_path: Path) -> None:
    """反向保护③：队列里 `status` 是任何值的卡都照查（这不是落地状态判据）。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G888", path="a.txt")
    _commit(repo, "T-G888", path="b.txt")
    result = wb_queue_audit.audit(
        _backlog(_mk_card("007", task="T-G888", status="done")), repo=repo)
    assert len(result.multi) == 1, result
    assert result.multi[0].card == "007"


# ------------------------------------------------ ④ 干净仓 ⇒ 绿

def test_clean_repo_is_green(tmp_path: Path) -> None:
    """④ 队列覆盖了 git 里所有号、且各只一笔 ⇒ 绿。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G888", path="a.txt")
    _commit(repo, "T-G999", path="b.txt")
    result = wb_queue_audit.audit(
        _backlog(_mk_card("007", task="T-G888"), _mk_card("008", task="T-G999")), repo=repo)
    assert result.clean, result
    assert result.findings == ()


# ------------------------------------------------ ⑤ 没有 git ⇒ 优雅跳过

def test_no_git_skips_gracefully(tmp_path: Path) -> None:
    """⑤ 没有 git 时优雅跳过（不崩、不当通过也不当红）。"""
    repo = tmp_path / "nogit"
    repo.mkdir()
    result = wb_queue_audit.audit(_backlog(_mk_card("007", task="T-G888")), repo=repo)
    assert result.skipped
    assert result.findings == ()
    assert not result.clean            # 跳过 ≠ 干净（不当通过）


# ------------------------------------------------ CLI：两种输出 + 退出码

def test_cli_report_and_exit_code_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`--report`：有漏 ⇒ 人读文本点名，退出码非零。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G999", subject="feat: 孤儿")
    backlog = tmp_path / "workbacklog.toml"
    backlog.write_text(
        '[base]\nreviewed = "abc"\n[[cards]]\nid = "007"\ntask = "T-G888"\n'
        'title = "t"\ntree = ""\nspec = ""\nfiles = ["a.py"]\nstatus = "pending"\n',
        encoding="utf-8")
    code = wb_queue_audit.main(["--backlog", str(backlog), "--repo", str(repo), "--report"])
    out = capsys.readouterr().out
    assert code == wb_queue_audit.EXIT_FINDINGS
    assert "T-G999" in out and "孤儿号" in out


def test_cli_json_and_exit_code_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`--json`：干净 ⇒ JSON 里 `clean=true`、退出码 0。"""
    repo = _git_init(tmp_path)
    _commit(repo, "T-G888", path="a.txt")
    backlog = tmp_path / "workbacklog.toml"
    backlog.write_text(
        '[base]\nreviewed = "abc"\n[[cards]]\nid = "007"\ntask = "T-G888"\n'
        'title = "t"\ntree = ""\nspec = ""\nfiles = ["a.py"]\nstatus = "pending"\n',
        encoding="utf-8")
    code = wb_queue_audit.main(["--backlog", str(backlog), "--repo", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == wb_queue_audit.EXIT_CLEAN
    assert payload["clean"] is True and payload["orphans"] == []


def test_cli_no_git_exit_code_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """没有 git ⇒ 退出码是「跳过」（既不是干净 0、也不是有漏 1）。"""
    repo = tmp_path / "nogit"
    repo.mkdir()
    backlog = tmp_path / "workbacklog.toml"
    backlog.write_text(
        '[base]\nreviewed = "abc"\n[[cards]]\nid = "007"\ntask = "T-G888"\n'
        'title = "t"\ntree = ""\nspec = ""\nfiles = ["a.py"]\nstatus = "pending"\n',
        encoding="utf-8")
    code = wb_queue_audit.main(["--backlog", str(backlog), "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == wb_queue_audit.EXIT_SKIPPED
    assert "跳过" in out
