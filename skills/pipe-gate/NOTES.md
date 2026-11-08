# pipe-gate —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在门表与库里。删掉整个 `skills/`，框架仍完整可用。
>
> 三层：元数据（frontmatter 的 `name` / `description`）→ 正文（六节 + 自查，≤120 行）→
> `references/`（按需加载）。本技能的长表在 [输出读法](references/output.md) 与
> [本仓绑定](references/repo-bindings.md)（相对链接，只深一层）。

## 这一层在防哪类错误

防「**把非绿读成绿**」。门禁的判决是三值，最要命的两种误读是：

1. 把「判不了」（空集 / 没收集到样例）当成通过；
2. 把运行状态「未跑」（依赖缺失，根本没跑）当成判决。

还有第三类，是本仓真踩过的：**快档全绿就以为可以提交** —— 它明确**不落盘**、只覆盖
「改一行就能犯」那几类。这一层把「第一行看整体结论、每道门看那一行、快档不是提交闸」
固化成动作。

## ★ 为什么分「SKILL.md / references/repo-bindings.md」两页

2026-11-08（用户 m91323/m91324）提出：这套技能只对 `program/engineering` 有效，换个仓就不能用；
要求「特定仓库表述下降到更下一层的 reference，基于 agent 文档和 skills 编写的最佳规范」。

按 `docs/reference/agent-skills-spec.md` 的口径落成两页：

- **`SKILL.md`** 只留**换仓不变的东西**：动作顺序、判据入口、读判决的方法、常见误读。
  里面不再出现本仓的路径 / 环境变量 / 锁名 / 日期读数 / 历史复盘文件名。
- **`references/repo-bindings.md`** 放**这个仓长什么样**：入口路径、档位命令、锁文件与租约、
  逐门超时秒数、跨机共享口径指哪份文档、本仓现读门数、复盘缺口证据链。
- 换仓用这套技能 ⇒ **只换 repo-bindings 一份**，`SKILL.md` 一字不动。

这与规范 §5（渐进加载第三层）、§6（引用只深一层）、§8（稳定写死 / 随环境变留参数）、
§9 第 ⑤ 条（长表下沉 references）是同一件事。判据侧没有放松：`SKILL.md` 仍要过
`skills/nails/check_skills.py` 四条（≤120 行 / 流程 ≤3 / 怎么读结果每条指向真脚本 / NOTES 三节）。

## 失败过什么（带读数）

- **卡 180（`T-G280`）**：三值判决的误读族是这层立起来的动机。
- **卡 209（`T-G318`）**：加严第一趟 `python -X utf8 skills/nails/check_skills.py` ⇒ rc=1，
  `skills/pipe-gate/SKILL.md`「怎么读结果」**6 条口径一条都没指向脚本** —— 讲得对，但没法机器重跑。
- **卡 A293 · 第一趟红**：改完正文跑钉子 ⇒ rc=1，两条口径没指向真脚本。真因**不是**漏写，
  而是指到了框架层的 `scripts/run_gates.py` —— 钉子 C 的允许根只有 `tools/` · `skills/` · `framework/cli/`。
  处置：改指 `tools/wb_verify.py`（一屏五块）与 `tools/pipeline_view.py`（每道门一行）。改后 70 行、绿。
- **本轮的实测现状**：旧稿 61 行里 `wb_` / `worktree` 出现 **0 次**，命令全是框架层的 `gate`（薄 CLI 入口）
  —— 而本仓根**没有 `pipeline.toml`**，那条命令在主路径上跑不了。
  新稿改成 `scripts/run_gates.py` 跑门 + `tools/wb_*.py` 读结论（实测快档 8 道全绿，最慢一道 4.96s）。
- **2026-11-08 泛用化第一趟**：把 `## 复盘缺口` 整节（8 条、每条挂 2–3 份复盘）搬进
  `references/repo-bindings.md`，`SKILL.md` 从 118 行降到 87 行；搬的时候顺手把「红门读 `detail`」
  那条口径补上脚本指针 —— 否则钉子 C 立刻红（实测：第一版就红在这一条）。

## 脚本接口与以后怎么改

- 跑门：本仓是 `scripts/run_gates.py`（快档 / 次档 / 全量 / `--no-reuse` / `--affected` / `--seal`）。
- 读结论：`tools/wb_verify.py --tree .`（一屏五块）、`tools/pipeline_view.py --json`（每道门一行）。
- **判据**（三值、空集绝不绿灯、复用、档位覆盖）在门禁入口与门表。改判据去那里，**别改本技能**。
- 加一门 / 改档位 ⇒ `references/repo-bindings.md` 的档位表要跟着对，但**别把门数写死**（门数现算）。
- **换一个仓** ⇒ 只改 `references/repo-bindings.md`（入口路径、锁、环境变量、文档指针）。
  如果那个仓的判据形状不同（比如没有「三值判决」），再改 `SKILL.md` 的读法 —— 但先把差异写进
  repo-bindings，别把新仓的路径塞回 SKILL.md。
- 金丝雀自检（门还活不活着）是**另一件**事，别拿它当跑门。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
