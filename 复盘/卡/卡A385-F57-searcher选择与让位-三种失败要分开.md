# 卡 A385：F57 searcher 的选择与「让位」—— 三种失败要分开

> 台账号 `T-AG673`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A385｜层 判据层（纯函数 + 钉子，**不接线**）｜基准 `f7d4d305`（立卡时主树 HEAD，2026-11-20 05:35 实读）｜depends A372
> depends 说明：草稿列了 A372、A363、A345、E94 四张。2026-11-20 实读 `docs/workbacklog.toml` 的 status：**A372（`docs/workbacklog.toml:6624`）仍 pending**，留在 depends；**A363（`:4977`）、A345（`:4743`）、E94（`:5564`）三张已 done**，一律降级成读法参照（见末节「与已完成卡的关系」）。★ 按今天实况核过：留 done 卡**不会**报冲突 —— `tools/pool/plan.py:267-272` 的 T-G119 更正写明 done / failed **不参与冲突判定**（`:268` 逐字「**`done` / `failed` 不参与冲突判定** —— 它们占过的文件与树**已经释放**」）。不留在 depends 的理由是：depends 只该列还欠着的依赖，队列读者不必再回 backlog 查一遍状态。**A372（F56 搜索 API 多 key 轮换）今天还没落地**：tools/pool/search.py、tools/pool/search-vendors.toml、tests/test_pool_search_keys.py 三件实测都不存在（`os.path.exists` 三条全是 False，2026-11-20 实读）。本卡要回答的「谁是可被问的 searcher、它有没有 key」只能来自 A372 的 vendor 表；**A372 不落，本卡不许开工**（否则本卡会长出第二份 vendor 名单）。A363 是 `tools/pool/route_log.py` 的卡 —— 本卡**不碰**那个文件（理由见「不许做」第 1 条）。A345 是 `tools/pool/sticky.py` 的卡 —— 「卡粘性」与「searcher 的选择」是同一形状（两层选择 + 理由），本卡只借读法不借字段。E94 是 `tools/pool/gateway.py` 的卡，它立的四条硬边界（不翻译协议 / 不做凭据发现 / 不做定时器 / 不复制判据）本卡全部继承。
> 域相交（**未拍板**，登记进队列前必须处理）：本卡 files 含 `docs/subsystems/pool/modules.toml`；2026-11-20 实读，pending 且 files 也含它的还有 A372、A374、A375、A380 四张。`tools/pool/plan.py:170-180` 的 `files_intersect()` 是**精确字符串**集合相交（不认通配）、`:233-240` 的 `dependency_path()` 认传递、`:257-340` 的 `validate()` 冲突类 ①（判定在 `:320-327`）要求「同域两卡之间必须有依赖路径」才允许共存，且只判 pending / running。两条出路：(a) depends 再加 **A380** —— 它的 depends 已含 A374、A375、A372，传递即可覆盖四张，代价是本卡排到它们之后；(b) files 去掉 modules.toml —— 代价是 `scripts/gen_pool_readme.py --check` 退 1 并点名缺 searcher.py。**倾向 (a)，未拍板**（决定权在立卡人）。
> 基准说明：立卡时主树 HEAD = `f7d4d305`（`git rev-parse --short HEAD` 实读，2026-11-20 05:35；该提交 2026-11-20 05:25:00 +0800，提交语「feat(pool): F26整窗用量估算接进派活面：没料就说得出为什么，不许估0（T-AG654）」）。草稿起草时的基准是 `08364825`，起草期间到过 `466a2578`；本文全部本仓「文件:行号」已按 `f7d4d305` 逐条重核，与草稿的差异逐处写在正文里（`tools/pool/gateway.py` 的 `classify` 180→**181**、换号循环 544→**651**、`continue  # server / other` 602→**709**、`route_once` 的 `forward` docstring 501-503→**613-614**、`_order` 431-435→**530**；`tools/pool/model_registry.py` 的 `class ModelEntry` 135→**136**；`tools/pool/outcomes.py` 的 `is_outcome` 124→**123**；`tests/test_pool_rest.py` 现共 **328** 行，草稿的 304-333 越界）。落地前按当时 HEAD 再核一次。
> 依据：`gates/diag/_magpie_scope.md:65` 逐字 `| F57 | searcher 的选择与「让位」 | PORT | no | 同上，无 searcher 选择逻辑 |` + `../_ext/_magpie_features.md:488-494`（原件在本仓**上一级**目录 `D:/repo/program/_ext/`，故写作 `../_ext/...`）+ magpie 原件 `../_ext/magpie-main/internal/gateway/search.go`（1287 行，逐行读过）、`../_ext/magpie-main/internal/netguard/netguard.go`（97 行，F57 的「让位到哪」与 F58 共用一份地址判据）。

