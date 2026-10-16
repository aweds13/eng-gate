# DSH 插件 —— 可抄清单（按我们的方面，2026-10-15 取证）

> 材料来源：市场精选 137 条（`_refs/dsh/shortlist-curated.json`）里挑出来的**同型实现**，README 已抓到
> `D:/repo/_refs/dsh/plugins/*.md`。每条都带**原样出处**；抄的是**机制**，不是抄代码。

## 一、★ 立刻能用在我们身上的四条（UI/形态）

| # | 机制 | 原样出处 | 用在我们哪 | 抄什么 |
|---|---|---|---|---|
| 1 | **一个插件同时占三种座位**：官方左栏面板座位 = `sidebar.panellist` + `main`（**图标带角标**）· 官方右栏页签 = `sidebarRight.tabs` + `sidebar.right.pane.tab` · 侧栏页签（装了 `dsh-better-sidebar` 才注册） | `plugins/workbench.md` 第 197~199 行逐字 | 我们的三行（工作台/禅道/timeflow） | 除左栏外**再挂右栏页签** ⇒ 对话留在中间、目标页在右手边 ✓；角标可以显示"待我审/未读数" |
| 2 | ★ 宿主**有右栏服务才注册**：`ctx.get('sidebarRight')` 返回 undefined 就跳过 | `workbench.md` 第 202 行逐字 | 我们要兼容不同 profile | 座位注册前先 `ctx.get(...)` 探服务，**没有就如实不注册**（不求全） |
| 3 | **清单三件套**：`dsh.bundle.patch` + `dsh.client.platform` + **`dsh.engines.dsh`** | `workbench.md` 第 261 行逐字（`├── package.json # dsh.bundle.patch + dsh.client.platform + dsh.engines.dsh`） | 卡 242 正在加前两件 | ★ 补上 **`dsh.engines.dsh`**（引擎版本范围）——这是核心会读的兼容字段 |
| 4 | **图标用 SVG 文件**：插件自带 `docs/icon/icon.svg`；`dsh-ops` 用 `icon.svg` 36×36、单色描边 `#7C7C82`、线宽 2.4、圆头，并在 `package.json.icon` 与 `dsh-plugin.json` 的 `contributes["x-display"][0].icon` 各指一次 | `plugins/widgets.md` 第 8 行；`dsh-ops-main/icon.svg` 头两行 | "左栏三个图标好丑" | 内联 SVG（`currentColor`）+ 包内 icon 文件；**线宽/圆头照它** |

## 二、我们要学习/对照的同型实现（按方面）

