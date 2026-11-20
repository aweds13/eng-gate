# 卡 A388：F22 并发闸的排队（QueueWait）判 SKIP_BY_REDLINE，只钉「不排队」

> 台账号 `T-AG676`｜分区 A（magpie 移植 / 号池 pool）｜树 .wt/A388｜层 判据层（钉住判据形状与零命中扫描，不落新行为）｜基准 `78d4c16a`（立卡时主树 HEAD，2026-11-20 实读）｜depends A339、A367

> depends 说明：**A339、A367 两张都已 `done` ⇒ 按 `tools/pool/plan.py` 的口径它们不参与冲突域判定**（`ACTIVE_STATUS = ('pending','running')`），抬头写它们是为了**判据引用归属**（与 A380 / A381 的既有体例一致），不是「同一文件两个写者」的解药。
> - **A339**（F22 并发闸本体，done）：`files` 正是本卡这四份（`tools/pool/lanes.py` / `tools/pool/guards.py` / `tools/pool/lanes.toml` / `tests/test_pool_lanes.py`）。F22 的「排队」这一层与它写在同一对文件上，所以本卡的改动落在它写过的行上 —— 判据 1 / 2 / 3 全是对它留下的签名的反向钉。
> - **A367**（F33 限额数据面，done）：`files` 只有 `docs/subsystems/pool/modules.toml`，与本卡四份**不相交**。抬头保留它是按立卡指令，作用同 A339 —— 读法参照（「限额/闸」这条线上它已经把数据面读过一遍），**不是**本卡的写冲突来源。
> - **★ 实算：按本卡四份卡域与台账求交，活跃命中 0 张**（2026-11-20 立卡时实跑：`tools/pool/plan.py` 的 `load_backlog()` 共 412 张、活跃 20 张；四份求交 ⇒ 活跃 0；全表命中 6 张全 `done`：108 / 120 / A336 / A339 / A342 / A344）。⇒ 立卡不会被拒单，也**不需要**额外补 depends。草稿 `gates/diag/_draft_F22.md:3` 写的「A373 / A375 / A381 只因 `docs/subsystems/pool/README.md` 潜在相交」也一并复核过：本卡**不碰 README**，四条卡域里没有它 ⇒ 三条都不用写（起草末的 410 张 / 20 活跃已漂到 412 / 20，台账一天动两次，立卡时按当时台账重核）。

> 基准说明：草稿的基准是 `1265dd1d`；物化这一刻主树 HEAD 是 `78d4c16a`（其后又到 `bc41ba76`，之后只有一笔 docs-only）。所引本仓源码行号在两处都逐条复读未变 —— `git diff --stat 1265dd1d..HEAD -- tools/pool/lanes.py tools/pool/guards.py tools/pool/lanes.toml tests/test_pool_lanes.py tools/pool/registry.py tools/pool/gateway.py` **为空**。

> 依据：功能清单 `D:/repo/program/_ext/_magpie_features.md:208` 的 F22；既有判定表 `gates/diag/_magpie_scope.md:30` 今天把 F22 判成 `PORT | partial`，备注逐字「tools/pool/lanes.py + guards.py 并发闸在（A339 done）；但 lanes.py:38/:60 明写「本卡不实现排队，queue 只进文案」⇒ 队列/QueueWait 未落」。★ 本卡**不是**把那个 `partial` 补成 landed，而是把「不落」写成可复核的钉子。

## 前情：原件为什么要有「排队」这一层

F22 在功能清单里是「每 key/账号并发闸与队列」，要解决的冲突（同文件 `:210` 逐字）：

```text
- 解决：一个账号同时跑太多请求会被 vendor 限流；完全串行又浪费。
```

⇒ **「排队」不是顺手加的**：没有它，超限只有两条路 —— 拒（浪费并发余量）或放开（撞 429）。排队是第三条路：让请求在闸门口等，槽一空就发。

原件的理由（`D:/repo/program/_ext/magpie-main/internal/gateway/concurrency.go:14-26` 逐字）：

```text
// A provider's MaxConcurrency (Discord, Lemon: a Codex account is
// risk-controlled past five or six requests at once) is how many requests
// may be out at the vendor at once on each of its keys or accounts — the
// key, the account, else the provider: a candidate's who(). One more waits
// in a queue of no bound, in the order it came, and is sent when one out
// is done: its reply read to the end, or the agent gone. A request whose
// agent goes away while it waits leaves the queue and is never sent.
//
// Waiting is not failing: a request queued is never passed to a fallback
// for want of a free slot, and the key or account it waits for doesn't
// rest. That is what the setting is
// for — the vendor sees no more than that many — and what is waited is
// told in the route's try (Try.Queued).
```

