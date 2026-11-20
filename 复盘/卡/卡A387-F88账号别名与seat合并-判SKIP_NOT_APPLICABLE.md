# 卡 A387：F88 账号别名与 seat 合并 —— 判 SKIP_NOT_APPLICABLE

> 台账号 `T-AG675`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A387｜层 判据层（「不移植」的可复核钉子）｜基准 `78d4c16a`（立卡时主树 HEAD，2026-11-20 实读）｜depends 无

> depends 说明：**无**（实算 0 命中，与立卡指令一致）。本卡域只含「新建的一份测试 + 本卡规格 + 一份 changelog」，三份今天都不存在，与 412 张台账卡（活跃 20 张，`plan.ACTIVE_STATUS` = pending / running）的 `files` 求交 ⇒ 零命中，`tools/pool/plan.py:321-327` 不会拒单。★ 卡域里**不列**判据要读的三份产品码（gateway.py / cleared.py / pool_accounts.py）—— 本卡只读不改，列进域会被 `files_intersect()` 算成本卡可写，而本卡的整个论点是「这些东西不该动」。
> 判据引用归属（草稿原 depends，两张全 `done`）：E143（已把 F86③「按窗口换号」判成不移植 —— F88 的 seatMatch 整条判据都建在窗口上）、E94（`tools/pool/gateway.py` 里 `seat` 一词的出处，它的意思是「账本稳定 id」，不是 magpie 的「座位」）。

> 基准说明：草稿跨了五个主树 HEAD（`964c43a3` → `845e9182` → `0046f64a` → `c8c8f211` → `95dbe680`，之后到 `78d4c16a`），五次都是 docs / 台账 / 测试类改动。物化这一刻主树 HEAD 已到 `bc41ba76`（`78d4c16a` 之后只有一笔 docs-only：修 A385 规格里 8 处仓外 `_ext` 反引号）。所引本仓源码行号在 `bc41ba76` 上逐条复读未变 —— `git diff --stat 78d4c16a..HEAD -- tools/pool/gateway.py tools/pool/cleared.py tools/pool_accounts.py tests/test_pool_gateway.py` **为空**。

> 依据：既有判定表 `gates/diag/_magpie_scope.md:96` 今天把 F88 判成 PORT / partial，证据写「gateway.py:269/:279/:384-410 seat 概念在；cleared.py:184 明写「别名归并 … 不移植」」；该表 `:3` 的三值口径是 PORT / SKIP_BY_REDLINE（永不做协议翻译层）/ SKIP_NOT_APPLICABLE（不可移植资产）。功能原文见 `D:/repo/program/_ext/_magpie_features.md:736-742`。★ 本卡把判定从 PORT / partial **改判 SKIP_NOT_APPLICABLE** —— 旧证据里那句「seat 概念在」是**同形不同义**：本仓的 seat 是号 id，见下「缺口」第二节。

## 前情：magpie 的 F88 是三层，缺一层都不成立

### （1）用户给账号取名 —— `internal/provider/account_names.go`

`account_names.go:3-12` 包注释逐字（这一段同时说明了「为什么需要人取名」和「名字出现在哪」）：

```text
// An account's name of the user's own (#1515, aindijrncom): a team's GLM
// seats are told apart by who holds each, while the vendor names a seat
// by a masked email (31****36@qq.com) or not at all. The name is kept in
// providers.json beside the account's other settings (AccountNames), by
// the account's name in lower case; the vendor's or plugin's sign-in is
// never written to. It is shown wherever the account is: the Usage page,
// the menu bar, magpie accounts, magpie quota and /v1/magpie/quotas
// (SubscriptionQuota.Alias, Quota.Alias), the Usage page's Accounts and
// the request log's Account filter, a gateway key's accounts, and the
// Routing page (which reads accountNames from /api/providers).
```

清洗与上限（`account_names.go:23` `const MaxAccountName = 64`；`:27-35`）：

```go
func cleanAccountName(s string) string {
	s = strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return ' '
		}
		return r
	}, s)
	return strings.Join(strings.Fields(s), " ")
}
```

