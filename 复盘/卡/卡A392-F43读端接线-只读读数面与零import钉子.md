# 卡 A392：F43 读端接线 —— 外部上报的用量接进只读读数面，并钉住它永不进派活链

> 台账号 `T-AG683`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A392｜层 判据层（接线，不新造判据）｜基准 `37a09b98`（立卡时主树 HEAD，2026-11-21 09:50 实读）
> 依据：`docs/traceability.toml:10432` 逐字「读端零消费者：`merged_tokens()` 今天没有任何生产调用方，把上报行真正并进限额判断是下一张卡（读端接线）的活。」+ `docs/traceability.toml:11125` 逐字「- `merged_tokens(include_reported=True)` 仍**没有生产调用方** —— 谁在什么界面上看「含上报的总量」是本卡范围之外的事。」
> 前情：写入口已完成 —— 卡 A347（T-AG550）做了 `tools/pool/usage_ingest.py` 与 MCP usage_report 写工具；别名归一是卡 E97（T-AG606）；「没有价」的口径是卡 E99（T-AG608）。三张都 done，本卡只接读端。

## 0 · 与原始任务措辞的差异（必须先看）

原始缺口写的是「把上报行真正**并进限额判断**」。**本卡不这么做**，理由是长期约束：`tools/pool/speed.py`、`tools/pool/pricing.py`、`tools/pool/usage_ingest.py:623` 的 `merged_tokens()` 这三支**都不许进派活链**（派活顺序、限额判断、路线选择一律不许消费）。所以本卡把「读端接线」落成两件事：

1. **只读读数面**（`tools/pipeline_view.py` 的第七块 holds、MCP 的 workbench_board）拿到「这一窗里上报账另有多少 token、有没有价」；
2. 用一条钉子把「这一支永远不进派活链」钉死（`tools/wb_dispatch.py` 与 `tools/pool/limits_check.py` 零 import、零调用）。

`tools/pool/usage_ingest.py:629-630` 自己就写着逐字「★ **这个方法不许被限额判据调用**，调用时必须让 `include_reported` 保持默认 `False`。」—— 本卡不改这句话，只给它补上消费者与钉子。

## 1 · 缺口（实测证据，全部在 HEAD `37a09b98` 复验；行号已重核）

### A · `merged_tokens` 读什么、`include_reported` 差在哪两行

`tools/pool/usage_ingest.py:623` `def merged_tokens(model, start, end, *, root=None, include_reported: bool = False) -> int`：`:654` `base = Path(root) if root is not None else TOOL_ROOT`；`:655` `total = _dispatch_tokens(...)`；`:656` `if include_reported:`；`:657` `total += _reported_tokens(...)`；`:658` `return total`。

- `include_reported=False` 只读 wb-usage.jsonl（`:554` `_dispatch_tokens`，`:574` 逐行比 `模型` 字段）；`True` 再叠上报账（`:590` `_reported_tokens`，`:596` 路径来自 `:66` `REPORTED_REL`，`:603` 用 `:106` `REPORTED_MARK` 做字节预筛，`:612` 比 `source` 与 `model`）。**差别只有 `:656-657` 两行**，返回值单个 `int`。
- 口径：三段相加 in + out + cache_read（`:584-586` 与 `:617-619`），窗口 `[start, end)`，`+08:00` 钉死，dry 行跳过。

**实测的缺口（本卡第一件要修的事）**：模型比较是**字面**的（`:574` `if record.get("模型") != model:`、`:612` `record.get("model") != model`），而 `tools/wb_dispatch.py:1733` `usage_in` 走别名归一（`:1799` `if not _matches_model(row.get("模型"), model): continue`）。同一沙箱账本（一行 模型=glm-5.2，in 10 / out 20 / cache_read 30，窗口 2026-10-13 全天 +08:00）：

```text
glm-5.2                      merged=   60 usage_in=(60, 0.0)
GLM-5.2                      merged=    0 usage_in=(60, 0.0)   <-- 差 60
huaweicloud-maas/GLM-5.2     merged=    0 usage_in=(60, 0.0)   <-- 差 60
model_aliases("huaweicloud-maas/GLM-5.2") = ('huaweicloud-maas/GLM-5.2', 'GLM-5.2')
```

⇒ 今天谁真去调 `merged_tokens(include_reported=True)`，拿到的数会**系统性少算**。这不是新判据，是把卡 E97 在 `usage_in` 做过的归一**复用到第二处**，且只许有一份实现。

