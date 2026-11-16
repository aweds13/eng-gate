# 卡 E118 · account_status 把「探过但没探到」洗成「未观测」—— 今天五个号全在撒谎

> 台账号 `T-AG628`｜分区 E（门禁与可信度）｜树 `.wt/E118`｜层 判据层｜基准 `71764d16`（立卡时主树 HEAD）｜depends 无
> 依据：用户 m00001「号池只读面撒谎体检第 8 条：account_status 把『探过但没探到』洗成『未观测』」；
> 行号已按 2026-11-16 20:40 现场（主树 `b306ba1c`）逐条复核 —— 旧草稿里的 `tools/pool_mcp.py` 行号来自基线 `27780739`，一律 +77 后才对。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · 五个号额度列全印「未观测」，可账本里每一次都探过、都留了结论码

真账本在仓外（`D:/repo/infra/pool/accounts.toml`，3457 B / CRLF 128 / bareLF 0 / mtime 2026-11-16T15:45:04），本卡只读它，不动。

```text
$ python -X utf8 -c "import sys,json; sys.path.insert(0,'tools'); import pool_accounts as pa; d=pa.load_ledger(pa.find_ledger()); ..."
codearts-1 {"amount": null, "unit": "credits", "observed_at": "2026-11-16T12:57:30+08:00", "last_sample": {"at": "2026-11-16T12:57:30+08:00", "kind": "skipped"}, "nsamples": 3, "health": {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}}
codebuddy-tongxue3 {"amount": null, "unit": "unknown", "observed_at": "2026-11-16T13:00:08+08:00", "last_sample": {"at": "2026-11-16T13:00:08+08:00", "kind": "uncertain"}, "nsamples": 4, "health": {"state": "unknown", "consecutive_failures": 0, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "not-supported"}}
workbuddy-1 {"amount": null, "unit": "点", "observed_at": "2026-11-16T12:57:30+08:00", "last_sample": {"at": "2026-11-16T12:57:30+08:00", "kind": "skipped"}, "nsamples": 3, "health": {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}}
trae-1 {"amount": null, "unit": "credits", "observed_at": "2026-11-16T12:57:30+08:00", "last_sample": {"at": "2026-11-16T12:57:30+08:00", "kind": "skipped"}, "nsamples": 3, "health": {"state": "unknown", "consecutive_failures": 1, "last_probe": "2026-10-25T18:30:46+08:00", "last_checkin": "uncertain"}}
meoo-1 {"amount": null, "unit": "积分", "observed_at": "2026-11-16T12:57:30+08:00", "last_sample": {"at": "2026-11-16T12:57:30+08:00", "kind": "skipped"}, "nsamples": 3, "health": {"state": "unknown", "consecutive_failures": 0, "last_probe": "", "last_checkin": "not-supported"}}
```

同一刻 `python -X utf8 tools/pool_accounts.py list`（rc=0）把五条全印成同一个词，差别只剩括号里的时刻：

```text
codearts-1          codearts   active  未观测（2026-11-16T12:57:30+08:00）  ~/.codeartsdoer/pool.env
codebuddy-tongxue3  codebuddy  active  未观测（2026-11-16T13:00:08+08:00）  ~/codebuddy-accounts/tongxue3
meoo-1              meoo       active  未观测（2026-11-16T12:57:30+08:00）  ~/.meoo/credentials.json
trae-1              trae       active  未观测（2026-11-16T12:57:30+08:00）  ~/.trae
workbuddy-1         workbuddy  active  未观测（2026-11-16T12:57:30+08:00）  ~/.workbuddy
```

机器面同一件事：`pool_mcp.tool_account_status({})` 的每行也是 `额度 未观测（<时刻>）`，五条 quota 字符串**长度全是 30 字符**、模板相同。

### 问题 2 · 判词只看 amount，不看 samples 末条的 kind

`tools/pool_accounts.py:702-708`：

