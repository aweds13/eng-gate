# evidence.md — 事实台账（intention 层）

> 这份文件只放**实测过的事实**，每条带来源。写规格时凡是引用数字，必须能指回这里。
> 规矩：**没实测的一律写「未验证」**，不许用「应该是」「一般来说」蒙过去。

## 1. 官方 API（来源：`https://api-docs.deepseek.com`，2026-10-23 抓取）

### 1.1 模型与价格

| 项 | 值 |
|---|---|
| 模型 | `deepseek-flash`（DeepSeek-V4.1-Flash-1017）、`deepseek-v4-pro`（DeepSeek-V4-Pro-0813） |
| 上下文 / 最大输出 | 1M / 384K（`max_tokens` ∈ [1, 393216]） |
| 默认输出长度 | 非思考 8K；思考 64K（`reasoning_effort=max` 时 128K） |
| 退役但兼容 | `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 仍被接受，按 Flash 计费 |
| 思考默认 | **enabled** |
| 思考模式限制 | `temperature` 无效；`top_p` 被夹到 0.95–1.0；`tool_choice` 的 `required` / 具名选择返 400 |
| 已废弃参数 | `frequency_penalty`、`presence_penalty` |

价格（每 1M token，低谷 / 高峰；项目只用来**估花费**，不参与逻辑）：

| 模型 | 输入·命中 | 输入·未命中 | 输出 |
|---|---|---|---|
| flash | $0.003 / $0.006 | $0.15 / $0.30 | $0.60 / $1.20 |
| v4-pro | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |

高峰 = 周一至周五 01:00–04:00、06:00–10:00 UTC（中国法定节假日除外），低谷为高峰半价。

### 1.2 其它端点（本客户端会用到的）

| 端点 | 用途 |
|---|---|
| `GET /api/list-models` | **模型清单**（SR-F4 的唯一真源） |
| `GET /api/get-user-balance` | 余额（可在设置里显示） |
| `POST /chat/completions` | 对话主接口（SSE） |
| `POST /v1/tools/search` | 联网搜索 |
| `POST /v1/tools/fetch` | 取网页正文（Markdown） |

### 1.3 Vision 规格

| 项 | 值 |
|---|---|
| 支持模型 | 仅 `deepseek-flash`（`deepseek-v4-pro` **不支持收图**） |
| 格式 | JPEG / PNG / GIF / WebP（按内容嗅探，不看扩展名） |
| 三种送法 | base64 data URL / 外链 http(s) / Files API `file_id` |
| `detail` | `low` / `high` / `original` / `auto`（low 缩到 512×512） |
| **硬约束** | 图片**只允许出现在 user 消息**；放 system/assistant 返 400 |
| 请求体上限 | 48 MiB |
| 单图上限 | base64 或外链 32 MiB；`file_id` 64 MiB；外链 ≤ 8192 字符 |
| 数量上限 | 单请求 ≤ 600 图；单边 ≤ 8192 px（≥15 张图时降到 4096 px） |
| 计费粒度 | **每图最多 1024 token**；小于约 544×544 会被放大，大图缩到总量约 1300×1300 再算 |

### 1.4 搜索 / 抓取

`POST /v1/tools/search` 请求字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 必填，1–128 字符，支持 `site:` / `-site:` / 引号短语 |
| `count` | int | 1–50，默认 10 |
| `ori_question` | string | 触发这次搜索的原始问题，≤128 字符，提升查询理解 |
| `localization` | string | 可选 IP，用于本地化结果 |
| `need_content` | bool | 是否在 `content` 里返回正文，默认 false |

返回 `results[]`：`rerank_score`（0–3，**≥1.5 算高质量**）、`title`、`url`、`snippet`（100–200 字，给 UI 显示）、`summary`（600–800 字，给模型读）、`content`（正文，`need_content=false` 时为空串）、`site_name`、`site_icon`。

`POST /v1/tools/fetch`：请求 `{url}`（≤8192 字符，禁带账号密码），返回 `{title, content}`（content 为 Markdown）。

计费：**$0.75 / 1000 次成功请求**。经 DeepSeek Harness / Claude Code / Codex 的 server-side tool calls 目前免费，**2026-11-01 00:00 北京时间起开始计费**。

## 2. 为什么必须真解释器（来源：arXiv 论文原文）

| 结论 | 数字 | 出处 |
|---|---|---|
| PAL 明显优于 CoT | GSM8K 65.6 → 72.0；**GSM-HARD 20.1 → 61.5** | [arXiv:2211.10435](https://arxiv.org/abs/2211.10435) |
| **模型写代码但自己心算执行 ≈ 没用** | 只有 23.2 | 同上 |
| PoT 优于「CoT + 计算器」 | 跨 8 数据集平均 +12% | [arXiv:2211.12588](https://arxiv.org/abs/2211.12588) |
| 代数题：让模型写算法 vs 只抽方程交 SymPy | 后者**高 20 点** | [arXiv:2304.09102](https://arxiv.org/abs/2304.09102) |
| 工具模式选错是主要失败源 | MATH500/AIME24 26.7% → 50.0% | [arXiv:2509.23292](https://arxiv.org/abs/2509.23292) |

**推论（写进 `SR-F6`）**：核验条的正确做法是**只抽式子交给 SymPy**，不是让模型写解释程序、更不是让模型自己心算。

## 3. Explore 的树（来源：`D:/repo/program/dsapp-probe/EXPLORE-逆向.md`）

- **卡片 = 独立对话线程**，自带 `messages`；项目 = 卡片树（`parentId` / `children` / `depth`）。
- 三种边语义不同：子卡片（读标题作**背景**主题）、发散卡片（读标题作**关联**主题）、**分支卡片（继承分支点之前的消息）**。
- 分支卡**不复制上下文**：`Ag()` 递归拉平 `branchingSourceId` 祖先链 → `splice` 到 `branchingSourceMessageId` → `"START"` 哨兵。
- 附件：图片存 IndexedDB `{id, dataUrl}`，正文用 Markdown `![](idb://<id>)` 引用；喂模型时转 multimodal。
- BYOK：三槽分离（对话 / 功能性 / 视觉），`credentials[slotKey] = {apiKey, baseURL, label}`。
- **它没有图片编号体系** —— 这正是本项目的差异点（N8）。

## 4. 官方 App（来源：`D:/repo/program/dsapp-probe/APK-功能盘点-REA.md`）

- 原生 Kotlin + Jetpack Compose，单 Activity（`com.deepseek.chat.MainActivity`），**不是 RN/Flutter/H5 套壳**。
- 13,147 类，R8 混淆（20,579 处描述符里只留 47 个 `com.deepseek.*` 名）。
- 权限只有 3 个：`INTERNET` / `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_MEDIA_PLAYBACK`。
- 值得抄：自研 markdown 方言词法器 `_DSFMLexer`、自研代码高亮、`ru.noties.jlatexmath` 渲公式、Mermaid 单开 WebView。
- 分叉入口文案：`message_press_edit_to_branch` = "Edit to branch"。
- 文件会过期：`invalid_file_ref_toast` = "The file has expired. Please re-upload." ⇒ 教材图不能长期托管（N9）。

## 5. 未验证（写代码前必须补测）

| 项 | 为什么不确定 |
|---|---|
| `GET /api/list-models` 的**返回结构** | 文档只给了端点，没给字段名；字段可能叫 `data[].id` 也可能别的 |
| 各模型是否支持 vision / thinking 的**能力字段** | 文档说明在 guide 里，未确认是否随 list-models 下发 ⇒ 客户端要做**探测兜底** |
| 官方 App 的请求体字段名 / SSE 事件名 | **未运行 APK、未抓包**（也不打算抓，见 T4） |
| 搜索结果的 `content` 长度上限 | 文档未给；要实测一次大页面 |
| Android WebView 里 KaTeX 长会话渲染性能 | 未实测；`SR-NF2` 要立判据 |
