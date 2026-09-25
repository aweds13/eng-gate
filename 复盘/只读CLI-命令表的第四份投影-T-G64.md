# 只读 CLI：命令表的第四份投影（T-G64）

> 用户 2026-09-23 问：「**AI 原生的 CLI 这个可以加进来吗？会不会更加方便后面的维护，以及功能的扩展**」，
> 同一条消息里定了「**4 个面集中到一个点……排最后，先做命令表**」。
> 命令表 T-G31 建完、⌘K 面板 T-G61 做完，这一张就是那条线的**第 ④ 步**（T-G30 §4.3 的"只读 CLI"）。
> 教训进 `复盘/视觉线地图.md` §6。

---

## 1. 这一步要回答的其实是那句话的后半截

用户问的是"**会不会更加方便后面的维护和扩展**"。T-G30 §4.2 已经答过前半截：
**直接加一个 CLI 会让维护变差** —— 每加一个功能要在界面 / HTTP / CLI / AI 四处各写一遍。
所以这一步的**验收标准不是"有没有 CLI"**，而是：

> **CLI 里有没有一行自己算出来的东西。**

如果一行都没有（全是从既有边界取来的），那它只是**又一份投影**，维护成本接近零；
只要有一行是"我在这儿再算一遍"，它就是第二个口径 —— 那正是这个项目一路在消的东西。

## 2. 落点：三层，各自只干一件事

```
docs/commands.toml            ← 唯一的源（T-G31 建的，这一步只加了 cli 字段）
        │
        ├── cli/table.py      读那张表（与 check_commands.py 共用同一个读法）
        ├── cli/registry.py   14 条命令 = (名字, 契约 OP, 路由, 参数, 排版)
        ├── cli/call.py       取数：**进程内走同一个 HTTP 边界**（create_app 的同一套路由）
        ├── cli/render.py     排版：只把边界的 JSON 折成几行中文，不取数不算数
        └── cli/main.py       参数 / 输出 / 四个退出码 / 自描述
```

**★ 为什么不让 CLI 直接调 `core/`**（少一层看着更简单）：`api/app.py` 是唯一的边界 ——
参数校验（`days` 越界就是 400）、字段形状、错误码都在那里。CLI 直接调 core 就得把那些再写一遍，
等于把"四个面各写一遍"从业务逻辑搬到校验逻辑上。
所以取数是**进程内直接调 ASGI 应用**：同一个 `create_app()`、同一套中间件、同一套路由，
只把 socket 换成一次函数调用 —— **不起服务、不占端口**（不会和正在跑的窗口抢 8520）。

## 3. 十四条命令（只读全覆盖）

| 命令 | 契约 OP | 路由 |
|---|---|---|
| `timeflow today` | OP-7 查看今日摘要 | `GET /api/summary` |
| `timeflow plan` | OP-28 到期列表 / 进 My Day | `GET /api/mydays` |
| `timeflow overdue` | OP-16 逾期债务展示 | `GET /api/overdue` |
| `timeflow due` | OP-28 | `GET /api/review/due` |
| `timeflow done` | OP-48 今天做成了什么 | `GET /api/today/done` |
| `timeflow week` | OP-15 周结算 | `GET /api/summary/weekly` |
| `timeflow trend` | OP-15 | `GET /api/insights/daily` |
| `timeflow habits` | OP-19 习惯热力图 | `GET /api/habits` |
| `timeflow check` | OP-20 自检 | `GET /api/selfcheck` |
| `timeflow tasks` | OP-45 智能视图 | `GET /api/tasks` |
| `timeflow upcoming` | OP-25 课程提醒 | `GET /api/assessments/upcoming` |
| `timeflow focus` | OP-51 跨端镜像 | `GET /api/focus/active` |
| `timeflow board` | OP-33 视角切换 | `GET /api/team/board` |
| `timeflow sync` | OP-41 冲突处理 | `GET /api/sync/status` |

外加 `timeflow commands [--kind …] [--table] [--json]`：**自描述**（不取数，直接读那张表）。

覆盖率的账：**只读操作 13 条 → 覆盖 12 条**。唯一空着的是 `OP-43`「配置加载」——
它**压根没有路由**（入口是启动时的 Pydantic 校验），没有可投影的东西。
这一条**写在表里**（`OP-43` 的 `note`）也**钉在测试里**（`rows_without_cli == ["OP-43"]`），
免得下一个人以为是漏填。

## 4. 「AI 原生」那六条性质，逐条落在哪（T-G31 §2）

| 性质 | 落点 |
|---|---|
| 输出结构化 | `--json` 打的是**边界原样**的 JSON（不重排、不改名、不合并） |
| 自带 schema | `commands --json` 里每条命令带 `params`（名字 / 类型 / 默认 / 说明）—— 这正是 MCP tool schema 的原料 |
| 非交互 | 永不提问、永不分页 |
| 稳定错误码 | 退出码 `0/1/2/3` + `--json` 时 stderr 上 `{"error":{"code":…,"detail":…}}` |
| 幂等/可逆/破坏性 | `commands --table` 把表整张打出来（含 `kind` / `reversible` / `ai`） |
| 自描述 | `commands`；**表找不到就拒绝工作**（退 3），不自己发明一份命令清单 |

**stdout 只放数据、错误一律进 stderr** —— 这样 `timeflow today --json > x.json` 永远不会被错误污染。

## 5. 「它不是第二套命令」是机器判的

`scripts/check_commands.py` 新增一节「命令行投影」，逐条钉五件事（任何一条不成立 = 门禁红）：

