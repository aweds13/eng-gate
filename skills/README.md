# skills —— 框架自带的人机接口（薄适配层）

> 这一层是**核心之上的薄适配层**：它把「怎么用才不出错」教给 agent（和人）。
> ★ 本层的判据：**删掉整个 `skills/` 目录，框架仍然完整可用。** 做不到，就说明判据漏进 skill 了。

> ★ **2026-10-24 起四条新口径**（老窗口若还按旧写法干，门禁会拦下并说明原因）：
> 1. **一张卡只归一个对话窗口**（卡 A324）：别的窗口的卡要显式 `--take-over` 才让过，
>    `wb_land` / `wb_dispatch` 被挡时退 2 并打印持有者；没 `DSH_SESSION_ID` 的环境（工人 / cron）照常放行。
>    看谁的卡：`python -X utf8 tools/wb_session.py --list`。
> 2. **工具根 ≠ 数据根**（卡 A326）：门表跟 `tools/` 走，台账 / 门禁产物跟**数据根**走
>    （`PIPE_DATA` > 当前目录像数据根 > 工具根）。默认两根同值，行为不变；
>    同一份 `tools/` 服务别的仓时才需要设 `PIPE_DATA`。
> 3. **提交闸按域要档**（卡 A327）：`gates/defs/domains.py` 一张表算必需档，
>    `last.json` 记 `profiles_run / required_profiles`；判不出或碰判据本体（`scripts/**` `tools/**` `gates/**`）
>    仍强制全量。缺档提交会被 `wb_review` 点名拒。
>    ★ **门数不写死**：以 `scripts/run_gates.py` 的 `GATE_PROFILES`（或它落盘的 `gates/last.json` 的 `gates[]` 条数）为准，
>    要写就读一次、带上日期（卡 E104 之前这里写死过「2026-10-28 现读 22 道」，门表一变它就在说错话）。
> 4. **派活即看守**（卡 E7）：`tools/wb_dispatch.py --execute` 起完工**自动**挂一份 `tools/wb_watch.py`
>    （默认 `--watch one`；`--watch shared` = 全局一份、引用计数归 0 写 `batch-done`）。
>    完工信号落 `gates/diag/wb-<卡>.done` + `gates/diag/notifications.jsonl`。
>    ★ 只有显式 `--no-watch` 才不起 —— 那时它**明说**「已关看守：完工后请自己轮询」，别当成已经有人盯。

## §0 新机制八条：落点索引（卡 G2 · 2026-10-24）

> 以前这八条在本目录里**一个字都没有** ⇒ 规矩只在最后时刻说话（18 处断链等到落地第 20 分钟才红）。
> 每条都按「疼在哪 + 命令 + 退出码」写在**明细页**：`skills/softeng-manage/references/commands.md` 的 ⓪ 节。
> 这里只给**一句话 + 去哪看**，别在别处再抄一遍（抄三份必漂）。

