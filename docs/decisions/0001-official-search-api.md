# 0001 搜索走官方 API，不走第三方搜索

Status: Accepted
Date: 2026-10-24
Supersedes:
Superseded-by:
来源: 台账 D6 / T-DG006（`docs/workbacklog.toml` 分区D）；`复盘/卡/卡D6-联网搜索与引用.md`

## 背景与问题

产品要「能联网搜索」，官方给了专用接口：`POST /v1/tools/search`、`POST /v1/tools/fetch`。
它返回的三层正好对上三处消费者：`snippet` 给 UI、`summary` 给模型、`rerank_score` 判质量，
按 **$0.75 / 1000 次成功请求**计费。另一条必须同时守住的切分是：
**「搜外网」与「搜我的资料」是两个工具，不能合成一个按钮** —— 合成一个之后，
用户分不清这次是不是花到外网的钱、也分不清答案是从网上来的还是从自己库里来的。

## 候选方案

A 走官方 `tools/search` + `tools/fetch`：结构固定、摘要/片段分层现成、计费口径写在官方文档里
（代价：绑一家计费，没有免费兜底）。

B 走第三方搜索服务（含第三方 MCP 客户端）：仓库里只留下 `McpSearchSource` 的 class 骨架与
注册注释，**当时没有正式比较过**第三方的成本与返回结构。

## 决定

选 A。`ToolSource.kt` 抽出接口 `suspend fun search(q, count, needContent): List<Result>` +
`suspend fun fetch(url): String`，`OfficialSearchSource` 是唯一实现，注册表
`ToolSources.register()` 留位给以后。`rerank_score < 1.5` 的结果默认折叠；
每次成功搜索计一次并在会话内可见（小于 $0.01 显示「< $0.01」）。
放弃 B 的代价：没有第二家可切；换来的是「模型看到的摘要」与「UI 看到的片段」同一份来源。

## 把握程度

medium —— 接口与计费口径抄的是官方文档原文，但台账里卡 D6 仍是 **pending**，这条决定还没上线跑过。
