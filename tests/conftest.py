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
import sys
import tempfile
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
