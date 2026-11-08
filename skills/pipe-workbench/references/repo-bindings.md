# pipe-workbench —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放"这个仓是什么样"**：四条命令落在哪个路径、产物写到哪、退出码是多少、
> 本仓现读几段、历史证据挂在哪。`SKILL.md` 里的动作与读法换仓也不变；
> 换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。

## 四件套的真实路径与参数

| # | 入口 | 本仓路径 | 参数（实测 `--help`） |
|---|---|---|---|
| ① | 读数入口 | `tools/pipeline_view.py` | `--json` / `--report` / `--root` |
| ② | 今日一页 | `tools/wb_daily.py` | `--root`（默认主工作树）/ `--json` |
| ③ | 注入 | `tools/workbench_bridge.py` | `--card` / `--tree` / `--batch` / `--root` |
| ④ | 面板 | `tools/wb_dash.py` | `--port`（默认 8787）/ `--host`（默认 `127.0.0.1`） |

```bash
python -X utf8 tools/pipeline_view.py --report     # ① 一份读数（人读）
python -X utf8 tools/pipeline_view.py --json       #    机器读
python -X utf8 tools/wb_daily.py                   # ② 今日一页（只读）
python -X utf8 tools/workbench_bridge.py --card <卡号> --tree <树标签> --batch <批号>  # ③ 注入
python -X utf8 tools/wb_dash.py --port 8787        # ④ 面板（默认只绑回环）
```

- 面板的端口 / 地址默认值在 `tools/wb_dash.py:601-602`（`--port` 8787、`--host` 127.0.0.1）。
- **池状态住主工作树**的 `gates/diag/`；从别的树跑今日一页 / 注入要 `--root` 指回主树。
- 面板只扫**主树**与本仓 `.wt/*/gates/diag/` —— 从某棵 worktree 里起就看不到兄弟树。

## 六块的源（别自己重读）

块 id 与源文件在 `tools/pipeline_view.py:97-125` 一张表里：

| 块 | 源 |
|---|---|
| `cards` | `docs/workbacklog.toml` |
| `gates` | `gates/last.json` |
| `verdicts` | `gates/diag/wb-*.verdict.txt` / `.report.md` |
| `leases` | `gates/diag/pool-registry.json` |
| `fences` | `gates/diag/batch/*.toml` |
| `worktrees` | `git worktree list` |

## 今日一页现读几段（★ 别写死成旧数字）

**2026-11-08 实跑 `python -X utf8 tools/wb_daily.py`：去重后 7 段**
（`[待派]` / `[在飞]` / `[批·等到提交]` / `[批·还在收集]` / `[内存]` / `[门禁]` / `[签到]`），
渲染顺序见 `tools/wb_daily.py:384-402`（六个 `_render_*` 加批状态两段）。

另有**条件行**，不是恒在分区：`[卡池]`（还没有卡池时）、`[读数]`（一份读数读不到时）、
`[已落没翻 status]`（stale 时）、`[批]`（`batch_notes`）。

> 历史陈述「五个分区」是旧读数 —— 已按 2026-11-08 实跑改成 7 段。
> 同一条错也写在 `skills/softeng-manage/SKILL.md:52`（那份归别人改，本技能不碰）。

## 收工看守：退出码、产物、阈值

参数（`tools/wb_watch.py:913-931`）：`--cards`（可多张）/ `--batch` / `--timeout` / `--interval` /
`--root` / `--mode {one,shared}`（默认 `one`）/ `--write-done` / `--since`。

退出码（`tools/wb_watch.py:97-101`）：

| 码 | 意思 |
|---|---|
| `0` | 全部收工 |
| `3` | 有卡判死（非零退出，没跑完就断了） |
| `4` | 超时（**没判决不算成功**） |
| `5` | 合用看守自己死了（心跳过期 + 还有卡没判决 ⇒ 写 `watcher-stale` 事件） |
| `2` | 用法错 / 读不到批次预声明 |

产物：

