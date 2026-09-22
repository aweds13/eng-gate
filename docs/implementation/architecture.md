# 总体架构分层与端到端数据流

> **路径约定**：实现包根为 `src/timeflow/`（下文 `core/`、`api/`、`storage/` 等均在其下）。

## 一、分层架构（自外向内的抽象）
```
┌─────────────────────────────────────────────┐
│ ① 交互/壳   pywebview 桌面窗口（可选） + Web 前端（src/web，手写无构建） │
└───────────────┬─────────────────────────────┘
                │ HTTP (fetch /api/...)
┌───────────────▼─────────────────────────────┐
│ ② API 层     FastAPI (REST)                  │
│              - 给前端 / 给 AI(读+新增) / 给外部集成   │
└───────────────┬─────────────────────────────┘
                │ 调用（纯 Python 上下文）
┌───────────────▼─────────────────────────────┐
│ ③ 核心领域层  core/（业务逻辑，模块化、错误隔离）        │
│   tasks·focus·review·feedback·academic·team·memo·facts  │
│   ledger（解读层：只读事实算账）                            │
└───────────────┬─────────────────────────────┘
                │ 读写（标准库 sqlite3，**非 ORM**）
┌───────────────▼─────────────────────────────┐
│ ④ 存储层     storage/（SQLite + schema 迁移 v5 + 同步 LWW） │
└───────────────┬─────────────────────────────┘
                │
┌───────────────▼─────────────────────────────┐
│ ⑤ 外部集成    getaways/（**空占位**：知识资产句柄 / 学校通知接口均未实现） │
└─────────────────────────────────────────────┘
```

> ⚠️ **形态现状**（2026-09-18 审计）：桌面窗口入口 `timeflow.app.main` 已写好，但 **pywebview 未安装**，
> 实际会回退到浏览器；「双击即用」的桌面形态**尚未真机验证**（见审计报告 GAP-NF-11）。

## 二、端到端数据流（一套任务，从建到记账）
```
用户(桌面/手机) → 新建任务(可带截止日/是否进 My Day)
   → api/ → core/tasks 校验状态 → storage 落库(SQLite, 带时间戳+version)
   → 到期/逾期 → core/ledger 读逾期集合算债务(项数+天数/程度，不折算时间)
   → 从任务发起专注 → core/focus 落 session(status=进行中)
   → 结束专注 → ①落库 ②发 focus.finished 事实 ③订阅器联动当日反馈
                ④绑定任务时长可按事实归因 ⑤前端刷新
   → core/ledger 读 facts 算投入（专注小时 / 复习张数 / 产出一条数 / 手动投入单列）
   → 完成任务 → 发 task.completed（可撤销发 task.uncompleted；设了重复则生成下一次）
   → 顶部轻量摘要（债务 + 投入 + 复习 + 产出）温和呈现
```

## 三、事实层与解读层（重构地基）

```
业务线(tasks/focus/review/memo/…) --record()--> 事实层 facts（SQLite，唯一真源）
                                        │
                                        ├─ publish() ──► 订阅器（core/focus/subscribers.py）
                                        │                 └─ 跨线联动：如 focus.finished → 当日反馈累加
                                        ▼
                                  解读层 ledger（按当前心智模型算账，只读 facts）
```

- `facts` 只记「发生了什么」：`kind` 自由字符串，高频值放 `value_num/value_text`，`extra` JSON 兜底，`revision/supersedes` 预留。
- 事件总线**同步执行**（publish 返回时订阅者已处理完）、订阅者异常隔离并记入 `facts.errors`（对应 SR-NF6 局部错误隔离）。
- **订阅者已接入**（第 2 步起）：`core/focus/subscribers.py` 负责 `focus.finished` → 反馈累加；
  订阅者按业务线各自成文件，业务线之间不直接调用（新增事实 kind 见 `modules.md` 的「事实 kind 总表」）。
- **换心智模型只换解读层，事实不动**。
- 存储边界（按 `../specification/conventions.md` 数据分流）：**计算型**（专注/完成/复习/产出/手动投入）已落结构化 `facts`；
  **沉淀型内容**（任务完成记录、任务信息、备忘、产出）落 Markdown：**已落地**（G 批 · T-G4/T-G5）——
  每天一个 md 写到**用户指定的独立目录**（`core/vault.py`），**数据库是权威、md 是产物**
  （md 手改不读回、下次导出覆盖；撤销之后 md 跟着变）。
  引用句柄用 `obsidian://` **只读跳转**（T-G5：Vault 名字 + 可选根目录；
  导出目录落在 Vault 里会被**三处拦住** —— 红线 `SR-F8.2` 做成不变量，而不是靠注释提醒）。
- 旧表 `ledger_entries` 已降级为**兼容/迁移来源**（解读层不读）。

## 四、三条关键边界（设计取舍）

1. **业务与存储分离**：`core/` 只做领域逻辑，不碰存储细节（用连接对象执行 SQL）；`storage/` 负责连接、schema 迁移与同步（可维护，SR-NF6）。
2. **本软件与知识资产解耦**：知识/笔记**只存引用句柄**（Vault 路径 / KB-ID），读写交给「知识资产项目」，本软件不碰 Vault 文件——避免膨胀与耦合（SR-F8.2）。
3. **事实与解读解耦**：业务线只发事实，账目由解读层算；跨线联动只允许发生在订阅器里（避免业务线互相直接调用形成网）。

## 五、模块目录对照
| 分层 | 目录 |
|---|---|
| 交互/壳 | `src/timeflow/app/`（pywebview 启动器，未安装时回退浏览器）+ `src/web/`（手写 HTML/CSS/JS，**无构建步骤、无打包器**，由服务端直出） |
| API | `src/timeflow/api/` |
| 核心领域 | `src/timeflow/core/`（tasks/ledger/focus/feedback/academic/review/team/memo/facts） |
| 存储 | `src/timeflow/storage/` |
| 外部集成 | `src/timeflow/getaways/`（预留） |
| 配置 | `src/timeflow/config.py` |