排队的两条边界（同文件 `:43-51` 逐字）：

```text
// Its own limit (#892) and the queue's bound and wait. A key or account
// may have a limit of its own, over the provider's (provider.LaneLimit),
// and the count is the lane's whatever asks for it: a model, a routing
// group or an agent. A provider's QueueLimit bounds how many wait for each
// of its lanes: one more is turned away at once (errQueueFull), and one
// that waited QueueWait seconds is turned away (errQueueWait) and leaves
// the queue. Turned away, a try is passed on as a failure that rests
// nobody: to the next key, account or member, else told to the agent as a
// 429 in its API's own shape, with Retry-After.
```

**排队是怎么实现的（这一段是本卡判定的关键）**：`concurrency.go:109-131` 逐字：

```go
	if queue > 0 && len(ln.queue) >= queue {
		l.mu.Unlock()
		return nil, 0, errQueueFull
	}
	ch := make(chan struct{})
	ln.queue = append(ln.queue, ch)
	l.mu.Unlock()
	defer notePhase(ctx, "slot")()
	queued := time.Now()
	var timeout <-chan time.Time
	if wait > 0 {
		t := time.NewTimer(wait)
		defer t.Stop()
		timeout = t.C
	}
	select {
	case <-ch:
		return l.releaser(who, ln), time.Since(queued), nil
	case <-ctx.Done():
		err = ctx.Err()
	case <-timeout:
		err = errQueueWait
	}
```

出队是 FIFO（`concurrency.go:218-224` 逐字）：

```go
func (ln *lane) grant() {
	for len(ln.queue) > 0 && (ln.limit <= 0 || ln.busy < ln.limit) {
		ln.busy++
		close(ln.queue[0])
		ln.queue = ln.queue[1:]
	}
}
```

并且排队期间**必须有人守着 agent 的流**，否则等待会被调用方的 header 超时掐掉 —— `internal/gateway/fallback.go:2669-2682` 逐字（节选关键两句）：

```text
// keepQueued keeps the agent of a stream alive while its try waits for a
// slot of its key's or account's (MaxConcurrency) or for room in its
// minute (MaxRPM), before anything is sent to the vendor: past
// keepHeldAfter it is sent the stream's 200 and SSE comments
// (keepAlive), every keepHeldEvery for as long as the wait lasts, as a
// try's held stream is. A wait of up to 2 minutes for the minute, or
// QueueWait's for a slot, sent the agent nothing at all, which an agent's
// or a proxy's timeout for its headers ended first (coeo91 on Discord:
// WorkBuddy, Trae and Qoder said the request timed out).
```

实现就在 `fallback.go:2687-2691` 逐字（起一个 goroutine + 一个 ticker）：

```go
	done, over := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(over)
		tick := time.NewTicker(watchEvery)
		defer tick.Stop()
```

（`watchEvery = time.Second`，同文件 `:2667`。）

**⇒ 结论性事实：原件的排队 = 一个有界队列 + 一个 channel 上的 select + 一个 `time.NewTimer` + 一个 `time.NewTicker` 守活 goroutine。没有定时器 / 后台等待，这一层在 Go 里也不成立。**

端点与计数面（`concurrency.go:233-239` 逐字）：

```go
type Lane struct {
	Busy    int `json:"busy"`
	Waiting int `json:"waiting"`
	Limit   int `json:"limit"`
}
```

配置上界（`internal/provider/concurrency.go:43-47` 逐字）：

```go
const (
	MaxLimit      = 1000
	MaxQueueLimit = 10000
	MaxQueueWait  = 3600
)
```

## 本仓现状（全部主树实读）

### 已经有的（A339 落地的那一半）

- `tools/pool/lanes.py:36` `MAX_LIMIT = 1000`；`:38-39`

```python
#: 队列上限的上界（同上 `maxQueueLimit`）。★ 本卡**不实现排队**，这个值只是"读进来不拒"。
MAX_QUEUE_LIMIT = 10000
```

- `tools/pool/lanes.py:41-42`

```python
#: 等多久的上界（同上 `maxQueueWait`），单位秒。★ 同上：留给下一张卡，本卡只做越界检查。
MAX_QUEUE_WAIT = 3600
```

