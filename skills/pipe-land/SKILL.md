---
name: pipe-land
description: 把一张卡落成一笔提交（迁移卡树 → 文书 → 按域门禁 → 封存 → 白名单提交 → 审计 → 合流 → 复核）。当你要收口一张卡、重跑被中断的落地、或判断「这一笔算不算落成」时用；落地参数与封存口径在工具里。
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
3. 卡上的活留在**工作区**，不要先在卡树里 commit；要暂存就 `git add -N`
   （落地链 ① 会 `git checkout` 主树 HEAD —— 已提交、主树没有的提交会被挡下退 3；
   这一条优先于上一条：卡树里**允许**有工作区改动，**不许**有主树没有的提交）。
4. 主树干净：别人的未提交改动先收起（落地会做 `add` / `commit`，会被卷进去）。
5. 卡归谁：卡若归别的对话窗口，会退 2 并打印持有者（卡 A324）—— 确要接手就加 `--take-over`，别反复重试。
6. 参数齐：`--card` 与 `--batch` **恰好给一个**；`--tree` / `--task` / `--title` / `--evidence` / `--allow` 必填。
7. 参数细则与文书三段见 [落地参数](references/land-steps.md)；
   **走 `--commit-only` 先看那份的 §4.1 五步前置**（realign / 派生文件 / 片段 `git add` / 绿的 `last.json` / 门禁+seal）。
8. **落地串行于门禁锁**：同时只跑**一趟**落地 —— 链④要占全局门禁锁（并发名额有限），
   两趟并行只会互相等锁 / 互相挡；上一趟没走到 ⑦ 释放锁之前，别起第二趟。
9. **文书 gaps 指针只认主树里现存的文件**：gaps 每条都要带指针，且指针必须在**落地时那棵树里真实存在**
   （文件路径 / commit sha / 快照 id）；指向「计划中的 / 还没生成的」产物 ⇒ 链②当场停
   （`python -X utf8 tools/card_doc_budget.py --gaps-file <文件> --root .` 可先自检）。
10. **`--evidence` 是文件路径，不是散文**：每个改动文件至少要有一条指针；写一句「改好了」不算证据 ——
   审计会按文件点名红。
11. **攒批**：`--batch` 走多成员预声明（`gates/diag/batch/<批号>.toml`，`register` 一次收齐）；
   **批要小（≤4）** —— 批树合不上就整批停，小批才二分得动「是哪张卡」。入口
   `tools/wb_batch.py`（plan / make / land）**已随卡 E10 落地**，三种子命令可直接用。

## 真命令

```bash
# 正式落地（默认按改动面跑必需档 —— 卡 A327；判不出 / 碰判据本体仍全量）
python -X utf8 tools/wb_land.py --card <卡号> --tree .wt/<卡号> --task <台账号> \
    --title "<一句话>" --type feat --scope <域> \
    --allow <文件>... --evidence <指针>... --port-base <端口段>

# 门禁已绿、封存没变：⑥ 起接着走（跳过 ①②③④⑤）
python -X utf8 tools/wb_land.py ... --commit-only

# 只体检不落地（卡 E1）：11 条判据一次说全、只读、约十几秒
python -X utf8 tools/wb_land.py --preflight --task <台账号> --allow <文件>...
#   0 = 全绿（可以直接落地）/ 1 = 有 ❌（逐条点名）。给了 --card / --batch ⇒ 绿了才接着落地。

# 攒批落地（批号来自多成员预声明；--card 与 --batch 恰好给一个）
python -X utf8 tools/wb_task.py register gates/diag/batch/<批号>.toml
python -X utf8 tools/wb_land.py --batch <批号> --tree .wt/batch<号> --task <台账号> ...

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
| 落了但队列还是 `pending` | 卡块缺 `status` 行 ⇒ 翻状态**静默跳过**（卡 E9） | `--allow` 里要含队列文件；**补 `status`** 后重核 `python -X utf8 tools/wb_plan.py check`（0 / 1） |
| 链②停「文书指针不存在」 | gaps / evidence 指向计划中或已改名的文件 | 指针只认**落地时那棵树里真实存在**的文件；先 `python -X utf8 tools/card_doc_budget.py --gaps-file <文件> --root .` 自检 |
| 链⑦ audit 咬「某文件没人声称」 | 审计 ⑫ 反向：本笔实际改的文件 ⊆ 台账指针（`file:` / `text:` / `test:`）∪ `[exceptions]` | 按**文件**补 `--evidence`；别只写一句「改好了」。单跑 `python -X utf8 scripts/audit_progress.py --rev <提交>`（0 / 1） |
| 落到 ⑦ 报「锁没释放 / 别人还在等」 | 锁还在（`gates/diag/gates-*.lock`） | 正常是链自己放；真泄漏才 `TF_GATE_PORT_BASE=<段> python -X utf8 gates/diag/gate_lock.py release --card <卡> --force` |
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
| ④ | 门禁锁 + 门禁（按域；碰判据本体则全量） | 红 ⇒ 停（链内自己跑，别外面再压） |
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
