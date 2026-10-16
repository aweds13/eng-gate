# DSH 插件 —— 协议与事实（唯一权威）

> 本文是 DSH 插件协议的**唯一权威**：只写**在磁盘上真读到的**，每条带出处（文件:行 或 URL）。
> 读不到 / 是草稿 / 是私有样式的，如实标注。
> 合并自旧文档（全文在 git 历史）：`DSH插件协议-权威清单.md`（协议两层 + 对抗复核修订）。
> 反例与纠正记录收在「已决问题索引」。

## 结论先行

1. 协议是**两层**，别混：A 层是 DSH 核心自带、可执行的那层；B 层是社区标准 `dsh-plugin.json`（草稿）。
2. DSH 核心里**查不到** `dsh-plugin.json` 的读取点，B 层是市场 / 工具链的事，不是核心要求。
3. 我们的面板走的是 **A 层**（`dsh.bundle.patch` + `dsh.client` + 座位）。
4. UI 面板现在**只能走 A 层**：B 层的 `contributes.panels` 留了名字但一条都不许有（`maxItems: 0`）。
5. 打开真实页面的正解是 `openTab("browser", { params: { url } })`，不是 `openResource`。
6. 真正被强制的兼容字段是 `peerDependencies` 里名为 `@deepseek-ai/dsh` 的 semver 范围，不是 `dsh.engines.dsh`。

## 一、协议两层

| 层 | 是什么 | 权威出处 | 我们能拿它干什么 |
|---|---|---|---|
| A. DSH 核心自带的插件协议 | 可执行的那层：包声明 `dsh.bundle.patch`（profile 层）+ `dsh.client`（浏览器半）+ cordis 条目 / 座位 | 见 §二 | 我们的面板正在用这一层 |
| B. 社区标准 `dsh-plugin.json` | 声明式元数据（清单），给市场 / 工具链读 | `T-Auto/dsh-std` 的 schema（见 §三） | 加一份可被市场认；但它的 `panels` 与 `requires.services` 都还没开放 |

判据：DSH 随附包里 grep `dsh-plugin.json` 零命中 ⇒ B 层不是核心要求的。

## 二、A 层（核心、可执行）

| # | 事实 | 出处 |
|---|---|---|
| A1 | 一个包要成为 profile 层，就在自己的 `package.json` 里声明 `"dsh": { "bundle": { "patch": "./cordis.patch.yml" } }` | 参考仓 `dsh-ops/package.json` 逐字 |
| A2 | 补丁层用 `- insert:` 新增行；行的 `name` 可以是本包的子路径导出，一个包能声明多行 | `dsh-ops/cordis.patch.yml`：`name: dsh-ops/shell` / `dsh-ops/file` / `dsh-ops/background` / `dsh-ops/ptc`，与 `exports` 的 `./shell` 等对应 |
| A3 | 浏览器半在 `package.json` 的 `dsh.client` 里声明：`platform`（`web`）、`inject`、`external`、`immediately`；并导出 `./client`。`inject` 是**信息性**的包名依赖，不是 cordis 服务注入；加载顺序来自模块图 | 本机 `@deepseek-ai/dsh-client-modules/README.zh.md`；类型注释 `types.d.ts:79-80` |
| A4 | 座位机制：`main` 是 `dsh-client-ui-layout` 声明的 root 作用域 keyed 座；左栏行来自 `sidebar.panellist`（list 槽），点一行 = `selectPanel(id)`，行 id 必须等于 main 的 key | 本机 `@deepseek-ai/dsh-client-ui-sidebar/lib/client.js`（`entriesOfSlot("sidebar.panellist")` + `onClick: selectPanel(id)`） |
| A5 | 侧栏浏览器是核心自带、桌面默认启用，可访问 loopback（Desktop 走 Electron `<webview>`） | 本机 `@deepseek-ai/dsh-web-app/cordis.patch.yml:277-280`；`dsh-client-ui-sidebar-browser/README.zh.md` |
| A6 | 安装 / 启用 / 版本豁免由 `dsh-plugin-manager` 管：`dsh plugin --profile <p> add <spec>`；换 manifest 要重启（精确边界见 §五）；`compatibility.json` 存版本豁免 | 本机 `@deepseek-ai/dsh-plugin-manager/README.zh.md` |
| A7 | 只带 `dsh.bundle` 的包用 `dsh plugin add` 装才对；缺 A1 那条时只能当普通依赖 + 手写 profile 行 | 卡 242；CLI 原话："declares no dsh.bundle — installed as a plain dependency, not a profile layer" |
| A8 | 兼容判据：**真正被强制**的是 `peerDependencies` 里名为 `@deepseek-ai/dsh` 或以 `@deepseek-ai/dsh-` 开头的 semver 范围；不满足则装前拒、bundle 加载时 `throw`。`dsh.manifestVersion` / `engines.dsh` 官方逐字"当前安装器与加载器**不强制**" | `dsh-package-manifest/README.zh.md:93`、`types.d.ts:22`；`app-boot/lib/index.js:286-304`（前缀过滤在 `:294`）、`:929-930`；`plugin-manager/index.js:506`；`dsh-ops/package.json:118-121` |
| A9 | 包级显示链路（官方不激活插件就能读）：`package.json` 的 `icon` + `locale/*.json` 的 `meta.title/description`，需导出 `./package.json` 与 `./locale/*.json` | 参考仓 `dsh-deepseek-web-relay/package.json` 逐字 |
| A10 | 补丁层三条纪律：三处 id / name 必须完全一致（patch 行 / package.json / index.js 导出）；顶层必须是 YAML 数组（写成 mapping 启动时抛错）；删掉那行并重启即紧急禁用 | `dsh-deepseek-web-relay/cordis.patch.yml` 头部注释逐字 |

