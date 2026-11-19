# pool 子系统（分区 G 的执行侧）—— 项目书

> 立项：2026 年 10 月 25 日（卡 F5 · `T-AG480`）。依赖：F3 的 `scripts/check_docs.py` 已落。
> 一句话：**pool 不是"跑门禁的那堆工具"，是仓库里唯一一处"派活与收口"的执行侧** ——
> 它决定「哪张卡、谁在改、改完怎么收成一笔提交」，但**不判门过不过、不写判据、不下审计结论**。
> 与 `docs/subsystems/ci/README.md` 同构：本篇只回答「是什么 / 多大 / 定了什么 / 边界在哪」，
> 判据本体一律留在 `tools/` `tests/` `gates/`，**这里不抄**。

## 1. 它现在是什么（代码边际）

<!-- pool-margin:begin -->
`tools/pool/` = 48 个 py（47 个模块 + `__init__.py`）、**21846 行**（`wc -l tools/pool/*.py`，2026-11-20 现算）。

每个模块都可 import（判据在库里），每个 CLI 都是**薄壳**（只解析参数 + 打印）。

| 模块（`tools/pool/`） | 行 | 职责 | 命令壳 |
|---|---|---|---|
| `__init__.py` | 27 | 包说明与模块地图；只解释分工，不放判据 | 无 |
| `account_id.py` | 160 | 人给的名字 ↔ 账本稳定 id 的唯一映射（纯函数：吃 rows，不读文件不读环境） | 无（被 `wb_dispatch` 调） |
| `accounts_import.py` | 549 | 账号导入：认别的工具导出的凭据文件（CliProxyAPI / Codex auth.json / Claude .credentials.json / Sub2API accounts[] / codexbar / 裸 refresh token 行文），归一成账本行再生成计划 —— 源文件只读、不联网不探测、认不出的条目逐条点名（仍进表）、默认只算不写，写只走 save_ledger 的注释闸与原子写 | python -X utf8 tools/pool_accounts.py import --agent codex/claude/antigravity --platform <能力表里的平台> [--yes] <文件>... |
| `accounts_scope.py` | 283 | 调用方名册 → 可见号的收窄：只删候选、从不加（空名单 = 不收窄） | 无（被 `pool.guards`、`pool_mcp` 调） |
| `callers.py` | 215 | 调用方名册的只读解析：谁能花哪个号的哪些模型；撤人改成 `off = true`，不删行 | 无（被 `wb_dispatch` 调） |
| `checkin.py` | 1055 | 五个平台的签到**写动作唯一住所**：六态结论码 + 幂等 + 华为云 `SDK-HMAC-SHA256` 签名（`apply=False` 只探不领）；读侧只加一个纯函数 `codearts_package_used()` —— 只认 `usageTotalPackageCredit` 那一条算已用百分比与余额，绝不把 basic/ondemand/bonus 相加 | 无（被 `pool_accounts.py` 调：`checkin` 走签到写动作、`probe` 的 codearts 分支走额度读数） |
| `cleared.py` | 286 | 清空用量的标记（`gates/diag/usage-cleared.json`）：清空**永不写进账**，只换读法；判不出就显出全部 | `pool.cleared main`（子命令 list / add） |
| `dispatch_shim.py` | 141 | 面板点「派活」的那一层中间壳：按卡号查规格（绝不让客户端传路径）、写死 argv 真跑一次派活器、往 `gates/diag/pool-actions.log` 追加一行痕；本壳不复制任何判据（卡号 / 域 / 树 / 干跑全在真派活器那边） | `python -X utf8 tools/pool/dispatch_shim.py --card <卡号> [--tree .wt/<卡>] [--dry-run]` |
| `failclosed.py` | 66 | 判不出来时拒还是放：`NotServing`（遮蔽器不在就不发）与 `NotLimited`（限额拿不到就不发）两条语义 | 无 |
| `gateway.py` | 1300 | 号池网关（同协议直通）：`classify` 七值失败分类（只看状态码与结构化字段，不解析文案）、`route_once` 干跑式选号/沉底/RPM/收窄/换号与 `wb-route.jsonl` 留痕、四条回环 HTTP 面（Bearer + Origin 白名单 + 32 MiB 上限）——不翻译协议、不攒流；不知道额度的座由 `route.tier(None)=UNKNOWN_TIER` 排到最后（不是抛错退原序） | `python -X utf8 tools/pool/gateway.py [--host 127.0.0.1] [--port 8766] [--routing order]`（要 `TF_POOL_GATEWAY_TOKEN`；`--routing` 是**唯一**选号入口：默认 `order`，空串 = `smart`（magpie 默认值），别名见 `pool.route.ROUTING_ALIASES`；名字认不出 ⇒ 退 2、一个端口都不绑） |
| `guards.py` | 480 | 树 / 冲突域 / 门禁锁 / 日志 / 项目五条守卫，**纯函数**（吃已读好的数据回 `list[str]`，不写文件不 print） | 无（被 `wb_dispatch`、`wb_registry` 调） |
| `holds.py` | 399 | 整窗用量的下限 + 五因估算（magpie `window_holds` 移植）：`bounds` / `holds_bounds` / `estimate` | 无 |
| `jobs.py` | 581 | 作业日志状态分桶（在跑 / 已判决 / 断了 + 历史尝试 / 已被取代 / 台账已完结 / 非派活，卡 E116；台账读不到 ⇒ 判不了，卡 E132 —— 这一源不可判、不是结束） + 归属卡解析 `card_of_log` + 在飞三源 `in_flight` + 产物定位；只读、无副作用 | `wb_status.py`、`pool_mcp` 的 `job_list` / `job_status` |
| `landing.py` | 3412 | 落地链八步（⓪ 回退 → ⑧ 复核落盘）：迁树 / 文书 / 门禁 / 封存 / 提交 / 合流，一笔提交的编排全在这里 | `wb_land.py` |
| `lanes.py` | 154 | 读 `lanes.toml`：一个号同时最多几张卡（数据面；判据在 `guards.lane_guard`） | 无（被 `pool.registry` 调） |
| `lanes.toml` | 45 | 每账号并发闸的数据：稳定 id → 同时最多几张卡（随仓走、由人改，改完不用重启） | 无（被 `pool.lanes` 读） |
| `lastgood.py` | 421 | 写盘纪律：原子替换 + `.bak` 落后一次 + fail-closed 读；`read_strict` 从不读 `.bak`（撤过的凭据不许复活） | 无（被 `pool.registry`、`pool.task`、`pool.queue`、`pool_accounts`、`gate_pool` 调） |
| `lease.py` | 109 | 码道派活那条路并进**同一本**租约账的命令行（不并账，守卫就瞎一半） | 本文件即入口 |
| `ledger.py` | 634 | 台账唯一的写入口：一把不看端口段的 gates/diag/ledger.lock 把「读字节 → 切块 → 查重 → 尾部追加 → 原子写（os.replace 带重试）→ 提交」包成短事务；只许尾部追加，已有块的字节一个不碰；提交那一笔顺手叫 gen_pool_readme.py 重算队列卡数（没生成器/README 本来就脏/生成器失败 ⇒ 只提交台账并点名） | 无（被 wb_card.py 与 pool.landing 的翻账路径调） |
| `ledger_spend.py` | 281 | 按账号累计花费的账（`pool-spend.jsonl`，一行一次派活）；**不内置价目表**，`cost` 由调用方给；没有价的行由写侧标 `priced=False`，`unpriced()` 数它们（提问，不是估算） | 无（被 `pool.limits_check` / `limits_policy` 调） |
| `limits.example.toml` | 50 | 限额文件的仓内模板（全注释 + 一条注释掉的样例）：读者照着它写本机那份；生产读的是仓外 infra/pool/limits.toml，不是它，本文件里不许出现会真拦人的限额 | 无（示例文件；不被生产读取） |
| `limits.py` | 132 | 限额策略的读法与「表读不出 = 拒」那条 `NotLimited`（magpie `ErrUnlimited` 移植） | 无（被 `wb_dispatch` 调） |
| `limits_check.py` | 174 | 派活**之前**的预算授权：这个号这个窗口还有余量吗 + `Retry-After`（`budget.Reserve` 移植）；按钱那一条遇到**没有价**的行就说「判不了」并拒，不许拿 cost=0.0 当还有余量 | 无 |
| `limits_policy.py` | 345 | 限额策略的窗口与 `Limit` 形状（magpie `access/limit.go` 移植）；与 `--input-budget` 熔断的语义差写在文件头 | 无 |
| `locks.py` | 76 | 门禁锁的只读封装：`status_argv` / `parse_entries`（拿/放/续租仍归 `gates/diag/gate_lock.py`） | 无（被 `pool_mcp` 调） |
| `mcp_http.py` | 406 | MCP 的 Streamable HTTP 传输：Origin / Bearer / 版本头 / 上限 / 202-405 都在这一层；判据只在传进来的 handle 上跑，不重写方法分发 | 无（被 tools/pool_mcp.py 调） |
| `model-registry.toml` | 63 | 跨池统一层：CodeBuddy 池的真源 + 码道池的引用（只引用不复制，不许有第二份可写名单） | 无（被 `pool.model_registry` 读） |
| `model_registry.py` | 1017 | 一层模型注册表、按池分流：`resolve_model` / `effective_allowed_for`（裸名 vs `provider/model` 两套 id 体系）+ 禁用表 `assert_not_disabled`（与注册表同目录的 `model-disabled.toml`；读不到≠没禁用） | 无（被 `wb_dispatch`、`wb_watch`、`pool.plan` 调；禁用判据被 `wb_dispatch` 派活主闸、`gateway._model_block`、`pool_mcp` 干跑面三处调） |
| `models.py` | 398 | 号池模型的只读读取：号池批准集 ∩ 号池快照（★ 不是派活允许集）；另给批准集逐条按池的派活真判决（可派 / 未接 / 跨池串用 / 未授权 + 今天的可派别名），判序照抄派活主闸、现算不写死；读快照（带 `at`），不联网、不写快照；过期时由 `probe_command` / `probe_hint` 现算出「怎么让它变新」的那条命令（脚本不在就明说没有，不给假命令），读面三处都调它不各自拼句 | `wb_state.py`、`pool_mcp` |
| `no_window.py` | 29 | 起子进程「不弹窗」的 `CREATE_NO_WINDOW` 常量 —— 全仓唯一真源 | 无（被十几个入口 import） |
| `outcomes.py` | 175 | 按**请求**而不是按轮算结局（magpie `Totals.count()` 移植）：`is_failed` / `is_outcome` / `request_of` / `count_requests`；只读账本，不改一个字节 | 无（被 `wb_dispatch` 的 `append_usage_line` / `usage_summary` 调） |
| `plan.py` | 680 | 队列解析 + 文件级冲突域 + 拓扑分层 + 同层贪心排批（`wb_plan.py` 的逻辑层，拒绝会冲突的组合） | `wb_plan.py`、`wb_batch.py` |
| `platforms.toml` | 260 | 平台能力表：九个平台的端点 / 凭据形态 / 结论码 / 出处；**零凭据**，未验证的标 `verified = false`；`probe` 三个取值 http / manual / codearts-credits（后一个是签名读一次 statistics/plugin 的真读） | 无（被 `pool_accounts.py` 读） |
| `pricing.py` | 231 | 定价算术（十进制位移 / 严格大于分档 / 整单按档 / 1 小时缓存写 2×）；**零价目表**，`Price` 一律由调用方构造；`unpriced_calls()` 与账本的 `unpriced()` 仍是两份读数，互不调用 | 无（纯函数；今天零生产调用方） |
| `projects.py` | 223 | 项目索引（`infra/pool/projects.toml`）只读 + 三条硬判据：root 存在 / 两项目不撞 root / 树在白名单内 | `wb_project.py` |
| `queue.py` | 412 | 落地合并队列：单写者段排队 + 投机预检（`gates/diag/merge-queue.json`）；投机结果**不许复用** | 无（被 `pool.landing` 调） |
| `quota_history.py` | 370 | 额度历史曲线：留点 / 回血检测（`new_cycle`）/ 去抖 / 剪枝（magpie `quota_history.go` 移植） | 无（被 `pool_accounts.py` 调） |
| `quota_line.py` | 226 | 一行说完「现在能不能派」：问不到就打空行、星号只给最新且紧贴名字、至少 1 小时不带秒；纯函数零 IO | 被 `pool_quota.py line` 调 |
| `registry.py` | 380 | 租约账：`reserve` / `release` / `list_reservations` / `is_dead`，落在**主树** `gates/diag/pool-registry.json` | `wb_registry.py`、`wb_dispatch` |
| `review.py` | 92 | 白名单越界 / 实际改动 vs 权威域（`outside_allow` / `changed_paths` / `outside_domain`）—— 全仓唯一实现 | 无（被 `wb_dispatch`、`wb_impact`、`wb_batch` 调） |
| `route.py` | 869 | Smart 路由：给「哪个号先上」排序（`tier` / `smart_order` / `apply_order`）+ `parse_routing` 名称归一（大小写/空白/别名，空串 = `smart`，认不出抛 `RouteError`），只标准库 + 只读 | 无 CLI（被 `pool.gateway` 调 `apply_strategy` 选号、`parse_routing` 归一 `--routing`；被 `pool.plan` 调 `reset_for`/`seconds_left`、被 `pool.sticky` 取 `USED_SHARE`） |
| `route_log.py` | 205 | 路由回放的**唯一写入处**：一行一轮记「谁被试过、谁真答了」，值只来自调用方传进来的事实（不读 usage 账重算）；`status` 四值闭集 | 无（被 `pool.trae_dispatch.finish` 调；`route_path` / `read_routes` 供读面） |
| `rpm.py` | 290 | 每号每分钟派活**趟数**闸（`decide`）；防不了 vendor 侧 RPM 429（那个归 `pool_quota.py` 的四态） | 无（被 `wb_dispatch` 调） |
| `rpm.toml` | 22 | 每分钟派活闸的数据：稳定 id → 每分最多几趟（0 = 关闸，越界报 `RpmError` 不静默当 0） | 无（被 `pool.rpm` 读） |
| `sink.py` | 238 | 429 且「还有配额」的候选沉底到次序末尾（`sink` / `unsink` / `unsink_all` / `sunk_at`，进程内状态） | 无 |
| `snapshot.py` | 104 | 零风险快照：`git stash create` 造 commit 再挂 `refs/snapshots/*`（完全不动工作区；不挂 ref 会被 gc） | 无（被 `pool.landing` 调） |
| `speed.py` | 261 | 输出速度的判据（**不是怎么算速度，是什么情况不许报**）：窗口不可测 / 末端爆发 / 推理比答案快 `THINK_PACE` 倍 / Codex 太短，一律回 `(0, 0)` | 无（今天**零调用**：pool 不产 `ttft` / `first_text` / `flow`，接线只能接假数） |
| `stage_card.py` | 450 | 三段文书片段生成器：台账条目 + changelog + 交接 CHECKPOINT（只写片段，汇总归 `sync_docs`）；test: 证据指针写盘前先归一形态（剥 tests/ 前缀）并按 audit 同一口径核文件与用例在不在（不在 ⇒ 退 4 点名） | `wb_stage_card.py` |
| `sticky.py` | 306 | 卡粘性：同一张卡第二次派活别换号（`STICK_KEEP_S` / `note` / `pick`），省重发上下文的 token | 无（被 `wb_dispatch` 调） |
| `task.py` | 1611 | 任务栅栏：批预声明 → 每张卡交成送申请 → 集齐才收口；含自旋锁与逐卡域检查 | `wb_task.py`、`auto_land.py` |
| `trae_dispatch.py` | 380 | 面板道（CDP 驱动 Trae）进账：一次跑落成租约 + 日志 + 判决；**刻意不接进派活** | 本文件即入口；`wb_watch.py` |
| `usage_ingest.py` | 658 | 外部用量上报：整批校验 + `rid` 幂等 + 上报行不计入限额（不经过派活器的调用也要进账） | 无 |
| `warmup.py` | 555 | 窗口登记：`window_of_row` / `register` / `window_running` / `due` —— 判「该不该 warm」（magpie `F28` 的**判据**，不移植节拍）；登记表 `gates/diag/warm-window.json`（派生、可重建），**零请求、零定时器** | `python -X utf8 tools/pool/warmup.py`（子命令 due / warm / register / status） |

