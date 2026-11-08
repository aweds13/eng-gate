# pipe-new 的来龙去脉

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在队列工具与落地链里。删掉整个 `skills/`，框架仍要可用。
>
> 三层：元数据 → 正文（六节 + 起始六步 + 自查，≤120 行）→ `references/`。
> 本仓的路径 / 字段名 / 树前缀 / 读数在 [本仓绑定](references/repo-bindings.md)；首笔落地细节在 [首笔落地](references/first-landing.md)。

## 这一层在防哪类错误

- **把两条路当成一条**：`pipe-init` 铺的是「自带配置文件 + 门表 + 钉子的独立骨架」，跑在别的目录；
  本仓工作链是 `wb_*` + 根目录那套门表，数据根在本仓。混着用就会出现
  「骨架铺了、门表也在，但落地链找不到台账」这种半条链。
- **跳步**：目录没提交就建卡、卡没写就建树、树没建就派活、卡规格没进索引就落地。
  代价从低到高，最后一步要跑几分钟全量门禁才发现白跑。
- **拿干跑当执行**：建树与派活默认都只打印，不加 `--execute` 什么都没发生。
- **替仓外的仓落地**（卡 A326 之后口径已变）：`tools/` 现在分**工具根**与**数据根** ——
  代码跟工具根走、台账与门禁产物跟数据根走（`PIPE_DATA` > 当前目录像数据根 > 工具根）。
  同一份 `tools/` 服务别的仓时，设 `PIPE_DATA` 指向那个仓即可；不设时两根同值、行为不变。
  但「一条命令替别仓落地」仍然不成立 —— 那是另一次部署。

## ★ 为什么分「SKILL.md / references/repo-bindings.md」两页（2026-11-08）

**问题**：这一页原来把本仓的路径、字段名、树前缀、日期读数、复盘证据全写在正文里。换一个仓整页作废，
agent 只能照抄就撞墙 —— 用户原话：「现在它们只针对 engineer 这个仓库，是不够的」，
「特定仓库表述下降到原来更下一层的 reference」。

**判据**（`docs/reference/agent-skills-spec.md` §5 三层渐进加载 / §6 引用只深一层 /
§8「稳定的写死、随环境变的留成参数」/ §9 第 ⑤ 条「长表下沉 references」）：

| 放哪 | 放什么 | 判据 |
|---|---|---|
| `SKILL.md` | 动作顺序、前置检查、读判决的方法、常见误读 | 换一个仓，**一个字都不用改** |
| `references/repo-bindings.md` | 队列文件叫什么、卡规格目录、树前缀与分支名、基点、入口路径、本仓读数、历史证据 | 换仓**只改这一份** |

**搬走了什么**（都留在 `repo-bindings.md` 里，行号是搬走前 `SKILL.md` 的行号）：`:29-30` 仓外止步的
实现理由、`:36` 仓内判定、`:39` 队列文件与卡规格目录、`:50-51` 九个字段名、`:54` 卡规格路径、
`:62` 派活命令里的规格路径、`:88-93` 六步表里的路径与分支名、`:118-119` 判据文件清单。

**判据侧不放松**：仍要过 `skills/nails/check_skills.py` 四条（≤120 行 / 流程级小节 ≤3 /
「怎么读结果」每条指向真脚本 / `NOTES.md` 三节）。这一页现在 **115 行**、流程级小节 3 条（`## 0. 先问再写` /
`## 起链六步` / `## 自查`，正好卡在上限 —— 再加一节就红）。

## 失败过什么（带读数）

- 本卡的 `skills/pipe-new/SKILL.md` 先写完、`NOTES.md` 后写，`python -X utf8 skills/nails/check_skills.py`
  当即判红，原文：`- skills/pipe-new/SKILL.md: 目录下缺 NOTES.md（人类理解版）`。
  即「SKILL.md 与 NOTES.md 必须同批出现」，不能留到下一步 —— 这就是这一节存在的原因。
- `grep -rl "infra/pool" tools` 在卡树里读到 **8 个源码文件、20 处命中**；在主树同一命令读到 **15 个文件**，
  多出的 7 个是 `__pycache__/*.pyc`。同一句话在不同树上读数是 15 或 8，写文档一律报**源码口径**并注明取证命令。
- `python -X utf8 tools/wb_plan.py worktrees` 只打印建树命令，末尾
  `[dry ] 默认不执行；真要建树加 --execute（基点 38522420）`。
  第一次看容易以为树已经建好；`git worktree list` 才是真读数。
- `python -X utf8 tools/wb_plan.py check` 的通过行是
  `[OK ] backlog 校验通过：339 张卡，无冲突（基点 38522420）`（2026-11-08 现读；原来是 175 张 / 64d9d02）。
  卡数与基点会随队列增长 —— 本页与 `SKILL.md` **都不写死**，只写「末行应是 backlog 校验通过」。
- 落地链里三条早退是**从代码里读出来的真值**（不是踩出来的）：退 5 主干保护在快照之前；
  退 4 卡规格索引钉子在**全量门禁之前**（脚本自己说「省下 9 分钟」）；退 3 卡树 HEAD 不是主树 HEAD 祖先。
  原文见 [首笔落地](references/first-landing.md) 的三节。

## 脚本接口与以后怎么改

- `tools/wb_plan.py`：工具根 `_FILE_ROOT = Path(__file__).resolve().parents[1]`，数据根
  `ROOT = pipe_root.data_root()`（卡 A326）；**有** `--root`（服务哪棵树，走 `tools/_repo.py` 解析链），
  子命令 `check` / `plan` / `stats` / `worktrees` / `dispatch` / `merge`；`worktrees` 与 `dispatch` 的
  干跑/执行由 `--execute` 分。旧的「没有 `--root`」已不成立 —— 若以后再改根的解析口径，
  本页与 `repo-bindings.md` 的「单数据根」那节要同步改。
- `tools/pool/landing.py`：`--card` 与 `--batch` 恰好一个（否则退 6）；`--tree` / `--task` / `--title` /
  `--evidence` / `--allow` 必填（`--title` 不给时从队列那张卡取）；`--allow` 是提交白名单，也是主干保护的豁免表。
  三步早退的码位固定为 5 / 4 / 3。以后加早退条，把新码位补进 [首笔落地](references/first-landing.md) 的
  「三个最常见失败」，不要在 `SKILL.md` 正文里重抄判据。
- `tools/pool/projects.py`：项目索引从祖先逐级找 `infra/pool/projects.toml`，找不到**抛错不猜**，
  `TF_PROJECTS_TOML` 可覆盖；三条硬判据（`root` 存在 / 不重根 / `tree_prefixes` 非空）在库里，不在技能里。
- `scripts/run_gates.py`：门表**已不在这个脚本里**（卡 A321）。定义层在 `gates/defs/`
  （`lang_python.py` / `contract.py` / `product_timeflow.py` / `domains.py`），脚本只做装配
  （`COMMON` / `GATE_PROFILES` / `FAST`）。改门表去 `gates/defs/`，这是「两套路」在实现层最容易被误认的地方。
- 本技能与 `pipe-init` 的分界只有一句：**目标目录里要不要一份自己的 `pipeline.toml`**。
  要 —— 走 `pipe-init`；不要 —— 走本技能。
