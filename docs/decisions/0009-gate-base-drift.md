# 0009 门禁基点：比「是不是这一笔的父提交」，也比「中间只动了台账」

Status: Accepted
Date: 2026-11-17
Supersedes:
Superseded-by:
来源: 台账 T-AG632；`复盘/卡/卡E123-门禁跑完主树又前进时复核器怎么判.md`；`tools/gate_base.py` 的 `gate_base_drift`

## 背景与问题

门禁把 rev 写进 `gates/last.json`，落地时判「这次门禁是不是为这一笔跑的」。
判据一直是「rev == 父提交」—— 0004 把它从「比字符串长度」修成「比解析后的提交」，
但仍然是**同一次提交**。

真实现场（89cd4deb，台账号 T-AG626）：门禁在 `f833d006` 上跑，期间主树插进两笔台账提交
（`5d57ade3` / `ebd39871`），这一笔的父提交成了 `ebd39871`。`R..P` 只动了三个文件
（`docs/subsystems/pool/README.md`、`docs/workbacklog.toml`、一份卡规格），一行源码都没动。
复核器仍然报两句：

```text
门禁不是为这一笔跑的（★ 一次门禁跑完提交两笔？第二笔没验过）
伪造门禁结论
```

第一句把「基线前移」说成「一次门禁提交两笔」，第二句是**指控**：`Gates:` 那行是落地链模板
自动出的，没人伪造。红对了（结论确实没为这一笔复验过），**理由错了**，而且它分不清
「中间只动台账」与「中间改了源码」——后者才是必须重跑的那一种。

## 候选方案

A 放宽成「rev 是父提交的祖先就算过」。（代价：「祖先」可以是几十笔之前，等于取消这道闸。）

B 三分支：同提交 ⇒ `MATCH`；真祖先且差异**全部**落在台账族 ⇒ `LEDGER_ONLY`（不判红，
但留读数、明说「未经复验」）；其余 ⇒ `DRIFT`（照红，且点名差异路径）。
台账族名单从 `gates/defs/domains.py` 的 `REQUIRED_PROFILES` 反推（只 allow `{audit}` 的前缀）。**选这个。**

C 在 `LEDGER_ONLY` 时也判红，只把文案改准。（代价：现场那种落地仍然卡死，本卡的问题没解决。）

D 落地链在 rebase 后自动重跑门禁。（代价：破「门禁只能在它自己的进程里跑」的口径
—— 锁 / 端口 / 卡树 cwd，见 `tools/pool/landing.py`；本卡明写不动 ④→⑦。）

## 决定

选 B。分类器**只有一份**（`tools/gate_base.py::gate_base_drift`），四处调它：
`tools/wb_review.py`（③ 与 ⓖ 两处）、`tools/wb_verify.py`、`tools/gate_pool.py`；
`framework/src/framework/review.py` 是纯库（不 import 本仓模块），做**镜像**，
一致性由 `tests/test_two_rulers.py::test_base_drift_classifier_has_one_source` 钉住。

`LEDGER_ONLY` **必须带见证**，不只是「真祖先 + 差异全台账」：

1. 第一现场读数 `gates/diag/base_drift/<task>.json`（落地链 ⑦ rebase 后落，字段
   `gates_rev` / `rebase_before_main` / `rebase_after_head` / `rebase_after_parent` / `diff_paths`）；或
2. 时间见证：产物里的 `sealed_at` 不早于父提交的提交时刻。

两者都没有 ⇒ 退回 `DRIFT`。理由：没有见证时，「真祖先 + 只差台账」与「旧产物被拿到新父提交上复用」
在数据上长得一模一样；既有钉子（`tests/test_wb_review.py:733-749`，真仓里 `~2` 那笔）要求这种情况仍红。

与 0004 的关系：0004 判的是**同一笔提交的两种短写法**（7 位 vs 8 位），修的是「字符串长度不是身份」；
0009 判的是**两笔不同提交**，修的是「差异只在台账时该怎么说话」。两条都保留：
先按字面量/解析值判同提交（0004 那条路），不同提交才走三分支。

## 把握程度

medium —— 现场 89cd4deb 的真读数已复现（`gates/diag/_rev_E123_before.txt` / `_after.txt`），
分类器与四处调用点都有钉子；但「时间见证」这条只有在产物带 `sealed_at` 时才生效，
没在满负载 / 多机并发下落过地。
