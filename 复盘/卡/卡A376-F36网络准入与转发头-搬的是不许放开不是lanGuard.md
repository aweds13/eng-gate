# 卡 A376：F36 网络准入、CIDR 白名单、TLS 与转发头 —— 本仓要搬的是「不许放开」，不是 lanGuard

> 台账号 `T-AG664`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A376`｜层 判据层 + 传输面｜基准 `6573205b`（立卡时主树 HEAD，2026-11-20 02:20 实读）｜depends E94、E103、E143、A372
> depends 说明：E94 是 `tools/pool/gateway.py` 的原始持有卡（安全口径与四条路径都在它里面），E103 是「启动面不许 fail-open」那条判据的持有卡，E143 与 A372 的 `files` 与本卡**精确相交**（都含 `tools/pool/gateway.py` 与 `tests/test_pool_gateway.py`）—— 不写 depends 会被 `tools/pool/plan.py:262-272` 的冲突域校验拒单（T-G119：同域两卡只要有依赖路径就允许共存）。
> 基准说明：起草时主树 HEAD = `7a4cc513`（`git rev-parse --short HEAD` 实读）。本文所有行号都在这棵树上逐行读过；`tools/pool/gateway.py` 1300 行、`tests/test_pool_gateway.py` 1150 行、`tools/pool/platforms.toml` 246 行。落地前请按当时 HEAD 重核一次再引用。
> 依据：`gates/diag/_magpie_scope.md:44`（F36 判定 PORT / landed no）、`gates/diag/_magpie_features.md:320-326`（功能清单，核实级别「仅文档」）、原件 `D:/repo/program/_ext/magpie-main/internal/gateway/{lan,cors,allow,tls}.go`。

## 前情

F36 在 magpie 里是四件事捆在一起：**谁能进**（`MAGPIE_ALLOW_IPS` 的 IP/CIDR 白名单）、**怎么算「远端」**（六个转发头任一出现即视为远端，`#1022`）、**TLS**（`MAGPIE_TLS_CERT` / `MAGPIE_TLS_KEY` + 证书热加载）、**DNS rebinding 与 Origin 两道**（`Origin: null`、`localhost` 子域一律 403）。

magpie 为什么需要这一整套？因为它**在回环上不要 key**。原件逐字（`_ext/magpie-main/internal/gateway/cors.go:22-23`）：

```
not an agent the user started, and on loopback a call needs no key, so without one any script
served at that origin ... could spend the user's subscriptions
```

本仓的号池网关**没有这个前提**：它恒需 Bearer，且没有 token 就拒绝建服务。所以 F36 里真正需要移植的不是 lanGuard 那套「地址判定 + 反弹击退」，而是**把「已经收窄的口子不许再放开」钉成可核证据** —— 这一条今天**一条测试都没有**。

## 结论：判 PORT（判据层 + 传输面），但搬的是「不许放开」

| 子项（_magpie_features.md:323-325） | 原件 | 本仓今天 | 判定 |
|---|---|---|---|
| `MAGPIE_ADDR` 绑地址 | `lan.go` 全套 lanGuard | `check_host` 只收三值（`gateway.py:968-976`），无第二套 host 来源 | PORT（钉现状） |
| `MAGPIE_ALLOW_IPS`（IP/CIDR） | `allow.go:32` `const AllowIPsEnv = "MAGPIE_ALLOW_IPS"` | `tools/ scripts/ tests/` 里 cidr / allow_ips 零命中 | SKIP_NOT_APPLICABLE（无地址维度可白名单：服务只可能在回环） |
| 六转发头即远端（`#1022`） | `lan.go:666` `var forwardHeaders = []string{...}` | 零命中；且**源码一次都不读 Host**（AST：497 个字符串常量里没有 `"Host"`） | SKIP_NOT_APPLICABLE（没有「远端」这个态）+ 反面钉子 |
| `MAGPIE_TRUST_PROXY` | `lan.go:681-684` `func trustProxy()` | 环境变量只有三个 `TF_POOL_GATEWAY_*`（TOKEN / ORIGINS / REQUIRE_ORIGIN），`TF_POOL_GATEWAY_HOST` 不存在 | SKIP_NOT_APPLICABLE |
| TLS（证书热加载） | `tls.go:33-34` `TLSCertEnv` / `TLSKeyEnv` | `import ssl` / `SSLContext` / `certfile` 零命中；AST 导入表里没有 `ssl` / `socket` | SKIP_NOT_APPLICABLE（套隧道是既定口径：`gateway.py:86`「远程访问走 SSH / frp 隧道」） |
| Origin 两道（`null`、`*.localhost`） | `cors.go:34` / `cors.go:41-43` | **已有**：`origin_allowed`（`gateway.py:1008-1011`）+ `_gate`（`:1050-1061`） | PORT（补 `null` 与 `*.localhost` 两个具体值的钉子） |

