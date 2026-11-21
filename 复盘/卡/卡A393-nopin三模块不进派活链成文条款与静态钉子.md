# 卡 A393：speed / pricing / usage_ingest.merged_tokens 永不进派活链 —— 把口头红线钉成静态判据

> 台账号 `T-AG684`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A393｜层 判据层（产品码一个字节不改）｜基准 `37a09b98`（起草时主树 HEAD，2026-11-21 09:58 实读；立卡时主树已推进，落地前重核）｜depends A392

> depends 说明：**只有一条 depends A392，且它不是「文件相交」而是「判据前提」**。A392（F43 读端接线）把 `tools/pipeline_view.py` 变成 `usage_ingest` 的第二个 importer —— 本卡判据 2 的白名单把它写进去了，A392 没落之前那条断言必然红。所以 depends A392 是判据依赖，不是域依赖。判据两处：`tools/pool/plan.py:61-64` 逐字「`files` 里**不许**出现的通配字符 … 「出现 "file" 这类通配 ⇒ 它与**任何**精确路径都不相交 ⇒ 两张卡明明改同一批文件却互不报冲突」，以及 `tools/pool/plan.py:320-327` 的「files 相交 …（同一文件两个写者；要共存就给其中一张写 `depends`）」。实算读数：`docs/workbacklog.toml` 里 status 非 done 的卡 14 张 = D1 到 D8、C1、C2、A375、A384、A389、A391（tomllib 实读，2026-11-21 09:58）；其中认领 pool 文档的只有三张 —— A375 与 A391 认领 `docs/subsystems/pool/README.md`、A384 认领 `docs/subsystems/pool/模型与号池.md`、A375 另认领 `docs/subsystems/pool/modules.toml`。本卡域四份**全是新建文件**，与这 14 张零相交。**前提是本卡不碰那三份文档**（见「卡域」末两条与判据 3 的代价）。

> 基准说明：抬头的 `37a09b98` 是起草这一刻实读的主树 HEAD（`37a09b9848efb405166a8b2b87de0912b938f005`，`git rev-parse` 实读），提交「fix(tools): 封存指纹临时索引每次调用唯一：并发读者不再互相锁死回退None（T-G385）」，2026-11-21 09:35:42 +0800。工作树从那一刻的 HEAD 切出来后行号要重核：本卡引用的 import 行号最密的是 `tools/wb_dispatch.py`（4336 行，26 处 pool import），它每天都在长。★ 起草时记的是 22，物化时在卡树 AST 实读是 26（条目里补上了 `:111` / `:112` / `:563` 三条 `import pool_accounts` / `import pool_quota`），这里就地改成实测值 —— 两个数不许并存。

> 依据（红线来自用户，不是仓内既有条款）：本会话用户多次重申的硬约束 —— 「speed.py / pricing.py / usage_ingest.merged_tokens 不许接进派活链（派活顺序、限额判断、路线选择都不许消费它们）」。这条规矩今天在仓内**没有成文条款**（见判据 5 与「诚实边界」第 6 条）；同类先例只有 `docs/subsystems/pool/README.md:170` 那一行「刻意不接进派活，卡 218 已裁定」（对象是 `tools/pool/trae_dispatch.py`）。

## 前情：三件东西为什么必须停在判据层（每件一句依据）

1. **`tools/pool/speed.py`（261 行）回答的是「什么情况不许报速度」**，它自己就是一条判据：`tools/pool/speed.py:27-28` 逐字「★ 所以「不许接线」是**判据**而不是洁癖：接进去只能接假数，那正是本卡要消灭的东西。`tools/` 全目录没有任何一处 import 本模块（钉子在 `tests/test_pool_speed_tells.py`，源码级断言）。」—— 今天 pool 不产 `ttft` / `first_text` / `flow` 这三列（`docs/subsystems/pool/modules.toml:223` 逐字「无（今天**零调用**：pool 不产 `ttft` / `first_text` / `flow`，接线只能接假数）」），接进派活链等于让排序器按**编出来的**速度决定先干哪张卡。
2. **`tools/pool/pricing.py`（231 行）没有价目表**，`Price` 一律由调用方构造（`docs/subsystems/pool/modules.toml:107-108`）；而活账今天**金额恒 0.0**：`tools/wb_dispatch.py:1755-1756` 逐字「* **金额恒 0.0**：仓里没有计价表（`tools/pool/model-registry.toml` 里 `price|cost|单价` 零命中），第二档不编单价，等有计价表再填。」。两边互不调用是写进注释的既有约束：`tools/pool/ledger_spend.py:23` 逐字「不是估算：本模块**仍然不算钱**（算术在 `tools/pool/pricing.py`，两边互不调用）。」，`:225` 再写一次。
3. **`usage_ingest.merged_tokens` 是读端合并器，而活账的读端另有其人**：`tools/pool/usage_ingest.py:44-45` 逐字「★ **本卡零接线**：`tools/wb_dispatch.py` 一个字节都没改。`merged_tokens()` 今天**零生产调用方**，`usage_in()` 还没有 `include_reported` 参数 —— 那是下一张卡。」这条注释本身就把「下一张卡」推给了未来 —— 本卡要做的是**在有人真去接之前先把闸门钉死**，而不是替他接线。

## 本仓现状（`37a09b98` 实读，四条独立读数）

**一句话：三件东西都是「有模块、零生产消费者」，而「零消费者」这件事今天只被三份**行为**测试间接照看着，没有一条钉子钉住「谁不许消费它们」。**

