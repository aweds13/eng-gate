# pipe-land —— 本仓绑定（仓无关骨架之外的那一层）

> **这一页只放"这个仓是什么样"**：命令落在哪、锁在哪、环境变量叫什么、文档指哪份、读数是多少。
> `SKILL.md` 里的动作与读法换仓也不变；换一个仓用这套技能，**只换这一份**，别改 `SKILL.md`。
> 本仓 = `program/engineering`（`pipe` 框架 + timeflow 实现）。其他仓的等价物按同一骨架填一份。
> 判据（八步定义、白名单语义、封存范围、退出码）在 `tools/pool/landing.py`，本页只做指针与读数。

## 入口与壳层参数

```bash
# 落地（壳）→ 落地链（逻辑）
python -X utf8 tools/wb_land.py --card <卡号> --tree .wt/<卡号> --task <台账号> ...   # 壳
#   └─ tools/pool/landing.py                                                            # 逻辑
python -X utf8 tools/wb_task.py status <任务>          # 前置检查第 1 条：申报齐没齐
python -X utf8 tools/card_doc_budget.py --gaps-file <文件> --root .   # 前置检查第 9 条：文书指针自检
python -X utf8 tools/wb_batch.py plan                  # 攒批入口（子命令 plan / make / land / bisect）
```

- 壳层（**不转发给落地链**）只有三个：`--preflight`（只读体检）、`--precheck <台账号|文书路径…>`
  （落地前置快检）、`--no-select`（关掉台账选测）。其余参数原样转发。
- 卡树约定：`.wt/<卡号>`；批树 `.wt/batch<号>`。
- 文书三段：`gates/diag/_text_<台账号>.md`（段名 `gaps` / `changelog` / `checkpoint`）。
- 批预声明：`gates/diag/batch/<批号>.toml`（登记一次收齐；`gates/diag/*` 被 gitignore，
  **不许**进 `--allow` —— 链里 `git add` 不带 `-f`，直接退 2）。

## 退出码表（写「退 N」之前先对这张表）

| 码 | 含义 | 真源 |
|---|---|---|
| 0 | 全绿（体检全绿 / 落地走完） | `tools/pool/landing.py` |
| 1 | 体检有 ❌ / 审计或复核判红 | 同上 |
| 2 | 云门禁机不可达（**不回落本机**）／白名单外的跟踪改动挡住某步／argparse 缺必填 | 同上 |
| 3 | 卡树与主树冲突（非派生物） | 同上 |
| 4 | ③′ fail-fast 钉子红（队列里登记的卡规格没进索引） | 同上 |
| 5 | 主干保护：主树有白名单外的跟踪改动 ⇒ 拒（任何写之前） | 同上 |
| 6 | `--card` 与 `--batch` 没有「恰好给一个」 | 同上 |
| 7 | ③″ 快门禁预检红（全量门禁一步没跑、锁也没拿） | 同上 |
| 8 | 合并队列等超时（`--queue-wait`，默认 3600 秒）⇒ 从队列摘掉 | 同上 |

## 落地前置体检（`--preflight`）：12 条，逐条名字现读自源码

★ **12 条**（2026-11-08 实读 `tools/pool/landing.py:1595` 的 docstring「12 条判据全部跑完再说」与
`:1736` 的打印行）。壳层 `--help` 的文案仍写「11 条」—— 那是陈旧文案，**以落地链为准**。
★ 12 条**全部跑完再报**，不 fail-fast；全程只读（不 `git add`、不建索引、不写 `gates/**`）。

