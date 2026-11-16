# Trae 接入结论（卡 218 · T-G331）—— 三条路，哪条死、为什么死、哪条活、活的怎么用

**树**：`.wt/traecli` ｜ **日期**：2026-10-13 ｜ **成员号**：`B-20261016` 的 M-1
**一句话**：★ **活的是 C**（反向把我们的 `pool` MCP 挂进 Trae 的 `.trae/mcp.json`，**不需要任何登录**）；
A 本机不可用（要企业版认证），**配方留档**（见 §2）；B（CDP 驱动面板）本机不可用、**已就地裁决保留**（§5），
但顺手把它对"面板重载"的**零韧性**补成了**重连**（§4）。

---

## §0 产品事实（别再重查）

**2026-10-10 新闻**：TraeWork 与 TraeCode 已合并为**全新 TRAE**（Agent 模式 / IDE 模式；桌面 + Web + 移动端；
灰度推送中）。⇒ 本机的面板页已经是 `workbench.desktop.main.solo-lite*`（`solo/solo-lite.html`），
**不再是** `workbench.html` —— 这一条直接决定了老零件为什么会"连不上 CDP"（§4）。

用户令（原话，可回查）：*「不是 pool 还有 trae 吗，用那个」* → *「登陆不了，要企业版，我开 IDE 给你，
之前也这样」* → *「**trae code 更新为 trae 了，搜索相关信息，确定新方案**」*。

---

## §1 三条路的裁定表

| 路 | 实测 | 裁定 |
|---|---|---|
| **A. TRAE CLI 2.0**（`traecli` / `traex.exe`） | 官方文档原话：**「TRAE CLI 会唤起企业用户登录页面」**；令牌页原文：**「套餐要求：旗舰版」**。MCP 层能起（`traecli` / `traecli-reply` 两个工具），但 `tools/call` 回 `isError: No Trae auth token available for Trae model fetch`。★★ 主控还试过**借 IDE 自己的登录态**：把 `~/.trae-cn/trae-jwt-token`（925 字节 JWT）塞进 `TRAECLI_PERSONAL_ACCESS_TOKEN` ⇒ `traecli models` 照出（**但那张表无令牌时也是同一张 ⇒ 不算证据**），真跑 `traecli exec "只回一个词：OK" --json` 回：`Error: Trae enterprise authentication required. Run traecli login before using TraeCode CLI.` ⇒ **连 IDE 的 JWT 都不认**（它要的是**企业版认证**，不是 IDE 登录态）。另：`app-server daemon` 是 **Unix-only**（Windows 直接报不支持） | **本机不可用**（三条子路都试过）；**配方留档**（§2） |
| **B. CDP 驱动 IDE 面板**（`tools/trae_pool.mjs`，卡 077） | ★ 该零件从没真跑过（`gates/diag/` 里零 `trae-*.jsonl`）。主控写 `~/.trae-cn/argv.json` 加 `remote-debugging-port` ⇒ 进程确实重启（21:27）、键还在、**端口就是不开**；改用启动参数 ⇒ **单实例锁**把参数吃掉（换 `--user-data-dir` 也起不来第二实例）。★ 但"端口开不开"与"面板页会重载"是两件事 —— **卡 218 实测：端口 9333 后来是通的**（`curl http://127.0.0.1:9333/json/version` 通），死因是**面板重载**（§4） | **放弃（不接进派活）**；**保留 + 文件头写结论**（§5） |
| **C. ★ 反向把我们的 `pool` MCP 挂进 Trae**（`.trae/mcp.json`） | 官方文档原话：**「TRAE 存储项目级 MCP Server 的目录是 `.trae/mcp.json`。TRAE CLI 可以读取和运行该目录下的 MCP Server」**。★ 卡 218 把"服务端这半"**验到能跑**：用仓里那份**故意独立实现**的客户端 `tools/mcp_client.py`，按配置里那条命令握手 → 协议 `2025-06-18`、服务端 `pool 1.0`、**14 个工具**（10 只读 + 4 写，每条 inputSchema 都自检通过，原样输出见 §3） | **★ 首选**（服务端已证；Trae 侧见 §3.3） |

---

## §2 路 A 的配方（**留档，不是现在做**）

本机跑不起来的原因只有一个：**缺企业版凭据**。真拿到凭据时照这个配：

