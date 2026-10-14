---
name: pipe-workbench
description: 用本仓的「工作台」四件套看现场 —— 一份读数（pipeline_view）→ 今日一页（wb_daily）→ 给工人注入状态（workbench_bridge）→ 工人面板（wb_dash）。当你要回答「现在谁在飞 / 今天该做什么 / 给工人什么开场白 / 工人动没动」时用。
---

# pipe-workbench —— 工作台四件套：从一份读数到面板

## 什么时候用

- 主控要**一份现场读数**：队列 / 门禁 / 判决 / 租约 / 栅栏 / 树，六块一起看。
- 每天**巡检**「今天该做什么」：待派几张、在飞几张、哪些批到了收口、哪些卡落了没翻状态、内存够不够。
- **派活**时给工人的开场白要一段**同源**的工作台状态（我在哪张卡 / 谁在飞 / 域占用 / 该看哪个产物）。
- 要盯**工人动没动**（在不在跑、跑到哪、有没有被掐）—— 开面板看。

## 什么时候别用

- 要**改**任何状态：四件套**全只读**（唯一会占端口的是 wb_dash 起一个本地只读页面）；
  派活 / 认领 / 收口用 `tools/wb_dispatch.py` / `tools/wb_task.py` / `tools/wb_land.py`，不在这层。
- 要**跑门禁**或读三值判决的口径：那是 pipe-gate 那份技能的事；这里只把「最近一次门禁」当读数块。
- 想**另写一份读数器**：六块的唯一读数入口是 `tools/pipeline_view.py`（卡 207），缺块它会如实
  标 `null` + 原因；别在别处把同源文件再读一遍 —— 两份一漂必出事。

## 前置检查

1. **在哪跑**：四件套都从自身位置推仓库根；池状态（租约 / 批状态）住**主工作树**的 `gates/diag/`
   —— 从别的树跑 `wb_daily` / `workbench_bridge` 要 `--root` 指回主树。
2. **面板要多树视野**：从主工作区起 `wb_dash`（只扫主树与本仓 `.wt/*/gates/diag/`；
   从某棵 worktree 里起看不到兄弟树）。
3. **上一道**：`python -X utf8 tools/pipeline_view.py --report` 能跑通、六块里缺哪块它自己会说。

## 真命令

```bash
# ① 一份读数（六块；--json 给机器、--report 给人）
python -X utf8 tools/pipeline_view.py --report

# ② 今日一页（今天该做什么；只读）
python -X utf8 tools/wb_daily.py

# ③ 给工人注入工作台状态（派活器与「面」都调它）
python -X utf8 tools/workbench_bridge.py --card <卡号> --tree <树标签> --batch <批号>

# ④ 工人面板（默认 http://127.0.0.1:8787，只绑回环）
python -X utf8 tools/wb_dash.py
```

## 怎么读结果

- **六块齐不齐**：`cards / gates / verdicts / leases / fences / worktrees` 各一块；**缺源 = 该块
  `null` + `*_note` 写原因**（不许拿空对象冒充「拉到了、是空的」）。复核
  `python -X utf8 tools/pipeline_view.py --json`。
- **今天该做什么**：待派（队列 pending）/ 在飞（租约）/ 到 `awaiting-commit` 的批 /
  落了没翻状态的卡（`done`、`failed` 之外都算没翻）/ 门禁内存够不够 —— 一屏说完。复核
  `python -X utf8 tools/wb_daily.py --json`。
- **注入段读法**：给了 `--card` 先回卡行（查不到会明说「N 张里查不到卡 X」），再依次租约 /
  判决 / 栅栏；每段缺源**整段省略并写原因**；同输入连跑两次**逐字节相同**（幂等是它的验收）。
  复核 `python -X utf8 tools/workbench_bridge.py --card <卡号>`。
- **面板读法**：每组一行「卡 / 在不在动 / 在跑什么与本次卡死阈值 / 判决」，**最新活动在最上面**；
  「可能卡死」只在**有在更新的心跳**时才允许出现，没判决又没心跳的如实显示「已停（无判决）」。
  复核 `python -X utf8 tools/wb_dash.py`（口径同它的 docstring）。
- **别把「没跑」读成「没卡」**：租约为空 ≠ 没人干活 —— 先确认注册表读没读到
  （读不到时 pipeline_view 的 `leases` 会是 `null` 带 note）。复核
  `python -X utf8 tools/pipeline_view.py --json`。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 某块 `null` 带 note | 来源文件缺 / 坏（如没有 `gates/last.json`） | 按 note 补来源；**别当空数据用** |
| `wb_daily` 读不到租约 / 批 | 从非主树跑，池状态在主树 `gates/diag/` | 加 `--root <主树>` |
| 面板看不到别的树 | 从某棵 worktree 里起的 | 回主工作区起 `wb_dash` |
| 注入说「查不到卡 X」 | `--card` 与队列 `id` 对不上 | 用 pipeline_view `cards` 里的 `id` 原样传 |
| 同输入两次输出不同 | 工具被改出非幂等（时戳 / 遍历序） | 这是口径破洞：停手报主控，别手工圆 |
| 想靠它判「内容对不对」 | 面板只报「在不在动」，不判内容 | 内容对错看判决文件与主控复核 |

> 判据都在工具与其源头卡里：一份读数 = 卡 207；今日一页 = 卡 220；注入 = 卡 224；面板口径 =
> `tools/wb_dash.py` docstring。本层只教「怎么用、怎么读」—— 删掉整个 `skills/`，四件套照常能用。
