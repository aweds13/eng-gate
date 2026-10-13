# pipe-gate —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在库里（见下「脚本接口」）。删掉整个 `skills/`，框架仍完整可用。

## 这一层在防哪类错误

防「**把非绿读成绿**」。门禁的判决是**三值**（`pass` / `fail` / `inconclusive`），而不是两值；
最要命的两种误读是：① 把 `inconclusive`（判不了 —— 例如一条样例都没收集到）当成通过；
② 把运行状态 `not-run`（依赖缺失，根本没跑）当成判决。这一层把「第一行看整体判决、每道门看那一行」
的读法固化成动作，免得 agent 在上下文里随手把「没跑 / 判不了」读成「过了」。

## 失败过什么（带读数）

- **卡 180（`T-G280`）立这层的动机就是这里**：三值判决里 `inconclusive` 的误读族，记进了这层的
  硬要求；同一笔的「红→绿」读数（故意写错命令名 ⇒ 钉子①点名到行）出处见 `T-G280` 条目。
- **卡 209（`T-G318`）加严时的第一趟红**：`python -X utf8 skills/nails/check_skills.py` ⇒ rc=1，
  `skills/pipe-gate/SKILL.md`「怎么读结果」**6 条口径一条都没指向脚本** —— 讲得对，但**没法被机器重跑**。
- **读数口径本身也摔过**：`gates/last.json` 的「复用」在**顶层 `reused` 字典**里、不在每道门里
  （见 `复盘/口径坑.md` 第 1 条）—— 所以下面那条复核一律走 `framework/cli/main.py gate --json`，
  别自己扒 `last.json` 猜字段。

## 脚本接口与以后怎么改

- 这一层的验收程序：`framework/cli/main.py`（`gate` 子命令，加 `--json` 给机器读；`--only <门>` 只跑几道）。
- 判决的**判据**（三值、空集绝不绿灯、增量复用）在 `framework/src/framework/gates.py` 与
  `framework/PIPELINE.md`。改读法/退出码表去那两处，**别改本 skill**。
- `doctor`（金丝雀自检）是**另一件**：它查「门还活不活着」，不是查你的改动 —— 别拿它当 `gate`。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