1. **拿令牌**：旗舰版；企业版控制台 → 个人信息 → 访问令牌（形如 `trae-lt-…`）。
   落到环境变量 `TRAECLI_PERSONAL_ACCESS_TOKEN`。
2. **非交互跑一回合**：
   `traecli exec "…" --json --model <模型>`；续跑用 `traecli exec resume`。
3. **配置文件** `~/.trae/traecli.toml`：`model` / `approval_policy` / `default_permissions`，
   以及 `[mcp_servers.<名>]`（**这样 CLI 也能挂我们的 MCP**，与本卡 §3 的 C 路同源）。
4. **已知死路**（别重走）：`app-server daemon` 是 **Unix-only**（Windows 上直接报不支持）；
   **IDE 的登录态不能顶替企业版认证**（实测两次：`models` 表不算证据、`exec` 直接拒）。

★ 一句话：**A 不是"配置问题"，是"凭据问题"** —— 有旗舰版令牌就能立刻接。

---

## §3 路 C：验到哪一步（本卡核心）

### 3.1 服务端这半：**通**（独立客户端握手 + 14 工具）

用的是仓里**另写一遍**的客户端 `tools/mcp_client.py`（T-G78：不 import 本项目任何东西，
`jsonrpc` / `id` 类型 / `result` 与 `error` 互斥 / 每个工具的 `required` 必须真在 `properties` 里，
任何一条不成立就判**协议违规**）。命令（`-X utf8`；`POOL_MCP_WRITE=1` 才列写工具）：

```
python -X utf8 tools/mcp_client.py handshake   # → 协议版本 2025-06-18 · 服务端 pool 1.0 · 能力 ['tools']
python -X utf8 tools/mcp_client.py list        # → 共 14 个工具（每条的 inputSchema 都已自检通过）
```

`list` 的**原样输出**（节选到工具名，逐字）：

```
  pool_plan      只读   外包队列与冲突域：哪些卡能同批跑（只读，走 wb_plan.py plan）。
  job_list       只读   扫 gates/diag/wb-*.jsonl：在跑 / 已判决 / 断了（看 mtime/大小/有无判决）。
  job_status     只读   一张卡现在到哪了：时间线 + 仓库状态（只读，走 wb_status.py --repo）。
  job_result     只读   一张卡的判决与摘要**原文**（缺产物就说'没有'，截断会明示总长）。
  lock_status    只读   门禁锁：哪把、谁的、租约剩多久（只列不拿，走 gate_lock.py status）。
  pool_models    只读   号池可用模型：批准集 ∩ 可用集（读号池快照，只读、不联网）。
  quota_status   只读   额度四态（卡 201）：按「记录时间 vs 现实时间」判 —— 限流中 / 已过期，需重新探测 / 余额耗尽 / 未记录。只读，当场算，不探测。
  task_list      只读   任务栅栏现状：所有任务一行（任务号 / 状态 / 成送申请进度 / 一句话 why）。只读，不要 env。
  task_status    只读   一个任务的详情：每张卡的层与域、交没交、history 尾部。参数 task。只读，不要 env。
  task_pool      只读   待办登记表（还没定卡的活，按层）。只读，不要 env。
  pool_dispatch  写    派活：干跑守卫 → 先占树 → 起工人（--detach，立刻返回）。只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。
  pool_cancel    写    取消本机登记里那张卡的工人（先核对 pid 身份再动手）。只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于卡号。
  task_register  写    ★ 注册一个任务（预声明它需要哪些卡 / 每张卡属于哪层 / 各自域）。给 manifest_text（整段 TOML）或 manifest_path；只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于 TOML 里的 id。
  task_claim     写    ★ 一张卡交成送申请（success 必带证据；failed ⇒ 挡住收口）。只在服务端 POOL_MCP_WRITE=1 时可见；arguments.confirm 必须等于 task；碰了域外文件会被拒并点名。
共 14 个工具（每条的 inputSchema 都已自检通过）
```

