# 卡 E116 · job_list / job_status 对「没派过的卡」和「没开始的日志」都说错话

> 台账号 `T-AG623`｜分区 E（门禁与可信度）｜树 `.wt/E116`｜层 判据层｜基准 `27780739`｜
> 依据：号池只读面撒谎体检第 5/6 条（`gates/diag/_pool_read_surface_findings.md`；真树读数由 `gates/diag/_probe_E116_*.py` 复算）。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · `card_of` 把变体后缀整段吞进卡号，`job_list` 把「历史尝试」报成「断了」

`tools/pool/jobs.py:316-319`：

```python
def card_of(log: Path) -> str:
    hit = re.match(r"^wb-(.+?)(?:\.r\d+)?\.jsonl$", log.name)
    return hit.group(1) if hit else ""
```

`tools/pool/jobs.py:325-331` 的 `classify_job_state(age, has_verdict)` 只看两件事（有判决 / 静默 480s），
再没有第三类证据可看，于是**早已作废的尝试日志**被判「断了」。真树读数：

```text
$ python -X utf8 gates/diag/_probe_E116_final2.py
SCAN 243 {'断了': 30, '已判决': 212, '非派活': 1}
```

`job_list` 逐字输出（`tools/pool_mcp.py:946-969`）：

```text
外包派活台账（job_list）—— 扫 gates/diag
共 243 个日志：已判决 212 · 断了 30 · 非派活 1
  · 卡 146.dead-20261017-164437  [断了]  wb-146.dead-20261017-164437.jsonl  696408B …
  · 卡 E14.trae  [断了]  wb-E14.trae.jsonl  261B …
  · 卡 S6.glm-掐掉的那轮  [断了]  wb-S6.glm-掐掉的那轮.jsonl  86013B …
```

「卡 146.dead-20261017-164437」根本不是卡号：卡 146 的台账号是 `T-G246`、`status=done`。

### 问题 2 · 30 条「断了」实测只有 3 条是真断

本卡写死的 canonical 判据：

- `stem` = 日志名去 `wb-` 前缀与 `.jsonl`；
- `stem` 不含点 ⇒ 归属卡 = `stem`；
- `stem` 形如 `<card>.r<N>` ⇒ 归属卡 = `card`（重跑轮，`jobs.py:311` 的 `card_artifacts` 也认这个形状）；
- 其余 ⇒ **非 canonical**。

`docs/workbacklog.toml` 实测 361 个 id，**含点号的 0 个**（样例 `'022','024','029','108','109','110','G6','G7','G8','G9'`）
⇒「canonical 名不许带变体后缀」在本仓成立，不是约定俗成。

非 canonical 实测 24 条（`_probe_E116_final2.py` 原样输出）：

```text
wb-120.killed / wb-123.claim / wb-124.claim / wb-125.amend / wb-125.reclaim / wb-125.reclaim2
wb-141.attempt1.old / wb-141.attempt2.old / wb-141.old / wb-141.r2.old
wb-143.attempt1 / wb-144.attempt1 / wb-146.dead-20261017-164437
wb-147.attempt1.old / wb-147.attempt2.old / wb-147.old / wb-147.r2.old
wb-148.attempt1.old / wb-148.attempt2.old / wb-148.old / wb-148.r2.old
wb-255.dead-20261017-164119 / wb-E14.trae / wb-S6.glm-掐掉的那轮
```

按写死的优先级重分：① 有判决 ⇒ 已判决 ② 非 canonical ⇒ 历史尝试
③ 同卡另有 `wb-<card>[.rN].jsonl` 且那份带 `.verdict.txt` ⇒ 已被取代 ④ backlog 该卡 `status=done` ⇒ 台账已完结
⑤ 其余 ⇒ 断了。