1. **派活侧四个文件，一个都没 import 这三个模块**（AST 实扫，不是 grep）：
   - `tools/wb_dispatch.py`（4336 行 / 30 个顶层模块名）**26 处** pool import（2026-11-21 11:40 卡树 AST 实读；起草时记 22），逐行：`:111` `import pool_accounts`、`:112` `import pool_quota`、`:121` account_id、`:122` guards、`:123` outcomes、`:124` registry、`:125` rpm、`:126` sink、`:127` sticky、`:128` task、`:129` `pool.jobs.card_artifacts`、`:130` `pool.model_registry`、`:148` `pool.models`、`:153` `pool.plan`、`:158` `pool.review`、`:467` / `:508` limits、`:563` `import pool_accounts`、`:2758` `pool.models.STALE_HOURS`、`:3580` callers、`:3644` ledger_spend、`:3645` limits_check、`:3646` limits_policy、`:3691` holds_wiring、`:3744` accounts_scope、`:4125` ledger_spend。三个禁名 0 命中。
   - `tools/pool/limits_check.py`（174 行 / 6 个模块名）：唯一的 pool 侧 import 是 `:29` 「from pool.limits_policy import Limit, window」。0 命中。
   - `tools/pool/route.py`（883 行 / 9 个模块名）：**一个 pool 包 import 都没有**，`:58` 是「import pool_quota」。0 命中。只提醒一处假阳性：`tools/pool/route.py:317` 的别名元组里有字符串 "speed"（FASTEST 的别名），那是**名字**不是 import —— 走 AST 就不会误判。
   - `tools/pool/gateway.py`（1458 行 / 19 个模块名）：pool 侧 `:58` guards、`:59` holds、`:60` lanes、`:61` model_registry、`:62` models、`:63` prompt_parts、`:64` route、`:65` route_log、`:66` rpm、`:67` sink。0 命中。
2. **全生产码 178 个 py 文件（`tools/` 与 `scripts/` 下全部，去掉 `__pycache__`）实扫**：`pricing` 的 importer **零**、`speed` 的 importer **零**、`usage_ingest` 的 importer **恰一条** —— `tools/pool_mcp.py:204` 「from pool import accounts_scope, guards, registry, task, usage_ingest」（MCP 写面 usage_report，卡 A364 的唯一入口）。`merged_tokens` 的 `ast.Name` / `ast.Attribute` 引用**零**（只有它自己的 def 在 `tools/pool/usage_ingest.py:623`，加两处 docstring 提及 `:22` 与 `:44`）。全仓也无 `importlib.import_module` 动态导入。
3. **公开面清单**（本卡钉子要按名字点名，所以先把名字抄下来）：`tools/pool/pricing.py` —— `Tier`:32、`Price`:48、`per_token`:63、`openrouter_pricing`:89、`one_hour_for`:106、`at`:126、`one_hour`:152、`cost`:161、`unpriced_calls`:193（私有 `_has_price`:213）；`tools/pool/speed.py` —— `window`:169、`tells`:185、`tells_record`:233、`codex_short`:254；`tools/pool/usage_ingest.py` —— `Fault`:119、`IngestRefusedError`:138、`reported_path`:155、`parse_batch`:166、`ingest`:483、`merged_tokens`:623（签名 `def merged_tokens(model: str, start: datetime, end: datetime, *, root: Path | str | None = None, include_reported: bool = False) -> int`）。
4. **既有的四份钉子各自只照一个点，没有一个照「面」**（判据 1/2 的不重复性就建立在这一条上）：`tests/test_pool_speed_tells.py:305` 只扫 `tools/`（不进 `scripts/`）、只认 `pool.speed` 一个名字；`tests/test_pool_pricing.py:293` 只钉 `pricing.cost` 与 `ledger_spend` 互不调用；`tests/test_pool_usage_ingest.py:416-431` 只钉 `merged_tokens` 的**行为**（60 / 1060），不钉它有没有被派活链消费；`tests/test_pool_route_wiring.py:64` / `:166` 钉的是**路由名**（fast / speed / speed-first 这些字符串常量 + `SINK_ROUTING == "order"`），不是模块。

## 判定

**PORT（只收「判据」这一层）：产品码一个字节不改，把「这三个模块永远不进派活链」从会话里的口头约束写成可执行的静态判据 + 一份 ADR。搜索三模块的处置（删码还是留库）**不**在本卡里替用户决定 —— 判据 3 只把两条互斥的判据面与各自代价写出来，等定夺后择一落。**

| 对象 | 今天的生产状态（实读） | 本卡要钉的那一位 | 依据 |
|---|---|---|---|
| `tools/pool/speed.py` | 零 importer（178 文件实扫） | 派活侧四文件的 import 集合里永不出现 | `tests/test_pool_speed_tells.py:305`（点）→ 本卡判据 1（面） |
| `tools/pool/pricing.py` | 零 importer | 同上 | `tests/test_pool_pricing.py:293`（只钉与 ledger_spend 互不调用） |
| `usage_ingest.merged_tokens` | 零调用点；`usage_ingest` 的唯一 importer 是 MCP 面 | 调用点集合恒空 + importer 集合恰等于一份白名单 | `tools/pool/usage_ingest.py:44`；`tools/pool_mcp.py:204` |
| `tools/pool/search.py` / `tools/pool/searcher.py` / `tools/pool/web_fetch.py` | 零 importer（三个都零） | **开放项**：判据 3 的两支择一 | magpie F59 的 web_search / web_fetch 已判 SKIP_BY_REDLINE（卡 A378 :73），所以它们永远不会有消费者 |

**立论支点**：把「不许接线」写成断言，收益不是「防止今天的 bug」，而是**让将来那一次接线变成一次可见的红**。今天这三件东西零消费者是**事实**，但事实没有守卫 —— 谁明天在 `tools/wb_dispatch.py` 顶部加一行「from pool import speed」，`pytest` 会全绿，`ruff` 会全绿，门禁会全绿。本卡要消灭的正是这个「看不见」。

## 判据（5 条，每条都能用一条 pytest 证明）

### 判据 1 · 派活侧四个文件的可达 import 集合与三个禁名零相交（**本卡新写的断言**）

**怎么证明**：AST 扫四个文件（**走 AST 不走正则** —— 体例照 `tests/test_no_window.py:15` 逐字「扫描走 **AST**（不是正则）：文档字符串里提一句 `subprocess.run(…)` 不会被误判。」）。收集 `ast.Import` 的 `alias.name` 与 `ast.ImportFrom` 的 `("." * level) + module` 及 `module + "." + alias.name`，按**末段**与禁名集合相比（这样 `import pool.speed`、`from pool import speed`、`from . import speed` 三种写法一网打尽）：