```text
def _quota_text(acc: dict) -> str:
    quota = acc.get("quota") or {}
    amount = quota.get("amount")
    observed = quota.get("observed_at") or ""
    if amount is None:
        return "未观测" + (f"（{observed}）" if observed else "")
    return f"{amount} {quota.get('unit', '')}".strip() + (f"（{observed}）" if observed else "")
```

⇒ 只要 amount 缺，samples 末条是 skipped / uncertain / failed / not-supported 一律走同一支。而 amount 是余额口径、由探针之外的人填（`tools/pool_accounts.py:1120` 逐字：「★ 不写 `amount`：探测读到多少就写在 `samples` 里；`amount` 是余额口径，由探针之外的人/流程填。」），四个非 ok 结论码**本来就不写 amount**（`tools/pool_accounts.py:1122`-`1126`）⇒「探过、没探到」在读数上永远等于「从没探过」。

### 问题 3 · 机器块也不带结论码，机器同样分不出四种

`tools/pool_accounts.py:716-727` 每行只交 8 个键：id / platform / platform_known / label / state / quota（已经洗成人话的字符串）/ models / credential —— **不带** samples、health、last_probe。
消费方 `tools/pool_mcp.py:1601-1604`（关键行 :1603 `f" · 额度 {row['quota']} · 批准 {models}"`）直接拼 row['quota']，`tools/pool_mcp.py:1608-1610`（关键行 :1609）把 rows 原样塞进 payload ⇒ 人与机器看到的是同一个被洗过的词，机器没有第二次机会。
实测：`tool_account_status` 顶层键只有 `['accounts','found','ledger']`，每行 8 键 `['credential','id','label','models','platform','platform_known','quota','state']` —— `health` 的四个字段一个都没进 payload。

### 问题 4 · 这条面上 health.state 与 consecutive_failures 被整个吞掉

真账本五条 health.state 全是 unknown，consecutive_failures 依次 1 / 0 / 1 / 1 / 0（读数见问题 1）；list 与 account_status 的判词里一个字都没有 ⇒「连探失败 1 次的号」与「好好的号」读数长得一模一样，而这两件事在派活决策上完全不是一回事。
★ 范围要写准：`tool_checkin_status`（`tools/pool_mcp.py:1705-1714`）已在念 `last_checkin` / `last_probe`，`pool_accounts cmd_show`（`tools/pool_accounts.py:1290` `"health": acc.get("health", {}),`）也交原值 —— 本卡缺的是 **list_rows 那条路**，不是「整个仓库都没有」。

## 兼容面（改了会碰到谁 —— grep 出来的，不是猜的）

