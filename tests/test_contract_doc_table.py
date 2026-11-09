r"""对账表装牙（卡 E101 · T-AG610）：表里每一格都由工具现读，漂了就红。

## 为什么有它

`复盘/契约-判据对账.md` 那张表回答「13 条契约段各自有没有判据盯着」。表的真源是
`tools/contract_audit.py` 的 `CONTRACTS`（现读文档取行号、现跑判据取 rc），
但**表本身没人守**：`test_real_repo_audit_has_expected_shape` 只核 13 / judge_ok 10 /
no_judge 3 三个总数，表里一格都不核。实测漂了 9 处（源行号 2 / 判据格 5 / 原句节选 2），
文档还写着「8 条」而真数是 12。

本文件钉 `--check-doc`：不跑判据（秒级），只逐格比对源行号 / 原句子串 / 判据标签 / 段标题条数。

## 为什么新开一份文件

`tests/test_contract_audit.py` 的 `test_real_repo_audit_has_expected_shape` 在
`tests/conftest.py` 的 `CHAIN_MANIFEST` 里（`tests/test_gate_split.py` 钉「打标集合 == 清单」），
改名或改断言会连带那两条红。所以新钉子只许进本文件。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import contract_audit as ca  # noqa: E402

RULE = "- **契约一**：派活之前就得停下，不许静默\n"
ANCHOR_A = "派活之前就得停下"
ANCHOR_B = "不许静默"

JUDGE = ("pytest", "tests/x.py::test_a")


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rules.md").write_text(
        "# 规则\n\n" + RULE, encoding="utf-8", newline="\n"
    )
    return tmp_path


def _contracts() -> list[ca.Contract]:
    return [
        ca.Contract(cid="CX-01", source=("src/rules.md", ANCHOR_A), judge=JUDGE),
        ca.Contract(
            cid="CX-02",
            source=("src/rules.md", ANCHOR_B),
            no_judge="现在装不了：得先把现状改到满足，属另一条卡",
        ),
    ]


_HEAD = """## 契约段清单（{total} 条）

### 有判据的（{jn} 条 · judge_ok）

| ID | 源 | 原句（节选） | 判据 | 当场跑一次的读数 |
|---|---|---|---|---|
{judge}

### 只有话的（{nn} 条 · no_judge）

| ID | 源 | 原句（节选） | 为什么现在装不了 |
|---|---|---|---|
{nojudge}

## 读数（现跑）

