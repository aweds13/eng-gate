# 卡 A386：F85 裸模型 id 列进 /v1/models 的开关

> 台账号 `T-AG674`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A386｜层 判据层｜基准 `78d4c16a`（立卡时主树 HEAD，2026-11-20 实读）｜depends A372、A373、A375、A380、A381、A384

> depends 说明：六条全是 **pending 的同域卡**（`tools/pool/plan.py:321-327` 只对 pending / running 判冲突：撞同一份文件又不写 depends 会被以「同一文件两个写者」拒单）。逐条相交（实跑 2026-11-20，backlog 412 张 / 活跃 20 张，`plan.ACTIVE_STATUS` = pending / running）：A372 撞第 1/2/4 三份；A373 撞 `tests/test_pool_gateway.py`；A375 撞第 1/2/4 三份；A380 撞第 1/2/4 三份；A381 撞 `docs/subsystems/pool/模型与号池.md`；A384 撞 `tests/test_pool_gateway.py` 与 `docs/subsystems/pool/模型与号池.md`。
> ★ **差额点名（不许静默吞掉）**：同法实算另有两张 pending 卡与本卡域相交 —— **A383**（F95 隐藏模型：列出来的必须能用）撞第 1/2/3 份 + `docs/subsystems/pool/模型与号池.md` 与 `docs/subsystems/pool/modules.toml`；**A385**（F57 searcher 的选择与让位）只撞 `docs/subsystems/pool/modules.toml`。⇒ **立卡时必须把 A383、A385 一并写进 depends**，否则 `tools/pool/plan.py` 的冲突域校验会拒单。本规格按立卡指令只列上面六条，差额在此点名。
> 判据引用归属（草稿原 depends，三张全 `done`，按 `plan.py` 口径不进 depends）：A353（裸名三档已落）、E105（禁用表接线已落）、E143（/v1/models 六键读数已落）。

> 基准说明：抬头基准 `78d4c16a` 是立卡指令给的读数；物化这一刻实读主树 HEAD 已到 `bc41ba76`（`78d4c16a` 之后只有一笔 docs-only：修 A385 规格里 8 处仓外 `_ext` 反引号、把 dead_refs 从 149 压回基线 147）。所引本仓源码行号在 `bc41ba76` 上逐条复读未变 —— `git diff --stat 78d4c16a..HEAD -- tools/pool/gateway.py tests/test_pool_gateway.py docs/subsystems/pool/模型与号池.md docs/subsystems/pool/modules.toml` **为空**。落地前按当时 HEAD 重核。

> 依据：`gates/diag/_magpie_scope.md:93` 把 F85 判成 PORT / partial，证据只有半句 —— 逐字「model_registry.py:618/:684 裸名三档在（A353），但「列进模型列表」的开关无」。本卡把这个「无」落成一条可验收的规格：**只搬「列进列表」这一半、默认关**，并把「用网关自己的解析决定裸 id 落到哪个 entry」「GET /v1/models/{id} 按裸 id 认」「设置面」「请求侧按裸名路由」四件写成决定（不是留成「还没做」）。功能原文见 `D:/repo/program/_ext/_magpie_features.md:714-717`。

## 前情：原件为什么这么做（逐字证据）

原件的动机是一个具体的迁移痛，不是「列表好看」：

- `D:/repo/program/_ext/_magpie_features.md:714` 逐字：「- 解决：从别的代理搬来的客户端只认 `gpt-5.6-sol`，不看 `codex/gpt-5.6-sol`。」
- 默认**关**，且关着时列表一个字不动。magpie 原件 `internal/provider/bare.go:9-15` 逐字：

~~~text
// Model ids without the provider (settings.BareModelIDs; love1sbug on X): a client moved
// from another proxy (CLIProxyAPI) asks for gpt-5.6-sol, not codex/gpt-5.6-sol, and picks
// its model from /v1/models. The gateway has always taken a bare id (GroupFor, then
// Resolve); with the setting on, /v1/models lists each model by its bare id as well,
// after the provider/model ids, which stay as they were. Off by default: a list nobody
// asked to grow keeps its ids.
~~~

