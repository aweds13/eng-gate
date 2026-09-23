# T-G21 · AI 写事实回报进展（N46 / OP-32）

> 2026-09-24。用户一句「**开工**」（前一轮我列的三条路里第 ① 条正是"开工 T-G21"）。
> 这是台账里**最后一张"只差开工"的卡**：口径 2026-09-23 就定了（方案 3），唯一关卡
> `conventions.md` 第 34 行在 T-G39 改齐 —— 所以这一轮**没有待定项、没有回头问**，
> 按设计文档 `复盘/口径落档-T-G19.md` §3.2 的四条直接落地。

---

## 一、这一卡在解决什么

N23 的边界（AI 只读 + 新增、不改不删）与 N46 的诉求（**AI 干完要能"回报进展"**）之间
原本只有一个出口：**加子步骤**。但真实用法里最常见的一句是 ——
「我把第 3 章读完了，第 6 题卡住」：这既不是"新建一件事"，也不是"这件事做完了"，
它**就是一句话**。以前这句话没处可放，AI 只能要么建个步骤（污染你的拆解），要么什么都不说。

方案 3 把这件事说清楚了：**让 AI 写「事实」**。事实层天生是**只追加**的，所以
"和你手动操作冲突"这件事**天然不存在** —— 约定层那句"不改不删"因此**一个字都不用松**，
松的只是"新增"的范围：新增的是**事实**，不是任务。

---

## 二、落地的四条（照设计 §3.2 逐条）

| 设计 | 落地 |
|---|---|
| 新事实 kind `task.progress.reported` | `manager.py`：`subject_id` = 任务 id、`value_text` = 一句话、`extra` 记 `actor`/`reported_on`、`source=ai`、`device_id` 可带。与 `task.attempt.failed` **同族**（同一个文件、同一种"只追加"的写法） |
| 新路由 `POST /api/ai/tasks/{id}/progress` | 挂在**现有 AI 组**里（`_ai_guard`：默认关 + 本机来源），`SURFACE` 表加一行（设置页与 `/api/ai/ping` 自动跟着长出来）。**没有**开改状态/改字段/删除的任何路由 |
| 解读层显示「AI 报告：…（时间）」，**不自动改 `status`** | `TaskOut` 带 `progress_count / progress_note / progress_at / progress_label`（由 `_out` 现算）；**卡片上**一行、**详情里**一块 + 撤销按钮；`progress_label`（「AI 报告」）由**后端给** —— 同 OP-33 视角名的规矩，界面不自己写一份中文 |
| 可撤销 = 追加 `task.progress.retracted` | `retract_progress` 只**追加**一条指回原事实（`extra.fact_id`），**原事实一个字不删** —— 与 `review.undone` 同款。**不做** `revision`/`supersedes` 那套预留机制（MVP 不做修正机制） |

---

## 三、★ 这一卡最关键的一句判断：它跟「勾完成」**正相反**

T-G6 定的边界是"**动的是不是你亲手写的东西**"：AI 只能勾 `created_by='ai'` 的，
碰你建的一律 400。很容易顺手把新路由也加上 `require_own` —— **那就错了**。

报告进展是**新增一条事实**，它**不碰**你的标题/状态/截止日/备注（真机自检专门钉这一条：
报告前后那条任务的 `status`/`version`/`note` **一个字节不差**）。既然没动你的东西，
就没有理由要求"这必须是我建的" —— 而**AI 往你建的任务上报进展，正是这条链的本意**
（你分配/交代给它的事，多半本来就是你建的）。

所以两句话并排写在这里，免得后人再混一次：

- **勾完成** = **改**你的东西 → 只许动它自己建的（400 带原话，不静默）；
- **报告进展** = **新增事实** → 谁建的都行（它压根没动任何东西）。

配套的三条也一并定死（都是**故意不做**，不是忘了）：

1. **不自动标完成** —— 你看到再勾，数字才可信（这个项目一贯口径：`attempt_failed` 也拒绝从别的动作推断）。
2. **AI 没有撤销接口** —— 撤销是"我对界面上的读数负责"的动作，在人这一侧；多一条 AI 撤销的路，
   就多一处会漂的边界（AI 真要改口，**在下一条报告里说清**就够了）。
3. **只撤最近一条**（不是"点哪条撤哪条"）—— 界面上就一颗按钮，连点两下一层层往回撤；
   与 `review.undone` 的用法一致。

---

## 四、验证（四层，按"一条判据只放一处"分的工）

| 层 | 判什么 | 数 |
|---|---|---|
| `tests/test_ai_line.py` | 领域+接口的全部行为：报告不改任务字段 / 空话·多传字段·已删 400·不存在 404 / 完成后仍可真事实 / 撤销是追加且一层层往回撤 / AI 自己读得回来 / 默认关 403（那把 `for` 循环里加了新路由）/ 跨站 403 | +5 条（该文件 28 条） |
| `tests/test_web_frontend.py` | **接线**：卡片与详情都用后端给的 `progress_label`（界面不许自己写「AI 报告」）/ 撤销按钮打到**人侧**那条后缀 `/progress/retract` / 详情里那句「报告 ≠ 状态」/ 事实流的两条 kind 有人话 | +1 条 |
| 真机自检 `tools/web_live_check.py` | 走**真 HTTP**（单元测试读的是同进程对象，看不出序列化与路由真相）：报告进展不改你的任务 / 报告落到卡片字段上 / 空话 400 / 撤销后**原事实还在** | +4 条 |
| DOM 探针 `tools/ui_dom_probe.mjs` | 真渲染：详情只读态出现「AI 报告 + 撤销这一条 + 不是状态」/ 卡片上那句话与时间 / ★ **反证：没有报告的任务不许挂那一行**（出现次数 = 1） | 「AI 接口 4/4」 |

