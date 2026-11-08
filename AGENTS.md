# AGENTS.md —— 工作区入口（`program/engineering`）

> 这个目录是 **`pipe` 框架**（工作项/门禁/台账/派活器）。本文件只做**路由**，
> 不重复各项目自己的规则。
>
> ★ 读者是**没有上下文的新窗口**。它只回答两件事：**这件事该读哪份**、**动手前必须先做什么**。
> 具体命令、读数、判据一律不抄进来（抄三份必漂）—— 指向下面那张表。

## 活在哪，先看哪

| 你要干的活 | 先读 |
|---|---|
| **OpenMAIC 二开**（`../OpenMAIC`） | `../OpenMAIC/AGENTS.md` —— 维护手册：改哪一层、文件地图、证据命令、坑；**当前状态**看它的 §0（现状）与 §8（未决项）<br>已量的结论看 `../OpenMAIC/复盘/已结案结论.md`。★ 原「新窗口交接卡」已于 2026-10-30 拆掉，状态进了那两节 |
| **找不到文档 / 不知道某份该不该读** | `docs/文档系统导航.md` —— 六份索引各管什么、按意图路由（改代码 / 查某张卡 / 门怎么判 / 规矩来历 / 发新功能）、哪些地方**不是权威** |
| **软件工程流程**（开卡 → 派活 → 跑门 → 落地 → 巡检 → 复盘） | `skills/softeng-manage/SKILL.md` —— 六段路由 + 六条铁律；**本仓命令落在哪**看同目录 `references/repo-bindings.md` |
| **跑门禁 / 读懂门禁结果**（退出码、未跑、复用、假红） | `skills/pipe-gate/SKILL.md` + `skills/pipe-gate/references/repo-bindings.md`（锁在哪、超时多少、档位怎么选） |
| **审计**（台账 / 证据 / 封存 / trailer） | 判据真源只有 `scripts/audit_progress.py` 一份；怎么用看 `skills/pipe-land/SKILL.md` 的收口段与 `skills/pipe-forensics/SKILL.md` |
| **号池 POOL**（账号 → 模型 → 派活；MCP 只读面与写面） | `tools/pool_mcp.py` 的 docstring —— 工具名、只读/写面的**唯一真源**；模块地图看 `docs/subsystems/pool/README.md`；派活顺序看 `skills/pipe-card/SKILL.md` |
| `pipe` 框架本身的门禁 / 派活 / 台账 | `skills/README.md`（分工判据，**顶部有四条 2026-10-24 新口径**）+ `复盘/新窗口交接卡.md`（本仓当前状态） |
| **接手一个已存在的项目 / 新起一个项目** | `skills/pipe-takeover/`（接手）或 `skills/pipe-new/`（新起）：**第一步**先跑 `python -X utf8 tools/wb_takeover.py --root <目录> --strict`（判据不足会退 2 —— 不许猜类别） |
| 接别的 harness | `skills/GLUE-harness.md` |
| DSH 技能 / 插件的写法 | `DSH-技能与插件开发参考.md` |

## ★ 写 / 改文档之前：先定层，再一次写完（别「改一点、看一点」）

**这条是硬指令，不是建议。** 实测症状：按「改一处 → 跑一遍检查 → 再改一处」的方式更新文档，
同一份文件上反复往返十几次，而且**每次都不知道自己漏了哪一层**。原因不是不努力，是**没先定层**。

动手前按顺序回答三问，**答完再写第一行字**：

1. **这份文档属于哪一层？** 本仓四套分层并存，**选一套并说清是哪套**，别混用：
   - 内容分层（意图 / 规格 / 契约 / 实现 / 品味）—— `docs/文档架构.md`、`skills/softeng-manage/references/doc-layers.md`
   - 文档系统的读者分层（先读哪份）—— `docs/文档系统导航.md`
   - 技能内部三层（渐进加载：元数据 / 正文 / references）—— `docs/reference/agent-skills-spec.md` §5
   - 技能的职责分层（索引 / 操作 / 判据）—— `skills/softeng-manage/references/skills-layers.md`
2. **这是「现在的事实」还是「当时的过程」？**
   - 读者会拿它当**当前真值**用（reference / how-to）⇒ **就地改成真值**；旧值、为什么改、谁改的，
     留在卡规格 + `docs/changelog.d/<台账号>.md` + 台账 `evidence`，**不要写进正文**。
   - 读者要看的是**当时的决定**（explanation / 历史复盘）⇒ **保留原文 + 顶部加注**「已被卡 N 推翻」，
     加注必须带日期与推翻它的卡号 / 台账号。
   - 一句话判据：**读者会拿它当「现在的事实」用吗？会 ⇒ 就地改；不会 ⇒ 加注。**
