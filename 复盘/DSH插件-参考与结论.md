# DSH 插件 —— 参考与结论（定点深读两批 + 生态普查）

> 本文合并：定点深读第一批（`DSH插件-定点深读.md`）、第二批（`DSH插件-定点深读-第二批.md`）、生态对照（`DSH插件-可抄清单.md`）、生态普查（`DSH插件-生态普查.md`）。
> 读源码不读简介；每条结论带 `文件:行号` 或原样片段；版本口径写在每批开头。
> 旧文档正文在 git 历史。

## 结论先行

1. 定点深读共用一套方法：读源码、每问带 `文件:行号`、末尾给「指名我们哪个文件 + 怎么验」的可落地建议。
2. 第一批三仓：`dsh-widgets`（读数单元的形状）、`dsh-plugin-gating-hub`（门禁的证据分型与回滚点）、`dsh-pilot`（浏览器驱动与响亮失败）。
3. 第二批两仓：`dsh-research-report`（内容寻址 + 哈希封印 + 负知识）、`dsh-session-enhance`（物理为权威的对账 + 墓碑防复活 + 搬移原子性）。
4. 生态对照：我们采用的形态（`dsh.bundle` + `dsh.client`）是生态通行形态（16 个核验仓里 15 个声明 `dsh.bundle`）。
5. 生态普查：4691 条按 16 方面铺开，我们最特有的方面（台账对账 / 通知）在生态里最薄。

## 一、定点深读 · 第一批

版本（`git rev-parse --short HEAD` 实测）：`dsh-widgets` = `293c029`，`dsh-plugin-gating-hub` = `792cead`，`dsh-pilot` = `a1dc0b3`。

### 1.1 dsh-widgets —— 读数单元的形状

- 每个内置单元一个目录，**双源声明**：`manifest.json`（机器可读半）+ `defineWidget()` 描述符（代码半），两边 id / sizes 必须一致（校验规则 R5 的「刻意的双源规则」，`src/client/lib/contract/external.ts:20-22`）。
- `render()` 输出**纯数据**（卡形）或 `null`；离线门禁 G4 会把它拍成 JSON 快照，不许有副作用、不许直接摸 DOM（`types.ts:1186,1499-1507`）。
- **没数据就退 `null`**（不造数）：`context-water/index.ts:12`、`tokens/index.ts:33`、`cache/index.ts:52-53`。
- 数据不是组件自己抓的：**收集器把会话 projection 折叠成一份 `Stats`**，组件只声明「我等哪个源」（`data/collector.tsx:68-71,83,89`；`data/session-stats.ts:22-53`）。
- 轮询型适配器两条纪律（`families/cc/adapter.ts:8-15`）：`STALE-WHILE-ERROR`（轮询失败记错误码、保留上一份好数据）、`STALE-WHILE-DEGRADED`（残缺回复永不替换完整回复）；成本护栏：组件栏在屏 + 卡已装 + 标签页可见才轮询（60 秒一拍）。
- 第三方单元注册先按 R1–R10 全量校验，违规带全清单 `throw`；注销把注册表恢复原状，locale 键刻意留下（`registry.ts:112-119,136-153`）。
- 槽位选择跟着**语义与 paint order**走，order 跟**邻居实测**走（`client/index.ts:270-281,315-321,329-341,362-364`）。

**能抄**：① 把六块读数做成机器可读「单元清单」，让 `--json` 与 `--report` 同源；② 连续监测的块加 `STALE-WHILE-ERROR`（坏读数不清空，与错误码并存）；③ 「没数据退 null」的三态纪律（缺 / 坏 / 未知）写进 docstring。
**不抄**：React / 槽位 / 骨架那一层 UI 机制；构建期代码生成。

### 1.2 dsh-plugin-gating-hub —— 门禁与升级安全

