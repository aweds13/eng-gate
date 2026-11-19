# 卡 A381：F14 决策模型与 /v1/systemone —— 判 SKIP_BY_REDLINE + SKIP_NOT_APPLICABLE

> 台账号 `T-AG669`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A381`｜层 判据层 + 不移植证据｜基准 `6573205b`（立卡时主树 HEAD，2026-11-20 02:20 实读）｜depends E94、E143、A363（三张全 `done`）
> depends 说明：本卡**产品码一个字不改**，卡域四个文件（见「交付」）与今天 14 张活跃卡（D1–D8、C1、C2、A369、A371、A372、E145）的 `files` **零相交**（实跑：tomllib 读 `docs/workbacklog.toml` 的 `d['cards']`，筛 `status in ('pending','running')` 后与本卡域求交 ⇒ 零命中）⇒ `tools/pool/plan.py:321-327` 不会拒单，写 `depends` 是因为**判据引用的红线**归那三张：E94 定的「四条路径、不做协议翻译」（`tools/pool/gateway.py:98`）、E143 立的「不移植也要留一段可核证据」体例（`tools/pool/gateway.py:16-17`）、A363 立的 `wb-route.jsonl` 三条纪律（`tools/pool/route_log.py:1-20`）。
> 基准说明：行号全部按 `171aecef` 逐行 `grep -n` / `awk` 实读；`git log -3` = `171aecef`（chore(ledger) 把卡 E145 规格搬进 git）/ `b8996c7d`（立卡 E145 T-AG660）/ `dce8d904`（feat(pool) F28 窗口登记 T-AG655）。
> 依据：判定表 `gates/diag/_magpie_scope.md:22` 逐字 `| F14 | 决策模型与 /v1/systemone | PORT | no | grep systemone 只命中 rpm.decide 与 route_log 注释，无决策组 |`（★ 这条证据列**不精确**：实测 `grep -F systemone` 全仓 0 行，见缺口 1）。magpie 原件 `internal/gateway/decide.go`、`internal/gateway/decide_group.go`、`internal/provider/decide.go`、`internal/provider/decide_group.go`、`internal/gateway/gateway.go:807`。

## 前情：magpie 的 System One 到底是什么（三件东西 + 一条禁令）

功能清单 `D:/repo/program/_ext/_magpie_features.md:145-151` 的 F14 只有短短几行，但源码里它分成三件东西：

1. **一条自己的端点** `POST /v1/systemone`。`internal/gateway/gateway.go:807` 逐字 `mux.HandleFunc("POST /v1/systemone", s.serveSystemOne)`；:848 的 404 文案把它和另外十二条端点一起念出来；:879 的 `apis` 数组第二项就是 `"/v1/systemone"`；:1297 `m["native_endpoints"] = []string{"/v1/systemone"}`。它是 magpie **自己的** API，不是上游协议的副本 —— `internal/gateway/decide.go:504-508` docstring 逐字：

   > serveSystemOne is magpie's own System One API. The model's prefix names the Jev provider (gptload-jev/jev-latest); the rest is what that provider is asked, at its /v1/systemone. The call is a route of its own, as a conversation is: the Routing view and the day's jsonl would otherwise never see Jev, which answers no /v1/chat/completions.

2. **一类只做决定的模型**（decision model），以及**只装它们的路由组**（decision group）。`internal/provider/decide.go:74-75` 逐字 `// Decides reports whether the provider is a decision API.` + `func (p Provider) Decides() bool { return p.Decide != "" }`；:77-80 `DecideOnly()` 判「连一个对话端点都没有」—— 逐字 `return p.Decides() && p.Chat == "" && p.Responses == "" && p.Anthropic == "" && p.Gemini == ""`。今天只有两个真实供给：`:32-34` 的 `const JevLatest = "jev-latest"`（TypeSafe 的 Jev）与 `:36-38` 的 `const BailianDecision = "decision-model-preview"`（阿里云百炼，同一个 System One API）。组语义在 `internal/provider/decide_group.go:9-16` 包注释逐字：

   > A decision group is a routing group of decision models (Jev and the like) and nothing else (ARNO on Discord: 给decision模型也加上group功能): a System One request naming it (/v1/systemone, "group/<id>" or the group's id or name) goes to its models as a conversation goes to a chat group's, the next asked when one fails. It holds no conversation, so it is kept out of the agents' catalog, a chat group can't hold it, and it takes nothing that shapes a conversation: no patterns, rules, classifier, effort, levels or fast mode.

3. **一个 classifier 宿主**：拿 decision 模型判「这句话是这条规则的哪个 intent」「这一轮要多难」，再据此选模型和 effort。`internal/gateway/decide.go:1-10` 包注释逐字：

   > A group whose classifier is a decision provider's model (Jev, from TypeSafe) asks it in one call, as a user's turn begins, what the classifier model would be asked — which of the rules' intents the message is — and, for a group with Effort "auto", how hard the turn is to think about. Jev answers each with how likely every option was rather than with words: an intent it isn't sure of counts as none, and the effort is the level the likelihoods weigh out to.

**一条禁令**：装 decision 模型的组**不许接任何塑造对话的东西**，也不许进 agent 目录；会话请求点到这种组，magpie 用 **400** 把它指到 `/v1/systemone` —— `internal/gateway/gateway.go:1997` 逐字 `writeError(w, from, 400, fmt.Sprintf("the routing group %s holds decision models: it only decides a routing group's model and effort, asked at /v1/systemone; it holds no conversation", g.Name))`；反过来 `internal/gateway/decide_group.go:49-53` 对「拿聊天组当 decision 组问」也回 400，逐字 `the routing group %s holds models that hold conversations; System One asks a group of decision models, or a decision model as "provider/model"`。

请求形状（功能清单 :148 逐字）：`{"model":"group/<id>","state":{"message":...},"questions":{"intent":{"type":"choice","choices":["bug","feature"]}}}` —— 即「**把问题本身也当成一次被路由的请求**」：body 上限单独定（`decide.go:498-502` 逐字 `// maxSystemOneBody is the most a System One request may be; larger is 413` + `const maxSystemOneBody = 16 << 20`），落账也单独一轮（同 docstring 的 *The call is a route of its own, as a conversation is*）。

## 缺口：本仓今天有没有这个东西 —— **完全没有**（不是「有代码没接线」）

### 缺口 1 · 生产码零命中（六条字面各自为 0）

实跑（仓库根，2026-11-20，`HEAD 171aecef`）：

~~~text
grep -rn -F 'systemone'        --include=*.py --include=*.toml --include=*.md --include=*.txt tools scripts tests docs 复盘 gates/defs | wc -l   ⇒ 0
grep -rn -F 'SystemOne'        （同上 include 集）                                                                                              ⇒ 0
grep -rn -F 'decides('         （同上）                                                                                                          ⇒ 0
grep -rn -F 'DecideOnly'       （同上）                                                                                                          ⇒ 0
grep -rn -F 'jev-latest'       （同上）                                                                                                          ⇒ 0
grep -rn -F 'decision-model-preview' （同上）                                                                                                    ⇒ 0
grep -rn -F 'decide_group'     （同上）                                                                                                          ⇒ 0
~~~

★ **两种必踩的假阳性**，判据里必须避开，否则钉子会假红：

- 裸词 `jev` 会命中云机 instance-id `i-0123456789abcdef0` —— `grep -rnE 'systemone|SystemOne|decision model|jev' --include=*.py --include=*.md --include=*.toml tools scripts tests docs 复盘` 实得 **11 行**，全在这个 id 里（`docs/changelog.md:1792`、`docs/changelog.d/T-AG517.md:5`、`docs/changelog.d/T-AG523.md:21`、`docs/subsystems/ci/云门禁机.md:16/:63/:66/:431/:572`、`复盘/交接-重构进度.md:5221`、`复盘/卡/卡F8-文档读数与意图导航.md:21`）。
- 裸词 `intent` 会命中 `intention` —— `grep -rniE 'jev|decision-model|decision group|classifier|intent' --include=*.py tools scripts` 实得 **9 行**，全是 `scripts/check_layers.py` 的五层对齐（:1/:4/:43/:64/:80/:233/:249/:328）与 `scripts/test_check_layers.py:76` 的 `docs/intention/needs.md`。带 `\bintent\b` 词边界后为 **0**。
- 另外：不加 `--include` 时 `__pycache__/*.pyc` 的字节会让 `decider` 假命中（来自 `hmac.compare_digest` 附近的字符串表）。

### 缺口 2 · 运行时也不存在（四条路径 / 没有方法 / 404 实measured）

- `PATHS` 恰好四条：`tools/pool/gateway.py:98` 逐字 `#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。`；:99-104 `PATHS` = `/v1/chat/completions: ("POST", PROTOCOL_CHAT)`、`/v1/messages: ("POST", PROTOCOL_MESSAGES)`、`/v1/models: ("GET", "")`、`/v1/pool/routes: ("GET", "")`。实跑 `import pool.gateway as g; tuple(g.PATHS)` ⇒ `('/v1/chat/completions', '/v1/messages', '/v1/models', '/v1/pool/routes')`（★ import 名是 `pool.gateway`，`import gateway` 会 `ModuleNotFoundError`）。
- 服务类上没有任何 systemone / decide / prompt 方法：`[n for n in dir(g._Server) if 'system' in n.lower() or 'decide' in n.lower() or 'prompt' in n.lower()]` ⇒ `[]`。
- **真起服务实测**（临时目录 + `gateway.build_server(token="t0ken", host="127.0.0.1", port=0, root=tmp)` + daemon 线程 + `http.client`）：
  - `POST /v1/systemone`（**带** Bearer）⇒ **404**，body 逐字 `{"error": {"type": "not_found_error", "message": "没有这条路径：'/v1/systemone'。本网关只有四条：POST /v1/chat/completions、POST /v1/messages、GET /v1/models、GET /v1/pool/routes。"}}`
  - **不带** Bearer ⇒ **同样 404（不是 401）**。原因在 `gateway.py:1084-1097`：`_dispatch` 先 `spec = PATHS.get(path)`，`if spec is None` 直接 404 返回，之后才 `if not self._gate():`。
  - `POST /v1/decide` ⇒ 404；`GET /v1/systemone` ⇒ 404（不是 405）。
- 「网关自己往对话端点发请求」也只有它自己：`grep -rn 'chat/completions' --include=*.py tools scripts | grep -v 'tools/pool/gateway.py' | wc -l` ⇒ **0**。

### 缺口 3 · 宿主概念不存在：本仓路由只有**排序**，没有「按意图选模型」

- `grep -rniE '\brule|pattern|classifier' --include=*.py tools/pool/gateway.py tools/pool/route.py` ⇒ **RC=1 零命中**。
- `from pool import route; [n for n in dir(route) if 'intent' in n.lower() or 'classif' in n.lower()]` ⇒ `[]`。
- 唯一的定序入口 `tools/pool/route.py:669-676` `def apply_strategy(name: str, seats: Sequence[Seat], *, pool: str, state: dict[str, Any] | None = None) -> list[int]:` docstring 逐字「按名字跑一个内置策略；**坏掉就 fail-open 回列出顺序，绝不抛**。」+「★ 名字先过 `parse_routing`（卡 E103）…名字认不出 ⇒ 仍然退恒等（本函数跑在请求路径上，抛一下就是 500）。」—— 输入是**座位的集合**，输出是**次序**；没有任何「先判意图再挑模型」的位置。
- `grep -rn 'decision' --include=*.py tools/pool/` ⇒ **4 行，全是别的东西**：`tools/pool/gateway.py:664` `decision = pool_rpm.decide(seat, stamp_map.get(seat, ()),`、`:666` `if not decision.allowed:`、`:667` `skipped.append(f"{seat}：{decision.why}")`、`tools/pool/route_log.py:6` 注释 `> It's recorded where the decisions are made, from the same values they are made with;` —— 那是**每分钟闸**，与 decision model 语义无关。

### 缺口 4 · 外部资产也不存在：没有可问的 decision 号

- 仓外账本 `D:/repo/infra/pool/accounts.toml`：`grep -rniE 'jev|decision|systemone|classifier'` ⇒ **0 行**。
- `tools/pool/platforms.toml`：九个平台段（`[platform.codearts]` 起，:43/:72/:100/:125/:151/:178/:199/:219/:245，`grep -c '^\[platform\.'` ⇒ **9**），`grep -nci 'decide\|decision'` ⇒ **0**；文件头 :13-20 逐字说明 `chat_urls` 空数组「= **没登记**这个平台的 chat 端点，**不是**「不支持」」—— 连 chat 端点都还没登记，更没有 decision API 一栏。
- `tools/pool/model-registry.toml`（63 行）：`grep -nci 'decide\|decision\|systemone\|jev'` ⇒ **0**。

**结论：判 SKIP，不是欠账。** 今天本仓既没有这条端点、也没有这套宿主概念、也没有可问的号。

## 为什么不移植（两半，理由不同，别混成一句）

### 第一半 · SKIP_BY_REDLINE：做得出来，但做了就破本仓明文边界

- `tools/pool/gateway.py:8` 逐字「1. **不做协议翻译**」；:98 逐字「四条路径，一个都不多」。加第五条 `/v1/systemone` 就是把「一个都不多」这句判据自己推翻，而它正是 `tests/test_pool_gateway.py:686-696` 在钉的东西（:687 docstring 逐字「只有四条路径：别的一律 404；方法不对一律 405 且带 `Allow`。」）。
- 更根本的是**语义**：System One 的 body 不是对话，是「问题 + 候选答案 + 概率」；回话也不是 chat completion。搬它就得搬一层**语义翻译**，而本仓的第一条硬边界恰恰是「不搬 magpie 的协议翻译层」（`gateway.py:3-5` 逐字「只搬「选号 → 转发 → 换号 → 留痕」这条链。**不搬**它的协议翻译层（forwardOnce / ir.go / decoderFor）」）。
- classifier 那一半还要一个**请求前**的调度点（「用户这一轮开始时先问一次」）。本仓的请求路径是「解析 → 选座 → 转发 → 留痕」一条直线，没有「先问一次再决定」的位置；硬塞进去等于给每个请求加一次**额外的上游往返**，而本仓的红线是 `gateway.py:11` 逐字「3. **不做定时器**：没有后台线程；沉底 / 每分钟闸 / 并发闸都是每次请求现读现算」所代表的「一次请求一次判定」。

### 第二半 · SKIP_NOT_APPLICABLE：本仓没有这套输入

- decision 模型是**厂商私有资产**（`internal/provider/decide.go:32-38` 的两个常量就是全部真实供给），本仓仓外账本与平台表里**一个都没有**（缺口 4）。移植过来会是一段**永远跑不到**的代码 —— 那不是移植，是占位。
- 「intent / rules / effort auto」这套宿主概念本仓从来没有（缺口 3）。没有 rules，就没有「这句话是哪个 intent」可判；没有 effort auto，就没有「这一轮多难」可用。

### 为什么这条 SKIP 要落成证据而不是「不写就完了」

E143 立过体例：不移植也要在**生产码的 docstring** 里留一段 `F86 ③ 不移植`（`gateway.py:16-17` 逐字「F86 ③ 不移植（卡 E143）：… 按 95% 挑号需要 token 计数，本仓没有分词器。」），并在 `docs/subsystems/pool/模型与号池.md:165-167` 写一段「这是决定，不是欠账」（逐字「**F86 ③「按 95% 挑号」不移植**：… 所以本仓只做**发布读数**这一半，挑号那一半留给消费方。」）。理由在 `docs/subsystems/pool/README.md:79-80` 逐字：卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写。本卡照同一体例，但**不动** `gateway.py`（那是 A372 的域）：证据落在 **ADR + 新测试文件 + tracked 文档**三处。

## 判定（先给结论）

| 半边 | 判定 | 一句话理由 |
|---|---|---|
| `POST /v1/systemone` 端点本体 | **SKIP_BY_REDLINE** | 撞 `gateway.py:8`「不做协议翻译」与 :98「四条路径，一个都不多」；body / 回话都不是对话 |
| decision group（只装 decision 模型的路由组 + 逐 key failover） | **SKIP_NOT_APPLICABLE** | 本仓没有 decision 号（仓外账本 / 平台表 / 模型注册表三处零命中） |
| classifier 宿主（rules/intent → 选模型 + effort） | **SKIP_NOT_APPLICABLE** | 本仓路由只有排序（`route.py:669-676`），没有 rules / effort auto 这套输入 |
| 会话请求被 400 指到 `/v1/systemone` | **SKIP_BY_REDLINE** | 本仓对应位置是 404（`gateway.py:1086-1090`），文案只点四条 —— 已是边界，不许再加指路 |

## 判据（五条，逐条给「怎么证明」）

### 判据 1 · 端点不存在要钉在**真服务**上：`POST /v1/systemone` 与 `POST /v1/decide` 都 404，且文案只点四条

新建 tests/test_pool_no_systemone.py（体例照 `tests/test_pool_gateway.py:686-696` 的 `start_server` + `_request` 形状，但**夹具自带**：`tmp_path` + `gateway.build_server(token=..., host="127.0.0.1", port=0, root=tmp)` + daemon 线程 + `shutdown/server_close/join(5)`）。断言四件：

1. `POST /v1/systemone` ⇒ `status == 404`；
2. body 里 `json.loads(...)["error"]["type"] == "not_found_error"`；
3. body 文案含「只有四条」与四条路径字面，且 `'"systemone" not in text'`、`'magpie' not in text`（**不许**在错误文案里点名 magpie 或 systemone —— 那等于给调用方指路）；
4. **不带** Bearer 时也是 404（钉住「先查 PATHS 后鉴权」这个次序，`gateway.py:1086-1097`）—— ★ 反过来说，这条**不能**断 401。

- **怎么证明**：`python -X utf8 -m pytest tests/test_pool_no_systemone.py -q -o addopts= --no-cov` 全绿；把 `gateway.py:1096` 的 `if not self._gate():` 挪到 `if spec is None` 之前 ⇒ 第 4 条变 401 ⇒ 红。

### 判据 2 · 生产码里**不许出现** @systemone` 这个字面，且 `PATHS` 恰好四条（AST/源码钉）

同一个测试文件里两条：

- 源码钉：`source = (ROOT / "tools" / "pool" / "gateway.py").read_text(encoding="utf-8")`，断言 `'systemone' not in source.lower()` 且 `'decide_group' not in source` —— 这样即使有人只加一个常量（不接线）也会红。
- 结构钉：`tuple(pool_gateway.PATHS) == ('/v1/chat/completions', '/v1/messages', '/v1/models', '/v1/pool/routes')`（精确相等，不是 `in`），另加 `[n for n in dir(pool_gateway._Server) if 'system' in n.lower() or 'decide' in n.lower()] == []`。

- **怎么证明**：同上 pytest 命令；把 `gateway.py:99-104` 的 `PATHS` 加一条 `"/v1/systemone": ("POST", PROTOCOL_CHAT)` ⇒ 两条同时红。

### 判据 3 · 全仓**生产码**零命中的扫描钉（范围写死，别让它咬到本卡自己的产物）

`scope = tools/ 与 scripts/ 下的 `*.py`（**不含** `tests/`、不含 `docs/`、不含 `__pycache__`）`，逐文件读文本，断言四个形状各 0 次命中：

- `'systemone'`（大小写不敏感）
- `'jev-latest'` 与 `'gptload-jev'`（★ **不扫**裸 `jev`：会命中云机 instance-id `i-0123456789abcdef0`，见缺口 1）
- `'decision-model-preview'`
- `re.search(r'\bintent\b', text)`（★ 用词边界：裸 `intent` 会命中 `intention`，见缺口 1）

★ **范围为什么只到生产码**：本卡的产物（ADR + `模型与号池.md` 新节 + 这个测试文件本身）**必须**写出 `systemone` 才能把决定说清楚（判据 5 反过来断言它们**确实写了**）。把 `docs/` 或 `tests/` 也纳入零命中扫描，就是自己咬自己 —— 这条边界必须写在测试文件的模块 docstring 里，**不许**靠一个淹没式的 `skip` 列表糊过去。

- **怎么证明**：同 pytest；在 `tools/pool/route.py` 末尾加一行 `def classify_intent(text): return None` ⇒ 第 4 条红；把字面 `systemone` 塞进 `tools/pool/gateway.py` 的注释 ⇒ 第 1 条红（判据 2 也红，双咬，正确）。

### 判据 4 · ADR docs/decisions/0011-no-systemone.md 存在且过机器检查

断言三件：

1. 文件存在、文件名匹配 `^([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$`（`docs/decisions/README.md:30` 的正则，逐字「slug 只用小写字母、数字、连字符；新记录取「当前最大号 + 1」」）；
2. 五个必需节齐全：`## 背景与问题` / `## 候选方案` / `## 决定` / `## 把握程度` 四节 + 头信息 `Status:` / `来源:` 非空（`docs/decisions/README.md:33-69` 的模板）；
3. 跑真检查器：`importlib` 载入 `scripts/check_docs.py`，`assert cd.check(ROOT).problems == []`（体例照 `tests/test_check_docs.py:566-568` 的 `test_real_tree_passes`，逐字 `assert cd.check(ROOT).problems == []`）—— 这条同时保证「编号连续无洞」「HEAD 里已 Accepted 的 0001..0010 一条都没被改」。

- **怎么证明**：`python -X utf8 -m pytest tests/test_pool_no_systemone.py -k adr -q -o addopts= --no-cov` + `python -X utf8 scripts/check_docs.py --decisions`（今天实跑 RC=0，输出 `[info] 决策记录：扫到 10 条（编号 0001..0010），supersedes 链 0 对`）；把 ADR 的 `## 把握程度` 整节删掉 ⇒ 第 2 条红且 `check_docs.py --decisions` 退 1。

### 判据 5 · 「这是决定，不是欠账」必须写在 **tracked 文档**里（两处各一句）

1. `docs/subsystems/pool/模型与号池.md` 新增 `## 8.`（该文件今天七节，末节 :141 是 `## 7. 窗口 / 回复上限…（卡 E143 · T-AG657）`，全文 170 行），节内**必须**同时出现「不移植」「0011」两个词，体例照 :165-167 的 F86 ③ 段（粗体一句结论 + 理由 + 归属）。
2. `docs/subsystems/pool/README.md` 的`表 B · pool 不做的事`（:164 标题，:168-174 现七行）新增一行，四格齐全（`| # | 不做 | 归谁 | 证据 |`）—— 证据那格指 ADR 与测试文件。

断言方式照 `tests/test_pool_mcp.py:1040-1053` 的现成体例（`doc = (ROOT / "docs" / "subsystems" / "pool" / "模型与号池.md").read_bytes().decode("utf-8")` / 找行 / 逐条 `assert`）：

- `模型与号池.md` 里 `next((ln for ln in doc.splitlines() if ln.startswith("## 8.")), None)` 不是 `None`，且从该行到文末的文本里 `'不移植' in section` 与 `'0011' in section`；
- `README.md` 表 B 段落里有一行同时含 `'systemone'`（或 `'/v1/systemone'`）与 `'0011-no-systemone'`。

★ 两处都在**生成器标记之外**：`scripts/gen_pool_readme.py:67-68` 的 `<!-- pool-margin:begin/end -->` 区段只覆盖自动表，`diff_lines` docstring 逐字「标记外的行不看 —— 那些字不是本脚本的（§3 决策、§5 边界），改了它们不该让 `--check` 红」⇒ 加表 B 一行**不会**让 `--check` 红，但**必须**断言它仍然退 0。

- **怎么证明**：`python -X utf8 -m pytest tests/test_pool_no_systemone.py -q -o addopts= --no-cov` + `python -X utf8 scripts/gen_pool_readme.py --check`（今天实跑 RC=0，输出 `[OK  ] docs/subsystems/pool/README.md 与现算一致（52 个文件 / 21297 行 / 2026-11-20）`）；把 `## 8.` 整节删掉 ⇒ 判据 5 红。

## 反向变异（四条，外加一条只改注释的安静对照）

脚本落 `gates/diag/_rev_F14.py`（`gates/diag/*` 被 `.gitignore:76` 忽略，不进 git），每条**真改 → 真跑 → 真还原**，并记改前改后的 `sha256` 自证。

| # | 改哪一行（锚点原文） | 哪条判据红 | 怎么红 |
|---|---|---|---|
| M1 | `tools/pool/gateway.py:99-104` 的 `PATHS` 里插一条 `"/v1/systemone": ("POST", PROTOCOL_CHAT),` | 判据 1 + 判据 2 | 判据 1：真服务不再 404（会走到 `route_once`，无候选 ⇒ 4xx 但不是 404 文案）；判据 2：`tuple(PATHS)` 不再等于四元组，`'systemone' in source.lower()` 也为真 |
| M2 | `tools/pool/gateway.py:1096` 的 `if not self._gate():` 挪到 `:1086` 的 `spec = PATHS.get(path)` 之前 | 判据 1（第 4 条） | 无 Bearer 的 `POST /v1/systemone` 返回 401 而不是 404 |
| M3 | `tools/pool/route.py` 末尾加 `def classify_intent(text: str) -> None: return None` | 判据 3 | `\bintent\b` 在 `tools/` 生产码命中 1 次 |
| M4 | `docs/subsystems/pool/模型与号池.md` 的 `## 8.` 节整段删除 | 判据 5 | `startswith("## 8.")` 找不到行 |
| **E1（安静对照）** | `tools/pool/gateway.py:11` 的注释措辞：把「**不做定时器**：没有后台线程」改成「**不做后台定时器**：没有后台线程」 | **一条都不红** | 证明判据 1/2/3 不是「只要文件被改就红」，而是钉在具体字面与结构上 |

★ 变异脚本必须先把原文件读成字节、改、跑、**在 `finally` 里按原字节写回**，并断言还原后 `sha256` 等于改前值 —— 否则一次失败的变异会把树留在坏状态。

## 交付（逐文件）

五个文件，**产品码零改动**：

| 文件 | 动作 | 内容 |
|---|---|---|
| docs/decisions/0011-no-systemone.md | 新建 | ADR：`# 0011 不移植 magpie 的决策模型与 /v1/systemone` / `Status: Accepted` / `Date:` / `Supersedes:`（空）/ `Superseded-by:`（空）/ `来源:`（台账 + 本卡 + 判定表 :22 与本卡对它的更正）/ 四节：背景与问题（三条红线 + 零命中读数）/ 候选方案（A 真移植、B 只搬分组 failover、C 不移植只钉证据 —— 各写代价）/ 决定（选 C，因为 A 破两条明文边界、B 没有输入）/ 把握程度（`medium —— 依据是本仓六条 grep 读数与两条源码边界，但 magpie 侧只读源码、没在真 decision 号上跑过`） |
| tests/test_pool_no_systemone.py | 新建 | 判据 1–5 的 5~8 条 `def test_`；模块 docstring 分「病 / 判据 / 为什么零命中扫描只到生产码」三节（体例照 `tests/test_no_window.py`） |
| `docs/subsystems/pool/模型与号池.md` | 改（只追加 `## 8.`） | 「## 8. 决策模型 / System One：不移植（卡 A381）」，体例照 :165-167 |
| `docs/subsystems/pool/README.md` | 改（表 B 加一行，标记之外） | 第 8 行：不做「决策模型路由 / System One」，归「本仓不做」，证据指 ADR + 测试 |
| `复盘/卡/卡A381-F14决策模型与systemone-判SKIP_BY_REDLINE.md` | 新建 | 立卡后把本草稿搬成正式卡规格 |

**卡域里不列** `tools/pool/gateway.py`、`tests/test_pool_gateway.py`、`docs/subsystems/pool/modules.toml`：前两个是 A372 的域、第三个是 A371/A372 的域，且本卡**一个字都不改**它们。这正是这条 SKIP 的分量所在 —— 如果哪天有人要动 `PATHS`，那是另一张卡，得先把本 ADR 推翻。

## 验收（可直接跑）

~~~bash
cd .wt/A381
python -X utf8 -m pytest tests/test_pool_no_systemone.py -q -o addopts= --no-cov
python -X utf8 -m pytest tests/test_check_docs.py -k real_tree -q -o addopts= --no-cov
python -X utf8 scripts/check_docs.py --decisions
python -X utf8 scripts/gen_pool_readme.py --check
python -X utf8 -m ruff check tests/test_pool_no_systemone.py docs/decisions/0011-no-systemone.md
python -X utf8 gates/diag/_rev_F14.py
~~~

**已知噪音**：

- 新增 ADR 会让 `docs/INDEX.md` 的篇数从 11 → 12（今天 :26 `| `docs/decisions/` | 11 | 0 | 11 |`、:450 `**`docs/decisions/`（11 篇）**`），**不要手改** —— 落地链自己跑 `scripts/gen_doc_index.py`（`tools/pool/landing.py:98-103` 逐字「落地链**自己会改**的**现算文档**」+ `RECOUNT_DOCS / RECOUNT_GENS` 一一对应）。单独跑 `gen_doc_index.py --check` 会红，那是预期的。
- `scripts/check_docs.py --mode report` 的 `drift` 一项今天就是 `+168` 超额（基线 379），只报告不判红；本卡不负责清它。
- `scripts/check_layers.py` 今天 RC=0（`LAYER CHECKS: PASS ✅`）。★ 若在 tracked 文档里写了**未建**路径的反引号会红它 —— docs/decisions/0011-no-systemone.md 与 tests/test_pool_no_systemone.py 是**本卡要建**的，写反引号安全；ADR 里若要提别的未建物，写「（计划建）」或去反引号。

## 不许做

1. **不许动 `tools/pool/gateway.py` 一个字** —— 尤其 `PATHS`（:99-104）、404 文案（:1088-1090）、模块头四条硬边界（:7-14）。判据 1/2 就是钉它们。
2. **不许动 `tests/test_pool_gateway.py:686-696`**（`test_http_only_four_paths`）与同文件 :789-798（唯一一条「不移植」先例钉子）—— 既有判据一个字都不许放宽；新钉子另立文件。
3. **不许改 `scripts/check_docs.py` 的 ADR 判据**（五段齐全 / 编号连续 / HEAD 冻结），也不许改 `docs/decisions/0001..0010` 任何一条（判据 4 靠它判，改了就是自证清白）。
4. **不许动 `docs/subsystems/pool/modules.toml`**（A371/A372 同域），也不许手改 `docs/INDEX.md` 与 `README.md` 的 `pool-margin` 段。
5. **不许碰仓外文件** `D:/repo/infra/**`（账本、号池快照都只读；本卡连读都只读一次取零命中读数）。
6. **不许为了让判据绿而放宽扫描范围**：判据 3 的范围边界（只到 `tools/` + `scripts/`）必须写在测试 docstring 里并给出理由；不许用大段 `skip` 列表、不许把 `systemone` 从断言里删掉。
7. **不许把 SKIP 写成「以后再说」** —— `docs/subsystems/pool/README.md:183-184` 的越界判据逐字含「出现"未来会做"」，写了就判不通过。

## 与已完成卡的关系

- **E143**（F86 ③ 上下文窗口与回复上限）立了「不移植也要留可核证据」的体例：生产码 docstring 一段 + tracked 文档一节 + 一条 `pytest -k`。本卡照抄这个体例，但把证据落在 ADR（因为 `gateway.py` 已归 A372）。
- **E94**（号池网关同协议直通）立了「四条路径，一个都不多」与「不做协议翻译」两条边界（`gateway.py:3-8`、:98）。本卡的 SKIP_BY_REDLINE 就是这两条的推论。
- **A363**（路由账 `wb-route.jsonl`）立了三条纪律：值必须是调用方事实 / tried 为空不写 / 追加不环形（`route_log.py:1-20`）。magpie 的 System One 是「一条自己的 route」，若移植就得给它开第二本账或第二套 status 闭集（`route_log.py:95` 四值）—— 这也是不做的一条理由。
- **A373 / A374 / A375**（同批兄弟草稿，未跟踪）分别处理 F94 图像替身 / F58 web_fetch / F82 远端 provider；F94 与本卡同为 SKIP_BY_REDLINE 型，体例互通。

## 未坐实项（草稿如实标注，别当成结论）

1. **magpie 的 decision API 实机行为没有取证** —— 本卡只读源码与文档，**没有**向 Jev / 百炼 `decision-model-preview` 真发过一次请求。功能清单自己就把 F14 列进「只靠文档（仅文档，无任何已核）：29 条 —— …F14…」（`_magpie_features.md:37` 逐字），本卡与它同一诚实度。
2. `internal/gateway/decide_group.go:295-324` 的「所有 try 共享同一段 classifier 等待」只读了**注释**（逐字 *Every try shares the one classifier's wait…*），**没有**逐行核实现体；这条只作为「宿主概念的复杂度」证据，不作为判据。
3. decision group 的 failover 细节（`serveDecisionGroup` :87 起、`decideTries` / `postDecide` 的分支）**只读到签名与注释层**，未逐支核。
4. 判定表 `gates/diag/_magpie_scope.md:22` 的证据列写着「grep systemone 只命中 rpm.decide 与 route_log 注释」—— 实测是 **0 行**。本卡**不修改**那份判定表（它在 gitignore 的 `gates/diag/` 里，且不属于本卡域），只在 ADR 的「来源」里如实记一笔「本条证据列已由本卡更正为零命中」。
5. 「将来若接入 decision 号，SKIP_NOT_APPLICABLE 那一半是否失效」—— 这是 **ADR 要写明的失效条件**，不是本卡能判的事：本卡只能保证「今天没有」，不能保证「永远没有」。
