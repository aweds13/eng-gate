---
name: pipe-new
description: 从空目录或新目录起一条本仓工作链（定层 → 目录 → 队列 → 卡规格 → 工作树 → 首笔落地），并分清「框架骨架」与「本仓工作链」两条路。当你要新开一个项目目录、把一批活从零登记进队列、或判断新项目该走 pipe-init 还是只登记进 wb_* 链时用；顺序与前置检查在这里，判据与落地参数在 tools/wb_plan.py 与 tools/pool/landing.py。
---

# pipe-new —— 从零起一条工作链

一句话：**先定层，再定路**。目录、队列、卡、树、首笔落地，五样按顺序来；跳一步就得回头补，
而越靠后的步骤越贵（首笔落地要跑全量门禁）。

## 0. 先问再写（硬规矩）

在写任何规格、文档层、骨架或代码之前，先用 `grill-me` 与用户一问一答把决策树走完，并拿到用户明确的「确认」。**未确认不得动笔**；确认结论写进卡里（哪一问、答了什么）。

理由：AI 自己补出来的规格与文档大多是编的，事后无法区分「事实」与「填补」。


## 什么时候用

- 一个空目录 / 新目录要接进本仓的工作链（队列 + 卡 + 树 + 落地）。
- 要判断这个新项目该「铺框架骨架」还是「只登记进本仓队列」。
- 一批活从没登记过，要把队列条目、卡规格、树一次补齐。

## 什么时候别用

- 只开一张卡：用 `pipe-card`（它管卡规格、派活、申报）。
- 接管一个**已经存在**的项目目录：用 `pipe-takeover`。
- 要一套自带 `pipeline.toml`、门表、钉子的独立骨架：用 `pipe-init`（框架层）。
- 目标在**仓外另一个 git 仓**：本仓工具链的根绑在 `tools/` 所在位置，没有「指向别仓跑」的开关；
  替别仓落地不在本技能范围内（出口见 `skills/pipe-new/references/first-landing.md`）。

## 前置检查

1. 先定资产层：这活是产品（timeflow）、工作链本身、还是机器（infra）——
   见 `skills/softeng-manage/references/asset-layers.md`。
2. 目标目录在**本仓内**：`git rev-parse --show-toplevel` 要指向本仓根。仓外目录只登记项目索引，
   不在这里落地。
3. 目标目录有首提交：链条以 git 为真源；空目录先 `git init` + 一次提交。
4. 卡号没被用过：`docs/workbacklog.toml` 与 `复盘/卡/` 都没有这个号。
5. 工作区干净：`git status --porcelain` 为空（落地的第一步会检查主树）。

## 真命令

```bash
# ① 目录与首提交（本仓内的新项目目录；已有目录跳过这一步）
mkdir -p <目录>
echo "# <项目名>" > <目录>/README.md
git add <目录> && git commit -m "chore(<scope>): <项目名> 起目录"

# ② 队列条目：往 docs/workbacklog.toml 的 [[cards]] 里加一条
#    id / task / title / tree / spec / files / depends / risk / status 九个字段
python -X utf8 tools/wb_plan.py check

# ③ 卡规格：复盘/卡/卡<号>-<短名>.md，四段（问题 / 改法 / 判据 / 证据）
git add 复盘/卡/卡<号>-<短名>.md

# ④ 建树（默认只打印；--execute 才真建；基点是队列的 [base].reviewed）
python -X utf8 tools/wb_plan.py worktrees
python -X utf8 tools/wb_plan.py worktrees --execute

# ⑤ 派活（默认 dry-run；--detach 立刻返回）
python -X utf8 tools/wb_dispatch.py --card <号> --spec 复盘/卡/卡<号>-<短名>.md \
    --cwd .wt/<号> --model <短名> --detach --execute

# ⑥ 首笔落地（八步链；参数面与断点见 pipe-land）
python -X utf8 tools/wb_land.py --card <号> --tree .wt/<号> --task <T-AG…> \
    --title "<标题>" --evidence "<证据>" --allow <文件…>
```

