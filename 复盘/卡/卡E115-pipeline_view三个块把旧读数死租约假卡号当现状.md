# 卡 E115 · pipeline_view 的三个块把旧读数 / 死租约 / 假卡号当现状

> 台账号 `T-AG626`｜分区 E（门禁与可信度）｜树 `.wt/E115`｜层 判据层｜基准 `71764d16`（立卡时主树 HEAD）｜depends 无
> 依据：用户 m00001「pipeline_view 的三个块把旧读数/死租约/假卡号当现状」。
> 归属划分：本卡只动 `tools/pipeline_view.py` 的读侧三块（gates / leases / verdicts）与它的两个出口（`--json` / `--report`）。
> `workbench_bridge` / `wb_daily` / `pool_mcp` 的**措辞**不在本卡（见文末「已知残留」）。

## 背景（逐条实测，不是推测）

### 问题 1 · gates 块把「上一次门禁」念成「最近一次」，既不说是多近、也不说落后几个提交

`tools/pipeline_view.py:403` 只把三个键搬出去：

```python
payload = {"ok": data.get("ok"), "rev": data.get("rev"), "items": items}
```

而 `gates/last.json` 里本来就有 `at` / `dirty` / `branch`（生产者 `scripts/run_gates.py:2778-2781` 写
`parent` / `branch` / `dirty` / `at` 四个字段）。声明表 `tools/pipeline_view.py:104-107` 的 `row_fields`
也只有 `("ok", "rev", "items")`，报告 `tools/pipeline_view.py:674-675` 只念 `rev=… ok=… 共 N 道`。

2026-11-16 20:22 实测：

```text
$ python -X utf8 tools/pipeline_view.py --report | grep '^\[gates\]'
[gates] 最近一次门禁（来源 gates/last.json）：rev=0d28b544 ok=True  共 23 道：
$ python -X utf8 -c "import json;d=json.load(open('gates/last.json'));print(d['at'],d['branch'],d['dirty'])"
2026-11-16T18:02:45 card/E116 True
$ python -X utf8 -c "…import pipeline_view; print(sorted(pipeline_view.read_gates(ROOT)['gates']))"
read_gates payload keys= ['items', 'ok', 'rev']
```

关键不是「缺字段」，是**旧读数与新鲜读数在报告里长得一模一样**：同一台机器上门禁一跑就重写 `gates/last.json`，
而报告首行除了 `rev` 与道数，读者看不出哪一份是几小时前、哪一个落后主树几个提交。
`--json` 里同样没有 `at`。

### 问题 2 · 租约块把 registry 早就判死的 E105 念成「谁在飞：1 条活租约」

`tools/pipeline_view.py:489-496` 逐行搬六个字段，**一次也不问 `is_dead`**；而真源
`tools/pool/registry.py:250-255` 的 `list_reservations` 是
`[row for row in load(target) if not is_dead(row, stamp, log_base=log_base)]`，
`is_dead` 在 `tools/pool/registry.py:219-225`（**TTL 过期 或 日志判死，两个都要问**），
`_DEAD_STATES = jobs.DEAD_STATES`（`tools/pool/registry.py:58`），
`tools/pool/jobs.py:365` 是五态 `("断了", "已判决", "已被取代", "台账已完结", "历史尝试")`。

2026-11-16 20:22 实测：

```text
$ python -X utf8 tools/pipeline_view.py --report | grep -A1 '^\[leases\]'
[leases] 租约（来源 gates/diag/pool-registry.json）：共 1 条：
  · card=E105  tree=.wt/E105  owner=DEV-HOST:32456  at=2026-11-10T07:07:37  ttl=21600.0s
$ python -X utf8 -c "…registry.list_reservations(path=…); registry.load(…); registry.is_dead(row, time.time(), log_base=lambda: ROOT)"
registry.list_reservations n= 0
is_dead with log_base=lambda:root -> True
```

`at=2026-11-10T07:07:37` + `ttl=21600.0`（6 小时）⇒ 2026-11-10 13:07 就该死了；20:22 量得已过期 **151.2 小时**。
死因**只有 TTL 这一支**（那条 `log_path` 是绝对路径且文件已不存在，`_log_dead` 回 False）。同机同刻两个读数打架：
块里 1 条，registry 0 条。

### 问题 3 · 判决块把 `120` 与 `120.killed` 摆成两行「都有判决」，读者判不出哪次是现状

`tools/pipeline_view.py:86-87` 只认 `.r\d+` 这一种后缀：

```python
_VERDICT_RE = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.verdict\.txt$")
_REPORT_RE  = re.compile(r"^wb-(.+?)(?:\.r\d+)?\.report\.md$")
```