- `grep -rn '未观测' tests/ --include='*.py'` ⇒ 只有 4 条 docstring（`tests/test_pool_accounts.py:604` / `:638` / `:765` / `:801`），**没有一条把这个词断言进输出** ⇒ 改判词不踩既有断言；反过来也说明这条谎从来没人钉过。
- `tests/test_pool_accounts.py:647-663` test_list_json_is_sorted_and_shaped：`:654-663` 断言 `set(rows[0]) >= {` 八个既有键，`:652-653` 断言排序键 (platform, id) ⇒ 机器块只许加键，不许改名、不许删键、不许改排序。★ 全仓 tests/ **没有** `set(rows[0]) ==` 那种精确键集断言（grep 零命中）⇒ 加四键安全。
- `tests/test_pool_accounts.py:566-576` test_save_caps_samples_and_is_atomic：那是**非法形状**样本（`{observed_at, amount}`，没有 kind），只为测截断 ⇒ 读 samples 末条 kind 必须容忍缺键（不许 KeyError、不许凭空编一个结论码），但它不是「合法样本形状」的样板。
- 合法样本形状两头：probe 路径 `tools/pool_accounts.py:1166` `quota.setdefault("samples", []).append({"at": stamp, "kind": row["kind"]})`（`tests/test_pool_accounts.py:746-750` 钉死）；签到路径 `tools/pool_accounts.py:1493-1497` 还会追加 `credit` / `was`（`tests/test_pool_checkin.py:720-725` 断言过）⇒ 判词只认 `kind` / `at` 两个键，多的键不管。
- `tests/test_pool_accounts.py:876-889` test_mcp_account_status_is_offline：断 `is_error is False` / `data["found"] is True` / accounts 非空 / 「账号账本」in text ⇒ 改人话行不许把这几条弄红。
- `tests/test_pool_accounts.py:258` `assert "sk-abcdefgh" not in json.dumps(rows, ensure_ascii=False)` ⇒ 新增的四个机器键不许带凭据（kind / at / health_state / 连败本来都不带）。
- `tests/test_pool_accounts.py:796` `assert set(quota2) == set(quota) | {"samples", "observed_at"}` ⇒ 不许往账本 `[account.quota]` 加键；本卡只加 **row dict** 的键。
- `tests/test_pool_accounts.py:588-590` list / show / discover 三命令都 `== pa.EXIT_OK`（`:586` 把 urlopen 打成炸弹）⇒ 新代码不许联网。
- `tests/test_pool_accounts.py:703` `assert "能力表里没有" in capsys.readouterr().out` ⇒ `tools/pool_accounts.py:1259` 那句示警文案不许改。
- `tools/pool_accounts.py:1235-1246` `_print_table`：`:1239` 把列宽封顶 48、`:1245` 按宽度硬截 ⇒ 新判词 `skipped @2026-11-16T12:57:30+08:00（连败 1；健康 unknown）` 实测 51 字符，uncertain 那条 53 字符；**最坏**是 `unknown-platform @<ISO>（连败 12；健康 unknown）` = 61 字符 ⇒ 上限要抬到 ≥64（62/63 会踩线）。`_print_table` 有 5 个调用点（`:1260` cmd_list / `:1321` cmd_discover / `:1346` cmd_probe / `:1633` cmd_checkin / `:1678` cmd_due）⇒ 抬上限会同时放宽这五张表；真账本现在 list 五列宽 id 18 / platform 9 / state 6 / quota 30 / credential 29，48 上限**现在没生效**。
- `tools/wb_dispatch.py:703-704` 的 docstring 明写「★ 为什么不用 `pool_accounts.list_rows()`：它把 `quota` 洗成人读的文本，拿不到 `used_percent` —— 而粘性的 `spent` 判据正要用它。」⇒ 派活面早已绕开这条读数，改判词不牵动派活；这条理由本身也不许改。
- `tools/pool/gateway.py:363-368` `_ledger_rows` 交的是 `data["account"]` 原始 dict，它**不消费 list_rows**（`:392` 读的 `_platform_known` 是 `_check_account` 打在原始 dict 上的读侧字段）⇒ 新键不落账本的真机制是「`list_rows` 的输出从不回写」，与 gateway 无关，也与 `_dump_toml` 的 `_` 前缀过滤无关。
- 派生文档：`tools/pool_accounts.py` 在 `tools/pool/` **之外**，`scripts/gen_pool_readme.py:65` `POOL_REL = "tools/pool"`、`:102-109` 只扫那一个目录的 py+toml ⇒ 改本文件**不改** README 任何一行（`gen_pool_readme.py --check` 实测 rc=0）。`docs/INDEX.md` 会因本卡新增的卡规格 / 片段变篇数，由落地链 ③.5 / ⑤′ 吸收，卡里**不写死篇数与行数**。

## 判据

### 判据 1 · 「未观测」只留给账本里从没探过的号

`_quota_text` 分三支：amount 有值 ⇒ 原样；amount 缺且没有 samples（缺键或空表）⇒ 「未观测」；amount 缺但有 samples ⇒ 按末条出判词。

**钉子**（`tests/test_pool_accounts.py`）新增 `test_unobserved_means_never_probed`，三条断言：

