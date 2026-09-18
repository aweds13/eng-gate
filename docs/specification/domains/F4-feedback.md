# SR-F4 反馈 / 习惯 / 自检 · 详细规格

> 上游：N12–N14 + `../functional.md` SR-F4.1~F4.3 + `../conventions.md` + `../behaviors.md`。
> 契约见 `../../contracts/domains/F4-feedback.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **feedback_logs**：date（主键）、plan_note、executed、gap_note、focus_minutes、created_at。
- **habits**：id、name、created_at。
- **habit_logs**：habit_id + date + done（联合主键）。
- 自检：消费 B 账本数据（投入 / 产出 / 债务趋势）与习惯数据。

## 2. 状态与生命周期

- 每日反馈每天一条；重复保存为更新。
- 习惯打卡按日切换；streak 从今天往前连续计数。
- focus_minutes 由 `focus.finished` 订阅器自动累加；用户手动补录按「不覆盖自动值」合并。

## 3. 规则

- **R1 计划 vs 执行**：两侧都要能记录；`executed` 不再是前端可选。
- **R2 专注自动计入**：结束专注自动累加当日 `focus_minutes`，前端不传也要有值。
- **R3 习惯**：打卡 / 取消 / 连续天数 / 热力图；纳入 B 可视化。
- **R4 自检**：消费 B 数据，温和呈现，不告警、不施压。
- **R5 日期**：按本地日期；跨午夜专注归完成日。
- **R6 空态**：无反馈/无习惯时给简短引导，不显示错误。

## 4. 边界与异常

- 同一天重复保存反馈：更新而非新增；空 plan/executed 允许但提示。
- 自动累加与手动补录同时发生：**已定案（A-012）**——`focus_minutes` 是 facts 的**派生量**，每次 `focus.finished`
  都按当日事实**重算**（不是增量累加）；接口传入的 `focus_minutes` 只是兼容旧参数、会被后续事实重算覆盖。
  用户备注（plan_note/executed/gap_note）永不被自动流程改写。
- 习惯重名：拒绝或允许但提示；习惯删除需确认，历史保留或一并删除。
- 打卡未来日期：拒绝或警告；补打卡过去日期允许。
- 自检无数据：0 值空态，不报错。
- 并发同日期保存：LWW + 冲突日志。

## 5. 动线

- FLOW-4：做任务/专注 → 自动累积到当日反馈 → 用户补录计划/差距 → 自检消费。

## 6. 验收

- LF-4 反馈闭环；AC-15/16/17。
- 补充：只做专注不手动填，当日反馈已有值。

## 7. 测试映射

- 现有：`../../tests/test_focus_feedback.py`、`../../tests/test_api.py`。
- 第 2 步（专注线发事实）：`../../tests/test_focus_line.py` —— 专注结束自动累加当日 min、只认正常结束、幂等、按完成日归属、不覆盖备注。
- 待补（B4）：习惯热力图/streak 边界。
