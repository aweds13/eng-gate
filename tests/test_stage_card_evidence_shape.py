"""卡 E100（T-AG609）：`--evidence test:tests/x.py::case` 这种**带 `tests/` 前缀**的形态
过去会被原样写进台账，而审计自己补前缀
（`scripts/audit_progress.py` 的 `p = ROOT / "tests" / fname`）
⇒ 求值成 `tests/tests/x.py`，**必红**。

真现场（E99 落地首趟）：`gates/diag/land-E99.log` 三条
`test:tests/test_pool_limits.py::…` 被 `③″` 快门禁拦下，白跑一趟；
写侧 `tools/pool/stage_card.py::_as_assertion` 只判「带前缀就原样保留」，
既不剥 `tests/`、也不问用例在不在。

本卡的口径（判据只在写侧一处，不另造第二道门）：
  ① **形态归一**：`test:` 指针写成裸文件名（剥 `tests/` 与 `./`、反斜杠转 `/`），
     `file:` / `text:` 一字不动；
  ② **本次新给的 `test:` 指针**在写盘**之前**就按审计同一口径求值 ——
     文件不在 / 用例不在 ⇒ 停手退 4，并把该写什么打出来；
  ③ 片段里**已有人写下的**（carried）只归一、不判死
     （那可能是人手补的、且现在判死会挡住别人的收口）；
  ④ 尺子复用 `tools/wb_invariants.py::defines_case`，**不许写第二份**。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
STAGE_MODULE = ROOT / "tools" / "pool" / "stage_card.py"


def _stage_card():
    """按文件路径加载**这一份** `tools/pool/stage_card.py`（钉它，不是别的副本）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("stage_card_e100", STAGE_MODULE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage_card_e100"] = mod
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path) -> Path:
    """够 stage_card 跑片段模式的最小树（含一个真测试文件）。"""
    wt = tmp_path / "wt"
    for d in ("docs/changelog.d", "docs/traceability.d", "复盘/交接.d", "tests", "tools"):
        (wt / d).mkdir(parents=True)
    (wt / "docs" / "traceability.toml").write_text("", encoding="utf-8", newline="\r\n")
    (wt / "docs" / "changelog.md").write_text("## 2026-10-01\r\n", encoding="utf-8",
                                              newline="\r\n")
    (wt / "复盘" / "交接-重构进度.md").write_text(
        "# 交接\r\n\r\nCHECKPOINT-PLACEHOLDER\r\n", encoding="utf-8", newline="\r\n")
    (wt / "tests" / "test_real.py").write_text(
        "def test_known():\n    pass\n", encoding="utf-8", newline="\n")
    for rel in ("tools/sync_docs.py", "tools/pool/__init__.py", "tools/pool/no_window.py",
                "tools/wb_invariants.py"):
        src = ROOT / rel
        if src.is_file():
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    return wt