> **补注（2026-11-10，卡 E111 / T-AG620）**：上面这段是当时的逐字输出，**不改**（改了就是伪造历史）。其中 `pool_models` 那句「号池可用模型：批准集 ∩ 可用集」已被卡 E107 / E109 推翻：交集**不是**派活允许集，今天派不派得出去要按池现算（判决、计数、允许集与探测命令现在也在机器块里）。
>
> **补注（2026-11-16，卡 E112 / T-AG621）**：这段逐字输出里 `quota_status` 那句「只读，当场算，不探测」仍然成立，
> 但**没说下一步怎么探**。现在工具在三态（已过期 / 余额耗尽 / 未记录）的人话段里直接念出那条命令，
> 并说明「探完四态未必变」；`can_dispatch` 也只有「限流中」才是 false，其余是 null（不知道）。

⇒ **`.trae/mcp.json` 里那条命令（`python -X utf8 <…>/tools/pool_mcp.py`）确实能起、能列 14 个工具。**
★ 注意：这一条是**服务端自证** —— 主控当天已经自证过一次，本卡用**另一个实现**再证一次，
但**它不等于"Trae 已经加载了它"**（见 3.3）。

### 3.2 schema：主控写的形状**是对的**（Trae 自己的代码就是权威）

从 Trae 自己的 bundle（`D:\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.solo-lite-slim.js`）
里挖出来的**权威形状**（原样片段）：

```js
static{this.H=[".trae"]}static{this.I=".trae/mcp.json"}
```

```js
async q(){this.b.clear(),this.a.clear();const e=this.h.getWorkspace().folders;
for(let t=0;t<e.length;t++){const s=e[t],n=L.joinPath(s.uri,".trae","mcp.json"),
r=`mcp.config.ws${t}.`,o=new fQ(n,"workspaceFolder",r,…);…
```

```js
var yGs={type:"object",allowTrailingCommas:!0,allowComments:!0,
properties:{mcpServers:{type:"object",description:"MCP server configurations",…}},…}
```

⇒ 三条硬结论：
1. Trae 认的路径就是 **`<每个工作区文件夹>/.trae/mcp.json`**（scope = `workspaceFolder`）；
   另有 user 级 `<settingsPath>/../mcp.json`（scope = `user`）。
2. 顶层就是 **`{"mcpServers": {"<名>": {…}}}`** —— 与主控推的写法**一致**。
3. ★★ **Trae 这份 mcp.json 允许注释**（`allowComments:!0, allowTrailingCommas:!0`）——
   所以"机器专有路径"这类说明**可以直接写在文件里**，不用另开文档。

⇒ **`schema` 不用改**：本卡最终形状 = 主控原样（见 §3.4）。改前 = 改后。

### 3.3 Trae 侧这半：**本会话没加载**（如实报，附读数）

四条读数（都在这台机器上现读到）：

1. ★ **本会话（Trae agent 面板）的可用工具里没有 `pool_*`**：用工具检索查 `pool_plan` / `job_list` /
   `task_claim` / 号池 等关键词，只回**内置**工具（WebSearch / Exec / GenerateImage…），**零个** `pool_*`。
2. `~/.trae-cn/mcps/` 下每个会话目录里只有 `solo_agent/integrated_code_mode/`（Trae **内置**的 code_mode
   服务），**没有** `pool` 这一支。
3. Trae 的 MCP 日志（`%APPDATA%\Trae CN\logs\<会话>\window1\mcp-servers-render.log`）在**今天 5 个会话**
   （`20261013T210820` / `212758` / `213722` / `220828` / `222624`，含本会话）里都是同一行：
   ```
   McpConfigService [PluginMcp] updatePluginMcpConfigs {"enabled":true,"globalCount":0,"projectCount":0,"projectServerCount":0,"serverNames":[]}
   ```
   ★★ **如实标注边界**：这一行的 tag 是 `[PluginMcp]` ⇒ 它数的是**插件带的** MCP，
   **不是** `.trae/mcp.json` 的直接读数（我核过源码：它就是 `updatePluginMcpConfigs` 那条）。
   所以它不是"工作区 MCP 一个都没加载"的机器判据，只是**旁证**。
4. ★ 本会话的 Trae 窗口，**工作区根下没有 `.trae/mcp.json`**：我的卡树 `.wt/traecli/.trae/`
   开工时是**空的**（本卡这一趟才把它建出来，见 §3.4）；主树那份（`engineering/.trae/mcp.json`）
   **不在窗口打开的那个工作区根下**。

