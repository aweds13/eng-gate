"""红单归并（卡 E4 / T-AG446）：同因只打一行，计数与代表用例都得对。

## 为什么有这张测试

门禁红了 **34 条**时，屏幕上是 788 KB 日志 + 34 条并列的 `FAILED …`；人要自己把 34 条
读成「其实是 3 个原因」。`tools/failure_group.py` 把那一层读数压成 ≤3 行 —— 但一条
**永远回「3 行」**的归并等于注释，所以这里先钉住：

- 今天的 34 红样例（`tests/fixtures/pytest-34fail.txt`，脱敏）→ **恰好 3 类**、计数 `12/12/10`；
- 屏幕 `report_lines` **恰好 3 行**（没超过 3 类就不许出现「另有 K 类」）；
- **按异常归并、不按文件归并**：同一个文件里两种异常 → 两类（卡 §不许做 的反面钉子）；
- 超过 3 类才追加「…另有 K 类见日志」；
- `Failed:` / 裸 `assert` 这两种异常行也认得出。

## 边界（如实写）

样例是**脱敏样例**：当天的 `gates/logs/pytest.log` 已被后续绿跑覆盖，仓库里只剩
`gates/diag/land-A324-5.log` 的汇总行（`34 failed, 2898 passed`）与 14 条用例名；
样例按那次失败的真实形状（`-q` + xdist、`E   …` + 结尾位置行）与真实用例名重建，
**不是**逐字节复制的原日志。判据依赖的是 pytest 输出**格式**，不是那天的具体字节。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import failure_group as fg  # noqa: E402
import run_gates as rg  # noqa: E402 —— 走 finish_gate 的真路径（不跑整趟门禁）

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pytest-34fail.txt"

# 样例里三类的期望计数（多的一类在前）
EXPECTED_COUNTS = [12, 12, 10]


def _sample() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_still_has_34_failed_lines() -> None:
    """样例自身先验一道：34 红是真数出来的，不是写在文案里的。"""
    failed = [ln for ln in _sample().splitlines() if ln.startswith("FAILED ")]
    assert len(failed) == 34


def test_today_34_fails_collapse_to_three_groups() -> None:
    """今天的 34 红 → 3 类，计数 12/12/10（卡 §判据 5）。"""
    groups = fg.group_failures(fg.parse_pytest_output(_sample()))
    assert len(groups) == 3, [g.as_dict() for g in groups]
    assert [g.count for g in groups] == EXPECTED_COUNTS
    assert sum(g.count for g in groups) == 34


def test_each_group_carries_exception_message_and_representative() -> None:
    """每类都带「异常 + 首句 + 首个仓内文件 + 代表用例」，且代表用例在组内。"""
    groups = fg.group_failures(fg.parse_pytest_output(_sample()))
    for g in groups:
        assert g.exception in {"AttributeError", "AssertionError", "ModuleNotFoundError"}
        assert g.message
        assert g.file.startswith("tests/")
        assert g.representative in g.nodeids
        assert g.representative == g.nodeids[0]


def test_report_is_exactly_three_lines_with_counts() -> None:
    """屏幕报告恰好 3 行，每行有 `× N`（卡 §验收：输出恰好 3 行 + 每行有计数）。"""
    lines = fg.summarize(_sample())
    assert len(lines) == 3, lines
    for ln in lines:
        assert ln.startswith("× "), ln
        assert "  ← tests/" in ln, ln
    # 没超过 3 类：不许出现「另有 K 类」
    assert not any("另有" in ln for ln in lines)


def test_grouping_is_by_exception_not_by_file() -> None:
    """反向钉子：同一个文件里的两种异常 → 两类（按文件归并就会错成 1 类）。"""
    text = """
================================== FAILURES ===================================
_____________________ test_one _____________________

    def test_one() -> None:
>       assert 1 == 2
E       AssertionError: assert 1 == 2

tests\\test_same.py:10: AssertionError
_____________________ test_two _____________________

    def test_two() -> None:
>       raise ValueError("boom")
E       ValueError: boom