于是 `.killed` / `.attempt1` 被当成**卡号的一部分**（`tools/pipeline_view.py:438` `cid = m.group(1)`）：

```text
$ python -X utf8 tools/pipeline_view.py --report | grep -E '^  · (120|143)'
  · 120: 有判决、有摘要  首行：card=120 第=1 次 … 结束于=2026-10-02T19:08:56
  · 120.killed: 有判决、有摘要  首行：card=120 结束于=2026-10-02T18:28:37
  · 143: 有判决、有摘要  首行：card=143 第=1 次 … 结束于=2026-10-02T20:06:58
  · 143.attempt1: 有判决、有摘要  首行：card=143 结束于=2026-10-02T20:05:52
```

按新正则独立重算（2026-11-16 20:22，不依赖任何临时探针脚本）：匹配 **459** 个产物文件 /
distinct card **212** / (card, att) **233** / 归一后含点的 card **0** 个。两个更糟的事实：

- `120.killed`（18:28:37）比 `120`（19:08:56）**更早** ⇒「按文件名字典序」与「按结束时间」给出**相反**答案，
  所以规范化规则不能靠排序，只能靠首行 `结束于=` 现算（实测 `.verdict.txt` 232 份，首行缺时间戳的 0 份）。
- `143` / `144` 的 `.r2` 那一次**根本没出现在行里**：`_read_verdicts` 的 `found[cid]` 被同键后写覆盖
  （`tools/pipeline_view.py:439` / `:447`）。`143` 行取到的是基名 20:06:58 那次，`r2`（20:15:10，**最新**）被丢了。

## 判据

### 判据 1 · `--report` 的 `[gates]` 段必须念出「多少小时前」与「落后几个提交」，两个数都是现算的

- 断言：夹具假仓的 `gates/last.json` 里 `at` = 跑测试那一刻减 5h30m、`rev` = 假仓**第 1 笔**提交（HEAD 是第 2 笔）。
  跑 `--report`，`[gates]` 首行必须同时匹配 `(\d+(?:\.\d+)?)\s*小时前`（值 ∈ [4.9, 6.1]）与
  `落后\s*(\d+)\s*个提交`（值 == 1）；`--json` 的 `gates` 块必须带 `at` / `dirty` / `branch` 三键，
  且逐字等于 `gates/last.json` 里的原值。
- 什么情况下红：`_report_gates`（`:674-675`）改回只念 `rev=/ok=/` ⇒ 第一条匹配不到 ⇒ 红；只把字段抄进
  `--json` 而人话段不念 ⇒ 红；把 `at` 原值抄进报告但不现算 ⇒ 小时数匹配不到 ⇒ 红。
- 口径（写死）：**小时数与落后提交数只许出现在 `--report`**，`--json` 里一个都不许有。理由：
  `tests/test_pipeline_view.py:443` 断言 `"stale_for_s" not in _json_bytes(r2)`、`:630` 断言冷热两次
  `--json` 逐字节相同 —— 墙钟进 JSON 必红。本判据的绿**只**由 `--report` 判；`--json` 只判「三键静态值到位」
  （这条口径必须写进钉子注释，否则拿 JSON 字段冒充「念出来了」会假绿）。
- 钉子：`tests/test_pipeline_view.py` 新增 `test_report_gates_says_age_and_commits_behind`。
- 失败分支：`git rev-list --count <rev>..HEAD` 对认不出的 rev 是非零退出（实测 `deadbee..HEAD` ⇒ rc 128 /
  `fatal: ambiguous argument 'deadbee..HEAD': unknown revision or path not in the working tree.`）。
  夹具 `_write_gates_last`（`:66-71`）默认 `rev="deadbee"`，所以报告必须回「认不出 rev=deadbee」而不是抛异常
  （否则 `:479-493` 与 `:656` 直接崩）。

### 判据 2 · 死租约必须在块里显式标 `dead`，不许过滤掉，也不许另写一份判据

- 口径（**定死标记，不过滤**）：`leases` 每行加 `dead: bool`，**行数不变**；`--report` 的 `[leases]` 段
  念出「其中 M 条已死」。三条理由写进代码注释：① 过滤会抹掉「这里曾有人占过树」这条证据，与模块自述
  `tools/pipeline_view.py:37-38`「缺什么说什么」冲突；② 过滤会让 `tests/test_pipeline_view.py:151-160`
  （`len(r["leases"]) == 1`）与 `tests/test_workbench_bridge.py:134-163` 三处域冲突夹具全部改口径 ——
  本卡是改读数，不是改夹具；③ 落盘清死租约是 `tools/pool/registry.py:258-268` `prune()` 的职责，
  读侧偷偷清等于造第二个真源。