## 前情

magpie 解决的是一个**静默失效**问题：把「搜了但没找到」「压根没搜」「报错」三件事混成一团，搜索就会在没人发现的情况下退化成「模型凭记忆回答」。`../_ext/_magpie_features.md:490` 逐字：

> 解决："搜了没找到"和"压根没搜"和"报错"混为一谈会让搜索静默失效。

它的实现由三段组成，本卡只移植其中**判据层**（纯函数），不接线：

1. **选谁**：`settings.Searcher`（空 = 自动；`"off"` = 关掉 provider 搜索）→ `chosenSearcher()` 给出 `(provider, model, why)`，`why` 是四值闭集（`../_ext/magpie-main/internal/gateway/search.go:379-385`）：

```go
SearcherGone = "gone"   // no such provider any more
SearcherOff  = "off"    // turned off, or signed out
SearcherCant = "cant"   // it can't search the web by itself
SearcherNoneOf = "nomodel" // it lists no model to search with
```

2. **问几个、按什么序**：静态排名 `searchRank`（`search.go:300-327`，草稿写 300-326，实读末行 327）+ 自动挑 `autoSearcher`（`:350-377`，有额度的排在全耗尽的之前 —— `:364-374` 的 `bestReady` 规则）+ 一轮最多问 `searchersInTurn = 3` 个（`:720-722` 逐字注释 `searchersInTurn is how many searchers a search is asked of, in turn, before it goes to the search APIs.`）。

3. **问完怎么判**：`searchWith` 只看响应的结构化块（`server_tool_use` / `web_search_tool_result` / `text`），三种结局在 `search.go:992-997` 逐字（草稿写 991-998；实读 `said :=` 在 992、这一块止于 997）：

```go
said := strings.TrimSpace(text.String())
if said == "" || (len(found) == 0 && !strings.Contains(said, "://")) {
    if !searched {
        return "", nil, fmt.Errorf("%s/%s %w", p.ID, model, errNotSearched)
    }
    return "", nil, fmt.Errorf("%s/%s %w", p.ID, model, errFoundNothing)
}
```

两个哨兵在 `search.go:898-906` 逐字：`var errFoundNothing = errors.New("found nothing")`（注释 `a searcher's reply that names no page it found`）；`var errNotSearched = fmt.Errorf("answered without searching the web: %w", errFoundNothing)`（注释原话 `It is found nothing too.`）。

**让位规则**（`search.go:724-730` 的包注释逐字）：「one magpie picked that fails or finds nothing gives way to the next searcher magpie would pick … One Settings names gives way to none: the search APIs, when set up, search in its place (webSearch), and Settings says it didn't search (SearcherFailed).」

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 本仓**完全没有** searcher 这个概念，也没有「三种失败」

实测（基准 `f7d4d305`，2026-11-20 实读）。下面三段是复跑用的原文（`python -X utf8 - <<PY` 跑，`os.walk` 而不是 grep —— git bash 的 grep 遇中文路径退 255）：

```
# 1) 概念：三棵目录树的全部 .py 里搜 searcher|errFoundNothing|not_searched|found_nothing
[]
# 2) 协议块：tools/ 下全部 .py 里搜 web_search|server_tool_use|web_search_tool_result|tool_use
tools/pool/jobs.py:248      elif item.get("type") == "tool_use":
tools/wb_dispatch.py:2188   if not isinstance(item, dict) or item.get("type") != "tool_use":
tools/wb_dispatch.py:2286   def _tool_use_blocks(lines: list[str]):
tools/wb_dispatch.py:2305   if isinstance(item, dict) and item.get("type") == "tool_use":
tools/wb_dispatch.py:2354   if not isinstance(item, dict) or item.get("type") != "tool_use":
# 3) 文件名：tools/pool 下含 search|searcher|seek 的条目
[]
```

⇒ **不是「有代码没接线」，是「完全没有」**。`tools/pool/` 实读 54 个条目（命令：`ls tools/pool | grep -v __pycache__ | wc -l`；2026-11-20 读数，会变），没有任何一件能回答「这次是搜了没找到、还是压根没搜」。

