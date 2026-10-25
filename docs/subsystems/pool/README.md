# pool 子系统（分区 G 的执行侧）—— 项目书

> 立项：2026-10-25（卡 F5 · `T-AG480`）。依赖：F3 的 `scripts/check_docs.py` 已落。
> 一句话：**pool 不是"跑门禁的那堆工具"，是仓库里唯一一处"派活与收口"的执行侧** ——
> 它决定「哪张卡、谁在改、改完怎么收成一笔提交」，但**不判门过不过、不写判据、不下审计结论**。
> 与 `docs/subsystems/ci/README.md` 同构：本篇只回答「是什么 / 多大 / 定了什么 / 边界在哪」，
> 判据本体一律留在 `tools/` `tests/` `gates/`，**这里不抄**。

## 1. 它现在是什么（代码边际）

`tools/pool/` = 17 个 py（16 个模块 + `__init__.py`）、**7143 行**（`wc -l tools/pool/*.py`，2026-10-25 实测）。
每个模块都可 import（判据在库里），每个 CLI 都是**薄壳**（只解析参数 + 打印）。

| 模块 | 行 | 职责 | 命令壳 |
|---|---|---|---|
| `tools/pool/guards.py` | 321 | 树 / 域 / 门禁锁 / 日志 / 项目五条守卫，**纯函数**（吃数据回 `list[str]`） | 无（被 `wb_dispatch` 调） |
| `tools/pool/registry.py` | 345 | 租约账：`reserve` / `release` / `list_reservations` / `is_dead` | `wb_dispatch`、`wb_registry` |
| `tools/pool/lease.py` | 109 | 租约命令行（把码道那条路接进同一本账） | 本文件即入口 |
| `tools/pool/locks.py` | 76 | 门禁锁的**只读**封装：`status_argv` / `parse_entries` | 无 |
| `tools/pool/task.py` | 1565 | 任务栅栏：批目录 / 收件箱 / 自旋锁 / 域检查 | `wb_task.py` |
| `tools/pool/landing.py` | 1962 | 落地链八步（⓪ 回退 → ⑧ 复核落盘） | `wb_land.py` |
| `tools/pool/review.py` | 92 | 白名单越界 / 实际改动 vs 权威域（`outside_allow` / `outside_domain`） | 无 |
| `tools/pool/plan.py` | 575 | 队列校验（`validate`）、冲突域、排批 | `wb_plan.py` |
| `tools/pool/stage_card.py` | 363 | 三段文书片段生成器 | `wb_stage_card.py` |
| `tools/pool/models.py` | 245 | 号池快照读取（批准集 ∩ 可用集）+ 外部开关文件 | `wb_state.py` |
| `tools/pool/model_registry.py` | 468 | 一层注册表、按池分流（`resolve_model` / `effective_allowed_for`） | `wb_dispatch` |
| `tools/pool/projects.py` | 223 | 项目索引只读 + 三条硬判据 | `wb_project.py` |
| `tools/pool/snapshot.py` | 104 | 零风险快照（`stash create` + 挂 ref） | 无 |
| `tools/pool/jobs.py` | 325 | 日志三态判据 / 产物定位（只读） | `wb_status.py` |
| `tools/pool/trae_dispatch.py` | 316 | 面板道进账（**刻意不接进派活**，卡 218） | 本文件即入口 |
| `tools/pool/no_window.py` | 29 | 起子进程不弹窗的常量 | 无 |
| `tools/pool/platforms.toml` | 192 | **平台能力表**（八个平台的端点 / 凭据形态 / 结论码 / 出处）：进 git、可审、**零凭据** | 无（被 `pool_accounts.py` 读） |
| `tools/pool_accounts.py` | 739 | **账号账本**只读面：`list` / `show` / `discover` / `probe`（在 `tools/` 根，不在 `tools/pool/`） | 本文件即入口 |
| `tools/pool/__init__.py` | 25 | 包说明 | — |

两张**账**分开住，这是理解本子系统的关键：

| 账 | 文件 | 记什么 | 真源模块 |
|---|---|---|---|
| 租约账 | 主树的 `gates/diag/pool-registry.json` | 谁占了哪棵树、哪个冲突域 | `tools/pool/registry.py` |
| 任务账 | 主树的 `gates/diag/batch/<任务>.toml` + `<任务>.json` | 这个任务要哪些卡、谁交了申请 | `tools/pool/task.py` |
| 账号账 | **仓外** `infra/pool/accounts.toml`（`TF_ACCOUNTS_TOML` 可覆盖） | 我有哪些号、每号批了哪些模型、额度最后观测是什么时候 | `tools/pool_accounts.py` |

> 前两张都锚在**主工作树**（`git rev-parse --git-common-dir` 的父目录），不在卡树 ——
> 卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写（`tools/pool/registry.py:72`、`tools/pool/task.py:119`）。
> 账号账**故意在仓外**：只存凭据指针（`~/.codeartsdoer/pool.env` 之类），不存凭据本身；
> 没有 git 兜底，所以写入一律原子替换，删号打墓碑（`tools/pool_accounts.py` 的 `save_ledger()`）。

