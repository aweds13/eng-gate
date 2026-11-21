# pipe-new —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放「这个仓是什么样」**：队列文件叫什么、卡规格落哪、树前缀与分支名、建树基点、
> 工具入口路径、本仓实测读数、历史证据挂在哪。
> `SKILL.md` 里的动作顺序与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现），分支 `line/impl-v1`。

## 本仓是哪种形态

- **单数据根**：队列、台账、门禁产物、卡规格都在**同一个仓**（`program/engineering`）。
  工具根与数据根由 `tools/pipe_root.py` 分：工具根 = `tools/` 上一级（或 `PIPE_HOME`），
  数据根优先级 = `PIPE_DATA` > 当前目录像数据根（有 `docs/workbacklog.toml` / `docs/traceability.toml` / `gates/diag` 之一）
  > 回落工具根。诊断：`python -X utf8 tools/pipe_root.py --check` 打印两个根。
- **没有分片队列**：`docs/backlog/` 在本仓**不存在**，队列是总表 `docs/workbacklog.toml`。
  `tools/wb_plan.py` 的口径是「先分片、后总表」—— 有 `docs/backlog/<分区>.toml` 才以分片为准。
- **不是独立骨架**：本仓根**没有** `pipeline.toml`（`ls pipeline.toml` ⇒ No such file）。框架 CLI 的
  `pipe gate` 在本仓主路径上跑不起来，本仓走 `tools/wb_*.py` 这一套。要一套自己的 `pipeline.toml`
  是 `pipe-init` 那条路。

## 入口路径（SKILL.md 里的 `<…入口>` 占位在本仓是谁）

| SKILL.md 的占位 | 本仓真命令 |
|---|---|
| `<队列校验入口>` | `python -X utf8 tools/wb_plan.py check` |
| `<建树入口>` | `python -X utf8 tools/wb_plan.py worktrees`（`--execute` 才真建） |
| `<派活入口>` | `python -X utf8 tools/wb_dispatch.py` |
| `<落地入口>` | `python -X utf8 tools/wb_land.py` |
| 核实五块 / 现场六块 | `python -X utf8 tools/wb_verify.py --tree .` / `python -X utf8 tools/pipeline_view.py --json` |

## 队列与卡规格的约定

- 队列：`docs/workbacklog.toml` 的 `[[cards]]`，字段九个 —— `id` / `task` / `title` / `tree` / `spec` /
  `files` / `depends` / `risk` / `status`。
- 卡规格：`复盘/卡/卡<号>-<短名>.md`，四段（问题 / 改法 / 判据 / 证据）；**必须进 git 索引**
  （`git add` + `git ls-files --error-unmatch`），落地的第一道钉子只认索引。
- 树上前缀：建树落在 `.wt/<号>`，分支 `card/<号>`；`worktrees` 打印的正是
  `git worktree add -b card/<号> .wt/<号> <基点>`。
- 基点：默认取队列里登记的基点（`[base].reviewed`），也可 `--base <rev>` 指定。
- 队列工具的 `--root` 可以服务别的树：`python -X utf8 tools/wb_plan.py --root <树> check`
  （`--root` 在 `tools/wb_plan.py` 的 argparse 里注册，走 `tools/_repo.py` 的解析链）。
  但这只换**读哪棵树**，不改变「一次只为一份数据根落地」。

## 本仓实测读数（数字会漂，口径不能漂）

- `python -X utf8 tools/wb_plan.py check`（2026-11-21）⇒ rc=0，末两行
  `[OK ] backlog 校验通过：425 张卡，无冲突（基点 38522420）` /
  `[队列] 待派 11 张 / 其它 414 张（★ 只有待派的参与冲突判定与排批）`。
  **卡数与基点每次都在变**：只写「末行应是 backlog 校验通过」，别把 425 当常量。
- `python -X utf8 tools/wb_plan.py stats`（同上时刻）⇒ `[统计] 队列共 425 张：待派 11 / 其它（done/failed）414`，
  并发上限 2 ⇒ 6 批。
- `python -X utf8 tools/wb_plan.py worktrees`（同上时刻）⇒ 干跑，尾行
  `[dry ] 默认不执行；真要建树加 --execute（基点 38522420）`。

## 仓外的新仓：本仓的三条出口

替**仓外另一个仓**落地不能靠这套命令，只能做三件事，都要另开一张卡：

1. 把对方登记进**项目索引**：`tools/pool/projects.py` 从祖先逐级找 `infra/pool/projects.toml`，
   找不到就抛错、**不猜路径**，`TF_PROJECTS_TOML` 可覆盖。★ 本机解析到的是
   `D:/repo\infra\pool\projects.toml` —— 它**不在本仓内**，仓内没有这份文件。三条硬判据
   （`root` 存在 / 不重根 / `tree_prefixes` 非空）在库里，不在技能里。
2. 把对方的产物映射成本仓的卡：顺序见 [映射表](../../pipe-takeover/references/mapping.md)，卡仍落本仓队列。
3. 真要在对方仓交首笔：在**对方仓**里按 `pipe-init` 铺最小骨架，用对方自己的门；不要指望本仓的落地链。

## 框架层那条路（对照用，不是本仓主路径）

- `pipe-init` 铺出来的骨架文件数：`framework/templates/minimal` 受控文件恰 **14** 个
  （2026-11-08 `git ls-files framework/templates/minimal | wc -l` ⇒ 14）。
- 骨架的门用 `python -X utf8 framework/cli/main.py --config pipeline.toml gate` —— `--config` 是
  **全局**参数，必须写在子命令**前**；写成 `main.py gate --config …` 实测 rc=2，
  `error: unrecognized arguments: --config pipeline.toml`。
- 门禁定义层在 `gates/defs/`（`lang_python.py` / `contract.py` / `product_timeflow.py` /
  `domains.py`），`scripts/run_gates.py` 只是装配与分档（`GATE_PROFILES` / `FAST`）——
  改门表**不用**改 `scripts/run_gates.py` 的元组。

## 入口文档与历史证据

- 入口文档写法：[agents-md](../../pipe-takeover/references/agents-md.md)（`AGENTS.md` 的分节与「命令必须真跑过」口径）。
- 落地链三条早退的码位与真因（退 5 主干保护在快照之前 / 退 4 卡规格索引钉子在**全量门禁之前** /
  退 3 卡树 HEAD 非祖先）：见 [首笔落地](first-landing.md)。
- 快照 ref 形状：`refs/snapshots/<段或卡>-<%Y%m%d-%H%M%S>`（`tools/pool/snapshot.py` 现拼）；
  退 5 那一次**还没打快照**，所以主树留脏改动就没有回滚点。
