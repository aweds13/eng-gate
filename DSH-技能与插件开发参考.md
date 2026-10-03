# DSH 技能与插件开发参考

> 本文是我在你这台机器上实际读文档 + 实测得到的**查法、结论与坑**。
> 证据标记：✅ 本机实测 ｜ 📖 官方 README ｜ 🔧 源码 ｜ ⏳ 未验证
> 根路径简写：`R` = `C:/Users/example\AppData\Local\npm-cache\_npx\b86ed90107c62dab\node_modules\@deepseek-ai`
> 　　　　　　 `H` = `C:/Users/example\.dsh`

---

## 0. 先记住一句话

**DSH 没有集中的文档站。文档就是每个包自己的 README，而"什么知识在哪"本身需要一张地图。**

---

## 1. 文档地图：想知道什么，去读哪个文件

| 我想知道 | 去读 |
| --- | --- |
| 某个包是干嘛的（一句话） | `R\<包名>\package.json` 的 `description` |
| 某个包的设计、用法、限制、示例配置 | `R\<包名>\README.zh.md`（中文）或 `README.md` |
| 某个包对**请求前缀/缓存**的影响 | 在 README 里搜 `KV Cache 影响` |
| 某个包**给模型看到什么** | README 里的 `## 模型体验` 小节 |
| 某个包**做不到什么** | README 里的 `## 已知限制与延期工作` |
| 技能怎么写 | `R\dsh-agent-presets\presets\cordis\skills\*\SKILL.md`（仅两篇，但是范例） |
| 技能系统怎么运作 | `R\dsh-skill\README.zh.md`、`dsh-skill-filesystem\README.zh.md`、`dsh-tool-skill\README.zh.md` |
| 组成（composition）怎么写 | `R\dsh-agent-presets\presets\standard\agent.cordis.yml`（最佳模板，带解释性注释） |
| 两个平面怎么分 | 同上文件头部注释 + `dsh-base\README.zh.md` |
| agent 的作用域与事件词汇 | `R\dsh-agent\README.zh.md` |
| 预设的装配/切换/代际 | `R\dsh-agent-presets\README.zh.md` |
| agent 驱动器与 setup 钩子 | `R\dsh-agent-loop\README.zh.md` |
| AGENTS.md / CLAUDE.md 机制 | `R\dsh-agent-instructions\README.zh.md` |
| profile、patch 分层、插件安装 | `R\dsh\README.zh.md` |
| 工具流水线与限制 | `R\dsh-tools\README.zh.md` |
| 沙箱能做什么 | `R\dsh-sandbox\README.zh.md`、`dsh-sandbox-policy\README.zh.md`、`dsh-fs-sandbox\README.zh.md` |
| 审批能做什么 | `R\dsh-user-approval\README.zh.md` |
| 权限档位 | `R\dsh-permission-presets\README.zh.md` |

### 关键路径

```
R\<包名>\README.zh.md          231 个包都有（英文版 README.md 同目录）
R\<包名>\README.i18n.yaml      文档的 i18n 源
R\<包名>\lib\index.js          实现
R\<包名>\lib\types\*.d.ts      类型 + JSDoc（注释本身就是文档）
R\dsh-agent-presets\presets\
    standard|ptc|minimal|cordis\
        agent.cordis.yml       组成
        preset.yml             显示名/描述/排序
        skills\<名>\SKILL.md   preset 自带的技能
H\settings.yaml                用户设置
H\profiles\web\package.json    profile 清单（bundles + patchReload）
H\profiles\web\cordis.patch.yml 用户 patch 层
```

### 📖 哪些文档**没有**随安装包发布

README 里大量链接指向这些，但**文件不存在**（`docs` 目录不在安装产物里）：

- `docs/subsystems/core.zh.md`、`session.zh.md`、`scope.zh.md`、`system-prompt.zh.md`
- `docs/config-catalog.zh.md` ← 每个配置字段的穷尽真源，很可惜看不到
- `docs/user/guide/**`、`docs/user/develop/practice/**`
- `.agents/notes/implemented/**`

**替代**：`dsh --dump-config` / `--dump-default-config` 能导出**实际生效**的配置树。

---

## 2. 查文档与查运行时的具体方法

### 2.1 找文档

```powershell
$R="C:/Users/example\AppData\Local\npm-cache\_npx\b86ed90107c62dab\node_modules\@deepseek-ai"
# 列全部 README
Get-ChildItem $R -Recurse -File -Filter README.zh.md | ForEach-Object { $_.FullName.Replace($R,"") }
# 找"哪些包提到某机制"
Get-ChildItem $R -Recurse -File -Filter README.zh.md | Select-String -Pattern "KV Cache 影响"
```

