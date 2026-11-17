# 卡 E134 · `_json_call` 一次没读到就整道门红：给它同款有界重试，但不许拿写请求赌

> 台账号 T-AG643｜分区 E（门禁与可信度）｜树 .wt/E134｜层 判据层｜基准 b4a1eb1d｜depends 无
> 依据：用户 m05230「改用 GitHub Actions 当云门禁，自己去探索，有想法都要联网搜索验证」；GitHub Actions 上 engineering 全量门禁（job `133805837526`，run `44013510622`，head `ccffc038`）的 `web_live` 门真红。
> 行号按 2026-11-17 主树 `b4a1eb1d` 现场（Python 3.14.6）复核：`tools/web_live_check.py` 1163 行 / 65570 B。
> 实验全部在本机做（打桩 `urllib`，不起真 uvicorn），未碰主树受保护文件。

## 要解决的问题（逐条实测，不是推测）

判据只有一条：**「一次没读到」不等于「服务坏了」**。慢机器上单次调用的偶发抖动，必须由客户端有界重试吸收；但**已经拿到状态码的绝不许重放**（那会把 403/404 洗掉），**非幂等的写请求也不许默认重放**（重放一次就多建一条）。

### 问题 1 · `_json_call` 没有重试（同一个仓里 `_lan_json` 有）

`tools/web_live_check.py:226-247` 现行全文：

```text
226	def _json_call(base: str, path: str, method: str = "GET", payload: dict | None = None,
227	               headers: dict | None = None, timeout: float | None = None) -> tuple[int, object]:
234	    url = f"{base}{path}"
235	    wait = call_timeout() if timeout is None else timeout
241	    try:
242	        with urllib.request.urlopen(req, timeout=wait) as resp:
243	            return resp.status, json.loads(resp.read().decode("utf-8"))
244	    except urllib.error.HTTPError as e:  # 4xx/5xx 也要看得到状态码
245	        return e.code, None
246	    except OSError as e:  # ★ 卡 E67：TimeoutError / URLError 原先没人接 ⇒ 抛穿成裸 traceback
247	        raise LiveCallError(method, url, wait, e) from e
```

对照 `tools/web_live_check.py:857-916` 的 `_lan_json`：`:893 attempts = 1 + lan_retry()`、`:900` 命中 `HTTPError` 时直接 `return e.code, _body(e.read())`（注释原话「★ 已拿到状态码 ⇒ 绝不重试」）、`:913-914` 打「[重试] … 没读到响应（…），再打一次」、`:916` `raise LiveCallError(..., broken_read=True) from last`。同一份文件里两条 HTTP 通道，一条有一界重试、一条没有。

探针实证（`gates/diag/_tmp/e134_json_retry_probe.py`，真模块 + 打桩：第一次超时、第二次本会成功）原样输出：

```text
=== _json_call: 第一次超时、第二次本会成功 ===
RAISED LiveCallError: PUT http://127.0.0.1:9/api/settings/ai 等了 10 秒没等到（TimeoutError: timed out）；慢机器调大等待窗：env TF_WEB_LIVE_TIMEOUT=<秒>（默认 10）
urlopen 被调用次数 = 1 (1 = 只打一次，没重试)
=== _lan_json 对照（同一个抖动）===
  [重试] GET http://127.0.0.1:9/api/summary 没读到响应（ConnectionResetError），再打一次
got (200, {'ok': True})
opener.open 被调用次数 = 2
```

### 问题 2 · GHA 上那一趟就是被这一条绊住的（不是业务坏）

job `133805837526` 的 `gates/enggate-logs/win-133805837526.log` 原文：

```text
[FAIL] web_live               exit=1  98.17s  [FAIL] 真机自检没跑完：PUT http://127.0.0.1:50280/api/settings/ai
         ★ PUT http://127.0.0.1:50280/api/settings/ai 等了 30 秒没等到（TimeoutError: timed out）
```

`TF_WEB_LIVE_TIMEOUT=30` 已经设了（适配器 `gates/diag/_tmp/gha_shim_autostart_v7.py` 里设的），仍然没等到；而服务端日志显示 `PUT /api/settings/ai status 200 ms 19.4` **是成功的** —— 客户端在等一个已经写完的响应。同一条门在本机（`gates/diag/wl-local-baseline.log`）rc=0、9 秒、六条真机子检查全 `[OK ]`。⇒ 这是慢 runner 的单次抖动，重试一次就能吸收；**不许用「把等待窗再调大」当修法**（那只是把概率推小，与卡 092 明令禁止的「用更长的固定等待顶替就绪判据」同罪）。
## 判据（7 条，逐条可执行）

