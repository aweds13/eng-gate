# DSH 插件定点深读（2026-10-15）

> 卡 246（T-G367）。读**源码**不读简介；每条结论带 `文件:行号` + 原样片段。
> 三仓版本（`git rev-parse --short HEAD` 实测）：`dsh-widgets` = **293c029**，`dsh-plugin-gating-hub` = **792cead**，`dsh-pilot` = **a1dc0b3**（克隆于 `D:/repo/_refs/dsh/`，depth 1）。
> 三份 README 本卡未逐字比对（主控已读过；本卡只读源码），下文所有片段均出自源码；未发现需要记录的「README 与源码冲突」新例。

## 结论先行（≤10 行）

1. **dsh-widgets 的「单元」= 双源声明**：`manifest.json`（机器可读半）+ `defineWidget()` 描述符（代码半），两边必须一致（R5 双源规则）；`render()` 输入 stats 快照、输出**纯数据卡形**或 `null`（无数据就不渲染，绝不造数）。
2. 数据不是组件自己抓的：**收集器把 DSH 会话的 projection 折叠成一份 `Stats`**（上下文水位、token、子代理、后台任务各是一条 projection / 会话镜像），组件只声明「我等哪个源」。
3. gating-hub 最值钱的是**证据分型**：`EVIDENCE_CODES`（四种确证形态）与 `NON_EVIDENCE_CODES`（明确不算证据的形态，写出来让「为什么没禁」可查）成对出现；解析不确定 ⇒ 整批只报告不写盘；禁前先写 last-known-good 快照，快照失败就放弃动作。
4. gating-hub 的兼容声明既不是裸 `peerDependencies` 也不是裸 `engines`：优先 `dsh.engines.framework / dsh.compat.framework / engines.dsh` 显式声明，再做依赖范围检查，再上**源码扫描 + 子进程冒烟导入**这两条硬判据（声明可能是假的，源码不会）。
5. 回滚点是「**记录 + 实物**」双验：记录存在且 checkpoint 目录仍在才算可用（"记录在、目录没了 = 实际不可用，不能骗用户"）。
6. dsh-pilot 的 ref 失败是**响亮失败 + 下一步指引**：`stale or unknown ref … — run pilot_snapshot`，工具描述里同时写明「refs go stale when the page changes」——错误消息本身就是修复指令。
7. pilot 的安全边界全写在 `src/index.js` 头部常量与 loopback 路由注册处：只听 127.0.0.1、URL 必须 `^https?://`、上传/下载有字节数上限、浏览器用独立临时 profile。
8. **我们的六块读数照 widgets 的形状做成机器可读单元清单是成立的**（§1.4、§四 建议 1）。

## 一、dsh-widgets

### 1.1 单元怎么声明（文件:行号 + 原样片段）

**双源声明**：每个内置单元一个目录（`src/widgets/<id>/`），内含 `manifest.json`（机器可读半）与 `index.ts`（代码半）。以 `context-water` 为例：

`src/widgets/context-water/manifest.json:2-7`（原样）：
```json
  "id": "context-water",
  "order": 21,
  "group": "system",
  "builtin": true,
  "sizes": ["2x2", "2x4"],
```

代码半用 `defineWidget()`，两边 id/sizes 必须一致——第三方单元校验规则 R5 写明这是**刻意的双源规则**：

`src/client/lib/contract/external.ts:20-22`（原样）：
```
 *  R5  sizes ⊆ {2x2, 2x4}, and manifest sizes === descriptor sizes (the same
 *      double-source rule the generator enforces: `sizesOf()` reads the descriptor
 *      while the market/all-instances list reads the manifest)
```

`manifest.json` 的全部字段（第三方版）：`src/client/lib/contract/external.ts:41-50` —— `id / order? / group? / builtin? / sizes? / source? / skeleton? / locale?`。其中 `source`（等哪个数据源适配器）、`skeleton`（加载骨架形状）是运行元数据，进 `WIDGET_RUNTIME`（`src/client/lib/registry.ts:127-130`）。

**`render()` 为什么是纯数据**：契约类型上写死——渲染输出是「卡形」，并且**离线门禁 G4 会把它拍成 JSON 快照**，所以不许有副作用、不许直接摸 DOM：

`src/client/lib/contract/types.ts:1499-1507`（原样，节选）：
```ts
export interface Widget {
  id: string
  name: string | (() => string)
  desc: string | (() => string)
  builtin: boolean
  group?: string
  /** Sizes this widget supports. Defaults to ['2x2'] when omitted. */
  sizes?: WidgetSize[]
  render: (stats: WidgetStats, meta?: WidgetRenderMeta) => WidgetRenderOut | null
```

`types.ts:1186`（原样）：`is pure DATA (the offline gate snapshots it as JSON), so the renderer maps each`。

实例（context-water 的 render，只有数据没有 JSX）：`src/widgets/context-water/index.ts:40-49`（原样）：
```ts
  return {
    title: t('card.contextWater.title'),
    // Percent + concrete figures sit on their own row below the title
    // (user preference over the inline header).
    headAfter: {
      big: `${Math.round(pct * 100)}%`,
      small: used && capacity ? `${used} / ${capacity}` : undefined,
    },
    chart: total > 0 ? { kind: 'segments', segments, totalTokens: total } : undefined,
  }
```

