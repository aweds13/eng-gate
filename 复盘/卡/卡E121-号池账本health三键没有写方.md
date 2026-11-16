# 卡 E121 · 号池账本 `[account.health]` 三键没有写方：state 永远是 unknown、连败停在 10 月、last_probe 落后额度 21 天

> 台账号 `T-AG630`｜分区 E（门禁与可信度）｜树 `.wt/E121`｜层 判据层｜基准 `c94b5e27`（落地人填：落地那一刻的主树 HEAD）｜depends E118
> 依据：卡 E118 落地时三片段（docs/changelog.d/T-AG628.md / docs/traceability.d/T-AG628.toml / 复盘/交接.d/T-AG628.md）里如实记下的缺口第 1 条 —— 「`health.state` 本身没有写方……要真把「连败 1 次」降回 0，得让 `record_probe_result`（成功那一支）也写 `[account.health].state`，那是另一张卡」。**不引** `gates/diag/_sect/gaps.txt`：那份是落地闸的缺口（`tools/pool/landing.py:315-323` / `:346-356` / `:2798-2799`），与 health 无关。
> 行号基准：2026-11-17 主树 `1398e089`（chore(ledger): 立卡 E122）现场逐条复核；`git diff --stat 89cd4deb 1398e089 -- <v1 引用的 14 个文件>` 空输出 rc=0 ⇒ v1 的行号在这棵树上仍有效，漂移仅三处，已在本卡修正。
> ★ E118 **尚未落地**：分支 `card/E118` HEAD `be3f3448`（主树 HEAD 的祖先），改动仍在 `.wt/E118` 未提交（`tools/pool_accounts.py` / `tools/pool_mcp.py` / `tests/test_pool_accounts.py` / `docs/INDEX.md` / `docs/subsystems/pool/模型与号池.md` + 三片段）。E118 落地后本卡 rebase 并按现场重核行号。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · `health.state` 全仓零写方，五个号全是手写的 "unknown"

写方只可能是「对 `health` 的赋值」或「`setdefault("health")`」。两条 grep 都只有 `tools/pool_accounts.py`：

```bash
grep -rn 'health' tools/ --include=*.py | grep -E 'health\[[^]]+\] *='
#   6 行，全在 tools/pool_accounts.py：
#   :525 health["revoked"] / :526 health["revoked_at"] / :1475 last_probe
#   :1482 last_checkin / :1484 与 :1486 consecutive_failures
grep -rn 'setdefault(.health...)' tools/ scripts/     # 只有 :524 与 :1473 两处
grep -rn 'health' scripts/                            # rc=1（0 处）
grep -rn 'health' tools/wb_dispatch.py                # rc=1（全文件 0 处）
```

⇒ **`health.state` 一条赋值都没有**。`health` 这个字在别处也出现，但都不是账本：`tools/pool_mcp.py` 6 处全是**读**（`:1597-1610` 人话行、`:1710-1717` 读 `last_probe`/`last_checkin`），`tools/route_ui_gap.py:2` / `tools/serve.py:9` / `tools/web_live_check.py:6` 是**网页健康检查**，与号池无关。

`record_probe_result`（`tools/pool_accounts.py:1111-1175`）**全函数从不触碰 `acc["health"]`**，它只写 `[account.quota]`：

- `:1114-1129` docstring —— 只承诺 `observed_at` / `samples` / `used_percent`
- `:1155` `    touched = False`
- `:1162` `        quota = acc.setdefault("quota", {})`
- `:1165` `        quota["observed_at"] = stamp`
- `:1166` `        quota.setdefault("samples", []).append({"at": stamp, "kind": row["kind"]})`
- `:1168-1169` `used_percent` 只对带该键的 `ok` 行写
- `:1170` `        touched = True`；`:1172` `note_quota_history(...)`；`:1174-1175` `if touched: save_ledger(...)`

全仓唯一写 `health` 的两处：`saved_refresh_failed()` `:501-529`（只写 `revoked` / `revoked_at`）与 `_record_checkin()` `:1471-1498`（写 `last_probe` / `last_checkin` / `consecutive_failures`）。`tools/pool/gateway.py:589` 明说「也不去写账本的 health —— 写账本是别的模块的事」，`tools/wb_dispatch.py` 全文件 0 处 `health`（只 `load_ledger`，无 `save_ledger`）。

