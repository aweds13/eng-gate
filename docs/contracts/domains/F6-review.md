# SR-F6 复习间隔重复 · 操作与动线契约

> 六要素见 `../interactions.md`；横切行为见 `../../specification/behaviors.md`。

## OP-26 建复习卡 / 升级

- 入口：复习页「新建」；学习任务「升级为复习」。
- 前置：无 / 任务存在。
- 输入：title、form（预留）、execution_source、ref_handle。
- 后续：落库 → 到期列表；升级时保留任务关联。
- 可逆：可删除。
- 反馈：卡片出现。
- 边界：空标题拒绝；非法 form/source 拒绝。
- **实现（T-C5/C6/C7，2026-09-20）**：
  - 任务 → 复习卡升级：`POST /api/tasks/{id}/to-review`（`{title?, form?, source?, ref_handle?}`），
    卡的 `task_id` 挂上来源任务（**弱关联**：不建外键、删任务不级联）；
    **幂等** —— 同一任务已经升级过就返回已有那张卡（`created=false`），不会越点越多张；
    任务侧反查：`GET /api/tasks/{id}/review-cards`。
  - 字段：`review_items.form`（`cloze` 挖空 / `qa` 问答卡 / `exam` 真题，v2 起就有）+ `task_id`（schema **v12**）；
    词表与中文标签只在后端一处，界面用 `GET /api/review/meta` 渲染。
  - 改定义类字段：`PATCH /api/review/items/{id}`（标题/形式/执行源/引用句柄）+ `GET /api/review/items/{id}`；
    **排期字段（due_date/interval/ease/reps）不给人手改** —— 那是 FSRS 的记忆状态。
  - 升级动作**不发事实、不动账本**；账目只来自真正的「复习完成」（OP-27）。
  - **界面入口（前端批次，2026-09-20）**：任务详情里有「升级为复习卡」按钮
    （`data-action="task-to-review"`）→ 升级后**跳到复习页**，并在任务详情里就地列出该任务已有的卡
    （标题 + 到期日，按钮随之变成「再看复习卡」）；复习卡的「改形式/句柄」展开**行内表单**
    （形式 / 执行源下拉 + 引用句柄输入），词表来自 `GET /api/review/meta`，表单里明写
    「到期/间隔/次数由 FSRS 管，不给人手改」。
    **点两次不会建两张卡** —— 幂等由后端保证，界面只如实说「已经有卡了」。

## OP-27 三态反馈

- 入口：复习卡「记得 / 模糊 / 忘了」。
- 前置：卡片到期。
- 输入：rating。
- 后续：FSRS 推进间隔 → 更新 due/reps → 记 `review.completed` 事实 → 投入账。
- 可逆：可撤销本次反馈（回退 interval/reps 与事实）——**第 5 步已实现**（`POST /api/review/{id}/undo`）。
- 反馈：下一间隔/到期时间即时更新。
- 边界：非法 rating 拒绝；同一天同卡只记一条投入事实（重复完成幂等）；已撤销的那次不阻止重新复习入账。
  **日期一律本地日历**（`specification/behaviors.md`：日界 00:00）—— 到期日/创建日/下次到期
  都按本地日期落库与返回，**不拿 FSRS 时刻的 UTC 日期**（T-D12 修：东八区凌晨曾会差一天）。
- API（第 2 步实现）：`POST /api/review/{id}/review`、`GET /api/review/{id}/facts`（事实流水）。
  撤销：`POST /api/review/{id}/undo`（当日最近一次；回退到事实里存的 before 快照 + 追加 `review.undone`）。
- **改判（T-G13，2026-09-23）**：「记错了想改成另一档」不只是"撤销再点一次"——
  `POST /api/review/{item_id}/regrade`（body `{feedback}`）= **撤销这一次 + 按新档重来**，两步都走既有路径：
  - FSRS 从**同一个复习前快照**重算 → "改判"与"当时就点另一档"结果**逐项相同**；
  - 原事实**不删**（追加 `review.undone` 指回它 + 新的 `review.completed` + 一条 `review.regraded`）；
  - **投入不重复计**（账本按"当日有效完成事实、同卡只算一次"）；
  - 拒绝都 **400 带原话**：今天没复习过 / 跟原来一样 / 非法档；卡不存在 404；
  - `GET /api/review/today` 给界面「今天复习过的」那一段（含这次记的是哪一档）；
    三档中文由 `GET /api/review/meta` 的 `ratings` 给（**词表只在后端一处**）。
  - 验证：`../../tests/test_review_regrade_line.py`（11 条）+ 真机自检 9 条 + DOM 探针「复习·改判」1 档。

## OP-28 到期列表 / 进 My Day

- 入口：复习页到期列表。
- 前置：有到期卡。
- 输入：无。
- 后续：排序（重要度 + 最久未复习）→ 建议进 My Day；不强制。
- 可逆：可移出。
- 反馈：列表按优先级展示。
- 边界：无到期卡空态；进 My Day 不重复。
- API（第 2 步实现）：`GET /api/mydays?include_reviews=1` 并入到期复习卡（`kind="review"`），默认不含。
- 第 9 步补充（SR-NF3「卡片+进度条+到期列表」）：复习页顶部加**今日复习进度条**
  （今日已复习 ÷（已复习 + 仍到期）），到期卡以卡片呈现；进度只反映今天，不做目标对标。

## OP-29 关联引用句柄

- 入口：卡片详情。
- 前置：无。
- 输入：Vault 相对路径 / KB-ID。
- 后续：只存引用；读写交给知识资产项目。
- 可逆：可清除。
- 反馈：引用显示。
- 边界：不直接读写外部文件。
- **实现（T-C7，2026-09-20）**：`ref_handle` 可经 `PATCH /api/review/items/{id}` 写入或清空
  （空串 = 清成 NULL，不写空串；非法值拒绝）；`GET /api/review/meta` 无需句柄。
  **界面入口也接上了**（前端批次）：复习卡「改形式/句柄」行内表单里的句柄输入框，留空即清除；
  卡面另有一行显示当前引用（`引用 notes/数学.md`）。
- **实现补充（T-G5，2026-09-21）**：卡面那行引用旁边可直接 **`obsidian://` 只读跳转**
  （`POST /api/vault/open`）—— 需要先填 Vault 名字（可选根目录，用来把绝对路径句柄换算成库内位置）；
  界面在后端给了链接时才摆按钮，跳不起来必出声（原话 + 复制链接）；**不往 Vault 里写任何东西**
  （红线 `SR-F8.2`，复盘见 `../../../复盘/Obsidian跳转与红线机器化-T-G5.md`）。

## OP-30 外部 app 完成

- 入口：外部 app 复习完，手动点完成。
- 前置：卡片 execution_source=external。
- 输入：无 / 可选 rating。
- 后续：推进间隔并记投入。
- 可逆：可撤销。
- 反馈：状态更新。
- 边界：外部进度只能手动报；不自动抓取。

## 复习闭环

- 到期 → 进 My Day 建议 → 三态反馈 → FSRS 推进 → 投入。

## 验收与测试

- 对应 AC-20。
- 测试：`../../tests/test_academic_review.py`；B4 补全链路。
- 改判（T-G13）：`../../tests/test_review_regrade_line.py` + `../../tests/test_web_frontend.py`
  （三档中文来自后端 / 只给另外两档 / 说清代价）+ 真机自检 `../../tools/web_live_check.py`。
