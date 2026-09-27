"""`tools/wb_review.py` 的分支判据三态（T-G158）—— 钉住"假 FAIL 修准了、判据没被废掉"。

## 为什么要有它（卡 064 §1 的根因）

`git rev-parse --abbrev-ref HEAD` 在**分离头指针**（detached HEAD）下返回的字面量就是 `"HEAD"`。
外包链路的每张卡都在 `.wt/<卡>` 的 detached worktree 里干活（卡规格明令"不许切分支"），
于是老判据那次比较 `"HEAD" != "line/impl-v1"` **永远**为真 → 干净提交被判 4/5。
复核器是防漏活的工具，**它说假话的次数一多，人就学会无视它**。

## 两条互补的护栏（缺一条都不算完）

1. **假 FAIL 修准**：detached + 默认期望分支 → 不报，且如实记一行（`--json` 里也看得见）；
2. **判据没废**：附着但分支不匹配 → **仍报**；detached 但显式要**别的**期望分支 → **仍报**。
   只测第 1 条的测试是**可以被"把判据删掉"骗过**的 —— 本卡 §5 的反证 C 专治这个。

## 桩打在真正被调用的地方（卡 §2.3 / §7 第 1 条）

`main()` 调用的 `git()` 是**模块级函数**，所以替身打在 `wb_review.git` 上
（`main()` 按模块全局查它）。
★ **不切分支**：worktree 里切分支会砸别的卡，也让本测试不可重入；替身直接喂
`rev-parse --abbrev-ref HEAD` 的三种返回值就够了。真跑 `audit_progress.py` 很慢
（~4 秒）且与本判据无关，所以 `audit_verdict` 也替掉。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_review as wr  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

DETACHED = "HEAD"  # `rev-parse --abbrev-ref HEAD` 在分离头指针下返回的字面量

_BODY = (
    "feat(x): 干了一件事（T-G158）\n"
    "\n"
    "正文随便写点。\n"
    "\n"
    "Task: T-G158\n"
    "Ledger: 新增 T-G158\n"
    "Gates: 全量门禁绿\n"
)

_PAYLOAD = {
    "rev": "def5678", "ok": True, "docs_sync_ok": True, "docs_sync_missing": [],
    "gates": [{"name": "pytest", "exit_code": 0}],
}


def _fake_git(branch: str):
    """把 `wb_review.git` 换成只回答 `main()` 真正会问的那几条的替身。"""
    replies = {
        ("rev-parse", "--short", "HEAD"): "abc1234",
        ("rev-parse", "--short", "abc1234^"): "def5678",
        ("log", "-1", "--format=%B", "abc1234"): _BODY,
        ("show", "--name-only", "--format=", "abc1234"): "tools/wb_review.py",
        ("show", "abc1234:gates/last.json"): json.dumps(_PAYLOAD, ensure_ascii=False),
        ("rev-parse", "--abbrev-ref", "HEAD"): branch,
        ("status", "--porcelain", "-uno"): "",
    }

    def fake(*args: str) -> str:
        assert tuple(args) in replies, f"替身没预料到这条 git 调用：{args}"
        return replies[tuple(args)]

    return fake


@pytest.fixture()
def stubbed(monkeypatch: pytest.MonkeyPatch):
    """返回一个 `run(branch, *argv)`：装好替身、跑 `main()`、回 `(退出码, stdout)`。"""

    def run(branch: str, *argv: str) -> tuple[int, str]:
        monkeypatch.setattr(wr, "git", _fake_git(branch))
        monkeypatch.setattr(wr, "audit_verdict", lambda: ([], "审计通过 ✅"))
        monkeypatch.setattr(sys, "argv", ["wb_review.py", "--rev", "HEAD", "--allow", "**", *argv])
        return _capture(wr.main)

    return run


def _capture(func) -> tuple[int, str]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = func()
    return code, buf.getvalue()


# ------------------------------------------------- ① 附着且匹配：不报（保持原样）


def test_attached_and_matching_branch_is_not_reported() -> None:
    problems, note = wr.check_branch("line/impl-v1", wr.DEFAULT_BRANCH)
    assert problems == []
    assert note == "", "附着分支没有要记的信息行"


def test_cli_passes_on_an_attached_matching_branch(stubbed) -> None:
    code, out = stubbed("line/impl-v1")
    assert code == 0, out
    assert "分支不对" not in out
    assert "[OK ] 五条全过" in out


# ------------------------------------------------- ② 附着但不匹配：必须仍报（判据不许废）


def test_attached_but_mismatched_branch_is_still_reported() -> None:
    problems, note = wr.check_branch("other-branch", wr.DEFAULT_BRANCH)
    assert any("分支不对" in p and "other-branch" in p for p in problems)
    assert note == ""


def test_cli_still_fails_on_an_attached_mismatched_branch(stubbed) -> None:
    code, out = stubbed("other-branch")
    assert code == 1, out
    assert "分支不对" in out


# ------------------------------------------------- ③ detached：跳过 + 如实记一行


def test_detached_skips_the_branch_check_and_records_it() -> None:
    problems, note = wr.check_branch(DETACHED, wr.DEFAULT_BRANCH)
    assert problems == []
    assert "detached" in note and "跳过" in note


def test_cli_passes_in_a_detached_tree_and_says_so(stubbed) -> None:
    code, out = stubbed(DETACHED)
    assert code == 0, out
    assert "分支不对" not in out
    assert "detached" in out or "分离头指针" in out, "detached 必须留下一条如实的信息行"


def test_cli_json_carries_the_detached_note(stubbed) -> None:
    """★ 机器也要读得到"为什么没报" —— `--json` 里必须有那行（卡 §2.1 第三行）。"""
    code, out = stubbed(DETACHED, "--json")
    assert code == 0, out
    verdict = json.loads(out)
    assert verdict["branch"] == DETACHED
    assert "detached" in verdict["branch_note"]


def test_cli_json_has_an_empty_note_when_attached(stubbed) -> None:
    code, out = stubbed("line/impl-v1", "--json")
    assert code == 0, out
    assert json.loads(out)["branch_note"] == ""


# ------------------------------------------------- ★ 反证 C 的机器版：判据没被废掉


def test_detached_with_an_explicit_other_branch_still_reports(stubbed) -> None:
    """★ 卡 §5 反证 C（"这是本卡的核心：别把有用的判据一起废掉"）的机器版。

    本树是 detached —— 若"detached 一律跳过"写成无条件的，`--branch main` 就**永远**不再报，
    这条判据在 detached 树里等于被删掉。所以跳过只对**默认期望分支**生效；
    显式要别的分支（如 `main`）时，detached 的树**确实不是** main → 照报。
    """
    code, out = stubbed(DETACHED, "--branch", "main")
    assert code == 1, out
    assert "分支不对" in out


def test_detached_with_branch_head_still_passes(stubbed) -> None:
    """`--branch HEAD` 与默认值都该过（卡 §7 第 3 条）—— 它不是"绕过"，是 detached 正常态。"""
    code, out = stubbed(DETACHED, "--branch", DETACHED)
    assert code == 0, out
    assert "分支不对" not in out


# ------------------------------------------------- 替身自己也得看得见东西


def test_the_stub_really_drives_the_verdict(stubbed) -> None:
    """★ 反空转：同一个替身喂两种分支给出**相反**的判决 —— 证明它真在驱动判据。

    少了这一条，替身写错（比如永远返回同一个值）会让上面三条测试**一起**变成没有牙的绿。
    """
    ok_code, _ = stubbed("line/impl-v1")
    bad_code, _ = stubbed("other-branch")
    assert (ok_code, bad_code) == (0, 1)


def test_the_stub_rejects_unexpected_git_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """替身对没预料到的 git 调用**报错**（不是静默回空串）—— 免得判据换了实现而测试假装没看见。"""
    monkeypatch.setattr(wr, "git", _fake_git("line/impl-v1"))
    with pytest.raises(AssertionError):
        wr.git("rev-parse", "--show-toplevel")
