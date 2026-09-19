# 模块实现落点（按规格分组）

> 对每条规格指出负责模块 + 靠什么机制/取舍保证成立。只给「模块名+职责+取舍」，不贴源码。
> **路径约定**：实现包根为 `src/timeflow/`；下文中的 `core/`、`api/`、`storage/` 等均指 `src/timeflow/` 下的子包。

## SR-F1 任务管理 → `core/tasks/`
- **My Day / 逾期栏 / 状态机 / 子任务 / Repeat**（SR-F1.1/1.2/1.5/1.6/1.8）：都在 `manager.py`。
  取舍：**昨日未完成自动进逾期栏而非静默消失**（如实、不假装）；逾期与否由截止日+今天判定，**不强推**；
  **软删除**（`status=已删`）而非物理删行，默认视图统一隐藏（`HIDDEN_STATUSES`）。
- **分组 / 多标签**（SR-F1.3）：`groups.py`；取舍：分组只是「组织维度」，不改变任务执行逻辑（避免割裂）。
- **完成/撤销 = 事实**（第 2 步）：完成发 `task.completed`、撤销发 `task.uncompleted`，成对留痕、不删历史。
- **任务字段**（F1 段2 起）：`note`（备注）已在 schema **v6** 落地（T-B1）——领域层 `create_task(note=)` 与
  `update_task` 白名单都带它；**备注是沉淀型内容，不发 facts、不进账本**；界面只在详情面板读写（列表不显示）。
  跨端 `sync.merge_task` 会带上 note，且**远端没带该字段时不清空本地备注**。
  `priority`（优先级 高/中/低，默认中）已在 schema **v7** 落地（T-B2）：非法值拒绝、不可清空；
  **排序统一为 `截止日 → 优先级 → 创建时间`**（`_ORDER_BY` 一处定义，列表/My Day/逾期三处共用，
  逾期栏两拨来源合并后用同口径的 `_sort_key` 重排）；Repeat 生成的下一次继承优先级。
  `flagged`（手动标记位）已在 schema **v8** 落地（T-B3）：`tasks_in_view()` 提供三个智能视图口径
  （Important=高优先级 / Planned=有截止日 / Flagged=标记位），**界面不自己筛**；`POST /api/tasks/{id}/flag`
  幂等翻转；三个视图在左栏、全部任务页、设置页都有入口（手机端左栏被隐藏，故不能只靠左栏）。
- **界面收口**（F1 段1，2026-09-18）：分组增删改 + 任务归属（T-A1）、子任务树与联动（T-A2）、任务编辑（T-A3）
  都已有入口；`purge_task` 收紧为「只能删回收站里的任务」。
- **附件 / 要求链接**（SR-F1.4 + SR-F5.3 / T-B4）：字段是 `tasks.attach` 与 `course_assessments.attach`
  （同一个形状：JSON 数组 `{target, title}`，只存引用）；**打开规则集中在 `core/attach.py`** ——
  模式（`folder` 默认 / `direct` / `auto`）与直接打开白名单存 `app_settings`（**服务端**，不由请求参数决定），
  可执行/脚本类永不直接打开；失败返回 `action="copy"` 让界面复制路径 + 提示。
  执行本机动作的接口（`POST /api/attach/open`、`PUT /api/settings/attach`）带**来源守卫**（只接受本机页面）。
- **提醒**（SR-F1.4 / T-B5）：`tasks.remind_at`（本地时间，schema **v10**）+
  `reminder_state()`（`over/today/soon/later`，完成/取消/归档/已删=不再催）+ `due_reminders(now)`（只读数据源）；
  `GET /api/reminders/due`、`GET /api/reminders`；前端详情可设、卡片/详情标注、今日页「该提醒了」区。
  **到点系统通知**（用户选 B′）在 `core/remind.py`：注册 `schtasks` 计划任务 `timeflow-reminders`
  （每分钟跑 `pythonw src/timeflow/app/remind.py`，`pythonw` 不闪控制台窗口、脚本与库都用绝对路径）；
  `show_notification()` 走 PowerShell WinRT 系统通知（失败退 `msg`，再不行如实报错）；
  **默认关**、开关可逆（关掉即删任务）、同一条提醒只弹一次、失败不标记下次重试、>3 条合并成一条汇总。
