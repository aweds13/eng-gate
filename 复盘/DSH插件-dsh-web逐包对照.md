---
title: DSH 插件 · dsh-web 逐包对照（卡 265 · T-G384）
status: superseded
supersedes: src/timeflow/core/lan.py（2026-09-23 起的局域网配对门）+ docs/subsystems/pool/README.md（现算的远端与传输面）
---

> **本文件已废弃（2026-11-02，卡 F13 / T-AG585）。**
> 保留它只为留痕：记下 2026-10-17 当时怎么判断的。**不再作为任何结论的来源**，也不要照着它去改代码。
> 现在以什么为准：`src/timeflow/core/lan.py` 与 `tools/pool/mcp_http.py`（代码本身）／`docs/subsystems/pool/README.md`（现算的子系统说明书）。
>
> 三条作废理由（都在 2026-11-02 现读过）：
> 1. 原文四条「我们没有远程访问面」不成立 —— `src/timeflow/core/lan.py` 自 `15000b30`（2026-09-23 07:07）起就有局域网配对门（`HEADER = "X-Timeflow-Pair"`、`verify()`、`gate()`、`check_pair()`），比本文件首次入库 `f9fd1b7b`（2026-10-17 11:20）**早 24 天**；2026-11-02 又多了 `tools/pool/mcp_http.py`（`b349ac6a`）这条 Streamable HTTP 传输。
> 2. 原文「636 行配对状态机」无出处 —— 上游 `packages/dsh-remote-web-ui/src/pairing.ts` 现读 766 行，加 `pair-grant.ts`（131）与 `pairing-access.ts`（36）共 933 行，整包没有任何一个 636 行的 `.ts`。
> 3. 原文 16 条本仓 `路径:行号` 引用全部指错段 —— 根因是 `scripts/check_docs.py` 的 `normalize()` 只校验文件在不在、从不校验行号；因此这份文档的行号从写下的那天起就没人验过。
>
> 本文件的作废**不牵连**别的结论：`skills/softeng-manage/references/safety.md` 里的 HS1（`~/.dsh` 是禁区）与 AI4（外部模型用完就撤）仍然成立，它们的结论出自 `复盘/INDEX.md` §5.2，本文件只是当年的证据之一。

# DSH 插件 · dsh-web 逐包对照（卡 265 · T-G384 · 树 `.wt/265`）

> 原则（用户 2026-10-16 令，最高优先）：**以我们为基底，借鉴它去改造。**
> 基底＝我们的卡 / 栅栏 / 台账 / 收口链 / 分区前缀 / 门禁 —— **不换**它的任务板、编号、市场。
> 只从它身上借**机制**，并指名落到我们哪个文件。

## 0. 这次读的是什么、怎么读的

| 项 | 实读 |
|---|---|
| 来源仓 | `D:/repo/_refs/dsh/dsh-web-dev/`（只读；未构建、未安装、未碰 `~/.dsh`） |
| 包数 | 11 个（卡规格点名的那 11 个）；每包文件清单按 `find -type f` 现算，单文件 >2000 行只读相关段 |
| 许可 | 根 `LICENSE` = **Apache-2.0**；**根目录没有 `NOTICE` 文件**（`ls` 实测）。逐包见 §2 |
| 三档 | 档 1 整包用 **0 条**（卡边界明令「不许装插件、不许改 `~/.dsh`」）；档 2 抄代码 **5 条**；档 3 只借机制 **6 条** |
| 没做 | 没跑 `dsh --profile desktop-copy --dump-config`（本机没有该 profile，建它=改 `~/.dsh`，边界不许）；详见 §4.1 |

逐包四栏的硬要求：**它怎么做**（`文件:行号`）、**我们的对应物**（我们仓里的文件，没有就写「没有」）、
**该借哪条机制**（一句话，可执行）、**不借什么**（✗ + 为什么在我们的基底上不合适）。

---

## 1. 逐包四栏

