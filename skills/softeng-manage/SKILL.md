---
name: softeng-manage
description: 软件工程管理总入口——把「开卡 → 派活 → 跑门 → 落地 → 巡检 → 复盘」串成一条不发散的流程。当你要新建工作项、把活派给号池工人、判断这棵树能不能合、落地一张卡、查今天该做什么、或某道门红了要定位时用；它只做路由与铁律，细节交给六个动作技能。换一个仓只需换 references/repo-bindings.md。
---

# 软工管理（总入口）

这是一张**路由表 + 六条铁律**。它不重复子技能的操作细节 —— 要动手就按表跳过去。

> 本页只写**换仓不变的东西**：六段流水线、铁律、自查。
> **本仓的命令落在哪、读入口叫什么、哪些文档是权威、哪些数字不许引用**：全在
> [本仓绑定](references/repo-bindings.md)（相对链接，只深一层）。换一个仓用这套技能，
> **只换那一份**，别改本页。

## 什么时候用

- 不确定「现在该走哪一步」（开卡 / 派活 / 跑门 / 落地 / 巡检 / 复盘）时。
- 技能文档里的命令与本仓跑得通的那条对不上，想知道到底敲哪条。
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
5. 本仓命令对照（六段各敲哪条）与流水线细则见 [本仓绑定](references/repo-bindings.md)；
   与框架 CLI 的逐条映射见 [动作映射](references/mapping.md)。

## 真命令

| 段 | 你想要的 | 走哪个动作技能 | 本仓敲哪条 |
|---|---|---|---|
| ① 开卡 | 一张可派的卡 | `pipe-card` | 见 repo-bindings |
| ② 派活 | 工人在自己树里干活 | `pipe-card` | 见 repo-bindings |
| ③ 跑门 | 这棵树能不能合 | `pipe-gate` | 见 repo-bindings |
| ④ 落地 | 落成一笔 | `pipe-land` | 见 repo-bindings |
| ⑤ 巡检 | 今天该做什么、谁在飞 | `pipe-workbench` | 见 repo-bindings |
| ⑥ 复盘 | 哪一步坏了 | `pipe-forensics` | 见 repo-bindings |

从零起一条链，先分清两条路（这两条与仓无关）：

- **框架层（要一份自己的门禁配置 + 门表 + 钉子，铺到某个目录）**：`pipe-init`。它自带模板。
- **工作链（在一个已有仓内新开一个项目目录，队列 / 卡 / 树 / 落地走自己那套工具）**：`pipe-new`。

## 怎么读结果

- 「今天该做什么」：`python -X utf8 tools/wb_daily.py`（分区一屏给全，空也要说「空」）。
- 六块现场（队列 / 门禁 / 判决 / 租约 / 栅栏 / 树）：`python -X utf8 tools/pipeline_view.py --report`。
- 「这一笔算不算落成」：`python -X utf8 tools/wb_verify.py --tree .`（五块，任一 FAIL 就先修那块）。
- 队列与 git 对不上：`python -X utf8 tools/wb_reconcile.py`。
- 台账分布有没有漂：`python -X utf8 tools/sync_counts.py --check`。

## 常见错与处置

| 症状 | 先看 |
|---|---|
| 门红 | 判决文件里的失败门名 → 那道门的日志 → `pipe-forensics` |
| 落地被挡 | 申报缺证据 / 卡规格没进 git / 文书缺 `=== gaps ===` 段 |
| 工人不动 | 那张卡的派活日志尾部；`python -X utf8 tools/wb_diag.py` 定位 |
| 队列与栅栏不一致 | `python -X utf8 tools/wb_reconcile.py` 的 stale 行 |
| 面板 / 读数怪 | 先跑 `python -X utf8 tools/verify_panel_routes.py`，别猜 |
| 命令敲了没反应 | 是不是把框架 CLI 当成了本仓主路径 —— 看 [本仓绑定](references/repo-bindings.md) |

## 六条铁律

1. **判据在库与门，不在提示词。** 技能只写「怎么用才不出错」；删掉整个 `skills/`，框架仍要完整可用。
2. **先申报，再落地。** 没有 `success` 申报（带 `--files` 与 `--evidence`）的卡，落地会被挡住；不要绕过。
3. **链红就停手。** 门红了先修红：不放宽判据、不加豁免、不手改门禁判决文件。
4. **落地后核对封存。** 判决文件的 `ok=true` 且 `rev` 是被落那笔的**父提交**。
5. **工人不直接合主树。** 工人在自己的卡树（分支 `card/<卡号>`）干活，落地由接手的会话串链。
6. **一卡一域。** 卡规格的 `files` 必须等于工人真正碰的文件；碰域外文件会被守卫点名拒收。

## 自查

1. 我能说出这件事落在哪一段（①～⑥），以及对应哪个子技能。
2. 我引用的每条命令都在本仓跑得通（不是照抄框架 CLI 的想象命令）。
3. 我没把判据抄进话里 —— 说的是「去哪个工具看」。
4. 我报的是**这棵树**的读数（`rev` / 分支 / 树路径对得上）。
5. 改过 `skills/**` ⇒ 跑 `python -X utf8 tools/check_skills_claims.py --check`：退 `1` 修对不上的那条，
   退 `3` 就在回报里如实写「判不出 N 条」—— `3` 不是绿。

> 铁律的来历见 `NOTES.md`；技能本身的写法见 [技能自检表](references/spec-checklist.md) 与
> `docs/reference/agent-skills-spec.md`。