- `tools/pool/lanes.py:60-61`（`Lane` docstring 逐字）

```text
    ★ `queue` 在本仓目前**只进文案**：pool 的派活是同步的，没有"在等"这个状态，
      所以它表达的是"允许多少个派活进程在闸门口等"，判据仍按 `limit` 算（见 `lane_guard`）。
```

- 判据面 `tools/pool/guards.py:337-338` 签名逐字 —— **注意：没有 `wait` 形参，连收都不收**

```python
def lane_guard(account: object, reservations: Iterable[dict], *, limit: int,
               queue: int = 0, now: float | None = None) -> list[str]:
```

- `tools/pool/guards.py:360-364` 逐字

```text
    ★ `queue` 的语义**说实话**：magpie 的 QueueLimit 是**真队列**（进不去就排队等）；pool 的派活
      是同步的，**没有"在等"这个状态** ⇒ 本函数里 `queue` 只能表达"允许多少个派活进程在闸门口等"，
      `queue == 0` = 不排队、直接拒。本卡**不实现等待**（`wait` 留给下一张卡），所以
      `queue > 0` 时判据与 `queue == 0` **完全相同**（都按 `limit` 判），只在文案里多一句
      "队列上限 q 张" —— 绝不写 `while True: sleep`。
```

- `tools/pool/lanes.toml:25-27`（配置面自己就把话说死了）

```text
# ★ `queue` / `wait` 现在**只进文案**：pool 的派活是同步的，没有"在等"这个状态，
#   本卡也不实现排队（`wait` 留给下一张卡）。所以 `queue > 0` 时判据与 `queue = 0` 相同，
#   都按 `limit` 判 —— 别以为写了 `queue = 5` 就真的会等 5 个。
```

### 接线处：三处都是「换下一个号 / 直接失败」，没有「等」

- `tools/pool/registry.py:339`（占树时判）：`*guards.lane_guard(account, live, limit=lane.limit, queue=lane.queue, now=stamp),`
- `tools/pool/gateway.py:661-663`（转请求时判，判到就换号）

```python
        if busy:
            skipped.append(f"{seat}：{'；'.join(busy)}")
            continue
```

- `tools/wb_dispatch.py:4034-4039`（派活时判，判到就退 2，不重试不等待）

```python
        except pool_registry.GuardError as exc:
            print("[FAIL] 占树被守卫拦下，**不派活**：", file=sys.stderr, flush=True)
            for item in exc.problems:
                print(f"  · {item}", file=sys.stderr, flush=True)
            give_back_stamp("占树被守卫拦下")
            return 2
```

- `grep -n 'add_argument("--wait' tools/wb_dispatch.py` ⇒ **0 命中**（派活面根本没有「等」这个开关）。

### 正面撞上的红线（原文）

- `tools/pool/gateway.py:11` 逐字

```text
3. **不做定时器**：没有后台线程；沉底 / 每分钟闸 / 并发闸都是每次请求现读现算。
```

- 同一条纪律被多张卡继承：`grep -rn '不做定时器'` 在仓内命中 `tools/pool/gateway.py:11`、`复盘/卡/卡A372-F56搜索API多key轮换-被拒才换下一个与各自rest.md:195`、`复盘/卡/卡A374-F58-web_fetch只读公共地址.md:325`、`复盘/卡/卡A375-F82远端provider显式登记.md:299`、`复盘/卡/卡A380-F96Context页分段账-只留名字与大小不搬面板与读回原文.md:25`。
- `tools/pool/guards.py:364` 末句「绝不写 `while True: sleep`」；A339 规格的判据 3 逐字「本卡**不实现等待**（`wait` 留给下一张卡）… **不许**把「等待」写成 `while True: sleep`」（`复盘/卡/卡A339-一个号同时只能派几张.md`）。
- 同判的 SKIP_BY_REDLINE 先例（A380 规格 `:25` 逐字）：「正面撞两条既有纪律：`gateway.py:11`「不做定时器：没有后台线程」与 `route_log.py` 模块 docstring 第 3 条「追加，不环形」」；`:152` 逐字「不许把 body 缓存起来、不许加后台线程 / 定时器 / 环形缓冲 —— 是**两条既有决定**，要改也得另开卡。」

### 零命中扫描（立卡时实跑，逐条可复核）

