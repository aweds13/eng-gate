"""钉子测试：`tools/card_doc_budget.py`（卡 164 / T-G264 · §17 第 5~6 条）。

判据（先红后绿）：
- 结构预算：超长 ⇒ 红 + 指出哪一节超多少；合规 ⇒ 绿；
- 指针：不带指针 ⇒ 红；指针指到不存在 ⇒ 红；指针指到真文件 / 真 sha ⇒ 绿。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import card_doc_budget as budget  # noqa: E402

# ---------------------------------------------------------- 合规（绿）
_CP_OK = """\
**做了什么**：把卡 X 推进 git。

**真读数**：
- 测试 62 passed。
- 审计通过。

**★ 老实说**：
1. 边界 A 没验。
2. 边界 B 没验。
"""

_GAPS_OK = """\
1. 边界：X 没做，见 tests/test_card_doc_budget.py:30。
2. 边界：Y 没做，见 tools/card_doc_budget.py:60。
"""

_CL_OK = """\
## 2026-10-03 —— 标题（T-Gxxx / 卡 xxx）

- 一行摘要。
"""


def test_compliant_doc_passes_budget_and_pointers(tmp_path):
    needle = tmp_path / "tests" / "test_card_doc_budget.py"
    needle.parent.mkdir(parents=True)
    needle.write_text("# ok\n", encoding="utf-8")
    gp = _GAPS_OK.replace("tests/test_card_doc_budget.py:30", f"{needle.relative_to(tmp_path)}:1")
    problems = budget.check_budget(checkpoint=_CP_OK, gaps=gp, changelog=_CL_OK)
    assert problems == [], problems
    ptr_problems = budget.check_pointers(gp, root=tmp_path)
    assert ptr_problems == [], ptr_problems


# ---------------------------------------------------------- 结构预算（红）
def test_checkpoint_too_long_is_red_with_exact_overflow():
    cp = "\n".join(f"行 {i}" for i in range(budget.MAX_CHECKPOINT_LINES + 5))
    problems = budget.check_budget(checkpoint=cp, gaps="1. ok。", changelog="## x\n")
    assert any("checkpoint" in p and "超 5 行" in p for p in problems), problems


def test_too_many_gaps_items_is_red():
    items = "\n".join(f"{i}. 条目 {i}。" for i in range(1, budget.MAX_GAPS_ITEMS + 2))
    problems = budget.check_budget(checkpoint="", gaps=items, changelog="")
    assert any("gaps" in p and "超 1 条" in p for p in problems), problems


def test_a_gap_item_too_many_lines_is_red():
    gap = "1. " + "\n".join(f"   续行 {i}" for i in range(budget.MAX_GAP_LINES + 2))
    problems = budget.check_budget(checkpoint="", gaps=gap, changelog="")
    assert any("第 1 条" in p and "超" in p for p in problems), problems


def test_too_many_honest_items_is_red():
    honest = "**★ 老实说**：\n" + "\n".join(
        f"{i}. 条目 {i}。" for i in range(1, budget.MAX_HONEST_ITEMS + 2)
    )
    problems = budget.check_budget(checkpoint=honest, gaps="", changelog="")
    assert any("老实说" in p and "超 1 条" in p for p in problems), problems


def test_changelog_too_long_is_red():
    cl = "\n".join(f"行 {i}" for i in range(budget.MAX_CHANGELOG_LINES + 3))
    problems = budget.check_budget(checkpoint="", gaps="", changelog=cl)
    assert any("changelog" in p and "超 3 行" in p for p in problems), problems


def test_problem_names_the_section_not_just_says_too_long():
    problems = budget.check_budget(checkpoint="x\n" * 999, gaps="", changelog="")
    assert problems, problems
    assert all("超" in p for p in problems), problems


# ---------------------------------------------------------- 指针（红）
def test_gap_without_pointer_is_red(tmp_path):
    gp = "1. 这条只说没做，不指哪里。"
    problems = budget.check_pointers(gp, root=tmp_path)
    assert any("没有指针" in p for p in problems), problems


def test_pointer_to_nonexistent_file_is_red(tmp_path):
    gp = "1. 见 nonexistent/path.py:10。"
    problems = budget.check_pointers(gp, root=tmp_path)
    assert any("不存在" in p for p in problems), problems


def test_pointer_to_nonexistent_sha_is_red(tmp_path):
    gp = "1. 见提交 deadbee。"
    problems = budget.check_pointers(gp, root=tmp_path)
    assert any("没有对象" in p or "不存在" in p for p in problems), problems


# ---------------------------------------------------------- 指针（绿）
def test_pointer_to_real_file_is_green(tmp_path):
    f = tmp_path / "tools" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text("# ok\n", encoding="utf-8")
    gp = f"1. 见 {f.relative_to(tmp_path)}:1。"
    assert budget.check_pointers(gp, root=tmp_path) == []


@pytest.mark.skipif(
    not ROOT.joinpath(".git").exists(), reason="不在 git 仓里"
)
def test_pointer_to_real_sha_is_green():
    r = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        pytest.skip("git 不可用")
    sha = r.stdout.strip()
    gp = f"1. 见提交 {sha}。"
    assert budget.check_pointers(gp, root=ROOT) == []


# ---------------------------------------------------------- 真实仓库回归
def test_real_checkpoints_fit_budget():
    """真实交接片段的**行数**应在预算内（回归：别让判据一上线就退回一堆既有文书）。

    ★ 「老实说 ≤ 4 条」既有 9 份超标（5~6 条）= **既有债**（判据上线后新写的不能再超）；
      这里只拦行数（既有全部 ≤ 60），老实说超标收集成已知债快照打印、不 fail。
    """
    d = ROOT / "复盘" / "交接.d"
    if not d.is_dir():
        pytest.skip("无交接片段目录")
    over_lines: list[str] = []
    honest_debt: list[str] = []
    for f in sorted(d.glob("T-G*.md")):
        cp = f.read_text(encoding="utf-8")
        if len(cp.splitlines()) > budget.MAX_CHECKPOINT_LINES:
            over_lines.append(f.name)
        honest = budget._split_honest(cp)
        if len(honest) > budget.MAX_HONEST_ITEMS:
            honest_debt.append(f"{f.name}: {len(honest)} 条")
    assert not over_lines, f"行数超 60: {over_lines}"
    if honest_debt:
        print(f"[已知债] 老实说超 4 条的既有文书: {honest_debt}")