- 没有 samples 的号（fixture 里的 wb-1）判词**恰好等于**「未观测」，且没有 observed_at 时不许凭空补一对括号；
- 有 amount 的号（codearts-1）判词不进这一支（判据 4 单独逐字钉）；
- samples 末条**缺 kind 键**（照 test_save_caps_samples_and_is_atomic 的形状造一条）⇒ 不抛异常，且判词里**不含**六个结论码中的任何一个（ok / skipped / uncertain / failed / not-supported / unknown-platform）—— 缺键只许说缺键，不许编。

### 判据 2 · 探过但没探到的，判词必须说出最近一次的结论码与时刻

**钉子** 新增 `test_probe_kind_is_named_not_washed`：

- 造 skipped / uncertain / failed / not-supported 四条 fixture，逐条断言 `row["quota"]` 以该 kind 打头、含末条 at 的 ISO 时刻、含「连败 N」（N 取 health.consecutive_failures 原值）；
- 断言这四条判词**两两不相等**（四种不许洗成一句）；
- 把今日五号的形状复刻成 fixture（skipped ×3 + uncertain ×1、health.state 全 unknown、amount 全缺）跑 `pa.main(["list", "--json"])`，断言 accounts 里**没有一条** `quota` 以「未观测」开头 —— 这一条直接钉住今天这条谎。

### 判据 3 · 机器块能分开四种，且只加键不改键

`list_rows` 每行新增四个机器键：`quota_kind` / `quota_at` / `health_state` / `consecutive_failures`，全部取账本原值；缺键就是 None，**不许**补 "" / "ok" / 0。

**钉子** 新增 `test_list_json_carries_probe_verdict`：rows[0] 的键集仍包含 `tests/test_pool_accounts.py:654-663` 那 8 个（既有的那条测试不许改红），新增四键的值分别等于 samples 末条 kind、samples 末条 at、health.state、health.consecutive_failures；排序仍满足 `keys == sorted(keys)`。

### 判据 4 · amount 有值时一个字都不变；health.state 未知不许编成 ok；cli 不许把判词截成半截

**钉子** 三条：

- `test_quota_text_unchanged_when_amount_present`：fixture 里 codearts-1 的判词**逐字**等于 `12 credits（2026-10-25T09:00:00+08:00）`（含全角括号，一个字符都不许动）；
- `test_health_state_is_never_invented`：health.state 缺键的号，机器块里 `health_state is None`，判词里不出现「健康 ok」这种编出来的好话；
- `test_cli_list_does_not_truncate_verdict`：用带 samples 的 fixture 跑 `pa.main(["list"])`，输出里含**完整的** `健康 unknown`（不是 `健康 unkn`）⇒ 列宽上限必须抬到容得下最坏 61 字符那条。

### 判据 5 · 反向变异 ≥4（真改、真跑、真还原，记 sha256）

- A：把 `_quota_text` 还原成只看 amount ⇒ 判据 1 / 2 的钉子必红；
- B：把有 samples 那一支的 kind 写死成「未观测」⇒ 判据 2 必红；
- C：把 `health_state` 的缺省从 None 改成 "ok" ⇒ 判据 4 必红；
- D：把 rows 里的 `quota_kind` 键删掉 ⇒ 判据 3 必红；
- C1（安静对照）：只改一句注释 ⇒ 全绿。