## 2. 度量（2026-10-25 实测）

| 指标 | 读数 | 怎么取 |
|---|---|---|
| 实现体量 | 7143 行 / 17 个 py | `wc -l tools/pool/*.py` |
| 队列卡数 | 239 张（218 done / 21 pending） | 读 `docs/workbacklog.toml` 的 `cards` |
| 批预声明 | 132 份 | `ls gates/diag/batch/*.toml \| wc -l`（只主仓有） |
| 派活日志 | 224 份（不含用量账与当前这轮） | 主树 `gates/diag/wb-*.jsonl` 共 226 个文件，减 `wb-usage.jsonl` 与当前这张卡 |
| 单次派活墙钟 | 中位 **681 s**、均值 909 s、最长 6858 s（222 份有 ≥2 个时间戳的样本） | 每份日志首个/末个 `__timestamp` 之差 |
| 最近一份跑完的 | `wb-E13.jsonl` 396 s（2026-10-24） | 同上 |

口径两条（别读错）：① 只统计**有 ≥2 个 `__timestamp`** 的日志，`wb-usage.jsonl`（用量账）不计；
② 耗时是**工人进程的墙钟**，不含主控自己的落地链（那条 11–15 min 记在 CI 子系统的度量里）。

## 3. 决策（D1–D7，指回卡号）

- **D1 守卫写成纯函数、只有一份**（卡 106 · `T-G202`）：吃数据回问题、不写文件不起进程 ——
  所以写面（派活）能直接复用，不会变成第二份真源。见 `tools/pool/guards.py:1`。
- **D2 租约账全窗口一本**（卡 108 · `T-G205`）；码道那条派活路也接进**同一本**（卡 195 · `T-G295`）——
  「两本账 = 守卫照旧瞎」，见 `tools/pool/lease.py:1`。
- **D3 攒批按「任务种类」不按数量**（用户 2026-10-02 裁定，卡 119 · `T-G217` 进 git）：
  判据是「名单上每一张卡都交了成功申请」，**不是**攒够 N 条。见 `tools/pool/task.py:1`。
- **D4 一层注册表、按池分流**（卡 166 · `T-G266`）：两个池的 id 体系不同（裸名 vs `provider/model`），
  所以"挑一份当真源"本身是错的。见 `tools/pool/model_registry.py:1`。
- **D5 落地链八步、封存排在暂存之后**（卡 228 · `T-G344`）：翻账是对跟踪文件的最后一笔改动，
  封存必须等它定型，否则「封存树 ≠ 提交树」必然红。见 `tools/pool/landing.py:31`。
- **D6 动别人工作区之前先打快照**（卡 192 · `T-G292`）：`stash create` + 挂 `refs/snapshots/*`
  （不挂 ref 的快照会被 gc 清掉，"救回来"只是运气）。见 `tools/pool/snapshot.py:1`。
- **D7 面板道进账、但不接进派活**（卡 218 · `T-G331`）：面板会重载 ⇒ 驱动 await 不 settle；
  它只把一次跑落成租约 + 日志 + 判决三样，**不 import `wb_dispatch`**。见 `tools/pool/trae_dispatch.py:1`。

## 4. 卡表（本子系统的账，不是全部历史）

| 卡 | 台账号 | 落了什么 |
|---|---|---|
| 106 | `T-G202` | 纯函数层抽出：guards / locks / jobs / models / plan / review / snapshot |
| 108 | `T-G205` | 租约账 + 门禁锁解析（`is_dead` / `list_reservations` / `parse_entries`） |
| 119 | `T-G217` | `task.py` 进 git（栅栏本体成为可 import 的权威副本） |
| 120 | `T-G232` | 项目索引 + 项目守卫（`project_guard`） |
| 128 | — | 域检查 + `gate_cmd` 白名单化 + 受保护共享文件 |
| 131 | `T-G228` | 实际改动 vs 权威域（`changed_paths` / `outside_domain`） |
| 138 | `T-G236` | 模型开关文件（只做加法，不进轮换链） |
| 139 | `T-G237` | `landing.py` / `stage_card.py` 进 git |
| 143 | — | 审计型只读成员（`read_only = true`） |
| 149 | `T-G249` | 多号：按 profile 现取环境变量注入 |
| 166 | `T-G266` | 一层注册表 + 按池适配器 + 最小规矩集 |
| 184 | `T-G284` | 增量门禁（三条强制全量）+ 复核落盘异步 |
| 192 | `T-G292` | 主干保护 + 落地前快照 |
| 195 | `T-G295` | 租约 CLI（码道并账） |
| 204 / 212 / 228 | `T-G311` / `T-G323` / `T-G344` | 落地即翻 status / 攒批收口 / 封存次序 |
| 218 | `T-G331` | 面板道进账 |
| F5 | `T-AG480` | 本篇（五篇说明书 + 旧三篇加注） |

专题页：[`派活口径.md`](派活口径.md)（四张入口的契约）· [`模型与号池.md`](模型与号池.md)（三集关系与 429）·
[`租约与锁.md`](租约与锁.md)（四把锁与死主）· [`事后判据清单.md`](事后判据清单.md)（现象 → 产物 → 判据）。

