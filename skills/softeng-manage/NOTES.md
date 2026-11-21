# softeng-manage —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**。★ 这里不写判据 ——
> 判据在库与门里。删掉整个 `skills/` 目录，框架仍要完整可用。

## 这一层在防哪类错误

防「**知道所有零件、却不知道下一步**」和「**把框架 CLI 的想象命令敲进终端**」。

六个动作技能各自完整，但没有任何一个能回答：

1. 现在该开卡还是该落地？（阶段判定）
2. 这个仓跑的是自己那套工具，技能文档写的是框架 CLI —— 到底敲哪条？
3. 哪几条是**不能破的铁律**（判据在门里、先申报后落地、链红就停手）？

把这三件事塞进任何一个子技能，都会让它变成第二个「总纲」。所以单开一个**只做路由**的技能：
它只说「这件事走哪一步、哪条铁律不能破」，细节以子技能为准。

## ★ 为什么分「SKILL.md / references/repo-bindings.md」两页

2026-11-08（用户 m91323/m91324）提出：这套技能只对 `program/engineering` 有效，换个仓就不能用；
要求「特定仓库表述下降到原来更下一层的 reference，基于 agent 文档和 skills 编写的最佳规范」。

按 `docs/reference/agent-skills-spec.md` 落成两页：

- **`SKILL.md`** 只留**换仓不变的东西**：六段流水线（每段走哪个动作技能）、六条铁律、自查。
  里面不再出现本仓的工具路径 / 环境变量 / 目录名 / 日期读数 / 复盘文件名 —— 「六段各敲哪条」那张表
  改成「见 repo-bindings」。
- **`references/repo-bindings.md`** 放**这个仓长什么样**：六段的本仓真命令、框架 CLI 在本仓能不能用、
  权威文档指针、按主题拆的复盘缺口细则、本仓现算读数（门数 / 台账张数 / `wb_daily` 分区数 / 复盘篇数口径）。
- 换仓用这套技能 ⇒ **只换 repo-bindings 一份**，`SKILL.md` 一字不动。

判据侧没有放松：`SKILL.md` 仍要过 `skills/nails/check_skills.py` 四条（≤120 行 / 流程级小节 ≤3 /
「怎么读结果」每条指向真脚本 / NOTES 三节）。本次改造后是 91 行。

## 失败过什么（带读数）

- **卡 180（`T-G280`）**：5 个技能落库当天，两道钉子（`check_commands.py` / `check_skills.py`）
  **没有任何消费端** —— 不在门表里、也没脚本调它们（「判据生成了但没人读」）。
- **卡 209（`T-G318`）**：第一趟加严时 `check_skills.py` 退 1 ——
  `skills/pipe-*/SKILL.md` 的「怎么读结果」**4~7 条口径一条都没指向脚本**。讲得对，但没法被机器重跑。
- **卡 A293**：这六份技能是框架 CLI 时代的稿子 —— 实测 `pipe card new` / `pipe gate` / `pipe land`
  在本仓根跑不了（**根目录没有 `pipeline.toml`**）。工人照稿敲命令 ⇒ 第一步就撞墙。
  处置：正文换成 `python -X utf8 tools/wb_*.py` 真命令，框架 CLI 的差异集中到 `references/mapping.md`。
- **同一轮**：本技能初稿把「流水线」写成一张 9 个小节的长表 ⇒ `check_skills.py` 判
  「流程级小节 9 条 > 上限 3」。处置：长表下沉到 `references/`，正文只留路由。
- **2026-11-08 泛用化**：把「六段各敲哪条」那张表里的 `tools/wb_*.py` / `scripts/run_gates.py` /
  `gates/last.json` / `docs/workbacklog.toml` 全部搬进 `references/repo-bindings.md`；正文那张表改成
  「走哪个动作技能 + 见 repo-bindings」。顺手修了「`wb_daily` 五个分区」（真值 **7** 段）与
  「`复盘/INDEX.md` 769 篇」（当时实测目录 950 篇、索引自标 773 篇，两个口径不同；2026-11-21 现读目录 1122 篇、索引仍 773 篇）这两处陈旧读数。

## 脚本接口与以后怎么改

- **它自己的验收**：`python -X utf8 skills/nails/check_skills.py`（六小节 / ≤120 行 / 流程 ≤3 /
  口径指脚本 / NOTES 三节）、`python -X utf8 skills/nails/check_commands.py`（命令名对账）、
  与 `npx -y skills-ref@latest validate ./skills/softeng-manage`。
- **参考件**（都在 `references/`，正文只给相对链接、只深一层）：
  - `repo-bindings.md` —— 本仓绑定：六段真命令、框架 CLI 能不能用、权威文档指针、读数口径；
  - `mapping.md` —— 自然语言 → 动作 → 真命令；框架 CLI 与本仓工具链的差异对照；
  - `commands.md` —— 六段流水线的命令速查；
  - `spec-checklist.md` —— 改技能时逐条过的自检表。
- 要改的事与落点：

| 要改的事 | 改哪 |
|---|---|
| 本仓命令 / 路径 / 读数变了 | `references/repo-bindings.md`（**别改 SKILL.md**） |
| 命令对照（框架 CLI ↔ 本仓工具） | `references/mapping.md` + `references/commands.md` |
| 换了 harness（注册方式、目录、frontmatter） | `skills/GLUE-harness.md`，**不要**改本技能正文 |
| 铁律增删 | 先问「这条能不能写成门里的判据」；能，就进门，不进这里 |
| 换一个仓 | 只换 `references/repo-bindings.md`；六段流水线与铁律不变 |

- 格式依据：[Agent Skills 规范离线副本](../../docs/reference/agent-skills-spec.md)（2026-10-19 抓取）。
