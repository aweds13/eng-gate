# 卡 E103 · magpie 的默认策略 `smart` 在 pool 侧调不到：路由名归一 + 不认识的要说话

> 台账号 `T-AG612`｜分区 E（门禁与可信度）｜树 `.wt/E103`｜层 判据层｜基准 `e8b86dbb`｜
> 依据：用户 m92988「把 magpie 移植好（同协议直通 + 选号 + 失败分类 + 留痕），再把 pool 的使用打磨好」。

## 要解决的问题（逐条实测，不是推测）

探针 `gates/diag/_probe_e103.py` 在 `e8b86dbb` 上跑出来的三行读数：

```
'smart' in BUILTIN            -> False
apply_strategy('smart', [95%, 10%])  -> [0, 1]     # 恒等，等于「按列出顺序」
smart_order(            [95%, 10%])  -> [1, 0]     # 真正的 Smart 会先上 10% 那个
```

于是**运维在命令行写 `--routing smart`（magpie 的默认值），网关静默退回列出顺序**，
日志里一个字的抱怨都没有。同族还有三处：

1. **空串的语义正好相反**。原件 `routes.Find`：`if routing == "" { return Smart, true }`；
   本仓 `apply_strategy("")` 走 `name not in BUILTIN` ⇒ 恒等。
2. **名字写错也不说话**。原件 `parseRouting`（`internal/cli/groups_cli.go:155-170`）不认识就退错
   `routing %q is not one magpie has: …`；本仓 `apply_strategy("totally-bogus")` 与
   `apply_strategy("order")` 的返回值**一模一样**，调用方无法区分。
3. **别名一个都不认**。原件有一整张 `routingNames` 表（大小写不敏感 + TrimSpace），
   `least-used` / `In-Order` / `fastest` / `speed` / `wrr` 都是合法输入；本仓只认七个裸值。

生产侧唯一调用点：`tools/pool/gateway.py:400-404 _order()` ⇒ `pool_route.apply_strategy(routing, …)`；
`routing` 来自 `--routing`（`gateway.py:1068`，默认 `order`）或 `_Server.routing`（:1011）。
`docs/subsystems/pool/modules.toml` 里 route.py 那条「`smart_order`/`apply_strategy` 零生产调用方」
**已经过期**（本卡顺手改真）。

## 判据（五条）

### 判据 1 · 名称归一表照抄原件，不认识就点名（`parse_routing`）

新增 `SMART = "smart"` / `MANUAL = "manual"` 与 `ROUTING_ALIASES`（canonical → 别名元组），
`parse_routing(name: str) -> str`：先 `strip()`、再 `lower()`，逐条比 `value / name / also`；
**空串 ⇒ `SMART`**（原件语义）；都不中 ⇒ 抛 `RouteError`，消息里带**收到的原值**与**可用名字全表**。
`<plugin>/<name>` 形态：本仓没有插件路由 ⇒ 抛 `RouteError` 并**明说原件支持、本仓不支持**
（不许静默当未知名字吞掉）。

★ `BUILTIN` **不动**：它逐字等于原件七个常量（`tests/test_pool_route_strategies.py:48` 的钉子），
`smart` 是**默认值**不是第八个内置策略 —— 进 `BUILTIN` 就等于改了那份外部契约。

**钉子**：`tests/test_pool_route_strategies.py` 新增参数化
`test_parse_routing_matches_magpie_name_table`（源头是 `internal/cli/groups_cli_test.go:79` 的
`{"smart": "", "": "", "order": "order", "In-Order": "order", "least-used": "usage",
"Fastest": "fast", "speed": "fast", "speed-first": "fast"}` 再加本仓的 `pace/weight/free/manual`）；
`::test_parse_routing_rejects_unknown_and_names_it`（`RouteError`、消息含原值）；
`::test_parse_routing_says_plugins_are_not_supported`（`acme/x` ⇒ RouteError、消息含「插件」）；
`::test_builtin_still_has_no_smart`（`"smart" not in BUILTIN and len(BUILTIN) == 7`）。

### 判据 2 · `smart` 与空串在 `apply_strategy` 里真能走到 `smart_order`

`apply_strategy` 先用 `parse_routing` 归一（`RouteError` ⇒ 仍然 fail-open 回恒等，见判据 3），
再按 canonical 名分派；`SMART` ⇒ `smart_order(seats)`。`MANUAL` ⇒ 恒等（没有自动排位，原件同）。

