"""卡 254（`T-G375`）· **受影响的测试选择**：改哪个文件 ⇒ 只跑哪几个用例。

## 为什么有这张测试

来路：一次全量门禁 = `pytest -n 4`（4 个 worker 实测 334+275+139+117 = 865 MB）＋ mypy / ruff /
若干审计脚本 ⇒ **~1 GB 峰**；2026-10-15 两次被内存闸挡下。用户 2026-10-16 从方案表里**只点了
1②（受影响的测试选择）** ⇒ 本卡只做这一件：给「改动文件 → 该跑哪些测试」立一张**可核查**的
映射，接进落地链的快门禁 ③″（`scripts/run_gates.py --fast`）。

## 判据（与卡 254「要做的事 / 判据」逐条对应）

  ① **命名对应**：`tools/<x>.py` ↔ `tests/test_<x>.py`（存在才算映射；`tools/wb_dash.py`
     ⇒ 只选集到 `tests/test_wb_dash.py`）。
  ② **兜底保守**：映射不到、或改动落在公共模块（`tools/pool/**` · `scripts/**` ·
     `pyproject.toml` 等）⇒ **回退全量**（宁可多跑，不许漏跑）。
  ③ **省内存的跑法**：选集必须**串行**（不带 `-n`）且 `--no-cov` —— 省的是进程/内存，
     **不是放宽判据**。
  ④ **全量仍在收口链 ④**：`build_jobs(False, False)` 的 pytest / 真机层一个字没动；
     选集只加在 `--fast` 那一趟（③″），**不替代** ④。

## 怎么验（纯函数，**不跑任何门禁**）

`select_tests` / `quick_test_job` / `build_jobs` 都是纯函数：喂路径列表，直接判"选了哪几个
用例 / 为什么退全量"。重活归收口链。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

# ------------------------------------------------------------------ ① 命名对应


def test_same_named_tool_selects_only_its_test() -> None:
    """★ 卡 254 的原话判据：改 `tools/wb_dash.py` ⇒ 选集只到 `tests/test_wb_dash.py`。

    前提（文件真的存在）先断言，免得这条钉在空气上。
    """
    assert (ROOT / "tools" / "wb_dash.py").is_file()
    assert (ROOT / "tests" / "test_wb_dash.py").is_file()

    plan = rg.select_tests(["tools/wb_dash.py"])
    assert plan.full_fallback is False, plan.note
    assert plan.tests == ("tests/test_wb_dash.py",), plan.tests

    # 反例（证明它按文件名现算，不是恒选某一个）：换一个同样有同名测试的工具
    other = rg.select_tests(["tools/wb_daily.py"])
    assert other.tests == ("tests/test_wb_daily.py",), other.tests

    # 带 `./` 前缀 / 反斜杠的路径也要归一（Windows 上照得到的形态）
    win = rg.select_tests([".\\tools\\wb_dash.py"])
    assert win.tests == ("tests/test_wb_dash.py",), win.tests


def test_changed_test_file_selects_itself() -> None:
    """改用例本身 ⇒ 只跑它自己（改名/新增都走这条，不需要另做映射）。"""
    plan = rg.select_tests(["tests/test_gate_peak.py"])
    assert plan.full_fallback is False
    assert plan.tests == ("tests/test_gate_peak.py",)


# ------------------------------------------------------------------ ② 兜底保守


def test_common_modules_fall_back_to_full() -> None:
    """★ 卡 254 的反例判据：改 `tools/pool/landing.py` ⇒ **必须回退全量**。

    （被选成子集 ⇒ 红。同时钉住卡里点名的另两类公共输入。）
    """
    for path in ("tools/pool/landing.py", "scripts/run_gates.py", "pyproject.toml"):
        plan = rg.select_tests([path])
        assert plan.full_fallback is True, f"{path} 被当成了可选集：{plan.tests}"
        assert plan.tests == (), f"{path} 回退时不许还留选集 {plan.tests}"
        assert "全量" in plan.note, plan.note


def test_unmapped_paths_fall_back_to_full() -> None:
    """映射不到（`src/**` / `tests/conftest.py` / 未知目录）⇒ 全量。"""
    for path in ("src/web/app.css", "tests/conftest.py", "harness/x.py", "framework/y.py"):
        plan = rg.select_tests([path])
        assert plan.full_fallback is True, f"{path} 没回退全量：{plan.tests}"

    # 反例：有映射的路径不许退全量（否则"只跑该跑的"这句是假的）
    hit = rg.select_tests(["tools/wb_dash.py"])
    assert hit.full_fallback is False

    # 混合：一条公共 + 一条可映射 ⇒ 宁多勿漏，整趟回退全量
    mixed = rg.select_tests(["tools/wb_dash.py", "scripts/audit_progress.py"])
    assert mixed.full_fallback is True and mixed.tests == ()


def test_docs_and_ledger_do_not_defeat_selection() -> None:
    """记账/文档改动**不参与**选集：落地链每笔都会写它们，若算进去 ⇒ 选集永远用不上。

    ★ 边界（如实写）：它们影响的用例（docs_fragments / card_doc_budget / ledger_summary …）
      在收口链 **④ 全量**照跑；③″ 从来不替代 ④。
    """
    plan = rg.select_tests([
        "docs/changelog.d/abc.md",
        "复盘/卡/卡254-门禁峰值治理.md",
        "gates/last.json",
        "tools/wb_dash.py",
    ])
    assert plan.full_fallback is False, plan.note
    assert plan.tests == ("tests/test_wb_dash.py",), plan.tests
    assert set(plan.ignored) == {
        "docs/changelog.d/abc.md", "复盘/卡/卡254-门禁峰值治理.md", "gates/last.json",
    }, plan.ignored


def test_nothing_to_select_is_not_a_full_run() -> None:
    """空改动 / 只有文档 ⇒ 选集为空（不退全量）：没有该跑的东西，③″ 照旧只跑快门。"""
    for paths in ([], ["docs/x.md"]):
        plan = rg.select_tests(paths)
        assert plan.full_fallback is False, plan.note
        assert plan.tests == ()
        assert rg.quick_test_job(plan) is None


# ------------------------------------------------------------------ 例外表可核查


def test_exception_table_is_explicit_and_real() -> None:
    """★ 例外表每一条都要指到**真实存在**的用例；且键必须是 `tools/*.py`。"""
    for tool, tests in rg.TEST_SELECTION_EXCEPTIONS.items():
        assert tool.startswith("tools/") and tool.count("/") == 1, tool
        assert tool.endswith(".py"), tool
        assert tests, f"{tool} 的例外表是空的（要么删条目、要么写清凭什么）"
        for t in tests:
            assert (ROOT / t).is_file(), f"例外表指向不存在的用例：{t}"
    # 例外表不许把"有同名测试的工具"偷偷换成别的（那会让命名对应失真）
    for tool in rg.TEST_SELECTION_EXCEPTIONS:
        stem = Path(tool).stem
        assert not (ROOT / "tests" / f"test_{stem}.py").is_file(), tool


# ------------------------------------------------------------------ ③ 改动路径解析 / 选集跑法


def test_status_parser_keeps_the_first_line_intact() -> None:
    """★ 真踩过的坑（卡 254 实测）：`git()` 会把整段 stdout `.strip()` —— 第一行的
    `" M "` 前缀被吃掉一个字符，`scripts/run_gates.py` 变成 `cripts/run_gates.py`，
    于是**永远映射不到 ⇒ 每次都白跑全量**。这里把解析单独钉住。
    """
    out = " M scripts/run_gates.py\n?? tests/test_gate_peak.py\n D docs/x.md"
    assert rg.parse_status_paths(out) == [
        "scripts/run_gates.py", "tests/test_gate_peak.py", "docs/x.md",
    ]
    # 空输出 / 只有空行 ⇒ 没有改动
    assert rg.parse_status_paths("") == []
    assert rg.parse_status_paths("\n\n") == []


def test_quick_job_is_serial_and_skips_coverage() -> None:
    """★ 省内存靠的是**少起 worker**：选集那条命令不带 `-n`，且关掉覆盖率门。

    `pyproject.toml` 的 `addopts` 带 `--cov --cov-fail-under=70` —— 只跑一个用例时覆盖率
    必然不达标，不关就永远是假红。`--no-cov` 与验收命令同口径。
    """
    plan = rg.select_tests(["tools/wb_dash.py"])
    job = rg.quick_test_job(plan)
    assert job is not None
    name, cmd = job
    assert name == "pytest_sel"
    assert "tests/test_wb_dash.py" in cmd
    assert "--no-cov" in cmd
    assert not any(x == "-n" or x.startswith("-n=") for x in cmd), f"选集不许并行：{cmd}"

    # 反例：回退全量 / 空选集 ⇒ **不生成**这条门（全量归 ④，绝不在这里冒充跑过）
    assert rg.quick_test_job(rg.select_tests(["tools/pool/landing.py"])) is None
    assert rg.quick_test_job(rg.select_tests([])) is None


# ------------------------------------------------------------------ ④ 全量仍在 ④


def test_full_gate_keeps_pytest_and_browser_layers() -> None:
    """★ 选集只加在 `--fast`（③″）；默认/`--quick` 的门清单**逐字未动**，全量仍含 pytest。"""
    full = [n for n, _ in rg.build_jobs(False, False)]
    assert "pytest" in full and "render" in full and "ui_flow" in full

    quick = [n for n, _ in rg.build_jobs(True, False)]
    assert "pytest" in quick and "render" not in quick

    fast = [n for n, _ in rg.build_jobs(False, True)]
    assert set(fast) == set(rg.FAST), "`--fast` 的固定门清单被改了（卡 226 的口径）"
    assert "pytest_sel" not in fast, "选集必须由 main 临时追加，不进 build_jobs 的固定清单"