### 1.1 `dsh-task-board` — 档 2（抄代码）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **动作幂等靠「请求号 + 内容指纹」**：`sha256(JSON.stringify(action))` 当指纹，同一 `requestId` 换内容直接抛错，指纹先入缓存再 `apply()`（`packages/dsh-task-board/src/host-ledger.ts:685-694`），并被持久化、重启后回填（同文件 `:504-505`、`:1652-1658`）<br>② **写盘 = tmp + fsync + rename + 0600**，Windows 不允许对目录 fsync 时注释明说「rename 仍原子」（`:1693-1742`）<br>③ **坏台账隔离而不是继续**：改名成 `<file>.corrupt-<ts>-<pid>-<uuid>`，再把原因写进 `scheduler.error`（`:1664-1676`）<br>④ **证据不可定位 = 不算判负**：`invalid` 单独一档、单独预算 2 次，花完**挂起等人**而不是判卡失败（`src/core/verification.ts:54-64`；引文最短 12 字符 `:84-86`；校验入口 `:861-889`）<br>⑤ 执行史只留 20 条，但**未结算的永不裁**（`src/core/tasks.ts:90-106`） |
| **我们的对应物** | `tools/pool/task.py:180-184`（同目录 `tmp` + `os.replace` 原子写，**已有**）；`tools/pool/task.py:622` `cmd_claim`；`tools/pool/task.py:313-322` `read_json`（坏文件**不动它**、直接抛 —— 比它更严）；台账 `docs/workbacklog.toml` |
| **该借哪条机制** | 给 `cmd_claim` 加「申请号 + `sha256(证据\|文件\|结论)`」：同一 `(任务, 成员)` 第二次递交内容不同 ⇒ **拒**并点名差异，而不是静默覆盖 `inbox/<成员>.json` |
| **不借什么** | ✗ 不借它的 `recoverCorrupt` **「隔离后从空台账继续」**—— 我们宁可拒跑：空台账继续=把「丢了谁的申请」变成静默吞活（铁律 4）。<br>✗ 不借 20 条执行史裁剪：我们的证据要能回指到具体提交。 |
| **处置** | **档 2 抄代码**：抄的是「请求号+指纹」这段纯逻辑与「`.corrupt-<ts>-<pid>-<uuid>`」命名形状，落 `tools/pool/task.py`。许可 **Apache-2.0**（包内 `LICENSE` 在），文件头注明「算法出自 dsh-web `packages/dsh-task-board` 0.4.6，Apache-2.0」。 |

### 1.2 `dsh-task-board-github` — 档 2（抄代码）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **不可信远端文本用定界包裹，并先「中和」定界符**：把 `ISSUE 原文 开始` 之类替换成 `ISSUE 原文·开始`（中点），正文就无法提前闭合包裹、也无法伪造我们自己的声明段（`packages/dsh-task-board-github/src/core/prompt.ts:69-75`、`:84-92`）<br>② **指纹区分「我们生成的」与「人改过的」**：FNV-1a 带版本前缀（`:107-121`），`isPromptEdited` 只在指纹不符时才要求确认覆盖（`:153`）<br>③ **回写只碰自己的标签**，别人的标签过滤掉（`src/host/service.ts:314`） |
| **我们的对应物** | `tools/wb_dispatch.py:795-806`（prompt = 开场白/切片 + 卡规格 + 最小规矩集 + 工作台状态）；`tools/wb_dispatch.py:297-312`（铁律文本）；远端 issue 同步面：**没有** |
| **该借哪条机制** | 拼 prompt 之前，把卡规格 / 用户原话里出现的**我们自己的分隔标记**（如 `【工作台状态`、`=== ` 段头）换成带 `·` 的变体，保证规格正文无法伪造出一个「工作台状态」段来改工人的口径 |
| **不借什么** | ✗ 不借 GitHub issue 同步 / 标签回写 / 自动开 PR：引入远端编号=**第二套编号体系**，直接撞我们的分区前缀与卡号唯一性（`docs/partitions.toml`）。 |
| **处置** | **档 2 抄代码**：`neutralizeDelimiters` 是 12 行纯函数、零依赖，落 `tools/wb_dispatch.py` 的拼装处。许可 **Apache-2.0**（`package.json` 声明；包内无 `LICENSE` 文件，随根 `LICENSE`）⇒ 文件头注明来源与版本。 |

