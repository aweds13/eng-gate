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

> **路径约定**：实现包根为 `src/timeflow/`（`import timeflow.*`）；`src/web/` 是前端静态资源。

| 模块 | 一句话职责 | 对应 SR |
|---|---|---|
| `src/timeflow/app/` | 桌面壳（pywebview 窗口，不可用时回退浏览器） | SR-NF1/2/4 |
| `src/web/` | Web 前端界面（`index.html` 主壳 + `app.css` + `sw.js` + **`offline.js` 手机离线引擎**，无构建步骤） | SR-NF1/2/4, SR-NF17 |
| `src/timeflow/api/` | FastAPI REST（供前端 + 外部/AI 接口） | SR-F7.3, SR-NF16 |
| `src/timeflow/core/tasks/` | 任务管理（CRUD/My Day/逾期/Repeat/子任务/软删除） | SR-F1 |
| `src/timeflow/core/facts/` | 事实层：只记「发生了什么」+ 同步事件总线（事实与解读解耦） | —（重构地基） |
| `src/timeflow/core/ledger/` | B 系统记账（投入轴/产出轴/债务/摘要/周结算，只读 facts） | SR-F2 |
| `src/timeflow/core/insights.py` | 可视化数据底座（逐日时序 / 按任务分组分布；后端出数据、前端出图） | SR-F2.7, SR-NF3 |
| `src/timeflow/core/focus/` | 计时与专注（番茄/普通/白名单/勿扰）+ **业务线订阅器** | SR-F3 |
| `src/timeflow/core/feedback/` | 每日反馈/习惯打卡与 streak/自检 | SR-F4 |
| `src/timeflow/core/academic/` | 学业追踪（GPA/学分/课程档案/考核项） | SR-F5 |
| `src/timeflow/core/review/` | 复习间隔重复（FSRS 调度 + 三态反馈 + 撤销反馈） | SR-F6 |
| `src/timeflow/core/team/` | 团队/执行者/AI 协作 | SR-F7 |
| `src/timeflow/core/memo/` | 备忘录 + 知识资产引用句柄 + 产出/手动投入事实 | SR-F8 |
| `src/timeflow/storage/` | SQLite 数据层 + schema 迁移（v17） + 备份/恢复 | SR-F9 |
| `src/timeflow/core/syncpack.py` | 跨端同步包（`timeflow-sync` v1）+ **先规划后执行**的合并 + 冲突留痕 | SR-F9.2 |
| `src/timeflow/core/ai.py` | AI 接口的边界与守卫（只读 + 新增 + 只能勾自己建的；默认关） | SR-F7.3 |
| `src/timeflow/config.py` | 配置加载 + 校验（pydantic / env 覆盖） | SR-NF14 |
| `src/timeflow/getaways/` | 知识资产/学校通知等外部集成（**预留占位**） | SR-F8.2, SR-F10 |

> 读法：先 `modules.md`（按 SR 分组的实现落点 + 事实 kind 总表）→ `architecture.md`（分层+数据流）→ `traceability.md`（SR→模块）。
> 要看代码，去 `src/timeflow/<子包>/` 找。未实现项在各文件里显式标注，不宣称已有落点。