```python
DISPATCH_SIDE = (
    "tools/wb_dispatch.py",        # 派活器本体（4336 行，26 处 pool import）
    "tools/pool/limits_check.py",  # 限额判断（174 行）
    "tools/pool/route.py",         # 路线选择（883 行）
    "tools/pool/gateway.py",       # 网关（1458 行）
)
BANNED_TAILS = frozenset({"speed", "pricing", "usage_ingest", "merged_tokens"})
# 前提自证：四份合起来至少 60 个模块名、四份都不为空 —— 防扫描器退化成恒真空转
# 判据：每个文件的 import 末段集合与 BANNED_TAILS 不相交
# 反向自证：临时注入一行 "from pool import speed as _x" ⇒ 必红；删掉 ⇒ 必绿
```

本卡实跑读数（`37a09b98`）：四份的顶层模块名个数分别是 **30 / 6 / 9 / 19**，禁名命中**全为 0**；反向自证见判据 4 的 M1 / M3。

★ **为什么不与既有钉子重复**：`tests/test_pool_speed_tells.py:305` 证明的是「`tools/` 全目录没人 import pool.speed」，扫的范围是**目录**、认的名字是**一个**，而且**不扫 `scripts/`**。它照不住三件事：① `scripts/` 下有人接线；② `pricing` 与 `usage_ingest` 两个名字；③ 「派活侧是哪四个文件」这个**面**。本卡钉的是面 —— 「这四个文件里不许出现，别处出现了本卡不管（那由判据 2 的白名单管）」。

### 判据 2 · 活账的分子只许来自 `wb_dispatch.usage_in`；`merged_tokens` 在**派活链上**的调用点集合恒空，`usage_ingest` 的 importer 集合恰等于一份白名单（**本卡新写的断言**）

**怎么证明**：三件事一起钉，缺一条都能被绕过。

```python
# ① 名字级零引用：**派活链那五个文件**里不出现 merged_tokens / reported_summary 的 Name / Attribute
#    （名字级，不是文本级 —— 所以 tools/pool/usage_ingest.py:44 那句 docstring 提及不会误判，
#      体例照 tests/test_pool_pricing.py:311 的 _code_names()：只收 Import / ImportFrom / Attribute / Name）
# ② 相等而不是包含：import usage_ingest 的文件集合 == {"tools/pool_mcp.py"}
ALLOWED_IMPORTERS = frozenset({"tools/pool_mcp.py", "tools/pipeline_view.py"})
# tools/pool_mcp.py = MCP 写面 usage_report（卡 A364 唯一入口）
# tools/pipeline_view.py = 只读读数面（卡 A392 / F43 读端接线，用 merged_tokens 与 reported_summary）
# ★ 判据是「相等」不是「包含」：再有第三个 importer 出现就得回来改这一行并在 ADR 里写理由。
# ③ 正对照：活账的分子今天走的是 wb_dispatch.usage_in，不是 merged_tokens ——
#    tools/pool/holds_wiring.py:184 的 "from wb_dispatch import usage_in" 必须仍在
```

本卡实跑读数：① 引用 **0**；② importer 恰为 `tools/pool_mcp.py`（`:204`）**一条**；③ 正对照在 —— `tools/pool/holds_wiring.py:176` 的定义、`:184` 的 import、`:214` 的 `usage_first_at` 都在，`tests/test_holds_wiring.py:275` 就是它的钉子（判据 5 原文「分子只许来自 `wb_dispatch.usage_in` —— 薄层不自己读那份 jsonl」）。

★ **这条钉的是「两个消费面分开」**：只读面（MCP 的 usage_report 收上报行）今天**有**消费者，那是设计允许的；派活链（派活顺序 / 限额判断 / 路线选择）**一个都不许有**。将来真要让只读面用 `merged_tokens`，必须先改这份白名单并在 ADR 里写一句为什么 —— 白名单是**评审面**，不是豁免口。

### 判据 3 · 搜索三模块的处置：**立卡时定为 3A（保留为库，钉零消费者）**

三个模块今天都零 importer（178 文件实扫）：`tools/pool/search.py`（258 行）、`tools/pool/searcher.py`（508 行）、`tools/pool/web_fetch.py`（695 行）。它们**永远不会有消费者**这件事有判词可依：magpie F59 的 `web_search` / `web_fetch` 已判 **SKIP_BY_REDLINE**（卡 A378 :73 逐字「1. `web_search` / `web_fetch` ⇒ **SKIP_BY_REDLINE**。」，红线是 `docs/EXTENDING.md:73` 逐字「2. **数据不出本地** —— 不上云、不新增对用户数据的外部依赖」）。但**「没有消费者」不等于「该删」** —— 删 1461 行产品码 + 1256 行判据是不可逆动作，本卡不替用户拍板。**立卡时定为 3A（保留为库）**：只钉「零消费者」，一行代码都不删；3B 的代价留在下面这张表里，将来谁要删另开卡。

| 分支 | 判据面怎么写 | 代价（都要写进 ADR） |
|---|---|---|
| **3A 保留为库** | 与判据 1/2 同一手法：三模块名在 `tools/` + `scripts/` 的 import 集合里恒为空集；红了就说明「有人接线了，先回来改 ADR」 | ① 1461 行代码继续被 `ruff` / `mypy` / 覆盖率门看着，永远不进产品；② 谁哪天顺手接线，钉子红但**没有明确的「归哪张卡」**；③ `docs/subsystems/pool/README.md` 表 B 值得补一行「为什么不删」（该文件在 A375/A391 域里 ⇒ 要写 depends 或交给下一张文档卡）；④ 好处是 A372 / A374 / A385 三张 done 卡的判据层仍有实现落点，`tests/test_pool_search_keys.py`（310 行）/ `tests/test_pool_searcher.py`（492 行）/ `tests/test_pool_web_fetch.py`（454 行）继续有效 |
| **3B 判死删码** | 反过来钉「文件不存在」：三个模块文件 + 三份测试文件 `is_file() is False`；`docs/subsystems/pool/modules.toml` 里也没有这三个 name | ① 删 1461 行产品码 + 1256 行判据（合计 2717 行）；② **必须同时删 `docs/subsystems/pool/modules.toml` 的 `:305` / `:309` / `:319` 三块** —— 否则 `scripts/gen_pool_readme.py:160-171` 的两向对账会报「清单自己成了死指针」（该对账是「仓里有但清单没写」与「清单写了但仓里没有」**两向**都点名）；③ `docs/subsystems/pool/modules.toml` 今天在 **A375** 的域里 ⇒ 选 3B 就**必须**写 `depends A375`，抬头「零相交」的前提当场失效；④ 三张 done 卡（A372 / A374 / A385）的判据层随之退回成「只剩复盘里的读数」，将来要复活得重写 |

