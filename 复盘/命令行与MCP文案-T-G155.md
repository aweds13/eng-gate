# 命令行与 MCP 文案清理（卡 061 · 台账号 `T-G155`）

> 承接 G-4（命令行与 MCP 的措辞）那条：用户 2026-09-27 原话「**一起清**」——
> 备忘录团队里的解释性话语删掉之后，**命令行 / MCP 面上同类解释句也一起清掉**。
> 口径沿用本项目已定的一脉（`T-G142` / `T-G144` / `T-G152`）：
> **解释** = 看名字 / 看参数就知道、只在教你怎么用、或解释设计；
> **必要语义** = 不说就歧义（**类型 / 单位 / 范围 / 默认值 / 枚举取值 / 口径 / 状态词**）。

## 1. 为什么有这张卡

- 用户 2026-09-27「一起清」，卡规格 `gates/diag/卡061-命令行与MCP文案清理.md` §1。
- 范围由主控划定（卡 §0.3 / §4）：**只清真正露给用户的两个面** ——
  ① `timeflow --help` / `timeflow <命令> --help`；② **MCP 工具描述**（AI 看到的那份）。
- ★ **`docs/commands.toml` 的 41 条 `note` 不在范围** —— 那是给维护者看的依据 / 出处 / 路由说明，
  不是 CLI/MCP 展示面（卡 §0.3 / §7.4）。本卡一个字未动。

## 2. 两个面各自由什么生成（清理的落点）

- **CLI 面** = `src/timeflow/cli/registry.py` 的 `Command.title` + `Param.help`
  （`main.py:_command_help()` 逐条拼出来；顶层 `main.py:_usage()` 另有一份），
  以及 `main.py:_usage()` / `_command_help()` 里的固定帮助句。
- **MCP 面** = `src/timeflow/mcp/server.py:tool_schema()` 把 **同一条命令**
  拼成 `f"{command.title}（契约 {command.op}；{kind_note}）"`，参数描述直接用 `param.help`
  —— **没有第二份文案**。所以清 `registry.py` 的 title/help，MCP 面同笔就清了。
- 结论：**`src/timeflow/mcp/server.py` 本身一行未改**（它的描述字段全是 `registry` 的投影 +
  OP 编号 + 只读/写状态词，没有独立的解释句）。

## 3. §2.1 逐条表

行号 = **改后**的 `src/timeflow/cli/registry.py` / `main.py` 行号。

### 表 A · 判为「解释」→ 删（共 16 处）

| # | 场合 | file:line | 原文 | 删成 / 理由 |
|---|---|---|---|---|
| A1 | `focus` 标题 | registry.py:156 | 现在有没有在专注（没有就是没有） | 现在有没有在专注 · 「（没有就是没有）」= 解释设计 |
| A2 | `board` 标题 | registry.py:163 | 团队视角（管理者 / 执行者，同一份分配记录） | 团队视角（管理者 / 执行者）· 删「，同一份分配记录」= 解释设计；枚举值保留 |
| A3 | `board --me` | registry.py:167 | 执行者视角要一个名字（本工具没有账号体系） | 执行者视角的名字 · 括号=卡 §1 点名的自我解释（保留「执行者视角」语义并压短） |
| A4 | `sync` 标题 | registry.py:174 | 同步现状（只报事实；网络那条路没做就如实说没做） | 同步现状 · 括号=解释设计 + 状态旁白 |
| A5 | `add-task --group-name` | registry.py:190 | 分组名（不存在的分组会被边界拒） | 分组名 · 括号=解释边界行为（边界自会拒绝，不必写在参数上） |
| A6 | `add-task --flagged` | registry.py:194 | 标星（重要） | 标星 · 「（重要）」= 同义复述 |
| A7 | `complete` 标题 | registry.py:201 | 完成任务（与界面上那个勾是同一条路） | 完成任务 · 括号=解释设计 |
| A8 | `complete --task-id` | registry.py:203 | 任务 id（见 timeflow tasks --json） | 任务 id · 括号=教你怎么取 id |
| A9 | `myday` 标题 | registry.py:209 | 把任务放进 / 移出今天的清单（同一条路由，来回切） | 把任务放进 / 移出今天的清单 · 括号=解释设计 |
| A10 | `focus-start` 标题 | registry.py:217 | 开始专注（回执里有这次专注的 id） | 开始专注 · 括号=教你怎么取 id |
| A11 | `focus-finish` 标题 | registry.py:228 | 结束专注 / 放弃 / 记中断（status 决定，是同一条路） | 结束专注 / 放弃 / 记中断 · 括号=解释设计；取值在 `--status` 的枚举里保留 |
| A12 | `focus-finish --session-id` | registry.py:231 | 专注 id（focus-start 回执里那个） | 专注 id · 括号=教你怎么取 id |
| A13 | `memo` 标题 | registry.py:246 | 随手记一条（沉淀型内容，写完自动落一份 md） | 随手记一条 · 括号=解释设计 + 副作用旁白 |
| A14 | `memo --ref-handle` | registry.py:251 | 引用句柄（Obsidian 跳转用） | 引用句柄 · 括号=解释用途 |
| A15 | 顶层 `--help` | main.py:110 | 命令（不起服务、不占端口） | 命令 · 括号=解释工具怎么实现的 |
| A16 | 顶层 `--help` | main.py:118 | 写命令（默认关：每条都要加 --allow-write）： | 写命令（默认关）： · 「每条都要加 --allow-write」= 教怎么用（开关在文末「全局：」那行仍列着） |