**没加行为流**（`ui_flow_check.mjs`）：按 T-G38 的最小验证法则，这条链的判据在 pytest 里
能一次说清（且更便宜），加一条真浏览器流只会让每轮多 20~40 秒 —— 所以**不加**。

---

## 五、★ 顺带修掉一条**过宽的护栏**（T-G11 的同款教训）

`test_web_frontend.py::test_task_note_is_editable_in_detail_only` 里有一句
`assert "note" not in card`，本意是"**任务自己的备注**不上卡（渐进聚焦）"。
我加的新字段名 `progress_note` 里含 `note` → **一条诚实的字段被这条护栏判红**。

改法不是把新字段改名绕开它，而是**让判据认它真正要管的东西**：`assert "t.note" not in card`
（字段访问），并在断言旁写明为什么不是裸子串。

> **教训**：护栏写得越宽，越容易罚到老实人；而被误伤的人最容易做的事就是"把自己的东西改名躲开"——
> 那一改，**护栏就永远收不到它本该收的那条**。同 T-G11（第一层护栏只扫 `index.html` 字符串
> 字面量、第二层的桩数据里没那些 note → 缝里漏了 19 处字面星号）。

---

## 六、改了哪些文件

| 文件 | 改了什么 |
|---|---|
| `src/timeflow/core/tasks/manager.py` | `PROGRESS_REPORTED`/`PROGRESS_RETRACTED`/`PROGRESS_ACTOR_LABELS`/`ProgressReport` + `report_progress`/`retract_progress`/`progress_reports`/`_retracted_ids`（放在「尝试失败」那一段之后，同一族的写法） |
| `src/timeflow/core/tasks/__init__.py` | re-export 新名字（7 个） |
| `src/timeflow/api/app.py` | `TaskOut` 四个 `progress_*` 字段 + `_out` 现算 + AI 路由 `ai_report_progress` + 人侧 `retract_progress` |
| `src/timeflow/core/ai.py` | `SURFACE` 加一行、`BOUNDARY`/`WHY`/`EXAMPLE`/`describe().note` 同步；模块头"四句话"变"五句话"（新加一条**报告进展**，并写明它与勾完成的区别） |
| `src/web/index.html` | 卡片一行「AI 报告：…（时间）」/ 详情一块 + 撤销 / `factLabel` 两条 kind / `ACTIONS` 注册 `progress-retract` / `retractProgress()` / 打开开关那句 toast 补上"报告进展" |
| `docs/contracts/domains/F7-team.md` | OP-32 的入口/输入/后续/可逆/反馈/边界补上 AI 那一路 + 新增「实现（T-G21）」段（含"它与勾完成不是一回事"） |
| `docs/specification/domains/F7-team.md` | R4 加「落地（T-G21）」+ **删掉那句 ⚠️ 约定层还写着"不改不删"**（T-G39 已改齐，那个警告过期了）+ 测试映射 |
| `docs/commands.toml` | OP-32：加两条路由、加一个界面动作、`ai` 从 `none` → `create`、写明"两条路" |
| `docs/implementation/architecture.md` | 窄接口那一句补上"报告进展（写事实）" |
| `docs/traceability.toml` | 新卡 `T-G21`（done）；`[contract_ops]` 挂 OP-32；`[acknowledged_ops]` **销掉 OP-32**；顺带清两条**过期 gaps**（T-G19 说"T-G21 未开工"、T-G22 说"2 条例外"） |
| `tests/test_ai_line.py` / `tests/test_web_frontend.py` | 见 §四；另修那条过宽的护栏 |
| `tools/web_live_check.py` / `tools/ui_dom_probe.mjs` | 真机 4 条 + 探针（含反证与桩数据） |
| `docs/changelog.md` / `复盘/交接-重构进度.md` | 功能变更一节 / 台账数字（170 条）、§二表格、§四-③、必读清单第 40 项 |

**没动的**：schema **不变**（事实表本来就够用 —— 这是"事实层"这个设计的红利：
新事实类型不需要迁移）、`contrast` / `style` 两道审美门（界面新增的文字与既有令牌同色）。
`gates/render/` 里**只有 `setting` 那份 × 3 档宽度**变了（设置页的动作表多了一行 AI 路由）——
它和 T-G40 的黄金更新在同一次 `--update` 里落地，理由落 `gates/render/LAST_UPDATE.md`。

---

## 七、诚实边界（这一轮**没**解决的）

1. **手机离线只读面不显示 AI 报告** —— 那一页是 T-G16 的缓存行（只列任务/提醒/复习），
   字段跟着缓存走但没画出来。桌面、局域网镜像、逾期/My Day 等用 `taskCard` 的地方都有。
2. **报告没有通知** —— 它只在界面上出现（打开页面/切视图时看得到），不发系统通知。
   要不要"AI 报告了就提醒我"是另一条产品判断，没做。
3. **同一任务的报告全量都在**（`progress_reports` 不分页）—— 个人工具的量级够用；
   真要到几百条再谈。
4. **`_out` 每张卡多两次小查询**（报告 + 撤销集合）。与 `_out` 既有的分组/分配/步骤同一取向
   （一次算好、界面只管画）；真要优化就做成批量接口，等有实测压力再说。