`:39-45` `normalAccountNames` 按 `accountKey(u)` 小写归一，`:43` 逐字 `if u == "" || v == "" || utf8.RuneCountInString(v) > MaxAccountName {`。`:88` `func AccountShownOf(id, user string) string { return cmp.Or(AccountNameOf(id, user), user) }` —— 「有名字用名字，没名字用掩码邮箱」。

### （2）座位合并 —— `internal/provider/account_seats.go`

`account_seats.go:3-13` 包注释逐字：

```text
// One GLM Coding Plan seat added twice, as a key provider and as a
// signed-in ZCode account, is shown once, on the account's card (#90,
// f02d37bb; scoped to GLM by #953): two cards would count its allowance
// twice, and routing goes by what a card has left. The two are told to
// be one seat by their windows' resets (seatMatch), which a failed read
// or a window not used yet doesn't have. So once they matched, that is
// remembered (seats.json, beside quotas.json): a read that fails is
// unknown, not "another seat", and doesn't bring the key's card back
// for a minute (#1515, aindijrncom). Only windows that disagree, or the
// account signed out, do. The account's card is then named for the key
// plan it stands in for (Seat), unless the user named it themselves.
```

判据本体 `account_seats.go:62-90` 逐字：

```go
// seatMatch says whether a key's plan a and the account's card b are one
// seat: 1 when their windows' resets agree (at least one, as sameAccount
// asks), -1 when they don't or b can't be a GLM seat, 0 when it can't be
// told: either failed to read, a is not known to be GLM's (a card kept
// from disk), or no window of both has a reset yet.
func seatMatch(a, b SubscriptionQuota) int {
	if b.Provider != "zcode" && b.Provider != "zcode-plugin" {
		return -1
	}
	if !a.glmPlan || a.Error != "" || b.Error != "" {
		return 0
	}
	matched := false
	for _, x := range a.Windows {
		for _, y := range b.Windows {
			if x.Aside || y.Aside || x.Span == 0 || x.Span != y.Span || x.ResetsAt == nil || y.ResetsAt == nil {
				continue
			}
			if !x.ResetsAt.Equal(*y.ResetsAt) {
				return -1
			}
			matched = true
		}
	}
	if matched {
		return 1
	}
	return 0
}
```

记忆体：`:36` `func seatsPath() string { return filepath.Join(filepath.Dir(Path()), "seats.json") }`；`:39` `func planSeatKey(p SubscriptionQuota) string { return p.Provider + "/" + accountKey(p.User) }`；`:109-151` `seatCards`（`:122` `if s.From == "" && seatMatch(p, s) == 1 {` 命中就 `shown` 里不放这张 key 卡；`:145-147` `if named[at].Seat == "" { named[at].Seat = seatName(p) }`）。

命名：`:97-101` `func seatName(p SubscriptionQuota) string` → `if p.User != "" && p.User != p.Name { return p.Name + " · " + p.User }`。

### （3）出口 —— `internal/provider/quotas.go` 的两个字段 + 管理面

`quotas.go:114-120` 逐字：

```go
	// From is the remote magpie whose account this is, by its name here
	// (remote_quotas.go); "" for this computer's own.
	From string `json:"from,omitempty"`
	// Alias is the account's name of the user's own, else Seat: the name
	// of the key plan whose card this account's stands in for (#1515).
	Alias string `json:"alias,omitempty"`
	Seat  string `json:"seat,omitempty"`
```

`account_names.go:128-136` 把它们算出来：`if q.From == "" { q.Alias = cmp.Or(AccountNameOf(q.Provider, q.User), q.Seat) }`。

命令行入口：`internal/cli/accounts_cli.go:25` 注释逐字 `magpie accounts alias <agent> <email> [<name>|--clear]`，`:33` 的 usage 长串里同一条。

**这三层是一条链**：seatMatch 决定「两张卡是不是一个座位」→ seatCards 把 key 卡藏掉、把账号卡标上 `Seat` → withAccountNames 算出 `Alias` → 管理面 `GET /v1/magpie/quotas` 交出去。**任何一层不成立，这个功能就没有可观察的效果**。