| 机制 | 一句话（疼在哪） | 命令 / 退出码（短版） | 明细 |
|---|---|---|---|
| 工具根 ≠ 数据根（A326） | 两根绑死 ⇒ 复用 `tools/` 时账本被写回工具仓 | `python -X utf8 tools/pipe_root.py --check`（0 / 2） | 命令速查 ⓪-1 |
| 引用完整性（`check_link_integrity`） | 反引号里的 `.md` 被当真路径查 ⇒ 断链连坐两道门 | `python -X utf8 scripts/check_layers.py`（0 / 1） | 命令速查 ⓪-2 |
| 队列 `status` 行（E9） | 缺这一行 ⇒ 落地翻状态**静默跳过**（已落仍 pending） | `python -X utf8 tools/wb_plan.py check`（0 / 1） | 命令速查 ⓪-3 |
| 审计 ⑫ 反向 | 「实际改的文件」没人声称 ⇒ 审计咬下来重跑 | `python -X utf8 scripts/audit_progress.py --rev <提交>`（0 / 1） | 命令速查 ⓪-4 |
| E1 `--preflight` | 参数 / 文书 / 卡域的错拖到第 12 分钟才红 | `python -X utf8 tools/wb_land.py --preflight --task <台账号> --allow <文件>...`（0 / 1） | 命令速查 ⓪-5 |
| E7 派活即看守 | 派完靠人肉轮询，忘了就过夜 | `python -X utf8 tools/wb_dispatch.py --card <卡号> --status` | `pipe-card` 的分派页 §6 |
| 攒批（`--batch`） | 一张卡两趟门禁；栅栏按卡建则永远攒不成 | `python -X utf8 tools/wb_task.py register gates/diag/batch/<批号>.toml` + `wb_land.py --batch` | 命令速查 ⓪-7 · `pipe-card` 分派页 §7 |
| 门禁锁与并发闸 | 两趟全量并行 = 假红；锁消失 = 那趟收口 | `TF_GATE_PORT_BASE=<段> python -X utf8 gates/diag/gate_lock.py release --card <卡> --force` | `pipe-gate` 前置检查 ⑤ |
| `tools/auto_land.py` | 收口时机曾靠 agent 读自然语言 | `python -X utf8 tools/auto_land.py --dry-run`（0 / 2 / 3 / 4 / 5） | 命令速查 ⓪-8 |

★ **旧口径还作数吗**：`skills/softeng-manage/references/retired-settings.md` 一页退役表（`active` / `已改判` / `已改名` / `半冲突`，每行指回改成它的卡与一条能重跑的命令）。

★ **云门禁机**（多会话共享一台）的正式口径在 `docs/subsystems/ci/云门禁机.md` —— 本页不写推断，别自己发明排队规矩；那台机器现在能不能上，读那份里的自检命令，别读某张卡的进度。

## 定位

- 框架本体 = 核心库（`framework/src/framework/**`）+ 薄 CLI（`framework/cli/main.py`）+ 模板仓 + 例子。
- skills = **只有操作知识**的一层：顺序、前置检查、常见错、该看哪个产物。
- 本仓主路径的命令是 `python -X utf8 tools/wb_*.py` 与 `python -X utf8 scripts/run_gates.py`；
  框架 CLI（`python -X utf8 framework/cli/main.py <命令>`）只在 `init` 这类自带模板的动作上直接用。
  两套命令的对照见 `skills/softeng-manage/references/mapping.md`。
- **契约（两条，别拿一条的绿当另一条也绿）**：`SKILL.md` 里引用的每个命令名，必须能在**同版** `pipe --help` 里找到
  （钉子①，只覆盖框架 CLI 那一条接法）；本仓主路径那种「`tools/` 下的脚本 + 某个 `--flag`」的写法，由
  `python -X utf8 tools/check_skills_claims.py --check`（门名 `skills_claims`）对 `tools/` 源码逐个核。

## §1 ★ 分工判据：这东西该放哪

| 这东西该放哪 | 判据 |
|---|---|
| **核心库**（`framework/src/framework/**`） | 逻辑与判据；不 `print`、不 `sys.exit`；换个前端照样成立 |
| **CLI 子命令**（`pipe <命令>`） | 人 / 机器都能用的**稳定契约**：参数 / 输出 / 退出码 / `--json` |
| **skill**（本目录） | ★ **只有**「怎么用才不出错」这层**操作知识**：顺序、前置检查、常见错、该看哪个产物 |
| **不许进 skill** | 任何**判据本身**、任何**业务逻辑**、任何**只能在这一个 harness 里成立**的东西 |

### 反例（放错会怎样）

1. **把一条判据塞进 skill** ⇒ 判据只在那个 harness 里成立，**换 harness 就没了**；而且库里、门里、skill 里各留一份，必漂。判据的唯一落点 = 库 / 门。
2. **把一条操作知识留在库里** ⇒ 库被迫知道交互顺序，于是「换个前端照样成立」这条判据破了。
3. **把 harness 胶水塞进核心库 / CLI** ⇒ 换 harness 要改库。
4. **把 skill 当判据真源** ⇒ 删掉 `skills/` 后框架判据缺失 ⇒ 本层自检失败。