- **列在哪一行不是随便挑**：由网关自己的解析决定「请求真会去到哪个 entry」。`bare.go:17-24` 逐字：

~~~text
// A bare id is listed only where a request for it goes, as the gateway routes it: two
// providers' gpt-5.6-sol is one row, the routing group magpie found for it (its members
// in the Providers order, failed over between), or with found groups off the first
// provider in the Providers order. A bare id that is a catalog id already, or that the
// gateway would take to a model the list doesn't show (a gateway key held to other
// models, an id like anthropic/claude-x that names a provider of the user's), isn't
// listed by it.
~~~

- 去重与跳过的三个条件（空名 / 已在目录里的 id / 已列过的尾段）：`bare.go:60-69` 逐字：

~~~text
for _, e := range entries {
	m := e.Model
	if e.Group != "" || m == "" || seen[m] || ids[m] {
		continue
	}
	seen[m] = true
	if i := bareTarget(shown, all, entries, m); i >= 0 {
		out = append(out, Bare{ID: m, Of: i})
	}
}
~~~

- 「落到哪一行」的判定函数：`bare.go:73-75` 逐字 docstring「// bareTarget is the index in shown of the entry a request for the bare id reaches: the routing group GroupFor gives it, else the provider's model Resolve does; -1 when shown has neither.」；匹配循环 `bare.go:91-95` 逐字：`if e.Group == "" && e.Provider.ID == p.ID && e.Model == model {` / `return i`。
- 单条读取也认裸 id：`bare.go:99-110` 的 `BareEntry(shown []Entry, id string) (Entry, bool)`（`:105` 逐字 `e.ID = id`）；接线在 `internal/gateway/gateway.go:1336-1342`（`if provider.BareModelIDs() { if e, ok := provider.BareEntry(shown, id); ok { ... } }`，其后才是 `writeError(..., 404, "unknown model "+id)`）。
- 列表侧接线：`gateway.go:1232-1236` 注释逐字含「each model by its bare id as well, after the provider/model ids ... Never for another magpie, whose provider would list each twice.」；`:1237` `rows, ids := slices.Clip(shown), map[int]string{}`；`:1238` `if !magpie && provider.BareModelIDs() {`；`:1240-1243` 先 `ids[len(rows)] = b.ID` 再 `rows = append(rows, shown[b.Of])` / `labels = append(labels, labels[b.Of])`，最后 `:1249-1251` `if id, ok := ids[i]; ok { m["id"] = id }`。
- 两条排除是**明确**的：另一台 magpie —— `gateway.go:1208` 逐字 `magpie := r.Header.Get(provider.DrawersHeader) != ""`，配 `:1238` 的 `!magpie`；Claude Desktop —— `gateway.go:1201-1205` 三分支（`if agent := agentOf(r); agent == "claude-desktop" { data = desktopModels(...) } else if agent == ScienceID { ... } else { ... }`），桌面那条走另一套构造，天然拿不到裸 id。
- 设置面：`internal/gui/api.go:1614-1621` 的 `mux.HandleFunc("POST /api/settings/bare-ids", ...)` → `provider.SetBareModelIDs(in.On)`；`bare.go:29-39` 的 `SetBareModelIDs` 同值直接 `return nil`，注释 `:31` 逐字「no agent's file names a model by one, so none is written again.」⇒ 这个开关**不写任何 agent 配置文件**。

## 本仓现状（`78d4c16a` grep 实读）

### 二.1 有的：裸名三档（卡 A353）—— 但用途是「判禁不禁」，不是「列不列」

