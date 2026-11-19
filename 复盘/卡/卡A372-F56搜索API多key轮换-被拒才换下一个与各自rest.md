# 卡 A372（已立卡）：F56 搜索 API 多 key 轮换 —— 「被拒才换下一个」+ 各自 rest

> 台账号 `T-AG658`（已立卡）｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A372`｜层 判据层｜基准 `4efaab8d`（起草时主树 HEAD；全文行号按此复核，之前一笔 `5b663886` 的取证已作废重读）｜depends E94、E103、E131、A332、A351、A368、A370、A371、E143

## 前情

- **magpie 原件**：`magpie search add <api> <key>`（key 逗号分隔多个）、`pick=order`、`magpie search off|on|move`；默认**轮流**（每个 vendor 一个计数器，每次搜索把首问 key 后移一位），`pick=order` 则总从第一个开始直到被拒。
- **「只有拒绝才换下一个」**：换号只对 401、402、403、429、432、433 生效，**任何其它错误就地结束**（`internal/gateway/search_api.go:159-160` `if !refused { break }`）。
- **rest 档位**（`internal/gateway/search_keys.go:50-56`、`searchRestFor:62-76`）：401/403 = `turnedAwayRest` **10 分钟**；402（以及 tavily 的 432/433）= `outOfCreditRest` **1 小时**；限流 = `rateLimitRest`，Retry-After 夹在 `rateLimitRestMin=30s` ~ `rateLimitRestMax=10min`，没有则 1 分钟。resting 的 key **不被丢弃**，排在不在 rest 的之后、最快恢复的在前（`searchKeyOrder:109-129`）。
- **rest 的键**（`search_keys.go:41-44`）`searchKeyID(vendor, key) = vendor + " " + hex(sha256(key)[:8])`；注释原文「so no map, log or dump holds the key itself」。
- **打码**（`internal/provider/search_api.go:100-106`）`MaskSearchKey`：`tvly-` 且长度 ≥ 16 ⇒ `"tvly-…" + 后 4 位`，否则退回 `Mask`。

**本仓现状（实测，基准 4efaab8d）**：`gates/diag/_magpie_scope.md:64` 把 F56 判为 `PORT | no | 无搜索 API 模块（grep search key 轮换零命中）`。勘察结论：**「零命中」只对「搜索 vendor 对象」成立，轮换 / 换号 / rest / 打码这四件底层件 pool 里全都有，但两处没接上、两处语义不同。本卡是「接上 + 补档」，不是「从零写一个搜索客户端」。**

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · `--routing rotate` 在真网关里等于 `order`（轮换恒等）

`tools/pool/gateway.py:431-436`：

```python
def _order(cands: Sequence[Mapping[str, Any]], routing: str, *, pool: str) -> list[int]:
    seats = [_seat(row) for row in cands]
    # apply_strategy 的末行就是 route.apply_order（route.py:580）—— 顺序护栏在那一份里，
    # 这里**不重写**：越界/重复/非整数一律退回原列顺序，永不抛（策略写坏也不许 500）。
    return pool_route.apply_strategy(routing, seats, pool=pool)
```

`tools/pool/route.py:669-670` `def apply_strategy(name, seats, *, pool, state: dict[str, Any] | None = None)`，`:694` `book: dict[str, Any] = {} if state is None else state`，`:703` `got = rotate(seats, pool=pool, turns=book.setdefault("turns", {}))`。

`_order` **不传 `state`** ⇒ 每次调用新建 `book` ⇒ `rotate()`（`route.py:455-471`）里 `so_far = book.get(pool, 0)` 恒为 0 ⇒ `start = 0` ⇒ **返回恒等排列**。上游 `route_once`（`gateway.py:491-497` 签名）没有 state 参数，`_Handler._post` 的调用点 `gateway.py:975-980` 也不传，`_Server.__init__`（`:1041-1058`）只存 `self.routing`（`:1051`）。

⇒ `--routing rotate` / `--routing in-turn` / `round-robin` 今天在真网关里**静默等于按列出顺序**，且没有任何测试咬住（`grep -n 'def test_.*rotate' tests/test_pool_route.py` 零命中；`tests/test_pool_gateway.py:962` 的 parity 用例只覆盖 `smart/usage/pace/fast` 四个名字）。

### 缺口 2 · `pool_quota.record` 的键是 card+model，没有 account / vendor 维度 ⇒「各自 rest」做不到

`tools/pool_quota.py:293-322`：

```python
def record(*, card: str, model: str, pool: str, kind: str,
           reset_raw: str, source_log: str | None = None, source_line: int | None = None,
           root: Path = ROOT) -> dict[str, Any]:
    ...
    cards.setdefault(card, {})[model] = rec