## 5. 边界

pool 只做**派活与收口**。下面三张表是全卡的主判据：写偏了（把门禁判据抄进来、把 pool 描述成"跑门禁的工具"）
就是没写成。

### 表 A · 唯一实现归属（谁是真源、谁是薄壳）

真源一律在 `tools/pool/**`；右列是**实测的 import 行**（`grep -n` 可复现）。

| 模块 | 薄壳入口 | 证据（薄壳里的 import 行） |
|---|---|---|
| `tools/pool/guards.py` | `tools/wb_dispatch.py` | `wb_dispatch.py:120` —— `from pool import guards as pool_guards  # 守卫唯一实现` |
| `tools/pool/registry.py` | `tools/wb_dispatch.py`、`tools/wb_registry.py` | `wb_dispatch.py:121`（`作业登记唯一实现`）、`wb_registry.py:28` |
| `tools/pool/task.py` | `tools/wb_task.py`、`tools/auto_land.py`、`tools/wb_advcard.py` | `auto_land.py:79` —— `# 批目录 / 收件箱 / 自旋锁唯一实现`；`wb_task.py:33` |
| `tools/pool/landing.py` | `tools/wb_land.py` | `wb_land.py:69` —— `from pool import landing as _landing` |
| `tools/pool/review.py` | `tools/wb_impact.py` | `wb_impact.py:55` —— `# 白名单判据唯一实现` |
| `tools/pool/plan.py` | `tools/wb_plan.py` | `wb_plan.py:82`、`:84` |
| `tools/pool/stage_card.py` | `tools/wb_stage_card.py` | `wb_stage_card.py:22` —— `from pool import stage_card as _stage_card` |
| `tools/pool/models.py` / `model_registry.py` | `tools/wb_state.py`、`tools/wb_dispatch.py` | `wb_state.py:70`（惰性 import）、`wb_dispatch.py:123` |
| `tools/pool/projects.py` | `tools/wb_project.py` | `wb_project.py:30` —— `from pool import projects, registry` |
| `tools/pool/platforms.toml` / `tools/pool_accounts.py` | `tools/pool_mcp.py`（`account_status`） | `pool_mcp.py` 的 `tool_account_status()` —— `import pool_accounts`，MCP 面只读账本、不探测不联网 |
| `tools/pool/trae_dispatch.py` | **无**（刻意不接进派活，卡 218 已裁定） | 全仓 `grep -rn trae_dispatch` 只命中 `tests/test_trae_dispatch.py` |

### 表 B · pool 不做的事（每条写「归谁」+ 证据）

| # | 不做 | 归谁 | 证据 |
|---|---|---|---|
| 1 | 不判「门过不过」 | 门表与判据在 `gates/defs/`；编排在 `scripts/run_gates.py` | `tools/pool/landing.py:25`（③″ 调 `run_gates.py --fast`）、`:28`（④ 跑门禁） |
| 2 | 不改判据、不放宽门、不手写门禁结论 | 判据归 `gates/`，封存归 `scripts/run_gates.py` | `scripts/run_gates.py:860`（`def seal()`） |
| 3 | 不算台账分布 | 片段只**写**、汇总归 `tools/sync_docs.py`、分布归 `tools/sync_counts.py` | `tools/pool/stage_card.py:1`；`tools/pool/landing.py:24`（③ 调 sync_counts） |
| 4 | 不建 / 不删工作树 | 树由 `tools/wb_plan.py worktrees` 建；pool 只在给定树里干 | `tools/wb_plan.py:22` |
| 5 | 不判模型额度与批准集 | 批准集在号池快照 + `tools/pool/model-registry.toml`；pool 只**读** | `tools/pool/models.py:1`（"只读、不联网、不写快照"） |
| 6 | 不做审计结论 | 归 `scripts/audit_progress.py` | `tools/pool/landing.py:37`（⑦ 调它） |
| 7 | 不做技能口径 | 归 `skills/`（分区 G）；**删掉 `skills/` 框架仍可用** | `skills/README.md` |

### 表 C · 与相邻子系统的交界（交界处谁说话）

| 相邻 | 交界在哪 | 谁定义口径 |
|---|---|---|
| CI 子系统（分区 E） | 门禁档位、封存指纹、红单归并 | `docs/subsystems/ci/README.md` |
| 文档治理（分区 F） | 片段的形态、汇总同步、文档门禁 | `docs/subsystems/`、`scripts/check_docs.py` |
| 软工技能（分区 G） | 操作顺序与常见错（怎么用，不是判据） | `skills/` |
| 号池基础设施（仓库外） | 池注册、账号、模型开关文件 | `D:/repo/infra/pool/`（仓外，只读） |

**越界判据**（写偏了就判不通过）：把门禁判据抄进 pool 文档；把 pool 描述成"跑门禁的工具"；
出现"未来会做"；把 `skills/` 的操作步骤整段搬过来；表 A/B/C 任一表缺失或缺证据路径。