★ **一个字没删的必要语义**（卡 §7.2 点名必须保住）：范围 `1~90` / `0~365`、默认值 `14` / `今天` /
`本周`、枚举 `important / planned / flagged`、`manager / executor`、`高 / 中 / 低`、
`tomato / plain`、`finished / abandoned / interrupted`、口径 `（周一起算）` / `（只列未录成绩的）`
—— 全部逐字保留。

### 表 B · 判为「必要语义」→ 原样留（逐条列以证「没漏清」）

| 场合 | 原文（保留） | 依据 |
|---|---|---|
| `today` 标题 | 今日摘要：专注 / 手动投入 / 复习 / 产出 / 习惯 / 债务 | 描述输出内容（看名字推不出） |
| `plan` 标题 | 今天的清单（My Day） | 「My Day」是界面里的既有名词 |
| `done` 标题 | 今天做成了什么（任务 / 步骤 / 产出） | 描述输出内容 |
| `week` 标题 | 周结算（周一起算）+ 逐日走势 | 「周一起算」= 口径 |
| `habits` / `check` / `trend` / `tasks` / `upcoming` 标题 | 习惯列表（连续天数 + 打卡天数）等 | 描述输出内容 / 口径（`只列未录成绩的`） |
| `add-task` 标题 | 新建任务（默认不进今天的清单） | 默认行为（默认值类） |
| `--day / --week-of` | 看哪一天（YYYY-MM-DD，默认今天）等 | 格式 + 默认值 |
| `--days`（trend / upcoming） | 看多少天（1~90，默认 14）/ 看多少天内（0~365，默认 14） | 范围 + 默认值 |
| `--view`（tasks / board） | 智能视图：important / planned / flagged；manager（默认）/ executor | 枚举取值 + 默认 |
| `--title / --due-date / --group-name / --priority / --note` | 任务标题（必填）等 | 必填 / 格式 / 枚举 |
| `--is-myday / --flagged` | 直接放进今天的清单 / 标星 | 语义（默认 false 在 help 里已渲染） |
| `--kind`（focus-start） | tomato（番茄钟）/ plain（正计时） | 枚举取值 + 各自含义 |
| `--status`（focus-finish） | finished（…）/ abandoned（…）/ interrupted（…） | 枚举取值 + 各自含义 |
| `--text / --task-id / --duration-sec / --ref-handle` | 记什么（必填）等 | 必填 / 语义 |
| `main.py:_usage` 其余 | 开窗口（默认）/ 我有哪些命令 / 整张契约命令表（含 kind / 可逆 / AI 边界）/ 全局：--json（机器读）· --db PATH（换库）· --allow-write（写命令的必要开关）· --help / 退出码：0=成功 … 4=写操作没开 | 默认值 / 各 flag 的含义 / 状态词映射（**保留**） |
| `main.py:_command_help` | 契约操作：… 路由：… / 参数：无 / 加 --json 打边界原样的 JSON；加 --db PATH 换库。/ ★ 这条会改数据… / 这条命令是只读的。 | 契约 + 路由（机器可核）/ 输出语义（边界原样）/ 状态词（**保留**） |

### 表 C · MCP 面（`src/timeflow/mcp/server.py`）

| 场合 | 内容 | 处置 |
|---|---|---|
| 工具描述 | `f"{command.title}（契约 {command.op}；{kind_note}）"` | 结构未动：title 随 A 表同笔清；`契约 OP-nn` 是机器对应、`只读` / `写操作，会改数据` 是状态词 → **保留** |
| 参数描述 | `entry["description"] = param.help` | 随 `registry` 的 `Param.help` 同笔清 |
| `_initialize.instructions` | 一段服务器说明 | **未动**——它不是「MCP 工具描述」（卡 §0.3 划定的面）；它含 AI 需要的上下文（写开关、写工具名单），删了是**越界**（见 §4） |
| `_mcp_usage()`（`timeflow mcp --help`） | 客户端配置示例等 | **未动**——同理不属于本卡划定的两个面（见 §4） |

**MCP 工具清单改后读数**（证明工具数与 schema 没少，见 §5）：
`allow_write=False` → **14 个**；`allow_write=True` → **20 个**；每个的名字 / `required` / `properties` 名称集合与改前**逐条相同**。

## 4. 拿不准 / 判为保留（不凭感觉删）

1. **`server.py:_initialize` 的 `instructions`** 与 **`_mcp_usage()`**：里面有解释性句子
   （如「写入走的是与界面完全相同的那套语义（同一个 HTTP 边界），不新增口径」），但它们
   **不属于**卡 §0.3 划定的两个面（① CLI `--help` ② MCP **工具描述**），且含 AI 客户端需要的
   可用性上下文 → **保留不动**。若主控认为该并入范围，另开一卡（不要在本卡扩范围）。