### 2.2 查运行时（动态插件的 Inspect 提供方）

先 `cordis_inspect_list`，再用 `cordis_inspect_query`：

| platform | provider | method | 用途 |
| --- | --- | --- | --- |
| host | `Service` | `listService` | 不带 `service` = 全部服务+签名目录；带 = 精确契约+类型 |
| host | `Event` | `listEvents` | 同上，事件与监听器签名 |
| host | `Builtin` | `listBuiltins` | 动态宿主半可用哪些全局符号 |
| host | `Tool` | `listTools` | 当前 agent 可见的全部工具 schema |
| client | `Service` / `Event` / `Builtin` | 同上 | 浏览器侧 |
| client | `Slots` | `listSubTree` | 不带 `root` = 紧凑树；带 = 精确注册契约+props |
| client | `Theme` | `listTokens` | 主题 token |

> ⚠️ `Tool.listTools` 输出极大。想在插件里自报数据，**注册一个自报告工具**比 dump Inspect 便宜得多。

### 2.3 校验组成

- `ctx.agentPresets.standingKeyFor(id)` = **真正的挂载校验器**：会拒绝"包找不到 / config 非法 / 行没激活 / 服务发布到根 realm"四种，并报出确切原因 ✅
- 不要用 roster 的 `broken` 字段当校验（那只是形状检查）📖

### 2.4 安装与检查

```sh
dsh --profile web --dump-config          # 看合成后的配置树
dsh plugin --profile web add <包或本地目录>   # 转发给 pnpm
dsh plugin --profile web remove <包>
```

⚠️ 换已挂载包的 manifest **需要重启**（manifest 身份在进程存活期内缓存）📖

---

## 3. Skill 系统：完整知识

### 3.1 三个词汇

| 词汇 | 含义 |
| --- | --- |
| **provider** | 技能的来源，注册在 `ctx.skills` 上 |
| **layer（层）** | 注册落在哪个作用域。**就近层直接赢得重名** |
| **rank（根排名）** | 同一个 provider 内、不同扫描根的优先级，数字越小越优先 |

**层**：注册落进「调用上下文所属的层」——
- host 行 / 动态插件 → **根层（进程级）**
- preset 常驻挂载的插件 → **那个 preset 的层**
- `agent.ctx` 注册 → **那个 agent 自己的层** ✅

读取 = 「全局层 + 观察 scope 的链」合并，**就近层赢重名**。

### 3.2 六个扫描根与 rank 📖🔧

| rank | 路径 | source |
| --- | --- | --- |
| 100 | `<项目>/.dsh/skills` | `project-dsh` |
| 200 | `<项目>/.agents/skills` | `project-agents` |
| 300 | `customSkillDirs`（preset 自带目录走这里） | `custom` |
| 400 | `~/.dsh/skills` | `user-dsh` |
| 500 | `~/.agents/skills` | `user-agents` |
| 600 | bundled（预留） | `bundled` |

> **最容易搞错的一点**：`~/.dsh/skills` **不是全局层**。它是**每个 preset 自己的** `skill-filesystem` 行扫出来的，落在**那个 preset 的层**里 ✅

### 3.3 SKILL.md 规格

两种布局都认：
- **目录束**：`<root>/<技能名>/SKILL.md`（可以有 `references/`、`scripts/`、`assets/`）
- **平铺**：`<root>/<技能名>.md`

frontmatter 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | ✅ | kebab-case，小写字母/数字/连字符 |
| `description` | ✅ | **这是触发器**，模型只靠它决定要不要加载 |
| `whenToUse` | — | **驼峰**（不是 `when-to-use`）；写错会被静默忽略 |
| `disable-model-invocation` | — | `true` → 不进模型目录，`skill` 工具点名被拒 |
| `user-invocable` | — | `false` → `/点名` 无效 |
| `metadata` | — | 任意键值 |

**踩坑（会直接抛错）**：`modelInvocable`、`userInvocable`、`disableModelInvocation` 这些是**被拒绝的旧键名**，写了会抛 `frontmatter field "x" is unsupported` 🔧

### 3.4 调用策略四象限

| modelInvocable | userInvocable | 效果 |
| --- | --- | --- |
| ✅ | ✅ | 默认：我能自动加载，你也能 `/点名` |
| ❌ | ✅ | **只有你点名才能用**（描述都进不了我的上下文）—— 做"绝对屏蔽"用这个 |
| ✅ | ❌ | 只有我能自动加载，`/点名` 无效 |
| ❌ | ❌ | 完全隐身（同名遮蔽时用这个） |

