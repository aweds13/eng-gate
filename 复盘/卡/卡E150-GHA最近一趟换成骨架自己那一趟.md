# 卡 E150 · GHA 文档 §6 的「最近一趟」换成骨架自己跑出来的那一趟

> 台账号 `T-AG685`｜分区 E（门禁与可信度）｜树 .wt/E150｜层 文书层｜基准见建树时主树 HEAD｜depends E146 / E148 / E149

## 要解决的问题

### 问题 · §6 写着「最近一趟」，但它已经不是最近那一趟

`docs/subsystems/ci/GitHub-Actions-云门禁.md` §6 的抬头是「真读数（最近一趟 2026-11-21：23 门全绿）」，
正文钉的是 job `136613578025`（head `190903a0`）。

E147 落地（主树 `37a09b98`）之后又推了一趟：commit `97d009e5`、run `44852205296`、
job `136685943795`，读数 `ok=True host=runnervmbpeip rev=97d009e5 n_gates=23 not_run=[]`，
22 门 `exit_code=0` + `render` `EXCLUDED`。于是「最近一趟」这句话与事实不符。

### 为什么这一趟比 190903a0 更该当证据

两趟都是仓里这份构建器产的，但**这一趟是在 profile 骨架落地之后、用 `--repo` 选 engineering 那份 profile
跑出来的**（`gates/diag/gha-eng-all-e147.log` 里 `ROOT HEAD: 37a09b98…` → `HEAD: 97d009e5…`）。
也就是说它同时是「仓无关骨架真的能跑 engineering」与「engineering 23 门能全绿」两条判据的同一次读数。
另外它让「23 门全绿」从**一趟**变成**连续两趟**（`190903a0` 与 `97d009e5`），
排掉「那一趟是侥幸」这一层怀疑。

## 判据（逐条可执行）

### 判据 1 · §6 的抬头与正文指到最新那一趟

抬头保留「23 门全绿」这个结论，日期改成这一趟的日子；正文换成
job `136685943795` / run `44852205296` / head `97d009e5`，并写明它就是
`scripts/cloud/gha/build_snapshot.py --repo engineering --stage all` 的产物。

### 判据 2 · 每个数字都能从日志复算

逐门 `seconds` 从 job `136685943795` 日志里 `=== GHA-GATE-READING-BEGIN/END ===` 之间那段 JSON 取，
22 门求和与 job 墙钟都要写明算法与来源：
求和 **3536.7 s**（`gates[].seconds` 相加）、墙钟 **1015 s**（`started_at 2026-11-21T01:47:16Z` /
`completed_at 2026-11-21T02:04:11Z`）。`pytest` 那门的 `summary` 原文是
`5458 passed, 5 skipped, 1 xfailed`（前一趟 `190903a0` 是另一组数，两趟都留）。

### 判据 3 · 旧读数降级，不删

`190903a0` 那一趟的读数块保留，改成「前一趟（同一份构建器，profile 骨架落地后第一趟）」；
更早的 `2026-11-19` 两趟与 `1e815a96` 那趟 22 绿 1 红的记述原样留着。
读者要靠这几趟看「runner 负载差」与「红门是怎么修掉的」两条结论的来历。
逐门耗时只保留**最新一趟**那一张表（三张表会让「这一页在说什么」失焦），
旧趟只留 `pytest` 秒数与求和这两个用于对照的量。

### 判据 4 · 三道文档门不涨

`check_docs.py --mode report` 死指针不涨过基线 147；`check_layers.py` PASS；
`check_derived_docs.py --check` 双 OK（该重跑生成器就重跑，不许手改产物）。

## 交付

1. `docs/subsystems/ci/GitHub-Actions-云门禁.md` §6：读数换 `97d009e5`、旧趟降级、耗时表换成本趟。
2. 两个文书片段（docs/changelog.d/T-AG685.md 与 docs/traceability.d/T-AG685.toml，**计划建**）：
   由 `tools/wb_stage_card.py` 现生成，不许手写。

## 验收（落地前自跑）

    cd .wt/E150
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 scripts/gen_doc_index.py --target docs
    python -X utf8 scripts/check_derived_docs.py --check

## 不许做

- 不许改 `scripts/` / `tools/` / `tests/` —— 纯文书笔。
- 不许手改 `docs/INDEX.md` / `docs/changelog.md` / `docs/traceability.toml` / `复盘/交接-重构进度.md`
  （都是生成 / 汇总产物）。
- 不许把旧几趟的读数删掉。
- 不许在反引号里写仓外日志路径（`gates/enggate-logs/…` 不进仓，写它会被 `check_docs.py` 判死指针）；
  要指出处就写「job 编号 + 日志里的 BEGIN/END 段」，job 编号在 GitHub 上可取回。
