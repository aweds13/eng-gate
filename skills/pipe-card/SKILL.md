---
name: pipe-card
description: 用 pipe card new 生成一张工作项，用 pipe claim 交一条完成申报。当你要开一张新卡、或为一张卡登记做完了没时用。
---

# pipe-card —— 写卡 / 认领 / 申报

## 什么时候用

- 开一张**新工作项（卡）**：从 `[cards].spec_template` 生成到 `[cards].cards_dir/<id>-<slug>.md`。
- 为一张卡交**完成申报**（`success` / `failed`），带证据。

## 什么时候别用

- 想**跑门**：用 `pipe-gate`。
- 想**集成发布**：申报只是它的输入之一；整条链用 `pipe-land`。
- 任务号 / 成员号**没预登记**就要申报：`claim` 会退 `5`（前置条件缺失）；先把任务与成员登记了再来。

## 前置检查

1. `pipeline.toml` 的 `[cards]` 段齐：`cards_dir` / `spec_template` / `claims_dir` / `backlog` / `authoritative_domains`。
2. 卡模板文件在（`spec_template` 指向的那份）。
3. `--domain` 按**实际改动的文件路径**给，别给自报清单（域检查按卡树实际改动对账）。

## 真命令

```bash
python framework/cli/main.py card new --id <卡号> --title <标题> --domain <路径> <路径>
python framework/cli/main.py claim --task <卡号> --member <成员号> --status success --files <路径> --why <一句> --evidence <指针>
python framework/cli/main.py claim --task <卡号> --member <成员号> --status failed
```

装成命令后：`pipe card new …` 与 `pipe claim …`。

## 怎么读结果

> 每条口径末尾的「复核」都指着**能重跑的那个脚本**——结论别靠人眼，跑它。

- `card new`：退 `0` 生成；退 `4` 卡号已存在 / 域含受保护文件；退 `5` 模板缺失。`--json` 给 `card_id` / `spec_path` / `domain`（复核 `python -X utf8 framework/cli/main.py card new --json`）。
- `claim`：退 `0` 收下；退 `4` 投了 `failed`（**会挡住集成发布**）；退 `5` 任务 / 成员未预登记。`--json` 给 `task` / `member` / `status` / `accepted`（复核 `python -X utf8 framework/cli/main.py claim --json`）。
- ★ **`success` 必须带 `--evidence`**：没证据不叫完成申报（复核 `python -X utf8 framework/cli/main.py claim --json`）。
- ★ 当前实现里 `claim`（以及 `land`）是**薄壳**：签名在、行为未建，调用即抛「未实现」并退 `5`（`PRECONDITION`）。看到退 `5` 且提示未实现，**不是你的用法错**（复核 `python -X utf8 framework/cli/main.py claim --json`）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| `card new` 退 `4` | 卡号已存在（不覆盖） | 换卡号；要改就改现有卡文件 |
| `claim` 退 `4` | 投了 `failed` | 这是显式挡住集成，不是异常；确认是不是真要判失败 |
| `claim` / `land` 退 `5` 说未实现 | 薄壳（本阶段未建行为） | 照薄壳当前口径处理；这不是用法错 |
| `claim` 退 `5` 说未预登记 | 任务 / 成员没登记 | 先登记任务与成员，再申诉 |
| 域检查不通过 | `--domain` 与卡树实际改动不符 | 按**实际改动的文件**给域 |
| ★ 工人在卡里空转，日志里反复同一条命令 | ★ **它的 harness 不许跑长命令**：原话 `Command rejected: … Reason: Background command execution is not supported in pr…`（2026-10-15 卡 245 实测，连试两次都被拒） | ★ **别把它当"工人不行"**：改分工 —— **工人只做秒级能跑完的那部分**（改代码 / `selftest` / 小口径 pytest），**长跑（真机、长服务、分钟级 CLI）在卡里写明"由主控跑"**；工人把**命令 + 预期 + 为什么**交回，主控用后台作业跑完把读数贴回文书 ✓ |
| ★ 卡要求"真机验收"，工人回报"没做" | 多为上一条（长命令被拒），或环境缺失（端口/进程不在） | ★ 卡里预先写清**降级口径**：环境不具备就**如实写"没做" + 证据**（不许假装 ✓），并交回可替代的证据（离线桩 / 类型面 / 源码行号）✓ |

> ★ 写卡硬规矩（2026-10-15 起）：**验收里含"真机、长跑、≥30 秒的命令"，必须在卡的「验收」段写明由谁跑** —— 秒级跑完的归工人，跑不完的归主控 ✓。否则工人会在那一步空转、日志里只剩同一条被拒的命令 ✗。

> 「域检查按卡树实际改动 vs 权威域」这条**判据**在库里（`framework/src/framework/claim.py`）。本 skill 只说怎么用，不复述判据。

## 派活走哪条道（用户 2026-10-16 定）

| 道 | 用来干什么 | 不许用来干什么 |
|---|---|---|
| **CodeBuddy / 备用号**（`wb_dispatch.py --account tongxue3 --model glm-5.3-flash` 等） | ★ **一切实现类卡**（改代码 / 写判据 / 落地前的活） | — |
| **Trae 道 · Kimi K3**（`trae_pool.mjs send --model Kimi-K3`） | ★ **只做「复核 / 对抗性审查」**：证伪既有结论、开工前审规格、落地后审产物 | ★ **不许当实现工人** ✗（用户 2026-10-16 明令：*「除了复核与对抗性审查，其他以后不能开 kimiK3」*） |
| **主控**（我自己） | 长跑（真机、门禁、落地链）、跨域决策、与用户对话 | 不许把工人的域内活抢来自己做（会撞文件 ✗） |

> ★ 派活前先问一句：**这张卡是「实现」还是「复核」？** 实现 ⇒ CodeBuddy ✓；复核 ⇒ 才可以上 Kimi K3 ✓。
