# 卡 E130 · checkin_status 把任意日期串当「今日」，并原样拼进留档路径

> 台账号 T-AG638｜分区 E（门禁与可信度）｜树 .wt/E130｜层 判据层｜基准 9bb2f9be（立卡时主树 HEAD，2026-11-17 06:43:48 +0800）｜depends 无
> 依据：用户 m00001「起草卡 E130 规格 —— checkin_status 把任意日期串当『今日』，并原样拼进留档路径；非法日期必须 isError=True 并在正文点名要 YYYY-MM-DD」。
> 行号已按 2026-11-17 06:50 现场（主树 9bb2f9be，Python 3.14.6，Windows）逐条复核；本卡域是 tools/pool_mcp.py:1613-1757 这一段。
> 全部实验在 tempfile.mkdtemp() 里做，脚本 gates/diag/_e130_probe3.py / gates/diag/_e130_probe4.py / gates/diag/_e130_final.py（未跟踪；gates/diag/* 被 .gitignore:76 忽略），未碰主树任何受保护文件；gates/diag 下真实 checkin 留档数 = 0。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · date 一行都没校验：schema 说 YYYY-MM-DD，代码只做 strip

- tools/pool_mcp.py:515-518 —— date 只有 `type` 与 `description`，**没有** `pattern` / `format` / `enum`：

```text
515|                 "date": {
516|                     "type": "string",
517|                     "description": "看哪一天（YYYY-MM-DD；默认今天，本地时区）",
518|                 },
```

- tools/pool_mcp.py:520 `"required": []`（可选是对的，但可选不等于任意串）。
- tools/pool_mcp.py:1644 `date = str(arguments.get("date") or "").strip() or _today_local()` —— 只有 strip 与「空 ⇒ 今天」两件事，没有形状检查、没有日历检查。
- tools/pool_mcp.py:1757 `return _result(chr(10).join(lines), payload, is_error=False)` —— 整条路径只有 :1662（留档读不了）会 `is_error=True`，参数非法恒 False。

实测（gates/diag/_e130_final.py，2026-11-17 跑，root = tempfile 临时树，原文摘录）：

```text
{"date": "2026-02-30", "isError": false, "payload_date": "2026-02-30", "first": "今日签到（checkin_status）—— 2026-02-30"}
{"date": "2026-13-99", "isError": false, "payload_date": "2026-13-99"}
{"date": "2026-1-2",   "isError": false, "archive": "...\gates\diag\checkin-2026-1-2.json"}
{"date": "today",      "isError": false, "archive": "...\gates\diag\checkin-today.json"}
{"date": "20260102",   "isError": false, "payload_date": "20260102"}
{"date": "2026-W01-1", "isError": false, "payload_date": "2026-W01-1"}
```

`date.fromisoformat` 单独用也不够（gates/diag/_e130_probe4.py，Python 3.14.6 原文）：

```text
'20260102'            -> 2026-01-02      # 8 位串被当合法
'2026-W01-1'          -> 2025-12-29      # ISO 周日期
'2026-1-2'            -> ValueError: Invalid isoformat string: '2026-1-2'
'2026-02-30'          -> ValueError: day 30 must be in range 1..28 for month 2 in year 2026
'2026-13-01'          -> ValueError: month must be in 1..12, not 13
'0000-01-01'          -> ValueError: year must be in 1..9999, not 0
```

⇒ 校验必须是**两条一起**：先 `^\d{4}-\d{2}-\d{2}$`（挡 20260102 / 2026-W01-1 / 时刻串 / 全角），再过 `date.fromisoformat`（挡 2026-02-30 / 2026-13-99 / 0000-01-01）。只用其中一条都会漏。

### 问题 2 · 非法串被原样拼进留档路径，还印在首行「今日签到」上

- tools/pool_mcp.py:1650 `archive = archive_root / _CHECKIN_DIR / f"checkin-{date}.json"` —— date 原样进 f-string。
- tools/pool_mcp.py:1653 `lines = [f"今日签到（checkin_status）—— {date}"]` —— 首行把非法串冒充「今日」。

实测（同上脚本，原文）：

```text
date="../x"     -> archive "...\gates\diag\checkin-..\x.json"   首行「今日签到（checkin_status）—— ../x」
date="C:/tmp/x" -> archive "...\gates\diag\checkin-C:\tmp\x.json"（冒号在 Windows 文件名非法，拼路径时不炸、打开时才炸）
```

### 问题 3 · 上跳够深就真读到树外文件（不只是路径难看）

gates/diag/_e130_probe3.py 在临时树外写了一份 outside/secret.json（内容 `{"date": "x", "applied": true, "results": [{"id": "leak", "platform": "outside-tree"}]}`），原文：

```text
n=3 date="../../../outside/secret"          resolve=...\tree\gates\outside\secret.json  inside_diag=False found=False
n=4 date="../../../../outside/secret"       resolve=...\tree\outside\secret.json        inside_diag=False found=False
n=5 date="../../../../../outside/secret"    resolve=<tmp>\outside\secret.json           inside_diag=False found=True
    -> 读到了树外内容 results=[{"id": "leak", "platform": "outside-tree"}]
    -> 正文首行「今日签到（checkin_status）—— ../../../../../outside/secret」
```

⇒ `checkin-` 前缀买不到安全：`...\gates\diag\checkin-..\..\..\..\..\outside\secret.json` 经 `resolve()` 之后就是 `<tmp>\outside\secret.json`。上面 n=3 / n=4 只是**恰好**没拼中 `.json` 才 found=False，不是被挡住了。

### 问题 4 · 三处文案都在假设「给了 YYYY-MM-DD 才会拼路径」，钉子对这个洞是盲的

- tools/pool_mcp.py:517 description 与前引一致：说给客户端看的是 YYYY-MM-DD，服务端没有对应实现。
- docs/subsystems/pool/README.md:159（表行，在 pool-margin 的 :11 与 :92 之外，scripts/gen_pool_readme.py 不生成它）同样只说「读留档 + 账本」。
- tests/test_pool_mcp_task.py:1028-1038 `test_checkin_status_prose_agrees_with_what_it_reads` 只断言 description / docstring / README 三处含「留档」「health.last_checkin」「last_probe」三个关键词，一个字符都没断言「非法值会怎样」。

### 问题 5（合法，不改，本卡照抄它的形状）

tools/pool_mcp.py:1662 `return _result(f"留档读不了：{exc}", {**payload, "found": False}, is_error=True)` —— 同一个函数里「读不了 ⇒ is_error=True」已经是对的。本卡加的非法参数分支只许照这个形状写，不另造一套。

## 先例（本仓现成的参数 / 日期校验写法，改法照抄这五条）

1. tools/pool_mcp.py:1540-1545（quota_status）—— 参数缺了就**在第一行** return `_result(text, {...}, is_error=True)`，文案点名要什么：「quota_status：card 和 model 都要给（例如 card=201, model=deepseek-v4.1-flash）。」
2. tools/pool_mcp.py:1662 —— 同函数内的 `is_error=True` 形状（见问题 5）。
3. tools/pool_accounts.py:1762-1773（cmd_due --now）—— 日期形参认不出就 `print(f"--now 认不出：{args.now!r}（要 ISO-8601）", file=sys.stderr)` 并 `return EXIT_USAGE`（:76 `EXIT_OK, EXIT_USAGE = 0, 2`）。本仓对「日期串不合法」的既有口径是**点名要什么格式**，不是只回一句「参数错误」。
4. tools/zentao_gantt.py:143-153（_parse_date）—— 坏格式抛 `GanttError("baddate", step, f"{label} 的 {field}={text!r} 不是 ISO 日期（YYYY-MM-DD）")`。
5. tools/pool/usage_ingest.py:108-115 —— `USAGE_TZ` + `_RFC3339_RE`，注释 :112 写明「datetime.fromisoformat 比它宽松（吃 2026-10-13 与裸本地时间），所以先过一遍这个正则」⇒ **正则 + fromisoformat 两条一起**是本仓现成口径。

## 兼容面（grep 出来的，改签名会碰到谁）

- 分发表 tools/pool_mcp.py:3007 `"checkin_status": tool_checkin_status,`；调用 tools/pool_mcp.py:3047-3048 直接透传 `isError` —— 非法分支只要 `is_error=True` 就够，协议层不用动。
- schema 面的既有断言都**不**钉键集与 pattern：tests/test_pool_mcp.py:193-197 只查 `type` / `additionalProperties` / `required ⊆ properties` / `readOnlyHint` / description 非空（:201 那条只钉 pool_plan 的 concurrency）。tests/test_pool_mcp_task.py:1107-1110 钉的是 usage_report 的键集。另有一套 registry 服务端的 tests/test_mcp_line.py:87 不覆盖 pool_mcp。⇒ 给 date 加 `pattern` 安全。
- payload 键集是**精确**的：tests/test_pool_mcp_task.py:938 `assert set(payload) == {"date", "archive", "found"} | _LEDGER_KEYS` 与 :950 同理（`_LEDGER_KEYS` 在 :926）⇒ 非法分支不许顺手加键。
- 同一段文案的钉子：tests/test_pool_mcp_task.py:1033-1034 `assert len(rows) == 1`（README 里含 checkin_status 的行只许 1 行）⇒ 补文案不许把表行拆成两行。
- 写端 tools/pool_accounts.py:1503-1505 `_checkin_archive(date)` 与 :1695-1706 `write_checkin_archive`：**本卡不改**（理由见下面的边界）。它的调用点 tests/test_pool_checkin.py:818-819 / :827 / :946-947 因而不受影响。
- 第三个日期读者 tools/wb_daily.py:116-134 `checkin_state`：`date = datetime.date.today().isoformat()`（:122）＋同样的 f-string 拼路径（:123）—— 它没有 date 形参，本卡不动它（见边界）。
- 消费方说明 tools/pool_mcp.py:3072-3074 的 instructions 不含 date 细节，不必改。

## 边界（诚实边界：这一条校验该落在哪一层）

**校验落在 MCP 层（工具入口），不落池层。** 依据是核实过的读口径：

- 「读留档」这件事在仓里只有两处实现 —— tools/pool_mcp.py:1650（本卡的域）与 tools/wb_daily.py:123（另一张卡）。tools/pool_accounts.py 里**只有写**：:1503-1505 `_checkin_archive` 与 :1695-1706 `write_checkin_archive`，`grep -n "checkin-" tools/pool_accounts.py` 只命中 :1504 的 docstring / :1505 的拼路径 / :1698 的 mkstemp 前缀，没有任何读函数（读回来解析 JSON 的只有 tools/pool_mcp.py:1660 与 tools/wb_daily.py:136）。
- 池层写端**结构上收不到用户串**：`checkin` 子命令的 argparse（tools/pool_accounts.py:1885-1892）只有 `--json` / `--all` / `--probe` / `--platform` / `--spacing`，没有 `--date`；日期由钟决定（:1718 `now = _now()`、:1727 `date = now.strftime("%Y-%m-%d")`，`_now` 用 :64 `TZ = timezone(timedelta(hours=8))`）。
- ⇒ 把校验塞进 `_checkin_archive` 只会得到一个「永远不被触发的分支」，而 MCP 面的洞照旧开着；那是把判据放在错的层。本卡只在 tools/pool_mcp.py 加一道入口校验，写端字节不动。
- **不许造第二份日期真源**：今天仍只有 tools/pool_mcp.py:1619-1623 `_today_local()`（UTC+8）这一份；新加的只是「形状 + 日历」检查，不新增任何 `_today_iso` / `today_str` 之类实现，也不许把 :1644 的 `strip` 与「空 ⇒ 今天」改掉。
- 另一条边界（**不在本卡域**，写清以免被当成漏做）：tools/wb_daily.py:122 用的是裸本地日期 `datetime.date.today()`（不是 UTC+8），与 `_today_local()` 是两个口径；它没有 date 形参，非法串进不去。要不要统一是另一张卡的事，本卡不许顺手改（改了会动 wb_daily 的既有钉子 tests/test_wb_daily.py:397 / :429）。

## 判据（5 条）

### 判据 1 · 非法日期一律拒收：`isError=True`，正文点名要 YYYY-MM-DD，且不往下走

`tool_checkin_status` 收到非法 date 时必须**在拼路径之前** return：`is_error=True`、正文含 `YYYY-MM-DD`、正文**不含** `留档路径：`（那是 :1654-1657 只有合法值才会打的行）、payload 不加键（判据 1 只管拒收；合法才拼路径由判据 2 断）。三批非法值都要覆盖：

- 格式不对：`2026-1-2`、`today`、`20260102`、`2026-W01-1`、`2026-01-02T00:00:00`、`２０２６-01-02`（全角数字）；
- 日历上不存在：`2026-02-30`、`2026-13-99`、`2026-02-29`、`0000-01-01`；
- 带路径分隔符或 `..`：`../x`、`../../../../outside/secret`、`C:/tmp/x`、`a\b`。

**钉子**（tests/test_pool_mcp_task.py）：

- `test_checkin_status_rejects_malformed_date` —— 第一批逐个断言 `is_error is True`、`"YYYY-MM-DD" in text`、`"留档路径" not in text`；
- `test_checkin_status_rejects_non_calendar_date` —— 第二批同形（这四条正则全过，只能靠 `date.fromisoformat` 挡，见问题 1 的 probe4 原文）；
- `test_checkin_status_rejects_path_like_date` —— 第三批同形，并断言 payload 里**没有**被 stat 过的越界路径（`payload.get("archive")` 要么不存在，要么 `Path(...).resolve().is_relative_to((tmp_path / "gates" / "diag").resolve())` 为真）。

### 判据 2 · 合法日期才拼路径，且 resolve() 之后必须落在 gates/diag 之内

合法值（`2026-01-02`、`2024-02-29`、`2026-12-31`）拼出来的 archive 必须 `Path(payload["archive"]).resolve()` 的父目录**恰好**等于 `(root / "gates" / "diag").resolve()`，文件名恰好 `checkin-<date>.json`。Windows 下用 `Path.is_relative_to()` 与 `resolve()` 后的 pathlib 比较，**不许**用字符串前缀或 `os.path.abspath` 拼。

**钉子**：`test_checkin_status_archive_stays_inside_diag_dir` —— 三个合法日期逐个断言「父目录 == diag 的 resolve()」＋「文件名 == checkin-<date>.json」；再对判据 1 那三批非法值断言 `is_error is True`（合法/非法在同一张表里过一遍，防止有人只加正则不接分支）。

### 判据 3 · 不给 date 时默认仍是今天，时区口径 UTC+8 一个字都不许改

`{}` / `{"date": ""}` / `{"date": "   "}` / `{"date": None}` 四种必须一律 `payload["date"] == pool_mcp._today_local()`，且 `is_error is False`（2026-11-17 实测四种都落到 `2026-11-17`，见 gates/diag/_e130_probe3.py 的 P2 段）。

**钉子**：`test_checkin_status_defaults_to_utc8_today` —— 四条空参断言同上；再断 `pool_mcp._today_local() == datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")`；最后照 tools/pool_mcp.py 既有源码断言先例（tests/test_pool_mcp_task.py:882-884 的 `needle not in src`）断 `_today_local` 的函数源码里含 `hours=8`、不含 `date.today()`。

### 判据 4 · 反向变异 ≥3，外加一条只改注释的安静对照（真改、真跑、真还原，记 sha256）

- A：把新加的校验分支整段删掉（回到 2026-11-17 的现状）⇒ 判据 1 的三条钉子必红；
- B：只做正则、不做日历检查（`^\d{4}-\d{2}-\d{2}$` 过了就放行）⇒ `test_checkin_status_rejects_non_calendar_date` 必红，另两条绿（这就是「两条一起」的理由）；
- C：只做 `date.fromisoformat`、不做正则 ⇒ `test_checkin_status_rejects_malformed_date` 必红（`20260102` / `2026-W01-1` 会被放行，probe4 实测）；
- D：把非法串回落成 `_today_local()`（「非法就当今天」）⇒ 判据 1 必红，而判据 3 的四条空参断言仍绿（说明「回落今天」不是合法修法）；
- C1（安静对照）：只改一句注释（例如 tools/pool_mcp.py:1645 那条卡 E114 注释加一个空格）⇒ 全绿。

每条真改、真跑、真还原；记改前 / 改后 sha256（`git hash-object`）与 `-k checkin` 子集的 passed/failed 数。记录落 gates/diag/_rev_E130_result.txt（gates/diag/* 被 .gitignore:76 忽略，不入库）。变异脚本必须放**主树** gates/diag/（`ROOT = __file__.parent.parent.parent`），放卡树会算成卡树里的卡树。

### 判据 5 · 既有钉子一条都不许削弱（先列全，再动代码）

tests/test_pool_mcp_task.py 里与 checkin_status 有关的钉子共 9 条（2026-11-17 `grep -n "def test_.*checkin"` 原文）：

1. :830 `test_checkin_status_says_missing_when_no_archive`
2. :840 `test_checkin_status_reads_archive`
3. :866 `test_checkin_status_is_offline_and_never_writes`
4. :930 `test_checkin_status_payload_separates_archive_from_ledger`（:938 / :950 的精确键集）
5. :954 `test_checkin_status_never_claims_today_from_a_stale_probe`（:965 `"今天签到" not in text`）
6. :980 `test_checkin_status_three_states_are_distinguishable`
7. :1010 `test_checkin_status_ledger_is_injectable_and_untouched`（账本 sha256 与目录清单前后比对）
8. :1028 `test_checkin_status_prose_agrees_with_what_it_reads`（三处文案 + 关键词 + 单行）
9. :1386 `test_checkin_read_side_lands_on_the_write_side`（读端 == 写端，:1436 `assert read == write`）

另有 tests/test_pool_mcp.py:185 `test_tools_list_shape_is_pinned` 管 schema 外形。**这 10 条原样留着**，一条都不许改断言、不许改 fixture 形状来「配合」新分支。

## 交付

1. tools/pool_mcp.py：在 :1644 之后、:1649 之前加入口校验（模块级 `re` 已在 :193，不必新增 import）：strip 后为空 ⇒ 仍走 `_today_local()`；非空且不满足 `^\d{4}-\d{2}-\d{2}$` 或 `date.fromisoformat` 抛 ValueError ⇒ `return _result(文案, {...}, is_error=True)`，文案点名「要 YYYY-MM-DD」并原样带出收到的值（照 :1662 与 :1544 的写法）。
2. tools/pool_mcp.py:512-522：给 date 加 `"pattern": "^\\d{4}-\\d{2}-\\d{2}$"`（schema 只给客户端看，服务端校验以判据 1 为准），description :517 补一句「非法值拒收，正文点名要 YYYY-MM-DD」；:506-510 的 description 与 :1629-1639 的 docstring 保持「留档 / health.last_checkin / last_probe」三个关键词不删。
3. tests/test_pool_mcp_task.py：新增判据 1 的三条钉子 + 判据 2 一条 + 判据 3 一条（共 5 条），全部用现成的 `tmp_path` 夹具形状（照 :840-863 与 :918-923 `_checkin_archive`）。
4. docs/subsystems/pool/README.md:159：表行补一句「非法日期拒收（正文点名 YYYY-MM-DD）」，**仍是一行**（:1033-1034 的 `len(rows) == 1`）。
5. 反向变异记录 gates/diag/_rev_E130_result.txt（gitignored，不入库）。
6. 卡规格与三份片段由落地链按台账号 T-AG638 生成（片段路径本卡不手写）。

## 验收（三条，落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pool_mcp_task.py tests/test_pool_mcp.py -o addopts= -q --no-cov
```

```bash
python -X utf8 -m ruff check tools/pool_mcp.py tests/test_pool_mcp_task.py
```

```bash
python -X utf8 scripts/check_derived_docs.py --check
```

基线（2026-11-17 06:50 在 9bb2f9be 上真跑，原文）：`python -X utf8 -m pytest tests/test_pool_mcp_task.py -o addopts= -q --no-cov` ⇒ 42 passed in 23.99s；`ruff` ⇒ All checks passed!；`check_derived_docs.py --check` ⇒ rc=0，末两行「[OK  ] docs/subsystems/pool/README.md 与现算一致（50 个文件 / 19821 行 / 2026-11-17）」与「[OK  ] docs/INDEX.md（423 篇…）」。

## 不许做

1. 不许改时区口径：`_today_local()` 的 UTC+8（tools/pool_mcp.py:1619-1623）不许换成 `datetime.date.today()`，也不许新增第二份「今天」实现。
2. 不许把校验塞进 tools/pool_accounts.py:1503-1505 / :1695-1706（写端结构上收不到用户串，见边界），也不许在 tools/pool/checkin.py 里再写一份日期校验。
3. 不许把非法串当成空串来「拒收」：`""` / `"   "` / 缺键仍表示「今天」（判据 3），非法串绝不许回落今天。
4. 不许靠 `date.fromisoformat` 单条放行（`20260102` / `2026-W01-1` 会被吃，probe4 实测），也不许靠正则单条放行（`2026-02-30` 会被吃）。
5. 不许改测试让门变绿：判据 5 列的 9 条既有钉子 + tests/test_pool_mcp.py:185 原样留着；payload 的精确键集（:938 / :950）不许加键。
6. 不许删 description / docstring / README 里的「留档」「health.last_checkin」「last_probe」，不许把 README 的行拆成两行（:1033-1034）。
7. 不许动 .wt/ 下任何工作树；不许把 gates/diag/ 下的探针与变异记录入库（.gitignore:76），gates/diag/gate_lock.py 是 :77 的唯一白名单文件。
8. 不许顺手统一 tools/wb_daily.py:122 的裸本地日期口径（不在本卡域，改了会动 tests/test_wb_daily.py:397 / :429）。
