# 卡 E119 · `checkin_status` 声称「只读留档 + 账本」，实现里一次都没打开过 accounts.toml

> 台账号 `T-AG624`｜分区 E（门禁与可信度）｜树 `.wt/E119`（计划建；落地链建卡树）｜层 判据层｜基准 `27780739`｜
> 依据：用户 m00001「本卡主题：checkin_status 声称读账本却没读，而且读写路径分叉（号池只读面撒谎体检第 7 条）」。
> 归属划分：**根分叉**（`tools/pipe_root.py` 的 cwd 判据、读端恒用 `__file__`）归卡 E114；本卡只负责 `checkin_status` 这一面。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · description 与 docstring 都写着「账本 health.last_checkin」，实现里没有这个符号

`tools/pool_mcp.py:501-505`（`TOOL_SPECS` 的 description）逐字：

```text
"今日签到读数（卡 E48）：读当天留档 gates/diag/checkin-<日期>.json "
"与账本 health.last_checkin。**永不触发签到、永不联网** —— "
"真要签得人跑 tools/pool_accounts.py checkin --all。"
```

`tools/pool_mcp.py:1497`（docstring 首行）逐字：「今日签到读数（卡 E48）—— **只读留档 + 账本，不联网、永不触发签到**。」

而实现体 `tools/pool_mcp.py:1494-1536` 只拼一个路径、只读一个文件：

- `tools/pool_mcp.py:1484` `_CHECKIN_DIR = Path("gates") / "diag"`
- `tools/pool_mcp.py:1505` `archive = root / _CHECKIN_DIR / f"checkin-{date}.json"`
- `tools/pool_mcp.py:1507` `payload: dict[str, Any] = {"date": date, "archive": str(archive), "found": archive.is_file()}`
- `tools/pool_mcp.py:1515` `payload.update({"applied": bool(data.get("applied")), "results": rows})`

字节码与源码切片双证（只读探针，`python -B -X utf8`，在主树跑）：

```text
HAS_LEDGER_SYMBOL= False
CO_NAMES= ['JSONDecodeError','OSError','_CHECKIN_DIR','_result','_today_local','append','as_posix','bool','chr','get','is_file','items','join','json','loads','read_text','sorted','str','strip','update']
BODY_HAS_accounts_toml= False BODY_HAS_health= False BODY_HAS_pool_accounts= True
```

最后那个 `True` 不是 import：命中的是 `tools/pool_mcp.py:1533` 那句给人看的话「要签就人跑 tools/pool_accounts.py checkin --all。」
⇒ **这个工具从不加载 `pool_accounts`、从不打开仓外的 `accounts.toml`（`D:/repo/infra/pool/accounts.toml`）、从不读 `health`**。

`git blame -L 499,505` 与 `-L 1494,1501` 全部指向同一笔 `0fff3c7b0`（Wang Jelly 2026-10-25）⇒ 从写下那天起就没读过账本，不是后来改坏的。

### 问题 2 · 读端恒用 `__file__`，写端走数据根 ⇒ 写的和读的不是一个文件

- 读端：`tools/pool_mcp.py:239` `ROOT = Path(__file__).resolve().parent.parent`；`tools/pool_mcp.py:1495` 默认 `root: Path = ROOT`。
- 写端：`tools/pool_accounts.py:58` `TOOL_ROOT = Path(__file__).resolve().parent.parent`，`:59-60` 注释逐字「留档与日志落**数据根**（门禁在卡树跑时数据根就是卡树，见 tools/pipe_root.py）—— 不许用 `__file__` 推，那样门禁在卡树跑会把留档写回主树。」，`:61` `DATA_ROOT = pipe_root.data_root() if pipe_root is not None else TOOL_ROOT`；落盘点 `tools/pool_accounts.py:1408-1410` `_checkin_archive()` → `DATA_ROOT / "gates" / "diag" / f"checkin-{date}.json"`。
- 数据根判据：`tools/pipe_root.py:20` `MARKERS = ("docs/workbacklog.toml", "docs/traceability.toml", "gates/diag")`；`:35-45` `data_root()` = `PIPE_DATA` > cwd（若 `_looks_like_data_root`）> `home_root()`。