- `tools/pool/model_registry.py:629` `def names_of(provider: str, model: str) -> list[str]`：`:633-634` 逐字「① model 本身；② provider == "" 时不加，否则 provider + "/" + model；③ LastIndex(model, "/") 之后那段（**有斜杠才加**）」；`:635` 逐字「★ 所以**裸名两档、带斜杠名三档**」。
- `tools/pool/model_registry.py:649` `def id_names(model_id: str) -> list[str]`：三档（id / 最后一段 / partition 第一刀之后）。
- `tools/pool/model_registry.py:715` `def id_disabled(model_id: str, *, table: Disabled | None = None) -> str | None`；`:722-723` 逐字：「10. `BareDisabled` —— pool 侧没有目录解析，这一档**并进了第 8 步**：`id_names` 的尾段 / 第一刀之后那两档正是「resolver 认不出来时的裸 id」要用的名字。」
- **关键辨析（本卡成立的前提）**：本仓的「裸名 / 裸 id」是**禁用判定的输入**，不是 `/v1/models` 的**输出**。F85 要的是后者；今天前者有、后者零。

### 二.2 没有的（每条都是真跑，不是印象）

- 零命中扫描（exit 1 = 无命中）：`grep -rnE "BareModelIDs|BareEntries|BareEntry|api/settings/bare-ids|DrawersHeader|X-Magpie" tools/ tests/ scripts/ docs/` ⇒ **0 行**。
- `/v1/models` 今天只发批准集，没有第二圈：`tools/pool/gateway.py:849` 逐字 `for name in info.get("approved") or []:`，循环体内 `:855-862` 只 append 一行；`:863-865` 收尾。全文没有「裸 id」这个词（`grep -n "bare" tools/pool/gateway.py` ⇒ 0 行）。
- 网关没有设置面：`grep -rnE "api/settings|/api/" tools/pool/gateway.py` ⇒ 0 命中。配置只有 env 与 toml。
- 请求侧只认批准集里的**字面** id：`tools/pool/gateway.py:355-356` 逐字 `if model not in approved:` / `return 404, f"模型 {model!r} 不在批准集里（已批：{', '.join(approved)}）⇒ 未批模型不许用"`；号级也按字面比：`:399-400` `if model not in approved:` / `why.append(f"{seat}：没批这个模型（{model!r} 不在它的 approved_models 里）")`；钉子 `tests/test_pool_gateway.py:344-350`。
- 没有子路径落点：`tools/pool/gateway.py:99-104` 的 `PATHS` 恰好四键（`:102` 逐字 `"/v1/models": ("GET", ""),`），`:1086` 逐字 `spec = PATHS.get(path)` —— 精确字典查，`/v1/models/<任意>` 今天一律 404；钉子 `tests/test_pool_gateway.py:1257-1258`（`:1253-1255` docstring 逐字「★ 判据 4：路径表恰好四键 ... ★ `test_http_only_four_paths` 只验了三条具体反例，集合本身没人管 —— 加第五键它照样绿。」）。
- **实测基线（本例就是「默认关时长什么样」）**：

~~~text
$ python -X utf8 -c "import sys,json;sys.path.insert(0,'tools');from pool import gateway;print(json.dumps(gateway.list_models(),ensure_ascii=False,sort_keys=True))"
{"data": [{"context_window": null, "id": "huaweicloud-maas/GLM-5.2", "limits_source": "unknown",
           "max_output_tokens": 16384, "object": "model", "owned_by": "pool"},
          {"context_window": null, "id": "huaweicloud-maas/deepseek-v4.1-flash", "limits_source": "unknown",
           "max_output_tokens": 16384, "object": "model", "owned_by": "pool"}],
 "note": "快照已过期 620.2 小时（上限 24h）⇒ 先重新探测再派活；... 有 2 条模型的窗口未知（context_window = null，回复上限按 16384 发）",
 "object": "list", "snapshot_at": "2026-10-25 20:51:56", "snapshot_stale": true}
~~~

  ⇒ 两条 id 都是 `provider/model` 形式，**没有一条裸 id**。这就是 F85 的「现状 = 无」的活证据。

