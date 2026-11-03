---
name: pipe-card
description: 开一张工作项（卡规格 + 队列条目）、交完成申报、把卡派给工人。当你要新建/登记一张卡、判断一张卡该不该算做完、或要看工人有没有在干活时用；它给顺序与真命令，域与收口的判据在工具里。
---

# pipe-card —— 写卡 / 派活 / 申报

一张卡 = 一份卡规格 + 一条队列条目 + 工人树里的提交 + 一条申报。
四样东西的名字与字段要能互相对上；对不上时先修名字，别急着往下走。

## 什么时候用

- 要开一张卡：写卡规格、登记队列、建工人树。
- 要把卡派出去，或查「工人动没动」。
- 一张卡干完了，要交 `success` 申报（带证据），或显式判 `failed`。

## 什么时候别用

- 要跑门：用 `pipe-gate`；要落地：用 `pipe-land`（申报只是它的输入之一）。
- 卡规格里的 `files` 还没定就想开干：**先定域**，域是后面一切拦截的依据。
- 想替工人改他树里的文件：一写一读，工作区归他。
- 任务 / 成员还没登记就要申报：先 `register`，否则申报无处可落。

## 前置检查

1. 卡号在本仓没被用过：`docs/workbacklog.toml` 与 `复盘/卡/` 都没有这个号。
2. 卡规格四段齐（问题 / 改法 / 判据 / 证据），且 `files` 是**你真正会碰**的文件。
3. 台账号（`T-AG…`）与卡号分开：`Task:` 只能有一个编号。
4. 树还没建：`git worktree list` 里没有 `.wt/<卡号>`。
5. 派活前读 [派活分工](references/dispatch.md)：谁做实现、谁只做复核、长跑归谁。

## 立卡：只走一个入口

台账（`docs/workbacklog.toml`）只有一处生产写方，别手编、别用临时脚本：

`python -X utf8 tools/wb_card.py add --id E82 --task T-AG587 --title 卡E82示例 --spec 复盘/卡/卡E82-示例.md`

- 它给的是：台账锁跨会话互斥、块级幂等（同号卡打「已在」退 0）、尾部按字节追加、原子替换（带重试）。
- 退 1 = 台账不是纯 CRLF（不写盘）；退 2 = 等不到锁 —— 两种都别手改台账对齐。
- 旧的 gates/diag/_add_card.py 已废：硬编码绝对路径、按全文子串判「已在」（头部注释里出现同形文本就误判 ⇒ 卡凭空丢），且住在 gitignore 里、不入库。
- 依据：卡 E81（提交 87f95ba5）已把这条收成生产代码 `tools/pool/ledger.py`。

## 真命令

```bash
# ① 建树（分支名 card/<卡号>）
git worktree add .wt/<卡号> -b card/<卡号>

# ② 派活（默认 dry-run；--detach 不等它，--execute 才真派）
python -X utf8 tools/wb_dispatch.py --card <卡号> --spec 复盘/卡/卡<卡号>-<短名>.md \
    --cwd .wt/<卡号> --model <短名> --detach --execute
python -X utf8 tools/wb_dispatch.py --card <卡号> --status

# ③ 申报（任务栅栏：先注册，再逐卡交）
python -X utf8 tools/wb_task.py register <预声明.toml>
python -X utf8 tools/wb_task.py claim <任务> <成员> --claim success \
    --evidence "<测试读数 / 门结论 / 原样输出>" --files <a.py,b.py> --why "<干了什么>"
python -X utf8 tools/wb_task.py status <任务>

# ④ 收口后给提交补文书（台账条目 + changelog + 交接 CHECKPOINT）
python -X utf8 tools/wb_stage_card.py --tree .wt/<卡号> --id <台账号> --title "<标题>" \
    --evidence <文件> --text-file gates/diag/_text_<台账号>.md
```

## 怎么读结果

- 卡排不排得出来：`python -X utf8 tools/wb_plan.py plan --concurrency 2`（只认 `status = "pending"`）。
- 队列里这张卡长什么样（`files` / `tree` / `status`）：`python -X utf8 tools/pipeline_view.py --json` 的 `cards` 块。
- 申报收没收：`python -X utf8 tools/wb_task.py status <任务>` 给「谁交了 / 还缺谁 / history」。
- 工人动没动：`python -X utf8 tools/wb_dispatch.py --card <卡号> --status`；日志在 `gates/diag/wb-<卡号>.jsonl`。
- 队列与 git 对不上（落了没翻状态 / 翻了没落）：`python -X utf8 tools/wb_reconcile.py`。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 卡排不出来 | `status` 不是 `pending`，或缺 `spec` / `files` / `depends` | 补齐字段；`depends` 指向的卡没 done 也会挡住 |
| 申报退「域不符」 | `--files` 与卡规格的 `files` 对不上 | 按**实际改动**报；确实要扩域就改卡规格并写明理由 |
| 申报退「任务/成员未登记」 | 直接 `claim` 没先 `register` | 先 `register`；成员号 = 卡号 |
| 工人日志里反复同一条命令 | harness 不许跑长命令（后台执行被拒） | 秒级活归工人，长跑（真机 / 分钟级）归主控，见 references |
| 工人说「没做」 | 上一条，或环境缺件（端口 / 进程不在） | 卡里写清降级口径：如实写「没做」+ 证据，不许假装 ✓ |
| 派活被拒「工作区不干净」 | 派活器的前置检查看的是**当前工作区** | 先提交；别人的改动用 `git stash push -- 路径` 挪开、事后精确复原，**绝不 `git reset --hard`**；别顺手一起提交 |
| 树建不出来 | 同名分支 / 目录已存在 | `git worktree list` 先看；别 `-f` 硬建 |

## 派活走哪条道

| 道 | 用来干什么 | 不许用来干什么 |
|---|---|---|
| CodeBuddy（本仓默认池） | 一切**实现类**卡：改代码 / 写判据 / 落地前的活 | — |
| 复核道（`--model kimi-k3-1`） | **只做复核 / 对抗性审查**：证伪结论、审规格、审产物 | 不许当实现工人 |
| 主控 | 长跑（真机 / 全量门禁 / 落地链）、跨域决策、与用户对话 | 不许抢工人域内的活（会撞文件） |

派活前先问一句：**这张卡是实现还是复核？** 实现走默认池，复核才上复核道。
★ **模型名不许凭记忆写**：真源 = `tools/pool/model-registry.toml` 里该池的条目 + 仓外开关
`infra/pool/model-switches.toml`（只做加法）。写错一律被 `wb_dispatch.py` 拒单并**原样列出允许集**
（2026-10-28 实测：`deepseek-v4.1-flash` 默认 / `glm-5.3-flash` / `glm-5.3` / `kimi-k3-1` / `glm-5.2`）；
开关被撤掉时按那一屏列出的允许集挑复核档，别硬写今天这份。

## 自查

1. 卡规格、队列条目、树、分支四处的**卡号**逐字一致。
2. `files` = 我真正会碰的文件；多一个少一个都会在后面被点出来。
3. 申报里的 `--evidence` 是**能重跑的东西**（命令 + 读数），不是「已完成」四个字。
4. 收工前 `git status --porcelain -uno` 在我这棵树里是 0 行。

> 域怎么判、申报怎么收口、封存怎么算：判据在 `tools/pool/task.py` 与 `tools/pool/landing.py`，本技能只讲顺序。
