# MCP 与写操作 CLI（T-G65）—— 「四个面集中到一个点」闭环，以及写操作怎么才敢开

> 起因：T-G30 §4.3 定的顺序 命令表（T-G31 ✅）→ 只读 CLI（T-G64 ✅）→ **MCP** → **写操作 CLI**。
> 用户 2026-09-23 那句「**最好就是 4 个面集中到一个点，然后调用同一个点的东西**」到这里闭合。
> 用户 2026-09-25 当面定的三条写入口径（只做界面上已有的那些 / 默认关 / 语义与界面一样）本卡落地。

---

## 1. 一句话结论

四个面（界面 / ⌘K / 命令行 / **AI·MCP**）现在**都是同一张命令表的投影**：
`timeflow.mcp` 的 `tools/list` 由 `registry` 现算，`tools/call` **把参数翻成 argv 直接调 CLI** ——
所以"AI 做的和界面做的是一回事"不是承诺，是**同一段代码**。写命令第一批 **6 条**，
**默认关**（CLI 退 4 / MCP 不列出），而且**只做界面上已有的那些**（门禁判）。

---

## 2. 四个面各自是谁的投影

| 面 | 落点 | 谁判它没漂 |
|---|---|---|
| 界面按钮 | `index.html` 的 `ACTIONS` / `VIEWS` + 表的 `ui` | `check_commands.py` 的界面一节 |
| ⌘K 面板 | `index.html` 的 `const COMMANDS` | 面板一节（动作注册、键位不重复、OP 入口真有它） |
| 命令行 | `src/timeflow/cli/registry.py`（14 只读 + 6 写）+ 表的 `cli` | 命令行一节（**双向**、写命令还要判"界面上已有"） |
| **AI·MCP** | `src/timeflow/mcp/server.py` 的 `tool_list()` + 表的 `mcp` | **MCP 一节**（本卡新增，双向 + 写工具同样要"界面上已有"） |

★ 表里 `cli` 与 `mcp` 现在内容一样，但**是两栏**：它们是两份投影，门禁分别核对 ——
以后"只给 MCP 不给 CLI"（或反过来）这种决定可以直接在表里表达，不用改代码结构。

---

## 3. 写操作三条口径 → 逐条的机器判据

| 口径（用户 2026-09-25） | 判据 | 判在哪 |
|---|---|---|
| ① **只做界面上已有的那些** | 写命令/写工具的 OP，`ui` 必须非空 | `check_commands.py` 两节 + `tests/test_cli_line.py` + `tests/test_check_commands.py`（合成一条 `ui = []` 的写命令必须红） |
| ② **默认关** | 不带 `--allow-write` → 退 **4** + `write_disabled`；MCP 不给开关**不列出**写工具 | `tests/test_cli_writes.py::test_every_write_command_is_refused_without_the_switch`（**逐条**写命令 + 库快照逐字节比）+ `tests/test_mcp_line.py` 两条 |
| ③ **语义与界面完全一样** | 同一条写命令走 CLI 与直接打那条路由，**可观察状态**逐条相同 | `tests/test_cli_writes.py::test_every_write_command_does_what_the_route_does` |

**为什么默认关是"每次带上"而不是一个持久设置**：持久开关打开就忘了关，而写操作的风险是**一次性**的；
每带一次，人和调用方在那一刻都知道自己在写。
持久开关要做就得连设置页 UI 一起做（属产品面），所以**如实记成没做**，不在这里偷偷定。

---

## 4. 为什么 `tools/call` 直接调 CLI，而不是自己再解析一遍

MCP 客户端给的是 JSON 参数，CLI 收的是 argv —— 最省事的写法是"直接在 MCP 里拼请求、调边界"，
但那正是这个项目一路在消的东西：**第二套参数解析**。
所以本卡的写法是：参数 → argv → `timeflow.cli.main.main()` → 把它打出来的 JSON 原样当 tool result。

代价与好处都清楚：

- 好处：校验、默认值、错误码、退出码、写入口语义**全部只有一份**（改 CLI 时 MCP 自动跟着改）；
- 代价：每次调用多一层 argparse 式的解析（本地工具，量级可忽略）；
- 另一条诚实账：`tools/call` 里"这个会话有没有开写"**与 `tools/list` 是同一个判断**
  （不开写时那个工具**不存在** → `-32602` 并附一句"怎么开"），而不是"存在但执行失败" ——
  MCP 的规矩是"只能调用 `tools/list` 里出现过的工具"，两者不一致会让客户端误判。

---

