# 门禁输出读法（细则）

> 本文件是 `pipe-gate/SKILL.md` 的按需参考。**判据不在这里** —— 哪道门算过、三值怎么折、
> 复用怎么算，全在 `scripts/run_gates.py` 与门表里。这里只讲「输出长什么样、怎么读不出错」。

## 1. `gates/last.json` 的骨架

顶层键（`python -X utf8 -c "import json;print(sorted(json.load(open('gates/last.json',encoding='utf-8'))))"` 现读，别抄）：

| 键 | 读它干什么 |
|---|---|
| `rev` / `parent` | 这趟门禁封的是哪笔提交；落地时要求 `rev == HEAD^` |
| `tree` / `tree_scope` | 封存指纹（缺省口径：去掉 `gates/**` 的提交树） |
| `branch` / `at` | 哪条分支、什么时候跑的 —— 和你在的树对不上的读数不能直接用 |
| `ok` | 总判决：**只有它是结论** |
| `gates[]` | 每道门：`name` / `exit_code` / `seconds` / `summary` |
| `not_run` | 没跑的道与原因（**不是**通过） |
| `reused` | 复用记录 —— 在**顶层字典**里，不在每道门里（`复盘/口径坑.md` 第 1 条） |
| `dirty` / `untracked` / `trailer` | 跑门时的现场与提交信息骨架 |

## 2. 四种「不是绿」

| 看到 | 意思 | 怎么办 |
|---|---|---|
| `not_run` 里有这道门 | 运行时缺件，根本没跑 | 补 node / 浏览器 / 服务再跑；回报里如实写「未跑」 |
| `exit_code` 非 0 | 真红 | 看 `gates/logs/<name>.log` 尾部 |
| 门在 `reused` 里 | 输入没变、采信上一轮 | 自己动过它或它的输入 ⇒ `--no-reuse` 真跑 |
| `exit_code` 是 `0`，但 summary 写着「没判完 / 判不出 N」 | 有判据看不见的条目（占位符、`not verified`）—— 门表里 `docs` / `skills_claims` 用 `--mode report`，这类不红 | 记「判不出」，**不记绿**；要它真红/真拦用 `--mode block`（那时退 `3`） |

`--fast` 的输出**不进** `last.json`（它明确不落盘）。看到「全过」只说明内循环那几类没犯。

## 3. 档位怎么选

| 档位 | 覆盖 | 用在哪 |
|---|---|---|
| `--fast` | 十几秒那几类（静态 / 台账 / 令牌层） | 改一小块后自查；**不许当提交闸** |
| `--quick` | 全量但跳过真机层 | 提交前赶时间；真机风险要自己点名 |
| 全量 | 含真机与浏览器 | 提交 / 收口 / 改了界面或交互 |
| `--affected <路径>` | 按「被这些路径影响」选集 | 只做自查；路径碰 `scripts/` `tools/` `gates/` 会强制回全量 |

## 4. 日志与证据落点

- 每道门的全量输出：`gates/logs/<门名>.log`（不进仓库）。
- 门禁自己的临时件：`gates/diag/`（gitignored；**卡树里没有**，别相对路径指给工人）。
- 复用的输入指纹：`gates/reuse.json` —— 它和 `last.json` 要一起看，单独一个说不清。

## 5. 逐门超时：有，别自己再套一层

门禁**每道门都有硬超时**（`scripts/run_gates.py` 的 `DEFAULT_DOOR_TIMEOUT = 1800.0` 秒；
`TF_GATE_DOOR_TIMEOUT` 可覆盖，`0` = 关掉这条路）：

- 到点 → 掐掉**整棵进程树** → 这道门记 `exit_code = 124` + `timeout=True`、summary 写「超时 N 秒被掐」
  并给出门名 / pid / 掐了几个子进程 → **判红**（124 ≠ 0），不许当「跳过 / 没跑」糊过去。
- 另一套数别混：`DEFAULT_DOOR_BUDGET = 600.0` 是**慢门软预算**，只告警并进 `gates/last.json` 的
  `slow_doors`（本次现读 `[]`），它**不掐门**。
- 所以读法变了：卡住先看 `gates/last.json` 里那道门是不是 `124` / `timeout=True`，再看日志尾；
  清洗残留按 PID 收，**别按进程名杀**（会杀掉用户正在用的浏览器）。
