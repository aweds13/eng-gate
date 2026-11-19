# 卡 A380（草稿）：F96 —— 逐部分拆 prompt、只留名字与大小（窄口 PORT + 三半 SKIP）

> 台账号 `T-AG668`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A380`｜层 判据层 + 数据形状｜基准 `6573205b`（立卡时主树 HEAD，2026-11-20 02:20 实读）｜depends A371、A372、A363、E143
> depends 说明：**A372**（F56 搜索多 key）与本卡**同域** `tools/pool/gateway.py` + `tests/test_pool_gateway.py`，**A371**（F30 账号导入）与本卡同域 `docs/subsystems/pool/modules.toml`；两张今天都是 `pending`，不给本卡写 `depends` 就会被 `tools/pool/plan.py:321-327` 拒单（逐字 `files 相交 …（同一文件两个写者；要共存就给其中一张写 depends）`）。**A363**（`tools/pool/route_log.py` 的拥有者）是本卡要加**行级新键**的那本账的作者；**E143**（窗口 / 回复上限的「知道就说数，不知道就说 null」）是本卡 `null` 口径的先例。四张里 A371 / A372 未 done，其余 done。
> 依据：`gates/diag/_magpie_scope.md:104` 逐字 `| F96 | Context 页：逐部分拆 prompt、只留名字与大小 | PORT | no | 无 prompt 拆解面板读数（tools/pool_mcp.py 无对应工具） |`；magpie 原件 `internal/gateway/prompt.go`（七类 part + `tokensOf` 估算 + `calibrate`）、`internal/gateway/prompt_text.go`（`promptBodies = 10` / `promptBodyMax = 32 << 20` / `promptBodiesMax = 64 << 20`）、`internal/gui/context.go:553` / `:564`（GUI 两端点）。

## 前情

magpie 的 F96 不是「一个面板」，是**三根支柱**，功能清单 `D:/repo/program/_ext/_magpie_features.md:800-806` 写得清楚：

1. **分段读数**：每个请求的 prompt 拆成七类，各报 token 与「名字列表」。
   `magpie-main/internal/gateway/prompt.go:30-41` 逐字：`PartSystem = "system"`（*the agent's own prompt: system, developer and harness messages*）、`PartTools = "tools"`（*tool definitions*）、`PartSkills = "skills"`、`PartMemory = "memory"`（*instruction files, reminders*）、`PartFiles = "files"`（*files and images the tools read in*）、`PartResults = "results"`（*the tools' other output*）、`PartChat = "chat"`，`var partOrder = []string{PartSystem, PartTools, PartSkills, PartMemory, PartFiles, PartResults, PartChat}`。
2. **只留名字与大小**：`prompt.go:57-71` 的 `PromptPart{Kind, Tokens, Items}` 与 `PromptItem{Name, Tag, N, Tokens}` —— 落盘那份里**没有正文**。包里注释（`prompt.go:1-16` 段）逐字：*The Prompt keeps only names — the instruction files' and read files' paths, the tools' names, "turn 3" — never the prompt's text, and it is what goes in the routing history on disk.*
3. **读回原文**（另一半，只在 GUI）：`prompt_text.go:1-12` 逐字 *The text is read again from the request's body, which the trace holds for the last few requests: in memory only, never written to disk or sent anywhere… When magpie quits, or a request is older than the last promptBodies, its text is gone.*

token 是**估的**，不是分词器：`prompt.go:76-78` 逐字 *tokensOf estimates the tokens of a text: about four characters a token for ASCII, a token a character for the rest (CJK, mostly).*；JSON 原样片段走 `prompt.go:93` `func rawTokens(b json.RawMessage) int { return (len(b) + 3) / 4 }`；上游答完再按 vendor 计的数缩放（`prompt.go:306-308` `calibrate`：`scale := float64(counted) / float64(est)`）。

## 判定（先给结论）

| 半边 | 判定 | 一句话理由 |
|---|---|---|
| 分段账（七类里本仓认得的那几类，只留名字与大小） | **PORT（窄口）** | 纯函数 + 行级一个新键，不碰协议、不碰转发、不留正文；估算口径照 magpie 原样搬 |
| calibrated 缩放到 vendor 计数 | **SKIP_NOT_APPLICABLE** | 网关**不解析上游 usage**（`tools/pool/gateway.py:287-298` 的 `Reply` 没有 usage 字段；`grep -n 'usage\|Usage' tools/pool/gateway.py` 只有 `:494` / `:1276` 两处 routing 名单注释）⇒ 永远只有估算，装不成 `counted` |
| GUI Context 页（`/api/context`、`/api/context/text`） | **SKIP_BY_REDLINE** | 本仓无 GUI / webview 宿主；这是功能清单「不可移植」节的口径 |
| 读回原文（`promptBodies = 10` / 每份 32 MiB / 合计 64 MiB 的环形缓冲） | **SKIP_BY_REDLINE** | 正面撞两条既有纪律：`gateway.py:11`「不做定时器：没有后台线程」与 `route_log.py` 模块 docstring 第 3 条「追加，不环形」 |

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 本仓今天**完全没有**这个东西（不是「有代码没接线」）

- 生产侧：`grep -rn 'parts\|prompt' --include=*.py tools/pool/` 命中的全是无关物 —— `tools/pool/gateway.py:282`（`Attempt.label` 的 docstring 逐字「只有号与原因，没有 prompt、没有凭据」）、`gateway.py:985` / `:991` / `:995`（`read_body` 内部的 `parts: list[bytes] = []` 分块读，读完就 `b"".join(parts)`，**不留**）、`tools/pool/jobs.py:93`（工具参数名白名单）、`tools/pool/landing.py` 的文书分段解析。**没有一处**把请求 body 按语义切段。
- 测试侧：`grep -rn 'prompt_parts' tools scripts tests docs` ⇒ 零命中；`import pool.prompt_parts` ⇒ `ModuleNotFoundError`。
- 面板侧：`[(b['id'], b['row_fields']) for b in pipeline_view.BLOCKS]` 实跑，六块 `cards / gates / verdicts / leases / fences / worktrees` 的 `row_fields` **没有** token / prompt / parts 任何一个字段；`grep -rniE 'wb-route|route\.jsonl' tools/pipeline_view.py tools/pool_mcp.py` ⇒ **0 行** ⇒ 面板与 MCP 都不读路由账。
- MCP 侧：`pool_mcp.tool_list()` 实跑 13 个工具（`pool_plan / job_list / job_status / job_result / lock_status / pool_models / quota_status / account_status / checkin_status / workbench_board / task_list / task_status / task_pool`），**没有** context / prompt 类。

结论：`_magpie_scope.md:104` 判 `PORT / no` 是**事实**，不是欠账。本卡要从零建起。

### 缺口 2 · 账里能加什么、不能加什么（形状约束，先读再动手）

- 行级**能加**新键：`tools/pool/route_log.py:162-174` 的 row 是**写死的八键**（`card / attempt / asked / tried / served / status / started_at / at`），加第九个键要改这一段；两个既有测试文件 `tests/test_pool_route_log.py` 与 `tests/test_pool_gateway.py` 里**没有** `set(row)` / `keys()` 键集断言（`grep -n 'set(row\|keys()'` 两文件 ⇒ 零命中）⇒ 加键不撞既有钉子。
- **不能**塞进 `tried`：`route_log.py:122-130` 的 `_one_try()` 逐字 `return {"model": model.strip(), "fail": _fail_text(row.get("fail"))}` —— **多余键被丢弃**。
- 纪律不能破：`route_log.py:144-150` 逐字「★ 每个参数都是**调用方传进来的事实**，本模块不读别的账、不重算、不排序」「★ `tried` 为空**不拒**…本模块只保证**传什么写什么**」；`:151-157` 三条校验（status 四值闭集 / card 非空 / attempt 正整数）**一个字都不许动**。
- 「不许把不知道写成 0」的既有先例：`docs/subsystems/pool/模型与号池.md:161-163` 逐字「为什么 `null` 不能写成 0：0 是「量过，一点都装不下」，`null` 是「没人量过」…**不许**为了填满而抄一个「看着合理」的 128k / 200k / 1m」。本卡的 `parts` 同口径：**说不出来就写 `null`，不写 `[]`**。

### 缺口 3 · 七类里本仓只认得四类（诚实边界，不许装成七类都有）

magpie 的七类里，`skills` / `memory`（CLAUDE.md / AGENTS.md 这类 instruction files）/ `files`（工具读进来的文件与图）**都是 agent harness 的语义**，靠解析「agent 原样 body 里的 system blocks / additional_tools」得到（`prompt.go:1-16` 包注释逐字 *Read from the body the agent sent, as it sent it: the parsed Request has the system blocks run together, and Codex's additional_tools lifted out.*）。本仓的 body 是**消费方发来的 chat / messages JSON**，没有这层语义。所以本卡只认：

| 本仓能认的段 | 从 body 的哪里切 |
|---|---|
| `system` | 顶层 `system`；`messages` 里 `role == "system"` 或 `role == "developer"` |
| `tools` | 顶层 `tools`（每个工具一项，`name` 当 `PromptItem.Name`） |
| `results` | `messages` 里 `role == "tool"`（工具输出） |
| `chat` | 剩下的 `messages`（user / assistant，含 `tool_calls`） |

`skills` / `memory` / `files` **恒定不出现**（不是空数组占位 —— 不出现就是「本仓没有这个概念」，写 `[]` 会读成「量过，零」）。这一条必须写进库的 docstring，让下一个人一眼看见边界。

### 缺口 4 · 参数化边界（body 不是 JSON 对象怎么办）

`gateway.py:1119-1126` 已经把「非 JSON / 非 dict」挡在 400，所以 `route_once` 拿到的 `body` 一定是**能解析的对象**；但 `prompt_parts.parts_of()` 是**独立可调用的纯函数**（测试与将来别的调用方都会直接喂它），所以它自己**也必须**对坏输入给 `None`（不是抛、不是 `[]`）。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 分段口径钉死：四类、顺序、≥24 项折叠、估算公式与 magpie 同口径

库 `tools/pool/prompt_parts.py` 暴露两个名字：

~~~python
def tokens_of(text: str) -> int: ...
def parts_of(protocol: str, body: bytes) -> list[dict] | None: ...
~~~

- `tokens_of` 必须逐字复刻 `prompt.go:76-91` 的口径：ASCII 四字符一 token，其余（CJK 为主）一字符一 token。实现允许写成 `(ascii + 3) // 4 + other`，但**必须**在 docstring 里点名 `magpie-main/internal/gateway/prompt.go:76-78`。
- `parts_of` 返回的每一项形状 = `{"kind": str, "tokens": int, "items": [{"name": str, "tag": str, "n": int, "tokens": int}, ...]}`，`kind` 只许出现 `system / tools / results / chat` 四值，**顺序固定**为 `system → tools → results → chat`（照 `prompt.go:41` 的 `partOrder` 取子序列，空段也占位成 `tokens: 0, items: []`，好让读的人一眼看见「这一类是零」而不是「这一类不存在」）。
- 每段 `items` 最多 24 项（`prompt.go:73-74` `const promptItems = 24`），按 token 降序；超出的**合并成一项** `{"name": "（其余 N 项）", "tag": "rest", "n": N, "tokens": 和}`。
- 坏输入（`protocol` 不是 `chat` / `messages`、body 不是 JSON 对象、JSON 坏）⇒ 返回 `None`。

