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
