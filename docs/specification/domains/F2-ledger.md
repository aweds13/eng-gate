# SR-F2 B 系统记账 · 详细规格

> 上游：N2 / N3 + `../functional.md` SR-F2.1~F2.8 + `../conventions.md`（债务/投入/产出口径）+ `../behaviors.md`。
> 契约见 `../../contracts/domains/F2-ledger.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **Fact（事实层）**：kind、subject、value_num、value_text、occurred_at、source。
- **投入轴**：专注 `focus.finished`（value_num=秒）；任务完成 `task.completed`（不估时）；
  复习完成 `review.completed`（不折算时间，计张数）；手动投入 `invest.manual`（**value_num=秒**，同专注口径）。
- **事实反向标记**：撤销类事实与正向事实成对（如 `task.uncompleted` 对 `task.completed`、
  `task.restored` 对 `task.deleted`、`output.retracted` 对 `output.manual`、`review.undone` 对 `review.completed`），
  解读层按最新有效状态计账，不删历史事实（R7 / A-003）。
- **产出轴**：学校 KPI（成绩/综测）与知识资产，独立记账、分开显示。
  事实形态（第 5 步物化）：`output.manual`（`subject_type=output`、`subject_id=ledger_entries.id`、
  `value_text=kind`（asset / kpi）、`value_num=数量`、`extra` 带 note/ref_handle）；
  撤销发 `output.retracted` 反向事实，不删历史。旧表 `ledger_entries` 仍写（兼容），两者不合并聚合。
- **可视化数据底座**（第 7 步，SR-F2.7）：`core/insights.py` —— `daily_insights()` 逐日时序、
  `group_insights()` 按任务分组的投入分布、`heatmap()` **时间热力图**逐日多指标
  （专注分钟/手动分钟/复习张数/产出条数/债务快照；债务=当日快照，不是当日新增）；
  后端只出数据，前端出图形（曲线 + 分组条 + 可切换日历热力图）；口径只读 facts。
- **债务**：逾期任务集合 + 天数/程度（轻≤3 / 中≤7 / 重>7），不折算时间。
- **周结算**：按本地周聚合投入/产出/债务趋势；温和呈现。
  - **均衡度（T-C3 / R6b，2026-09-20）**：`weekly_summary()` 增 `focus_variation_minutes`（逐日专注分钟的
    **标准差**，单位分钟）、`longest_gap_days`（本周最长连续 0 天）、`rhythm_note`（一句温和描述）。
    **只用分钟/天数这类不折算的原始单位**；措辞**只描述事实，不设目标、不告警、不催**（守 R6 温和）。
    界面上显示待前端批次。
  实现（第 6 步）：`ledger.weekly_summary()` / `GET /api/summary/weekly` —— 周 = 周一→周日，
  只读 facts（撤销照扣），债务取周日快照，附 7 天逐日专注与 `steady_note`（如实描述，不设目标、不告警）。

## 2. 状态与生命周期

- 逾期出现 → 债务 +1（按天更新程度）；完成 → 当天清零；取消 → 按已过天数计完即止；推到明天 → 随天数累计。
- 投入事实一旦发生，不被解读层改写；撤销通过反向事实或标记实现（见 A-003）。
- 学校硬考核逾期计债务，但不可重组清零。

## 3. 规则

- **R1 事实优先**：ledger 只从 facts 读，不直接查业务表；`focus_sessions` 仅作原始记录/回填来源。
- **R2b 手动投入口径（2026-09-18 用户确认）**：单位 = **秒**（与专注同口径，便于相加与换小时）；
  `manual_hours` 单列，**不并入** `invest_hours`（后者保持「只算专注」，避免两种来源混成一个数字）。
- **R2 投入口径**：专注按秒累加；完成/复习按完成事实；未绑定专注也计投入。
  `ledger.summary()` 返回 `invest_hours`（**专注**换算小时）+ `review_count`（今日复习张数，去重）
  + `output_count`（今日产出条数，已撤销不计）+ `output_kpi` / `output_asset`（同上，按两类分列）
  + `habit_count`（今日习惯打卡**次数**，只报次数、不折算时间，T-C1）
  + `manual_hours`（今日有效手动投入，秒/3600，**单列**）；
  **各项分开展示、互不折算、不合并**。
- **R3 产出口径**：学校 KPI 与知识资产分开；第一版手动粗颗粒；不做打分器。
  手动产出（第 5 步起）同时落 `ledger_entries`（兼容旧路径）与 `output.manual` 事实；撤销发反向事实。
  - **R3b 分两类显示（T-C4，2026-09-19 用户决定"分两行显示"）**：`summary()` 增
    `output_kpi` / `output_asset`（各报**条数**，与 `output_count` 同口径：条目数、已撤销不计）；
    **不拆轴、不折算** —— 同一份产出事实按 `kind` 分组显示而已。展开看明细见 F1 契约 OP-48
    （`GET /api/today/done`：产出明细 + 已撤销如实标注）。
- **R4 债务口径**：不折算时间；分级展示；无截止日任务不计债务。
- **R5 日期**：投入按 `occurred_at` 完成日归属；周起点周一。
- **R6 温和**：不设目标实体、不用算法推荐、不告警施压。
- **R7 可回退**：撤销/删除要回退对应事实或标记；重要操作可备份/快照。

## 4. 边界与异常

- 同一秒多条事实：逐条累加，不覆盖。
- 0 秒/0 值：可记录，但不产生有效投入；负值拒绝。
- 撤销后再完成：产生新事实，按最新有效状态解读。
- 旧数据无 facts：由 v4 回填保证；迁移后仍缺则回退读旧表并记录缺口。
- `ledger_entries` 与 facts 并存：**已定案（第 2 步子任务 4）**——两者**互不相通**，记为「新/旧两条路」：
  - 事实层 `facts` = **新路径 / 唯一真源**。专注、任务完成、复习完成等**计算型**记录一律走 facts；
    `ledger.summary()` 与各线读口径只读 facts，不读 `ledger_entries`。
  - `ledger_entries` = **旧路径（兼容保留）**。仍由 `memo.add_invest_entry/add_output_entry` 写入，
    是「手动记投入/产出」的历史落点（覆盖 SR-F8.4 产出评价器第一版「手动粗颗粒」）。
    **第 5 步进展**：手动**产出**（`output.manual`）与手动**投入**（`invest.manual`，秒）**都已物化到事实层**；
    `ledger_entries` 自此仅为兼容/迁移来源，解读层不读它。
  - `type` 与 `source` **不跨表 join、不合并聚合** ⇒ 不存在重复计账。
- 跨端冲突：LWW + 冲突日志，不静默覆盖。
- 空账本：投入 0 / 债务 0，界面友好，不显示错误。

## 5. 动线

- FLOW-1 ④→⑤：专注结束 → 投入 + 反馈 + 任务 + 摘要。
- FLOW-2：逾期 → 债务分级 → 处置 → 清零。
- 产出流：手动/成绩 → 产出轴（B2/B3 完善）。

## 6. 验收

- LC-5 完成记账、LC-7 摘要、LF-1 主链。
- 补充：撤销后账目回退；产出轴有真实写入；周结算温和呈现。

## 7. 测试映射

- 现有：`../../tests/test_ledger_summary.py`、`../../tests/test_facts.py`、`../../tests/test_team_memo.py`。
- 第 2 步补充：`../../tests/test_task_line.py`（完成事实不得混入投入口径）、`../../tests/test_focus_line.py`
  （专注事实→反馈/自检口径、读口径只认 facts）、`../../tests/test_review_line.py`（复习投入计张数）。
- 第 5 步补充：`../../tests/test_output_axis.py`（产出事实 + 撤销 + `output_count` 与投入分离）、
  `../../tests/test_invest_axis.py`（手动投入事实按秒 + 撤销 + `manual_hours` 与 invest_hours 分离）。
- 第 6 步补充：`../../tests/test_week_summary.py`（周边界/跨月跨年/四项聚合/撤销扣除/债务快照/温和提示/API）。
- 第 7 步补充：`../../tests/test_insights.py`（逐日时序/债务快照/撤销扣除/分组分布与「未分组」/未绑定不计入/
  时间热力图多指标与 400 天上限/API 边界）。
- 真实运行验证：`../../tools/lf1_live_check.py`（起真服务走 LF-1 主链 8 步）。
- 待补（B4）：复习的「卡片+进度条」与今日完成度进度环（SR-NF3 列举的其余形态）。
