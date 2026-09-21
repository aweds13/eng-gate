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

## 功能模块（对应治理规格层 SR-F）
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

> 重构地基：`src/core/facts/`（事实层 + 事件总线）不属于任何 SR-F 功能域，服务于「事实/解读分离」，详见 `implementation/architecture.md`。

## 结构（五层治理 + 源码）

**`docs/` 目录（治理文档）**：
```
intention/        为什么做（N1–N46 + 决策）
specification/    必须做到什么（SR-F / SR-NF，N→SR 追踪）
  conventions.md    约定层：横切基线（不能违反什么）
  behaviors.md      用户逻辑横切细则（B-xx：状态/校验/撤销/边界/并发）
  domains/          每域详细规格（F1–F10）
contracts/        怎么才算真的做成（操作闭环 + 动线）
  interactions.md   单个操作六要素（MVP 核心）
  flows.md          多操作链路（触发→传导→落点；MVP 核心）
  domains/          其余域与边界契约（F1–F10）
implementation/   哪个模块负责（模块名+职责+取舍，SR→模块）
  coverage.md       SR→操作/动线→验收→测试 覆盖矩阵
taste/            技术品味与红线（已重写为项目专属）
README.md / ACCEPTANCE.md / CODING_GUIDELINES.md / EXTENDING.md / changelog.md   总入口·验收·护栏·如何加功能·日志
```

**仓库根（代码与配置）**：
```
src/    源码（timeflow/：app · api · core · storage · getaways · config）
tests/  单元测试 + tests/acceptance/（可执行验收，B4）
examples/  三个由浅入深的**可跑**扩展示例（加事实 kind / 加配置项 / 加解读层口径）
scripts/  护栏脚本（check_layers.py：五层对齐检查）
config.example.toml / pyproject.toml
```

## 想加一个功能 / 想自己定制？
- **照着填**：`EXTENDING.md`（「如何加一个功能」五步模板 + 三条红线 + 反模式清单）。
- **照着跑**：`../examples/`（三个示例都是可直接执行的脚本，跑在临时库上，不碰你的真实数据；
  有 `tests/test_examples.py` 兜着，示例跑不通 = 门禁红）。
- **只想调参数**：抄 `config.example.toml` 成 `config.toml`，或设 `TIMEFLOW_<段>__<键>` 环境变量。

> **文档读法（防"做一半"）**：实现任一功能前，依次读
> ① `specification/conventions.md`（不能违反什么）→
> ② `contracts/interactions.md` + `contracts/flows.md`（怎样才算做完/走通）→
> ③ `implementation/`（谁负责写）。

## 状态
- ✅ 五层骨架闭环：intention / specification（含 conventions）/ contracts / implementation / taste（含护栏、验收、五层对齐脚本 `check_layers.py`）。
- ✅ **第一版功能域已落地（存在级）**：任务管理 + B 记账 + 专注(F3) + 反馈/习惯(F4) + 学业/GPA(F5) + 复习FSRS(F6) + 团队/AI(F7) + 备忘录(F8) + 同步(F9) + **GPA 4.0/5.0 切换**。
- ✅ **重构第 0 / 0.1 / 1 步已完成**：事实层（facts + 总线）→ 事实语义分 kind + v4 历史回填 → `ledger.summary()` 改读 facts（完成日口径）。详见 `changelog.md`。
- ⚠️ **已知断层**：契约层 `contracts/` 揭示多项"操作闭环/模块联动"缺口（详见 `../复盘/三层断裂诊断-实现与交互复盘.md`），存在 ≠ 完成，LC-1~LC-8 多数仍 ❌。
- ✅ 质量门：`scripts/run_gates.py` **十一项阻断门**全绿（pytest 501 passed / 验收 2 / ruff 0 / mypy 0（38 文件）/ 五层对齐 PASS / 护栏自测 PASS / DOM 探针 / 台账审计 / 台账↔规格标题对账 / 两项真机自检）；覆盖率门 70%（写在 `pyproject.toml`）。
- ✅ **可执行验收层（B4）**：`../tests/acceptance/README.md`（默认排除，显式 `-m acceptance`）。
- ✅ **可扩展/易上手**：`EXTENDING.md`（加功能的五步模板）+ `../examples/` 三个可跑示例（SR-NF7 / SR-NF10）。
- ⏭️ 后置（第二版）：重规划/债务重组(F2.8)、AI 接口写/改/删、学校通知监测脚本(F10)、移动端 PWA 深联动。

> 工程规范见 `CODING_GUIDELINES.md`；功能验收见 `ACCEPTANCE.md`；变更日志见 `changelog.md`。
> 设计决策（know-why）：`DESIGN.md`/`LEARN.md` **经用户决定撤回、暂不建**（决策见 `../复盘/DESIGN-LEARN撤回与闭环验收恢复.md`），暂以本文件 + `changelog.md` + `specification/conventions.md` + `contracts/` 承载。