**本卡落 3A**：判据 3 的可执行断言只有一条 —— 三个模块名在 tools/ 与 scripts/ 的 import 集合里恒为空集（红了就说明「有人接线了，先回来改 ADR」）；3B 的代价写进 ADR 的「候选方案」一节（`docs/decisions/README.md:66` 要求 `Status:` 只能是 Proposed / Accepted / Superseded，被否的分支不进 Status，只进正文）。

### 判据 4 · 反向变异 ≥3 条全部咬住 + 1 条安静对照不响（**本卡自己证明自己的钉子有牙**）

**怎么证明**：在卡树（.wt 下的 A<新号> 目录）里真改、真跑、按**原字节**写回（不碰 git —— 见「不许做」第 8 条），最后用 sha256 自证四个文件与注入前逐字相同。

| 编号 | 变异（真改下去的那一行） | 应当咬住 | 期望 |
|---|---|---|---|
| M1 | `tools/wb_dispatch.py` 顶部插一行「from pool import speed as _speed」 | 判据 1 | 红，且报错里点名 `tools/wb_dispatch.py` 与名字 `speed` |
| M2 | `tools/pool/holds_wiring.py:184` 的「from wb_dispatch import usage_in」改成走 `usage_ingest.merged_tokens` | 判据 2 ③（正对照） | 红 |
| M3 | `tools/pool/limits_check.py` 里插一行「from pool.pricing import cost」（四份里最不起眼的一个） | 判据 1 | 红，且点名 `tools/pool/limits_check.py` |
| M4 | 把 ADR 0013 的「## 决定」一节删掉，或把编号改成 0014 | 判据 5 | 红 |
| N1 | 安静对照：只改三模块 docstring 里的**一句话**（不动 import、不动调用、不动签名） | 四条**一条都不许红** | 全绿 |

收尾口径照 A378 的写法：**「结论：4/4 咬住 + 1 条安静对照未响，收尾绿」**，并把每次变异的 `sha256` 与还原后的 `sha256` 一起记进卡规格的「本卡落地实测」一节。变异脚本落 gates/diag 下（被 `.gitignore:76` 的 gates/diag 通配规则覆盖 ⇒ 不进主树、不进卡域，**不是**长期钉子）。

### 判据 5 · 成文条款：ADR 0013 落盘并过机器检查（**把口头约束挪进可检索的地方**）

**怎么证明**：

```python
# ① 文件在：docs/decisions/0013-<slug>.md（编号取下一个空号）
# ② 结构：四节齐全（## 背景与问题 / ## 候选方案 / ## 决定 / ## 把握程度）
#    + 头信息 Status / 来源 两行（正则体例照 tests/test_pool_no_systemone.py:217-237）
# ③ 正文里逐字出现 9 个名字：speed.py / pricing.py / usage_ingest.py / merged_tokens
#    + 四个派活侧文件路径 —— 没有名字的禁令没法 grep，也没法对账
# ④ python -X utf8 scripts/check_docs.py --decisions 退出码 0（编号连续、无空洞）
```

编号口径：`docs/decisions/` 今天实存 0001…0012 加一个 README（13 个文件，`ls` 实读）⇒ 下一个空号是 **0013**；A390 的 `docs/decisions/0012-route-strategies-wiring.md` 已经落盘，不再是待建。今天基线：`scripts/check_docs.py --decisions` ⇒ 扫到 12 条（0001..0012）、`[OK ] 决策记录检查通过`、退出码 0。

★ **为什么那条「README 表 B 第 9 行 / 模型与号池.md 新增一节」不列本卡域**：那两份文件分别被 A375 / A391 与 A384 认领（上面的 depends 说明）。成文条款落 ADR + 钉子两处就够了 —— ADR 是可检索的「决定」，钉子是可执行的「守卫」；README 表 B 那一行由落地后台账点名交给下一张文档卡，**不要为了「写进文档」把域撞开**。

## 卡域 files（精确路径，不许通配）

- 新建的 tests/test_pool_nopin.py —— 判据 1/2/5 与 3A 若被选中时的断言全部落在这一个文件（约 6 条 `def test_`；模块 docstring 写三节：「病 / 判据判什么 / 为什么走 AST」）。**本卡新建，故不作反引号路径**。
- 新建的 docs/decisions/0013-nopin-not-wired.md —— 四节按 `docs/decisions/README.md:33` 的模板；`Status: Accepted`、`来源:` 写台账条目号 + 本卡号。**本卡新建，故不作反引号路径**。
- 复盘/卡 下的本卡规格（**本卡新建，故不作反引号路径**）。
- 新建的 docs/changelog.d/<台账号>.md（**本卡新建，故不作反引号路径**）。

> **卡域里不列**这些（列进去会被 `tools/pool/plan.py:320-327` 的 `files_intersect()` 算成本卡可写，而本卡一个字节都不改）：`tools/wb_dispatch.py`、`tools/pool/limits_check.py`、`tools/pool/route.py`、`tools/pool/gateway.py`（判据只**读**它们）、`tools/pool/speed.py`、`tools/pool/pricing.py`、`tools/pool/usage_ingest.py`（判据只**点名**它们，不改）、`docs/subsystems/pool/README.md`（A375 / A391）、`docs/subsystems/pool/模型与号池.md`（A384）、`docs/subsystems/pool/modules.toml`（A375）。
> **不列 `docs/workbacklog.toml`**：立卡惯例（A386 / A387 / A388 / A390 的台账条目）是台账由立卡脚本写、不进 `files`。
> **若判据 3 选 3B**：域要多一行 `docs/subsystems/pool/modules.toml` 侧的三块删除 + 三个模块与三份测试的删除，并**必须**写 `depends A375` —— 那时抬头「零相交」这句要当场改，不许留着。

