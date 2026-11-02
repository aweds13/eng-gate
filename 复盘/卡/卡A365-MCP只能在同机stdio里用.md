# 卡 A365 —— MCP 只能在同机 stdio 里用：给它开一条 HTTP 传输（T-AG584）

> 台账号 `T-AG584` ｜ 分区 A（号池功能线）｜ 树 `.wt/A365` ｜ 层 实现层
> 基准提交 `68ec6c86`（主树 HEAD，E80 刚落）。
> **来路**：User said (m76234)「主要是我想远程操作怎么办」→ User said (m76323)「B」⇒
> 定案走 **给 `tools/pool_mcp.py` 加 Streamable HTTP 传输**，不做 DSH 插件。

## 要解决的问题（已实测，不是推测）

`tools/pool_mcp.py` **纯 stdio**：`grep "http.server|HTTPServer|socketserver|BaseHTTPRequestHandler|socket\."`
在整份文件里**零命中**（2762 行 / 129285 B / 干净 CRLF）。后果是**只能被同一台机器上、
由客户端起子进程**用 —— 手机、平板、另一台电脑都接不进来，`m76323` 要的「远程操作」无从谈起。

规范这一半已经查清并逐字记在 `复盘` 会话里（MCP [Transports 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)）。
本仓**不引第三方 MCP SDK**（模块头 `:25` 逐字「只用标准库」）⇒ 用 `http.server`（本仓有先例：
`tools/wb_dash.py:50 from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer`，
`:602` 默认 `--host 127.0.0.1`）。

**已有的可复用点（本卡的核心机会）**：`tools/pool_mcp.py:2545`
`def handle(message: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any] | None`
是**与传输无关的纯函数**（initialize / ping / tools/list / tools/call；通知一律 `return None`）。
HTTP 层要做的事只有「body 里的 JSON 交给它 → 把回话写成响应」，**判据一条都不用重写**。

## 判据（8 条）

1. **判据只许一份 —— `handle()` / `call_tool()` / `tool_list()` 一个字节不动。**
   HTTP 层**不许**重新实现方法分发、**不许**另写一份工具清单、**不许**碰 `WRITE_NAMES` 一族。
   ★ 钉子：`handle(` 的函数体在本笔 `git diff` 里**零改动**（按函数边界切出来比字节）。
   ★ 钉子：`pool.mcp_http` **不 import `pool_mcp`**（避免循环依赖；`handle` 是**传进去的**）。
2. **★ Origin 校验（规范 MUST）**：带 `Origin` 头的请求，其值必须命中白名单，否则
   **403 且请求体不被执行**（断言：桩住的 handle 调用次数 = 0）。
   白名单 = `TF_MCP_HTTP_ORIGINS`（逗号分隔）∪ 默认 `http://127.0.0.1:<port>` / `http://localhost:<port>`。
   **无 `Origin` 头放行** —— 理由写进 docstring：DNS rebinding 要靠浏览器发起的跨站请求，
   非浏览器客户端不带这个头；要更严就把 `TF_MCP_HTTP_REQUIRE_ORIGIN=1` 打开（这时没头 ⇒ 403）。
3. **★ 只绑回环（规范 SHOULD）**：默认 `--host 127.0.0.1`；`--host` 只接受
   `127.0.0.1` / `localhost` / `::1`，**别的值退 2 并说明理由**（不给 `0.0.0.0` 开口子 ——
   要暴露就交给隧道，不在这里绑全网卡）。
4. **★ 鉴权（规范 SHOULD）—— 不许「默认无鉴权」**：`TF_MCP_HTTP_TOKEN` **不设 ⇒ 拒绝启动**
   （退 2，把「怎么设」印出来）。带 `Authorization: Bearer <token>` 且比对用
   `hmac.compare_digest`（**不许 `==`**）；不符/缺失 ⇒ **401** + `WWW-Authenticate: Bearer`。
5. **三态与 GET（规范 MUST）**：
   - 输入是 **notification / response**（无 `id`）⇒ **202 Accepted，body 空**（`Content-Length: 0`）；
   - 输入是 **request** ⇒ **200 + `Content-Type: application/json`**（本卡**不提供 SSE**，如实写）；
   - **GET ⇒ 405**（规范：不给 SSE 就 MUST 回 405）；`DELETE` ⇒ 405（本卡无会话可终止）。
   - `Accept` 既不含 `application/json` 也不含 `text/event-stream` ⇒ **406**。
6. **版本头（规范 MUST）**：缺 `MCP-Protocol-Version` ⇒ 按 **`2025-03-26`** 假定；
   给了但不在 `KNOWN_PROTOCOLS` ⇒ **400**。（`KNOWN_PROTOCOLS` 与 `PROTOCOL_VERSION`
   **从 `pool_mcp` 传进来**，HTTP 侧不另写一份字面量。）
7. **★ 无会话 + 有上限 + 坏消息不打死服务**：
   - **不发** `Mcp-Session-Id`（本卡 stateless；理由写进 docstring：`handle()` 本来就无状态，
     发了就要维护「终止后 404」那套，本卡不做）。★ 钉子：响应头里**不出现**这个头；
     且**带了** `Mcp-Session-Id` 的请求照样正常处理（不认识 ≠ 拒收）。
   - 请求体上限**复用 `MAX_LINE_BYTES`**（32 MiB，从 `pool_mcp` 传进来），超限 ⇒ **413**、
     不许整份读进内存；**HTTP 侧不许另写 `32 << 20` 字面量**。
   - 非 UTF-8 / 非 JSON / 不是对象 ⇒ **400**（**不许 500**），服务继续接下一个请求。
