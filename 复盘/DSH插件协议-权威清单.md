# DSH 插件协议 —— 权威事实清单（2026-10-15 取证）

> 用户令：*「关键是 dsh 是万物皆插件，然后有个官方承认的 dsh 插件协议，你找找」*。
> 本文只写**在磁盘上真读到的**，每条带出处；读不到/是草稿的，**如实标**。

## 一、结论先说：协议是**两层**，别混

| 层 | 是什么 | 权威出处（本机/引用） | 我们能拿它干什么 |
|---|---|---|---|
| **A. DSH 核心自带的插件协议** | 可执行的那一层：包声明 `dsh.bundle.patch`（profile 层）＋ `dsh.client`（浏览器半）＋ cordis 条目/座位 | 见 §二 | ★ 我们的面板**正在用**这一层 |
| **B. 社区标准 `dsh-plugin.json`** | 声明式元数据（清单），给市场/工具链读 | `T-Auto/dsh-std` 的 schema（本文 §三） | 加一份可被市场认；**但它的 `panels` 还没开放** ✗ |

★ 关键判据：**DSH 核心里查不到 `dsh-plugin.json` 的读取点**（在随附包里 grep 零命中）⇒ B 层是**社区标准/市场工具链**的事，不是核心要求的 ✗。

## 二、A 层（核心、可执行）—— 事实与出处

| # | 事实 | 出处 |
|---|---|---|
| A1 | 一个包要成为 **profile 层**，就在自己的 `package.json` 里声明 `"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }` | 参考仓 `dsh-ops/package.json` 逐字：`"dsh": {"bundle": {"patch": "./cordis.patch.yml"}}` |
| A2 | 补丁层用 `- insert:` 新增行；行的 `name` 可以是**本包的子路径导出**（一个包能声明多行） | `dsh-ops/cordis.patch.yml`：`name: dsh-ops/shell` / `dsh-ops/file` / `dsh-ops/background` / `dsh-ops/ptc`，与 `exports` 里的 `./shell` `./file` … 对应 |
| A3 | 浏览器半在 `package.json` 的 `dsh.client` 里声明：`platform`（`web`）、`inject`（要先加载的**客户端插件包名**）、`external`、`immediately`；并导出 `./client` | 本机 `@deepseek-ai/dsh-client-modules/README.zh.md`（"声明客户端插件"一节）；我方插件 `tools/dsh_panel.py` 产出的清单 |
| A4 | ★ `inject` 里只许列**自己声明了 `dsh.client` 的包** —— 不声明 `dsh.client` 的包（如 `@deepseek-ai/dsh-client-ui-slots`，它的 `dsh` 字段是 null）永远不可能是提供方 | 本机各包 `package.json`；已写成判据（`tools/dsh_panel.py` 的 `CLIENT_INJECT_DENY`） |
| A5 | 座位机制：`main` 是 `dsh-client-ui-layout` 声明的 **root 作用域 keyed 座**；左栏行来自 **`sidebar.panellist`（list 槽）**，点一行 = `selectPanel(id)` ⇒ **行 id 必须等于 main 的 key** | 本机 `@deepseek-ai/dsh-client-ui-sidebar/lib/client.js`（`entriesOfSlot("sidebar.panellist")` + `onClick: selectPanel(id)`） |
| A6 | ★ **侧栏浏览器是核心自带、桌面默认启用**，可访问 **loopback**（Desktop 走 Electron `<webview>`） | 本机 `@deepseek-ai/dsh-web-app/cordis.patch.yml` 第 277~280 行 `disabled: !!js "…!== 'desktop'"`；`@deepseek-ai/dsh-client-ui-sidebar-browser/README.zh.md` 原话 |
| A7 | 安装/启用/版本豁免由 `dsh-plugin-manager` 管：`dsh plugin --profile <p> add <spec>`；**换 manifest 要重启**；`compatibility.json` 存版本豁免 | 本机 `@deepseek-ai/dsh-plugin-manager/README.zh.md`（"使用本包"/"版本兼容性与豁免"） |
| A8 | 只带 `dsh.bundle` 的包用 `dsh plugin add` 装才对；**我们的包现在缺 A1 那条** ⇒ 只能当"普通依赖 + 手写 profile 行" ✗ | 卡 242 第 4 项；CLI 原话（昨日日志）：*"declares no dsh.bundle — installed as a plain dependency, not a profile layer"* |

## 三、B 层（社区标准 `dsh-plugin.json`，**草稿**）—— 逐字事实

