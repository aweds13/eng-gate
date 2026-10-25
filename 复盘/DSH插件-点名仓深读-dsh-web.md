# DSH 插件：点名仓深读 —— dsh-web（2026-10-16）

**卡**：卡 258 §一（T-G379 · 本会话只做 dsh-web；§二 thoughtdag / §三 dsh-ops 另开会话 ✗）
**仓**：`D:/repo\_refs\dsh\dsh-web-dev`（zhu1090093659/dsh-web）｜ **HEAD**：`924c087`（`git -C <仓> rev-parse --short HEAD` 实测 ✓，2026-09-14 "docs(30): 固化数据库访问方式（实测打通）"）
**纪律**：只读未跑构建；整读 12 个文件 + 10 个文件仅 grep 定向核对（清单见附录 A）；每条带 `文件:行号` 与原样片段；读不到的写明（附录 B）。

## 结论先行（≤12 行）

1. **它不是 fork、不是套壳、也不是独立实现**：是建在官方 `@deepseek-ai/dsh-*` npm SDK（0.2.0-rc.2 cohort）之上的**第三方插件家族聚合**（根 `package.json:2-5` "DeepSeek Harness Web GUI 插件全家桶" + 根 `package.json:48-76` 全套官方 devDependencies）⇒ 我们该抄的基准仍是官方源码，它是"生态怎么用官方面"的最佳范本 ✓。
2. **市场装插件走三档写入器**（`packages/dsh-market/README.zh.md:25`）：官方进程内管理器 remote 面 `remote.pluginManager.installBundle` → 家族 `pluginManager` 服务（其内又双通道：官方 `/plugin-installer`/`/plugin-control` RPC → 自有回环 HTTP 网关）→ 都没有则**诚实降级为复制命令索引**（`dsh plugin --profile web add <spec>`）。
3. **装完要重启才生效**：`enabled` 一律是"下次启动生效"语义（`plugin-manager-bridge.ts:23`）；重启分 `shell`/`relaunch`/`manual` 三档，先 GET-shaped plan-read 再执行（`restart.ts:86-110`）。
4. **插件面与我们同 A 层不同座位**：`package.json.dsh.{engines,bundle.patch,client.inject,platform}` + `cordis.patch.yml` insert 行 ✓；但它用的座位是 `settings.section`、`plugins.bundle.config`、自定义 `web-ui.plugin.item` 子槽，**不是** `sidebar.panellist`/`sidebarRightTabs`（`docs/plugins.md:150`）。
5. **皮肤 = 重映射官方 `--dsw-*` CSS 变量**：官方权威 350 个唯一 token（`dsh-client-ui-theme` 两份 css）；运行时由官方 ThemePresenter 写 body 内联变量、皮肤中心挂 `html[data-dsh-skin]`（`docs/archive/2026-08-18-upstream-theme-seam-recon.md:14,45`）。
6. **它没有 `locale/*.json`**（Glob `packages/*/locale/*.json` 无结果）：显示名靠 insert 行名渲染、icon 走 `package.json.icon`、运行时文案在代码内 `locales.ts` 经官方 `ctx.locale` 注册 ⇒ 与我们"locale/en.json 为锚"的口径不同，**别抄它这条** ✗。

## 一、dsh-web（zhu1090093659/dsh-web）

### 1.1 市场安装链路

**入口**：市场卡是设置页里的一级分区（`packages/dsh-market/src/client/index.ts:2-8` 原话 "the single first-level Workshop settings section (settings.section id `dsh-web-ui-market`) that renders the store card"）。资产与插件两条装法分工写在包描述里（`packages/dsh-market/package.json:3`）："install them in the GUI (**assets into the DSH home directories, plugins through the optional plugin manager**)"。

**插件安装的完整三档链路**（`packages/dsh-market/README.zh.md:25` 原话）：

> 一键安装插件复用官方写入器：只要宿主发布了官方进程内插件管理器的 remote 面（`ctx.remote.pluginManager.installBundle`，即官方插件页所用的同一个调用）就走它——在打包桌面客户端上该管理器是唯一写入器，因为 CLI 拒绝应用自有 profile；否则回退到家族 `pluginManager` 服务（`@linxin666/dsh-client-ui-plugin-manager`）。两者都没有时降级为复制命令索引。

