# dsmate — 手机上自己用的 DeepSeek 聊天客户端

> 一句话：**只用官方 API、只做聊天、专门为「啃教材 + 追分支」定制**的安卓客户端。

## 它不是什么

- 不是 Agent 平台，不做多工具编排，不接 MCP。
- 不是网页端的壳，**不抓网页端已渲染内容**（用户 2026-10-23 明确撤回这条路线）。
- 不逆向、不绕过风控、不实现 PoW 求解（见 `docs/specification/conventions.md` 红线 C1–C3）。

## 它是什么

| 能力 | 一句话 |
|---|---|
| 对话 | 官方 `api.deepseek.com`，OpenAI 兼容；思考开关、流式、重生成 |
| 模型自选 | 启动拉 `GET /api/list-models`，**模型列出来你自己点**，不做「快/强」代你决定 |
| BYOK | 自带 key、自带 baseURL、自带模型名；三槽分离（对话 / 功能性 / 视觉） |
| 树形分支 | 任意一条消息分叉，分支只存自己新增的消息，随时回主干 |
| 一窗一书 | 一个会话绑定一本教材，图片按**页码**编号，`#p12` 直接唤图 |
| 算式核验 | 关键式子丢给 SymPy 独立算，与模型答案并排比；不一致就如实摆出来 |
| 联网搜索 | 官方 `POST /v1/tools/search` + `POST /v1/tools/fetch`，带引用 |
| 本机存储 | 全部数据在本机，手动导出备份；教材图**不上云长期托管** |

## 目录

```
src/dsmate/
  README.md                  本文件（入口）
  ACCEPTANCE.md              验收清单
  docs/
    intention/               为什么做：需求 N*、决策台账
    specification/           必须做到什么：SR-F* / SR-NF* / 红线
    contracts/               怎样才算真的走通：操作六要素 + 动线
    implementation/          哪个模块负责：分层 + 模块表
```

## 读文档的顺序（防「做一半」）

1. `docs/specification/conventions.md` —— **不能违反什么**（红线）
2. `docs/contracts/interactions.md` + `docs/contracts/flows.md` —— **怎样才算做完 / 走通**
3. `docs/implementation/architecture.md` —— **谁负责写**

`docs/intention/` 是给「为什么要这么设计」用的，改需求时先改它。

## 状态

- 2026-10-23：文档层在建。**代码一行没写**，所有实现相关表述以 `docs/` 为准。
- 决策来源：与用户的 grill-me 问答，逐条记在 `docs/intention/decisions.md`（**哪一问、答了什么**），
  未确认的一律标 `待确认`，不许当成事实往下写。