**⇒ 我判断的原因（不是猜，是上面四条指向的）**：Trae 只在**打开工作区时**按
`getWorkspace().folders` 逐个扫 `<folder>/.trae/mcp.json`（3.2 的源码），
而**这个会话的工作区根下当时没有那份文件** ⇒ 没有 `pool`。
★ 另：Trae **没有**一个"热重载 MCP 配置"的命令行口（本卡也没找到可点的命令），
真要让它生效得**重开窗口**；★ 我**不许自己起 / 重启 Trae IDE**（卡的硬约束）⇒ **这一步没做**。

**⇒ 结论（一句话）**：**C 路的"服务端"这半通了（§3.1 + §3.2）；"Trae 侧加载"这半本会话没通，
卡在"配置不在窗口工作区根 + 需要重开窗口"** —— 要真通，人工两步：
① 把 `.trae/mcp.json` 放进**窗口打开的那个工作区根**；② **重开窗口**，然后在 MCP 面板 / `/mcp` 看
`pool` 与那 14 个工具在不在。

### 3.4 `.trae/mcp.json` 的最终形状（改前 / 改后）与"该不该进 git"

**改前**（主控在**主树**写的，`engineering/.trae/mcp.json`）：

```json
{
  "mcpServers": {
    "pool": {
      "command": "C:/Users/example\\miniconda3\\python.exe",
      "args": ["-X", "utf8", "D:/repo/engineering\\tools\\pool_mcp.py"],
      "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "POOL_MCP_WRITE": "1", "PYTHONUNBUFFERED": "1"}
    }
  }
}
```

**改后**（本卡在卡树建的 `.wt/traecli/.trae/mcp.json`）：**逐字节同上** ——
★ schema 经 3.2 核过，**不用改**；缺的是"把它放到窗口工作区根下"（§3.3），不是形状。

**该不该进 git：★ 应该入库。** 判据（现读）：
- `git check-ignore -v .trae/mcp.json` → **退出码 1**（**没被忽略**）；`git status --porcelain -- .trae` → `?? .trae/`。
  ⇒ 它是**可入库**的项目级配置，不是本机私有文件。
- ★ **但它含机器专有路径**（`C:/Users/example\miniconda3\python.exe` 与 `D:/docs\…`），
  换机就废 ⇒ **两条路**（都不用改 schema）：
  ① 入库 + **在文件里写注释**说明"这两处按本机改"（3.2 第 3 条：Trae 这份 mcp.json **允许注释**）；
  ② 把 `command` / `args` 换成变量形式 —— Trae 的预定义变量里有 `${workspaceFolder}`
     （bundle 里 `gzt` 那张表原样列着 `` `${cwd}` `` `` `${workspaceFolder}` `` …），
     但**"`.trae/mcp.json` 的 `command`/`args` 到底吃不吃变量替换"，本卡没验**（不猜）。
  ★ 本卡**没动** `command`/`args` —— 保持"主控自证过的那一份"，把选择权交回主控。
- ★ 顺带（**本卡没做**）：主树那份目前是**未跟踪**状态；要不要**替主树也入库**、用①还是②，属于
  "口径"，交主控收口。

---

## §4 路 B：第 1 次真派卡是怎么死的（原样证据）＋ 本卡补的**重连**

### 4.1 原样证据

**症状**：驱动进程提前退出，Node 报
```
Warning: Detected unsettled top-level await at file:///D:/…/tools/trae_pool.mjs:400
await main()
```
（`main()` 的 Promise 永远没 settle ⇒ 事件循环空掉 ⇒ Node 直接退出。）

**`gates/diag/trae-218.jsonl` 原样节选**（第 1 次派活那趟，36 行 poll，**没有 `done` 收尾**）：
```
{"ev":"connect","port":9333}
{"ev":"balance","value":null}
{"ev":"send","promptLen":5395}
{"ev":"poll","sec":3,"turns":6,"lastLen":9,"busy":true,"done":false}
…（中间省略）
{"ev":"poll","sec":30,"turns":6,"lastLen":23,"busy":false,"done":false}
{"ev":"poll","sec":33,"turns":6,"lastLen":9,"busy":true,"done":false}
…（一直到 sec=100 都还没有 done）
```

