"""命令行（T-G64）—— **命令表的第四份投影**。

用户 2026-09-23 问「AI 原生的 CLI 这个可以加进来吗？会不会更加方便后面的维护，
以及功能的扩展」；T-G30 §4 的结论是「**直接加一个 CLI 会让维护变差**」——
四个面（界面 / ⌘K / CLI / AI·MCP）各写一遍就是四处会漂。
所以顺序是：**命令表（T-G31）→ 只读 CLI（本包）→ MCP → 写操作 CLI**。

这个包就是第二步，三条口径：

1. **只读**。每条子命令挂的都是一条 `GET /api/...`，而且那条路由**必须**出现在
   `docs/commands.toml` 里某条 `kind = "read"|"derive"` 的操作下 —— 机器判
   （`scripts/check_commands.py` 的「CLI 投影」一节）。写操作要等口径（AI 只写事实）。
2. **不自己算口径**。取数一律走进程内的 HTTP 边界（`create_app()` 的同一套路由，
   只把 socket 换成直接调 ASGI 应用），自己不碰 `core/`、不碰 sqlite
   （`tests/test_cli_line.py` 扫源码钉着这一点）。
3. **读同一张表**。`timeflow commands` 是自描述，直接从 `docs/commands.toml` 出；
   表找不到就**拒绝工作**（退 3），不自己发明一份命令清单。

AI 原生那六条性质（T-G31 §2）在 `main.py` 的 docstring 里逐条对应。
"""

from __future__ import annotations