### 1.3 `dsh-plugin-manager` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① 动手前先用 `dsh --profile <p> --dump-config` **探测能力面**，退出码非 0 就当没有（`packages/dsh-plugin-manager/src/host/gateway.ts:580-594`）<br>② **运行时下限不满足 ⇒ 412 前置拒绝**，并点名「要求 X、当前 Y、先去升 DSH」（`src/host/routes.ts:352-360`、`:372-386`）<br>③ CLI 输出**整段缓冲后一次性解码**：zh-CN 控制台是 CP936/GBK，逐块 `toString()` 会切字（`gateway.ts:216-219`） |
| **我们的对应物** | `tools/wb_dispatch.py:2490-2540`（派活前置检查：树在不在、脏不脏、锁）;`tools/pool/landing.py:960` `fast_preflight`；CLI 网关：**没有** |
| **该借哪条机制** | 在派活前置检查里加一条**运行时下限**：Python / Node / CLI 版本不满足就**派活前**拒（退出码 2），报错照它的格式点名「要求 X、当前 Y」 |
| **不借什么** | ✗ 不借 job 表 + HTTP 轮询 + CLI 网关三件套：我们的派活与门禁是**同步进程模型**，再加一层 job 生命周期=两套状态机抢「谁算完成」。 |
| **处置** | **档 3**：整套代码绑定 Node/cordis 与 DSH profile，搬进 Python 仓是重写而非搬运。 |

### 1.4 `dsh-git-graph` — 档 2（抄代码）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① git 调用**全是 argv 构造器**，没有 shell 字符串（`packages/dsh-git-graph/src/core/git-command.ts:11-47`）<br>② 切分支前查**三类守卫**：未合并文件 `diff --name-only --diff-filter=U`（`:26`）、进行中操作标记 `OPERATION_MARKERS`（`:86`）、分支是否已被别的 worktree 检出（`src/host/git-service.ts:232` `guardBlock`）<br>③ 建树永远**新开分支 + `wt/` 前缀**，路径自己算、不接受客户端给（`git-service.ts:305-311`；`git-command.ts:47`）<br>④ 删树**双重遏制**：canonical 路径 + 必须出现在 `git worktree list`（`git-service.ts:358-364`） |
| **我们的对应物** | `tools/pool/landing.py:1406`（只看 `--diff-filter=U`）；`tools/pool/landing.py:138-168`（只自动解派生物冲突）；`tools/wb_plan.py:103`（建树 `git worktree add -b card/<id>`）；`tools/wt_prune.py:8-25`（七条判据） |
| **该借哪条机制** | 在 `landing` 合入/`rebase` 之前把三条守卫并成一个函数：未合并 + 有进行中操作（`rebase-merge`/`MERGE_HEAD`/`CHERRY_PICK_HEAD`）+ 该分支已被别的树检出，**任一命中就拒合并并点名是哪一条** |
| **不借什么** | ✗ 不借图形 UI 与客户端分支选择器：我们没有「用户点选分支」这个面。<br>✗ 不借「删树时连带 `branch -D`」：我们的 `card/<号>` 分支是这张卡唯一凭证，删分支=丢证据。 |
| **处置** | **档 2 抄代码**：argv 表 + 三条守卫是纯逻辑（`git-command.ts` 200 余行里可搬的是守卫与 argv 形状），落 `tools/pool/landing.py`。许可 **Apache-2.0**（包内 `LICENSE`）。 |

