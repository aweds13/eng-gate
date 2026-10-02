"""测试用的**慢门禁桩**：睡 N 秒再退 0（默认 8）。

★ 为什么有它：`gate_cmd` 从卡 128（`T-G226`）起**白名单化** —— 只认 `python -X utf8 scripts/…`
或 `python -X utf8 tools/…`（**不许** `python -c`，那等于任意代码）。而 MCP 那条
「收申请时 stdio 不许被冻住」的钉子（卡 130 / `T-G227`）需要一条**合法但慢**的门禁命令，
否则那条钉子测不出东西（门禁太快 ⇒ 主循环就算被冻住也看不出来）⇒ 用这个桩。
"""
from __future__ import annotations

import sys
import time

time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0)
