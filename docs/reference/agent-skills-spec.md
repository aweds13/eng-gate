# Agent Skills 规范（离线参考副本）

> **来源**：<https://agentskills.io/specification.md>（规范正文，含官方校验器）
> **抓取时间**：2026-10-19
> **辅助来源**：
> - <https://github.com/anthropics/skills> —— 参考实现与示例技能
> - <https://code.claude.com/docs/zh-CN/skills> —— 产品侧行为（何时触发、如何加载）
>
> 本文件是给本仓用的**离线抄本 + 落地约定**。规范若更新，以 agentskills.io 为准；
> 这份副本要**整份重抓**（不要只改零散几行）。

---

## 1. 目录结构

一个技能 = 一个目录，至少含 **SKILL.md**：

```
skill-name/
├── SKILL.md          # 必需：元数据 + 指令
├── scripts/          # 可选：可执行代码
├── references/       # 可选：按需加载的文档
├── assets/           # 可选：模板、图片、数据
└── ...               # 允许任意其它文件/目录
```

## 2. frontmatter（YAML）

| 字段 | 必需 | 约束 |
|---|---|---|
| `name` | 是 | ≤64 字符；只允许 `a-z`、`0-9`、`-`；不得以 `-` 开头或结尾；不得有连续 `--`；**必须与父目录同名** |
| `description` | 是 | ≤1024 字符；非空；写「做什么 + 什么时候用」（触发靠它） |
| `license` | 否 | 许可证名或捆绑许可证文件的引用 |
| `compatibility` | 否 | ≤500 字符；环境要求 |
| `metadata` | 否 | 任意字符串键值映射 |
| `allowed-tools` | 否 | 空格分隔的预批准工具列表（实验性，各实现支持不一） |

最小示例：

```markdown
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

`name` 合法 / 非法对照：

```
合法: pdf-processing / data-analysis / code-review
非法: PDF-Processing（大写） / -pdf（首连字符） / pdf--processing（连续连字符）
```

`description` 好 / 坏对照：

```
好: Extracts text and tables from PDF files, fills forms, merges PDFs.
    Use when working with PDF documents or when the user mentions PDFs, forms, or extraction.
坏: Helps with PDFs.
```

## 3. 正文

frontmatter 之后的 Markdown 就是技能指令，**格式无限制**，推荐包含：

- 分步指令；
- 输入 / 输出示例；
- 常见边界情况。

注意：技能一旦被激活，**整个 SKILL.md 会被载入上下文** —— 长了就把细节拆进 `references/`。

## 4. 可选目录约定

- `scripts/`：可执行代码。自包含或写清依赖；错误信息要有用。
- `references/`：按需读取的文档。单个参考文件要**聚焦**，越小越省上下文。
- `assets/`：模板、图片、数据表等静态资源。

## 5. 渐进加载（Progressive Disclosure）

1. **元数据**（约 100 tokens）：所有技能的 `name` + `description` 启动即载入；
2. **指令**（建议 <5000 tokens）：技能被激活时才载入整个正文；
3. **资源**（按需）：`scripts/`、`references/`、`assets/` 只在需要时载入。

正文**保持在 500 行以内**；更长的参考材料拆成独立文件。本仓把上限收紧到 **120 行**（卡 209）。

## 6. 文件引用

在技能内引用其它文件，用**相对技能根的相对路径**：

```markdown
See [the reference guide](references/REFERENCE.md) for details.
Run the extraction script: scripts/extract.py
```

**引用只深一层**（直接从 SKILL.md 指出），避免深层引用链。

## 7. 校验

```bash
npx skills-ref validate ./my-skill
```

它检查 frontmatter 合法性、命名约定等。本仓另有更严的两道钉子与一张手检表，
见 `skills/softeng-manage/references/spec-checklist.md`。

## 8. 写作风格（来自产品侧文档的补充，非规范硬约束）

- **命令式**：写「ALWAYS use this exact template」，不写「你可以考虑……」。
- **解释为什么**：agent 理解了理由才能处理边界；只写「做什么」会僵化。
- **理论心智**：默认读者是聪明但没上下文的 agent —— 每节自足。
- **通用 vs 具体**：稳定的写死（输出模板、字段名），随环境变的留成参数。
- **避免过度规定**：给判据 + 一两个例子，让 agent 泛化。
- **大文件带目录**：参考文件 >300 行时在开头放目录。
- `description` 要“**pushy**”：模型倾向于**不**主动触发技能，所以把「什么时候用」的具体场景、
  关键词都塞进 description，而不是正文。

## 9. 本仓落地约定（超出规范的部分）

1. **判据不进技能**：技能只写「怎么用才不出错」；任何「算不算过」的规则必须在
   `scripts/`、`tools/`、`tests/` 里有一份可执行真源。删掉整个 `skills/`，框架仍要完整可用。
2. **一技能一动作**，外加一个**路由技能**（`softeng-manage`）—— 它不重复动作细节。
3. 技能目录里保持两份：**SKILL.md**（机器执行版）+ **NOTES.md**（人类理解版：这一层在防哪类错误、
   失败过什么、接口怎么改）。NOTES 不是判据的第二份抄写。
4. **六节骨架**（钉子在 `skills/nails/check_skills.py`）：什么时候用 / 什么时候别用 / 前置检查 /
   真命令 / 怎么读结果 / 常见错与处置；正文 ≤120 行；除六节外的小节 ≤3 条；
   「怎么读结果」的**每条**口径都要指向一个真实存在的脚本。
5. 长表（门清单、落地参数、批次围栏、状态机）下沉到该技能的 `references/`，正文给相对链接。
6. 命令一律写**本仓真命令**（`python -X utf8 tools/…` 或 `python -X utf8 framework/cli/main.py …`）；
   与 `pipe` CLI 的差异看 `skills/softeng-manage/references/mapping.md`。