实测（同一条探针分别从两个 cwd 跑）：cwd=主树 ⇒ 读写同一路径、`found=false`；cwd=`C:/Users/example/.dsh/profiles/desktop`（那里只有 `gates/diag/`、没有 `docs/workbacklog.toml`）⇒ `pool_mcp.ROOT` 仍是仓库、`pool_accounts.DATA_ROOT` 变成 `C:/Users/example\.dsh\profiles\desktop`，`diverge=true`。
今天（2026-11-16）两个根都**没有**留档（主树 `gates/diag/` 下没有 `checkin-2026-11-16.json`，那份 profile 下也没有同名文件；`os.path.isfile` 双 False）。

⇒ 本卡**不修**根判据（E114 修），但必须让 `checkin_status` 的读数**不假装跨树一致**：payload 要给绝对路径，文案要点明「读的是**本树**的留档」。

### 问题 3 · 账本的 `last_checkin` 是**结论码**，不是「今天的时刻」——照字面读会造出第二次撒谎

- 写：`tools/pool_accounts.py:1475` `health["last_probe"] = stamp`（时刻）、`:1482` `health["last_checkin"] = row["kind"]`（结论码）；`:1480-1481` `if not apply: return`（`--probe` 只写 last_probe，不写 last_checkin）。
- 结论码全集：`tools/pool/checkin.py:44` `KINDS = (CLAIMED, ALREADY_CLAIMED, INACTIVE, NOT_SUPPORTED, UNCERTAIN, FAILED)`。
- 真账本读数（只读 `find_ledger()` + `load_ledger()`，2026-11-16）：

```text
D:/repo\infra\pool\accounts.toml
codearts-1          codearts   last_checkin=uncertain     last_probe=2026-10-25T18:30:46+08:00
codebuddy-tongxue3  codebuddy  last_checkin=not-supported last_probe=2026-10-25T18:30:46+08:00
workbuddy-1         workbuddy  last_checkin=uncertain     last_probe=2026-10-25T18:30:46+08:00
trae-1              trae       last_checkin=uncertain     last_probe=2026-10-25T18:30:46+08:00
meoo-1              meoo       last_checkin=not-supported last_probe=(空)
```

⇒ 五个号的 `last_probe` 全是 **2026-10-25**（22 天前），`meoo-1` 干脆没问过。谁按 description 字面「读 health.last_checkin」写一句「今天签到：uncertain」，就是在今天（2026-11-16）拿 10-25 的结论冒充今天 —— 修完立刻是**新的**撒谎。

### 问题 4 · 兼容面：没有测试断言过 payload 的键集合，但三条既有钉子会咬新实现

`grep -n "set\(payload\)\|payload\.keys\(\)" tests/` 全仓命中只有四处，**没有一条针对 checkin_status**：

```text
tests/test_mutate_report.py:158
tests/test_pipeline_view.py:381
tests/test_pool_mcp_task.py:1081   （usage_report 的 {"accepted","skipped","records"}）
tests/test_renew_lock.py:263
```

⇒ 加 payload 键本身不撞钉子。但 `tests/test_pool_mcp_task.py` 里卡 E48 的三条钉子（分段注释在 `:826`）都传 `root=tmp_path`、除此之外不带任何参数：

- `tests/test_pool_mcp_task.py:829-836` `test_checkin_status_says_missing_when_no_archive`：`is_error is False`、`payload["found"] is False`、`payload["date"] == "2026-01-02"`、text 含「没有留档」与「pool_accounts.py checkin」。
- `tests/test_pool_mcp_task.py:839-862` `test_checkin_status_reads_archive`：在夹具目录里造 `gates/diag/checkin-2026-01-02.json`（`tests/test_pool_mcp_task.py:840-855`）⇒ `payload["found"] is True`、`payload["applied"] is False`、`payload["results"][0]["id"] == "x"`、text 含「只探未领」「not-supported=1」「uncertain=1」。
- `tests/test_pool_mcp_task.py:865-883` `test_checkin_status_is_offline_and_never_writes`：`monkeypatch.setattr("urllib.request.urlopen", _boom)`（被调用就 `AssertionError("checkin_status 不许联网")`），并读 `Path(pool_mcp.__file__)` 源码断言四个写端点（`/v1/ops/claim`、`/daily-checkin`、凭据领取与签到领取两条 URL）一个都不出现（逐字清单见 `tests/test_pool_mcp_task.py:882`）。

