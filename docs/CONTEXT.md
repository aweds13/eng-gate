# CONTEXT — 项目接续点（新会话从这里接手）

> 本文件是**会话交接**用的。新对话窗口的 agent 读到它，就能快速恢复全部上下文继续开发。
> 项目名：**timeflow**（本地优先的个人时间与学习投入管理工具）。工作区：`D:/docs\engineering`。

## 这是什么（一句话）
一个**本地优先、桌面端为主**的个人「时间与学习投入」管理工具：My Day / 任务 / 拆解 / 分组，**债务/储蓄如实记账**（逾期=债务、投入=储蓄），守住与学校考核不冲突，可外接 AI 与知识资产。

## 治理三层（TASTE，参考 openbiliclaw）
- `intention/needs.md`：N1–N46 + 记账规则 + 核心概念 + 决策/范围（**权威需求**）
- `specification/`：SR-F（功能）×10 领域 + SR-NF（质量）×18 + `traceability.md`（N→SR 闭合）
- `implementation/`：模块骨架（README/modules/architecture/traceability，SR→模块）
- `taste/README.md`：品味与红线；`DESIGN.md`：know-why 设计决策

## 护栏 / 质量门（已就位）
- `CODING_GUIDELINES.md`（工程规范）、`ACCEPTANCE.md`（每功能 DoD 验收清单 AC-1~AC-12）
- `scripts/check_layers.py`：三层对齐检查（intent→spec→impl，禁止已砍概念回流）
- `scripts/backup.py`：备份 db/config 到 `backups/`
- 命令：`ruff check src/ tests/`、`mypy src/`、`pytest --cov=timeflow`

## 已完成（第一版 MVP）
- ✅ 三层文档 + 护栏 + 项目骨架（git 已有 root commit）
- ✅ 依赖装好：fastapi / uvicorn / pydantic / pywebview / pytest / mypy / ruff（`pip install -e ".[dev]"`）
- ✅ 源码：`src/timeflow/`（config / api / app / core(tasks·ledger) / storage / getaways）+ `src/web/index.html`
- ✅ **任务管理 MVP**：任务 CRUD / My Day / 逾期识别 / 状态机 / 子任务(子完成父自动完成) / Repeat / 轻债务(逾期=债务计数+天数/程度+顶部摘要) / SQLite 持久化 / 桌面窗口(pywebview)
- ✅ **测试全绿**：pytest 11 passed，覆盖率 79%，ruff 0，mypy 0
- ✅ **服务验证能跑**：`python -m uvicorn timeflow.api.app:create_app --factory --port 8520`（已实测 `Application startup complete`）；`timeflow` 可启动桌面窗口（pywebview，失败回退浏览器）

## 下一步（接线清单）
1. **运行验证**：curl `http://127.0.0.1:8520/api/health`、`/api/summary`、`/`（index.html）；POST 一个任务看债务摘要。（用 `curl.exe`，别用 PowerShell Invoke-WebRequest——会 PermissionError）
2. **git 提交当前代码**：`git add -A && git commit -m "feat: 任务管理 MVP（CRUD/MyDay/逾期/子任务/Repeat/轻债务 + SQLite + 桌面窗口）"`
3. **展示**：给用户看初步界面（可截图 index.html 或说明运行方式）；运行 `scripts/check_layers.py` + 跑一次质量门确认
4. **后续模块**（按 SR 逐步）：专注计时(SR-F3) → 复习FSRS(SR-F6) → 学校KPI(SR-F5) → 团队/AI(SR-F7) → B记账完整(SR-F2 细化) → 备忘录/知识资产句柄(SR-F8)

## 关键约定
- 用 `git worktree` 独立分支开发新功能；Conventional Commits；每功能对照 `ACCEPTANCE.md` 的 DoD。
- 改代码后跑 `scripts/check_layers.py` + 质量门（ruff/mypy/pytest）。
- B 系统温和不施压、如实记账；知识资产只存引用句柄、不碰 Vault 文件；数据不出本地。