### 1.5 `dsh-usage` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① 记账**只从事件流折叠**：`request/header` 先立路由、`assistant/message` 落 token（`packages/dsh-usage/src/host/usage-service.ts:471-493`），按**本地日期**分桶（`src/core/ledger.ts:11-16`）<br>② **旧数据不追溯**：保留期按天裁掉老桶（`ledger.ts:128-139`）；花费在**折叠那一刻**按下当时价目表盖章（`src/core/pricing.ts:1-20`），峰谷/节假日口径写死在注释里<br>③ **厂商族归属显式声明**：同一家族的目录 id 与运行时别名折叠成一个族，避免两行重复计（`src/core/adapters.ts:47-68`；`familyOnlyIds` `:156-158`） |
| **我们的对应物** | `src/timeflow/core/focus/timer.py:180` `today_focus_minutes`；`src/timeflow/api/app.py`（读侧）；台账 `docs/traceability.toml` |
| **该借哪条机制** | 给每条结算记录盖「口径版本 + 价目(权重)版本」，**改公式只对新记录生效**，旧记录按盖章版本读，不重算 |
| **不借什么** | ✗ 不借余额/配额探测与峰谷计价：我们的投入单位是分钟不是 token，价目表在我们这里没有对象（硬塞进来=多一层没人维护的口径）。 |
| **处置** | **档 3**：依赖各家 provider 的 HTTP 端点与价目表，搬过来只有注释可留。 |

### 1.6 `dsh-update` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **退 0 不是成功**：更新前快照版本、更新后**回读**，一个都没动 ⇒ `stale`；回读不了 ⇒ `verify-failed`（`packages/dsh-update/src/update.ts:915-975`）<br>② **锚点路径运行后重新解析**：pnpm 会删旧版本目录，开机时抓的路径运行后读不到（`:952-956`）<br>③ `link:`/`file:` 本地开发安装**拒绝自更新**（`:205` mode 三态、`:600`） |
| **我们的对应物** | `scripts/run_gates.py:1273-1298`（每门 `exit_code` + summary）、`:1350` `gates_ok`；`tools/pool/landing.py:1324-1340`（`sealed_tree`） |
| **该借哪条机制** | 让「绿」带一次回读：`gates/last.json` 的 `ok` 由**产物回读**推出（rev + 每门 `exit_code` + 该门产物的 sha/行数），而不是只看子进程退出码 |
| **不借什么** | ✗ 不借 npm registry 探测与自动更新：我们没有自更新面，加进来等于给仓装一个会自己改自己的按钮。 |
| **处置** | **档 3**：`pnpm`/registry 语义不可移植；可移植的只有「回读再判」这个判据。 |

### 1.7 `dsh-market` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **整包下到同目录 tmp，全部成功才 `rename` 就位**，失败删 tmp，绝不留半装目录（`packages/dsh-market/src/core/installer.ts:309-345`）<br>② 每个文件算 sha256 写进 `dsh-market.provenance.json`，消费方据此区分「市场正品」与「手放目录」（`:315-333`；文件名常量 `:41`）<br>③ 路径白名单：`rel` 逐段校验（无 `..`、无绝对、无空段），URL 由**校验后的 rel 重建**而不是信客户端（`:1-31`） |
| **我们的对应物** | `tools/wt_prune.py:41-45`（删前必须留档，拷不出来就不删）；`tools/snapshot.py`（快照） |
| **该借哪条机制** | 留档也带出处清单：`wt_prune --apply` 拷 `wb-*` 时**逐文件 sha256** 写成 manifest，`wb-usage.jsonl` 追加合并后对不上 ⇒ 整棵保留 |
| **不借什么** | ✗ 不借商店/下载/资产目录：我们没有资产市场；装进来只会多出第二套「往 home 目录写东西」的入口，和「只动指名文件」直接冲突。 |
| **处置** | **档 3**：业务面完全不同；可借的是「原子就位 + 出处清单」这条写盘纪律。 |

### 1.8 `dsh-remote-web-ui` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **同一时刻只有一枚令牌**，`issue()` 覆盖旧的；`stop()` 撤销全部设备会话（`packages/dsh-remote-web-ui/src/pairing.ts:8-20`）<br>② **授权由服务端授予**：只有门控落地页在 boot 之前发了授权标记，通道钩子才装；未配对浏览器的应用壳**永远不会自称机器主人**（`src/pair-grant.ts:1-20`）<br>③ 移动适配用**语义后缀选择器**（`[class$="_composerSeat"]`）而不是 hash 类名；按 `data-dsh-plugin` 根隐藏桌面插件（`src/client/mobile-adapt.ts:288-300`） |
| **我们的对应物** | `tools/pool/task.py:622-690`（`claim` 由工人自报）；`tools/pipeline_view.py`（现状快照）；远程/移动面：**没有** |
| **该借哪条机制** | 把「谁能声明成功」从**工人自报**改成**由产物授予**：`claim --claim success` 只在 report/verdict/产物 sha 都在且能对上时记 `success`，否则记 `pending` 并点名缺哪份 |
| **不借什么** | ✗ 不借配对/二维码/Cloudflare 隧道/触控适配层：我们没有远程访问面，API 围栏与门禁锁已经把「谁在写」管住了。 |
| **处置** | **档 3**：636 行配对状态机服务的是一个我们没有的远程通道。 |