- 断言：夹具写两条 —— 一条 TTL 过期（`at` = now - 7h、`ttl_seconds=21600`），一条活的（`at` = now - 1h）。
  `--json` 里两行都在，死的 `dead is True`、活的 `dead is False`；`--report` 段内含 `其中 1 条已死`。
  判死必须调 `pool.registry.is_dead(row, now, log_base=lambda: root)` —— `now` 是 **epoch 秒 float**，
  且 `log_base` 必须显式给（`_log_base_for` 在 `tools/pool/registry.py:228`，用 `Path(__file__)` 推仓库根，
  **不看传进来的 root**；`tmp_path` 假仓里不给 `log_base` 就会去真仓库找日志）。
- 什么情况下红：把死的过滤掉（行数变 1）⇒ 红；`dead` 写死 `False` ⇒ 红；自己写一份
  `(now - started) > ttl` 而不调 `is_dead` ⇒ 用「`ttl_seconds=10**9` 但日志已判死」的夹具必红（那一支只有 `_log_dead` 能判）。
- 钉子：新增 `test_leases_mark_dead_without_dropping`（两支：TTL 过期 / 仅日志判死）与 `test_report_leases_counts_dead`。

### 判据 3 · 判决块必须一卡一行 + `attempts`，`120` 与 `120.killed` 不许并列成两行

- 规范化规则（写死）：
  - 正则：`^wb-(?P<card>[^./]+?)(?:\.(?P<att>r\d+|killed|attempt\d+))?\.(?:verdict\.txt|report\.md)$`
  - `card` = 不含 `.` 的那一段（实测真目录 212 个 card，无一含点）；`att` = 后缀标签，无后缀记 `""`（第 1 轮），
    `.rN` ⇒ `"rN"`，`.killed` ⇒ `"killed"`，`.attemptN` ⇒ `"attemptN"`（**保留原字面**，不许改写成 `rN` —— 改名 = 改证据）。
  - 一行一卡；行里新增 `attempts: [{att, has_verdict, has_report, ended_at, selected}]`。
  - `selected`（哪一次是现状）= 该卡所有**能解析出 `结束于=`** 的 attempts 中 `ended_at` **最大**那个；
    并列时按 `att` 字典序取后者（确定性）。**不许按文件名字典序**（`120.killed` 更早，见问题 3）。
  - 回落（草稿没写、必须写死）：**一个都解析不出 `结束于=` 时**，`selected` = 该卡唯一那个无后缀（`att == ""`）
    attempt；连无后缀都没有才取 `min(att)`。理由：真目录里已有 `wb-260.report.md` 这种只有摘要、没有 `结束于=`
    的产物；夹具 `:144-149` / `:250` 的判决首行也不带时间戳，不回落就会把既有断言打红。
  - 四个既有字段语义不变、名字不改：`card` / `has_verdict` / `has_report` / `verdict_first_line`
    （`verdict_first_line` = `selected` 那一次的判决首行）。改名的爆炸半径：
    `tools/workbench_bridge.py:154`、`tools/timeflow_inbox.py:179-192`、`tools/pipeline_view.py:710-718`。
- 断言：夹具写 `wb-007.verdict.txt`（`结束于=2026-10-02T20:00:00`）与 `wb-007.r2.verdict.txt`
  （`结束于=2026-10-02T19:00:00`）⇒ `len(r["verdicts"]) == 1`、`card == "007"`、`len(attempts) == 2`、
  `selected == ""`（基名更晚）。再写 `wb-120.verdict.txt` + `wb-120.killed.verdict.txt` ⇒ 仍只有一行 `120`，
  `{a["att"] for a in attempts} == {"", "killed"}`。
- 什么情况下红：`.killed` / `.attemptN` 仍落进 `card`（今天的样子）⇒ 第二行 ⇒ 红；`selected` 改成
  `sorted(attempts)[-1]` ⇒ 第一个夹具的 `selected` 变 `"r2"` ⇒ 红；`card` 里出现 `.` ⇒ 红。
- 另一条不变量（钉子要含）：`len({row["card"] for row in r["verdicts"]}) == len(r["verdicts"])`。
- 口径提醒：`len(verdicts)` 从 215（今天的「茎数」）变成 **212**（卡数）是**本卡预期**，不是回归。
- 钉子：新增 `test_verdicts_one_row_per_card_with_attempts` 与 `test_verdicts_selected_is_latest_by_ended_at`。