### B · 上报账今天有几行

- 仓内 gates/diag/usage-reported.jsonl **今天不存在**（`Path.exists()` False）⇒ 0 行。`.gitignore` 把 gates/diag/ 整段忽略，所以它进不了 git；读数面必须把「没有这个文件」与「有但空」当同一件事的两种说法，都不许抛。
- 对照：gates/diag/wb-usage.jsonl 270 行 / 79005 字节（实读）；gates/diag/pool-spend.jsonl 也不存在 ⇒ 0 行。
- 上报行落盘 **21 个键**（沙箱实测）：agent, cache_read, cache_write, cache_write_1h, cost, effort, err, first_text_ms, flow_ms, in, model, ms, out, provider, reasoning, rid, session, source, status, t, ttft_ms。`source` 恒 `"reported"`（`:101` `SOURCE_REPORTED`）。**没有 `account` 字段**（`:84-89` 的 `FIELDS` 里没有），`:435` `_reported_row` 还额外剥掉 caller / key / account / caller_key_id / caller_key_name 五个身份栏。
- 同一 rid 再 ingest ⇒ `accepted=0 skipped=1`、文件仍 1 行（实测），读数不变 ⇒ 去重今天已成立，本卡只钉住、不新写。

### C · `usage_in` 的调用方：它不进限额判断

`grep` 的生产命中只有一处链路：`tools/pool/holds_wiring.py:189` `numerator(...)` → `:203` `tokens, cost = fn(model, start, end, root=root)`；它的调用方是 `tools/pipeline_view.py:759` `read_holds`（面板第七块）与 `tools/wb_dispatch.py:3694`（**只打一行 [整窗] 留痕，不拒派**）。`holds_row`（`tools/pool/holds_wiring.py:223`）返回 10 个键：account / platform / model / used_percent / why / why_text / tokens / cost / priced / since；`priced` 是 `:81` 常量 `PRICED = False`。

### D · 限额链吃的是什么（⇒ 为什么上报行并进去会出问题）

`tools/pool/limits_check.py:73` `def check(limits, *, spent, now, inflight_tokens=0, inflight_cost=0.0, unpriced=None) -> Verdict`，**只吃两个映射**：`:108` `used_tokens, used_cost = spent.get(index, (0, 0.0))`；`:113` `if unpriced is not None and limit.cost > 0:`；`:129` `if not over and unknown:` ⇒ 拒（`:140` 逐字「按钱那一支判不了：第 {unknown_binding} 条」）。

两个映射的唯一生产来源是 `tools/wb_dispatch.py:3661` `spent[index] = (tokens, cost)` / `:3665` `unpriced[index] = pool_ledger_spend.unpriced(...)` → `:3667` `pool_limits_check.check(...)` ⇒ 进 problems 走 [FAIL] 退 2（**占树之前**）。账本是 gates/diag/pool-spend.jsonl，`sums()` 口径 tokens = input + output + cache_write（默认不含 cache_read），`unpriced()` 数 `priced=False` 的行。**上报行不进这本账** ⇒ 上报 tokens 今天对 `check()` 的 spent / unpriced 零影响。真要并进去只能在 `:3661-3665` 换成跨两本账求和 —— **本卡不做**。

### E · 上报行有没有价（本卡最需要钉死的语义）

- 有 `cost` 但**可选**：`:378-382` cost 缺席 ⇒ 落盘 `"cost": null`（实测）；`:388` `_cost_field` 三条判据（USD 数 / 非负 / ≤10000）。
- 没有 `priced` 标记，也不进 pool-spend.jsonl ⇒ 「这一行有没有价」今天没有任何消费者。
- ⇒ 结论：上报行不带价，它的钱就无从知道。把上报 tokens 并进限额判断一旦做错，就是让按钱那一支的 used_cost 变成**漏了上报行的下界**，再拿这个下界当「还有余量」——`limits_check.py:140` 的文案自己写着「没价的行只能当花钱的下界，拿它当「还有余量」就是沉默 ⇒ 派活之前就拒」。
- 第二条硬理由：**上报行无法按账号归属**（B 段），而限额是按账号判的（spent 的键是账号 index）。

### F · 现有相关测试（本卡改动后必须原样绿，一条都不许放宽）

