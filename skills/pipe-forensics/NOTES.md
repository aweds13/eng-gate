# pipe-forensics —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在库里（见下「脚本接口」）。删掉整个 `skills/`，框架仍完整可用。

## 这一层在防哪类错误

防「**靠回忆复现，不靠落盘证据**」。出事了（门红 / 判决说不清 / 复现不了）时，唯一可信的是
**已经落盘的产物**：门结论（`[paths].gates_state`）、日志、证据目录、封存指纹。
这一层把「先看留痕，再看代码」的顺序固化，并且反复点两种最容易被读反的东西：
空集 `inconclusive`（补样例）≠ 依赖缺失 `not-run`（补依赖）；某门带 `[复用]` 是**读缓存**，不是
「现在重跑过」。还有一条防「查错对象」：要证明**门**还活着用的是 `doctor`（金丝雀自检），不是 `gate`。

## 失败过什么（带读数）

- **「复现不了」多半是结论属于另一棵树**：封存指纹含未跟踪文件（`staged_tree()` 走 `git add -A`
  到临时索引再 `write-tree`）—— 封存之后再新增文件，「提交树」就 ≠ 「封存树」。
  这是 `复盘/口径坑.md` 第 14 条，真踩过（想把新复盘塞进同一笔 ⇒ 只能改成后续一笔）。
- **「复用通过 ≠ 这道门现在是绿的」**：自己动过的那道门（或它的输入）**必须 `--no-reuse` 真跑**
  再提交，否则等于没验（`复盘/口径坑.md` 第 11 条，卡 094 实例）。
- **卡 209（`T-G318`）加严时的第一趟红**：`python -X utf8 skills/nails/check_skills.py` ⇒ rc=1，
  `skills/pipe-forensics/SKILL.md`「怎么读结果」**7 条口径一条都没指向脚本**。
- **本层有已知「薄壳」**：`ledger check` 与 `trace seal` 调用即退 `5`（未实现）——
  这**不是**「台账没问题」，是「这一层还没建」。

## 脚本接口与以后怎么改

- 这一层的验收程序：`framework/cli/main.py`（`gate` / `doctor` / `ledger check` / `trace seal`
  子命令，加 `--json` 给机器读；`ledger check --missing` 只回报失败条目）。
- 判决与「空集绝不绿灯」的**判据**在 `framework/src/framework/gates.py` 与 `framework/PIPELINE.md`；
  台账对账在 `framework/src/framework/ledger.py`；封存指纹在 `framework/src/framework/trace.py`。
  改读法去这几处，**别改本 skill**。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