★ 草稿在这里有一处口径不准，物化时改正：草稿说「`web_search|server_tool_use|web_search_tool_result` 只命中 `tools/pool/jobs.py:248` 与 `tools/wb_dispatch.py`」。实读是那条 pattern **零命中**；命中的是 `tool_use` 这个词本身 —— 上面第 2 段列出的那些行解析的是**工人日志**里的 `tool_use` / `tool_result` 块（看门狗配对），一条也不能拿来当「本仓已有 searcher 判据」。

### 缺口 2 · 既有两件**看着像**、语义不是同一层 —— 别拿来冒充

`tools/pool/outcomes.py:1-10`（模块 docstring 逐字，节选）：

> 按**请求**而不是按轮统计结局（移植自 magpie `internal/usage/usage.go:777-806`）……**两者语义不同一层**：magpie 的重试是「换上游再试一次」，pool 的续跑是「同一个工人带同一会话接着干」。

它记的是**一轮请求的结局**：`:61` `OUTCOME_HANDED_ON = "handed_on"`、`:68` `COUNT_KEYS = ("requests", "errors", "retried", "handed_on")`、`:123` `def is_outcome(...): return not row.get(OUTCOME_HANDED_ON)`（草稿写 :124，实读定义在 :123）。它的 `handed_on` 是**续跑**（这一轮失败、把请求交给下一轮），**不是** searcher 让位。

`tools/pool/gateway.py:651` 的 `for idx in _order(cands, routing, pool=pool, model=model, now=clock)`（草稿写 :544）是**同一个模型多个号**的轮转，`:709` 逐字 `continue  # server / other ⇒ 换下一个号，不降权`（草稿写 :602）—— 连 500 都换号；429 沉底在 `:691-696`（草稿写 :581-586）。magpie 的让位是**换 searcher（provider / 模型）**，而且点名的 searcher **一个都不换**（`search.go:753-761`，失败文案逐字带 `(the searcher picked in Settings › Web search: no other provider searches in its place)`）。**换号 ≠ 让位**，两件事混在一处会让 429 沉底与 searcher 让位互相污染。

### 缺口 3 · 「谁知道谁会搜网页」这件事在本仓无处可查

`tools/pool/model_registry.py:136-149`（草稿写 135-149，实读 `class ModelEntry:` 在 `:136`）：

```python
class ModelEntry:
    """一条注册表记录：``alias / pool / id / default / note`` + 两个**可选**窗口字段。"""
    alias: str
    pool: str
    id: str
    default: bool
    note: str = ""
```

`:197` `for key in ("alias", "pool", "id"):`（三个必填键，其余靠 `.get` 默认）；`tools/pool/model-registry.toml:19-24` 把五个字段写死成 `alias / pool / id / default / note`，`:26-28` 另有两个可选窗口字段 `context_window` / `max_output`（留空 = 不知道）。⇒ **没有任何「会不会搜网页」的能力列**，也没有「这个 provider 有几个 model 能搜」。

### 缺口 4 · 让位链今天**没有落点可读**，而最顺手的落点被一条钉子挡着

`tools/pool/route_log.py:90-100` 的 status 是**四值闭集**（`STATUSES` 定义在 `:95`）；`:151-153` 逐字：

```python
    if status not in STATUSES:
        raise RouteError(
            f"status={status!r} 不在闭集 {list(STATUSES)} 里 —— 第五个值不许发明")
```

`tried` 的每条只能是 `{"model", "fail"}` 两个键（`:122-130` `_one_try` 的返回值逐字 `return {"model": model.strip(), "fail": _fail_text(row.get("fail"))}`）；`tests/test_pool_route_log.py:97` 逐字 `assert rows[0]["tried"] == [{"model": M1, "fail": ""}]`（硬等，多一个键就红），`:252-271` 逐字 `assert route_log.STATUSES == ("served", "all_failed", "stopped", "quota_blocked")`。

⇒ 本卡**不改这两处**（A363 的判据 9）。让位链走**返回值**（内存级可核），落盘留给以后再开卡 —— 与 magpie 一致：magpie 的让位账也**不落盘**，它挂在 ctx 的 `CallFor` 上（`search.go:61-92` 的 `Instead / Why / NothingFound / NotSearched / Picked` 五字段，json `omitempty`）和内存里的 `SearchFailure`（`:799-814`，其中 `lastNamedFail` 是 `:799-804`）。

### 缺口 5 · 「点名的就不许让位」这条**没有任何对应物**

