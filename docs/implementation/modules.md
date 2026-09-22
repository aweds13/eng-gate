# 模块实现落点（按规格分组）

> 对每条规格指出负责模块 + 靠什么机制/取舍保证成立。只给「模块名+职责+取舍」，不贴源码。
> **路径约定**：实现包根为 `src/timeflow/`；下文中的 `core/`、`api/`、`storage/` 等均指 `src/timeflow/` 下的子包。

## SR-F1 任务管理 → `core/tasks/`
- **My Day / 逾期栏 / 状态机 / 子任务 / Repeat**（SR-F1.1a / SR-F1.4b / SR-F1.5a / SR-F1.6）：都在 `manager.py`。
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
- **附件 / 要求链接**（SR-F1.4a + SR-F5.3 / T-B4）：字段是 `tasks.attach` 与 `course_assessments.attach`
  （同一个形状：JSON 数组 `{target, title}`，只存引用）；**打开规则集中在 `core/attach.py`** ——
  模式（`folder` 默认 / `direct` / `auto`）与直接打开白名单存 `app_settings`（**服务端**，不由请求参数决定），
  可执行/脚本类永不直接打开；失败返回 `action="copy"` 让界面复制路径 + 提示。
  执行本机动作的接口（`POST /api/attach/open`、`PUT /api/settings/attach`）带**来源守卫**（只接受本机页面）。
- **提醒**（SR-F1.4a / T-B5）：`tasks.remind_at`（本地时间，schema **v10**）+
  `reminder_state()`（`over/today/soon/later`，完成/取消/归档/已删=不再催）+ `due_reminders(now)`（只读数据源）；
  `GET /api/reminders/due`、`GET /api/reminders`；前端详情可设、卡片/详情标注、今日页「该提醒了」区。
- **类型 + 所属课程**（SR-F5.4 / T-C12）：`tasks.task_type`（普通/作业/考试/论文/小测，默认普通）
  + `tasks.course_id`（→ `courses.id`，schema **v11**）；校验在 `_check_course_pair`（**「普通」不挂课程**、
  按改完后的状态判、课程必须存在）；`TaskOut.course_name` 由 `course_name()` 查好给前端；
  前端编辑态两个下拉 + 卡片/详情「课程 · 类型」徽标 + **学业页课程卡反向列出该课任务**。详见 F5 段。
  **到点系统通知**（用户选 B′）在 `core/remind.py`：注册 `schtasks` 计划任务 `timeflow-reminders`
  （每分钟跑 `pythonw src/timeflow/app/remind.py`，`pythonw` 不闪控制台窗口、脚本与库都用绝对路径）；
  `show_notification()` 走 PowerShell WinRT 系统通知（失败退 `msg`，再不行如实报错）；
  **默认关**、开关可逆（关掉即删任务）、同一条提醒只弹一次、失败不标记下次重试、多条合并成一条汇总。
  **响铃收口（T-B5c）**：闹钟式会一直响到被关掉 → ① `clear_first` 弹前先 `History.Clear`（最多一条在响）
  ② `MAX_NOTIFICATIONS_PER_RUN = 1`（多条合并，绝不堆成好几个闹钟）③ `clear_notifications()` +
  `POST /api/reminders/stop` + 设置页「停止响铃」。**弹与清共用同一个 AUMID**（`TOAST_APP_ID`），否则清不掉。
- **未实现**（以 `../../复盘/全量审计报告-五层一致性与缺口登记.md` §四 F1 为准）：拖拽排序（段2 决策明确不做）、
  任务存档（尝试记录+关联笔记）、三类任务区分。
- **Repeat 触发**（第 5 步）：完成时调 `process_repeats`；以 `task.repeat.generated` 事实去重 ⇒ 同一任务只生成一次。

## SR-F2 B 系统记账 → `core/ledger/`
- **两轴记账**（SR-F2.1）：`ledger.py` 投入轴与产出轴分开；**逾期=债务、专注=投入、复习完成=投入（维持）、
  完成悬赏=收益（T-F6）**。
- **只读事实层**（R1）：`summary()` 全部数据来自 `facts`——`focus.finished`（小时）、`review.completed`（张数）、
  `output.manual − output.retracted`（条数）、`invest.manual − invest.retracted`（单列小时）；`focus_sessions` 仅作原始记录/回填来源。