```text
BUCKETS {'断了': 3, '已判决': 212, '历史尝试': 21, '已被取代': 4, '台账已完结': 2, '非派活': 1} sum 243
断了: ['wb-002.jsonl', 'wb-045.jsonl', 'wb-A323.jsonl']
已被取代: ['wb-153.r2.jsonl', 'wb-173.r2.jsonl', 'wb-A298.jsonl', 'wb-R-1969b46.r2.jsonl']
台账已完结: ['wb-180.jsonl', 'wb-E14.jsonl']
```

21 = 24 条非 canonical 减 3 条已判决（`wb-120.killed` / `wb-143.attempt1` / `wb-144.attempt1`）。
用户口述的「21 条卡号非规范」精确对上；总账 21+3+4+2+212+1 = 243 ✔。
三张真断卡（002 / 045 / A323）**都不在 backlog** ⇒ 它们是真断，不是「没人认领」。

### 问题 3 · `job_status` 对走落地链落的卡说「还没派过」

`tools/pool_mcp.py:989-1000` 原文：

```python
    diag = diag_dir(root)
    logs = card_artifacts(diag, card, ".jsonl")
    if not logs:
        text = (
            f"没有：卡 {card} 在 {diag.as_posix()} 里没有 `wb-{card}.jsonl`"
            f"（连 r2… 也没有）—— 还没派过，或日志不在这个树里。"
        )
```

实测 `job_status('E105')` 走的正是这一支，逐字：

```text
没有：卡 E105 在 gates/diag 里没有 `wb-E105.jsonl`（连 r2… 也没有）—— 还没派过，或日志不在这个树里。
{"card":"E105","found":false,"log":null,"diag_dir":"gates/diag"}  is_error=True
```

而 E105 是 `T-AG614`、`status=done`，四项正式证据全在：`gates/diag/land-E105.log`、`docs/traceability.d/T-AG614.toml`、
`docs/changelog.d/T-AG614.md`、`gates/review/T-AG614.json`。**「还没派过」是假话**：它没被 `wb-*.jsonl` 那条路派过。

规模（`_probe_E116_final2.py`）：backlog cards 361、`status=done` 349，其中**没有** `wb-<id>[.rN].jsonl` 的 213 张。
这 213 张按「首个命中的正式证据类」计：

```text
FIRSTHIT {'land': 118, 'trace.d': 70, 'trace.toml': 8, 'changelog': 2} NONE 15
NONE list [('204','T-G311'),('207','T-G316'),('212','T-G323'),('214','T-G326'),('217','T-G330'),
 ('219','T-G333'),('220','T-G334'),('221','T-G335'),('222','T-G336'),('223','T-G337'),('224','T-G338'),
 ('226','T-G342'),('230','T-G347'),('231','T-G348'),('260','B-20261047')]
```

★ 这 15 张不是「什么都没留下」：`gates/diag` 里有 `_land_260.log` / `_land_card260.log` / `_msg_T-G260.txt`、
卡 204 有 `_int_204.patch` / `_patchTG204_mem.py`、卡 222 有 `_p16_222.patch` / `_prompt_222.md`，
卡 231 连杂项都没有。这些 `_` 前缀文件**不是正式证据**（见判据 2 的五类清单），卡里必须承认这一档。

正式证据**只有五类**，顺序写死（命中即停，按此顺序报第一个）：
① `gates/diag/land-<card>[a-z]?.log`
② `docs/traceability.d/<task>.toml`
③ `docs/changelog.d/<task>.md`
④ `gates/review/<task>.json`
⑤ `docs/traceability.toml` 的 `entries[<task>]`

★ land 正则**只许一位小写字母**，多一位都不行。实测串卡（允许卡号后跟数字时）：
`land-E1` 命中 1→29（`land-E10.log` / `land-E100.log` / `land-E101.log` …）、`E2` 1→21、`E6` 1→16、
`E7` 1→13、`E8` 0→18、`F1` 4→10、`E4` 0→4（`land-E45.log` / `land-E49.log`）、`B2` 0→2（`land-B20261051.log`）。
按严格规则实测命中 118 张；并上 `^land-<task 去横线>[a-z]?.log$` 后仍是 118（被 card 规则全覆盖）。

