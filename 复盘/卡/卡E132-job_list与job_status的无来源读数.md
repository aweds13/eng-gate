# 卡 E132 · job_list / job_status 的无来源读数：台账读不到就降级成「断了」，退出码与命令是编的

> 台账号 T-AG640｜分区 E｜树 .wt/E132｜层 判据层｜基准 b5a703cf｜depends E131（同一文件 tools/pool_mcp.py 有两个写者）
> 依据：用户 m00001「起草卡 E132 规格 —— job_list / job_status 的无来源读数：台账读不到就降级成「断了」，退出码与命令是编的」
> 行号已按 2026-11-17 现场（主树 2d396355，分支 line/impl-v1，Python 3.14.6）逐条复核；tools/pool_mcp.py 共 3392 行、tools/pool/jobs.py 共 560 行、tests/test_pool_mcp.py 共 1194 行、tests/test_pool_jobs.py 共 653 行。
> 全部实验在 tempfile.TemporaryDirectory() 里做，探针脚本 gates/diag/_e132_matrix.py、gates/diag/_e132_probe_red.py、gates/diag/_e132_probe_fixture.py（均未跟踪；gates/diag/* 被 .gitignore:76 忽略），未碰主树任何受保护文件、未提交、未跑全量门禁。

## 要解决的问题

判据只有一条：**说不出来源的读数就不许说**。台账读不到 ⇒ 这一行的状态**判不了**（要显式说出来），既不是「断了」也不是「台账已完结」；没起子进程 ⇒ 不许给 exit_code，也不许说「来自 <某条命令>」。逐处下结论，合法的另列问题 6。

### 问题 1（最重）：台账读不到 ⇒ 同一行从「台账已完结」翻成「断了」，而客户端看不见差别

三段链路：

- tools/pool_mcp.py:1028 —— `statuses = {cid: c.status for cid, c in _backlog_cards(root).items()}`：台账失败在这里已经被洗成 `{}`；
- tools/pool_mcp.py:967-970 把异常吞掉：`except Exception as exc:  # noqa: BLE001 —— 台账坏了/不在/格式变了，一律当「没有台账」` → `print(f"[job_status] 台账读不到，按没有台账继续：{type(exc).__name__}: {exc}", file=sys.stderr)` → `return {}`；
- tools/pool/jobs.py:399-400 —— `if backlog is not None and backlog.get(card) == "done": return "台账已完结", "台账里这张卡已经 done，日志留在盘上"`；台账没了就落到 :401 `return classify_job_state(age, has_verdict)`，而 :360 是 `return "断了", f"无判决，且日志已静默 {age:.0f}s > {STALL_SECONDS}s"`（`STALL_SECONDS = 480`，:41）。

实测：同一份 gates/diag/wb-Z1.jsonl（内容一行 `{"type":"assistant"}`，mtime 拨到 now-100000），台账三种形态，contextlib.redirect_stderr 把 stderr 与正文分开。原始输出：

```text
=== 台账 done ===  is_error = False | counts = {"台账已完结": 1} | 顶层键 = ['count', 'counts', 'diag_dir', 'jobs']
  state = ["台账已完结"] | why = ["台账里这张卡已经 done，日志留在盘上"] | stderr(客户端看不到) = ''
  正文：外包派活台账（job_list）—— 扫 <tmp>/gates/diag
        共 1 个日志：台账已完结 1
          · 卡 Z1  [台账已完结]  wb-Z1.jsonl  22B  mtime=2026-11-16 02:38:54（距今 100000s）  无判决  —— 台账里这张卡已经 done，日志留在盘上｜在飞：否
=== 台账 broken（TOML 截断成 [[cards]）===  is_error = False | counts = {"断了": 1} | 顶层键同 4 键
  state = ["断了"] | why = ["无判决，且日志已静默 100000s > 480s"]
  stderr = "[job_status] 台账读不到，按没有台账继续：BacklogError: backlog 不是合法 TOML：Expected ']]' at the end of an array declaration (at line 4, column 8)"
  正文：共 1 个日志：断了 1 ／ · 卡 Z1  [断了]  wb-Z1.jsonl  22B  mtime=2026-11-16 02:38:54（距今 100000s）  无判决  —— 无判决，且日志已静默 100000s > 480s｜在飞：否
=== 台账 absent（docs/workbacklog.toml 不存在）===  is_error = False | counts = {"断了": 1}
  stderr = "[job_status] 台账读不到，按没有台账继续：BacklogError: backlog 文件不存在：<tmp>\docs\workbacklog.toml"
  正文与 broken 同形（只有 tmp 路径不同）
```

结论：**同一份日志、同一份 mtime**，台账 done ⇒「台账已完结 1」，台账坏掉/不在 ⇒「断了 1」。两种读数互斥，而 data 顶层键完全相同（`['count','counts','diag_dir','jobs']`，见 :1054）、isError 都是 False、正文里**没有一句**提台账 ⇒ 客户端唯一能感知的差别只在它看不见的 stderr。工具自述（:401-402 的 description 与 :1026 的 docstring）也只列「在跑 / 已判决 / 断了 + 历史尝试 / 已被取代 / 台账已完结 / 非派活」，**没有**「台账读不到」这一态。

### 问题 2：那句 stderr 把工具名写错（job_list 也走 _backlog_cards）

tools/pool_mcp.py:968 的前缀硬写 `[job_status]`，但 `_backlog_cards` 的调用点有两处：:1028（job_list）与 :1081（job_status 无日志支）。实测 job_list 打出来的 stderr 原文：

```text
[job_status] 台账读不到，按没有台账继续：BacklogError: backlog 文件不存在：<tmp>\docs\workbacklog.toml
```

一行日志指错了工具，排障时会把 job_status 当嫌疑人。这也是「这条失败面今天没有任何人看」的旁证。

### 问题 3：job_status 的 command / exit_code 没有来源

有日志那一支（tools/pool_mcp.py:1121-1141）：

```text
1121:     log = logs[-1]
1122:     argv = [sys.executable, "-X", "utf8", "tools/wb_status.py", log.name, "--repo"]
1123:     command = _cmd_text(argv)
1124:     lines = read_log_lines(log)
1125:     timeline, summary = parse_events(lines)
1126:     body = render_timeline(log.name, timeline, summary, tail=0, repo=True, git_cwd=diag).strip()
...
1130:         f"卡 {card} 的状态（job_status）—— 来自 `{command}`（cwd={diag.as_posix()}）：\n{body}"
...
1136:         "command": command,
1137:         "exit_code": 0,
```

:1122 只是**拼了一串 argv 字符串**，:1124 / :1126 是进程内 import 渲染，:1137 的 `0` 是字面量。实测（临时 root + gates/diag/wb-E999.jsonl 一行 `{"e":"start"}`）：

```text
is_error = False
data 顶层键 = ['card', 'command', 'exit_code', 'found', 'in_flight', 'in_flight_why', 'log']
data["command"] = "C:/Users/example\miniconda3\python.exe -X utf8 tools/wb_status.py wb-E999.jsonl --repo"
data["exit_code"] = 0
正文第 2 行 = "卡 E999 的状态（job_status）—— 来自 `C:/Users/example\miniconda3\python.exe -X utf8 tools/wb_status.py wb-E999.jsonl --repo`（cwd=<tmp>/gates/diag）："
源码核对（同一次跑）：tools/pool_mcp.py:1061-1141 区间内 "_run(" 出现 0 次；"read_log_lines(" / "render_timeline(" 出现在行 [1124, 1126]
```

单独真跑那串命令确实退 0（`subprocess.run(argv, cwd=diag)` rc=0），但那只是因为 wb_status.py 这一页恰好退 0 —— MCP 从未跑它、从未拿到它的 rc，两个 0 只是碰巧同值，**不是来源**。这就是「编的」：机器块给了一个看起来可核的字段，读者无从知道它没被核过。

### 问题 4：同一段 docstring 里自相矛盾

tools/pool_mcp.py:1064 与 :1066 隔两行互相打架：

```text
1064:     """一张卡现在到哪了 —— **import** `tools/pool/jobs.py` 读 log 并渲染（不再起进程）。
1066:     ★ `command` 字段仍给 CLI 说法；输出形状与 `tools/wb_status.py <log> --repo` **逐字一致**。
```

「不再起进程」与「command 字段仍给 CLI 说法」并排，就是让人照抄一条本工具没跑过的命令。模块头的表（:38「时间线 + 仓库状态 | **import** `tools/pool/jobs.py`（读 log + 渲染）」）已经把真相写对了，只有 :1066 这一句与 :1130 / :1136 / :1137 三处实现还留在旧写法。

### 问题 5（连带）：无日志支在台账读不到时把「判不了」说成「还没派过」

tools/pool_mcp.py:1081-1082 同样调 `_backlog_cards(root)`，:1115-1120 的兜底文案是：

```text
1117:             + f"没有：卡 {card} 在 {diag.as_posix()} 里没有 wb-{card}.jsonl"
1118:             + "（连 r2… 也没有）—— 还没派过，或日志不在这个树里。"
1120:         return _result(text, base, is_error=True)
```

这一支至少 is_error=True（没有撒谎成 False），但「台账读不到」被翻译成「还没派过」仍是同一个病：**这一源不可判，却说成了另一个肯定判断**。本卡只要求它把「台账读不到」这句也跟上（判据 1 的侧面断言），不改它的三支结构。

### 问题 6（合法，不改）：_backlog_cards 的「读不到就回空字典，绝不抛」是对的

tools/pool_mcp.py:955-961 的 docstring 逐字：「台账 `id -> Card`（`task/status` 都要用）。**读不到就回空字典，绝不抛**。……号池工具是只读面，台账不在只该让「证据链」少几类，不该让整个 `job_status` 变成一行 traceback。」—— 这条口径本身没错，tests/test_pool_mcp.py:1136-1150 也把它钉住了（台账缺失时仍 is_error=False + 落地日志照读）。本卡**不动**「不抛」，改的是它的下一句：**不抛 ≠ 不说**。

## 先例（本仓现成的「读不到要说读不到」写法，改法照抄这四条）

1. 同一份 jobs.py 里就有现成写法 —— tools/pool/jobs.py:481-482，租约登记文件读不了时把「这一源不可判」拼进 why：

```text
    except Exception as exc:  # 登记文件坏了不该把「在飞」判成假 —— 但要说出这一源不可判
        lease_gap = f"（登记文件读不了：{type(exc).__name__}: {exc} ⇒ 这一源不可判）"
```

2. tools/pool_mcp.py:1106-1114，台账说 done 但仓里五类证据全不中 ⇒ is_error=True 且正文点名「这是台账与仓对不上，不是「没派过」」—— 同一个工具的相邻分支已经在「不许把两件事说成一件」上做对了。
3. tools/pool_mcp.py:466-469 的额度四态（「只读，当场算，不探测」）与 :1536「四态都不猜：`未记录` 不当可用、`已过期` 不当可用。」—— 多态口径与「不许洗成两态」的先例。
4. tools/pool/plan.py:73 `class BacklogError(Exception)`，:149-161 的四处 raise 原文（`backlog 文件不存在：{path}` / `backlog 不是合法 TOML：{exc}` / `缺 [base] 段或 base.reviewed` / `缺 [[cards]] 段（至少一张卡）`）；而 tools/pool_mcp.py:929-930 的 pool_plan 已经单独 `except BacklogError` 并把原文摆到正文（:934），`_backlog_cards` 的 `except Exception` 是这张面上仅剩的宽口。

## 兼容面（grep 出来的，改签名会碰到谁）

- `scan_jobs` 四个调用点：tools/pool_mcp.py:1029（**唯一**传 `backlog=` 的）、tools/pool/registry.py:213、tools/pool/trae_dispatch.py:304、tools/wb_status.py:186。后三个不传 backlog，本卡**不动**它们（不传 backlog 的已知分叉记在 docs/traceability.d/T-AG623.toml:25 的 gaps 第 1 条，另卡收口）。
- `DEAD_STATES` 引用点：tools/pool/jobs.py:363-370（定义 + `is_dead_state`）与模块 docstring :10、:16、tools/pool/registry.py:55-58（`_DEAD_STATES = jobs.DEAD_STATES`）与 :215、tests/test_pool_registry.py:470-485。新态**不进** DEAD_STATES 时这五处一条都不破（已实测 `jobs.is_dead_state("判不了") is False`、`registry._DEAD_STATES == jobs.DEAD_STATES` 仍 True）。
- 既有钉子（不许削弱，名字与行号见判据 7）：tests/test_pool_mcp.py:190-202 / :217-239 / :258-288 / :335-344 / :365-390 / :430-445 / :1111-1133 / :1136-1150 / :1153-1163 / :1166-1176 / :1179-1194；tests/test_pool_jobs.py:471-502 / :518-549；tests/test_pool_lib.py:175-188；tests/test_pool_registry.py:470-485；tests/test_pool_mcp_task.py:68-69；tests/test_pool_mcp_write.py:42-43；tests/test_pool_mcp_http.py:480。
- 空白面（本卡可以动、不踩既有断言）：tests/ 下 `exit_code` 只在别的工具里出现，job_status 的 `data["command"]` **没有任何断言**（test_pool_mcp.py 里的 command 断言只有 :301 pool_plan / :362 lock_status / :1009-1011、:1029、:1072 额度探针）；也没有任何 `set(data)` / `sorted(data)` 的精确键集断言 ⇒ 给 job_list 的 data 加键、把 job_status 的 command 与 exit_code 删掉，都不破既有钉子。
- **唯一会破的既有钉子**：tests/test_pool_mcp.py:365-390 `test_job_list_classifies_by_evidence`。它今天的树里**没有台账**（:337 只建 gates/diag），正好落在被本卡改掉的那一支上；改完之后 :389 的精确等式 `data["counts"] == {"在跑": 1, "断了": 1, "已判决": 1}` 会变成 `{"在跑": 1, "判不了": 1, "已判决": 1}`。实测三种 fixture 组合（gates/diag/_e132_probe_fixture.py 原始输出）：

```text
cards=[]                          -> counts = {'在跑': 1, '断了': 1, '已判决': 1}   ← 但仍走「台账读不到」支（stderr: 缺 [[cards]] 段（至少一张卡））
cards=[('Z9','T-Z9','done')]      -> counts = {'在跑': 1, '断了': 1, '已判决': 1}   == 期望 ? True
cards=[('101','T-101','doing')]   -> counts = {'在跑': 1, '断了': 1, '已判决': 1}
```

⇒ 补一份**可读**台账（至少一张卡，不许是空 `[[cards]]`）就能让 :389 的等式一个字不改地继续绿。这是本卡唯一被允许碰的既有钉子，且只许**加 fixture**。
- 派生文档：tools/pool/jobs.py 在 tools/pool/ 下 ⇒ docs/subsystems/pool/README.md:29 那行（`| jobs.py | 560 | … |`）落在生成区（:11 的 pool-margin begin 到 :92 的 pool-margin end 之间），真源是 docs/subsystems/pool/modules.toml:70-73。改 jobs.py 的行数与状态集合 ⇒ 先改 modules.toml 再重跑 scripts/gen_pool_readme.py（POOL_REL 在 :65），**绝不手改 README**；scripts/check_derived_docs.py:92-104 的 TARGETS 就是这两条。
- skills/ 里 grep `job_list` / `job_status` 零命中 ⇒ 本卡不改 skills。

## 判据（7 条）

### 判据 1 · 台账读不到必须显式化，且那一行不许写成「断了」/「台账已完结」

新态字符串定为「判不了」（本仓已在用的词，不新造）。落点：`scan_jobs` 与 `_state_of_log` 增 keyword-only `backlog_error: str | None = None`，**由 jobs.py 自己**在末支分岔产态；`tool_job_list` 只做两件事 —— 把 gap 传下去、把 gap 摆到 data 与正文首段。判不了时 why 里要同时摆出两件事：台账为什么读不到，以及「原始三态读数是断了」这个事实（不许把它当结论）。

**钉子**（tests/test_pool_mcp.py）新增 `test_job_list_says_backlog_unavailable`，六条断言：

- data 有 `backlog_unavailable` 键：台账坏时是**非空字符串**且含 `BacklogError`；台账正常时是 `None`；
- 正文里出现「台账读不到」四个字；
- `data["jobs"][0]["state"] == "判不了"`，且 `!= "断了"`、`!= "台账已完结"`；
- `data["counts"] == {"判不了": 1}`；
- `is_error is False`（这是读数不是崩溃，与判据 7 的「不抛」一起守）；
- 侧面断言：同一棵树调 `tool_job_status({"card": "X1"})`（无日志、台账也坏）时，正文里要出现「台账读不到」。

### 判据 2 · 台账读得到时，一个字都不许变

**钉子** 两条：

- tests/test_pool_mcp.py 新增 `test_job_list_unchanged_when_backlog_readable`：复刻 :369-390 的现场（wb-101 / wb-102 / wb-103 + wb-103.verdict.txt + 一份**可读**台账，用 :1088-1108 的 `_e116_backlog` 写至少一张卡）⇒ `data["counts"] == {"在跑": 1, "断了": 1, "已判决": 1}`、`data["backlog_unavailable"] is None`、正文不含「台账读不到」、每行 `(card, state)` 与改前一致；
- tests/test_pool_jobs.py 新增 `test_scan_jobs_unchanged_when_backlog_error_absent`：不传 `backlog_error` 调 `scan_jobs(diag, now=now)` ⇒ 行里 11 个键与 why 文案**逐字**与今天相同（复刻 :493-502 那条八行精确等式的形状），且 11 个键里**没有**新键。

另：tests/test_pool_mcp.py:365-390 那条既有钉子只许**加一份可读台账 fixture**，:388-390 三条断言原文不动（理由见兼容面）。

### 判据 3 · job_status 的机器块不许有无来源的 command / exit_code

落点：有日志支**删掉** `"command"` 与 `"exit_code"` 两个键，换成 `"rendered_by"`（值写清「在进程内 import pool.jobs.render_timeline 渲染，没有起子进程」）；正文 :1130 的「来自 `{command}`」跟着改成同一句真话；docstring :1064-1066 与 tools/list 的 description（:412 附近 job_status 条目）同步。

**钉子**（tests/test_pool_mcp.py）新增 `test_job_status_payload_has_no_invented_command`，五条断言：

- 有日志（wb-E999.jsonl 一行）时 `"command" not in data` 且 `"exit_code" not in data`；
- `data["rendered_by"]` 含「进程内」三字，且含 `render_timeline`；
- 正文里**不出现** tools/wb_status.py（那串命令是从别处借来的），且出现「进程内」；
- 有日志支仍 is_error=False、`data["found"] is True`（形状没变，只换了说法）；
- 源码级：`inspect.getsource(pool_mcp.tool_job_status)` 里不出现 `_run(`、不出现 `"exit_code"` 字面量 —— 钉住「以后有人再塞一个没来源的字段」。

### 判据 4 · 状态只在 tools/pool/jobs.py 判一次（MCP 层不许再判一遍）

**诚实边界（本卡的域上限）**：`classify_job_state` 与 `_state_of_log` 是**唯一**状态真源。MCP 层只许把台账那句 gap 传下去，不许出现任何状态字符串常量、不许自己比 `STALL_SECONDS`、不许自己数 .verdict.txt。

**钉子**（tests/test_pool_mcp.py）新增 `test_job_list_takes_state_from_jobs_only`，两半：

- 契约半（今天**绿**，当护栏）：monkeypatch `pool.jobs.classify_job_state` 让它返回 `("夹具态", "假的")` ⇒ `tool_job_list` 的 `counts == {"夹具态": 1}`、`jobs[0]["state"] == "夹具态"`（实测今天的读数就是 `counts = {'夹具态': 1}`）；
- 源码半（今天**红**）：`inspect.getsource(pool_mcp.tool_job_list)` 不含字符串字面量「断了」（实测今天 `"断了" in src` 为 True，来源是 :1050 的行文案模板；改法是把那句文案改成从 row 里取、不写字面量）。

### 判据 5 · 「判不了」不是「这一轮已经结束」：不许进 DEAD_STATES

它不是「结束」的证据，只是「这一源不可判」。进了 DEAD_STATES 会让 registry 把活租约判死（tools/pool/registry.py:215 的 `return jobs.is_dead_state(row["state"])`）。

**钉子**（tests/test_pool_jobs.py）新增 `test_unjudged_state_is_not_a_dead_state`，五条断言：

- `"判不了" not in jobs.DEAD_STATES`；
- `jobs.is_dead_state("判不了") is False`；
- `registry._DEAD_STATES == jobs.DEAD_STATES`（复刻 tests/test_pool_registry.py:477 那条等式，但不在那个文件里加钉子）；
- 五类死态仍逐个判死、`在跑` 与 `非派活` 仍判活（复刻 :480-485）；
- `scan_jobs(diag, backlog_error="BacklogError: 试")` 产出的行 state 为「判不了」时，`is_dead_state` 仍 False。

今天这条钉子会**红在关键字上**：`TypeError: scan_jobs() got an unexpected keyword argument 'backlog_error'`（实测原文，`scan_jobs` 现签名 `(diag: Path, now: float | None = None, backlog: Mapping[str, str] | None = None) -> list[dict]`）。

### 判据 6 · 反向变异 ≥3 + 一条只改注释的安静对照

- A：把 `_state_of_log` 末支的 `backlog_error` 分岔删掉、回到 `classify_job_state` ⇒ 判据 1 必红；
- B：把 `"exit_code": 0` 加回 job_status 的 data ⇒ 判据 3 必红；
- C：把正文改回「来自 `{command}`」（并把 command 拼回去）⇒ 判据 3 必红；
- D：把 data 里的 `backlog_unavailable` 键删掉 ⇒ 判据 1 必红；
- C1（安静对照）：只改一句注释 ⇒ 六条钉子全绿。

每条真改、真跑、真还原；记改前 / 改后 sha256 与 `-k` 子集的 passed / failed 数。记录落 gates/diag/_rev_E132_result.txt（该文件尚未生成；gates/diag/* 被 .gitignore:76 忽略，不入库）。脚本必须放**主树** gates/diag/（`ROOT = __file__.resolve().parent.parent.parent`，照 gates/diag/_e132_probe_red.py:15-16 的写法），放卡树会算成卡树里的卡树。

### 判据 7 · 不许削弱 / 不许顺手改

- 除 tests/test_pool_mcp.py:365-390 补一份**可读**台账 fixture（:388-390 断言原文不动）外，下列既有钉子一个字不许动：tests/test_pool_mcp.py:190-202（:202 job_list 的 required==[]）、:217-239、:258-288、:335-344（:342-344 空树仍 is_error=False / count==0 /「没有」+「假装」）、:430-445（:436 真 stdio 调 job_list、:445 正文首段仍是「外包派活台账」）、:1111-1133、:1136-1150（:1144 land-X1.log in text、:1145 is_error False 且 found False、:1150「没有」）、:1153-1163、:1166-1176、:1179-1194（:1189 首行仍匹配 `^在飞：(是|否)`、:1190 `data["in_flight"]` 仍是 bool）；tests/test_pool_jobs.py:471-502（:493-502 八行精确等式，含 wb-006 对应台账已完结）、:518-549（真树普查）；tests/test_pool_lib.py:175-188（不传 backlog 的三键 `rows == {"101":"在跑","102":"断了","103":"已判决"}`）；tests/test_pool_registry.py:470-485；tests/test_pool_mcp_task.py:68-69；tests/test_pool_mcp_write.py:42-43；tests/test_pool_mcp_http.py:480。
- 不许把「判不了」加进 `DEAD_STATES`（判据 5），不许在 MCP 层写状态字符串常量或比 `STALL_SECONDS`（判据 4），不许改 `classify_job_state` 的三态口径与它那句 why 文案。
- 不许改 `_backlog_cards` 的「绝不抛」语义：台账缺失时 `tool_job_status` 仍要 is_error=False 且继续读落地日志。
- 不许顺手把 tools/pool/registry.py:213、tools/pool/trae_dispatch.py:304、tools/wb_status.py:186 三个 `scan_jobs` 调用点改成传 backlog —— 那是 docs/traceability.d/T-AG623.toml:25 那条 gaps 的域，另卡。
- 不许手改 docs/subsystems/pool/README.md 的生成区，只改 docs/subsystems/pool/modules.toml 的 duty 再重跑 scripts/gen_pool_readme.py。
- 不许动 docs/doc-debt-baseline.toml 的任何计数；不许为了过门而放宽任何断言。

## 交付

1. tools/pool/jobs.py：`scan_jobs` 增 keyword-only `backlog_error: str | None = None` 并透传给 `_state_of_log`；末支按「台账读不到 ⇒ 判不了」分岔（why 里同时写台账原因与原始三态读数）；模块 docstring :10 与 :16-18 的状态清单补一句「+ 台账读不到 ⇒ 判不了（这一源不可判，不是结束）」；`DEAD_STATES` 一个字不动。
2. tools/pool_mcp.py：`_backlog_cards` 能把「为什么读不到」交出去（返回 (cards, gap) 或并列一个 `_backlog_gap`），stderr 那句前缀改成不指错工具；`tool_job_list` 把 gap 传给 `scan_jobs`、data 增 `backlog_unavailable`、正文首段点名、行文案不再硬写态名（判据 4 的源码半）；`tool_job_status` 有日志支删 `command` 与 `exit_code`、加 `rendered_by`、改 :1130 正文与 :1064-1066 docstring、同步 tools/list description（:401-402）与模块表 :37-38 的说法。
3. tests/test_pool_mcp.py：新增 4 条钉子（test_job_list_says_backlog_unavailable / test_job_list_unchanged_when_backlog_readable / test_job_status_payload_has_no_invented_command / test_job_list_takes_state_from_jobs_only），并给 :365-390 补一份可读台账 fixture（断言不动）。
4. tests/test_pool_jobs.py：新增 2 条钉子（test_scan_jobs_unchanged_when_backlog_error_absent / test_unjudged_state_is_not_a_dead_state）。
5. docs/subsystems/pool/modules.toml：:72 的 duty 补「台账读不到 ⇒ 判不了」这一态；然后重跑 scripts/gen_pool_readme.py 让 docs/subsystems/pool/README.md 的生成区跟上（不许手改）。
6. 反向变异记录：gates/diag/_rev_E132_result.txt（A / B / C / D + C1 的 sha256 与 passed / failed 读数），未跟踪。
7. 卡规格 + 三片段（由落地链的 ② 文档件按台账号 T-AG638 自动生成；E132 现在还没登记进 docs/workbacklog.toml，落地前先登记）。

## 验收（三条，落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pool_mcp.py tests/test_pool_jobs.py tests/test_pool_registry.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool_mcp.py tools/pool/jobs.py tests/test_pool_mcp.py tests/test_pool_jobs.py
python -X utf8 scripts/check_derived_docs.py --check
```

改前基线（2026-11-17 实测，供对比）：tests/test_pool_mcp.py 的 `-k 'job_list or job_status or missing_artifacts'` 子集 7 passed；tests/test_pool_jobs.py 的 `-k 'scan_jobs_reports_card_and_kind or classify_job_state'` 1 passed；tests/test_pool_registry.py 的 `-k dead_states` 1 passed；ruff 输出 `All checks passed!`；scripts/check_derived_docs.py --check 两行 `[OK  ]`（50 个文件 / 19821 行 / 2026-11-17）。

## 不许做

- 不许把「台账读不到」洗成第三种**结论**：「断了」「台账已完结」「没有台账所以都算断了」都不行 —— 判不了就是判不了。
- 不许把 `backlog_unavailable` 只塞进 data 而不进正文（客户端读的是正文），也不许反过来只改正文。
- 不许在 MCP 层再判一遍状态（判据 4）：不许出现状态字符串常量、不许比 `STALL_SECONDS`、不许自己数 .verdict.txt。
- 不许让 job_status 为了「看起来可核」而真的用 subprocess 跑 wb_status.py —— 那会把只读面变成起进程的面，且 `_run` 的调用点今天只有 `lock_status` 一处（tools/pool_mcp.py:789-794 的注释写死了这条）。
- 不许给 exit_code 编一个新来源（例如 try/except 猜 0 与 1），也不许把 `command` 改名后原样留着那串命令。
- 不许改 `classify_job_state` 的三态口径、不许改 `DEAD_STATES` 的五个成员、不许动 tools/pool/registry.py 的 `_DEAD_STATES = jobs.DEAD_STATES`。
- 不许扩域去改 tools/pool/registry.py / tools/pool/trae_dispatch.py / tools/wb_status.py 三个不传 backlog 的调用点。
- 不许靠改测试让门变绿：判据 7 列出的既有钉子必须原样留着（唯一例外是 :365-390 补一份可读台账 fixture，断言不动）。
- 不许提交、不许跑全量门禁；本卡只交规格与钉子。