- **契约预检**：升级前单独预检会话格式契约（框架把消息格式升版、运行期生产方还写旧格式 ⇒ 一发消息就报错），因为包级依赖门看不见运行期契约破坏（`routes/framework-preflight.js:5-13`）。扫描面 = 用户预设目录 + profile 内每个已装插件包；规则数据化（`lib/contracts/rules.json`），规则库缺失时 `source='unavailable'`，调用方不得当零发现。
- 三种触发：手动完整预检（会打 registry、可能出补丁）· 指纹变化自动预检（只读、不联网）· 服务外预检（dsh 起不来时的自救，四条硬规矩：只补缺的 / 绝不 kill·抢端口 / 修复源可解释 / 改前留痕）。失败呈现为**结构化 JSON**，不阻塞。
- **整树回滚点**：只镜像 `.pnpm` 里所有 `@deepseek-ai` 条目的自包内容 + 顶层 scope + `lock.yaml` + 框架 `package.json`，不跟随依赖 junction（`domain/framework.js:145-170`）；存在 `<stateDir>/framework-backups/<版本>/fw-tree/<ts>`；清理策略「回滚点那条 ∪ 最近 N 条」，回滚点引用的那条永不删。
- **可用性判定 = 记录存在 且 checkpoint 目录仍在**（双验），防「记录在、实物没了还骗用户能回滚」（`compat-state.js:158-175`）。
- **有确证证据才自动禁用**：证据是白名单枚举码（`package-unresolvable` / `file-target-missing` / `boot-log` / `boot-quarantine`），**非证据码成对列出**让「为什么没禁」可查（`auto-disable.js:33-47`）。五道栏：解析不确定 ⇒ 整批只报告绝不写盘；身份豁免（`@deepseek-ai/*` 与裸 `dsh-*` 永不自动禁用）；自己不禁自己；禁前先写 last-known-good 快照，没有可回滚材料就不动手；开关 + 每次动作追加 JSONL，每条禁用记录自带一键回滚命令。顺序：计划（纯判定）→ 禁前快照 → 复用 disableSuspects → 追加可读记录。
- **兼容声明**（`compat.js:45-95`）：优先 `dsh.engines.framework / dsh.compat.framework / engines.dsh` 显式声明 → **硬判据源码扫描**（命中已删除的 dsh-settings API 直接 fail）→ 依赖面兜底 → **运行期冒烟**（独立子进程动态 import，8 秒超时，失败 / 超时按不通过）。口径：源码扫描干净 = 权威判据，声明 / 依赖范围只作参考不作 fail 依据。

**能抄**：「声明 → 静态硬判据 → 冒烟」三级递进与「声明只作参考、源码才是权威」；回滚点「记录 + 实物双验」。
**不抄**：整个框架升级 / `.pnpm` 镜像域（我们对应物是 git 树本身）。

### 1.3 dsh-pilot —— 浏览器驱动与响亮失败

- 可执行文件发现：硬编码候选表按序 `existsSync`，找不到就响亮报错（`src/index.js:26-36,258`）。
- CDP 端口：先用 **bind 探测**选空闲端口（9222 起、扫 40 个），注释写明「HTTP 探测不权威」（`src/index.js:71-84`）；自己拉浏览器进程并把 `--remote-debugging-port` 写进 argv（`:295-297`）；CDP 走 Node ≥22 原生 WebSocket、零运行时依赖。
- 会话隔离：每个 agent 会话一个浏览器实例（池上限 `POOL_CAP = 8`），每实例一个临时 profile；防认错浏览器 —— 校验 `/json/version` 的 `webSocketDebuggerUrl` 确实是自己刚拉起的那个（`:367-373`）；认错就报错重选端口。
- **ref 失效响亮失败**：快照给每个可交互元素钉一个从 1 起的编号 ref；点击 / 输入取不到就是失败返回，绝不猜、绝不静默降级（`:593-595`）。提示三件套：发生了什么（`stale or unknown ref <N>`）、为什么（页面变了 ref 就失效）、下一步（`run pilot_snapshot`）。
- cockpit 数据通道：一条 same-origin HTTP 通道，无 RPC 桥；状态每 2 秒轮询；截图走 CDP `Page.captureScreenshot` 的最近一帧内存缓存；动作走 POST；复用宿主同一端口（`webServer.register({kind:'prefix'})`）。
- 安全边界写在两处：`src/index.js` 头部常量区与 loopback 路由注册处 —— 面板 API 只听回环、导航 URL 必须 `^https?://`、上传必须绝对路径 + 字节上限、端口只在自己控的 9222..9261 里挑且必须 bind 得上、浏览器文件系统面 = 独立临时 profile。

**能抄**：`canBind` 的 bind 探测与「HTTP 探测不权威」；接入本机服务前的「验明正身」一步；错误消息三件套（发生了什么 / 为什么 / 下一步跑哪条命令）。
**不抄**：CDP 驱动与浏览器池整层。

## 二、定点深读 · 第二批

版本（codeload tar.gz 抓取，tarball 无 `.git`，sha 取自 GitHub API `commits/main`）：`dsh-research-report` = `8d00f06`，`dsh-session-enhance` = `f7eb9a0`。

### 2.1 dsh-research-report —— 证据台账与不可篡改

