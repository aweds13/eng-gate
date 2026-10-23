# architecture.md — 分层与取舍

> 本文件回答「**谁负责写**」。上游是 `../specification/`，下游是 `modules.md`。

## 1. 一句话

**一个安卓壳 + 一份离线前端 bundle，壳负责网络与存储，前端负责一切界面。**

```
┌───────────────────────────────────────────────┐
│  Android（Kotlin）                             │
│  ┌─────────────────────────────────────────┐  │
│  │ WebView  ← assets/web/ 里的离线 bundle    │  │
│  │   界面 / 渲染 / 树视图 / 输入解析          │  │
│  └───────────────┬─────────────────────────┘  │
│         JS Bridge（仅 4 类能力）                │
│  ┌───────────────┴─────────────────────────┐  │
│  │ 壳服务层                                  │  │
│  │  net     OkHttp + SSE 解析 + 重试          │  │
│  │  store   SQLite（会话/消息/分支/书/页）     │  │
│  │  media   相机/相册/压缩/私有目录            │  │
│  │  secret  Keystore 加密的密钥槽             │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
              ↓ HTTPS
        api.deepseek.com
```

## 2. 为什么是 WebView 而不是原生 Compose

| 方案 | 优 | 劣 | 判定 |
|---|---|---|---|
| **原生 Compose** | 手感最好 | KaTeX / 代码高亮 / Mermaid 全要重造；热更新靠插件化，很重 | ✗ |
| **PWA / 浏览器** | 零安装 | 用户要的是「App」；相机与相册权限受限；后台易被杀 | ✗ |
| **服务端起在本机** | 复用生态 | 手机上没有 Node；且用户明确否决电脑端（T2） | ✗ |
| **壳 + 离线 bundle** | 渲染生态直接用；热更新=换文件；安卓原生项目零可用 | 滚动性能不如原生 | ✓ |

**关键依据**：GitHub 上「安卓原生 + 树形分支 + 公式渲染」的开源项目实测 **0 个**（`intention/decisions.md` D13）。

## 3. 桥只有四类（不许长胖）

| 桥 | 方向 | 内容 |
|---|---|---|
| `net.chat` | JS→Kotlin→JS | 发起流式对话；Kotlin 推 `delta` 事件 |
| `net.tools` | JS→Kotlin→JS | search / fetch / list-models / balance |

> 工具层按 `ToolSource` 接口可插拔（decisions D16）：`OfficialSearchSource` 是默认实现，`McpSearchSource`
> 只留注册点、不实现连接。换源只改注册表，不改 UI 与桥协议。
| `store.*` | JS→Kotlin→JS | 读写信/会话/消息/分支/书/页 |
| `media.*` | JS→Kotlin→JS | 拍照、选图、压缩、路径解析 |

> **约束**：前端**不许**自己 `fetch` 外网。原因：密钥在壳里、CSP 只允许 `file://` 与桥。

## 4. 热更新怎么走

```
assets/web/version.json   ← {"version":"1.0.3","built":"2026-10-23T..."}
assets/web/index.html + bundle.js + katex/ + shiki/
```

- 换 bundle = 换 `assets/web/` 整个目录（由壳侧「检查更新包 → 解压到 files/ 覆盖 → 重启加载」）。
- 保留上一版到 `files/web-prev/`，出问题回滚。
- **不依赖 adb、不依赖重装 APK**（N1 / SR-NF5）。

## 5. 数据在哪

| 数据 | 位置 | 备注 |
|---|---|---|
| 会话 / 消息 / 分支 / 书 / 页元数据 | SQLite（App 私有目录） | WAL 模式 |
| 图片本体 | `files/books/<bookId>/<pageNo>/<hash>.jpg` | 入库压缩长边 ≤2048（SR-NF4） |
| 密钥 | Keystore 加密区 | 明文不落盘（C10） |
| 日志 | `files/logs/`，滚动 7 天 | key 打码 |

## 6. 三个高风险点（写代码前先验证）

1. **KaTeX 长会话性能**：1000 条消息 + 公式，WebView 里滚动是否掉帧 ⇒ `SR-NF2`。测不过的备选：虚拟滚动只渲染可视区。
2. **`list-models` 返回结构**：字段名未验证（`evidence.md` §5）⇒ 壳侧做**兼容解析**（`data[]` / `models[]` / 顶层数组都认）。
3. **SymPy 在 WebView 里跑**：Pyodide 体积大（~10 MB+），要么首次按需下载，要么退到「壳侧原生算」（不可行，安卓没 SymPy 运行环境）⇒ 倾向 **Pyodide 懒加载 + 缓存**，需实测启动耗时。

## 7. 目录（写代码时按这个铺）

```
src/dsmate/
  docs/                 ← 本套文档
  app/                  ← 安卓工程（Kotlin）
    app/src/main/
      assets/web/       ← 离线前端 bundle（构建产物）
      java/.../net|store|media|secret|bridge/
  web/                  ← 前端源码（Vite 构建 → assets/web）
  tools/                ← 构建与门禁脚本
```