本仓所有「选择」都是**尽力而为**：`tools/pool/gateway.py:530` 的 `_order` 调 `apply_strategy`，而 `tools/pool/route.py:669` 的 `apply_strategy` docstring 逐字「按名字跑一个内置策略；**坏掉就 fail-open 回列出顺序，绝不抛**」（`except RouteError` 在 `:688-691`，`MANUAL` 走 `identity` 在 `:692-693`；`identity` 定义在 `:355`）。**没有一处**表达「这是人点名的，它失败了就报错、不许悄悄换一个」。而 magpie 恰恰把这条当成第一判据（`search.go:753-761`）。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 四值 `why` 分得开：不在 / 关了 / 不会搜 / 没有可搜的模型

**要什么**：tools/pool/searcher.py（本卡新建）提供 `chosen(picker: str, providers: Mapping[str, ProviderView]) -> Choice`，`Choice(picked: str | None, model: str, why: str)`，`why ∈ {"", "gone", "off", "cant", "nomodel"}`（四值常量逐字照 `search.go:381-385`）。`picker` 为空或 `"off"` ⇒ `(None, "", "")`；点名的模型已不在 provider 的模型表 ⇒ **退到它的小模型**（`search.go:387-392` 注释 `A model it no longer lists gives way to its small model, as when none is named.`），**不报 gone**。

**怎么证明**：本卡新建的测试文件 tests/test_pool_searcher.py，表驱动 8 行 —— `""` / `"off"` / `"ghost"`（gone）/ `"p1"` 且 `on=False`（off）/ `"p1"` 且 `rank=-1`（cant）/ `"p1"` 在·on·能搜但无模型（nomodel）/ `"p1/m1"` 但 m1 已下线（退小模型，`why=""`）/ `"p1/m1"` 全在。**反向断言**：前四类（gone / off / cant / nomodel）的 `why` 两两不等（防「四个值并成一个」）。

**钉子落点**：本卡新建的 tests/test_pool_searcher.py（本仓无同名文件；2026-11-20 实读 `ls tests/test_pool_*.py | wc -l` = 58 份里零冲突）。

### 判据 2 · 排名与「谁先被问」：静态表 + 一轮最多三个

**要什么**：`rank(view) -> int` 逐条照 `search.go:300-327`：claude `0`（`:303`）、codex `1`（`:305`）、copilot `-1`（`:307-310`，只为自己模型搜）、Anthropic 协议 `2`（`:311`）、Responses 协议 `3`（`:313`）、Chat 协议 `4`（`:315`）、`partSearcher && searchesAlone` `4`（`:317`）、google 账号 `5`（`:319`）、远端会搜 `5`（`:322`）、兜底 `-1`（`:326`）；`manualRelayRank = 6`（`search.go:329-331`，注释 `after every provider magpie picks or falls back to by itself: a relay said to search is offered only to be named`）**只在被点名时可问**，自动挑选时永不入选。`turn(choice, views) -> list[str]` 一轮最多 3 个（`searchersInTurn = 3`），同一个 provider 不重复问。

**怎么证明**：同上测试文件 —— (a) 10 行 `rank` 表逐行断言；(b) 造 5 个都会失败的 searcher，断言 `len(turn(...)) == 3` 且名字按 rank 升序；(c) relay（rank 6）在自动挑选里**不出现**、在被点名时**出现且排最后**；(d) 同一 provider 的两个模型只出现一次。

**钉子落点**：同上。

### 判据 3 · 三种失败分得开 —— 且 `not_searched` 与 `nothing_found` 的**包含关系**要对

**要什么**：`verdict(blocks: Sequence[Mapping]) -> Failure`，`Failure(kind, why, sources, nothing_found, not_searched)`，`kind ∈ {"ok", "found_nothing", "not_searched", "error"}`，逐条照 `search.go:950-1002`：`searched` 只在出现 `server_tool_use` 或 `web_search_tool_result` 块时置真（`:965-968`）；`sources` 只收 `URL` 与 `CitedText` **都非空**、且同一 URL 未被此前引用过的 citation（`:961`），且 `len(sources) > 0 && len(sources) <= 20` 才追加 `Sources:` 段（`:999-1000`）。

★ **最容易移植错的一处**（必须逐字钉）：Go 里 `errNotSearched` **包着** `errFoundNothing`（`errors.Is(errNotSearched, errFoundNothing)` 为真，注释原话 `It is found nothing too.`），但 `SearchFailure` 结构体里两个 bool 是**互斥**的 —— `search.go:830`（`namedFailed` 里）逐字 `f.NothingFound = !f.NotSearched && errors.Is(err, errFoundNothing)`，`search.go:890`（`searchingInstead` 里）逐字 `g.NothingFound = !g.NotSearched && errors.Is(err, errFoundNothing)`。⇒ 「是不是都没找到」（语义包含）与「这次算不算 nothing_found」（结构体字段）**是两个问题**，Python 移植必须两个都给。

