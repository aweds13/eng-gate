# Changelog — timeflow

> 按时间倒序记录每次有意义的功能/变更。遵循 Conventional Commits 类型。

## [未发布] — 文档体系重建 · 事实层（第 0 / 0.1 / 1 / 2 步 + 第 3 步迁移）

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

### 重构 · 第 1 步：ledger.summary 改读 facts
- `ledger.summary()` 的投入项从 facts 读 `focus.finished`，按 `occurred_at`（完成日）归属当日；对外 API 不变。
- 新增 `tests/test_ledger_summary.py`：事实计入 / 放弃不计入 / 完成日边界 / API 集成。
- 质量门：pytest 68 passed / ruff 0 / mypy 0（32 文件）/ 五层对齐 PASS / 护栏自测 PASS。

### 重构 · 第 2 步：各业务线发事实（事实层成为唯一出口）
- **专注线**：`focus.finished` 订阅器（幂等接线）→ 当日反馈 `focus_minutes` 按事实重算落库；
  `today_focus_minutes`/`self_check`/`sessions_by_task` 改读 facts。
- **任务线**：完成发 `task.completed`、撤销发 `task.uncompleted`（成对事实，不删历史）；
  `POST /api/tasks/{id}/uncomplete`、`GET /api/tasks/{id}/facts`。
- **复习线**：复习完成发 `review.completed`（当日同卡去重）；`ledger.summary` 新增 `review_count`；
  `GET /api/mydays?include_reviews=1`、`GET /api/review/{id}/facts`。
- **口径定案**：`ledger_entries`（旧路径/手动投入产出）与 facts（新路径/唯一真源）不合并聚合、不重复计账。
- **可执行验收**：MVP 主链靶子转真实通过（验收 2 passed）；新增 LF-1 真机脚本 `tools/lf1_live_check.py`。
- 质量门：pytest 109 passed + 2 deselected / 验收 2 passed / 覆盖率 85.47% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 3 步：旧数据迁移（schema v5）
- 历史**已完成任务**幂等回填 `task.completed` 事实：`value_num=NULL`（不估时）、归属 `updated_at`、
  `extra.migrated=True`；缺列旧库（v1 tasks 无 due_date）不失败。
- 历史复习记录**不回填**（无逐次时间戳，不伪造时间，记缺口 A-015）。
- 质量门：pytest 111 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 4 步：前端补交互（把已打通的数据链接到界面）
- **进行中态**：`focus_sessions.status` 新增 `进行中`；`start_session` 不再直接置 finished（未结束不计投入）；
  重复开始拒绝（400）；结束不存在/重复结束分别 404 / 幂等；新增 `GET /api/focus/active` 支持重开页面恢复计时。
- **前端（`src/web/index.html`，单文件无构建）**：
  - 今日页：标题 + 截止日 + 「加入今天」勾选；任务卡片「完成/撤销完成 / 加入·移出 My Day / 专注 / 记录 / 删除（二次确认）」；
    债务程度温和一行；到期复习卡并入今日。
  - 专注页：走动计时器 + 「结束 / 记中断 / 放弃」，结束后今日专注分钟与反馈即时刷新。
  - 复习页：三态反馈 + 今日复习张数；习惯页：显示今日专注分钟并回填已存反馈。
  - 修首屏空白（此前只在点击导航时才渲染）；统一错误 toast（温和不弹窗式告警）。
- **测试**：新增 `tests/test_web_frontend.py`（前端入口/调用路径/API 契约/主链 15 项）+ 进行中态 5 项；
  LF-1 真机脚本扩到含「进行中不计投入 / 重复开始被拒 / 前端页面可达」。
- 质量门：pytest 131 passed + 2 deselected / 验收 2 passed / 覆盖率 85.83% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

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
