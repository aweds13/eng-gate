r"""外包号池的**只读逻辑包 + 写面地基**（卡 106 · T-G202；卡 108 加登记与守卫）。

CLI 与 MCP 共用同一批函数。

为什么有它（用户原话「你可以把之前相关的脚本集成进里面吗」）：派活这套逻辑原先散在
`wb_plan.py` / `wb_status.py` / `wb_review.py` / `wb_brief.py` / `pool_mcp.py` 等脚本里，
**同一个判据有多份实现**（白名单越界三处、作业状态两处）。换个窗口的 AI 想用，得读懂 6 个
脚本；而"两份真源"正是本仓最忌的。

这一包收**只读那一半 + 写面地基**，且**只搬不改语义**：

| 模块 | 一句话 |
|---|---|
| `pool.plan`   | 队列 / 冲突域 / 排批（从 `wb_plan.py` 抽）+ 计划渲染 |
| `pool.jobs`   | 作业状态三态 + 扫 `gates/diag/wb-*.jsonl` + 时间线渲染 |
| `pool.locks`  | 门禁锁的**薄封装**（给 `gate_lock.py status` 的说辞与判据） |
| `pool.models` | 号池模型白名单**只读**（批准 ∩ 可用；`infra/pool/` 只读） |
| `pool.review` | **白名单越界**的唯一实现（把三处收敛成一处） |
| `pool.registry` | 作业登记：谁占了哪棵树 / 哪个冲突域（租约 JSON，卡 108 · T-G205） |
| `pool.guards` | 三条自家守卫（树 / 冲突域 / 门禁锁）+ 日志不许覆盖（纯函数） |
| `pool.lastgood` | 写盘纪律：原子替换 + `.bak` 落后一次写 + fail-closed 读（卡 A330） |

★ 边界（如实写）：本包提供**登记（`pool.registry`）与守卫（`pool.guards`）**；但**不派活、
不跑门禁、不起进程** —— 真正动手的写面（MCP 的 `pool_dispatch` / `pool_cancel`）在
`tools/pool_mcp.py`，它只 import 本包、不在这里重写判据。
"""
