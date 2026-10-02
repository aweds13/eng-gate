"""不变量台账核查器（`tools/wb_invariants.py`，卡 144 · T-G243）的反例钉子。

这个工具的价值全在**判据**上：台账是一张「安全主张 → 判据 → 反例钉子 → 覆盖到没覆盖」的表，
它自己**不许烂掉**（指向不存在的路径 / 用例名）。所以这张测试按卡 §验收 钉五条：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | `judge` 路径不存在 ⇒ `--check` **咬**并点名那一行 | 指针烂了没人管 |
| ② | `nail` 的用例名不存在（真测试文件里查不到）⇒ **咬**并点名 | 钉子缺了没人管 |
| ③ | ★ **真台账**（`复盘/不变量台账.toml`）`--check` 必须通过 | 防「账本写得太随意」 |
| ④ | ★ `--missing` 输出里必须有那条「门数≠17 冒充全量门禁」 | 它**真的没关**，必须在待验台账里 |
| ⑤ | `missing` **不算错**：整份台账全是 `missing` 时 `--check` 仍退 0 | 状态与错误要分开 |

★ 只读：这里不写仓库里的真台账（临时台账都落在 `tmp_path`），也不跑门禁。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_invariants as wb  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

#: 这份测试自己——nail 里指向它，保证「文件在、用例名在」这一半是真的。
SELF = "tests/test_wb_invariants.py"


def _write_ledger(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "ledger.toml"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------ ① judge 路径不存在 ⇒ 咬


def test_check_bites_when_judge_path_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`judge` 指一个不存在的路径 ⇒ `--check` 非零退出，并**点名那一行**。"""
    ledger = _write_ledger(tmp_path, f"""
[[invariant]]
id = "INV-X1"
claim = "self-test: a judge path that does not exist must bite"
judge = "tools/__no_such_tool__.py::main"
nail = "{SELF}::test_check_bites_when_judge_path_is_missing"
status = "covered"
note = "self-test"
""")
    rc = wb.main(["--ledger", str(ledger), "--check"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "INV-X1" in out and "judge 路径不存在" in out
    assert "tools/__no_such_tool__.py" in out


# ------------------------------------------------------------------ ② nail 用例名不存在 ⇒ 咬


def test_check_bites_when_nail_case_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`nail` 指向真测试文件里**没有的**用例名 ⇒ `--check` 非零退出，并点名那一行。"""
    ledger = _write_ledger(tmp_path, f"""
[[invariant]]
id = "INV-X2"
claim = "self-test: a nail case name that is not in the test file must bite"
judge = "tools/wb_invariants.py"
nail = "{SELF}::test_no_such_case_xyz"
status = "covered"
note = "self-test"
""")
    rc = wb.main(["--ledger", str(ledger), "--check"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "INV-X2" in out and "用例名" in out
    assert "test_no_such_case_xyz" in out


# ------------------------------------------------------------------ ③ 真台账 --check 必须通过


def test_real_ledger_check_passes(capsys: pytest.CaptureFixture) -> None:
    """拿仓库里那份**真台账**跑 `--check`：必须退 0（防「账本写得太随意」）。"""
    assert wb.DEFAULT_LEDGER.exists(), f"真台账不在：{wb.DEFAULT_LEDGER}"
    rc = wb.main(["--ledger", str(wb.DEFAULT_LEDGER), "--check"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[OK ]" in out


# ------------------------------------------------------------------ ④ --missing 里必须有那条


def test_missing_lists_the_gate_count_backdoor(capsys: pytest.CaptureFixture) -> None:
    """★ `--missing` 的输出里**必须**有「门数≠17 冒充全量门禁」——它就是真的没关。"""
    rc = wb.main(["--ledger", str(wb.DEFAULT_LEDGER), "--missing"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "门数≠17 冒充全量门禁" in out
    assert "INV-14" in out


# ------------------------------------------------------------------ ⑤ missing 不算错


def test_all_missing_ledger_still_passes_check(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """整份台账全是 `missing`（判据 / 钉子都写 `-`）时 `--check` **仍退 0**：状态 ≠ 错误。"""
    ledger = _write_ledger(tmp_path, """
[[invariant]]
id = "INV-M1"
claim = "self-test: all-missing ledger is honest, not broken"
judge = "-"
nail = "-"
status = "missing"
note = "self-test"

[[invariant]]
id = "INV-M2"
claim = "self-test: the second all-missing row"
judge = "-"
nail = "-"
status = "partial"
note = "self-test"
""")
    rc = wb.main(["--ledger", str(ledger), "--check"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "missing 2" in out or "missing 1" in out


# ------------------------------------------------------------------ 附：核判据与分组函数


def test_judge_path_parsing_takes_the_path_only() -> None:
    """`judge` 里带命令时**只取路径**（命令不真跑）——`scripts/x.py 一句命令` → `scripts/x.py`。"""
    assert wb.judge_path("tools/wb_review.py::check_trailers") == "tools/wb_review.py"
    assert wb.judge_path("scripts/run_gates.py 跑全量门禁") == "scripts/run_gates.py"


def test_grouping_and_counts_split_states() -> None:
    rows = [
        {"id": "A", "status": "covered"},
        {"id": "B", "status": "missing"},
        {"id": "C", "status": "partial"},
        {"id": "D", "status": "covered"},
    ]
    assert wb.counts(rows) == {"covered": 2, "partial": 1, "missing": 1}
    assert {row["id"] for row in wb.missing_rows(rows)} == {"B", "C"}
