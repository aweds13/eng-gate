"""不变量台账核查器（卡 144 · T-G243）+ 条款台账核查器（卡 162 · T-G262）的反例钉子。

这个工具的价值全在**判据**上：台账是一张「安全主张 → 判据 → 反例钉子 → 覆盖到没覆盖」的表，
它自己**不许烂掉**（指向不存在的路径 / 用例名）。所以这张测试按卡 §验收 钉五条：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | `judge` 路径不存在 ⇒ `--check` **咬**并点名那一行 | 指针烂了没人管 |
| ② | `nail` 的用例名不存在（真测试文件里查不到）⇒ **咬**并点名 | 钉子缺了没人管 |
| ③ | ★ **真台账**（`复盘/不变量台账.toml`）`--check` 必须通过 | 防「账本写得太随意」 |
| ④ | ★ `--missing` 如实列没关的缝（哨兵 INV-72；INV-14 已关不许再出现） | 关了的不许还挂 missing |
| ⑤ | `missing` **不算错**：全 `missing` 时 `--check` 仍退 0 | 状态与错误分开 |
| ⑥ | ★ 核查器**真进了门表**（`invariants`→`wb_invariants.py --check`） | 有机器落点 |

卡 162（T-G262）加条款台账的那半 —— 钉核查器对 `unjudgeable` 的判据：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ⑦ | `unjudgeable` 无 `note` ⇒ `--clauses` **咬**并点名 | ★ 本卡最关键：不许「用人话糊过去」 |
| ⑧ | `covered` 无 `judge` / `nail` ⇒ **咬** | covered 必须有判据 + 钉子 |
| ⑨ | ★ **真条款台账**（`复盘/条款台账.toml`）`--clauses` 必须通过 | 防条款台账写得太随意 |
| ⑩ | ★ 卡规格模板真有「本卡是否属视觉/布局类」那一行 | CL-02 的判据落点 |

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


def test_missing_lists_the_unclosed_seams(capsys: pytest.CaptureFixture) -> None:
    """★ `--missing` 必须**如实**列出还没关的缝，且**关了的不许再挂 missing**。

    卡 160（T-G260）之前 INV-14（「门数≠17 冒充全量门禁」）确实没关、必须露面；卡 147+160
    把它关掉之后（门数从门表现读、复核主链真查），它**不该**再出现在待验台账里。
    INV-72（一份数字手抄两处）同日仍是真欠账 ⇒ 拿它当「待验台账」的哨兵。
    """
    rc = wb.main(["--ledger", str(wb.DEFAULT_LEDGER), "--missing"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "INV-72" in out, "INV-72（数字手抄两处）真的没关，必须在待验台账里"
    assert "INV-14" not in out, "INV-14 已由卡 147/160 关掉，不许再挂 missing"


def test_checker_is_wired_into_the_gate_table() -> None:
    """⑥ ★ 核查器**真进了门表**：「新能力没进这张表，就不算做完」要有机器落点。

    反例（先红）：把 `run_gates.py` 里那道 `invariants` 门删掉 ⇒ 本用例当场红。
    """
    sys.path.append(str(ROOT / "scripts"))
    import run_gates as rg  # noqa: PLC0415 —— 需要先把 scripts/ 挂上

    jobs = dict(rg.build_jobs(quick=False, fast=False))
    assert "invariants" in jobs, "不变量核查器没进门表（那条规矩还只是一句人话）"
    cmd = jobs["invariants"]
    assert "tools/wb_invariants.py" in cmd and "--check" in cmd


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
    # ★ 2026-10-04：卡 164 给 `STATUSES` 加了 `unjudgeable` ⇒ `counts()` 会把**所有**状态
    #   都初始化出来（多一个 `unjudgeable: 0`）—— 这是有意的"诚实标记"，不是回归。
    assert wb.counts(rows) == {"covered": 2, "partial": 1, "missing": 1, "unjudgeable": 0}
    assert {row["id"] for row in wb.missing_rows(rows)} == {"B", "C"}


# ==================================================================
# 卡 162 · T-G262 —— 条款台账核查器（`--clauses`）的反例钉子
# ==================================================================
#
# 与不变量台账的差异：状态集合用 `unjudgeable` 替代 `missing`，
# 且 `unjudgeable` **强制要 `note`**（「用一句人话糊过去」不许蒙混）。


def _write_clauses(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "clauses.toml"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------ ⑦ unjudgeable 无 note ⇒ 咬


def test_clauses_bites_when_unjudgeable_has_no_note(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """★ 本卡最关键的一条判据：`status = unjudgeable` 但 `note` 为空 ⇒ `--clauses` 非零退出并点名。

    反例（先红）：把 `note` 删掉 ⇒ 用例当场红。
    这条钉住的是「『机器判不了』要诚实 + 给理由」，不是「用一句人话糊过去」。
    """
    ledger = _write_clauses(tmp_path, """