```

注释 :296 逐字「把一次 429 落成一条记录 —— 同卡同模型覆盖」。⇒ 同一个模型下**两个不同的 key/账号互相覆盖**，读的时候 `status()`（`:540-566`）也只按 `cards[card][model]` 取一条。`gates/diag/quota-state.json`（`STATE_REL` :62）里因此**没有「这个 key 在 rest 到几点」这一格**。

另：`tools/pool/route.py:181` `resting: bool = False` 这个字段今天**生产侧没有任何人置 True**（`grep -rn 'resting=' tools/ scripts/` 只命中 `tests/test_pool_route.py:151`）—— rest 与选号没接上。

### 缺口 3 · rest 档位与 F56 不同（三处数字差）

`tools/pool_quota.py:90-99` 现常量：`CREDIT_REST_S = 30 * 60`、`QUOTA_REST_S = 15 * 60`、`LONGEST_RETRY_S = 10 * 60`、`LONGEST_RATE_REST_S = 30 * 60`、`COOLDOWN_S = 60`、`REST_CAP_OFF = -1`。`rest_after`（`:399-486`）分支行为：

| 情形 | F56 要的 | pool 今天给的 |
|---|---|---|
| 401 / 403 | 固定 10 分钟 | `why="auth"` 落 else 分支（:472-478）⇒ 60s 起指数、上限 `LONGEST_RETRY_S` 10 分钟（首错恰好 600s；`failures` 再涨也被 10 分钟封顶）|
| 402 | 固定 1 小时 | `why="credit"` ⇒ `CREDIT_REST_S` = 30 分钟 |
| 限流无 Retry-After | 1 分钟 | `COOLDOWN_S` = 60s（一致）|
| 限流有 Retry-After | 夹在 [30s, 10min] | `w = min(Retry-After, LONGEST_WAIT_S=1h)`，且只有 `w >= 退避值` 才采信（:462-468）⇒ 退避起点 60s、上限 `LONGEST_RATE_REST_S` 30 分钟，**没有 30s 下界** |

⇒ 不是「没有 rest」，是「rest 的表里缺搜索 vendor 的那几档」。改法必须是**加一档参数**（`own_rest_s` / `rest_cap_s` 已经存在，`:405`），不是改现有数字 —— 现有数字有钉子（`tests/test_pool_rest.py` 21 条、`tests/test_pool_quota_history.py` 23 条）。

### 缺口 4 · 「被拒才换下一个」的档位与 F56 不同

`tools/pool/gateway.py:581-599`（`route_once` 主循环）：

```python
        if kind == KIND_RATE:            # :581 沉底 + parse_retry_after + continue
        if kind == KIND_QUOTA:           # :587 记一条 + continue
        if kind == KIND_AUTH:            # :594 换号，不写沉底 → :596 continue
        if kind in (KIND_OVERFLOW, KIND_BAD_REQUEST):   # :597
            break  # :598 不换号：换号也装不下 / 是请求本身不对
        continue  # :599 server / other ⇒ 换下一个号，不降权
