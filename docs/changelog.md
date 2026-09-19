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

### 重构 · 第 5 步·OP-8：Repeat 触发收口
- `complete_task` 完成后对设了重复的任务调用 `process_repeats`（此前是**死代码**，无任何触发点）。
- 幂等与审计：以 `task.repeat.generated` 事实（subject=原任务，extra 带 `next_task_id`/`next_due`/`repeat_days`）
  作为「已生成」依据 —— 同一任务只生成一次，重复完成/重复扫描不再生成。
- 生成的下一次继承标题/分组/周期/My Day；无截止日的重复任务不生成。
- 新增 `tests/test_task_repeat.py`（7 项）。
- 质量门：pytest 138 passed + 2 deselected / 验收 2 passed / 覆盖率 86.42% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 5 步·OP-6：软删除 + 撤销
- 新增状态「已删」（`STATUS_DELETED`）：`DELETE /api/tasks/{id}` 改为**软删除**（置状态 + 发 `task.deleted` 事实），
  不再物理删行；默认视图（列表 / My Day / 逾期 / 债务）统一隐藏（`HIDDEN_STATUSES`）。
- 可逆：`POST /api/tasks/{id}/restore`（默认恢复「未开始」，可指定）+ `GET /api/tasks/deleted` 回收站；
  前端删除后提示条给「撤销」，今日页有回收站区。
- 彻底删除保留为 `purge_task()`（显式调用、不在界面暴露）。
- 新增 `tests/test_task_delete.py`（9 项）；`interactions.md` 自查表 OP-6 回填 → **OP-1~OP-8 全部闭环**。
- 质量门：pytest 147 passed + 2 deselected / 验收 2 passed / 覆盖率 87.17% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 5 步·产出轴物化 + 全部任务视图
- **产出轴物化**：`POST /api/ledger/output` 除写 `ledger_entries`（兼容）外，发 `output.manual` 事实；
  撤销走 `output.retracted` 反向事实（幂等、不删历史）；新增 `GET /api/ledger/outputs`、`DELETE /api/ledger/output/{id}`；
  `ledger.summary()` 新增 `output_count`（今日产出 − 已撤销），**与投入轴分开展示、互不折算**。
- **前端**：新增「全部任务」视图（补 OP-2 残留：未进 My Day 的任务可见、可加回今天）；备忘录页新增
  「今日产出」区（记一笔 + 撤销）；摘要行加产出条数；移动端底栏加「任务」入口。
- 新增 `tests/test_output_axis.py`（11 项）。
- 质量门：pytest 161 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 5 步·复习撤销 + LF-2 逾期处置
- **复习撤销（F6 OP-27 可逆）**：`review.completed` 事实的 `extra.before` 存复习前卡片快照；
  新增 `review.undo_review` 回退 FSRS 字段（due/interval/ease/reps/lapses/state）并追加 `review.undone` 反向事实；
  账本 `review_count` 改为按 `review.reviewed_today()`（当日完成 − 当日已撤销）计数；已撤销的那次不阻止重新复习入账；
  API `POST /api/review/{item_id}/undo`；前端复习卡加「撤销上次」。
- **LF-2 逾期处置**：逾期卡片新增「推到明天」（`PATCH due_date`）与「取消」（二次确认）；债务随摘要即时重算。
- 新增/扩展测试 5 项（`tests/test_review_line.py`）；`ACCEPTANCE.md` LF-2 转 ✅。
- 质量门：pytest 166 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 重构 · 第 5 步·手动投入物化（收尾）
- 单位定案（用户确认）：手动投入 = **秒**，与 `focus.finished` 同口径。
- `memo.add_invest_entry` 除写 `ledger_entries`（兼容）外发 `invest.manual` 事实；新增
  `retract_invest_entry`（`invest.retracted` 反向事实、幂等）与 `list_invests`（含 `minutes`）；
  API `POST /api/ledger/invest`（负值 400）、`GET /api/ledger/invests`、`DELETE /api/ledger/invest/{id}`。
- `ledger.summary()` 新增 `manual_hours`（今日有效手动投入 /3600），**单列、不并入** `invest_hours`；
  前端备忘录页新增「今日手动投入」区（按分钟输入、内部换算成秒），摘要行显示「手动投入 Xh」。
- `ledger_entries` 至此仅为兼容/迁移来源（手动投入与产出都走事实层）。
- 新增 `tests/test_invest_axis.py`（12 项）；台账 A-016 记录单位决策。
- 质量门：pytest 179 passed + 2 deselected / 验收 2 passed / 覆盖率 88.80% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 文档/代码债务收尾（实现层对齐）
- 修正 `docs/implementation/modules.md`、`docs/implementation/architecture.md`、`docs/implementation/traceability.md`、
  `docs/implementation/README.md`：**路径从搬家前的 `src/core/...` 改为实际的 `src/timeflow/...`**；
  删掉对**不存在文件**的宣传（`status.py`/`repeat.py`/`subtask.py`/`debt.py`/`settle.py`/`stats.py`）；
  架构图「SQLAlchemy」更正为「标准库 sqlite3」；数据流改写为第 2 步后的真实链路（发事实 → 订阅器 → 只读 facts）；
  新增「事实 kind 总表」（含第 2/3/5 步新增的 `task.deleted/restored/repeat.generated`、`review.undone`、`output.*`、`invest.*`）。
- 未实现项改为**显式标注**（周结算 OP-15/可视化、习惯热力图、`getaways/` 外部集成），不再宣称已有落点。
- 更新 `docs/CODING_GUIDELINES.md` §1/§2/§6/§9：项目结构补 `src/timeflow/`、`tools/`；质量门口径更新为当前实测值
  （179 passed / 验收 2 passed / 覆盖率 88.80%）；worktree 由「强制」改为「可选」（与当前单工作区 checkpoint 流程一致）；
  新增「发现文档与代码不一致必须先登记再对齐、未实现项必须标注」的硬要求。
- 清理死代码：`core/focus/timer.py` 的 `_publish_started()`（定义后从未调用；`focus.started` 不作为事实存在）。
- 登记：`复盘/文档债务清理-实现层对齐.md`（D-01~D-12 逐条发现与处置）。

### 第 6 步 · 周结算视图（OP-15 / SR-F2.5）
- 新增 `ledger.weekly_summary()` + `GET /api/summary/weekly?week_of=`：周 = **周一→周日**（`week_of` 传该周任意一天），
  只读事实层（撤销照扣），返回 `focus_hours / manual_hours / review_count / output_count / debt_count(周日快照)
  / days[7] / active_days / steady_note`；非法日期 400。