**没数据就退 `null`**（不造数）：`src/widgets/context-water/index.ts:12` `if (pct == null || !brk) return null`；`src/widgets/tokens/index.ts:33` `if (!u || u.inputTokens <= 0) return null`；`src/widgets/cache/index.ts:52-53` `// Hidden until an input AND a cache read have been observed (the shipped // card's own gate): a fresh session must not advertise a 0% hit rate.`

**注册**：内置单元由构建期生成的 `generated.registry.ts` 提供，运行期注册表是**活数组、原地变更**，第三方单元走 `registerExternalUnit()`：先按 R1–R10 全量校验，**违规就带全清单 throw**（半装机的单元不许存在）：

`src/client/lib/registry.ts:112-119`（原样，节选）：
```ts
export function registerExternalUnit(unit: ExternalWidgetUnit): () => void {
  const errors = validateExternalUnit(unit, {
    isTaken: (id) => widgetById(id) !== undefined,
    hasSource,
  })
  if (errors.length > 0) {
    throw new Error(`[dsh-widgets] third-party unit rejected:\n  - ${errors.join('\n  - ')}`)
  }
```

### 1.2 生命周期（数据从哪来 / 怎么更新 / 怎么收尾）

**数据从哪来（两层）**：

- **路由型**：单元在 manifest 声明 `source: '<id>'`；数据源适配器（构建期从 `families/<id>/adapter.ts` 生成清单）按调度节奏轮询宿主 HTTP 路由，把结果 patch 进状态。cc 家族适配器（`src/client/families/cc/adapter.ts:27-50`，原样节选）：
  ```ts
  export const ccSource = defineSource({
    id: 'cc',
    host: 'host/commandcode.ts',
    schedule: {
      mount: true,
      settle: true,
      railOpen: true,
      pollMs: (tick: SourceTick) => tick.railOpen ? 60_000 : null,
    },
    pulls: () => [{
      url: '/api/commandcode-usage',
  ```
  调度带两条写进注释的纪律（`adapter.ts:8-15`，原样）：`STALE-WHILE-ERROR: a failed poll records the error code and KEEPS the last good payload.`（轮询失败记错误码、**保留上一份好数据**，`-` 只留给"这个账户没有这个数"）；`STALE-WHILE-DEGRADED`（200 但切片残缺 ≠ 完整答案，残缺回复**永不替换**完整回复，只安排 5 秒后多看一眼）。还有成本护栏：只有「组件栏在屏幕上 + 相关卡已安装 + 标签页可见」才轮询（`adapter.ts:36-46` 注释，60 秒一拍）。

- **会话 projection 型**：上下文水位/token/子代理/后台任务这几个单元的数据**全部**来自会话收集器对 DSH 桥接 projection 的折叠（`src/client/data/collector.tsx:68-71, 83, 89`，原样节选）：
  ```ts
  const projected = useProjection ? useProjection('sessionStats') : undefined
  const usage = useProjection ? useProjection('tokenUsage') : undefined
  const contextPres = useProjection ? useProjection('contextPressure') : undefined
  const contextBrk = useProjection ? useProjection('contextBreakdown') : undefined
  const subagentProj = useProjection ? useProjection('subagentCatalog') : undefined
  const jobsBySession = useSessions ? useSessions((s: any) => s?.jobsBySession) : undefined
  ```
  上下文百分比在收集器里算（`collector.tsx:333-342`，原样）：`// contextPressure projection is { contextWindow?, pressureTokens?, projectedTokens? }. // Ratio = projectedTokens / contextWindow.` ⇒ `contextPercent = Math.min(1, Math.max(0, contextPres.projectedTokens / contextWindow))`。
  子代理/后台任务：`subagentCatalog` projection + 会话列表镜像 `jobsBySession`（`collector.tsx:89-99` 注释：**这是父会话自己的 projection 看不到的**，由槽根上的 `dsh-client-ui-session` 提供给每个槽组件）；最终折进 `Stats`（`src/client/data/session-stats.ts:22-53`，`usage: { inputTokens; cacheReadTokens; outputTokens } | null`、`subagents?: SubagentEntry[] | null`、`jobs?: JobInfo[] | null`）。
  cache 单元的读数就是 `usage.cacheReadTokens`，命中率与语义阈值在**组件里**不在渲染器里（`src/widgets/cache/index.ts:27-32`，原样：`/** 命中率 → 语气：越高越好。≥80% 绿、≥50% 琥珀、其余红。 */ const TONE_STEPS …`）。

**怎么更新**：收集器每次桥接 emit / projection 变化重算 `Stats` 全量下发；轮询型按适配器的 `pollMs` 节奏。更新不经过组件——组件只吃 stats。

