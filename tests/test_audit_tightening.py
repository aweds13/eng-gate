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
