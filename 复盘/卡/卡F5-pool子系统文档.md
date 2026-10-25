# 卡 F5 —— pool 子系统文档：把 7143 行实现写成五篇可核的说明书

> 台账号 T-AG480 · 分区 F（文档治理）· 依赖：无（F3 的 `scripts/check_docs.py` 已落）

## 现在疼在哪

`docs/subsystems/` 下**只有 `ci/`** 一个子系统。号池/派活器（`tools/pool/` 17 个模块、7143 行）没有一份子系统说明书，知识散在三种地方：

| 现存的 | 行数 | 为什么不够 |
|---|---|---|
| `复盘/号池MCP-使用与设计.md` | 103 | 只讲 MCP 八个工具怎么接；含过期断言（原文说「`_stage_card.py` 未进 git，这是已知缺口」，而 `tools/pool/stage_card.py` 今天**在库里**：`git ls-files tools/pool/stage_card.py` 有输出） |
| `复盘/派活器三合一-T-G114.md` | 230 | 是那次改动的**变更记录**，不是现状口径 |
| `复盘/外包派活脚本-T-G82.md` | 46 | 已被 T-G114 超越 |
| `skills/pipe-card/references/dispatch.md` | 125 | 技能层按铁律只写「怎么用」，**不抄判据、不描述实现** |

结果：要回答「派活器现在到底怎么工作、谁能写、产物在哪、哪条判据在哪」得同时读四份互相矛盾的文档，还会读到已失效的结论。

## 目标

新建 `docs/subsystems/pool/`，**与 `docs/subsystems/ci/` 同构**（那份是 69 行的 `README.md` + 判据清单 + 专题页），五篇：

| 文件 | 必须回答 |
|---|---|
| `README.md` | 是什么（分区 G 的执行侧）/ 度量（卡数、批数、最近一次派活耗时）/ 决策 D1–Dn（指回卡号）/ 边界（明确不做什么） |
| `派活口径.md` | `wb_dispatch` → `wb_task register` → `claim` → `wb_land` 四张入口的**契约表**：谁写、写什么、参数口径、失败怎么报 |
| `模型与号池.md` | 批准集 / 可用集 / 开关文件三者的关系、跨池为什么拒、429 时的处置 |
| `租约与锁.md` | 租约（`lease.py`）、树锁（`registry.py`）、门禁锁（`gates/diag/gate_lock.py`）各保什么、TTL、死主怎么办 |
| `事后判据清单.md` | 照 `docs/subsystems/ci/事后判据清单.md` 的表格结构：现象 → 去哪份产物 → 哪条判据 |

## 边界（这一节是全卡的**主判据**，写不清就是没写成）

pool 必须被写成「**一个只管派活与收口的执行侧**」，而不是「仓库里跟门禁/提交/台账混在一起的那堆工具」。`README.md` 必须有独立一节 `## 边界`，内含三张表：

**表 A · 唯一实现归属**（谁是真源、谁是薄壳，每条给 `grep -n` 证据）：

| 模块 | 薄壳入口 | 不许在别处重写的理由（实测注释原文） |
|---|---|---|
| `tools/pool/guards.py` | `tools/wb_dispatch.py`（`from pool import guards as pool_guards  # 守卫唯一实现`） | 域/树/锁/日志四类拦截只有一份 |
| `tools/pool/registry.py` | `tools/wb_dispatch.py` / `tools/wb_registry.py` | 「作业登记唯一实现」 |
| `tools/pool/task.py` | `tools/wb_task.py` / `tools/auto_land.py` / `tools/wb_advcard.py` | 「批目录 / 收件箱 / 自旋锁唯一实现」 |
| `tools/pool/landing.py` | `tools/wb_land.py`（`from pool import landing as _landing`） | 八步链只此一处 |
| `tools/pool/review.py` | `tools/wb_impact.py` | 「白名单判据唯一实现」 |
| `tools/pool/plan.py` | `tools/wb_plan.py` | 队列校验与排批 |
| `tools/pool/stage_card.py` | `tools/wb_stage_card.py` | 文书生成 |
| `tools/pool/models.py` / `model_registry.py` | `tools/wb_state.py`、`wb_dispatch` | 号池快照 / 开关 / 允许集 |
| `tools/pool/projects.py` | `tools/wb_project.py` | 项目书索引 |
| `tools/pool/trae_dispatch.py` | 无（**刻意不接进派活**，卡 218 已裁定） | 面板会重载 ⇒ 驱动 await 不 settle |

**表 B · pool 不做的事**（≥6 条，每条写「归谁」+ 证据路径）：

- 不判「门过不过」：`tools/pool/landing.py:25` 只是**调** `scripts/run_gates.py`；门表与判据在 `gates/defs/*`。
- 不改判据、不放宽门、不手写 `gates/last.json`：判据归 `gates/`，封存归 `scripts/run_gates.py --seal`。
- 不算台账分布：`tools/pool/stage_card.py` 只**写**片段，汇总归 `tools/sync_docs.py`，分布归 `tools/sync_counts.py`。
- 不建/不删工作树：树由 `tools/wb_plan.py worktrees` 建；pool 只在给定树里干活。
- 不判模型额度与批准集：归 `tools/pool/model_registry.py`（允许集）+ 号池快照文件，pool 只**读**。
- 不做审计结论：归 `scripts/audit_progress.py`；pool 只把它的红单原文带回给人看。
- 不做技能口径：归 `skills/`（G 分区），pool 文档不许抄技能里的流程话术。