### 1.9 `dsh-session-archive` — 档 2（抄代码）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **族级全或无**：一个族（会话 + 全部后代）里**任一成员受保护 ⇒ 整族跳过**，绝不半删（`packages/dsh-session-archive/src/core/cascade.ts:33-40`）<br>② 保护集合 = 当前会话 + 运行中 + 有运行中后代（`src/host/janitor.ts:247-258`）<br>③ 删前给**确认数字**：直接选中数 / 级联数 / 最终数 / 受保护数 / 预计释放空间（`janitor.ts:417-430`）<br>④ **归档时间未知的历史会话永不自动删**（`README.zh.md`「本插件出现之前归档…显示未知，且永远不会被自动删除」） |
| **我们的对应物** | `tools/wt_prune.py:8-25`（七条判据、默认 dry-run、删前留档，**已有**）；删除单位目前是「树」 |
| **该借哪条机制** | 把「卡树 + `card/<号>` 分支 + `gates/diag` 留档」当一个**族**：三者任一失败（留档拷不出、jsonl 合并失败、分支删不掉）⇒ **整族保留**，并在表里点名是哪一环挡住的 |
| **不借什么** | ✗ 不借自动归档/自动清理策略：定时删除对我们=不可逆，而「未知时间」在我们这里恰恰是常态（老树的提交时间不可靠）。 |
| **处置** | **档 2 抄代码**：`planDelete` 的「保护 → 族 → 全或无 → 预览数字」是纯函数，落 `tools/wt_prune.py`。许可 **Apache-2.0**（`package.json` 声明；包内无 `LICENSE` 文件）。 |

### 1.10 `dsh-skill-explorer` — 档 2（抄代码）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **来源分级 rank 显式成表**：系统 < 项目 `.dsh/skills` < 项目 `.agents/skills` < 用户（`packages/dsh-skill-explorer/src/collect.ts:59-95`）；重名按 rank 解析（`:64-78`）<br>② 文件**三态** `editable / provider-file / virtual`，不可写的**显式打标「由插件提供」**，而不是悄悄少一个按钮（`:97-144`）<br>③ 删除 = 移进同目录 `.trash`，可恢复（`:597-604`）<br>④ 写入前比 revision，别人改过就 409「刷新重试」（`src/routes.ts:184`） |
| **我们的对应物** | `tools/dsh_skills_link.py:1-50`（只挂含 `SKILL.md` 的子目录；指向不对就停，**已有**）；`skills/`（真源） |
| **该借哪条机制** | 链接器加来源分级：同名技能同时出现在 `skills/` 与 `.dsh/skills` 时按 rank 取一，并在 `--check` 输出里**点名被遮住的那个** |
| **不借什么** | ✗ 不借 GUI 新建/编辑面板：我们的真源是 git 里的 `skills/`，面板写盘=第二个写入口，和「一写一读」冲突。 |
| **处置** | **档 2 抄代码**：rank 表 + 三态枚举是数据形状，落 `tools/dsh_skills_link.py`。许可 **BSD-3-Clause**（包内 `LICENSE`）⇒ 保留版权声明，文件头注明出处。 |

### 1.11 `dsh-model-capabilities` — 档 3（只借机制）