### 问题 2 · 真账本读数：state 五个 unknown，连败停在 10 月，额度却是 11 月

```bash
python -X utf8 -c "import sys;sys.path.insert(0,'tools');import pool_accounts as pa;d=pa.load_ledger(pa.find_ledger());..."
```

（只读，未写账本、未跑 probe、未联网；ledger = D:/repo\infra\pool\accounts.toml，rc=0）

```text
codearts-1          {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}    | 顶层 state=active
codebuddy-tongxue3  {"state": "unknown", "consecutive_failures": 0, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "not-supported"} | 顶层 state=active
workbuddy-1         {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}    | 顶层 state=active
trae-1              {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}    | 顶层 state=active
meoo-1              {"state": "unknown", "consecutive_failures": 0, "last_probe": "", "last_checkin": "not-supported"}                         | 顶层 state=active
```

同一份账本里 `quota.observed_at` 是 **2026-11-16T12:57:30+08:00**（codebuddy 为 13:00:08）。⇒ 探测确实在 11 月 16 日跑过、真的落盘了，而 `health` 全部停在 10 月 25 日 —— 这就是「问题 1」的现场形态。

`python -X utf8 tools/pool_accounts.py list --json`（rc=0，只读）：八键 `id/platform/platform_known/label/state/quota/models/credential`，`quota` 是「未观测（…）」文本串，**没有 `health` 键** ⇒ 读面不背这个锅（读面归 E118）。

### 问题 3 · `consecutive_failures` 与 `last_probe` 的写方只有一个：签到

`tools/pool_accounts.py:1471-1498` `_record_checkin()`：

- `:1472` docstring「回写账本：健康态 + 额度样本。**不碰 amount**（amount 是余额，不是本次发放）。」
- `:1473` `    health = acc.setdefault("health", {})`
- `:1474` `    previous = health.get("last_checkin")`
- `:1475` `    health["last_probe"] = stamp`  ← **last_probe 唯一写方**
- `:1476-1479` 注释：`--probe` 只探不领，留档 JSON 与 `last_probe` 是它许写的全部
- `:1480-1481` `    if not apply: return` ← 只读探针在这里早退
- `:1482` `    health["last_checkin"] = row["kind"]`
- `:1483-1487` `    if row["kind"] in ("uncertain", "failed"):` ⇒ +1，否则归零 ← **consecutive_failures 唯一写方**

⇒ 探测路径一次都不写 `health`，而 `last_probe` 却在签到路径上被写。**`last_probe` 这个名字今天记的是「最后一次签到/探测的时刻」，不是「最后一次探测的时刻」** —— 名字与语义已经分叉。

### 问题 4 · `:1529` 那句注释是空头支票

`recheck_rows` docstring `:1529`：「时刻取同一行 `health["last_probe"]`（签到与探测都在那一刻写它）」。后半句是假的：独立 probe 不写 `last_probe`（`record_probe_result` 不碰 health），只有经过 `--probe` 的签到才顺带写。改写这条注释之前，得先把「谁写」变成事实。

### 问题 5 · `health.state` 零校验，而且**校验器根本不在写路径上**

- `tools/pool_accounts.py:65` `STATES = ("active", "limited", "exhausted", "expired", "disabled")` —— 只约束**顶层** `[[account]].state`
- `:167` `def _check_account(...)`，`:197-198` `if acc["state"] not in STATES: raise LedgerError` —— 只校验顶层，**`[account.health].state` 一个字都不看**
- 写路径上连 `_check_account` 都不跑：`:327` `save_ledger()` ⇒ `:348` `payload = _dump_toml(data)` ⇒ `:351` `_lastgood().write_atomic(path, payload, validate=_validate_ledger_toml)`
- `:1389-1391` `def _validate_ledger_toml(text: str) -> None:` docstring「判「这份账本还能不能当 lastgood」：TOML 解得开就算（卡 A330）」，函数体只有一行 `    tomllib.loads(text)`

⇒ 写一个 `state = "healthy"` 能顺利落盘，连 `.bak` 都会认它是合法 lastgood。**校验必须加在 `_validate_ledger_toml`，加在 `_check_account` 挡不住写**（后者只在 `load_ledger` `:298` 被调用）。

