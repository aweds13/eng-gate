# 0004 封存口径：比提交，不比字符串长度

Status: Accepted
Date: 2026-10-24
Supersedes:
Superseded-by:
来源: 台账 A319 / T-AG433；`复盘/卡/卡A319-封存比提交.md`；`tools/wb_review.py` 的 `_resolve_commit`

## 背景与问题

封存时门禁把 rev 写进 `gates/last.json`，落地时判「这次门禁是不是为这一笔跑的」，
拿的是短 sha 字面量。可 git 的 `--short` 长度**随仓库变大而变**（实测同一笔一处 7 位、一处 8 位），
于是同一笔提交被判成两笔，报出来的是假红：

```text
["门禁不是为这一笔跑的：last.json 的 rev='94d343c'，而这一笔的父提交是 '94d343cc'"]
```

假红的后果不是假绿，是**落地链卡死**，而且看起来像「有人跑完门禁又提交了一笔」。

## 候选方案

A 先比字面量，不等则把两边 `git rev-parse --verify <short>^{commit}` 解析成完整 sha 再比
（合成 sha 的用例仍走字面量那条）。

B 只比解析后的完整 sha（解析不出就红）。

其它可选做法（把短 sha 统一写到固定长度、或禁止短 sha 进门禁产物）**当时没有正式比较过**。

## 决定

选 A，落在 `tools/wb_review.py`：新增 `_resolve_commit(short)`（解析不出返回空串），
`check_gate_evidence()` 先比字面量、不等再比解析值，两边都解析不出**仍判红**。
这不是放宽：仍然要求「同一次提交」，只是不许拿字符串长度当判据。
放弃 B 的代价：多一条分支，好处是合成 sha 的用例不用造真提交。

## 把握程度

high —— 假红原文是实测复现的，修法有回归测试（`tests/test_wb_review.py`）。