| 文件 | 用例（行号按 37a09b98） | 为什么本卡要提它 |
|---|---|---|
| `tests/test_pool_usage_ingest.py` | `:409` `test_reported_rows_do_not_count_by_default`（`:416` 断 60、`:429` 断 1060、`:431` 未知模型断 0） | 本卡改别名归一后必须原样绿 |
| 同上 | `:305` `test_rid_is_skipped_on_second_post`、`:324` `test_rid_duplicate_within_one_batch_is_skipped` | 判据 2 的去重已有钉子 |
| 同上 | `:388` `_write_dispatch_usage` 夹具 | 新用例复用，不另造账本 |
| `tests/test_usage_in_alias.py` | `:104` `test_usage_in_counts_every_alias_of_the_same_model`、`:126` `test_registry_failure_falls_back_to_literal_equality`、`:152` `test_alias_table_reads_disk_only_once` | 下沉实现要保住「读不到 ⇒ 字面相等」与「只读盘一次」 |
| `tests/test_pool_limits.py` | `:497` `test_pin_22_unpriced_default_is_byte_identical`、`:506` `test_pin_23_tokens_only_limit_never_asks_for_money`、`:514` `test_pin_24_cost_limit_with_unpriced_rows_is_refused` | 限额判据一个字节都不许动 |
| `tests/test_pool_limits_wiring.py` | `:350` `test_spend_row_is_marked_unpriced`、`:371` `test_cost_limit_with_unpriced_rows_refuses_before_taking_the_tree` | 同上（接线侧护栏） |
| `tests/test_pipeline_view_holds.py` | `:106` `_block_empty_ledger`、`:123` `_rows_carry_reason`、`:158` `_missing_ledger_is_a_note_not_a_crash`、`:172` `_broken_ledger_does_not_break_the_reading`、`:186` `_cli_json_and_report_survive_both_ends` | 「缺料/坏料都不许抛」的现有钉子 |
| `tests/test_pipeline_view.py` | `:405` `test_blocks_table_declares_seven_blocks`、`:421` `test_json_rows_match_blocks_row_fields` | 块的行键集由声明表钉死 ⇒ 加列必须两处一起改 |
| `tests/test_holds_wiring.py` | `:264` `test_holds_wiring_uses_usage_in`（ast 扫源码：必须 from wb_dispatch import usage_in、不许 import wb_status、不许裸 open） | 判据 5 的零 import 钉子照它写 |
| `tests/test_pool_mcp_board.py` | `:259` `test_bad_section_is_rejected`（遍历 WORKBENCH_SECTIONS 断言都在文案里） | 给 section 白名单加 holds 后自动覆盖 |

## 2 · 判据（5 条：4 条行为 + 1 条钉子，每条都带「怎么证明」）

### 判据 1 · 统一读数在窗口内把上报行 tokens 加进来，且别名算同一条

`merged_tokens(model, start, end, include_reported=True)` 对同一个模型的三种写法（glm-5.2 / GLM-5.2 / huaweicloud-maas/GLM-5.2）返回**同一个数**，且该数 = 派活账命中 + 上报账命中；`include_reported=False` 时三种写法同样等值（= 只算派活账）。

实现要求：别名归一**只许一份**。`tools/pool/model_registry.py:649` 的 `id_names()` 是底层三档，`tools/wb_dispatch.py:1695` `model_aliases()` 是加了注册表别名组的唯一实现；本卡把它下沉成两边共用（`wb_dispatch` 侧降成薄委托，**签名与返回值逐字不变**），`usage_ingest` 侧不许抄第二份别名表。

**怎么证明**：`tests/test_pool_usage_ingest.py` 新增 `test_merged_tokens_counts_every_alias_of_the_same_model` —— 用现有 `:388` 夹具写一行 模型=glm-5.2，再用 `usage_ingest.ingest()` 落一条 model=GLM-5.2 的上报行（in 400 / out 300 / cache_read 300），断言三种写法 `include_reported=False` 全 `== 60`、`True` 全 `== 1060`；外加反向断言 `merged_tokens("kimi-k3-1", ...) == 0`（不许把别名做成「任何名字都命中」）。`tests/test_usage_in_alias.py:104` 与 `tests/test_pool_usage_ingest.py:409` 原样绿。

### 判据 2 · 同一条上报行 ingest 两次只算一次

rid 幂等（`:305` / `:324` 已成立）在**读端**也成立：同一批 body 连 ingest 两次后，`merged_tokens(..., include_reported=True)` 与只 ingest 一次逐字节相同，上报摘要也只算一次。