## 交付（逐文件）

| 文件 | 动作 | 内容 |
|---|---|---|
| tests/test_pool_nopin.py（已建，322 行） | 新建 | 判据 1（四文件 AST 不相交 + 前提自证）、判据 2（名字级零引用 + importer 白名单相等 + 正对照）、判据 5（ADR 结构 + 9 个名字 + 编号）、判据 3A 三模块零消费者（若选 3A） |
| docs/decisions/0013-nopin-not-wired.md（已建，109 行） | 新建 | 标题「speed / pricing / merged_tokens 不进派活链」；「决定」一节逐字写 3 个模块名 + 4 个派活侧文件 + 「接进派活链 = 违反本 ADR，钉子红」；「候选方案」一节写判据 3 被否的那一支与理由 |
| 复盘/卡 下的本卡规格（即本文件） | 新建 | 本文件物化后的形态；「本卡落地实测」一节填真读数 |
| docs/changelog.d/T-AG684.md（已建，5 行） | 新建 | 一行摘要 + 证据指针 |

## 验收命令

```bash
# ① 本卡新增的钉子（今天应先把 5 条全红着写出来，再让它变绿）
python -X utf8 -m pytest tests/test_pool_nopin.py -q -o addopts= --no-cov
# ② 既有五套判据一条都不许红（今天基线 63 passed，逐文件 13/17/14/12/7）
python -X utf8 -m pytest tests/test_pool_speed_tells.py tests/test_pool_pricing.py \
    tests/test_pool_usage_ingest.py tests/test_holds_wiring.py tests/test_pool_route_wiring.py \
    -q -o addopts= --no-cov
# ③ ADR 结构 + 编号连续
python -X utf8 scripts/check_docs.py --decisions
# ④ pool 清单与盘子两向对账（若判据 3 选 3B 删码，这条是必跑项）
python -X utf8 scripts/gen_pool_readme.py --check
# ⑤ 风格（行宽 100）
python -X utf8 -m ruff check tests/test_pool_nopin.py
```

★ **落地实跑一律带 `-p no:xdist`**：上面 ① ② 两块照卡规格抄下来少了这一个开关，装了 pytest-xdist 的机器上会并发跑。物化后本卡的两条判据命令实际是
`python -X utf8 -m pytest tests/test_pool_nopin.py -o addopts= -q --no-cov -p no:xdist`，既有五套同理（读数见「本卡落地实测」）。

**今天的基线读数（起草时实跑，`37a09b98`）**：五套既有判据合跑 ⇒ **63 passed in 13.12s**（`--collect-only` 逐文件：speed_tells 13 / pricing 17 / usage_ingest 14 / holds_wiring 12 / route_wiring 7）；`scripts/check_docs.py --decisions` ⇒ 扫到 12 条、`[OK ]`、退出码 0；`scripts/gen_pool_readme.py --check` ⇒ `[OK  ] docs/subsystems/pool/README.md 与现算一致（60 个文件 / 24293 行 / 2026-11-21）`、退出码 0。

**已知噪音（别当红）**：

1. 默认 `addopts` 带覆盖率门槛（`pyproject.toml:51` 逐字 `addopts = "-q -m \"not acceptance and not chain\" --cov=timeflow --cov-fail-under=70"`）⇒ 单跑一个文件不加 `-o addopts= --no-cov` 会因覆盖率不到 70% 而红，与本卡无关。
2. 新 ADR 会让 `docs/INDEX.md` 的篇数 +1 —— **不要手改 `docs/INDEX.md`**（它是生成物），落地链自己跑 `scripts/gen_doc_index.py`。
3. `scripts/check_docs.py --mode report` 今天**不是干净基线**：死指针 147（基线 147，+0）、drift 560（基线 379，+181，只报告）、superseded 1（基线 1，+0）、「判不出」1516 条（skip，**不是 PASS**）。本卡不负责清；交付口径是「与动手前逐项相同」。★ 这两个数**会动**：同一条命令在 f90acf75（立卡 A392，10:04）上重跑是 drift 563 / 判不出 1521，死指针仍是 147 —— 变的只有台账条目，与本卡无关。
4. 判据 1 / 2 会在「真有人把这三个模块接进派活链」那一天变红 —— **这是设计意图，不是回归**。
5. 判据 3 无论选哪一支，都会让域与 **A375** 相交（3B 必然要改 `docs/subsystems/pool/modules.toml`；3A 若要在 README 表 B 补一行也必然）—— 那不是噪音，那是 `depends` 的判据；抬头已写明「选 3B 就要当场改」。
6. 「京」类误判提醒：`tools/pool/route.py:317` 的字符串 "speed" 是 FASTEST 的**别名**，不是模块名；`tools/pool/speed.py:23` 提到 magpie 的 internal/gateway/usage_ingest.go:77 是**另一个仓的同名文件**，与 `tools/pool/usage_ingest.py` 无关。走 AST 两条都不会误判 —— 别改成文本 grep。

## 本卡落地实测（卡树 .wt/A393，2026-11-21 11:40–12:45）

四条判据命令都在**卡树**里跑（`cwd = .wt/A393`），一律 `-o addopts= -q --no-cov -p no:xdist`。

### 交付文件与行数

| 文件 | 行数 | 字节 | 行尾 |
|---|---|---|---|
| tests/test_pool_nopin.py（新建） | 322 | 15415 | crlf 322 / lf-only 0 |
| docs/decisions/0013-nopin-not-wired.md（新建） | 109 | 8591 | crlf 109 / lf-only 0 |
| docs/changelog.d/T-AG684.md（新建） | 5 | 580 | crlf 5 / lf-only 0 |
| 本文件（改：22 → 26、补本节） | 310 | 43471 | crlf 310 / lf-only 0 |