- **怎么证明**：新增 `tests/test_pool_prompt_parts.py`（体例照 `tests/test_pool_pricing.py:1-30`：模块 docstring 写「本卡 N 条钉子」+ `ROOT = Path(__file__).resolve().parent.parent` + `sys.path.insert(0, str(ROOT / "tools"))` + `importlib.import_module("pool.prompt_parts")`）。至少四条：① `tokens_of("abcd") == 1` 与 `tokens_of("中文") == 2`（ASCII 四字符一 token / CJK 一字一 token，两边都钉）；② 用一份含 `system` + `tools` + `role:"tool"` + 用户轮次的合成 body，断言 `[p["kind"] for p in parts] == ["system", "tools", "results", "chat"]`；③ 造 30 个工具的 `tools`，断言 `len(parts[1]["items"]) == 24` 且最后一项 `tag == "rest"`、`n == 7`（24 项 + 1 项汇总）；④ `parts_of("chat", b"not json") is None` 与 `parts_of("gemini", b"{}") is None`。

### 判据 2 · **正文一个字都不进账**（哨兵串实测，照既有 判据 2 的体例）

- `parts_of` 只从 body 里取 **名字**（工具名、JSON 顶层键名、`"turn 3"` 这种轮次标签）与**大小**；不取任何自由文本。