一句话：**magpie 的准入是「有地址、有远端、可选不要 key」三件事的解；本仓这三个前提一个都不成立**，所以要写的是「边界不许被人推开」的哨兵测试，不是把 lanGuard 翻成 Python。

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 三个值只写在常量里，没有任何断言挡人加第四个

`tools/pool/gateway.py:86-87`：

```
#: 只认回环。**没有例外**：不给 0.0.0.0 开口子（远程访问走 SSH / frp 隧道）。
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
```

现有钉子只挡「坏值被收」（`tests/test_pool_gateway.py:516-525` 的 `test_check_host_rejects_non_loopback`，参数化六个坏值），**不挡「好集合被放宽」**：往 `ALLOWED_HOSTS` 里加一个 `"0.0.0.0"`，那条测试依然全绿（它只调 `check_host("0.0.0.0")` 的入参，不看集合本身）。`ALLOWED_HOSTS` 在 `:72-79` 的 `__all__` 里是公开符号，改它不需要动任何测试。

### 缺口 2 · 伪造 Host 与转发头没有任何测试（今天靠「没实现」）

`tools/pool/gateway.py:1052` / `:1056` 是 `_gate` 唯一读头的地方：

```
if not origin_allowed(self.headers.get("Origin"), self.server):
...
if not bearer_ok(self.headers.get("Authorization"), str(self.server.token)):
```

**源码里 `get("Host")` 一次都没有**（AST 实测：497 个字符串常量中无 `"Host"`）。这是「安全靠没写」，不是「安全靠判据」：下一个人为了打日志顺手读 `self.headers.get("Host")` 做分支，不会有任何测试变红。另外 `tests/` 全量里 `Forwarded` / `X-Forwarded-For` / `X-Real-IP` **零命中**（`grep -rn` 实跑 0 行）。

实测读数（本机真服务，`build_server(forward, host="127.0.0.1", port=0, token="tok", pool="codebuddy", root=<tmp>)`）：带合法 Bearer 的 `GET /v1/models`，基线 200 / 体长 86；加 `Host: evil.example` 仍 200 且**响应体与基线逐字节相同**；再加六个转发头（`Forwarded`、`X-Forwarded-For`、`X-Real-IP`、`Cf-Connecting-IP`、`True-Client-IP`、`Tailscale-User-Login`）仍 200 且逐字节相同；`forward` 桩调用 **0** 次。读数成立，但**没有一条测试记着它**。

### 缺口 3 · 「没开的口子」只有一半有钉子

`tools/pool/gateway.py:1070-1077` 三个方法直调 405，`:1079-1082` 是那条 405：

```
self._fail(405, "本网关只有 POST /v1/chat/completions、POST /v1/messages、"
                 "GET /v1/models、GET /v1/pool/routes 四条路径。",
           headers=(("Allow", "GET, POST"),))
```

而 `OPTIONS` **连方法都没有**（`grep -c do_OPTIONS tools/pool/gateway.py` = 0），实测回 **501**（`BaseHTTPRequestHandler` 的默认错误页，HTML）。`tests/test_pool_gateway.py` 里 `OPTIONS` **零命中**。

Origin 侧：`test_http_origin_whitelist`（`:699-709`）只测了任意 `evil.test`，**`Origin: null` 与 `*.localhost` 这两个 magpie 专门点名的形状没有测试**。实测：`Origin: null` ⇒ 403（「来源不被允许」）；`Origin: http://a.localhost` ⇒ 403；`Origin: http://127.0.0.1:<port>` ⇒ 200。