### 判据 4 · 反向变异 ≥4（真改、真跑、真还原，记 sha256）

- A：`_report_gates` 首行改回 `rev=… ok=… 共 N 道` ⇒ 判据 1 的钉子必红；
- B：`_read_leases` 里的 `dead` 改成恒 `False` ⇒ 判据 2 的钉子必红；
- C：`_VERDICT_RE` / `_REPORT_RE` 改回 `^wb-(.+?)(?:\.r\d+)?\.…` ⇒ 判据 3 的钉子必红；
- D：`selected` 从「最大 `ended_at`」改成「`sorted(att)` 里最后一个」⇒ 判据 3 第二个钉子必红；
- C1（安静对照）：只改一句注释 ⇒ 全绿。
- 记录落 `gates/diag/_rev_E115_result.txt`（每条带改前/改后的 `sha256` 与那一次 pytest 的退出码）。

### 判据 5 · 不许削弱 / 不许顺手改

- `tools/pool/registry.py` 的 `is_dead` / `list_reservations` / `prune` **一行都不改**（只许调用；
  `tools/pool/guards.py:355-358` 明写「在这里重判一遍 = 造第二份『死租约』真源」，读侧同理）；
- `tools/pipeline_view.py` 的 `_continuous_out`（`:185-196`）/ `_cacheable`（`:264-270`）/
  `_cached`（`:273-295`）/ last-good 三分支不许改；
- `--json` 里不许出现任何墙钟派生值（`age_hours` / `stale_for_s` / 「落后 N 个提交」）；
- `tests/test_pipeline_view.py:202-214`（`r["leases"] == []` 是合法空表）、`:416-451` / `:454-476`（last-good）、
  `:479-493`（报告头「（来源 X）」）、`:622-632`（冷热逐字节）、`:357-368`（声明表六块与 continuous 分界）一条都不许改；
- `tests/test_wb_daily.py:193`、`tests/test_workbench_bridge.py:122` / `:127`、`tests/test_pool_mcp_board.py:190-229`
  不许改（本卡不动这三个消费者的措辞与投影）；
- **唯一允许改的既有断言**：`tests/test_pipeline_view.py:656`（`assert "[git] 本次调用 2 次" in report`）里的
  `2` → `3`。★ `tests/test_pipeline_view.py:646`（`assert pipeline_view._GIT_CALLS == 2`）**必须保持 2** ——
  它咬的是 `build_reading`，而 `rev-list` 落在 `_report_gates`（只有 `--report` 走），实测 `pv._report()`
  本身不调 git。同时必须给 `tools/pipeline_view.py:770-774` 的 `_GIT_SHAPES` 补 `3:` 档描述
  （否则 `:785` 会打「（未登记的调用形状）」）。理由：`git rev-list --count` 必须走 `_run_git`
  （`tools/pipeline_view.py:311-319` 是唯一的 `_GIT_CALLS += 1` 点，绕过它 = 让 `[git] 本次调用 N 次` 这笔账说谎），
  这条断言咬的正是「不许悄悄加 git 调用」，本卡是一次**明确批准**的例外。
- **必须改的常量（草稿漏了，不改就打脸验收第 3 条）**：`tools/pipeline_view.py:82` 的
  `_CACHE_SCHEMA = 1` 必须提到 `2`。实测：`build_reading()` 即使 `_REMEMBER=False` 也**读**缓存
  （只有 `_cache_put` 受 `:249` 管），缓存键是**来源文件**的 `[rel, mtime_ns, size, sha256]` ——
  改 `pipeline_view.py` 不改键 ⇒ 真仓库跑 `--report` 仍打旧字段（把三个 reader 猴补成 raise 之后
  `read_gates/read_leases/read_verdicts` 依旧返回旧读数）。这不是削弱，是给读侧换版本号。
- **明确写下（防下一张卡误判）**：`tests/test_pipeline_view.py:381`
  （`assert set(payload) == set(_spec(bid)["row_fields"])`）**不会因为本卡变红** —— 它比运行时 payload 与
  声明表，两边同步加字段就仍然守恒。若它红了，说明只改了一边（那是 bug，不是权限）。

## 交付

1. `tools/pipeline_view.py`：`_read_gates` payload 加 `at` / `dirty` / `branch`（原样透出，不转时区），
   `BLOCKS[gates]["row_fields"]` 同步加三项；`_read_leases` 每行加 `dead`
   （`from pool import registry` + `registry.is_dead(row, time.time(), log_base=lambda: root)`），
   `BLOCKS[leases]["row_fields"]` 同步加 `dead`；`_read_verdicts` 换新正则、改「一卡一行 + attempts + selected」，
   `_empty_verdict`（`:453-459`）加 `attempts`，`BLOCKS[verdicts]["row_fields"]` 加 `attempts`。
