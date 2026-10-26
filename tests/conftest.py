"""pytest 全局配置（小，但有必要）。

## 为什么要有这个文件：测试**不许**写进真实的落盘目录

`SR-F8 / G 批 · T-G4` 之后，只要走 REST 完成任务 / 记备忘 / 记产出，后端就会把当天那份
markdown 写出来（那是产品行为）。默认目录是项目下的 `export/` —— 于是**跑一遍测试**就会用
**临时测试库里的数据**覆盖**你当天真实那份** md。

md 是产物（数据库才是权威），但"跑测试把我今天的记录冲了"仍然是不可接受的副作用，
所以在**测试进程**里把默认导出目录指到临时目录：环境变量 `TIMEFLOW_EXPORT__DIR` 会被
`config._env_override()` 套成 `[export] dir`，而 `create_app()` 每次都重新读配置。

生产代码不受影响：那里没有这个环境变量，默认仍是 `export/`（或在设置页/配置里指定的目录）。

## 并行跑（T-G7）时再加一条：每个 worker 一个日志文件

门禁现在用 `pytest-xdist` 并行（见 `scripts/run_gates.py`）。`create_app()` 会调
`logs.setup_logging()`，默认路径是仓库里的 `logs/timeflow.jsonl` —— 16 个 worker 同时往同一个
文件 append 会互相插行（它是 gitignore 的本机产物、不影响判定，但没必要让它变脏变慢）。
所以**只在并行时**把日志指到各自的临时文件；串行（也就是你平时手敲 `pytest`）保持默认，
与真实运行一致。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_TEST_EXPORT_DIR = tempfile.mkdtemp(prefix="timeflow-tests-export-")
os.environ.setdefault("TIMEFLOW_EXPORT__DIR", _TEST_EXPORT_DIR)

_WORKER = os.environ.get("PYTEST_XDIST_WORKER")
if _WORKER:  # 只有 xdist 的分身进程才有这个变量
    os.environ.setdefault(
        "TF_LOG_PATH", os.path.join(_TEST_EXPORT_DIR, f"timeflow-{_WORKER}.jsonl")
    )

## worktree 导入口径（T-G134）：测试必须 import **本树**的 src
#
# 背景：miniconda 的 editable 安装（`__editable__.timeflow-0.1.0.pth`）硬指主树的
# `engineering\src` —— 在 `git worktree` 里跑 pytest，`import timeflow` 拿到的是
# 主树的旧代码（既能造假红，也能造假绿：新测试跑在旧实现上照样通过）。
# 修法：pytest session 一开始就把**本树**的 `src` 前置到 `sys.path` 最前，钉子在
# `tests/test_src_import_line.py`（判据相对本树根，不写死任何绝对路径）。
# 主树里语义不变：主树的本树 src 就是它自己，前置只是把 .pth 已做的事提前。

_TREE_SRC = Path(__file__).resolve().parents[1] / "src"
if _TREE_SRC.is_dir():
    sys.path.insert(0, str(_TREE_SRC))

## 起子进程遇「拒绝访问」要重试（卡 E14 · T-AG465）
#
# 现象：门禁在临时目录里起极短的 `git` 子进程，偶发
# `PermissionError: [WinError 5] 拒绝访问。`（杀软扫码 / 句柄回收 / 临时目录竞争）。
# 同一用例在主树单跑 4 次全过、同趟其余 2987 条也全过 ⇒ 不是被测代码的毛病，
# 却把整趟落地判红（E7 为此多烧两趟全量门禁）。
#
# 口径：只对「起进程被拒」这类**瞬时**错误重试，别的 `OSError` 原样抛（别把真错当抖动）；
# 三次全失败 ⇒ 抛**原异常**（不 skip、不吞），返回值与 `subprocess.run` 完全一致。

#: 合计最多尝试次数（初次 1 + 重试 2）—— 卡规格「三次都失败 ⇒ 抛原异常」即此口径。
GIT_MAX_TRIES = 3
#: 每次重试前的等待（秒）
GIT_RETRY_DELAY_S = 0.05


def _is_spawn_denied(exc: OSError) -> bool:
    """`PermissionError` 或 `winerror == 5`（`[WinError 5] 拒绝访问`）才算瞬时抖动。"""
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5


def run_git(*args: str, **kwargs: object) -> subprocess.CompletedProcess:
    """起 `git <args>` 子进程；参数与返回值都照 `subprocess.run` 的语义走。

    遇瞬时「拒绝访问」最多尝试 `GIT_MAX_TRIES` 次（间隔 `GIT_RETRY_DELAY_S`），
    每次重试打印一行 `[retry] git … PermissionError（第 N 次）`；
    三次都失败 ⇒ 抛**原异常**（调用方的断言/判据照旧生效）。
    """
    cmd = ["git", *args]
    for attempt in range(1, GIT_MAX_TRIES + 1):
        try:
            return subprocess.run(cmd, **kwargs)
        except OSError as exc:  # PermissionError 是 OSError 的子类，一起接住
            if not _is_spawn_denied(exc) or attempt == GIT_MAX_TRIES:
                raise  # 不是瞬时抖动 / 已到上限 ⇒ 抛原异常（不吞、不 skip）
            print(f"[retry] git {' '.join(args)} {type(exc).__name__}（第 {attempt} 次）")
            time.sleep(GIT_RETRY_DELAY_S)
    raise AssertionError("run_git(): 不可达")  # 只为静态检查：上面必然 return 或 raise


## 宿主注入的仓外配置**不许渗进判据**（卡 E49 · T-AG499）
#
# 云机跑门禁时 `scripts/cloud/run_gate.sh` 会注入 `TF_PROJECTS_TOML` /
# `TF_MODEL_REGISTRY` / `TF_MODEL_WHITELIST` / `TF_POOL_CFG_DIR`（那些路径在云机上存在），
# 而本机没有。有些用例读的是**默认解析**（自己再 setenv 一份），注入一变就换了判对象：
# 云机 pass8 上 `test_account_auth_uses_the_profile_env_and_model` 因此报
# 「模型注册表不存在：C:\infra\pool\models.whitelist.toml」，本机则通过。
# ⇒ 统一在测试进程里摘掉这四个变量；**需要它们的用例自己 `monkeypatch.setenv`**
#   （`tests/test_wb_dispatch.py` 的 `sandbox` 夹具就是这么做的），不会被本夹具覆盖。
_HOST_CONFIG_ENV = (
    "TF_PROJECTS_TOML",
    "TF_MODEL_REGISTRY",
    "TF_MODEL_WHITELIST",
    "TF_POOL_CFG_DIR",
    "TF_POOL_CFG_DST",
)


def strip_host_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """把宿主注入的四个仓外配置从测试进程里摘掉（判据钉在 `tests/test_wb_dispatch.py`）。"""
    for key in _HOST_CONFIG_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _no_host_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    strip_host_config_env(monkeypatch)


## 快慢分层（卡 E50 段2 · 并 E32）：`chain` 标记的**唯一清单**
#
# 为什么清单收在 `conftest.py` 一处，而不是逐个用例头上加 `@pytest.mark.chain`：
#   · 本卡的 `files` 域只覆盖 `tests/test_wb_land.py` 与 `tests/test_contract_audit.py`；
#     清单里另外 6 个文件（`test_partitions.py` / `test_evidence_map.py` /
#     `test_wb_dispatch.py` / `test_docs_fragments.py` / `test_card_specs_tracked.py` /
#     `test_wb_plan.py`）是**别的卡的域**，不许动。打标动作因此收在**一处**（这张表），
#     不散成 22 处；
#   · 判据认的也正是这张表：`tests/test_gate_split.py` 钉「标记集合 == 清单」，并钉清单里
#     每一个 nodeid 都真能被 collect 到（改名 / 删用例 ⇒ 红，不会静默少打）。
#
# 口径（卡 E32 §判据 2）：**一条用例都不许删、一条断言都不许改** —— 这里只加标记，
# 默认门靠 `pyproject.toml` 的 `not chain` 把它们排掉，`pytest_chain` 那道门再单独跑。
CHAIN_MANIFEST: tuple[str, ...] = (
    "tests/test_card_specs_tracked.py::test_every_registered_spec_exists_and_is_tracked",
    "tests/test_contract_audit.py::test_real_repo_audit_has_expected_shape",
    "tests/test_docs_fragments.py::test_real_repo_is_in_sync_and_merge_is_noop",
    "tests/test_docs_fragments.py::test_audit_verdict_unchanged_by_sync",
    "tests/test_evidence_map.py::test_stale_on_the_real_ledger_matches_audit",
    "tests/test_partitions.py::test_same_number_different_partition_is_allowed",
    "tests/test_partitions.py::test_check_without_backlog_option_uses_shards",
    "tests/test_wb_dispatch.py::test_retry_round_threshold_eats_only_its_own_log",
    "tests/test_wb_land.py::test_second_run_of_same_landing_hits_no_duplicate",
    "tests/test_wb_land.py::test_no_reset_really_disables",
    "tests/test_wb_land.py::test_affected_passes_through_when_no_force_full",
    "tests/test_wb_land.py::test_touching_tools_forces_full",
    "tests/test_wb_land.py::test_empty_plan_forces_full",
    "tests/test_wb_land.py::test_incremental_trailer_says_not_full",
    "tests/test_wb_land.py::test_full_run_marks_daily_full",
    "tests/test_wb_land.py::test_degraded_run_trailer",
    "tests/test_wb_land.py::test_landing_renews_lock_during_gate",
    "tests/test_wb_land.py::test_full_chain_review_green_e2e",
    "tests/test_wb_land.py::test_gate_artifacts_present_or_changed_keep_review_green_e2e",
    "tests/test_wb_land.py::test_tamper_after_seal_review_red_e2e",
    "tests/test_wb_land.py::test_batch_landing_flips_member_status_e2e",
    "tests/test_wb_plan.py::test_check_passes_when_no_landed_but_pending",
)


def _chain_key(nodeid: str) -> str:
    """collect 出来的 nodeid → 清单里的键（只统一斜杠：xdist 不改 nodeid 前缀）。"""
    return nodeid.replace("\\", "/")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """给清单里的用例补 `chain` 标记（**只加标记**，不动断言、不 skip）。"""
    want = set(CHAIN_MANIFEST)
    for item in items:
        if _chain_key(item.nodeid) in want:
            item.add_marker(pytest.mark.chain)