### 缺口 4 · 路径表「恰四键」没有断言，加一条谁都不知道

`tools/pool/gateway.py:98-104`：

```
#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。
PATHS: dict[str, tuple[str, str]] = {
    "/v1/chat/completions": ("POST", PROTOCOL_CHAT),
    "/v1/messages": ("POST", PROTOCOL_MESSAGES),
    "/v1/models": ("GET", ""),
    "/v1/pool/routes": ("GET", ""),
}
```

`test_http_only_four_paths`（`:686-696`）只验了三条**具体**的反例，没验集合本身 { `len(PATHS) == 4` }。实测 `sorted(gateway.PATHS)` = `['/v1/chat/completions', '/v1/messages', '/v1/models', '/v1/pool/routes']`。

### 缺口 5 · 传输层开关与「第二个 host 来源」没有任何守卫

`tools/pool/gateway.py` 全文件 `os.environ` 命中 **4 行**（`:887` 取凭据值、`:1281`/`:1282`/`:1283` 取三个 `TF_POOL_GATEWAY_*`），`getenv` **0 行**。这既是现状，也是唯一挡「从环境变量放宽」的东西 —— 但没人钉。同理 `platforms.toml`（246 行）的键名实测为 `amount_path` / `auth_kind` / `base_urls` / `chat_urls` / `claim_flow` / `label` / `local_archive` / `note` / `pitfalls` / `probe` / `probe_url` / `quota_flow` / `schema` / `source` / `supported` / `token_env` / `token_file` / `token_key` / `unit` / `updated_at` / `verified`，**没有 host / port / tls / listen / bind / addr**（`grep -E "^\s*(host|port|tls|listen|bind)\s*="` 零命中）。

### 缺口 6 · 端口与编排现状没人记，「以为 stack.py 会起它」是空想

`tools/pool/gateway.py:84-85`：

```
#: 与 pool_mcp --http 的 8765 错开：两个服务面不许抢同一个端口。
DEFAULT_PORT = 8766
```

实测 `8766` 在生产文件里只出现 **3 处**（`tools/pool/gateway.py:85`、`docs/subsystems/pool/modules.toml:58`、`docs/subsystems/pool/README.md:26`）；`grep -c "gateway" tools/stack.py` = **0**（`tools/stack.py:105` 起的 `COMPONENTS` 五件里没有它）；`gates/diag/gate_lock.py:92` 的 `GATE_PORTS = (8531, 8532, 8541, 8542, 8543, 8544)` 与它不相交（`8766 in gate_ports()` = False）。⇒ **网关今天只能手工 `python tools/pool/gateway.py` 起**，这是「有代码没接线」，不是「已经跑在 8766 上」。

## 判据（六条，逐条给「怎么证明」）

全部钉在**既有** `tests/test_pool_gateway.py`（不新建文件）：复用文件里的 `start_server` / `_request` / `_header` / `_Stub` / `_ok` 夹具，测量口径与本文件其余 96 条完全一致。

### 判据 1 · `ALLOWED_HOSTS` 恰好三个值，且不存在第二个 host 来源

**怎么证明**：新 `test_f36_allowed_hosts_is_exactly_three`。

- 运行时断言：`sorted(gateway.ALLOWED_HOSTS) == ["127.0.0.1", "::1", "localhost"]`。
- AST 断言（本文件 `:36` 已 `import ast`，`test_bearer_ok_uses_compare_digest`（`:573`）示范了同一手法）：取 `gateway.py` 源码，`ast.parse` 后收集全部 `ast.Constant` 里的 `str`，断言 `"0.0.0.0"` 与 `"::"` **不在**常量集里（今天 497 个常量里确实没有）。
- 字面断言：`"TF_POOL_GATEWAY_HOST" not in 源码`（今天 False ⇒ 通过）。

### 判据 2 · 伪造 Host + 六个转发头拿不到任何额外东西

**怎么证明**：新 `test_f36_host_and_forward_headers_change_nothing`（`start_server` 起真服务）。