**主控当场取证四条（指向同一根因）**：
1. **CDP 目标变了**：第 1 次 target `title=Agent`；出事后 `title=` 空、url 直接当标题 ⇒ **面板页重载/跳转**；
2. **端口持有者换 pid**：`9333` 的所有者从 `5692` → `22340`；
3. **截图变空白**：同一时刻 `Page.captureScreenshot` 只 **11 KB**（正常 133 KB）；
4. 树里**零产出**（只有主控种进去的 `trae_pool.mjs` 与规格副本）。

**根因**：这条驱动对**页面重载 / 目标更替零韧性** —— WS 一断，`poll` 里那个 `await` 永远不 settle；
而**没有任何东西保持事件循环存活** ⇒ Node 退出；**任务在面板里可能还在跑，驱动却已经死了**。

### 4.2 已经做完的 5 处（★ 别重走，也别推翻）

1. `findWorkbench` 的 URL 过滤：老代码只认 `workbench`，新版面板是 **`solo-lite.html`**
   ⇒ 改成两代都认（`workbench` 或 `solo-lite`）。★ 实测：改前报「连不上 CDP」，
   而 `curl http://127.0.0.1:9333/json/version` **明明是通的**。
2. `SEL_AGENT`：新版 agent 的回答落在 **`.core-finish-card`**（实测链路
   `p.markdown-p` → `.markdown-renderer` → `.core-finish-card__summary` → `.core-finish-card`）
   ⇒ 改成 `.turn__agent-message, .core-finish-card`（两代都认）。★ 只认老那个时 `--out` 会抽到界面文字
   （真抽到过「TRAE / 思考过程 / 由 AI 生成」）。
3. `APPROVE_RE` **收紧**成授权框专有文案：老写法含「继续 / 确认 / 允许 / Run」这类**通用词**，
   会把界面上的**快捷回复芯片**（"好的，执行吧"）当按钮点掉 ⇒ **那句话被当成用户消息发了出去**
   （截图实证：它出现在**用户侧**气泡，agent 回了一句「目前没有待执行的任务…」）。
4. 授权候选**只扫真按钮**（`button,[role=button],a`）并**排除**输入区 / 会话列表。
5. `Cdp.send()` 原来**只有 resolve 一条路**（没 reject、没超时）⇒ 主控改成：① 构造时挂
   `ws.onclose/onerror`，断线把 pending **全部拒绝**（回 `{__closed}` 哨兵，`eval` 翻成可读异常）；
   ② `send` 加 **30 秒超时**兜底。
   ★ **教训（踩过）**：模板串里的注释**不许出现反引号**（主控在 ③ 的注释里用了反引号，
   把模板串提前闭合、`node --check` 报 229 行语法错）。

★ 另一次实测已通（`gates/diag/trae-218.r2.jsonl`，即"第 2 次派活"）：
`send` → 面板真跑起来 → `--out` **一字不差**取回 agent 的回答 —— 那次模型自己把 **PONG 答成了 PORT**。

### 4.3 本卡（卡 218）接着做的：**把"断线"从"可读的失败"升级成"重连"**

改的是 `tools/trae_pool.mjs`（白名单内，**不推翻**上面 5 处）：

- **`Cdp.markDead(why)`**：把原来构造函数里那个闭包 `fail` 提成方法，并记下 `deathWhy` ——
  断线后**能被调用方看见**（"为什么死的"）。
- **`attach()` 的 WS-open await 加退路**：原来只挂 `onopen`/`onerror`，
  而"连上又立刻被关"（面板正在重载）会让 `onerror` 永远不来 ⇒ 又是挂死。
  现在加 **15 秒超时** + `onclose` 兜底，**任何一条路都 settle**。
- **`cmdSend` 的 `ensureCdp()`**：每一拍先看连接死没死；死了就
  **重读 `/json/list` 找 `solo-lite` 目标 → 重连**（`findMs` 放宽到 15 秒，面板刚重载时 2 秒太短），
  断线 / 重连**都落进 JSONL**（`{"ev":"disconnect"} / {"ev":"reconnect","ok":…}`）。
- **重连后"接着判完成"**：面板重载会把 agent 轮次数冲掉 ⇒ 重连过之后不再要求"出现新轮次"，
  改成 **"非空回答 且 连续 2 拍 `!busy && sendDisabled===true`"**。