- 温和口径：`days` 固定 7 天（含 0，便于画走势）；`steady_note` 只如实描述「几天在投入」，**不设目标、不评价、不告警**
  （单测断言不得出现「目标/应该/警告/失败/落后」等词）。
- 前端专注页新增「本周投入」区：7 根柱状走势 + 数字行 + 一句温和提示；空态文案友好。
- 新增 `tests/test_week_summary.py`（12 项）；F2 规格/契约、modules/traceability/coverage 同步（可视化细项仍标注未实现）。
- 质量门：pytest 192 passed + 2 deselected / 验收 2 passed / 覆盖率 89.23% / ruff 0 / mypy 0（33 文件）/ 五层对齐 PASS。

### 第 7 步 · 更细可视化（SR-F2.7 / SR-F4.2 / SR-NF3）
- 新增 `core/insights.py`（可视化数据底座，**后端出数据、前端出图形**）：
  - `daily_insights(days)`：近 N 天逐日时序——专注/手动投入/复习/产出/习惯打卡/**债务当日快照**；无记录日也返回 0（走势连续）。
  - `group_insights(days)`：近 N 天投入**按任务分组（领域）分布**；只统计绑定任务的专注（未绑定不计入，
    不制造假归因）；多分组任务如实重复计入（界面注明）；无分组归「未分组」。
- 新增 `GET /api/insights/daily`、`GET /api/insights/groups`（`days` 1~90，越界 400）。
- 新增 `GET /api/habits` + `feedback.list_habits()`：补齐此前缺失的**习惯列表**接口（带 streak 与近 90 天打卡日期）；
  前端习惯页改为列表 + **日历热力图**（53 周 × 7 天，列=周、行=周一→周日），修掉「刷新后习惯消失」（原靠 sessionStorage 记 id）。
- 前端新增「统计」页：近 30 天投入曲线（SVG）+ 按分组的投入分布条 + 债务快照；桌面导航与移动底栏各加入口。
- 新增 `tests/test_insights.py`（14 项）；F2/F4 规格与契约、modules/README/traceability/coverage 同步
  （债务时间热力图仍标注未实现）。
- 质量门：pytest 209 passed + 2 deselected / 验收 2 passed / 覆盖率 90.32% / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。

### 第 8 步 · 时间热力图（SR-F2.7 / SR-NF3 的「债务/储蓄 曲线 + 时间热力图」）
- 新增 `insights.heatmap(days)` + `GET /api/insights/heatmap`（1~400 天，默认 365）：逐日**多指标**
  ——专注分钟 / 手动投入分钟 / 复习张数 / 产出条数 / **债务当日快照**（未完成且当时已逾期，已删归档不计）。
- 前端统计页新增「时间热力图（近一年）」：53 周 × 7 天日历网格（列=周、行=周一→周日），
  **可切换维度**（专注/手动投入/复习/产出/债务）；颜色深浅=当天数值相对最大值；
  空说明「那天没记」，不写成失败（温和口径）。
- 口径统一：`heatmap()` 与 `daily_insights()` 共用同一个 `_cell()` 取数，避免两处口径分叉。
- 新增/扩展 `tests/test_insights.py`（+5 项：多指标、债务快照逐日点亮、400 天上限、API 与边界）；共 18 项。
- 质量门：pytest 214 passed + 2 deselected / 验收 2 passed / 覆盖率 90.45% / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。
- 至此 SR-NF3 列举中「债务/储蓄曲线+热力图」「习惯日历热力图」均已实现；未实现项：复习卡片+进度条、今日完成度进度环、GPA 雷达。

### 第 9 步 · SR-NF3 剩余可视化形态（进度环 / 复习进度条 / GPA 多维）
- **今日完成度进度环**（今日页顶部）：`已完成 ÷（已完成 + 仍在手）`；只统计今天的清单与今天完成的，
  **不翻旧账、不做目标对标**；没有任务时显示「—」而不是 0%（不制造挫败）。
- **今日复习进度条**（复习页）：`今日已复习 ÷（已复习 + 仍到期）`，与到期卡片列表同屏（SR-NF3「卡片+进度条+到期列表」）。
- **学业多维概览**（学业页）：新增 `GET /api/grades`（`academic.all_grade_rows` 此前**没有任何读接口**）
  + 雷达图（GPA 4.0 制 / 5.0 制 / 平均分 / 学分 / 课程覆盖）+ 条形明细 + 成绩明细列表；
  各轴各自归一到本图最大值，**只用于看是否均衡，不跨人比较**（避免变成打分器，守 conventions 红线）。
- 前端新增可复用组件：`ring()`、`progressBar()`、`radar()`、`gpaRadar()`、`todayCard()`。
- 至此 **SR-NF3 列举的六类形态全部实现**；`docs/implementation/traceability.md` 的「未实现」标注同步清空。
- 质量门：pytest 215 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。

### 第 10 步 · 延后域补强（学业 / 团队 / 备忘录 / 习惯 / 同步）
- **学业**：新增 `upcoming_assessments()` + `GET /api/assessments/upcoming?days=14`（OP-25 课程提醒）——
  只提醒**未录成绩**的考核项，`days_until` 负=逾期 / None=无截止日，排序「逾期优先 → 无截止日最后」；
  新增 `DELETE /api/assessments/{id}` 与 `DELETE /api/grades/{id}`（此前**只能建不能删**）；前端学业页加
  「临期与逾期（14 天内）」区、添加考核项表单、成绩删除。
- **团队**：`TaskOut.assignments`（任务直接带回分配）+ `team.assignments_for_task()` ——
  任务卡片显示「谁负责 / 进展到哪」，并按状态给「开始 / 完成 / 恢复」按钮（OP-31/32 的反馈闭环）；
  `assign_task` 补校验：任务不存在 404、执行者空 400（此前会产生指向不存在任务的分配）。
- **备忘录**：`POST /api/memos/{id}/to-task`（OP-36 顺手建任务：保留备忘录并写回 `task_id`）
  + `DELETE /api/memos/{id}`（不连坐任务）。
- **习惯**：`PATCH /api/habits/{id}` 改名、`DELETE /api/habits/{id}` 删除（打卡记录一并删除，避免孤立历史）；
  前端习惯卡片加「改名 / 删除」。
- **同步**：`sync.status()` + `GET /api/sync/status` —— 只报告事实（冲突条数/最近时间），
  跨端传输未实现时 **`enabled=false`，不谎报"已同步"**；设置页显示在线/离线与同步说明。
- **修 bug**：`sync.log_conflict` 原用**秒级时间戳当主键**，同一秒两次冲突触发
  `sqlite3.IntegrityError` —— 改为随机 id（由新测试发现）。
- 新增测试 `tests/test_academic_line.py`（9 项）、`tests/test_habit_memo_line.py`（10 项）、
  `tests/test_team_line.py`（7 项）+ 同步状态 3 项；共 **246 passed**。
- 质量门：pytest 246 passed + 2 deselected / 验收 2 passed / 覆盖率 92.34% / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。

### 第 11 步 · 并发修复 + 学业制式切换 + 加权平均成绩（用户反馈驱动）
- **修 `快速点击顶部导航 → 「操作未完成」`**：根因在**后端**——`create_app` 让所有请求共用一个
  `sqlite3.Connection`，而 Connection 非线程安全，一个请求的 `commit()` 会打断另一个请求的事务
  （实测复现：并发 80 次读写 16 次异常，异常类型含 `cannot commit - no transaction is active`、
  `another row available`、`bad parameter or other API misuse`；真机 132 并发请求 33 次 500）。
  修复：新增 `storage/db.thread_local()` **按线程分发连接**的代理（路由代码零改动）；
  真机复测 **180 并发请求 0 个 500**。新增 `tests/test_concurrency.py`（5 项回归守卫）。
- **前端竞态防护**（同一问题的客户端侧）：渲染加**序号**（后点的那次说了算）+ `AbortController`
  （切视图即取消上一组请求）；`AbortError` **静默**处理（取消不是错误，不该弹提示）；
  强调色先读 localStorage 再校正，消除首屏闪色。
- **GPA 制式可在页面切换**（用户指出「4.0 与 5.0 应该是要切换的」）：学业页新增「4.0 制 / 5.0 制」按钮，
  切换即按该制式重算显示并记住选择；不再只弹一句"去改 config.toml"
  （写死默认值仍归 `config.toml`，前端不偷偷改本地配置）。
- **新增加权平均成绩**（用户给定公式）：`weighted_average()` = `Σ(单科学分 × 单科成绩) / Σ单科学分`，
  用**百分制原始分**加权，与 GPA（绩点加权）**并存、同屏、互不替代**；学分为 0/负 的记录不参与加权；
  `GET /api/gpa` 一次返回 `{gpa, credits, scale, weighted_average, weighted_credits}`。
- 质量门：pytest 265 passed + 2 deselected / 覆盖率 92.03% / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。

### 前端接缝重构 R1 + R2（视觉/行为零变化）
- **R1 抽样式 + 颜色令牌化**：新增 `src/web/app.css`（语义令牌 `:root` + `[data-theme="dark"]` 预置 + 布局/元件样式），
  `index.html` 删内联 `<style>` 改引 `/app.css`（735→689 行）；JS 模板里的硬编码色清零
  （只剩 `<meta name="theme-color">`，它不接受变量）。
- **R2 事件委托 + 壳级模态**：58 处内联 `onclick/onkeydown` → `data-action` + `ACTIONS` 注册表 + 全局委托；
  新增壳级模态 `ask()` 取代 `prompt()`、`alert()` 改 `toast()`。
- 新增护栏 6 项（无硬编码色 / 令牌亮暗齐备 / 无内联事件 / 动作必须注册 / 无 alert·prompt）
  + `tools/web_live_check.py`（用 `node --check` **真解析页面脚本** —— JS 语法错会整页白屏而字符串测试抓不到）。
- 质量门：pytest 252 passed + 2 deselected / 覆盖率 92.34% / 真机自检 8 项 OK。

### 前端接缝重构 R3 · 三栏布局（SR-NF4 落地）
- **壳改三栏**：`index.html` 顶层改为 `.shell`（左 `.rail` 导航 / 中 `#main` / 右 `.sidebar`），
  文案与挂载点布局交给 CSS：**≥1024px 三栏网格（200 / 1fr / 340）**，1023px 以下退回单列
  （左栏变成主区上方的横向导航、右栏落到主区下方），≤640px 仍用底部 Tab；未引入任何框架/打包器。
- **计时器常驻右栏**（R3 的核心）：「进行中」的计时与「结束 / 记中断 / 放弃」渲染在右栏 `#focusRail`，
  `render()` 每次渲染都重画右栏 —— **切到任何页面计时都不丢**，分页不再各自维护一个计时器
  （专注页改为只说明"去哪里结束"，全页只剩一个 `#clock`）。
- **右详情面板（渐进聚焦）**：任务卡片新增「详情」，点开在右栏 `#detailRail` 显示字段
  （标题/状态/截止/分组/重复/分配）+ 最近事实流水 + 与列表一致的动作；切视图自动收起，默认不占屏。
- 新增护栏 3 项（`tests/test_web_frontend.py`：三栏骨架与网格断点 / 计时器只有一个主人 / 切视图清详情），
  真机自检加 3 项（骨架齐全 / 宽屏网格存在 / 计时器归右栏 + 数据源 `GET /api/focus/active` 可用）。
- 质量门：pytest 268 passed + 2 deselected / 验收 2 passed / 覆盖率 92.03% / ruff 0 / mypy 0（34 文件）/
  五层对齐 PASS / 护栏自测 PASS / LF-1 真机 PASS / 前端自检 12 项 OK。
- ⚠️ 诚实声明：**布局视觉与点击手感需人工在浏览器确认**（本环境无浏览器，只能保证骨架、脚本语法与接口可用）。

### 前端接缝重构 R4 · 设置页（暗色主题 + 强调色 + 收拢调整项）
- **统一设置页**（用户要求「有些功能的调整可以统一放在一个设置界面里」）：宽屏左栏导航补「设置」入口
  （此前只有移动端底部 Tab 能进），页面分「常用 / 外观 / 学业 / 数据与同步 / 入口」；
  收拢主题、强调色、GPA 制式、在线与同步状态、各域入口；学业页的制式切换保留（两处一致）。
- **双主题接通**（SR-NF1）：`<html data-theme="dark|light">` + `localStorage('tf_theme')` +
  `matchMedia` 跟随系统三选；暗色令牌 R1 已备好，本阶段只接线。
- **强调色可改**：预设色板写在 `app.css` 令牌区（`--accent-1..6`），JS 用 `getComputedStyle` 读
  （守住 R1「颜色只住在 CSS」）；修 bug：此前每次渲染都用配置值覆盖 `--accent`，用户选的强调色会被打回默认。
- **修挤压/遮挡**（用户真机反馈）：新增行原来 `input{flex:1}` + 日期框/按钮不收缩，
  一行超宽时**「添加」按钮溢出被遮住**；改为允许换行 + 输入框 `flex:1 1 220px`、`min-width:0` +
  **按钮 `flex:none`**。学业页考核项/成绩录入由「一行塞 4~5 个控件」改为 `.form/.field` 表单块（标签在上）。
- 护栏 +5（`tests/test_web_frontend.py`）+ 真机自检 +4（共 16 项）；`render` 增视图白名单（未知视图名报警而非静默空屏）。
- 质量门：pytest 273 passed + 2 deselected / 验收 2 passed / 覆盖率 92.03% / ruff 0 / mypy 0（34 文件）/ 五层对齐 PASS。

### 用户反馈轮 U-06~U-12 · 布局断点 / 日期默认 / 回收站硬删 / 任务详情 / 正圆勾选 / 工程审计
- **布局**（用户：全屏时列表应该在最左边，不该跑到上面）：三栏门槛 1024→**980px**，单列块改 `max-width:979px`
  —— 原来 980/1023 两个断点**重叠**，左栏同时套用"固定列宽"与"横向 banner"两套规则；
  三栏由 grid 改 **flex**，并顺带修掉"媒体块规则被后面的基础规则覆盖"（`main` 的宽度上限与上边距曾被清掉）。
- **日期默认今天**（用户要求）：`todayISO()` 按**本地时区**拼串（不用 `toISOString()`，东八区晚上会差一天）；
  今日页与全部任务页的截止日默认今天，想改再点进去选。
- **「加入今天」说明**：文案简化（勾选保留 —— `due_date` 与 `is_myday` 是两个维度，日期默认今天 ≠ 自动进今天）。
- **回收站可彻底删除 / 清空**（用户：纯软删除会越积越多）：`purge_task` 收紧为**只接受回收站里的任务**
  （活动任务 400，必须先软删除），新增 `purge_deleted_tasks`；
  `DELETE /api/tasks/{id}/purge`、`POST /api/tasks/purge-deleted`（固定路径须声明在 `/{task_id}` 之前）；
  界面两处二次确认 + 「不可恢复」措辞。
- **任务详情**（用户：要看到完成时间和详细）：`humanTime()` 输出「完成于 2026年09月18日 17:31」；
  任务卡显示「完成于 …／未完成」状态徽标；详情面板补「建于/更新于」+ 最近 12 条事实流水 + 选中卡片描边。
- **完成圈改正圆**（用户：椭圆的不好看）：`.check` 显式 `appearance:none`/`padding:0`/`min-width:22px`/`border-radius:999px`。
- **工程审计**（用户：是不是有些地方没做完整）：修 2 处**文档失真**（`modules.md` 称习惯不能增删、
  `traceability.md` 称周结算/可视化未实现 —— 实际都已实现并有测试）；查出 3 处**"规格有、界面没有"**
  （OP-9 任务编辑、OP-12 子任务、OP-11 分组管理）登记为 GAP-02/03/04；
  GAP-01「任务步骤/关联文件」数据库无此概念，未擅自开工。
- **工具**：`tools/ui_ab.py` —— 用现后端跑任意历史提交的前端，便于并排对比"改前/改后"。
- 质量门：pytest 284 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（34 文件）/ 前端自检 17 项 OK。

### 全量五层审计 + 文档失真修正 + 任务重规划（文档为主，无功能改动）
- **方法**：写脚本逐条到代码里找证据（路由从 `api/app.py` 解析、表结构从 `db.py` 解析、
  前端视图/动作从 `index.html` 解析），**源文件读不到就直接报错**，不许静默给"没做"的结论。
- **结果**：**做到 40 / 半成品 9 / 没做 22**（其中 4 条是规格自标「二版/后置」）。
- **修 6 处文档失真**：`modules.md`（习惯"未实现"过期、SR-F3.4 写"靠同步转发专注状态"实际不存在、
  "179 项"过期、学校任务同构的乐观表述）、`traceability.md`（周结算/可视化"未实现"过期）、
  `architecture.md`（"Vite 构建入口"不存在、getaways 占位说明）、`ACCEPTANCE.md`（AC-11 pywebview 未验证）。
- **新增**：`复盘/全量审计报告-五层一致性与缺口登记.md`（GAP-F1-01…GAP-NF-11 逐条带证据 + 审计边界）
  与 `复盘/任务重规划-剩余工作.md`（A–E 五批剩余任务，含依赖/验收/3 个待定口径）。
- **审计脚本自身查出 3 个假判定**并修正（拿错源文件、条件过松、`--shadow` 令牌误命中）—— 已记入报告。
- 质量门：pytest 284 passed + 2 deselected / 验收 2 passed / ruff 0 / mypy 0（34 文件）/ 前端自检 17 项 OK。

### 强制框架：git + 台账 + 门禁三方对账（治"文档偏移 / 前后端接缝断裂 / 后端做不完整"）
- **问题复盘**：`复盘/文档偏移与约束框架复盘.md`（用户指出三件事 → 我的核实 → 决策与边界）。
- **机器可读台账**：新增 `docs/traceability.toml`（88 条：done 42 / partial 22 / todo 22 / deferred 2），
  每条 = 状态 + **可验证断言**（file/text/route/table/column/ui/test）+ gaps；
  生成器 `scripts/seed_traceability.py`（一次性初始化，之后台账本身是真源）。
- **六项对账**：`scripts/audit_progress.py` —— ①提交带 `Task:` ②任务号已登记 ③**声称=证据**（逐条实跑断言）
  ④**文档与代码同提交** ⑤门禁有落盘产物 ⑥进度可从 git 重建；**不通过退出码 1 → 不许提交**。
- **门禁落盘**：`scripts/run_gates.py` 跑全套门禁并把结果写 `gates/last.json`（入库），
  提交里的 `Gates:` trailer 因此有产物支撑；含"改了 src 必须同提交改台账/changelog/CHECKPOINT"的提交前检查。
- **覆盖率门槛写进配置**（GAP-NF-08）：`pyproject` 的 `addopts` 加 `--cov=timeflow --cov-fail-under=70`。
- **协议新增 §九 强制框架**：六条硬规矩（无任务卡不开工 / 必须带 Task: / 文档同提交 / 门禁落盘 /
  审计不过不提交 / CHECKPOINT 带台账状态变更）+ 台账状态词表 + 标准动作 + "一条线一条线"的节奏。
- **执行过程复盘**：`复盘/框架落地执行复盘.md` —— 框架第一次运行就拦下 7 个问题：
  ①断言里的 `(` 被当正则 ②门禁脚本被 Windows 中文输出解码搞崩 ③结论行抓成 ResourceWarning
  ④验收被覆盖率门误伤 ⑤**`gates/last.json` 自指悖论**（产物自己也在被记录范围内 → tree 永不相等；
  而 rev 因"门禁必须提交前跑"时序上也对不上 → 改为时效校验）⑥覆盖率门槛没进配置（GAP-NF-08）
  ⑦台账自身缺必填校验与反向覆盖。全部已修。

### F1 主线 · T-A1 分组管理（契约 OP-11 / SR-F1.3 收口）
- **后端**：`groups.py` 补 `get_group / rename_group / delete_group / toggle_task_group /
  tasks_in_group / groups_of_task`；**删除分组只解绑、不删任务**；改名到已存在的分组 = 合并（不留同名组）。
- **API**：`POST /api/groups`（空名 400、**重名 400**）、`PATCH /api/groups/{id}`（404/400，改名合并幂等）、
  `DELETE /api/groups/{id}`（返回解绑任务数）、`GET /api/groups/{id}/tasks`（点分组看任务）、
  `POST /api/tasks/{id}/group`（`{name,on}`，按名字加入/移出，缺组自建）。
- **前端**：设置页新增「分组管理」区（新建/改名/删除 + 计数）；任务详情面板新增「所属分组」chips，
  点一下即加入/移出（选中显示 ✓）；分组列表做了缓存避免每个任务卡都请求。
- **测试**：`tests/test_task_groups_line.py`（11 项：领域层 8 + API 3）。
- **工具**：新增 `tools/ui_dom_probe.mjs`（**假 DOM 渲染探针**）并加进门禁 —— 在本机跑不了浏览器的情况下，
  把 9 个视图各真渲染一遍，抓 TypeError／未注册动作／空渲染。定式门禁因此从 9 项升到 10 项。
- 台账：`SR-F1.12` 与 `OP-11` partial → **done**（缺口 GAP-F1-08 消除）；`DELIVERY.READY` 证据补 2 条路由。
- 质量门：pytest **295 passed** + 2 deselected / 验收 2 passed / ruff 0 / mypy 0 / 五层 PASS /
  DOM 探针 9/9 / LF-1 PASS / 前端自检 PASS / 审计通过。

### F1 主线 · T-A2 子任务树（契约 OP-12 / SR-F1.6 收口）
- **后端**：`subtask_progress / subtasks / create_subtask / set_task_parent`（+ `_would_cycle` / `_autocomplete_parent`）。
  **子任务全完成 → 父任务自动完成**（链式向上，每层都过"子任务是否全完成"的校验）；**禁止成环**
  （自己作父、挂到自己的子/孙任务下都 400）；`parent_id=null` 可脱离父任务。
- **API**：`GET/POST /api/tasks/{id}/subtasks`、`POST /api/tasks/{id}/parent`；
  `TaskOut` 新增 `subtask_done/subtask_total`（父任务卡直接显示「步骤 1/3」）。
- **前端**：详情面板新增「步骤（子任务）」——进度徽标 + 列表（勾选即完成，最后一步完成时父任务自动完成）
  + 「添加一个步骤」（回车即加）+ 每个子任务可「脱离」；任务卡片显示步骤进度。
- **修两个真 bug**（都是自测/单测抓出来的）：
  ① `update_task` 用 `v is not None` 过滤，导致 `parent_id=None` / `due_date=None` 这类**清空操作被静默忽略**
     → 改为按"键是否存在"判断；
  ② `complete_task` **没有挂"子任务全完成 → 父任务自动完成"**（原始需求 SR-F1.6 的联动），只做了反向拦截
     → 补上，并在最后一个子任务完成时触发。
- **测试**：`tests/test_task_subtasks_line.py`（12 项，含成环、脱离、联动、进度、可空字段清空）。
- 台账：`SR-F1.8` 与 `OP-12` todo → **done**（缺口 GAP-F1-04 消除）；done 45→49。
- 质量门：pytest **307 passed** + 2 deselected / 验收 2 passed / ruff 0 / mypy 0 / 五层 PASS /
  DOM 探针 9/9 / LF-1 PASS / 前端自检 PASS / 审计通过。

### F1 主线 · T-A3 任务编辑（契约 OP-9 收口）
- **前端**：详情面板新增「编辑」态（标题 / 截止日 / 分组 / 重复 / 是否在今天）；
  保存走 `PATCH /api/tasks/{id}`；**已完成任务也能编辑，但不改写历史完成事实**；
  切视图/切任务自动退出编辑态（避免残留半截表单）。
  「改 ddl」由此补齐 → 契约 OP-10（逾期处置四选一）随之闭环。
- **修一个真 bug**：`PATCH /api/tasks/{id}` 把 `KeyError`（任务不存在）与 `ValueError` 一起吞成 **400**，
  还会把 `str(KeyError)` 的引号一起显示（`detail: "'任务不存在: xxx'"`）→ 改为 **404 + 「任务不存在」**。
- **测试**：`tests/test_task_edit_line.py`（8 项：改字段 / 清空可空字段 / 改截止重算债务 /
  已完成任务历史不动 / 404 与 400 / 未列入白名单字段被忽略 / 债务程度分档）。
- 台账：`SR-F1.13`、`OP-9`、`OP-10` → **done**；新增 T-A3；done 49→53。
- 质量门：pytest **320 passed** + 2 deselected / 验收 2 passed / ruff 0 / mypy 0 / 五层 PASS /
  DOM 探针 9/9 / LF-1 PASS / 前端自检 PASS / 审计通过。
- **段1（T-A1~T-A3）到此收口**：分组管理、子任务树、任务编辑三条都做完，可以人工验收这一段。

### 段2 设计决策定案（提醒 / 附件打开方式 / 优先级）—— 只定口径，未动代码
- **提醒**（SR-F1.4 Remind me + SR-NF17）：`tasks.remind_at` + **到点发系统通知 + 设置页开关（默认关）**；
  界面同时标出今天/临期/过期；移动端只标不通知；**通知选型属新增运行时依赖，动手前先出方案给用户确认**。
- **附件/要求链接**（SR-F1.4 + SR-F5.3 + N20）：打开方式**三层** ——
  默认按格式（网页新标签 / 目录开目录 / 文档类定位文件夹 / 其它只到文件夹）→ 设置可切换
  （到文件夹 / 直接打开 / 按格式）→ **直接打开白名单**（用户维护扩展名）；`file://` 链路须真机验证，
  不通则降级"复制路径 + 提示"，**失败不许静默**。
- **优先级**：三档 高/中/低（默认中）；排序统一 `截止日 → 优先级 → 创建时间`；Important 视图 = 高优先级；
  明确不做 1–5 与拖拽排序。
- 共同原则：**默认保守 + 显式放行 + 失败必提示**。
- 文档：`复盘/段2设计决策-提醒与附件打开方式.md`（新）、`复盘/任务重规划-剩余工作.md`（B 批改写为定案版）、
  `复盘/新窗口交接卡.md` 与 `复盘/交接-重构进度.md`（刷新为"段1 完成 / 段2 待做"）。

### F1 主线 · T-B1 任务备注 `note`（SR-F1.4 备注落地，schema v5 → v6）
- **schema v6**：`tasks` 加 `note` 列（**向后兼容的加列迁移**：先查 `PRAGMA table_info`，幂等、重复连接不报错；
  缺 `tasks` 表的残缺库跳过不失败）。v1 的历史建表语句**保持原样**，列由 v6 加。
- **领域/API**：`Task.note`、`create_task(note=)`、`update_task` 白名单加 `note`；`TaskIn/TaskOut` 带 `note`；
  `PATCH /api/tasks/{id}` 可写、可**清空**（存 null，不留空串）；改别的字段不会顺手抹掉备注。
- **前端**（渐进聚焦）：详情面板编辑态多一个「备注」文本域；非编辑态有备注时显示（保留换行）；
  **列表卡片不显示备注**（护栏钉住）。
- **口径**：备注是**沉淀型内容**，不发 `facts`、不进账本（投入/债务/产出都不受影响）；已完成任务可补备注，
  但**不改写历史完成事实**（OP-9 边界）。
- **跨端**（顺手做完的交叉点）：`sync.merge_task` 带上 `note`；远端记录**没带 note 字段时不清空本地备注**
  （老客户端/旧快照不静默丢数据）。
- **工具**：`scripts/audit_progress.py` 的 `columns()` 现在也认 `ALTER TABLE ... ADD COLUMN` 加的列
  —— 否则 `column:` 断言永远看不到迁移新增的字段（T-B2/B3/B5 也要靠它）；
  `tools/ui_dom_probe.mjs` 的假 DOM 渲染探针**补上右栏详情面板**（只读态 + 编辑态各渲染一遍）——
  视图循环覆盖不到它（默认没选中任务），T-B1 的备注输入正好在那个模板里。
- **测试**：`tests/test_task_note_line.py`（14 项：迁移幂等/缺表不失败/缺列兜底/建与读/改写与清空/
  改别的字段保留备注/已完成任务历史不动/不发事实不动账本/不动债务/领域直调/同步三条）；
  `tests/test_web_frontend.py` +1（详情可写可读、列表不显示）。
- 台账：`SR-F1.4` todo → **partial**（备注已做，提醒/附件未做）；新增 `T-B1`。
- 质量门：见 `gates/last.json`（pytest / 验收 / ruff / mypy / 五层 / 护栏自测 / DOM 探针 / audit / LF-1 / 前端自检）。

### F1 主线 · T-B2 优先级 `priority` + 三处排序统一（SR-F1.2，schema v6 → v7）
- **schema v7**：`tasks` 加 `priority`（`ALTER TABLE ... ADD COLUMN priority TEXT DEFAULT '中'`，幂等；
  老行补默认「中」—— **不猜**，不按截止日远近偷偷标高标低）；缺 tasks 表的残缺库跳过不失败。
- **口径**：三档 **高 / 中 / 低，默认「中」**；**非法值一律拒绝**（领域层 ValueError / API 400），
  **不可清空**（没有"无优先级"这一态）；明确不做 1–5 数字分级、不做拖拽排序（段2 决策）。
- **排序统一（本任务的主要价值）**：`list_tasks` / `myday_tasks` / `overdue_tasks` 一律
  **截止日 → 优先级 → 创建时间**，无截止日排最后；三处共用同一个 `_ORDER_BY` 片段，
  逾期栏"SQL 结果 + 无截止日 My Day"两拨合并后用 `_sort_key` 重排，口径与 SQL 版一致
  （逾期栏以前只按截止日排，列表**根本没排序**）。
- **前端**：任务卡片与详情显示优先级色标（高=实心强调色 / 中=描边 / 低=灰，颜色只住 `app.css` 的
  `.prio*`）；编辑态可改优先级。
- **Repeat**：下一次**继承优先级**（优先级属于任务定义，不该每周期掉回默认）；**备注不继承**
  （备注常是这一次的具体说明，抄下去会误导）。
- **跨端**：`sync.merge_task` 带 priority —— 远端没带时保留本地值，带了但非法则拒绝（不写库、不静默降级）。
- **测试**：`tests/test_task_priority_line.py`（18 项：v7 迁移幂等/默认值/非法拒绝/三处排序/
  合并后排序/不发事实不动账本/Repeat 继承/同步三条）；`tests/test_web_frontend.py` +1（色标与编辑入口）。
- **工具**：假 DOM 探针的详情面板检查补上优先级（只读态要有色标、编辑态要有 `editPriority`）。
- 台账：`SR-F1.2` todo → **partial**（排序已统一，拖拽按决策不做）；新增 `T-B2`。

### F1 主线 · T-B3 三视图 Important / Planned / Flagged（SR-F1.3，schema v7 → v8）
- **schema v8**：`tasks` 加 `flagged INTEGER DEFAULT 0`（手动标记位；幂等加列，老行一律 0=未标记
  —— **不帮用户猜**"哪些算标记"）。
- **口径定在领域层**（`tm.tasks_in_view`，界面不自己筛）：`important` = **优先级「高」**（复用 T-B2 的字段，
  不另造"重要"概念）；`planned` = **有截止日**；`flagged` = **手动标记位**。
  基线同「全部任务」：只隐藏 归档/已删（**完成的仍如实显示**）；排序沿用统一口径（截止日→优先级→创建时间）。
  **未知视图名 → 400，不静默返回全部**（否则用户会以为筛选生效了）。
- **API**：`GET /api/tasks?view=important|planned|flagged`；`POST /api/tasks/{id}/flag`（翻转标记，幂等），
  `PATCH` 白名单也带 `flagged`。
- **前端（可达性）**：三个视图加入 `VIEWS` 白名单与左栏导航；「全部任务」页与每个智能视图顶部都有
  互跳行（`smartViewNavHTML`），设置页「入口」也列出 —— **手机端（≤640px）左栏导航被 CSS 隐藏**，
  所以不能只靠左栏，否则手机上根本进不去。卡片新增「标记 / 取消标记」按钮与已标记小旗（`.flag`）。
- **跨端**：`sync.merge_task` 带 `flagged`（远端没带则保留本地；带了以远端为准）。
- **测试**：`tests/test_task_views_line.py`（14 项：v8 迁移/口径/基线/排序/未知视图/API/标记幂等/
  不发事实不动账本/同步两条）；`tests/test_web_frontend.py` +1（**处处可达**护栏）；
  `tools/web_live_check.py` +1（智能视图可达）；`tools/ui_dom_probe.mjs` 视图从 9 个扩到 **12 个**。
- 台账：`SR-F1.3` todo → **done**（GAP-F1-03 消除）；新增 `T-B3`。

### F1/F5 主线 · T-B4 附件 / 要求链接 + 打开方式三层（SR-F1.4 附件 + SR-F5.3，schema v8 → v9）
- **schema v9**：`tasks.attach` 与 `course_assessments.attach`（**任务与学业考核项共用同一字段**）
  + `app_settings` 通用 key/value 表（幂等加列；老行 NULL=没有附件；缺表跳过不失败）。
  附件 = JSON 数组 `[{target, title}]`：只存**引用**（网址或本地路径），不复制文件内容；类型现场判定，
  不存冗余 kind（免得出现"标着网页其实是路径"的脏数据）。
- **新建模块 `core/attach.py`（口径只有一份，界面不复述）**：
  - ① 网址 → 浏览器新标签；目录 → 打开该目录；本地文件 → 见 ②③；
  - ② 模式三选（**服务端持久化**）：`folder` 只到文件夹（**默认，最保守**）/ `direct` 直接打开 /
    `auto` 按格式（文档类**定位到该文件** `explorer /select`，其它只到文件夹）；
  - ③ **直接打开白名单**（用户维护扩展名，`auto`/`folder` 下都放行直接打开）；
  - **安全底线**：可执行/脚本类（`.exe/.bat/.cmd/.ps1/.lnk/.msi/...`）**任何模式都不直接打开**，
    且**不许进白名单**（点开本地文件等于从文档里启动程序，这条底线不能靠配置绕过）；
  - **失败必提示**：路径不存在 / 打不开 → `action="copy"` + 原因，界面复制路径并出声（不许静默）。
- **实施方式与原设计的偏离（如实记录）**：设计文档原估"靠本地服务返回 `file://` 让浏览器导航，需真机验证"。
  实施时改为**后端执行本机动作**（Windows `explorer` / `os.startfile`，其它平台 `xdg-open`/`open`）——
  浏览器不会替网页开资源管理器，`file://` 从 http 页面跳转默认被拦，"跳转文件夹"只有本机进程能可靠做到；
  `file_url` 仍随响应返回作兜底展示。理由与安全代价记在 `复盘/段2设计决策-提醒与附件打开方式.md` §七。
- **安全守卫（新增）**：会在本机开东西/改设置的接口（`POST /api/attach/open`、`PUT /api/settings/attach`）
  加**来源守卫** —— 带 `Origin` 的请求必须是 `127.0.0.1/localhost/::1`，否则 403；且**模式与白名单只从
  服务端设置读**，不接受请求参数指定（否则任何网页都能要求"直接打开"）。
- **API**：`POST/DELETE /api/tasks/{id}/attachments[/{index}]`、`POST /api/attach/open`
  （支持 `dry_run` 只解析不执行）、`GET/PUT /api/settings/attach`、
  `POST/DELETE /api/assessments/{id}/attachments[/{index}]`。
- **前端**：任务详情新增「附件 / 要求链接」区（列表 + 添加 + 打开 + 删除）；任务卡片显示「附件 N」徽标；
  学业页新增「考核项」列表（要求备注 + 要求链接就近挂/点，此前考核项只在 14 天临期窗口里可见）；
  设置页新增「附件打开方式」（三选 + 白名单维护 + 常用区快捷入口）。
- **测试**：`tests/test_attach_line.py`（23 项：v9 迁移/坏 JSON 容错/规则矩阵/安全底线/失败降级/
  dry_run/设置校验/接口 CRUD/跨站 403/学业复用/跨端合并）；`tests/test_web_frontend.py` +1（前端接线与"不许静默"）；
  `tools/web_live_check.py` +8（**真服务 + 真文件系统**验证规则链）；假 DOM 探针详情面板补附件检查。
- 台账：`SR-F1.4` 备注/附件已做（提醒仍缺，保持 partial）；**`SR-F5.3` todo → done**（GAP-F5-01 消除）；
  新增 **T-B4** 与 **OP-46**（附件三层打开）。

### F1 主线 · T-B5（前半）提醒 `remind_at` + 界面标注 —— **通知通道待选型**（SR-F1.4，schema v9 → v10）
- **schema v10**：`tasks` 加 `remind_at`（本地时间 `YYYY-MM-DDTHH:MM`，可空=不提醒；幂等加列、老行 NULL）。
  校验：空格分隔也接受并归一；**只给日期不行**（提醒要具体到时间，避免"猜一个时间"）；
  空值 = 清除（存 NULL）；非法格式 400 —— **不静默忽略**。
- **界面口径只在领域层**（`tm.reminder_state`）：`over`（到点/过点）/ `today` / `soon`（7 天内）/ `later`；
  **完成/取消/归档/已删之后不再催**（不打扰基调）；`tm.due_reminders(now)` 是"该提醒了"的只读数据源
  （`remind_at <= now` 且任务还活着，按时间正序）。
- **API**：`GET /api/reminders/due?now=`、`GET /api/reminders`（带 `state`）；`TaskOut.reminder_state` 由后端算，
  前端不自己拿当前时间比（免得口径分叉）。
- **前端**：详情编辑态可设提醒（`datetime-local`）、只读态显示「提醒 2026-09-20 08:30（今天提醒）」、
  卡片上提醒徽标（到点=强调色实心）、**今日页「该提醒了」区**（不接通知通道也不瞎）；
  设置页新增「提醒」一节，**如实写明"系统通知通道尚未接入"并给出选型文档位置 —— 不放按了没反应的假开关**。
- **Repeat 不继承提醒**（提醒是"这一次什么时候叫我"，抄到下一周期会变成乱响）。
- **测试**：`tests/test_remind_line.py`（12 项：v10 迁移/时间校验与归一/清除/四档状态/完成后不催/
  due 只取活着的且有序/API 与 400/不发事实不动账本/Repeat 不继承/跨端合并）；
  `tests/test_web_frontend.py` +1（前端接线 + **不许谎报通道**）；
  假 DOM 探针补 `/api/reminders/due` 桩（顺带抓出并修掉一处模板字符串里写反引号导致的**语法错误**）。
- 台账：`SR-F1.4` 补 remind_at 证据（**仍 partial**：缺"到点发系统通知"）；新增 `T-B5`（**partial**，gaps 写明三案）。
- **未做（等你一句话）**：系统通知通道。三案见 `复盘/段2设计决策-提醒与附件打开方式.md` §八。
- **框架修正**：审计 ⑥「进度重建」原来假设"挂了 `Task:` 的条目一定该是 done"，于是**有意拆分的任务**
  （T-B5 前半已提交、后半等用户选型）被误判成"台账漏更新"并卡住提交。现在 `[exceptions]` 对 ⑥ 同样生效
  （逐条留痕 + 打印理由，修完删掉），条目继续如实保持 `partial` —— 不谎报完成，也不把"拆分"当"漏更新"。

### F1 主线 · T-B5（后半）到点系统通知：计划任务方案 B′（SR-F1.4，段2 收口）
- **用户决策**：在 A（应用内轮询，关掉不响）/ **B′（计划任务 + 系统通知，关掉也响）**/ C（第三方库）之间
  选了 **B′**；并且确认过"直接调用系统闹钟 App"这条路走不通（微软没开放往「闹钟和时钟」里建闹钟的接口，
  只能打开它）。