| 我们的方面 | 对照插件（repo） | 它的做法（README 原样要点） | 抄什么 / 不抄什么 |
|---|---|---|---|
| 工作台六块读数（`pipeline_view.py`） | **dsh-widgets**（`Physicolor/dsh-widgets`） | 会话右侧**组件栏**：55 个内置单元覆盖「会话轮次·步数 / 上下文水位 / token 与缓存 / 工具调用 / **后台任务 / 子代理** / 额度」；`manifest.json` 是**机器可读的单元清单**（id/order/group/builtin/defaultInstalled/sizes/locale + 可选 `source`/`skeleton`）；单元 `render()` 是**纯数据** | 抄"单元清单 + 纯数据 render"这套：我们的六块也该有一份机器可读清单；★ 但它靠 `conversation.*` 槽位（聊天子树），**我们是仓库/流程面** ⇒ 槽位别照抄 |
| 门禁与升级安全 | **dsh-plugin-gating-hub**（`Noob-stupid/dsh-plugin-gating-hub`） | 升级前**契约预检** + 配置备份 + **整树回滚点**，失败自动回滚；"加载不了的插件**有确证证据才自动禁用**" | ★ 抄"证据不足就不动手"的口径（和我们"缺数据如实说/不许假装"同源）；它的 `dsh.engines` 兼容判据可对上我们的 `compat` 想法 |
| 交付纪律（"只做完一部分就报完成"） | **dsh-completion-guard**（`GreenLv/dsh-completion-guard`） | 长任务里**会话恢复后继续核对关键条件与完成依据**，防止部分完成被报成整体完成 | ★ 与我们的"验收=真读数/先红后绿"同问题；可对照它的"完成依据"字段设计我们的验收模板 |
| 工作台时间轴 + 技能库 | **dsh-workbench**（`liiydong/dsh-workbench`） | 左栏图标 + 右栏页签 + 主区域面板；把"AI 改 Markdown → 生成 Word/PDF/Excel → 你审这一版"做成**看得见的时间轴**，可停主区域或右栏 | ★ 座位组合照抄（见 §一.1）；它是文档流，我们是**卡/门禁流** ⇒ 时间轴的数据源换成我们的门禁/判决 |
| 额度与用量 | **dsh-usage-panel**（`AlfredChaos/dsh-usage-panel`） | 设置页 token 用量统计：**与侧边栏会话列表同口径**、热力图、按模型堆叠、Top 会话、provider 分布，JSON/CSV 导出；"投影增量聚合、只读重算" | ★ "同口径"正是我们反复咬的"不许第二份真源"；抄它的口径声明方式 |
| MCP 管理 | **dsh-plugin-hub**（`wingsky-1/dsh-plugin-hub`） | **按工作目录**维护项目级/全局两级 MCP 配置（项目级随仓库走、可提交 git）；模型面固定两个原子工具（`ws_mcp_search`/`ws_mcp_call`）按会话 cwd 路由 | ★ 对照我们的 `pool_mcp.py`（我们写工具默认不列 = 存在性即授权）；它的"两原子工具 + cwd 路由"值得抄 |
| 任务/待办 | **dsh-ticktick**（`PerryLink/dsh-ticktick`） | 会话头部任务面板（筛选/搜索/拖拽排序）+ 十一个工具 + 设置卡片，走官方 MCP 端点 | 对照我们的 `timeflow_inbox`；它把"外部任务源"做成面板 ⇒ 与我们"直接跳真实页面"互补 |
| 记忆层 | **dsh-ltm**（`tr1v3r/dsh-ltm`） | 本地 SQLite 结构化长期记忆：**CJK 感知**检索、BM25 + 字符 n-gram 余弦混合重排、去重/更新/合并/确认/过期复核、全局与项目两级作用域 | 对照我们的 `复盘/` 与记忆守卫；CJK 检索那块对我们中文语料直接有用 |
| 跨会话协作 | **dsh-team-rooms**（`PerryLink/dsh-team-rooms`） | 跨独立会话的持久共享房间：消息总线 + **共享任务板** + 时间线 | 对照我们的"卡 + 栅栏"；共享任务板＝我们的 workbacklog |
| ★ **让 agent 有手（驱动真实浏览器）** | **dsh-pilot**（`guo6x/dsh-pilot`，23★） | 原话：*"Drive a real browser from the DSH chat: the agent opens pages, reads them as structured text with a numbered element list, clicks and types **by ref** (no CSS guessing), presses keys, navigates back/reload, waits, evaluates JS, and takes screenshots — while you watch a live draggable **cockpit panel** … and can take over at any time"*；零运行时依赖、**CDP** over Node≥22 WebSocket、用现成 Edge/Chrome；ref 失效会**响亮失败并给提示**；装完侧栏底部出现 ✈️ | ★ 与我们自己的 Trae/CDP 道**同源**：禅道整站不只能"看"，还能被**点着走**（点菜单/填表单/截图当证据）；cockpit 那种"实时截图 + URL + 动作日志 + 会话切换"是我们"直接跳"之外的第二种形态；"stale ref 响亮失败"照抄我们的"缺什么说什么" |
| ★ 深链/地址栏（**已补读正文**） | **dsh-url-router**（`DDDMUC/dsh-url-router`） | 原话（中文版）：*"每个界面都有自己的链接：地址栏写着屏幕上的东西，链接点开就是那个界面"*；映射表逐字给出 **`#/panel/<panelId>` → `layout.selectPanel(id)`**（就是我们在用的座位机制 ✓），还有 `#/session/<id>`、`#/panel/plugins/<包名>`、`…/<包名>/<组件 id>`；它是**地址栏的唯一写者**、**只用 `replaceState`**（不往后退栈塞历史）、路径与查询串（`?token=…`）原样保留、**只有浏览器半、零依赖、无宿主路由、无遥测**；装法 `dsh plugin --profile web add dsh-url-router` ✓ | ★ 与 `openResource`（在右栏开一个真实网页）**互补**：它解决"**把界面状态变成一条可分享/可点开的链接**" ⇒ 我们那三行可以两条都上：点＝`openResource(url)` 开真实页面，**右键/贴链接＝用 URL 直接回到那个界面**；"唯一写者 + replaceState"这条纪律照抄（别多处改 URL） |

