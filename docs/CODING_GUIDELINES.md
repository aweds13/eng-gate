# 编码规范（CODING_GUIDELINES）— 本仓库所有代码必须遵循

> 依据：本项目 TASTE（品味/红线）+ implementation 模块划分 + 五层（intention / specification(+conventions) / contracts / implementation / taste）对齐。原则：**一切以仓库现状为准；改动必须经 AC 验收、可回退、有测试、有文档。**
> 本文件是**护栏**（硬规则），与 `ACCEPTANCE.md`（功能验收）、`specification/conventions.md`（约定基线）、`contracts/`（操作/动线契约）、`taste/`（品味）配合。

## 0. 实现前必读顺序（硬约束）
1. `specification/conventions.md` —— 不能违反什么（横切基线）
2. `specification/behaviors.md` + `specification/domains/` —— 用户逻辑横切细则 + 每域细节
3. `contracts/interactions.md` + `contracts/flows.md` + `contracts/domains/` —— 怎样才算做完/走通
4. `implementation/README.md` + `modules.md` + `implementation/coverage.md` —— 谁负责写 + 覆盖矩阵

> 判定原则：**「存在」不等于「完成」**；操作六要素齐备且契约验收通过才算实现完成。

---

## 1. 项目结构（别放错地方）
- 主代码：`src/`（`app/` 壳 · `api/` · `core/`(tasks·ledger·focus·feedback·academic·review·team·memo·facts) · `storage/` · `getaways/`）
- 测试：`tests/`（`test_<module>.py`）；前端：`src/web/`；配置：`src/config.py`
- 文档：`docs/`（或根 README；DESIGN/LEARN 经用户决定撤回、暂不建）；护栏：`CODING_GUIDELINES.md`、`ACCEPTANCE.md`

## 2. 环境与检查命令（写完后必须跑）
```bash
ruff format src/ tests/        # 格式化
ruff check src/ tests/         # lint（⚠️ 新增代码必须零错误）
mypy src/                      # 类型检查（strict；改接口/配置/类型必跑）
pytest                         # 测试（提交前必跑，且功能 AC 通过）
python -X utf8 scripts/check_layers.py       # 五层对齐（含引用完整性）
python -X utf8 scripts/test_check_layers.py  # 护栏脚本自测（正/负样例）
pytest --cov=timeflow          # 覆盖率（目标 ≥70%）
```

## 3. 编码风格（Python，Ruff 为准）
- 4 空格、PEP 8、`line-length = 100`。
- Ruff select：`E,W,F,I,N,UP,B,SIM,TCH`。
- 公开函数/核心数据结构**必须**写类型注解 + 简洁 docstring；模块名小写下划线。

## 4. 类型检查（mypy strict）
`strict = true`；新增代码必须通过 `mypy src/`，不得引入新类型错误。

## 5. 测试要求（每功能必配 DoD）
- 新增功能**默认同时补单元测试**（`test_<behavior>`），并**在 `ACCEPTANCE.md` 登记该功能验收**。
- 真实/外部调用（知识资产/网络）拆成**可 mock** 的单测；真实调用留给集成测试（标 `integration` marker）。
- 覆盖率目标 ≥70%；提交前 `pytest` 全绿。

## 6. Worktree 开发约定（强制）
- 新功能/修 bug **先用 `git worktree add` 建独立 worktree + 分支**，在其中改/测/提交；不得在主工作区直接动手。
- 开始前确认当前工作区未提交改动不丢失；完成后保留清晰分支边界。

## 7. 提交规范（Conventional Commits）
```
feat: add task CRUD
fix: correct overdue detection
docs: update ledger design
refactor: extract storage layer
test: add task manager tests
build:/chore:/perf:/ci: ...
```
- 类型（scope 可选）：`feat fix docs refactor test build chore perf ci`；动词现在时、小写。

## 8. PR 要求
- PR 说明含：**变更摘要 + 测试命令与结果 + 关联的 SR/N + ACCEPTANCE 条目**。
- **不得**提交真实 `config.toml`、Cookie、API Key、本地敏感数据。

## 9. 文档更新要求（强制）
- 改接口/模块边界/配置/数据流/依赖 → 同步 `implementation/modules.md`(模块职责) + `changelog.md` + `config.example.toml`；若涉及横切规则 → 同步 `specification/conventions.md`。
- 新增/修改操作、动线、验收或测试 → 同步 `implementation/coverage.md`；发现规格缺口 → 先登记 `复盘/缺口处理与假设台账.md` 再实现。
- 改动必须能通过五层对齐：**intention → specification(+conventions) → contracts → implementation → taste**（见 `scripts/check_layers.py`）。

## 10. 配置与敏感信息
- 配置基于 `config.example.toml` → 本地 `config.toml`（gitignore）；敏感（API Key/Cookie）**只存本机**，不入 Git/PR/日志/截图。
- 新增配置项 → 同步 `config.example.toml` + 文档。

## 11. 本地优先红线（坚决不做）
- **数据不出本地**（不上云）；复杂外部监测不硬塞进主工具（走接口）。
- **不直接读写 Obsidian/Vault 文件**（知识资产只存引用句柄，读写给「知识资产项目」）。
- **不新增对用户数据的外部依赖**（保持本地优先/隐私最小）。
- **不破坏**一致性机制（LWW 同步/同 id 去重/schema 迁移/备份回滚）。
- B 系统**不得**变成施压器（温和、不告警、如实）。
