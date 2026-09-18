# SR-F2 B 系统记账 · 操作与动线契约

> 六要素见 `../interactions.md`；横切行为见 `../../specification/behaviors.md`。

## OP-7 查看今日摘要（扩展）

- 入口：顶部摘要区。
- 前置：无。
- 输入：无。
- 后续：债务 = 逾期项数 + 天数/程度；投入 = 今日 `focus.finished` 事实 sum/3600；
  复习投入 = 今日有效 `review.completed` 主体数（`review_count`）；
  产出 = 今日 `output.manual` 去重减 `output.retracted`（`output_count`，与投入分开展示）；
  手动投入 = 今日有效 `invest.manual`（秒）/3600（`manual_hours`，同样单列）；任一操作后刷新。
- 可逆：只读。
- 反馈：一行摘要，温和不告警。
- 边界：空账本显示 0；跨午夜按完成日；旧库无 facts 由回填/回退保证。
- API：`GET /api/summary` →
  `{debt_count, debt_items, invest_hours, review_count, output_count, manual_hours}`。

## OP-13 手动记投入（目标态）

- 入口：投入流水/设置页（第一版可无 UI，API 保留）。
- 前置：无。
- 输入：数值（非负，**单位=秒**）、可选备注/来源。
- 后续：发 `invest.manual` 事实 → 摘要/周结算重算。
- 可逆：撤销/反向事实。
- 反馈：流水新增。
- 边界：0 值可存不显；负值拒绝。
- 实现（第 5 步物化，2026-09-18 单位定案=秒）：`POST /api/ledger/invest` 写 `ledger_entries`（兼容）**并**发
  `invest.manual` 事实（value_num=秒）；`GET /api/ledger/invests?date_str=` 列当日（含 `retracted`、`minutes`）；
  `DELETE /api/ledger/invest/{entry_id}` 追加 `invest.retracted` 反向事实（幂等、不删历史）；负值 400。
  账本：`manual_hours = 今日有效手动投入(秒)/3600`，**单列**，不并入 `invest_hours`。

## OP-14 手动记产出（目标态）

- 入口：产出流水入口（`ledger_entries` 现路径）。
- 前置：无。
- 输入：数值、kind（学校 KPI / 知识资产）、备注、可选引用句柄。
- 后续：产出轴 +1，与投入分开展示。
- 可逆：撤销。
- 反馈：产出流水新增。
- 边界：不做知识资产打分；只存句柄。
- 实现（第 5 步物化）：`POST /api/ledger/output` 写 `ledger_entries` **并** 发 `output.manual` 事实；
  `GET /api/ledger/outputs?date_str=` 列当日产出（含 `retracted` 标记）；
  `DELETE /api/ledger/output/{entry_id}` 追加 `output.retracted` 反向事实（幂等、不删历史）；负值 400。

## OP-15 周结算

- 入口：统计/账本页（当前落在**专注页「本周投入」区**）。
- 前置：有事实数据。
- 输入：周起止（默认本地周一）；`week_of` 传该周任意一天即可定位。
- 后续：聚合投入/产出/债务趋势与波动；温和呈现。
- 可逆：只读。
- 反馈：图表/数字。
- 边界：无数据空态友好；不硬对标、不告警。
- 实现（第 6 步）：`GET /api/summary/weekly?week_of=` → `{start, end, focus_hours, manual_hours,
  review_count, output_count, debt_count, days[7], active_days, steady_note}`；
  口径与 `GET /api/summary` 同源（只读 facts，撤销照扣）；**债务取周日快照**；
  `days` 固定返回周一→周日 7 天（含 0，便于画走势）；`steady_note` 只如实描述、不评价不告警；
  非法日期 400。前端专注页用 7 根柱状展示逐日专注，空态给友好文案。

## OP-16 逾期债务展示

- 入口：摘要/逾期栏。
- 前置：有逾期任务。
- 输入：无。
- 后续：项数 + 天数 + 程度；学校硬考核加强提示但不施压。
- 可逆：只读。
- 反馈：温和一行。
- 边界：无 due 的 My Day 任务不计债务。

## FLOW 与验收

- 对应 LC-5/7、LF-1/2。
- 测试：`../../tests/test_ledger_summary.py`、`../../tests/test_facts.py`；B4 补全链路。
