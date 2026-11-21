# 0013 speed / pricing / usage_ingest.merged_tokens 永不进派活链：保留为库，钉零消费者

Status: Accepted
Date: 2026-11-21
Supersedes:
Superseded-by:
来源: 卡 A393（台账号 T-AG684）· 规格 `复盘/卡/卡A393-nopin三模块不进派活链成文条款与静态钉子.md` · magpie 移植功能清单 F17 / F56 / F59

## 背景与问题

仓里有三个模块，**有模块、零生产消费者**，而且它们三个恰好都长在「派活链」的门口：

- `tools/pool/speed.py`（261 行）回答的是「什么情况不许报速度」。pool 今天不产 ttft /
  first_text / flow 这三列，接进排序器只能接**编出来的**速度。
- `tools/pool/pricing.py`（231 行）没有价目表，`Price` 一律由调用方构造；而活账的金额恒
  0.0（仓里没有计价表）。`tools/pool/ledger_spend.py` 的注释逐字写着「本模块仍然不算钱
  （算术在 pricing.py，**两边互不调用**）」。
- `tools/pool/usage_ingest.py` 的 `merged_tokens()` 是**读端合并器**，今天零生产调用方；
  活账的分子走的是 `wb_dispatch.usage_in()`（经 `tools/pool/holds_wiring.py` 的函数级
  import）。

这三条「不许接」的约束今天只活在**口头与注释**里：用户会话里反复重申，模块 docstring 里
写一句，`docs/subsystems/pool/modules.toml` 的 cli 字段写一句。没有任何一条是**机器判据**。
后果是具体的：谁明天在 `tools/wb_dispatch.py` 顶部加一行 `from pool import speed`，
`pytest` 会全绿、`ruff` 会全绿、`scripts/run_gates.py` 会全绿 —— 红线在代码里**看不见**。

本记录要回答的就一个问题：**「这三个模块不进派活链」是判据还是洁癖？** 答：是判据。
接进去只能接假数，而假数正是本记录要消灭的东西。

## 候选方案

**甲：把它们接进派活链（否决）。** 支持者可以说「模块都写好了，不接白不接」。否决理由不是
品味，是**数**：speed 要的 ttft / first_text / flow 三列 pool 不产 ⇒ 排序器只能按编出来的数
排序；pricing 没有价目表 ⇒ 金额只能编；`merged_tokens` 与 `usage_in` 是**两个口径**，同时
接会让活账的分子出现两个真源。三条都是「接进去之后读数不再可信」，与「节约」无关。

**乙：删掉（判据 3 的 3B 支，本次不采纳）。** 三个模块合计 1461 行产品码 + 1256 行判据，
删掉它们能少一份维护面。但这是**不可逆动作**，代价清单如下（逐条来自仓内实读）：

1. 产品码 1461 行 = `tools/pool/search.py` 258 行 + `tools/pool/searcher.py` 508 行 +
   `tools/pool/web_fetch.py` 695 行 —— 这三个才是 3A 要保留、3B 要删的那一组（`speed.py`
   261 行与 `pricing.py` 231 行属于判据 1 的面，不在 3B 的删除清单里）；判据 1256 行同批消失。
2. `docs/subsystems/pool/modules.toml` 的 :305 / :309 / :319 三块（`web_fetch.py` /
   `search.py` / `searcher.py`）必须同批删 —— 否则 `scripts/gen_pool_readme.py:160-171` 的
   两向对账会当场报「清单写了 X，但目录里没有这个文件 —— 清单自己成了死指针」。
3. `docs/subsystems/pool/README.md` 的生成段（`scripts/gen_pool_readme.py` 产）会跟着变，
   而那份文档被卡 A375 / A391 认领 ⇒ 走 3B 就**必须**写 `depends A375`，本卡「零相交」的
   前提当场作废。

**丙（采纳）：3A —— 保留为库，只把「零消费者」钉成静态判据。** 一行代码都不删，把
「今天没人接」与「以后也不许接」分开：前者是事实（钉住，红了就说明有人接了），后者是
决定（本记录）。要删另开卡，届时 3B 的代价表就在上面，不用重新勘察。

## 决定

**一、三个模块不进派活链，一个字都不许接。** 具体点名：

| 模块 | 派活链上的位置 | 今天的缺席理由（一格一句） |
|---|---|---|
| `tools/pool/speed.py` | 排序 / 路线选择的**输入** | pool 不产 ttft / first_text / flow 三列，接进去只能按编出来的速度排序。 |
| `tools/pool/pricing.py` | 限额判断的**金额** | 仓里没有计价表，金额恒 0.0；`ledger_spend` 与本模块的注释互写「两边互不调用」。 |
| `tools/pool/usage_ingest.py` 的 `merged_tokens()` | 活账的**分子** | 分子只许有一个真源，今天走 `wb_dispatch.usage_in()`；读端合并器是另一个口径。 |

