# 卡 F11 —— pool 项目书自己就是过期的：手写的体量表 21 个模块一个都没提

> 台账号 **T-AG559** ｜ 分区 **F**（文档治理）｜ 树 `.wt/F11` ｜ 层 **文档层**
> 依据：2026-10-30 现读（主树 `ac3af848`）——
> · `docs/subsystems/pool/README.md:11` 写「`tools/pool/` = 17 个 py（16 个模块 + `__init__.py`）、**7143 行**」；
>   实测 `tools/pool/*.py` = **36 个文件 / 13817 行**。
> · `docs/subsystems/pool/README.md:54` 的度量表把同一对数字再写一遍：「7143 行 / 17 个 py」。
> · 模块表列了 **19 项**（含 2 个非 `tools/pool/` 的 `pool_accounts.py` / `checkin.py`），
>   而 `tools/pool/` 实有 **40 个文件**（36 py + 4 toml）。逐名 diff：
>   **README 没列、但仓里真有的 21 个** —— `account_id.py` `accounts_scope.py` `callers.py`
>   `failclosed.py` `holds.py` `lanes.py` `lanes.toml` `lastgood.py` `ledger_spend.py`
>   `limits.py` `limits_check.py` `limits_policy.py` `model-registry.toml` `queue.py`
>   `quota_history.py` `route.py` `rpm.py` `rpm.toml` `sink.py` `sticky.py` `usage_ingest.py`。
>   README 列了但已不存在的：**0 个**（不存在的方向没漂，只漏了新增的）。
> · 度量表其余四行也全过期：队列卡数「239 张（218 done / 21 pending）」→ 实读 **294 张
>   （284 done / 10 pending）**；批预声明「132 份」→ 实读 **152 份**；派活日志「224 份」→
>   实读 **242 份**（`wb-*.jsonl`）。

## 要解决的问题

1. **同一对数字写了两遍**（`:11` 与 `:54`），而且两处都过期 —— 手写计数必然过期，
   这不是「写错了一个字」，是**记录方式本身错了**：它记的是文件系统的事实
   （模块个数、行数、队列卡数、批目录份数、日志份数），却由人手抄。
2. **21 个模块一个都没进表**。这张表是本子系统的「代码边际」，读者靠它判断「这东西多大、
   谁是谁」。漏 21 个（其中 `landing.py` 之外最重的几个：`usage_ingest.py` 655 行 /
   `model_registry.py` 644 行 / `usage` 一族 / F 系 magpie 移植的 12 个判据模块）⇒
   读者会以为 pool 只有 17 个文件、不敢改也不敢用。
3. **过期没有任何门咬**。`grep -rn "7143" tests/ scripts/` **零命中** —— 没有任何钉子、
   任何门在看这份文档的计数。所以它会一直过期下去。

## 判据（6 条）

1. **新建 `scripts/gen_pool_readme.py`**：只重写
   `docs/subsystems/pool/README.md` 里两处标记之间的内容
   （`<!-- pool-margin:begin -->` … `<!-- pool-margin:end -->`，§1 的体量表 + §2 的度量表），
   **标记之外的字节一个都不动**（含文件头、§3–§5、表 A/B/C）。
   - `--check`：一致退 0；不一致退 1 并**逐行点名**哪几行不一样（不是只说「有差异」）。
   - 写盘（无参数）：只写这一个文件；**不碰** `docs/INDEX.md`、不碰别的子系统文档。
   - 行尾**跟随目标文件现状**：CRLF 目标重算后 `\r\n` 数不变、裸 `\n` 为 0；
     不许写死常量。先例：`scripts/gen_doc_index.py` 的口径。
2. **§1 表覆盖 `tools/pool/` 下全部 40 个文件**（36 个 `*.py` + 4 个 `*.toml`），
   每行 = 模块名 + **现算行数** + 一句话职责 + 命令壳。行数口径
   = `path.read_bytes().count(b"\n")`（与本仓既有实测一致：36 文件 / 13817 行）。
   - 「职责」与「命令壳」由一份**单一真源**提供：新建 `docs/subsystems/pool/modules.toml`，
     形如 `[[module]] name = "guards.py" / duty = "…" / cli = "…"`。生成器读它；
     **出现仓里有、清单里没有的模块 ⇒ 生成器必须退 1 并点名那个模块**（不许静默跳过）。
   - `duty` 不许为空串（空 ⇒ 退 1，理由明写「空职责等于没写」）。