**怎么收尾**：第三方单元注册返回**注销函数**，注销时把注册表恢复原状（`src/client/lib/registry.ts:136-153`，原样注释：`a bundle being unloaded must leave the registry exactly as it found it — the same discipline every ctx.effect follows`）；locale 键**刻意留下**（`:150-151`：`another unit may legitimately share a family key, and a stale string is harmless where a missing one renders a raw key`）。插件生命周期整体挂 `ctx.effect()`（`src/client/index.ts:73-80`，返回时逐个 dispose）。

### 1.3 槽位选择与理由

入口 `src/client/index.ts:37` `export const inject = ['slots']`，共挂四个槽（`client/index.ts:283, 320, 343, 360`）：

| 槽 | id / order | 为什么（源码注释原话） |
|---|---|---|
| `conversation.session.header.utilities` | `widgets-panel-toggle` / 5 | 开关按钮。order 5 是**量出来的**：官方导出控件 order 0、`dsh-better-sidebar` 的底栏开关 order 10，取 5 才「right of the official export control … and left of that toggle, independent of load order」（`:270-281`；order 10 曾与人家撞号，按钮位置随加载次序漂） |
| `conversation.composer.dock` | `widgets-panel-collector` / 9999 | 数据收集器挂在会话内 ⇒ mount/unmount 恰好等于「存在活跃会话」的信号（`:315-321` 注释 `its mount/unmount effects are what signal "a session exists" to the rail`） |
| `conversation.input.overlay` | `widgets-panel` / 1000 | 右栏本体。**刻意不挂 `shell.overlay`**，两条理由（`:329-341` 原样）：`1. paint order: everything in shell.overlay (z-20) paints ABOVE the right column's panel (z-10) — a rail there can never be covered by a panel; 2. semantics: the rail is a conversation-scoped utility strip … "floating entries rendered inside the resident composer card" is its natural home` |
| `settings.section` | `widgets` / 30 | 组件配置页；预览吃的是 `liveStats`——与栏里同一份 fold（`:362-364` 注释 `the 组件配置 preview shows the instance's real numbers whenever a session is running`） |

通则：**槽位选择跟着语义与 paint order 走，order 跟邻居实测走**，两个决定都有踩坑记录写在注释里。

### 1.4 ★ 我们能抄什么（对着 tools/pipeline_view.py 的六块说）/ 不抄什么

我们的六块（`tools/pipeline_view.py:11-16`）：`cards / gates / verdicts / leases / fences / worktrees`，每块写清来源（如 `gates` ← `gates/last.json`）。

**能抄的（三条）**：

1. **「单元清单」的形状**：widgets 把每个读数单元做成 `manifest.json`（id / group / sizes / source / locale）+ 声明「我等哪个源」。六块读数可以照此给每块加一个机器可读的**单元声明**（块 id、来源文件、字段表、缺源时的标注语），让 `--report` 与 `--json` 从**同一份声明**生成，而不是两处各写一遍（`pipeline_view.py` 现在的块语义同时写在 docstring、`build_reading()` 与 `_report_*()` 三处）。
2. **STALE-WHILE-ERROR**：widgets 轮询失败**保留上一份好数据 + 错误码并存**，而不是清成空。`pipeline_view.py` 的口径是「缺什么说什么」（`:19-20`，来源缺失 ⇒ 该块 `null` + note）——那是**一次性读数**的正确口径；但对**连续监测**的面板（`leases`/`gates`），可以再加一层「last-good 快照 + 错误码并存」，让一次来源抖动不至于把面板上本来有的数字抹掉。
3. **没数据退 null 的纪律**：三个组件的 gate（§1.1 末）与收集器的「unknown 成员丢掉、绝不穿传」（`session-stats.ts:62-67` 注释 `a card must never be the thing that throws inside the selector … Unknown members are DROPPED rather than passed through`）—— 与我们「不许用空对象冒充、不许猜」同宗，可以照它的措辞把「什么算缺、什么算坏、什么算未知」三态写进六块的 docstring。

**不抄的**：React/槽位/骨架那一整层 UI 机制（我们是命令行读数器，没有界面可挂）；构建期代码生成（`generated.registry.ts`）——我们六块是静态写死的，块数不增长，生成本不值。

## 二、dsh-plugin-gating-hub

### 2.1 契约预检（检查什么 / 失败怎么呈现）

**检查什么**：**升级前**的「会话格式契约」预检 —— 框架把会话消息格式升版（V3→V4）而本地运行期生产方还在写旧格式 ⇒「一发消息就报错、会话整体不可用」。包级依赖门看不见这类**运行期契约破坏**，所以单独预检。`lib/server/routes/framework-preflight.js:5-13`（原样）：
```
// 为什么要有它（2026-09-24 事故）：框架 0.1.5-rc.2 → 0.1.7-rc.1 把会话消息格式升到 V4，
// 运行期生产方（agent-presets + 插件 runtime）仍写 V3 的 `kind: 'plugin'` 包装 →
// 「一发消息就报错、会话整体不可用」。包级适配门（peerDependencies / 版本号）看不见这类
// 运行期契约破坏，所以必须在**升级前**单独预检、先把本地适配好再装。
```