def _run(wt: Path, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    narrative = tmp_path / "text.md"
    narrative.write_text(
        "=== gaps ===\n- 无\n\n=== changelog ===\n## 测试卡（T-AG999）\n\n- 一行\n\n"
        "=== checkpoint ===\n- 一段\n",
        encoding="utf-8", newline="\n")
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(STAGE_MODULE), "--tree", str(wt),
         "--id", "T-AG999", "--title", "测试卡", "--group", "ENGINEERING",
         "--evidence", *extra, "--text-file", str(narrative)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")


def _evidence(wt: Path) -> list[str]:
    data = tomllib.loads(
        (wt / "docs" / "traceability.d" / "T-AG999.toml").read_text(encoding="utf-8"))
    return list(data["entries"]["T-AG999"]["evidence"])


# ------------------------------------------------------------------ 判据 ①：形态归一
def test_test_pointer_drops_the_tests_prefix() -> None:
    """`test:tests/x.py::case` ⇒ `test:x.py::case`（审计自己补 `tests/`）。"""
    sc = _stage_card()
    assert sc._as_assertion("test:tests/test_real.py::test_known") == \
        "test:test_real.py::test_known"
    # 反斜杠 / ./ 也一并抹平（Windows 上 git 与 shell 都爱给这两种）
    assert sc._as_assertion("test:.\\tests\\test_real.py::test_known") == \
        "test:test_real.py::test_known"
    # 已经是正确形态 ⇒ 幂等（跑两遍不变）
    once = sc._as_assertion("test:test_real.py::test_known")
    assert sc._as_assertion(once) == once


def test_normalization_does_not_touch_other_kinds() -> None:
    """`file:` / `text:` 指针一个字符都不许改（`text:` 的图案在 `::` 之后，含斜杠很正常）。"""
    sc = _stage_card()
    assert sc._as_assertion("file:tests/test_real.py") == "file:tests/test_real.py"
    assert sc._as_assertion("text:tools/wb_plan.py::图案例") == "text:tools/wb_plan.py::图案例"
    assert sc._as_assertion("tools/wb_plan.py") == "file:tools/wb_plan.py"


# ------------------------------------------------------------------ 判据 ②：写盘前判死
def test_a_missing_test_file_refuses_before_anything_is_written(tmp_path: Path) -> None:
    """指到不存在的测试文件 ⇒ 退 4、点名它，且**片段一个都不写**。"""
    wt = _tree(tmp_path)
    r = _run(wt, tmp_path, "test:no_such_test.py::test_known")
    assert r.returncode == 4, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "no_such_test.py" in out, out
    assert "tests/</" in out or "tests/" in out, out
    assert not (wt / "docs" / "traceability.d" / "T-AG999.toml").exists(), \
        "停手之前不许写盘"


def test_a_missing_case_name_refuses_and_names_the_case(tmp_path: Path) -> None:
    """文件在、用例不在 ⇒ 同一条出口：退 4，且**点名那个用例**（不是只说文件有）。"""
    wt = _tree(tmp_path)
    r = _run(wt, tmp_path, "test:test_real.py::test_imaginary")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "test_imaginary" in (r.stdout + r.stderr)
    assert not (wt / "docs" / "traceability.d" / "T-AG999.toml").exists()


def test_the_good_shape_lands_normalized_and_evaluates_true(tmp_path: Path) -> None:
    """给对的形态（哪怕带了 `tests/`）⇒ 写进片段的指针能被审计判 True。"""
    wt = _tree(tmp_path)
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_progress as ap

    r = _run(wt, tmp_path, "test:tests/test_real.py::test_known", "file:tests/test_real.py")
    got = _evidence(wt)
    assert "test:test_real.py::test_known" in got, (r.stdout + r.stderr, got)
    # 两个前缀不许同时出现（`file:test:` 那类双重前缀是另一条老坑）
    assert not [x for x in got if x.startswith("file:test:")], got
    # 用**审计自己那份代码**求值，只是把它的根指向这棵小树（同一套规则，不另写一份）
    old_root = ap.ROOT
    ap.ROOT = wt
    try:
        ok, desc = ap.eval_assertion("test:test_real.py::test_known")
    finally:
        ap.ROOT = old_root
    assert ok, f"写进去的形态审计该判真：{desc}"


def test_pytest_parametrized_case_name_still_passes(tmp_path: Path) -> None:
    """`test_known[case-a]` 这种参数化后缀要按 `case_name` 剥掉再核（与审计同一把尺子）。"""
    wt = _tree(tmp_path)
    r = _run(wt, tmp_path, "test:test_real.py::test_known[a]" )
    assert (wt / "docs" / "traceability.d" / "T-AG999.toml").is_file(), r.stdout + r.stderr
    assert "test:test_real.py::test_known[a]" in _evidence(wt)


# ------------------------------------------------------------------ 判据 ③：carried 只归一
def test_carried_pointers_are_normalized_but_not_judged(tmp_path: Path) -> None:
    """片段里人手上一条 `test:tests/…`（文件在树里**不存在**）⇒ 归一后保留，不许判死。"""
    wt = _tree(tmp_path)
    frag = wt / "docs" / "traceability.d" / "T-AG999.toml"
    frag.write_text(
        '[entries."T-AG999"]\nid = "T-AG999"\ntitle = "测试卡"\n'
        'group = "ENGINEERING"\nstatus = "done"\nevidence = [\n'
        '  "test:tests/ghost.py::test_gone",\n]\ngaps = ""\n',
        encoding="utf-8", newline="\n")
    r = _run(wt, tmp_path, "test:test_real.py::test_known")
    got = _evidence(wt)
    assert "test:ghost.py::test_gone" in got, (r.stdout + r.stderr, got)
    assert "test:test_real.py::test_known" in got, got


# ------------------------------------------------------------------ 判据 ④：尺子不写第二份
def test_the_case_ruler_is_wb_invariants_not_a_second_copy() -> None:
    r"""用例存在性只能问 `tools/wb_invariants.py`；本文件里不许出现自己那份 `def\s+…\(` 正则。"""
    text = STAGE_MODULE.read_text(encoding="utf-8")
    assert "wb_invariants" in text, "没有复用那把尺子"
    assert "defines_case" in text, "没有复用 defines_case"
    assert "case_name" in text, "没有复用 case_name（参数化后缀要按它剥）"
    assert '\\bdef\\s+' not in text, "这里出现了第二份『用例存在性』正则"
