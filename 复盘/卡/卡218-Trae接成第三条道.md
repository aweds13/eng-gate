# 卡 218 —— **把 Trae 接进管线**（MCP 反向接入为主；CLI 为备）（T-G331）

**树**：`.wt/traecli` ｜ **base**：主控派活时的主树 HEAD ｜ **提交**：★ 不要 commit
**成员号**：`B-20261016` 的 **M-1**。★ 干完交申请：
`python -X utf8 tools/wb_task.py claim B-20261016 218 --claim success --why "…" --evidence "…" --files "…"`

## 来路（主控 2026-10-13 实测 + 官方文档，**全部可回查**）

用户令：*「不是 pool 还有 trae 吗，用那个」* → *「登陆不了，要企业版，我开 IDE 给你，之前也这样」*
→ *「**trae code 更新为 trae 了，搜索相关信息，确定新方案**」*。

**产品事实**（2026-10-10 新闻）：**TraeWork 与 TraeCode 已合并为全新 TRAE**
（Agent 模式 / IDE 模式，桌面 + Web + 移动端，灰度推送中）。

**三条路的实测结论（★ 别再重走）**：

| 路 | 实测 | 裁定 |
|---|---|---|
| **A. TRAE CLI 2.0**（`traecli` / `traex.exe`） | 官方文档原话：**「TRAE CLI 会唤起企业用户登录页面」**；令牌页原文：**「套餐要求：旗舰版」**。本机现跑 `trae-cli mcp-server` 的 MCP 层**能起**（2 个工具 `traecli` / `traecli-reply`），但 `tools/call` 回 **`isError: No Trae auth token available for Trae model fetch`**。★★ **主控随后还试了「借 IDE 自己的登录态」**：`~/.trae-cn/trae-jwt-token`（925 字节 JWT）塞进 `TRAECLI_PERSONAL_ACCESS_TOKEN` ⇒ `traecli models` 照出（**但那张表无令牌时也是同一张 ⇒ 不算证据**），而真跑 `traecli exec "只回一个词：OK" --json` 回 **`Error: Trae enterprise authentication required. Run traecli login before using TraeCode CLI.`** ⇒ **连 IDE 的 JWT 都不认**（它要的是**企业版认证**，不是 IDE 登录态）。另：`app-server daemon` 是 **Unix-only**（Windows 上直接报不支持） | **本机不可用**（三条子路都试过）；**配方留着**（见 §2） |
| **B. CDP 驱动 IDE 面板**（`tools/trae_pool.mjs`，卡 077） | ★ 该零件**从没真跑过**（`gates/diag/` 里零 `trae-*.jsonl`）。主控写 `~/.trae-cn/argv.json` 加 `remote-debugging-port` ⇒ **进程确实重启了（21:27）、键还在、端口就是不开**；改用启动参数 ⇒ **单实例锁**把参数吃掉（换 `--user-data-dir` 也起不来第二实例） | **放弃**（`trae_pool.mjs` 文件头自己写着「**脆**：全是 UI 自动化」） |
| **C. ★ 把我们的 `pool` MCP 挂进 Trae**（反向） | 官方文档原话：**「TRAE 存储项目级 MCP Server 的目录是 `.trae/mcp.json`。TRAE CLI 可以读取和运行该目录下的 MCP Server」**。主控已写 `.trae/mcp.json` 并用**配置里那条命令**自证：起得来、**14 个工具**（10 只读 + 4 写） | **★ 首选**（**不需要任何登录**） |

## 要做的事

### 1. ★ 把 C 这条路**验到能跑**（本卡的核心）

`.trae/mcp.json` 主控已写好（`{"mcpServers": {"pool": {command, args, env}}}`），**但那个 schema 是主控按通行写法推的、没在 Trae 里验过**。
- 请**在 Trae 里验一次**：用它的 MCP 面板 / `/mcp`，看是否列出 `pool` 与那 14 个工具。
- ★ **schema 不对就照 Trae 实际要的形状改**（它自己写的配置就是权威）—— 把**改前/改后**贴出来。
- ★ **验不到就如实报**（哪一步、原样报错），并**给出结论**：这条到底通不通。
- ★ **顺带查清**：`.trae/mcp.json` 该不该进 git（是项目级配置 ⇒ 倾向**入库**；若含机器专有路径要说明）。

### 2. 把 A 那条路的**配方**写下来（不是现在做，是留档）

- `TRAECLI_PERSONAL_ACCESS_TOKEN=trae-lt-…`（**旗舰版**；企业版控制台 → 个人信息 → 访问令牌）
- 非交互：`traecli exec "…" --json --model <模型>`；续跑：`traecli exec resume`
- 配置文件：`~/.trae/traecli.toml`（`model` / `approval_policy` / `default_permissions` / `[mcp_servers.<名>]`）
- ★ 写进文档，**别只写在回报里**。

### 3. 新 `复盘/Trae-接入结论.md`（**本卡的真交付**）

把上面那张表 + 三条路的**原样证据**（命令与报错）写进去，让下一个窗口**不必重走**。
★ 特别写清：**哪些路死、为什么死、哪条活、活的怎么用**。

### 4. 卡 077 那个零件怎么办（**明确裁决**）

`tools/trae_pool.mjs`（CDP 那条）本机不可用。
- ★ **二选一并说明**：① 在文件头加一段**结论 + 日期**（"本机实测不可用，原因…"）后保留；② 或**另开一张卡**删它。
- ★ **不许**什么都不写就留着 —— 那正是本仓最恨的"建了却零接线"。

## 硬约束

- ★ `python -X utf8 tools/wb_plan.py check` 退 0（贴尾行）；**必须跑 `ruff`**。
- ★ 不许 commit / tag；不许跑全量门禁。
- ★ **不许改 `tools/pool_mcp.py`**（它已经能跑，自证过 14 工具）；不许放松任何既有判据。
- ★ **不许自己去起 Trae IDE**、**不许自己跑 `traecli login`**（要凭据）。
- 白名单：`.trae/mcp.json` · `复盘/Trae-接入结论.md`（新建） · `tools/trae_pool.mjs` · `harness/README.md`

## 验收（照这个报）

1. `wb_plan.py check` 尾行（退 0）；
2. ★★ **C 路的验证读数**：Trae 里到底列没列出 `pool` 与那 14 个工具（原样文本）——**不通就写不通**，并给出你判断的原因；
3. `.trae/mcp.json` 的**最终形状**（改前改后）；
4. `复盘/Trae-接入结论.md` 的**成稿**（三条路 + 证据 + 配方）；
5. ★ 对卡 077 那个零件的**裁决**（①还是②）+ 写进文件头/回报的原文；
6. `ruff` 尾行；
7. 成送申请命令与回话。