[[clause]]
id = "CL-BAD"
clause = "self-test: unjudgeable without a note must bite"
judge = "-"
nail = "-"
status = "unjudgeable"
note = ""
""")
    rc = wb.main(["--ledger", str(ledger), "--clauses"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "CL-BAD" in out
    assert "unjudgeable" in out and "note" in out


def test_clauses_passes_when_unjudgeable_has_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`unjudgeable` 带 `note` ⇒ `--clauses` 退 0（诚实态不是失败）。"""
    ledger = _write_clauses(tmp_path, """
[[clause]]
id = "CL-OK"
clause = "self-test: unjudgeable with a note is honest"
judge = "-"
nail = "-"
status = "unjudgeable"
note = "因为 X 判不了"
""")
    rc = wb.main(["--ledger", str(ledger), "--clauses"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[OK ]" in out
    assert "unjudgeable 1" in out


# ------------------------------------------------------------------ ⑧ covered 无 judge / nail ⇒ 咬


def test_clauses_bites_when_covered_lacks_judge_or_nail(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`covered` 必须判据 + 钉子都在（缺任一 ⇒ 红）。"""
    ledger = _write_clauses(tmp_path, f"""
[[clause]]
id = "CL-COV1"
clause = "self-test: covered without judge"
judge = "-"
nail = "{SELF}::test_clauses_bites_when_covered_lacks_judge_or_nail"
status = "covered"
note = "self-test"

[[clause]]
id = "CL-COV2"
clause = "self-test: covered without nail"
judge = "tools/wb_invariants.py"
nail = "-"
status = "covered"
note = "self-test"
""")
    rc = wb.main(["--ledger", str(ledger), "--clauses"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "CL-COV1" in out and "judge" in out
    assert "CL-COV2" in out and "nail" in out


def test_clauses_bites_when_judge_path_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """judge 指不存在的路径 ⇒ 红（指针烂了没人管）。"""
    ledger = _write_clauses(tmp_path, f"""
[[clause]]
id = "CL-PATH"
clause = "self-test: judge path does not exist"
judge = "tools/__no_such_tool__.py::main"
nail = "{SELF}::test_clauses_bites_when_judge_path_missing"
status = "covered"
note = "self-test"
""")
    rc = wb.main(["--ledger", str(ledger), "--clauses"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "CL-PATH" in out and "judge 路径不存在" in out


# ------------------------------------------------------------------ ⑨ 真条款台账 --clauses 必须通过


def test_real_clauses_ledger_check_passes(capsys: pytest.CaptureFixture) -> None:
    """拿仓库里那份**真条款台账**跑 `--clauses`：必须退 0（防「账本写得太随意」）。"""
    assert wb.DEFAULT_CLAUSE_LEDGER.exists(), f"真条款台账不在：{wb.DEFAULT_CLAUSE_LEDGER}"
    rc = wb.main(["--clauses"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[OK ]" in out


# ----------------------------------------------- ⑩ CL-02 判据落点：卡规格模板视觉/布局那一行


def test_clause_template_has_visual_layout_row() -> None:
    """CL-02（视觉/布局改动人工过目）的判据落点：卡规格模板 §18.3 真有那一行。

    反例（先红）：把那一行从模板里删掉 ⇒ 本用例当场红 —— 人话条款停在「建议」没落地。
    """
    rules_path = ROOT / "复盘" / "外包-卡表与规矩.md"
    text = rules_path.read_text(encoding="utf-8")
    # ★ 这一行是 INV-70 那句人话从「建议写进协议」变成「卡规格模板里机器可查」的落点。
    assert "本卡是否属视觉/布局类" in text, (
        "卡规格模板里没有「本卡是否属视觉/布局类」这一行 —— "
        "CL-02（视觉/布局改动人工过目）还停在「建议写进协议」，没落地"
    )
