# modules.md — 模块表（SR → 模块）

> 一个模块只干一件事；边界写「不负责什么」比写「负责什么」更重要。

## 壳（Kotlin）

| 模块 | 负责 | 不负责 | 对应 |
|---|---|---|---|
| `net/ChatClient` | 组装 OpenAI 兼容请求、SSE 逐块解析、断流、取消、重试 | 不拼 UI、不存数据 | SR-F1 |
| `net/ToolsClient` | `list-models` / `search` / `fetch` / `balance` | 不做结果排序（那是服务端 `rerank_score`） | SR-F4 SR-F7 |
| `net/ModelCatalog` | 清单拉取、兼容解析、缓存、失效降级 | 不做「快/强」映射（D9） | SR-F4 |
| `store/Db` | SQLite schema、迁移、事务 | 不存图片本体 | SR-F8 |
| `store/Repo*` | 会话/消息/分支/书/页的读写与约束（禁循环引用） | 不做渲染决策 | SR-F2 F5 F8 |
| `media/Camera` `Pickers` `Compressor` | 拍摄、选取、压缩、落盘、缩略图 | 不做 OCR（v1） | SR-F5 |
| `secret/KeyVault` | Keystore 加解密、三槽凭据 | 不参与任何业务判断 | SR-F4 C10 |
| `bridge/Bridge` | 四类桥方法的注册与类型校验 | 不实现业务 | — |
| `update/BundleUpdater` | 校验/解压/切换/回滚前端 bundle | 不做在线热更分发（v1 手动放包） | SR-NF5 |

## 前端（离线 bundle）

| 模块 | 负责 | 不负责 | 对应 |
|---|---|---|---|
| `ui/ChatView` | 气泡、流式追加、停止/重生成入口 | 不直连网络 | SR-F1 |
| `ui/ReasoningFold` | 思考内容折叠与计时 | — | SR-F1 |
| `ui/BranchBar` | 版本切换器、回主干、分叉入口 | 不决定树结构（读 store） | SR-F2 |
| `ui/TreeView` | 树骨架与跳转 | — | SR-F2 |
| `ui/CompareView` | 同分叉点并排对比 | — | SR-F2 |
| `md/Renderer` | markdown-it + KaTeX + Shiki + 表格 + Mermaid | 不做公式推断（C6） | SR-F3 |
| `input/PageRef` | `#p12` 解析、胶囊、候选弹层 | 不做页码分配（用户说了算） | SR-F5 |
| `ui/BookShelf` | 书库、页网格、补拍 | — | SR-F5 |
| `calc/Pyodide` | 懒加载 SymPy、表达式抽取、结果格式化 | **不下"正确"结论**（C8） | SR-F6 |
| `ui/VerifyBar` | 核验条三态与三方视角 | — | SR-F6 |
| `ui/SearchBar` | 搜索结果条、引用、计次 | 不混「搜我的资料」（D12） | SR-F7 |
| `ui/Settings` | 主题/字号/预设/关于/导出导入 | — | SR-F9 SR-F8 |

## 共用

| 模块 | 负责 |
|---|---|
| `pricing/Estimate` | 按北京时间判高峰/低谷，估算花费（只展示，不参与逻辑） |
| `logging/Redactor` | 日志里 key 一律打码 |

## 明确不建

- 不做「工具注册表 / 插件系统」（N2）。
- 不做「云端同步器 / 账号系统」（D5）。
- 不做「网页抓取器 / 浏览器扩展」（C2）。
