# 卡 E74 —— 又多了一份 `wb-*.jsonl`：三个读者不许把它当成一张卡（T-AG576）

> 台账号 `T-AG576` ｜ 分区 E（门禁与可信度）｜ 树 `.wt/E74` ｜ 层 判据层
> 依据：卡 A363（T-AG575）在 `.wt/A363` 引入 `gates/diag/wb-route.jsonl`（F39 路由回放，一行一轮）。A363 工人当场指出：**这份文件会落进三个按 `wb-*.jsonl` 通配的读者眼里**，而 A363 的域不含这三个文件。
> T-G137 的先例：当时 `wb-usage.jsonl` 也栽在同一个坑（9 棵树 9 行 `usage` 幻影）。
> 基准提交 `4fd68707`（主树 HEAD，A361 刚落）。

## 要解决的问题

pool 的「工人日志」口径是文件名 `gates/diag/wb-<卡>.jsonl`。谁按这个通配去扫，谁就会把**不是卡**的 jsonl 也当成一张卡。今天这条通配出现在三处，且三处对「不是卡」的处理**各写各的**：

| 读者 | 现写法 | 新文件落进来会怎样 |
|---|---|---|
| `tools/wb_dash.py:159` | `NON_CARD_LOGS = frozenset({"wb-usage.jsonl"})`，`:164` `return name not in NON_CARD_LOGS` | 面板多一行「卡 `route`」 |
| `tools/pool/jobs.py:40` | `USAGE_LOG_RE = re.compile(r"^wb-usage(\.r\d+)?\.jsonl$")`，`scan_jobs` 用它把用量账单独标出来 | `?`（本卡要先读清它落在哪条分支） |
| `tools/wb_retention.py:164` | `c.jsonl_files = sorted(diag.glob("wb-*.jsonl"))`，随后 `c.no_verdict_jsonl = [p for p in c.jsonl_files if not has_verdict(p)]` | 每次巡检报「有日志没判决」的假欠账 |

真正的问题是**同一件事（哪几个 `wb-*.jsonl` 不是卡）被三处各自记一份**，新增一份非卡日志就要改三处、且谁都不知道还有第三处。这与本仓反复落地的「判据只许一份」是同一条原则。

## 判据（6 条，逐条可执行）

1. **一份名单**：哪几个文件名（含 `wb-usage.r<N>.jsonl` 这类变体）不是卡，**只在一处定义**。三处读者都引用它，`grep` 之后不许再有第二份字面量集合。
2. **名单是「按文件名的正则/谓词」，不是硬编码枚举**：`wb-usage.r2.jsonl` 这种带轮次的变体，与 `wb-usage.jsonl` 一样判成非卡（现有 `USAGE_LOG_RE` 已经是这个口径，别退化）。
3. **`wb_dash` 不把非卡日志当卡**：给它一份含 `wb-route.jsonl` 的目录，输出的卡片列表里**没有** `route`。
4. **`wb_retention` 不把非卡日志算进假欠账**：`no_verdict_jsonl` 里没有任何非卡日志；且真卡的「有日志没判决」**照旧能报出来**（反证：造一份 `wb-999.jsonl` 无判决 ⇒ 必须出现在 `no_verdict_jsonl` 里）。
5. **`scan_jobs` 对非卡日志的处理与本卡前一致**：`wb-usage*` 仍被单独标出不当卡；`wb-route.jsonl` 同办。断言：目录里同时有 `wb-001.jsonl` / `wb-usage.jsonl` / `wb-route.jsonl` ⇒ `scan_jobs` 只把 `001` 算成卡。
6. **新名字要能一处加**：加一个假想的 `wb-foo.jsonl` 到名单里，三处读者同时生效（断言：改名单一处后，三条断言全过，且**没有**第二处需要改）。

## 交付

1. **一处定义**（选一处最自然的家。建议 `tools/pool/jobs.py` —— 它已经是「工人日志是什么」的权威，`wb_dash` 与 `wb_retention` 都 import 过 pool 的模块）：一个谓词（如 `is_card_log(name: str) -> bool`）或一组常量 + 谓词，**带上今天的两个真值**（`wb-usage.jsonl` 与 `wb-route.jsonl`，以及 `wb-usage.r<N>.jsonl` 变体）。
2. `tools/wb_dash.py`、`tools/wb_retention.py` 改成引用这一处；`tools/pool/jobs.py` 自己的 `USAGE_LOG_RE` 若被新谓词取代就删掉，若仍有独立用途就与谓词共用同一个真源（**不许两份字面量**）。
3. 新测试：并进 `tests/test_pool_jobs.py` / `tests/test_wb_dash.py` / `tests/test_wb_retention.py` 任一即可（**不点名新文件名** —— 本仓 `check_docs` 会把还没落地的路径判成死指针）。6 条判据每条至少一条钉子。
4. `gates/diag/_rev_E74.py`：≥5 条变异，逐条真改坏、跑、证明某条钉子变红、再还原。

## 验收（跑完逐条报末行原文）

```bash
cd .wt/E74
python -X utf8 -m pytest tests/test_pool_jobs.py tests/test_wb_dash.py tests/test_wb_retention.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool/jobs.py tools/wb_dash.py tools/wb_retention.py
python -X utf8 gates/diag/_rev_E74.py
```

## 不许做

- **不许**把 `wb-route.jsonl` 从 `gates/diag/` 挪走或改名 —— 卡 A363 的落点已定，本卡只治读者。
- **不许**改 `wb_dash` / `wb_retention` 的输出格式与人话（只改「哪些文件算卡」这一处判断）。
- **不许**把名单做成「把所有 `wb-*` 都当非卡」或「只认数字卡号」—— `card_of()` 今天接受非数字卡号（`B1` / `C1` / `B-20261052` 都在用），收紧会把它们判掉。
- **不许**碰 `gates/last.json` / `gates/reuse.json` / 六份 `PROTECTED_FILES`。

## 缺口（如实写在卡里）

1. `gates/diag/` 里今天还有别的非卡 jsonl（`pool-sink.json` / `quota-state.json` 之类），本卡**只治 `wb-*.jsonl` 这一族**，别的文件名不在通配里，不是本卡的病。
2. `wb_retention` 的 `verdict_files` 有同样形状的问题（`glob("wb-*.verdict.txt")`），本卡**不处理** —— 非卡日志今天不产判决文件，现在没有症状。
3. 只在本机 win32 验过。