- 出处：参考仓 `dsh-ops` 的 `dsh-plugin.json` 头一行指向 schema：`https://raw.githubusercontent.com/T-Auto/dsh-std/<sha>/packages/manifest/schema/dsh-plugin-0.15.schema.json`；本机已抓下标准仓 → `D:/repo/_refs/dsh/dsh-std-main/`。
- schema 标题逐字：**`DSH Plugin Manifest Community Draft v0.15`** ⇒ **是社区草稿**，不是核心的正式规范 ✓（如实标）。
- 顶层字段（schema 的 `properties`）：`$schema` · `manifestVersion` · `id` · `name` · `version` · `facets` · `requires` · `permissions` · `contributes` · `subscriptions` · `license` · `source` · `artifact` · `compat` · `overrides`
- `facets`：**只有 `host`**（必填），形如 `{"host": {"entry": "lib/index.js", "apiVersion": "v1alpha1"}}` ⇒ ★ **没有 client/UI facet** ✗
- `contributes`：`commands`（有 `$defs/command`）＋ **`panels`**，而 `panels` 逐字是
  ```json
  "panels": { "type": "array", "maxItems": 0 }
  ```
  ⇒★ **留了名字但一条都不许有**（还没开放）✗ —— 所以"用标准声明一个 UI 面板"这条路**现在走不通**，UI 只能走 A 层的 `dsh.client` + 座位 ✓
- `x-*` 扩展位：`patternProperties: {"^x-": {"type":"array"}}` ⇒ 官方允许 `x-display` / `x-prompt-sections` / `x-tool-namespaces` 这类扩展（`dsh-ops` 三个都用了）
- `permissions`：`[{name, scope, reason}]`（例：`dsh-ops.process.spawn` / `subprocess`）· `requires.contracts`：`[{apiVersion: "tools.dsh/v1alpha1", kind: "Tool"}]`

## 四、★ 图标：核心规则 vs 私有样式（2026-10-15 经对抗复核修订）

**核心（协议级）规则 —— 这条才要照办**（出处：`@deepseek-ai/dsh-agent-preset/skills/cordis-plugin-development/.../host-plugin.md:45`）：
- icon 用**相对路径**；格式 **SVG / PNG / JPEG / WebP**；**≤ 256 KiB**；
- **拒绝**绝对路径、URL、以及越界（逃出包目录）的符号链接。

**行内 glyph（我们左栏那三个）**：核心行条目只有 `{id, order, label}`，**行内容由插件自己渲染**（`dsh-client-ui-sidebar/lib/client.js:454-461`、`:187-197`，会给 `size: 16/18`）
⇒ 所以"图标丑"的根因是**我们用了文字符号** ✗；正解是**内联 SVG + `currentColor`**（跟随主题）✓ —— 尺寸/线宽/颜色**没有**协议规定 ✓。

**★ 请注意（复核者推翻的一条）**：网上看到的 `36×36 / #7C7C82 / stroke-width 2.4 / 圆头` **不是约定**，那只是参考仓 `dsh-ops` 那一个文件的**私有样式**（`dsh-ops-main/icon.svg:1-2`）⇒ 可以借鉴观感，**别当标准引用** ✓。
另外：`package.json` 的 `icon` 键 + `dsh-plugin.json` 的 `contributes["x-display"][0].icon`（`dsh-ops` 两处都写了）是**给插件清单/市场读**的，与左栏行 glyph 是**两个面** ✓。

## 五、市场数据源（已落盘，零网络检索用）

| 源 | 规模 | 路径/URL | 字段 |
|---|---|---|---|
| 精选列表（awesome） | **4691** 条 | `D:/repo/_refs/dsh/catalog.json` | name / repo / desc / category |
| **市场清单（精选）** | **137** 条 | `dsh-web-dev/market/dist/manifest/plugins.json` | `id, name, rank, nameEn, author, description, descriptionEn, repo, npm, category, subcategory` |
| 皮肤 | **60** 套 | `…/manifest/skins.json` | id/name/author/repo/description（机制＝**设计 token 重映射** `--dsw-alias-*` / `--aion-*`，`assets/`、`hooks.mjs`） |
| 预设 / 编辑精选 / 宠物 | 有 | `…/manifest/{presets,editor-picks,pets}.json` | — |
| ★ **社区插件索引**（另一个市场数据源，2026-10-15 从 `dsh-url-router` README 读到） | 未计数 | `zhu1090093659/dsh-community-plugins` 的 **`community.json`** —— 原话："本插件在 **DSH Workshop 商店**与 **dsh-market.com** 清单里的唯一数据源" | 条目形如 `dsh-url-router` + 分类 `ui/panel` ✓ |

