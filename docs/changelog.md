# Changelog — timeflow

> 按时间倒序记录每次有意义的功能/变更。遵循 Conventional Commits 类型。

## [未发布] — 文档体系重建 · 事实层（第 0 / 0.1 步）

### 文档
- **约定层**：新增 `specification/conventions.md`（横切基线，实现任何 SR 前必读）。
- **契约层**：新增 `contracts/interactions.md`（操作六要素）+ `contracts/flows.md`（动线契约）。
- **一致性**：统一为**五层**口径（intention / specification(+conventions) / contracts / implementation / taste）；`scripts/check_layers.py` 扩展为五层检查（含引用完整性）。
- **验收**：`ACCEPTANCE.md` 标注"MVP"术语两义 + 已知局限；补闭环验收指引。
- **本轮同步**：事实层进展回写 README / implementation / CODING_GUIDELINES；DESIGN/LEARN 状态改为「经决定撤回、暂不建」；交接文档质量门口径更新。

### 已知断层（待 MVP 重构解决）
- 契约层揭示多项"操作闭环/模块联动"缺口（专注结束不记账、完成后不记账等）。
- 详见 `../复盘/三层断裂诊断-实现与交互复盘.md`。

### 重构 · 第 0 步：事实层
- 新增 `src/core/facts/`：facts 表（schema v3）+ 进程内同步事件总线（异常隔离、通配订阅）。
- 专注 `finish_session` 结束即落事实并 `publish`；事实与解读层（ledger）解耦。
- 质量门：pytest 60 passed / ruff 0 / mypy 0（32 文件）/ 五层对齐 PASS。

### 重构 · 第 0.1 步：事实语义修正 + 历史回填
- 结束状态分 kind：只有正常结束记 `focus.finished`；暂停/放弃/记中断分别记 `focus.paused/abandoned/interrupted`，避免第 1 步误计入投入。
- schema v3→v4：幂等回填历史 `focus_sessions` → facts，保证 ledger 改读 facts 后旧数据不归零。
- 质量门：pytest 64 passed / ruff 0 / mypy 0（32 文件）/ 五层对齐 PASS / 护栏自测 PASS。

## [0.1.0] — 第一版完整（功能域 F1–F9 + GPA 制式切换）

### 新增
- **任务管理（SR-F1）**：My Day / CRUD / 逾期栏 / **多分组（AC-6）** / 子任务 / Repeat / 状态机；**无截止日但昨日未完成的 My Day 任务自动移入逾期栏（AC-4）**。
- **B 系统记账（SR-F2）**：逾期=债务（天数/程度），**专注=投入真实化**（invest_hours 不再硬编码 0），顶部轻量摘要 + 产出/投入流水。
- **专注计时（SR-F3）**：番茄/普通计时、绑定任务、中断三选（暂停/放弃/记中断）、白名单默认阻止非白名单、勿扰时段（含跨午夜）。
- **反馈/习惯/自检（SR-F4）**：每日复盘（计划vs执行差距）、习惯打卡+连续天数、自检消费 B 数据。
- **学业追踪（SR-F5）**：课程档案（学分/考核/任课）、考核项（权重/评分/备注）、GPA 手动录入；**GPA 4.0/5.0 制可切换（配置驱动 + API scale 参数）**，用分段绩点法封顶不越界。
- **复习间隔重复（SR-F6）**：现成 Python fsrs 库调度、反馈三态（记得/模糊/忘了 → Good/Hard/Again）、到期排序、外部执行源标签。
- **团队/AI 协作（SR-F7）**：任务分配（管理者→执行者）、进展回报（assigned/in_progress/done/blocked）、AI 接口（只读+新增）。
- **备忘录/知识资产（SR-F8）**：本地随手记、**只存引用句柄**（Vault 路径 / KB-id）、产出评价器接口。
- **存储/同步（SR-F9）**：schema 版本化迁移（v2）、LWW 同步（较新者胜、同 id 去重）、冲突日志不静默覆盖、sync_logs 表。

### 工程
- **schema 版本化迁移**：`SCHEMA_VERSION` 从 1 升到 2（多分组 + F3–F8 全部基础表：groups/task_groups/focus_sessions/habits/habit_logs/feedback_logs/courses/course_assessments/grades/review_items/memos/ledger_entries/team_assignments/sync_logs）。
- **质量门**：pytest **44 passed** / ruff 0 / mypy 0（strict）/ 五层对齐 PASS。
- 新增模块：`core/focus`、`core/feedback`、`core/academic`、`core/review`、`core/team`、`core/memo`、`core/sync`、`core/tasks/groups`。

### 待办（第二版 / 后置）
- SR-F2.8 重新规划 / 债务重组
- AI 接口写/改/删（当前只读+新增）
- SR-F10 学校通知监测脚本（以独立脚本实现，主工具只提供合作接口）
- 移动端 PWA 深联动
