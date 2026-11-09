# 卡 E106 · MCP 干跑面拿一张**更窄**的名单判模型：开关放行的模型被拒，理由还是个空串

> 台账号 `T-AG615`｜分区 E（门禁与可信度）｜树 `.wt/E106`｜层 判据层｜基准 `d493a1bf`｜
> 依据：用户 m92988「把 pool 的使用打磨好，不计代价与 token」；m93503「之前的任务记得做完」。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · MCP 干跑面判的是**另一张名单**

`tools/pool_mcp.py:1771` 用 `model not in wb_dispatch.MODEL_WHITELIST` 做模型闸；而
`MODEL_WHITELIST` 经 PEP 562 `__getattr__` 只回 `rotation_chain_for("codebuddy")`。
CLI 派活主路径用的是 `model_rejected()` ⇒ `effective_allowed_models(pool)`（注册表条目 +
一次性授权 + 开关文件打开的）。现场读数（`.wt/E106` 实跑）：

```text
MODEL_WHITELIST = ('deepseek-v4.1-flash', 'glm-5.3-flash')
effective       = ('deepseek-v4.1-flash', 'glm-5.3-flash', 'glm-5.3', 'kimi-k3-1', 'glm-5.2')
'glm-5.3'   in_whitelist=False  rejected=''            ← CLI 放行、MCP 拒
'gpt-99'    in_whitelist=False  rejected='未授权模型，已拒绝派活：gpt-99…'
```

⇒ 同一个模型，CLI `--model glm-5.3` 派得出去，MCP `pool_dispatch(model="glm-5.3")` 被拒。

### 问题 2 · 拒了却不给理由

上一条走到 `_result(wb_dispatch.model_rejected(model), …)`，而该函数对「在允许集里」的模型
返回**空串** ⇒ MCP 回 `isError=true` + 一段**空文本**。现场（`POOL_MCP_WRITE=1` 真调）：

```text
glm-5.3 isError=True reason_len=15 reason='--- tf-json ---'   ← 一个字的理由都没有
gpt-99  isError=True reason_len=266 reason='未授权模型，已拒绝派活：gpt-99…'
```

### 问题 3 · `pool` 参数不生效：判一个池、登记一个池、工人跑另一个池

`tool_pool_dispatch` 收了 `pool` 参数，只拿它喂 `guards.account_guard` 与 `registry.reserve`；
模型闸与 caller 收窄都写死 `wb_dispatch.DEFAULT_POOL`（`:1771`/`:1794`），而 `_dispatch_argv`
**不透传** `--pool` ⇒ 三个地方各说各的。`pool="nope"` 这种错值今天也照派（`effective_allowed_models`
对未知池回空元组，只是把它当「什么都没批」）。

### 问题 4 · 开关文件坏了会把 MCP 请求打崩

`model_rejected()` 会经 `load_switches()` 读开关文件，文件坏 ⇒ `SwitchFileError`（`ValueError` 子类）。
今天 MCP 走的是成员判定、根本不调它，所以看不出来；把判据换过去之后**必须**接住它并响亮拒绝，
否则一个坏 TOML 就能让 `tools/call` 抛异常。

## 判据（四条）

### 判据 1 · MCP 干跑面的模型闸与 CLI 是**同一份判据**

`tool_pool_dispatch` 不再自己比名单，改成调 `wb_dispatch.model_rejected(model, pool)`；
`pool` 取 `arguments["pool"]`（空 ⇒ `DEFAULT_POOL`）。判定结果非空即拒，并把**那段文案**原样带回。

**钉子**（`tests/test_pool_mcp_write.py`）：
- `test_switch_opened_model_passes_the_mcp_gate`：`TF_MODEL_SWITCHES` 指到临时开关文件（`glm-5.3 = true`），
  `pool_dispatch(model="glm-5.3")` ⇒ `isError is False`，且 argv 里 `--model glm-5.3`。
- `test_mcp_gate_and_cli_gate_agree_on_every_probe`：对 `("deepseek-v4.1-flash", "glm-5.3", "kimi-k3-1", "gpt-99")`
  逐个比：MCP 放行 ⟺ `wb_dispatch.model_rejected(name) == ""`（两处判据只许有一份）。

### 判据 2 · 拒单必须带理由（空理由 = 假绿）

任何 `isError=True` 的模型拒单，文本里都必须非空且点名模型。口径落在收紧后的实现上：
补一条「判据换过去以后，把 `model_rejected` 换成恒返回空串的桩 ⇒ 这条钉子必须红」。