| # | 判据 | 叫什么（屏幕上的那一行） |
|---|---|---|
| ① | 卡树 HEAD 是主树 HEAD 的祖先（否则 ① 的 checkout 会抹掉已提交的改动） | `卡树 HEAD 是主树祖先` |
| ② | 文书存在且三段齐（`gaps` / `changelog` / `checkpoint`） | `文书三段齐` |
| ③ | changelog 段首行是 `## ` 标题 | `changelog 段首行是 ##` |
| ④ | 文书结构预算与指针（真源 `tools/card_doc_budget.py`） | `文书预算与指针` |
| ⑤ | 队列里每条 `spec=` 都存在于卡树且已被 git 跟踪 | `队列 spec 已进 git` |
| ⑥ | 卡域内有产物可落地（暂存 / 未暂存 / 未跟踪都算） | `卡域内有产物` |
| ⑦ | 主树没有白名单外的跟踪改动（与 ④ 之前那道守卫**同一个函数**） | `主树 offender 为空` |
| ⑧ | 队列**全队列**卡块都有 `status` 行（缺了落地翻状态会静默跳过） | `队列卡块有 status 行` |
| ⑨ | `audit --all` 绿 | `audit --all 绿` |
| ⑩ | ruff 快检绿（`--no-cache`） | `ruff 快检绿` |
| ⑪ | `Gates:` trailer 模板合规（与 ⑥ 共用同一个模板函数） | `Gates: trailer 模板合规` |
| ⑫ | 本次三份文书里反引号包住的 `.md` 都解析得到（三基准同 `check_layers`） | `文书引用解析得到` |

- 退出码：`0` 全绿 / `1` 有 ❌。全绿那行打 `✓ 12 条全绿（…s，只读）⇒ 可以直接落地`。
- ⑧ 在批模式（给了 `--batch`）下不逐卡判：成员翻账按「产物 ∩ 暂存清单」走。
- 体检还会**先说锁**（只读：不清锁、不写文件）—— 等锁 28 分钟才发现的代价太大。
- 2026-11-08 实测 `python -X utf8 tools/wb_land.py --preflight --card E93` ⇒ **rc=1**，
  屏幕正好 12 行，2 条 ❌（⑥卡域内无产物 / ⑨audit 被当时别人在改的 `skills/pipe-gate/SKILL.md` 咬红）。

## 八步链里那几个容易漏的子步

`tools/pool/landing.py` 模块 docstring 的真文比「八步」细，`SKILL.md` 的表已按它画：

- **⓪′ 落地前快照**（卡树 + 主树，`stash create` + 挂 ref ⇒ gc 不清、镜像带得走）。
- **③′ fail-fast 钉子**（队列里登记的卡规格必须已进索引；红 ⇒ 退 4，**在全量门禁之前**）。
- **③″ 快门禁预检**（`scripts/run_gates.py --fast`，十几秒、不落盘；红 ⇒ 退 7）。次序钉死：
  参数合法性（退 6）→ ③′ → ③″ → ④ 全量。`--skip-preflight` 可跳（旧名 `--no-preflight` 仍收）。
- **④′ 合并队列**（同写者：④–⑦ 同时只许一笔；同文件卡不许同批）。
- **⑤′ 白名单核对 + 落地即翻 status**、**⑤′.5 重算现算文档**、**⑤ `--seal` 封存**、**⑤″ 兜底重封存**。
- **⑧ 复核**：`tools/wb_review.py --rev <新提交> --json` → 落 `gates/review/<task>.json`；
  异步、不挡提交，但**申报收口（`landed`）之前必须存在一条复核记录**。
- `--gate-on {cloud,local}`：默认读 `TF_GATE_ON`，再默认 **cloud**；云机不可达 ⇒ 退 2 且**没有**继续落地。

## 封存与锁（本仓的具体形状）

- 封存文件 `gates/last.json`：`rev` = 被封的那笔（落地后应等于 `HEAD^`），`tree` = 去掉 `gates/**` 的提交树。
  对不上**不许手改**，重跑落地。
- 门禁锁：`gates/diag/gates.lock`（没给段）/ `gates/diag/gates-<端口段>.lock`（给了段）。
  读账本 `python -P -X utf8 gates/diag/gate_lock.py status`（★ `-P` 必须带，铁律 24：防 `gates/diag/`
  里的同名脚本顶掉标准库）；它给持有者与**租约剩余**，默认租约 **10800 秒**（`--stale-after` 可调）。