**一句话分界**：**判据 → 库 / 门；怎么用 → skill；换个 harness 要改的 → 只许集中在 `GLUE-harness.md`。**

## §2 三层结构（Agent Skills 规范）

一个技能 = 一个目录，三层按需加载：

| 层 | 是什么 | 本仓约定 |
|---|---|---|
| ① 元数据 | frontmatter 的 `name` + `description` | `name` = 目录名；`description` 写「做什么 + 什么时候用」（触发靠它） |
| ② 正文 | `SKILL.md` | **≤120 行**；六节骨架 + 自查；只写流程 |
| ③ 参考 | `references/*.md` | 长表（门清单、落地参数、批次围栏、状态机）按需加载；正文给**相对链接、只深一层** |

技能目录里两份：

- `SKILL.md` = **机器执行版**（顺序 / 前置检查 / 真命令 / 怎么读结果 / 常见错与处置 / 自查）。
- `NOTES.md` = **人类理解版**（这一层在防哪类错误 / 失败过什么（带读数）/ 脚本接口与以后怎么改）。
  它不是判据的第二份抄写 —— 判据仍在库与门里，它只讲来历与接口。

### ★ 换仓只用换一份：`references/repo-bindings.md`（2026-11-08 起）

**问题**：这套技能原来只对 `program/engineering` 有效 —— 入口路径、锁文件名、`TF_*` 环境变量、
本仓日期读数、复盘证据链，全写在 `SKILL.md` 正文里。换个仓，正文整页作废，agent 只能照抄就撞墙。

**约定**（按 `docs/reference/agent-skills-spec.md` §8「稳定的写死、随环境变的留成参数」与 §9 第 ⑤ 条）：

| 放哪 | 放什么 | 判据 |
|---|---|---|
| `SKILL.md` | **换仓不变**：动作顺序、判据入口（去哪个工具看）、读判决的方法、常见误读 | 换个仓，这一页**一个字都不用改** |
| `references/repo-bindings.md` | **这个仓长什么样**：入口路径、命令档位、锁与租约、环境变量、超时秒数、权威文档指针、本仓现算读数、历史证据链 | 换仓只改这一份 |
| `references/<主题>.md` | 某一类动作的长表（落地八步、输出读法、分派页…） | 与仓无关，可复用 |

**硬规矩**：

1. `SKILL.md` 里**不许**出现具体的 `gates/…` / `tools/…` 路径、`TF_*` 变量名、卡号、日期读数、
   复盘文件名 —— 这些一律进 `repo-bindings.md`。命令块里用 `<门禁入口>` 这类占位，真路径给相对链接。
2. `repo-bindings.md` 里每条读数都要**带日期**、并写清是哪条命令算出来的（数字会漂，口径不能漂）。
3. 引用**只深一层**：`SKILL.md` → `references/xxx.md`，别写「见 references/a.md 里的 b.md」。
4. 判据侧**不放松**：`SKILL.md` 仍要过 `skills/nails/check_skills.py` 四条（≤120 行 / 流程级小节 ≤3 /
   「怎么读结果」每条指向真脚本 / `NOTES.md` 三节）。下沉之后这些约束反而更容易满足。
5. 每个技能在自己 `NOTES.md` 里写一节「为什么分两页」，把搬走了什么、踩了什么坑记下来（下次别再犯）。

**已完成**：九个技能全部按这个形状改过（`pipe-gate` 是样板：`SKILL.md` 87 行 + `repo-bindings.md` 97 行）。

规范离线副本：`docs/reference/agent-skills-spec.md`；改技能时逐条过的自检表：
`skills/softeng-manage/references/spec-checklist.md`。

## §3 skills 清单（9 个）