### 问题 4 · 两个工具都答不出「这张卡现在到底在不在飞」

`tools/pool/registry.py:22-23` 的边界原文：

```text
- ★ 本模块**不登记 pid**，判活只用「租约 + 日志」。
- ★★ **绝对不许用 `os.kill(pid, 0)` 探活**：Windows 上 CPython 的 `os.kill` 走 `TerminateProcess`
```

实测：`registry.list_reservations() == []`（今天没有活租约）；`gates/diag/pool-registry.json` 顶层是 **list**，
1 条 `{card: E105, task: T-AG614, at: 2026-11-10T07:07:37, ttl_seconds: 21600.0}`，TTL 早过 ⇒ `is_dead` 真。
`gates/diag/watch-registry.json` **不存在**（`tools/wb_watch.py:397` 才写它）；`gates/diag/wb_notify.pid` 存在；
`gates/diag/wb-*.done` 15 个。

更糟的一条：`job_status('E14')` 走通了 `wb-E14.jsonl`（330B、1 条事件、mtime 2026-10-25），
末行原文「  最后一条结果：（还没见到 result —— 可能还在跑）」—— 半年多前的死日志被说成「可能还在跑」。
该句出处 `tools/pool/jobs.py:417` 的 `render_timeline`，且是**逐字契约**
（`tests/test_pool_lib.py:255` 的 `test_wb_status_cli_and_library_agree`、`tests/test_wb_dispatch.py:2487` 锁它）
⇒ 本卡**不许改 `render_timeline`**，只能在 `job_status` 自己的那段先给一行「在飞判据」结论。

### 问题 5 · 修法本身会撞红 7 处既有断言（不许削弱，必须同时处理）

1. `tests/test_pool_lib.py:187-188` —— `rows = {r["card"]: r["state"] for r in jobs.scan_jobs(diag, now=now)}`
   后 `assert rows == {"101": "在跑", "102": "断了", "103": "已判决"}`：**正好相等**，多一个键就红。
   ⇒ 新分类在**没有 backlog 的小树**上必须仍给这三态、且 `card` 值仍是 `101/102/103`。
2. `tests/test_pool_mcp.py:389` —— `assert data["counts"] == {"在跑": 1, "断了": 1, "已判决": 1}`：
   那条钉子造的是 `101/102/103` 三份 canonical 日志的**小树**（`tmp_path`，没有 backlog、没有变体日志），
   所以 `counts` 在那棵树上**必须仍只有三个键**。⇒ 新归属类只准由「真有那份证据」产生，
   不许为了凑口径凭空多一类；也不许为了保住三键把 `state` 写死成三态（那是问题 1 本身）。
   真树上 `counts` 会多出三键（`历史尝试/已被取代/台账已完结`）—— 这是**预期**，且 `tools/wb_status.py:177`
   的 `marks` 会把它们归 `other`（今天 `other:1` 会随之变大，卡里不锁这个数字）。
3. `tests/test_pool_jobs.py:289-295` —— 「非『非派活』的行里只有 `wb-001.jsonl`」且旁账 `why` 必含「不是派活日志」
   ⇒ 历史尝试**不许**标成「非派活」。
4. `tests/test_pool_jobs.py:207-211` —— `CARDS` 含 `wb-E14.trae.jsonl`，断言 `is_card_log` 为真、`non_card_reason==""`
   ⇒ `.trae` **不许**判成非卡（但归进「历史尝试」这个归属类不红：那条判的是 `is_card_log`，不是归属类）。
5. `tests/test_pool_mcp.py:339/343-344` —— 空树 `job_status({"card":"777"})` 文本必含「没有」、`job_list` 文本必含「没有」与「假装」
   ⇒ 新文案保留「没有」二字；空树里新证据查找必须**一律落空**，不许编造。
6. `tests/test_pool_mcp.py:217-239` —— 真树逐个调九个工具，断言无新建未跟踪文件、真源哈希不变
   ⇒ 新证据查找**纯只读**，不许写缓存 / 不许建索引。