- **连不上就明说**：连续 6 拍连不上 ⇒ `{"ev":"lost"}` + 退 3，stdout 打 `LOST`；
  **不再**是 Node 的内部警告。发指令那一刻断线 ⇒ **不重发**（会重复提问），如实退 3。
- **顶层兜底**：`await main().catch(…)` ⇒ 任何没接住的异常都变成**一行可读的失败 + 退出码 3**。

★ 边界（如实）：**重连这条路本卡没有机会实测**（要真把面板打断一次才看得到）——
它的判据是"每一拍都有结论、进程不再因 unsettled await 而死"，这一点由 4.2 第 5 条 + 本节兜底保证。

---

## §5 卡 077 那个零件（`tools/trae_pool.mjs`）的裁决

**裁①：保留 + 在文件头写结论与日期**（不另开卡删它）。理由：
- 这条道**唯一**的"活用法"是"主控遥控 Trae 面板"（**本卡就是这么被派出去的**）——真删了，
  下次要在面板里跑东西又得从零写；而它的死因（面板重载）**半天就能修**（本卡已经修了一半）。
- 本仓最恨的是"建了却零接线" —— 那就**把结论写进文件头**，让它**有接线、也有交代**。

**写进文件头（`tools/trae_pool.mjs`）的原文**（节选，完整在文件里）：

> ★★ 卡 218（2026-10-13）当场裁决 —— **① 保留 + 就在这里写下结论**（不另开卡删它，不装作没这回事）：
> 本机实测这条道**不可用于派活**：面板页会**重载 / 目标更替**……
> 第 1 次真派卡（`gates/diag/trae-218.jsonl`）就是这么死的……
> 取证四条（同日，指向同一根因）：① CDP target 从 `title=Agent` 变成 `title=` 空、url 当标题；
> ② 端口 9333 的所有者 pid 从 5692 → 22340；③ 同一时刻 `Page.captureScreenshot` 只 11 KB（正常 133 KB）；
> ④ 树里零产出。
> ⇒ 卡 218 就地补了**断线重连**（`Cdp.markDead` + `cmdSend` 的 `ensureCdp`）……
> ★ 但这条道**仍不接进派活**：首选是**反向**把我们的 `pool` MCP 挂进 Trae（`.trae/mcp.json`，
> 不需要任何登录）—— 三条路的实测与证据见 `复盘/Trae-接入结论.md`。

★ **另需主控收口的一条**（本卡只记结论，不做）：`tools/trae_pool.mjs` 在**每一棵卡树里都有一份拷贝**
（`.wt/*/tools/trae_pool.mjs`，几十份），要统一结论的话得在主树收口一次（卡树里的那些按规矩不动）。

---

## §6 进账：让 Trae 这条道被**现有账**认出来（新工具）

**新零件**：`tools/pool/trae_dispatch.py`（+ 它的测试 `tests/test_trae_dispatch.py`，7 个用例全过）。
它补的正是"建了却零接线"那个洞 —— 这条道的日志原本叫 `trae-<卡>.jsonl`，
而**整仓的账**认的是另一套名字：

| 现有账 | 认什么 | 本工具怎么接 |
|---|---|---|
| 租约（`pool.registry`） | `gates/diag/pool-registry.json`：树 / 域 / owner | `start` → `registry.reserve(...)`（**守卫照走**，本模块不重写判据） |
| 工人日志（`pool.jobs.scan_jobs`） | `gates/diag/wb-<卡>.jsonl` | `start` 写 `system/init` 开场；`finish` 写 `assistant`（`--out` 原文）+ `result` 收尾 |
| 判决（卡 215 的 `wb_watch` / `scan_jobs`） | `gates/diag/wb-<卡>.verdict.txt` | `finish` 落判决（形状照 `wb-215.verdict.txt`），`scan_jobs` 立刻判「已判决」 |

用法（三个子命令对着这条道的真实生命周期）：

```
python -X utf8 tools/pool/trae_dispatch.py start  --card 218 --tree .wt/traecli \
    --files .trae/mcp.json,复盘/Trae-接入结论.md --task T-G331 --pool trae --model "DeepSeek-V4.1-Flash Max"
python -X utf8 tools/pool/trae_dispatch.py finish --card 218 --exit-code 0 \
    --answer-file gates/diag/trae-218.r2.out.md --session-id <会话号> --release
python -X utf8 tools/pool/trae_dispatch.py status --card 218      # 只读
```