**怎么证明**：新增 `test_reported_summary_is_stable_after_double_ingest` —— 第一次 `ingest()` 回 `accepted=1 skipped=0`、第二次 `accepted=0 skipped=1`；文件行数仍 1（`len(reported_path(root).read_text().splitlines()) == 1`）；两次之后的 `merged_tokens(..., include_reported=True)` 相等且 `== 1060`。

### 判据 3 · 无价的上报行不许被当成 0 花费放行（搬到读数面如实标）

读数面（`tools/pipeline_view.py` 的 holds 行）必须让「这一窗有上报行、但其中至少一行没有价」**看得见**：行里新增 `reported_tokens`（int）与 `reported_priced`（True 全有价 / False 有行无价 / None 窗口里没有上报行）。**并且**：这一格不许改变派活判据 —— `tools/pool/limits_check.py` 与 `tools/wb_dispatch.py:3661-3667` 的限额闸一个字节不动，F 段那五条限额钉子原样绿。

理由写进代码注释：上报账**按账号归不了**（没有 account 字段），价又是可选的，所以它不能进 spent / unpriced；能做的是「让读的人看见这里有个下界没算进来」，而不是把它折成 0。

**怎么证明**：新增 `test_holds_row_flags_unpriced_reported_rows` —— 沙箱账本里放一条**不带 cost** 的上报行，断言 holds 行 `reported_priced is False` 且 `reported_tokens == 1000`；再放一条带 `cost: 2.5` 的行，断言同一行仍为 False（只要有一行没价就是 False）；两条都带价 ⇒ True；一条上报行都没有 ⇒ None 且 `reported_tokens == 0`。同时断言 why / why_text 与没有上报行时**逐字相同**（上报账不许改判据），以及 cost 与 priced 两列仍来自 holds_wiring（`priced` 仍是 False 常量，不许因为上报行带了价就翻成 True）。

### 判据 4 · 不加开关，且今天（上报账不存在）读数里这一格是 0 / None，不是崩溃

**本卡不加开关**（不加 `TF_POOL_REPORTED_READ` 之类的 env）。理由三条：(a) 上报账今天 0 行，加了开关也只有一种取值，等于假的选择；(b) 读数面本来就允许「缺料就说清楚」（`tests/test_pipeline_view_holds.py:158` 与 `:172` 的形状），再叠一个开关会让「有没有上报」变成两个读数；(c) 开关会把「读端到底接没接」重新变成不可判定 —— 本卡的全部价值是让它**可判定**。

代替开关的是：新列**追加**、不改 tokens / cost / priced 三列语义（tokens 仍是 `holds.estimate()` 的整窗换算，**不含**上报），并在块声明表里把新列写进 `row_fields`（`tools/pipeline_view.py:172`），让 `tests/test_pipeline_view.py:421` 的「payload 键集 == 声明表 row_fields」自己守住。

**怎么证明**：新增 `test_missing_reported_ledger_is_zero_not_a_crash` —— 沙箱里**不放** usage-reported.jsonl，`read_holds()` 不抛、每行 `reported_tokens == 0` / `reported_priced is None`；再放一个**坏文件**（半行 JSON）⇒ 同样不抛，且 `reported_tokens == 0`（读不出来就回 0，照 `merged_tokens` 既有口径「跳过或回 0，不猜、不抛」）。`tests/test_pipeline_view_holds.py:106` / `:123` / `:158` / `:172` 与 `tests/test_pool_usage_ingest.py:409` 原样绿。

### 判据 5（钉子）· 这一支永远不进派活链

`tools/wb_dispatch.py` 与 `tools/pool/limits_check.py` 里**零 import、零调用** `usage_ingest` / `merged_tokens` / 新加的 `reported_summary`；`tools/pool/holds_wiring.py` 里也零（它在 `tools/wb_dispatch.py:3694` 的派活留痕行上被调用，上报数字不许从它流出去）。

**怎么证明**：新增 `test_read_face_stays_off_the_dispatch_path`，照 `tests/test_holds_wiring.py:264` 的形状用 `ast.parse` 扫四个文件的源码：import 名单里没有 usage_ingest、`ast.Attribute` 里没有 merged_tokens / reported_summary、`ast.Call` 的 `func.attr` 里没有它们；另加一条 `assert "usage_ingest" not in src` 覆盖字符串形式的间接引用。

## 3 · 反向变异（≥4，改哪一行 / 哪个钉子红）