### 二.3 可复用的开关形状（不是新发明）

- `tools/pool/gateway.py:963-965` 逐字：`def require_origin_from_env(text: str | None) -> bool:` / `"""TF_POOL_GATEWAY_REQUIRE_ORIGIN=1 ⇒ 连**没带 Origin** 的请求也拒。"""` / `return (text or "").strip() == "1"`；常量在 `:91` `REQUIRE_ORIGIN_ENV = "TF_POOL_GATEWAY_REQUIRE_ORIGIN"`；读取点在 `main` 的 `:1283`。本卡的新开关照这个形状写，不发明第二种。
- 另外两条本仓惯例要跟着：`serve_http` docstring `:1250` 逐字「**默认关**：只有显式调用（main）才会监听，import 不动任何端口。」；`build_server` `:1224` 逐字「建服务。**没有 token 就不建** —— 不为「无鉴权」留默认路径。」

## 依赖 / 冲突（`78d4c16a` 实测 backlog）

与卡域四个文件相交的**非 done** 卡，必须串行（同文件并行会撞域）：

- A372 pending：「F56搜索API多key轮换：被拒才换下一个，各自rest」——碰 `tools/pool/gateway.py`、`tests/test_pool_gateway.py`、`docs/subsystems/pool/modules.toml`
- A373 pending：「F94图像识别替身seer：判SKIP_BY_REDLINE并钉住」——碰 `tests/test_pool_gateway.py`、`docs/subsystems/pool/README.md`
- A375 pending：「F82远端provider显式登记：一个地址一段，连不上就点名那台机器」——碰 `tools/pool/gateway.py`、`tests/test_pool_gateway.py`、`docs/subsystems/pool/README.md`、`docs/subsystems/pool/modules.toml`
- A380 pending：「F96 Context 页分段账：只留名字与大小，不搬面板与读回原文」——碰 `tools/pool/gateway.py`、`tests/test_pool_gateway.py`、`docs/subsystems/pool/modules.toml`
- A381 pending：「F14决策模型与 systemone：判 SKIP_BY_REDLINE，落成 ADR 与反向钉子」——碰 `docs/subsystems/pool/README.md`、`docs/subsystems/pool/模型与号池.md`
- A384 pending：「F10 previous_response_id：判SKIP_BY_REDLINE，只钉同协议直通原样透传」——碰 `tests/test_pool_gateway.py`、`docs/subsystems/pool/模型与号池.md`
- A383 pending：「F95隐藏模型：列出来的必须能用」、A385 pending：「F57 searcher 的选择与让位」——**立卡时必须补进 depends**，实算相交见抬头「差额点名」。

depends 三张全部 done（判据引用归属，不进 depends）：A353（禁用的模型：三种名字 × 单星号 glob × 读不到就等于全禁）、E105（禁用表装好了判据却没人问）、E143（F86 窗口读数发布）。
本卡的 docs 面最小：只在 `docs/subsystems/pool/模型与号池.md` 续一节 §8（现有 §7 是「窗口 / 回复上限」，:141）。**不碰** `docs/subsystems/pool/README.md` 的 pool-margin 生成段。

## 判定：PORT（最小形态，默认关）+ 四件不搬写成钉子

