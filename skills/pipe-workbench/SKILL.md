---
name: pipe-workbench
description: 用本仓「工作台」四件套看现场——一份读数（pipeline_view）→ 今日一页（wb_daily）→ 给工人注入状态（workbench_bridge）→ 工人面板（wb_dash）；外加派活后的收工看守（wb_watch / Trae 侧的 trae_watch）。当你要回答「现在谁在飞 / 今天该做什么 / 给工人什么开场白 / 工人动没动 / 那张卡收工没有」时用；全部只读（wb_watch 只有加 --write-done 才落事件）。
---

# pipe-workbench —— 工作台四件套

一条线：**一份读数 → 今日一页 → 注入 → 面板**。上游只有 `pipeline_view` 一个读数入口，
下游都只加工、不另读源文件（两份一漂必出事）。判据在四个工具里，这层只讲怎么用。

## 什么时候用

- 主控要**一份现场读数**：队列 / 门禁 / 判决 / 租约 / 栅栏 / 树，六块一起看。
- 每天**巡检**「今天该做什么」：待派几张、在飞几张、哪些批到收口、落了没翻状态。
- 派活时给工人的开场白要一段**同源**状态（我在哪张卡 / 谁在飞 / 域占用 / 该看哪个产物）。
- 要盯**工人动没动**（在不在跑、跑到哪、有没有被掐）。
- 要确认**那张卡收工没有**（`wb_watch` 的收工信号，见下面「看完工信号」）。

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

## 看完工信号（wb_watch，卡 E7）

派活器**默认**已经挂好收工看守（`tools/wb_dispatch.py --execute` 后那一屏有 `[看 ] 看守已起`），
所以「工人收工了吗」不用靠每两分钟敲一次 `--status`。要自己看或重挂：

```bash
python -X utf8 tools/wb_watch.py --cards <卡号>                 # 只读：盯到收工 / 判死 / 超时
python -X utf8 tools/wb_watch.py --cards <卡号> --write-done    # 顺手写 wb-<卡>.done + 通知一行
python -X utf8 tools/wb_watch.py --cards <卡号> --mode shared   # 合用看守：引用计数 +1/-1/归 0
```

- **收工事件**：`gates/diag/wb-<卡>.done`（一行 JSON：`card` / `task` / `exit_code` / `at` /
  `log` / `report`）；中间态看 `gates/diag/notifications.jsonl` 末尾那一行。
- **退出码怎么读**：`0` 全部收工 · `3` 有卡判死（没跑完就断了）· `4` 超时
  （**没判决不算成功**）· `5` 合用看守心跳过期（已写 `watcher-stale`：这批没人守了）· `2` 用法 / 批次读不到。
- **合用看守的计数**在 `gates/diag/watch-registry.json`：派一张 `+1`、出判决 `-1`、
  归 `0` 才写一条 `batch-done` —— 想看中间态就看这份文件，别等最后的通知。
- **Trae 侧另有一份看守**（`tools/trae_watch.py`，卡 E29）：面板里的任务没有进程、也没有判决，
  它每拍采一次 DOM（图标 / 正文长度 / 正文哈希 / 是否被终止）判四态，落点是**三种不同的文件** ——
  · **收工**（图标 `chat-icon-stop` → `chat-icon-arrow-up`）⇒ `gates/diag/wb-<卡>.done`（与工人同一种行）+ 通知 `done`；
  · **被终止**（正文出现「手动终止输出」）⇒ `gates/diag/trae-<卡>.stopped` + 通知 `trae-stopped`，退 **5**；
  · **空转塌陷**（图标仍 stop、正文 ≥ `--stale-min` 一字未变、给了 `--tree` 时树也不动）⇒ 同一个 `.stopped` + 通知 `trae-stalled`，退 **5**。
  不给 `--write-done` 就只读；每拍明细在 `gates/diag/trae-watch.jsonl`。

## 复盘缺口（一份读数 / 容错 / 端口）

- （缺口 PN1）面板只认「一份读数」单一入口（pipeline_view）：各面板不许自己再算一遍，否则同一现场两个数 —— 任何新读数需求先加进 `python -X utf8 tools/pipeline_view.py --json`，下游只加工。证据：`复盘/卡/卡207-一份读数.md`、`复盘/卡/卡231-W7收口面.md`、`复盘/问题清单-组3.md`
- （缺口 PN2）面板读日志要容错坏行 / 幻影行：解析失败给 note + 原样行，不许整页崩或静默吞 —— 看到坏行先确认面板给了 note，别拿「没显示」当「没发生」。证据：`复盘/面板幻影行与日志容错-T-G137.md`、`复盘/文档重整方案.md`、`复盘/索引-台账号到复盘.md`
- （缺口 EN3）端口按树隔离：挑端口用「能不能 bind」，接入前验明正身（PID + 映像名），不许猜一个空号 —— 起 `wb_dash` 等服务前实测 bind；撞端口先查占用者是谁再换段。证据：`复盘/DSH插件-定点深读-第二批.md`、`复盘/DSH插件-参考与结论.md`、`复盘/段2设计决策-提醒与附件打开方式.md`

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 某块 `null` 带 note | 来源文件缺 / 坏（如没有 `gates/last.json`） | 按 note 补来源；**别当空数据用** |
| `wb_daily` 读不到租约 / 批 | 从非主树跑，池状态在主树 `gates/diag/` | 加 `--root <主树>` |
| 面板看不到别的树 | 从某棵 worktree 里起的 | 回主工作区起 `wb_dash` |
| 注入说「查不到卡 X」 | `--card` 与队列 `id` 对不上 | 用 `cards` 块里的 `id` 原样传 |
| 工人收工了却没人知道 | 派活时用了 `--no-watch`（那一屏会明说） | 用 `python -X utf8 tools/wb_watch.py --cards <卡号>` 单看，或看 `.done` 在不在 |
| 同输入两次输出不同 | 工具被改出非幂等（时戳 / 遍历序） | 口径破洞：停手报主控，别手工圆 |
| 想靠面板判「内容对不对」 | 面板只报在不在动 | 内容对错看判决文件与主控复核 |

## 自查

1. 我用的**同一份**读数源：先 `pipeline_view`，后加工；没有自己重读队列。
2. 我报的六块里，每块要么有数据，要么带了 `null` + note —— 没有静默留空。
3. 我在**主树**里跑的巡检（或显式给了 `--root`），租约读得到。
4. 我给工人的开场白与面板读数来自同一次运行（不是两趟拼的）。

> 一份读数 = 卡 207；今日一页 = 卡 220；注入 = 卡 224；面板口径 = `tools/wb_dash.py` 的 docstring。
> 删掉整个 `skills/` 目录，四件套照常能用。
