# timeflow — 本地优先的时间与学习投入管理工具

> 一个**本地优先、桌面端为主**的个人「时间与学习投入」管理工具：管要做什么（My Day / 任务 / 拆解 / 分组），**用「债务 / 储蓄」如实记账**（该做没做=债务、投入=储蓄），守住与学校考核不冲突，可外接 AI 与笔记。

## 它解决什么
- 想清楚「今天该做什么」（My Day），并把待办如实记下来、能追踪、能拆解。
- 用「债务 / 储蓄」看自己在**长期投入上是否均衡**（不突击、不拖延），但**不施压**——只如实记账、温和呈现。
- 学校 KPI / 考试 / 作业别漏掉（硬约束提醒），与自学不冲突。

## 快速开始
```bash
pip install -e ".[dev]"
cp config.example.toml config.toml     # 首次：生成本地配置（勿入库）
timeflow                                # 启动桌面窗口
```

## 结构（三层治理 + 源码）
```
intention/  为什么做（N1–N46 + 决策）
specification/  必须做到什么（SR-F / SR-NF，N→SR 追踪）
implementation/  怎么实现（模块名+职责+取舍，SR→模块）
taste/  技术品味与红线
CODING_GUIDELINES.md / ACCEPTANCE.md  护栏与验收
src/  源码（app · api · core · storage · getaways · config）
tests/  单元测试
```

## 状态
- ✅ intention / specification / implementation 骨架已闭环（含护栏、验收、三层对齐脚本）。
- 🔨 编码中：第一版 MVP = 任务管理（My Day / CRUD / 逾期 / 分组 / 子任务 / Repeat / 轻债务 + SQLite + 桌面窗口）。
- ⏭️ 后续：专注计时、B 系统完整记账、复习(FSRS)、学业 KPI、团队/AI 接口、知识资产句柄。

> 设计决策（know-why）见 `DESIGN.md`；工程规范见 `CODING_GUIDELINES.md`；功能验收见 `ACCEPTANCE.md`。