## 三、★ 生态给的两条"反面/提醒"

1. **`link:` 装法在生态里是合法的开发用法**（`workbench.md` 第 184~185 行逐字："从本仓库源码安装（link: 方式，改源码只需重启宿主）"）—— 我们昨天踩的坑**不是 link: 本身错**，而是**我们的宿主半裸导入了 `@deepseek-ai/dsh-tools`**、而链接目标的真路径够不到 DSH 的 node_modules ✗。⇒ 若要长期用 `link:`，**把宿主半的裸导入去掉或自备 node_modules**，别改判据。
2. **"装完必须重启"是生态共识**（`workbench.md` 第 191 行逐字："客户端 bundle 在组合阶段被快照进内存，刷新页面不够"）⇒ 我们那边"面板要重启才看得见"的说法与生态一致 ✓，不是我们的缺陷。

3. ★★ **装法对照（2026-10-15 实测，两条路不一样，别混）**：
   - **registry 包**（`dsh plugin --profile desktop add dshmarket`）⇒ 装完**自动进 `dsh.profile.bundles`** ✓、包自带补丁层立刻生效 ✓（实测：`bundles` 里自动多了 `dshmarket`；合成结果里出现 `- id: dsh-market / name: dshmarket` ✓）；
   - **`file:` 本地目录包**（我们那块面板）⇒ **只进 `dependencies`，不进 `bundles`** ✗ ⇒ 包自带的那层 patch **根本不会生效** ✗，必须**手工**把它加进 `dsh.profile.bundles`（本次已做，`package.json` 与 `cordis.patch.yml` 各留 `.bak-before-bundle-*` 备份 ✓）。
   ⇒ **本地包要自己补 bundles 这一步**；给别人的安装说明必须写清，否则对方会觉得"装了没反应" ✗。

## 四、★ 短名单**实况核验**（2026-10-15，`gh api repos/<o>/<r>` + raw 取清单；读数落在 `_refs/dsh/shortlist-verified.json`）