- **完成收益**（T-F6 / N3 口径「完成悬赏 = 收益/储蓄」，2026-09-21 补）：`_gained_subjects()` ——
  当日 `task.completed` 去重、且任务**现在仍是「完成」**（撤销照扣）、**只算任务不算子步骤**；
  `summary.gain_count` / `weekly_summary.gain_count`，界面上与**债务并排**（债↔收益是一对）。
- **债务口径**（SR-F2.3）：在 `ledger.py` 内按逾期天数给档（轻≤3 / 中≤7 / 重>7），**不折算时间**。
- **旧表 `ledger_entries`**：已降级为**兼容/迁移来源**（手动投入与产出都走事实层），解读层不读它。
- **周结算**（SR-F2.5 / OP-15，第 6 步）：`ledger.weekly_summary()` —— 周=周一→周日、只读 facts、
  债务取周日快照、7 天逐日专注 + `steady_note`（如实描述，不设目标不告警）；`GET /api/summary/weekly`。
- **均衡度：波动 / 空档**（T-C3 / SR-F2.5，2026-09-20）：`_rhythm()` 出 `focus_variation_minutes`
  （逐日专注分钟的**标准差**，分钟）、`longest_gap_days`（最长连续 0 天）；`_rhythm_note()` 把它们说成
  **一句温和的话**（不设目标、不告警、不折算）。前端专注页「本周投入」卡片显示成一行（`rhythmRow()`）。
- **温故知新 → 记一笔产出**（SR-F2.2 / T-C2，2026-09-20）：复习完成时把入口挂在 **toast** 上
  （`toastAction(...)` → `reviewOutput()`）—— 用户定「**想记才点**」：不自动弹窗、不打断复习；
  产出入**知识资产**（`POST /api/ledger/output`，`kind=asset`），可在备忘录页撤销。
- **可视化数据底座**（SR-F2.7 / SR-NF3，第 7 步）：`core/insights.py` —— `daily_insights()`（逐日专注/手动/复习/产出/习惯/债务快照）、`group_insights()`（按任务分组的投入分布；未绑定专注不计入、多分组如实重复计数）、
  `academic_vs_self()`（**学业 vs 自学**投入对照，见 F5 段）；
  `heatmap()`（**近一年时间热力图**逐日多指标：专注分钟/手动分钟/复习/产出/债务快照）；
  `GET /api/insights/daily`、`/api/insights/groups`、`/api/insights/academic-vs-self`（days 1~90）、`/api/insights/heatmap`（days 1~400）。
  前端：统计页曲线 + 分组条 + 对照条 + 可切换维度的时间热力图（专注/手动/复习/产出/债务）。

## SR-F3 计时与专注 → `core/focus/`
- 番茄/普通计时（SR-F3.1/3.2）：`timer.py`；`status=进行中` 为真实中间态（未结束不计投入）；
  `active_session()` 供前端重开恢复；重复开始拒绝；结束幂等。
- **业务线订阅器**（第 2 步）：`subscribers.py` —— `focus.finished` → 当日反馈自动累加（跨线联动只在这里接线，
  业务线之间不直接调用）。
- **白名单/勿扰**（SR-F3.3）：`guard.py` 默认阻止非白名单、勿扰时段（含跨午夜）。
  **设置界面已接上（前端批次③，2026-09-20 / GAP-F3-02 收口）**：默认值来自 `config.toml` 的 `[focus]`，
  本机改过的存 `app_settings`（`focus_block_by_default` / `focus_whitelist` / `focus_dnd`）并优先，
  **逐项独立**；`GET /api/focus/guard` 连口径说明一起返回，`PUT /api/settings/focus-guard`
  服务端持有 + 只接受本机页面；`to_config()` 让判定与界面**共用同一份口径**。
  边界：**只做配置与判定，不做系统级屏蔽**（那需要桌面壳能力）。
