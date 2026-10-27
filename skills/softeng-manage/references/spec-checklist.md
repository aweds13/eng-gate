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

## 2. 十二条手检

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

## 3. `description` 模板

```yaml
description: <一句话说做什么>。当<场景 A>/<场景 B>/<关键词>时用；它<给什么结果>，<判据在哪>。
```

反例：`Helps with PDFs.`（没说何时用）
正例（本仓 `softeng-manage`）：`软件工程管理总入口——把「开卡 → 派活 → 跑门 → 落地 → 巡检 → 复盘」串成一条不发散的流程。当你要…时用；它只做路由与铁律，细节交给六个动作技能。`

## 4. 当前 9 个技能的读数（卡 A304 之后）

| 技能 | `skills-ref validate` | 正文行数 | `check_skills.py` |
|---|---|---|---|
| `pipe-card` | Valid | 91 | 绿 |
| `pipe-forensics` | Valid | 100 | 绿 |
| `pipe-gate` | Valid | 80 | 绿 |
| `pipe-init` | Valid | 98 | 绿 |
| `pipe-land` | Valid | 92 | 绿 |
| `pipe-new` | Valid | 110 | 绿 |
| `pipe-takeover` | Valid | 87 | 绿 |
| `pipe-workbench` | Valid | 77 | 绿 |
| `softeng-manage` | Valid | 104 | 绿 |

`spec-grill` 还没建目录，是 `skills/README.md` 索引里的一行占位（后续卡补）。
卡 A293 的旧表（7 个技能 / 70–91 行）已被本表取代：gate / land / workbench 在 A304 之前就已改动过，
旧读数当时已经过期。

复现：`wc -l skills/*/SKILL.md`、`python -X utf8 skills/nails/check_skills.py`、
`npx -y skills-ref@latest validate ./skills/<名>`。行数会随改写变，**这张表是读数不是判据**。

## 5. 注册与可见性（规范之外，本仓必须）

| 注册点 | 维护工具 | 核对命令 |
|---|---|---|
| 用户级 `~/.dsh/skills/` | 手工 junction（或 `dsh_skills_link.py --root`） | `ls ~/.dsh/skills` |
| 项目级 `<仓>/.dsh/skills/` | `tools/dsh_skills_link.py` | `--check` |
| 工人侧 `.codeartsdoer/skills` | 工人侧注册脚本 | 对应 `--check` |

三处都是 **junction、零副本**：真源只有 `skills/<名>/` 一份。
**不要**把 `skills/README.md`、`skills/GLUE-harness.md` 或 `skills/nails/` 挂进去 ——
前两个没有 frontmatter，会被当成坏技能。