★ 后两条把话钉死：**`is_error is False` 在「没有留档」时也不许翻**。所以新实现里账本读不到 ⇒ 只能是 payload 的一格（`ledger_found=False` + 原因），**不许**把 `is_error` 变成 True。
★ 三条钉子都只传 `root=tmp_path` ⇒ 若新实现直接调 `pool_accounts.find_ledger()`，它会读**宿主机真账本**（仓外），测试从此依赖某台机器的账本内容 ⇒ 必须可注入 + 钉子自己 monkeypatch。

### 问题 5 · 「读账本」这件事在只读面里已有现成合法样板，合规成本为零

`tools/pool_mcp.py:1422-1478` `tool_account_status` 就是先例：`:1430` `import pool_accounts`、`:1437` `pool_accounts.find_ledger()`、`:1439-1443` 找不到再按 `root`/`root.parents` 向上逐级拼 `infra` / `pool` / `accounts.toml`、`:1452` `pool_accounts.load_ledger(ledger)`；全程不写盘、不联网。
`tools/pool_accounts.py:287` 的读走 `_lastgood().read_strict(...)`，而 `tools/pool/lastgood.py:350-355` `read_strict` 就是 `target.read_text(encoding="utf-8"); validate(text)` —— 同一份账本**永不被写**，且**账本文件不存在时抛的是 `FileNotFoundError`、不是 `LedgerError`** ⇒ 新实现必须 two-except。

### 推荐侧（二选一，本卡只许走这一侧）：**真读账本**，不是把文案改成「只读留档」

1. 留档只在人真跑过 `pool_accounts.py checkin` 时才落（写端 `tools/pool_accounts.py:1625-1626` 先写留档再 `save_ledger`）；今天两个根都没有留档 ⇒ 只留档那一侧永远只能回 `found=false`，**区分不了「没跑过」与「跑了但 uncertain」**，而后者恰恰是账本唯一记得住的东西。
2. 合规成本为零：问题 5 的样板已证明 `find_ledger + load_ledger` 可以在只读面内完成（不写、不联网、不动凭据）。
3. 三处既有文档投影本来就只写「留档」（`docs/subsystems/pool/README.md:159`、`tools/pool_mcp.py:2845-2846` 的 `_initialize` instructions、`复盘/卡/卡E48-手动签到与聚合入口.md:79`）⇒ 改文案要动三处、还留下「明明账本里有结论却不说」；真读只需把 description/docstring 那句**变成真的**。
4. `tools/wb_daily.py:116-134` 的 `checkin_state` 已经选了相反的侧（`:120` 注释「不拿账本里的 last_checkin 冒充今天的结果」，钉子 `tests/test_wb_daily.py:375-384`）—— 那是「今日一页」的**一行摘要**，口径可以保守；MCP 的 `checkin_status` 是**诊断入口**，description 承诺了账本，就该给全额读数（并如实标 stale）。两处不冲突：都禁止「拿旧结论冒充今天」。

⇒ 判据 2 就是把第 4 条落成机器判据：**账本结论必须与 `last_probe` 的日期一起说**。

## 判据

### 判据 1 · payload 把「留档」与「账本」分成两件事，键集合被钉子钉住

**断言：`payload["found"]` 恒指**留档**存不存在；账本另用 `ledger` / `ledger_found` / `ledger_rows` / `ledger_error` 四格 —— 两件事在 payload 里永远分得开。**

- 无留档、有账本：`set(payload) == {"date", "archive", "found", "ledger", "ledger_found", "ledger_rows", "ledger_error"}`，且 `found is False`、`ledger_found is True`、`len(ledger_rows) == 账本里的账号数`、`is_error is False`。
- 有留档（键集合再加两格）：`{"applied", "results"}`，其余不变。
- 键名纪律：`found` 在本工具**只**指留档（既有钉子 `tests/test_pool_mcp_task.py:833` 已按这个语义钉住）；账本存在性**不许**复用 `found`。`account_status` 的 `{"found","ledger","accounts"}` 组合语义不同（`tools/pool_mcp.py:1477`），不许把两套键混成一套。
- 钉子：`tests/test_pool_mcp_task.py` 新增 `test_checkin_status_payload_separates_archive_from_ledger` —— 上面两条 `set(payload) ==` 逐字断言 + 三格类型断言。

