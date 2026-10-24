"""门禁收紧三条（T-G22）的测试 —— 给"新加的护栏"也上护栏。

三条是什么（都在 `scripts/audit_progress.py` 里，跟着 `audit` 这道门禁跑）：
- ⑧ `Task:` 逐条严查（必须**恰好一个**台账编号）—— 治 T-G17 那类"一路没红"；
- ⑨ 契约层覆盖（`docs/contracts` 里每条 `OP-nn` 要么挂台账卡、要么写明先不挂）——
  治"契约 53 条／台账只见 18 条"；
- ⑩ 母条/子卡一致性（规格仍 `todo` 但引用同一 N 的实现卡全 `done`）—— 治 T-G18 抓到的过期 gaps。

测试分两层：
1. **零件层**：喂合成数据，钉住"什么样的输入该报错"（真仓库里造不出一条错提交来验）；
2. **数据层**：拿**真实台账**跑一遍，断言当前 0 报错 —— 顺带把"三条检查开着且是绿的"这件事钉住，
   以后谁改台账改出缺口，这里先红，不用等到提交时被门禁拦。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_progress as ap  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

IDS = {"T-G22", "T-G13", "SR-F1.7", "T-F2"}
SEP, FIELD, REC = "\x1f", "\x1f", "\x1e"


def _rec(sha: str, subject: str, task: str) -> str:
    return f"{sha}{FIELD}{subject}{FIELD}{task}{REC}"


# ---------------------------------------------------------------- ⑧ trailer

def test_valid_single_trailer_passes() -> None:
    assert ap.parse_task_trailers(_rec("abc123", "feat: x", "T-G22"), IDS) == []


def test_multi_id_trailer_fails() -> None:
    """T-G17 的原样错误：`Task:` 里塞了 SR/OP 编号。"""
    fails = ap.parse_task_trailers(_rec("abc123", "feat: x", "T-G13 / F6 OP-27 延伸"), IDS)
    assert len(fails) == 1
    assert "恰好一个台账编号" in fails[0] and "Refs" in fails[0]


def test_two_task_trailers_fail() -> None:
    """两条 `Task:` 行 → valueonly 里是两行 → 也算"不止一个"。"""
    fails = ap.parse_task_trailers(_rec("abc123", "feat: x", "T-G13\nT-G22"), IDS)
    assert len(fails) == 1


def test_unknown_id_fails() -> None:
    fails = ap.parse_task_trailers(_rec("abc123", "feat: x", "T-ZZ"), IDS)
    assert len(fails) == 1 and "T-ZZ" in fails[0]


def test_missing_trailer_fails() -> None:
    fails = ap.parse_task_trailers(_rec("abc123", "feat: x", ""), IDS)
    assert len(fails) == 1 and "没有" in fails[0]


def test_empty_log_is_not_a_failure() -> None:
    assert ap.parse_task_trailers("", IDS) == []


# ---------------------------------------------------------------- ⑨ 契约覆盖

def _data(entries: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"entries": entries, **extra}


def test_contract_op_already_a_card_counts_as_covered() -> None:
    """`OP-1`…`OP-12` 那些**自己就是一张卡**，不该要求再挂一遍。"""
    data = _data({"OP-1": {"status": "done", "title": "新建任务"}})
    assert ap.check_contract_ops(data, ops={"OP-1"}) == []


def test_uncovered_contract_op_fails() -> None:
    errs = ap.check_contract_ops(_data({"SR-F1.7": {}}), ops={"OP-13"})
    assert len(errs) == 1 and "OP-13" in errs[0]


def test_mapping_to_unknown_card_fails() -> None:
    data = _data({"SR-F1.7": {}}, contract_ops={"T-NOPE": ["OP-13"]})
    errs = ap.check_contract_ops(data, ops={"OP-13"})
    assert any("不是台账条目" in e for e in errs)


def test_mapping_to_unknown_op_fails() -> None:
    data = _data({"SR-F1.7": {}}, contract_ops={"SR-F1.7": ["OP-999"]})
    errs = ap.check_contract_ops(data, ops={"OP-13"})
    assert any("契约里没有" in e for e in errs)


def test_duplicate_op_registration_fails() -> None:
    data = _data(
        {"SR-F1.7": {}, "T-F2": {}},
        contract_ops={"SR-F1.7": ["OP-13"], "T-F2": ["OP-13"]},
    )
    errs = ap.check_contract_ops(data, ops={"OP-13"})
    assert any("重复登记" in e for e in errs)


def test_acknowledged_op_counts_as_covered() -> None:
    data = _data({"SR-F1.7": {}}, acknowledged_ops={"OP-13": "还没做（等口径）"})
    assert ap.check_contract_ops(data, ops={"OP-13"}) == []


def test_acknowledged_unknown_op_fails() -> None:
    data = _data({"SR-F1.7": {}}, acknowledged_ops={"OP-999": "理由"})
    errs = ap.check_contract_ops(data, ops={"OP-13"})
    assert any("OP-999" in e for e in errs)


# ---------------------------------------------------------------- ⑩ 母条/子卡

N2SR = {"11": {"SR-F1.7"}}


def test_todo_spec_with_all_children_done_fails() -> None:
    data = _data(
        {
            "SR-F1.7": {"status": "todo", "title": "任务存档"},
            "T-F2": {"status": "done", "title": "完成 N 天后进档案（N11 任务存档）"},
        }
    )
    errs = ap.check_spec_child_cards(data, n2sr=N2SR)
    assert len(errs) == 1 and "SR-F1.7" in errs[0] and "T-F2" in errs[0]


def test_partial_spec_is_not_flagged() -> None:
    """partial 可以合法地"卡片都完了、还剩一句不靠卡片的缺口"（SR-F1.7 更正后就是这种）。"""
    data = _data(
        {
            "SR-F1.7": {"status": "partial", "title": "任务存档"},
            "T-F2": {"status": "done", "title": "…（N11 任务存档）"},
        }
    )
    assert ap.check_spec_child_cards(data, n2sr=N2SR) == []


def test_unfinished_child_is_not_flagged() -> None:
    data = _data(
        {
            "SR-F1.7": {"status": "todo", "title": "任务存档"},
            "T-F2": {"status": "done", "title": "…（N11 任务存档）"},
            "T-F9": {"status": "todo", "title": "…（N11 剩余）"},
        }
    )
    assert ap.check_spec_child_cards(data, n2sr=N2SR) == []


def test_spec_without_cards_is_not_flagged() -> None:
    data = _data({"SR-F3.4": {"status": "todo", "title": "多设备同步专注"}})
    assert ap.check_spec_child_cards(data, n2sr={"17": {"SR-F3.4"}}) == []


# ---------------------------------------------------------------- 数据层（真台账）

def _ledger() -> dict[str, Any]:
    with (ROOT / "docs" / "traceability.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_real_ledger_is_fully_covered_by_contract_mapping() -> None:
    data = _ledger()
    assert ap.check_contract_ops(data) == [], "台账的契约覆盖映射漏了操作（见 [contract_ops]）"
    ops = ap.collect_contract_ops()
    mapped = {op for ops_list in data.get("contract_ops", {}).values() for op in ops_list}
    acked = set(data.get("acknowledged_ops", {}))
    as_cards = {op for op in ops if op in data["entries"]}
    assert mapped | acked | as_cards == ops, "契约操作集合与三条来路对不上"


def test_real_ledger_has_no_stale_mother_entries() -> None:
    assert ap.check_spec_child_cards(_ledger()) == []


def _blank_ack_reasons(data: dict[str, Any]) -> list[str]:
    """`[acknowledged_ops]` 里**理由为空**的那些操作号（判据本身，喂合成数据也能用）。"""
    return [
        op for op, reason in (data.get("acknowledged_ops") or {}).items()
        if not (isinstance(reason, str) and reason.strip())
    ]


# ---------------------------------------------------------------- ⑫ 卡 159：用例级 test: + 反向判据


def test_case_level_test_assertion_bites_on_a_missing_case() -> None:
    """★ 卡 159（INV-32 的钉子）：`test:文件::用例名` 必须真的核**用例名**在文件里。

    红读数（实现前）：eval_assertion 对 `::` 后面那段**不认识**（老代码只做文件存在性，
    任何用例名都返回 True）⇒ 下面第一条断言当场红。
    绿读数（实现后）：真用例名 ⇒ True；编造的用例名 ⇒ False 且**点名**用例。
    `:文件`（不带用例名）**继续支持**（卡 159 明写「`:文件` 继续支持」）。
    """
    ledger_file = "test:test_audit_tightening.py"
    real_case = f"{ledger_file}::test_valid_single_trailer_passes"
    fake_case = f"{ledger_file}::test_this_case_does_not_exist_zzz"
    assert ap.eval_assertion(real_case) == (True, ap.eval_assertion(real_case)[1])
    ok, desc = ap.eval_assertion(real_case)
    assert ok, desc
    ok, desc = ap.eval_assertion(fake_case)
    assert not ok, f"编造的用例名不该通过：{desc}"
    assert "test_this_case_does_not_exist_zzz" in desc, f"要点名缺失的用例：{desc}"
    ok, _desc = ap.eval_assertion(ledger_file)
    assert ok, "裸 `test:文件` 要继续支持（卡 159）"


def test_case_ruler_is_wb_invariants_not_a_second_copy() -> None:
    """判据必须**复用** `tools/wb_invariants.py` 那把「核用例名真的存在」的尺子（不许写第二份）。"""
    wb = ap._wb_invariants()
    assert wb.__file__ is not None and str(Path(wb.__file__)).replace("\\", "/").endswith(
        "tools/wb_invariants.py"
    )
    text = "def test_a():\n    pass\n"
    assert wb.defines_case(text, "test_a")
    assert not wb.defines_case(text, "test_ab")  # 词边界：test_a 不许命中 test_ab


def test_unclaimed_changed_file_is_named() -> None:
    """★ 卡 159（INV-33 的钉子）：反向判据 —— 本笔实际改动的文件 ⊆ 台账证据指针 ∪ 豁免清单。

    红读数（实现前）：`check_claimed_files` 不存在 ⇒ AttributeError 当场红。
    绿读数（实现后）：没人声称的文件被**点名**；有 `text:` 指针 / 在豁免清单里 ⇒ 放行。
    """
    data = {"entries": {"T-X": {"status": "done", "evidence": ["text:src/a.py::def f"]}}}
    fails = ap.check_claimed_files(["src/a.py", "src/nobody_claimed_this.py"], data)
    assert len(fails) == 1 and "src/nobody_claimed_this.py" in fails[0], fails
    # 声称过（text: 指针指到）⇒ 放行
    assert ap.check_claimed_files(["src/a.py"], data) == []
    # 派生物豁免清单（模块常量）⇒ 放行
    assert ap.check_claimed_files(["docs/changelog.md", "gates/last.json"], data) == []
    # 台账自己的 `[claimed_files_exempt]` 追加豁免 ⇒ 放行
    data2 = {**data, "claimed_files_exempt": ["config.example.toml"]}
    assert ap.check_claimed_files(["config.example.toml"], data2) == []


def test_evidence_file_set_strips_the_case_name_from_test_pointers() -> None:
    """★ 卡 E21：`test:xxx.py::用例名` 要当成 `tests/xxx.py`，不是 `tests/xxx.py::用例名`。

    红读数（实现前）：集合里是 `tests/test_x.py::case_a` ⇒ 与历史提交里的
    `tests/test_x.py` 对不上，审计 ⑫ 反向判据假红（2026-10-25 F1 落地现场）。
    """
    data = {"entries": {"T-X": {"status": "done",
                                "evidence": ["test:test_x.py::case_a", "file:tools/a.py"]}}}
    claimed = ap.evidence_file_set(data)
    assert "tests/test_x.py" in claimed, claimed
    assert "tests/test_x.py::case_a" not in claimed, claimed
    assert "tools/a.py" in claimed, claimed


def test_check_claimed_files_accepts_a_test_pointer_with_a_case_name() -> None:
    """同一条判据的反向入口：被 `test:` 带用例名声称过的测试文件 ⇒ 不算"没声称"。"""
    data = {"entries": {"T-X": {"status": "done", "evidence": ["test:test_x.py::case_a"]}}}
    assert ap.check_claimed_files(["tests/test_x.py"], data) == []
    # 反空转：没被任何指针指到的文件仍要点名
    assert ap.check_claimed_files(["tests/test_y.py"], data) != []


def test_real_repo_history_files_are_all_claimed() -> None:
    """数据层：真台账的证据指针集合，要能盖住最近几笔真实提交的改动（豁免清单除外）。

    这条钉住「反向判据开着且当前 0 假红」—— 以后谁改出缺口，这里先红。
    """
    import fnmatch  # noqa: F401
    import subprocess  # noqa: F401

    data = _ledger()
    claimed = ap.evidence_file_set(data)
    exempts = ap.claimed_files_exempt(data)
    log = subprocess.run(
        ["git", "-c", "core.quotepath=false", "log", "-6", "--name-only", "--format="],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    files = {ln.strip().replace("\\", "/") for ln in log.splitlines() if ln.strip()}
    unclaimed = sorted(
        f for f in files
        if f not in claimed and not any(fnmatch.fnmatch(f, pat) for pat in exempts)
    )
    assert unclaimed == [], f"这几笔提交里有台账没声称过的文件：{unclaimed}"


def test_every_acknowledged_op_has_a_nonempty_reason() -> None:
    """`[acknowledged_ops]` 里每一条都要写清"**为什么**先不挂"（不是"忘了"）。

    ★ 2026-09-25（T-G75）：这一节**现在是空的** —— `OP-32` 在 T-G21 销账、`OP-38` 在 T-G75 销账
    （两条都是"活儿其实做完了，只是没人回头销"）。原来那句 `assert acked` 因此过期了，
    但它想防的东西没错：**空集永远满足"每一条都写了理由"** —— 那种绿灯比红更坏。
    所以改成两条一起：① 留着的每一条理由都不许为空；② 用一条**合成数据**证明这个判据真的会红。
    """
    data = _ledger()
    assert _blank_ack_reasons({"acknowledged_ops": {"OP-38": "   "}}) == ["OP-38"], \
        "判据本身不会红 —— 那它在真台账上绿着也没有意义"
    assert _blank_ack_reasons({"acknowledged_ops": {"OP-38": "理由在这儿"}}) == []
    assert _blank_ack_reasons(data) == [], f"这些例外没写理由：{_blank_ack_reasons(data)}"

def test_gitignored_evidence_is_not_a_missing_file() -> None:
    """卡 A288：`gates/diag/*` 被 `.gitignore` 忽略 ⇒ 裸 `git worktree add` 建出来的
    卡树里必然没有它。判据不能把"本来就不进 git"的路径当缺（A286/A287 两次人工拷
    文件才过门），但也**不许**放过真缺的跟踪文件。
    """
    ok, desc = ap.eval_assertion("file:gates/diag/_never_exists_probe.md")
    assert ok, f"gitignored 的路径不该算缺：{desc}"
    assert "gitignored" in desc, f"要说明为什么放过：{desc}"
    ok, desc = ap.eval_assertion("file:tools/_never_exists_probe.py")
    assert not ok, f"跟踪文件缺了必须红：{desc}"
    ok, _desc = ap.eval_assertion("file:tools/stack.py")
    assert ok, "真存在的文件照旧通过"
