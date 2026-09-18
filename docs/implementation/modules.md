# 模块实现落点（按规格分组）

> 对每条规格指出负责模块 + 靠什么机制/取舍保证成立。只给「模块名+职责+取舍」，不贴源码。
> **路径约定**：实现包根为 `src/timeflow/`；下文中的 `core/`、`api/`、`storage/` 等均指 `src/timeflow/` 下的子包。

## SR-F1 任务管理 → `core/tasks/`
- **My Day / 逾期栏 / 状态机 / 子任务 / Repeat**（SR-F1.1/1.2/1.5/1.6/1.8）：都在 `manager.py`。
  取舍：**昨日未完成自动进逾期栏而非静默消失**（如实、不假装）；逾期与否由截止日+今天判定，**不强推**；
  **软删除**（`status=已删`）而非物理删行，默认视图统一隐藏（`HIDDEN_STATUSES`）。
- **分组 / 多标签**（SR-F1.3）：`groups.py`；取舍：分组只是「组织维度」，不改变任务执行逻辑（避免割裂）。
- **完成/撤销 = 事实**（第 2 步）：完成发 `task.completed`、撤销发 `task.uncompleted`，成对留痕、不删历史。
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
- 白名单/勿扰（SR-F3.3）：`guard.py` 默认阻止非白名单；桌面/移动分别配置。
- 多设备同步专注（SR-F3.4）：靠 `storage/` 的同步（LWW）转发专注状态。

## SR-F4 反馈/习惯/自检 → `core/feedback/`
- 每日反馈（SR-F4.1）、习惯打卡与连续天数（SR-F4.2）、自检（SR-F4.3，消费 B 数据）。
- 读口径（第 2 步）：`focus_minutes` 由订阅器按事实**重算**（非增量）；`self_check` 的周专注也读 facts。
- **习惯列表与热力图数据**（第 7 步）：`list_habits()` —— 全部习惯 + streak + 近 90 天打卡日期，
  `GET /api/habits`；前端习惯页渲染日历热力图（SR-F4.2 / OP-19）。
- **进度形态**（第 9 步，SR-NF3）：今日完成度进度环（今日页）与今日复习进度条（复习页）——由既有接口
  （`/api/tasks`、`/api/review/due`、`/api/summary`）在前端算比例，不新增后端口径。
- **未实现**：习惯删除/重命名（当前只有新建与打卡）。

## SR-F5 学业追踪 → `core/academic/`
- 课程档案（学分/考核/任课）+ 考核项 + GPA（4.0/5.0 可切换）；学校任务**同构**进任务系统（只多课程标签+硬约束元数据）。
- **可视化**（第 9 步）：`GET /api/grades`（`all_grade_rows`）供前端「学业多维概览」（GPA 4.0/5.0、平均分、
  学分、课程覆盖的雷达 + 条形）；各轴各自归一到本图最大值，**只用于看均衡，不跨人比较**。
- **考核提醒与增删**（第 10 步）：`upcoming_assessments()`（只提醒未录成绩的；`days_until` 负=逾期/None=无截止日）
  + `GET /api/assessments/upcoming` + `delete_assessment` / `delete_grade`；前端学业页「临期与逾期（14 天内）」区。
- **未实现**：学校任务↔课程的字段级合流（OP-24，可先用「分组」当课程标签）。

## SR-F6 复习间隔重复 → `core/review/`
- FSRS 调度（SR-F6.1）用现成 Python `fsrs` 库；到期按「最久未复习 + 低 reps」排序；外部 app 只做调度中枢。
- 反馈三态（记得/模糊/忘了 → Good/Hard/Again）；完成发 `review.completed`（当日同卡去重）。
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
| NF15 测试 | `tests/` 每模块 pytest（179 项）+ `tests/acceptance/` 可执行验收 + `tools/lf1_live_check.py` 真机 |
| NF16 本地隐私 | 数据本地 SQLite；敏感只存本机 |