| 栏 | 内容 |
|---|---|
| **它怎么做** | ① **保存带 revision 栅栏**：快照读到的 revision 当写栅栏，别人改过 ⇒ 重读并标 stale，**绝不盲写**（`packages/dsh-model-capabilities/src/client/CapabilitiesPanel.tsx:65-66`、`:209-216`）<br>② **写前按适配器规则校验**，直接说清为什么会被拒，而不是让宿事事后再拒（`src/core/capabilities.ts:130-155`）<br>③ 禁用=先存档再下线，排序保证**最坏是重复存档，绝不是丢档**（`src/core/provider-toggle.ts:1-15`） |
| **我们的对应物** | `docs/workbacklog.toml`（只许末尾追加，铁律 35）；`tools/wb_plan.py` 分片合并（卡 262 分区）；`tools/wb_invariants.py`（79 条不变量） |
| **该借哪条机制** | 分片合并带 revision：`wb_plan.py merge` 读各分片时记 sha，写回前再算一次，不一致就**拒合并并点名哪个分片被谁改过** |
| **不借什么** | ✗ 不借设置页写回/提供方启停：我们的配置是 TOML + 门禁，GUI 写回会让「谁改了台账」失去 git 证据。 |
| **处置** | **档 3**：整套挂在 DSH 设置命名空间与 path-op 上，我们没有那层。 |

---

## 2. 许可与出处（抄代码前先读，卡规格 §「处置」第 2 档前提）

| 包 | `package.json` license | 包内 `LICENSE` | 允许抄代码 |
|---|---|---|---|
| `dsh-task-board` | Apache-2.0 | 有 | ✓ 保留版权与许可声明 |
| `dsh-task-board-github` | Apache-2.0 | **无**（随根 `LICENSE`） | ✓ 同上 |
| `dsh-plugin-manager` | **BSD-3-Clause** | 有 | ✓（本卡不抄） |
| `dsh-git-graph` | Apache-2.0 | 有 | ✓ |
| `dsh-usage` | Apache-2.0 | **无** | ✓（本卡不抄） |
| `dsh-update` | Apache-2.0 | **无** | ✓（本卡不抄） |
| `dsh-market` | **BSD-3-Clause** | **无** | ✓（本卡不抄） |
| `dsh-remote-web-ui` | Apache-2.0 | 有 | ✓（本卡不抄） |
| `dsh-session-archive` | Apache-2.0 | **无** | ✓ |
| `dsh-skill-explorer` | **BSD-3-Clause** | 有 | ✓ 保留 BSD 版权段 |
| `dsh-model-capabilities` | Apache-2.0 | **无** | ✓（本卡不抄） |

- 根目录 **无 `NOTICE` 文件**（`ls` 实测）⇒ Apache-2.0 的 NOTICE 转发义务本仓无对象；
  但**版权行必须留**：抄进我们文件的每一段，文件头写「算法出自 `dsh-web` `packages/<包>` 0.4.6，Apache-2.0 / BSD-3-Clause」。
- 版本来源：11 个包的 `package.json` 全部是 `0.4.6`（逐个 `json.load` 读出来的）。

## 3. 处置汇总（三档，逐包给理由）

| # | 包 | 档 | 一句话理由 |
|---|---|---|---|
| 1 | `dsh-task-board` | **2 抄代码** | 「请求号+指纹」与隔离命名是纯逻辑，搬得动；整包装会换掉我们的任务板 |
| 2 | `dsh-task-board-github` | **2 抄代码** | 12 行定界符中和，直接补我们拼 prompt 的洞 |
| 3 | `dsh-plugin-manager` | **3 借机制** | Node/cordis + profile 网关，搬=重写；只借「运行时下限前置拒绝」 |
| 4 | `dsh-git-graph` | **2 抄代码** | argv 表 + 三条守卫可原样落成 Python 函数 |
| 5 | `dsh-usage` | **3 借机制** | 价目/端点不可移植；只借「口径版本盖章、旧账不追溯」 |
| 6 | `dsh-update` | **3 借机制** | registry/pnpm 语义不可移植；只借「退 0 后回读再判」 |
| 7 | `dsh-market` | **3 借机制** | 无资产市场；只借「原子就位 + 逐文件 sha256 出处清单」 |
| 8 | `dsh-remote-web-ui` | **3 借机制** | 无远程面；只借「成功由产物授予，不由自称」 |
| 9 | `dsh-session-archive` | **2 抄代码** | 族级全或无的删除计划是纯函数，正好补我们清树 |
| 10 | `dsh-skill-explorer` | **2 抄代码** | 来源 rank 表 + 三态打标是数据形状，补我们链接器 |
| 11 | `dsh-model-capabilities` | **3 借机制** | 挂在设置命名空间；只借「revision 栅栏 + 写前校验」 |

