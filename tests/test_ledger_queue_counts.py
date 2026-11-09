r"""卡 E100 · T-AG609 —— 立卡那一笔顺手把队列卡数跟上（钉子）。

判据原文见 `复盘/卡/卡E100-证据形态与队列卡数.md`（计划建）。这些钉子钉的是**实测过的一次白烧**：
E98 立卡（`36eb59f3`）只提交了台账，`docs/subsystems/pool/README.md` 里的
「队列卡数 | 345 张」没跟着变 ⇒ 下一张卡落地的腿②刚才报红
（`[FAIL] 第 87 行：应为 '| 队列卡数 | 346 张（333 done / 13 pending） |'`），
只好单开一笔 `796ea840 fix(docs): 队列卡数跟上 E98 立卡` 补上。

口径只有一条：**立卡写台账的那一笔，如果这棵树里有生成器和 README，就重算并一起提交**。
不做的（故意的）：不在这里算队列卡数（那是 `scripts/gen_pool_readme.py` 的唯一真源），
不把 README 上**别人的**未提交改动扫进这一笔，不因为派生文档出问题就把卡丢掉。

跑法（必须带 `--no-cov`：覆盖率门 `fail-under=70` 会把新建测试读成「覆盖率掉了」）：

    python -X utf8 -m pytest tests/test_ledger_queue_counts.py -q -o addopts= --no-cov
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import ledger  # noqa: E402  —— tools/ 已经在 sys.path 上

if TYPE_CHECKING:
    from collections.abc import Iterator

README_REL = "docs/subsystems/pool/README.md"
GEN_REL = "scripts/gen_pool_readme.py"

CARD_BODY = (
    '[base]\r\nreviewed = "00000000"\r\n\r\n'
    "[[cards]]\r\n"
    'id = "C1"\r\n'
    'task = "T-AG900"\r\n'
    'title = "第 1 张"\r\n'
    'tree = ""\r\n'
    'spec = "x/C1.md"\r\n'
    'files = ["src/c1.py"]\r\n'
    'status = "done"\r\n'
).encode()

README_INITIAL = b"| \xe9\x98\x9f\xe5\x88\x97\xe5\x8d\xa1\xe6\x95\xb0 | 1 \xe5\xbc\xa0\xef\xbc\x880 pending\xef\xbc\x89 |\r\n"  # noqa: E501

#: 生成器**桩**：只管「把台账的卡数写进 README」。真生成器算得对不对不是这张卡的事
#: （那是 `tests/test_pool_readme_counts.py` 的钉子）；这张卡只问**立卡笔有没有叫它**。
_GEN = r'''import argparse
import pathlib
import sys

p = argparse.ArgumentParser()
p.add_argument("--check", action="store_true")
p.add_argument("--root", default=None)
a = p.parse_args()
root = pathlib.Path(a.root or ".").resolve()
with open(root / "gen_calls.log", "a", encoding="utf-8") as log:
    log.write("check\n" if a.check else "write\n")
raw = (root / "docs" / "workbacklog.toml").read_text(encoding="utf-8")
total = raw.count("[[cards]]")
pending = raw.count('status = "pending"')
want = f"| 队列卡数 | {total} 张（{pending} pending） |\r\n".encode("utf-8")
readme = root / "docs" / "subsystems" / "pool" / "README.md"
have = readme.read_bytes()
if a.check:
    if have != want:
        print("[FAIL] README 与现算不一致")
        sys.exit(1)
    print("[OK  ] 一致")
    sys.exit(0)
if have == want:
    print("[OK  ] 已是最新，未写盘")
    sys.exit(0)
readme.write_bytes(want)
print("[OK  ] 写了 README")
'''

#: 生成器桩：直接失败（写模式也退 3）。
_GEN_BROKEN = '''import sys
print("[FAIL] 生成器自己坏了")
sys.exit(3)
'''

#: 生成器桩：写盘成功、`--check` 却说不一致（自检这一层要挡住）。
_GEN_CHECK_BAD = r'''import argparse
import pathlib
import sys

p = argparse.ArgumentParser()
p.add_argument("--check", action="store_true")
p.add_argument("--root", default=None)
a = p.parse_args()
root = pathlib.Path(a.root or ".").resolve()
readme = root / "docs" / "subsystems" / "pool" / "README.md"
if a.check:
    print("[FAIL] 写完之后自己判不一致")
    sys.exit(1)
readme.write_bytes(b"| queue | 999 |\r\n")
print("[OK  ] 写了 README")
'''


# --------------------------------------------------------------------------- 夹具
def _git(repo: pathlib.Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert done.returncode == 0, f"git {args} 失败：{done.stderr}"
    return done.stdout


def _mk_repo(tmp: pathlib.Path, *, gen: str | None = _GEN, readme: bool = True) -> pathlib.Path:
    """最小仓库：一份 CRLF 台账 +（可选）生成器桩 +（可选）README。"""
    repo = tmp / "repo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "e100@example.invalid")
    _git(repo, "config", "user.name", "e100")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "docs" / "workbacklog.toml").write_bytes(CARD_BODY)
    (repo / ".gitignore").write_text("gen_calls.log\n", encoding="utf-8")
    if gen is not None:
        (repo / "scripts").mkdir(parents=True)
        (repo / GEN_REL).write_text(gen, encoding="utf-8")
    if readme:
        (repo / "docs" / "subsystems" / "pool").mkdir(parents=True)
        (repo / README_REL).write_bytes(README_INITIAL)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _add(repo: pathlib.Path, cid: str = "C2", *, commit: bool = True) -> None:
    ledger.add_card(repo, id=cid, task="T-AG900", title=f"卡 {cid}",
                    tree=f".wt/{cid}", spec=f"x/{cid}.md",
                    files=[f"tools/{cid}.py"], commit=commit)


def _head_files(repo: pathlib.Path) -> list[str]:
    out = _git(repo, "show", "--name-only", "--format=", "HEAD")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _readme(repo: pathlib.Path) -> str:
    return (repo / README_REL).read_bytes().decode("utf-8")


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    yield _mk_repo(tmp_path)


# =============================================== 判据 1：重算并**同一笔**提交
def test_the_queue_count_rides_along_in_the_same_commit(repo: pathlib.Path,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    """判据 1：台账与 README 在**同一笔**提交里，README 里的卡数已经变了。"""
    before = _readme(repo)
    _add(repo)
    shown = _head_files(repo)
    assert "docs/workbacklog.toml" in shown, shown
    assert README_REL in shown, f"README 没跟这一笔走：{shown}"
    after = _readme(repo)
    assert after != before, "README 一个字节都没变 —— 生成器根本没被叫"
    assert "2 张" in after and "1 pending" in after, after
    assert "另开一笔" in capsys.readouterr().out


def test_the_count_is_written_from_the_tree_that_was_just_written(repo: pathlib.Path) -> None:
    """判据 1 的配套：README 读的是**写完台账之后**的树（少这一步就会写回旧卡数）。"""
    _add(repo)
    cards = tomllib.loads((repo / "docs" / "workbacklog.toml").read_text(encoding="utf-8"))
    total = len(cards["cards"])
    assert f"| 队列卡数 | {total} 张" in _readme(repo)


def test_the_generator_is_asked_to_check_what_it_wrote(repo: pathlib.Path) -> None:
    """判据 1 的配套：写完要**自检**一次（写盘腿与自检腿成对，E78 的老口径）。"""
    _add(repo)
    calls = (repo / "gen_calls.log").read_text(encoding="utf-8").split()
    assert calls == ["write", "check"], calls


# =============================================== 判据 2：没有源就安静跳过
def test_without_the_generator_only_the_backlog_is_committed(tmp_path: pathlib.Path) -> None:
    """判据 2：这棵树里没有生成器 ⇒ 只提交台账，并**点名**跳过了什么（不静默）。"""
    repo = _mk_repo(tmp_path, gen=None)
    before = _readme(repo)
    _add(repo)
    assert _head_files(repo) == ["docs/workbacklog.toml"]
    assert _readme(repo) == before, "没有生成器却动了 README"
    assert (repo / "docs" / "workbacklog.toml").read_bytes().count(b'id = "C2"') == 1


def test_without_the_readme_only_the_backlog_is_committed(tmp_path: pathlib.Path) -> None:
    """判据 2 的另一半：生成器在、README 不在 ⇒ 同样只提交台账（最小树/假仓）。"""
    repo = _mk_repo(tmp_path, readme=False)
    _add(repo)
    assert _head_files(repo) == ["docs/workbacklog.toml"]
    assert not (repo / README_REL).exists(), "凭空造出了一份 README"


def test_the_skip_line_names_both_paths(tmp_path: pathlib.Path) -> None:
    """判据 2 的配套：跳过那一行必须点出**两个**路径，别让人以为跑过了。"""
    repo = _mk_repo(tmp_path, gen=None)
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_card.py"), "add",
         "--id", "C2", "--task", "T-AG900", "--title", "卡C2", "--tree", ".wt/C2",
         "--spec", "x/C2.md", "--file", "t.py", "--commit"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert done.returncode == 0, done.stderr
    assert GEN_REL in done.stdout and README_REL in done.stdout, done.stdout


# =============================================== 判据 3：不碰别人的脏改动
def test_a_dirty_readme_is_not_swept_into_this_commit(repo: pathlib.Path) -> None:
    """判据 3：README **本来就**有未提交改动 ⇒ 不重算、不带进这一笔。

    ★ 为什么必须有这条：主树上的 README 常常被另一个会话的落地链改到一半；
      把那份改动扫进「立卡」这一笔，等于替别人提交了他没验过的东西。
    """
    foreign = "别人改到一半的一行\r\n"
    (repo / README_REL).write_bytes(foreign.encode("utf-8"))
    _add(repo)
    assert _head_files(repo) == ["docs/workbacklog.toml"]
    assert _readme(repo) == foreign, "把别人的改动重算掉/覆盖掉了"


def test_a_dirty_readme_says_so_out_loud(repo: pathlib.Path,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    """判据 3 的配套：不重算的理由要打出来（不许静默跳过）。"""
    (repo / README_REL).write_bytes("别人\r\n".encode())
    _add(repo)
    out = capsys.readouterr().out
    assert "未提交" in out and README_REL in out, out


# =============================================== 判据 4：派生文档坏了也不丢卡
def test_a_broken_generator_does_not_lose_the_card(tmp_path: pathlib.Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    """判据 4：生成器失败 ⇒ 台账照提交（卡不能丢）、README 不进这一笔、响亮地说。"""
    repo = _mk_repo(tmp_path, gen=_GEN_BROKEN)
    before = _readme(repo)
    _add(repo)
    assert _head_files(repo) == ["docs/workbacklog.toml"]
    assert _readme(repo) == before
    assert (repo / "docs" / "workbacklog.toml").read_bytes().count(b'id = "C2"') == 1
    out = capsys.readouterr().out
    assert "生成器" in out and "退 3" in out, out


def test_a_generator_that_disagrees_with_itself_is_not_committed(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """判据 4 的另一半：写盘成功但 `--check` 说红 ⇒ 不把这份 README 提交，且还原原字节。"""
    repo = _mk_repo(tmp_path, gen=_GEN_CHECK_BAD)
    before = _readme(repo)
    _add(repo)
    assert _head_files(repo) == ["docs/workbacklog.toml"]
    assert _readme(repo) == before, "自检红了还把生成的 README 留在工作区/提交里"
    assert "--check" in capsys.readouterr().out


# =============================================== 判据 5：不提交就不碰 README
def test_without_commit_the_generator_is_not_called(repo: pathlib.Path,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    """判据 5：不带 `--commit` ⇒ 一次都不叫生成器，只提示「提交时记得重算」。"""
    before = _readme(repo)
    _add(repo, commit=False)
    assert not (repo / "gen_calls.log").exists(), "没提交却动了派生文档"
    assert _readme(repo) == before
    out = capsys.readouterr().out
    assert GEN_REL in out and "--commit" in out, out


def test_the_commit_message_records_the_extra_doc(repo: pathlib.Path) -> None:
    """判据 5 的配套：提交信息里点名这一笔顺手改了哪份派生文档（读 log 时不用猜）。"""
    _add(repo)
    body = _git(repo, "log", "-1", "--format=%B")
    assert README_REL in body, body
    assert body.count("Task: T-AG900") == 1, body