7. `tests/test_pool_mcp.py:475-480` —— `STALL_SECONDS` / `HEARTBEAT_SECONDS` 与 `wb_dispatch` 同值
   ⇒ `480` 不许动（改它等于把「断了」的阈值改软）。

8. `tools/pool/registry.py:55` 的 `_DEAD_STATES = ("断了", "已判决")` + `:200-213` 的 `_log_dead` 复用 `scan_jobs`：
   一旦 `state` 多出「已被取代 / 台账已完结」，**指向那些日志的老租约就不再被判死**（它们不在 `_DEAD_STATES` 里）。
   ⇒ 判据 1 必须同时给出一个**公开谓词**（如 `jobs.is_dead_state(state)`），`registry._DEAD_STATES` 改为引用它
   （仍是「一份真源」，不是第二份名单）。

另：`tools/wb_status.py:177` 的 `marks = {"在跑": "running", "断了": "stopped", "已判决": "verdict"}` 只认三态，
新状态名会自动落 `other`（`wb_status.py --jobs --json` 今天给 `{"total":243,"running":0,"stopped":30,"verdict":212,"other":1}`）；
`tools/dsh_panel.py:2486-2494` 的 `POOL_MARK` 同样只认三态，新名显示 `○ 历史尝试`。两处都**不红**，但卡里要说明：不要求改面板。

## 判据

### 判据 1 · 每条日志给出「归属卡 + 归属类」，五类分桶与实测人口普查一致

- `tools/pool/jobs.py` 新增一个**公开**函数（建议 `card_of_log(name) -> tuple[str, str]` 或 `resolve_card(log)`），
  返回 `(归属卡, 类别)`，类别取值**只有** `canonical` / `variant`；`card_of()` 改为复用它，
  不再把 `.claim/.reclaim2/.attempt1.old/.dead-20261017-164437/.trae` 吞进卡号。
- `scan_jobs` 每行新增两个键（**不许动既有键、不许动 `state` 的三态口径**）：
  `card`（归属卡，canonical 后）、`card_kind`（`canonical` / `variant`）。
  分类优先级写死在卡里、也写死在代码注释里：
  ① `has_verdict` ⇒ `已判决` ② `card_kind == "variant"` ⇒ `历史尝试`
  ③ 同卡另有 `wb-<card>[.rN].jsonl` 带 `.verdict.txt` ⇒ `已被取代`
  ④ backlog 该卡 `status=done` ⇒ `台账已完结` ⑤ 其余 ⇒ `断了`。
- 「非派活」仍由 `is_card_log` / `non_card_reason` 判断，**优先于**上面五类（旁账不是卡）。
- 「这个 state 算不算死」也只许一份真源：`tools/pool/jobs.py` 导出 `is_dead_state(state) -> bool`，
  `tools/pool/registry.py:55` 的 `_DEAD_STATES` 改成引用它（现在写死的 `("断了", "已判决")` 会让
  「已被取代 / 台账已完结」的老租约一直显活 —— `registry.py:210-212` 用的正是 `row["state"] in _DEAD_STATES`）。
- 钉子：`tests/test_pool_registry.py` 新增 `test_dead_states_come_from_jobs` —— 断言
  `registry._DEAD_STATES` 里的每个值 `jobs.is_dead_state(v) is True`，且 `jobs.is_dead_state("在跑") is False`、
  `is_dead_state("非派活") is False`；把「已被取代 / 台账已完结」两条加进去后，
  `tests/test_pool_registry.py:315-347` 的既有三条（verdict / stalled / live 保租约）仍必须绿。
- 钉子：`tests/test_pool_jobs.py` 新增 `test_scan_jobs_reports_card_and_kind`（合成树，覆盖五类各一条 +
  一条 `wb-usage.jsonl` 旁账），逐条断言 `(card, card_kind, state)`；再新增
  `test_variant_logs_never_take_the_card_number` —— 断言 `wb-146.dead-20261017-164437.jsonl` 的 `card=="146"`
  且 `card_kind=="variant"`，`"." not in card`。