| 仓 | ★ | 最近提交 | 许可 | `dsh` 声明 |
|---|---:|---|---|---|
| `Noob-stupid/dsh-plugin-gating-hub` | **101** | 2026-10-15 | MIT | **bundle+client** ✓ |
| `hyzyn/dsh-plugin-kit` | **49** | 2026-10-13 | Apache-2.0 | bundle ✓ |
| `PerryLink/dsh-claude-move` | 28 | 2026-10-12 | Apache-2.0 | bundle+client ✓ |
| `wingsky-1/dsh-plugin-hub` | 24 | 2026-10-12 | MIT | ★ **无**（多半是 monorepo：清单在子包里，我的探法是看根清单 ⇒ 我方探法粗糙 ✗，不是它不合规） |
| `PerryLink/dsh-output-styles` | 14 | 2026-10-12 | Apache-2.0 | bundle+client ✓ |
| `Sivan757/dsh-agent-plugins-market` | 13 | 2026-10-14 | MIT | bundle+client ✓ |
| `AlfredChaos/dsh-usage-panel` | 12 | 2026-09-15 | MIT | bundle+client ✓ |
| `Physicolor/dsh-widgets` | 5 | 2026-10-14 | MIT | bundle+client ✓ |
| `zbsph/dsh-ppt-studio` | 5 | 2026-09-30 | MIT | bundle ✓ |
| `PerryLink/dsh-ticktick` | 4 | 2026-10-12 | Apache-2.0 | bundle+client ✓ |
| `PerryLink/dsh-team-rooms` | 3 | 2026-10-07 | Apache-2.0 | bundle+client ✓ —— ★ **已 archived** ✗（别抄一个停更的） |
| `Nath-Vikky/dsh-codekin` | 2 | 2026-10-05 | MIT | bundle+client ✓ |
| `zhy5/dsh-wx-bridge` | 1 | 2026-09-27 | MIT | bundle+client ✓ |
| `liiydong/dsh-workbench` | 0 | 2026-10-11 | MIT | bundle+client ✓ |
| `GreenLv/dsh-completion-guard` | 0 | 2026-10-15 | Apache-2.0 | bundle ✓ |
| `Link-h1j/dsh-screen-capture-record-desktop` | 0 | 2026-10-02 | MIT | bundle+client ✓ |

**三条结论（照收，别当花絮）**：
1. ★ **协议合规是常态**：16 个里 **15 个声明了 `dsh.bundle`**（有 UI 的还带 `dsh.client`）⇒ **我们采用的形态就是生态的通行形态** ✓（这条是对 §一.3 的最强佐证）。
2. ★ **星级不是质量代理**：`gating-hub` 101★ 与 `completion-guard` 0★ 都是**当天还在提交**的活项目 ⇒ 选型要看"是否活跃 + 是否对得上我们的问题"，别按星排 ✓（市场列表自己也这么写：*"This list doesn't rank plugins or judge their quality"*）。
3. ★ **两处要当心**：`dsh-team-rooms` **已 archived** ✗（停更）；我的"是否声明 `dsh`"探法**只看了根清单** ⇒ monorepo 会被误判为"无" ✗ —— 结论里凡"无"都要再核子包。

## 五、下一步（卡/改造建议）

| 建议 | 归属 | 状态 |
|---|---|---|
| 面板补 `dsh.bundle.patch` + 包内 `cordis.patch.yml` | 卡 242 | 正在做 ✓ |
| ★ 补 `dsh.engines.dsh`（§一.3） | 卡 242 之后的小改 | 待开 |
| ★ 三行**再加右栏页签**（`sidebarRight.tabs` + `sidebar.right.pane.tab`）+ 角标（§一.1/2） | 新卡（等 242 落地后开，避免同文件相撞） | 待开 |
| 六块读数补一份**机器可读单元清单**（照 dsh-widgets 的 `manifest.json` 形状） | 新卡（`tools/pipeline_view.py` 是别人域） | 待开 |
| 图标：内联 SVG + 包内 `icon.svg/png`（36×36、`#7C7C82`、2.4、圆头） | 卡 242 | 正在做 ✓ |

## 六、★ 定点深读（第一批，2026-10-15）：两个"唯一同型"候选的实现要点

> 依据：对抗复核（`gates/diag/_trae_review.md` §五）推荐的两个候选，**已抓源码逐文件读** ✓
> 仓：`_refs/dsh/dsh-session-diff-main/`（v 已解包）· `_refs/dsh/dsh-deepseek-web-relay-main/`

### 6.1 右栏页签的**正解**：服务名是 `sidebarRightTabs`（不是 `sidebarRight` ✗）

`dsh-session-diff-main/src/80-apply.js` 逐字（`:12` 与 `:65-72`）：

```js
const inject = ["slots", "locale", "sidebarRightTabs", "remote", "remote.workspaceFiles",
                "uiConversation", "sessions"];
…
ctx.effect(() => ctx.sidebarRightTabs.register(fileTabDefinition()), "… file tab type");
ctx.effect(() => ctx.sidebarRightTabs.register(changesTabDefinition()), "… changes tab type");
ctx.slots.inject("sidebar.right.pane.tab", () => ctx.slots.register(
    { name: "sidebar.right.pane.tab", key: FILE_TAB_ID, locale: NS }, SessionDiffFileBody));
```

