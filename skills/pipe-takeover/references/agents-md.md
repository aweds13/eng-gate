# AGENTS.md 入口模板（接管 / 新建项目的第 1 步）

> 目的：任何 agent 进这个仓库，先读一份「会做错的地方」清单，而不是从头摸。
> 判据：`python -X utf8 tools/wb_takeover.py --root <目录> --strict` 会检查根目录有没有 `AGENTS.md`。

## 什么时候写

- **接手**一个已有项目：`wb_takeover.py` 定类之后、铺骨架之前。
- **新建**一个项目：铺完骨架、跑通第一条测试之后（那时命令才是真的）。
- 顺序永远是：**先 grill-me 问清 → 再写 AGENTS.md → 再写五层文档**。未确认不得动笔。

## 四块必填（缺一块 `--strict` 也要报）

| 块 | 小节 | 为什么必填 |
|---|---|---|
| 能跑 | `Run it` | agent 会**自动执行**这里的命令 |
| 能验 | `Test it` | 同上；测试命令错 = 报告假绿 |
| 算完 | `Gates and acceptance` | 没有判据的「完成」都是自称 |
| 下一步 | `Next step` | 接手的人要知道从哪开始 |

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

## 写法规则

1. 只写「模型会做错的地方」，通用道理一律删。
2. 每条命令都要能直接跑；不能写占位符。
3. 不知道就写 `TODO(verify)`，并在接管报告里列出待验证项。
4. 全文 ≤120 行；细节走链接，不塞正文。
5. **能用工具判的写命令，判不了的写链接**：`Style and lint` 只放命令与配置路径，审美/取舍指向 taste 文档，两边不许各抄一份。
6. 命令必须来自实测：写进去之前先跑一遍，把真实输出贴进卡规格。