### 判据 2 · 「今天」不许冒领：账本结论必须与 `last_probe` 的日期一起说

**断言：`ledger_rows` 每行必须有 `{"id","platform","last_checkin","last_probe","last_probe_date","is_today"}`；`is_today` 当且仅当 `last_probe` 的日期等于 `payload["date"]`；`is_today is False` 时文案必须说「最近一次问是 <日期> · <结论码>」，不许出现「今天」与结论码连写。**

- `last_probe` 为空（现场就有：`meoo-1`）⇒ `last_probe_date is None`、`is_today is False`，文案「没问过」，**不许**当成今天的结论。
- 留档存在时，同一天（`date` 相同）的留档优先：账本那一段必须写明「留档是同日的、以留档为准」；`date` 早于今天的读法不许改（`tools/pool_mcp.py:1504` 允许 `date` 参数回看）。
- 钉子：`tests/test_pool_mcp_task.py` 新增 `test_checkin_status_never_claims_today_from_a_stale_probe` —— (a) 账本 `last_probe="2026-10-25T18:30:46+08:00"` + `date="2026-11-16"` ⇒ `is_today is False`、`last_probe_date == "2026-10-25"`、text 含 `2026-10-25` 且不含「今天签到」；(b) `last_probe="2026-11-16T09:00:00+08:00"` ⇒ `is_today is True`；(c) `last_probe=""` ⇒ `last_probe_date is None` + text 含「没问过」。

### 判据 3 · 三态可分：留档没有 / 账本说 X / 账本读不了

**断言：三种状态在 payload 上互不覆盖，且三种都不会把 `is_error` 翻成 True。**

- (a) 无留档 + 账本读不到 ⇒ `found is False`、`ledger_found is False`、`ledger_error` 非空、`is_error is False`；
- (b) 有留档 + 账本读不到 ⇒ `found is True`、`ledger_found is False`、`ledger_error` 非空、`is_error is False`；
- (c) 两者都有 ⇒ 两个 True、`ledger_error` 为空串。
- 账本读不了的文案必须点名**绝对路径 + 原因**（照 `tools/pool_mcp.py:1444-1454` 的形状），不许静默回落成「今天还没跑过签到」——那是把「读不到账本」洗成「没签到」。
- 钉子：`tests/test_pool_mcp_task.py` 新增 `test_checkin_status_three_states_are_distinguishable` —— 三态各跑一次，断言上面九条。

### 判据 4 · 账本可注入、只读、离线：不读宿主机真账本、不写账本、不联网

**断言：账本路径必须可注入（参数或 env），钉子跑完账本文件字节不变，且实现里没有一个写端点。**

- 注入样板照抄 `tests/test_pool_accounts.py:876-889`：`monkeypatch.setattr(pa, "find_ledger", lambda explicit=None: patched)`；并按 `tests/test_pool_due.py:145-148` 的警告显式 `monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)`（本机若继承了它会指到别处）。
- 跑前跑后 `hashlib.sha256(fixture.read_bytes())` 必须相同；`fixture.parent` 里不许新增任何文件（`read_strict` 不看 `.bak`，`tools/pool/lastgood.py:350-355`）。
- 既有只读总钉子 `tests/test_pool_mcp.py:217-239` 只按 `tests/test_pool_mcp.py:114-117` 的 `READ_ONLY_INPUTS` 两个文件核对哈希（`docs/workbacklog.toml`、`gates/diag/gate_lock.py`），**不含账本** ⇒ 新钉子补这一格，**不许**靠改 `READ_ONLY_INPUTS` 去覆盖账本（那是仓外文件，`_hashes()` 用 `ROOT / rel` 拼不出来）。
- 钉子：`tests/test_pool_mcp_task.py` 新增 `test_checkin_status_ledger_is_injectable_and_untouched` —— 注入夹具 + sha256 前后相等 + 目录无新文件 + `urlopen` monkeypatch 成 `_boom`（沿用 `:868-871` 的写法）。

### 判据 5 · 文案三处同口径（照卡 E109 的钉子形状）