- **多设备同步专注**（SR-F3.4）：**未实现**。跨端现在能做的是**走文件**的同步包
  （`core/syncpack.py`，T-G8 / 场景 ③）与**手机离线采集**（`src/web/offline.js`，T-G10 / 场景 ①），
  但**没有专注状态的实时推拉**（手机侧也刻意不做离线专注计时 —— 它会牵动电脑侧的派生账目，
  而导入是直接写行、不过订阅器）。
  （旧文案写"靠 storage 的同步转发专注状态"是**文档失真**，2026-09-18 审计修正；
  旧文案说 `enabled=false` 也是**旧口径** —— 现在分开报 `file_sync` / `network_sync`。）

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
- **学校任务"同构"的现状**（2026-09-19 更新 · T-C12）：学校任务与普通任务用同一套 CRUD/My Day/子任务，
  并且 **`tasks` 已经有 `course_id` + `task_type`** —— 任务能字段级挂到课程（契约 OP-24 已落地）。
  口径：类型 ∈ 普通/作业/考试/论文/小测（默认「普通」），**只有非「普通」才允许挂课程**（校验在领域层
  `_check_course_pair`，按"改完之后的状态"判）；课程是**弱关联**（不建外键、删除不级联）。
  **分组仍可用**，但不再需要拿分组名充当课程标签。
- **可视化**（第 9 步）：`GET /api/grades`（`all_grade_rows`）供前端「学业多维概览」（GPA 4.0/5.0、平均分、
  学分、课程覆盖的雷达 + 条形）；各轴各自归一到本图最大值，**只用于看均衡，不跨人比较**。
- **考核提醒与增删**（第 10 步）：`upcoming_assessments()`（只提醒未录成绩的；`days_until` 负=逾期/None=无截止日）
  + `GET /api/assessments/upcoming` + `delete_assessment` / `delete_grade`；前端学业页「临期与逾期（14 天内）」区。
- **加权平均成绩 + 制式切换**（第 11 步，用户要求）：`weighted_average()` =
  `Σ(学分×成绩)/Σ学分`（百分制原始分加权，学分为 0/负 不参与），与 `gpa()`（绩点加权）并存；
  `GET /api/gpa?scale=` 一次返回两个口径；前端学业页可在 4.0/5.0 制之间**切换查看**（写死默认值仍在 config.toml）。
- **硬考核「强」呈现**（T-C8，2026-09-20）：`upcoming_assessments()` 返回的本就是「有截止日 + 未录成绩」
  的硬考核，前端学业页因此把它**视觉上升级**（区标题写明"硬考核/未录成绩/逾期不候"、按剩余天数排序、
  `card hard` + `badge hard` 样式）；**只做视觉** —— 不加声音、不弹窗（守温和红线）。
- **学业投入 vs 自学投入**（SR-F5.1b / T-C10，2026-09-20）：`insights.academic_vs_self()` +
  `GET /api/insights/academic-vs-self`（1~90 天）—— 只算**绑定了任务**的专注：挂课程=学业、
  没挂课程=自学；未绑定（或任务已彻底清理）**单列**（不归因）；手动投入不参与；
  前端统计页出两条条形 + 一行口径说明。**口径决策见 `../../复盘/C批口径定案.md` §7.3**。
- **未实现**：无（SR-F5.1b 的对照视图与 OP-24 合流都已落地；`course_assessments` 与任务的互链
  按 §六 的决定**不做**）。
  **要求备注 + 跳转要求已落地**（SR-F5.3 / T-B4）：`course_assessments.note`（要求备注）+
  `course_assessments.attach`（要求网页/本地路径，与任务附件共用 `core/attach.py` 的打开规则）；
  学业页「考核项」区可就近挂/点开（此前考核项只在 14 天临期窗口里看得到）。

## SR-F6 复习间隔重复 → `core/review/`
- FSRS 调度（SR-F6.1）用现成 Python `fsrs` 库；到期按「最久未复习 + 低 reps」排序；外部 app 只做调度中枢。
- 反馈三态（记得/模糊/忘了 → Good/Hard/Again）；完成发 `review.completed`（当日同卡去重）。
- **任务 → 复习卡升级 / 形式 / 句柄**（T-C5/C6/C7，2026-09-20）：schema **v12** 加 `review_items.task_id`
  （弱关联）；`items_for_task()` 反查、`POST /api/tasks/{id}/to-review`（**幂等**，重复升级返回已有卡）、
  `PATCH/GET /api/review/items/{id}`（改标题/形式/执行源/引用句柄；**排期字段不给人手改**）、
  `GET /api/review/meta`（形式与执行源词表 + 中文标签，只在后端一处）。升级不发事实、不动账本。