两张**账**分开住，这是理解本子系统的关键：

| 账 | 文件 | 记什么 | 真源模块 |
|---|---|---|---|
| 租约账 | 主树的 `gates/diag/pool-registry.json` | 谁占了哪棵树、哪个冲突域 | `tools/pool/registry.py` |
| 任务账 | 主树的 `gates/diag/batch/<任务>.toml` + `<任务>.json` | 这个任务要哪些卡、谁交了申请 | `tools/pool/task.py` |
| 账号账 | **仓外** `infra/pool/accounts.toml`（`TF_ACCOUNTS_TOML` 可覆盖） | 我有哪些号、每号批了哪些模型、额度最后观测是什么时候 | `tools/pool_accounts.py` |

> 前两张都锚在**主工作树**（`git rev-parse --git-common-dir` 的父目录），不在卡树 ——
> 卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写（`tools/pool/registry.py:72`、`tools/pool/task.py:119`）。
> 账号账**故意在仓外**：只存凭据指针（`~/.codeartsdoer/pool.env` 之类），不存凭据本身；
> 没有 git 兜底，所以写入一律原子替换，删号打墓碑（`tools/pool_accounts.py` 的 `save_ledger()`）。

## 2. 度量（2026-11-20 现算）

| 指标 | 读数 | 怎么取 |
|---|---|---|
| 实现体量 | **21846 行** / **48 个文件**（47 个模块 + `__init__.py`） | `wc -l tools/pool/*.py`（与 §1 同源，一次现算） |
| 队列卡数 | 408 张（386 done / 22 pending） | 读 `docs/workbacklog.toml` 的 `cards`，按 `status` 分 |
| 批预声明 | 152 份 | 主工作树 `gates/diag/batch/*.toml` 的份数（卡树里读成 0） |
| 派活日志 | 242 份（不含 `wb-usage.jsonl`） | 主工作树 `gates/diag/wb-*.jsonl` 减 `wb-usage.jsonl` |
| 单次派活墙钟 | 不写死：见右列 | 每份日志首个/末个 `__timestamp` 之差；只统计**有 ≥2 个** `__timestamp` 的日志 |
| 最近一份跑完的 | 不写死：见右列 | 同上；取 `gates/diag/wb-*.jsonl` 里 mtime 最新、且 ≥2 个 `__timestamp` 的那份 |
<!-- pool-margin:end -->
口径两条（别读错）：① 只统计**有 ≥2 个 `__timestamp`** 的日志，`wb-usage.jsonl`（用量账）不计；
② 耗时是**工人进程的墙钟**，不含主控自己的落地链（那条 11–15 min 记在 CI 子系统的度量里）。

