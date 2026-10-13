# pipe-init —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在库里（见下「脚本接口」）。删掉整个 `skills/`，框架仍完整可用。

## 这一层在防哪类错误

防「**铺骨架**」这一下把已经存在的项目文件**当空地刷掉**。`pipe init` 是给空目录起点的，
不是「把项目重置成模板」—— 所以它不合并、不覆盖：目标非空就退 `5`，要覆盖必须显式 `--force`，
而 `--force` 又**只许在仓内**（仓外退 `4`）。这一层把「什么时候该铺、什么时候会踩雷」讲清，
免得 agent 一上手就 `--force` 把自己改过的东西盖掉。

## 失败过什么（带读数）

- **卡 180（`T-G280`）落这层时的「红→绿」**：造钉子时故意写错一个命令名 `pipe initt` ⇒
  钉子①红，原样点名到行：`skills/pipe-init/SKILL.md:40 引用了不存在的命令 pipe initt`
  （读数出处：`docs/traceability.toml` 的 `T-G280` 条目「诚实缺口④」）。
- **卡 209（`T-G318`）加严时的第一趟红**：`python -X utf8 skills/nails/check_skills.py` ⇒
  rc=1，本文件所在的 `skills/pipe-init/SKILL.md`「怎么读结果」**5 条口径一条都没指向脚本**。
  ⇒ 教训：**只要判据不查它，skill 自己不会长出自检**。
- **同一个坑的上一层**：两道钉子（`check_commands.py` / `check_skills.py`）落库当天
  **没有任何消费端**（不在 `scripts/run_gates.py` 门表里，也没脚本调它们，`T-G280` 缺口②）——
  「判据生成了但没人读」。本卡只把判据加严，**接线仍未做**（如实记，别把绿读成「已进闸」）。

## 脚本接口与以后怎么改

- 这一层的验收程序：`framework/cli/main.py`（`init` 子命令）。要机器读的结论就加 `--json`。
- 骨架的**判据**（铺哪些文件、什么算幂等）在 `framework/src/framework/scaffold.py`；模板在
  `framework/templates/minimal/`。改「铺什么」去那两处，**别改本 skill**。
- 换 harness 要改的（注册方式 / frontmatter 字段名 / 调用入口）只许集中在 `skills/GLUE-harness.md`；
  本文件与 `SKILL.md` **一个字不该为此而改**。