> `inject`「只许列声明了 `dsh.client` 的包」是**我们自己的经验判据**（写在 `tools/dsh_panel.py` 的 `CLIENT_INJECT_DENY`），**不是**协议规则：loader 只做 `optionalStringArray` 校验（`dsh-client-modules/lib/client.js:66`），没有成员资格检查。

## 三、B 层（社区标准 `dsh-plugin.json`，草稿）

出处：参考仓 `dsh-ops/dsh-plugin.json` 头一行指向 schema `https://raw.githubusercontent.com/T-Auto/dsh-std/<sha>/packages/manifest/schema/dsh-plugin-0.15.schema.json`；标准仓已抓下到 `_refs/dsh/dsh-std-main/`。

- schema 标题逐字：**`DSH Plugin Manifest Community Draft v0.15`** ⇒ 是社区草稿，不是核心正式规范。
- 顶层字段（schema 的 `properties`）：`$schema` · `manifestVersion` · `id` · `name` · `version` · `facets` · `requires` · `permissions` · `contributes` · `subscriptions` · `license` · `source` · `artifact` · `compat` · `overrides`。
- `facets`：只有 `host`（必填），形如 `{"host": {"entry": "lib/index.js", "apiVersion": "v1alpha1"}}` ⇒ 没有 client / UI facet。
- `contributes`：`commands`（有 `$defs/command`）+ `panels`，而 `panels` 逐字是 `{"type": "array", "maxItems": 0}` ⇒ 留了名字但一条都不许有。
- `requires.services` 同款 `{"maxItems": 0}`（schema `:34`）。
- `x-*` 扩展位：`patternProperties: {"^x-": {"type":"array"}}` ⇒ 官方允许 `x-display` / `x-prompt-sections` / `x-tool-namespaces` 这类扩展。
- `permissions`：`[{name, scope, reason}]`（例：`dsh-ops.process.spawn` / `subprocess`）；`requires.contracts`：`[{apiVersion: "tools.dsh/v1alpha1", kind: "Tool"}]`。

## 四、图标

核心（协议级）规则 —— 出处 `@deepseek-ai/dsh-agent-preset/skills/cordis-plugin-development/.../host-plugin.md:45`：

- icon 用相对路径；格式 SVG / PNG / JPEG / WebP；≤ 256 KiB；
- 拒绝绝对路径、URL、以及越界（逃出包目录）的符号链接。