8. **端到端真跑（不是桩）**：真起子进程 `python -X utf8 tools/pool_mcp.py --http --port <p>`，
   走真 socket 完成 `initialize` → `tools/list` → `tools/call`（挑一个只读工具），
   断言中文**不乱码**、`id` 原样回来、`tools/list` 的个数与 stdio 口径一致。
   ★ 端口用 `0`（内核分配）或 pytest fixture 现找的空口，**不许写死**（卡 E73：两条门抢同一端口踩过）。

## 交付

- **新** `tools/pool/mcp_http.py` —— 全部 HTTP 逻辑（`serve_http(handle, *, host, port, token, origins, max_bytes, protocols, ...)`）。
  零第三方依赖，只用标准库。**不 import `pool_mcp`**（依赖反向注入）。
- 改 `tools/pool_mcp.py` —— 只加 CLI 分支（`--http` / `--port` / `--host`）+ `_usage()` 补三行 + 模块头补一段。
  ★ **`main()` 现在「无参数 ⇒ stdio」「`--help` ⇒ usage」「别的参数 ⇒ 退 2」三条行为一字不变**
  （既有 `tests/test_pool_mcp.py:286 assert pool_mcp.serve([]) == 0` 不许改）。
- 改 `docs/subsystems/pool/modules.toml` —— **同笔**登记 `mcp_http.py`（三键 `name` / `duty` / `cli`，
  `duty` 不许写成模块名的同义重复；`cli = "无（被 tools/pool_mcp.py 调）"`）。
- **新** `tests/test_pool_mcp_http.py` —— 八条判据各至少一条钉子。
- **新** `gates/diag/_rev_A365.py` —— 反向变异（见下）。
- 卡规格本文一份。

## 验收（缺一不可，逐条给末行原文）

```bash
# ① 新钉子全绿
python -X utf8 -m pytest tests/test_pool_mcp_http.py -o addopts= -q --no-cov

# ② 既有 MCP 面一条都不许坏（七份一起跑）
python -X utf8 -m pytest tests/test_pool_mcp.py tests/test_mcp_line.py \
  tests/test_mcp_client_independent.py tests/test_pool_mcp_board.py \
  tests/test_pool_mcp_line_cap.py tests/test_pool_mcp_task.py \
  tests/test_pool_mcp_write.py -o addopts= -q --no-cov

# ③ 模块清单与目录对得上（生成器自己判）
python -X utf8 scripts/gen_pool_readme.py --check

# ④ ruff
python -X utf8 -m ruff check tools/ tests/

# ⑤ 反向变异
python -X utf8 gates/diag/_rev_A365.py
```

## 反向变异（≥6 条，每条都要真改坏 → 跑 → 咬住 → `finally` 还原 → sha 核对）

- **M1** 删掉 Origin 校验那一段 ⇒ 判据 2 的钉子必红。
- **M2** `hmac.compare_digest` 换回 `==` ⇒ 判据 4 的「比对方式」钉子必红（★ 语义钉，不是行为钉 ——
  要专门有一条钉**源码里不出现** `Authorization` 与 `==` 的裸比较）。
- **M3** notification 分支从 202 改成 200 ⇒ 判据 5 必红。
- **M4** GET 从 405 改成 200 ⇒ 判据 5 必红。
- **M5** 版本头不再校验、非法值也放行 ⇒ 判据 6 必红。
- **M6** 请求体上限改回「整份 `read()`」⇒ 判据 7 的「超限 413 且不吃进内存」钉子必红。
- **M7** 允许 `--host 0.0.0.0` ⇒ 判据 3 必红。
- **C1（对照）**：只改 docstring ⇒ 按设计**不**咬住。

## 不许做（六条）

1. **不许**改 `handle()` / `call_tool()` / `tool_list()` / `WRITE_NAMES` / `TASK_WRITE_NAMES` /
   `USAGE_WRITE_NAMES` 的任何行为（判据 1）。
2. **不许**引第三方包（`mcp` / `starlette` / `uvicorn` 一律不许），只用标准库。
3. **不许**把 `--host` 的默认值或允许集放宽到非回环地址（判据 3）。
4. **不许**给「没有 token」留默认放行路径（判据 4）。
5. **不许**改既有七份 MCP 测试来迁就本卡（② 必须原样通过）。
6. **不许**碰六份 `PROTECTED_FILES`（`docs/traceability.toml` / `docs/changelog.md` /
   `复盘/交接-重构进度.md` / `复盘/新窗口交接卡.md` / `gates/last.json` / `gates/reuse.json`）。

## 直做

按上面判据直接开工。**多行 Python 一律用 `write` 落盘再跑，不要 heredoc**（会吃掉 `\` 与 `\n`）。
★ 本仓源文件是**干净 CRLF**（`tools/pool_mcp.py` 2762 行全 CRLF）⇒ 改文本要
`text.replace("\r\n", "\n")` → 改 → 回写 `\r\n`，否则锚点命中 0 次。新文件也用 CRLF。
变异脚本必须：`_preflight()` 每条锚点恰好命中 1 次 + 每条变异各自 `try/finally` + 还原后 sha256 核对
+ 每次先清 `__pycache__` 并传 `PYTHONDONTWRITEBYTECODE=1` + `_busy()` 只认**本树**的 pytest
+ **绝不 kill 变异脚本**（卡 E74 踩过：`| tail` + `job_kill` 把文件停在半改状态）。