- **未实现**（以 `../../复盘/全量审计报告-五层一致性与缺口登记.md` §四 F1 为准）：拖拽排序（段2 决策明确不做）、
  任务存档（尝试记录+关联笔记）、三类任务区分。
- **Repeat 触发**（第 5 步）：完成时调 `process_repeats`；以 `task.repeat.generated` 事实去重 ⇒ 同一任务只生成一次。

## SR-F2 B 系统记账 → `core/ledger/`
- **两轴记账**（SR-F2.1）：`ledger.py` 投入轴与产出轴分开；**逾期=债务、专注=投入、复习完成=投入（维持）**。
- **只读事实层**（R1）：`summary()` 全部数据来自 `facts`——`focus.finished`（小时）、`review.completed`（张数）、
  `output.manual − output.retracted`（条数）、`invest.manual − invest.retracted`（单列小时）；`focus_sessions` 仅作原始记录/回填来源。
- **债务口径**（SR-F2.3）：在 `ledger.py` 内按逾期天数给档（轻≤3 / 中≤7 / 重>7），**不折算时间**。
- **旧表 `ledger_entries`**：已降级为**兼容/迁移来源**（手动投入与产出都走事实层），解读层不读它。
- **周结算**（SR-F2.5 / OP-15，第 6 步）：`ledger.weekly_summary()` —— 周=周一→周日、只读 facts、
  债务取周日快照、7 天逐日专注 + `steady_note`（如实描述，不设目标不告警）；`GET /api/summary/weekly`。
- **可视化数据底座**（SR-F2.7 / SR-NF3，第 7 步）：`core/insights.py` —— `daily_insights()`（逐日专注/手动/复习/
  产出/习惯/债务快照）、`group_insights()`（按任务分组的投入分布；未绑定专注不计入、多分组如实重复计数）、
  `heatmap()`（**近一年时间热力图**逐日多指标：专注分钟/手动分钟/复习/产出/债务快照）；
  `GET /api/insights/daily`、`/api/insights/groups`（days 1~90）、`/api/insights/heatmap`（days 1~400）。
  前端：统计页曲线 + 分组条 + 可切换维度的时间热力图（专注/手动/复习/产出/债务）。

## SR-F3 计时与专注 → `core/focus/`
- 番茄/普通计时（SR-F3.1/3.2）：`timer.py`；`status=进行中` 为真实中间态（未结束不计投入）；
  `active_session()` 供前端重开恢复；重复开始拒绝；结束幂等。
- **业务线订阅器**（第 2 步）：`subscribers.py` —— `focus.finished` → 当日反馈自动累加（跨线联动只在这里接线，
  业务线之间不直接调用）。
- **白名单/勿扰**（SR-F3.3）：`guard.py` 默认阻止非白名单、勿扰时段（含跨午夜）。
  ⚠️ **前端没有设置界面**（只有后端判定），见 `../../复盘/全量审计报告-五层一致性与缺口登记.md` GAP-F3-02。
- **多设备同步专注**（SR-F3.4）：**未实现**。`core/sync.py` 只有 LWW 合并语义与冲突日志，
  **没有专注状态（或任何数据）的跨端推拉传输**；`GET /api/sync/status` 如实返回 `enabled=false`。
  （旧文案写"靠 storage 的同步转发专注状态"是**文档失真**，2026-09-18 审计修正。）

## SR-F4 反馈/习惯/自检 → `core/feedback/`
- 每日反馈（SR-F4.1）、习惯打卡与连续天数（SR-F4.2）、自检（SR-F4.3，消费 B 数据）。
- 读口径（第 2 步）：`focus_minutes` 由订阅器按事实**重算**（非增量）；`self_check` 的周专注也读 facts。
- **习惯列表与热力图数据**（第 7 步）：`list_habits()` —— 全部习惯 + streak + 近 90 天打卡日期，
  `GET /api/habits`；前端习惯页渲染日历热力图（SR-F4.2 / OP-19）。
- **进度形态**（第 9 步，SR-NF3）：今日完成度进度环（今日页）与今日复习进度条（复习页）——由既有接口
  （`/api/tasks`、`/api/review/due`、`/api/summary`）在前端算比例，不新增后端口径。
