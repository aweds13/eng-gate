# Changelog — timeflow

> 按时间倒序记录每次有意义的功能/变更。遵循 Conventional Commits 类型。

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
- **质量门**：pytest **44 passed** / ruff 0 / mypy 0（strict）/ 三层对齐 PASS。
- 新增模块：`core/focus`、`core/feedback`、`core/academic`、`core/review`、`core/team`、`core/memo`、`core/sync`、`core/tasks/groups`。

### 待办（第二版 / 后置）
- SR-F2.8 重新规划 / 债务重组
- AI 接口写/改/删（当前只读+新增）
- SR-F10 学校通知监测脚本（以独立脚本实现，主工具只提供合作接口）
- 移动端 PWA 深联动