扫描面 = **用户预设目录 + profile 内每个已装插件包**（`routes/framework-preflight.js:44-88` `preflightRoots()`；框架自带包也扫但**只报告不改**）。规则是**数据化**的（`lib/contracts/rules.json` + `domain/contract-rules.js`），所以对没发过升级包的框架版本同样有效；规则库缺失时 `source='unavailable'`，调用方**不得当成零发现**（`routes/framework-preflight.js:171-174` 注释原话：`预检读的是**数据化规则** … 调用方不应把它当「零发现」`）。

三种预检触发（分工写在各自文件头）：
- **手动完整预检**（会打 registry 抓目标版本契约、可能出补丁）：`routes/framework-preflight.js`（POST `/plugin-console/framework-preflight`，只读；`-patch` 路由 `mode=plan` 出 diff、`mode=apply` 备份后写回，`:186-221`）；
- **指纹变化自动预检**（**只读、不联网**）：`domain/auto-preflight-run.js:1-5`（原样：`本模块是**指纹变化自动触发**的**只读**预检 —— 不下载、不安装、不改补丁、不碰 loader`）；扫不到规则库时的兜底文案如实声明局限（`auto-preflight-run.js:30-31`：`自动预检是只读且不联网的：结论来自内置规则库与本地文件；目标版本的 registry 契约未核对（可手动跑完整预检）`）；
- **服务外预检**（dsh 起不来时的自救）：`domain/fw-preflight.js:1-30` —— 2026-10-14 真机停机事故（四个框架包被掏空）后立的**进程外**预检与治包，四条硬规矩：只补缺的 / 绝不 kill·抢端口 / 修复源必须可解释（本地 npm 缓存 + lock integrity，不联网不猜版本）/ 改前留痕（`<name>.preflight-bak-<ts>`）。

**失败怎么呈现**：预检结果是**结构化 JSON**而非报错弹窗 —— `routes/framework-preflight.js:164-180` 返回 `{ ok, targetVersion, contract, contractError, contractWarnings, contractSummary, sessionFormatVersion, rules, roots, scan, patchTarget, presetAudit }`；预设声明体检**只读不阻塞**，作为 `presetAudit` 字段随预检下发，`blockers>0` 时由面板提示先修再升（`:155-163` 注释：`升级前就能看见"补丁里的声明行已陈旧/缺失" … blockers>0 时由面板提示先修再升`）。

### 2.2 整树回滚点（备份/恢复哪些东西、存在哪）

**备份什么**：框架全树 checkpoint —— 只镜像 **`.pnpm` 里所有 `@deepseek-ai` 条目的「自包」内容** + 顶层 `@deepseek-ai` scope + `lock.yaml` + 框架 `package.json`；**不跟随依赖 junction**（避免重复拷贝），恢复时按同路径写回即可让整个依赖世界回到升级前。`lib/server/domain/framework.js:145-170`（原样，节选）：
```
/**
 * 框架全树 checkpoint（可靠回滚点）：镜像 .pnpm 中所有 @deepseek-ai 条目「自包」内容 +
 * 顶层 @deepseek-ai scope + lock.yaml。只镜像自包、不跟随依赖 junction，避免重复拷贝；
 * 恢复时按同路径写回 .pnpm 条目即可让整个依赖世界回到升级前。
 */
function checkpointFrameworkTree(fwRoot, destRoot) {
```

**存在哪**：`<stateDir>/framework-backups/<版本>/fw-tree/<ts>`（`framework.js:152` `const dest = join(destRoot, 'fw-tree', String(Date.now()))`；清理策略 `domain/framework-cleanup.js:314`：`C 档：framework-backups/<版本>/fw-tree/<ts> 快照按「回滚点那条 ∪ 最近 N 条」保留，其余删除`；**回滚点引用的那一条永不删** —— `framework-cleanup.js:418`：`/** 回滚点引用的路径（framework-rollback.json 的 checkpointDir / cliBackupDir）—— 这些永远不删。 */`）。

**可用性判定**（★ 值得抄的细节）：回滚点 = **记录存在 且 checkpoint 目录仍在**，双验，防止"记录在、实物没了还骗用户能回滚"。`domain/compat-state.js:158-175`（原样，节选）：
```
/** 回滚点：记录存在 **且** 其 checkpoint 目录仍在（记录在、目录没了 = 实际不可用，不能骗用户）。 */
function readRollbackRecord() {
  …
  applicable: fwRoot !== null && existsSync(fwRoot),
  …
  reason: applicable ? null : '框架树路径不存在（可能已被清理或换了安装根）',
```

### 2.3 ★ 「有确证证据才自动禁用」：证据形状 + 怎么避免误禁

权威实现：`lib/server/domain/auto-disable.js`（全文 226 行读完）。**证据形状 = 白名单枚举码**，每个码一句人话（`auto-disable.js:33-38`，原样）：
```js
const EVIDENCE_CODES = {
  'package-unresolvable': '包在所有解析基准上都解析不到（确证缺失）',
  'file-target-missing': 'file:// 目标文件确实不存在（确证缺失）',
  'boot-log': '启动失败日志点名了这一行',
  'boot-quarantine': '升级脚本留下的启动失败隔离记录点名了这一行',
}
```