```

⇒ pool 今天让 **500 / other 也换号**；F56 的搜索语义是**只有 401/402/403/429/432/433 换号，其它就地结束**。这是一处**必须显式选边**的语义差（见「未坐实项」第 1 条），不能默默沿用。

### 缺口 5 · 打码对 `tvly-…abcd` 这种搜索 key **实测无效**

`tools/pool_accounts.py:74` `SECRET_RE = re.compile(r"(?i)(bearer\s+)?(sk-|ak-|ghp_|xoxb-)[A-Za-z0-9_\-]{8,}")`，`:693` `def mask(value: str) -> str` = `SECRET_RE.sub("***", value)`；`:500` `def mask_token(token: str)` 只认三段式 JWT。

实测（`python -X utf8` 真跑）：`mask('tvly-abcdefghijklmnop')` **原样返回**（前缀白名单没有 `tvly-`）；`mask_token('tvly-abcdefghijklmnop')` 整串变 `'<token>'`（把尾巴也吃了）。⇒ **`tvly-…abcd` 这种「保留后 4 位」的打码今天两个函数都做不到**，搜索 key 一旦进日志就是明文。

### 缺口 6 · 搜索 vendor 对象本身不存在

`tools/pool/platforms.toml` 是 `[platform.<id>]` 段（`:29 codearts`、`:58 workbuddy`、`:86 qoder`、`:111 trae`、`:137 minimax`、`:164 lobsterai`、`:185 opencode`、`:205 meoo`、`:231 codebuddy`，共 9 段），`grep -rn 'tavily|brave|serper|searxng|firecrawl|search_key' tools/ scripts/ docs/subsystems/pool/` **零命中**。⇒ 没有「搜索 vendor + 它的一串 key」这个对象。

## 立卡人裁决（2026-11-19 立卡时定，实现者按此做；要推翻必须另开卡）

- **未坐实项 1（500 换不换号）= 只在搜索路径不换**：`tools/pool/gateway.py:599` 的聊天路径一个字节不动（`tests/test_pool_gateway.py` 既有换号用例全绿），搜索路径新增「非拒绝就地结束」这一档。
- **未坐实项 2（vendor 表落哪）= 单开 `tools/pool/search-vendors.toml`**，不改 `tools/pool/platforms.toml` 的 9 段既有内容。理由：platforms 的 schema 是 `base_urls` / `chat_urls` / `token_env`，搜索 vendor 要的是 `base` + key 是否必需 + 哪些状态码算「余额耗尽」；塞进去要扩 schema 又要动既有段（本卡「不许碰既有段」），而单开一份表可以直接照 `tools/pool/rpm.toml` / `tools/pool/model-registry.toml` 的体例。
- **未坐实项 3（每个 key 只占搜索时间的 1/4）= 本卡不做**：本仓没有任何「一次搜索耗时」的落点（`Attempt.started_at` 只记开始），要做得先加计时，另开卡。原文保留在「未坐实项」备查。
- **未坐实项 4（Tavily `/usage` 读取）= 另开卡**：它要一个带缓存的 HTTP 读取器，与判据 6「只编排」冲突。
- **未坐实项 5（判据 1 的端到端怎么做）= 不改 `route_once` 签名**：给 `_Server` 加一个 `turns` 属性、`_order` 加关键字参数 `turns: dict | None = None`，`route_once` 从 `self.turns` 取。这样 `tests/test_pool_gateway.py` 现有 67 条调用点一个都不动，(a)(b) 两条钉子都能落。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · `rotate` 在网关路径上真的轮转

**要什么**：同一个 pool、同一列座位，连续两次 `gateway._order(rows, "rotate", pool="p")` 返回的排列**首项不同**；`"order"` 则两次相同。计数由调用方持有（一个显式的 `turns` dict 或 `_Server` 上的一个属性），`rotate()` 本身仍是纯函数（`route.py:461` docstring「`turns` 由调用方持有，本函数不落盘」）。

**怎么证明**：`tests/test_pool_gateway.py` 新增两条 —— (a) 纯函数级：连调三次 `_order` 得 `[0,1,2] / [1,2,0] / [2,0,1]`；(b) 端到端：`build_server(routing="rotate")` 起服务、用 `_Forward` 假上游跑两轮 `route_once`，两轮的 `Outcome.attempts[0].seat.key` 不同。反向：把 `state` 去掉（等价改回今天）⇒ (a) 立刻红。

**钉子落点**：`tests/test_pool_gateway.py`（现 67 条，一条都不许放宽）。

### 判据 2 · 每个 key 一条 rest，互不覆盖

**要什么**：同一个 `model` 下两个不同的 key 各自被拒后，**两条 rest 同时存在**、各自带自己的 `until`，且「现在哪些 key 在 rest」这个读数能一次取全。键必须是 `vendor + sha256(key)[:8]` 这种**不含明文**的形状（照 `search_keys.go:41-44`）。

**怎么证明**：`tests/test_pool_search_keys.py`（新建）—— (a) 两条记录写同一 model、不同 key，`read` 回两条，`len(records) == 2`；(b) 落盘文件里 `grep` 不到明文 key（把 key 设成 `tvly-` + 20 位可识别串，断言该串**不出现在任何落盘字节里**）；(c) 旧签名 `pool_quota.record(card, model, pool, kind, reset_raw)` 仍可用且行为不变（向后兼容钉子，`tests/test_pool_rest.py:264` 那批调用点一条都不改）。

**钉子落点**：新建 `tests/test_pool_search_keys.py` + 既有 `tests/test_pool_rest.py` 21 条不许改。

### 判据 3 · 搜索档 rest 数字逐条对上 F56

**要什么**：新增一个「搜索档」的取值路径 —— 401/403 ⇒ 600s（`by="turned-away"`）、402 与 tavily 的 432/433 ⇒ 3600s（`by="out-of-credit"`）、限流有 Retry-After ⇒ `min(max(w,30),600)`、无 Retry-After ⇒ 60s。**既有四真值一个数都不改。**

**怎么证明**：`tests/test_pool_search_keys.py` 表驱动 8 行（401/403/402/429+RA=10s/429+RA=90s/429+RA=3600s/429 无 RA/tavily-433），逐行断言 `seconds` 与 `by`；再加一条「旧路径不变」：`rest_after(why="credit", ...)` 仍是 1800、`why="auth"` 仍是 60 起指数。反向：把 `rateLimitRestMin` 的 30s 下界删掉 ⇒ 表里的 `429+RA=10s` 那一行红。

**钉子落点**：`tests/test_pool_search_keys.py` 新建；`tests/test_pool_rest.py` 只许**增**不许改。

### 判据 4 · 「只有被拒才换下一个」是显式的一档，不是沉默的副作用

**要什么**：搜索路径上，非拒绝类错误（500 / 超时 / other）⇒ **就地结束**，且这一点可读地记下来（例如 `Outcome` 上带 `stop_reason`，或 rest 记录里带 `by="not-refused"`）。**聊天路径的现有语义不许被这一条改掉**（500 今天换号，钉子在 `tests/test_pool_gateway.py`）。

**怎么证明**：`tests/test_pool_search_keys.py` 两条对照 —— (a) 搜索路径：第一个 key 回 500 ⇒ `attempts` 长度 1、`forward` 只被调用一次；(b) 聊天路径：同一个 500 ⇒ `attempts` 长度 2（今天的语义原样）。反向：把搜索路径的 break 改成 continue ⇒ (a) 红。

**钉子落点**：`tests/test_pool_search_keys.py` 新建 + `tests/test_pool_gateway.py` 既有换号用例全部保持绿。

### 判据 5 · key 在日志/错误里打码成 `tvly-…abcd`

**要什么**：新增一个打码入口（例如 `pool_accounts.mask_search_key`），行为照 `search_api.go:100-106`：`tvly-` 且 len ≥ 16 ⇒ `"tvly-…" + 后 4 位`；其余退回既有 `mask()`。**既有 `mask()` / `mask_token()` 的行为不许改**（`tests/test_renew_lock.py:203-231` 钉着）。

**怎么证明**：单测 4 行 —— `tvly-abcdefghijklmnop` ⇒ `tvly-…mnop`；`tvly-short` ⇒ 走 `mask()`；`sk-abcdefgh12345678` ⇒ `***`；错误串里 `keyLabel` 风格 `"key 2 (tvly-…mnop)"` 断言原文里**不含**完整 key。反向：把长度阈值从 16 改成 4 ⇒ 第 2 行红。

**钉子落点**：新建 `tests/test_pool_search_keys.py`（或并入 `tests/test_pool_accounts.py`，现 67 条，只许增）。

### 判据 6 · 搜索 vendor 对象复用既有四件套，不复制第二份判据

**要什么**：`tools/pool/search.py` 只做「vendor 表 + key 串解析 + 把拒绝翻译成 pool 的七值」三件事；轮换调 `route.rotate`、rest 调 `pool_quota.rest_after` 的搜索档、沉底调 `pool_sink`、打码调 `pool_accounts`。**不许**在 `search.py` 里出现第二份 rest 数字表、第二份分类正则。

**怎么证明**：(a) `python -X utf8 scripts/gen_pool_readme.py --check` 退 0（新模块已进 `docs/subsystems/pool/modules.toml`，现 50 条 `[[module]]`，生成器 :27-28 明写「仓里有、清单里没有 ⇒ 退 1 并点名」）；(b) `grep -n 'sha256\|hexdigest' tools/pool/search.py` 零命中（哈希只许在判据 2 那个落点里出现一次）；(c) `grep -n '600\|3600\|1800' tools/pool/search.py` 不许出现字面量 —— 数字只能来自 `pool_quota`。反向：把 `search.py` 里手抄一份 `600` ⇒ (c) 红。

**钉子落点**：`docs/subsystems/pool/modules.toml` 新增一条 + `tests/test_pool_readme_counts.py:105` 的正向钉子自然覆盖。

## 交付

| 文件 | 性质 | 说明 |
|---|---|---|
| `tools/pool/search.py` | 新增 | 搜索 vendor 表 + key 串解析 + 拒绝→七值；只编排、不复制判据 |
| `tools/pool/route.py` | 改 | `rotate` 的计数由调用方显式传入（今天已有 `turns` 参数，只是没人传；本卡只补「谁会传」与一处 `resting` 的标注位）|
| `tools/pool/gateway.py` | 改 | `_order` / `route_once` / `_Server` 透传 `turns`；搜索路径的「非拒绝就停」那一档 |
| `tools/pool_quota.py` | 改 | `record` 增 account/vendor 维度的可选键（旧签名不变）；`rest_after` 增搜索档（既有数字不动）|
| `tools/pool_accounts.py` | 改 | 新增 `mask_search_key`（既有 `mask` / `mask_token` 不动）|
| `tests/test_pool_search_keys.py` | 新增 | 判据 2/3/4/5 的钉子 |
| `tests/test_pool_gateway.py` | 改（只增）| 判据 1 的钉子 |
| `docs/subsystems/pool/modules.toml` | 改 | 新增 `search.py` 一条 `[[module]]` |
| `tools/pool/search-vendors.toml` | 新增 | 搜索 vendor 表（裁决 2：单开一份，不塞 `tools/pool/platforms.toml`）|
| `复盘/卡/卡A372-F56搜索API多key轮换-被拒才换下一个与各自rest.md` | 新增 | 本卡规格落地后的正式件 |

**不许碰**：`docs/subsystems/pool/README.md` 的生成区（`<!-- pool-margin:begin -->` 第 11 行 ~ `<!-- pool-margin:end -->` 第 92 行由 `scripts/gen_pool_readme.py` 生成）、`tools/pool/platforms.toml` 的 9 段既有内容（只许**追加**搜索 vendor 段，不许改既有段）、仓外 `accounts.toml`。

## 验收（三条，逐条真跑）

```bash
# 1. 新增的钉子全绿（单跑，绕开 pyproject 的覆盖率门）
python -X utf8 -m pytest tests/test_pool_search_keys.py -o addopts= -q --no-cov