## 3. 决策（D1–D7，指回卡号）

- **D1 守卫写成纯函数、只有一份**（卡 106 · `T-G202`）：吃数据回问题、不写文件不起进程 ——
  所以写面（派活）能直接复用，不会变成第二份真源。见 `tools/pool/guards.py:1`。
- **D2 租约账全窗口一本**（卡 108 · `T-G205`）；码道那条派活路也接进**同一本**（卡 195 · `T-G295`）——
  「两本账 = 守卫照旧瞎」，见 `tools/pool/lease.py:1`。
- **D3 攒批按「任务种类」不按数量**（用户 2026-10-02 裁定，卡 119 · `T-G217` 进 git）：
  判据是「名单上每一张卡都交了成功申请」，**不是**攒够 N 条。见 `tools/pool/task.py:1`。
- **D4 一层注册表、按池分流**（卡 166 · `T-G266`）：两个池的 id 体系不同（裸名 vs `provider/model`），
  所以"挑一份当真源"本身是错的。见 `tools/pool/model_registry.py:1`。
- **D5 落地链八步、封存排在暂存之后**（卡 228 · `T-G344`）：翻账是对跟踪文件的最后一笔改动，
  封存必须等它定型，否则「封存树 ≠ 提交树」必然红。见 `tools/pool/landing.py:31`。