**为什么没有一条「整包用」**：① 卡边界明写「不许装插件、不许改 `~/.dsh`、不许跑 dsh-web 的构建」；
② 它们全部是 **DSH Web GUI 的插件行**，装进我们的基底=在我们的卡/栅栏/台账旁边再放一套任务板与编号，
正面冲撞「以我们为基底」那条最高优先原则。⇒ 档 1 的前置条件（`desktop-copy` profile）留给后续卡，
本轮不建、不装。

## 4. 「装了不打架」的硬判据（逐条给证据）

### 4.1 副本 profile 验合成 —— 本轮不适用，且实测不可做

- 本轮 **0 条整包用**；5 条「抄代码」抄的是**纯函数/表**，不挂插件行、不加依赖、不碰 profile ⇒ 没有「合成」这件事。
- 实测：`~/.dsh/profiles` 只有 `desktop` / `headless` / `web`，**没有 `desktop-copy`**；
  `dsh --version` = `0.2.0-rc.2`（经 `cmd` 调用）。建 `desktop-copy` = 改 `~/.dsh` ⇒ 卡边界禁止。
- 留作后续卡的前置命令（本轮**未执行**）：
  `dsh --profile desktop-copy --dump-config` —— 退出码 0、0 错误、且合成里我们自己的座位（如 `workbench-panel`）仍在。

### 4.2 同一件事只能有一个实现

| 借来的机制 | 我们已有的实现 | 落法 |
|---|---|---|
| 请求号+指纹（task-board） | `cmd_claim` 直接覆盖 `inbox/<成员>.json` | **替换**该写入路径，不新增第二个 claim 入口 |
| 定界符中和（github） | 无 | **新增**在 `wb_dispatch` 唯一的拼 prompt 处 |
| 三条 git 守卫（git-graph） | `landing.py:1406` 只看 `--diff-filter=U` | **扩**这个函数，不另写一套 preflight |
| 族级全或无（session-archive） | `wt_prune.py` 七条判据 + 留档 | **扩** `--apply` 的删除步骤，不新增清理器 |
| 来源 rank（skill-explorer） | `dsh_skills_link.py` 只挂 `SKILL.md` 子目录 | **扩** `--check`，不新增第二个链接器 |

### 4.3 它的标识不许渗进我们的台账

- 全部落点用**我们自己的**卡号/任务号/树名（`card/<号>`、`T-G…`、`.wt/<号>`）。
- 它的 `wt/` 分支前缀、npm 包名（`@linxin666/*`）、issue 号、DSH 设置命名空间 —— **一律不进口**。

### 4.4 同一 UI 槽位只有一个主人

- 本轮 **0 条**动 UI（`src/web/**` 一个字节不改）。11 个包里只有 `dsh-remote-web-ui` 涉及 UI，处置是档 3 且只借授权判据。

### 4.5 只动指名文件

- 本卡产物 = 本文件一份（`复盘/DSH插件-dsh-web逐包对照.md`）。证据见 §5。

### 4.6 抄来的代码必须注明出处与许可

- 落点文件头统一写：`算法出自 dsh-web packages/<包> 0.4.6（Apache-2.0 / BSD-3-Clause），见 复盘/DSH插件-dsh-web逐包对照.md §2`。
- BSD-3-Clause 的两条（`dsh-skill-explorer`）额外保留「版权人 + 三条款」原文段落。

## 5. 判据自检（本卡）