- **内容寻址**：对快照全文算 SHA-256（`ledger.ts:28-31`）；证据对象落 `objects/<sha256>`、同内容只存一份、对象不可变（`ledger.ts:4-9,183-185`）；结论文本也按内容寻址（`claimHash = sha256Of(registration.text)`，`provider-local.ts:583`）。
- **结论绑证据 = append-only JSONL 三本账**：`index.jsonl`（证据）/ `claims.jsonl`（结论，`evidenceIds: string[]` 一对多）/ `verdicts.jsonl`（裁定，latest per claim wins）；id 重复注册但内容不同 ⇒ `ID_CONFLICT` 响亮拒绝（`ledger.ts:229-237,276-281`）。三层引用封存时全量校验。
- **封存 = 哈希封印**：`manifest.json` 记 reportSha256 + 每条证据 sha256 + 全部裁定；seal hash = manifest 精确字节的 SHA-256（`assemble.ts:7-10,278-304`）；`verify-sealed.ts` 零网络零模型重算全部哈希并逐条重验裁定，防「事后被改」而不是「不让改」。
- **裁定五态**：`verified | unverified | contradicted | insufficient | disproven`（`service.ts:62`）；默认裁定者是确定性字节级检查（数字 / 引文必须在绑定快照里逐字可定位，`verify.ts:173-241`），可选模型核验器「是增强，永不是替代」。
- **交付前重审计 + 漂移即挡**：封存前每条 claim 重验，与上轮 verified 比对，漂了强制 `contradicted` 且计入 `blockedReasons`（`provider-local.ts:590-612,671-673`）；**负知识**：同文本曾被证伪且证据未变 ⇒ 永远挡住重报 verified。

**能抄**：① 裁定取值域显式五态；② 负知识按内容哈希记；③ 封存 = 重算哈希而非禁止修改（读侧检查）。
**不抄**：内容寻址对象仓（我们已有 git）；`ctx.web` 抓取层；SARIF 输出。

### 2.2 dsh-session-enhance —— 对账与墓碑

- **一键对账**：以物理 header 列表为权威，对 storages 记账；判据是 **id 集合比对 + realpath 归一 cwd 归属**，不是内容哈希（`domains/sync.js:2,13-14`）。五步：归档集合清幽灵 / 工作区幽灵移除 + 归属修正 / 漏记补录 / 投影缓存清理 + 身份对齐 / 工件编码卫生 / 重建 header 索引。
- 处置：自动修但**只修记账侧、不动物理侧**；无 dry-run、无备份；失败降级 warn 不阻断；返回七字段对账报告（`scanned / archivedRemoved / workspaceRemoved / workspaceAdded / projcacheRemoved / projcacheRehomed / artifactMismatchesRemoved`）。
- **墓碑防复活**（纯内存，不落盘，FIFO 上限 4096）：记 id + 被删生命周期的日志身份（createdAt/cwd），不记时间戳与删除原因。四个检查点：索引重建跳过墓碑 id；入口探活走冷复用探针（同 id + 同身份 = stale，同 id + 不同身份 = 新生命周期，放行）；投影缓存写前挡 + 写后补删；删除顺序里等在途写落定后才删缓存行。
- **搬移 = 物理先行、记账后动、失败回滚**：转录目录整体搬 + 工件第一行 header.cwd 改写 + zstd 帧布局重编码 + 读回验证，全过了才动工作区记账。漏搬投影缓存身份 ⇒ 标题回退工作区名（fail-soft）；zstd 帧布局破坏 ⇒ `session.list` 整体 500。

**能抄**：① 「物理为权威」的对账方向；② 对账产出多字段报告（动了谁逐条可查）；③ 墓碑的「身份探针」形状（按内容哈希认出，不按字面）；④ 写前挡 + 写后补删。
**不抄**：内存墓碑不落盘（我们的排除项必须落盘）；zstd 帧编码层；单飞串行。

## 三、生态对照（可抄清单）

### 3.1 立刻能用在我们身上的四条（UI / 形态）

| 机制 | 出处 | 用在哪 |
|---|---|---|
| 一个插件同时占三种座位：左栏面板座 `sidebar.panellist` + `main` · 右栏页签 `sidebarRight.tabs` + `sidebar.right.pane.tab` | `plugins/workbench.md:197-199` | 三行再挂右栏页签，对话留中间、目标页在右手边；角标显示「待我审 / 未读数」 |
| 宿主有右栏服务才注册：`ctx.get('sidebarRight')` 返回 undefined 就跳过 | `workbench.md:202` | 座位注册前先探服务，没有就如实不注册 |
| 清单三件套：`dsh.bundle.patch` + `dsh.client.platform` + `dsh.engines.dsh` | `workbench.md:261` | 卡 242 加前两件 |
| 图标用 SVG 文件 + 包级显示链路 | `plugins/widgets.md:8`、`dsh-ops-main/icon.svg` | 内联 SVG（`currentColor`）+ 包内 icon 文件 |