| # | 命令 | 读数 |
|---|---|---|
| S1 | `grep -rn '\.wait\b' tools/ --include=*.py` | `tools/pool/lanes.py` 只有 `:93`（读入）、`:98-99`（越界）两处；没有第二处消费者 |
| S2 | `grep -rn 'QueueWait\|queue_wait' tools/ scripts/ --include=*.py` | 只有 2 行：`tools/pool/lanes.py:41`（注释）与 `tools/pool/landing.py:2601`（**落地合并队列**，同名不同物） |
| S3 | `grep -n 'time\.sleep\|threading\|asyncio' tools/pool/registry.py tools/pool/gateway.py tools/pool/lanes.py tools/pool/guards.py` | **RC=1（零命中）** |
| S4 | AST 扫三个文件的 import 与 `ast.While` | lanes: `__future__ dataclasses pathlib tomllib`，While=[]；guards: `__future__ collections datetime domain_symbols pathlib pool typing`，While=[]；registry: 有 `time`（TTL 用）但 While=[] |

★ S2 的 `tools/pool/landing.py:2601` 逐字：

```python
    if not merge_queue.wait_turn(a.task, timeout=a.queue_wait, say=print):
```

那是**落地合并队列**（`tools/pool/queue.py` 的单写者段排队；`docs/subsystems/pool/README.md:54` 写「落地合并队列：单写者段排队 + 投机预检」），跟 F22 的「每 key/并发闸排队」**同名不同物** —— 本卡不许把它当成 F22 的排队，也不许删它。

## 判定：SKIP_BY_REDLINE

**为什么不是 PORT。** 原件这一层的成立条件是「有东西在等」，而本仓的派活是**同步进程** —— `wb_dispatch` 占树被拦就 `return 2`（上引 `tools/wb_dispatch.py:4034-4039`），调用方自己决定等多久或换号；进程退出后没有对象能「继续等」。要真做，只有三条路，三条都撞墙：

1. **进程内自旋等**（`while True: sleep`）⇒ 直接违反 `tools/pool/guards.py:364` 与 A339 判据 3 的明文禁令；
2. **后台线程 / 定时器**（照抄 `time.NewTicker` + goroutine 那个形状）⇒ 违反 `tools/pool/gateway.py:11`「不做定时器：没有后台线程」，且守卫那层要变成有状态服务（今天 `tools/pool/guards.py:1-6` 逐字「**纯函数**…不写文件、不 `print`、不起进程」）；
3. **把等待挪到租约层**（先占位再阻塞）⇒ 会把「占树」从一次原子判断变成「持有半张租约」，`tools/pool/registry.py:330-344` 那条「判不出来就不动手」的纪律就废了。

**为什么不是 SKIP_NOT_APPLICABLE。** 这个能力**可理解、本仓也懂**（`queue` / `wait` 的读入、越界、文案全都在），撞的是**本仓自己写下的纪律**，不是「这个能力跟我们没关系」。按本仓口径：撞红线的判 SKIP_BY_REDLINE。

**⇒ 判定：队列 / QueueWait 这一层不移植。** 保留今天的三件事：数据面「读进来不拒」、判据只按 `limit`、`queue` 只进文案。并且**把「不排队」本身钉成判据**（下节），不留成「还没做」。

## 判据（6 条，每条一条命令或一个 pytest 能证）

**判据 1 — `lane_guard` 的签名永远没有 `wait`。**
命令：`python -X utf8 -c "import sys,inspect;sys.path.insert(0,'tools');import importlib;g=importlib.import_module('pool.guards');print(sorted(inspect.signature(g.lane_guard).parameters))"`
今天读数（实跑）：`['account', 'limit', 'now', 'queue', 'reservations']`。
为什么钉得住：有人要偷偷实现等待，第一件事就是给判据塞一个 `wait`；签名是白名单判断，塞进去立刻红。

**判据 2 — `queue > 0` 与 `queue == 0` 的判据完全相同，只在文案里多一句。**
命令：`python -X utf8 -m pytest tests/test_pool_lanes.py::test_lane_guard_bites_at_limit -q`（该测试 `:104-108` 已钉 `queue=5` 多出「队列上限 5 张」）。本卡扩成参数化并加一条反向：`queue=0` 的文案里**不含**「队列上限」。
今天读数（实跑，2 条同账号租约 + `limit=2`）：`queue=0` ⇒「这个号已经占满：账号 codearts-1 同时在跑 2 张，上限 2 张 —— 等它收工（或换个号）再派」；`queue=5` ⇒ 同上但在「上限 2 张」后多「，队列上限 5 张」。两条问题**条数都是 1**。