1. 基线：`_request(port, "GET", "/v1/models")` ⇒ 200，记 `body0`。
2. `_request(port, "GET", "/v1/models", headers={"Host": "evil.example"})` ⇒ 200 且 `body == body0`。
3. 再叠六个转发头（`Forwarded: for=10.0.0.1` / `X-Forwarded-For: 10.0.0.1` / `X-Real-IP: 10.0.0.1` / `Cf-Connecting-IP: 10.0.0.1` / `True-Client-IP: 10.0.0.1` / `Tailscale-User-Login: evil@example.test`）⇒ 200 且 `body == body0`。
4. `stub.calls == []`（这三条 GET 一次都没走到转发）。

（`_request` 的 `merged.update(headers or {})`（`:663`）会把 `Host` 原样带下去；本机实测 http.client 确实照发，服务端读到 `host = evil.example`，不必 `putrequest`。）

### 判据 3 · 没开的口子仍然没开：`Origin: null` / `*.localhost` / `OPTIONS` / `PUT`

**怎么证明**：新 `test_f36_origin_null_and_localhost_subdomain_still_refused` + `test_f36_options_and_put_stay_unavailable`。

- `_request(port, "GET", "/v1/models", headers={"Origin": "null"})` ⇒ 403，且体里 `permission_error`；`stub.calls == []`。
- `headers={"Origin": "http://a.localhost"}` ⇒ 403。
- 对照（证明不是把 Origin 一刀切）：`headers={"Origin": f"http://127.0.0.1:{port}"}` ⇒ 200。
- `_request(port, "OPTIONS", "/v1/chat/completions")` ⇒ **501**（基类无 `do_OPTIONS`），且 `body` 里没有 `"chat/completions"` 之外的路由信息 —— 这条同时钉住「别为了过 CORS 预检而补一个 do_OPTIONS」。
- `_request(port, "PUT", "/v1/chat/completions")` ⇒ 405 且 `_header(headers, "Allow") == "GET, POST"`。

### 判据 4 · 路径表恰好四键，且没有任何 `/v1/magpie/` 前缀的常量

**怎么证明**：新 `test_f36_paths_table_is_exactly_four`。

- `sorted(gateway.PATHS) == ["/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes"]`（`len == 4` 由列表相等隐含）。
- AST 常量集里 `[c for c in consts if c.startswith("/v1/magpie/")] == []`。
- 行为对照（本卡与 F37 共用的那条读数）：带**合法** Bearer 的 `/v1/magpie/heap`、`/v1/magpie/cpu?seconds=30`、`/v1/magpie/goroutines` ⇒ 全部 404 且体里 `not_found_error`；而 `/v1/models` 去掉 token ⇒ 401 —— 证明那三条 404 **不是**鉴权挡的。

### 判据 5 · 源码里没有任何传输层 / 准入层开关

**怎么证明**：新 `test_f36_no_transport_layer_switches`（纯 AST + 文本，不起服务、不联网）。

- AST 导入表（`ast.Import` / `ast.ImportFrom`）里 `ssl` / `socket` **都不在**（今天实测导入表 = `__future__, argparse, collections.abc, contextlib, dataclasses, datetime, email.utils, hmac, http.server, json, os, pathlib, pool, pool_accounts, pool_quota, sys, time, typing, urllib.error, urllib.parse, urllib.request`）。
- 字符串常量里**没有一个**包含（大小写无关）`x-forwarded-for` / `x-real-ip` / `cf-connecting-ip` / `tailscale-user-login` / `trust_proxy` / `cidr` / `allow_ips` / `certfile`。
- 反向：`"0.0.0.0"` 只出现在**注释与 docstring**（`:86` / `:969` / `:974` 三处文本），不在任何 `ast.Constant` 字符串里 —— 这条把「哪天有人写 `if host == "0.0.0.0"` 放行」变成红。

### 判据 6 · 端口与接线现状被记着（8766 一处、stack.py 不编排）

**怎么证明**：新 `test_f36_port_8766_is_declared_once_and_not_orchestrated`。