| skill | 覆盖的动作 | 本仓真命令 | references |
|---|---|---|---|
| `softeng-manage` | **总入口**：六段路由 + 六条铁律 | 只路由（细节见右列技能） | `repo-bindings.md` · `mapping.md` · `commands.md` · `spec-checklist.md` · `doc-layers.md` · `asset-layers.md` · `grill-me.md` |
| `pipe-card` | 开卡 / 派活 / 申报 | `tools/wb_dispatch.py` · `tools/wb_task.py` · `tools/wb_stage_card.py` | `repo-bindings.md` · `dispatch.md` |
| `pipe-gate` | 跑门并读懂结果 | `scripts/run_gates.py` + `tools/wb_verify.py` | `repo-bindings.md` · `output.md` |
| `pipe-land` | 集成与落地（八步链） | `tools/wb_land.py` · `tools/wb_verify.py` | `repo-bindings.md` · `land-steps.md` |
| `pipe-workbench` | 工作台四件套（读数 / 巡检 / 注入 / 面板）+ 收工看守 | `tools/pipeline_view.py` · `wb_daily.py` · `workbench_bridge.py` · `wb_dash.py` · `tools/wb_watch.py` | `repo-bindings.md` · `tools.md` |
| `pipe-forensics` | 出事了从证据里查 | `tools/wb_verify.py` · `wb_diag.py` · `wb_reconcile.py` | `repo-bindings.md` · `evidence-map.md` |
| `pipe-new` | 在本仓内从零起一条工作链 | `tools/wb_plan.py` · `tools/wb_dispatch.py` · `tools/wb_land.py` | `repo-bindings.md` · `first-landing.md` |
| `pipe-init` | 铺框架骨架（框架层，唯一还用 CLI 的） | 框架 CLI 的 `init` 子命令（见技能正文） | `repo-bindings.md` · `scaffold.md` |
| `pipe-takeover` | 接管旧项目：勘察定类 → 映射 → 接链 | `tools/wb_takeover.py` | `repo-bindings.md` · `classify.md` · `mapping.md` · `limits.md` · `attach-to-chain.md` |

`spec-grill` 不再单独立技能（卡 A305 的决定）：grill-me 是意图 / 规格 / 契约三层**共用**的
决策方法，落成参考 `skills/softeng-manage/references/grill-me.md`，由 `softeng-manage` 按需加载；
三层各有一句指引写在 `skills/softeng-manage/references/doc-layers.md` 里 ——
别按旧占位顺手补一个 `spec-grill` 目录出来。

除 `softeng-manage`（路由）之外，其余八个是**动作技能**（一种操作一份）：
它们不重复动作细节以外的判据，只给「这件事该走哪个工具 / 哪条铁律不能破 / 本仓命令与技能文档的差异」。
装法相同，注册脚本会把它们一起挂到工人技能根。

## §4 ★ 换 harness 要改什么（清单式）

**通用的（一个字不改）：** 每个 `SKILL.md` 的正文（六节 + 自查）、本 README 的 §1 分工判据、
§5 版本对齐。只要命令契约不变，这些就是**跨 harness** 的。

**每个 harness 的胶水（★ 全部集中在 `GLUE-harness.md`，别处不许出现）：**

- **G1 注册方式** —— 把 `skills/` 目录指给该 harness 的 skill 扫描根 / 注册接口。
- **G2 目录约定** —— skill 放哪个目录、`SKILL.md` 的文件名与目录束层级。
- **G3 frontmatter 字段名** —— 哪些键必填、哪些键会被拒。
- **G4 触发机制** —— 自动加载 vs `/点名`，以及「描述进不进上下文」。
- **G5 调用入口** —— CLI / 工具怎么被 harness 调起。
- **G6 沙箱 / 权限** —— 跑命令需要的权限档与工作目录。

★ 除这六条外，**任何 harness 特有的路径 / 工具名都不许进 skill 正文**。

## §5 版本对齐