**怎么证明**：同上测试文件 —— (a) 只有 `server_tool_use` + 一段带 `://` 的 text ⇒ `kind == "ok"`；(b) 有 `web_search_tool_result` 但 results 空、text 无 `://` ⇒ `found_nothing`；(c) 只有 text、两个搜索块都没有 ⇒ `not_searched`；(d) 对 (c) 断言 `f.not_searched is True and f.nothing_found is False and f.is_found_nothing() is True`（**三句一起断言**，少一句就抓不住那个歧义）；(e) 21 条 citation ⇒ 不追加 `Sources:` 段，20 条 ⇒ 追加。

**钉子落点**：同上。

### 判据 4 · 让位：最多三次、不重复问、**点名的那个一个都不让位**

**要什么**：`search(choice, views, ask) -> Result` 里 `ask` 是**注入的**（签名 `(provider, model) -> Failure`，照 `gateway.route_once` 的 `forward` 注入体例：`tools/pool/gateway.py:613-614` 的 docstring 逐字「forward 是**注入的**（签名 (model, account, url, payload) -> Reply）：干跑时给桩，整条链路照走不误、一个字节都不出网」；草稿写 501-503，那是草稿基准 `466a2578` 的坐标）。规则三条：(1) `len(tried) >= 3` 即停（`search.go:776` 逐字 `if err == nil || ctx.Err() != nil || len(tried) >= searchersInTurn { break }`）；(2) 同一个 provider 不重复（`:779`）；(3) `choice.why == "" and choice.picked == 当前 p` ⇒ **只问它一次**，失败原样回给调用方，错误串带逐字 `(the searcher picked in Settings › Web search: no other provider searches in its place)`（`search.go:759`）。

**怎么证明**：同上测试文件 —— (a) 5 个都失败 ⇒ `len(tried) == 3`；(b) 点名的 searcher 失败 ⇒ `len(tried) == 1` 且错误串 `endswith` 那句原文；(c) 非点名的第一个失败 ⇒ 第二个被问、且结果里带 `instead` 五字段；(d) 一个 provider 出现两次的候选表 ⇒ `tried` 里它只出现一次。

**钉子落点**：同上 + 一句话说明它**故意不碰** `tests/test_pool_gateway.py`（换号语义是另一维度）。

### 判据 5 · 「不静默」：五字段齐 + `off` 的真语义（关 provider 不关 Search API）

**要什么**：`instead(...)` 返回的记账对象五键齐（逐字照 `search.go:872-896`）：`instead`（先问的是谁，`provider` 或 `provider/model`，`:881-884`）、`picked`（它是不是人在 Settings 里点的，`:885-888`）、`nothing_found`、`not_searched`（`:889-890` 两句互斥赋值）、`why`（**只在既不是没找到也不是没搜时才填** —— `:891-894` 逐字 `g.Why = ""` + `if !g.NothingFound && !g.NotSearched { g.Why = strings.TrimPrefix(err.Error(), g.Instead+": ") }`；草稿写 :887-890）。`picker == "off"` 时 `chosen()` 回 `(None, "", "")`，`search()` 直接回 `off`，**但 Search API 那条路必须仍然跑**（`search.go:668-673` 逐字：`if settings.Load().Searcher == "off" { … return s.apiSearch(ctx, query) }`，没有 Search API 才回 `errNoSearcher`）。

**怎么证明**：同上测试文件 —— (a) 「找不到」的让位：`why == ""`、`nothing_found is True`；(b) 「报错」的让位：`why` 非空且等于 `"<provider>: <err>"` 去掉前缀的形状；(c) `picker="off"` + 有 Search API ⇒ `ask` 被调用 0 次、`search_api` 被调用 1 次；(d) `picker="off"` + 无 Search API ⇒ 错误的文案逐字等于 `no provider that can search the web, nor a search API, is set up in magpie`（`search.go:709`）。

**钉子落点**：同上。

### 判据 6 · 反向变异 ≥3 条（每条真改真跑真复原）+ 一条只改注释的安静对照

脚本落 gates/diag/_rev_F57.py（gitignored，`.gitignore:70` 已忽略 `gates/diag/`，`:75-77` 是只放行 `gate_lock.py` 的例外），末行打印「结论：N/N 条全部咬住，收尾绿。」。