- **界面入口（前端批次，2026-09-20）**：任务详情「升级为复习卡 / 再看复习卡」按钮（`toReview()`）→
  升完跳复习页，详情里就地列出该任务已有的卡；复习卡「改形式/句柄」行内表单（`reviewEditForm()`，
  形式/执行源下拉从 `GET /api/review/meta` 取词表、句柄留空即清除）。**只改定义类字段**，
  排期字段不给人手改 —— 表单里明写了这一条，省得用户以为能改到期时间。
- **撤销本次反馈**（第 5 步 / 契约 OP-27 的可逆部分）：`review.completed` 的 `extra.before` 存复习前快照，`undo_review()` 回退 FSRS 字段
  并追加 `review.undone`；`reviewed_today()` = 当日完成 − 当日已撤销。

## SR-F7 团队/AI → `core/team/`
- 管理者/执行者两视角；不强制执行者装软件（状态手动为主）；AI 接口（`api/`）第一版只读+新增；团队任务不计个人投入。
- **分配可见性**（第 10 步）：`assignments_for_task()` 让 `TaskOut.assignments` 直接带回分配 ——
  任务卡片显示「谁负责 / 进展到哪」，并按状态给「开始 / 完成 / 恢复」下一步动作；
  `assign_task` 校验任务存在（404）与执行者非空（400）。
- **未实现**：独立的管理者/执行者**视角切换页**（SR-F7.1 / OP-33）与跨端集成。

## SR-F8 备忘录/知识资产 → `core/memo/`
- 备忘录本地记录（可带引用句柄与任务关联）。
- **转任务**（第 10 步，R2）：`memo_to_task()` —— 备忘录用正文建任务、**保留原记录**并写回 `task_id`；
  另有 `delete_memo()`（删备忘录不连坐任务）。
- **产出/投入手动入口**（SR-F8.4）：`add_output_entry` / `add_invest_entry` 同时落旧表（兼容）与事实
  （`output.manual` / `invest.manual`），并支持 `retract_*` 反向事实；**知识资产只存引用句柄**（Vault 路径/KB-ID）。
- `getaways/`：外部集成（知识资产/学校通知）**预留占位**，尚无实现。

## SR-F9 存储/同步 → `storage/` + `core/syncpack.py` + `src/web/offline.js`
- SQLite（标准库 `sqlite3`，非 ORM）+ schema 版本化迁移（当前 **v17**：v3 facts、v4 focus 回填、
  v5 已完成任务回填、v6 note、v7 priority、v8 flagged、v9 attach+app_settings、v10 remind_at、
  v11 task_type+course_id、v12 review_items.task_id、v13 doing_rank、v14 groups.parent_id、
  v15 分组同层唯一 + 按 id 归属、v16 tasks.created_by、**v17 跨端（六张表 updated_at 触发器 +
  `sync_tombstones` 删除墓碑 + `sync_logs.result/note`）**）；
  LWW 同步（时间戳+version，不静默覆盖）；跨端**同 id 去重**（来源标记尚未落库，见 `traceability.toml` 的 SR-F2.6b）。
- **跨端同步包（`core/syncpack.py`，G 批 · T-G8 = 场景 ③）**：`timeflow-sync` v1 的 JSON 包
  （`build_pack`/`export_pack`/`load_pack`/`check_pack`）+ **先规划后执行**的合并
  （`plan_merge` → `merge_pack`，所以"预览"与"真导入"是同一套判断）；三类表三套规则
  （LWW 行 / 只增行 / 关系行）；每次导入逐条记 `sync_logs`（`result` + "差在哪"），**不静默**；
  **v1 边界：导入永不删本地数据**（远程墓碑只防复活 + 继续传播）。
- **手机离线记（`src/web/offline.js`，G 批 · T-G10 = 场景 ①）**：浏览器侧 IndexedDB 队列与缓存 +
  纯函数造行/打包（**拆成独立文件就是为了能在 Node 里用同一份代码真跑**，见 `tools/phone_check.mjs`）；
  断网时记下（任务/完成与撤销/习惯打卡/备忘/每日反馈）→ 导出一份**同格式**的包 → 回电脑导入。
  **判断不在这里**（手机没有库、没有领域层，不做"半套合并"）。契约 OP-49，复盘 `复盘/手机离线记-T-G10.md`。