### 问题 6 · v2 新增：判据 3 会撞 `due` 判据（v1 漏了）

`recheck_rows` `:1546-1558`：`last_checkin` 是结论码时，`:1554` `                at = _stamp_or_none(health.get("last_probe"))` 取 **`last_probe`** 当那一刻。若 `record_probe_result` 开始写 `last_probe`，一个下午 probe 过的号，其「上午签过（claimed）」会被算成「刚问过」⇒ `tools/pool/checkin.py:166-195` `due_for_recheck` 的 ⑥/⑦ 分支（`RECHECK_EVERY_S = 30 * 60` `:69`、`RETRY_AFTER_S = 30 * 60` `:71`）给出 `(False, "当日已定案")` —— **正好是 `:1476-1479` 注释要防的那件事的另一种形态**。

定夺（本卡执行）：`last_probe` 回它字面语义（最后一次**探测**时刻），**另开 `health["last_checkin_at"]`** 记签到时刻，`recheck_rows` 取结论码时刻时**优先 `last_checkin_at`、缺失才回落 `last_probe`**（老账本兼容）。


## 判据（每条带钉子名，钉子落在 tests/）

### 判据 1 · `derive_health_state` 是一张显式表，不是 if 链

新增纯函数（不读不写账本、不读钟）：`def derive_health_state(kind: str | None) -> str | None:`

| 输入 `kind` | 返回 |
|---|---|
| `ok` | `ok` |
| `failed` | `auth-expired` |
| `uncertain` / `skipped` / `not-supported` / `unknown-platform` / `None` | `None`（**不编 state**） |

**钉子** `test_derive_health_state_is_a_table`：六种结论码 + `None` 逐条断言；再断言返回值要么是 `None`、要么落在卡 E45 的五值枚举 `{"ok","degraded","quota-exhausted","auth-expired","unknown"}` 里（`复盘/卡/卡E45-账号账本与只读探测.md:74-78`）。

### 判据 2 · 只有一个写点：`_apply_probe_health(acc, kind, stamp)`

`def _apply_probe_health(acc: dict, kind: str | None, stamp: str) -> bool:` —— 逐键写，**不许整块替换** `acc["health"]`（会冲掉 `revoked` / `revoked_at`，`tests/test_renew_lock.py:192-193`）：

```python
    state = derive_health_state(kind)
    if state is None:
        return False
    health = acc.setdefault("health", {})
    health["state"] = state
    health["last_probe"] = stamp
    if kind in _ck().NEEDS_HUMAN:
        health["consecutive_failures"] = int(health.get("consecutive_failures", 0) or 0) + 1
    else:
        health["consecutive_failures"] = 0
    return True
```

接入点：`record_probe_result` 的写循环 `:1156-1170`，在 `:1166` `        quota.setdefault("samples", []).append({"at": stamp, "kind": row["kind"]})` 之后调它，并与 `:1170` `        touched = True` 同一支（`:1174-1175` 仍按 `touched` 决定落盘，不另写 `save_ledger`）。`:1114-1129` docstring 必须同步改成事实。

**钉子** `test_probe_writes_health_through_the_single_writer`：fixture 里 `state` / `last_probe` / `consecutive_failures` 是旧值，跑 `record_probe_result(..., now=<固定时刻>)` 后断言三键都被写、且 `revoked` 与 `quota.amount` 一字不动。

### 判据 3 · `last_probe` 回字面语义 + 新增 `last_checkin_at`：**下午 probe 不许把上午签到判成刚签过**

三处一起改，缺一条这条判据不算过：

1. `record_probe_result` 经判据 2 写 `health["last_probe"] = stamp`（探测时刻）；
2. `_record_checkin` 的 `:1475` `    health["last_probe"] = stamp` **保持原样不动**（不改签到既有语义）；在其后、且**在 `:1480-1481` `    if not apply: return` 之后**（与 `:1482` `    health["last_checkin"] = row["kind"]` 同一支）另写 `    health["last_checkin_at"] = stamp`。理由同 `:1476-1479`：`--probe` 不许让账本看起来像「今天签过」，所以 `last_checkin_at` 不进早退之前；
3. `recheck_rows` `:1546-1558`：`        health = acc.get("health") or {}` 之后，`at` 优先取 `health.get("last_checkin_at")`，**缺失才回落** `health.get("last_probe")`；`:1523-1535` docstring 一起改写成新口径，写明「为什么不能拿 `last_probe` 当签到时刻（下午探一次会把上午的签到判成刚签过 ⇒ 当日已定案）」。

