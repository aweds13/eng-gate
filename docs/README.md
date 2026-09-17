# timeflow — 本地优先的时间与学习投入管理工具

> 一个**本地优先、桌面端为主**的个人「时间与学习投入」管理工具：管要做什么（My Day / 任务 / 拆解 / 分组），**用「债务 / 储蓄」如实记账**（该做没做=债务、投入=储蓄），守住与学校考核不冲突，可外接 AI 与笔记。

## 它解决什么
- 想清楚「今天该做什么」（My Day），并把待办如实记下来、能追踪、能拆解。
- 用「债务 / 储蓄」看自己在**长期投入上是否均衡**（不突击、不拖延），但**不施压**——只如实记账、温和呈现。
- 学校 KPI / 考试 / 作业别漏掉（硬约束提醒），与自学不冲突。
- 专注计时 / 习惯打卡 / 每日复盘 / 复习(FSRS) 与学习投入统一在一个本地工具里。

## 快速开始
```bash
pip install -e ".[dev]"
cp config.example.toml config.toml     # 首次：生成本地配置（勿入库）
timeflow                                # 启动桌面窗口
# 或仅本地 API：python -m uvicorn timeflow.api.app:create_app --factory --port 8520
```

## 功能模块（对应治理三层 SR-F）
| 模块 | 说明 | 规格 |
|---|---|---|
| 任务管理 | My Day / CRUD / 逾期栏 / 多分组 / 子任务 / Repeat / 状态机 | SR-F1 |
| B 系统记账 | 逾期=债务(天数/程度) / 专注=投入 / 顶部轻量摘要 / 产出投入流水 | SR-F2 |
| 专注计时 | 番茄/普通计时、绑定任务、中断三选、白名单勿扰 | SR-F3 |
| 反馈/习惯/自检 | 每日复盘、习惯打卡热力图、自检消费B数据 | SR-F4 |
| 学业追踪 | 课程档案 / 考核项 / GPA（**4.0/5.0 制可切换**） | SR-F5 |
| 复习(FSRS) | 间隔重复调度、反馈三态、外部执行源 | SR-F6 |
| 团队/AI | 管理者/执行者、任务分配、AI 接口(只读+新增) | SR-F7 |
| 备忘录/知识资产 | 顺手记录、**只存引用句柄**(Vault路径/KB-id) | SR-F8 |
| 存储/同步 | SQLite + schema迁移 + LWW同步(不静默覆盖) | SR-F9 |

## 结构（三层治理 + 源码）
```
intention/  为什么做（N1–N46 + 决策）
specification/  必须做到什么（SR-F / SR-NF，N→SR 追踪）
  conventions.md  约定层（横切基线，实现任何 SR 前必读）
contracts/  怎么才算真的做成（操作闭环 + 动线，实现前必读）
implementation/  怎么实现（模块名+职责+取舍，SR→模块）
taste/  技术品味与红线
CODING_GUIDELINES.md / ACCEPTANCE.md  护栏与验收
src/  源码（app · api · core · storage · getaways · config）
tests/  单元测试（44 项）
```

> **文档读法（防"做一半"）**：实现任一功能前，先读 `specification/conventions.md`（不能违反什么）→ 再读 `contracts/interactions.md` + `contracts/flows.md`（怎样才算做完/走通）→ 最后看 `implementation/`（谁负责写）。

## 状态
- ✅ intention / specification / implementation 骨架闭环（含护栏、验收、三层对齐脚本）。
- ✅ **第一版完整**：任务管理 + B 记账 + 专注(F3) + 反馈/习惯(F4) + 学业/GPA(F5) + 复习FSRS(F6) + 团队/AI(F7) + 备忘录(F8) + 同步(F9) + **GPA 4.0/5.0 切换**。
- ✅ 质量门：pytest 44 passed / ruff 0 / mypy 0 / 三层对齐 PASS。
- ⏭️ 后置（第二版）：重规划/债务重组(F2.8)、AI 接口写/改/删、学校通知监测脚本(F10)、移动端 PWA 深联动。

> 设计决策（know-why）见 `DESIGN.md`；工程规范见 `CODING_GUIDELINES.md`；功能验收见 `ACCEPTANCE.md`。