## 缺口：本仓今天有没有这个东西 —— **没有，而且连「对象」都不存在**

### ① 名字这一维：本仓**已有替代**，所以不是缺口

真实账本（仓外 `D:/repo/infra/pool/accounts.toml`，只读）每行自带 `label`，逐字五行：

```text
:2  id = "codearts-1"          :3  label = "备用号 codearts（华为云码道）"
:27 id = "codebuddy-tongxue3"  :28 label = "CodeBuddy 同学3（DSH 号池主力）"
:53 id = "workbuddy-1"         :54 label = "WorkBuddy 主号"
:78 id = "trae-1"              :79 label = "Trae 本机客户端"
:103 id = "meoo-1"             :104 label = "秒悟 Meoo（OAuth 登录，额度读 availableBalance）"
```

「人给的名字 ↔ 账本稳定 id」的唯一映射也已经有了 —— `tools/pool/account_id.py`（卡 A344），头注释 `:1` 逐字 `r"""人给的名字 ↔ 账本里的那个号：唯一映射（卡 A344 · T-AG546）。`，三步顺序钉在 `:16` `**三步顺序固定**（顺序本身是判据的一部分，别调换）：`，歧义 `:29-30` `**歧义必须响亮**…**不许取第一条** —— 取第一条 = 悄悄替人挑一个号。`

⇒ magpie 的 `AccountNames` / `cleanAccountName` / `MaxAccountName = 64` 这一层，本仓用「账本 `label` + `tools/pool/account_id.py` 的映射」回答了同一个问题，**但代价更低**：不引入第二份名字表，也不往 `providers.json` 里写。

### ② 座位这一维：**词同、义不同**

`tools/pool/gateway.py` 里 `seat` 出现 31 次、`tools/pool/route.py` 里 96 次，但它的意思是**号**：

```text
:271     """一次真实的尝试。**粒度 = (号, 模型)** —— 换号不动模型（照 magpie gateway.go:2659）。"""
:273     seat: str
:283         base = f"{self.seat}/{self.model}"
:388         seat = str(row.get("id") or "").strip()
```

`:388` 那行就是定义：`seat` 直接取自账本行的 `id`。**本仓一个号就只有一张卡**（账本一行 = 一张卡，见 `tools/pool_accounts.py:360-387` `load_ledger`），所以「同一个座位出现两张卡」这个**对象本身不存在** —— 没有东西可合并。

### ③ 机制这一维：seatMatch 的两个前提本仓都没有

- **前提 A：对端平台必须是 ZCode。** `account_seats.go:68` 逐字 `if b.Provider != "zcode" && b.Provider != "zcode-plugin" {` —— 不是就 `return -1`（直接判「不是同一座位」）。本仓 `tools/pool/platforms.toml` 有 9 个平台（`[platform.codearts]` / `workbuddy` / `qoder` / `trae` / `minimax` / `lobsterai` / `opencode` / `meoo` / `codebuddy`），`grep -nEi "zcode|glm|z\.ai|智谱" tools/pool/platforms.toml` ⇒ **RC=1 零命中**。
- **前提 B：两边都要有可比的 per-window `ResetsAt`。** `account_seats.go:77` 逐字 `if x.Aside || y.Aside || x.Span == 0 || x.Span != y.Span || x.ResetsAt == nil || y.ResetsAt == nil { continue }`。本仓真账本每行 `[account.quota]` 只有四个键（`observed_at` / `samples` / `source` / `unit`，**没有 per-window 段**），所以 `gateway._windows(row)` 对五行**全回 `[]`**；`tools/pool/gateway.py:461-465` 自己就写着这件事：

```text
    ★ **数据从哪来（判据 2 要求的事实说明）**：今天的仓外账本
    `infra/pool/accounts.toml` 的 `[account.quota]` 只有 unit / source / observed_at /
    samples，**没有 per-window 段**，所以真数据上这里永远回空表 ⇒ `_seat()` 走老路、
    窗口过滤在全放行状态下什么都不改。
```