- **怎么证明**：照 `tests/test_pool_route_log.py:44` 的哨兵体例（`SECRET = "<SECRET-2f9a>"`）+ `:103` `test_no_prompt_no_secret` + `:116-117` 两条断言（`assert SECRET not in raw` / `assert SECRET not in path.read_text(encoding="utf-8")`）。本卡在 `tests/test_pool_prompt_parts.py` 里加一条对称的：把 `SECRET` 放进 `messages[0]["content"]` 与 `tools[0]["description"]`，再 `json.dumps(parts_of(...))`，断言 `SECRET not in 序列化结果`；同时**反向自证**（照 `:119-120` 的写法）断 `SECRET in body_text` —— 证明哨兵确实在输入里，否则这条钉子会假绿。

### 判据 3 · 账里多一个行级键 `parts`；说不出来就是 `null`（不是 `[]`、不是 0）

- `tools/pool/route_log.py` 的 `append_route()` 增加**关键字参数** `parts: Sequence[dict] | None = None`（只能加在参数表末尾，**不许**动已有八个参数的顺序与名字，否则 `tools/pool/trae_dispatch.py:280` 那个生产调用方会被咬）；row 里加第九个键 `parts`：传了列表就写列表，传 `None` 写 `null`。
- `tools/pool/gateway.py` 的 `_log()`（`:590-598`）把 `prompt_parts.parts_of(protocol, body)` 的结果传下去；`route_once` 的 `body` 已经是**原始字节**（`gateway.py:1134-1138` 逐字 `body=payload`）⇒ **不必另缓一份 body**，也不许缓（见判据 5）。
- 老账（今天已落盘的 `gates/diag/wb-route.jsonl` 行）不该被改写：本卡只追加，不回填。

