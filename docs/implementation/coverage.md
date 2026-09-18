# 覆盖矩阵 — SR → 详细规格 / 操作·动线 / 验收 / 测试

> 用途：长程任务中防止「有规格没契约、有契约没验收、有验收没测试」。
> 状态：B0 建骨架；B1-B4 逐域填满。
> 图例：✅ 已有；🟡 部分；⬜ 待补。

| SR | 详细规格 | 操作 / 动线 | 验收 | 测试 | 状态 |
|---|---|---|---|---|---|
| SR-F1 任务管理 | `../specification/domains/F1-tasks.md` | OP-1/2/5/6/8，FLOW-1/2 | LC-1/2/5/6/8，LF-1/2 | `../../tests/test_tasks.py`、`../../tests/test_groups.py`、`../../tests/test_api.py`、`../../tests/test_task_line.py`、`../../tests/test_task_repeat.py`、`../../tests/test_task_delete.py` | ✅ 规格/契约 |
| SR-F2 B 系统记账 | `../specification/domains/F2-ledger.md` | OP-5/7/13/14/15 | LC-5/7，LF-1 | `../../tests/test_ledger_summary.py`、`../../tests/test_facts.py`、`../../tests/test_output_axis.py`、`../../tests/test_invest_axis.py`、`../../tests/test_week_summary.py`、`../../tests/test_insights.py` | ✅ 规格/契约（含时间热力图） |
| SR-F3 计时与专注 | `../specification/domains/F3-focus.md` | OP-3/4 | LC-3/4，LF-1/3 | `../../tests/test_focus_feedback.py`、`../../tests/test_facts.py`、`../../tests/test_focus_line.py` | ✅ 规格/契约 |
| SR-F4 反馈 / 习惯 | `../specification/domains/F4-feedback.md` | OP-4/17/18/19，FLOW-4 | LF-4 | `../../tests/test_focus_feedback.py`、`../../tests/test_focus_line.py`、`../../tests/test_insights.py`、`../../tests/test_habit_memo_line.py` | ✅ 规格/契约 |
| SR-F5 学业追踪 | `../specification/domains/F5-academic.md` | OP-21/22/23/25 | AC-18/19（历史） | `../../tests/test_academic_review.py`、`../../tests/test_academic_line.py` | ✅ 规格/契约（含加权平均成绩与制式切换；OP-24 合流未实现） |
| SR-F9 存储 / 同步 | `../specification/domains/F9-storage-sync.md` | OP-39–43 | AC-23（历史） | `../../tests/test_sync.py`、`../../tests/test_facts.py`（含 v4/v5 迁移）、`../../tests/test_concurrency.py`（每线程连接） | ✅ 规格/契约（跨端传输未实现） |
| SR-F6 复习 | `../specification/domains/F6-review.md` | OP-27/28 | AC-20（历史） | `../../tests/test_academic_review.py`、`../../tests/test_review_line.py`（含撤销反馈） | ✅ 规格/契约 |
| SR-F7 团队 / AI | `../specification/domains/F7-team.md` | OP-31/32 | AC-21（历史） | `../../tests/test_team_memo.py`、`../../tests/test_team_line.py` | ✅ 规格/契约（OP-33 视角页未实现） |
| SR-F8 备忘录 | `../specification/domains/F8-memo.md` | OP-35/36/38 | AC-22（历史） | `../../tests/test_team_memo.py`、`../../tests/test_output_axis.py`、`../../tests/test_habit_memo_line.py` | ✅ 规格/契约 |
| SR-F9 存储 / 同步 | `../specification/domains/F9-storage-sync.md` | OP-39–43 | AC-23（历史） | `../../tests/test_sync.py`、`../../tests/test_facts.py`（含 v4/v5 迁移）、`../../tests/test_concurrency.py`（每线程连接） | ✅ 规格/契约（跨端传输未实现） |
| SR-F10 学校通知 | `../specification/domains/F10-notify.md` | 后置 | 后置 | ⬜ 待补 | 后置 |
| 前端交互层（第 4/5 步 → R1–R5） | `../contracts/interactions.md`（OP-1–OP-8 自查表）+ `../../复盘/前端现状评估与接缝重构方案.md` | 六要素齐备 | LC-1–LC-8 / LF-1–LF-4 | `../../tests/test_web_frontend.py`、真机 `../../tools/lf1_live_check.py`、`../../tools/web_live_check.py` | ✅ 全闭环（视觉/布局：R3–R5 待做） |

> 契约文件在 `../contracts/domains/`；可执行验收见 `../../tests/acceptance/README.md`（默认排除，显式 `-m acceptance`）；
> 覆盖率门 70%（当前实测 92.34%）；真实运行验证见 `../../tools/lf1_live_check.py`。
> 未实现项在各域行内标注；实现文档与代码一致性见 `../../复盘/文档债务清理-实现层对齐.md`。
