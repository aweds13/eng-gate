# pipe-card —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在 `tools/pool/` 里。删掉整个 `skills/`，框架仍完整可用。
>
> 三层：元数据 → 正文（六节 + 派活分工 + 自查，≤120 行）→ `references/`。
> 本技能的长表在 [派活分工](references/dispatch.md) 与 [本仓绑定](references/repo-bindings.md)（相对链接，只深一层）。

## 这一层在防哪类错误

防「**没证据就算完成**」和「**域对不上还申报**」。

- 完成申报是收口的输入之一：`success` 不带 `--evidence` 就不叫申报；`failed` 会**显式挡住收口**。
- `--files` 要按**实际改动**给：域检查是拿卡规格的 `files` 去对工人真正碰的文件。
- 另一类（2026-10-15 实测）：**把长跑派给工人**，工人 harness 不支持后台命令，于是在卡里空转，
  日志里只剩同一条被拒的命令。所以派活前要问「这张卡是秒级能跑完的吗」。

## ★ 为什么分「SKILL.md / references/repo-bindings.md」两页

2026-11-08（用户提出）：「你顺便把软工的那些技能的泛用性提升一下，现在它们只针对 engineer 这个仓库，
是不够的」；「建议是特定仓库表述下降到原来更下一层的 reference，基于 agent 文档和 skills 编写的最佳规范」。

按 `docs/reference/agent-skills-spec.md` 的口径落成两页：

- **`SKILL.md`** 只留**换仓不变的东西**：卡的四件套（规格 / 队列条目 / 树提交 / 申报）、开卡与派活的顺序、
  读结果的方法、常见误读。里面不再出现本仓的台账文件名 / 目录 / 卡号 / `T-AG…` 样例 / 模型清单 / 看守产物路径。
- **`references/repo-bindings.md`** 放**这个仓长什么样**：立卡入口与退码、队列字段真值、派活器与看守的
  产物路径与退出码、模型批准集的三条真源、会话闸、攒批栅栏、复盘缺口证据链。
- 换仓用这套技能 ⇒ **只换 repo-bindings 一份**，`SKILL.md` 一字不动。

这与规范 §5（渐进加载第三层）、§6（引用只深一层）、§8（稳定写死 / 随环境变留参数）、
§9 第 ⑤ 条（长表下沉 references）是同一件事。判据侧没有放松：`SKILL.md` 仍要过
`skills/nails/check_skills.py` 四条（≤120 行 / 流程 ≤3 / 怎么读结果每条指向真脚本 / NOTES 三节）。

搬走时顺手修掉的陈旧陈述：`risk` 的枚举 **`medium` → `mid`**（真源 `tools/wb_card.py:68` 的 choices、
`tools/pool/ledger.py:276`/`:422` 的默认值；2026-11-08 实测队列 `mid` 200 条、`medium` 0 条）。

## 失败过什么（带读数）

- **卡 180（`T-G280`）「诚实缺口①」**：工人正常收工（`finished=true`、`errors=[]`、293s、
  56 事件、`tokens total=37245`），但**没走最后一步交申报** ⇒ 栅栏停在 `collecting 0/1`。
  真因在收工侧漏最后一步，不是登记侧 —— 这条正是「申报 = 一等动作」的由来。
- **卡 209（`T-G318`）加严第一趟**：`check_skills.py` ⇒ rc=1，本文件对应的
  `skills/pipe-card/SKILL.md`「怎么读结果」**4 条口径一条都没指向脚本**。
- **卡 A293（本轮）的实测现状**：旧稿 68 行里 `wb_` / `worktree` 只出现 **1 次**（还是叙述），
  正文全是 `pipe card new` / `pipe claim`。实测框架 CLI 的 `claim` 在本仓直接报
  「配置不存在：…\pipeline.toml」—— 主路径根本走不到它的实现。
  新稿改成真链路：`git worktree add` → `wb_dispatch.py` → `wb_task.py claim` → `wb_stage_card.py`，
  `wb_` / 树相关出现 **14 次**，91 行、绿。

- **2026-11-02 20:36 台账被 reset 扫掉**：另一会话落地失败后手工在主树跑 reset --hard，
  把主控刚写进台账的 F13 条目一起扫掉，只能重做立卡。同一天卡 E81 把立卡收成生产代码
  （`tools/wb_card.py add` → `tools/pool/ledger.py`：锁 + 块级幂等 + 原子写）；旧的
  `gates/diag/_add_card.py` 住在 gitignore 里、按全文子串判「已在」，已废。

## 脚本接口与以后怎么改

- 派活：`tools/wb_dispatch.py`（默认 dry-run；`--detach` 不等、`--execute` 真派；`--status` 看现场）。
- 申报：`tools/wb_task.py register` / `claim` / `status`（成员号 = 卡号；`--claim success` 必带 `--evidence`）。
- 文书：`tools/wb_stage_card.py`（台账条目 + changelog + 交接 CHECKPOINT 三段）。
- **判据**：域检查与收口在 `tools/pool/task.py`、`tools/pool/landing.py`；改它们去库里，**别改本技能**。
- 卡规格的段落骨架在 `tools/pool/stage_card.py`；改骨架要同改 `references/dispatch.md` 的模板。
- **换一个仓** ⇒ 只改 `references/repo-bindings.md`（立卡入口、队列字段、派活器与看守产物、模型名单、闸）。
  派活器 / 申报器形状不同才改 `SKILL.md` 的读法，先把差异写进 repo-bindings。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