- **人工兜底只有一条**：`TF_GATE_PORT_BASE=<段> python -X utf8 gates/diag/gate_lock.py release --card <卡> --force`
  —— 不带段会在默认段里找锁、报「没有锁，无需释放」，真锁照样泄漏。
- `gate_lock.py` 退出码：`0` 拿到 / `3` 等超时 / `4` 释放时锁不是你的（`--force` 才强解）/ `5` 续租时锁不是你的。

## 环境变量（`scripts/run_gates.py` 与 `gate_lock.py`）

| 变量 | 不设时的行为 | 备注 |
|---|---|---|
| `TF_GATE_PORT_BASE` | **8531**（历史默认，逐字不变） | 与 `gate_lock.py::segment_base()` 同口径；释放锁要带同一个段 |
| `TF_PYTEST_WORKERS` | 按可用内存自适应分档 | 内存紧时会自己降到 1 |
| `TF_PYTEST_DIST` | `worksteal` | — |
| `TF_GATE_DOOR_TIMEOUT` | `DEFAULT_DOOR_TIMEOUT = 1800.0` 秒 | `0` = 关掉逐门硬超时（会打印「已关」） |
| `TF_GATE_DOOR_BUDGET` | 600 秒 | 超了只告警、不阻断；`0` 关 |
| `TF_GATE_MIN_FREE_GB` | 2.0 | 内存闸；`0` 关 |
| `TF_SELECT` | 落地链里默认 **1**（走台账选测） | 可被壳层 `--no-select` 关掉 |
| `TF_TIA` | 不开 | `=1` 按覆盖映射选测；判不出退回全量 |
| `TF_GATE_ON` | 再默认 **cloud** | 与 `--gate-on` 同源 |
| `TF_GATE_MAX_CONCURRENT` | 2（门禁锁的并发上限，**不是目标**） | 锁在 = 有人正在跑这趟，等锁不是卡死 |

## 跨机 / 跨档的口径指哪份文档

- 云门禁机能不能上、怎么排队：`docs/subsystems/ci/云门禁机.md`（读它的自检命令，别读某张卡的进度）。
- 该跑哪一档、何时选测与夜间：`docs/subsystems/ci/测试流程.md`。
- 跑门禁本身（档位 / 锁 / 逐门超时）见 `skills/pipe-gate/references/repo-bindings.md`，本技能不重复。

## 复盘缺口（队列状态收口 · 历史证据层）

这一节是**历史证据层**：每条缺口挂 2–3 份复盘。读它为了知道「为什么有这条检查」，不是当判据用。

- （缺口 PO13）队列状态要收口：落地即翻状态（同一笔里做完），否则面板永远显示「落了没翻」——
  落地时白名单必须含队列文件；落地后用 `python -X utf8 tools/wb_reconcile.py` 核 stale。
  证据：`复盘/卡/卡204-落地即翻状态.md`、`复盘/并行与攒批模型.md`、`复盘/交接.d/T-G310.md`
- （缺口 PO8）收口链必须先把「要提交的文件」同步进卡树，否则文书引用不可达 ⇒ 每笔都可能假红
  （红在顺序，不是红在判据）。处置：先 `git checkout <主树> -- <文件>`，再生成文书。
  证据：`复盘/交接.d/T-G274.md`
- 文书反引号断链那一族（裸文件名 / 占位符 / 通配符）：`复盘/口径坑.md` 坑 21/29/40；
  提前到秒级的那条快检（`--precheck <台账号>`）来自卡 A301，证据 `复盘/卡/卡A295-坑进流程.md`、
  `tests/test_false_success_pins.py`。

## 本仓特有的两处读数怎么读

- `--affected` / `--changed-from` 是**增量**，trailer 会写「非全量」；碰 `scripts/**` `tools/**` `gates/**`
  （判据本体）强制回全量，今天还没跑过全量也会强制回全量。别把增量那趟当全量读数。
- 复核产物不在 ⇒ 先看 `--no-review` 有没有被用；再看 `gates/review/<task>.json` 与逐门日志
  （`gates/logs/<门名>.log`，不进仓库）。