- **PORT（本卡做的那一半）**：`/v1/models` 在既有批准集行**之后**追加一圈裸 id 行，只有 `TF_POOL_GATEWAY_BARE_IDS=1` 才开；关着时输出**逐字节**与今天相同。
- **不搬 ①（SKIP_NOT_APPLICABLE）** `GET /v1/models/{id}` 按裸 id 认单个模型（原件 `bare.go:99-110` + `gateway.go:1336-1342`）：本仓 `PATHS` 恰好四键（`tools/pool/gateway.py:99-104`）+ `_dispatch` 精确字典查（`:1086`），加子路径即撞「四条路径，一个都不多」（`:98`）这条既有红线。
- **不搬 ②（SKIP_NOT_APPLICABLE）** 「用网关自己的解析决定裸 id 落到哪个 entry」：pool **没有** provider 目录、**没有**路由组。这不是我的判断，是仓里已经写死的结论 —— `tools/pool/model_registry.py:726-730` 逐字：「**没有「路由组」这个概念**（`model-registry.toml` 只有 `[[model]]` 与 `[pool.*]` 两段，没有组），**没有落点**；- 第 9 步 `Resolve` + `modelOff` —— pool 没有「id 目录 / resolver」」。
- **不搬 ③（SKIP_NOT_APPLICABLE）** 设置面与 GUI（`POST /api/settings/bare-ids`、Settings › Network and sharing）：本仓网关零 `/api/` 路由，配置只走 env / toml。
- **不搬 ④（SKIP_NOT_APPLICABLE）** 请求侧按裸名路由（让裸 id 的请求真打通）：那要动 `_model_block` 的 404（`tools/pool/gateway.py:355-356`）与 `_candidates` 的号级字面比（`:399-400`），等于改「未批模型不许用」这条既有判据。本卡**只发布读数、不接请求**，判据 5 把这条钉住。
- **天然成立 + 钉住**：绝不列给另一台 magpie / Claude Desktop（本仓没有这两个调用方概念，零命中）；绝不改任何 agent 配置文件（本仓不写 agent 配置）。

为什么不判 SKIP_BY_REDLINE：F85 的主体是**只读列表多一圈行**，不翻译协议、不解析自由文案、不建定时器、不做凭据发现、不复制判据、不动 `PATHS` 四键、不写 agent 配置 —— 四条硬边界（`tools/pool/gateway.py:8-14`）一条都不撞。撞红线的部分是 `GET /v1/models/{id}`（撞「四条路径」），已经单独判成不搬。

## 判据（每条都能用一条命令或一个 pytest 证明）

### 判据 1 · 开关默认关时，`/v1/models` 输出与今天逐字节相同

怎么证明：

~~~bash
python -X utf8 -m pytest -q -o addopts="" tests/test_pool_gateway.py -k "models or unapproved or paths_table"
~~~

今天实测 **9 passed, 94 deselected in 17.97s**（`78d4c16a`，真跑）。其中两条既有断言就是钉子：`tests/test_pool_gateway.py:748` docstring 逐字「`GET /v1/models` 只报批准集（只读快照，不联网）。」+ `:753` 逐字 `assert [item["id"] for item in data["data"]] == [MODEL]`；`:1146` 同形（HTTP 面）。**加一行裸 id 就会红** ⇒ 「默认关」不是靠注释，是靠这两条断言。新增一条用例：不设 env 时 `gateway.list_models()` 的 `data` 与上面「实测基线」逐字节相等。

### 判据 2 · 开关只认 `"1"`，且只有一处定义、一处读取

怎么证明：pytest `test_bare_ids_switch_defaults_off` —— `""` / `"0"` / `"true"` / `"yes"` / `"  "` ⇒ 全关，`"1"` ⇒ 开；外加 `grep -c "TF_POOL_GATEWAY_BARE_IDS" tools/pool/gateway.py` == 2（常量定义一处 + `main` 读取一处，形状照 `require_origin_from_env:963-965`）。

### 判据 3 · 打开后：既有行**先原样**、裸 id 行**后追加**，且逐字段指向同一行

怎么证明：pytest 新用例（起真服务 + 真 `GET /v1/models`）三条断言 ——

1. `ids[:n] == 关时的 ids`（条数、顺序、逐字都相同；原件对应句见 `_magpie_features.md:717`「打开后**先原样列它此前列的所有行**，再每个裸 id 一行」）；
2. 追加部分每条 `"/" not in item["id"]`；
3. 每条裸 id 行的 `object` / `owned_by` / `context_window` / `max_output_tokens` / `limits_source` 与被指向的原行**完全相同**，只有 `id` 不同。