| 判据 | 读数 |
|---|---|
| 11 个包都有四栏 | 11/11（§1.1–§1.11，每节 4 行 + 处置行） |
| 每条结论带 `文件:行号` | 每节「它怎么做」全部带；只有「我们的对应物」里的「没有」不带（该栏允许写「没有」） |
| 空话检查 | 按判据三类空话（「值得×」「可以参×」「很有×」）逐节扫：正文 **0 处**；原样命令与读数见报告 `gates/diag/wb-265.report.md` |
| 末尾 ≤5 条可落地改造 + 指名文件 + 怎么验 | 5 条（§7） |
| `git status --short` 只有这一份新增 | 见 §5 的实测输出 |
| 三档逐包选一 + 理由 | 11/11（§3） |
| 许可类型与出处 | §2（11 行 + 根 `LICENSE`/`NOTICE` 实测） |

## 6. 边界（没做到的部分，如实写）

1. **没装任何包**（卡边界）；因此 `dsh --profile desktop-copy --dump-config` **没跑**，§4.1 只给了后续卡的验证命令。
2. **没有 `desktop-copy` profile**（实测 `~/.dsh/profiles` 只有 desktop/headless/web）—— 要验合成得先建它，那是改 `~/.dsh`，本轮禁区。
3. **没改 `tools/`、`tests/`、`scripts/`**：§7 五条改造是**提案**，各自要单独一张卡（带测试白名单）。
4. `dsh-market`、`dsh-remote-web-ui`、`dsh-plugin-manager` 只读了主路径 + README + 相关段（单文件 >2000 行只读相关段，按卡规格允许），未逐行通读 `client/` 下的 React 组件。
5. 许可结论来自包内 `LICENSE` 与 `package.json` 的 `license` 字段；**没有**做 npm registry 上的许可复核（离线、且卡不许联网装包）。

## 7. ≤5 条可落地改造（每条：落哪个文件 + 怎么验）

| # | 落点 | 改什么 | 怎么验（先红后绿） |
|---|---|---|---|
| 1 | `tools/pool/task.py` | `cmd_claim` 加「申请号 + `sha256(证据\|文件\|结论)`」；同 `(任务, 成员)` 内容变了就拒并点名差异 | 新增反例：同一成员连交两次、第二次只改 `--evidence` ⇒ 期望退 2 且 stderr 含「内容变了」；改前该用例失败（当前是静默覆盖）。命令：`python -X utf8 -m pytest tests/test_pool_task.py -q` |
| 2 | `tools/wb_dispatch.py`（`:795-806` 拼装处） | 拼 prompt 前中和我们自己的分隔标记（`【工作台状态`、`=== ` 段头）为带 `·` 的变体 | 造一份含 `【工作台状态】` 的假卡规格，生成 prompt 后 `grep -c '【工作台状态】'` 期望 0，且 `grep -c '【工作台状态·'` ≥1、正文其余字句逐字仍在 |
| 3 | `tools/pool/landing.py`（`:1406` 扩成守卫函数） | 合入前查三条：未合并文件 / 进行中操作标记 / 该分支已被别的树检出；任一命中拒合并并点名 | 临时仓三条各造一次（`git merge` 冲突、`rebase` 中断、`worktree add` 同分支）⇒ 三条都要退 2 且报错里出现对应那一句；改前只对第一条有效 |
| 4 | `tools/wt_prune.py`（`--apply` 删除步骤） | 「树 + 分支 + 留档」当一族：任一环失败整族保留；留档写逐文件 sha256 manifest | 造「留档合并失败」（目标 jsonl 只读 / 内容坏）⇒ 树仍在、退非 0、manifest 未落；正常路径 ⇒ 树删、manifest 里的 sha256 与源文件逐个相等 |
| 5 | `scripts/run_gates.py`（`:1350` `gates_ok`） | `ok` 由产物回读推出：每门 `exit_code==0` **且**该门产物存在、sha/行数与 `gates/last.json` 记的一致 | 手改一份 `last.json`（一门写 `exit_code:0` 但产物 sha 不符）⇒ `gates_ok` 期望 False；现有实现返回 True（这就是先红） |

★ 五条都**不在本卡实施**（卡边界：不改 `tools/` 与 `tests/`，只新增这一份文档）。它们各自需要一张带 `tests/` 白名单的卡。