- **D6 动别人工作区之前先打快照**（卡 192 · `T-G292`）：`stash create` + 挂 `refs/snapshots/*`
  （不挂 ref 的快照会被 gc 清掉，"救回来"只是运气）。见 `tools/pool/snapshot.py:1`。
- **D7 面板道进账、但不接进派活**（卡 218 · `T-G331`）：面板会重载 ⇒ 驱动 await 不 settle；
  它只把一次跑落成租约 + 日志 + 判决三样，**不 import `wb_dispatch`**。见 `tools/pool/trae_dispatch.py:1`。

## 4. 卡表（本子系统的账，不是全部历史）

| 卡 | 台账号 | 落了什么 |
|---|---|---|
| 106 | `T-G202` | 纯函数层抽出：guards / locks / jobs / models / plan / review / snapshot |
| 108 | `T-G205` | 租约账 + 门禁锁解析（`is_dead` / `list_reservations` / `parse_entries`） |
| 119 | `T-G217` | `task.py` 进 git（栅栏本体成为可 import 的权威副本） |
| 120 | `T-G232` | 项目索引 + 项目守卫（`project_guard`） |
| 128 | — | 域检查 + `gate_cmd` 白名单化 + 受保护共享文件 |
| 131 | `T-G228` | 实际改动 vs 权威域（`changed_paths` / `outside_domain`） |
| 138 | `T-G236` | 模型开关文件（只做加法，不进轮换链） |
| 139 | `T-G237` | `landing.py` / `stage_card.py` 进 git |
| 143 | — | 审计型只读成员（`read_only = true`） |
| 149 | `T-G249` | 多号：按 profile 现取环境变量注入 |
| 166 | `T-G266` | 一层注册表 + 按池适配器 + 最小规矩集 |
| 184 | `T-G284` | 增量门禁（三条强制全量）+ 复核落盘异步 |
| 192 | `T-G292` | 主干保护 + 落地前快照 |
| 195 | `T-G295` | 租约 CLI（码道并账） |
| 204 / 212 / 228 | `T-G311` / `T-G323` / `T-G344` | 落地即翻 status / 攒批收口 / 封存次序 |
| 218 | `T-G331` | 面板道进账 |
| F5 | `T-AG480` | 本篇（五篇说明书 + 旧三篇加注） |