- `gates/diag/wb-<卡>.done` —— 一行 JSON：`card` / `task` / `exit_code` / `at` / `log` / `report`。
- `gates/diag/notifications.jsonl` —— 中间态看末尾那一行（与 `wb_notify` 同一份文件、同一种行）。
- `gates/diag/watch-registry.json` —— 合用看守的引用计数：派一张 `+1`、出判决 `-1`、
  归 `0` 才写一条 `batch-done` 并退出。

本仓的挂法：派活器 `tools/wb_dispatch.py --execute` 之后**默认**就起一份看守（那屏有 `[看 ] 看守已起`），
`--no-watch` 才不起 —— 所以「工人收工了吗」不用靠每两分钟敲一次 `--status`。

```bash
python -X utf8 tools/wb_watch.py --cards <卡号>                 # 只读：盯到收工 / 判死 / 超时
python -X utf8 tools/wb_watch.py --cards <卡号> --write-done    # 顺手写 wb-<卡>.done + 通知一行
python -X utf8 tools/wb_watch.py --cards <卡号> --mode shared   # 合用看守：引用计数 +1/-1/归 0
```

## Trae 侧那份看守（面板里的任务没有进程、也没有判决）

参数（`tools/trae_watch.py:453-470`）：`--task`（**必填**，面板任务的标题子串）/ `--card`（**必填**）/
`--tree` / `--root` / `--interval`（30 s）/ `--timeout`（5400 s）/ `--stale-min`（10 min）/
`--port` / `--write-done` / `--json`。

- 锚点（`tools/trae_watch.py:105-107`）：`chat-icon-stop`（在跑）→ `chat-icon-arrow-up`（真收工）；
  正文出现「手动终止输出」= 被掐。
- `--stale-min 10` 是**本仓默认**；`<= 0` = **关掉空转判定**（`tools/trae_watch.py:188`：
  「0 分钟没动」不是读数，是「别判空转」的开关写法）。
- 三种落点（`tools/trae_watch.py:110`、`:124-125`、通知名 `:90-91`）：
  · 收工 ⇒ `gates/diag/wb-<卡>.done`（与工人同一种行）+ 通知 `done`；
  · 被终止 / 空转 ⇒ `gates/diag/trae-<卡>.stopped` + 通知 `trae-stopped` / `trae-stalled`，退 **5**；
  · 每拍明细追加进 `gates/diag/trae-watch.jsonl`。
- 退出码（`tools/trae_watch.py:95-99`）：`0` 真收工 · `2` 用法 · `3` 采样就没成（node / CDP / 页面读不到）·
  `4` 超时 · `5` 被终止 / 空转塌陷。

## 复盘缺口（一份读数 / 容错 / 端口）

这一节是**历史证据层**：每条缺口挂 2–3 份复盘。读它为了知道「为什么有这条检查」，不是当判据用。

- （缺口 PN1）面板只认「一份读数」单一入口：各面板不许自己再算一遍，否则同一现场两个数 ——
  任何新读数需求先加进 `python -X utf8 tools/pipeline_view.py --json`，下游只加工。
  证据：`复盘/卡/卡207-一份读数.md`、`复盘/卡/卡231-W7收口面.md`、`复盘/问题清单-组3.md`
- （缺口 PN2）面板读日志要容错坏行 / 幻影行：解析失败给 note + 原样行，不许整页崩或静默吞 ——
  看到坏行先确认面板给了 note，别拿「没显示」当「没发生」。
  证据：`复盘/面板幻影行与日志容错-T-G137.md`、`复盘/文档重整方案.md`、`复盘/索引-台账号到复盘.md`
- （缺口 EN3）端口按树隔离：挑端口用「能不能 bind」，接入前验明正身（PID + 映像名），不许猜一个空号 ——
  起 `wb_dash` 等服务前实测 bind；撞端口先查占用者是谁再换段。
  证据：`复盘/DSH插件-定点深读-第二批.md`、`复盘/DSH插件-参考与结论.md`、`复盘/段2设计决策-提醒与附件打开方式.md`

## 来历卡号（改这一份时对照）

一份读数 = 卡 207；今日一页 = 卡 220；注入 = 卡 224；面板口径 = `tools/wb_dash.py` 的 docstring；
收工看守 = 卡 E7；Trae 侧看守 = 卡 E29。
