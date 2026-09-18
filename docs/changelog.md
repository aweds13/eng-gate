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