| # | 改哪一行（锚点原文） | 哪条判据该红 |
|---|---|---|
| M1 | tools/pool/searcher.py 里把 `WHY_CANT = "cant"` 改成 `WHY_CANT = "gone"` | 判据 1 第 5 行（cant）与第 3 行（gone）撞值 ⇒ 红 |
| M2 | 判据 3 的实现里把 `f.nothing_found = False` 改成 `f.nothing_found = f.not_searched or found_nothing` | 判据 3(d) 的 `nothing_found is False` 断言 ⇒ 红 |
| M3 | `searchersInTurn = 3` 改成 `searchersInTurn = 99` | 判据 4(a) 的 `len(tried) == 3` ⇒ 红 |
| M4（安静对照） | 只改注释：把 `# searchersInTurn is how many searchers…` 这行注释换个说法，**不改数字** | 六条判据**全绿**（若有一条红，说明有判据在咬注释而不是咬行为 —— 那是坏钉子） |

**怎么证明**：脚本逐条 `shutil.copyfile` 备份 → `str.replace(锚点, 改写, 1)` → 断言替换**恰好发生一次**（`assert src.count(锚点) == 1`）→ 跑对应 pytest 选测 → `assert rc != 0` → 复原 → 最后跑一遍全绿 → 打印结论行。

## 交付

| 文件 | 性质 | 说明 |
|---|---|---|
| tools/pool/searcher.py | **新增** | 六个纯函数：`rank` / `chosen` / `turn` / `verdict` / `instead` / `search`。**不读盘、不读钟、不出网、不 print**（`search` 的外呼一律由 `ask` 注入）|
| tests/test_pool_searcher.py | **新增** | 判据 1-5 的钉子（表驱动 + 注入桩，零网络零落盘）|
| `docs/subsystems/pool/modules.toml` | 改 | 追加一条 `[[module]]`：`name = "searcher.py"` + `duty` + `cli`（三个键一个都不能少、多一个也不行；`cli` 没有命令壳就写 `"无"`，不许留空）|
| 复盘/卡/卡A385-F57-searcher选择与让位-三种失败要分开.md | 本件 | 本卡的规格文件（就是本文）|

★ **不碰**：`tools/pool/gateway.py`、`tools/pool/route.py`、`tools/pool/route_log.py`、`tools/pool_mcp.py`、A372 的 tools/pool/search.py。这条不是洁癖 —— `tools/pool/plan.py:170-180` 的 `files_intersect()` 是**精确字符串集合相交**，碰了 A372 / A374 / A375 / A380 的文件就会与它们串批（见抬头「域相交」段）。

## 验收（可直接跑）

```bash
cd .wt/A385

# 1. 新钉子全绿（单跑必须绕开 pyproject 的覆盖率门：pyproject.toml:51 的 addopts 带 --cov-fail-under=70）
python -X utf8 -m pytest tests/test_pool_searcher.py -o addopts= -q --no-cov

# 2. 老钉子一条没被放宽（这三个文件本卡一个字节都没改，条数不许动）
python -X utf8 -m pytest tests/test_pool_route_log.py tests/test_pool_gateway.py \
    tests/test_pool_rest.py -o addopts= -q --no-cov

# 3. 新模块进了清单（仓里有、modules.toml 没有 ⇒ 退 1 并点名）
python -X utf8 scripts/gen_pool_readme.py --check

# 4. 反向变异（3 条必须咬住 + 1 条安静对照必须全绿）
python -X utf8 gates/diag/_rev_F57.py

# 5. ruff（line-length 100、select E/W/F/I/N/UP/B/SIM/TCH —— pyproject.toml:78/:81）
python -X utf8 -m ruff check tools/pool/searcher.py tests/test_pool_searcher.py
```

五条都退 0 才算成。第 3 条退 1 时会逐行点名缺的是哪个文件 —— 那就是没进 `modules.toml`。

**已知噪音**：第 2 条里 `tests/test_pool_gateway.py` 会读 `tools/pool/platforms.toml` 与 `tools/pool/lanes.toml`（只读常量），在没配号池的机器上仍是绿的；若它红，先看是否本卡意外改了 `gateway.py`（本卡不该改）。

## 不许做