- **可改名/可删除**（第 10 步）：`rename_habit()` / `delete_habit()`（打卡记录一并删除）+
  `PATCH /api/habits/{id}`、`DELETE /api/habits/{id}`（此前只能新建与打卡）。

## SR-F5 学业追踪 → `core/academic/`
- 课程档案（学分/考核/任课）+ 考核项 + GPA（4.0/5.0 可切换）。
- **学校任务"同构"的现状**（2026-09-18 审计如实化）：可以做到"学校任务与普通任务用同一套 CRUD/My Day/子任务"，
  但 **`tasks` 表没有 `course_id`** —— 无法把任务字段级挂到课程，现只能用**分组名当课程标签**。
  规格要求的「课程标签 + 硬约束元数据」只实现了"用分组当标签"这一半（契约 OP-24 未做）。
- **可视化**（第 9 步）：`GET /api/grades`（`all_grade_rows`）供前端「学业多维概览」（GPA 4.0/5.0、平均分、
  学分、课程覆盖的雷达 + 条形）；各轴各自归一到本图最大值，**只用于看均衡，不跨人比较**。
- **考核提醒与增删**（第 10 步）：`upcoming_assessments()`（只提醒未录成绩的；`days_until` 负=逾期/None=无截止日）
  + `GET /api/assessments/upcoming` + `delete_assessment` / `delete_grade`；前端学业页「临期与逾期（14 天内）」区。
- **加权平均成绩 + 制式切换**（第 11 步，用户要求）：`weighted_average()` =
  `Σ(学分×成绩)/Σ学分`（百分制原始分加权，学分为 0/负 不参与），与 `gpa()`（绩点加权）并存；
  `GET /api/gpa?scale=` 一次返回两个口径；前端学业页可在 4.0/5.0 制之间**切换查看**（写死默认值仍在 config.toml）。
- **未实现**：学校任务↔课程的字段级合流（OP-24，见上）。
  **要求备注 + 跳转要求已落地**（SR-F5.3 / T-B4）：`course_assessments.note`（要求备注）+
  `course_assessments.attach`（要求网页/本地路径，与任务附件共用 `core/attach.py` 的打开规则）；
  学业页「考核项」区可就近挂/点开（此前考核项只在 14 天临期窗口里看得到）。

## SR-F6 复习间隔重复 → `core/review/`
- FSRS 调度（SR-F6.1）用现成 Python `fsrs` 库；到期按「最久未复习 + 低 reps」排序；外部 app 只做调度中枢。
- 反馈三态（记得/模糊/忘了 → Good/Hard/Again）；完成发 `review.completed`（当日同卡去重）。
- **未实现**（2026-09-18 审计）：由学习任务升级为复习卡（SR-F6.2）、复习形式字段（SR-F6.5）、
  复习卡挂引用句柄（SR-F8.3）—— 见审计报告 GAP-F6-01/02/03。
- **撤销本次反馈**（第 5 步）：`review.completed` 的 `extra.before` 存复习前快照，`undo_review()` 回退 FSRS 字段
  并追加 `review.undone`；`reviewed_today()` = 当日完成 − 当日已撤销。

## SR-F7 团队/AI → `core/team/`
- 管理者/执行者两视角；不强制执行者装软件（状态手动为主）；AI 接口（`api/`）第一版只读+新增；团队任务不计个人投入。
- **分配可见性**（第 10 步）：`assignments_for_task()` 让 `TaskOut.assignments` 直接带回分配 ——
  任务卡片显示「谁负责 / 进展到哪」，并按状态给「开始 / 完成 / 恢复」下一步动作；
  `assign_task` 校验任务存在（404）与执行者非空（400）。
- **未实现**：独立的管理者/执行者视角切换页（OP-33）。

## SR-F8 备忘录/知识资产 → `core/memo/`
- 备忘录本地记录（可带引用句柄与任务关联）。
- **转任务**（第 10 步，R2）：`memo_to_task()` —— 备忘录用正文建任务、**保留原记录**并写回 `task_id`；
  另有 `delete_memo()`（删备忘录不连坐任务）。