- **怎么证明**：`tests/test_pool_gateway.py` 里新增一条（文件已被 A372 占域，本卡靠 `depends` 与它排批 —— 见抬头 depends 说明）：走 `_run(env, forward)` 单轮，断言 `_route_log(env)[-1]["parts"]` 是列表且 `[p["kind"] for p in ...]` 非空；再加一条「body 里没有 `system` / 没有 `tools`」的请求，断言该行 `parts` 是 **`null`**（不是 `[]`）—— 逐字 `assert row["parts"] is None, "说不出来要写 null，不许写 []（0 是「量过，一点都没有」）"`。`route_log` 侧另加一条：`append_route(..., parts=None)` 与不传该参数两种调用的落盘结果里，`parts` 都是 `None`（默认值不许变成 `[]`）。

### 判据 4 · 只读面读得回来，且坏行仍如实计数

- `gateway.py:1141-1156` 的 `GET /v1/pool/routes` 直接 `json.dumps` 读到的行（`{"data": rows[-limit:], "bad_lines": bad, "total": len(rows)}`）⇒ 新键**自动**跟着出去，**不改**这段代码。

- **怎么证明**：照 `tests/test_pool_gateway.py:756-764` `test_http_serves_route_replay` 的体例（起真服务 → POST 一条带 `X-Pool-Caller: alice` → `GET /v1/pool/routes?limit=5` ⇒ 200 + `data["total"] >= 1` + `data["data"][-1]["card"] == "gw:alice"`），在同一条里补一句 `assert "parts" in data["data"][-1]`。另加一条坏行钉子：手工往账里追加一行 `"{bad json"`，断言 `bad_lines == 1` 且好行仍带 `parts`（坏行不许把整个只读面拖成 500）。

