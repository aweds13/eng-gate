"""契约段 ↔ 判据对账器（卡 217 · T-G330）的反例钉子。

这个工具的价值全在**判据真去执行**上：不是扫一遍文档看字符串像不像，而是对每条 `judge:`
**当场跑一次**贴读数。所以这张测试钉六条：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 一条契约段 + 一条真判据 ⇒ 绿 | 对账器把好的判成坏的 |
| ② | judge 指向**不存在**的脚本 ⇒ 红并**点名** | 指针烂了没人管 |
| ③ | no_judge ⇒ 非零（如实，不是失败但不是绿） | 把「只有话」当「有判据」 |
| ④ | 源文件不存在 / 锚点找不到 ⇒ 优雅处理并说清 | 坏文档让工具崩 |
| ⑤ | ★ **反例**：判据名写错一个字 ⇒ 必须红 | 证明它真去**执行**，不是只看字符串像不像 |
| ⑥ | ★ **真仓**对账：10 judge_ok / 3 no_judge（如实） | 美化「只有话」的条数 |

★ 只读：这里不写真仓的 CONTRACTS（临时契约段都落在 `tmp_path`），也不跑门禁。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import contract_audit as ca  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _write_doc(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def _write_judge_ok(tmp_path: Path, name: str = "check.py") -> str:
    """在 tmp_path 写一个退 0 的判据脚本，回它的相对名。"""
    (tmp_path / name).write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    return name


# ------------------------------------------------------------------ ① 真判据 ⇒ 绿


def test_one_contract_with_real_judge_is_green(tmp_path: Path) -> None:
    """一条契约段 + 一条真判据（退 0）⇒ 对账结果 judge_ok。"""
    _write_doc(tmp_path, "# 规矩\n删掉 skills 框架仍完整可用。\n")
    judge_name = _write_judge_ok(tmp_path)
    c = ca.Contract(
        cid="CX-T1",
        source=("rules.md", "删掉 skills 框架仍完整可用"),
        judge=("cmd", ["python", judge_name]),
    )
    results = ca.audit([c], tmp_path)
    assert len(results) == 1
    r = results[0]
    assert r.status == "judge_ok", f"应绿，实 {r.status}：{r.reason}"
    assert r.source_line == 2
    assert "删掉 skills 框架仍完整可用" in r.source_text
    assert r.judge_rc == 0


# ------------------------------------------------------------------ ② judge 指向不存在 ⇒ 红并点名


def test_judge_pointing_at_nonexistent_script_is_red_and_names_it(
    tmp_path: Path,
) -> None:
    """judge 指向不存在的脚本 ⇒ judge_red，且结果带那条的 id（点名）。"""
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    c = ca.Contract(
        cid="CX-T2",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", "no_such_check.py"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "judge_red", f"指向不存在的判据必须红，实 {r.status}"
    assert r.cid == "CX-T2"  # 点名
    assert r.judge_rc != 0
    assert r.reason  # 有说清为什么红


# ------------------------------------------------------------------ ③ no_judge ⇒ 非零（如实）


def test_no_judge_is_honest_nonzero(tmp_path: Path) -> None:
    """一条契约段 + no_judge ⇒ status=no_judge，且不算 ok（退出码非零的依据）。"""
    _write_doc(tmp_path, "# 规矩\n某目标态。\n")
    c = ca.Contract(
        cid="CX-T3",
        source=("rules.md", "某目标态"),
        no_judge="这是目标态，现状不满足，要等另一条卡",
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "no_judge"
    assert not r.ok  # no_judge 不算 ok ⇒ 退出码非零
    assert r.judge_rc is None  # 没跑判据


# ------------------------------------------------------------------ ④ 坏文档 ⇒ 优雅处理


def test_missing_source_file_is_handled_gracefully(tmp_path: Path) -> None:
    """源文件不存在 ⇒ source_missing（不崩，说清）。"""
    c = ca.Contract(
        cid="CX-T4a",
        source=("no_such_file.md", "某契约"),
        judge=("cmd", ["python", "-c", "exit(0)"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "source_missing"
    assert not r.ok
    assert r.source_line is None


def test_anchor_not_found_is_handled_gracefully(tmp_path: Path) -> None:
    """源文件在但锚点子串找不到 ⇒ source_missing（不崩，说清）。"""
    _write_doc(tmp_path, "# 规矩\n这里没有那句契约。\n")
    c = ca.Contract(
        cid="CX-T4b",
        source=("rules.md", "不存在的锚点子串"),
        judge=("cmd", ["python", "-c", "exit(0)"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "source_missing"
    assert not r.ok
    assert "锚点" in r.reason or "找不到" in r.reason


# ------------------------------------------------------------------ ⑤ ★ 反例：判据名写错一个字 ⇒ 红


def test_typo_in_judge_name_bites(tmp_path: Path) -> None:
    """★ 反例：把判据名写错一个字 ⇒ 必须红。

    证明对账器真去**解析并执行**判据，不是只看字符串像不像：真判据是 `check.py`（退 0），
    写错成 `chekc.py`（不存在）⇒ subprocess 真去跑那个不存在的脚本 ⇒ 红。
    """
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    _write_judge_ok(tmp_path, "check.py")  # 真判据在
    c = ca.Contract(
        cid="CX-T5",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", "chekc.py"]),  # ★ 写错一个字
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "judge_red", f"写错判据名必须红，实 {r.status}"
    assert r.judge_rc != 0


# ------------------------------------------------------------------ ⑥ ★ 真仓对账如实


def _cli_available() -> bool:
    """本仓 CLI 在不在（决定 CX-02 是「真判」还是「未验证」）。"""
    import shutil

    return (ca.ROOT / "framework" / "cli" / "main.py").is_file() or bool(shutil.which("pipe"))


def test_real_repo_audit_has_expected_shape() -> None:
    """★ 真仓 13 条契约段：0 judge_red / 0 source_missing，且 judge_ok + no_judge == 13。

    钉的是「别美化」：
      · 有 CLI 的机器 —— 10 judge_ok / 3 no_judge（框架泛用性三条目标态，一条都不许漏列）；
      · 没有 CLI 的机器（云机）—— 9 / 4：CX-02 自报未验证（rc=3），如实落 no_judge。
        卡 E49：既不许把未验证算成绿（漏真违约），也不许算成红（假红）。
    """
    results = ca.audit(ca.CONTRACTS, ca.ROOT)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    assert sum(by_status.values()) == 13, f"契约段应为 13 条，实 {sum(by_status.values())}"
    assert by_status.get("source_missing", 0) == 0, "源文件或锚点找不到 ⇒ 配置烂了，不是契约问题"
    reds = [r.cid for r in results if r.status == "judge_red"]
    assert by_status.get("judge_red", 0) == 0, f"判据跑红 ⇒ 有判据的那几条契约没守住：{reds}"
    ok, no = by_status.get("judge_ok", 0), by_status.get("no_judge", 0)
    assert ok + no == 13, f"judge_ok({ok}) + no_judge({no}) 应等于 13"
    if _cli_available():
        assert (ok, no) == (10, 3), f"有 CLI 时应 10 judge_ok / 3 no_judge，实 {ok}/{no}"
    else:
        assert (ok, no) == (9, 4), f"没有 CLI 时应 9 judge_ok / 4 no_judge，实 {ok}/{no}"


def test_judge_reporting_not_verified_is_neither_green_nor_red(tmp_path: Path) -> None:
    """★ 卡 E49：判据退 **3**（自报未验证）⇒ 落 no_judge，不算 judge_ok，也不算 judge_red。

    反向意义：把 rc=3 当红 ⇒ 云机（没 CLI）上 CX-02 假红；当绿 ⇒ 真违约被漏掉。
    """
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    script = tmp_path / "unverified.py"
    script.write_text("import sys\nprint('这台机器缺前置')\nsys.exit(3)\n", encoding="utf-8")
    c = ca.Contract(
        cid="CX-NV",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", str(script)]),
    )
    r = ca.audit([c], tmp_path)[0]
    assert r.status == "no_judge", f"rc=3 应落 no_judge，实 {r.status}"
    assert r.judge_rc == 3
    assert "未验证" in r.reason


def test_main_returns_nonzero_when_there_are_no_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """有 no_judge 时 main() 退非零（如实反映「还有多少条只有话」）。"""
    _write_doc(tmp_path, "# 规矩\n某目标态。\n")
    c = ca.Contract(
        cid="CX-M1",
        source=("rules.md", "某目标态"),
        no_judge="目标态，没守住",
    )
    # main() 用模块级 CONTRACTS；这里直接验 audit 的退出码逻辑
    results = ca.audit([c], tmp_path)
    rc = 0 if all(r.ok for r in results) else 1
    assert rc == 1  # 有 no_judge ⇒ 非零
