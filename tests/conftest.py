"""pytest 全局配置（小，但有必要）。

## 为什么要有这个文件：测试**不许**写进真实的落盘目录

`SR-F8 / G 批 · T-G4` 之后，只要走 REST 完成任务 / 记备忘 / 记产出，后端就会把当天那份
markdown 写出来（那是产品行为）。默认目录是项目下的 `export/` —— 于是**跑一遍测试**就会用
**临时测试库里的数据**覆盖**你当天真实那份** md。

md 是产物（数据库才是权威），但"跑测试把我今天的记录冲了"仍然是不可接受的副作用，
所以在**测试进程**里把默认导出目录指到临时目录：环境变量 `TIMEFLOW_EXPORT__DIR` 会被
`config._env_override()` 套成 `[export] dir`，而 `create_app()` 每次都重新读配置。

生产代码不受影响：那里没有这个环境变量，默认仍是 `export/`（或在设置页/配置里指定的目录）。
"""

from __future__ import annotations

import os
import tempfile

_TEST_EXPORT_DIR = tempfile.mkdtemp(prefix="timeflow-tests-export-")
os.environ.setdefault("TIMEFLOW_EXPORT__DIR", _TEST_EXPORT_DIR)