- **新增 `core/remind.py`（通知通道）**：
  - `schtasks` 注册计划任务 `timeflow-reminders`（`/SC MINUTE /MO 1`，`/F` 覆盖）；
    命令用 **`pythonw.exe`**（不闪控制台窗口，否则每分钟闪一次黑框比不提醒还烦）+ **脚本与库都给绝对路径**
    （计划任务的工作目录不是项目根）。
  - `show_notification()`：PowerShell 调 WinRT **系统通知**（标题/正文走环境变量，中文不乱码）；
    失败退 `msg`；都不行就**如实返回失败**（不静默）。
  - `set_enabled()`：打开 = 写设置 + 注册任务；关闭 = 写设置 + **删除任务**（可逆、不留痕）；
    **注册失败设置不落库**（避免"以为开了其实没开"）；`uninstall_task` 先查后删（不做字符串匹配 ——
    受限环境下错误文案里也有 "cannot find"，会把"删不掉"误报成"本来就不存在"）。
  - `notify_due()`：同一条提醒（同 `remind_at`）**只弹一次**，改了时间重新弹；**失败不标记**（下次重试）；
    一次到点太多（>3 条）**合并成一条汇总**（关机几天回来不轰炸）。
- **新增可执行入口 `src/timeflow/app/remind.py`**（计划任务调它；也支持 `--check` / `--now` / `--test` 排查），
  自己补 `sys.path`，不依赖工作目录/PYTHONPATH。