- **① 官方 remote 面**：`packages/dsh-market/src/client/native-plugin-faces.ts:92` `ctx.inject(['remote.pluginManager'], (inner) => {...})` —— 之前"它桥接 remote.pluginManager"的判断**在源码里坐实** ✓。
- **② 家族服务**：市场卡经可选桥接拿服务（`packages/dsh-market/src/client/plugin-manager-bridge.ts:102-109`，用 `ctx.inject` 保证"没有该插件也不炸"）；服务面很窄（`plugin-manager-bridge.ts:40-53`）：`isLoopback / list / install(spec) / uninstall(id) / status / onChange`。该服务客户端半区**双通道**（`packages/dsh-plugin-manager/src/client/index.ts:7-11` 原话 "on runtimes with the official installer services (DSHCode, the 1.0.4 checkout web) every operation rides the official `/plugin-installer` and `/plugin-control` loopback RPC channels (the single writer); on the npm-published web runtime those channels do not exist, so the same face falls back to this package's own loopback HTTP gateway"），RPC 调法 `:128` `connection.rpc.call(CHANNEL, endpoint, payload)`，`:59` `const CHANNEL = '/plugin-installer'`。协议形状**镜像官方 web 安装页**、不是 import（`packages/dsh-plugin-manager/src/core/protocol.ts:8-10` 原话 "The shapes mirror the official web installer tab's wire protocol (see the DSH checkout's packages/client/ui-settings-plugin-installer/src/client/protocol.ts); they are a contract observation, not an import"）。
- **③ 复制命令降级**：`packages/dsh-market/src/client/install-source.ts:24` `return \`dsh plugin --profile web add ${entry.npm ?? entry.repo ?? entry.id}\``；spec 白名单 `:39-42` 只收 npm 包名（`pkg@version`）或 **https://** git URL，"ssh://, git@-style, file://, http://, relative paths and bare repo names are rejected, so the remote manifest can never drive a non-https or local install"。

**失败怎么呈现**：

- 安装/更新进度四段：`protocol.ts:54-59` `stage: 'fetch' | 'download' | 'extract' | 'write'` + 可选 percent，经 `status()` 轮询（`plugin-manager-bridge.ts:50`）。
- RPC 不绿：`packages/dsh-plugin-manager/src/client/index.ts:128-131` `throw new Error(\`plugin-installer ${endpoint} failed: ${result.error.code}: ${result.error.message}\`)`。
- **通道漂移降级**：所有响应按"decoded but untrusted"逐字段校验、不匹配即抛 typed error，"Callers treat a parse failure as 'channel unavailable or drifted' and degrade to command hints"（`protocol.ts:4-7`）。
- **启动失败环**：`protocol.ts:87-105` `PluginFailureItem { pluginId, kind: 'load-failure' | 'hang' | 'late-rejection', message, stack, installPath, at }` + `PluginFailuresSnapshot { items, pluginRoot, safeMode }`，宿主经 `/failures` 路由供给（`client/index.ts:234-235`）。
- 更新兼容提示读 `dsh.engines.dsh`：`protocol.ts:74-84` `requiresDsh`（"Declared DSH minimum the update needs (package manifest's `dsh.engines.dsh`)"）+ `compatible` + `hostVersion` —— 注意：这里是**提示兼容性**，不是安装闸；与我们"安装器不强制查 `dsh.engines.dsh`"的既有结论不冲突 ✓。

**装完怎么激活（要不要重启）——要**：

- `enabled` 的语义就是"下次启动"：`plugin-manager-bridge.ts:23` 原话 "Saved next-start enablement from the managed profile patch row"；`protocol.ts:33` 同口径（"Effective next-start enablement"）。
- 重启走自有路由（官方两通道都没有 restart 方法，`client/index.ts:98-101`），三档模式（`packages/dsh-plugin-manager/src/host/restart.ts:86-110`）：打包桌面（`desktop === true || ELECTRON_RUN_AS_NODE === '1'`）⇒ `shell`（Electron 拥有进程树，本插件只停宿主、壳自己 `app.relaunch()`）；可证明是交互终端启动 ⇒ `relaunch`（detached helper 等本进程退出 ≤30s 后原样重执行命令行，日志落 `~/.dsh/logs/plugin-manager-restart.log`，`restart.ts:113-115`）；其余（supervisor/管道 stdio）⇒ `manual`（保持运行、用户自己重启，"a process that cannot be replaced stays up"，`restart.ts:223-233`）。
- 先问后做：GET-shaped plan read 不改状态，"The toolbar words its confirmation from this"（`client/index.ts:104-108`）。