### 3.2 同型实现对照（16 方面）

工作台六块读数 ↔ `dsh-widgets`（抄「单元清单 + 纯数据 render」，槽位别照抄）；门禁与升级安全 ↔ `dsh-plugin-gating-hub`（抄「证据不足就不动手」）；交付纪律 ↔ `dsh-completion-guard`；工作台时间轴 + 技能库 ↔ `dsh-workbench`（座位组合照抄）；额度与用量 ↔ `dsh-usage-panel`（抄「同口径」声明方式）；MCP 管理 ↔ `dsh-plugin-hub`（两原子工具 + cwd 路由）；任务 / 待办 ↔ `dsh-ticktick`；记忆层 ↔ `dsh-ltm`（CJK 混合检索）；跨会话协作 ↔ `dsh-team-rooms`（共享任务板）；让 agent 有手 ↔ `dsh-pilot`（CDP 驱动 + cockpit + stale ref 响亮失败）；深链 / 地址栏 ↔ `dsh-url-router`（`#/panel/<panelId>` → `selectPanel(id)`；地址栏唯一写者 + 只用 `replaceState`）。

### 3.3 装法对照

- registry 包（`dsh plugin --profile desktop add dshmarket`）⇒ 装完自动进 `dsh.profile.bundles`，补丁层立刻生效。
- `file:` 本地目录包 ⇒ 只进 `dependencies`，不进 `bundles` ⇒ 包自带补丁层不生效，必须手工加进 `dsh.profile.bundles`。
- `link:` 装法在生态里是合法的开发用法；长期用 `link:` 要保证宿主半的裸导入够得到 DSH 的 node_modules。
- 「装完必须重启」是生态共识（客户端 bundle 在组合阶段被快照进内存）。

### 3.4 短名单实况核验（16 仓）

- 协议合规是常态：16 个里 15 个声明 `dsh.bundle`（有 UI 的还带 `dsh.client`）⇒ 我们采用的形态就是生态通行形态。
- 星级不是质量代理：`gating-hub` 101★ 与 `completion-guard` 0★ 都是当天还在提交的活项目 ⇒ 选型看「是否活跃 + 是否对得上我们的问题」。
- 核验的仓（含 ★ / 最近提交 / 许可 / `dsh` 声明）：`Noob-stupid/dsh-plugin-gating-hub`(101) · `hyzyn/dsh-plugin-kit`(49) · `PerryLink/dsh-claude-move`(28) · `wingsky-1/dsh-plugin-hub`(24) · `PerryLink/dsh-output-styles`(14) · `Sivan757/dsh-agent-plugins-market`(13) · `AlfredChaos/dsh-usage-panel`(12) · `Physicolor/dsh-widgets`(5) · `zbsph/dsh-ppt-studio`(5) · `PerryLink/dsh-ticktick`(4) · `PerryLink/dsh-team-rooms`(3) · `Nath-Vikky/dsh-codekin`(2) · `zhy5/dsh-wx-bridge`(1) · `liiydong/dsh-workbench`(0) · `GreenLv/dsh-completion-guard`(0) · `Link-h1j/dsh-screen-capture-record-desktop`(0)。

### 3.5 两个「唯一同型」候选的实现要点

- `dsh-session-diff`：右栏页签的服务名是 `sidebarRightTabs`；页签类型用 `ctx.sidebarRightTabs.register(<tabDefinition>)` 注册，正文挂 `sidebar.right.pane.tab` 槽（`key` = 页签 id）；tab id 带包名前缀；`keepMounted: true` 恰好作用在 `sidebar.right.pane.tab` 座上 ⇒ 常驻真实页面只需在页签定义里加它（核心能力，生态里还没有先例可抄）。
- `dsh-deepseek-web-relay`：包级 `icon` + `./package.json` 与 `./locale/*.json` 导出；补丁层三条纪律（三处 id / name 一致、顶层数组、删行即禁用，已收进 `协议与事实` §二 A10）。

## 四、生态普查（4691 条按 16 方面）

数据源：`_refs/dsh/catalog.json`（4691 条）。方法：每方面主方面 + 次方面，weak = 该方面得分 < 2（只命中一个宽词或零命中）。