- 钉子（真树，人口普查）：新增 `test_real_diag_census_buckets` —— 三句，**都不许用计数**（计数会随新日志漂）：
  ① 每一行的 `card` 里**没有点号**；
  ② 卡里写死的 `VARIANT_LOGS`（那 24 个文件名）里**当前还在盘的每一条**，其 `card == 名字.split('.')[0]`
     且 `card_kind == "variant"`（用 `if (diag/name).exists()` 跳过已被清理的，删文件不算本卡的事）；
  ③ 反向：`card_kind == "variant"` 的行集合，**正好等于**测试内**独立写的一份**「非 canonical」判定
     （测试自己用 `stem.split('.')` 重算，不 import 实现里的正则）算出来的集合 —— 这条堵「实现把某个
     canonical 日志误判成 variant」以及「实现漏了新出现的变体名」。

### 判据 2 · `job_status` 对「有正式证据但无 `wb-*.jsonl`」的卡说清它走的是哪条路

- 无 `wb-*.jsonl` 时，按下面写死的五类顺序查证据（`task` 从 backlog `by_id()[card].task` 取；
  卡不在 backlog 就跳过 `②③④⑤`，只查 `①` 的 `land-<card>`）。
- **台账读不到时不许抛**：实测 `wb_plan.load_sharded_backlog(<不存在的路径>)` 直接抛
  `BacklogError: backlog 文件不存在：…`（命令 `gates/diag/_probe_E116_missing.py`），
  而 `job_status` 在 `tmp_path` 小树里天天遇到这种树 ⇒ 必须 `try/except BacklogError` 当作「没有台账」
  继续走 `①`，**不许**把异常漏给调用方（`tests/test_pool_mcp.py:335-344` 就是空树场景）。
- 命中任一 ⇒ `is_error=False`，文案必须同时含：卡号、**「没有 wb-… 日志」**（保留「没有」二字）、
  「走的是落地链 / 直接提交」（按命中类别给措辞）、以及**点名证据文件路径**（`as_posix()` 相对 `root`）；
  `data` 增 `"evidence": [{"kind": "land"|"trace_d"|"changelog"|"review"|"trace_entry", "path": "..."}],
  "log": null, "found": false`（`found` 语义不变：**有没有** `wb-*.jsonl`）。
- 五类全不中但 backlog 有该卡且 `status=done` ⇒ 文案「台账写 `done`，但仓里查不到五类正式证据中的任何一类」+
  `data["evidence"] == []`，`is_error=True`（如实说没有，**不许**说「还没派过」）。
- backlog 无该卡、五类全不中 ⇒ 才允许说「还没派过」（本卡 E116 自己就是这一档：`job_status('E116')` 今天给的就是这句，实测正确）。
- 钉子：`tests/test_pool_mcp.py` 新增 `test_job_status_names_the_landing_path` —— `tmp_path` 里造
  `docs/workbacklog.toml`（照 `tests/test_wb_daily.py:49-63` 的最小形状：`[base]` + `[[cards]]`，
  卡 `X1` / `status="done"` / `task="T-X1"`）+ `gates/diag/land-X1b.log` + `gates/review/T-X1.json`，
  断言文本含「没有」「落地链」「land-X1b.log」，`data["found"] is False`、`data["evidence"][0]["kind"]=="land"`。
- 钉子：`test_job_status_survives_a_missing_backlog` —— 只造 `gates/diag/land-X1.log`、**不造** `docs/workbacklog.toml`，
  断言调用**不抛**（`BacklogError` 被吞成「没有台账」）且文本含「land-X1.log」；再对**完全空**的 `tmp_path`
  断言文本含「没有」（保住 `tests/test_pool_mcp.py:339` 那条既有钉子）。
- 钉子：`test_job_status_says_no_formal_artifacts` —— 同树但 `status="done"` 且五类产物一个不留，
  断言文本含「没有」且**不含**「还没派过」。
