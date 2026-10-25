# 0006 按域跑必需门：提交闸认「必需的那几档」

Status: Accepted
Date: 2026-10-24
Supersedes:
Superseded-by:
来源: 台账 A327 / T-AG442；`复盘/卡/卡A327-按域跑必需门.md`；`gates/defs/domains.py` 的 `REQUIRED_PROFILES`

## 背景与问题

提交闸原本要求 19 道门全绿。可只改 `skills/**` 或文档时也要等 13 分钟
（`ui_flow` 367s、`render` 105s 全是真浏览器），与改动面严重不匹配。
门禁分层（卡 A321 / T-AG434）已经存在，但提交闸不认单档，还是要全量。

## 候选方案

A 保持全量：稳，但每次改文档花 13 分钟，人会开始绕过门禁。

B 按域算「这次改动最少要跑哪几档」，跑完的档写进 `gates/last.json`，
复核方按同一张表判够不够。风险是映射表判错就漏门，所以必须 fail closed。

## 决定

选 B，且把风险钉死：

- 映射表只有一份：`gates/defs/domains.py` 的 `REQUIRED_PROFILES`（`run_gates.py` 与
  `wb_review.py` 都 `import` 它，不许各写一份）；初始表 —— `src/`、`examples/`、`harness/` ⇒ `{lang, product}`；
  `tools/`、`scripts/`、`tests/`、`gates/` ⇒ `{lang, audit}`；`docs/`、`复盘/`、`skills/` 与根上的 Markdown 文件 ⇒ `{audit}`；
- **判不出就全量**：空清单 ⇒ `ALL_PROFILES`，任何未匹配路径 ⇒ `None` ⇒ 全量（fail closed）；
- `gates/last.json` 记 `profiles_run`，`wb_review` 第 ③′ 条据同一张表判，分档复核口径见卡 E24。

放弃 A 的代价：多了一条「映射表本身可能写错」的风险，靠单一真源 + fail closed 兜。

## 把握程度

high —— 映射表、fail-closed 回落、两个消费者共用一个常量，都有测试
（`tests/test_run_gates_domains.py`、`tests/test_wb_review.py`）。