- **不许**改 `tools/pool/route_log.py` 的 `STATUSES` 四值闭集，也不许改 `_one_try` 的两键形状 —— A363 的判据 9 钉在 `tests/test_pool_route_log.py:252-271`（硬等四值）与 `tests/test_pool_route_log.py:97`（硬等 `tried` 只有 model/fail 两键）。让位链走**返回值**，不落盘。
- **不许**改 `tools/pool/gateway.py` 的换号循环（`:651-709`；草稿写 541-599，那是 `466a2578` 的坐标）。「换号 = 同模型多个号」与「让位 = 换 searcher」是两个维度，混在一处会让 429 沉底（`:691-696`）与 searcher 让位互相污染。
- **不许**往 `tools/pool_mcp.py` 的工具列表里加东西 —— 2026-11-20 实读是 13 个只读 / 18 个写面，硬等钉在 `tests/test_pool_mcp_task.py:819` 与 `:824`（`assert len(thirteen) == 13` / `assert len(eighteen) == 18`），`tests/test_pool_mcp.py:45-59` 与 `tests/test_pool_mcp_write.py:40-56` 各有一份 13 项硬列。
- **不许**在 tools/pool/searcher.py 里出现：rest 数字（600/3600/1800 之类）、key 明文、`hashlib`、`import urllib` / `socket` / `requests` / `httpx`、`time.time()` / `datetime.now()`。grep 断言照 `tests/test_pool_rest.py:304-313`（`FORBIDDEN_IN_STATUS` 元组）与 `:316-320`（`test_status_has_no_network_or_sleep`，`inspect.getsource(...)` + 命中列表必须为空）的体例，模块头那条在 `:323-328`。草稿写 304-333 —— 那个文件 2026-11-20 实读共 328 行，越界了。
- **不许**在 tools/pool/searcher.py 里复制第二份「失败分类」：七值分类只有 `tools/pool/gateway.py:181` 一份（`def classify(status: int, body: bytes | dict | None = None) -> Kind:`，草稿写 :180），本卡的三种结局是**另一层**（搜没搜），不许把状态码搬进来。
- **不许**改 A372 的 tools/pool/search-vendors.toml 格式；本卡只**读**它（读的是「有哪些 vendor、各自 key 够不够」）。
- **不许**改仓外文件：`D:/repo/infra/**`（`accounts.toml` / `limits.toml` / `callers.toml`）一个字都不许动。
- **不许**手改 `docs/subsystems/pool/README.md` 的生成区（`<!-- pool-margin:begin -->` 到 `<!-- pool-margin:end -->` 之间由 `scripts/gen_pool_readme.py` 重算）。

## 与已完成卡的关系

| 卡 | 状态 | 关系 |
|---|---|---|
| A372（F56） | **pending（未落地，`docs/workbacklog.toml:6624`）** | 本卡 depends 它。它落 tools/pool/search.py 与 vendor 表；本卡不碰那些文件，只从它读「哪些 vendor 可问」。**它不落，本卡不许开工。** |
| A363 | done（`docs/workbacklog.toml:4977`） | `route_log.py` 的四值闭集与两键 `tried` 是本卡**故意不改**的东西（见「不许做」第 1 条）。已 done ⇒ 只作读法参照，不留在 depends。 |
| A345 | done（`docs/workbacklog.toml:4743`） | `sticky.py` 的「两层选择 + Why」形状本卡只借读法；tools/pool/searcher.py 不复用它的字段（`STICK_KEEP_S` / `STICKS_KEPT` 都是粘性参数，与 searcher 无关）。已 done ⇒ 只作读法参照。 |
| E94 | done（`docs/workbacklog.toml:5564`） | 四条硬边界（不翻译协议 / 不做凭据发现 / 不做定时器 / 不复制判据）全部继承；`ask` 注入体例照它的 `forward`。已 done ⇒ 只作读法参照。 |
| A368（F24） | done（`docs/workbacklog.toml:6496`） | **草稿写它 pending，2026-11-20 实读是 done** —— 已落地。它管 `gateway.py` 的窗口维度过滤（`_order` 的 `model` 形参，`tools/pool/gateway.py:535`）；本卡不碰 `gateway.py`，与它无域相交。 |
| E143（F86③） | done（`docs/workbacklog.toml:6591`） | **草稿写它 pending，实读 done** —— 已落地（窗口读数发布成可核元数据）。同样不碰 `gateway.py`。 |
| A374 / A375 / A380 | pending | 只在本卡 files 含 `docs/subsystems/pool/modules.toml` 这一点上与本文相交；处理方式见抬头「域相交」段（**未拍板**）。 |

## 未坐实项（草稿如实标注，别当成结论）