★ **边界（如实写）**：① **不 import / 不改 `tools/wb_dispatch.py`**（那是卡 215 的域）；
② 本卡**已有活租约**时 `start` 只**沿用**、不第二次 `reserve`（否则 `tree_guard` 会判"自己占自己"）；
③ **日志不许覆盖**（与 `pool.guards.log_guard` 同口径）—— 要跑第二轮就换 `wb-<卡>.r2.jsonl` 这种新名字；
④ 本工具**不起任何子进程**（不涉及 NO_WINDOW）。
★ **没验到的一条**：卡 215 的 `tools/wb_watch.py` **不在本树**（本树只有 `wb_dispatch.py`）——
所以"`wb_watch` 认不认这份判决"**是按文件命名口径推的**（`wb-<卡>.verdict.txt`，与 `scan_jobs` 同一处判据），
**没有**跑 `wb_watch` 实测。卡 215 收口时用它真跑一次即可。

---

## §7 给下一个窗口的清单（不必重走）

1. **别重走 A**：本机不可用，是**凭据**问题不是配置问题；配方在 §2。
2. **别重走 B 的"端口不开"**：端口 9333 能开（`curl …/json/version` 通）；
   这条道死在**面板重载**，`trae_pool.mjs` 已补重连（§4.3），但**不接进派活**。
3. **首选 C**：`.trae/mcp.json`（形状已核 = 主控原样）。要让它真生效就两步：
   **放到窗口工作区根 + 重开窗口**，然后在 MCP 面板 / `/mcp` 数 `pool` 的 14 个工具。
4. **要机器判据**别信 `[PluginMcp]` 那行日志（它数的是插件 MCP，§3.3 第 3 条）。
   真要判"工作区 MCP 加载了没"，看**agent 面板的可用工具里有没有 `pool_*`**。
5. 两条**交主控收口**的口径题：① `.trae/mcp.json` 入库时 `command`/`args` 用绝对路径（+文件内注释）
   还是 `${workspaceFolder}`；② `tools/trae_pool.mjs` 在几十棵卡树里的拷贝要不要统一。

---

## §8 本卡的验收读数（**原样**，别信转述）

全部在 `.wt/traecli` 里现跑现贴：

```
$ python -X utf8 tools/wb_plan.py check
…
[OK ] backlog 校验通过：99 张卡，无冲突（基点 64d9d02）
[队列] 待派 8 张 / 其它 91 张（★ 只有待派的参与冲突判定与排批）
（退出码 0）

$ python -X utf8 -m ruff check src/ tests/ scripts/ tools/ examples/ harness/
All checks passed!
（退出码 0）

$ node --check tools/trae_pool.mjs
（退出码 0）

$ python -X utf8 -m pytest tests/test_trae_dispatch.py -q --no-cov
.......                                                                  [100%]
（退出码 0；7 个用例）

$ python -X utf8 tools/mcp_client.py list          # 服务端那条命令，独立客户端
共 14 个工具（每条的 inputSchema 都已自检通过）
（退出码 0）

$ python -X utf8 tools/pool/trae_dispatch.py status --card 218
卡 218 的 Trae 道现状 —— 读 D:/repo/engineering/gates/diag：
  活租约：1 条
    · 树 .wt/traecli｜pool=trae｜owner=DEV-HOST:16688｜at=2026-10-13T22:27:51｜log=…\gates\diag\trae-218.r2.jsonl
  工人日志：没有（还没跑 start）
（退出码 0）
```

★ **交申请那一趟（原样回话）**：

```
$ python -X utf8 tools/wb_task.py claim B-20261016 218 --claim success --why "…" --evidence "…" --files "…"
✗ BatchError：没有这个任务的预声明：D:\…\gates\diag\batch\B-20261016.toml（先 `register`）
（退出码 2）
```

⇒ **`B-20261016` 这个任务本机还没注册**（`gates/diag/batch/` 里只有 `B-20261013/14/15`）。
★ 本卡**没有**替主控 `register`（注册任务 = 口径，且 `gates/diag/batch/` 不在本卡白名单里）——
**卡 218 的成送申请等主控先注册 `B-20261016` 再交**。

