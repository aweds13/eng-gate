"""MCP（Model Context Protocol）—— 命令表四个面里的第四个（T-G65）。

用户 2026-09-23 那句话是这条线的起点：「最好就是 4 个面集中到一个点，然后调用同一个点的东西」。
四个面 = 界面按钮 / ⌘K 面板 / 命令行 / **AI·MCP**；「一个点」= `docs/commands.toml` +
它背后的那道 HTTP 边界。这个包就是第四个面：

- `server.py` 讲 **stdio 上的 JSON-RPC**（一行一个消息），把命令当工具暴露给 AI 客户端；
- 工具清单**由 `timeflow.cli.registry` 生成**（而它与命令表由门禁双向核对），
  所以"AI 能做什么"与"界面上有什么"永远是同一张表 —— 不手抄第二份；
- `tools/call` **直接调 CLI**（`timeflow.cli.main.main()`），连参数解析都不另写一套：
  写出去的效果、错误码、退出码与人在终端里敲是同一条路。

默认关：没有 `--allow-write` 就不列出写工具（详见 `server.py` 顶部）。
"""