产品码零改动：卡树里 `git status --porcelain` 只有三行 `??`（上面三份新文件）+ 本文件一行 ` M`，`git diff` 对 `tools/` 与 `scripts/` 无输出。

### 判据的自测命令与读数

1. **判据 1（派活侧 import 末段零相交）** —— 断言 `test_dispatch_side_imports_never_touch_banned_modules`。前提自证实读：`tools/wb_dispatch.py` 30 / `tools/pool/limits_check.py` 6 / `tools/pool/route.py` 9 / `tools/pool/gateway.py` 19 ⇒ **合计 64**（门槛 60），禁名命中 0。
   ★ 实测踩到一个真坑：`_import_tails` 一开始只收 `ImportFrom.module`，于是 `from pool import speed`（名字挂在 alias 上、module 是光秃秃的 `pool`）**整条漏网**，变异 M1 第一次跑竟是绿的 —— 判据自己没牙。修法是把 `module + 点 + alias.name` 也收进末段集合；改完 M1 立刻咬住。
2. **判据 2 ①（名字级零引用）** —— `test_dispatch_chain_never_names_merged_tokens`；派活链五文件（四份 + `tools/pool/holds_wiring.py`）的名字集合里 `merged_tokens` / `reported_summary` 全 False。
3. **判据 2 ②（importer 白名单）** —— `test_usage_ingest_importers_stay_in_whitelist`：今天是**子集 + 必含**（`tools/pool_mcp.py` 在，且不越出 `ALLOWED_IMPORTERS`），**不是**字面的「相等」—— 因为 `tools/pipeline_view.py` 今天还没接线（A392 未落），写成相等必红。A392 落下后收紧成相等是一行改动（ADR 0013「决定」三已写明这条口径）。
4. **判据 2 ③（正对照）** —— `test_positive_control_is_wb_dispatch_usage_in`：`tools/pool/holds_wiring.py:184` 的 `from wb_dispatch import usage_in` 仍在。**判据 3A（搜索三模块零消费者）** —— `test_search_triplet_has_zero_consumers`：`search` / `searcher` / `web_fetch` 在 178 个 py 文件的 import 集合里各 0。
5. **判据 5（ADR）** —— `test_adr_exists_and_passes_machine_check`（结构 + 九个名字 + 真检查器）+ `python -X utf8 scripts/check_docs.py --decisions`。

```bash
# 判据 1 / 2 / 3A / 5 合跑（卡树）
python -X utf8 -m pytest tests/test_pool_nopin.py -o addopts= -q --no-cov -p no:xdist
# ⇒ 6 passed in 5.58s

# 既有五套一条都没动、一条都没红
python -X utf8 -m pytest tests/test_pool_speed_tells.py tests/test_pool_pricing.py tests/test_pool_usage_ingest.py tests/test_holds_wiring.py tests/test_pool_route_wiring.py -o addopts= -q --no-cov -p no:xdist
# ⇒ 63 passed in 7.36s（与起草时同数、同逐文件条数）

# ADR 结构与编号
python -X utf8 scripts/check_docs.py --decisions
# ⇒ [info] 决策记录：扫到 13 条（编号 0001..0013），supersedes 链 0 对
# ⇒ [OK ] 决策记录检查通过   退出码 0

# pool 清单两向对账（3A 不改码，这条只为确认没被带偏）
python -X utf8 scripts/gen_pool_readme.py --check
# ⇒ [OK  ] docs/subsystems/pool/README.md 与现算一致（60 个文件 / 24293 行 / 2026-11-21）   退出码 0
```

### ruff（行宽 100）

```bash
python -X utf8 -m ruff check tests/test_pool_nopin.py
# ⇒ All checks passed!   退出码 0（ruff 0.16.6）
```

改到全绿之前被咬过三处，记下来免得下一个人重踩：① 模块 docstring 里排 markdown 表格，每行 106~114 字 ⇒ E501 六条，改成条目列表；② `_import_tails` 的 docstring 单行 108 字 ⇒ E501；③ 正对照里的嵌套 if ⇒ SIM102，提成 `is_usage_in` 再单层 if。

### 反向变异（判据 4）

脚本 `gates/diag/_rev_A393.py`，结果 `gates/diag/_rev_A393_result.txt`（都在主树、被 gates/diag 的 ignore 规则挡着，不是长期钉子）。真改 / 真跑 / 按**原字节**写回（不碰 git）：每份文件先 `read_bytes()` 存进内存，改变异、跑 pytest、立刻原样写回，最后再用 sha256 前 16 位自证。五次跑的都是同一条 pytest 命令。

| 编号 | 真改下去的那一行 | 期望 | 实测 | sha256 前 16 位（注入前 → 注入后 → 还原） |
|---|---|---|---|---|
| M1 | `tools/wb_dispatch.py` 顶部插 `from pool import speed as _speed` | 判据 1 红且点名文件与名字 | **红**：`test_dispatch_side_imports_never_touch_banned_modules` FAILED，1 failed / 5 passed | `9f2bd180559d3d26` → `71ce6807b952c29e` → `9f2bd180559d3d26` |
| M2 | `tools/pool/holds_wiring.py:184` 的 `from wb_dispatch import usage_in` 改成 `from pool.usage_ingest import merged_tokens` | 判据 2 ③ 红 | **红**：`test_positive_control_is_wb_dispatch_usage_in` + `test_usage_ingest_importers_stay_in_whitelist` FAILED，3 failed / 3 passed | `d894198b311cedde` → `9af9f8ed75d0cfdc` → `d894198b311cedde` |
| M3 | `tools/pool/limits_check.py` 插 `from pool.pricing import cost` | 判据 1 红且点名 limits_check.py | **红**：`test_dispatch_side_imports_never_touch_banned_modules` FAILED，1 failed / 5 passed | `96bcc14bf7797e96` → `b531a3649dd45964` → `96bcc14bf7797e96` |
| M4 | 删掉 ADR 0013 的「## 决定」一节 | 判据 5 红 | **红**：`test_adr_exists_and_passes_machine_check` FAILED，1 failed / 5 passed | `c400e9e11dabc234` → 删节后 → `c400e9e11dabc234` |
| N1 | `tools/pool/speed.py` docstring 里加一句「（安静对照改的这一行）」 | 四条一条都不响 | **全绿**：6 passed | `610196c03b5b2dae` → `ac14ddd8c03fc4f1` → `610196c03b5b2dae` |

