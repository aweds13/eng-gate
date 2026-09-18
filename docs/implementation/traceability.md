# 追踪矩阵 · 规格 → 实现（SR → 模块）

> **路径约定**：实现包根为 `src/timeflow/`；下表 `src/...` 均为完整路径。

## 映射
| 规格 | 主导实现模块 | 抽象实现要点 |
|---|---|---|
| SR-F1.1~F1.9 | `src/timeflow/core/tasks/`（`manager.py`/`groups.py`） | My Day/逾期栏/状态机/分组/Repeat/子任务/软删除 |
| SR-F2.1~F2.7 | `src/timeflow/core/ledger/`（`ledger.py`） | 两轴记账/债务(逾期天数/程度)/顶部摘要 + **周结算(OP-15)**（只读 facts） |
| SR-F2.7 可视化 | `src/web/index.html`（周走势柱状） | 逐日专注柱状 + 数字；曲线/热力图/分组分布**未实现** |
| SR-F2.8 | `src/timeflow/core/ledger/` | 重规划/债务重组（二版） |
| SR-F3.1~F3.4 | `src/timeflow/core/focus/`（`timer.py`/`guard.py`/`subscribers.py`） | 计时/中断三选/白名单/勿扰/多设备同步/事实联动 |
| SR-F4.1~F4.3 | `src/timeflow/core/feedback/` | 每日反馈/习惯打卡与 streak/自检（读 facts） |
| SR-F5.1~F5.4 | `src/timeflow/core/academic/` | GPA/课程档案/考核项/同构合流 |
| SR-F6.1~F6.6 | `src/timeflow/core/review/` | FSRS 调度/创建/排序/外部 app/形式/反馈三态/撤销反馈 |
| SR-F7.1~F7.4 | `src/timeflow/core/team/` + `src/timeflow/api/` | 管理者执行者/团队原则/AI 接口 |
| SR-F8.1~F8.4 | `src/timeflow/core/memo/`（+ `getaways/` 预留） | 备忘录/引用句柄/产出与手动投入事实（含撤销） |
| SR-F9.1~F9.3 | `src/timeflow/storage/` | SQLite/schema 迁移 v5/LWW 同步/备份 |
| SR-F10.1 | `src/timeflow/getaways/`（预留） | 学校通知接口（后置） |
| SR-NF1~NF5 | `src/timeflow/app/` + `src/web/` | 界面/交互/可视化/一屏/可回退 |
| SR-NF6~NF8,NF13~NF15 | 各模块 + `tests/` + `src/timeflow/config.py` + `tools/lf1_live_check.py` | 可维护/可扩展/可测试/可观测/配置/测试闭环 |
| SR-NF11 | 全仓库 | Git 工作流（分支/commits；worktree 见 CODING_GUIDELINES §6） |
| SR-NF16~NF18 | `src/timeflow/storage/`,`src/timeflow/app/` | 本地隐私/移动端/性能 |

> 横切机制：`src/timeflow/core/facts/`（事实层/事件总线）不认领 SR-F 功能域，服务于 SR-NF6（局部错误隔离）与 SR-F9.1（可扩展多域）；
> 事实与解读的分离决策见 `../../复盘/事实层架构设计复盘.md`；订阅器接入见 `modules.md`「事实 kind 总表」。

## 五层闭合校验
| 维度 | 结果 |
|---|---|
| 每条 SR 是否都有实现落点 | ✅ 是（SR-F1~F10、SR-NF1~NF18 均有模块；**未实现项已在 modules.md 显式标注**：周结算/可视化、习惯热力图、getaways 外部集成） |
| 每个模块是否都能回溯到规格与需求 | ✅ 是（按模块名可回溯到 SR→N） |
| 五层闭环 | intention → specification(+conventions) → contracts → implementation → taste 闭合；`docs/taste/` 已于 2026-09-18 从空壳重写 |
| 实现文档与代码一致性 | ✅ 2026-09-18 复核：路径、模块落点、数据流已按当前代码（含第 2/3/5 步）对齐，见 `../../复盘/文档债务清理-实现层对齐.md` |

> 真实代码在 `src/timeflow/`，按模块名阅读；护栏/验收见 `docs/CODING_GUIDELINES.md`、`docs/ACCEPTANCE.md`。