2. **`main.py:_command_help` 的两行固定句**（「加 --json 打边界原样的 JSON；加 --db PATH 换库。」）：
   含输出语义（边界原样的 JSON）+ flag 含义（换库）→ 判**必要语义**，保留。
   （被测试钉住的两句「会改数据」`WRITE_FLAG`「只读的」也在这一层，原样保留。）
3. **`--kind` / `--status` 括号里的中文释义**（番茄钟 / 正计时 / 结束，计入投入 …）：判**枚举取值
   的含义**（不说就不知道选哪个）→ 保留。
4. **`--flagged` 的「（重要）」**：判同义复述 → 删；若主控认为「重要」是口径，可单独回滚这一处。

## 5. 读数（真输出，命令见回报）

- `timeflow --help` **改前 / 改后**：8 条标题去掉括号解释（focus / board / sync / complete /
  myday / focus-start / focus-finish / memo），「写命令（默认关：…）」→「写命令（默认关）」，
  「命令（不起服务、不占端口）」→「命令」。
- `timeflow board --help`：`--me` 改后 = `执行者视角的名字`；`--view` 枚举原样。
- MCP 工具清单：改后 **14（只读）/ 20（含写）**，schema 逐条相同。
- `tests/test_cli_line.py` + `test_mcp_line.py` + `test_cli_writes.py` + `test_check_commands.py`：
  **63 passed**。
- `ruff` `All checks passed!`；`mypy` `Success: no issues found in 56 source files`。
- `gates/render/**` **零变动**（`git status --porcelain -- gates/render` 为空）；
  `tools/ui_text_baseline.toml` **零变动**（均为空，本卡未碰界面）。

## 6. 边界（如实写）

- **没碰**：`docs/commands.toml`（41 条 note）、`src/web/**`、`src/timeflow/core/**`、
  `src/timeflow/api/**`、`tools/**`、`scripts/**`、`docs/contracts/**`、`复盘/` 里除本文件与本卡
  白名单外的一切、`.wt/**`、主树外来未跟踪文件、`data/`。
- **没改**：`server.py`、`tests/**` —— 现有测试**没有**钉住任何被删字面（pin_check 16 条字面
  命中 15、**钉子 0**；evidence_map 显示这三个文件上挂的 `text:` 证据都锚在**未改动的代码行**）。
- **`memo` 的「写完自动落一份 md」副作用**：删的是读法（解释设计）；该副作用本身在
  `docs/`（约定层 / F8 契约 / 代码）里另有记录，未丢依据。
- 台账分布行（`复盘/交接-重构进度.md`）由 `tools/sync_counts.py` 刷新（加 `T-G155` 后 → 共 281 条）；
  本卡按规格**自提**（四个 trailer：`Task` / `Refs` / `Ledger` / `Gates`）。

## 7. 台账条目（供集成者粘贴）

```toml
[entries."T-G155"]
id = "T-G155"
title = "清掉命令行与 MCP 里的解释性话语（G-4 措辞线）：只留类型/单位/范围/默认值/枚举/口径"
group = "CLI"
status = "done"
evidence = [
  "file:复盘/命令行与MCP文案-T-G155.md",
  "text:src/timeflow/cli/registry.py::Param",
]
gaps = "**为什么有这张卡**：用户 2026-09-27「一起清」—— 承接 G-4（命令行与 MCP 的措辞），把两个露给用户的面上的解释性话语一并删。**范围（主控划定）**：① timeflow --help / timeflow <命令> --help（来源 registry.py 的 title/help + main.py 的固定帮助句）；② MCP 工具描述（来源 server.py，且它就是 registry 的投影）。**逐条删了什么**：8 条标题的括号解释（focus/board/sync/complete/myday/focus-start/focus-finish/memo）、6 条参数 help 的括号解释（me/group_name/flagged/task_id/session_id/ref_handle）、main.py 两处（命令（不起服务、不占端口）」与「写命令（默认关：每条都要加 --allow-write）」）共 16 处。**逐条保留了什么**：范围 1~90 / 0~365、默认值 14 / 今天 / 本周、枚举 important/planned/flagged、manager/executor、高/中/低、tomato/plain、finished/abandoned/interrupted、口径（周一起算）/（只列未录成绩的）一个字未删。**范围边界（不动）**：docs/commands.toml 的 41 条 note（维护者依据记录）；server.py 的 _initialize.instructions 与 _mcp_usage（不属两个面且含 AI 上下文，见复盘 §4）；src/web/**、core/**、api/**、tools/**、scripts/**、contracts/**。**读数**：pin_check 16 条字面钉子 0；目标四测试 63 passed；ruff 通过；mypy 56 文件 0 error；MCP 工具数 14/20 与 schema 逐条不变；gates/render 与 ui_text_baseline.toml 零变动；全量门禁以 gates/last.json 为准。**没动的**：server.py 与 tests/** 零改动（无测试钉住被删字面）。**提交**：本卡自提，四个 trailer（Task / Refs / Ledger / Gates）齐全。"
```