- **框架版本**：`framework/pyproject.toml` 里的版本。
- **skills 版本**：跟框架**同版** —— 本目录随框架版本一起动。
- **契约（两条，别混）**：本仓工作链的命令名必须在 `tools/` / `scripts/` 里真实存在（钉子②第三条兜脚本路径）；
  框架层的命令名（只有 `pipe-init` 还在用）必须能在**同版** `pipe --help` 里找到（钉子①机器判）。
- **兼容规则**：CLI **加**命令 / 加字段 = 次版本；**删**命令 / **改**命令名 / 改退出码表 = 主版本
  （skills 必须同版改，否则钉子①红）。

## §6 钉子（怎么自证）

两道钉子都在 `nails/`，都**只读**、可用退出码判读：

- 钉子①（`check_commands.py`）**三态**：`0` 绿 / `1` 红 / **`3` 判不出**（卡 E49 —— 找不到同版 CLI、解释器跑不了命令面）。
  `3` **不等于红，也不等于绿**：如实写「判不出」，别改判据去凑绿。
- 钉子②（`check_skills.py`）**两态**：`0` 绿 / `1` 红。

```bash
python -X utf8 skills/nails/check_commands.py    # ① 引用的命令名，都能在 CLI 帮助里找到
python -X utf8 skills/nails/check_skills.py      # ② 格式 + 卡 209 四条加严
npx -y skills-ref@latest validate ./skills/<名>  # ③ 官方校验器
```

- 钉子①：扫 `skills/**/SKILL.md` 里代码段 / 围栏 / 标题中的 `pipe <命令>`，与 CLI 的 `--help` 对账。
- 钉子②：frontmatter / `name` kebab 且等于目录名 / 六节齐；
  **卡 209（`T-G318`）加严四条**（口径只写在 `check_skills.py` 的 docstring 里）：
  1. **长度上限** ≤ **120 行**；
  2. **流程级小节**（六个固定小节之外的 `##` / `###` 标题）≤ **3**；
  3. ★★ **验收必须指向脚本**：「怎么读结果」每条口径都要有一个**真实存在**的脚本路径
     （允许的根：`tools/` · `skills/` · `framework/cli/`）；
  4. **人类理解版**：每个技能目录必须有 `NOTES.md` 且含三节。

## §7 边界（如实写）

- skills **只有操作知识**；**框架能不能用，不由 skills 证明** —— 那是框架自己门禁的事。
- 命令面里有几条在**本仓主路径上走不到实现**：框架 CLI 的 `gate` / `land` / `claim` / `ledger check` /
  `trace seal` 都要求根级 `pipeline.toml`，本仓没有 ⇒ 实测直接报「配置不存在」（退 `5`，前置条件缺失）。
  所以各技能的正文一律走 `tools/wb_*.py`；框架 CLI 只保留在 `pipe-init`（它自带模板）。
- 本层**不绑某个 harness**：harness 特有值只在 `GLUE-harness.md`。
- ★ **两道钉子仍没有消费端**（2026-10-28 现读 `gates/defs/`）：`skills/nails/*` 不在门表里 ⇒
  **加严了判据，但没接线**。门表里管技能的只有 `skills_claims`（= `tools/check_skills_claims.py --check --mode report`，
  核的是「技能里引用的 `tools/` 脚本与它的 `--flag` ↔ `tools/` 源码」，**不是** nails 那两条）—— 两把尺子，别互相顶班。
- ★ **正文行数别抄表**（会漂）：现算用 `wc -l skills/*/SKILL.md`；上限判据只有 `skills/nails/check_skills.py`
  一处（`MAX_LINES = 120`）。卡 A293（2026-10-19）那次读数是 7 份、70~91 行 —— 那是当时的读数，
  现在已是 9 份，别当常量引用。
  卡 A304 之后是 **9 份**（新增 `pipe-new`，`pipe-takeover` 补了「接链六步」一节），当前行数以
  `python -X utf8 skills/nails/check_skills.py` 的输出为准。