**市场内容来源**：四个 git 子模块（`market-inputs.lock.json:4-25`：skins/pet/community/presets 各指向 `satellites/*` 子模块内目录），"`scripts/market-fetch-inputs.mjs` materializes each content directory"；`satellites/` 本地未检出（见附录 B）。README 部署口径：`README.md:209` `dsh plugin --profile web add @linxin666/dsh-web-all@latest`；`:298` 卸载后"完成后重启 `dsh web` 即可恢复纯净状态"。

### 1.2 插件面（面板/座位/槽位/命令的注册方式）

**同一套 A 层**（与我们一致）：`packages/dsh-market/package.json:14-29`：

```json
"dsh": {
  "engines": { "dsh": ">=0.2.0-rc.2" },
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": { "inject": ["@deepseek-ai/dsh-client-connection", "@deepseek-ai/dsh-client-ui-renderer", "@deepseek-ai/dsh-client-ui-settings"], "platform": "web" }
}
```

加 `peerDependencies: { "@deepseek-ai/dsh": ">=0.2.0-rc.2" }`（`:38-41`）—— 正是官方强制检查的那个口 ✓。

**座位与槽位**（与我们用的不同座位，重点）：

- 子插件的最小 patch 就一行 insert，两个半区一次挂载（`packages/dsh-market/cordis.patch.yml:1-8`）：

  ```yaml
  # dsh-market bundle patch: inserts the market card row into the web profile
  # roster. The single row mounts BOTH halves: the host side registers the
  # market settings namespace and the loopback install gateway; the dsh.client
  # declaration in package.json makes the browser half (exports "./client",
  # served from lib/client.js) render the first-level "Market" section.
  - insert:
      - id: ui-market
        name: '@linxin666/dsh-client-ui-market'
  ```

- 官方插件管理页给每个 bundle 一片配置区：**`plugins.bundle.config` 槽（按 bundle 包名分派）**；各家族注册**一级设置分区 `settings.section`**（label 用 thunk 跟随语言）；Web 插件组自定义 **`web-ui.plugin.item` 子槽**归组 task-board 等卡片（`docs/plugins.md:150` 原话）。
- 官方**尚未发布的槽位**（例：`conversation.input.selector.*`）用模块形式本地 augmentation 补类型（`import type {}` + `declare module '@deepseek-ai/dsh-client-ui-slots'`，`docs/plugins.md:139-142`），SDK 发布后移除 —— 一个我们没有的"提前用新槽"手法 ✓。
- 浏览器半区经 `window.__ModuleLoader__` 加载 `@deepseek-ai/*/client` 子路径（`docs/plugins.md:138-139`）。
- 聚合包行**带 children**：聚合包 insert 行声明子行，每行可单独启停，卸载整包进行；管理器自身行与兼容面行 `locked` 永不可禁（`protocol.ts:14-24,38-44` 原话 "Rows the manager must never disable (the manager tab itself, the compat face)"）。
- 聚合 patch 是**生成物**：`packages/dsh-web-all/cordis.patch.yml:1-3` "AUTO-GENERATED by scripts/aggregate.mjs — do not edit ... edit aggregate.yml and rerun"；行名统一 `web-ui-*` 命名空间（":4 Rows are namespaced web-ui-* so the bundle can coexist with standalone installs"），官方库存每行渲染一个 "web-all/<family>" 标题（":5-6"）；可选行 `disabled: true` 出厂（":116-121"，启用写用户层覆盖"that wins"）；外部卫星 bundle 行（community-plugins/pet/preset-center/skin-center）也在同一 patch 里（":123-149"）。
- 挂载坑记载：insert 行不带 `config` 时 loader 用 schema 默认值填充，`apply` 无条件加载时校验会把空配置当配置抛错 ⇒ "组合条目配置了关键字段才在加载时校验"（`docs/plugins.md:155-157`）。
- 它**没有用** `sidebar.panellist`/`main`/`sidebarRightTabs`/`sidebar.right.pane.tab` —— 这家族面向 web GUI 的设置页与插件管理页；桌面右栏生态另有其人（`docs/publish-prep.md:31`：`dsh-better-sidebar@0.19.1` 因 peer 区间不覆盖 rc.2 已从聚合移除，"右侧面板改为按需安装"）⇒ 我们的卡 247（右栏常驻页签）**别拿 dsh-web 当参考**，仍以官方 `dsh-client-ui-sidebar-right` 为准 ✓。