tests\\test_same.py:20: ValueError

=========================== short test summary info ===========================
FAILED tests/test_same.py::test_one - AssertionError: assert 1 == 2
FAILED tests/test_same.py::test_two - ValueError: boom
"""
    groups = fg.group_failures(fg.parse_pytest_output(text))
    assert len(groups) == 2
    assert {g.exception for g in groups} == {"AssertionError", "ValueError"}


def test_fourth_class_gets_the_extra_line() -> None:
    """超过 3 类才追加「…另有 K 类见日志」；K 数是**没打出来的那几类**。"""
    groups = [
        fg.FailureGroup(
            "AssertionError", f"reason {i}", "tests/test_x.py", [f"tests/test_x.py::t{i}"]
        )
        for i in range(4)
    ]
    lines = fg.report_lines(groups)
    assert len(lines) == 4
    assert lines[-1] == "…另有 1 类见日志"


def test_bare_assert_and_failed_prefix_are_recognized() -> None:
    """`E   assert 0 == 2`（无异常名）算 AssertionError；`Failed:` 单独算一类。"""
    assert fg._split_exception("assert 0 == 2") == ("AssertionError", "assert 0 == 2")
    assert fg._split_exception("Failed: DID NOT RAISE <class 'Exception'>")[0] == "Failed"


def test_falls_back_to_summary_when_failures_section_is_absent() -> None:
    """只有 summary、没有 FAILURES 段时不许伪造：首句取 `- 原因`，文件取 nodeid 路径。"""
    text = (
        "FAILED tests/test_x.py::test_a - TypeError: bad operand\n"
        "FAILED tests/test_x.py::test_b - TypeError: bad operand\n"
    )
    failures = fg.parse_pytest_output(text)
    assert [f.message for f in failures] == ["bad operand", "bad operand"]
    assert fg.group_failures(failures)[0].count == 2


# ---------------------------------------------------------------- 收尾接进真路径


def _fake_pytest(tmp_path: Path) -> list[str]:
    """假门：把样例原样吐到 stdout 再退 1（形状与真 pytest 一样，不真跑用例）。"""
    script = tmp_path / "fake_pytest.py"
    script.write_text(
        "import pathlib, sys\n"
        "sys.stdout.write(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    return [sys.executable, "-X", "utf8", str(script), str(FIXTURE)]


def test_finish_gate_prints_three_lines_and_records_groups(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """★ 卡 §判据 2/3/4：走 `finish_gate` 真路径 —— 屏幕 ≤3 行、明细进 items、原日志全量落盘。"""
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")
    proc, t0, why = rg.start_gate("pytest", _fake_pytest(tmp_path))
    assert proc is not None, why
    item = rg.finish_gate("pytest", proc, t0, 60)
    out = capsys.readouterr().out

    assert item["exit_code"] == 1
    groups = item["pytest_failure_groups"]
    assert isinstance(groups, list) and len(groups) == 3
    printed = [ln for ln in out.splitlines() if ln.strip().startswith("× ")]
    assert len(printed) == 3, out[-800:]
    assert any("× 12" in ln for ln in printed)
    # 原始输出**一个字节都不少**地落盘（卡 §不许做：日志必须全）
    log = (tmp_path / "logs" / "pytest.log").read_text(encoding="utf-8")
    assert log.count("FAILED ") >= 34
    assert "ModuleNotFoundError" in log


def test_other_gates_keep_the_old_tail(tmp_path: Path, monkeypatch, capsys) -> None:
    """反向钉子：归并**只**作用于 pytest —— 别的门失败仍打旧的尾部 12 行。"""
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")
    proc, t0, why = rg.start_gate("ruff", _fake_pytest(tmp_path))
    assert proc is not None, why
    item = rg.finish_gate("ruff", proc, t0, 60)
    out = capsys.readouterr().out

    assert "pytest_failure_groups" not in item
    assert not any(ln.strip().startswith("× ") for ln in out.splitlines())
    assert "这道门的输出尾部" in out