**钉子**：`test_model_refusal_always_carries_a_reason`（`gpt-99` 与开关关闭时的 `glm-5.3` 两例，
断文本 `strip()` 非空且含模型名）。

### 判据 3 · `pool` 参数一路走到底：判它、登记它、工人也按它跑

- 未知池 ⇒ 干跑面就拒（点「未知池」），**不 spawn**；
- 未接的池（`codearts`）⇒ 干跑面就拒（点 `codearts 池的调用还没接`），**不 spawn**；
- 给了非默认池且该池已接 ⇒ argv 追加 `--pool <pool>`；不给 / 给默认池 ⇒ argv **逐字不变**（不许凭空多一个参数）；
  ★ 实测边界：`KNOWN_POOLS` 只认 `codebuddy` / `codearts`，注册表里造第三个池名会被校验拒掉；
  而 `codearts` 今天 `wired=False`。所以「非默认且已接」只能用**两侧同时桩**来造：临时注册表放
  `pool = "codearts"` 的条目（决定允许集）+ `get_adapter` 对该池回已接的假适配器（决定接没接）。
  只桩一半会得到「允许集里有、但池未接」的自相矛盾现场。
- caller（账号）收窄也按同一个池判（`caller_model_rejected(model, pool, account)`）。

**钉子**：`test_unknown_pool_is_refused_before_spawning` / `test_unwired_pool_is_refused_before_spawning` /
`test_pool_argument_reaches_the_worker`（把 `wb_dispatch.get_adapter` 换成已接的假适配器）/
`test_default_pool_argv_is_byte_identical`。

### 判据 4 · 文档与文案不再把 `MODEL_WHITELIST` 当模型闸的真源

`tools/pool_mcp.py` 的 :61（`--model` 只许取 `MODEL_WHITELIST` 里的值）与 :87（六条不变量表 ⑥）
改成「允许集 = `wb_dispatch.effective_allowed_models(pool)`，判据函数 `model_rejected`」；
`_dispatch_argv` docstring 补一行「`--pool` 只在非默认池时才带」。

**钉子**：`test_docs_stop_naming_the_narrow_list_as_the_gate`（AST/文本钉：docstring 里
`MODEL_WHITELIST` 只剩「轮换链」含义的提及，六条不变量表 ⑥ 那行必须点名 `effective_allowed_models`）。

## 交付

`tools/pool_mcp.py`（模型闸 + `pool` 参数 + `_dispatch_argv` + 两处 docstring）、
`tests/test_pool_mcp_write.py`（判据 1–4 的钉子，追加不改既有断言）、
`docs/subsystems/pool/modules.toml`（若有对应条目的 duty 需要跟着说清）、
`复盘/卡/卡E106-MCP模型闸用对名单.md`。

## 验收

```bash
python -X utf8 -m pytest tests/test_pool_mcp_write.py tests/test_pool_mcp_task.py -o addopts= -q --no-cov -p no:xdist
python -X utf8 -m pytest tests/test_pool_disabled_wiring.py tests/test_wb_dispatch.py -k "model or disabled or gate" -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool_mcp.py tests/test_pool_mcp_write.py
python -X utf8 scripts/check_derived_docs.py --check
```

## 不许做

- 不许在 `tools/pool_mcp.py` 里另写一套名单判定（判据只有 `wb_dispatch.model_rejected` 一份）。
- 不许放宽 `model_rejected` 的口径（那是 CLI 主闸，改它 = 改派活语义）。
- 不许给 `_dispatch_argv` 透传 `--force` / `--allow` / `--resume` / `--no-preflight`（既有钉子仍要绿）。
- 不许把「拒单没理由」洗成「不拒」（空理由要么补上、要么当 bug 修，不许吞）。
- 不许碰 `docs/INDEX.md` / `docs/subsystems/pool/README.md` 的生成段（跑生成器）。

## 直做

1. 先立卡（`tools/wb_card.py add` + 卡规格一并提交）→ 主树 `scripts/gen_pool_readme.py` 重算队列卡数。
2. 先写钉子（会红）→ 再改 `tools/pool_mcp.py`。
3. 变异脚本 `gates/diag/_rev_E106.py` ≥4 条（把闸改回名单 / 空理由吞掉 / 不透传 `--pool` / 未知池不拦）+ C1 只改注释。
4. 三片段 → precheck → preflight → 落地。