行内 glyph（左栏那三行）：

- 核心行条目只有 `{id, order, label}`，**行内容由插件自己渲染**，会给 `size: 16/18`（`dsh-client-ui-sidebar/lib/client.js:454-461`、`:187-197`）。
- 正解是内联 SVG + `currentColor`（跟随主题）；尺寸 / 线宽 / 颜色没有协议规定。
- 没有角标槽：要显示角标只能画进自己的 glyph 内容里。

两个面的区分：

- `package.json` 的 `icon` 键 + `dsh-plugin.json` 的 `contributes["x-display"][0].icon` 是给插件清单 / 市场读的；
- 与左栏行 glyph 是两个面。

## 五、打开真实页面与重启边界

打开真实页面的正解：

```js
ctx.sidebarRight.openTab("browser", { params: { url: "http://127.0.0.1/zentao/" } })
```

- 侧栏浏览器注册的是右栏页签类型 `browser`，其参数接受 URL：`SidebarRightTabParamsMap { browser: { readonly url?: string } }`（`@deepseek-ai/dsh-client-ui-sidebar-browser/lib/types/client/index.d.ts` 末尾 `declare module`）。
- `openResource` 只收 `dsh-resource://<type>/…`，传 `http://…` 必抛（`sidebar-right/lib/types/client/service.d.ts:150-161`）；DSH 浏览器页开新页用的也是 `openTab`（`sidebar-browser/lib/client.js:157-162`）。
- 时序：`openTab` / `openResource` 内部先取屏幕会话，无屏幕会话时抛 `sidebarRight: no session surface is mounted`（`client.js:6385-6396`）。逃生门是订 `ctx.sidebarRight.mounted` 记住最后在屏的 sessionId，改用 `openTabIn(sessionId, …)`（对未 adopted 会话静默无操作）。
- 浏览器地址白名单：接受 HTTP/HTTPS（含 loopback）；拒 `file:`、脚本 / `data` / `blob`、内嵌凭据、DSH 应用自身 origin（`sidebar-browser/README.zh.md:59`、`lib/types/client/browser/url.d.ts:1-30`）。禅道不能用 `http://user:pass@…` 那种地址。
- 右栏一等公民 API：`active() / focus(tabId) / isExpanded() / toggleExpanded() / split() / float() / dock() / close(tabId)`。
- 右栏页签正文挂 `sidebar.right.pane.tab` 槽（`key` = 页签 id），页签类型用 `ctx.sidebarRightTabs.register(<tabDefinition>)` 注册；tab id 带包名前缀避免撞号（`dsh-session-diff/src/80-apply.js:12,65-93`）。

重启边界（官方逐字）：安装新 bundle **可以**通过 HMR 激活；**替换**已安装的包需要重启（`host-plugin.md:60`）。

## 六、市场数据源（已落盘，零网络检索用）

| 源 | 规模 | 路径 |
|---|---|---|
| 精选列表（awesome） | 4691 条 | `_refs/dsh/catalog.json`（name / repo / desc / category） |
| 市场清单（精选） | 137 条 | `dsh-web-dev/market/dist/manifest/plugins.json` |
| 皮肤 | 60 套 | `…/manifest/skins.json`（机制＝设计 token 重映射 `--dsw-alias-*` / `--aion-*`） |
| 预设 / 编辑精选 / 宠物 | 有 | `…/manifest/{presets,editor-picks,pets}.json` |
| 社区插件索引 | 未计数 | `zhu1090093659/dsh-community-plugins` 的 `community.json`（DSH Workshop 商店与 dsh-market.com 清单的唯一数据源） |

## 七、边界（没答 / 待办）

- `dsh-std` 除 schema 还有 `docs/` 与 `AGENTS.md`，可能写了提交插件进市场的要求（未读）。
- 是否给包补 `dsh-plugin.json`（B 层）取决于是否要进市场；核心不读它。
- `thoughtdag` 的 `package.json` 里 `dsh: null` ⇒ 它不是 DSH 插件，是独立应用（无限画布思维图），对我们的价值是设计参考。
