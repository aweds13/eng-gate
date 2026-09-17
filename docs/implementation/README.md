# implementation（实现层）— 每条规格「具体如何实现」的抽象化

> 按「**模块名 + 一句话职责 + 关键设计取舍**」呈现，**刻意不贴源码**。上游 `../specification/`（SR），下游是根目录 `src/` 里的真实代码（按模块名去找）。
> 原则：抽象封装；每个关键机制给设计取舍/兜底，这是封装背后的价值。

## ⚠️ 实现前必读（防"做一半"）

本文件只回答「**哪个模块负责**」，**不回答「一个操作怎样才算做完」**——后者在契约层。
**直接按本文件写代码，必然产出"功能存在但没闭环"的半成品。**

实现顺序（硬约束）：
1. `../specification/conventions.md` —— 不能违反什么（横切基线）
2. `../contracts/interactions.md` —— 每个操作要走到哪一步才算做完（六要素）
3. `../contracts/flows.md` —— 多个操作串起来必须走通什么（触发→传导→落点）
4. **本文件 + `modules.md`** —— 最后由谁负责写

> 判定原则：**「存在」不等于「完成」。** 操作六要素齐备且契约验收通过，才算实现完成。

## 模块索引（对应规格领域）
| 模块 | 一句话职责 | 对应 SR |
|---|---|---|
| `src/app/` | 桌面壳（pywebview 窗口）+ Web 前端 UI | SR-NF1/2/4 |
| `src/api/` | FastAPI REST（供前端 + 外部/AI 接口） | SR-F7.3, SR-NF16 |
| `src/core/tasks/` | 任务管理（CRUD/My Day/逾期/Repeat/子任务/存档） | SR-F1 |
| `src/core/ledger/` | B 系统记账（投入轴/产出轴/债务/可视化） | SR-F2 |
| `src/core/focus/` | 计时与专注（番茄/普通/白名单/勿扰/多设备） | SR-F3 |
| `src/core/feedback/` | 每日反馈/习惯热力图/自检 | SR-F4 |
| `src/core/academic/` | 学业追踪（GPA/学分/课程档案/考核提醒） | SR-F5 |
| `src/core/review/` | 复习间隔重复（FSRS 调度） | SR-F6 |
| `src/core/team/` | 团队/执行者/AI 协作 | SR-F7 |
| `src/core/memo/` | 备忘录 + 知识资产引用句柄 | SR-F8 |
| `src/storage/` | SQLite 数据层 + schema 迁移 + 同步(LWW) | SR-F9 |
| `src/config.py` | 配置加载 + 校验（pydantic / env 覆盖） | SR-NF14 |
| `src/getaways/` | 知识资产/学校通知等外部集成（预留接口） | SR-F8.2, SR-F10 |

> 读法：先 `modules.md`（按 SR 分组的实现落点）→ `architecture.md`（分层+数据流）→ `traceability.md`（SR→模块）。要看代码，去根目录 `src/<package>/<module>/` 找。