每条真改、真跑、真还原；记改前 / 改后 sha256 与 `-k` 子集的 passed/failed 数。记录落 `gates/diag/_rev_E118_result.txt`（gates/diag/* 被 .gitignore 忽略，不入库）。脚本必须放**主树** gates/diag/（`ROOT = __file__.parent.parent.parent`），放卡树会算成卡树里的卡树。

### 判据 6 · 不许削弱 / 不许顺手改

- 不许把「未观测」从「从没探过」那一支删掉（判据 1 堵的就是「干脆全改成别的词」这种反向偷懒）；
- 不许给 amount 编数值、不许把 health.state 缺键补成 "ok" / "healthy"；
- 不许改账本格式、不许写账本、不许联网：`save_ledger`（`tools/pool_accounts.py:327-351`）与它内部 `_dump_toml` 的三子表循环（`:374-380` `for sub in ("credential", "quota", "health"):`）都不动；`_quota_text` 与 `list_rows` 里不许出现 urlopen / requests / subprocess；
- 不许删既有 8 个 row 键、不许改排序键 (platform, id)、不许改 `_platform_known` 的读侧语义；
- 不许改 `tools/wb_dispatch.py:703-704` 那条「为什么不用 list_rows」的理由；
- 不许把 `tools/pool_accounts.py:1239` 的列宽上限**降低**（要抬，不是降）；不许动 `docs/doc-debt-baseline.toml` 的任何计数。

## 交付

1. `tools/pool_accounts.py`：`_quota_text` 按判据 1/2 改判词；`list_rows` 按判据 3 加四个机器键（只加不改）；`_print_table` 的列宽上限（`:1239` 那个 `min(48, …)`）抽成模块级常量并抬到 ≥64，旁边写一行注释说明为什么不能再封 48。
2. `tests/test_pool_accounts.py`：新增 6 条钉子 —— test_unobserved_means_never_probed / test_probe_kind_is_named_not_washed / test_list_json_carries_probe_verdict / test_quota_text_unchanged_when_amount_present / test_health_state_is_never_invented / test_cli_list_does_not_truncate_verdict。
3. `tools/pool_mcp.py`：`tool_account_status` 的人话行把结论码 / 时刻 / 连败 / health.state 也念出来（每号仍占 1 行，即 `:1601-1604` 那三行），保留 `:1607` 那条「只读读数，不探测」尾注 —— 只改文案，不新增探测、不联网。
4. `docs/subsystems/pool/模型与号池.md` 的额度节（`:68-84`，`:85` 是空行、`:86` 是 `## 5`）末尾加一条 ④：探过没探到怎么读（kind + at + 连败 + health.state），并写明「未观测」只表示账本里从没探过。
5. 证据行：落地前把 `python -X utf8 tools/pool_accounts.py list` 的真读数（今日五号）与 `list --json` 对应片段贴进台账 evidence。
6. 卡规格 + 三片段（由落地链的 ② 文档件按台账号 `T-AG628` 自动生成）。

## 验收（三条，落地前自跑，零手工步骤）

```bash
python -X utf8 -m pytest tests/test_pool_accounts.py tests/test_pool_mcp.py tests/test_pool_mcp_task.py -o addopts= -q --no-cov
python -X utf8 -m ruff check tools/pool_accounts.py tools/pool_mcp.py tests/test_pool_accounts.py
python -X utf8 scripts/check_derived_docs.py --check
```

## 不许做

- 不许加新探测、不许联网、不许写账本：本卡只改**读数怎么念**，账本一个字不动（探过没探到是既成事实，不是本卡要补的活）。
- 不许把四种结论码洗成一个词；也不许反过来把「未观测」这一支删掉 —— 那只是换一种撒谎。
- 不许给 amount 编数值，不许把 health.state 缺键补成 ok。
- 不许改账本 `quota.samples` 的项形状（probe 写 `{at, kind}`、签到另加 `credit` / `was`，都不是本卡的域）。
- 不许删既有 8 个 row 键、不许改排序键、不许改 `_platform_known` 的读侧语义。
- 不许只改人话、不改机器块（判据 3 就是堵这条）。
- 不许靠改测试让门变绿：既有 4 条 docstring 与下列断言都得原样留着（`tests/test_pool_accounts.py:652-663` 的排序键与八键 / `:258` 的凭据不外泄 / `:703` 的「能力表里没有」 / `:796` 的 quota 键集 / `:588-590` 的三命令退 0 / `:876-889` 的 MCP 四条）。