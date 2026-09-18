# SR-F2 B 系统记账 · 详细规格

> 上游：N2 / N3 + `../functional.md` SR-F2.1~F2.8 + `../conventions.md`（债务/投入/产出口径）+ `../behaviors.md`。
> 契约见 `../../contracts/domains/F2-ledger.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **Fact（事实层）**：kind、subject、value_num、value_text、occurred_at、source。
- **投入轴**：专注 `focus.finished`（value_num=秒）；任务完成 `task.completed`（不估时）；复习完成 `review.completed`（不折算时间，计张数）；手动投入 `invest.manual`。
- **事实反向标记**：撤销类事实与正向事实成对（如 `task.uncompleted` 对 `task.completed`），解读层按最新有效状态计账，不删历史事实（R7 / A-003）。
- **产出轴**：学校 KPI（成绩/综测）与知识资产，独立记账、分开显示。
  事实形态（第 5 步物化）：`output.manual`（`subject_type=output`、`subject_id=ledger_entries.id`、
  `value_text=kind`（asset / kpi）、`value_num=数量`、`extra` 带 note/ref_handle）；
  撤销发 `output.retracted` 反向事实，不删历史。旧表 `ledger_entries` 仍写（兼容），两者不合并聚合。
- **债务**：逾期任务集合 + 天数/程度（轻≤3 / 中≤7 / 重>7），不折算时间。
- **周结算**：按本地周聚合投入/产出/债务趋势；温和呈现。

## 2. 状态与生命周期

- 逾期出现 → 债务 +1（按天更新程度）；完成 → 当天清零；取消 → 按已过天数计完即止；推到明天 → 随天数累计。
- 投入事实一旦发生，不被解读层改写；撤销通过反向事实或标记实现（见 A-003）。
- 学校硬考核逾期计债务，但不可重组清零。

## 3. 规则

- **R1 事实优先**：ledger 只从 facts 读，不直接查业务表；`focus_sessions` 仅作原始记录/回填来源。
- **R2 投入口径**：专注按秒累加；完成/复习按完成事实；未绑定专注也计投入。
  `ledger.summary()` 返回 `invest_hours`（专注换算小时）+ `review_count`（今日复习张数，去重）
  + `output_count`（今日产出条数，已撤销不计）；**三者分开展示、互不折算**。
- **R3 产出口径**：学校 KPI 与知识资产分开；第一版手动粗颗粒；不做打分器。
  手动产出（第 5 步起）同时落 `ledger_entries`（兼容旧路径）与 `output.manual` 事实；撤销发反向事实。
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
  - `ledger_entries` = **旧路径（待物化）**。仅由 `memo.add_invest_entry/add_output_entry` 手动写入，
    是「手动记投入/产出」的落点（覆盖 SR-F8.4 产出评价器第一版「手动粗颗粒」）。
    **第 5 步进展**：手动**产出**已同时发 `output.manual` 事实（产出轴物化）；手动**投入**（`invest.manual`）仍只在旧表。
  - `type` 与 `source` **不跨表 join、不合并聚合** ⇒ 不存在重复计账。
  - 后续：`invest.manual` 也物化到事实层后，`ledger_entries` 降级为迁移来源。
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
- 第 5 步补充：`../../tests/test_output_axis.py`（产出事实 + 撤销 + `output_count` 与投入分离）。
- 真实运行验证：`../../tools/lf1_live_check.py`（起真服务走 LF-1 主链 8 步）。
- 待补（B4）：专注→记账主链、完成→记账、`invest.manual` 物化。
