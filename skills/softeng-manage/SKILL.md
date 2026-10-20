---
name: softeng-manage
description: 本仓（program/engineering）软件工程管理总入口——把「开卡 → 派活 → 跑门 → 落地 → 巡检 → 复盘」串成一条不发散的流程。当你要新建工作项、把活派给号池工人、判断这棵树能不能合、落地一张卡、查今天该做什么、或某道门红了要定位时用；它只做路由与铁律，细节交给六个动作技能。
---

# 软工管理（本仓总入口）

这是一张**路由表 + 六条铁律**。它不重复子技能的操作细节 —— 要动手就按表跳过去。
本仓跑的是 `tools/wb_*.py` 那一套；技能文档里写的 `pipe` CLI 是框架另一条接法，
两者顺序与前置检查一致、命令不同 —— 动作与命令的逐条对照见 [动作映射](references/mapping.md)。

## 什么时候用

- 不确定「现在该走哪一步」（开卡 / 派活 / 跑门 / 落地 / 巡检 / 复盘）时。
- 本仓命令与技能文档对不上，想知道到底敲哪条。
- 要确认某条铁律（判据在哪、什么时候算落成）时。

## 什么时候别用

- 已经知道要走哪一步：直接去那个子技能，别在这里绕。
- 要判「算不算过」：判据在 `scripts/` `tools/` `tests/`；本技能只给路由，不抄判据。
- 换了 harness（注册方式 / 目录 / frontmatter）：改 `skills/GLUE-harness.md`，不改这里。
- 要产品口径决策：停下来问用户，别自己定。

## 前置检查

1. 我在哪棵树、哪条分支：`git worktree list` + `git branch --show-current`。
2. 工作区干净吗：`git status --porcelain -uno`（有别人的未提交改动就先停手）。
3. 队列里这张卡长什么样：`python -X utf8 tools/pipeline_view.py --json` 的 `cards` 块。
4. 先跑 `python -X utf8 scripts/audit_progress.py` 确认台账本身是活的（0.5 秒）。
5. 命令对照与六段流水线细则见 [命令对照](references/commands.md)。

## 真命令

| 段 | 你想要的 | 走哪个工具 | 细节 |
|---|---|---|---|
| ① 开卡 | 一张可派的卡 | 卡规格 + `docs/workbacklog.toml` 条目 | `pipe-card` |
| ② 派活 | 工人在自己树里干活 | `tools/wb_dispatch.py`（或号池） | `pipe-card` |
| ③ 跑门 | 这棵树能不能合 | `scripts/run_gates.py` + `gates/last.json` | `pipe-gate` |
| ④ 落地 | 落成一笔 | `tools/wb_land.py` | `pipe-land` |
| ⑤ 巡检 | 今天该做什么、谁在飞 | `tools/wb_daily.py` / `tools/pipeline_view.py` | `pipe-workbench` |
| ⑥ 复盘 | 哪一步坏了 | `tools/wb_verify.py` / `tools/wb_diag.py` / `tools/wb_reconcile.py` | `pipe-forensics` |

空目录起新骨架：`pipe-init`（`python -X utf8 framework/cli/main.py init --dir <目录>`）。

## 怎么读结果

- 「今天该做什么」：`python -X utf8 tools/wb_daily.py`（五个分区，空也要说「空」）。
- 六块现场（队列 / 门禁 / 判决 / 租约 / 栅栏 / 树）：`python -X utf8 tools/pipeline_view.py --report`。
- 「这一笔算不算落成」：`python -X utf8 tools/wb_verify.py --tree .`（五块，任一 FAIL 就先修那块）。
- 队列与 git 对不上：`python -X utf8 tools/wb_reconcile.py`。
- 台账分布有没有漂：`python -X utf8 tools/sync_counts.py --check`。

## 常见错与处置

| 症状 | 先看 |
|---|---|
| 门红 | `gates/last.json` 的失败门名 → 那道门的日志 → `pipe-forensics` |
| 落地被挡 | 申报缺证据 / 卡规格没进 git / 文书缺 `=== gaps ===` 段 |
| 工人不动 | `gates/diag/wb-<卡>.dispatch.log` 尾部；`tools/wb_diag.py` 定位 |
| 队列与栅栏不一致 | `tools/wb_reconcile.py` 的 stale 行 |
| 面板 / 读数怪 | 先跑 `tools/verify_panel_routes.py`，别猜 |
| 命令敲了没反应 | 是不是把 `pipe` CLI 当成了本仓主路径 —— 看 references 的对照表 |

## 复盘缺口细则（按主题拆进 references）

全量复盘入口是 `复盘/INDEX.md`（587 篇 / 58 缺口的三层索引，§5.2 是缺口清单）；下面按主题给操作指针，动手前按主题读对应那份，别凭印象：

- 派活（预声明 / 基点 / 白名单 / 攒批 / 增量收口）：[dispatch](references/dispatch.md)
- 看门狗与锁租约（判活 / 掐人还租约 / 锁分把带 TTL）：[watchdog](references/watchdog.md)
- 禁区与外部授权（宿主目录 / 外部模型用完就撤）：[safety](references/safety.md)
- 对抗复核与长任务（反空转 / 派生物噪声 / 复核常态化）：[ai-collab](references/ai-collab.md)
- 产品线结论（timeflow，不改本仓框架）：[product-lines](references/product-lines.md)
- 界面判据（主题令牌 / 非文字对比度）：[ui-notes](references/ui-notes.md)
- 文档口径：同一事实只许一处投影、第四份投影必须脚本对账（缺口 CF2）；口径漂移用「加注」治——保留原文 + 顶部加注「已被卡 N 推翻」，不原地改写（缺口 CF1）。
- 框架两条总纲：事实层是唯一真源、AI 只写「做了什么」的事实回报、结论与产物由库/门产出（缺口 FW1）；框架要能整体提升为独立仓、先跑抽取清单、先抽后搬（缺口 FW2）—— 操作面见 `pipe-init`。

依据：`复盘/INDEX.md`（§5.2 全量清单）、`复盘/文档重整方案.md`。

## 六条铁律

1. **判据在库与门，不在提示词。** 技能只写「怎么用才不出错」；删掉整个 `skills/`，框架仍要完整可用。
2. **先申报，再落地。** 没有 `success` 申报（带 `--files` 与 `--evidence`）的卡，落地会被挡住；不要绕过。
3. **链红就停手。** 门红了先修红：不放宽判据、不加豁免、不手改 `gates/last.json`。
4. **落地后核对封存。** `gates/last.json` 的 `ok=true` 且 `rev == HEAD^`（它封的是被落那笔的父提交）。
5. **工人不直接合主树。** 工人在 `.wt/<卡号>`（分支 `card/<卡号>`）干活，落地由接手的会话串链。
6. **一卡一域。** 卡规格的 `files` 必须等于工人真正碰的文件；碰域外文件会被守卫点名拒收。

## 自查

1. 我能说出这件事落在哪一段（①～⑥），以及对应哪个子技能。
2. 我引用的每条命令都在本仓跑得通（不是照抄 `pipe` CLI 的想象命令）。
3. 我没把判据抄进话里 —— 说的是「去哪个工具看」。
4. 我报的是**这棵树**的读数（`rev` / 分支 / 树路径对得上）。

> 流水线与铁律的来历见 `NOTES.md`；技能本身的写法见 [技能自检表](references/spec-checklist.md) 与
> `docs/reference/agent-skills-spec.md`。