### 判据 5 · **不缓存 body**（这是一条反向钉子：谁想「顺手留一份原文」就红）

- 正向：`parts_of` 是纯函数，调完不持有任何东西；`gateway.py` 里不出现新的模块级可变容器（`grep -n 'prompt_parts' tools/pool/gateway.py` 只允许出现在 `import` 与 `_log` 的调用处）。

- **怎么证明**：在 `tests/test_pool_prompt_parts.py` 里用 AST 扫 `tools/pool/prompt_parts.py`（体例照 `tests/test_pool_gateway.py:571-584` 的 `ast.parse` 钉）：断言模块 `tree.body` 里**没有** `Assign` 到模块级 `list` / `dict` / `deque`（即没有缓存容器），且**没有** `import threading` / `import time`（不做定时器、不做环形缓冲 —— 与 `gateway.py:11` 同一条纪律）。再在 `tests/test_pool_gateway.py` 里断 `gateway._log(...)` 签名**不含** `body` 参数（参数名集合与今天逐字相同，只多不换成 body：这条用 `inspect.signature` 断）。

### 判据 6 · 反向变异 ≥3 条（每条真改真跑真复原，`sha256` 自证）

脚本落 `gates/diag/_rev_A380.py`（`.gitignore:70/76` 已忽略 `gates/diag/*`，只有 `gate_lock.py` 被 `:77` 放行 —— 所以脚本与日志都不进 git）。做法照 `复盘/卡/卡E143-F86上下文窗口与回复上限-窗口读数发布成可核元数据.md` 的判据 5：每条变异记改前 `sha256`、真改、跑对应选测、断言退非零、还原、再记 `sha256`，末行打「结论：N/N 条全部咬住，收尾绿。」。

| # | 改哪一行（锚点原文） | 哪条判据红 |
|---|---|---|
| M1 | `prompt_parts.py` 里 `return (ascii + 3) // 4 + other` 改成 `return len(text) // 4 + other` | 判据 1 的 ①（`tokens_of("abcd") == 1` 仍绿，但 `tokens_of("abcdefgh") == 2` 变 1）—— 所以 ① 必须**同时**钉两个长度，只钉 `"abcd"` 会漏 |
| M2 | `parts_of` 里把 `items.append({"name": tool["name"], ...})` 改成 `items.append({"name": tool["description"][:80], ...})` | 判据 2（哨兵串进账） |
| M3 | `prompt_parts.py` 里 `if len(items) > prompt_items:` 改成 `if len(items) > 99:`（`prompt_items = 24` 被改大） | 判据 1 的 ③（`len(parts[1]["items"]) == 24` 红） |
| M4 | `route_log.py` 里 `row = {...}` 的 `parts` 值从 `part_list` 改成 `part_list or []` | 判据 3 的「说不出来要写 null」那条红 |
| E1 | **只改注释**：在 `prompt_parts.py` 模块 docstring 末尾加一句中文说明（不含任何被扫字面） | 全绿（安静对照 —— 证明上面四条钉的是行为不是文件指纹） |