**表 C · 与相邻子系统的交界**（各一行，说明「交界处谁说话」）：

| 相邻 | 交界在哪 | 谁定义口径 |
|---|---|---|
| CI 子系统（分区 E） | 门禁档位、封存指纹、红单归并 | `docs/subsystems/ci/` |
| 文档治理（分区 F） | 片段的形态、汇总同步、文档门禁 | `docs/subsystems/`、`scripts/check_docs.py` |
| 软工技能（分区 G） | 操作顺序与常见错 | `skills/**`（铁律：删掉 `skills/` 框架仍可用） |
| 号池基础设施（仓库外） | 池注册、账号、模型开关文件 | `D:/repo/infra/pool/`（仓库外，只读） |

**越界判据（写偏了就判不通过）**：把门禁判据抄进 pool 文档；把 pool 描述成「跑门禁的工具」；出现「未来会做」；把 `skills/` 的操作步骤整段搬过来；表 A/B/C 任一表缺失或缺证据路径。

## 判据

1. **五篇齐全**，`README.md` 的二级节与 `docs/subsystems/ci/README.md` 同构（现在是什么 / 度量 / 决策 / 卡表 / **边界**），且「边界」节按上面三张表写全。
2. **参数口径必须实测**：每篇里出现的命令行/参数都要有跑过的读数（`--help` 输出或真实一次调用），不许凭印象写。至少覆盖：
   - `tools/wb_dispatch.py` 只认 `--cwd`（不是 `--tree`）、`--pool codebuddy|codearts`、跨池串用被拒的原文报错；
   - `tools/wb_task.py register <toml>` 的预声明必填项（`why`、`[[member]]` 表头、成员键 `id`、`paths` 必须含卡规格）；
   - `claim` 的 `--files` 是**逗号串**、域外文件被 `RefuseError` 点名；
   - `wb_land --batch` 与 `--commit-only` 的差别（后者跳过 ①～⑤ 的实测依据：`tools/pool/landing.py` 里那段分叉）。
3. **事实可核**：文档里点到的每个文件/函数都必须存在 —— 文件用 `git ls-files <path>` 有输出，函数用 `grep -n "def <name>" <file>` 命中；**不许出现「未进 git」「还没做」这类没复核的判断**。
4. **旧三篇加注**：`复盘/号池MCP-使用与设计.md`、`复盘/派活器三合一-T-G114.md`、`复盘/外包派活脚本-T-G82.md` 顶部各加**一行**加注「本页是历史记录；现状口径见 `docs/subsystems/pool/README.md`」，**原文正文一个字都不改**（CF1 口径：保留原文 + 顶部加注）。
5. **不抄判据**：判据本体仍在 `tools/` `tests/` `gates/`；每篇只写「去哪看」，抄进散文即算不通过。
6. **体量上限**：每篇 ≤ 200 行、五篇合计 ≤ 900 行（防止把代码抄一遍）。
7. **自证**：贴 `python -X utf8 scripts/check_docs.py`、`python -X utf8 scripts/check_layers.py`、`python -X utf8 tools/check_skills.py`、`pytest tests/test_check_docs.py -q -o addopts=` 四条读数。

## 起点材料（不要从零猜）

- 模块与公开函数（实测于 `945a15c`，可直接引用）：`guards.py`（`tree_guard/domain_guard/lock_guard/log_guard/project_guard`）、`jobs.py`（`parse_events/card_artifacts`）、`landing.py`（`reset_derived/is_ancestor/expand_allow`）、`lease.py`（`cmd_claim/cmd_release`）、`locks.py`、`model_registry.py`（`effective_allowed_for/resolve_model/rotation_chain_for` + 四个异常类 `PoolMismatchError/UnknownPoolError/PoolNotWiredError`）、`models.py`（`load_pool_models/load_switches/compare_rosters`）、`plan.py`（`validate/audit_batch_claims/dependency_path`）、`projects.py`、`registry.py`（`is_dead/list_reservations`）、`review.py`（`outside_allow/outside_domain`）、`snapshot.py`（`take_snapshot/snapshot_sha`）、`stage_card.py`、`task.py`（`batch_dir/manifest_path/state_path` + `BatchError/RefuseError`）、`trae_dispatch.py`。
- 产物路径：`gates/diag/wb-<卡>.jsonl`、`wb-<卡>.report.md`、`wb-<卡>.verdict.txt`、`gates/diag/batch/<任务>.toml`、`<任务>.why.md`、`gates/diag/gates-<端口>.lock`。
- 已落卡的结论可直接链：卡 E7/E9（攒批三例）、E24（分档门禁复核口径）、E25（翻账不再抹证据）、G3（`--preflight` 分层）、G4（`skills/softeng-manage/references/retired-settings.md` 旧设置退役表）。

## 不许做

- 不许改 `tools/`、`gates/` 下任何代码或判据（本卡只写文档）。
- 不许把 `retired-settings.md` 那张表复述一遍 —— 只链过去。
- 不许写「未来会做 X」当现状；没有实测支撑的段落直接删掉，别用「可能」「应该」糊。
- 不许新增 `docs/subsystems/pool/` 以外的文件（旧三篇只加一行注）。