### 1.3 主题令牌与重映射

令牌清单**从官方包来**（本仓只有审计与转述，权威文件在官方仓）：

- 官方唯一权威定义在 `@deepseek-ai/dsh-client-ui-theme`：`lib/styles/design-platform.css`（162 唯一）+ `lib/styles/gradient-shadow-text.css`（187 唯一）= **350 个唯一 token、514 次定义出现**（亮套 `body`、暗套 `body[data-ds-dark-theme]` 各一份；`docs/archive/2026-08-18-skin-token-coverage-audit.md:13-16,19-21`）；token 名模式 `--dsw-[a-z0-9-]+`（`:4`）。
- 三层语义：`static-*` 色阶原料；`alias-*` 语义层（**换肤主战场**）；`font-*` markdown/shiki 排版细粒度（`:35`）。
- 皮肤怎么生效 = **重映射这些变量**：11 个皮肤各有重映射数与 var() 引用数（`:55-57`）；78 个官方 alias token 中 77 个被 ≥1 皮肤重映射、28 个被全部 11 个覆盖（`:99`）。
- 运行时注入：官方 token 经 apps/web `base.css` `@import` 进构建产物；**运行时覆盖层由 ui-layout ThemePresenter 写 body 内联变量**（`docs/archive/2026-08-18-upstream-theme-seam-recon.md:14` 原话）；首屏 FOUC 用官方 tapIndex 注入 boot-theme 同步内联脚本（`:38`）；皮肤中心挂 **`html[data-dsh-skin]`** 属性、与官方 body 属性惯例"CSS 等价"无冲突（`:45`）。
- 皮肤可带**执行钩子**，皮肤中心对预置钩子有来源验证：仅当已装 manifest 与钩子字节匹配审查通过的生成标识才恢复效果；纯资产路线也有（whalechan-harness，"无执行钩子"）（`docs/publish-prep.md:36`）。皮肤脚手架 `node scripts/dsh-skin-new.cjs <id>` 在 dsh-skins 卫星仓（`docs/plugins.md:153`）。
- 审计文化可抄：幻觉 token 三分类（皮肤定义了 19 个非官方 token；**插件引用了 6 个官方不存在的 token**，"更严重，插件纯消费"，`:74-84`）；L1 稳定 token 白名单建议 84 个（`:101-103`）；仓内自治：皮肤中心私有变量从 `--dsw-skin-*` 改非官方前缀 `--dsh-skin-*`（`:124`）。

### 1.4 i18n 与显示元数据

- **没有 `locale/*.json`**：`Glob packages/*/locale/*.json` 无结果 ⇒ 这家族不走我们已核实的"官方以 `locale/en.json` 为锚读 meta"那条路。
- 显示元数据从哪读：**icon** = `package.json` 顶层 `"icon": "icon.svg"` + `files` 携带（`packages/dsh-market/package.json:5,70-74`）；**title** = 插件库存按 insert 行渲染（聚合注释原话 "the official plugin inventory renders one distinct 'web-all/<family>' title per row"，`packages/dsh-web-all/cordis.patch.yml:5-6`），设置分区标题是跟随语言的 thunk（`docs/plugins.md:150`）；**description** = `package.json` 顶层 description（英文，`packages/dsh-market/package.json:3`）。官方对"无 locale 目录"的回退实现在官方 boot 代码，本仓读不到（附录 B）——仅观察到：无 locale 也能正常渲染行标题。
- 运行时文案：代码内字典。市场卡 `import { en, zh, type MarketKey } from './locales.ts'`（`packages/dsh-market/src/client/index.ts:26`），经官方 locale 服务注册。
- 语言包范例 `dsh-i18n`（俄语包）：`inject = ['locale']`，`ctx.locale.addLanguage(RU_LANGUAGE)`（`RU_LANGUAGE = { id: 'ru', label: 'Русский', fallback: 'en' }`）+ 逐命名空间 `ctx.locale.register(ns, 'ru', dict)`；失败语义钉死：addLanguage 抛错只影响定义不影响字典注册、重复 (ns, locale) 只跳过该 ns、disposer 幂等（`packages/dsh-i18n/src/client/index.ts:33-57`）。
- `README.i18n.yaml` **不是显示元数据**：是 README 双语对的 git blob 哈希一致性记录，"Both languages carry equal authority"，用 `node scripts/verify-docs.mjs --write <dir>` 重记（`packages/dsh-market/README.i18n.yaml:1-5`）；由 `docs:check` 门禁（`docs/publish-prep.md:49`）。