## 5. 协议这一半（手写，零依赖）

| 方法 | 回什么 |
|---|---|
| `initialize` | 协议版本（认识的客户端版本优先，否则回我们的 `2025-06-18`）+ `capabilities.tools` + `serverInfo` + 一段 `instructions` 交代边界 |
| `tools/list` | 由 `registry` 现算：只读 14 + （开了写）6；`inputSchema` 的类型/默认/必填/说明就是参数表的投影 |
| `tools/call` | 走 CLI（见 §4） |
| 通知（无 `id`） | **不回**（JSON-RPC 规矩；不会让客户端卡住） |
| 不认识的方法 | `-32601` |
| 不认识的工具（含没开写的写工具） | `-32602` + 可用的工具清单 |
| 坏 JSON | `-32700` |

传输只做 **stdio**（一行一个 JSON-RPC 消息）；stdout 上**只有**协议消息，日志走 stderr
（`TF_LOG_PATH=off` 可关）。

---

## 6. ★ 与 `/api/ai/*` 的关系（两个 AI 面，别混）

| | 应用内 AI 边界（T-G6 / OP-34 / OP-32） | 本卡的 MCP |
|---|---|---|
| 谁在写 | 应用**内置**的 AI 接口 | **用户自己本机**起的 `timeflow mcp` |
| 能写什么 | **只写事实**（方案 3）+ 新增任务 + 勾**自己建的** | 界面上已有的写操作（第一批 6 条） |
| 默认 | 关（`ai.enabled`，设置页开关） | 关（每次 `--allow-write`） |
| 判据 | `ai` 字段 + 默认关 403 | `mcp` 字段 + 退 4 / 不列工具 |

**MCP 没有放宽 `/api/ai/*` 那条边界** —— 它是另一个出口、另一套开关，两边各自有判据。
这一条要写清是因为"AI 能写"听起来像一件事，其实是两件：一件是**别人家的 AI 替我写**（收严），
一件是**我自己的本机工具让 AI 帮我写**（默认关、由我每次点头）。

---

## 7. 验收与数字

- 新增测试 **23 条**：`tests/test_cli_writes.py` **7** + `tests/test_mcp_line.py` **12** +
  `tests/test_check_commands.py` **+4**（三条写命令硬冲突 + MCP 双向）；`tests/test_cli_line.py` 改写 4 条。
- 其中两条是"证明咬得住"的：
  ① **逐条**写命令不带开关 → 退 4 且**库一个字节没动**（快照逐字节比）；
  ② **真起子进程走真 stdio**：`initialize` → `tools/list`（没开关时无写工具）→ 带 `--allow-write`
     再起一次 → `tools/call memo` → 读回来**文本对得上**，而且 stdout 上只有协议消息。
- 门禁：`commands` 一节现在报 **20 条命令（只读 14 + 写 6）· MCP 20 个工具 · 写操作开了 6/40**。
- 退出码从 4 个变 5 个（新增 `4 = 被拒绝（写操作默认关）`）；`commands --json` 多了 `write_gate`。

---

## 8. 顺手修的两条（都不在计划里，都是踩出来的）

1. **★ 日志 handler 把 `sys.stderr` 绑死在配置那一刻**（真基础设施缺陷）：
   pytest 的 `capsys` 每个用例都换掉 `sys.stderr`，于是"第一次配置日志"若发生在用了 capsys 的用例里，
   **后面**的用例一记日志就往**已关闭**的流写，logging 打出一段「--- Logging error --- + Traceback」
   混进别的用例正在断言的 stderr —— 症状是 `test_broken_database_gives_a_stable_code_not_a_traceback`
   **随跑的先后顺序**时红时绿（单跑绿、先跑写命令那几个文件就红）。
   修法：`_CurrentStderrHandler.emit()` 每次现取 `sys.stderr`。
2. **检查器里两条"恒真"的判定**：`is_write` 本来就由路由方法算出来，所以
   "写命令不能是 GET / 只读命令必须是 GET"这两条**永远不会失败** —— 它长得像判据，其实是注释。
   换成真会失败的一条：写命令的方法必须在 `POST/PUT/PATCH/DELETE` 里（挡 `FETCH` 这种手滑）。

---

## 9. 边界与洞（如实记）

- **写命令第一批 6/40 条**写操作：口径①"只做界面上已有的那些"本来就是慢工，
  `check_commands.py` 把"还差多少条"报出来（**洞是进度**）；