- **局域网访问 + 配对码（`core/lan.py`，G 批 · T-G10b = 场景 ②）**：`[net] allow_lan`（默认 false）
  或 `python tools/serve.py --lan` → 绑 `0.0.0.0` + 装那道门（判定是**纯函数** `gate()`：
  回环免检 / 静态壳与 `/api/lan/pair` 免检 / 其余要 `X-Timeflow-Pair` / 失败节流）。
  ★ **配对码只在本机（回环）响应里出现**；换码（`PUT /api/settings/lan`）也只允许本机。
  界面：没配对的设备看到的是**配对墙**（不是"操作失败"）；设置页「局域网访问」一节
  在 `renderSetting` 里（数据来自 `GET /api/settings/lan`）。
  **边界**：只在同一个 WiFi 里管用、明文、**不是加密**（一处措辞在 `lan.banner()` / `lan.status()`）。
  **至此跨端 ③（走文件）/ ①（手机离线记）/ ②（同一 WiFi 直连）三步全部落地**；
  还没做的是"手机直接把包传上来"（会引入"上传时谁合并"，单独定）。- **备份与恢复**（`storage/backup.py`，2026-09-21 用户定：设置页列出最近几个备份、点一下恢复）：
  `make_backup()` / `list_backups()` / `resolve_backup()`（**名字是唯一安全边界**）/ `restore()`；
  **起服务前与开窗口前各自动备份一次**（都在 schema 迁移之前）；
  恢复用 SQLite **在线备份 API** 写内容、**不替换文件**，且**恢复前先再备份一次现库**（可逆）；
  老备份就地跑 `db.migrate()`；比程序新的备份如实报 `newer_than_app`。
  配套：`db.raw_conn()`（拿到线程代理背后的真连接，`Connection.backup` 需要真连接）+ `db.migrate()`（公开的迁移入口）。
- **并发连接（第 11 步修）**：`db.thread_local()` 代理按线程各持一个连接（`create_app` 用它）。
  原因：`sqlite3.Connection` 非线程安全，共享时一个请求的 `commit()` 会打断另一个请求的事务
  （真机表现：快速点击顶部导航 → 「操作未完成」）；实测并发 180 请求由 33 次 500 降到 0。
  回归守卫：`tests/test_concurrency.py`。
- **同步状态**（第 10 步；T-G8 起改口径）：`sync.status()` + `syncpack.status()` + `GET /api/sync/status` ——
  只报告事实（**分开报** `file_sync` / `network_sync`、设备号、墓碑数、冲突条数、上次导出/导入），
  **不谎报"已同步"**。
- **已修 bug**（第 10 步）：`log_conflict` 原用秒级时间戳当主键，同一秒两次冲突会 `IntegrityError` —— 改随机 id。

## 重构地基（非 SR）→ `core/facts/`
- 事实层：`store.py` 读写 `facts` 表；`bus.py` 同步发布-订阅、通配匹配、订阅者异常隔离。
- 设计取舍：`kind` 自由字符串（加事实类型不改表）；高频值走 `value_num/value_text`；`extra` JSON 兜底；`revision/supersedes` 预留不实现。
- 与 ledger 的关系：业务线只发事实，ledger 读事实按当前心智模型算账；换心智模型只改解读层。
- **订阅者接入点**：`core/focus/subscribers.py`（当前唯一订阅器；跨线联动都写在各线自己的 `subscribers.py`）。

## 扩展（SR-NF7 / SR-NF10）→ `docs/EXTENDING.md` + `examples/`

- **「如何加一个功能」模板**：`docs/EXTENDING.md` —— 先判层（事实/解读/操作/配置/界面）→
  五步（意图→规格→契约→实现→台账）每步的产出物与检查 → 三条红线 → 反模式清单。
- **三个可跑示例**（`examples/`，由浅入深）：加事实 kind / 加配置项 / 加解读层口径；
  每个都跑在**临时库**上、不碰真实数据，并且有 `tests/test_examples.py` **当子进程真跑一遍**兜着
  （示例跑不通 = 测试红 = 门禁拦人），免得文档里的示例随接口漂移而腐烂。
- **已有的扩展点**：`kind` 自由字符串（加事实类型不改表）、配置驱动（`config.py` + env 覆盖）、
  契约层的界面动作（`data-action` + `ACTIONS` 两处声明）、
  **可配置词表 `src/timeflow/vocab.py`**（G 批 · T-G1：一张词表声明一处 → 配置校验/三层默认/
  拒绝非法值/API/设置页全自动；"加新词表不用碰路由和界面"这条已被复习形式与热力图维度两处验证）。