**避免误禁的五道栏**（`auto-disable.js:10-18` 头注释 + 实现逐条对应）：

1. **非证据码成对列出**，让「为什么没禁」可查而不是静默放过（`auto-disable.js:41-47`，原样）：
   ```js
   /** 明确**不算**证据的形态（写在这里是为了让"为什么没禁"可查，而不是静默放过）。 */
   const NON_EVIDENCE_CODES = {
     'subpath-unresolvable': '子路径解析不到（父包还在，可能只是导出变了）',
     'row-without-name': '行既没有 name 也没有 config（形态可疑但无证据）',
     …
   ```
2. **解析不确定 ⇒ 整批只报告、绝不写盘**（`:76-80`：`resolution-uncertain` 时全部进 skipped，`hasEvidence: false`）。
3. **身份豁免**：`@deepseek-ai/*` 与裸 `dsh-*` 框架自带包**永不**自动禁用（`:49-55`）、核心行（`CORE_PATCH_ROW_IDS`）与受保护行跳过（`:88, 96`）、自己不禁自己（`:89`）。
4. **禁前先写 last-known-good 快照**，**没有可回滚材料就不动手**（`:172-179`，原样）：
   ```js
   // ③ 禁前先写 last-known-good 快照：没有可回滚材料就不动手
   const snap = ensureSnapshotForCurrentState({ … })
   if (snap.ok !== true) {
     return { ok: false, code: 'snapshot-failed', … error: `禁前快照失败，已放弃自动禁用：…` }
   }
   ```
5. **开关 + 留痕**：`compat-gate.json#autoDisableOnEvidence`（默认开，关了退回"只报告 + 等你点"，`:18`）；每次动作**追加一条 JSONL**（永不覆盖历史，`:29-30`），记录里带 `evidence`（逐行：rowId / moduleName / code / detail）、`snapshotId`、`restoreCommand: 'node scripts/safe-boot.mjs --restore-last-good'`（`:186-200`）——**每条禁用记录自带一键回滚命令**。

顺序也有讲究（`:142-146`，原样）：`计划（纯判定）→ 禁前快照（当前状态有可回滚材料）→ 复用 disableSuspects（改前备份 + 严格 YAML 闸门 + 原子写 + 读回核实）→ 追加可读记录。任一步失败都如实返回，**绝不部分静默**`。判定函数本身是**纯函数不写盘**（`:58`），判定与落盘分离。

### 2.4 兼容声明（peerDependencies / engines / 别的）→ 我们能抄什么

**都不是裸的** —— 判定顺序（`lib/server/domain/compat.js:45-95` `checkPluginFrameworkCompat()`）：

1. **显式声明优先**（`compat.js:57`，原样）：`const declared = pkg?.dsh?.engines?.framework ?? pkg?.dsh?.compat?.framework ?? pkg?.engines?.dsh ?? null` —— 是 **`dsh.*` 命名空间下的框架版本声明**（三种键位兼容），不是裸 `engines.node` 也不是裸 `peerDependencies`。
2. **硬判据：源码扫描**（`compat.js:63-70`，原样注释）：`【硬判据】提供 pkgDir 时扫描包源码：命中已删除的 dsh-settings API（settingsNamespace / installSettingsSection）→ 直接 fail（2026-09-04 教训：0.3.6 全家仍引用旧 API，静态声明/依赖检查判 pass 是假通过，loader 单行失败 = 服务崩溃）`。源码扫描干净时，声明/依赖范围**只作参考不作 fail 依据**（避免"假拒绝"：`:71-73` `源码扫描干净 = 权威判据：依赖范围可能滞后旧版（"假拒绝"），不作为 fail`）。
3. **依赖面兜底**：`dependencies / peerDependencies / optionalDependencies` 里 `@deepseek-ai/*` 的范围任一不含框架版本 ⇒ fail（`compat.js:74, 85-92`）。
4. **运行期冒烟**：启用前在**独立子进程**里动态 import 插件主模块，8 秒超时，探测失败/超时按不通过处理 —— **宁可拒绝，不冒险拖崩服务**（`compat.js:100-104` 注释原话：`启用前冒烟检查（服务永不崩机制）… 子进程失败不影响控制台；探测失败/超时按"不通过"处理（宁可拒绝，不冒险拖崩服务）`）；`compat.js:107` `spawn(process.execPath, […], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })`。

**我们能抄什么 / 不抄什么**：抄「**声明 → 静态硬判据 → 冒烟**」三级递进与"声明只作参考、源码才是权威"的口径（对我们：台账/预声明的 `paths` 域是声明，卡树实际改动是源码级判据 —— 主控已有的「收批时按卡树实际改动重跑域检查」与它同构，可互相印证）；抄回滚点「记录 + 实物双验」（我们的 `wb_task.py` 成送/收口状态可加同款双验）。不抄：整个框架升级 / `.pnpm` 镜像域（我们没有 pnpm 框架树；我们对应物是 git 树本身，`git` 已是权威回滚点）。