- **MCP 协议是手写的**（本项目零依赖，没有第三方 SDK）：验的是"我们的客户端脚本 ↔ 我们的服务端"，
  **第三方客户端（DSH / Claude Desktop）接一次**是人工项 —— 已写进交接的验收清单；
- 只做 stdio 传输；没有 `resources` / `prompts` / `logging` 能力；
- 没有**持久开关 + 设置页 UI**（见 §3 的理由）；也没有把写命令做成"可撤销/二次确认"那种交互层
  —— 破坏性高的 `DELETE`（删任务/删备忘）**这一批没开**；
- 幂等性：`myday` 是**切换**（不是幂等设置），`focus-start` 同时只允许一个进行中的专注（边界会 400）
  —— 这两条如实写在 `commands.toml` 与命令帮助里，没有假装幂等。

---

## 10. 踩过的坑（记下来，别再犯）

1. **TOML 串里写 ASCII 双引号（第 12 次）**：T-G65 那段的 `gaps` 一次写进 **9 对** ASCII 引号，
   `check_toml.py` 当场报出行列。这次用了个小脚本把**那一行内部**的引号成对换成「」
   （`gates/diag/probes/fix_quotes.py`）—— 与其在两千多字里逐个找，不如做对一次机械动作。
2. **CRLF 陷阱**：用 `Path.read_text()`（通用换行）读过再写回，会把整个文件变成 LF，
   于是 diff 变成"全文件都改了"。手术脚本一律**先探测换行符**、写完再用原样换行符写回
   （本次实测：`traceability.toml` 是 CRLF）。
3. **★ 注贴错了条目**：给 T-G64 写的 ★ 注第一次贴到了 T-G27 的 `gaps` 末尾（两处结尾句式太像）。
   发现后挪正 —— 教训是**按行号或唯一长串定位**，别用一条随处可见的半句话当锚点。
4. `tools/call` 的"隐藏写工具"一开始返回的是 `isError: true`（"执行了但失败"），
   而 `tools/list` 是"不列出" —— 两处判断不一致，测试当场抓到（真 stdio 那条断言 `error` 不存在）。

---

## 11. 这一卡改了哪些文件

| 文件 | 改动 |
|---|---|
| `docs/commands.toml` | 新增 **`mcp` 一栏**（18 条 OP）+ 6 条写命令的 `cli`；头注释改成"四个面都通了"+ 写操作三条口径 |
| `src/timeflow/cli/registry.py` | `Param.where`（query/path/body）+ `Param.required`；`WRITE_COMMANDS`（6 条）；`all_commands()` / `is_write()`（**由路由方法算**） |
| `src/timeflow/cli/call.py` | 支持路径参数与 JSON body（`path_params` / `body`）；写命令同样"库不存在就拒绝"（T-G66 口径延伸） |
| `src/timeflow/cli/main.py` | `EXIT_REFUSED = 4` + `write_disabled`；`--allow-write` 闸门（**发请求之前**拦）；bool/整数类型转换；帮助分出只读/写两段；`mcp` 子命令分派 |
| **`src/timeflow/mcp/`（新）** | `__init__.py`（为什么是第四个面）+ `server.py`（stdio JSON-RPC、`tool_list` 由 registry 现算、`tools/call` 走 CLI） |
| `src/timeflow/cli/render.py` | `receipt()`：写命令的人读回执（只列回执里真有的那几栏，**不猜字段名**） |
| `src/timeflow/logs.py` | **修**：`_CurrentStderrHandler`（不把 stderr 绑死） |
| `scripts/check_commands.py` | 命令行一节改判只读/写两批；**新增 MCP 一节**；删掉两条恒真判定、加一条真判据；报告多 8 个数 |
| `tests/test_cli_writes.py`（新）/ `tests/test_mcp_line.py`（新） | 7 + 12 条 |
| `tests/test_cli_line.py` / `tests/test_check_commands.py` | 改写 4 条 / +4 条 |
| `docs/specification/nonfunctional.md` / `docs/user-guide.md` / `docs/implementation/modules.md` / `docs/changelog.md` | 口径与用法同步 |
| `docs/traceability.toml` | T-G65 → done；T-G64 标 ★ |

**没动的**：界面（一个按钮没加没改）、`app.py`（**一条路由都没加**：MCP/CLI 打的全是已有的路由）、
黄金（45 份一份没动）。

---

## 12. 下一步

T-G30 §4.3 这条线**走完了**。剩下的工程债：`T-G33` 跨函数事务残留；人工验收
（含本卡新添的一项：**第三方 MCP 客户端接一次**）。之后按用户定的顺序走人工验收。