### 1.5 它与官方 DSH 的关系（fork？套壳？独立实现？）

**判决：都不是 —— 是建在官方 npm SDK 之上的第三方插件家族聚合（bundle + 四卫星仓），复用并跟随官方，不改动官方文件。**

- 自述定位（根 `package.json:2-5` 原话）："DeepSeek Harness Web GUI 插件全家桶。皮肤、宠物与社区插件索引已拆分为独立仓库（dsh-skins / dsh-pet / dsh-community-plugins），本仓通过 npm 包内置它们。"
- **官方 SDK 是唯一类型来源**（`docs/plugins.md:136-137` 原话）："构建/类型/测试全部以 node_modules 的 SDK 包为唯一类型来源，克隆后无需任何源码 checkout 即可构建" ⇒ 不持有官方源码 ⇒ 不是 fork。
- 根 devDependencies 整套官方 cohort（`package.json:48-76`：cordis 4.0.4 + 数十个 `@deepseek-ai/dsh-*@0.2.0-rc.2`，含官方 web 前端 `dsh-web-frontend`）；子包 peer `"@deepseek-ai/dsh": ">=0.2.0-rc.2"`（`packages/dsh-market/package.json:38-41`）。
- 官方 SDK 的发布缺陷用 pnpm `packageExtensions` 在**本仓工作区**补声明，"no installed file is patched"（`pnpm-workspace.yaml:22-32`）—— 克制、不碰已装文件。
- 协议"观察而不 fork"：`protocol.ts:8-10`（contract observation, not an import）；官方进程内管理器 remote 面**直接复用**（`native-plugin-faces.ts:92` + `README.zh.md:25` "即官方插件页所用的同一个调用"）。
- 引入第三方纪律（`README.md:448`）："具有活跃上游的第三方项目优先以 npm 依赖或 fork 方式引入，避免直接复制代码"。
- CI 挂载冒烟目标就是官方包（`docs/publish-prep.md:57`）："CI 与发布挂载冒烟测试挂载目标为 `@deepseek-ai/dsh@0.2.0-rc.2`"。

### 1.6 发布流程（源码 → 可安装包）