专题页：[`派活口径.md`](派活口径.md)（四张入口的契约）· [`模型与号池.md`](模型与号池.md)（三集关系与 429）·
[`租约与锁.md`](租约与锁.md)（四把锁与死主）· [`事后判据清单.md`](事后判据清单.md)（现象 → 产物 → 判据）。

## 5. 边界

pool 只做**派活与收口**。下面三张表是全卡的主判据：写偏了（把门禁判据抄进来、把 pool 描述成"跑门禁的工具"）
就是没写成。

### 表 A · 唯一实现归属（谁是真源、谁是薄壳）

真源一律在 `tools/pool/**`；右列是**实测的 import 行**（`grep -n` 可复现）。

| 模块 | 薄壳入口 | 证据（薄壳里的 import 行） |
|---|---|---|
| `tools/pool/guards.py` | `tools/wb_dispatch.py` | `wb_dispatch.py:120` —— `from pool import guards as pool_guards  # 守卫唯一实现` |
| `tools/pool/registry.py` | `tools/wb_dispatch.py`、`tools/wb_registry.py` | `wb_dispatch.py:121`（`作业登记唯一实现`）、`wb_registry.py:28` |
| `tools/pool/task.py` | `tools/wb_task.py`、`tools/auto_land.py`、`tools/wb_advcard.py` | `auto_land.py:79` —— `# 批目录 / 收件箱 / 自旋锁唯一实现`；`wb_task.py:33` |
| `tools/pool/landing.py` | `tools/wb_land.py` | `wb_land.py:69` —— `from pool import landing as _landing` |
| `tools/pool/review.py` | `tools/wb_impact.py` | `wb_impact.py:55` —— `# 白名单判据唯一实现` |
| `tools/pool/plan.py` | `tools/wb_plan.py` | `wb_plan.py:82`、`:84` |
| `tools/pool/stage_card.py` | `tools/wb_stage_card.py` | `wb_stage_card.py:22` —— `from pool import stage_card as _stage_card` |
| `tools/pool/models.py` / `model_registry.py` | `tools/wb_state.py`、`tools/wb_dispatch.py` | `wb_state.py:70`（惰性 import）、`wb_dispatch.py:123` |
| `tools/pool/projects.py` | `tools/wb_project.py` | `wb_project.py:30` —— `from pool import projects, registry` |
| `tools/pool/platforms.toml` / `tools/pool_accounts.py` | `tools/pool_mcp.py`（`account_status`） | `pool_mcp.py` 的 `tool_account_status()` —— `import pool_accounts`，MCP 面只读账本、不探测不联网 |
| `tools/pool/checkin.py` / `gates/diag/checkin-<日期>.json` | `tools/pool_mcp.py`（`checkin_status`）+ `tools/wb_daily.py`（一行） | 只读**留档** + 账本 `health.last_checkin` / `last_probe`（结论码可能是旧的，标明是哪天的，别当今天）：MCP 与今日一页都不触发签到、不联网；真要签得人跑 `pool_accounts.py checkin --all` |
| `tools/pool/trae_dispatch.py` | **无**（刻意不接进派活，卡 218 已裁定） | 全仓 `grep -rn trae_dispatch` 只命中 `tests/test_trae_dispatch.py` |

