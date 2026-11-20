# 0011 不移植 magpie 的决策模型与 /v1/systemone

Status: Accepted
Date: 2026-11-20
Supersedes:
Superseded-by:
来源: 台账 A381 / T-AG669（`docs/workbacklog.toml` 的 A381 条目）、卡规格 `复盘/卡/卡A381-F14决策模型与systemone-判SKIP_BY_REDLINE.md`；判定表 `gates/diag/_magpie_scope.md` 第 22 行的 F14 行（★ 该行「证据」列写的是「grep systemone 只命中 rpm.decide 与 route_log 注释」，本卡实跑更正为**全仓零命中**，见下「背景与问题」）；判据落在 `tests/test_pool_no_systemone.py`，决定同时写进 `docs/subsystems/pool/模型与号池.md` 的 §9 与 `docs/subsystems/pool/README.md` 的表 B 第 8 行。

## 背景与问题

magpie 的 F14「决策模型与 /v1/systemone」在源码里是三件东西加一条禁令：一条自己的端点
`POST /v1/systemone`（`internal/gateway/gateway.go` 的 `mux.HandleFunc("POST /v1/systemone", …)`）、
一类只做决定的模型与只装它们的路由组（`internal/provider/decide.go` 的 `Decides()` 与
`DecideOnly()`，真实供给只有 `jev-latest` 与 `decision-model-preview` 两个常量）、
一个 classifier 宿主（`internal/gateway/decide.go` 的包注释：拿 decision 模型判「这句话是哪个
intent」「这一轮多难」）；禁令是「装 decision 模型的组不许接任何塑造对话的东西」，会话请求点到
这种组被 **400** 指到 `/v1/systemone`。

本仓今天**完全没有**这个东西，而且不是「有代码没接线」—— 三条读数各自独立：

1. **生产码零命中六条字面**。范围 = `tools/` 与 `scripts/` 下的 `*.py`（不含 `tests/`、
   不含 `docs/`、不含 `__pycache__`），实跑 170 个文件：`systemone`（大小写不敏感）0、
   `decides(` 0、`DecideOnly` 0、`jev-latest` 0、`decision-model-preview` 0、`decide_group` 0。
   同一趟还量了 `\bintent\b`（词边界）0 —— 裸词 `intent` 会命中 `intention`，裸词 `jev`
   会命中云机 instance-id `i-0123456789abcdef0`，两个假阳性都必须在判据里避开。
2. **运行时不存在**。`tools/pool/gateway.py` 的 `PATHS` 恰好四条
   （`/v1/chat/completions` / `/v1/messages` / `/v1/models` / `/v1/pool/routes`），
   `_dispatch` 先查 `PATHS` 后鉴权 ⇒ `POST /v1/systemone` 带不带 Bearer 都是 **404**，
   文案只说「本网关只有四条」。服务类上也没有任何 systemone / decide 方法。
3. **宿主概念与外部资产都不存在**。路由只有排序（`tools/pool/route.py` 的 `apply_strategy`：
   输入是座位集合、输出是次序），没有 rules / intent / effort auto 这套输入；仓外账本
   `D:/repo/infra/pool/accounts.toml`、`tools/pool/platforms.toml`、
   `tools/pool/model-registry.toml` 三处 `decide|decision|systemone|jev` 全 0（平台表的
   `chat_urls` 九个平台全空 = 没登记，不是不支持）⇒ 没有可问的 decision 号。

三条红线挡在前面：① `tools/pool/gateway.py` 模块头「**不做协议翻译**」—— System One 的 body
不是对话，是「问题 + 候选答案 + 概率」，搬它就得搬一层语义翻译；② 同一文件「**四条路径，
一个都不多**」—— 加第五条就是把这条判据自己推翻，而它正是
`tests/test_pool_gateway.py` 的 `test_http_only_four_paths` 在钉的东西；③「**不做定时器**：
没有后台线程；沉底 / 每分钟闸 / 并发闸都是每次请求现读现算」—— classifier 要的是「用户这一轮
开始时先问一次」的请求前调度点，硬塞进去就是给每个请求加一次额外的上游往返。