**钉子** `test_probe_does_not_forge_todays_checkin`（**正面证明**，不是「不崩就行」）：
- fixture：`last_checkin = "claimed"`、`last_checkin_at = "2026-10-26T09:00:00+08:00"`、`last_probe = "2026-10-25T18:30:46+08:00"`；
- 跑 `record_probe_result(..., now=<同日 15:00>)`（`kind="skipped"` 一次；再 `kind="ok"` 一次）；
- 断言 `health["last_probe"]` 变成 15:00，而 `health["last_checkin_at"]` **仍是 09:00**；
- 再跑 `recheck_rows(data, platforms, now=<同日 15:05>)` ⇒ 该号**不在返回行里**（`due_for_recheck` 仍判「当日已定案」）；
- 反向：把 `last_checkin_at` 删掉、只留 `last_probe=15:00`，再跑一次 ⇒ 断言这里走的是**回落**分支（`at` 等于 15:00），把兼容分支也钉住。

**钉子** `test_recheck_prefers_last_checkin_at`：同一 `now` 下喂两份账本（有 / 无 `last_checkin_at`），断言两者结论**不同**，且只有「有 `last_checkin_at`"那份是「当日已定案」。

### 判据 4 · 连败口径只许一套：用 `tools/pool/checkin.py` 的 `NEEDS_HUMAN`

今天 `tools/pool_accounts.py:1483` 是字面量 `    if row["kind"] in ("uncertain", "failed"):`，而真源在 `tools/pool/checkin.py:47` `NEEDS_HUMAN: frozenset[str] = frozenset({UNCERTAIN, FAILED})`（结论码定义 `:37-44`）。两套词表已经在漂。

本卡定夺：`_record_checkin` `:1483` 与 `_apply_probe_health` **都**用 `_ck().NEEDS_HUMAN`（`_ck()` 见 `:1394`），全仓只剩这一处口径；「哪些码算失败」不许在 `tools/pool_accounts.py` 里再写字面量。

**钉子** `test_failure_policy_is_single`：同一个 `kind`（`uncertain` / `failed` / `skipped` / `ok`）分别走 `run_checkin(apply=True)` 与 `record_probe_result`，断言两条路得到的 `(health["state"], health["consecutive_failures"])` **完全一致**。

★ 口径不变：`uncertain ∈ NEEDS_HUMAN` ⇒ `tests/test_pool_checkin.py:711` `assert acc["health"]["consecutive_failures"] == 2` **不用改**；本判据删掉的是第二份**字面量**，不是改判定。

### 判据 5 · 写路径上校验 `health.state` 枚举；只读面一个字节不改

(a) `tools/pool_accounts.py:1389-1391` `_validate_ledger_toml` 在 `    tomllib.loads(text)` 之后加校验：遍历 `[[account]]`，若 `health.state` 存在且不在 `HEALTH_STATES = frozenset({"ok","degraded","quota-exhausted","auth-expired","unknown"})` ⇒ `raise LedgerError`（点名账号 id 与坏值）。新常量紧跟 `:64-65` 的 `SAMPLES_CAP` / `STATES`。因为 `:351` `write_atomic(..., validate=_validate_ledger_toml)` 与 `:287` `read_strict(..., validate=...)` 都走它，写侧读侧**同时**收口。

(b) 本卡**不改**只读面：`list_rows`（`:711-730`）、`_quota_text`（`:702-708`）、`_print_table`（`:1235`）、`account_status`（`:1290`）、`tools/pool_mcp.py` 人话行（`:1597-1610`，尾注 `:1607`）。**绝不把 `health_state` / `consecutive_failures` 加进 `list_rows`** —— E118 已占那几个键位（`.wt/E118` 的 `tools/pool_accounts.py:767-770`）。