- 钉子：`test_job_status_land_glob_does_not_cross_cards` —— 造 `land-X10.log` / `land-X100.log`，
  查卡 `X1` 时 `data["evidence"]` 里**不许**出现它们（写死「只许一位小写字母」这条）。

### 判据 3 · 两个工具都能回答「在不在飞」，且答案只由三个确定性来源决定

- 新增 `tools/pool/jobs.py: in_flight(diag, card, now=None) -> tuple[bool, str]`（或 `flight_state`），三源按序：
  ① 活租约：`registry.list_reservations(now)` 里有该卡 ⇒ `(True, "有活租约 …")`；
  ② 判决：`card_artifacts(diag, card, ".verdict.txt")` 非空 ⇒ `(False, "有判决 …")`；
  ③ 日志 mtime：最新一份 `wb-<card>[.rN].jsonl` 的 `age <= STALL_SECONDS(480)` ⇒ `(True, "日志 mtime 距今 Ns ≤ 480s")`，
     否则 `(False, "日志已静默 Ns > 480s，且没有活租约")`。
- **不许** `os.kill` / `tasklist` 探活；**不许**把 `watch-registry.json` 当唯一来源（实测不存在）；
  租约与日志冲突（老日志 + 活租约）⇒ 判「在飞」但 `why` 必须写出冲突原文。
- `job_status` 输出**第一行**必须是 `在飞：是 / 在飞：否 —— <why>`（放在 `render_timeline` 那一段**之前**，
  不碰 `jobs.py:417`）；`data` 增 `"in_flight": bool, "in_flight_why": str`。
- `job_list` 每行末尾追加 `｜在飞：是/否`（`data["jobs"][i]` 加 `in_flight`）。
- 钉子：`tests/test_pool_jobs.py` 新增 `test_in_flight_has_three_sources_and_no_pid` —— 四个子场景
  （活租约 / 有判决 / 新日志 / 老日志无租约）逐一断言 `(bool, why 关键词)`；再用 **ast 走代码**断言
  模块里没有 `attr == "kill"` 的调用、没有 `tasklist` 字面量 —— 照 `tests/test_pool_registry.py:353-360`
  的写法（那里明确「看代码里有没有 `.kill(` 这个调用，不看文档字符串 —— 那里正好在讲这条禁令」）。
  ★ 不许用 `"os.kill" not in getsource` 这种写法：文档字符串里要讲这条禁令，一写就红。
- 钉子：`tests/test_pool_mcp.py` 新增 `test_job_status_first_line_says_in_flight` —— 头一行匹配 `^在飞：(是|否)`，
  且 `data["in_flight"]` 是 `bool`（不是 `None`）。

### 判据 4 · 归类真源只有一份，四个读者不许各写各的

- `tools/pool/jobs.py` 是唯一真源；`tools/wb_dispatch.py:1452` 的第二份 `_card_of`、`tools/wb_retention.py:115` 的
  `_CARD_RE = re.compile(r"wb-(\d+)")` **本卡不许扩写**（`wb_dispatch.py` 一行都不改，避免撞它 4000+ 行钉子）。
- 新归类**不许**在 `tools/wb_dash.py` / `tools/wb_retention.py` / `scripts/gen_pool_readme.py` 里出现第二份名单
  （这三个读者继续只调 `is_card_log`，`tests/test_pool_jobs.py:168-194` 已经在钉这件事）。
- 钉子：`tests/test_pool_jobs.py` 新增 `test_card_resolution_has_one_definition` —— 用 ast 取三个读者
  （`tools/wb_dash.py` / `tools/wb_retention.py` / `scripts/gen_pool_readme.py`）**代码里**的字符串常量，
  断言其中没有 `dead-` / `attempt` / `claim` / `reclaim` / `.old` 这些变体后缀（注释与文档字符串不算），
  且三个读者都必须出现 `is_card_log`；`tools/pool/jobs.py` 里变体后缀字面量**只许出现在一个函数体内**
  （按含这些字面量的函数个数断言 == 1）。