- **API**：`GET/PUT /api/settings/reminder`（开关，PUT 有来源守卫）、`POST /api/reminders/test`（当场试一下）。
- **前端**：设置页「提醒」一节 = 开关（**默认关**）+ 「试一下」+ 状态（是否已注册任务 / 上次通知时间 /
  上次结果 / **上次错误**）；如实写明"关掉应用也响，但**注销/关机不响**"。
- **真机实测（本次）**：`show_notification` **真的弹出了 Windows 通知** ✅；
  **计划任务注册在本沙箱里做不了**（实测 `schtasks` 报 "The system cannot find the path specified"、
  `Get-CimInstance` 直接"拒绝访问" —— 沙箱屏蔽了任务计划程序/WMI 面），所以注册那一步
  **由用户在真机点开关验证**；界面会把失败原因原样显示，不会静默。
- **测试**：`tests/test_remind_channel.py`（15 项：命令构造纯函数/开关与失败不落库/去重与重试/合并汇总/
  已完成不提醒/脚本入口能独立跑/API 与跨站 403/默认不碰系统）；
  `tests/test_web_frontend.py` 的提醒护栏改为覆盖真开关与诚实边界；
  `tools/web_live_check.py` +2（状态可读、开关拒跨站）。
- 台账：**`SR-F1.4` → done**、**`T-B5` → done**（**删掉之前那条例外**：修一条删一条）、新增 `OP-47`。
  **段2（T-B1~T-B5）全部收口。**

