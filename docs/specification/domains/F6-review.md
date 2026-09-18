# SR-F6 复习间隔重复 · 详细规格

> 上游：N26–N29 + `../functional.md` SR-F6.1~F6.6 + `../conventions.md` + `../behaviors.md`。
> 契约见 `../../contracts/domains/F6-review.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **review_items**：id、title、form（预留：挖空/真题/问答卡）、execution_source（builtin / external）、ref_handle、stability、difficulty、due、reps、lapses、last_review、created_at。
- **反馈三态**：记得（Good）/ 模糊（Hard）/ 忘了（Again）。
- **关联**：可引用 Vault 路径 / KB-ID，不直接读写外部文件。

## 2. 状态与生命周期

- 新卡 → 到期 → 三态反馈 → FSRS 推进下一间隔。
- 复习完成 = 投入（维持）；温故知新可额外记产出（可选）。
- 复习逾期 = 轻度债务，由 FSRS 自愈；不单独隔离。

## 3. 规则

- **R1 调度**：用现成 Python FSRS 库；字段按 FSRS 兼容设计。
- **R2 三态接口**：记得/模糊/忘了 = 与外部复习工具的联动接口。
- **R3 到期排序**：重要度 + 最久未复习；到期优先建议进 My Day。
- **R4 外部 app**：只做调度中枢；用户手动点完成；带执行源标签。
- **R5 升级**：学习任务可升级为复习任务；保留关联引用句柄。
- **R6 投入**：复习完成发 `review.completed` 事实（第 2 步子任务 3 已接线）。
  事实形态：`subject_type=review_item`、`subject_id=卡片 id`、`value_num=0`（不折算时间）、
  `extra={title, feedback, reps, next_due, reviewed_on}`；同时广播同名事件。
  **当日去重**：同一天同一张卡只留一条投入事实（重复完成幂等）；解读层计「今日不同卡片数」。

## 4. 边界与异常

- 非法 rating / form：拒绝并提示。
- 重复完成同一到期卡：推进 FSRS 但**当日只记一条投入事实**（幂等）；学习阶段的卡当天可能仍到期并留在
  My Day（FSRS 行为），不代表重复记账。
- 无到期卡：空态友好。
- 外部引用句柄失效：不阻断复习，只提示引用缺失。
- 删除卡片：需确认；历史记录可选保留。
- FSRS 参数/字段迁移：schema 版本化 + 兼容读取。
- 跨端冲突：LWW + 冲突日志。
- 任务升级后原任务：保留或标记为已升级，避免双重计数。
- 撤销本次三态反馈（OP-27「可逆」）：**第 5 步已实现** —— 事实 `extra.before` 存复习前快照，
  `undo_review` 回退 FSRS 字段并追加 `review.undone` 反向事实；账本 `review_count` 按
  「当日完成 − 当日已撤销」计数（同卡当日归 0），已撤销的那次不阻止重新复习入账。

## 5. 动线

- 复习闭环：到期 → 优先进 My Day → 三态反馈 → 推进间隔 → 记投入。

## 6. 验收

- AC-20 复习 FSRS。
- 补充：三态映射、外部执行源、到期进 My Day、复习完成计投入。

## 7. 测试映射

- 现有：`../../tests/test_academic_review.py`。
- 第 2 步（复习线发事实）：`../../tests/test_review_line.py` —— 完成事实/事件、当日去重、账本 `review_count`、到期进 My Day、API 全链路。
- 第 5 步（撤销反馈）：同文件 —— `undo_review` 回退 FSRS 字段与账目、幂等、无完成事实时空操作、撤销后可重新入账。
- 待补（B4）：外部执行源。
