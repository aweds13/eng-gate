# 卡 A317 —— AGENTS.md 作为接管/新建的第 1 步（T-AG431）

**树**：`.wt/A317` ｜ **base**：A316 落地后的 HEAD ｜ **提交**：主控提交（工人不 commit）

## 来路（用户 2026-10-23 令）

`"假如我用软工模式下，我是否能让他接手一个比较拉垮的项目的时候，他是啥文档都没有，他是否能做到把 Agent 文档也弄好，就是以他这个为一个入口。进行一个规范，然后再继续执行任务"`

现状（已实测）：`skills/pipe-new/`、`skills/pipe-takeover/`、`skills/pipe-init/`、`skills/softeng-manage/`、`tools/wb_takeover.py` 里 **`AGENTS.md` 命中全为 0** —— 接管一个没有任何文档的项目时，技能链不产入口文档，`--strict` 也不查。

## 调研（2026-10-23 实查，两份来源）

- [agents.md · What to Include](https://mintlify.wiki/agentsmd/agents.md/guides/what-to-include)：必备 = 项目概览 / 环境搭建 / 构建与测试命令 / 代码风格 / PR 与提交规范 / 安全注意；原文 *"Agents auto-execute testing commands found in AGENTS.md"* ⇒ **命令必须是真的**。
- [GitHub Blog · 2500+ 仓库](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/)：短、只写模型易错点、命令要真、不要通用道理。
- 两份都没有「入口/路由」这一层 —— 本仓补两节：`Gates & acceptance`、`Next step`。

## 模板（9 节，英文，≤120 行）

```markdown
# AGENTS.md

> Entry point for any agent working in this repository. Read this first, then follow the links.

## 1. What this is
One paragraph: purpose, stack, layout (`src/`, `tests/`, `docs/` …).

## 2. Run it
- Install: `<real command>`
- Dev server: `<real command>`
- If a command is unknown, write `TODO(verify)` — never invent one.

## 3. Test it
- Full suite: `<real command>`
- Single package: `<real command>`
- Single test: `<real command>`

## 4. Style and lint
- Formatter: `<real command>`
- Lint: `<real command>`
- Where the rules live: `<path to the style config>`
- Taste / design judgement lives in `<link to the taste doc>`; do not restate it here.

## 5. Gates and acceptance
- What "done" means here: <gates, acceptance checklist, ledger file>
- Where results are written: <path>
- Never claim green without the command's exit code.

## 6. Do not touch
- Secrets / credentials: <path or rule>
- Production data: <path>
- Generated artifacts: <path>
- Other people's directories: <path>

## 7. How to change things
- Branch: `<scheme>`
- Commit: `<format>`
- Before opening a PR: <commands>

## 8. Next step
- Current task: <one line>
- Acceptance for it: <one line>

## 9. Details
- Architecture: <link>
- Decisions: <link>
- Skills/playbooks: <link>
```

**写法规则**：① 只写「模型会做错的地方」，通用道理一律删；**⑥ 能用工具判的写命令、判不了的写链接**——`Style and lint` 只放命令与配置路径，审美/取舍一律指向 taste 文档，两边不许各抄一份；② 每条命令都要能直接跑，不能写占位符；③ 不知道就写 `TODO(verify)` 并计数（接管报告里列出）；④ 全文 ≤120 行，细节走链接。

## 要做的事

1. 新建 `skills/pipe-takeover/references/agents-md.md`：上面模板 + 写法规则 + 「四块必填」（Run it / Test it / Gates / Next step）。
2. `skills/pipe-takeover/SKILL.md`：在 §0（先问再写）之后加「第 1 步：落 AGENTS.md」，再接五层。
3. `skills/pipe-new/SKILL.md`：新建项目同样先落 AGENTS.md（用模板，命令按新仓实际填）。
4. `tools/wb_takeover.py`：`--strict` 时目标根无 `AGENTS.md` ⇒ problems 加「缺入口」；`--plan` 输出应写的小节清单。
5. `tests/test_wb_takeover.py`：两条钉子（模板四块关键字齐全；无 AGENTS.md 时 strict 退 2）。

## 判据

- `pytest tests/test_wb_takeover.py tests/test_check_skills.py -q --no-cov` 全过。
- `python -X utf8 tools/wb_takeover.py --root . --strict` 在本仓仍判 A 类且绿（本仓有 AGENTS.md）。
- `tools/wb_takeover.py --root <无 AGENTS 的临时目录> --strict` 退 2 且输出含「缺入口」。

## 验收

1. 造一个只有 `README.md` 的临时目录，跑 `--strict` ⇒ 退 2、「缺入口」在输出里。
2. 按技能走一遍：先 grill-me、再落 AGENTS.md、再 `--strict` ⇒ 转绿。
