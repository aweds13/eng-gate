# pipe-new 的来龙去脉

## 这一层在防哪类错误

- **把两条路当成一条**：`pipe-init` 铺的是「自带 `pipeline.toml` + `gates.d/` 门表 + 钉子的独立骨架」，
  跑在别的目录；本仓工作链是 `wb_*` + 根 `scripts/run_gates.py`，根写死在本仓。混着用就会出现
  「骨架铺了、门表也在，但 `wb_land` 找不到 `docs/traceability.toml`」这种半条链。
- **跳步**：目录没提交就建卡、卡没写就建树、树没建就派活、卡规格没进索引就落地。
  代价从低到高，最后一步要跑几分钟全量门禁才发现白跑。
- **拿干跑当执行**：`wb_plan worktrees` 与 `wb_dispatch` 默认都只打印，不加 `--execute` 什么都没发生。
- **替仓外的仓落地**（卡 A326 之后口径已变）：`tools/` 现在分**工具根**与**数据根** ——
  门表跟工具走、台账与门禁产物跟数据根走（`PIPE_DATA` > 当前目录像数据根 > 工具根）。
  同一份 `tools/` 服务别的仓时，设 `PIPE_DATA` 指向那个仓即可；不设时两根同值、行为不变。

## 失败过什么（带读数）

- 本卡的 `skills/pipe-new/SKILL.md` 先写完、`NOTES.md` 后写，`python -X utf8 skills/nails/check_skills.py`
  当即判红，原文：`- skills/pipe-new/SKILL.md: 目录下缺 NOTES.md（人类理解版）`。
  即「SKILL.md 与 NOTES.md 必须同批出现」，不能留到下一步 —— 这就是这一节存在的原因。
- `grep -rl "infra/pool" tools` 在卡树里读到 **8 个源码文件、20 处命中**；在主树同一命令读到 **15 个文件**，
  多出的 7 个是 `__pycache__/*.pyc`。同一句话在不同树上读数是 15 或 8，写文档一律报**源码口径**并注明取证命令。
- `python -X utf8 tools/wb_plan.py worktrees` 只打印建树命令，末尾 `[dry ] 默认不执行；真要建树加 --execute（基点 64d9d02）`。
  第一次看容易以为树已经建好；`git worktree list` 才是真读数。
- `python -X utf8 tools/wb_plan.py check` 的通过行是 `[OK ] backlog 校验通过：175 张卡，无冲突（基点 64d9d02）`，
  卡数会随队列增长；README 与 NOTES 里不要写死卡数，只写「最后一行应是 backlog 校验通过」。
- 落地链里三条早退是**从代码里读出来的真值**（不是踩出来的）：退 5 主干保护在快照之前；
  退 4 卡规格索引钉子在**全量门禁之前**（脚本自己说「省下 9 分钟」）；退 3 卡树 HEAD 不是主树 HEAD 祖先。
  原文见 `skills/pipe-new/references/first-landing.md` 的三节。

## 脚本接口与以后怎么改

- `tools/wb_plan.py`：`ROOT = Path(__file__).resolve().parent.parent`，**没有** `--root`；
  子命令 `check` / `plan` / `stats` / `worktrees` / `dispatch` / `merge`；`worktrees` 与 `dispatch` 的
  干跑/执行由 `--execute` 分。以后若加 `--root`，本技能的「仓外止步」一节要同步改 ——
  它现在是**按实现**写的，不是按意图写的。
- `tools/pool/landing.py`：`--card` 与 `--batch` 恰好一个（否则退 6）；`--tree` / `--task` / `--title`
  必填；`--allow` 是提交白名单，也是主干保护的豁免表。三步早退的码位固定为 5 / 4 / 3。
  以后加早退条，把新码位补进 `references/first-landing.md` 的「三个最常见失败」，不要在 SKILL.md 正文里
  重抄判据。
- `tools/pool/projects.py`：项目索引从祖先逐级找 `infra/pool/projects.toml`，可用 `TF_PROJECTS_TOML` 覆盖；
  三条硬判据（`root` 存在 / 不重根 / `tree_prefixes` 非空）在库里，不在技能里。
- `scripts/run_gates.py`：门表**硬编码在脚本**里（`INFO_GATES` 与 main 里的元组），改门表要改脚本，
  不是加 `gates.d/*.toml`。这是「两套路」在实现层最容易被误认的地方。
- 本技能与 `pipe-init` 的分界只有一句：**目标目录里要不要一份自己的 `pipeline.toml`**。
  要 —— 走 `pipe-init`；不要 —— 走本技能。
