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
    # text=True 必给 encoding：云机 cp936 解码中文会崩，本机 utf-8 看不出来。
    # errors="replace"：宁可拿到带替换符的中文，也不要整条炸掉。
    r = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False,
    )
    if r.returncode != 0:
        pytest.skip("git 不可用")
    sha = (r.stdout or "").strip()
    gp = f"1. 见提交 {sha}。"
    assert budget.check_pointers(gp, root=ROOT) == []


@pytest.mark.skipif(
    not ROOT.joinpath(".git").exists(), reason="不在 git 仓里"
)
def test_numeric_short_sha_is_still_a_pointer(tmp_path):
    """★ 回归（2026-10-14 主树真红过一次）：短 sha **恰好纯数字**时，它仍是指针。

    病根：`_find_pointers` 的启发式要求 sha 里**至少有一个 `a`~`f`**（免得把正文里的
    普通数字当指针）。可提交的短 sha 有 `(10/16)**7 ≈ 3.7%` 的概率**纯数字** ——
    2026-10-14 主树 HEAD 恰好是 `2051255` ⇒ `test_pointer_to_real_sha_is_green` **必红**，
    **跟改了什么无关**，而且**任何收口都过不去**（门禁在卡树里跑，卡树 HEAD 也是它）。

    钉的是"纯数字候选要**实测**、是 git 对象才算指针"，**不是**"数字都算指针"：
    同一串数字在**没有**这个对象的仓库里，照旧不算指针（见断言 ②）。
    """
    # ① 一个**真实存在**的纯数字短 sha（本仓 2026-10-14 那笔，仍在历史里可达）⇒ 必须算指针
    assert budget.check_pointers("1. 见提交 2051255。", root=ROOT) == []
    # ② 同一串数字，在**没有**这个对象的仓库里 ⇒ 不许算指针（不然就是把「数字」当「指针」）
    assert budget.check_pointers("1. 见提交 2051255。", root=tmp_path) == [
        "gaps 第 1 条没有指针（须带文件路径 / commit sha / 快照 id）"]


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


# ---------------------------------------------------------- _selfcheck 接线（卡 193 / T-G293）
# 四条反例钉子：判据接进 stage_card._selfcheck 后，坏文书当场退回、合规文书放行。
# 判据真源只在 tools/card_doc_budget.py；_selfcheck 只透传正文、不重写判据。
from pool import stage_card as _stage_card  # noqa: E402


def _crlf(text: str) -> bytes:
    """纯 CRLF 字节（_selfcheck 第③条要求三个共享文档纯 CRLF）。"""
    return text.encode("utf-8").replace(b"\n", b"\r\n")


def _compliant_wt(tmp_path: Path) -> Path:
    """造一个让 _selfcheck 前 4 条都过的工作树。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "复盘").mkdir()
    (tmp_path / "docs" / "traceability.toml").write_bytes(
        _crlf('[entries]\n\n[entries."T-G293"]\nid = "T-G293"\nstatus = "done"\n'))
    (tmp_path / "docs" / "changelog.md").write_bytes(_crlf("## 2026-10-11 标题\n"))
    (tmp_path / "复盘" / "交接-重构进度.md").write_bytes(_crlf("# 交接\n"))
    return tmp_path


def _compliant_gaps(wt: Path) -> str:
    """一条带真文件指针的合规 gap（在 wt 下造指针指向的文件）。"""
    needle = wt / "tools" / "ok.py"
    needle.parent.mkdir(parents=True, exist_ok=True)
    needle.write_text("# ok\n", encoding="utf-8")
    return f"1. 边界 X 没做，见 {needle.relative_to(wt)}:1。"


def _stub_subprocess_for_selfcheck(monkeypatch) -> None:
    """_selfcheck 第④条要跑 tools/sync_docs.py（tmp_path 里没有）⇒ stub 成过；
    check_pointers 的 git cat-file ⇒ stub 成失败（sha 不存在，钉子③用得上）。"""
    real = subprocess.run

    def fake(cmd, **kwargs):                       # noqa: ANN001, ANN202
        cmd = list(cmd)
        if any("sync_docs.py" in c for c in cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "git" in cmd and "cat-file" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: no git")
        return real(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake)


def test_selfcheck_rejects_over_budget_checkpoint(tmp_path, monkeypatch):
    """① 反例：checkpoint 61 行 > 预算 60 ⇒ _selfcheck 报出哪一节超多少。"""
    wt = _compliant_wt(tmp_path)
    _stub_subprocess_for_selfcheck(monkeypatch)
    cp = "\n".join(f"行 {i}" for i in range(budget.MAX_CHECKPOINT_LINES + 1))
    bad = _stage_card._selfcheck(wt, cp_text=cp, gaps_text=_compliant_gaps(wt), cl_text=_CL_OK)
    assert any("checkpoint" in b and "超" in b for b in bad), bad


def test_selfcheck_rejects_gap_without_pointer(tmp_path, monkeypatch):
    """② 反例：gaps 一条不带指针 ⇒ _selfcheck 报出来。"""
    wt = _compliant_wt(tmp_path)
    _stub_subprocess_for_selfcheck(monkeypatch)
    bad = _stage_card._selfcheck(wt, cp_text=_CP_OK, gaps_text="1. 这条只说没做，不指哪里。",
                                 cl_text=_CL_OK)
    assert any("没有指针" in b for b in bad), bad


def test_selfcheck_rejects_pointer_to_nonexistent(tmp_path, monkeypatch):
    """③ 反例：指针指向不存在的东西 ⇒ _selfcheck 报出来。"""
    wt = _compliant_wt(tmp_path)
    _stub_subprocess_for_selfcheck(monkeypatch)
    bad = _stage_card._selfcheck(wt, cp_text=_CP_OK, gaps_text="1. 见 no/such.py:1。",
                                 cl_text=_CL_OK)
    assert any("不存在" in b for b in bad), bad


def test_selfcheck_passes_compliant_doc(tmp_path, monkeypatch):
    """④ 反例：合规文书 ⇒ _selfcheck 全绿（别把正常文书也拦了）。"""
    wt = _compliant_wt(tmp_path)
    _stub_subprocess_for_selfcheck(monkeypatch)
    bad = _stage_card._selfcheck(wt, cp_text=_CP_OK, gaps_text=_compliant_gaps(wt), cl_text=_CL_OK)
    assert bad == [], bad