⇒ seatMatch 的输入恒为空：`matched` 永远是 `false`，`return 0`（「判不出」），永远等不到 `1`。

### ④ 出口这一维：消费面是管理面，本仓明文不开

`tools/pool/gateway.py:98` 逐字 `#: 四条路径，一个都不多（不开 /v1/responses、Gemini、Ollama 兼容、管理面）。`；`:99-104` 的 `PATHS` 恰好四键（`/v1/chat/completions` / `/v1/messages` / `/v1/models` / `/v1/pool/routes`）；`:1079-1082` 的 405 与 `:1087-1090` 的 404 都把这句话写进了回话。勘察件 `gates/diag/magpie-gateway-recon.md` 的管理面行逐字：`| /v1/magpie/{quotas,usage,usage/requests,quotas/history,route,trace,concurrency,limit,omarchy} | 管理面 |`。

⇒ 就算前面三维都存在，本仓也**没有一条路径**能把「合并后少一张卡」这个读数交出去。

### ⑤ 扫描：一次说清「一个都没搬」

```text
$ grep -rnE "seatMatch|seats\.json|seatsPath|planSeatKey|AccountNames|AccountShown|SeatNameOf|withAccountNames|setAccountName|magpie/quotas" tools/ src/ scripts/ tests/ --include=*.py --include=*.toml
-> RC=1（零命中）

$ grep -rn "alias" tools/ src/ scripts/ --include=*.py     # 77 条，只有四类，没有一类是账号别名
-> ① tools/dsh_panel.py 的 CSS 令牌 var(--dsw-alias-…)（:418 :1981 :1988-2000 :3052 :3055 :3848 :3850 :3852）
   ② tools/pool/model_registry.py 的**模型**别名（:23-30 :105-107 :137 :143 :197-214 :229 :269 :311 :328-332）
   ③ tools/pool/gateway.py:811/:813  `if entry.alias == name or entry.id == name:`（码道条目 alias == id）
   ④ tools/pool/cleared.py:184  「别名归并（:91-98 的 c.alias）**不移植**」

$ grep -nEi "zcode|glm|z\.ai|智谱" tools/pool/platforms.toml
-> RC=1（零命中）

$ ls D:/repo/infra/pool/ | grep -i "seat\|alias"
-> RC=1（零命中：目录里没有 seats.json，也没有任何别名文件）
```

## 结论：判 SKIP_NOT_APPLICABLE（不是 SKIP_BY_REDLINE，也不是 PORT）