- **怎么证明**：`python -X utf8 gates/diag/_rev_A380.py` 退 0，且日志里 M1–M4 四条各自打出「预期红 → 实测红」，E1 打出「预期绿 → 实测绿」。

## 交付（逐文件）

| 文件 | 做什么 | 今天存在吗 |
|---|---|---|
| `tools/pool/prompt_parts.py` | 新建。`tokens_of` / `parts_of` 两个纯函数 + 模块 docstring 写明「只认四类」「只留名字与大小」「估算不是分词器」「七类里三类的缺席理由」 | **不存在**（`import pool.prompt_parts` ⇒ ModuleNotFoundError） |
| `tools/pool/gateway.py` | 只在 `_log()`（`:590-598`）里加一段 `parts = prompt_parts.parts_of(protocol, body)` 并透传；**不改** `PATHS` / `_dispatch` / `_post` / `_get` / `Reply` / `Attempt` 任何一行 | 存在，1300 行；**本卡与 A372 同域**（靠 depends 排批） |
| `tools/pool/route_log.py` | `append_route()` 加关键字参数 `parts`（加在末尾）+ row 加第九键；三条校验、八键名字与顺序、`_one_try()` 一个字不动 | 存在，205 行 |
| `tests/test_pool_prompt_parts.py` | 新建。判据 1 / 2 / 5 的钉子（分段口径、哨兵串、无缓存 AST 钉） | **不存在** |
| `tests/test_pool_gateway.py` | 判据 3 / 4 的钉子（行级 `parts`、`null` 口径、只读面读回、`inspect.signature` 断 `_log`）——**只加新 `def test_`，既有 72 条一条不动** | 存在，1150 行；**与 A372 同域** |
| `docs/subsystems/pool/modules.toml` | 给新模块加一条 `[[module]]`（`name = "prompt_parts.py"`、`duty`、`cli = "无"`）—— 不加的话 `scripts/gen_pool_readme.py --check` 会退 1 并点名（生成器判据：仓里有、清单没有 ⇒ 退 1） | 存在；**与 A371 / A372 同域** |
| `复盘/卡/卡A380-F96Context页分段账-只留名字与大小不搬面板与读回原文.md` | 本卡规格（落地时把「草稿」改成实测读数） | 本文件 |

**卡域里不写**：`docs/subsystems/pool/模型与号池.md`（那本讲号池与模型的关系，不讲 prompt 分段；硬塞会让两份文档各说一半）、`tools/pipeline_view.py` / `tests/test_pipeline_view.py`（A369 占着，且本卡的读数**不走面板**）、`tools/pool_mcp.py`（MCP 十三个只读工具的口径刚被卡 213 收口，本卡不加工具）。

## 验收

~~~bash
cd .wt/A380
python -X utf8 -m pytest tests/test_pool_prompt_parts.py tests/test_pool_gateway.py tests/test_pool_route_log.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool/prompt_parts.py tools/pool/route_log.py tools/pool/gateway.py
python -X utf8 scripts/gen_pool_readme.py --check
python -X utf8 gates/diag/_rev_A380.py
~~~

- 第一条必须**全绿**；`-o addopts= --no-cov` 不能省（`pyproject.toml:51` 的 `addopts` 带 `--cov-fail-under=70`）。基线（今天，`dce8d904`）：`tests/test_pool_route_log.py` 9 passed、`tests/test_pool_gateway.py` 72 条全绿。
- 第二条：`ruff` 不许有新增告警（`tools/pool/prompt_parts.py` 是新文件，`F401` / `E501` 一类都要自己先清）。
- 第三条：加 `[[module]]` 之后必须退 0；**不加就退 1 并点名** —— 这条既是验收也是判据（生成器自己会咬）。

## 不许做

