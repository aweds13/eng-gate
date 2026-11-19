# 卡 A367（已立卡）：F33 限额数据面 —— limits.toml 落地前先裁决「同一份文件两个形状」

> 台账号 `T-AG652`（已立卡）｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A367`｜层 数据层（判据层不动）｜基准 `5b663886`（起草时主树 HEAD）｜depends A338、A341、A350
> depends 说明：**A338**（限额判据层三份模块 + `tests/test_pool_limits.py`）、**A350**（派活前限额闸接线，`tools/wb_dispatch.py:3584-3629`）、**A341**（F34 模型白名单，`tools/wb_dispatch.py:451-483`）三张都已 done；本卡要定的是它们**共用那一份数据文件**的形状，三者任一改口径都会让本卡判据失去意义 ⇒ 必须写 depends（同域共存规则见 `tools/pool/plan.py:267-272` 的 T-G119）。
> 基准说明：起草时主树 HEAD = `5b663886`（`git rev-parse --short HEAD` 实读）。本文全部行号是只读勘察时逐行读过的；落地前请按当时 HEAD 重核一次再引用。
> 依据：`gates/diag/_magpie_scope.md:41`（F33 判 `partial`：「数据面未落；无 tools/pool/limits.toml」）+ `tools/pool/limits.py:14` 逐字「★ **本卡不引入 limits.toml 的真实数据文件**（那是 F33 的活）」+ `tools/pool/limits.py:18-21`（「表坏了、但我不知道这张卡有没有声明」这一态今天读不出来）+ 本文缺口 2 的实测 schema 冲突。

## 前情

- F33 的**判据层已经齐了**，三份模块都在生产路径上：
  - `tools/pool/limits_policy.py`（283 行）：解析 `[[<账号>.limit]]` 段，入口 `load_limits(path=None)` 在 `:249`；
  - `tools/pool/limits_check.py`（174 行）：判「还有没有余量」，入口 `check(...)` 在 `:73`；
  - 接入点两处，都在 `tools/wb_dispatch.py`：`:3584-3629` 限额闸（卡 A350）、`:451-483` 模型白名单（卡 A341/F34）。
- 缺的**只有数据面**：仓外 `D:/repo/infra/pool/limits.toml` 不存在（实测 `os.path.exists` = `False`）；仓内没有任何 limits 数据文件（`ls tools/pool/*.toml` 只有 `lanes.toml` / `model-registry.toml` / `platforms.toml` / `rpm.toml` 四份）。
- 今天的行为是**正确但空转**：`load_limits()` 回 `{}` ⇒ 限额闸一个副作用都没有（`wb_dispatch.py:3593` 逐字「判据 4：文件不存在 ⇒ `load_limits()` 回 `{}` ⇒ 这一段一个副作用都没有」）；`caller_model_patterns()` 恒空 ⇒ 白名单闸不生效（`docs/traceability.toml:10179` 记过同一条）。
- ★ 所以本卡**不是「补一个文件」**：文件一旦存在，「文件坏了」与「两个 reader 抢同一份」这两件事就同时从不可能态变成现实态。写文件之前先把契约定死。

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 默认路径落在**仓外**，在仓内写一份不会被读到

现场（2026-11-19 实跑，`sys.path` 插 `tools/`）：

```
limits.TOOL_ROOT    = D:/repo/engineering
limits.pool_dir()   = D:/repo/infra/pool
limits.limits_path()= D:/repo/infra/pool/limits.toml      exists = False
os.path.isdir('infra') = False        # 本仓没有 infra/ 目录
```

- `tools/pool/limits.py:41` `TOOL_ROOT`；`:43` `LIMITS_ENV = "TF_POOL_LIMITS"`；`:44` 注释「策略文件名（与 `accounts.toml` 同目录）」；`:45` `LIMITS_NAME = "limits.toml"`；`:47` `POOL_ANCHOR = ("infra", "pool")`。
- `:50-62` `pool_dir()` 逐级向上找 `infra/pool`（`:54-55` 注释：与 `tools/pool/models.py::find_pool_dir` 同一套找法，只是不要求锚点文件存在）；`:65-71` `limits_path()` 三段（env > `pool_dir()` > `TOOL_ROOT/infra/pool/limits.toml`）；`:75` `LIMITS_PATH = limits_path()` —— **import 时求值**，测试只能靠 env 覆盖。
- 对照组：`tools/pool/rpm.py:181` `load_rpm()` 的默认位址是 `Path(__file__).resolve().parent / RPM_FILE` —— **仓内**。两份数据文件一个仓外一个仓内是刻意的差别（rpm 是人写的闸表，limits 要与 `accounts.toml` 同目录），但这条差别**从没写进任何规格**。

### 缺口 2 · 同一份 limits.toml，两份 reader 要的顶层形状**不相容**（实测复现）

现场（tempfile 写一份含两段的文件，再跑两个 reader）：

```toml
[accounts."codebuddy-tongxue3"]
models = ["claude-*"]

[[codebuddy-tongxue3.limit]]
period = "day"
tokens = 1000000
```

```
pool.limits.load_limits(p)        -> {'accounts': {'codebuddy-tongxue3': {'models': ['claude-*']}},
                                      'codebuddy-tongxue3': {'limit': [{'period': 'day', 'tokens': 1000000}]}}    # 不抛
pool.limits_policy.load_limits(p) -> RAISED LimitError 账号 accounts 的段里有不认识的键：codebuddy-tongxue3（只认 limit）
```

- F34 那份 reader：`tools/wb_dispatch.py:451-483`，`:469` `table = pool_limits.load_limits(pool_limits.limits_path())`，`:470` `table.get("accounts")`，`:476` `section.get("models")` ⇒ **要求顶层有 `accounts` 表**；`:454` 注释逐字「★ 数据在**仓外** D:/repo/infra/pool/limits.toml（与 F33 共用同一份策略表）」。
- F33 那份 reader：`tools/pool/limits_policy.py:249-283` → `_rows()` `:226-246`；`:229-233` 段里除 `limit` 外的任何键 ⇒ `LimitError`；`:234-235` 段里没有 `limit` 数组 ⇒ `LimitError` ⇒ **要求顶层每一个键都是账号段**。
- ⇒ 今天**没有任何一份文件能同时喂饱两道闸**。这不是「数据还没写」，是**契约冲突**：写下去的每一行都会让其中一道闸拒派。

裁决候选（本卡必须择一并写进文档，不许两个都留）：

- **(a)** 账号段搬到 `[accounts."<id>"]` 下，两套键（`models` 与 `limit`）同居一段 ⇒ 改 `limits_policy._rows()` 的「只认 limit」白名单；`load_limits()` 的返回形状 `{账号: (Limit, ...)}` 不变，只改取数路径。
- **(b)** 顶层保留账号段、`accounts` 表只放 `models` ⇒ `_rows()` 显式跳过 `accounts` 键，**并在 docstring 与错误文案里点名它是 F34 的段**，否则下一个人会把它当成「未知键被静默忽略」。
- **(c)** 文件分两份（`limits.toml` + 模型白名单一份）⇒ 要改 `caller_model_patterns()` 的读取路径，属 A341 的域，**不推荐**（把一张卡变成两张卡的合并）。

### 缺口 3 · 「表坏了但我不知道这张卡有没有声明」今天读不出来

- `tools/pool/limits.py:18-21` 逐字：「★ 边界（如实写，**未核到**的部分明说）：`load_limits()` 读不出来一律回 `{}`（设计口径），于是「表坏了、但我不知道这张卡有没有声明」这一态**今天读不出来** ⋯ 要修得让 `load_limits()` 换成「保留声明位」的形态（F33 建数据文件时一并定）。记录在此，**不许当成已解决**。」
- `:78-92` `load_limits()` 的 `except (OSError, tomllib.TOMLDecodeError, ValueError): return {}` —— 空表 / 空文件 / 坏 TOML / 没权限 / 是目录**全都回 `{}`**（`:84` 注释逐字「★ 空表 / 空文件 / 坏 TOML / 没权限 / 是目录 ⇒ 全都回 `{}`（同一条「读不出来」）」）。
- `:109-132` `assert_serving()` 两个方向都判了：有声明且读不出 ⇒ `NotLimited`（`:121-132`），没声明 ⇒ 一律不抛（`:119`）。但它今天在生产里**零调用方**（`grep -rn "assert_serving\|has_requirement" tools/ scripts/` 只命中 `tools/pool/limits.py` 自身与 `tools/pool/failclosed.py:49` 的一行注释）。
- ⇒ 缺口 3 是「要不要在本卡把老 reader 换成保留声明位」的裁决项，**不能默默不动**。

### 缺口 4 · 「没数据 = 不限」今天由两处保证，新数据面不许破坏

- `tools/pool/limits_policy.py:262-263`：`if not target.exists(): return {}` —— **在解析之前**，文件不存在 ⇒ 空表（`:252-256` 判据 8 逐字：「文件不存在 ⇒ `{}`（= 没设限额 = 今天的行为；**不是**「无限」，也**不抛**）」）。
- `tools/pool/limits_check.py:94-101`：`if not limits: return Verdict(allowed=True, ..., why="没有声明任何限额 ⇒ 永不过问（budget.go:341）")`。
- 反方向必须保住：`tools/wb_dispatch.py:3600-3602` 逐字「**限额策略读不懂 ⇒ 拒派**（不许当成「没设限额」）」；`limits_policy.py:252-256` 后半「坏 TOML / 某条越界 / 某账号超过 MAX_LIMITS 条 ⇒ **抛 LimitError**（**不许跳过坏条目继续用剩下的**）」。

## 立卡人裁决（2026-11-19 立卡时定，实现者按此做；要推翻必须另开卡）

- **数据文件位址**：仓外 `D:/repo/infra/pool/limits.toml`（今天 `limits.limits_path()` 算出来的就是它，不改代码）。理由：`:44` 注释明写「与 `accounts.toml` 同目录」，`assert_serving()`/`limits_policy` 三处默认值都指向它；改仓内要同时改 `limits_path()` 第三段并证明 `pool_dir()` 为 None 时的回落，**收益只有「文件进 git」，代价是把两份 reader 的默认值再分叉一次**。
- **仓内交付面**：新增 tools/pool/limits.example.toml（计划建） —— 判据 4 的「体例」需要一个**可进 git、可被 `load_limits` 真读**的模板；它是**示例**（全注释 + 一条注释掉的样例），不是会被生产读到的那份。生产读那份在仓外，本卡不写任何真会拦人的限额。
- **形状裁决 = (b)**：顶层保留账号段（`[[<id>.limit]]` 形状不动，`tests/test_pool_limits.py` 的 40+ 条 pins 一字不改），`accounts` 表**只**放 `models`；`limits_policy._rows()` 显式跳过 `accounts` 键，**并在 docstring 与错误文案里点名它是 F34 的段**。
  为什么不是 (a)：`_rows()` 的白名单要放行 `models`，等于让「限额段里混着别的东西」变成正常态 —— 下一份坏文件就再也判不出来了（判据 5 的 pin_19 正是靠「多一个键就抛」守住的）。(b) 把两份数据放在两个**名字不同**的表里，谁是谁一眼可见，坏文件仍然会抛。
- **缺口 3（`assert_serving()` 要不要接）**：本卡**不接**，只在卡规格与 changelog 里点名它仍零生产调用方。理由：接它就得先裁决「它和 `wb_dispatch.py:3600-3602` 的『读不懂 ⇒ 拒派』谁在上位」，那是另一张卡的判据。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 数据文件位址唯一且被钉住

选定一个位址写进卡规格。候选：仓外 `D:/repo/infra/pool/limits.toml`（与 `accounts.toml` 同目录，符合 `limits.py:44` 的注释）；若选仓内，则**必须同时**改 `limits_path()` 的第三段，并证明 `pool_dir()` 返回 `None` 时能回落到仓内。

**怎么证明**：新增 tests/test_pool_limits_data.py（计划建）::test_limits_path_is_the_one_we_document —— 不设 env 时 `limits_path()` 的返回值**逐字等于**卡规格里写的那条路径；再加一条 `test_pool_dir_does_not_follow_cwd` 的对照（体例照抄 `tests/test_pool_callers.py:278-289`：换 cwd 后结果不变）。

### 判据 2 · 两份 reader 的顶层形状裁决（缺口 2）

择 (a)/(b)/(c) 之一写进卡规格；被改的那一侧必须附一句「为什么这样改不会松开判据」。

**怎么证明**：`test_both_readers_accept_one_file` —— 用**同一份**临时 limits.toml 依次调 `pool.limits.load_limits(p)` 与 `pool.limits_policy.load_limits(p)`，两边都必须成功且语义都对（前者取得到 `[accounts."<id>"].models`，后者取得到限额条目）。再加一条**反向**：把裁决前的旧形状写回临时文件，被改的那一侧必须抛或必须空 —— 钉住「不是靠放宽到什么都收」。若选 (b)，再加 `test_accounts_key_is_named_not_ignored`（`accounts` 键必须在 docstring 与错误文案里被点名）。

### 判据 3 · 「没数据 = 不限」与「坏数据 = 拒」两条同时成立（缺口 4）

**怎么证明**：三条钉子 —— ① `test_missing_file_is_empty_not_refuse`：文件不存在 ⇒ `limits_policy.load_limits()` 回 `{}`，且 `wb_dispatch` 限额闸零副作用（体例照 `tests/test_pool_limits_wiring.py:12` 判据 4「没有策略文件 ⇒ 工人拿到的 argv 与接线之前逐项一字不差」）；② `test_broken_file_refuses`：文件存在但坏 TOML ⇒ `LimitError`，且 `wb_dispatch.py:3600-3602` 那条拒派文案出现（体例照 `tests/test_pool_limits_wiring.py:296-306`）；③ `test_no_data_is_not_infinite`：断言「不存在 ⇒ 空表」，**不许**回一个「无上限」的哨兵值（体例照 `tests/test_pool_limits.py:353-358` 的 pin_18）。

### 判据 4 · 数据文件自身的体例（人写的表）

照 `tools/pool/rpm.toml` 的体例写：文件头写清「键用账本的**稳定 id**，不是 email / profile 名」「不在表里的号 = 没设限额」「`MAX_LIMITS = 5`（`limits_policy.py:56`）与 `MAX_DAYS`/`MAX_HOURS`（`:58`/`:60`）的边界」；正文可以是**空表**（像 `rpm.toml:18-22` 那样全是注释示例）。

**怎么证明**：`test_data_file_parses` —— 拿**真文件**跑 `limits_policy.load_limits()` 必须得 `{}` 或合法表（不许抛）；`limits.load_limits()` 同形。别钉文案（文案会漂），改为在回执里附 `python -X utf8 -c` 的实跑读数（体例照卡 A340 的回执）。

### 判据 5 · 坏条目不许被跳过（既有口径一条都不许放宽）

**怎么证明**：直接复用 `tests/test_pool_limits.py:361-379`（pin_19：一条坏的连带整份）与 `:401-411`（`MAX_LIMITS` 边界）—— **本卡一条都不许改**；若裁决动了 `_rows()`，跑一遍这两条必须仍绿（这就是「同判据同源」的对照）。

### 判据 6 · 反向变异 ≥3 条（每条真改真跑真复原，sha256 自证）

- M1：`limits_policy.load_limits()` 的 `if not target.exists(): return {}` 改成返回一条 `default` 限额 ⇒ 判据 3 的 ① 必须红。
- M2：裁决处把「不认识的键」从抛改成 `continue`（(b) 做错就是这样）⇒ 判据 2 的反向必须红。
- M3：`limits.py` 的 `load_limits()` 从「吞成 `{}`」改成「抛」⇒ `tests/test_pool_limits_wiring.py:310-334`（`test_only_the_policy_loader_is_consulted`）必须红 —— 这一条同时证明**两份 reader 没被合并**。
- 脚本落 `gates/diag/_rev_A367.py`（gitignored），末行必须是「结论：N/N 条全部咬住，收尾绿。」

## 交付

- 数据文件一份（位址按判据 1）。默认交付是**空表 + 注释示例**，不是一条真会拦人的限额。
- 若裁决动了 reader：`tools/pool/limits_policy.py`（**只动 `_rows()` / `load_limits()` 的取数路径，判据语义不动**）或 `tools/pool/limits.py`（仅当选 (a) 的保留声明位）。
- tests/test_pool_limits_data.py（计划建）（新）。
- `复盘/卡/卡A367-…….md`（本文件落地）+ docs/changelog.d/T-AG652.md（计划建）（写清「limits.toml 从今天起存在」与裁决结果）。

## 验收

```bash
cd .wt/A367
python -X utf8 -m pytest tests/test_pool_limits_data.py tests/test_pool_limits.py tests/test_pool_limits_wiring.py tests/test_pool_failclosed.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool/limits.py tools/pool/limits_policy.py tests/test_pool_limits_data.py
python -X utf8 gates/diag/_rev_A367.py      # 末行：「结论：N/N 条全部咬住，收尾绿。」
```

已知噪音：`tests/test_pool_failclosed.py:26` 明写「一律 `tmp_path`，不碰仓外那份 `infra/pool/limits.toml`」⇒ 本卡落地后那条纪律**仍然成立**：真文件路径不许出现在测试里，测试一律 `TF_POOL_LIMITS` 指临时文件。

## 不许做

- **不许**把 `tools/pool/limits.py` 与 `tools/pool/limits_policy.py` 合并 —— `tests/test_pool_limits_wiring.py:14` 判据 6 钉的正是「旧语义那份读同一份文件是 `{}`」。
- **不许**改 `tools/pool/limits_check.py`（判据层，卡 A338 的域）。
- **不许**为了让文件「看起来有用」而在主树默认数据文件里写一条真会拦人的限额。
- **不许**碰 `tools/pool/plan.py:46-53` 列出的六份 `PROTECTED_FILES`（`docs/traceability.toml` / `docs/changelog.md` / `复盘/交接-重构进度.md` / `复盘/新窗口交接卡.md` / `gates/last.json` / `gates/reuse.json`）。
- **不许**在卡域 `files` 里写通配（`plan.py:287-291`：`*` `?` `[` 一律拒单）。
- **不许**顺手改 `caller_model_patterns()` 的语义（属 A341 的域）；裁决 (a) 若必须动它，写进 `depends` 并在卡规格里说明。

## 与已完成卡的关系

- **A338**（限额判据层）：`limits_policy.py` / `ledger_spend.py` / `limits_check.py` / `tests/test_pool_limits.py`，done。本卡给它**喂数据**。
- **A350**（派活前限额闸）：`tools/wb_dispatch.py:3584-3629`，done。本卡不改它一个字节。
- **A341**（F34 模型白名单）：`tools/wb_dispatch.py:451-483`，done。与 F33 **共用同一份文件** ⇒ 裁决必须两边都认。
- **A344**（`rpm.toml` 的 id 解析三步）：本卡的数据文件**照抄**那套键口径，但**不重写**它。
- **A348**（`callers.py`）：三段路径 + 「文件不存在 ⇒ `{}`；文件在但读不懂 ⇒ 抛」的体例，`callers.py:12-15`/`:37-38`。本卡的数据面**照抄**这个体例。

## 未坐实项（草稿如实标注，别当成结论）

- **未坐实**：F33 原文（`D:/repo/program/_ext/_magpie_features.md:296-302`）里的 `budget.counts(r) = !r.IsRejected() && !r.IsReported() && r.Computer == ""`（拒绝的与外部自报的都不计数）在 pool 侧没有对应维 —— `tools/pool/ledger_spend.py:11-12` 只抄了 tokens 口径（`tokens = input + output + cache_write`，默认不含 `cache_read`）。本卡**不开这一支**，写在这里备查。
- **未坐实**：`assert_serving()` 今天零生产调用方。本卡要不要接、接在哪一步（它会不会与 `wb_dispatch.py:3600-3602` 的「读不懂 ⇒ 拒派」重叠）—— 若接，必须先说清谁是谁的上位。
- **未坐实**：若选裁决 (a)，`limits.load_limits()` 的返回形状会是 `{"accounts": {...}, 账号: 段}` 的混合体（实测今天已经是这样）。这个混合体是不是 F34 想要的，要在 A341 的规格里核一次（本文只核到 `:470` 的 `table.get("accounts")`）。
