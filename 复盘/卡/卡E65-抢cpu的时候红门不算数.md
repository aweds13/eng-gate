# 卡 E65 —— 抢 CPU 的时候，红门不算数

> 台账号：`T-AG524`｜分区：E（框架 / CI）｜树：`.wt/E65`
> 依据：卡 091 的满载竞态签名；2026-10-29 云门禁 e/f/g 三趟「每趟红的浏览器流都不同」；
> 速度调查 `gates/diag/_speed_shard_plan.md` 的「同机争抢 +21.6%」与「并行吞吐 2.05×」。

## 实测证据（2026-10-29，云机 `203.0.113.10` / `C:/eng`）

| 趟 | 门禁 | 红在哪 | 证据 |
|---|---|---|---|
| e（端口 9414） | `ui_flow exit=1` | `⑮ Obsidian 只读跳转 … 能关掉跳转 —— 实际 false，期望 true` | `gates/diag/cloud-gate-E63e.log` |
| g（端口 9418） | `web_live exit=1` | `tools/web_live_check.py:283` `_json_call(base, "/api/settings/ai", "PUT", {"enabled": True})` ⇒ `TimeoutError: timed out`（`timeout=10`，`:127`） | 本卡 `cloud-gate-E63g.log` / `.wt/E64/gates/logs/web_live.log` |
| b（端口 9428，E64） | `web_live exit=1` | 同上同一行、同样 `TimeoutError: timed out`，门耗时 23.67 s | `.wt/E64/gates/logs/web_live.log:283` |
| h（端口 9420，E63 落地那趟） | —— | **22 门全绿**，`ok=true`，`729 s` | `gates/diag/cloud-gate-E63h.log` |

同一棵树上、同一批代码，`web_live` 有时绿有时红；单跑 `ui_flow` 全绿（26 条流 / 362 断言 / 365.6 s），单跑 `⑬` 也绿。⇒ 红的不是代码，是**墙钟**。

## 要解决的问题

云门禁机是 2 物理核 / 4 逻辑核。同一台机上跑两套负载（门禁自己的 pytest 泳道 + 浏览器泳道，或者别人也在跑门禁）时，浏览器门会在**墙钟**上超时：
2026-10-29 那天同一棵树上，`ui_flow` 一趟红 `⑬ 导出 Markdown`、一趟红 `㉒ 删除可选`、一趟红 `⑮ Obsidian 只读跳转`；而把这道门**单独**跑（`node tools/ui_flow_check.mjs --port 9462`）是 `26 条流 / 362 项断言` 全绿、`365.6s`。

也就是说：现在的门禁把「这台机当时有多少 CPU 可用」偷偷算进了「代码对不对」的结论里。红的时候没人知道该去修代码还是该重跑一遍。更坏的情况是反过来——满载下偶发的**假绿**（某条流因为慢而没触发断言窗口）。

## 判据

1. **跑门禁必须记下同租户**：`scripts/run_gates.py` 在产出 `gates/last.json` 时写一条 `co_tenants`（数组），至少包含「同机同端口段之外的 python/node 进程数」与「本次门禁自己的泳道并发度」。采集失败记 `null` 并在 `reasons` 里写明「没采到」，**不许静默写 0**。
2. **超时类失败要标 `SUSPECT`**：浏览器门（`render` / `ui_flow` / `ui_dom_probe` / `web_live` / `lf1_live`）的失败，若摘要匹配墙钟/超时形状（`等了约 N s`、`timeout`、`超过 N 秒`），产物里那道门记 `status = "SUSPECT"` 而不是 `"FAIL"`，并附 `co_tenants` 快照。
3. **`SUSPECT` 不许洗白成通过**：整趟 `ok` 仍为 `false`（`SUSPECT` 是「未验证」的近亲，不是「绿」）；`tools/gate_verdict.py:judge()` 的 `state` 必须能区分出第三种取值，且三把尺子（`run_gates` / `wb_verify` / `wb_review` / `gate_pool`）读同一份判据。
4. **反向钉子**：拿一份「满载 + 超时摘要」的合成产物，钉住「记 `SUSPECT` 且 `ok=false`」；拿一份「干净 + 同样摘要」的产物，钉住「记 `FAIL` 且 `ok=false`」——两种都必须红，区别只在措辞与第三次取值。
5. **不许把并发度当免罪符**：`co_tenants` 非空不改变判据（不因为「当时忙」就放行），只改变**人怎么读**。

## 交付

- `scripts/run_gates.py`：`co_tenants` 采集 + `SUSPECT` 标注 + 产物字段。
- `tools/gate_verdict.py`：`judge()` 增加 `SUSPECT` 状态与对应 reason 文案。
- `tests/test_gate_co_tenants.py`（新）：判据 1/2/4 的正反用例。
- `docs/subsystems/ci/测试流程.md`：写清「红 / 未验证 / SUSPECT」三者的读法与处置。
- `docs/subsystems/ci/云门禁机.md`：补一节「同机争抢的实测代价」（pytest 529 s vs 单跑 435 s，+21.6%）。

## 验收

```
python -X utf8 -m pytest tests/test_gate_co_tenants.py -q -o addopts= --no-cov
python -X utf8 scripts/run_gates.py --profiles audit   # co_tenants 字段出现且非空
python -X utf8 tools/wb_verify.py --tree .             # 五块无 FAIL
```
云门禁：`bash scripts/cloud/run_gate.sh E65 <端口段>` 一趟 `exit 0`、22 门、`ok=true`。

（2026-10-29 现读：门表 22 道；本机 3.14.6、云机 3.12.8。）

## 不许做

- 不许把 `SUSPECT` 当成「跳过」或「绿」；不许让 `ok=true`。

（2026-10-29 现读：门表 22 道；本机 3.14.6、云机 3.12.8。）
- 不许为这条卡放宽任何现有超时阈值（那是把症状藏起来）。
- 不许在门禁里写「本机核数」之类的硬编码；采集失败就记 `null`。
- 不许顺手改 `TF_PYTEST_WORKERS` 的默认值（那是另一张卡的事，且云机已用 `setx` 定成 2）。
