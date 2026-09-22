# SR-F9 存储 / 同步 · 详细规格

> 上游：N25 / N41 + `../functional.md` SR-F9.1~F9.3 + `../nonfunctional.md` SR-NF12/NF14/NF16 + `../conventions.md` + `../behaviors.md`。
> 契约见 `../../contracts/domains/F9-storage-sync.md`；覆盖见 `../../implementation/coverage.md`。

## 1. 实体与字段

- **schema_version**：version。
- **业务表**：tasks / focus_sessions / facts / ledger_entries / feedback_logs / habits / courses / review_items / memos / team_assignments / sync_logs 等。
- **sync_logs**：id、entity、local_ts、remote_ts、**result**、**note**、created_at
  （后两列 v17 补：只记时间戳看不出"是覆盖了还是保留了本地"）。
- **sync_tombstones**（v17）：entity、entity_id、deleted_at —— **删除墓碑**，
  由各表 DELETE 触发器自动产生（硬删的东西不被旧包复活）。
- **`updated_at`**（v17，六张会被改的表 + memos）：跨端判新旧的依据，由触发器自动维护；
  `tasks` 早就有它（且刻意维护得更精细：换「进行中」顺序不动它）。
- **配置**：`config.example.toml` → 本地 `config.toml`（gitignore）；Pydantic 校验 + env 覆盖。

## 2. 状态与生命周期

- schema 版本只增不减；connect 时逐版本升级到目标版本；每版增量、幂等。
- 同一数据跨端同步：时间戳 + version → LWW；同 id 去重 + 来源标记；冲突写日志。
- **版本履历**：v3 事实层（facts）；v4 历史 `focus_sessions` 回填 `focus.*` 事实；
  v5（第 3 步）历史**已完成任务**回填 `task.completed` 事实（`extra.migrated=True`，
  归属时间取 `updated_at`，缺列/缺值退回 `created_at`；只回填「完成」，不做反向猜测）。
  历史复习记录**不回填**（无逐次时间戳，见 A-015）。

## 3. 规则

- **R1 本地优先**：SQLite / 本地文件；数据不出本地；离线可用。
- **R2 迁移**：版本化 + 幂等 + 可回滚；旧数据不丢、不重复。
- **R3 同步**：LWW 较新者胜；不静默覆盖；冲突给提示/日志。
  - **落地（2026-09-22，G 批 · T-G8 = 场景 ③）**：判据 **version → updated_at**；
    每次导入**逐条**记 `sync_logs`（`result` + "差在哪"）；界面**先预览（dry_run）再二次确认**；
    预览与真导入用**同一套判断**（先规划 `plan_merge` 再执行）。
    走**文件**：导出同步包 → 拷到另一台 → 预览 → 导入；走网络的 ①② 仍未做（分开报，不谎报）。
- **R4 去重**：同 id + 来源标记；重复导入幂等。
  - **落地**：三类表三套规则 —— **LWW 行**（tasks/habits/groups/course_assessments/review_items/
    team_assignments/feedback_logs/memos）、**只增行**（facts/focus_sessions/courses/grades/
    ledger_entries，只插不改）、**关系行**（task_groups/habit_logs，缺则插、墓碑拦住的不插）。
    **主键不能假设都叫 `id`**（`feedback_logs` 是 `date`、两张关系表是复合键）——
    有护栏拿 `PRAGMA table_info` 对账。
- **R5 备份**：重要数据（任务/学业/复习历史）可备份、可回滚。
- **R6 数据分流**：计算型走结构化索引；沉淀型走 Markdown（目标态，契约第 3 步定）。
  - **落地（2026-09-21，G 批 · T-G4）**：每天一个 md（frontmatter 带 type + 命名空间）写到
    **用户指定的独立目录**（`core/vault.py`；`[export] dir` → 设置页）；**数据库是权威、md 是产物**
    （手改不读回、下次导出覆盖）。**与 Obsidian 笔记分目录**（红线 SR-F8.2）；跳转见 T-G5。
- **R7 隐私**：敏感只存本机，不入 Git/PR/日志/截图。
- **R8 AI 接口**：可被 AI 读写（第一版只读+新增），走同一去重/LWW。

## 4. 边界与异常

- 迁移失败：回滚到升级前状态；不留下半迁移库。
- 并发写 / 数据库锁：可重试；不产生半截数据。
- 时间戳相同 / 设备时钟偏差：按版本或来源决胜，冲突写日志。
- 同 id 不同内容：LWW + 记录被覆盖旧值。
- **导入永不删本地数据**（T-G8 v1 明确边界）：远程墓碑只用于**防复活**与**继续传给下一台**，
  不替用户删 —— 于是**删除不跨端传播**（你在 A 删掉的，B 那边还在，只是 B 也不会被旧包复活它）。
  要改成"删除也传播"，得允许导入侧删行，属产品决策（登记为 T-G8b）。
- 坏包 / 非本格式 / 格式版本比程序新 / 自己导给自己：**400 带原话**（不"尽力猜"）。
- 备份损坏：校验失败要报错，不静默覆盖。
- 本地配置缺失：用 example 默认 + 明确提示。
- 大库：查询走索引；多年数据仍可用。
- 数据库损坏：给恢复/备份指引，不静默清空。

## 5. 动线

- 启动 → 迁移 → 可用；跨端 → 同步 → 冲突处理 → 对齐。
- 备份 → 改动 → 回滚。

## 6. 验收

- AC-10 持久化、AC-23 同步 LWW。
- 补充：迁移幂等、冲突不静默覆盖、备份可回滚、配置隐私。

## 7. 测试映射

- 现有：`../../tests/test_sync.py`（LWW 单元 + 状态）、`../../tests/test_facts.py`（含 v4/v5 迁移与幂等）。
- 同步包与合并（T-G8）：`../../tests/test_sync_pack_line.py`（30 条：包身份与排除表 / 坏包四连拒 /
  LWW 两向 / 只增行 / 关系行 / 墓碑防复活 / 远程墓碑不删本地 / dry_run 不动库 / 幂等 /
  六张表触碰 + tasks 的刻意例外 / 五种硬删留墓碑 / app_settings 不跨端 / API 与跨站）；
  真机自检 10 条（`../../tools/web_live_check.py`）。
- 待补：并发写、时间戳同秒打平的确定性（现为"保留本地 + 记冲突"）。