1. **未取证**：`../_ext/magpie-main/internal/gateway/search_kimi.go`（169 行）与 `../_ext/magpie-main/internal/gateway/search_workbuddy.go`（133 行）只核了**文件存在与行数**（`wc -l`），没读 `canSearchFor` / `wbSearch` 的实现。本卡把「Kimi Code 的搜索服务 / WorkBuddy 的搜索服务」归到「provider 自带能力，不在本卡移植范围」—— 这条归类**没有证据**，落地前要补读。
2. **本卡不接线**（纯函数先落，照 `tools/pool/holds.py` 的先例）。理由：接进生产会碰 `gateway.py` / 搜索编排，那两处分别属于 A368（已 done）/ E143（已 done）/ A372（pending）。**若立卡人要求本卡就接线**，files 域必须加 `tools/pool/gateway.py`；届时 A368、E143 已是 done，**别把 done 卡写进 depends**，需要另开一张接线卡，且判据 4 要扩一条端到端。**未拍板。**
3. **`searcherSpent`（额度耗尽不试，#1801）没有移植**：它依赖 magpie 自己的额度读数（`search.go:769`、`:786`）；pool 侧对应物是 `pool_quota.status` 的四态（`tools/pool_quota.py`）与 `tools/pool/limits.py:109` 的 `assert_serving`。两者能不能一一对上**未坐实**。本卡只移植 `autoSearcher` 的「有额度的排在全耗尽的之前」（`search.go:364-374` 的 `bestReady` 规则），**不移植**那句额度文案。
4. **模型注册表要不要加「会不会搜网页」这一列**（`tools/pool/model_registry.py:136-149` 五字段、`:197` 只认三个必填键）：加了要动解析器与 `tests/test_model_registry.py`。草稿倾向**不加** —— searcher 能力由 provider 名 + 协议决定（`searchRank` 就是静态表，不看模型）。**未拍板。**
5. **四值 `why` 的取值文本**照 magpie 原样用英文（`gone` / `off` / `cant` / `nomodel`）。本仓既有闭集两种写法都有（`route_log` 的四个 status 是英文，`tools/pool/sink.py:47-48` 的 `KIND_RATE` / `KIND_BALANCE` 是中文 `限流` / `余额耗尽`）。草稿选英文（与上游逐字对得上，便于回查原件），**未拍板。**

## 物化说明（本件与草稿的差异，逐条）

草稿 `gates/diag/_draft_F57.md` 的判断一条没改，只把会过期的东西换成 `f7d4d305` 上的实读：

1. 本仓行号按 `f7d4d305` 重核：`gateway.py` 的 `classify` :180→**:181**、换号循环 :544→**:651**、`continue  # server / other` :602→**:709**、`forward` docstring :501-503→**:613-614**、`_order` :431-435→**:530**、429 沉底 :581-586→**:691-696**（草稿这些是 `466a2578` 的坐标）。
2. `tools/pool/model_registry.py` 的 `class ModelEntry` :135→**:136**；`tools/pool/outcomes.py` 的 `is_outcome` :124→**:123**。
3. `tests/test_pool_rest.py` 草稿写 `:304-333`，该文件实读共 **328** 行 ⇒ 拆成 `:304-313` / `:316-320` / `:323-328`。
4. 草稿缺口 1 说 `web_search|server_tool_use|web_search_tool_result` 命中 `tools/pool/jobs.py:248` 与 `tools/wb_dispatch.py`；实读该 pattern **零命中**，命中的是 `tool_use` 一词（工人日志解析）⇒ 正文按实读重写。
5. magpie 行号微调：`searchRank` 300-326→**300-327**；`searchWith` 的三种结局 991-998→**992-997**（该函数整体 950-1002）；`searchingInstead` 的 `Why` 两句 887-890→**891-894**。
6. 草稿「tools/pool/ 48 个条目」「55 份 `test_pool_*.py`」是会漂的常量 ⇒ 换成带日期的读数 54 / 58 并附命令。
7. 草稿关系表把 A368、E143 写成 pending ⇒ 2026-11-20 实读均 done（`docs/workbacklog.toml:6496` / `:6591`）。
8. 草稿 depends 列 A372、A363、A345、E94 ⇒ 只留 **A372**（`docs/workbacklog.toml:6624` 仍 pending），A363（`:4977`）/ A345（`:4743`）/ E94（`:5564`）降级成读法参照。
9. 指向本卡将新建文件的路径去掉了反引号（tools/pool/searcher.py、tests/test_pool_searcher.py、gates/diag/_rev_F57.py 等在正文里按普通文字写），免得 `scripts/check_docs.py` 把它们记成死指针。