```
=== 契约段 ↔ 判据对账（卡 217 · T-G330）：{total} 条 ===
分布：judge_ok {jn} / no_judge {nn} / judge_red 0 / source_missing 0
```
"""

ROW_JUDGE = "| CX-01 | `src/rules.md:3` | 派活之前就得停下 | `tests/x.py::test_a` | rc=0 |"
ROW_NO = (
    "| CX-02 | `src/rules.md:3` | 派活之前就得停下，不许静默 "
    "| 现在装不了：得先把现状改到满足 |"
)


def _doc(*, judge: str = ROW_JUDGE, nojudge: str = ROW_NO, jn: int = 1,
         nn: int = 1, total: int = 2) -> str:
    return _HEAD.format(judge=judge, nojudge=nojudge, jn=jn, nn=nn, total=total)


def _check(tmp_path: Path, text: str) -> tuple[int, list[str], Path]:
    doc = tmp_path / "table.md"
    doc.write_text(text, encoding="utf-8", newline="\n")
    rc, problems = ca.check_doc(doc, _contracts(), _tree(tmp_path))
    return rc, problems, doc


def _joined(problems: list[str]) -> str:
    return "\n".join(problems)


# ---------------------------------------------------------------- 真仓
def test_real_table_matches_the_contracts_now() -> None:
    """真仓那张表现在必须逐格对上（本卡修好之后）。"""
    rc, problems = ca.check_doc(ROOT / ca.DOC_TABLE, ca.CONTRACTS, ROOT)
    assert rc == 0, "对账表与 CONTRACTS 现读值不一致：\n" + _joined(problems)
    assert problems == []


def test_contract_ids_are_the_thirteen_documented_ones() -> None:
    """表的 13 条 = CONTRACTS 的 13 条：id 集合与顺序都不动（本卡不碰 CONTRACTS）。"""
    want = [f"CX-{i:02d}" for i in range(1, 14)]
    assert [c.cid for c in ca.CONTRACTS] == want


def test_real_table_lists_every_contract_exactly_once() -> None:
    rows, counts, total = ca.parse_table((ROOT / ca.DOC_TABLE).read_text(encoding="utf-8"))
    ids = [r.cid for r in rows]
    assert sorted(ids) == [c.cid for c in ca.CONTRACTS]
    assert len(ids) == len(set(ids))
    assert counts == {"judge": 10, "no_judge": 3}
    assert total == 13


# ---------------------------------------------------------------- 逐格
def test_line_number_drift_is_named(tmp_path: Path) -> None:
    rc, problems, _ = _check(tmp_path, _doc(judge=ROW_JUDGE.replace("rules.md:3", "rules.md:4")))
    assert rc == 1
    assert "CX-01" in _joined(problems) and "源" in _joined(problems)
    assert "src/rules.md:3" in _joined(problems), _joined(problems)


def test_judge_label_drift_is_named(tmp_path: Path) -> None:
    rc, problems, _ = _check(tmp_path, _doc(judge=ROW_JUDGE.replace("test_a", "test_b")))
    assert rc == 1
    assert "判据" in _joined(problems) and "tests/x.py::test_a" in _joined(problems)


def test_judge_label_without_the_tests_prefix_is_named(tmp_path: Path) -> None:
    """裸 `x.py::test_a` 不算数：真值带 `tests/` 前缀（表里那 5 处就是这么漂的）。"""
    bare = ROW_JUDGE.replace("`tests/x.py::test_a`", "`x.py::test_a`")
    rc, problems, _ = _check(tmp_path, _doc(judge=bare))
    assert rc == 1
    assert "判据" in _joined(problems)


def test_excerpt_that_is_not_in_the_document_is_named(tmp_path: Path) -> None:
    drifted = ROW_JUDGE.replace("派活之前就得停下", "派活之前必须先停下来再说")
    rc, problems, _ = _check(tmp_path, _doc(judge=drifted))
    assert rc == 1
    assert "原句" in _joined(problems)


def test_too_short_excerpt_is_named(tmp_path: Path) -> None:
    """一个词冒充原句不算（长度 ≥ 8）——「派活之前」是子串但太短。"""
    short = ROW_JUDGE.replace("派活之前就得停下", "派活之前")
    rc, problems, _ = _check(tmp_path, _doc(judge=short))
    assert rc == 1
    assert "原句" in _joined(problems) and "短" in _joined(problems)


def test_section_count_drift_is_named(tmp_path: Path) -> None:
    rc, problems, _ = _check(tmp_path, _doc(jn=2))
    assert rc == 1
    assert "有判据的" in _joined(problems)


def test_total_count_drift_is_named(tmp_path: Path) -> None:
    rc, problems, _ = _check(tmp_path, _doc(total=3))
    assert rc == 1
    assert "读数块" in _joined(problems)


def test_missing_contract_in_the_table_is_named(tmp_path: Path) -> None:
    rc, problems, _ = _check(tmp_path, _doc(nojudge="", nn=1))
    assert rc == 1
    assert "CX-02" in _joined(problems) and "没有这一条" in _joined(problems)


def test_row_in_the_wrong_section_is_named(tmp_path: Path) -> None:
    """CX-02 是 no_judge，写进「有判据的」段就得红（别拿段位置冒充有判据）。"""
    misplaced = ROW_NO[:-2] + " |  |"
    text = _doc(judge=ROW_JUDGE + "\n" + misplaced, nojudge="", jn=2, nn=0)
    rc, problems, _ = _check(tmp_path, text)
    assert rc == 1
    assert "CX-02" in _joined(problems)


# ---------------------------------------------------------------- 宽容 / 结构
def test_same_as_previous_row_is_allowed(tmp_path: Path) -> None:
    """「同 CX-01」指向前一条的 live 值 —— 表里 CX-04 就是这么写的，必须放行。"""
    contracts = _contracts() + [
        ca.Contract(cid="CX-03", source=("src/rules.md", ANCHOR_B), judge=JUDGE)
    ]
    row = "| CX-03 | `src/rules.md:3` | 派活之前就得停下，不许静默 | 同 CX-01 | rc=0 |"
    doc = tmp_path / "table.md"
    doc.write_text(
        _doc(judge=ROW_JUDGE + "\n" + row, nojudge=ROW_NO, jn=2, nn=1, total=3),
        encoding="utf-8", newline="\n",
    )
    rc, problems = ca.check_doc(doc, contracts, _tree(tmp_path))
    assert rc == 0, _joined(problems)


def test_excerpt_markup_is_normalised(tmp_path: Path) -> None:
    """`**` / 反引号 / 行首 `>` / 多重空白都归一 —— 表里允许带 markdown 记号。"""
    row = "| CX-01 | `src/rules.md:3` | > **派活之前就得停下** | `tests/x.py::test_a` | rc=0 |"
    rc, problems, _ = _check(tmp_path, _doc(judge=row))
    assert rc == 0, _joined(problems)


def test_column_count_mismatch_is_unparsable(tmp_path: Path) -> None:
    """行列数不符 = 表坏了（退 2），不是「漂」（退 1）。"""
    bad = "| CX-01 | `src/rules.md:3` | 派活之前就得停下 | rc=0 |"
    rc, problems, _ = _check(tmp_path, _doc(judge=bad))
    assert rc == 2
    assert "格" in _joined(problems)


def test_missing_section_is_unparsable(tmp_path: Path) -> None:
    text = _doc().split("### 只有话的")[0]
    rc, problems, _ = _check(tmp_path, text)
    assert rc == 2
    assert "缺段" in _joined(problems)


def test_missing_table_file_is_unparsable(tmp_path: Path) -> None:
    rc, problems = ca.check_doc(tmp_path / "nope.md", _contracts(), tmp_path)
    assert rc == 2
    assert "读不出来" in _joined(problems)


def test_custom_doc_path_is_checked(tmp_path: Path) -> None:
    """`--doc` 换一份表也照核（合成树上验，不靠真仓）。"""
    rc, problems, doc = _check(tmp_path, _doc())
    assert doc.name == "table.md" and rc == 0, _joined(problems)
    doc.write_text(_doc(jn=5), encoding="utf-8", newline="\n")
    assert ca.check_doc(doc, _contracts(), tmp_path)[0] == 1


# ---------------------------------------------------------------- CLI
def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "contract_audit.py"), *args],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, **ca.NO_WINDOW,
    )


def test_cli_check_doc_is_green_on_the_real_table() -> None:
    proc = _cli("--check-doc")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[OK ]" in proc.stdout


def test_cli_check_doc_reports_json_and_nonzero_on_drift(tmp_path: Path) -> None:
    doc = tmp_path / "table.md"
    doc.write_text(_doc(jn=9), encoding="utf-8", newline="\n")
    proc = _cli("--check-doc", "--json", "--doc", str(doc))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False and payload["problems"]


def test_check_doc_does_not_run_judges(tmp_path: Path) -> None:
    """秒级的判据：判据格指到一条不存在的测试也不该真去跑它（否则真仓那 13 条要几分钟）。"""
    row = "| CX-01 | `src/rules.md:3` | 派活之前就得停下 | `tests/x.py::test_a` | rc=0 |"
    rc, problems, _ = _check(tmp_path, _doc(judge=row))
    assert (rc, problems) == (0, [])
    assert "tests/x.py" not in (tmp_path / "src" / "rules.md").read_text(encoding="utf-8")