结果文件末行：**「结论：4/4 条全部咬住，收尾绿。」**（脚本退出码 0）。五个被改文件的还原 sha256 与注入前逐字相同（结果文件里逐条列了）。

### CRLF 自检

`crlf > 0` 且 `lf-only == 0`：`tests/test_pool_nopin.py` 322/0、`docs/decisions/0013-nopin-not-wired.md` 109/0、`docs/changelog.d/T-AG684.md` 5/0、本文件 310/0。变异脚本写回时也自检裸 LF（`mutate()` 里断言注入后裸 LF 数为 0）—— 五个文件注入期间与还原后都没出现裸 LF。

### 文档门禁读数（`scripts/check_docs.py --mode report`）

| 时点 | 死指针 | drift | superseded | 判不出 |
|---|---|---|---|---|
| 本卡动手前（卡树 HEAD 80436182） | 150（基线 147，+3） | 561 | 1 | 2727 |
| 本卡交付后 | 150（+3，**未涨**） | 561 | 1 | 2725 |

那 +3 条**不是本卡引入**：`--json` 的 `dead_refs` 里过滤 `A393` / `nopin` / `T-AG684` 命中 **0 条**；三条全部来自 A392 规格（它的 changelog / traceability / 交接三处计划建路径，见 A392 规格 :140-142），主树已由 f8ce9d25 修掉，卡树 HEAD 80436182 不含那笔。主树同命令今天是 147（+0）。本卡的交付口径是「不新增」—— 三份新文件里的反引号没有一个指向计划建或不存在的路径。

### 诚实边界（本卡落地时新发现、没坐实或坐实不了的）

1. **判据 2 ② 今天不是字面的「相等」**：`tools/pipeline_view.py` 至今**没有** import `usage_ingest` / `merged_tokens` / `reported_summary`（A392 未落，主树与 .wt/A392 两个树都零命中）。所以断言写成「子集 + 必含 `tools/pool_mcp.py`」，并在测试 docstring 与 ADR 里逐字写明为什么今天只能这么钉。
2. **「A392 落地后 `pipeline_view` 会消费 `merged_tokens`」仍然只是计划**：A392 的卡规格这么写，但代码不存在、无法验证。本卡的白名单第二项是照卡规格钉的，不是照代码钉的。
3. **`reported_summary` 在仓里根本不存在**（`tools/pool/usage_ingest.py` 里 0 次、全仓 import 0 次）：它只作为**禁名**出现在判据 2 ①，是 ADR 正文里逐字写出的第 9 个名字（卡规格只列了 8 个）。
4. **判据自己没牙只能靠变异照出来**：M1 第一次跑是绿的（`_import_tails` 漏了 `from pool import X` 这种写法）。读代码看不出来，只有真注入一行才发现。
5. **没跑全量门禁**（按卡规格「不许做」第 9 条）：`scripts/run_gates.py`、全量 pytest 都没跑。所以本卡证明的是「这 6 条新钉子 + 既有 63 条绿」，**不是**「整棵树过门」。

---

## 不许做

1. **不许**改产品码一个字节：`tools/wb_dispatch.py`、`tools/pool/limits_check.py`、`tools/pool/route.py`、`tools/pool/gateway.py` 只**读**。判据是「它们今天长这样」，不是「把它们改成这样」。
2. **不许**把 `speed` / `pricing` / `merged_tokens` 接到任何生产路径上 —— 包括「只是先 import 进来备用」「只是放进 `__all__`」「只是加个 feature flag」。本卡的判据 1 / 2 就是为了让这类「先接上再说」变成红。
3. **不许**放宽既有判据：`tests/test_pool_speed_tells.py` 13 条、`tests/test_pool_pricing.py` 17 条、`tests/test_pool_usage_ingest.py` 14 条、`tests/test_holds_wiring.py` 12 条、`tests/test_pool_route_wiring.py` 7 条，一字不改。
4. **不许**替用户决定判据 3（搜索三模块删码还是留库）。物化时若拿不到选择，**停在 3A**（保留现状 = 不改任何文件），并把问题原样带进简报 —— 不许默默按「反正没人用就删」处理。
5. **不许**手改 `docs/subsystems/pool/README.md` 的生成段（`:11` 到 `:102` 之间那一段 pool-margin）与 `docs/subsystems/pool/modules.toml`（后者在 A375 域里）。
6. **不许**用文本 grep 实现判据：`speed` / `pricing` / `merged_tokens` 这三个词在 docstring、注释、别名表里都合法存在（见已知噪音第 6 条）。
7. **不许**把缺口写成「以后再说」：三个模块各自的缺席理由必须落在 ADR 的「决定」一节里，一格一句，留 TODO 视为未完成。
8. **不许**做 git 写操作：不 `add` / `commit` / `stash` / `checkout` / `branch` / `worktree`。判据 4 的变异还原**按原字节写回**（先读到内存，改，跑，写回，比 sha256），不靠 git 恢复。
9. **不许**在本卡里跑 `scripts/run_gates.py`，不许跑全量 `pytest`，不许起后台作业，不许碰仓外（D 盘 jelly_ware 下的 program/_ext 与 infra 两个目录，只读；本卡判据全部是进程内 AST 读文本，**不发网络、不起服务**）。

## 与已完成卡的关系

