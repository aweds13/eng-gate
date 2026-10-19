---
name: pipe-land
description: 把一张卡落成一笔提交（迁移卡树 → 文书 → 全量门禁 → 封存 → 白名单提交 → 审计 → 合流 → 复核）。当你要收口一张卡、重跑被中断的落地、或判断「这一笔算不算落成」时用；落地参数与封存口径在工具里。
---

# pipe-land —— 集成与发布

落地不是 `git commit`、也不是 `git merge`：它是 `tools/wb_land.py` 那条八步链，
**每一步都留读数**，链红了就停，绝不带着红门禁提交。

## 什么时候用

- 一张卡的结果齐了（提交在卡树里、申报已交），要落进主树。
- 落地跑到一半被打断，要从断点续（`--commit-only` / `--no-reset`）。
- 已经落了，要判断这一笔算不算数（封存 / 队列 / 台账是否一致）。

## 什么时候别用

- 还没交申报：入口条件不满足会被挡（不是异常，是设计上的挡）。
- 只想跑门：用 `pipe-gate`（落地链内部会自己跑，别外面再压一趟）。
- 想用普通 `git commit` / `git merge` 交差：那**不是**落地；封存、审计、队列翻转都会缺。
- 工人树里还脏着（`git status --porcelain -uno` 非 0）：先让工人提交。

## 前置检查

1. 申报齐：`python -X utf8 tools/wb_task.py status <任务>` 显示该卡已交。
2. 卡树干净：在卡树里 `git status --porcelain -uno` 为 0 行。
3. 主树干净：别人的未提交改动先收起（落地会做 `add` / `commit`，会被卷进去）。
4. 参数齐：`--card` 与 `--batch` **恰好给一个**；`--tree` / `--task` / `--title` / `--evidence` / `--allow` 必填。
5. 参数细则与文书三段见 [落地参数](references/land-steps.md)。

## 真命令

```bash
# 正式落地（默认跑全量门禁 + 复核落盘）
python -X utf8 tools/wb_land.py --card <卡号> --tree .wt/<卡号> --task <台账号> \
    --title "<一句话>" --type feat --scope <域> \
    --allow <文件>... --evidence <指针>... --port-base <端口段>

# 门禁已绿、封存没变：⑥ 起接着走（跳过 ①②③④⑤）
python -X utf8 tools/wb_land.py ... --commit-only

# 落地后一屏核实
python -X utf8 tools/wb_verify.py --tree . --expect-parent <期望父提交>
```

## 怎么读结果

- 这一笔算不算数（五块一屏：提交骨架 / 门禁 / 封存 / 台账 / 审计）：`python -X utf8 tools/wb_verify.py --tree .`。
- 队列翻没翻（落了却仍 `pending`、或翻了却没落）：`python -X utf8 tools/wb_reconcile.py`。
- 复核产物在不在：`gates/review/<台账号>.json`，可用 `python -X utf8 tools/wb_review.py --rev <新提交> --json` 重出一份。
- 卡与门的当前形态：`python -X utf8 tools/pipeline_view.py --json`（`cards` / `gates` 两块）。
- 每一步的开关与退出码：`python -X utf8 tools/wb_land.py --help`（`--commit-only` / `--no-reset` / `--affected` 都有说明）。

## 常见错与处置

| 现象 | 真因 | 处置 |
|---|---|---|
| 被挡在入口 | 申报不齐 / 卡树脏 / 参数互斥 | 先补申报；脏树先提交；`--card` 与 `--batch` 只给一个 |
| 门禁红 | 链④真跑红了 | 修红；**不许** `--no-gate` 绕过（它会在 trailer 里如实写「没跑门禁」） |
| 封存对不上 | `gates/last.json` 的 `rev != HEAD^` | 说明封的不是这一笔；重新落地，别手改 `last.json` |
| 重跑报「重复合成」 | 上一趟把 changelog / 台账 / 交接合成过一遍 | 默认⓪会回退派生物；若关了 `--no-reset` 才会撞，重跑别再关 |
| 落了但队列还是 `pending` | 状态没翻 | `--allow` 里要含队列文件；已落未翻用 `python -X utf8 tools/wb_reconcile.py --fix` 前先看清楚 |
| 增量门禁被当全量 | 给了 `--affected` 却按全量汇报 | trailer 会写「非全量」；别把它当全量读数 |
| 复核没产物 | `--no-review` 用了，或复核跑挂 | 默认别关；挂了先看 `gates/review/` 与日志 |

## 复盘缺口（队列状态收口）

- （缺口 PO13）队列状态要收口：落地即翻状态（同一笔里做完），否则面板永远显示「落了没翻」—— 落地时 `--allow` 必须含队列文件；落地后用 `python -X utf8 tools/wb_reconcile.py` 核 stale，落了仍 `pending` 就是没翻。证据：`复盘/卡/卡204-落地即翻状态.md`、`复盘/并行与攒批模型.md`、`复盘/交接.d/T-G310.md`

## 落地链（八步）

| 步 | 干什么 | 失败就停在哪 |
|---|---|---|
| ⓪ | 回退派生物（幂等重跑；`--no-reset` 可关） | 回退不干净 ⇒ 后面必撞「重复合成」 |
| ① | 卡树迁到主树 HEAD | 冲突 ⇒ 先解，别 `checkout` 硬盖 |
| ② | 文档件（gaps / changelog / checkpoint） | 缺 `=== gaps ===` 段 ⇒ 停 |
| ③ | `sync_counts` | 台账分布漂 ⇒ 停 |
| ④ | 门禁锁 + 全量门禁 | 红 ⇒ 停（链内自己跑，别外面再压） |
| ⑤ | `seal`（写 `gates/last.json` 的 tree） | 封存指纹与提交树对不上 ⇒ 停 |
| ⑥ | 白名单 → `add` → `commit` | `--allow` 少了文件 ⇒ 那文件没进这一笔 |
| ⑦ | audit → 释放锁 → `ff` 合流 | 锁没释放会占全局并发名额 |
| ⑧ | 复核落盘 `gates/review/<task>.json` | 异步、不挡提交 |

## 自查

1. `git status --porcelain -uno` 主树 0 行（工人的活都进了这一笔）。
2. `python -X utf8 tools/wb_verify.py --tree .` 五块里没有 FAIL。
3. `docs/workbacklog.toml` 里这张卡是 `done`，且 `python -X utf8 tools/wb_reconcile.py` 无 stale。
4. 回报里写清「跑的是全量还是增量」—— 增量那次 trailer 有「非全量」字样。

> 八步的定义、`--allow` 的白名单语义、封存范围（去掉 `gates/**` 的提交树）：判据在 `tools/pool/landing.py`。