### 判据 5 · 反向变异 ≥4（真改、真跑、真还原，记 sha256）

- A：把 `card_of` 改回原正则（吞后缀）⇒ 判据 1 的 `test_variant_logs_never_take_the_card_number` 与真树人口普查必红；
- B：把 `.trae` 加进 `NON_CARD_LOG_RE`（当成旁账）⇒ `tests/test_pool_jobs.py:207-211` 必红；
- C：把 `job_status` 的「没有」二字删掉（或退回原「还没派过」文案）⇒ `tests/test_pool_mcp.py:339` 与判据 2 两条钉子必红；
- D：让 `in_flight` 去 `os.kill` 探活（或直接 `return True`）⇒ 判据 3 的 `test_in_flight_has_three_sources_and_no_pid` 必红；
- E：把 `land` 规则放宽成允许数字 ⇒ 判据 2 的 `test_job_status_land_glob_does_not_cross_cards` 必红；
- C1（安静对照）：只改一句注释 ⇒ 三条验收全绿。
- 记录落 `gates/diag/_rev_E116_result.txt`（含变异前后的 sha256 与 pytest 尾行）。

## 交付

1. `tools/pool/jobs.py`：`card_of` 重写 + 新增 `card_kind` 解析、`in_flight`、`is_dead_state`（真源只此一份）；`scan_jobs` 加 `card_kind` / `in_flight` 键；`tools/pool/registry.py:55` 的 `_DEAD_STATES` 改为引用 `jobs.is_dead_state`；**不动** `STALL_SECONDS`、**不动** `render_timeline`。
2. `tools/pool_mcp.py`：`tool_job_status` 的无日志分支改成「五类正式证据 first-hit + 在飞结论」；`tool_job_list` 每行加 `在飞`、`data` 加 `in_flight`；`counts` 口径不变。
3. `tests/test_pool_jobs.py`：判据 1（3 条）+ 判据 3（1 条）+ 判据 4（1 条）新钉子；`tests/test_pool_registry.py`：`test_dead_states_come_from_jobs`（1 条）。
4. `tests/test_pool_mcp.py`：判据 2（3 条）+ 判据 3（1 条）新钉子。
5. `gates/diag/_rev_E116.py` + `gates/diag/_rev_E116_result.txt`（变异读数）。

## 验收（落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pool_jobs.py tests/test_pool_mcp.py tests/test_pool_lib.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool/jobs.py tools/pool_mcp.py tests/test_pool_jobs.py tests/test_pool_mcp.py
python -X utf8 tools/wb_status.py --jobs --json
```

## 不许做

- 不许改 `tools/wb_land.py` / `tools/pool/landing.py`（落地链不是本卡的问题面）；
- 不许改 `tools/wb_dispatch.py`（它有第二份 `_card_of`，本卡只把它写进「已知重复」，不许伸手）；
- 不许删 / 改名 / 移动任何历史日志（`.old` / `.attempt*` / `.dead-*` / `.claim` / `.trae` 都是取证材料）；
- 不许把「断了」直接改成 0 或改名来消红（`tests/test_pool_mcp.py:389` 会立刻红；且那等于把判据改软）；
- 不许改 `STALL_SECONDS` / `HEARTBEAT_SECONDS`（`tests/test_pool_mcp.py:475` 锁它与 `wb_dispatch` 同值）；
- 不许改 `tools/pool/jobs.py:417` 的 `render_timeline`（逐字契约：`tests/test_pool_lib.py:255`、`tests/test_wb_dispatch.py:2487`）；
- 不许削 `tests/test_pool_jobs.py` / `tests/test_pool_mcp.py` / `tests/test_pool_lib.py` 的既有断言；
- 不许在证据查找里写缓存 / 建索引 / 落任何文件（`tests/test_pool_mcp.py:217-239` 真树查未跟踪文件）；
- 不许用 `os.kill` / `tasklist` 判活（`tools/pool/registry.py:22-23` 的边界），也不许把 pid 当唯一证据。