**断言：`TOOL_SPECS` 的 description、docstring、`docs/subsystems/pool/README.md` 的表行，三处说的是同一件事（留档 + 账本 `health.last_checkin` / `last_probe`），且都点明「结论码不等于今天」。**

- 钉子：`tests/test_pool_mcp_task.py` 新增 `test_checkin_status_prose_agrees_with_what_it_reads` —— 读 `next(s for s in pool_mcp.TOOL_SPECS if s["name"] == "checkin_status")["description"]`（`tools/pool_mcp.py:501-505`）、读 `pool_mcp.tool_checkin_status.__doc__`（`:1497`）、读 `docs/subsystems/pool/README.md:159` 那一行，三处都断言含「留档」+「health.last_checkin」+「last_probe」。形状照 `tests/test_pool_mcp.py:793-813`（卡 E109 判据 5）。
- ★ **不许**把 `复盘/号池MCP-使用与设计.md` 写成第四处对账面：实测 `grep -c checkin 复盘/号池MCP-使用与设计.md` ⇒ **0**，该文件里没有 checkin_status 行；照 E109 那样写 `assert row is not None` 必红。
- `docs/subsystems/pool/README.md:11` / `:92` 是 `<!-- pool-margin:begin/end -->`（生成器 `scripts/gen_pool_readme.py` 管的段），`:159` 在段外 —— 只许改 `:159` 那行文字，不许碰 margin 内。

### 判据 6 · 反向变异 ≥4（真改、真跑、真还原，记 sha256）

- A：把 `tools/pool_mcp.py:1507` 的 `"found": archive.is_file()` 改成 `"found": archive.is_file() or ledger_found` ⇒ 判据 3(a) 的钉子必红（留档没有与账本有分不开）；
- B：把 `is_today` 改成恒 `True` ⇒ 判据 2 的钉子必红；
- C：把注入点换成写死仓外真账本的绝对路径（绕过 `find_ledger`）⇒ 判据 4 的钉子必红（钉子注的是临时夹具）；
- D：在实现里加一行写账本（`save_ledger` 或 `write_text`）⇒ 判据 4 的 `sha256` 断言必红；
- E：把 docstring 改回「只读留档」（去掉账本字样）⇒ 判据 5 的钉子必红；
- C1（安静对照）：只在实现里改一句注释文字 ⇒ 全绿（证明判据不是靠 diff 大小判的）。
- 记录落 `gates/diag/` 下（文件名 `_rev_E119_result.txt`，本卡落地时生成；落地前它不存在）。

### 判据 7 · 不许削弱 / 不许顺手改

- `tests/test_pool_mcp_task.py:829-836` / `:839-862` / `:865-883` 三条既有钉子的断言**一个字都不许改**（`found` 语义、`date` 回显、「没有留档」、「只探未领」、「not-supported=1」、「uncertain=1」、四个写端点不出现）。
- `tools/pool_accounts.py` **一行都不改**（写端与账本形状归 E45 / E114；本卡只读）。
- `tools/pipe_root.py` 的 `MARKERS`（`:20`）与 `data_root()`（`:35-45`）**一行都不改**（归 E114）。
- `tests/test_pool_mcp.py:114-117` 的 `READ_ONLY_INPUTS` 两项不许减（只许加，且不许把仓外账本塞进去）。
- 13 个只读工具的名字与 `annotations.readOnlyHint` 不许动（四处清单：`tests/test_pool_mcp.py:44-58`、`tests/test_pool_mcp_write.py:49-50`、`tests/test_pool_mcp_task.py:74` / `:76`、`tests/test_pool_registry.py:140-141`）。
- 不许把 `DEFAULT` / 阈值类常量改软；不许为了让门变绿去调 `docs/doc-debt-baseline.toml`。

## 交付