- 全部条目分到 16 方面之一，另 519 条零命中进兜底桶（多为 UI 交互 / 附件 / 阅读类）。
- 有真读数的仓 200；进表 top8×16 = 128 行（127 个唯一仓）。
- 最热三方面：派活器与看门狗（556）/ 浏览器网页驱动（475）/ 门禁预检质量闸（376）。
- weak 占比：1209 / 4691 = 25.8%。
- 已抄 vs 未抄：合计约 12 个机制点，覆盖 8 个方面（只读面板 / 门禁 / 浏览器 / 跨会话 / 号池 / 任务板 / 收口 / 图标）；派活器、后台任务、证据链、时间、工单、台账、通知、搜索这 8 个方面零覆盖或近乎零。
- 最薄的两方面（生态少有人做）：通知提醒告警（152 条，weak 4）、台账账目对账（81 条，weak 17）—— 后者正是我们最特有的东西（卡 / 栅栏 / 账目 / 证据链）。

每方面条数与 weak：派活器 556/310 · 后台任务 143/30 · 任务板 232/133 · 门禁 376/117 · 证据链 225/55 · 收口 307/42 · 时间 109/75 · 工单 46/31 · 台账 81/17 · 号池 351/63 · 只读面板 149/82 · 图标皮肤 350/41 · 浏览器 475/187 · 跨会话 285/10 · 通知 152/4 · 搜索 335/12。

「该深读」清单 29 个（每方面 ≤2），要点几条：`ZSeven-W/dsh-crew`（跨 harness 反向派活）· `shengsheng90/DSH-taskboard`（SQLite 项目 / 任务 / 看板）· `JW53222/faultseed`（确定性 hook 挡「削弱测试」）· `030611/qiushi-dsh-evidence-audit`（哈希链证据回执）· `PerryLink/dsh-checkpoint-rewind`（git-first 快照）· `liu3734/jira-tasks-dsh-plugin`（JIRA 凭据 → 会话内任务列表）· `xswt442-cmd/dsh-treekeeper`（任务账本与 OS 进程树对账）· `Aik358/dsh-auto-memory`（回复前记忆回注）· `LeslieWylie/dsh-task-relay`（跨会话任务接力）· `RevolutionLA/dsh-dream-skin`（主题 token 化）。

## 五、可落地建议汇总（指名文件 + 怎么验）

| 建议 | 依据 | 指名文件 |
|---|---|---|
| 六块读数落「机器可读单元清单」，`--json` 与 `--report` 同源 | 第一批 §1.4 | `tools/pipeline_view.py` |
| 连续监测的块加 `STALE-WHILE-ERROR` | 第一批 §1.4 | `tools/pipeline_view.py` |
| 端口探测一律用「能不能 bind」+ 接入前「验明正身」 | 第一批 §四.3 | `tools/serve.py` |
| 成送申请的证据「读时重算哈希」（防篡改） | 第二批 §三.1 | `tools/pool/task.py` |
| 「被证伪口径」立落盘墓碑 + 冷复用探针 | 第二批 §三.2 | 新增 `docs/tombstones.toml` + `tools/wb_dispatch.py` |
| 收口前「交付重审计」：域文件指纹漂了就挡 | 第二批 §三.3 | `tools/pool/task.py` + `tools/pool/landing.py` |
| 抄 dsh-crew 的「跨 harness 反向派活」 | 生态普查 §四.1 | `tools/wb_dispatch.py` + `tools/pool/` |
| 抄 dsh-treekeeper 的「账实对账」 | 生态普查 §四.2 | `tools/pipeline_view.py` |
| 抄 dsh-ltm / dsh-anima-rag 的 CJK 混合检索 | 生态普查 §四.3 | 记忆 / 复盘检索入口 |

## 六、边界（如实写）

- 定点深读第一批：`dsh-widgets` 实读 12 个源文件（超「每仓最多 10」预算，超出的都是「>2000 行看相关段」式的部分读）；`gating-hub` 读的是 `lib/server/**` 源码模块，未读打包单文件 `lib/client.js`（6281 行）；三仓 README 本卡未逐字比对。
- 定点深读第二批：`git clone` 直连失败，按规格退 codeload `tar.gz` ⇒ 无本地 git 对象，两仓 sha 取自 GitHub API 而非 `git rev-parse`；`dsh-session-enhance` 的 `lib/client.js`（5603 行）是打包产物，未读。
- 生态普查：认证通道实际走无认证配额（search 端点 10 次/分钟限速 + 逐仓缓存 + 退避重试）；weak 是子串匹配导致的噪声，其标记兜住一部分；top8 表里个别条目属 strong 词命中但语义不符，如实保留并声明。
- `_refs/` 不在仓里（`catalog.json` / `sweep-by-aspect.json` / `sweep-raw/`），报告即其摘录入口。