1. **只读**：每条命令的路由方法必须是 `GET`，且挂的 OP 的 `kind` 必须是 `read`/`derive`
   —— 写操作 CLI 是另一张卡（要等 AI 边界口径，用户已定"AI 只写事实"）。
   （合成测试里塞了一条 `POST` + `kind=write` 的假命令，两条都报出来。）
2. **路由真是那条 OP 的**：`GET /api/nope` 这种"我记得是这个路径"当场红。
3. **双向指认**：代码里有这条命令 → 那条 OP 的 `cli` 字段必须写上它；
   表里写了 `timeflow xxx` → 代码里必须有这条命令、且挂的就是这条 OP。任一边漏了都报。
4. **命令名不重复**。
5. **覆盖率**：只读操作里还有哪几条没有命令行入口 → 报出来（**洞是进度不是错误**）。

另外测试层还有一条源码级护栏：`src/timeflow/cli/**` 的 import 里**不许**出现
`sqlite3` / `timeflow.core` / `timeflow.storage`，而 `timeflow.api.app` **必须**在
—— 用 `ast` 读 import 语句（不是字符串搜索：docstring 里提到 `core/` 不该被误伤）。

## 6. 验证

| 层 | 证据 |
|---|---|
| pytest（19 条，`tests/test_cli_line.py`） | 见下 |
| 检查器（`commands` 门，`--fast` 里也有） | 真仓库 0 条硬冲突；报了「命令行 14 条 · 覆盖 12/13 条只读操作 · 没入口的 1 条」 |
| 检查器自身的测试（`tests/test_check_commands.py` +3） | 合成假命令 → 路由不匹配 / 表里没写 / POST / 挂写操作，四种都报；真仓库覆盖率断言 |

`tests/test_cli_line.py` 里最值钱的三条：

1. **`test_every_command_is_a_projection_of_the_same_route`**：
   逐条命令跑 `--json`，拿 CLI 的输出与 `TestClient` 直接打同一条路由的响应 **`==`**。
   这一条就是 §1 那个验收标准的机器形态 —— CLI 一旦自己算数，它立刻红。
2. **`test_cli_does_not_touch_the_database_or_the_domain_layer`**：源码级 import 白名单（见 §5）。
3. **`test_bare_timeflow_still_opens_the_window`**：不带参数**仍然开窗口**（原行为一个没改）；
   `timeflow today` 才走命令行。两条一起把"只加不改"钉住
   —— 断的是 `SystemExit` 与 `uvicorn.Server` 有没有被构造，不靠"我觉得它没开窗口"。

顺带跑的一条真事：**假日子对 CLI 也生效**（`TIMEFLOW_FAKE_TODAY=2026-06-15` → `timeflow today`
第一行就是 `2026-06-15`）—— T-G62 那条时钟缝是**产品层**的，所以命令行免费继承，
不需要为它再钉一处（这正是当初把它做成"一处出口"的回报）。

## 7. 没做 / 边界（不许假装）

- **写操作 CLI 没做**（`add` / `done` / `focus start`…）：那是 T-G30 §4.3 的第 4 步，
  卡在"AI 边界口径"上 —— 用户已定"AI 只写事实"，但**哪些操作必须在 CLI 里可达**这句还没定。
  这一版**一行写路径都没有**（检查器钉着 `GET`）。
- **MCP 没做**（第 3 步）：它要的元数据比 CLI 更多（参数 schema 必须精确），
  这一步把原料备齐了（`commands --table --json` + `commands --json` 的 params），但协议那层是另一张卡。
- **不连正在跑的服务**：每次调用自己开一个进程内 app 读同一个库。
  好处是**行为确定**（不会"连上了就一套、没连上另一套"）；代价是每次约 0.3–0.5s 的启动开销。
  库里同时开着桌面窗口也能读（SQLite 文件级并发，只读不写）。
- **stderr 上会有一行 `app_start` 的 JSON**：那是真发生的事（app 真的建了）。
  脚本要绝对干净就 `TF_LOG_PATH=off`（既有的日志开关）；stdout 永远只有数据。
- **局域网配对门在这条路上不判定**：来源写死回环（`allow_lan=False`），而回环本来就是放行的那一类。
  也就是说 CLI **不是**一个对外服务 —— 它是本机读。
- **`pip install` 出的包不一定带 `docs/commands.toml`**：所以 `commands`（自描述）在找不到表时**退 3**。
  数据命令不受影响（它们的路由绑定写在 `registry.py`，由门禁逐条核对 —— 与 ⌘K 面板同一个做法：
  面板也不在运行时读那张表）。

## 8. 这一卡改了哪些文件

| 文件 | 改动 |
|---|---|
| `src/timeflow/cli/{__init__,table,call,registry,render,main,__main__}.py` | **新增**：只读 CLI（7 个文件） |
| `src/timeflow/app/main.py` | 入口分派：第一个词是已知子命令或 `-h/--help` → 走 CLI；**不带参数原样开窗口** |
| `docs/commands.toml` | 新增 `cli` 字段（12 条 OP）+ 头注释补"四份投影的现状" |
| `scripts/check_commands.py` | 新增「命令行投影」一节（五条判定 + 覆盖率）；`load_commands` 改成与 CLI 共用同一个读法 |
| `tests/test_cli_line.py` | **新增** 19 条 |
| `tests/test_check_commands.py` | **+3**（覆盖率 / 路由不匹配 / 拒绝写命令） |
| `docs/specification/nonfunctional.md` | SR-NF6/SR-NF7 那条线补第 ④ 步 |
| `docs/user-guide.md` | 用户向一节：命令行怎么用 |
| `docs/changelog.md` · `docs/traceability.toml` · 交接两份 | 台账与快照 |
