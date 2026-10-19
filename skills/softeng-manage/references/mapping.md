# 动作映射（自然语言 → 动作 → 本仓真命令）

> 这张表回答一件事：**你心里那句话，落到本仓哪个动作、敲哪条命令。**
> 逐条命令的存在性由下面的「核对」手动复查；改了表就要顺手重跑一次，别让表烂掉。

## A. 先定动作，再谈命令

| 你说的话（或心里的意图） | 落到哪个动作 | 不可混的地方 |
|---|---|---|
| 「开卡 / 建卡 / 立个项」 | **开卡** | 产出卡规格 + 队列条目；不是写一段评论 |
| 「派 / 给工人 / 外包」 | **派活** | 起 `wb_dispatch`（或号池）；不是自己动手写代码 |
| 「过门 / 门禁 / 能不能合」 | **跑门** | 跑 `run_gates.py` 并读 `last.json`；不是 `git status` 绿就算过 |
| 「落一下 / 合进主树 / 收口」 | **落地** | 跑 `wb_land.py`；`git commit` 或 `git merge` **都不等于**落地 |
| 「对账 / 查老账 / 这卡到底落没落」 | **对账** | 跑 `wb_reconcile.py`；不靠翻聊天记录 |
| 「看现场 / 今天干嘛 / 谁在飞」 | **巡检** | `wb_daily.py` 或 `pipeline_view.py`；不靠猜 |
| 「起服务 / 开面板 / 打不开」 | **服务** | `stack.py` + `verify_panel_routes.py`；不是重启 DSH |
| 「提交」 | **提交（工人树内）** | `git commit`；提交 ≠ 落地，落地才进主树 |
| 「注册技能 / 技能不生效」 | **注册** | `dsh_skills_link.py`（`--check` 核对） |
| 「这棵树干净吗」 | **自查** | 见 §C，先自己看 |

## B. 动作 → 真命令 → 产物

| 动作 | 真命令（本仓） | 产物 |
|---|---|---|
| 开卡 | 写卡规格 + 追加 `docs/workbacklog.toml` 条目；`python -X utf8 tools/wb_plan.py plan` 核它排得出 | 卡规格文件、队列条目 |
| 派活 | `python -X utf8 tools/wb_dispatch.py --card <卡> --spec <规格> --cwd .wt/<卡> --detach --execute` | `gates/diag/wb-<卡>.jsonl`、`brief-<卡>.md` |
| 看工人 | `python -X utf8 tools/wb_dispatch.py --card <卡> --status` | 终端读数 |
| 申报 | `python -X utf8 tools/wb_task.py claim <任务> <成员> --claim success --evidence … --files …` | 栅栏状态 |
| 跑门 | `python -X utf8 scripts/run_gates.py` | `gates/last.json`、`gates/logs/` |
| 落地 | `python -X utf8 tools/wb_land.py --card <卡> --tree .wt/<卡> --task <T> --title <…> --allow … --evidence …` | 主树提交 + 封存 |
| 核实一笔 | `python -X utf8 tools/wb_verify.py --tree .` | 五块读数 |
| 巡检 | `python -X utf8 tools/wb_daily.py` | 今日一页 |
| 六块读数 | `python -X utf8 tools/pipeline_view.py --json` | 一份 JSON |
| 对账 | `python -X utf8 tools/wb_reconcile.py` | 三份清单 |
| 服务起停 | `python -X utf8 tools/stack.py start <name>` | `gates/diag/stack-actions.log` |
| 面板自检 | `python -X utf8 tools/verify_panel_routes.py <port>` | 终端 ✓/✗ |
| 技能校验 | `npx -y skills-ref@latest validate ./skills/<名>` | `Valid skill` |
| 技能注册 | `python -X utf8 tools/dsh_skills_link.py`（`--check` 只核不写） | junction（零副本） |

## C. 状态自查（先自己看，别问人）

```bash
git branch --show-current          # 我在哪条分支（工人应在 card/<卡>）
git worktree list                  # 主树 + 各工人树
git status --porcelain -uno        # 有没有没进提交的改动
git log --oneline -5               # 最近落了什么
ls gates/diag/wb-<卡>*              # 工人的日志在不在
```

「当前在哪个树、哪条分支、有没有未提交改动」是**自查项**，不是提问项。

## D. 三件事各归哪一层

| 东西 | 归哪 | 判据 |
|---|---|---|
| **算不算过**（阈值、不变量、字段） | 门 / 库（`scripts/`、`tools/`、`tests/`） | 删掉 `skills/` 后仍能判定 |
| **怎么用才不出错**（顺序、前置检查、常见错） | 技能（`SKILL.md`） | 只写操作知识，不写阈值 |
| **换 harness 要改的** | `skills/GLUE-harness.md`（G1–G6） | `SKILL.md` 里不出现某个 harness 特有路径作为前提 |

## E. 与 `pipe` CLI 的关系

框架自带一条 `python -X utf8 framework/cli/main.py <命令>` 的 CLI（`init` / `gate` / `card` /
`claim` / `land` / `doctor` / `ledger` / `trace`）。本仓**根目录没有 `pipeline.toml`**，
所以 `gate` / `land` 这两条在本仓主路径上用不了 —— 顺序与前置检查照技能，命令走上表 `wb_*`。
唯一仍在用 CLI 的是 `init`（它自己带模板，不需要根级配置）。