**二、派活侧四个文件是这条禁令的判定面**：`tools/wb_dispatch.py`、
`tools/pool/limits_check.py`、`tools/pool/route.py`、`tools/pool/gateway.py`。它们的
`ast.Import` / `ast.ImportFrom` 末段与四个禁名（speed / pricing / usage_ingest /
merged_tokens）**零相交**；名字级还要再钉两个禁名：`merged_tokens` 与 `reported_summary`
（前者是读端合并器的入口，后者是上报批次的汇总口径 —— 两个都只许留在读端）。
判据落在 `tests/test_pool_nopin.py`：接进派活链 = 违反本 ADR，钉子红。

**三、`usage_ingest` 的 importer 白名单只有两个**：`tools/pool_mcp.py`（MCP 写面，卡 A364）
与 `tools/pipeline_view.py`（只读读数面，卡 A392 / F43）。第三个消费者出现之前，先改本记录
与白名单，别偷偷加 import。★ 今天是「白名单的子集 + 必含 `tools/pool_mcp.py`」，不是字面上
的**相等**：`tools/pipeline_view.py` 是卡 A392 的产物，A392 落之前它还不 import；A392 落地后
两项都在集合里，断言**自动等价于相等**。在那之前按相等写会红，而红的原因是「隔壁卡还没落」，
不是本卡的红 —— 这一点写在这里，是为了让下一个人知道该动哪一行。

**四、与 0012 的分工（两份记录钉的不是同一位）。**
`docs/decisions/0012-route-strategies-wiring.md` 钉的是**名字**：七种路由策略的别名只许
存在于判据层，它的钉子扫 `ast.Constant` 字符串常量（`"speed"` 作为 FASTEST 的别名）。
本记录钉的是**模块**：`ast.Import` / `ast.ImportFrom` 的模块名。两者互不覆盖 —— 把别名
改成 import 不会触发 0012 的钉子，把模块名写成字符串也不会触发本记录。所以两份都要有。

**五、判据 3 支路定案 = 3A（保留为库）。** 三个搜索模块 `tools/pool/search.py`、
`tools/pool/searcher.py`、`tools/pool/web_fetch.py` 的名字在 `tools/` + `scripts/` 的
import 集合里**恒为空集**；一行代码都不删。它们「永远不会有消费者」有判词可依（magpie F59
的 web_search / web_fetch 已判 SKIP_BY_REDLINE，红线是「数据不出本地」），但「没有消费者」
不等于「该删」—— 见候选方案乙的代价表。

**六、正对照（别把判据写成「谁都不许提这四个字」）。** 四个禁名在仓里**合法地**出现很多次：
`tools/pool/route.py` 的别名元组里 `"speed"` 是路由名字，`tools/pool/speed.py` 的 docstring
提到 magpie 的同名文件，`tools/pool/usage_ingest.py` 自己的注释里就写着 `merged_tokens`。
所以判据一律只认 AST 节点（`ast.Import` / `ast.ImportFrom` / `ast.Name` / `ast.Attribute`），
不做文本 grep；同时保留一条**正对照**：`tools/pool/holds_wiring.py` 的 `_usage_in()` 必须
仍然 `from wb_dispatch import usage_in` —— 断了说明分子被换掉，那比多接一个 import 更糟。

## 把握程度

high —— 因为是**实扫**出来的数，不是读注释读出来的：`tools/` + `scripts/` 178 个 `.py` 文件
AST 实扫，speed / pricing / search / searcher / web_fetch / merged_tokens 的 importer 各 0 条，
usage_ingest 恰 1 条（`tools/pool_mcp.py`）。四个派活侧文件的 import 末段与四个禁名零相交，
顶层模块名合计 64 个（前提自证要求 ≥ 60）。

medium —— 「白名单是相等还是包含」这一位今天只能钉子集：`tools/pipeline_view.py` 要等卡 A392
落地才成为第二个 importer。等 A392 落了，`tests/test_pool_nopin.py` 里那条断言从「子集 +
必含」升成「相等」是一行改动，但**必须有人去改**，否则这条判据会停在比卡规格更松的位置上。

low —— 「三个模块将来会不会真的被需要」。本记录只钉「不许接进派活链」，没有判断它们的
长期价值；要删（3B）另开卡，代价表在「候选方案」乙里。