- **16 个公开家族包统一版本**（当前 0.4.6），"根 package.json 与 shared 私有包**不发布**"——根只作 git 安装别名 bundle（`docs/publish-prep.md:5`；根 `package.json:11-17`：files 只带 `package.json` + `packages/dsh-web-all/cordis.patch.yml`，dependencies 指聚合包 `@linxin666/dsh-web-all@^0.4.6`）。
- **四卫星仓先发、本仓后发**（`docs/publish-prep.md:7` 原话）："四个卫星仓与本仓发布同一个版本号：卫星先发、本仓后发，聚合包的依赖范围、锁定条目与 gitlink 随对齐一起更新"。卫星 = dsh-skins / dsh-pet / dsh-community-plugins / dsh-presets（各自 npm：`@linxin666/dsh-client-ui-skin-center` / `@linxin666/dsh-pet` / `@linxin666/dsh-client-ui-community-plugins` / `@linxin666/dsh-client-ui-preset-center`）。
- 单包出包步骤：`tsdown` 构建（`build`/`prepare`，`packages/dsh-market/package.json:31-33`）出 `lib/`；`files` 携带 `lib + cordis.patch.yml + icon.svg`（`:70-74`）。
- 聚合 patch 生成链：`aggregate.yml` → `scripts/aggregate.mjs` → 自动生成 `cordis.patch.yml`（"do not edit"），`aggregate:check` 防漂移（`packages/dsh-web-all/cordis.patch.yml:1-3`；根 `package.json:25`）。
- 发布门禁清单（`docs/publish-prep.md:42-56` 原样）：`pnpm sync-shared:check` → `typecheck` → `test` → `test:scripts` → `aggregate:check` → `runtime-deps:check` → `docs:check` → `i18n:check` → `market:fetch` → `market:check` → `libs:check` → `build` → `node scripts/verify-version.mjs 0.4.6`。
- 市场站发布：`market:fetch`（子模块 gitlink 固定输入，`market-inputs.lock.json:3`）→ `market:build` / `market:check` / `market:verify` → `deploy:market`（根 `package.json:42-46`），站点 `dsh-market.com`（`README.md:90`）。
- 皮肤不走 `dsh-web-all` 注册：在 dsh-skins 仓用脚手架生成"纯资产目录"（`docs/plugins.md:153`）。
- 用户侧装法三形态（`README.md:209,224-225,258-264`）：聚合 npm 包 / git 仓根别名（`github:zhu1090093659/dsh-web` 或 `git+https://...dsh-web.git`）/ 单插件逐个 add。

### 1.7 ★ 我们能抄什么 / 不抄什么

**抄（5 条，均有本仓行号依据）：**

1. **三档写入器 + 诚实降级**（1.1 全链）：官方 remote 面 → 自有通道（内再分官方 RPC / 自有网关双通道）→ 都没有就降级成"复制这条命令"的只读索引。降级不冒充成功、失败按 `{code, message}` 原话抛出、协议响应逐字段校验当 untrusted。⇒ 对我们任何"桥接官方服务"的插件（如卡 247 的页签管理）是现成的鲁棒性范式。
2. **next-start 启用语义 + 三档重启计划**：`enabled` 字段名与文档都写明"下次启动生效"；重启 `plan`（纯函数可测）/`perform`（副作用可注入）分离，plan-read 是 GET-shaped 先问后做，确认文案按 shell/relaunch/manual 模式措辞；relaunch helper 等待 30s、写 `~/.dsh/logs/plugin-manager-restart.log`；"换不了的进程就不杀"（`restart.ts:223-233`）⇒ 我们做"重启后状态保留/复活提示"直接抄这套语义。
3. **启动失败环**：`load-failure | hang | late-rejection` + `pluginRoot + safeMode` 快照（`protocol.ts:87-105`）⇒ 比我们"起不来翻日志"强，值得做进我们的插件诊断面。
4. **生成器/清单分离 + namespacing + locked 行**：`aggregate.yml` 人写、`cordis.patch.yml` 机生成 + `aggregate:check` 防漂移；行名 `web-ui-*` 命名空间使聚合与单独安装共存；管理器自身行 `locked` 防自锁。⇒ 对应我们的教训"仅依赖现有生成器实现会遗漏关键字段"——把必填字段收进**清单 schema** 而不是生成器代码，正是解法。
5. **安装 spec 白名单**（只收 npm 名或 https:// git URL，拒 ssh/file://，"the remote manifest can never drive a non-https or local install"，`install-source.ts:33-42`）与 **`dsh.engines.dsh` 用作更新兼容提示**（`protocol.ts:74-84`，提示不拦截，与官方安装器不强制查该字段的结论兼容）。

**不抄（5 条）：**

1. **"无 `locale/*.json`"的元数据路线** ✗：它靠行名渲染 + 代码内字典；我们已核实官方以 `locale/en.json` 为锚读 meta（项目记忆 2026-10-16），我们的插件继续带 `locale/en.json`，别被它带偏。
2. **皮肤"执行钩子"+ 字节匹配审查门** ✗：安全面重、需审计基建；若我们做皮肤，抄它的**纯资产路线**（whalechan-harness 式"无执行钩子"，`publish-prep.md:36`）即可。
3. **`pnpm packageExtensions` 修官方包清单缺陷** ✗：那是官方 SDK 发布期的权宜；连它自己也强调 "no installed file is patched"——学它的克制，不学它的 extensions。
4. **16 包同版本 + 4 卫星仓联动的仓结构** ✗：对我们单插件仓是过度工程。
5. **市场静态站 + 遥测 badge**（`telemetry.ts` / `dsh-market.com` 用户数徽章，`README.md:24`）✗：隐私与运维承诺我们没立过，先不抄。