1. **不许动** `tools/pool/route_log.py:151-157` 那三条校验（status 四值闭集 / card 非空 / attempt 正整数），也不许动 `:90-100` 的 `STATUSES` 四值与 `:103` 的 `MAX_FAIL = 200` —— 本卡只加**第九个键**，不加第五个 status。
2. **不许**把分段塞进 `tried`（`_one_try` 会丢键），也不许改 `_one_try` 的返回形状 —— 那会咬 `tests/test_pool_route_log.py:97` 的 `assert rows[0]["tried"] == [{"model": M1, "fail": ""}]`。
3. **不许**把 body 缓存起来、不许加后台线程 / 定时器 / 环形缓冲 —— `gateway.py:11`「不做定时器：没有后台线程」与 `route_log.py` 模块 docstring 第 3 条「追加，不环形」是**两条既有决定**，要改也得另开卡。
4. **不许**在账里写任何自由文本（`content` / `description` / 系统提示词原文）；只留 `name` / `tag` / `n` / `tokens`。判据 2 是这条的钉子。
5. **不许**把「估的 token」写成「vendor 计的」：不加 `counted` 键、不加 `window` 键（`window` 是 E143 / A368 的域，本卡不越界）。
6. **不许**改既有的 72 条网关钉子、9 条账钉子、`tests/test_pipeline_view.py` 的六块钉子（`:404` 的 `ids == [...]`）；不许为了让新键好看去放宽任何既有断言。
7. **不许**写 `sha256` 之外不留痕的「假变异」：变异脚本必须真改文件、真跑选测、真还原，且末行给结论。
8. 仓外不许动：`D:/repo/infra/**`（号池账本与端点表）本卡一个字都不碰。

## 与已完成卡的关系

- **A363**（`wb-route.jsonl` 的作者）：本卡在它那本账上加**行级**新键，不改它的三条纪律与三条校验 —— 抬头 depends 已写它。
- **A368 / E143**（窗口与回复上限）：本卡**不碰** `window`，也不碰 `Reply` 的形状；两边共用的是「说不出来就 `null`」这一条口径（`模型与号池.md:161-163`）。
- **A354**（定价算术）：无关 —— 本卡只报 token 计数，不算钱（`tools/wb_dispatch.py:1595` 的 `append_usage_line` docstring 逐字「只数 token，**不做金额换算**」，同一条分工）。
- **249 / 卡 213**（面板六块）：本卡的读数**不进**面板六块 —— 那条路要另开卡（面板的唯一口径源是 `tools/pipeline_view.py:31-33` 的「BLOCKS 声明表」，加字段会咬 `tests/test_pipeline_view.py:415` / `:428` 两条钉子）。

## 未坐实项（草稿如实标注，别当成结论）

1. **`magpie` 七类里 `skills` / `memory` / `files` 的切法没有再逐行读**（`prompt.go:246` `skillsApart` / `:357` `memoryTag` / `:379` `splitMemory` / `:414` `skillsList` / `:420` `splitSkills` 只读了签名与位置，没读体）。本卡**不移植**这三类，所以不影响判据；但如果将来有人要搬，必须回去把这几段读完。
2. **`promptItems = 24` 之外还有没有第二层折叠**（例如 `Prompt.Turns` 与 `PartChat` 的 `items` 关系）未取证；判据 1 的 ③ 只钉 `24` 这一条。
3. **估的 `tokens_of` 与真分词器的偏差有多大**未量（本仓没有分词器，`gateway.py:16-17` 的 F86 ③ 已把这条写成「不移植」理由）。本卡**不**承诺精度，只承诺**口径可复算**。
4. **`route_once` 之外还有没有别的调用方会传 `body`**：今天只有 `gateway.py:1134-1138` 一处（`tests` 里另有若干），`grep` 已核；但 A372 落地后 `tools/pool/search.py` 可能成为第二个调用方 —— **未坐实**，落地前按当时 HEAD 重核。