**判据 3 — 闸这条链上没有定时器 / 线程 / 自旋（源码级钉子）。**
命令（AST，不靠肉眼）：扫 `tools/pool/lanes.py`、`tools/pool/guards.py`、`tools/pool/registry.py`，断言 `ast.While` 为空、`lanes.py` 与 `guards.py` 的 import 集合里没有 `time` / `threading` / `asyncio`。
今天读数（实跑）：lanes `['__future__','dataclasses','pathlib','tomllib']` While=[]；guards `['__future__','collections','datetime','domain_symbols','pathlib','pool','typing']` While=[]；registry 有 `time`（TTL 用，不是等待）但 While=[]。
★ 反向变异：在 `guards.py` 里加一行 `time.sleep(0.1)` ⇒ 这条必红（A380 规格 `:104` 用同一手法）。

**判据 4 — 数据面仍是「读进来不拒」，且不许 clamp。**
命令：`python -X utf8 -m pytest tests/test_pool_lanes.py -q`，并加一条新钉子：`wait = 3601` 必须抛 `LanesError`、`queue = 10001` 必须抛，且 `load_lanes()` 读到的 `Lane.wait` 原样等于文件里的值（不夹到 3600）。
为什么钉得住：一旦有人在读入处擅自 clamp（「反正不用，夹到 0 更安全」），配置里写了什么就再也看不出来了 —— 而「读进来不拒」正是将来真要接这层时唯一的入口。

**判据 5 — 全仓没有第二个消费者把 `wait` 当真（零命中扫描固化成测试）。**
命令：`grep -rn 'QueueWait\|queue_wait' tools/ scripts/ --include=*.py`，断言命中集合恰为 `tools/pool/lanes.py:41`（注释）与 `tools/pool/landing.py:2601`（落地合并队列）。
今天读数（实跑）：正是这 2 行。
★ 断言里要写明为什么放行 `landing.py:2601`：它排的是**落地合并**，不是每 key 并发闸（`docs/subsystems/pool/README.md:54`）；不加这句，后来人一定误删。

**判据 6 — 反向变异 ≥3 条，每条都要有人变红。**

- (a) `tools/pool/guards.py:372` 的 `if limit <= 0:` 改成 `if limit < 0:` ⇒ 判据 2 与既有 `test_lane_guard_zero_limit_is_unlimited` 一起红；
- (b) `tools/pool/guards.py:375` 的 `if running < limit:` 改成 `if running <= limit:` ⇒ `test_lane_guard_bites_at_limit` 红（`:96` `len(problems) == 1` 失败）；
- (c) 在 `tools/pool/guards.py` 里 import `time` 并加一句 `time.sleep(0.1)` ⇒ 判据 3 红。

## 卡域 files（精确路径，不含通配）

- `tools/pool/lanes.py`
- `tools/pool/guards.py`
- `tools/pool/lanes.toml`
- `tests/test_pool_lanes.py`

卡规格本身：复盘/卡/下的一张（本文件；落盘前不加反引号，见「不许做」第 7 条）。

**故意不写进卡域的两份**：

- `gates/diag/_magpie_scope.md` —— 被 `.gitignore` 覆盖，卡树里没有这份文件，改了也落不了地；它的 `:30` 那一格由**落地时的主树动作**改（与 A384 草稿 `:238` 同一处理）。
- `docs/subsystems/pool/README.md` —— 今天 `files` 含它的活跃卡是 A373 / A375 / A381 三张；按上面四份求交 ⇒ **0 命中**，只有把 README 也算进域才会撞上这 3 张。不碰 README ⇒ 三条 depends 都不必写。

## 验收命令

```bash
# 1) 闸的全部测试（含本卡新增的反向钉子）
python -X utf8 -m pytest tests/test_pool_lanes.py -q

# 2) 判据 1：签名里没有 wait
python -X utf8 -c "import sys,inspect;sys.path.insert(0,'tools');import importlib;g=importlib.import_module('pool.guards');print(sorted(inspect.signature(g.lane_guard).parameters))"

# 3) 判据 5：全仓只有 2 行提到 queue_wait（恰为 lanes.py:41 与 landing.py:2601）
grep -rn 'QueueWait\|queue_wait' tools/ scripts/ --include=*.py; echo "RC=$?"

# 4) S3：闸这条链上没有 sleep / 线程 / 协程（必须 RC=1）
grep -n 'time\.sleep\|threading\|asyncio' tools/pool/registry.py tools/pool/gateway.py tools/pool/lanes.py tools/pool/guards.py; echo "RC=$?"
```