- `gateway.DEFAULT_PORT == 8766`；`gateway.DEFAULT_HOST == "127.0.0.1"`。
- 读 `tools/stack.py` 源码断言 `"gateway" not in text`（今天 `grep -c` = 0）。
- `gateway.DEFAULT_PORT not in gates/diag/gate_lock.py 的 GATE_PORTS`：用 `importlib` 载入 `gates/diag/gate_lock.py` 太重，改为读文本断言 `"8766" not in gate_lock 源码`（今天成立，且 `gate_lock.py` **被 git 跟踪**，读它安全）。

## 反向变异（至少三条，逐条锚点原文，另加一条只改注释的安静对照）

写入 `gates/diag/_rev_A376.py`（照 `_rev_A368.py` 体例：`run_pytest` 用 `-o addopts= -q --no-cov -p no:xdist`、`cwd=.wt/A376`；每条先数锚点出现次数，不等于 1 就报「定位失败」；try/finally 还原并打印 sha256 前 16 位）。

| # | 改哪一行（锚点原文，实测 `count == 1`） | 改成 | 应该变红的判据 |
|---|---|---|---|
| M1 | `ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})` | 集合里加 `"0.0.0.0"` | 判据 1（列表相等）、并且既有 `test_check_host_rejects_non_loopback` 也会红 |
| M2 | `if not origin_allowed(self.headers.get("Origin"), self.server):` | `if False and not origin_allowed(...):` | 判据 3（`Origin: null` 会变 200） |
| M3 | `    "/v1/pool/routes": ("GET", ""),` | 其后追加一行 `    "/v1/magpie/heap": ("GET", ""),` | 判据 4（键集合不再相等）、F37 的判据 1 也会红 |
| M4 | `        self._fail(405, "本网关只有 POST /v1/chat/completions、POST /v1/messages、"` 前的 `def do_PUT(self) -> None:` 分支 | 把 `self._method_not_allowed()` 换成 `self._dispatch("PUT")` | 判据 3（`PUT` 不再回 405，而回 404 —— 断言写 `== 405` 就红） |
| Q（安静对照） | `#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。` | 改成任意别的注释文字（例如「#: 四条路径：两条 POST、两条 GET。」） | **一条都不许红**（证明新钉子钉的是行为与常量，不是注释） |

## 交付

| 文件 | 改什么 |
|---|---|
| `tests/test_pool_gateway.py` | 新增六条 `test_f36_*`；文件头的钉子表（`:5-28`）加一行；**不动**任何既有测试、不动任何既有夹具的默认参数 |
| `复盘/卡/卡A376-F36网络准入与转发头-搬的是不许放开不是lanGuard.md` | 本卡规格入库版（落地链自动补 `docs/changelog.d/` 与 `docs/traceability.d/` 片段） |

`tools/pool/gateway.py` **一个字都不改**（本卡只加钉子）。若落地时发现必须改它（例如判据 2 竟不成立），就地停下改判 SKIP，不要顺手改生产代码。

## 验收

```bash
cd .wt/A376
python -X utf8 -m pytest tests/test_pool_gateway.py -k "f36 or http_only_four_paths or requires_bearer_token or origin_whitelist or check_host_rejects or build_server_requires_token" -q -o addopts= --no-cov
# 期望：既有 10 条 + 新增 6 条全绿；今天既有 10 条的实测读数是「10 passed, 86 deselected」
python -X utf8 -m ruff check tests/test_pool_gateway.py
python -X utf8 gates/diag/_rev_A376.py      # 末行：「结论：4/4 条全部咬住 + 安静对照全绿，收尾绿。」
```

已知噪音：`tests/test_pool_gateway.py` 的 `:548` / `:561` 起子进程（`subprocess.run` + `NO_WINDOW`），在本机偶发 `PermissionError: [WinError 5]`（`tests/conftest.py:76-80` 记着这条与 `-k` 无关的既有噪声）；裸 `ThreadingHTTPServer` 收尾偶发打一条 `ConnectionResetError: [WinError 10054]`，都不是本卡引入的。

## 不许做