### 判据 4 · 尾段冲突就**不列**，并在 note 里报计数（不许静默取第一条）

怎么证明：pytest 新用例造两条 approved（`pa/x` 与 `pb/x`）⇒ 裸 id `x` **不在** `data` 里；`note` 出现带数字的「N 条裸 id 因重名未列」，且 N 是读数（0 也照说）—— 写法照 E143 的窗口未知计数（`tools/pool/gateway.py:818-822` 逐字 `tail = (f"有 {unknown} 条模型的窗口未知（context_window = null，"` / `f"回复上限按 {pool_model_registry.UNKNOWN_MAX_OUTPUT} 发）")`）。

理由：原件靠 groupForIn / resolveIn 决定唯一目标；本仓没有那个 resolver ⇒ 只能把「唯一化规则」**显式写出来**，而不是抄一个近似行为当作等价（见「诚实边界」第一条）。

### 判据 5 · 只发布读数、不接请求：裸 id 发请求仍然 404

怎么证明：pytest `test_bare_ids_are_listed_but_not_routed` —— 开关打开后 `POST /v1/chat/completions`，`model="GLM-5.2"` ⇒ 404 且正文含「不在批准集里」（既有断言形状见 `tests/test_pool_gateway.py:344-350`，docstring 逐字「未批模型 ⇒ 404 + 点名；**不回 429**（回 429 会让调用方白等一个 reset）。」）。这条是「不搬 ④」的钉子。

### 判据 6 · 三件不搬各有一条零命中扫描（不是「还没做」）

怎么证明（三组，必须与今天基线一致）：

~~~bash
grep -rn "DrawersHeader\|X-Magpie\|claude-desktop" tools/ tests/ scripts/
grep -rn "/v1/models/" tools/pool/gateway.py tests/test_pool_gateway.py
grep -rnE "api/settings\|/api/" tools/pool/gateway.py
~~~

今天基线（三条逐条真跑）：第一组 **0 行**；第二、三组 **0 行**。补一条**大小写不敏感**的旁证：把第一组放宽成 claude desktop 与 claude-desktop 两种写法才有 3 处注释 —— `tools/mcp_client.py:36`、`tests/test_mcp_client_independent.py:57`、`tests/test_mcp_line.py:15`，全是「DSH / Claude Desktop 那种配法」的说明，**不是调用方概念**；DrawersHeader 与 X-Magpie 仍然 0 行。落地后这三组必须与基线一致（第一组仍 0 行；放宽写法仍只允许那 3 处注释），并且 `tests/test_pool_gateway.py:1257-1258`（PATHS 恰好四键）与 `:1264-1267`（`/v1/magpie/*` 三条 404）原样绿。

## 卡域 files（精确路径，不许通配）

- `tools/pool/gateway.py`
- `tests/test_pool_gateway.py`
- `docs/subsystems/pool/模型与号池.md`（续 §8：开关名 + 「只发布读数、不接请求」+ 重名不列的规则）
- `docs/subsystems/pool/modules.toml`（gateway.py 那条 `[[module]]` 的 cli 段若列出 env 名，补一处）

本卡**不新建**文件（卡规格本身由立卡脚本落到 复盘/卡/ 下，不列进产品域）。

## 验收命令

~~~bash
# ① 卡域内的两条测试面（改 tools/ + tests/ ⇒ 至少 lang+audit 档，由落地链按域跑）
python -X utf8 -m pytest -q -o addopts="" tests/test_pool_gateway.py
python -X utf8 -m pytest -q -o addopts="" tests/test_model_registry.py

# ② 默认关：打印应与「实测基线」逐字节相同（无裸 id 行）
python -X utf8 -c "import sys,json;sys.path.insert(0,'tools');from pool import gateway;print(json.dumps(gateway.list_models(),ensure_ascii=False,sort_keys=True))"