**期望**：①pytest 全绿（今天 `tests/test_pool_lanes.py` 8 passed）；②签名恰为 `['account','limit','now','queue','reservations']`；③第二条 grep 恰 2 行；④第三条 grep **RC=1**（零命中）。

**门禁由 `wb_land` 按域跑，起草 / 立卡阶段不跑 `scripts/run_gates.py`。**

## 不许做

1. **不许**在 `tools/pool/guards.py` / `tools/pool/lanes.py` 里出现 `time.sleep` / `while True` / `threading` / `asyncio` / 后台线程 / 定时器 —— 这是 `tools/pool/gateway.py:11` 与 A339 判据 3 的**既有决定**，要改也得另开卡。
2. **不许**给 `lane_guard` 加 `wait` 形参，也不许在 `registry.reserve` / `gateway` 的换号循环里加「等到有空位」。
3. **不许**把 `queue` 的语义改成「真排队」的文案（比如「排第 3 位」）—— 文案说了不等，行为就必须不等。
4. **不许**动 `tools/pool/landing.py:2601` 那个 `merge_queue.wait_turn`：它是落地合并队列，与本卡无关。
5. **不许**在 `load_lanes()` 里 clamp `wait` / `queue`（判据 4）。
6. **不许**改 `gates/diag/_magpie_scope.md` 当作本卡交付（它在 `.gitignore` 里）；表那一格写进落地的「主树动作」。
7. **不许**跑 `scripts/run_gates.py` 或建 worktree 来「验证」本卡 —— 本卡只动四份文件 + 测试。另外：**指向本卡新建文件的路径不加反引号**（`scripts/check_docs.py` 会把不存在的反引号路径记成死指针，`docs/doc-debt-baseline.toml` 的基线只能降不能升）。

## 诚实边界（没坐实的事）

1. **原件 `internal/gateway/active.go` 未读**：`notePhase(ctx, "slot")` 的可观测面（对外暴露「正在等槽」这个相位）本卡没有逐行核，只说功能清单 `:212` 提到它。**未坐实**。
2. **`/v1/magpie/concurrency` 那个 HTTP 端点本仓没有对应面**（`concurrency.go:251-266` 的 `waiting` 汇总）：本卡**不判它**（scope 表里 F37「诊断三件套」已判 no，两者相邻但不重叠），若要判应另开卡。
3. **「真正瓶颈是本机内存」这句是转引**：`tools/pool/lanes.py:12` 与 `tools/pool/guards.py:344` 都写「`gates/diag/gate_lock.py` 原文：一趟 17 门要 15–30 个无头 Edge」；已回读 `gates/diag/gate_lock.py:13` 逐字「2. **整机并行趟数**有上限（真正的瓶颈是内存：一趟 17 门要 15–30 个无头 Edge）」，但**没有**独立测量今天一台机器能扛几张卡 —— 本卡不需要这个数，也别把它当成本卡的判据。
4. **`tools/pool/plan.py` 的 `DEFAULT_CONCURRENCY = 2`（`:40`）与 F22 无关**：它算的是**排批**（一批同时跑几张卡），F22 算的是**同一个号**同时在跑几张。两者名字像、单位不同，不许互相引用。
5. **基准会漂**：起草期间主树 HEAD 从 `964c43a3` → `807c44a8` → `1265dd1d`（别的卡在落地），物化时到 `78d4c16a`。抬头写的 `78d4c16a` 是立卡那一刻的读数，立卡脚本落盘时若 HEAD 已前进，按当时重读 `git rev-parse --short HEAD`。
6. **「A373 / A375 / A381 相交」的复核是 2026-11-20 的实算**（backlog 412 张 / 活跃 20 张；草稿起草时是 410 / 20、更早 408 / 19 —— 台账一天动两次）。本卡四条卡域与台账求交今天 0 活跃命中，但**立卡时必须重跑一次**，不能照抄这段读数。

（立卡说明：本规格由草稿 `gates/diag/_draft_F22.md` 物化；草稿被 `.gitignore` 覆盖、不进卡域。写入者 T-AG676。）
