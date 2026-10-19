---
name: pipe-gate
description: 判断「现在这棵树过不过门」，并读懂门禁结果（每道门的退出码 / 未跑 / 复用）。当你要跑门禁、只看某几道门、确认某道门红没红、或提交前要一份全量结论时用；它给你命令档位与读法，判据在门表与工具里。
---

# pipe-gate —— 跑门禁并读懂结果

跑门用 `scripts/run_gates.py`，读结论看 `gates/last.json` 与 `gates/logs/`。
本仓门数是**现算**的（门表只有一处真源），任何文档都不许写死数字。

## 什么时候用

- 改完一小块，自查这棵树还绿不绿（`--fast`，十几秒）。
- 提交 / 收口前要一份全量结论（`--quick` 次之；`wb_land` 内部跑全量）。
- 某道门红了，要知道「哪道门、什么退出码、日志在哪」。

## 什么时候别用

- 要验证**门本身还活着**（判据没退化成注释）：那是金丝雀自检，不是跑门。
- 想把红改成绿：先修代码或修门；**不许**放宽判据、加豁免、手改 `gates/last.json`。
- 只想看「今天该做什么 / 谁在飞」：用 `pipe-workbench`。
- 已经有一趟门禁在跑：**同一时间只跑一趟**（重活并发 = 假红的头号来源）。

## 前置检查

1. 在**要判的那棵树**里跑 —— 每棵 worktree 有各自的 `gates/`：`pwd` + `git rev-parse --show-toplevel`。
2. 工作区状态先看清：`git status --porcelain -uno`（有别人的未提交改动就先停手）。
3. 内存 / 端口够不够：真机层要起服务与浏览器；`--fast` 只跑轻门，不受影响。
4. 读法细则（每行字段、未跑、复用、退出码）见 [输出读法](references/output.md)。

## 真命令

```bash
python -X utf8 scripts/run_gates.py --fast            # 内循环：十几秒那几道（不落盘）
python -X utf8 scripts/run_gates.py --quick           # 跳过真机层
python -X utf8 scripts/run_gates.py                   # 全量（提交前用这一档）
python -X utf8 scripts/run_gates.py --no-reuse        # 不信复用记录，全部重跑
python -X utf8 scripts/run_gates.py --affected <路径>  # 只跑受影响的门（自查，不是提交闸）
python -X utf8 scripts/run_gates.py --seal            # 只更新 last.json 的 tree 字段，不跑门
# 每道门的全量输出落 gates/logs/<门名>.log（不进仓库）
```

## 怎么读结果

- 一屏核对五块（提交骨架 / 门禁 / 封存 / 台账 / 审计，且报出「not_run N 道 · 复用 N 道」）：`python -X utf8 tools/wb_verify.py --tree .`。
- 每道门一行（名字 / `exit_code` / 秒数）：`python -X utf8 tools/pipeline_view.py --json` 的 `gates.items`。
- 自己动过的门（或它的输入）要 `--no-reuse` 真跑；复跑后用 `python -X utf8 tools/wb_verify.py --tree .` 看「复用 N 道」有没有降下来。
- 红门的日志尾在 `gates/logs/<门名>.log`；跨树汇总、缺源说明用 `python -X utf8 tools/pipeline_view.py --json`（缺块给 `null` + note，不洗成空）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| `--fast` 全绿就改了提交 | `--fast` **不落盘**、只覆盖「改一行就能犯」那几类 | 提交前跑 `--quick` 或全量；`--fast` 不是提交闸 |
| 有门 `not_run` 却当通过 | 运行状态 ≠ 判决 | 补依赖再跑；在回报里如实写「未跑」 |
| 门全绿但结论是上一棵树的 | 在别的 worktree 里读到了自己的 `gates/last.json` | 用 `rev` / 树路径对齐；`wb_verify` 会报 `rev` 与父提交关系 |
| 自己改过的门显示复用 | 增量执行读了缓存 | `--no-reuse` 真跑；别拿复用当验证 |
| 整趟门禁卡住几十分钟 | 某道门卡死，门禁本身**没有逐门超时** | 自己套 `timeout 1800`；按 PID 人工收，别杀用户的浏览器 |
| 两趟门禁同时跑 | 重活并发 | 串行；两个池也别同时满载 |

## 自查

按顺序四条，任一条不成立就**别报「绿了」**：

1. 我跑的是**这棵树**：`git rev-parse --show-toplevel` 与 `pwd` 同一棵。
2. 我报的那一档是**落盘档**（全量 / `--quick`），不是 `--fast`。
3. `gates/last.json` 的 `ok` 为真，且 `rev` 是本笔的父提交（封存口径见 `pipe-land`）。
4. 每道 `not_run` 都在回报里点了名，没有混进「通过」里。

> 判据（哪道门算过、三值与空集、复用规则）在 `scripts/run_gates.py` 与门表里，本技能只讲怎么跑、怎么读。