### 3.5 生效时机与刷新机制 ✅📖

- 目录变化在**下一个模型步骤**生效（`tool-skill` 每步重新快照，digest 变了就**追加**一条替换目录消息）
- 只有 **`SKILL.md` 级**变更触发刷新；技能内部 `references/`、`scripts/` 的编辑**不触发**
- 允许新增、删除、替换；删除会从我的目录里消失 📖"空替换会显式停用较早的名称"

### 3.6 目录如何进上下文 / `/点名` 手势

- 目录以 `<available_skills>` 消息注入；**`skill` 工具对该 agent 不可见时，目录为空** 🔧
- `/name` 手势正则 🔧：`(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)`，只在**直接用户消息**里扫描
- 命中后 Host 在 `agent/pre-step` 里把技能正文作为 `instructions` 注入 → **在我的第一个步骤之前就在上下文里**
- 所以 `/点名` 能保证"读过"，**不能保证"照做"**

### 3.7 Provider API 📖

```ts
ctx.skills.registerProvider(create: (control: SkillProviderControl) => SkillProvider): () => void
ctx.skills.register(skill: SkillRegistration): () => void
ctx.skills.list(options?: SkillViewOptions): Promise<SkillSummary[]>
ctx.skills.snapshot(options?): Promise<SkillCatalogSnapshot>
ctx.skills.get(name, options?): Promise<SkillDefinition | undefined>
```

- `SkillRegistration` = `Omit<SkillDefinition,'invocation'|'provider'> & { invocation?, provider? }`
  → 必填：`name`、`description`、`source`、`content`
- `SkillViewOptions` = `{ cwd?, signal?, scope? }`；**省略 `scope` = 只读全局/根层**
- `ctx.skills.register` 在**整个部署里零个一方调用者** 🔧 —— 这套运行时注册 API 从没被用过（所以怎么用没有范例，得自己摸）

### 3.8 明确**不存在**的东西

- ❌ 按会话开关单个技能的 RPC（技能的 Remote 只有 `list`）📖
- ❌ 任何 skill 相关的 settings 命名空间 📖
- ❌ 技能声明"我允许用哪些工具"（`allowed-tools` 全库无匹配）🔧
- ❌ 把全局技能"排除"出某个会话的手段（只能同名遮蔽，或关掉整个默认根）📖

---

## 4. 插件系统：完整知识

### 4.1 两种插件，别混

| | 组成式插件 | 动态 Cordis 插件 |
| --- | --- | --- |
| 形态 | `cordis.yml` 里的一行 | `cordis_define` + `cordis_run` |
| 寿命 | 进程/部署级，重启仍在 | 只在当前进程内存，重启即无 |
| 作用 | 常驻能力 | 探测、实验、临时扩展 |
| 授权 | 由配置授权 | Client 半需要一次授权（审批关闭时会被自动拒绝）|

### 4.2 两个平面（决定一行该放哪）

- **宿主组成**：注册表本身（`tools`/`systemPrompt`/`agents`/`agent-loop`/`sessions`）、跨会话的东西（持久化、设置、凭据、遥测）、沙箱与审批栈、模型路由、subagent 注册表
- **agent preset**：一个会话贡献给这些注册表的东西 —— 它的工具、人设、提示词段

**判定规则**：**发布服务且外面有人消费的行，不能散放在 preset 里**，必须放进带 `isolate` realm 的 group；否则第二个会话挂载同一 preset 会撞车，挂载审计会直接拒绝 📖✅

### 4.3 组成分层与 patch

```
空根
 → dsh.profile.bundles 各组合包的 patch
 → profile 的 cordis.patch.yml
 → H\cordis.patch.yml            ← home 级用户 patch 层
 → --patch 覆盖层
```
`patchReload: live` 会**监视** profile 与 home 级 patch 文件 → 这些改动是**热**的 📖✅

patch 语义：**替换整行 config，不是合并** —— 每一行要重述它拥有的全部键 📖

### 4.4 preset 的机制与硬约束