## 三、dsh-pilot

### 3.1 CDP 发现与驱动（怎么找到 Edge/Chrome、会话怎么隔离）

**可执行文件发现**：硬编码候选表按序 `existsSync`（`src/index.js:26-36` `EDGE_CANDIDATES`，覆盖 Windows x86/x64/D 盘、Linux、macOS 的 Edge/Chrome/Chromium），找不到就响亮报错：`'pilot: no Edge/Chrome executable found; install one or set edgePath'`（`src/index.js:258`）。

**CDP 端口怎么找（★ 它自己管 `--remote-debugging-port`）**：先用 **bind 探测**选空闲端口（9222 起、扫 40 个），并且注释里写明**为什么不能用 HTTP 探测**（`src/index.js:71-84`，原样）：
```
/**
 * Whether 127.0.0.1:port can still be bound — the only authoritative free-port
 * test. An HTTP probe is not: a busy browser can miss the probe window, and a
 * port reported free that way is how a pilot used to attach itself to another
 * session's browser instead of starting its own.
 */
```
然后**自己拉浏览器进程**并把调试端口写进 argv（`src/index.js:295-297`，原样）：
```js
    const argv = [
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${this.profileDir}`,
```
CDP 走 Node ≥22 原生 WebSocket、零运行时依赖（`src/index.js:6` `talks CDP over the native Node >= 22 WebSocket (zero runtime dependencies)`；`src/index.js:143` `/** Minimal CDP client over the native WebSocket. */`），先 `Page.enable / Runtime.enable / DOM.enable`（`src/index.js:342-344`）。

**会话怎么隔离**（两层）：
1. **每个 agent 会话一个浏览器实例**：池按 `exec.agent?.session?.id ?? 'default'` 发实例（每个工具 execute 里 `pool.for(exec.agent?.session?.id ?? 'default')`，如 `src/index.js:1193-1195`），池上限 `POOL_CAP = 8`（`src/index.js:39`），每实例一个临时 profile（`mkdtemp(join(tmpdir(), PROFILE_PREFIX))`，`src/index.js:291-293`），异常退出的 profile 也有回收路径（`src/index.js:316-321` 注释：`An unexpected exit owns a profile too: without this the directory outlives the browser and nothing ever revisits it.`）。
2. **防"认错浏览器"**：端口起好后校验 `/json/version` 的 `webSocketDebuggerUrl` 确实是**自己刚拉起的那个**（`src/index.js:367-373`，原样）：
   ```js
        // Own the endpoint: a browser answering on this port that is not the
        // child just spawned belongs to another session, and driving it would
        // hand this session's navigation to a stranger's page.
        if (!String(version.webSocketDebuggerUrl ?? '').includes(`:${port}/`)) {
          foreign = true
          continue
        }
   ```
   认出是别人家的就报错重选端口：`pilot: port ${port} is answering for another browser session; retry to pick a free port`（`src/index.js:381`）。操作串行化靠每实例 `opLock`（`src/index.js:272-274` `withOp()`）。

### 3.2 ★ ref 失效「响亮失败」的判据与提示

**判据**：快照时给每个可交互元素钉一个**从 1 起的编号 ref**（`src/index.js:430` `els.push({ el, ref: els.length + 1, tag, type, label, href })`），元素表挂在页面侧 `window.__pilotEls`；点击/输入按 `ref - 1` 取表项，**取不到就是失败返回，绝不猜、绝不静默降级**（`src/index.js:593-595`，原样）：
```js
          if (!entry) return { ok: false, error: 'stale or unknown ref ' + ${JSON.stringify(String(target))} + ' — run pilot_snapshot for the current numbered list' }