| # | 改哪一行 | 期望哪个钉子红 |
|---|---|---|
| 1 | `tools/pool/usage_ingest.py:574` 的 `!= model` 改回裸字面比较（或让 `_dispatch_tokens` 不走共用别名 helper） | 判据 1 的 test_merged_tokens_counts_every_alias_of_the_same_model |
| 2 | `reported_priced` 的判定改成「只要有一行带价就回 True」（或恒 True） | 判据 3 的 test_holds_row_flags_unpriced_reported_rows |
| 3 | 在 `tools/pool/limits_check.py` 顶部加一行 import merged_tokens（**哪怕不用**） | 判据 5 的 test_read_face_stays_off_the_dispatch_path |
| 4 | 让 `read_holds` 在 usage-reported.jsonl 缺失时抛异常（或直接 return None） | 判据 4 的 test_missing_reported_ledger_is_zero_not_a_crash + test_pipeline_view_holds.py:158 |
| 5 | `tools/pipeline_view.py:172` 的 row_fields 加了新列、但 `read_holds` 不真写这三列 | tests/test_pipeline_view.py:421 |
| 6 | 让 `ingest()` 的 `_known_rids` 恒空（去重失效） | 判据 2 的 test_reported_summary_is_stable_after_double_ingest + test_pool_usage_ingest.py:305 |

★ 变异脚本写主树 gates/diag/_rev_A392.py（不入库，gates/diag/ 已被 .gitignore 忽略），每条真改真跑真还原并记 sha256，末行写「结论：N/N 条全部咬住，收尾绿。」；另加一条只改注释的安静对照。

## 4 · 交付（逐文件；卡域以本节为准，台账 files 照抄）

| 文件 | 改什么 |
|---|---|
| `tools/pool/model_registry.py` | 别名归一的**唯一**实现落点：把 `tools/wb_dispatch.py:1695-1731` 的 model_aliases / _matches_model 逻辑搬成这里的公开函数（id_names 已在 `:649`，只补「注册表别名组 + 大小写不敏感 + 读盘一次」这一层），导出 `model_aliases(name) -> tuple[str, ...]` 与 `matches_model(row_name, model) -> bool` |
| `tools/wb_dispatch.py` | `:1695` `model_aliases()` 与 `:1722` `_matches_model()` 改成对上面的**薄委托**（签名、返回值、`_ALIAS_TABLE` 的「只读盘一次」与 `reset_model_aliases()` 行为逐字不变）；`:1733` `usage_in` 的签名与 `(tokens, 0.0)` 口径一字不改 |
| `tools/pool/usage_ingest.py` | `:574` 与 `:612` 的模型比较改成走同一份别名实现（注册表读不到 ⇒ 退回字面相等，与 usage_in 的 fail-open 一致）；新增公开 `reported_summary(model, start, end, *, root=None) -> tuple[int, bool or None]`；`:44-45` 与 `:629-630` 的措辞更新（「零生产调用方」改成新事实，**「不许被限额判据调用」这句保留**） |
| `tools/pipeline_view.py` | `:172` 的 row_fields 加 reported_tokens / reported_priced 两列；`:759` `read_holds` 在拿到 reading.rows 后给每行追加这两列（**只在这里调 usage_ingest**，holds_wiring 一个字不改；上报账缺失/坏掉 ⇒ 0 / None，不抛） |
| `tools/pool_mcp.py` | `:374` `WORKBENCH_SECTIONS` 加 `"holds"`（顺序照 pipeline_view 块序，放最后）；相应「六块」文案改「七块」（`:551` enum、`:2007` 白名单校验、`:2073` shown 都从常量来，改常量即可，文案逐处核） |
| `tools/dsh_panel.py` | `:127` `SECTIONS` 加 `"holds"`（同一份块序的第二处投影） |
| `tests/test_pool_usage_ingest.py` | 判据 1 / 2 的两条用例（复用 `:388` 夹具） |
| `tests/test_pipeline_view_holds.py` | 判据 3 / 4 的用例（沙箱账本 + 沙箱上报账） |
| tests/test_f43_read_face.py（新建） | 判据 5 的零 import 钉子 |
| `docs/subsystems/pool/modules.toml` | usage_ingest.py 的 duty 追加「读数面单独列出上报量（不进限额判据）」；pipeline_view.py 的 module 条目同步提两列 |
| `docs/changelog.d/T-AG683.md` | 新片段（本卡改了什么、留下的钉子） |
| `docs/traceability.d/T-AG683.toml` | 新片段，:10432 与 :11125 两条缺口在**落地时**结案（改成「读端消费者 = pipeline_view holds 块」），并注明「并进限额判断」被长期约束否决 |
| `复盘/交接.d/T-AG683.md` | 新片段 |
| `复盘/卡/卡A392-F43读端接线-只读读数面与零import钉子.md` | 本规格 |