1. `tools/pool_mcp.py` 的 `tool_checkin_status`（`:1494-1536`）：加只读账本段（复用 `:1430-1454` 的 `import pool_accounts` + `find_ledger` + `load_ledger` 写法，two-except `LedgerError` / `FileNotFoundError`），payload 加 `ledger` / `ledger_found` / `ledger_rows` / `ledger_error`，正文加「最近一次问」一段；**保留** `date` / `archive` / `found` / `applied` / `results` 五格原义。
2. `tools/pool_mcp.py:1497` docstring 与 `:501-505` description 改成真话（留档 + 账本 `health.last_checkin` / `last_probe`，并明说「结论码可能是旧的，读的时候带 `last_probe` 日期」）。
3. `docs/subsystems/pool/README.md:159` 表行补「+ 账本 `health.last_checkin` / `last_probe`（只读，标明哪天的结论）」半句；`tools/pool_mcp.py:2845-2846` 的 `_initialize` instructions 同句跟着改（现在只写「读当天签到留档」）。
4. `tests/test_pool_mcp_task.py`：判据 1-5 的五条新钉子（放在卡 E48 那段 `:826` 之后、卡 A364 那段 `:884` 之前）。
5. 变异读数落 `gates/diag/` 下（文件名 `_rev_E119_result.txt`）。
6. 卡规格 + 三片段由落地链 ② 文档件按台账号 `T-AG623` 自动生成；**落成前它们还不存在，所以这里不写死路径**。

## 验收（三条，落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pool_mcp_task.py tests/test_pool_mcp.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool_mcp.py tests/test_pool_mcp_task.py
python -X utf8 -m pytest tests/test_pool_registry.py tests/test_pool_accounts.py -o addopts= -q --no-cov
```

第二条跑 ruff；第三条盯的是「工具面与账本面没被碰坏」（工具名清单 + `account_status` 的账本只读），不是新增判据。

## 不许做

- 不许两条腿都占：既然本卡选了「真读账本」，就**不许**同时把 docstring 降级成「只读留档」——两侧都含糊等于第二次撒谎；
- 不许拿 `health.last_checkin` 冒充「今天的结果」（判据 2 就是堵这条；`last_probe` 22 天前是现场事实）；
- 不许联网、不许触发签到（`pool_accounts.py checkin` 只许出现在「要人手动跑」的文案里）、不许写账本 / 写留档 / 建 `.bak`；
- 不许读宿主机真账本做钉子（必须注入），否则测试从此绑某台机器；
- 不许改 `tools/pool_accounts.py` / `tools/pipe_root.py` / `tools/pool/lastgood.py` / `tools/pool/checkin.py`，也不许把 `is_error` 在「没有留档」时翻成 True（会直接红掉 `tests/test_pool_mcp_task.py:832`）；
- 不许在 `docs/subsystems/pool/README.md` 的 `pool-margin` 段内手改（`:11` / `:92`，生成器管）；不许在 `复盘/号池MCP-使用与设计.md` 里现造一行 checkin_status 去凑对账。

## 直做几步

1. 先读 `tools/pool_mcp.py:1494-1536` 与 `:1422-1478`，照 `account_status` 的 two-except 只读段写；**不新造帮手**（`tools/pool_accounts.py` 一行不改）。
2. 先改钉子再改实现：让判据 1-5 先红（红在「键不存在」），再逐格补 payload。
3. 时间口径先定死：`last_probe_date = last_probe[:10]`（空 ⇒ None），`is_today = last_probe_date == payload["date"]`；文案两个分支分开写。
4. 再改三处文案（description / docstring / README:159 + `_initialize` instructions），跑判据 5 的钉子。
5. 跑验收三条命令；然后逐条做判据 6 的 A/B/C/D/E + C1，每条记 sha256 与退出码，还原后重跑一遍全绿。

## 未验证（不许当结论）

- 本轮**没跑** pytest / 门禁 / 落地链（主树在跑全量门禁，硬约束禁止）⇒ 判据 1-5 的钉子全部**未验证**，验收退出码也未验证。
- `scripts/gen_pool_readme.py` 重跑后 `docs/subsystems/pool/README.md:159` 会不会漂移：未验证（未跑生成器）。
- `tools/dsh_panel.py:2696`（`checkin ? (checkin.found ? "已签到" : "没跑") : "—"`）读的是 `wb_daily` 的 `daily.checkin`、不是 MCP 的 `checkin_status` ⇒ 本卡是否需要同步面板：未验证。
- 卡 E114-E118 的卡号与内容不在 `docs/workbacklog.toml`、也不在 `复盘/卡/` 下：未验证（本卡与 E114 的边界按用户 m00001 的划分写）。
- `tests/test_wb_daily.py:375-384` 那条钉子的逐字断言：只读到「绝不拿账本里的 last_checkin 冒充」这一句注释，未逐行读：未验证。