- **不许**放宽 `ALLOWED_HOSTS` / `DEFAULT_HOST`（`tools/pool/gateway.py:83` / `:87`）。判据 1 就是钉死它；需要远程访问一律套 SSH / frp 隧道（`:86` 逐字）。
- **不许**给 `_Handler` 补 `do_OPTIONS`（判据 3 把 501 当成正确行为钉住）。要过 CORS 预检就在客户端解决，不在服务面开端。
- **不许**动 `tools/pool/gateway.py` 的任何既有判据与钉子：`_gate`（`:1050-1061`）、`bearer_ok` 的常量时间比较（`:998-1005`）、`check_host`（`:968-976`）、`build_server` 的 fail-closed（`:1219-1242`，含 `:1233` 卡 E103 那条注释所指的语义）、`PATHS`（`:99-104`）。
- **不许**碰生产调用面：`tools/pool/route.py`（选号真源）、`tools/pool/model_registry.py`、`tools/pool/mcp_http.py`（另一套 token 的服务面）、`tools/stack.py`（编排）。
- **不许**在卡域 `files` 里写通配或目录（`tools/pool/plan.py:61-64`：`*` `?` `[` 一律拒单；`files_intersect()` 是精确字符串匹配）。
- **不许**碰 `tools/pool/plan.py:46-53` 的六份 `PROTECTED_FILES`（`docs/traceability.toml` / `docs/changelog.md` / `复盘/交接-重构进度.md` / `复盘/新窗口交接卡.md` / `gates/last.json` / `gates/reuse.json`）。
- **不许**改仓外文件：`D:/repo/infra/**`（号池账本、模型开关）一个字节都不动。
- **不许**在本卡里新增任何 TLS / 证书 / 转发头**实现**。本卡只出钉子；要真做 TLS 是另一张卡（且大概率 SKIP：隧道是既定口径）。

## 与已完成卡的关系

- **E94**（`tools/pool/gateway.py` 原始卡）：建立了 `ALLOWED_HOSTS` / `check_host` / Bearer / Origin / 32 MiB 上限。本卡只补「集合与路径不许被放宽」的哨兵。
- **E103**（启动面不许 fail-open）：`build_server` 的 `token` 为空即抛 `ConfigError`（`:1224-1230`）、`RouteError` 即退 2（`:1285-1289`）。本卡的判据 4/6 与它同向，不重复钉它的文案。
- **E143 / A372**（pending，`files` 与本卡精确相交）：本卡不改 `gateway.py`，只加测试 ⇒ 冲突域相交但可共存（`plan.py:262-272` 的依赖路径）。
- **F37**（同批起草）：`/v1/magpie/*` 三条 404 的读数两卡共用，但断言分居两个文件（本卡在 `tests/test_pool_gateway.py`，F37 在 `tests/test_magpie_diag_scope.py`），互不 import。

## 未坐实项（草稿如实标注，别当成结论）

1. **没有起真进程验证「监听日志」**：判据里没有一条读 `serve_http` 的 `[pool-gateway] 监听 …`（`:1256-1257`）。要钉它得真起 `main`，会占端口、会和 `:548` 那两条 subprocess 测试抢资源，本轮判定不值当。**未取证**。
2. **`*.localhost` 的完整形状没扫**：只实测了 `http://a.localhost` ⇒ 403。`http://localhost.evil.test`、`http://LOCALHOST:127.0.0.1` 这类未测；判据 3 只钉两个具体值，别把它写成「所有 localhost 子域都被挡」。
3. **IPv6 面没测**：`ALLOWED_HOSTS` 含 `::1`，但本机探针全部走 `127.0.0.1`。`--host ::1` 起服务后 `server_address` 的形状、`loops` 拼出的 `http://localhost:<port>` 是否仍匹配 —— **未取证**。
4. **magpie 原件里 `allow.go` 的 CIDR 语义没有逐条对照**（如「空列表 = 全放」`allow.go:35`）。因为本仓判定该子项 SKIP，所以只引了常量行与函数名，没做行为级比对。
5. **端口冲突面未扫全**：只确认 8766 不在 `gate_lock.GATE_PORTS` 里、不在 `stack.py` 里；`8766` 是否与用户本机其他常驻服务撞车，**未取证**（那属于运行期事实，写进卡里会过期）。

（草稿：只读勘察产物，未落盘入库。写入者 T-AG664 待填。）