- **产出/投入手动入口**（SR-F8.4）：`add_output_entry` / `add_invest_entry` 同时落旧表（兼容）与事实
  （`output.manual` / `invest.manual`），并支持 `retract_*` 反向事实；**知识资产只存引用句柄**（Vault 路径/KB-ID）。
- `getaways/`：外部集成（知识资产/学校通知）**预留占位**，尚无实现。

## SR-F9 存储/同步 → `storage/`
- SQLite（标准库 `sqlite3`，非 ORM）+ schema 版本化迁移（当前 **v5**：v3 facts、v4 focus 回填、v5 已完成任务回填）；
  LWW 同步（时间戳+version，不静默覆盖）；跨端去重（来源标记）。
- **并发连接（第 11 步修）**：`db.thread_local()` 代理按线程各持一个连接（`create_app` 用它）。
  原因：`sqlite3.Connection` 非线程安全，共享时一个请求的 `commit()` 会打断另一个请求的事务
  （真机表现：快速点击顶部导航 → 「操作未完成」）；实测并发 180 请求由 33 次 500 降到 0。
  回归守卫：`tests/test_concurrency.py`。
- **同步状态**（第 10 步）：`sync.status()` + `GET /api/sync/status` —— 只报告事实
  （冲突日志条数/最近时间），**跨端传输未实现时 `enabled=false`，不谎报"已同步"**。
- **已修 bug**（第 10 步）：`log_conflict` 原用秒级时间戳当主键，同一秒两次冲突会 `IntegrityError` —— 改随机 id。

## 重构地基（非 SR）→ `core/facts/`
- 事实层：`store.py` 读写 `facts` 表；`bus.py` 同步发布-订阅、通配匹配、订阅者异常隔离。
- 设计取舍：`kind` 自由字符串（加事实类型不改表）；高频值走 `value_num/value_text`；`extra` JSON 兜底；`revision/supersedes` 预留不实现。
- 与 ledger 的关系：业务线只发事实，ledger 读事实按当前心智模型算账；换心智模型只改解读层。
- **订阅者接入点**：`core/focus/subscribers.py`（当前唯一订阅器；跨线联动都写在各线自己的 `subscribers.py`）。

## 事实 kind 总表（便于查「谁发了什么」）

| kind | 发出方 | value_num | 反向/配套 |
|---|---|---|---|
| `focus.finished` | `focus/timer.py` | 秒 | `focus.paused/abandoned/interrupted`（各自成 kind） |
| `task.completed` | `tasks/manager.py` | 无（不估时） | `task.uncompleted` |
| `task.deleted` | `tasks/manager.py` | 无 | `task.restored` |
| `task.repeat.generated` | `tasks/manager.py` | 周期天数 | —（幂等依据 + 血缘） |
| `review.completed` | `review/review.py` | 0（不折算时间） | `review.undone` |
| `output.manual` | `memo/memo.py` | 数量 | `output.retracted` |
| `invest.manual` | `memo/memo.py` | **秒** | `invest.retracted` |

> 说明：`focus.started` 曾预留但**未使用**（开始不是投入事实）；如需前端联动再引入。

## 质量属性（SR-NF）落点

| SR-NF | 实现关键 |
|---|---|
| NF1 美感 | 前端 CSS（自定义强调色/主题）；`src/web/index.html` 单文件、无构建步骤 |
| NF2 交互低门槛 | 前端默认 My Day、一键操作、温和 toast（不弹窗施压） |
| NF6 可维护 | 模块化分层 + 局部错误隔离（订阅者异常记入 `facts.errors`，不崩全局） |
| NF14 配置 | `config.py` pydantic 校验 + `config.example.toml` + `TIMEFLOW_*` env 覆盖 |
| NF15 测试 | 覆盖矩阵见 `coverage.md`（测试文件数不写死在这里，避免随代码漂移）+ `tests/acceptance/` 可执行验收 + `tools/lf1_live_check.py` 真机。⚠️ **覆盖率门槛尚未写进 `pyproject`**（只在文档与手敲命令里），见审计报告 GAP-NF-08 |
| NF16 本地隐私 | 数据本地 SQLite；敏感只存本机 |
