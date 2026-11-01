# 卡 B2 · 工作台搬进 DSH：先把「要搬什么」盘成一张能派活的表

**task**：T-BG002　**risk**：mid　**tree**：`.wt/B2`

## 为什么

用户 m08232 原话：「把 Open Maic 工作台所有的东西都迁移到 DSH 里面。这是第1个任务。」

这句话目前**没法直接开工**，因为它没说清三件事，而这三件事决定了后面每一张卡长什么样：

1. **「所有东西」是哪几样？** OpenMAIC 自己不是一个页面，是三层叠起来的：`app/` 的 Next 路由（3000 端口那个生产构建）、`lib/server/agent-runtime` 的 50 个 agent 工具与生成循环、PostgreSQL 里的 `document_stages` / `document_scenes`。DSH 插件 `openmaic-course` 现在只直连了**第三层**的读面（`lib/db.mjs` 直连 5433），`lib/index.js` 里 `localhost:3000|/api/` 零命中 —— 也就是说**它一行 agent-runtime 都没跑**。
2. **「搬」到哪一层？** 同一个功能，做成「DSH 工具」（模型能调）和做成「DSH 面板」（人能点）是两个完全不同的活，判据也不同。已有 12 个工具可以照着的路子走，但没有盘点就不知道哪些功能**根本不该搬**（例如生成循环要不要搬进 DSH，还是留着 OpenMAIC 自己跑）。
3. **怎么分批？** 一口气搬 160 个功能点必然做不完也验不了。

**不盘点的后果**（已经真实发生过一次）：B0 交付时 `client.src.js:130` 写 `const data = page.data || {};`，而 `/page` 端点返回的形状里**没有 `data` 层** —— slide 分支恒不成立、页面停在「取文本…」。这个缺陷能过三份文档的关，是因为当时没有一张「每个功能点 → 它该长成什么样 → 怎么算做完」的表。

## 判据（怎么算做完）

1. 交付 `docs/implementation/迁移DSH.md`，含三部分：**A 盘点表**（OpenMAIC 工作台的每个功能点一行）、**B 五分类判定**（每个功能点恰好落在 A/B/C/D/E 之一）、**C 分批计划**（每批有依赖顺序、有验收口径）。
2. **盘点覆盖到模块级而非文件级**：每个功能点必须指到它现在真实的实现位置（`lib/**` 的具体模块，`wc -l` 过），不是只写「课程页」。
3. **五分类的定义要能互相排斥**：
   - **A 已有**：DSH 里现在就能干这件事（12 个工具 + 面板），给出在跑的证据；
   - **B 加工具**：只缺一个模型可调的工具，代码能放进插件仓；
   - **C 加面板**：必须人眼看/人手动，要 `sidebar.panellist` 或 `main` 槽；
   - **D 留原生**：**故意不搬**，写清为什么（这是最重要的一类，见判据 5）；
   - **E 该删**：搬过去以后 OpenMAIC 侧的对应实现可以退役，写清依赖它的还有谁。
4. 交付 `docs/implementation/迁移DSH-盘点表.csv`，列为 `功能点,现状实现,分类,批次,判据,风险`，行数 = A 部分的行数（脚本可比对）。
5. **D 类必须给理由，不能留空**，且理由必须是「搬过来会失去什么」或「谁的循环在跑它」这种可反驳的话，不是「优先级低」。参照 §D 两条已定案：生成循环留 OpenMAIC（DSH 插件里 `db.mjs` 直连库、不调 3000 ⇒ agent-runtime 不跑）；上下文压缩留宿主（`compaction.ts` 压的是 OpenMAIC 自己的 durable entry tree，工作台搬走后不会被调用，且 `config.ts:49` 硬等 `'true'`，现在本来就没开）。
6. **每批必须能独立验收**：一批做完，用户能自己看一眼说「这批成了」，不需要等下一批。
7. 文档过 `python -X utf8 scripts/check_layers.py`（本卡不动 `docs/` 的五层判据，但反引号里的 `.md` 必须是真实文件 —— 这是 `wb_land.py --precheck` 会咬的）。

## 不做什么

- **这一轮不改代码**、不写插件、不重启 DSH。本卡只出文档与表。
- 不改 `AGENTS.md`（`docs-map-coverage` 硬断言 `Buffer.byteLength < 56_000`，现在 **55990 B**，余 10 B —— 加一行就红）。
- 不碰 `D:/repo/_tools/dsh-plugins/`（那是插件仓自己的域，且它在 engineering 仓外，写不进 `files`）。
- 不评估「性能」「要不要换框架」这类方向性问题 —— 只盘功能点与搬运方式。
- 不对 OpenMAIC 侧做任何删除；E 类只写建议，不动手。

## files

`docs/implementation/迁移DSH.md`、`docs/implementation/迁移DSH-盘点表.csv`

## 证据（开工前已知的读数）

- 插件现状：`openmaic-course` 7 工具（`openmaic_courses` / `scenes` / `page` / `active` / `page_text` / `search` / `patch_stage`）+ `openmaic-local-capabilities` 5 工具（`local_services` / `pdf_to_markdown` / `browse_page` / `course_search` / `embed_texts`）= **12**。
- 插件 seam `SEAM = "/dsh-openmaic"`，端点是 `GET /courses|/scenes|/page|/text|/active` + `POST /active`；`ACTIVE`/`LAST_ERROR` 是**进程内状态**（重启清空）。
- `lib/db.mjs` 直连 PostgreSQL（`const { Client } = req("pg")`，`DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5433/postgres`）；`lib/index.js` 里 `localhost:3000` 与 `/api/` **零命中**。
- 库表：`document_stages(id, name, description, interactive_mode, task_engine_mode, created_at, updated_at, folder_id, data JSONB)`、`document_scenes(stage_id, id, scene_order, data JSONB, PK(stage_id,id))`、`document_folders`；**无版本列** ⇒ 并发保护只能靠 jsonb 值本身（CAS 逐字：`` `update document_scenes set data = $1::jsonb where stage_id = $2 and id = $3 and data = $4::jsonb` ``）。
- agent 侧工具数 **50 个**，我们新加约 20 个（`lib/practice/practice-tools.ts` 406 行 / `lib/scratch/scratch-tools.ts` 451 行 / `lib/server/agent-runtime/plan-freeze-tools.ts` 622 行 等）。
- 上下文压缩现况（D 类已定案）：`lib/server/agent-runtime/config.ts:49` `compaction: { enabled: process.env.OPENMAIC_AGENT_COMPACTION_ENABLED === 'true', ... }`；导入点 `lib/server/agent-runtime/runner.ts:125`、调用点 `:1485`；压缩对象是 `entry-tree-storage.ts` 的 `firstKeptEntryId` + `Session.appendCompaction`。
- `docs/` 现有 34 份 md，五层判据工具 `D:/repo\program\OpenMAIC\scripts\check-layers.py` 目前 **122 条引用 / 断链 0 处 / PASS ✅**。