1. **对象不存在。** 本仓的「一个号」就是「一张卡」（账本一行 = 一张卡；`tools/pool/gateway.py:388` 的 `seat` 就是账本 `id`）。magpie 要合并的是「同一个 GLM 座位既是 key 又是登录账号」这一情形，本仓没有这种一对二的行，也没有一个字段能表达它。
2. **机制无落脚点。** `seatMatch` 要求对端是 `zcode` / `zcode-plugin`（`account_seats.go:68`）且两边有可比的 per-window `ResetsAt`（`:77` / `:80`）。本仓 `tools/pool/platforms.toml` 九平台零 zcode / glm 命中；真账本 `[account.quota]` 只有四个键，`_windows()` 五行全 `[]`。输入恒空 ⇒ 判据恒回「判不出」。
3. **出口不存在。** 唯一消费面是管理面 `GET /v1/magpie/quotas` 的 `alias` / `seat` 字段；本仓 `PATHS` 恰四条且 `tools/pool/gateway.py:98` 明写「不开管理面」，`gates/diag/_magpie_scope.md` 判 F36 时也用「路径恰四键 + /v1/magpie/* 常量零命中」钉过一次（`tests/test_pool_gateway.py:1252-1261`）。

> **为什么不是 SKIP_BY_REDLINE。** 七条红线里 F88 只**间接**碰到第六条（它唯一的出口是管理面路径），而它的「用户给账号取名」那一维与任何红线都不冲突 —— magpie 的 `account_names.go` 是干净的本地功能。判 SKIP_BY_REDLINE 会传递一个错误信号：「等哪天解禁红线，这件事还要做」。不对：**挡它的是数据形状（per-window resets + zcode 平台），不是红线**。所以判 SKIP_NOT_APPLICABLE，并用下面五条判据把「不做」钉成可复核的事实，而不是留成「还没做」。

> **所以本卡的产物不是代码，是三样**：①一份可复核的「结构性不存在」判据（新建一个测试文件，五条断言）；②卡规格（记录改判理由与三条论证）；③一条**不许被删**的锚 —— `tools/pool/cleared.py:184-185` 的「别名归并 … 不移植」句（它是今天仓里唯一写着这件事的地方）。

## 判据（五条，逐条给「怎么证明」）

### 判据 1 · 词表零命中：seatMatch / seats.json / AccountNames 这一族一个都没被搬进来

- **怎么证明**：一条 grep —— `grep -rnE "seatMatch|seats\.json|seatsPath|planSeatKey|AccountNames|AccountShown|SeatNameOf|withAccountNames|setAccountName|magpie/quotas" tools/ src/ scripts/ tests/ --include=*.py --include=*.toml; echo RC=$?` 必须回 `RC=1`；同一条在新建测试文件里以 pytest 形式再跑一次（逐文件扫 `tools/` `src/` `scripts/`，**不扫 `tests/`** —— 测试文件自己就含这些词）。
- **今天的读数**：`RC=1`，零命中（见「缺口 ⑤」）。
- 这条咬的是：有人把 magpie 那一族名字搬进任何模块 —— 不管搬进哪，词表先红。

### 判据 2 · 路径表恰好四键，且没有任何 `/v1/magpie/*` 常量

- **怎么证明**：pytest 断言 `sorted(gateway.PATHS) == ["/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes"]`；再断言 `tools/pool/gateway.py` 的字符串常量里没有 `/v1/magpie/` 前缀；再起桩服务 `GET /v1/magpie/quotas` 必须回 404。
- **今天的读数**：`tests/test_pool_gateway.py:1252-1261` 已在钉同样三件（`:1253` 注释逐字「★ 判据 4：路径表恰好四键，且没有任何 /v1/magpie/ 前缀的常量。」、`:1257-1258` 的集合断言、`:1260-1261` 的常量断言），新文件里**独立再钉一次** —— F88 的钉子不能依赖 F36 那个测试文件将来不被改。
- 这条咬的是：把 F88 的读数出口（管理面 `quotas` 的 `alias` / `seat`）开出来。

### 判据 3 · 账本里没有窗口段：窗口维恒为空

- **怎么证明**：pytest 断言 `gateway._windows({}) == []`、`gateway._windows({"quota": {"unit": "percent", "samples": []}}) == []`；并对真账本（仓外 `D:/repo/infra/pool/accounts.toml`）逐行断言 `gateway._windows(row) == []` —— **账本不存在时必须 skip，不许 fail**（它是仓外文件）。
- **今天的读数**：真实账本 5 行，`[account.quota]` 键集 `['observed_at', 'samples', 'source', 'unit']`，五行的 `_windows` 全 `[]`（`python -X utf8 -c ...` 实跑，见验收）。
- 这条咬的是：有人给账本加了 `[account.quota.windows]` 却以为 seatMatch 那一套会自动有意义 —— 加了之后 `_windows` 才可能非空，那时才轮到另开一张卡讨论。

### 判据 4 · 账本校验只按 `id` 去重，没有按名字 / 别名 / 座位去重

- **怎么证明**：pytest 读 `tools/pool_accounts.py` 源码文本，断言 `load_ledger` 函数体含 `if acc["id"] in seen:` 与 `账号 id 重复`，且**不含** `acc["label"] in` / `acc["alias"] in` / `acc["seat"] in` 三个子串（任何形式的「同名合并」都要先撞上这三条否定断言）。
- **今天的读数**：`tools/pool_accounts.py:381-382` 逐字 `if acc["id"] in seen:` / `raise LedgerError(f"账号 id 重复：{acc['id']}")`；`:378` `seen: set[str] = set()`。仓里没有任何按 `label` 去重的代码。
- 这条咬的是：有人把「两个号同一个名字就合成一行」写进账本读取 —— 那是 seat 合并的**另一种实现路径**（不经 seats.json 也能做到），本判据封的就是这条侧门。

### 判据 5 · `tools/pool/cleared.py` 的「别名归并 … 不移植」句逐字在位

- **怎么证明**：pytest 读 `tools/pool/cleared.py` 文本，断言三句都在：`别名归并`、`**不移植**`、`第二套真源`；并断言 `hides()` 函数体里没有把 `model` 映射成别名的分支（否定：不含 `alias` 子串）。
- **今天的读数**：`tools/pool/cleared.py:184-185` 逐字 `别名归并（`:91-98` 的 `c.alias`）**不移植**：pool 的模型名是字面量，猜别名 = 造` / `第二套真源。`
- 这条咬的是：有人「顺手删掉一条过期注释」—— 那会把本卡唯一的锚删掉，而删掉之后仓里再没有任何地方写着「这件事判过、判的是不做」。

## 反向变异（四条，外加一条只改注释的安静对照）

| # | 改哪一行 / 加哪一行（锚点原文） | 哪条判据红 | 怎么红 |
|---|---|---|---|
| M1 | 在 `tools/pool/` 下新建任意模块，写 `def seatsPath(): ...` 或 `seats.json` 字面量（哪怕没人调用） | 判据 1 | 词表 grep 由 `RC=1` 变 `RC=0` 并点名文件 |
| M2 | `tools/pool/gateway.py:99-104` 的 `PATHS` 里加 `"/v1/magpie/quotas": ("GET", ""),` | 判据 2 | 集合断言多出一键；常量断言同时点名 `/v1/magpie/quotas`；桩服务那条 404 也变 405/200 |
| M3 | `tools/pool_accounts.py:381` 前插 `if acc["label"] in seen_labels:` | 判据 4 | 三个否定子串断言中 `acc["label"] in` 命中 |
| M4 | 删掉 `tools/pool/cleared.py:184-185` 那两句（或把「**不移植**」改成「暂缓」） | 判据 5 | `别名归并` / `**不移植**` / `第二套真源` 任一缺失即红 |
| N1 | 只改 `:184` 的标点（句末加一个句号） | 无（安静对照） | 五条全绿 —— 证明判据咬的是事实，不是「文件一动就红」 |

变异脚本落 `gates/diag/_rev_F88.py`（gitignored，`.gitignore:76` 的 `gates/diag/*`），每次 `git checkout -- <file>` 复原；**它不是长钉**，只是这张卡的自检。

## 交付（逐文件）

1. **tests/test_pool_no_seat_merge.py（新建）** —— 五条判据各一个 `test_`，体例照 `tests/test_pool_gateway.py:1-32` 的头注释（钉子表 + 「这里只写**会失败**的断言」）。判据 1 扫仓、判据 2 起桩服务、判据 3 读仓外账本（不存在则 skip）、判据 4 与 5 读源码文本。
2. 复盘/卡/卡A387-F88账号别名与seat合并-判SKIP_NOT_APPLICABLE.md（本文件，已落盘）—— 记录三条论证 + 五条判据 + 改判理由。
3. docs/changelog.d/T-AG675.md（计划建）—— 一段，体例照 `docs/changelog.d/T-AG392.md`（标题行 + `-` bullet + 末行「真读数」）。

> **卡域里不列** `tools/pool/gateway.py`、`tools/pool/cleared.py`、`tools/pool_accounts.py`：本卡只**读**这三份（判据 2 / 4 / 5 都是读源码文本），一个字节都不改。列进域会让 `files_intersect()` 把它们算成本卡可写 —— 而本卡的整个论点是「这些东西不该动」。将来真要改它们，那是另一张卡。

> 既有判定表 `gates/diag/_magpie_scope.md` 在忽略区（`git check-ignore -v gates/diag/_draft_F88.md` ⇒ `.gitignore:76:gates/diag/*`），把 F88 行从 PORT / partial 改成 SKIP_NOT_APPLICABLE 只动未跟踪文件、不进提交 —— 所以**改判的正式投影是卡规格（交付 2），不是那张表**。那张表的 `:96` 一格由**落地时的主树动作**改（与 A384 草稿同一处理）。

## 卡域 files（精确路径，不含通配）

- tests/test_pool_no_seat_merge.py（**本卡新建**，故不作反引号路径）
- 复盘/卡/卡A387-F88账号别名与seat合并-判SKIP_NOT_APPLICABLE.md（本卡规格）
- docs/changelog.d/T-AG675.md（**本卡新建**，故不作反引号路径）

## 验收命令

```bash
# 1) 五条判据（必须 -o addopts= --no-cov，理由见「已知噪音」第一条）
python -X utf8 -m pytest tests/test_pool_no_seat_merge.py -q -o addopts= --no-cov

# 2) 风格（行宽 100，pyproject.toml:78）
python -X utf8 -m ruff check tests/test_pool_no_seat_merge.py

# 3) 判据 1 的原命令（人眼复核用；RC 必须是 1）
grep -rnE "seatMatch|seats\.json|seatsPath|planSeatKey|AccountNames|AccountShown|SeatNameOf|withAccountNames|setAccountName|magpie/quotas" tools/ src/ scripts/ tests/ --include=*.py --include=*.toml; echo "RC=$?"

# 4) 判据 3 的「今天的读数」（5 行账本的窗口维）
python -X utf8 -c "import tomllib,pathlib; from tools.pool import gateway; d=tomllib.loads(pathlib.Path('D:/repo/infra/pool/accounts.toml').read_text(encoding='utf-8')); print(len(d['account']), [gateway._windows(a) for a in d['account']])"

# 5) 判据 4 / 5 的锚（人眼复核用）
sed -n '378,383p' tools/pool_accounts.py
sed -n '184,185p' tools/pool/cleared.py
```

**已知噪音（别当红）**：

- 默认 `addopts` 带覆盖率门槛（`pyproject.toml:51` 逐字 `addopts = "-q -m \"not acceptance and not chain\" --cov=timeflow --cov-fail-under=70"`）⇒ 单跑一个文件不加 `-o addopts= --no-cov` 会因为覆盖率不到 70 而红，那与本卡无关。
- 光秃秃 `grep -rn seat tools/` 会撞 `tools/pool/gateway.py`（31 处）与 `tools/pool/route.py`（96 处）—— 那是「号 id」的意思，不是本卡的对象。用判据 1 的词表，别用 `seat` 单字。
- 真实账本在**仓外**（`D:/repo/infra/pool/accounts.toml`），别的机器上可能不存在 ⇒ 判据 3 那一条必须是 skip，不是 fail。
- `pipe doctor` 在本仓跑不了（无 `pipe` 包、无 tools/doctor.py（仓里没有这个文件），唯一入口是 `tools/pipe.cmd`）⇒ 验收里不列它。

## 不许做

1. **不许实现** `seatMatch` / `seats.json` / 账号别名合并 —— 本卡的产物是「不做」的钉子，不是功能。真要做，先证明本仓出现了「一个座位两张卡」的数据形状。
2. 不许动 `tools/pool/gateway.py` 的 `PATHS`，不许开任何 `/v1/magpie/*` 路径（判据 2 就是钉这个）。
3. 不许往仓外账本写 `alias` / `seat` / `[account.quota.windows]`，也不许在 `infra/pool/` 下建 seats.json。
4. 不许读 / 写 agent 配置文件（红线：不写 agent 配置文件）；不许翻 cookie / 目录 / 钥匙串找凭据。
5. 不许改 `tools/pool/plan.py:46-53` 的 `PROTECTED_FILES` 六条，也不许把这六份文件写进卡域。
6. 不许删 / 改写 `tools/pool/cleared.py:184-185` 的「不移植」句 —— 它是判据 5 的锚。
7. 不许把**未建**的文件写成反引号路径（死指针会顶破 `docs/doc-debt-baseline.toml` 的基线）：本卡里一切未创建的文件都写「（计划建）/ 本卡新建」，且不加反引号。

## 诚实边界（没坐实的事，别当成结论）

1. **`tools/pool/cleared.py:184` 引的 `:91-98` 的 `c.alias` 在当前 magpie 源码里找不到。** `internal/settings/settings.go` 的 `UsageClear` 在 `:2027-2036`、`Covers` 在 `:2043-2046`、`ClearUsage` 在 `:2078`，**没有** `c.alias` 字段；usage alias 已挪到 `UsageAliases`（`:814-822`）与 `internal/provider/usage_alias.go`。⇒ 那两行注释引的是**旧版行号**。本卡不改它（改它要动 cleared.py，属别的卡），但也**不把它当现行判据引用**。**未坐实**。
2. **`D:/repo/program/_ext/_magpie_features.md:740` 说的「文档所指 services.accounts.ts」在 magpie 仓里不存在** —— `find . -name accounts.ts` 空、无 `services/` 目录。该行「实现」列真正指的三个 Go 文件都在（`quotas.go` / `planquota.go` 的 `PlanQuotas` 在 `:719` / `account_seats.go`），TS 那句是功能清单作者的误记。**未坐实**。
3. **「合并后少一张卡」这个效果在本仓无法观察。** 唯一出口是管理面 `GET /v1/magpie/quotas`，本仓 `PATHS` 恰四条、`tools/pool/gateway.py:98` 明写不开管理面 ⇒ 本卡只能钉「机制与出口都不在」，**钉不了「合并逻辑本身对不对」**。
4. **「两条同 label、不同 id 的账本行各占一行」这条运行时探针没跑通。** 造临时账本时先被 `LedgerError: 账号 a-1 的 approved_models 含未批准模型：['m']（批准权只在用户）` 挡住（需 monkeypatch `pool_accounts._approved_models_from_whitelist`），补上后又被 `LedgerError: 账号 a-1 缺 [account.credential] 表`（抛点 `tools/pool_accounts.py:219`）挡住 ⇒ 判据 4 改成**读源码文本**，不写运行时断言。**未坐实**。
5. **`pipe doctor` 跑不了**：本仓无 `pipe` 包（`python -m pipe` ⇒ `No module named pipe`）、无 tools/doctor.py（仓里没有这个文件），唯一入口是 `tools/pipe.cmd`。开工自检因此没跑成，所有读数改用 `git rev-parse` + grep + pytest 实读。
6. **`_ext/` 在本仓不存在** —— 真身在 `D:/repo/program/_ext/`（相对本仓是 `../_ext/`）。本卡把 magpie 引用写全前缀（便于与既有勘察件对齐），但**它不是本仓路径**，任何工具拿它当相对路径都会 `No such file or directory`；复核时请加全前缀。

## 与已完成卡的关系

- **E94**（号池网关同协议直通，done）：给出 `tools/pool/gateway.py` 与 `seat` 这个词。本卡把它的意思钉清楚 —— **号 id，不是座位**。
- **E143**（F86 ③ 窗口与回复上限，done）：把窗口定成**模型属性**；F88 的 `seatMatch` 全靠窗口，所以 E143 一落地，F88 的机制就失去对象。
- **A344**（人给的名字 ↔ 稳定 id，`tools/pool/account_id.py`）：本仓对「名字」这一维的**已有**答案 ⇒ F88 的名字维不是缺口。
- **A368**（`gateway._windows()` 与 `holds.pick()`）：把「有窗口数据时」的分支写对了。本卡只引它，不动它。
- **A358**（`tools/pool/quota_line.py`，magpie `statusline` 移植）：`:43-44` 已独立写过同一结论 —— `4. **`alias` / `user` / `provider` 三个可比值无对应物。** 本模块等比缩到三个串：` / `   `card` / `model` / `card/model`。`

（立卡说明：本规格由草稿 `gates/diag/_draft_F88.md` 物化；草稿被 `.gitignore` 覆盖、不进卡域。写入者 T-AG675。）
