"""`tools/evidence_map.py`（证据倒排索引，T-G108）的测试 —— 给"少读"这件事上护栏。

为什么要有测试：这个工具的全部价值是**在改文件之前**回答两句话 ——
「这个文件上挂着哪些台账断言」与「哪些断言已经失配」。它错了的代价是**主控以为安全**，
结果是提交时被 `audit` 打脸（T-G93 / T-G86 那两次的字面失配）。

两条护栏：
1. **口径不许自成一套**：求值一律走 `scripts/audit_progress.py` 的 `eval_assertion` ——
   测试直接拿审计的遍历结果跟它对，两者不一致就红；
2. **它只读**：`--stale` 求值要读源码，但**绝不改任何文件**。

★ 这里的"三种类型"（`file:` / `text:` / `test:`）用的是**真仓库里的真文件**，不是造假。
"""

from __future__ import annotations

import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_progress as ap  # noqa: E402 —— 复用它的求值口径（唯一真源）
import evidence_map as em  # noqa: E402


def _ledger(*entries: dict) -> dict:
    return {"entries": {e["id"]: e for e in entries}}


# ------------------------------------------------------------------ 零件层


def test_assertion_path_and_pattern_split_file_kinds() -> None:
    """三类指向文件的断言各自怎么取出「路径」与「图案」。"""
    assert em.assertion_path("file:tools/wb_dash.py") == "tools/wb_dash.py"
    assert em.assertion_path("text:tools/wb_dash.py::def _state(") == "tools/wb_dash.py"
    assert em.assertion_path("test:test_wb_status.py") == "tests/test_wb_status.py"
    # 语义类断言（route/table/column/ui）不指向文件
    assert em.assertion_path("route:GET /api/tasks") is None
    assert em.assertion_pattern("text:a/b.py::def f(") == "def f("
    assert em.assertion_pattern("file:a/b.py") == ""


def test_evaluate_covers_file_text_and_test_types() -> None:
    """三种类型各正反一对 —— 口径与 audit 一致（这里直接断言 audit 的同一结果）。"""
    for assertion, want in [
        ("file:tools/evidence_map.py", True),
        ("file:tools/__no_such_file__.py", False),
        ("text:docs/traceability.toml::[entries.", True),
        ("text:docs/traceability.toml::__no_such_pattern__", False),
        ("test:test_evidence_map.py", True),
        ("test:test_no_such_file.py", False),
        # 语义类也能求值（口径同样复用 audit）
        ("table:tasks", True),
        ("table:no_such_table", False),
    ]:
        got, _desc = em.evaluate(assertion)
        assert got is want, f"{assertion} 期望 {want}，拿到 {got}"


def test_stale_reports_only_done_entries_with_a_synthetic_mismatch() -> None:
    """人造失配必须报出来；`todo` 条目的坏断言**不算失配**（与 audit 的遍历口径一致）。"""
    data = _ledger(
        {"id": "T-X1", "status": "done", "evidence": ["file:tools/evidence_map.py"]},
        {"id": "T-X2", "status": "done",
         "evidence": ["text:docs/traceability.toml::__deliberately_missing__"]},
        {"id": "T-X3", "status": "todo",
         "evidence": ["file:tools/__also_missing__.py"]},
    )
    stale = em.stale_assertions(data)
    ids = sorted(eid for eid, _a, _d in stale)
    assert ids == ["T-X2"], f"只该报 done 里的失配：{stale}"


def test_stale_on_the_real_ledger_matches_audit() -> None:
    """真台账上，本工具报的失配集合必须**等于**审计的遍历结果（一个字都不许差）。"""
    data = tomllib.loads(em.DEFAULT_LEDGER.read_text(encoding="utf-8"))
    mine = {(eid, a) for eid, a, _d in em.stale_assertions(data)}
    audit: set[tuple[str, str]] = set()
    for eid, entry in data["entries"].items():
        if entry.get("status") != "done":
            continue
        for assertion in entry.get("evidence", []):
            ok, _desc = ap.eval_assertion(assertion)
            if not ok:
                audit.add((eid, assertion))
    assert mine == audit, f"与 audit 不一致：只我有 {mine - audit}；只 audit 有 {audit - mine}"


def test_stat_counts_add_up() -> None:
    """汇总：总数 = 各类型之和；指向文件的三种类型单独计数。"""
    data = tomllib.loads(em.DEFAULT_LEDGER.read_text(encoding="utf-8"))
    s = em.stat(data)
    assert s["total"] == sum(s["by_kind"].values())
    assert s["file_like"] == sum(s["by_kind"].get(k, 0) for k in em.FILE_KINDS)
    assert s["entries"] == len(data["entries"])


def test_file_lookup_only_returns_assertions_on_that_file() -> None:
    """`--file` 只列挂在这个文件上的断言 —— 这是"改前先看会碎什么"的那一问。"""
    data = tomllib.loads(em.DEFAULT_LEDGER.read_text(encoding="utf-8"))
    rows = em.assertions_on_file(data, "tools/wb_dash.py")
    assert rows, "真台账里应当有挂在 tools/wb_dash.py 上的断言"
    for _eid, assertion in rows:
        assert em.assertion_path(assertion) == "tools/wb_dash.py", assertion


def test_unknown_assertion_kind_is_not_a_crash() -> None:
    """认不出的断言类型 → 求值 False（不是炸）—— 台账将来加新类型不许把这个工具打崩。"""
    ok, _desc = em.evaluate("weird:whatever")
    assert ok is False


def test_row_format_shows_the_five_columns() -> None:
    """一行五栏：条目 / 类型 / 路径 / 图案（截断 80）/ 命中与否。"""
    line = em.format_row("T-G93", "text:tools/wb_dash.py::def _state(", "命中")
    assert "T-G93" in line and "text" in line and "tools/wb_dash.py" in line
    assert "def _state(" in line and "命中" in line
    long_pattern = "x" * 500
    clipped = em.format_row("T-G93", f"text:a.py::{long_pattern}", "失配")
    assert "x" * 81 not in clipped, "图案必须截断到 80 字符"
