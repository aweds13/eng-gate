---
name: pipe-workbench
description: 用本仓「工作台」四件套看现场——一份读数（pipeline_view）→ 今日一页（wb_daily）→ 给工人注入状态（workbench_bridge）→ 工人面板（wb_dash）。当你要回答「现在谁在飞 / 今天该做什么 / 给工人什么开场白 / 工人动没动」时用；四件套全只读。
---

# pipe-workbench —— 工作台四件套

一条线：**一份读数 → 今日一页 → 注入 → 面板**。上游只有 `pipeline_view` 一个读数入口，
下游都只加工、不另读源文件（两份一漂必出事）。判据在四个工具里，这层只讲怎么用。

## 什么时候用

- 主控要**一份现场读数**：队列 / 门禁 / 判决 / 租约 / 栅栏 / 树，六块一起看。
- 每天**巡检**「今天该做什么」：待派几张、在飞几张、哪些批到收口、落了没翻状态。
- 派活时给工人的开场白要一段**同源**状态（我在哪张卡 / 谁在飞 / 域占用 / 该看哪个产物）。
- 要盯**工人动没动**（在不在跑、跑到哪、有没有被掐）。

## 什么时候别用

- 要**改**状态：四件套**全只读**（唯一占端口的是 `wb_dash` 起一个本地只读页面）。
  派活 / 申报 / 收口走 `tools/wb_dispatch.py` / `tools/wb_task.py` / `tools/wb_land.py`。
- 要**跑门禁**或读三值判决：用 `pipe-gate`；这里只把「最近一次门禁」当读数块。
- 想**另写一份读数器**：六块的唯一入口是 `tools/pipeline_view.py`，缺块它如实标 `null` + note。
- 想把面板当**内容判据**：它只报「在不在动」，不判干得对不对。

## 前置检查

1. **在哪跑**：四件套从自身位置推仓库根；池状态住**主工作树**的 `gates/diag/` ——
   从别的树跑 `wb_daily` / `workbench_bridge` 要 `--root` 指回主树。
2. **面板要多树视野**：从主工作区起 `wb_dash`（只扫主树与本仓 `.wt/*/gates/diag/`）。
3. 上一道能跑通：`python -X utf8 tools/pipeline_view.py --report` 六块里缺哪块它自己会说。
4. 参数与产物全表见 [四件套](references/tools.md)。

## 真命令

```bash
python -X utf8 tools/pipeline_view.py --report     # ① 一份读数（人读）
python -X utf8 tools/pipeline_view.py --json       #    机器读
python -X utf8 tools/wb_daily.py                   # ② 今日一页（只读）
python -X utf8 tools/workbench_bridge.py --card <卡号> --tree <树标签> --batch <批号>  # ③ 注入
python -X utf8 tools/wb_dash.py --port 8787        # ④ 面板（默认只绑回环）
```

## 怎么读结果

- 六块齐不齐（`cards` / `gates` / `verdicts` / `leases` / `fences` / `worktrees`）：`python -X utf8 tools/pipeline_view.py --json`（缺源 = `null` + `*_note` 写原因，不许拿空对象冒充「拉到了、是空的」）。
- 今天该做什么（待派 / 在飞 / 到收口的批 / 落了没翻状态 / 内存）：`python -X utf8 tools/wb_daily.py --json`。
- 注入段读法（卡行 → 租约 → 判决 → 栅栏；缺源整段省略并写原因；同输入两次逐字节相同）：`python -X utf8 tools/workbench_bridge.py --card <卡号>`。
- 面板读法（每组一行「卡 / 在不在动 / 在跑什么与卡死阈值 / 判决」，最新活动在最上面）：`python -X utf8 tools/wb_dash.py`（口径同它的 docstring）。
- 「没数据」不等于「没人干活」：租约为空先确认注册表读没读到，`python -X utf8 tools/pipeline_view.py --json` 会给 `null` 带 note。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 某块 `null` 带 note | 来源文件缺 / 坏（如没有 `gates/last.json`） | 按 note 补来源；**别当空数据用** |
| `wb_daily` 读不到租约 / 批 | 从非主树跑，池状态在主树 `gates/diag/` | 加 `--root <主树>` |
| 面板看不到别的树 | 从某棵 worktree 里起的 | 回主工作区起 `wb_dash` |
| 注入说「查不到卡 X」 | `--card` 与队列 `id` 对不上 | 用 `cards` 块里的 `id` 原样传 |
| 同输入两次输出不同 | 工具被改出非幂等（时戳 / 遍历序） | 口径破洞：停手报主控，别手工圆 |
| 想靠面板判「内容对不对」 | 面板只报在不在动 | 内容对错看判决文件与主控复核 |

## 自查

1. 我用的**同一份**读数源：先 `pipeline_view`，后加工；没有自己重读队列。
2. 我报的六块里，每块要么有数据，要么带了 `null` + note —— 没有静默留空。
3. 我在**主树**里跑的巡检（或显式给了 `--root`），租约读得到。
4. 我给工人的开场白与面板读数来自同一次运行（不是两趟拼的）。

> 一份读数 = 卡 207；今日一页 = 卡 220；注入 = 卡 224；面板口径 = `tools/wb_dash.py` 的 docstring。
> 删掉整个 `skills/` 目录，四件套照常能用。