### 判据 1 · 有界重试，默认 1 次，env 可关

新增 `json_retry() -> int`：读 `TF_WEB_LIVE_JSON_RETRY`（新常量 `JSON_RETRY_ENV`，默认值 `DEFAULT_JSON_RETRY = 1`）。坏值 / 负数 ⇒ 退回默认；`0` 是**合法**值（明确关掉）。**不要**复用 `TF_WEB_LIVE_RETRY`：那个旋钮的幂等面是 `_lan_json`（只打 GET 与 `POST /api/sync/import`），而 `_json_call` 的 47 个 POST 会建任务 / 建课程，两者的安全前提不是一回事。

### 判据 2 · 只重放「没读到响应」的那一类，三种情形一票否决

照 `_lan_json` 的口径分三态，其中**有一处与 `_lan_json` 有意不同**，代码注释必须写出差异与理由：

- **已拿到状态码（`urllib.error.HTTPError`）⇒ 绝不重试**（`return e.code, None` 原样）；重放会把 403/404 洗成 200。
- **超时（`WAIT_TIMEOUTS`）⇒ 允许重试，但只对判据 3 认定的幂等调用**。`_lan_json` 的超时那一支是直接抛（`:907-908`），因为它的调用面含整包体 `POST /api/sync/import`；`_json_call` 的 78 个默认 GET 是纯读，重放安全。这处差异**不许静默**。
- **真的没送到（`ConnectionRefusedError` / `socket.gaierror` / `NO_ROUTE_ERRNOS`）⇒ 不重试**，直接 `LiveCallError`（服务没起来时重放只是白等）。`_read_broken()`（`:203-213`）已经把这一类和「连上了但对端先关」分开了，直接用它。

### 判据 3 · 幂等面：GET/HEAD 默认可重放，写请求要调用点显式声明

`_json_call` 的 135 个调用点实测分布：**默认 GET 78 + 显式 `"GET"` 1**、`POST` 47、`PUT` 6、`PATCH` 2、`DELETE` 1。写方法默认**不重放**（`POST /api/tasks` 重放一次就多建一条任务，后面 `/api/ledger/output` 的计数判据会跟着错）。

做法：给 `_json_call` 加关键字参数 `retry_ok: bool = False`；重放条件 = `method in ("GET", "HEAD") or retry_ok`。把**确属幂等**的写调用点显式标上 `retry_ok=True`：
- `:283` / `:294` / `:295` `PUT /api/settings/attach`（设一个值，设两次同一个值结果一样）
- `:400` / `:421` `PUT /api/settings/ai`（开关）
- `:652` `PUT /api/settings/notify`（开关）

**不许**给 `POST /api/tasks`、`POST /api/courses`、`POST /api/ai/tasks`、`POST …/to-review`、`PATCH`、`DELETE` 任何一处标 `retry_ok=True`。

### 判据 4 · 重放日志与「重试用尽」的错必须点名

每次重放打一行 `  [重试] {method} {url} 没读到响应（{type(last).__name__}），再打一次`（与 `_lan_json:913-914` 同形）；用尽后 `raise LiveCallError(method, url, wait, last, broken_read=True)` —— 带 `broken_read=True` 才会在消息尾部补「★ 这是**没读到响应**（连上了、对端先关了连接）——不等于服务端没回 401，也不等于配对失败」（`tools/web_live_check.py:163-165`，卡 E85 的钉子）。

### 判据 5 · 既有二十七条钉子一条都不许改

`tests/test_web_live_timeout.py` 九条全绿且**逐字不动**，尤其：`test_timeout_error_names_the_endpoint_and_the_wait`（消息含 `/api/settings/ai`、`PUT`、`TimeoutError`、`"10"`）、`test_refused_connection_is_also_named`（拒连仍抛 `LiveCallError` 且含 `URLError`）、`test_http_error_still_returns_its_status_code`（`(404, None)`）、`test_wait_window_actually_reaches_urlopen`（`seen["timeout"] == 42.0`）。另 `tests/test_web_live_lan_timeout.py` 10 条、`tests/test_web_live_read_failure_is_not_401.py` 8 条同样不动。

### 判据 6 · 七条新钉子

