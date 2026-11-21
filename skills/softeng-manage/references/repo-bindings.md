# softeng-manage —— 本仓绑定（仓无关路由之外的那一层）

> `SKILL.md` 是六段流水线 + 六条铁律（换仓不变）；**这一页只放"这个仓是什么样"**。
> 换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。

## 六段各敲哪条（本仓真命令）

| 段 | 你想要的 | 本仓真命令 | 细节 |
|---|---|---|---|
| ① 开卡 | 一张可派的卡 | 卡规格 + `docs/workbacklog.toml` 条目（`python -X utf8 tools/wb_card.py add …`） | `pipe-card` |
| ② 派活 | 工人在自己树里干活 | `python -X utf8 tools/wb_dispatch.py --card <卡> --spec <规格> --execute` | `pipe-card` |
| ③ 跑门 | 这棵树能不能合 | `python -X utf8 scripts/run_gates.py`（判决落 `gates/last.json`） | `pipe-gate` |
| ④ 落地 | 落成一笔 | `python -X utf8 tools/wb_land.py --card <卡> --task <台账号> --tree .wt/<卡>` | `pipe-land` |
| ⑤ 巡检 | 今天该做什么、谁在飞 | `python -X utf8 tools/wb_daily.py` / `python -X utf8 tools/pipeline_view.py --report` | `pipe-workbench` |
| ⑥ 复盘 | 哪一步坏了 | `python -X utf8 tools/wb_verify.py` / `tools/wb_diag.py` / `tools/wb_reconcile.py` | `pipe-forensics` |

**框架层那条接法**：本仓**也有** `pipe` CLI（`python -X utf8 framework/cli/main.py`，子命令
`init / gate / doctor / card / claim / land / ledger / trace`，全局开关 `--config` 必须写在子命令**前**）。
但它读 `pipeline.toml`，而本仓根**没有**那份文件 ⇒ 在本仓主路径上别用它，用 `tools/wb_*.py` 那一套。
逐条对照见 [动作映射](mapping.md)。

## 权威文档指针

- 门禁怎么跑、怎么读：`docs/subsystems/ci/测试流程.md`（五维口径与决策树）、`docs/subsystems/ci/云门禁机.md`。
- 复盘三层索引：`复盘/INDEX.md`（由 `python -X utf8 scripts/retro/retro_index.py` 生成，§5 是缺口清单）。
- 文档分层：`docs/文档架构.md`、[文档五层](doc-layers.md)。
- 技能自身规范：`docs/reference/agent-skills-spec.md` + [技能自检表](spec-checklist.md)。

## 复盘缺口细则（历史证据层，不写在本页正文）

按主题给操作指针，动手前按主题读对应那份，别凭印象：

- 派活（预声明 / 基点 / 白名单 / 攒批 / 增量收口）：[dispatch](dispatch.md)
- 看门狗与锁租约（判活 / 掐人还租约 / 锁分把带 TTL）：[watchdog](watchdog.md)
- 禁区与外部授权（宿主目录 / 外部模型用完就撤）：[safety](safety.md)
- 对抗复核与长任务（反空转 / 派生物噪声 / 复核常态化）：[ai-collab](ai-collab.md)
- 产品线结论（timeflow，不改本仓框架）：[product-lines](product-lines.md)
- 界面判据（主题令牌 / 非文字对比度）：[ui-notes](ui-notes.md)
- 技能三层与登记表（索引 / 操作 / 判据）：[skills-layers](skills-layers.md)
- 文档五层（意图 / 规格 / 契约 / 实现 / 品味）：[doc-layers](doc-layers.md)
- 资产三层（timeflow 是产品 / pool 是谁来做 / infra 是在什么机器上）：[asset-layers](asset-layers.md)
- 文档口径（缺口 CF2 / CF1）：同一事实只许一处投影、第四份投影必须脚本对账。**口径漂移怎么治，按文档类型分**
  （2026-10-28 用户定的分工，别自己另立一套）：
  - **reference / how-to**（读者拿它当「现在是什么」「该怎么做」）：**就地改成当前真值**。证据（为什么改、
    谁改的、旧值是多少）留在卡规格 + `docs/changelog.d/<台账号>.md` + 台账 `evidence`，**不进这份文档**。
  - **explanation / 历史复盘**（讲「当时为什么这么决定」）：**加注** —— 保留原文 + 顶部加注「已被卡 N 推翻」，
    因为删掉原文等于毁证据。加注必须带**日期 + 推翻它的卡号 / 台账号**。
  - 判据一句话：**这份文档的读者会拿它当「现在的事实」用吗？会 ⇒ 就地改；不会（它讲的是历史）⇒ 加注。**
- 框架两条总纲：事实层是唯一真源、AI 只写「做了什么」的事实回报、结论与产物由库/门产出（缺口 FW1）；
  框架要能整体提升为独立仓、先跑抽取清单、先抽后搬（缺口 FW2）—— 操作面见 `pipe-init`。

依据：`复盘/INDEX.md`（§5.2 全量清单）、`复盘/文档重整方案.md`。

## 本仓读数（写日期，别当常量引用）

- 复盘篇数、门数、台账张数这类**现算量**一律以命令输出为准；要写就写带日期的读数。
- 2026-11-21 实测：门禁 **23 道**（真源 `scripts/run_gates.py` 的 `GATE_PROFILES`，成员在 `gates/defs/`）；
  台账 **425 张**（`python -X utf8 tools/wb_plan.py check`）；`wb_daily` 有 **7** 个分区
  （`[待派]` / `[在飞]` / `[批·等到提交]` / `[批·还在收集]` / `[内存]` / `[门禁]` / `[签到]`）。
  `复盘/` 目录实测 **1122** 篇（根 272 + `卡/` 459 + `交接.d/` 391），而 `复盘/INDEX.md` 自身标 **773 篇**
  —— 那两份数字来自不同口径（索引只收被写进索引的），引用时**说明是哪一个**。