```

**提示里给什么**：三样 —— 发生了什么（`stale or unknown ref <N>`）、为什么（页面变了 ref 就失效，写在工具描述里：`src/index.js:1248-1251` `Re-run after navigation; refs go stale when the page changes.`）、**下一步做什么**（`— run pilot_snapshot for the current numbered list`）。selector 兜底同样响亮：`'no element matches selector'`（`src/index.js:599`）/ `'no element matches the given ref or selector — run pilot_snapshot first'`（`src/index.js:628`）。

**配套**：快照带 diff（`src/index.js:450-451` `const changed = diffSnapshots(this.lastSnapshot, …)`；`src/index.js:1057` `/** Element fingerprint for cross-snapshot matching (heuristic, not DOM identity). */`），`pilot_diff` 工具专吃「动作到底有没有生效」而不必整页重读（`src/index.js:1256-1258` 描述：`Use it after an action (click/type/press) to judge whether the action had the intended effect`）。

### 3.3 cockpit 面板的数据通道

**一条 same-origin HTTP 通道，无 RPC 桥**（`src/client/index.jsx:3` 原样：`Talks to the host over same-origin fetch to /dsh-pilot/* (no RPC bridge).`）：

- **状态**：面板打开时每 2 秒 `GET /dsh-pilot/state`（`src/client/index.jsx:10` `const POLL_MS = 2000`；`:89-104` 轮询循环）。
- **截图**：状态里 tick 自增做缓存击穿，`<img src="/dsh-pilot/shot.png?t=${tick}">`（`src/client/index.jsx:156-157`）；宿主侧 PNG 是 CDP `Page.captureScreenshot` 的最近一帧内存缓存（`src/index.js:809-810`），没有就用 204（`src/index.js:1161-1163`）。
- **动作**（启动/关闭/导航/切换会话）：`POST /dsh-pilot/<action>`（`src/client/index.jsx:70-78` `post()`）；会话切换是 `POST /select-session`，值必须是 `"latest"` 或已知会话 id，否则 400（`src/index.js:1156-1160`：`sendJson(res, 400, { error: 'session must be "latest" or a known session id' })`）。
- **宿主侧注册**：`webServer.register({ kind: 'prefix', path: '/dsh-pilot', … })` 挂进 DSH 的 web 服务（`src/index.js:1136-1139`）—— 复用宿主同一端口，pilot 不自己开第二个端口服务面板。
- **动作日志**：随 state 一起下发（`log` 数组，`MAX_LOG = 200` 条，`src/index.js:37`），面板只显示最后 4 条（`src/client/index.jsx:180-184`）。

### 3.4 安全边界（能不能访问任意本机端口/文件，边界写在哪）→ 我们能抄什么

**边界全写在两处**：`src/index.js` 头部常量区（`:25-44`）与 loopback 路由注册处（`:1136-1144`）：

| 边界 | 落点（文件:行号） | 原样 |
|---|---|---|
| 面板 API 只听回环 | `src/index.js:27, 1140-1144` | `const LOOPBACKS = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])` … `if (!LOOPBACKS.has(remote)) { sendJson(res, 403, { error: 'loopback only' })` |
| 导航 URL 必须 http(s) | `src/index.js:1169-1172` | `if (typeof body.url !== 'string' \|\| !/^https?:\/\//.test(body.url)) { sendJson(res, 400, { error: 'url must be an http(s) URL' })` |
| 上传文件必须绝对路径 | `src/index.js:744` | `if (typeof path !== 'string' \|\| !isAbsolute(path)) return { ok: false, error: 'every upload path must be absolute' }` |
| 字节上限 | `src/index.js:32-34` | `const MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024`、`const MAX_UPLOAD_BYTES = 100 * 1024 * 1024` |
| 端口只在自己控的 9222..9261 里挑，且必须 bind 得上 | `src/index.js:265-270` | `async pickPort(base = 9222) { for (let port = base; port < base + 40; port++) { if (await canBind(port)) return port }` |
| 浏览器文件系统面 = 独立临时 profile | `src/index.js:291-293` | `this.profileDir = await mkdtemp(join(tmpdir(), PROFILE_PREFIX))` |

它**能**驱动浏览器去任何 http(s) 网址（`pilot_eval` 能在页面上下文跑任意 JS，`src/index.js:1402-1410`）—— 边界不在"能不能上网"，而在：**进程面**（只拉自己控的浏览器、只连自己验明正身的 CDP 端点）、**API 面**（loopback only）、**文件面**（上传要绝对路径 + 限额、下载默认落会话工作区/临时目录 + 限额）。工具描述里也把授权责任写给了模型：`Upload only files the user has authorized for the current site.`（`src/index.js:1322`）。

**我们能抄什么**：① `canBind` 的 bind 探测 + 「HTTP 探测不权威」这条注释（我们任何起本地服务的工具都适用）；② 认错浏览器/认错端点的「验明正身」一步（对应我们：接任何本机服务前先验 `/json/version` 级别的身份，而不是端口通就连）；③ 错误消息三件套（发生了什么 / 为什么 / 下一步跑哪条命令）—— 与我们判决文件的「还原命令」同构。**不抄**：CDP 驱动与浏览器池整层（我们没有浏览器域）。

## 四、★ 三条「直接可用」的建议

1. **给六块读数落一份「机器可读单元清单」，让 `--json` 与 `--report` 同源**。
   改哪个文件：`tools/pipeline_view.py` —— 在模块级加一个 `BLOCKS` 声明表（每块：`id`、来源文件、缺源标注语、字段名），`read_*()` 与 `_report_*()` 都从它取口径（现状：块语义同时写在 docstring `:11-16`、`build_reading() :286-293`、各 `_report_*()`，三处人肉同步）。
   怎么验：`python -X utf8 tools/pipeline_view.py --json` 连跑两次**逐字节相同**（幂等不变量，`pipeline_view.py:23` 已立）＋ 故意把 `gates/last.json` 改名 ⇒ `gates` 块给 `null` + 声明表里的那句标注语（而不是空对象）；`--report` 里同一块的名字与来源与 `--json` 一致。
2. **连续监测的块加「STALE-WHILE-ERROR」：坏读数不清空，与错误码并存**。
   改哪个文件：`tools/pipeline_view.py`（`gates` / `leases` 两块）—— 读数失败时若有上一份好读数（落一份 last-good 快照，可放 `gates/diag/`），返回 `last_good` + `error_code` + `stale_for_s`，而不是直接 `null`；一次性读数口径「缺什么说什么」保留给静态块。依据：widgets 的 `STALE-WHILE-ERROR`（`families/cc/adapter.ts:10-12`）——「一次轮询失败不该把已经显示的数字抹掉」。
   怎么验：先把来源文件临时改名跑一次（记下读数），恢复后再改名跑一次 ⇒ 第二次 `--json` 里该块仍是上一份好值 + 错误标注，`--report` 不出现无解释的空块；恢复原状后连跑两次仍逐字节相同。
3. **端口探测一律用「能不能 bind」，并把「验明正身」写进接入序列**。
   改哪个文件：`tools/serve.py`（及任何将来要挑本地端口的工具）—— 挑端口照抄 `canBind`（`pilot/src/index.js:76-84`）的 bind 探测；接入已有服务前先取一个身份指纹（如 `/json/version` 式的自述端点）确认「连的是谁」再发请求。
   怎么验：占住目标端口起一个假监听（比如 `python -c` 裸 `socket`）⇒ 挑端口逻辑必须报忙并顺延，而不是靠 HTTP 探测超时误判空闲；对假监听做身份校验 ⇒ 必须以「验明失败」拒绝接入，错误信息里带上下一步排查命令。

## 验收（原样读数）

### 1. 三仓版本

```
git -C D:/repo/_refs/dsh/widgets-src rev-parse --short HEAD  ⇒ 293c029
git -C D:/repo/_refs/dsh/gating-src  rev-parse --short HEAD  ⇒ 792cead
git -C D:/repo/_refs/dsh/pilot-src   rev-parse --short HEAD  ⇒ a1dc0b3
```

### 2. 每仓读过的文件（路径 + 行数；「部分读」指只读了与问题相关的段）

**dsh-widgets**（293c029）：
- `src/widgets/context-water/manifest.json`（20 行，全读）＋ `src/widgets/context-water/index.ts`（59 行，全读）
- `src/widgets/tokens/index.ts`（57 行，全读）＋ `src/widgets/cache/index.ts`（91 行，全读）
- `src/client/lib/registry.ts`（164 行，全读）
- `src/client/lib/contract/external.ts`（约 125 行，部分读）
- `src/client/lib/contract/types.ts`（1520 行，部分读：1440-1520 + grep 定位）
- `src/client/data/sources.ts`（部分读：1-100 + grep）
- `src/client/data/collector.tsx`（404 行，部分读：40-120、320-365 + grep 行号）
- `src/client/data/session-stats.ts`（376 行，部分读：1-90 + grep）
- `src/client/index.ts`（406 行，部分读：1-80、270-406 + grep 行号）
- `src/client/families/cc/adapter.ts`（部分读：1-95 + grep 行号）
- `src/host/context.ts`（39 行，全读）

**dsh-plugin-gating-hub**（792cead）：
- `lib/server/domain/auto-disable.js`（226 行，全读）
- `lib/server/domain/framework.js`（539 行，部分读：120-230 + grep 行号）
- `lib/server/domain/compat-state.js`（部分读：140-210 + grep 行号）
- `lib/server/domain/compat.js`（558 行，部分读：40-130 + grep 行号）
- `lib/server/domain/fw-preflight.js`（351 行，部分读：1-60）
- `lib/server/routes/framework-preflight.js`（227 行，部分读：1-80、150-227 + grep 行号）

**dsh-pilot**（a1dc0b3）：
- `src/index.js`（1481 行，部分读：1-80、255-430、480-620、1125-1290、1310-1481 + grep 行号）
- `src/client/index.jsx`（214 行，全读）
- `dsh.plugin.json`（12 行，全读；内容：`{ "name": "dsh-pilot", "client": "./lib/client.js", … }` 形态的 DSH 插件清单）

### 3. §四 三条建议

见上（每条指名改我们哪个文件 + 怎么验）。

### 4. 本卡不碰代码

`python -X utf8 -m ruff check` 与 pytest 均未跑（卡规格明说不需要）；`git status --short` 见下（只新增本文件）。

### 5. 老实说（边界）

- ★ **widgets 仓超了「每仓最多 10 个文件」的预算**：实读 12 个源文件（另加 manifest/package 两份清单）。超的 4 个（`types.ts`、`collector.tsx`、`session-stats.ts`、`client/index.ts`）都是「>2000 行看相关段 / 只读相关段」式的部分读，且都在四个问题点的必经链上（声明→注册→数据→槽位）；没有整仓扫。
- gating-hub 的 `lib/` 是**构建产物**（打包后的 JS）；深读读的是它仓库里的 `lib/server/**` 源码模块（该仓以 lib 直发，源码即此形态），没有读打包成单文件的 `lib/client.js`（6281 行）。
- 本卡未逐字读三仓 README（按卡规格：README 已由主控读过、本卡只读源码），因此「README 与源码冲突」一条是**没采集**而不是「零冲突」。
- 未按 pin_check 流程查字面：本卡是**新增文件**，不改任何既有文件的字面/常量，pin_check 不适用（如需，请主控复核时示下）。