★ **主控对抗核验过复核给的 `keepMounted` 引用（核心逐字，2026-10-15）**：
```js
// @deepseek-ai/dsh-client-ui-sidebar-right/lib/client.js:5522
const retained = seat === "sidebar.right.pane.tab" && definition?.keepMounted === true;
// 同文件 :5698
keepMounted: (tab) => types.find((type) => type.kind === tab.kind)?.keepMounted === true
// lib/types/client/tab-registry.d.ts:89
readonly keepMounted?: boolean;
```
⇒ **它恰好作用在 `sidebar.right.pane.tab` 这个座上** ✓ —— 与上一条"正文挂哪个槽"是同一处，所以"常驻真实页面"只需在页签定义里加 `keepMounted: true` ✓。
（另：在参考仓 `dsh-web-dev` 的 18 个包里 grep `keepMounted` **零命中** ⇒ 这是**核心能力**，生态里还没有先例可抄 —— 我们是早用的 ✓。）

⇒ **抄什么**：① 页签**类型**用 `ctx.sidebarRightTabs.register(<tabDefinition>)` 注册；② 页签**正文**挂在 **`sidebar.right.pane.tab`** 槽上、`key` = 页签 id ✓；③ 它的 tab id 形如 `"dsh-session-diff:file"`（**带包名前缀** ⇒ 避免与别的插件撞 id ✓ 我们该照做 `"dsh-client-ui-workbench-panel:…"`）；
④ 它自己就用 `dsh-resource://file/session/<sessionId>/<path>` 这种地址去读资源（`src/10-util.js:117` ✓）—— 与 §六.1 那条"`openResource` 只收 `dsh-resource://`"完全吻合 ✓。

### 6.2 左栏入口 → **真实网页**的同型：`dsh-deepseek-web-relay`

清单逐字（我方抓到的 `package.json`）：
```json
"icon": "./icon.png",
"dsh": { "bundle": { "patch": "./cordis.patch.yml" },
         "client": { "inject": [], "platform": "web", "immediately": false } },
"exports": [".", "./client", "./package.json", "./locale/*.json"]
```
⇒ 它**同时**做了我们缺的两件事：**包级 `icon`** ✓ 与 **`./package.json` + `./locale/*.json` 导出**（复核 §二.4 说的"显示元数据链路"：`locale/en.json` 的 `{"meta":{"title","description"}}` + `icon`，**核心不激活插件就能读** ✓）。

它的 `cordis.patch.yml` 头部注释逐字（三条纪律，★ 我们都该守）：
- *"三处 id / name 必须完全一致：本文件 insert 的 id 与 name / package.json 的 name / index.js 导出的 name"* ✓；
- *"必须是「顶层 YAML 数组」。写成 mapping 会在启动时直接抛错，不是静默跳过"* ✓；
- *"删掉这一行（或整行注释掉）并重启，插件就彻底不加载了 —— 这就是紧急禁用手段之一"* ✓。

### 6.3 对下一张卡的三条直接结论

1. **右栏页签**照 §6.1 写（`sidebarRightTabs` + `sidebar.right.pane.tab` 槽 + 带包名前缀的 tab id ✓），并按复核 §四.方案 A 加 **`keepMounted`**（常驻真实页面、保住滚动位置/登录态 ✓）；
2. **包级显示链路**照 §6.2 补齐：`icon`（SVG 即可 ✓）+ **`locale/zh.json` 的 `meta.title/description`** + **导出 `./package.json`、`./locale/*.json`**（否则插件管理器的卡片/清单读不到标题与图标 ✗）；
3. 补丁层守 §6.2 那三条纪律（尤其**顶层数组**与**三处 id/name 一致** ✗）。