# 2. 老钉子一条没放宽（这五个文件是本卡的域，条数只许增）
python -X utf8 -m pytest tests/test_pool_gateway.py tests/test_pool_route.py \
    tests/test_pool_rest.py tests/test_pool_accounts.py tests/test_pool_sink.py \
    -o addopts= -q --no-cov

# 3. 模块清单与 README 生成区一致（新模块必须被点名进去）
python -X utf8 scripts/gen_pool_readme.py --check
```

三条都退 0 才算成。第 3 条退 1 时会逐行点名缺的是哪个文件 —— 那就是没进 `modules.toml`。

## 不许做

- **不许**改 `pool_quota.py:90-99` 那十一个常量里的任何一个数（`CREDIT_REST_S` / `QUOTA_REST_S` / `LONGEST_RETRY_S` / `LONGEST_RATE_REST_S` / `COOLDOWN_S` …）—— 它们是 F20 的判据，有 `tests/test_pool_rest.py` 21 条钉着。搜索档只能是**新参数**。
- **不许**改 `pool_quota.record` 的**既有签名**（`card/model/pool/kind/reset_raw`）的语义；`tools/wb_dispatch.py:4110`、`tools/pool/gateway.py:590` 两个生产调用点必须原样能跑。
- **不许**改 `pool_accounts.mask()` / `mask_token()` 的既有行为（`tests/test_renew_lock.py:203-231`）。新打码是**另一个函数**。
- **不许**在 `tools/pool/search.py` 里复制第二份 rest 数字表或第二份失败分类正则 —— 判据只许一份真源（`gateway.classify` :177 七值、`pool_quota.rest_after` :399）。
- **不许**把搜索 key 的明文写进任何落盘文件、日志、错误体；键一律 `vendor + sha256[:8]`。
- **不许**手改 `docs/subsystems/pool/README.md` 的生成区，也不许手改 `docs/INDEX.md` / `复盘/INDEX.md`。
- **不许**动 `tools/pool/outcomes.py` 的七值台账口径（它**不是**失败分类器，`OUTCOME_TRIES` :59 / `OUTCOME_HANDED_ON` :61 / `OUTCOME_STOP` :63 是台账读数桶）。

## 与已完成卡的关系

| 卡 | 状态 | 关系 |
|---|---|---|
| E94 | done | 本卡改 `gateway.py` 的换号主循环与 `platforms.toml`；E94 立的「四条硬边界」（不翻译协议 / 不做凭据发现 / 不做定时器 / 不复制判据）本卡全部继承 |
| E103 | done | `apply_strategy` 的 `state` 参数、`parse_routing` 归一都是 E103 立的；本卡只是**第一次真传 state**，不重写策略 |
| E131 | done | `rest_until` / `rest_by` 两个键与四态口径是 E131 立的；本卡加搜索档时**不许**动四态名字与 `why` 文案 |
| A332 | done | `rest_after` 四真值；本卡只加参数路径，不改数字 |
| A351 | done | `sink.key_of` / `sink_order` 两段式键；本卡的 resting 排序复用 `sink_order`，不新写排序 |
| E95 / A329 / E105 / E107 / E110 / A328 / A331 / A349 / E112 | done | 同碰 `route.py` / `gateway.py` / `pool_quota.py` / `sink.py`，本卡 files 域与它们相交 ⇒ 必须写进 depends（`tools/wb_plan.py:764-768`：depends 不拦派活，同文件靠 files 相交串批）|

## 未坐实项（草稿如实标注，别当成结论）

1. **「500 就不换号」要不要同时改聊天路径** —— F56 只描述搜索。本卡默认**只在搜索路径**加这一档，聊天路径保持今天语义（`gateway.py:599` 不动）。这条需要立卡人拍板；若拍「两条都要」，判据 4 的反向钉子要拆成两条。
2. **搜索 vendor 表要不要落到 `platforms.toml`** 还是单开 `tools/pool/search_vendors.toml` —— 前者复用 `load_platforms()`（`pool_accounts.py:167`）但要扩 schema，后者干净但多一份表。草稿倾向后者（`platforms.toml` 的字段是 `base_urls` / `chat_urls` / `token_env`，搜索 vendor 只需要 `base` + 是否 `KeyOptional`）。**未拍板。**
3. **「每个 key 用搜索时间的 1/4」这条判据没写进本卡** —— 它需要「一次搜索耗时」的读数，pool 今天没有任何计时落点（`Attempt.started_at` 只记开始）。要不要为它单开一张卡，未定。
4. **Tavily `/usage` 读取（2 分钟缓存、10 次/10 分钟限速）没写进本卡** —— 它需要一个带缓存的 HTTP 读取器，本仓没有现成件；属 F56 的 `search_quota.go` 那一半，判据 6 的「只编排」原则下应另开一张卡。
5. **判据 1 的 (b) 端到端那条**依赖 `_Forward` 假上游与 `build_server` 现成（`tests/test_pool_gateway.py` 里已有 `start_server` fixture），但 `route_once` 目前拿不到 `turns`，改签名会碰 `tests/test_pool_gateway.py` 里 67 条的所有调用点 —— 若 pytest 改造成本过高，退一步只做 (a) 纯函数级钉子 + 一条 `_Server` 属性断言。**未定。**