- **集成（SR-NF7 · T-G2）**：外部脚本 / 别的程序直接调本机 REST —— 写法、五条规矩与**边界表**在
  `docs/EXTENDING.md` §六，可跑示例 `examples/04_external_script.py`（`tests/test_examples.py` 真跑）。
- **仍没有的**：「插件注册机制」的完整版 —— **能不改核心加的只有词表**；加**字段**（schema 迁移）
  与加**功能**（领域函数 + 路由 + 界面）**做不到不改核心**，如实标注（`SR-NF7` → done：
  词表 + 集成 + 模板都到位，做不到的写明）。

## 可观测（SR-NF13）→ `src/timeflow/logs.py`

- **结构化日志**：一行一条 JSON（`logs/timeflow.jsonl`，gitignore 的本机产物）；`setup_logging()` 幂等，
  写不进文件就退回控制台（**日志失败不挡启动**）；`log_event(事件名, **字段)` 是唯一写入口。
- **关键路径**：`api/app.py` 的 `log_key_paths` 中间件记**改动类请求**（方法/路径/状态/耗时）+ 启动事件；
  GET 不记（读了就记会把日志淹掉）。
- **调试开关**：`TF_DEBUG=1`（或 `tools/serve.py --debug`）只把级别降到 DEBUG，**不改变业务行为**。
- **隐私最小化**（守 SR-NF16）：不记请求正文/备注/标题；`log_event` 刻意只接受机器可读字段。
- **健康检查**：`GET /api/health` → `{status, database_ok, schema_version, tasks, facts, debug, log_file}`；
  库坏了报 `degraded` + 原因，**自己不许 500**。

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
>
> **从手机来的事实**（G 批 · T-G10）：`task.completed` / `task.uncompleted` 也可能是
> **手机离线记**在断网时写下的（`src/web/offline.js`），随同步包导入落到电脑的 `facts` 表，
> `source="phone"`、`occurred_at` = 手机上那一刻。**注意**：导入是**直接写行**，不过订阅器 ——
> 所以 `focus.finished` 这类会牵动派生缓存的 kind **不在**离线可记范围内（见 `复盘/手机离线记-T-G10.md` §六）。

## 质量属性（SR-NF）落点

| SR-NF | 实现关键 |
|---|---|
| NF1 美感 | 前端 CSS（自定义强调色/主题）；`src/web/index.html` 主壳（无构建步骤）+ `app.css` 令牌区 + `offline.js` 离线引擎。**R5 起有尺度令牌**：间距 `--sp-1..11` / 圆角 `--r-*` / 字号 `--fs-*` / 布局常量 `--nav-clearance`、`--page-bottom` —— 组件**只写令牌不写裸像素**（护栏强制），空态统一走 `emptyState()` |
| NF2 交互低门槛 | 前端默认 My Day、一键操作、温和 toast（不弹窗施压）。**新手引导**（R5）：今日页三步卡片，可一键关掉/设置页可重看，**不用遮罩弹窗**（不拦路） |
| NF4 一屏到底 | 三栏（左导航/中列表/右详情）+ 渐进聚焦；**右栏可折叠**（`.shell.rail-off`，选择记本机 `tf_rail`，左栏与设置页两处入口） |
| NF5 反馈与可回退 | 完成划线 / toast / 删除可撤销；**不可逆操作二次确认走壳级模态** `confirmAsk(title, 动作名)`（R5 起页面里**没有原生 `confirm`**，护栏断言） |
| NF6 可维护 | 模块化分层 + 局部错误隔离（订阅者异常记入 `facts.errors`，不崩全局） |
| NF14 配置 | `config.py` pydantic 校验 + `config.example.toml` + `TIMEFLOW_*` env 覆盖 |
| NF15 测试 | 覆盖矩阵见 `coverage.md`（测试文件数不写死在这里，避免随代码漂移）+ `tests/acceptance/` 可执行验收 + `tools/lf1_live_check.py` 真机。覆盖率门槛**已写进 `pyproject`**（`--cov-fail-under=70`）；未做的是规格写的 `integration` marker（现由真机自检脚本替代），见 `traceability.toml` 的 SR-NF15 |
| NF16 本地隐私 | 数据本地 SQLite；敏感只存本机 |
