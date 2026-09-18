# 覆盖矩阵 — SR → 详细规格 / 操作·动线 / 验收 / 测试

> 用途：长程任务中防止「有规格没契约、有契约没验收、有验收没测试」。
> 状态：B0 建骨架；B1-B4 逐域填满。
> 图例：✅ 已有；🟡 部分；⬜ 待补。

| SR | 详细规格 | 操作 / 动线 | 验收 | 测试 | 状态 |
|---|---|---|---|---|---|
| SR-F1 任务管理 | `../specification/domains/F1-tasks.md` | OP-1/2/5/6/8，FLOW-1/2 | LC-1/2/5/6/8，LF-1/2 | `../../tests/test_tasks.py`、`../../tests/test_groups.py`、`../../tests/test_api.py` | ✅ 规格/契约 |
| SR-F2 B 系统记账 | `../specification/domains/F2-ledger.md` | OP-5/7 | LC-5/7，LF-1 | `../../tests/test_ledger_summary.py`、`../../tests/test_facts.py` | ✅ 规格/契约 |
| SR-F3 计时与专注 | `../specification/domains/F3-focus.md` | OP-3/4 | LC-3/4，LF-1/3 | `../../tests/test_focus_feedback.py`、`../../tests/test_facts.py` | ✅ 规格/契约 |
| SR-F4 反馈 / 习惯 | `../specification/domains/F4-feedback.md` | OP-4 后续，FLOW-4 | LF-4 | `../../tests/test_focus_feedback.py` | ✅ 规格/契约 |
| SR-F5 学业追踪 | `../specification/domains/F5-academic.md` | 待 B2 定义 | AC-18/19（历史） | `../../tests/test_academic_review.py` | ✅ 规格/契约 |
| SR-F6 复习 | `../specification/domains/F6-review.md` | 待 B2 定义 | AC-20（历史） | `../../tests/test_academic_review.py` | ✅ 规格/契约 |
| SR-F7 团队 / AI | `../specification/domains/F7-team.md` | 待 B3 定义 | AC-21（历史） | `../../tests/test_team_memo.py` | ✅ 规格/契约 |
| SR-F8 备忘录 | `../specification/domains/F8-memo.md` | 待 B3 定义 | AC-22（历史） | `../../tests/test_team_memo.py` | ✅ 规格/契约 |
| SR-F9 存储 / 同步 | `../specification/domains/F9-storage-sync.md` | 待 B3 定义 | AC-23（历史） | `../../tests/test_sync.py`、`../../tests/test_facts.py` | ✅ 规格/契约 |
| SR-F10 学校通知 | `../specification/domains/F10-notify.md` | 后置 | 后置 | ⬜ 待补 | 后置 |

> 契约文件在 `../contracts/domains/`；可执行验收在 B4 加入 `../../tests/acceptance/`。