**钉子** `test_health_state_is_validated_on_write`：fixture 里把某号写成 `state = "healthy"`，调 `save_ledger` ⇒ 抛 `LedgerError`，且**盘上文件字节不变**（写前后 `read_bytes()` 相同）。**钉子** `test_read_surface_keys_unchanged`：`list_rows` 返回的键集与本卡落地前逐字相同（八键写死在断言里），写后读亦同。

### 判据 6 · 反向变异 ≥4（真改、真跑、真还原，记 sha256）

- A：`derive_health_state` 的 `uncertain` 支改成返回 `degraded` ⇒ 判据 1 必红；
- B：删 `failed` 支的连败 +1（只写 state）⇒ 判据 2 / 判据 4 必红；
- C：把 `record_probe_result` 里对 `_apply_probe_health` 的调用注释掉 ⇒ 判据 2 / 判据 3 必红；
- D：把 `state` 写成 `healthy` ⇒ 判据 5(a) 必红（写路径挡住）；
- E：`recheck_rows` 的 `at` 改回只读 `last_probe` ⇒ 判据 3 的 `test_probe_does_not_forge_todays_checkin` 必红；
- F（安静对照）：只改一句注释 ⇒ 全绿。

记录落 `gates/diag/_rev_E121_result.txt`（gitignored）；脚本放**主树** `gates/diag/`（`ROOT = __file__.parent.parent.parent`）。


## 交付

1. `tools/pool_accounts.py`：
   - 新增 `HEALTH_STATES`（紧跟 `:64-65`）、`derive_health_state()`、`_apply_probe_health()`（放 `:1111` `record_probe_result` 之前）
   - `record_probe_result` 写循环 `:1156-1170` 接入；`:1114-1129` docstring 改成事实（写 `state` / `consecutive_failures` / `last_probe`；`last_checkin` / `last_checkin_at` 仍只由签到写）
   - `_record_checkin`：`:1482` 之后加 `    health["last_checkin_at"] = stamp`（在 `:1480-1481` 早退之后）；`:1483` 字面量改 `_ck().NEEDS_HUMAN`
   - `recheck_rows`：`:1546-1558` 的 `at` 改为优先 `last_checkin_at`、回落 `last_probe`；`:1523-1535` docstring 重写
   - `_validate_ledger_toml` `:1389-1391` 加 `health.state` 枚举校验
2. `tests/test_pool_accounts.py`：新增 `test_derive_health_state_is_a_table` / `test_probe_writes_health_through_the_single_writer` / `test_probe_does_not_forge_todays_checkin` / `test_recheck_prefers_last_checkin_at` / `test_failure_policy_is_single` / `test_health_state_is_validated_on_write` / `test_read_surface_keys_unchanged`；并把 `:711` `test_record_probe_result_only_touches_observed_at_and_samples` 的**名字与 docstring** 改成事实（断言本体 `:742-759` 一条不动 —— 它只查顶层 `state` / `approved_models` / `amount` / `quota`，加写方不会让它红，但名字会变成第二句谎）。
3. `tests/test_pool_checkin.py`：`:613` `test_probe_mode_never_touches_the_verdict_bits` 的四条断言（`:665` `last_probe` 刷新 / `:667` `last_checkin=="uncertain"` / `:668` `consecutive_failures == 3` / `:669` samples 空）**必须仍绿**；另补一条「`--probe` 不写 `last_checkin_at`"的断言（本卡新增，防把新键写进早退之前）。
4. `docs/subsystems/pool/模型与号池.md`：**新增一节**「`[account.health]` 六个键谁写」（全文 97 行今天只有 `:84` 一处提 health，是新增不是改段）：`state` ← 探测（`derive_health_state` 表）、`consecutive_failures` ← 探测与签到（`NEEDS_HUMAN` 口径）、`last_probe` ← 探测与签到、`last_checkin` / `last_checkin_at` ← 签到、`revoked` / `revoked_at` ← `saved_refresh_failed`；并写清「`recheck_rows` 优先 `last_checkin_at`"的理由。
5. 三片段 docs/changelog.d/T-AG630.md / docs/traceability.d/T-AG630.toml / 复盘/交接.d/T-AG630.md（落地链按台账号生成；**不许手改** `docs/INDEX.md`，要跑生成器）。
6. 证据行：落地前把 `python -X utf8 -c "…load_ledger…"` 的五号 health 原文（改前 / 改后对比，**改后必须是 `tmp_path` fixture 读数，不许动仓外真账本**）与 `pytest -k health` 子集数贴进台账 `evidence`。

