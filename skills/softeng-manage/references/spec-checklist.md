# 技能自检表（按 Agent Skills 规范）

规范离线副本：[规范](../../../docs/reference/agent-skills-spec.md)（2026-10-19 抓取）。
**新建或改技能后，逐条过这张表**；能跑校验器就先跑校验器。

## 1. 机器校验（一票否决）

```bash
npx -y skills-ref@latest validate ./skills/<技能名>
# 期望输出：Valid skill: ./skills/<技能名>
```

本仓另有两道钉子（比校验器更严，且都能离线跑）：

```bash
python -X utf8 skills/nails/check_skills.py      # 六小节 / ≤120 行 / 流程 ≤3 / 口径指脚本 / NOTES 三节
python -X utf8 skills/nails/check_commands.py    # 正文里的命令名要能在 CLI 帮助里找到
```

## 2. 十三条手检

| # | 检查 | 判据 | 不过会怎样 |
|---|---|---|---|
| 1 | 目录名 = `name` | 完全一致，小写连字符 | 校验器红；部分实现直接不加载 |
| 2 | `name` 合法 | ≤64、无大写、无 `--`、不首尾连字符 | 校验器红 |
| 3 | `description` 有「做什么 + 什么时候用」 | 两个信息都在，含触发关键词 | 技能永不触发（最大的坑） |
| 4 | `description` ≤1024 字符 | 数一下 | 校验器红 |
| 5 | 正文 ≤120 行 | `wc -l SKILL.md` | 卡 209 钉子红 |
| 6 | 细节在 `references/`，正文只给指针 | 正文出现长表 ⇒ 下沉 | 正文膨胀、常驻上下文超标 |
| 7 | 文件引用是**相对链接**且只深一层 | `[xx](references/<文件名>.md)` | 深链 / 纯文本路径，agent 找不到 |
| 8 | 被引用的文件真实存在 | 逐条 `test -f` | 断链 |
| 9 | 报错 / 边界的处置写出来了 | 「红 X ⇒ 先看 Y」 | agent 卡住后瞎猜 |
| 10 | 命令是真命令（不是示意） | 在本仓能跑通 | 照着敲就错 |
| 11 | 判据没有抄进技能 | 「算不算过」在库 / 门里有可执行真源 | 双真源，迟早打架 |
| 12 | 有 `NOTES.md`（本仓约定） | 三节齐：防哪类错误 / 失败过什么 / 接口与怎么改 | 钉子红 |
| 13 | ★ **换仓只用换一份**（2026-11-08 起） | `SKILL.md` 里没有本仓独有物（具体路径 / `TF_*` / 卡号 / 日期读数 / 复盘文件名）；这些都在同目录 `references/repo-bindings.md`，每条读数带日期 + 算它的命令 | 换个仓整页作废，agent 照抄就撞墙 |

## 3. `description` 模板

```yaml
description: <一句话说做什么>。当<场景 A>/<场景 B>/<关键词>时用；它<给什么结果>，<判据在哪>。
```

反例：`Helps with PDFs.`（没说何时用）
正例（本仓 `softeng-manage`）：`软件工程管理总入口——把「开卡 → 派活 → 跑门 → 落地 → 巡检 → 复盘」串成一条不发散的流程。当你要…时用；它只做路由与铁律，细节交给六个动作技能。`

## 4. 行数等读数：**现算，不抄表**

★ 这里原来有一张「9 个技能 / 各自正文行数」的表 —— **删掉了**：行数每次改写都变，
抄进文档当天就开始说谎（旧表里有 8/9 行已经对不上）。**会漂的数字不进文档**，只给算法：

```bash
wc -l skills/*/SKILL.md                       # 每份正文行数（上限 120，判据在钉子②里）
python -X utf8 skills/nails/check_skills.py   # 六小节 / ≤120 行 / 流程 ≤3 / 口径指脚本 / NOTES 三节
npx -y skills-ref@latest validate ./skills/<名>  # 官方校验器
```

要留历史读数就写进卡规格或 `NOTES.md` 的「失败过什么（带读数）」，并**带日期**。

`spec-grill` 没有目录：它是 `skills/README.md` 索引里的一行占位，grill-me 已并入
`references/grill-me.md`（卡 A305），**别顺手补一个 `spec-grill` 目录出来**。

## 5. 注册与可见性（规范之外，本仓必须）

| 注册点 | 维护工具 | 核对命令 |
|---|---|---|
| 用户级 `~/.dsh/skills/` | 手工 junction（或 `dsh_skills_link.py --root`） | `ls ~/.dsh/skills` |
| 项目级 `<仓>/.dsh/skills/` | `tools/dsh_skills_link.py` | `--check` |
| 工人侧 `.codeartsdoer/skills` | 工人侧注册脚本 | 对应 `--check` |

三处都是 **junction、零副本**：真源只有 `skills/<名>/` 一份。
**不要**把 `skills/README.md`、`skills/GLUE-harness.md` 或 `skills/nails/` 挂进去 ——
前两个没有 frontmatter，会被当成坏技能。