2. `tools/pipeline_view.py`：`_report_gates` 念「at=…（X 小时前；落后 N 个提交）」，新增
   `_commits_behind(rev)`（走 `_run_git`，rc != 0 回「认不出 rev=<x>」）与 `_age_hours(at)`
   （`gates/last.json` 的 `at` 是 **naive 本地时间**，`scripts/run_gates.py:2781` 用
   `datetime.now().isoformat(timespec="seconds")`；与 `_now_iso()` 的 aware 值直接相减会
   `TypeError: can't subtract offset-naive and offset-aware datetimes`）；`_report_leases` 念「其中 M 条已死」；
   `_report_verdicts` 每行念 selected 与 attempts 数；docstring `:14` 与 `:466` 的「活租约」改成
   「租约（行内 `dead` 标死活）」。
3. `tools/pipeline_view.py`：`_GIT_SHAPES`（`:770-774`）补 `3:` 档，
   `_CACHE_SCHEMA`（`:82`）`1` → `2`，`import time`（文件现在没有）与 `from pool import registry`
   （先例 `tools/timeflow_inbox.py:74-77` 用 try/except ImportError）。
4. `tests/test_pipeline_view.py`：五条新钉子（判据 1 一条、判据 2 两条、判据 3 两条）；
   `_write_gates_last`（`:66-71`）加 `at` / `dirty` / `branch` 三键（默认「测试运行时 - 5h30m」/ `False` /
   `line/impl-x`，`rev` 默认保持 `deadbee`）；`_make_repo`（`:41-52`）补**第 2 笔提交**（判据 1 要「落后 1」）；
   `_write_registry`（`:88-94`）参数化（判据 2 要两条）；`:656` 的 `2` → `3`（`:646` 不动）。
5. `gates/diag/_rev_E115.py` + `gates/diag/_rev_E115_result.txt`（四条变异 + 一条安静对照的读数）。
6. 卡规格 + 三片段（由落地链的 ② 文档件按台账号 `T-AG626` 自动生成）。

## 验收（三条，落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pipeline_view.py tests/test_workbench_bridge.py tests/test_wb_daily.py tests/test_pool_mcp_board.py tests/test_timeflow_inbox.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pipeline_view.py tests/test_pipeline_view.py
python -X utf8 tools/pipeline_view.py --report
```

第三条人读一遍，三件事必须同时成立：`[gates]` 首行念出「X 小时前」与「落后 N 个提交」；
`[leases]` 念出「其中 1 条已死」（今天主树那条 E105）；`[verdicts]` 里 `120` 只出现**一次**、
`120.killed` 不再作为卡号出现。

## 已知残留（本卡不做，别当成改完了）

- `tools/workbench_bridge.py:97-110` 的 head 仍写「N 条活租约」、行内不标死活，`tools/wb_daily.py:424`
  仍写「[在飞] N 条租约」，`tools/pool_mcp.py:1778-1783` 的 board 人话仍只念 `ok=/rev=/共 N 道` ——
  这三处按归属划分留给下一张卡；改 head 措辞会红 `tests/test_workbench_bridge.py:122`，
  并要连带把夹具 `_lease()`（`:77-79`）的 `at` 改成相对当前时间，那是另一张卡的爆炸半径。
- `.stale` 归档文件（如 `gates/diag/wb-144.r2.verdict.txt.stale`）天然不被新正则命中
  （不以 `.verdict.txt` / `.report.md` 结尾）—— 既有口径，本卡不动。

## 不许做

- 不许改 `gates/last.json` 的写法（生产者 `scripts/run_gates.py:2778-2781` 一个字节都不动）；
- 不许削弱 `tools/pool/registry.py` 既有的 `is_dead` 判据（TTL **或** 日志判死，两条都要问），
  也不许把它抄一份进 `pipeline_view`；
- 不许手改 `gates/diag` 下的任何既有产物（`pool-registry.json` / `wb-*.verdict.txt` /
  `pipeline-view-lastgood.json` / `readcache/`）—— 要造夹具就在 `tmp_path` 里造；
- 不许把死租约过滤掉（本卡定死「标记」），也不许在读侧顺手 `registry.prune()`；
- 不许把墙钟（小时数 / 落后提交数 / `stale_for_s`）写进 `--json`；
- 不许为了让 bug 消失去改 `gates/last.json` 的时间戳，或删 `wb-120.killed.*` / `wb-143.attempt1.*` 这些历史文件。