- **A360（`tools/pool/speed.py` 的判据本体）**：本卡不改它的任何判据，只把「零接线」从它自己 docstring 里的一句自述（`tools/pool/speed.py:27-28`）升级成跨文件的静态断言。
- **A364（外部用量上报 / MCP 写面）**：`usage_ingest` 唯一的生产 importer（`tools/pool_mcp.py:204`）就是它接的。本卡判据 2 把这条接线**钉成白名单**，等于给 A364 的接面画了个圈：MCP 面可以，派活链不行。
- **A372 / A374 / A385（`tools/pool/search.py` / `tools/pool/web_fetch.py` / `tools/pool/searcher.py` 三张判据卡，全 done）**：本卡判据 3 正是它们的**下游归属问题** —— 判据层做完了，产品面被 F59 的红线判死，那这三份实现留不留？本卡只出题。
- **A378（F59 三个自带 MCP server 按路径挂载，done）**：它判了 `web_search` / `web_fetch` = **SKIP_BY_REDLINE**（:73），但**没有**提到 `tools/pool/search.py` 与 `tools/pool/web_fetch.py` 这两个模块文件 —— 所以「三模块怎么办」到今天仍是空的，这是本卡判据 3 的来历。它落地时还留了一条教训可复用：:115 记着「全文子串不带词边界把门打红」—— 所以本卡判据一律走 AST / 名字级。
- **A390（F17 七种路由策略，done）**：它已经把「`fast` / `speed` / `speed-first` 必须永久停在判据层，不许接进派活链」（:36、:69、:217）写成了 ADR 0012 + `tests/test_pool_route_wiring.py:64`。★ **那是「路由名字」这一位，不是「模块」这一位**：`speed` 作为字符串常量出现在 `tools/wb_dispatch.py` 里会被 A390 的钉子咬，但「from pool import speed」这行 import 它一条都照不住（它扫的是 `ast.Constant`，不是 `ast.Import`）。本卡补的正是这个缺口，ADR 0013 里要写明与 0012 的分工，别让读者以为两张卡在说同一件事。
- **卡 218（`tools/pool/trae_dispatch.py` 刻意不接进派活）**：同一类先例，`docs/subsystems/pool/README.md:170` 是它的判词形状（「**无**（刻意不接进派活，卡 218 已裁定）」+ 证据列写「全仓 grep 只命中测试」）。ADR 0013 的写法可以直接借这一行的口吻。

## 诚实边界（没坐实的事，别当结论）

**坐实了的（都是本会话实跑 / 实读）**：

1. 派活侧四个文件的 AST import 集合与三个禁名**零相交**（四份的顶层模块名个数 30 / 6 / 9 / 19 实计数）。
2. `tools/` + `scripts/` 共 **178 个 py 文件**的实扫结果：`pricing` 0、`speed` 0、`usage_ingest` 恰 1（`tools/pool_mcp.py:204`）、`merged_tokens` 引用 0、无 `importlib.import_module`。
3. 既有五套判据的行号、条数与合跑读数（63 passed / 逐文件 13·17·14·12·7）都是现场实跑，不是抄来的。
4. `scripts/check_docs.py --decisions` 绿（12 条，0001..0012）、`scripts/gen_pool_readme.py --check` 绿（60 文件 / 24293 行）、`scripts/check_docs.py --mode report` 的死指针 147（+0）/ drift 560 / skip 1516 —— 三个读数都是起草这一刻跑的。
5. `docs/decisions/` 今天 13 个文件（0001…0012 + README）⇒ 0013 是空号；`docs/workbacklog.toml` 里 status 非 done 的 14 张卡与它们的 files 清单（A375 / A384 / A389 / A391 的域是 tomllib 实读，不是印象）。

**没坐实的（不许当结论）**：

6. **「speed / pricing / merged_tokens 不许接进派活链」这条规矩在仓内没有任何成文条款**。它是本会话用户反复重申的口头红线，本卡的全部工作就是「把它写下来」—— 所以判据 5 是**立**条款，不是**验**条款。任何「仓里早就有这条规矩」的说法都不成立（全仓 grep 到的 `speed` 全是测试耗时语境、路由别名、或 `tools/pool/speed.py` 这个吞吐判据模块本身）。
7. **判据 3 的答案没有**：搜索三模块该删还是该留，仓里没有任何判词（A378 只判了 MCP 上的 `web_search` / `web_fetch` 两个工具，没提这三个模块文件）。本卡把两条路的代价写清了，但**选择权在用户**。
8. **「只读面将来会消费 `merged_tokens`」这件事没有任何证据**：`tools/pool/usage_ingest.py:44` 说「那是下一张卡」，`usage_in()` 的 `include_reported` 参数今天不存在；`tools/pool/holds_wiring.py` 走的是 `usage_in`，不是 `merged_tokens`。所以判据 2 的白名单是**照今天的样子钉的**，不是照某份设计文档钉的 —— 将来真接，是改白名单那一行，不是判据失效。
9. **行号会漂**：本卡引用的行号全部以 `37a09b98` 为基准，`tools/wb_dispatch.py` 4336 行且每天在长（26 处 pool import 分散在 `:111` 到 `:4125`）。工作树从别的 HEAD 切出来，行号与「顶层模块名个数」都要重核 —— 判据里那些**计数**（30 / 6 / 9 / 19 / 178 / 63）也一样。已核：git diff --name-only 37a09b98..HEAD 对本卡引用的七个文件（四份派活侧源码 + speed / pricing / usage_ingest）输出为空 ⇒ 起草基准的行号今天仍然有效。
10. ~~没有在 .wt 工作树里验证过~~ —— **已补**：本文「本卡落地实测」一节的全部读数都在卡树里重取过；卡树的 `check_docs.py --mode report` 死指针是 150（比主树多 3，那 3 条来自 A392 规格、不是本卡），交付口径是「不新增」而非「等于 147」。

---

（起草与物化说明：本文件 2026-11-21 09:58 以草稿形态起草于 gates/diag 下（起草基准 `37a09b98`，只读勘察工人），11:12 由立卡脚本物化成 复盘/卡 下的卡规格（抬头台账号与卡号由脚本填），11:40–12:45 由实现工人在卡树 .wt/A393 里补齐「本卡落地实测」并把 `22 处 pool import` 就地改成 AST 实测的 26。四个交付文件的产品码域一个字节都没改。）