- 一个 preset = 一个目录：`agent.cordis.yml`（必需）+ `preset.yml`（显示元数据）
- 放在 `H\.agent-presets\<id>\`；随附集合在 `R\dsh-agent-presets\presets\`
- **每个 preset 在进程内只挂载一次**（常驻 scope），会话通过 scope 认父加入
- **代际只以 `agent.cordis.yml` 的 stamp 为键**：已加入的会话保持原代际；**改组成只影响新会话** 📖
- **只有空会话能换 preset**；一旦有消息或工具调用就锁定 📖✅
- **被替代的代际永不回收**（每轮"改完再建会话"会多一套活的目录 watcher）📖
- 创作 = 复制：`ctx.agentPresets.copy(from, id, name)`（host 侧执行，不需要提权；会解引用符号链接保证自包含）📖
- ⚠️ **不要从 `cordis` 复制**：它自带 `tool-cordis`，注册进程级 inspect provider，与运行中的 `cordis` 撞车 ✅

### 4.5 作用域与"能注册什么"

| 作用域 | 怎么拿到 | 注册影响范围 |
| --- | --- | --- |
| 根（全局） | 动态插件的 `ctx` | 所有会话（但会被更近的层压过）✅ |
| preset | 由 preset 挂载的插件 | 该 preset 的全部会话 |
| **agent** | `agent.ctx`（工具执行的 `exec.agent.ctx`）| **只有那一个会话** ✅ |

`agent.ctx` 能注册（📖，且技能这条我实测过 ✅）：
工具、提示词段、变量、事件监听器、**限制**、**技能**
> 文档原话："同一机制也是 agent preset 用来让一个会话获得不同能力集、同时不影响其邻居的方式。"

### 4.6 生命周期与 disposer 纪律（我踩过）

- 每一个 `register*` / `on` / `effect` 都返回 disposer，**必须保留或交给 `ctx.effect()`**
- ⚠️ **实测坑**：`tools.guard` 通过 `agent.ctx` 注册后，**不保留 disposer 就永远摘不下来**（撤销插件也没用，因为 guard 挂在 agent 的作用域上，不是插件 fiber 上）
- ⚠️ `guard` 是**单调**的：任何 guard 能拒绝，但**没有 guard 能放行**被别的 guard 拒绝的调用

### 4.7 动态插件的技术约束

- `code.host` / `code.client` 是**纯 JS 函数体**，返回一个 Cordis Plugin 对象；无 TS/JSX/import
- 宿主半可用 Builtin：`ctx`（**只有 get/on/provide/effect**）、`harness`（`handle` / `defineTool` / `registerTool`）、`console`、`btoa`/`atob`、`TextEncoder`/`TextDecoder`
- 客户端 React 必须 `React.createElement(...)`；UI 必须注册进查询到的 Slot
- ⚠️ `harness.defineTool` 的 `parameters` **不能写 `additionalProperties: false`**（隐式参数根是开放的）✅
- Client 半需要一次授权；**审批被关掉时，这类请求会被自动拒绝**

### 4.8 上线路径

1. 做成一个包（本地目录即可，⏳ 不必发布 npm）
2. `dsh plugin --profile web add <路径>`
3. 在组成里加行（preset 的 `agent.cordis.yml`，或 patch 层）
4. 重启 profile（换 manifest 必须重启）

---

## 5. 边界与权限：原生到底能做什么

| 你想限制 | 原生能不能 | 靠什么 |
| --- | --- | --- |
| 写某个目录以外 | ✅ 能，但要**会话 cwd = 那个目录** | `workspace-write` 沙箱 |
| 读某个目录以外 | ❌ **读不受限**（Windows 下 ACL runner 只限写）| —— |
| 多几个允许目录 | ❌ 每会话**只有一个**工作区根 | —— |
| 禁某个工具名 | ✅ `tools.restrict({allow,deny})`，但需 `agent.ctx` | 自己写 |
| 禁某些命令 / 参数级规则 | ❌ 原生**完全没有** | `tools/pre-execute` 自己写 |
| 网络/进程/凭据 | ❌ 沙箱策略**只表达文件操作** | —— |
| 靠审批做参数级规则 | ❌ 审批请求**不携带工具参数**，且只有"仅本次允许" | —— |

**工具流水线** 📖：`tools/pre-execute`（allow / **deny+reason** / **ask**）→ 单调守卫 → 执行 → `tools/post-execute` → 只观测的 `tools/result`

**选型建议**：
- 要"越界被拦 + 给理由 + 我自行改正" → **`pre-execute`**（可撤销）
- 要"这个会话根本不许用某个工具" → `restrict`
- **不要用 `guard`**（单调、丢了 disposer 就摘不下来）

---

## 6. KV Cache：这个系统的核心约束

**DSH 的 231 个包里几乎每个都有一节「KV Cache 影响」** —— 这是判断"一个改动值不值得"的第一手依据。用 `Select-String -Pattern "KV Cache 影响"` 就能定位。

### 三条硬事实

1. **DeepSeek 缓存命中约为未命中的 1/10** —— 官方公告标题就是"价格再降一个数量级" 📖
2. **只有系统文本、schema 与此前历史逐字节一致时才保持"仅追加"**；**schema 或组合变更从第一个改变的请求 token 起使复用失效** 📖
3. **`systemPromptUpdate: 'in-history'`** 让提示词变更**追加到已缓存历史之后**，从而保住到历史末尾的前缀 📖
   → 你的 `H\settings.yaml` 里给 `deepseek-flash` **已经开着**这一项

### 由此推出的设计原则

- **改动尽量追加，不要改写早期节点**（AGENTS.md 机制就是按"仅追加"设计的 📖）
- **每个会话一份不同前缀 = 跨会话缓存不再共享**（换 preset 也是这个代价 📖）
- 所以：**纯为了省 token 而做"渐进式披露/按需加载"，在 DeepSeek 上通常是负收益**，除非文档体量真的很大

---

## 7. 踩坑清单（都是我实际踩到的）

| # | 坑 | 结论 |
| --- | --- | --- |
| 1 | 以为 `~/.dsh/skills` 是全局层 | 它是每个 preset 自己扫出来的，落在那个 preset 的层 ✅ |
| 2 | 以为动态插件能给一个会话隐藏技能 | 它落**根层**，被 preset 层压过，无效 ✅ |
| 3 | 用 `guard` 且丢了 disposer | 会话内**永久无法撤销**，改用 `pre-execute` ✅ |
| 4 | 改了 preset 组成想立刻生效 | **只有新会话**加入新代际 ✅📖 |
| 5 | 想中途换 preset | 只有空会话能换 ✅📖 |
| 6 | 从 `cordis` 复制 preset | 挂载失败（inspect provider 撞车）✅ |
| 7 | `harness.defineTool` 写 `additionalProperties: false` | 报错，省略即可 ✅ |
| 8 | frontmatter 写 `modelInvocable` | **直接抛错**，要用 `disable-model-invocation` 📖 |
| 9 | 写 `when-to-use` | 静默忽略，正确的是 `whenToUse` 📖 |
| 10 | 以为读也受沙箱限制 | **读不受限** 📖 |
| 11 | 以为审批能看参数 | 审批只收到工具名+原因 📖 |
| 12 | `Tool.listTools` 当数据通道 | 输出极大；用自报告工具代替 ✅ |
| 13 | 工作区外写文件 | 需提权（或把策略设为 full-access）；`copy()` 例外，它是 host 侧 ✅ |

---

## 8. 验证方法论（这套流程被证明有效）

1. **先 Inspect，不猜**：任何服务/事件/Slot/Builtin 都先查精确契约
2. **优先自报告工具**：让插件把测量结果**返回给我**，别去 dump 大输出
3. **做双向测量**：想证明"隔离"，必须同时读「目标视图」和「非目标视图」（如 agent 视图 vs preset 视图 vs 全局视图）
4. **用挂载校验器**：写完组成先 `standingKeyFor`，它会报出确切失败原因
5. **用子会话验隔离**：子 agent 加入父方装配，是天然的"另一个会话"对照组
6. **探针用完就撤**：`cordis_undefine`；**disposer 一定保留**
7. **文档与实测冲突时以实测为准**：本次至少有 3 处文档与实际行为/推论不一致（全在本文标注）

---

## 9. 一页速查

```text
技能放哪        100 项目/.dsh/skills → 400 ~/.dsh/skills（数字越小越优先）
按窗口/会话隔离  rank 300 的 customSkillDirs，或 agent.ctx 注册（实测可行）
禁止模型自动读  frontmatter: disable-model-invocation: true（描述都不进上下文）
禁止用户点名    frontmatter: user-invocable: false
完全隐身        两者都写
只有你点名      disable-model-invocation: true（保留 user-invocable）

插件放哪        常驻 → preset 的 agent.cordis.yml / patch 层
                临时 → cordis_define + cordis_run
服务发布行      必须放进带 isolate 的 group
改组成生效      新会话（patch 层例外，是热的）
装自定义包      dsh plugin --profile web add <路径>，然后重启

限制工具        tools.restrict（工具名）/ tools/pre-execute（参数+理由，可撤销）
不要用          tools.guard（单调、不可撤）

判值不值得      README 搜「KV Cache 影响」；只有追加才不伤前缀
```
