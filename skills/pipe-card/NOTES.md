# pipe-card —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在库里（见下「脚本接口」）。删掉整个 `skills/`，框架仍完整可用。

## 这一层在防哪类错误

防「**没证据就算完成**」和「**域对不上还申报**」。完成申报（`claim`）是集成发布的输入之一：
`success` 不带 `--evidence` 就不叫申报；`failed` 会**显式挡住集成**（不是异常）；
`--domain` 要按**实际改动的文件路径**给，因为域检查是拿卡树实际改动去对权威域的。
这一层把「什么时候能申报、申报要带什么」讲清，免得 agent 拿「签了名」冒充「做完了」。

## 失败过什么（带读数）

- **卡 180（`T-G280`）的「诚实缺口①」**：工人**正常收工**（`finished=true`、`errors=[]`、293s、
  56 事件、`tokens total=37245`），但**没走最后一步交申请** ⇒ 任务栅栏停在 `collecting 0/1`。
  ⇒ 真因在**收工侧漏最后一步**，不是登记侧 —— 这条正是「申报 = 一等动作」的由来。
- **卡 209（`T-G318`）加严时的第一趟红**：`python -X utf8 skills/nails/check_skills.py` ⇒ rc=1，
  `skills/pipe-card/SKILL.md`「怎么读结果」**4 条口径一条都没指向脚本**。
- **本层有个已知的「薄壳」事实**：`claim`（以及 `land`）在本阶段**签名在、行为未建**，调用即退 `5`。
  这一条写进了 `SKILL.md` 与 `skills/README.md §6` —— 别把「退 5」读成用法错。

## 脚本接口与以后怎么改

- 这一层的验收程序：`framework/cli/main.py`（`card new` 与 `claim` 子命令，加 `--json` 给机器读）。
- **域检查**的判据在 `framework/src/framework/claim.py`；卡模板在 `[cards].spec_template` 指的那份。
  改「域怎么判、卡长什么样」去那两处，**别改本 skill**。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