3. **这次改的是「一页」还是「一条链」？** 一条事实只许有**一处投影**。若它在别处还有投影
   （计数、门数、路径清单、行数表），**一次把全部投影列出来一起改**，别改一处跑一次检查。
   列不全就先搜：同一串数字 / 路径在 `docs/` `复盘/` `skills/` `AGENTS.md` 里各出现几次。

**写完之后的顺序**（不是写之前；一次跑完，别一段一段跑）：

```bash
python -X utf8 scripts/check_docs.py --mode report        # 死指针 / 漂移 / 已废弃未标注
python -X utf8 scripts/check_layers.py                    # 引用完整性（反引号里的 .md 会被当真路径查）
python -X utf8 tools/check_skills_claims.py --check       # 只在改过 skills/** 时；退 3 = 判不出，不是绿
python -X utf8 skills/nails/check_skills.py               # 只在改过 skills/**/SKILL.md 时
```

**四条不许做的事**（都踩过）：

- **不许**在反引号里写一个**不存在 / 计划中**的路径（`check_docs.py` 会当死指针；`docs/doc-debt-baseline.toml`
  的基线**只能降不能升**，多一条就红一道门）。要么去掉反引号，要么写明「（计划建）」。
- **不许**把会漂的数字当常量写进文档（门数、篇数、行数、卡数）。要写就写**带日期**的读数 + 算它的命令。
- **不许**手改机器生成的部分：`docs/INDEX.md`（整份，`scripts/gen_doc_index.py`）、`复盘/INDEX.md`
  （整份，`scripts/retro/retro_index.py`）、`docs/subsystems/pool/README.md` 的
  `<!-- pool-margin:begin -->` 与 `<!-- pool-margin:end -->` 之间那段（`scripts/gen_pool_readme.py`）。
  改生成器或生成器内的常量，然后重跑生成器。
- **不许**在 `skills/` 里写判据。判据在 `tools/` / `scripts/` / `tests/` 里只有一份真源；
  `skills/` 只写「怎么用才不出错」。

## 长命令怎么跑（免得看着像卡死）

**禁止**把长命令用管道截断后再跑，例如 `python tools/wb_land.py … | tail -3`：
管道要等进程结束才吐一次，中途后台作业读不到任何输出，看起来像卡死。

**也禁止** `sleep N` 硬等：长任务起后台作业，等运行时给完成通知，中途要看进度就
`tail -n 20 <日志>` 或读作业输出（瞬间返回）。
**也禁止** `job_output(wait: true)` 长时间阻塞：软工预设已把 `waitTimeoutMs` / `maxWaitTimeoutMs` 压到 1 秒，
长等会被截断并回 `running` —— 等完成通知，或用 `job_output`（不带 wait）读增量 + `tail -n 20 <日志>`。

**强制检查**（写法不合规直接拦下）：

```bash
python -X utf8 tools/cmd_guard.py --cmd '<你要跑的命令>'
```

**一律**用带日志的跑法（逐行落盘 + 定时心跳，后台输出增量可读）：

```bash
python -X utf8 tools/run_logged.py --log gates/diag/land-A302.log -- \
    python -X utf8 tools/wb_land.py --card A302 ...
```

要复核进度就读日志 `tail -n 20 gates/diag/land-A302.log`，别再套 `| tail`。

## 三条本地约定（免得踩）

- `skills/` 里**只放操作知识**（顺序、前置检查、常见错、该看哪个产物）。
  判据放库/门里 —— **删掉整个 `skills/` 目录，框架仍要完整可用**。
- **技能分两页写**：`SKILL.md` 只放**换仓不变**的动作与读法；本仓的路径 / 环境变量 / 锁 / 读数 /
  历史证据一律进同目录 `references/repo-bindings.md`。换一个仓用这套技能，**只换那一份**。
  这不是风格偏好 —— 原来全写死在 `SKILL.md` 里，换个仓整页作废（2026-11-08 用户提出）。
  细则见 `skills/README.md` §2「换仓只用换一份」。
- `harness.toml` 是 `harness/` 复制体与本项目之间的**唯一胶水**。
  改它之前先读它自己的文件头注释（键的口径写在那里）。