## 六、★ 对抗复核修订（2026-10-15，复核者 = 另一个模型的工人，任务书见 `gates/diag/_trae_review_protocol.md`，回报 `gates/diag/_trae_review.md`）

> 复核者的目标就是"**证明本文档是错的**"。它**推翻了 4 条**、纠了 4 处口径 —— 逐条照收（这是本文档的可信度来源，不是丢面子）：

| 原主张 | 判决 | 修订后的正确说法（带依据） |
|---|---|---|
| `openResource(url)` 是开真实页面的口子 | ★ **被推翻** | 只收 `dsh-resource://`，传 http **必抛**；正解 `openTab("browser", {params:{url}})`（依据见 §六.1 三条铁证）|
| `dsh.engines.dsh` 是"核心会读/会被用"的兼容字段 | ★ **被推翻** | 官方逐字：*"Current installers and loaders **do not enforce** `dsh.manifestVersion` or `engines.dsh`"*（`dsh-package-manifest/README.zh.md:93`，类型注释同义 `types.d.ts:22`）。真正被强制的 = **`peerDependencies` 里名为 `@deepseek-ai/dsh` 或以 `@deepseek-ai/dsh-` 开头的 semver 范围**（`app-boot/lib/index.js:286-304`，前缀过滤在 `:294`）：不满足 ⇒ **装前拒**（`plugin-manager/index.js:506`）、bundle 加载时 `throw`（`app-boot:929-930`）。`dsh-ops` 自己就是 `peerDependencies: {"@deepseek-ai/dsh": "^0.2.0-rc.2"}`（`package.json:118-121`），`engines` 只写了 node（`:149-151`）⇒ **该补 `peerDependencies`，不是 `engines.dsh`** ✗ |
| 图标"约定"= 36×36 / `#7C7C82` / 2.4 / 圆头 | ★ **被推翻（作为约定）** | 那只是 `dsh-ops` 一个文件的**私有样式**；**核心规则**是：icon 用**相对路径**、格式 SVG/PNG/JPEG/WebP、**≤256 KiB**、**拒绝绝对路径 / URL / 越界符号链接**（`dsh-agent-preset/skills/cordis-plugin-development/.../host-plugin.md:45`）—— **没有尺寸/线宽/颜色要求** ✓；"内联 SVG + `currentColor`"的方向仍成立（glyph 就是插件自渲染的槽内容，`sidebar/client.js:190-193`，传 `size:16/18`）✓ |
| "点左栏行 → 右栏开页面"可直连 | ★★ **被推翻（时序）** | 见 §六.1 的"致命时序坑"与 `openTabIn` 逃生门 |
| `dsh.client.inject` = "要先加载的客户端插件包名" | 半错，已改 | 官方类型注释逐字：*"**Informational** package-name dependencies, **not** Cordis service injection"*（`types.d.ts:79-80`）；加载顺序来自**模块图**（"让动态提供方先于其消费方加载"）⇒ 本文档 A3 的措辞已按此改 |
| "`inject` 只许列声明了 `dsh.client` 的包"当作**协议判据** | 降级为**经验判据** | loader 只做 `optionalStringArray` 校验（`dsh-client-modules/lib/client.js:66`），**没有成员资格检查** ⇒ 我们在 `tools/dsh_panel.py` 里那条 `CLIENT_INJECT_DENY` 是**经验归纳 + 我们自己的判据**，**不是协议规则**，别写成协议 ✓ |
| "换 manifest 要重启" | 已精确化 | 官方 SKILL 逐字：*"Installing a new bundle **can activate through HMR**; **replacing** an installed package requires restart"*（`host-plugin.md:60`）|
| `dsh-client-ui-slots` 的 `dsh` 字段是 `null` | 已改正 | 它**根本没有 `dsh` 键**（grep 零命中），不是"值为 null" ✓ |
| `contributes.panels` 是唯一"留名未开放"的 | 已补 | **`requires.services` 同款 `maxItems:0`**（schema `:34`）—— 本文档漏了 ✓ |
| 角标（badge）当成核心能力 | 已改正 | 核心行条目只有 `{id, order, label}`（`sidebar/client.js:454-461`）、行渲染是自绘 glyph+label（`:187-197`）⇒ **没有角标槽**，要显示角标只能**画进自己的 glyph 内容里** ✓ |