## 验收命令（落地前自跑）

```bash
python -X utf8 tools/cmd_guard.py --cmd '<下面任意一条>'      # 本仓强制预检
python -X utf8 -m pytest tests/test_pool_accounts.py tests/test_pool_checkin.py tests/test_pool_due.py \
    tests/test_renew_lock.py tests/test_pool_quota_history.py tests/test_pool_mcp_task.py \
    -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool_accounts.py tests/test_pool_accounts.py tests/test_pool_checkin.py
python -X utf8 scripts/check_derived_docs.py --check
```

- 第 4 条**今天实跑 rc=0**：「`docs/subsystems/pool/README.md` 与现算一致（50 个文件 / 19821 行 / 2026-11-17）」「`docs/INDEX.md`（421 篇）」。
- **不列** E118 的两条钉子（`test_list_json_carries_probe_verdict` / `test_health_state_is_never_invented`）：主树 grep -rn 'health_state' tests/ tools/pool_accounts.py ⇒ rc=1 零命中，它们只在 `.wt/E118/tests/test_pool_accounts.py:1092` 与 `:1117`，**本卡在主树跑不了**（判据 5 的「E118 归属」写进卡规格：E118 落地后才存在）。
- E118 落地后：本卡 rebase，由落地人复跑 `python -X utf8 -m pytest tests/test_pool_accounts.py -o addopts= -q --no-cov` **全绿**（含 E118 那两条，不许改），读数贴进台账。
- `depends E118` 保持不变。

## 不许做

- **不许跑 probe、不许联网、不许写仓外账本**：D:/repo\infra\pool\accounts.toml 一个字节都不动；所有钉子只用 `tmp_path` fixture（`save_ledger` 见 `:327-351`）。
- 不许改**顶层** `[[account]].state`（人判定的五值，`:65` 与 `:1117-1118`）；本卡只碰 `[account.health]`。
- 不许给 `skipped` / `not-supported` / `unknown-platform` / 缺 `kind` 编任何 state，也不许把 `uncertain` 写成 `degraded`。
- 不许新增 state 枚举值（卡 E45 五值 `ok|degraded|quota-exhausted|auth-expired|unknown`）；要加值必须同卡改 `HEALTH_STATES` 与文档三处。
- 不许整块替换 `acc["health"]`（会冲掉 `revoked` / `revoked_at`，`tests/test_renew_lock.py:192-193`）。
- 不许删 `_record_checkin` 的 `apply=False` 早退（`:1480-1481`），也不许让 `--probe` 写上 `last_checkin` 或 `last_checkin_at`（`:1476-1479` 的理由）。
- **不许在本卡把 `health_state` / `consecutive_failures` 加进 `list_rows` / `_print_table` / `account_status` / `tool_account_status`** —— E118 已占那几个键位（`.wt/E118` `:767-770`），本卡一字不改读面。
- 不许在 `tools/pool_accounts.py` 写「哪些结论码算失败」的第二份字面量（只用 `tools/pool/checkin.py:47` `NEEDS_HUMAN`）。
- 不许靠改测试让门变绿：`tests/test_pool_accounts.py:796` 的 quota 键集、`:258` 的凭据不外泄（`test_list_redacts_token_like_locator` 在 `:254`）、`tests/test_pool_checkin.py:613` 的 apply=False 四条（`:665/:667/:668/:669`）、`tests/test_pool_quota_history.py:290` `test_real_ledger_produces_no_curve_today` 的「一个点都画不出」，都得原样留着。
- 不许动 `docs/doc-debt-baseline.toml` 的任何计数；不许手改 `docs/INDEX.md`。
- v1 的两处按键错误本卡**已删**：列宽常量「48→64」在主树不成立（`:1239` 今天就是 `min(48, ...)`，64 只在 `.wt/E118` `:1283` `_COL_MAX = 64`）；门禁锁不许再引 `gates-9072.lock`（那把它已不存在）—— 落地时**按现场重核**：`ls gates/diag/*.lock` 后把 `cat` 到的 `card` / `pid` / `at` 原样写进卡。