## 5 · 验收（可直接跑）

```bash
python -X utf8 -m pytest tests/test_pool_usage_ingest.py tests/test_usage_in_alias.py \
    tests/test_pipeline_view.py tests/test_pipeline_view_holds.py \
    tests/test_pool_mcp_board.py tests/test_holds_window.py tests/test_holds_wiring.py \
    tests/test_f43_read_face.py -o addopts= -q --no-cov -p no:xdist
# 限额判据一个字节都没动（这五条必须原样绿）
python -X utf8 -m pytest tests/test_pool_limits.py tests/test_pool_limits_wiring.py -o addopts= -q --no-cov -p no:xdist
# 读数面：上报账不存在时也出得来，且两列恒 0/None
python -X utf8 tools/pipeline_view.py --report
# 零 import 钉子（落地后应零命中）
grep -n 'usage_ingest\|merged_tokens\|reported_summary' tools/wb_dispatch.py tools/pool/limits_check.py tools/pool/holds_wiring.py
```

## 6 · 不许做（6 条）

1. **不许**把上报 tokens 并进 `tools/pool/limits_check.py` 的 spent / unpriced，也**不许**把 merged_tokens / reported_summary 接进派活链（派活顺序、限额判断、路线选择一律不许消费）。`tools/wb_dispatch.py:3661-3667` 的限额闸一个字节不动。
2. **不许**改 `tools/wb_dispatch.py:1733` 的 `usage_in` 签名或返回值（别名实现只许下沉成薄委托，`(tokens, 0.0)` 口径逐字不变）；**不许**在 usage_ingest 里抄第二份别名表。
3. **不许**给 `tools/pool/holds_wiring.py` 的 holds_row 加列 —— 它在 `tools/wb_dispatch.py:3694` 的派活留痕行上被调用，加了就等于把上报数字塞进派活路径。
4. **不许**把「上报账没有价」润色成 0 花费或 0 token；没有价就写 reported_priced=False，没有行就写 None。**不许**给上报账编计价表（仓里没有权威单价，`tools/pool/holds_wiring.py:81` 的 PRICED=False 就是这条的现状）。
5. **不许**把上报行按账号摊开（今天没有归属判据：FIELDS 没有 account，_reported_row 还主动剥掉五个身份栏）。要做就另立卡，先给判据。
6. **不许**手改生成物（docs/INDEX.md、复盘/INDEX.md、docs/subsystems/pool/README.md 的 pool-margin 段），也**不许**在反引号里写不存在 / 仓外 / 计划新建的路径（`docs/doc-debt-baseline.toml` 的 dead_refs=147 只能降不能升）。

## 7 · 与已完成卡的关系

- **A347 / T-AG550**（usage_ingest + MCP usage_report）：本卡**只加读端**，写入口一个字节不改；`:44-45` 那句「本卡零接线」由本卡改写成新事实。
- **E97 / T-AG606**（model_aliases / _matches_model）：本卡把它的实现从 `tools/wb_dispatch.py` 下沉到 `tools/pool/model_registry.py`，**行为不变**，`tests/test_usage_in_alias.py` 五条钉子原样绿。
- **E99 / T-AG608**（无价行不许当花完了）：判据 3 是它在**只读面**的对应物 —— 判据层（limits_check 第 ⑥ 条）不动，只把「有下界没算进来」摆到读数上。
- **A369 / T-AG654**（holds 第七块）：本卡给它的行加两列，`holds.estimate()` 的算式与五因顺序一个字不改。

## 8 · 未坐实项（如实标注，落地前必须补齐）

1. **`tools/dsh_panel.py:127` 的第二处投影没核到底。** SECTIONS 与 `tools/pool_mcp.py:374` 是同一份块序的两处投影，只逐行读了那行常量，**没有**核面板前端/网关拿到 holds 之后怎么显示（是否另有白名单、多一块会不会崩）。落地前要么读通那条链，要么把这处改动拆成独立一步单独验。
2. **注册表读不到时的等价性只推理未实测。** `tools/wb_dispatch.py:1722-1731` 的 fail-open 分支没跑过（本机 model-registry.toml 存在）。下沉实现后必须在 usage_ingest 侧也钉一条打断读盘的用例。
3. **上报行按账号归属无判据**（B 段）。本卡只按模型 + 窗口出数，不按账号摊。