## 候选方案

A **真移植**：把端点、decision group、classifier 三件一起搬，按 magpie 的形状开第五条路径。
代价：立刻破掉「不做协议翻译」与「四条路径，一个都不多」两条明文边界，且要为一个非对话
往返新开一本路由账（`wb-route.jsonl` 的 status 闭集是四个值）或第二套闭集；更硬的是
**永远跑不到** —— 本仓一个 decision 号都没有，代码进来就是占位。否决。

B **只搬分组 failover**：不搬 classifier、不搬端点，只把「同一个 decision 模型的多个号按
key 依次试」这一层并进现有 `route_once`。代价：本仓没有任何 decision 号，这段 failover 的
输入恒为空 —— 它退化成一个永不生效的分支，而分支持久化在请求路径上，读代码的人会以为
本仓支持决策模型。同时「只装 decision 模型的组」这个概念也要一起搬（否则没有「组」可
failover），又把宿主概念拖了回来。否决。

C **不移植，只把决定钉成证据**：产品码一个字节不改，把「为什么不做、什么情况下会变」
写成这份 ADR，并把同一句话投影到两处 tracked 文档（`docs/subsystems/pool/模型与号池.md`
§9、`docs/subsystems/pool/README.md` 表 B），再加一个只读的测试文件把「今天确实没有」
钉在真服务、源码、结构与文档四层上。代价：将来真要接 decision 号，得先推翻这份 ADR
（这是**故意的**：推翻一份写下来的决定，比删掉一段没人敢动的死代码便宜）。

## 决定

选 C。理由：A 破两条明文边界且落进来是死代码；B 的输入恒为空，等于给请求路径加一个
永不生效的分支还顺带搬回宿主概念；C 一行产品码不动，代价只是「将来要接时先推翻 ADR」。

**失效条件**（写在这里，因为它比结论更容易烂掉）：本 ADR 判的是**两半**，两半的失效条件
不同。① `SKIP_NOT_APPLICABLE` 那一半 ——「本仓没有 decision 号、没有 rules / intent /
effort auto 这套输入」—— 一旦仓外账本或平台表里登记了任何一个 decision 号（哪怕只有一个），
这一半**立刻失效**，必须重新立卡评估；它保证的是「今天没有」，不是「永远没有」。
② `SKIP_BY_REDLINE` 那一半 ——「不做协议翻译 / 四条路径 / 一次性判定」—— 只有先修
`tools/pool/gateway.py` 的模块头那三条边界（那是另一张卡、另一份 ADR）才会失效；
光有号不会让这一半失效。

判据只留一份真源：`tests/test_pool_no_systemone.py`。它钉四件事 —— 真服务上
`POST /v1/systemone` 与 `POST /v1/decide` 都 404 且文案只点四条（带不带 Bearer 都 404，
**不许**断 401，那会把「先查 PATHS 后鉴权」的次序钉反）、`tools/pool/gateway.py` 里没有
`systemone` / `decide_group` 字面且 `PATHS` 精确等于四元组、`tools/` 与 `scripts/` 的生产码
四形状零命中、以及这份 ADR 与两处文档确实写着这个决定。

★ 零命中扫描**只到生产码**（`tools/` + `scripts/`），不到 `tests/` 与 `docs/`：本卡自己的
产物必须写出 `systemone` 才说得清决定，把产物也纳入扫描就是自己咬自己。这条边界写在测试
文件的模块 docstring 里并给了理由，不是靠一份跳过名单糊过去。

## 把握程度

medium —— 依据是本仓生产码的零命中读数（170 个文件、六个字面）、真服务上的 404 实测与两条源码边界，但 magpie 侧只读源码、没在真 decision 号上跑过。