**钉子**：`::test_smart_routing_actually_orders`（`used=95` / `used=10` 两座，
`apply_strategy("smart")`、`("")`、`("default")`、`("SMART")` 四个写法都给 `[1, 0]`，
且与 `smart_order` 的返回逐字相等）；
`::test_manual_routing_keeps_the_listed_order`（`("manual")` ⇒ `[0, 1]`，且
`sink.sinks(True, "manual")` 仍为假 —— 两条口径对齐）。

### 判据 3 · 写得出来就说话：网关三个生产入口共用同一份归一

`apply_strategy` 的 fail-open 语义**保持不变**（既有钉子
`test_apply_strategy_unknown_name_falls_open` 的「非置换 / 越界 / 自抛」三条一个字都不改）；
而**启动面**不许 fail-open：`gateway.build_server()` 里把 `routing` 过一遍
`pool_route.parse_routing`，`RouteError` ⇒ 抛既有 `ConfigError`（消息点名收到的值与可用名字）。
`main()` 因此退 2 且**一个端口都不绑**（这是它既有的口径）。`serve_http` 走 `build_server`，不另写。

**钉子**：`tests/test_pool_gateway.py` 新增
`test_build_server_rejects_unknown_routing_with_the_name`（`ConfigError`、消息含 `nope`）；
`test_main_returns_2_without_binding_when_routing_is_unknown`（设 `TF_POOL_GATEWAY_TOKEN`，
`main(["--routing","nope"])` 回 2，stderr 点名；用 `monkeypatch` 把 `build_server` 换成会记录调用的桩，
断言**没被调用**）；
`test_gateway_routing_default_stays_order_but_smart_works`（`_order(rows,"smart")` ⇒ `[1,0]`；
`_order(rows,"order")` ⇒ `[0,1]`；`_order(rows,"")` ⇒ `[1,0]`）。

### 判据 4 · 反向变异 ≥4 条，每条真改真跑真还原

`gates/diag/_rev_E103.py`（本卡新建，体例照 `_rev_E102.py`）：A 把 `smart` 从分派里摘掉
（回恒等）；B 让 `parse_routing` 对空串回 `ORDERED`；C 把 `build_server` 的归一删掉（回到静默）；
D 让 `parse_routing` 对未知名字回 `ORDERED` 而不是抛。每条断言对应钉子**转红**、还原后 sha256
一致，读数落 `gates/diag/_rev_E103_result.txt`。

### 判据 5 · 文档三处投影一次改完，既有钉子只动那一处语义

- `docs/subsystems/pool/modules.toml`：route.py 的 duty/cli 改成真值（`apply_strategy` **有**
  生产调用方 = `tools/pool/gateway.py`；新增 `parse_routing` 的一句话）；gateway.py 的 cli 补
  `--routing`（当前名表 + 默认 `order` + 空串 = smart）。
- `docs/subsystems/pool/README.md` 与 `docs/INDEX.md` 由生成器重算（不许手改）。
- `tests/test_pool_route_strategies.py::test_apply_strategy_unknown_name_falls_open` **只删空串那一行**
  （空串现在等于 smart，已由判据 2 的钉子接管）；「非置换 / 越界 / 自抛」三条与 `BUILTIN` 七项那条
  **一个字都不改**。

## 交付

`tools/pool/route.py`（名称表 + `parse_routing` + `apply_strategy` 归一）、
`tools/pool/gateway.py`（`build_server` 归一 + `--routing` help）、
`tests/test_pool_route_strategies.py`、`tests/test_pool_gateway.py`、
`docs/subsystems/pool/modules.toml`、`gates/diag/_rev_E103.py`、本卡规格与三片段。

## 验收

```bash
pytest tests/test_pool_route_strategies.py tests/test_pool_route.py \
       tests/test_pool_route_unknown.py tests/test_pool_gateway.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool/route.py tools/pool/gateway.py tests/
python -X utf8 scripts/check_derived_docs.py --check
```

## 不许做

- 不许把 `smart` 塞进 `BUILTIN`（那是原件七个外部契约值）。
- 不许把 `apply_strategy` 改成「不认识就抛」—— 它跑在请求路径上，抛一下就是 500；
  说话的责任在启动面（`build_server`/`main`）。
- 不许改网关的默认 `--routing order`（E94「四路由默认关」的口径）；只让**显式写 smart 的人真的拿到 smart**。
- 不许手工改 `docs/subsystems/pool/README.md` 与 `docs/INDEX.md`。
- 不许碰 `tools/pool/sink.py` 的判据（只读它的 `sinks()` 口径来对齐 `manual`）。

## 直做

先写钉子（会红）→ 改 `route.py` → 改 `gateway.py` → 跑四条变异 → 文档三处 → 落地。