### F1 主线 · T-B5b 提醒方式：闹钟式（留在屏幕上 + 循环响铃）/ 温和 —— 用户反馈驱动
- **触发**：用户看了实际提醒后说「这个提醒不是闹钟那种吗，效果很差」——普通 toast 右下角浮几秒就没了，
  确实"提不住人"。
- **改法（用 Windows 官方 toast 能力，仍不引第三方依赖）**：新增**提醒方式**设置
  （`reminder.style`，默认 **`alarm`**）：
  - `alarm` = **警报通知**：`<toast duration="long" scenario="alarm">` + `<audio src="ms-winsoundevent:Notification.Looping.Alarm" loop="true"/>`
    → 预先展开、**留在屏幕上直到手动关掉**、**循环播放闹钟音**，并**能突破「专注助手/免打扰」**
    （见 [toast 元素](https://learn.microsoft.com/zh-cn/uwp/schemas/tiles/toastschema/element-toast)、
    [audio 元素](https://learn.microsoft.com/en-au/uwp/schemas/tiles/toastschema/element-audio)）；
  - `gentle` = 普通通知（几秒后消失）。
- **实现**：`build_toast_xml()` 直接产 XML（不再用 ToastText02 模板，才能控制 scenario/duration/audio），
  标题正文做 XML 转义（不转义会把 XML 弄坏、通知直接弹不出来）；`show_notification()` 按 style 弹；
  `notify_due()` 缺省跟随设置；`--test` 与 `POST /api/reminders/test` 也按当前方式弹。
- **前端**：设置页「提醒」顶部新增「提醒方式」两个按钮 + 说明（写清闹钟式的效果与代价）。
- **真机实测（已确认）**：按闹钟式弹了一条，**用户目视确认效果正确 —— 会一直留在屏幕上 + 有响铃**
  ✅（无需再自建"响铃窗口"）。
- **测试**：`tests/test_remind_channel.py` +6（闹钟 XML 的 scenario/duration/loop、温和 XML 无 scenario、
  XML 转义、默认值与设置校验、`show_notification` 真的把 XML 传下去、`notify_due` 跟随设置）；
  `tests/test_web_frontend.py` 护栏补「提醒方式」入口与措辞。
- 台账：新增 `T-B5b`（done）。
- **注册失败可自助诊断（用户点开关报错后加）**：`schtasks` 失败时，错误信息里**附上可直接粘贴的手动命令**
  （`manual_command_text()`）+ 一句"若应用跑在受限环境（沙箱/容器）里，系统调用会被挡"。
  实测查清：那条报错是**环境问题**（用户当时看的应用是我在 DSH 沙箱里启动的，沙箱屏蔽了任务计划程序/WMI），
  用更宽权限重跑同一条命令**成功创建并删除**了探针任务 → 命令构造本身没问题。

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