### 表 B · pool 不做的事（每条写「归谁」+ 证据）

| # | 不做 | 归谁 | 证据 |
|---|---|---|---|
| 1 | 不判「门过不过」 | 门表与判据在 `gates/defs/`；编排在 `scripts/run_gates.py` | `tools/pool/landing.py:25`（③″ 调 `run_gates.py --fast`）、`:28`（④ 跑门禁） |
| 2 | 不改判据、不放宽门、不手写门禁结论 | 判据归 `gates/`，封存归 `scripts/run_gates.py` | `scripts/run_gates.py:860`（`def seal()`） |
| 3 | 不算台账分布 | 片段只**写**、汇总归 `tools/sync_docs.py`、分布归 `tools/sync_counts.py` | `tools/pool/stage_card.py:1`；`tools/pool/landing.py:24`（③ 调 sync_counts） |
| 4 | 不建 / 不删工作树 | 树由 `tools/wb_plan.py worktrees` 建；pool 只在给定树里干 | `tools/wb_plan.py:22` |
| 5 | 不判模型额度与批准集 | 批准集在号池快照 + `tools/pool/model-registry.toml`；pool 只**读** | `tools/pool/models.py:1`（"只读、不联网、不写快照"） |
| 6 | 不做审计结论 | 归 `scripts/audit_progress.py` | `tools/pool/landing.py:37`（⑦ 调它） |
| 7 | 不做技能口径 | 归 `skills/`（分区 G）；**删掉 `skills/` 框架仍可用** | `skills/README.md` |

### 表 C · 与相邻子系统的交界（交界处谁说话）

| 相邻 | 交界在哪 | 谁定义口径 |
|---|---|---|
| CI 子系统（分区 E） | 门禁档位、封存指纹、红单归并 | `docs/subsystems/ci/README.md` |
| 文档治理（分区 F） | 片段的形态、汇总同步、文档门禁 | `docs/subsystems/`、`scripts/check_docs.py` |
| 软工技能（分区 G） | 操作顺序与常见错（怎么用，不是判据） | `skills/` |
| 号池基础设施（仓库外） | 池注册、账号、模型开关文件 | `D:/repo/infra/pool/`（仓外，只读） |

**越界判据**（写偏了就判不通过）：把门禁判据抄进 pool 文档；把 pool 描述成"跑门禁的工具"；
出现"未来会做"；把 `skills/` 的操作步骤整段搬过来；表 A/B/C 任一表缺失或缺证据路径。