首笔落地的完整时间线、三个最常见的失败、仓外项目的出口：
见 `skills/pipe-new/references/first-landing.md`。

## 怎么读结果

- 队列条目立没立住：`python -X utf8 tools/wb_plan.py check` 最后一行应是
  「backlog 校验通过：N 张卡，无冲突」。
- 树建没建对：`python -X utf8 tools/wb_plan.py worktrees` 打印的
  `git worktree add -b card/<号> .wt/<号> <基点>` 与你手上的分支、基点一致。
- 首笔落成没落成：`python -X utf8 tools/wb_verify.py --tree .` 五块（提交骨架 / 门禁 / 封存 /
  台账 / 审计）逐块对，任一 FAIL 就先修那块。
- 现场六块（队列 / 门禁 / 判决 / 租约 / 栅栏 / 树）：`python -X utf8 tools/pipeline_view.py --json`。
- 卡号与台账号对不上：`python -X utf8 tools/wb_reconcile.py` 的三份清单。

## 起链六步

| 步 | 做什么 | 验收 |
|---|---|---|
| 1 | 定层（产品 / 工作链 / 机器） | 能一句话说清改的是哪一层，见 `skills/softeng-manage/references/asset-layers.md` |
| 2 | 目录 + 首提交 | `git log --oneline -1` 有新提交，`git status --porcelain` 干净 |
| 3 | 队列条目 | `python -X utf8 tools/wb_plan.py check` 通过 |
| 4 | 卡规格 | 四段齐；`git ls-files --error-unmatch 复盘/卡/卡<号>-<短名>.md` 认得它 |
| 5 | 树 | `git worktree list` 里有 `.wt/<号>`，分支是 `card/<号>` |
| 6 | 首笔落地 | `python -X utf8 tools/wb_verify.py --tree .` 五块无 FAIL |

★ 第 2 步之后先落入口文档：`AGENTS.md` 照 `skills/pipe-takeover/references/agents-md.md` 写，命令必须是真跑过的（新仓没有历史，写 `TODO(verify)` 也要标出来）。

★ 第 4 步的 `git add` 不能省：落地脚本在全量门禁之前先跑一条「卡规格都要在索引里」的钉子，
不满足就停手（省下的正是几分钟全量门禁）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| `wb_plan check` 报同一文件两个写者 | 两张待派卡的 `files` 相交 | 给其中一张加 `depends`，或把 `files` 拆小 |
| 建树基点很旧 | 队列的 `[base].reviewed` 停在旧提交 | 把它更新到主树当前 HEAD，再 `worktrees` |
| `wb_land` 退 4（全量门禁之前） | 卡规格没进索引 | `git add 复盘/卡/卡<号>-<短名>.md` 后重跑 |
| `wb_land` 退 5（快照之前） | 主树有跟踪改动，且不在白名单 | 把改动挪进卡树；主干只接受合并 |
| `wb_land` 退 3 | 卡树 HEAD 不是主树 HEAD 的祖先 | 按脚本提示手工摆树，别让它 `checkout` 抹掉改动 |
| 想给仓外的新仓落地 | 工具链根绑定在本仓 `tools/` | 只在本仓登记卡与项目索引；仓外落地另开一张卡 |

## 自查

1. 我能一句话说清这活属于哪一层，以及为什么。
2. 目录、队列、卡、树、落地五样都有机器产物，不是我口头说「好了」。
3. 我没有把框架层（`pipeline.toml` / `gates.d/`）和工作链（`wb_*`）混成一条。
4. 目标在仓外时我止步了，没有假装本仓工具能替别仓落地。

> 判据在 `tools/wb_plan.py`（队列与冲突域）、`tools/pool/landing.py`（落地八步）、
> `tools/pool/projects.py`（项目索引三条硬判据）；本技能只讲顺序与前置检查。