**负面结论（对卡 247）**：dsh-web 家族**不用**桌面右栏座位（`sidebarRightTabs`/`sidebar.right.pane.tab`），右侧面板生态另有其人且已从聚合移除（`publish-prep.md:31`）⇒ 右栏常驻页签开发**继续以官方 `dsh-client-ui-sidebar-right` 源码为准**，dsh-web 参考价值在安装器/重启/失败面，不在座位面。

---

## 附录 A：读过哪些文件（路径 + 行数）

**整读（12 个）**：
1. `package.json`（根）79 行
2. `pnpm-workspace.yaml` 185 行
3. `packages/dsh-market/src/client/plugin-manager-bridge.ts` 109 行
4. `packages/dsh-market/src/client/install-source.ts` 135 行
5. `market-inputs.lock.json` 26 行
6. `packages/dsh-plugin-manager/src/core/protocol.ts` 292 行
7. `packages/dsh-plugin-manager/src/host/restart.ts` 238 行
8. `packages/dsh-market/package.json` 79 行
9. `packages/dsh-market/cordis.patch.yml` 8 行
10. `packages/dsh-web-all/cordis.patch.yml` 149 行
11. `packages/dsh-i18n/src/client/index.ts` 62 行
12. `docs/publish-prep.md` 57 行

**grep 定向核对（未整读，只看相关段）**：`packages/dsh-plugin-manager/src/client/index.ts`（双通道/路由/重启段）、`packages/dsh-plugin-manager/src/host/gateway.ts`（约 1900 行，只查 install/remove 行）、`packages/dsh-market/src/client/native-plugin-faces.ts`（remote.pluginManager 段）、`packages/dsh-market/src/client/index.ts`（settings.section 段）、`README.md`（安装/市场/许可定向行）、`packages/dsh-market/README.zh.md:25` / `README.md:36`（三档写入器段）、`docs/plugins.md`（座位/槽位段）、`docs/archive/2026-08-18-skin-token-coverage-audit.md`（token 统计段）、`docs/archive/2026-08-18-upstream-theme-seam-recon.md`（生效机制段）、`packages/dsh-market/README.i18n.yaml`（6 行全文）。

## 附录 B：读不到 / 未验清单

- **皮肤中心（skin-center）实现源码读不到**：在卫星仓 dsh-skins（`satellites/` 子模块本地未检出，`.gitmodules` 在而内容空）⇒ 令牌重映射的**实现代码**、"执行钩子"的字节匹配门实现，只有本仓审计文档转述，未读到源码；如需深读须另拉 dsh-skins 仓。
- **官方主题文件的行号是转述**：`design-platform.css`、`theme-presenter.ts:43-48`、`boot-theme.ts:31-39` 等是官方仓文件，本任务未打开，行号引自本仓 `docs/archive/2026-08-18-upstream-theme-seam-recon.md` 与 `2026-08-18-skin-token-coverage-audit.md` 的记载（这两份是本仓自己的实测审计，可信度较高但非我实测 ✓）。
- **官方 boot 对"无 locale 目录"包的回退实现读不到**：在官方 `.dsh-app-boot` 代码里，本仓只有"无 locale 也能渲染行标题"的观察（`packages/dsh-web-all/cordis.patch.yml:5-6`），未开官方仓核对。
- **`gateway.ts`（69.5KB ≈ 1900 行）未整读**：只 grep 了 install/remove 相关行（`:61,955,1287-1289,1346,1404`）；宿主侧网关的完整路由表（uninstall/set-enabled/check-updates 的宿主实现细节）未逐行核。
- **`MarketCard.tsx`（47KB）未读**：市场卡 UI 的进度条/失败渲染细节未读；失败呈现只引到协议层与 README 描述。
- 遥测/turnstile（`telemetry.ts`/`turnstile.ts`）、dsh-remote-web-ui 的 LAN/配对细节：与六问无直接关系，未读。