# ③ 打开：追加的每条 id 都不含 "/"，且前 n 条与 ② 相同
TF_POOL_GATEWAY_BARE_IDS=1 python -X utf8 -c "import sys,json;sys.path.insert(0,'tools');from pool import gateway;print(json.dumps(gateway.list_models(),ensure_ascii=False,sort_keys=True))"

# ④ 开关只有一处定义一处读取
grep -c "TF_POOL_GATEWAY_BARE_IDS" tools/pool/gateway.py

# ⑤ 三件不搬的零命中扫描（口径见判据 6）
grep -rn "/v1/models/" tools/pool/gateway.py tests/test_pool_gateway.py
~~~

门禁本身由落地链（wb_land）按改动域跑 —— 起草与立卡阶段**不**跑 `scripts/run_gates.py`。

## 不许做

- 不许往 `PATHS` 加第五键、不许给 `/v1/models` 开子路径（钉子 `tests/test_pool_gateway.py:1257-1258`）。
- 不许改 `_model_block` / `_candidates` / `_post` 让裸 id 的请求通过（判据 5 钉反向）。
- 不许新增任何 `/api/` 路由、GUI、HTTP 设置面。
- 不许为了「更贴近原件」引入 provider 目录 / 路由组 / resolver —— `tools/pool/model_registry.py:726-730` 已把这条路判死。
- 不许解析任何自由文案（`tools/pool/gateway.py:23-24` 逐字「**绝不解析自由文案**（含中文提示语）。网关每条请求背后都可能是不同上游，正文措辞不可信。」）。
- 不许写任何 agent 配置文件；不许读别人的 agent 配置来猜模型 id。
- 不许反转默认值：env 不设时行为必须与今天**逐字节**相同。
- 不许手改 `docs/subsystems/pool/README.md` 的 pool-margin 段 —— 行数变了就重跑 `scripts/gen_pool_readme.py`。
- 不许改历史文书与台账里 done 卡的任何一行；不许改 `gates/diag/_magpie_scope.md:93` 那行的行号引用（它在那边按当时的快照写，本稿按实读给）。

## 诚实边界（没坐实的事）

- 原件「只列请求真会去到的地方」（`bare.go:17-24`）在本仓**无法等价**：pool 没有 provider 目录与路由组，本卡只能弱化成「只列批准集里已有的行 + 尾段唯一」，**这是不同的语义**。判据 4 的作用就是把差异写成规则，而不是假装等价。
- 未读 `pricedModelObject` 与 magpie 列表项的其余字段（`gateway.go` 只读到 `:1249-1251` 的 `m["id"] = id`），所以「裸 id 行除 id 外还差什么」**未验证**。
- 未坐实 `settings.Load()` / `SetBareModelIDs` 的落盘路径（只读了 `bare.go:26-39` 与 `gui/api.go` 两处行号），「不写 agent 文件」在原件侧是注释 + 我的读法，**不是全链路实测**。
- 未坐实本仓 approved 里出现重复尾段的现场概率：今天实测只有两条（`huaweicloud-maas/GLM-5.2` 与 `huaweicloud-maas/deepseek-v4.1-flash`），无冲突。判据 4 是**设计规则**，不是现场读数。
- 未跑 `scripts/run_gates.py`（起草与立卡硬约束），所以「全量门过不过」**未验证**；只跑了 `tests/test_pool_gateway.py` 的 9 条子集（9 passed）。
- `gates/diag/_magpie_scope.md:93` 写的行号 `model_registry.py:618/:684` 与实读 `:629/:649` 有偏移 —— 本稿按实读给，未改那张表。
- 所有事实实测于 `78d4c16a`；物化时主树 HEAD 已到 `bc41ba76`（只动 A385 规格，所引源码 diff 为空）。基准会漂，写盘那一刻的 HEAD 见抬头与基准说明。

（立卡说明：本规格由草稿 `gates/diag/_draft_F85.md` 物化；草稿被 `.gitignore` 覆盖、不进卡域，只作主树 grep 验收对象。写入者 T-AG674。）