3. **表头那句话由生成器写**，不许手写：
   `` `tools/pool/` = <N> 个 py（<N-1> 个模块 + `__init__.py`）、**<M> 行**（`wc -l tools/pool/*.py`，<生成日期> 现算）。 ``
   —— 日期取生成当天，不许沿用 `2026-10-25`。
4. **§2 度量表的会漂数字全部现算**，不许留手抄值：
   实现体量（py 个数 + 行数，与判据 3 同源）· 队列卡数（读 `docs/workbacklog.toml` 的
   `cards`，分 `done` / `pending`）· 批预声明份数（`gates/diag/batch/*.toml`）·
   派活日志份数（`gates/diag/wb-*.jsonl` 减 `wb-usage.jsonl`）。
   「最近一份跑完的」与「单次派活墙钟」两行**允许退化为口径句**（说明怎么取 + 不写死数字），
   但必须保留「怎么取」那一列。
5. **新增 `tests/test_pool_readme_counts.py`，≥6 条钉子**（每条都要能在真仓上跑）：
   ① 真仓 `python -X utf8 scripts/gen_pool_readme.py --check` 退 0；
   ② 合成树里新加一个假模块（文件名 `zzz_new.py`，本仓没有这个文件）且 `modules.toml` 没登记它 ⇒ `--check` 退 1 并**点名**它；
   ③ 合成树里把 `duty` 改成空串 ⇒ 退 1 并点名；
   ④ 手改 `README.md` 表里一行的行数（不动别处）⇒ `--check` 退 1 且**报到行号**；
   ⑤ 标记之外的字节：手改 §3 一行 ⇒ `--check` **仍退 0**（证明它不越界），
      而重写后那一行**逐字未被改动**（生成器只写标记内）；
   ⑥ CRLF 目标重算后 `\r\n` 数不变、裸 `\n` 为 0（行尾跟随，不写死）。
6. **旧数字零残留**：改后 `docs/subsystems/pool/README.md` 里
   `grep -c "7143"` = **0**、`grep -c "17 个 py"` = **0**、`grep -c "2026-10-25"` = **0**
   （本卡规格除外）；且「36 个文件 / 13817 行」这组现算值必须出现在 §1 与 §2 两处。

## 交付

- `scripts/gen_pool_readme.py`（新）
- `docs/subsystems/pool/modules.toml`（新，40 条 `[[module]]`）
- `docs/subsystems/pool/README.md`（§1 + §2 换成标记内的生成物，§3–§5 逐字不动）
- `tests/test_pool_readme_counts.py`（新，≥6 条钉子）
- `复盘/卡/卡F11-pool项目书自己就是过期的.md`（本卡规格）

## 验收

```bash
python -X utf8 scripts/gen_pool_readme.py --check              # 退 0
python -X utf8 -m pytest tests/test_pool_readme_counts.py -q -o addopts= --no-cov   # 全绿
python -X utf8 -m pytest tests/test_gen_doc_index.py -q -o addopts= --no-cov        # 不许连累索引
python -X utf8 scripts/check_docs.py --json                    # dead_refs 不涨（现 145，基线 152）
python -X utf8 scripts/run_gates.py --only docs,check_layers,audit_titles            # 三门绿
```

## 不许做

- **不许改 `tools/pool/**` 一个字节**（本卡只治文档与其生成器；`duty` 文字读文件头 docstring 写，
  不许为了让表好看去改源码注释）。
- 不许改 `docs/subsystems/ci/README.md` 或任何别的子系统文档（每份各自开卡）。
- 不许把度量数字写进 `docs/doc-debt-baseline.toml`（那不是文档欠账，是把会漂的量当阈值）。
- 不许让生成器写 `docs/INDEX.md` 或 `复盘/INDEX.md`（那是 `scripts/gen_doc_index.py` 的活）。
- 不许删 §3–§5（决策 / 卡表 / 边界三表是这份文档的主判据，只能原样保留）。
- 不许把「未来会做」写进表里（本仓越界判据之一：出现「未来会做」即判不通过）。
- 不许为凑数把 `modules.toml` 的 `duty` 写成模块名的同义重复（如 `guards.py` 写「守卫」）——
  必须写它**管什么**，读者能据此判断该不该改它。
