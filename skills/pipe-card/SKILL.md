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

> 「域检查按卡树实际改动 vs 权威域」这条**判据**在库里（`framework/src/framework/claim.py`）。本 skill 只说怎么用，不复述判据。