新文件 `tests/test_web_live_json_retry.py`（打桩 `wlc.urllib.request.urlopen`，与既有文件同款装模块手法）：
1. `test_json_retry_defaults_to_one_and_is_env_tunable` —— 不设 env ⇒ `json_retry() == 1`；`TF_WEB_LIVE_JSON_RETRY=3` ⇒ 3；`0` ⇒ 0。
2. `test_junk_retry_value_falls_back_instead_of_going_infinite` —— `"abc"` / `"-1"` / `""` ⇒ 回 1；**上限也要有**：`"9999"` 不许真的打 9999 次（封顶写死并断言，或直接拒绝）。
3. `test_a_status_code_is_never_retried` —— `urlopen` 恒抛 `HTTPError(404)` ⇒ `urlopen` 被调用 **1** 次、返回 `(404, None)`。
4. `test_timeout_then_success_retries_only_once` —— 第一次 `TimeoutError`、第二次 200 ⇒ 返回 200，计数 = 2。
5. `test_post_is_not_retried_by_default` —— 第一次 `TimeoutError` 的 `POST` ⇒ 抛 `LiveCallError`，计数 = 1。
6. `test_explicitly_idempotent_write_is_retried` —— 同一场景加 `retry_ok=True` ⇒ 计数 = 2、返回 200。
7. `test_retry_zero_means_no_second_request` + `test_exhausted_retry_is_named_broken_read` —— `TF_WEB_LIVE_JSON_RETRY=0` ⇒ 计数 1；用尽后 `err.broken_read is True` 且消息含 endpoint 与方法。

### 判据 7 · 反向变异（真改、真跑、真还原 + sha256）

三处各改一次，改完跑 `tests/test_web_live_json_retry.py`：
- A：把 `attempts = 1 + json_retry()` 改成 `attempts = 1` ⇒ 钉子 4 / 6 必红；
- B：把 `except urllib.error.HTTPError` 那支挪进重试循环并重放 ⇒ 钉子 3 必红；
- C：把 `retry_ok` 默认值改成 `True` ⇒ 钉子 5 必红。

每条真改、真跑、真还原；记改前 / 改后 `sha256(tools/web_live_check.py)` 与 `-k` 子集的 passed/failed 数，记录落主树 `gates/diag/_rev_E134_result.txt`（脚本放主树 `gates/diag/`，`ROOT = __file__.parent.parent.parent`；放卡树会算成卡树里的卡树）。

## 交付

1. `tools/web_live_check.py`：`DEFAULT_JSON_RETRY` / `JSON_RETRY_ENV` / `json_retry()`（放在 `lan_retry()` 之后，:201 附近）、`_json_call` 加 `retry_ok` 参数与重试循环、判据 3 列的 6 个调用点标 `retry_ok=True`。
2. `tests/test_web_live_json_retry.py`：判据 6 的七条钉子。
3. `docs/subsystems/` 下 web_live 那页补一句：慢机器上「一次没读到」由 `TF_WEB_LIVE_JSON_RETRY` 吸收，判据强度不变。（先 `python -X utf8 scripts/check_docs.py --mode report` 确认那页路径存在再写反引号。）
4. 卡规格（本文件）。三片段由落地链 ② 按台账号 T-AG643 自动生成，本卡不手写。

## 验收（三条，落地前自跑）

```bash
python -X utf8 -m pytest tests/test_web_live_json_retry.py tests/test_web_live_timeout.py tests/test_web_live_lan_timeout.py tests/test_web_live_read_failure_is_not_401.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/web_live_check.py tests/test_web_live_json_retry.py
python -X utf8 -m mypy tools/web_live_check.py
```

读数门槛：第一条 **全绿**（既有 27 条一条不许红）；第二条 `All checks passed!`；第三条 `Success: no issues found`。

## 不许做

- 不许把默认等待窗从 10 秒改大（`test_wait_window_defaults_to_ten_and_is_env_tunable` 钉住），也不许把重试次数默认调成 >1。
- 不许对 `HTTPError`（已拿到状态码）重试 —— 判据 2 / 钉子 3 钉住。
- 不许给任何非幂等写调用点标 `retry_ok=True`（判据 3 末段逐条列了名单）。
- 不许把 `_json_call` 与 `_lan_json` 合并成一个函数（两者的失败语义不同：`_json_call` 拒连抛 `LiveCallError`，`_lan_json` 拒连回 `(0, None)`，各有各的钉子）。
- 不许改 `mark_live_error()` 与 `main()` 的收口（卡 E67 的判据：等不到要落成 `checks[...] = False`，不许洗成通过）。
- 不许在反引号里写未来才生成的路径（三片段、变异记录一律不加反引号）。

## 直做（已实测的探针）

- 复现「只打一次」：`python -X utf8 gates/diag/_tmp/e134_json_retry_probe.py`（真模块 + 打桩，输出见上）。
- 调用点分布随时可重算：`gates/diag/_tmp/e134_callsites.py`。