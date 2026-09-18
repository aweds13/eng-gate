# 追踪矩阵 · 规格 → 实现（SR → 模块）

## 映射
| 规格 | 主导实现模块 | 抽象实现要点 |
|---|---|---|
| SR-F1.1~F1.9 | `src/core/tasks/` | My Day/逾期栏/状态机/分组/Repeat/子任务/存档 |
| SR-F2.1~F2.7 | `src/core/ledger/` | 两轴记账/债务(逾期天数)/结算/可视化/顶部摘要 |
| SR-F2.8 | `src/core/ledger/` | 重规划/债务重组（二版） |
| SR-F3.1~F3.4 | `src/core/focus/` | 计时/中断/白名单/勿扰/多设备同步 |
| SR-F4.1~F4.3 | `src/core/feedback/` | 每日反馈/习惯热力图/自检 |
| SR-F5.1~F5.4 | `src/core/academic/` | GPA/课程档案/考核提醒/同构合流 |
| SR-F6.1~F6.6 | `src/core/review/` | FSRS调度/创建/排序/外部app/形式/反馈三态 |
| SR-F7.1~F7.4 | `src/core/team/` + `src/api/` | 管理者执行者/团队原则/AI接口 |
| SR-F8.1~F8.4 | `src/core/memo/` + `src/getaways/` | 备忘录/引用句柄/产出评价器接口 |
| SR-F9.1~F9.3 | `src/storage/` | SQLite/schema迁移/LWW同步/备份 |
| SR-F10.1 | `src/getaways/` | 学校通知接口（后置） |
| SR-NF1~NF5 | `src/app/` + `src/web/` | 界面/交互/可视化/一屏/可回退 |
| SR-NF6~NF8,NF13~NF15 | 各模块 + `tests/` + `src/config.py` | 可维护/可扩展/可测试/可观测/配置/测试闭环 |
| SR-NF11 | 全仓库 | Git 工作流（worktree/commits/PR） |
| SR-NF16~NF18 | `src/storage/`,`src/app/` | 本地隐私/移动端/性能 |

> 横切机制：`src/core/facts/`（事实层/事件总线）不认领 SR-F 功能域，服务于 SR-NF6（局部错误隔离）与 SR-F9.1（可扩展多域）；事实与解读的分离决策见 `../../复盘/事实层架构设计复盘.md`。

## 五层闭合校验
| 维度 | 结果 |
|---|---|
| 每条 SR 是否都有实现落点 | ✅ 是（SR-F1~F10、SR-NF1~NF18 均有模块） |
| 每个模块是否都能回溯到规格与需求 | ✅ 是（按模块名可回溯到 SR→N） |
| 五层闭环 | intention → specification(+conventions) → contracts → implementation → taste 闭合，无孤儿哑项 |

> 至此五层骨架完成。真实代码在仓库根 `src/`，按模块名阅读；护栏/验收见 `docs/CODING_GUIDELINES.md`、`docs/ACCEPTANCE.md`。
