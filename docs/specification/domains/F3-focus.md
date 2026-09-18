# SR-F3 计时与专注 · 详细规格

> 上游：N15–N17 + `../functional.md` SR-F3.1~F3.4 + `../conventions.md` + `../behaviors.md`。
> 契约见 `../../contracts/domains/F3-focus.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **focus_session**：id、task_id（可空）、kind（tomato / plain）、started_at、ended_at、duration_sec、status、device_id、created_at。
- **GuardConfig**：block_by_default、allowed 列表、dnd_windows（可跨午夜）。
- **事实**：正常结束 `focus.finished`；暂停 `focus.paused`；放弃 `focus.abandoned`；记中断 `focus.interrupted`。

## 2. 状态机

```
未开始 → 进行中 → 正常结束（finished）
             ├→ 暂停（paused）→ 继续/结束
             ├→ 放弃（abandoned）
             └→ 记中断（interrupted）
```

- 进行中必须有可见计时（番茄倒计时 / 普通正计时）。
- 同一设备同一时间只允许一个进行中 session；并发开始要拒绝。
- **实现口径（第 4 步）**：`focus_sessions.status` 用 `进行中`（`STATUS_ACTIVE`）作为进行中态；
  开始**不写** facts（不计投入），结束才按结束状态发 `focus.*` 事实。
  恢复入口：`GET /api/focus/active`（无进行中返回 `null`）。

## 3. 规则

- **R1 绑定任务**：可绑定 task_id；正常结束时时长计入该任务 + 当日反馈 + 投入账。
- **R2 自动归属**：时长自动计算；未绑定也计投入（轻量、不硬归因）。
- **R3 中断三选**：暂停保留 session 可继续；放弃不入投入；记中断按实际时长入账并标记。
- **R4 白名单 / 勿扰**：默认阻止非白名单；勿扰时段可跨午夜；桌面/移动分别配置。
- **R5 多设备同步**：任一设备开始，其他设备同步进入专注/勿扰；同一时间去重，不产生并行。
- **R6 事实语义**：只有正常结束落 `focus.finished`；其他状态各自落 kind（第 0.1 步已修）。

## 4. 边界与异常

- 重复开始：返回已有 session 或拒绝，不产生两条并行。**（第 4 步已实现：拒绝并返回 400）**
- 结束不存在的 session：明确报错，不写半截数据。**（第 4 步：KeyError → 404）**
- 结束两次：幂等，不重复记投入。**（第 4 步已实现：非「进行中」直接返回）**
- duration 为 0 / 负：0 可记录不产生有效投入；负拒绝。
- 结束时间早于开始时间：拒绝或按 0 处理并记录异常。
- 跨午夜：按完成日归属投入。
- 番茄到点：自动提示或结束；用户可确认。
- 应用关闭 / 重开：进行中 session 可恢复；超时策略待 B4 定。
- 绑定任务被删除：session 保留，事实保留；任务归因失效但不丢数据。
- 设备冲突：LWW / 拒绝；冲突写日志，不静默覆盖。
- 白名单配置非法（空、重复、跨午夜格式错）：拒绝并提示。

## 5. 动线

- FLOW-1：从任务开始专注 → 计时可见 → 结束 → 四步联动。
- FLOW-3：开始 → 计时 → 正常 / 暂停 / 放弃 / 记中断分支。

## 6. 验收

- LC-3 开始专注、LC-4 结束专注、LF-1、LF-3。
- 补充：放弃不产生投入、记中断带标记、白名单/勿扰窗口正确。

## 7. 测试映射

- 现有：`../../tests/test_focus_feedback.py`（含进行中态 / 并行拒绝 / 结束幂等）、`../../tests/test_facts.py`。
- 第 2 步：`../../tests/test_focus_line.py`（事实 → 反馈/任务/读口径）。
- 第 4 步：`../../tests/test_web_frontend.py`（前端依赖的 API 契约 + 主链）；真机 `../../tools/lf1_live_check.py`。
- 待补（B4）：番茄到点自动提示、应用重开恢复（当前已支持 `GET /api/focus/active` 恢复计时）。
