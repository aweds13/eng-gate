# 卡 E149 · GHA 门禁读数回写：23 门全绿的现场与两份文档的旧口径

> 台账号 `T-AG682`｜分区 E（门禁与可信度）｜树 .wt/E149｜层 文书层｜基准 `641484be`（建卡树时主树 HEAD）｜depends E146 / E148
> 依据：E148（`3a0511ae`）把 `tests/test_pool_limits_data.py` 的宿主机绑定判据改成位址规则后，eng-gate 上重推了一趟，
> 23 门**首次全绿**（`ok=True rev=190903a0 n_gates=23 not_run=[]`，唯一 `EXCLUDED` 是 `render`）。但仓内那份 GHA 文档 §6
> 还停在 2026-11-19 的两趟旧读数，E146 的交接块也还写着「22 绿 1 红」。

## 要解决的问题

### 问题 1 · 文档 §6 的真读数落后于源码能产出的那一趟

`docs/subsystems/ci/GitHub-Actions-云门禁.md` 的 §6 标题是「真读数（2026-11-19）」，正文只写
job `135331686931`（head `cdb2c0fa`）与 job `135640738507`（head `14220c7c`）。这两趟都早于 E148，
读者按它去对源码会对不上「现在这份构建器能跑出什么」。E145 卡规格 `:37` 已经把「必须指到仓里这份脚本能产出的那一次」
写成判据，E148 之后那一次就是 head `190903a0`。

### 问题 2 · 同一句「22 绿 1 红」在交接文档里没有失效标记

`复盘/交接-重构进度.md:2316` 与片段 `复盘/交接.d/T-AG680.md:5` 是同一段（片段纪元之后由 `tools/sync_docs.py`
汇总），逐字写着「engineering 的 23 门读数这一趟是 22 绿 1 红（head 1e815a96…），不是「全绿」」。
按 `AGENTS.md` 的文档分层，这句话在当时是真的、读者会拿它当历史看 ⇒ **保留原文 + 加注**，不许静默改写。

### 问题 3 · 同一条事实的第三处投影：判据「engineering 逐字不变」的条数

§8.2 的对比块写「两边各 2786 条」，而 E146 自己那份最新读数（`gates/diag/cmp-e146.log`，同 HEAD `bf791e53` 两趟）
是 **2793** 条。2786 是更早一趟的口径，全仓只此一处命中。

## 判据（逐条可执行）

### 判据 1 · §6 必须指到仓里这份构建器能产出的那一趟

`docs/subsystems/ci/GitHub-Actions-云门禁.md` §6 的抬头与正文改成 head `190903a0`
（job `136613578025` / run `44830398970`），并给出：读数原文四行、逐门耗时表（22 门 `exit_code=0` + `render` `EXCLUDED`）、
同源求和、job 墙钟。旧两趟降级成「更早的对照」，并**如实标注** `1e815a96` 那趟的 22 绿 1 红与它的红门是谁、
由哪张卡修掉 —— 不许只留好看的读数。

### 判据 2 · 数字必须能从日志复算，不许抄

表里每个 `seconds` 与求和结果都要能由 `gates/enggate-logs/win-136613578025.log` 里那段 JSON 复算：
22 门求和 **4464.59 s**；job 墙钟由 `started_at 2026-11-20T22:36:55Z` / `completed_at 2026-11-20T22:57:12Z` 得 **1217 s**。

### 判据 3 · 交接块加注，不改原句

`复盘/交接.d/T-AG680.md:5` 那句下面加一行「**2026-11-21 补注（卡 E149 / `T-AG682`）**：…」，
再由 `tools/sync_docs.py` 汇总进 `复盘/交接-重构进度.md`（**不许手改汇总文件**）。

### 判据 4 · §8.2 的条数改成最新口径

`git ls-tree -r HEAD  # 两边各 2786 条` 改成 `2793 条`（源：`gates/diag/cmp-e146.log` 的对比段）。

## 交付

1. `docs/subsystems/ci/GitHub-Actions-云门禁.md`：§6 重写（读数换 190903a0、旧趟降级为对照）、§8.2 条数改 2793。
2. `复盘/交接.d/T-AG680.md`：`:5` 加补注行；`复盘/交接-重构进度.md` 由 `tools/sync_docs.py` 现生成。
3. 两个文书片段（docs/changelog.d/T-AG682.md 与 docs/traceability.d/T-AG682.toml，**计划建**）：由 `tools/wb_stage_card.py` 现生成，不许手写。

## 验收（落地前自跑）

    cd .wt/E149
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 tools/sync_docs.py --root .

门槛：① 死指针仍 147（基线 147，+0），不许涨；② `check_layers` PASS；③ `sync_docs` 报「（+1）」且汇总文件里那句话原样还在（加注是新增行，不是替换）。

## 不许做

- 不许改 `scripts/` / `tools/` / `tests/` —— 本卡是纯文书笔，碰源码会被强制跑全量门禁（本机内存只够 1 worker，20 分钟起）。
- 不许手改 `docs/INDEX.md` / `复盘/INDEX.md` / `docs/subsystems/pool/README.md`（都是生成器产物）。
- 不许把 §6 的旧两趟删掉：读者要靠它们看「runner 负载差」这条结论的来历。
- 不许在文书里用反引号写仓外快照路径或本机日志路径（E144/E145/E146 各因此吃过一次死指针）。

## 直做（已实测）

E149 现场：主树 HEAD `ee3489b9`、`git status --porcelain -uno` 空；`.wt/E149` 建在 `641484be` 上；
`grep -c 'id = "E149"' docs/workbacklog.toml` ⇒ 0；`T-AG682` 在 docs/ 与 复盘/ 里 0 命中。
