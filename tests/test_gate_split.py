r"""快慢分层的钉子（卡 E50 段2 · 并 E32）：`chain` 标记 + 默认门排除 + 独立门 + 覆盖面不丢。

判据（卡 E32 §判据 3 的七条，逐条落到函数上）：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | `chain` marker 已在 `pyproject.toml` 注册 | 打标成「未知标记」，`-m chain` 静默收不到 |
| ② | **默认门**命令里有 `not chain`（`not acceptance` 在、覆盖率门没松） | 去掉 ⇒ 回到默认门 |
| ③ | `pytest_chain` 在 `GATES` 里，且带 `-m chain --no-cov` | 只加标记不加门 ⇒ e2e 永远不跑 |
| ④ | 改任一 chain 用例所在的文件 ⇒ 必需档含 `lang`，而 `lang` 里有它 | 档表与门表两套 |
| ⑤ | 落地档（全量 `build_jobs`）包含 `pytest_chain` | 落地可以绕开 e2e |
| ⑥ | **打标集合 == 清单**（真 collect 一遍，双向比） | 清单写了不存在的用例 / 悄悄少打 |
| ⑦ | 同批文件里跑真链路（`_wand(`）的用例必须有个交代 | 新加一条完整 e2e 却忘了打标 |

★ 为什么清单在 `tests/conftest.py` 而不在用例头上：本卡 `files` 域只覆盖清单里 8 个文件
中的 2 个，打标动作收在**一处**（`CHAIN_MANIFEST`），判据也认那一处。详见 `tests/conftest.py`。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import conftest  # noqa: E402 —— 清单的唯一真源（`CHAIN_MANIFEST`）

CHAIN_MANIFEST = conftest.CHAIN_MANIFEST
#: Windows 上起子进程不弹窗（本仓铁律：`subprocess` 必须带 creationflags）。
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _load_run_gates():
    target = ROOT / "scripts" / "run_gates.py"
    spec = importlib.util.spec_from_file_location("run_gates_split_under_test", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_gates_split_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_run_gates()


def _ini() -> dict:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return cfg["tool"]["pytest"]["ini_options"]


def _collect(marker: str) -> list[str]:
    """真 collect 一遍（子进程跑 pytest），拿 nodeid 列表。

    `-o addopts=` 是必须的：默认 addopts 里有 `not chain`，不清掉就**一条都收不到**
    （那会让下面的「集合相等」变成永远红的假钉子）。
    """
    cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "--collect-only", "-q",
           "-m", marker, "-o", "addopts=", "-p", "no:cacheprovider"]
    done = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, check=False, **_NO_WINDOW,
    )
    assert done.returncode == 0, f"collect 都失败了：\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}"
    return sorted(
        line.strip().replace("\\", "/")
        for line in done.stdout.splitlines()
        if "::" in line and line.strip().startswith("tests/")
    )


# ---------------------------------------------------------------- ① marker 已注册
def test_chain_marker_is_registered() -> None:
    markers = _ini()["markers"]
    assert any(str(m).startswith("chain:") for m in markers), (
        f"`chain` 没在 pyproject 的 markers 里注册：{markers}")


# ---------------------------------------------------------------- ② 默认门排除
def test_default_gate_command_excludes_chain() -> None:
    addopts = _ini()["addopts"]
    assert "not acceptance" in addopts, addopts
    assert "not chain" in addopts, f"默认门没有排除 chain（分层白做）：{addopts}"
    # ★ 防「为了变快顺手放松别的东西」：覆盖率门一个字不许松。
    assert "--cov-fail-under=70" in addopts, addopts


# ---------------------------------------------------------------- ③ 独立门存在
def test_pytest_chain_gate_exists_in_gate_table() -> None:
    from gates.defs import lang_python

    table = dict(lang_python.GATES)
    assert "pytest_chain" in table, f"门表里没有 pytest_chain：{list(table)}"
    cmd = table["pytest_chain"]
    # 第 2 个 `-m`（第 1 个是 `-m pytest`）后面必须紧跟 marker 名
    marks = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "-m"]
    assert marks == ["pytest", "chain"], f"pytest_chain 没按 marker 选：{cmd}"
    assert "--no-cov" in cmd, f"pytest_chain 没关覆盖率门（会因覆盖率不足恒红）：{cmd}"


# ---------------------------------------------------------------- ④ 档表认这道门
def test_touching_a_chain_file_requires_lang_profile() -> None:
    from gates.defs import domains

    files = sorted({key.split("::")[0] for key in CHAIN_MANIFEST})
    assert files, "清单空了"
    for f in files:
        need = domains.required_profiles([f])
        assert "lang" in need, f"改 {f} 不需要 lang 档 ⇒ 那道门跑不到"
    lang_jobs = [n for n, _ in rg._profile_filter(rg.build_jobs(True, False), "lang")]
    assert "pytest_chain" in lang_jobs, f"lang 档里没有 pytest_chain：{lang_jobs}"


# ---------------------------------------------------------------- ⑤ 落地档不能绕开
def test_landing_profile_contains_the_chain_gate() -> None:
    names = [n for n, _ in rg.build_jobs(False, False)]
    assert "pytest_chain" in names, f"全量/落地趟里没有 pytest_chain：{names}"
    assert rg.profiles_covered(rg.build_jobs(False, False)) == ["all"]
    assert "pytest_chain" in rg.GATE_PROFILES["lang"]


# ---------------------------------------------------------------- ⑥ 集合相等（双向）
def test_marked_set_equals_the_manifest() -> None:
    got = _collect("chain")
    want = sorted(key.replace("\\", "/") for key in CHAIN_MANIFEST)
    missing = [k for k in want if k not in got]
    extra = [k for k in got if k not in want]
    assert not missing, f"清单里有、实际没收到的用例（改名 / 删了？）：{missing}"
    assert not extra, f"实际打了 chain、清单里没有（漏记）：{extra}"
    assert len(got) == len(CHAIN_MANIFEST), (len(got), len(CHAIN_MANIFEST))


# ---------------------------------------------------------------- ⑦ 防漏打
#: 清单那 8 个文件里，**同批**但只跑链的某一段 / 早退的用例（实测 3–12 s，跑不到
#: 「门禁 + 复核」那一步，所以不算 chain）。★ 写死是**故意**的：以后谁在这些文件里新加
#: 一条 `_wand(...)` 用例而没进清单、也没进这里 ⇒ 第 ⑦ 条红 —— 漏不了。
SUBSTEP_ALLOWED: frozenset[str] = frozenset({
    "tests/test_wb_land.py::test_unexpected_staged_file_stops_and_resets",
    "tests/test_wb_land.py::test_fail_fast_stops_before_gate_and_takes_no_lock",
    "tests/test_wb_land.py::test_atexit_releases_lock_on_abnormal_exit",
    "tests/test_wb_land.py::test_reset_derived_restores_head_state_and_prints",
    "tests/test_wb_land.py::test_reset_derived_never_touches_whitelist_sources",
    "tests/test_wb_land.py::test_reset_warns_and_continues_when_head_unavailable",
    "tests/test_wb_land.py::test_no_daily_full_forces_full",
    "tests/test_wb_land.py::test_review_step_writes_to_gates_review",
    "tests/test_wb_land.py::test_review_cmd_gets_landing_allow",
    "tests/test_wb_land.py::test_review_whitelist_complaint_is_not_silenced",
    "tests/test_wb_land.py::test_review_real_problems_still_count",
    "tests/test_wb_land.py::test_incremental_writes_affected_block_for_card147_fence",
    "tests/test_wb_land.py::test_no_review_skips_step8",
    "tests/test_wb_land.py::test_ff_merge_failure_does_not_print_complete",
    "tests/test_wb_land.py::test_landing_flips_status_when_task_matches",
    "tests/test_wb_land.py::test_landing_does_not_flip_status_on_registration",
    "tests/test_wb_land.py::test_landing_refuses_when_card_not_registered",
    "tests/test_wb_land.py::test_landing_skip_when_already_done",
    "tests/test_wb_land.py::test_card_tree_head_not_ancestor_says_cherry_pick",
    "tests/test_wb_land.py::test_preflight_red_stops_before_full_gates",
    "tests/test_wb_land.py::test_preflight_green_continues_to_full_gates",
    "tests/test_wb_land.py::test_lock_progress_is_streamed_into_the_landing_log",
    "tests/test_wb_land.py::test_landing_joins_queue_and_leaves_it_empty",
    "tests/test_wb_land.py::test_landing_refuses_to_cut_in_line",
})


def _wand_tests(path: Path) -> list[str]:
    """文件里**函数体出现 `_wand(`**（= 真跑一次 `wb_land`）的用例名。"""
    src = path.read_text(encoding="utf-8")
    names: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        body = ast.get_source_segment(src, node) or ""
        if "_wand(" in body:
            names.append(node.name)
    return names


def test_no_e2e_test_is_silently_left_out() -> None:
    """清单那 8 个文件里，跑真链路的用例**不许**既不进清单、也不在 `SUBSTEP_ALLOWED`。"""
    unknown: list[str] = []
    for rel in sorted({key.split("::")[0] for key in CHAIN_MANIFEST}):
        for name in _wand_tests(ROOT / rel):
            key = f"{rel}::{name}"
            if key not in CHAIN_MANIFEST and key not in SUBSTEP_ALLOWED:
                unknown.append(key)
    assert not unknown, (
        "这些用例真跑链路却没进 chain 清单（漏打 —— 要么打标，要么说明它是子步骤）：\n"
        + "\n".join(f"  {k}" for k in unknown)
    )


def test_substep_allow_list_has_no_stale_entries() -> None:
    """★ 反向：`SUBSTEP_ALLOWED` 里不许留已经不存在的用例（名单不会烂在原地）。"""
    stale: list[str] = []
    for key in SUBSTEP_ALLOWED:
        rel, name = key.split("::")
        if (ROOT / rel).is_file() and name not in _wand_tests(ROOT / rel):
            stale.append(key)
    assert not stale, f"这些 SUBSTEP_ALLOWED 条目已经不匹配任何用例了（删掉）：{stale}"
