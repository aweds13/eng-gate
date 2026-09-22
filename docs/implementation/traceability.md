# 追踪矩阵 · 规格 → 实现（SR → 模块）

> **路径约定**：实现包根为 `src/timeflow/`；下表 `src/...` 均为完整路径。

## 映射
| 规格 | 主导实现模块 | 抽象实现要点 |
|---|---|---|
| SR-F1.1~F1.9 | `src/timeflow/core/tasks/`（`manager.py`/`groups.py`） | My Day/逾期栏/状态机/分组/Repeat/子任务（**软删除**与**任务编辑**分别是契约 OP-6 / OP-9，不再占用 SR 号） |
| SR-F2.1~F2.7 | `src/timeflow/core/ledger/`（`ledger.py`） | 两轴记账/债务(逾期天数/程度)/顶部摘要 + **周结算(OP-15)**（只读 facts） |
| SR-F2.7 可视化 | `src/timeflow/core/insights.py` + `src/web/index.html` | 逐日曲线 + 按任务分组分布 + **可切换维度的时间热力图**（专注/手动/复习/产出/债务）+ 周走势柱状（SR-F2.7 已覆盖） |
| SR-NF3 可视化分工 | `src/timeflow/core/insights.py`（数据）+ `src/web/index.html`（图形） | 后端出数据、前端出图；**六类形态已全覆盖**：债务/储蓄曲线+时间热力图、习惯日历热力图、计划-执行柱状、复习卡片+进度条+到期列表、今日完成度进度环、GPA 卡片+多维雷达 |
| SR-F2.8 | `src/timeflow/core/ledger/` | 重规划/债务重组（二版） |
| SR-F3.1~F3.4 | `src/timeflow/core/focus/`（`timer.py`/`guard.py`/`subscribers.py`） | 计时/中断三选/白名单/勿扰/多设备同步/事实联动 |
| SR-F4.1~F4.3 | `src/timeflow/core/feedback/` | 每日反馈/习惯打卡与 streak/自检（读 facts） |
| SR-F5.1~F5.4 | `src/timeflow/core/academic/` | GPA/课程档案/考核项/同构合流 |
| SR-F6.1~F6.6 | `src/timeflow/core/review/` | FSRS 调度/创建/排序/外部 app/形式/反馈三态（**撤销本次反馈**是契约 OP-27） |
| SR-F7.1~F7.4 | `src/timeflow/core/team/` + `src/timeflow/api/` | 管理者执行者/团队原则/AI 接口 |
| SR-F8.1~F8.4 | `src/timeflow/core/memo/`（+ `getaways/` 预留） | 备忘录/引用句柄/产出与手动投入事实（含撤销） |
| SR-F9.1~F9.3 | `src/timeflow/storage/` | SQLite/schema 版本化迁移（当前 **v12**）/LWW 同步/启前备份（回滚入口未做，SR-F9.3 与 SR-NF12 同缺口） |
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
| 每条 SR 是否都有实现落点 | ✅ 是（SR-F1~F10、SR-NF1~NF18 均有模块）。**残留未实现项**（均已显式标注）：OP-33 团队视角切换页、复习「改判」、跨端同步传输、F10 学校通知、~~沉淀型内容迁 Markdown~~（**一版已落地**，T-G4：每天一个 md + 目录可配置，数据库权威；Obsidian 跳转见 T-G5）、前端 R5 收尾（**OP-24 学校任务↔课程字段级合流已于 2026-09-19 落地，T-C12**）。**另有「后端已具备、前端界面未做」的两项**：任务详情/编辑（OP-9）、子任务管理（OP-12）—— 已登记 `../../复盘/使用体验问题与修改台账.md` §四。 |
| 每个模块是否都能回溯到规格与需求 | ✅ 是（按模块名可回溯到 SR→N） |
| 五层闭环 | intention → specification(+conventions) → contracts → implementation → taste 闭合；`docs/taste/` 已于 2026-09-18 从空壳重写 |
| 实现文档与代码一致性 | ✅ 2026-09-18 复核：路径、模块落点、数据流已按当前代码（含第 2/3/5 步）对齐，见 `../../复盘/文档债务清理-实现层对齐.md` |

> 真实代码在 `src/timeflow/`，按模块名阅读；护栏/验收见 `docs/CODING_GUIDELINES.md`、`docs/ACCEPTANCE.md`。