**复核者另外给的"你漏掉的协议面"**（照收，待下一轮补进 §二/§三）：`requires.services`（同样 `maxItems:0`）、`peerDependencies["@deepseek-ai/dsh"]` 的**强制**语义、浏览器地址白名单（§六.1 末）、以及"新装可 HMR / 替换要重启"的精确边界 ✓。

## 七、还没答的问题（留给下一轮，别当已答）

1. ✅ **已答（2026-10-15，主控读类型声明钉死）**：**"直接跳真实页面"的正式口子**
   - 侧栏浏览器注册的是**右栏页签类型 `browser`**，其参数接受 URL：
     ```ts
     declare module '@deepseek-ai/dsh-client-ui-sidebar-right/client' {
       interface SidebarRightTabParamsMap { browser: { readonly url?: string } }
     }
     ```
     出处：`@deepseek-ai/dsh-client-ui-sidebar-browser/lib/types/client/index.d.ts` 末尾那段 `declare module`（含注释 `/** Optional initial Browser URL. */`）。
   - ★★ **正解是 `openTab`，不是 `openResource`**（主控当天先写错、被两份独立复核同时推翻 ✗）：
     ```ts
     ctx.sidebarRight.openTab("browser", { params: { url: "http://127.0.0.1/zentao/" } })
     ```
     - 铁证一（类型注释逐字）：`openResource` 的 `address` 只接受 **`dsh-resource://<type>/…`**，*"An address outside `dsh-resource://`, or one no type will open … **throws**"*（`sidebar-right/lib/types/client/service.d.ts:150-161`、`:253` 同文）；
     - 铁证二（实现硬校验）：`const RESOURCE_SCHEME = "dsh-resource://"`，`client.js:6327` 赋值、`:6445` `throw` ⇒ 传 `http://…` **连注册表都不进，必抛** ✗；
     - 铁证三（官方自证）：**DSH 自己的浏览器页开新页用的就是**
       `tab.actions.openTab("browser", { params: { url }, revealIfOpened: false })`（`sidebar-browser/lib/client.js:157-162`）。
     - 反例排除：`openTabFromTarget(kind, target)`（`service.d.ts:332`）收的是**捕获的窗格/页面目标**（`SidebarRightTarget`），**开不了任意网址** ✗；`browser.new` 命令不带初始 URL 参数 ✗。
   - ★★ **一条致命时序坑**（两份文档起初都没发现，复核者指出）：`openTab`/`openResource` 内部先 `require()` 屏幕会话，**无屏幕会话时抛** `sidebarRight: no session surface is mounted`（`client.js:6385-6396`、`:6744-6752`）；而"屏幕会话"的定义是 *"The Session on screen, or undefined while none is (a **global panel fills the main column**, …)"*（`service.d.ts:141-143`）
     ⇒ **"点左栏行（=占 main 的全局面板）→ 立刻 openTab" 第一次点击就会抛** ✗。
     逃生门：订 `ctx.sidebarRight.mounted` 记住最后在屏的 sessionId，改用 **`openTabIn(sessionId, …)`** —— 它对未 adopted 会话**静默无操作**（`client.js:6418-6421`），不炸 ✓。
     （我方卡 242 的处理是 **catch + 如实报错**（不炸、不假装）✓；换成 `openTabIn` 的更稳版本留给下一笔 ✓。）
   - 配套可用的还有：`active() / focus(tabId) / isExpanded() / toggleExpanded() / split() / float() / dock() / close(tabId)`
     ⇒ 「对话留中间、目标页在右手边」这套是有**一等公民 API** 的 ✓（不必自绘 ✗）
   - ★ 浏览器地址白名单（复核者补）：**接受 HTTP/HTTPS（含 loopback）**，但 `file:`、脚本/`data`/`blob`、**内嵌凭据**、DSH 应用自身 origin 会被拒（`sidebar-browser/README.zh.md:59`、`lib/types/client/browser/url.d.ts:1-30`）⇒ 禅道**不能用 `http://user:pass@…` 那种地址** ✗。
2. `dsh-std` 除了 schema 还有 `docs/` 与 `AGENTS.md` —— 里面可能写了**提交插件进市场的要求**（下一轮读）。
3. 我们该不该给包补 `dsh-plugin.json`（B 层）——取决于我们是否要进市场；**核心不读它** ✓（已验）。
4. ✅ **thoughtdag 的定性（2026-10-15）**：`package.json` 里 `dsh: null` ⇒ **它不是 DSH 插件**，是独立应用（无限画布思维图）；对我们的价值是**设计参考**（画布/图结构），不是插件接入参考 ✓。
