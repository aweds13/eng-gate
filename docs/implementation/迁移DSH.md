# 迁移 DSH —— 全量功能盘点与迁移路径设计

> 这份文件回答：**OpenMAIC 工作台有哪些功能、每一个能不能搬到 DSH、怎么搬、按什么顺序搬**。
> 它不回答「已经搬好的那部分怎么实现」（那是 `docs/implementation/modules.md` 的 M13 与
> 宿主仓自己的注释）、也不回答「DSH 插件怎么写」（见 `AGENTS.md` §12）。
>
> 本轮**只勘察与设计**：没有改一行代码、没有跑测试、没有提交 git。
> 所有行数与路径都经 `wc -l` / `ls` / `grep` 实测；凡拿不准的都标了「不知道」并写明缺什么。

---

## §1 现状

### 1.1 已经搬完的那部分（别重复做、别推翻）

| 项 | 事实 | 判据 |
|---|---|---|
| 仓库 | `D:/repo/program/OpenMAIC`，分支 `upgrade/v1.3.0`，HEAD `728d6105` | `git rev-parse --short HEAD` |
| 插件源 | `D:/repo/_tools/dsh-plugins/`（独立 git 仓，HEAD `863e36a`） | 该目录下 `git log -1` |
| 部署副本 | `C:/Users/example/.dsh/profiles/desktop/node_modules/dsh-openmaic-*` | 两包 `lib/index.js` 分别 697 / 235 行，与源一致 |
| ★ 部署形态 | pnpm `file:` 是**实体拷贝**，不是 junction —— 改源**必须 cp 过去** | `diff -rq lib <部署目录>` 应为空 |

**12 个工具，全部实测存在**：

`openmaic-course`（`lib/index.js` 697 行，7 次 `register(`）：

| 工具 | 注册行 | 干什么 |
|---|---|---|
| `openmaic_courses` | 563 | 课程列表（`document_stages` ⋈ `document_folders` ⋈ `document_scenes` 聚合） |
| `openmaic_scenes` | 573 | 一门课的页列表（id / order / title / type） |
| `openmaic_page` | 588 | 一页原文；非 slide 页加 `text` 与「B2 只读」note |
| `openmaic_active` | 609 | 面板里当前选中的页（进程内状态，重启即空） |
| `openmaic_page_text` | 624 | 非 slide 页只读文本 |
| `openmaic_search` | 641 | 库内关键词搜（`sc.data::text ilike`，limit 20） |
| `openmaic_patch_stage` | 657 | 单页改：`title` / `canvasJson` / `textsJson` / `opsJson` + `dryRun` |

`openmaic-local-capabilities`（`lib/index.js` 235 行）：`local_services`(93)、`pdf_to_markdown`(112)、
`browse_page`(161)、`course_search`(186)、`embed_texts`(210)。

**seam 前缀 `/dsh-openmaic`**（`openmaic-course/lib/index.js:83`）：`GET /courses`(487)、`GET /scenes`(490)、
`GET /page`(495)、`GET /text`(501)、`GET /active`(509)、`POST /active`(512)，兜底 404(536)。
路由在 `ctx.effect(...)` 里注册(547)，**先挂路由再注册工具**（工具注册炸了不许把路由带走）。

### 1.2 B0 / B1 / B2 分别落到哪一步

- **B0「看」**：课程列表 → 页列表 → 用上游 `@openmaic/renderer` 的 `SlideCanvas({slide})` **原生渲染**一页。
  不是自绘近似版，不是 iframe。判据是 `node smoke-render.mjs` 末行 `SMOKE: PASS ✅`（11 条 check，
  jsdom + react-dom/client 真跑 effect），而且**双向钉住**：改回 `page.data` 会红 3 条。
- **B1「写」**：`openmaic_patch_stage` + 版面差集 + CAS + `dryRun` 默认只算差集。
  CAS 不是「先读后写」—— `document_scenes` 只有 `(stage_id, id, scene_order, data)` **四列没有版本列**，
  并发保护靠 jsonb 值本身 `WHERE data = $base::jsonb`（`lib/db-write.mjs` 72 行，唯一改库入口）。
  真库端到端验过：`stage-0O5fLNmbe4/scene-p1` 指纹 `740876…|4007` → `de49c74…|3980` → 还原回 `740876…|4007` 逐字节相同。
- **B2「非 slide 页只读」**：quiz 页按 `content.questions[]` 逐题拆（题干 / 选项 / 答案 / 解析），
  interactive / pbl 页 `content.html` 剥标签取前 2000 字。★ 不能靠通用 walk —— 会把答案字母与选项混成一串。

### 1.3 这一轮要回答的问题

12 个工具覆盖的是「**看 + 单页局部改 + 非 slide 页读**」。工作台剩下的东西远不止这些：
`lib/server/agent-runtime/` 一个目录就 25038 行、49 个工具；`lib/workbench/` 68 个文件 12412 行全是浏览器端状态；
`lib/server/generation/` 的 run + steps 合计 9752 行；`app/api/` 83 条路由；`components/` 309 个 tsx。

所以下面 §2 先穷举，§3 再逐个判，§4 排批次，§5 列不可迁，§6 说风险。

---

## §2 功能全量盘点表

口径：**一个「功能点」= 用户在界面上能做的一件事**，或**agent 能做的一件事**。同一模块里成组的工具算一个功能点，
拆开的理由写在「它是什么」列里。行数是该模块 `wc -l` 实测值；`见备注` 表示这条功能点横跨多个文件（备注里给数量）。

功能点共 **90** 个：A 已有 **14**、B 加工具 **21**、C 加面板 **11**、D 留原生 **39**、E 该删 **5**。

### 一、看（B0 已落地）

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F01 | 课程列表 | 主页课程库 | `app/page.tsx` | 2411 | 读 document_stages/document_scenes 聚合；插件无参调用 |
| F02 | 按文件夹分组浏览 | 主页课程库 | `lib/db.mjs` | 129 | SQL 已 left join document_folders 并回落出 folder 名，分组折叠是 UI 的事 |
| F03 | 页列表（序/类型/标题） | 页侧栏 | `components/stage/scene-sidebar.tsx` | 601 | select scene_order/id/data->>'title'/data->>'type' |
| F04 | 单页 slide 原生渲染 | 编辑/播放画布 | `components/edit/surfaces/slide/SlideCanvas.tsx` | 见备注 | ★ @openmaic/renderer 的 SlideCanvas({slide})，面板侧 page.content/page.type；冒烟 11 条钉住 |
| F05 | 当前页进对话上下文 | 面板选中 | `openmaic-course/lib/index.js` | 697 | 读插件进程内 active，重启即空；面板选中走 POST /dsh-openmaic/active |
| F06 | 非 slide 页只读文本 | quiz/pbl/interactive | `openmaic-course/lib/index.js` | 697 | sceneText() 逐题拆 question/options/answer/analysis；不能通用 walk |
| F07 | quiz 页交互（答题/交卷/批改） | 场景渲染器 | `components/scene-renderers/quiz-renderer.tsx` | 83 | 渲染器只有 83 行但依赖 quiz-view.tsx 与 runtime_records 写入侧 |
| F08 | PBL 页渲染与操作 | 场景渲染器 | `components/scene-renderers/pbl-renderer.tsx` | 541 | 541 行渲染器 + lib/pbl/v2/ 五个 API 路由（evaluate/instructor/open-task/simulator/task-update） |
| F09 | interactive 页运行 | 场景渲染器 | `components/scene-renderers/interactive-renderer.tsx` | 65 | InteractiveIframeHost 沙箱 + postMessage 协议；DSH 面板里跑等价于跨域沙箱 |
| F10 | 库内全文关键词搜索 | 检索 | `lib/db.mjs` | 129 | sc.data::text ilike，limit 20，%_ 已转义 |
| F11 | 本地课程库 6 万门 BM25 | 课程库检索 | `lib/chat/pi/tools/course-search.ts` | 312 | peek/full 两档在 OpenMAIC 侧；插件只透传 query/topk |
| F12 | 页缩略图导航栏 | 编辑外壳 | `components/edit/SlideNavRail/SlideNavRail.tsx` | 476 | 476 行拖拽排序 + 插入区；缩略图靠 scene-thumbnail-content.tsx |
| F13 | 阅读页滚轮翻页 | 播放层 | `lib/playback/reading-navigation.ts` | 127 | WHEEL_TURN_MIN_DELTA=12 / COOLDOWN=450ms / SCROLL_EDGE_SLACK_PX=1；零依赖 |
| F14 | 播放引擎（讲稿/圆桌 live） | 播放层 | `lib/playback/engine.ts` | 985 | idle→playing→paused→live 状态机，直接消费 actions，无中间编译步 |
| F15 | 课堂模式整页 | 课堂 | `components/classroom/ClassroomSurface.tsx` | 377 | 377 行 + /classroom/[id] 路由（10 行薄壳） |

### 二、改（B1 已落地 + 未迁）

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F16 | 单页局部改 + CAS | 写入 | `openmaic-course/lib/db-write.mjs` | 72 | document_scenes 无版本列 ⇒ CAS 靠 WHERE data = $base::jsonb |
| F17 | 版面差集（改前判据） | 写入 | `openmaic-course/lib/index.js` | 697 | added/removed/moved/resized/textChanged/markupChanged/restyled；默认 dryRun=true |
| F18 | 可视化画布编辑（拖/改/删） | 编辑画布 | `components/edit/surfaces/slide/` | 见备注 | 16 个文件：RendererEditorCanvas/ElementPickLayer/AnchoredBar×3/ColorPicker/ImagePicker/TableInsertPicker… |
| F19 | quiz 表单编辑（题/选项/解析） | quiz 画布 | `components/edit/surfaces/quiz/QuizForm.tsx` | 见备注 | 9 个文件；quiz-edit-session.ts 是编辑会话状态，服务端无对等物 |
| F20 | 元素引用 / 拾取回话 | 元素引用 | `lib/workbench/element-refs.ts` | 482 | 482 行；把画布元素 id 塞进 composer 再发给模型，链路全是客户端状态 |
| F21 | 页面增 / 删 / 排序 | 编辑外壳 | `components/edit/EditShell/EditShell.tsx` | 381 | InsertionZone + CanvasPager；写入侧对应 document_scenes.scene_order |
| F22 | 阶段（课）增删改 / 归文件夹 | 课程编排 | `lib/server/agent-runtime/curriculum-tools.ts` | 621 | 对应 6 个工具：create_stage/create_folder/move_to_folder/rename_stage/list_folder_stages/read_stage_outline |
| F23 | 发布 / 撤回 / 新鲜度 | 阶段元数据 | `app/api/stages/[id]/publish/route.ts` | 见备注 | 还有 unpublish/freshness/status/generation-complete 共 6 条；单机自用场景下用不到 |

### 三、生成（agent-runtime）

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F24 | agent 会话循环 + 租约恢复 | 运行宿主 | `lib/server/agent-runtime/runner.ts` | 2477 | ★ pi-agent-core Session + PostgreSQL 租约/event ordering/cancel/resume；DSH 有自己的 agent loop，换宿主＝重写 |
| F25 | 工具装配 + 系统提示词组装 | 运行宿主 | `lib/server/agent-runtime/runner-contract.ts` | 16 | assembleRunnerTools() 平铺 18 组；courseSystemPrompt() 是前缀缓存整体，改一字节整段重算 |
| F26 | 生成一页（generate_scene） | 生成工具 | `lib/server/agent-runtime/generation-tools.ts` | 1004 | buildCompleteScene() 在 @openmaic/generation 包内，需要整份 brief（course-design.ts 253 行定其必写项） |
| F27 | 生成动作 / 讲稿（generate_actions） | 生成工具 | `lib/server/agent-runtime/generation-tools.ts` | 1004 | generateSceneActions()；与上一页讲稿、学习者画像、语言指令耦合 |
| F28 | 多阶段课程编排 | 课程编排 | `lib/server/agent-runtime/curriculum-tools.ts` | 621 | 「一句话 7 天 python，一个会话跑到底」的另一半；纯 PG CRUD，可脱离 agent loop |
| F29 | 阶段冻结（准入闸） | 写入闸 | `lib/server/agent-runtime/plan-freeze-tools.ts` | 622 | status/add/backfill/freeze/revise 五动作；状态落 data/plan-freeze/，写盘 mkdir→.tmp→rename |
| F30 | 计划依赖校验 | 写入闸 | `lib/quiz/plan-check.ts` | 251 | 超前引用/无归属/预算三条，只输出「补」和「挪」；tsx 实测可跑 |
| F31 | 课程级审计（承接率） | 审计 | `lib/server/agent-runtime/audit-tools.ts` | 190 | auditCourse() 纯函数；NOVEL_P90=60 只对 slide 有效（pbl p50=95 是别的量纲） |
| F32 | 写后诊断（一页） | 审计 | `lib/server/agent-runtime/scene-diagnostics.ts` | 271 | sceneWriteDiagnostics()；THIN_PAGE_CHARS=120 / OVERFLOW_RISK_CHARS=800；tsx 实测可跑 |
| F33 | 覆盖缺口（题干词是否讲过） | 审计 | `lib/quiz/coverage-gap.ts` | 457 | findCourseCoverageGaps()；零外部依赖；按内容块切不比字符 |
| F34 | 版面检查（溢出/重叠/装不下/字号） | 审计 | `lib/quiz/layout-check.ts` | 500 | checkLayout()；CANVAS 1000×562.5、MIN_READABLE_FONT_PX=14；不碰「好不好看」 |
| F35 | 对抗性课程审查 | 审查 | `lib/server/agent-runtime/review-tools.ts` | 555 | ★ 无会话历史/无画像/无工具的隔离调用；输入是学生看得见的文字；按字符预算分批 |
| F36 | 写后带上下文审查（一页+上文） | 审查 | `lib/server/agent-runtime/page-review.ts` | 175 | reviewPageWithContext()；★ 输了绝不能让写入失败（结论进回话、抛错被吞） |
| F37 | 草稿纸（source→claim 落点） | 工作记忆 | `lib/server/agent-runtime/scratch-tools.ts` | 451 | 两层 open/promoted；编号 s001 永不复用；promote 只记指针不写材料库 |
| F38 | 材料库（INDEX + 主题文件） | 材料 | `lib/server/agent-runtime/materials-library.ts` | 388 | read_materials/update_materials 两工具；清单是产出不是输入；INDEX 每次注入、主题文件按需读 |
| F39 | 材料清单（列/读/搜/抽取/等待） | 材料 | `lib/server/agent-runtime/material-tools.ts` | 1207 | 5 个工具：list/read/search/extract/wait_for_materials；抽取是 MinerU 异步任务 |
| F40 | 材料库文件夹（建/改名/移动） | 材料 | `lib/server/agent-runtime/material-library-tools.ts` | 359 | 5 个工具；薄适配层，底层是 lib/persistence/material-library 的共享操作 |
| F41 | 练习脚手架（一页课→可跑文件夹） | 练习 | `lib/server/agent-runtime/practice-tools.ts` | 406 | 落 课程与学习\练习\<stageId>\<NN-标题>\；★ 不覆盖已有、不起进程；agent 只写 checks.json |
| F42 | 练习结果读回 | 练习 | `lib/server/agent-runtime/practice-tools.ts` | 406 | 固定三层深度读 result.json；只读不碰写 |
| F43 | 答题记录折叠成学习状态 | 学习状态 | `lib/quiz/attempt-fold.ts` | 389 | ★ 值导入 @openmaic/dsl ⇒ tsx 直接跑会报 ERR_PACKAGE_PATH_NOT_EXPORTED，须走 Next 或有别的编译路径 |
| F44 | 学习状态渲染器 | 学习状态 | `lib/quiz/learner-state.ts` | 207 | renderLearnerState() 依赖 attempt-fold 的折叠结果；同 F43 的编译路径问题 |
| F45 | 学习者画像注入提示词 | 系统提示词 | `lib/server/agent-runtime/learner-profile.ts` | 69 | 整份 个人数据\学习画像.md 注入每次运行；DSH 的提示词组装是另一套 |
| F46 | 上下文压缩（durable compaction） | 上下文 | `lib/server/agent-runtime/compaction.ts` | 407 | ★ usageAnchorIsStale()：用量锚点比最新 compaction 还旧就不采信；DSH 有自己的压缩（本项目 ACP 那套） |
| F47 | `/compact` 手动挡命令 | 会话命令 | `lib/server/agent-runtime/session-commands.ts` | 71 | COMMAND_PATTERN 锚空白不锚 \b；不剥 token（读侧改写会让 prompt 与 durable 记录不一致） |
| F48 | 外部 MCP 服务器接入 | MCP | `lib/server/agent-runtime/mcp-client.ts` | 266 | ★ DSH 已原生支持 MCP（本会话就有 arxiv/dblp/literature/github/metaso/pool 六个），这一层直接作废 |
| F49 | 向用户提问（ask_user） | 交互 | `lib/server/agent-runtime/ask-user.ts` | 127 | ★ 不是插件工具，是 DSH 宿主自带；OpenMAIC 靠「结束本轮」实现，DSH 原生就有 |
| F50 | 24 个 SKILL 技能包 | 技能 | `skills/agent-runtime/` | 见备注 | ★ 53 个文件、24 个 SKILL 目录（slide-craft/stage-design/feynman-learning…）；DSH skills 是另一套目录与发现机制 |
| F51 | 技能自建 / 读取 / 修改 | 技能 | `lib/server/agent-runtime/skill-edit-tools.ts` | 412 | ★ DSH 自带 create_skill + skill 加载；复刻这层没意义（记 D 也行，选 A 因为能力已在） |
| F52 | 翻自己以前的会话 | 个人历史 | `lib/server/agent-runtime/personal-history-tools.ts` | 600 | 4 个工具：search_classrooms/read_classroom/search_chats/read_chat；★ 值导入 pi Session |
| F53 | 花名册 / 音色表 | 课堂 | `lib/server/agent-runtime/roster-tools.ts` | 414 | set_roster/list_voices；roster 落 stage.generatedAgentConfigs，与 TTS 强绑 |
| F54 | 声音克隆（切片/登记） | 媒体 | `lib/server/agent-runtime/voice-clone-tools.ts` | 479 | clip_audio 从音视频里切单人独白再回存成 session material |
| F55 | 图片生成 | 媒体 | `lib/server/agent-runtime/generate-image.ts` | 390 | 值导入 @openmaic/storage 的 AssetStore |
| F56 | PPTX 导入成一门课 | 导入 | `lib/server/agent-runtime/import-pptx.ts` | 687 | 布局保留路径；687 行 |
| F57 | 页面渲染成 PNG 给 agent 看 | 生成 | `lib/server/agent-runtime/scene-preview.ts` | 253 | ★ buildScenePreviewTools() 没配服务就 return []，工具压根不注册——本部署大概率没配 |
| F58 | 网页搜索 | 抓取 | `lib/server/agent-runtime/web-search.ts` | 见备注 | ★ DSH 自带 web_search；OpenMAIC 这层是自建供应商抽象 |
| F59 | URL 抓取（含 SSRF 信任闸） | 抓取 | `lib/server/agent-runtime/fetch-url.ts` | 314 | lookup + isIP 做本机信任边界；★ 这是安全判据，别在宿主侧重写一份 |
| F60 | 真浏览器抓页 | 抓取 | `lib/server/agent-runtime/browse-url.ts` | 153 | ★ 本机 8730 被 fake-IP 拦（环境如此，不是坏了） |
| F61 | 读文档（整篇） | 抓取 | `lib/chat/pi/tools/read-document.ts` | 326 | 与 course_search 的 peek/full 配套；3091 份可整篇读的文档 |
| F62 | 子 agent 调用 | 编排 | `lib/chat/pi/tools/call-agent.ts` | 1046 | 1046 行；DSH 有自己的 subagent/workflow 机制，语义不等价 |
| F63 | 白板（native-whiteboard） | 白板 | `lib/chat/pi/tools/native-whiteboard.ts` | 1199 | 1199 行 + components/whiteboard/ 3 文件 + /eval/whiteboard 路由；单机自学场景没有协作白板需求 |
| F64 | 课堂动作（讲到哪/打断） | 课堂 | `lib/chat/pi/tools/classroom-actions.ts` | 812 | 812 行；与播放引擎 live 态强绑 |

### 四、生成管线（老路径）与媒体

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F65 | 生成 run 引擎（复刻 1.1.x 预览） | 生成管线 | `lib/server/generation/run/engine.ts` | 7004 | run/ 目录 17 文件 7004 行；每步 checkpoint/next state/events 一个事务、按租约代数围栏 |
| F66 | 生成十步（research→outline→…→narration） | 生成管线 | `lib/server/generation/steps/outline.ts` | 2748 | steps/ 10 文件 2748 行；outline.ts 810、material-analysis.ts 467 |
| F67 | 生成预览页（outline 确认交互） | 生成管线 | `app/generation-preview/page.tsx` | 606 | 606 行；outlineReview: auto/countdown 两种确认节奏都在服务端引擎里 |
| F68 | 无头生成 API（generate-classroom） | 生成管线 | `app/api/generate-classroom/route.ts` | 见备注 | 3 条路由；靠 assertWorkspaceModelsAuthorized + resolveAgentsForOwner 一整条授权链 |
| F69 | 图片 / TTS / 视频 / 语音四个生成 API | 媒体 | `app/api/generate/` | 见备注 | 4 组路由 + verify-{image,model,pdf,video}-provider + provider/probe-models |
| F70 | 视频导出（渲染任务） | 媒体 | `app/api/export-video/render/route.ts` | 见备注 | 4 条路由（capability/render/render-[jobId]/download）；本机没配渲染服务时 capability 应报不可用 |
| F71 | 音频转录 | 媒体 | `app/api/transcription/route.ts` | 见备注 | 单条路由 |
| F72 | 媒体字节代理 | 媒体 | `app/api/proxy-media/route.ts` | 见备注 | 给浏览器绕同源限制用；DSH 桌面版是 Electron <webview>，不适用 |
| F73 | PBL v2（五条 API） | PBL | `lib/pbl/v2/operations/` | 见备注 | evaluate/instructor/open-task/simulator/task-update；agents+prompts+runtime 四层 |
| F74 | 圆桌讨论（多人 agent 对话） | 课堂 | `components/roundtable/index.tsx` | 见备注 | 4 个文件 + presentation-speech-overlay；与播放引擎 live 态强绑 |

### 五、导出

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F75 | 单课导出（pptx / interactive html / maic.zip） | 导出 | `lib/export/use-export-pptx.ts` | 1621 | ★ 三个 builder 都在浏览器端（Blob + saveAs）；服务端要重做 pptxgenjs 那条，interactive/maic.zip 可直接搬 |
| F76 | 批量导出（多课→一个 ZIP） | 导出 | `lib/export/batch-export.ts` | 384 | buildBatchExportZip() 可在 Node 跑（tsx 实测过了）；缺的是三个 builder 的服务端版本 |
| F77 | 批量下载对话框 | 导出 | `components/workbench/workspace/BatchDownloadDialog.tsx` | 454 | ★ 入口在课程标签页工具栏，默认是对话标签（这条曾经踩过） |

### 六、认证 / 诊断 / 设置

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F78 | 访问码（access-code） | 认证 | `components/access-code-guard.tsx` | 见备注 | 单机自用；DSH 自己有认证墙（签名 cookie，见结论库 1.13），两套认证并存只会打架 |
| F79 | owner 身份 / 旧数据迁移绑定 | 身份 | `app/api/identity/claim/route.ts` | 见备注 | OwnerPrincipal + withRequestOwner；★ 插件读库时目前不分 owner（单机单用户可接受，多 owner 就得补） |
| F80 | whoami 一次性诊断 | 诊断 | `app/api/whoami/route.ts` | 82 | 回显 5 个运行期目录 + planGate/selfStudy 等模块加载时求值的开关真实值 |
| F81 | 模型设置 / 供应商探测 | 设置 | `components/settings/` | 见备注 | 28 个文件；模型选择在 DSH 里是 profile 的事，两处并存会互相覆盖 |
| F82 | 语言切换 / 主题切换 / 用量统计 | 设置 | `components/language-switcher.tsx` | 见备注 | DSH 有 locale 扩展点与自己的主题；用量统计是 3000 API 的概念 |
| F83 | 音效 / 音频指示 | 媒体 | `components/audio/` | 见备注 | 1 个文件；随 F14 播放引擎一起走 |

### 七、工作台外壳

| # | 功能 | 模块 | 文件 | 行数 | 它是什么 |
|---|---|---|---|---|---|
| F84 | 三栏工作台外壳 | 工作台 UI | `components/workbench/workspace/WorkspaceShell.tsx` | 1981 | 1981 行；DSH 侧用 main 座位 + sidebar.panellist，参考 gates/diag/panel-plugin |
| F85 | 左栏（课程树 / 材料库入口 / 历史） | 工作台 UI | `components/workbench/workspace/WorkspaceRail.tsx` | 2491 | 2491 行，全仓最大的 UI 组件 |
| F86 | 对话主面板 | 工作台 UI | `components/workbench/WorkbenchChat.tsx` | 1371 | ★ DSH 自己有对话界面；搬过去等于把两套 chat 拼一起，不建议 |
| F87 | 材料库整页 | 工作台 UI | `components/workbench/workspace/MaterialLibraryPage.tsx` | 1964 | 1964 行；材料是 F38/F39/F40 的 UI 面 |
| F88 | 课程标签页 | 工作台 UI | `components/workbench/workspace/WorkspaceCourseTabs.tsx` | 259 | 259 行；批量下载入口就在这 |
| F89 | 请求活动面板（agent 在干什么） | 工作台 UI | `components/workbench/workspace/WorkspaceRequestActivity.tsx` | 812 | 812 行；DSH 侧对应的是会话工具卡片，可参考 |
| F90 | 工作台会话状态存储 | 客户端状态 | `lib/workbench/session-store.ts` | 2347 | ★ lib/workbench/ 共 68 文件 12412 行，全是浏览器端状态；换宿主＝整层作废 |


---

## §3 逐个迁移判断（四列判断）

**「迁到 DSH 的路径」只有五类，没有第六类**：

- **A 已有** —— 12 个工具里已经能做（或 DSH 宿主自带），指出是哪个。
- **B 加工具** —— 在 `openmaic-course` 里加一个 MCP 工具，直接读写 PG / 文件系统（像 `patch_stage` 那样）。
- **C 加面板/客户端** —— 需要 DSH 的 slots/UI（成例：`gates/diag/panel-plugin`）。
- **D 必须留原生 / 不可迁** —— 说明为什么。
- **E 该删** —— 迁过去没意义。

| 功能 | OpenMAIC 里在哪（文件:行） | 依赖什么 | 迁到 DSH 的路径 | 难度 |
|---|---|---|---|---|
| F01 课程列表 | `app/page.tsx` | PG | A 已有 → `openmaic_courses` | 低 |
| F02 按文件夹分组浏览 | `lib/db.mjs` | PG | A 已有 → `openmaic_courses` | 低 |
| F03 页列表（序/类型/标题） | `components/stage/scene-sidebar.tsx` | PG | A 已有 → `openmaic_scenes` | 低 |
| F04 单页 slide 原生渲染 | `components/edit/surfaces/slide/SlideCanvas.tsx` | PG+浏览器端 React | A 已有 → `openmaic_page` | 低 |
| F05 当前页进对话上下文 | `openmaic-course/lib/index.js`:609 | 进程内状态 | A 已有 → `openmaic_active` | 低 |
| F06 非 slide 页只读文本 | `openmaic-course/lib/index.js`:398 | PG | A 已有 → `openmaic_page_text` | 低 |
| F07 quiz 页交互（答题/交卷/批改） | `components/scene-renderers/quiz-renderer.tsx`:1 | 浏览器端 React+PG | C 加面板 | 中 |
| F08 PBL 页渲染与操作 | `components/scene-renderers/pbl-renderer.tsx`:1 | 浏览器端 React+3000 API | D 留原生 | 高 |
| F09 interactive 页运行 | `components/scene-renderers/interactive-renderer.tsx`:1 | 浏览器端 React+sandbox iframe | D 留原生 | 高 |
| F10 库内全文关键词搜索 | `lib/db.mjs` | PG | A 已有 → `openmaic_search` | 低 |
| F11 本地课程库 6 万门 BM25 | `lib/chat/pi/tools/course-search.ts`:291 | 本地 HTTP 8720 | A 已有 → `course_search` | 低 |
| F12 页缩略图导航栏 | `components/edit/SlideNavRail/SlideNavRail.tsx`:1 | 浏览器端 React | C 加面板 | 中 |
| F13 阅读页滚轮翻页 | `lib/playback/reading-navigation.ts`:119 | 无（纯函数） | C 加面板 | 低 |
| F14 播放引擎（讲稿/圆桌 live） | `lib/playback/engine.ts`:1 | 浏览器端 React+Scene.actions[] | D 留原生 | 高 |
| F15 课堂模式整页 | `components/classroom/ClassroomSurface.tsx`:1 | 浏览器端 React+PG | D 留原生 | 高 |
| F16 单页局部改 + CAS | `openmaic-course/lib/db-write.mjs` | PG | A 已有 → `openmaic_patch_stage` | 低 |
| F17 版面差集（改前判据） | `openmaic-course/lib/index.js`:178 | 无 | A 已有 → `openmaic_patch_stage` | 低 |
| F18 可视化画布编辑（拖/改/删） | `components/edit/surfaces/slide/` | 浏览器端 React | C 加面板 | 高 |
| F19 quiz 表单编辑（题/选项/解析） | `components/edit/surfaces/quiz/QuizForm.tsx`:1 | 浏览器端 React | D 留原生 | 高 |
| F20 元素引用 / 拾取回话 | `lib/workbench/element-refs.ts` | 浏览器端 React | D 留原生 | 高 |
| F21 页面增 / 删 / 排序 | `components/edit/EditShell/EditShell.tsx`:1 | 浏览器端 React+PG | C 加面板 | 中 |
| F22 阶段（课）增删改 / 归文件夹 | `lib/server/agent-runtime/curriculum-tools.ts`:196 | PG | B 加工具 → `openmaic_stage_admin` | 中 |
| F23 发布 / 撤回 / 新鲜度 | `app/api/stages/[id]/publish/route.ts` | PG+3000 API | D 留原生 | 中 |
| F24 agent 会话循环 + 租约恢复 | `lib/server/agent-runtime/runner.ts`:1 | agent-runtime+PG | D 留原生 | 极高 |
| F25 工具装配 + 系统提示词组装 | `lib/server/agent-runtime/runner-contract.ts`:1 | agent-runtime | D 留原生 | 极高 |
| F26 生成一页（generate_scene） | `lib/server/agent-runtime/generation-tools.ts`:389 | agent-runtime+模型调用+PG | D 留原生 | 极高 |
| F27 生成动作 / 讲稿（generate_actions） | `lib/server/agent-runtime/generation-tools.ts`:860 | agent-runtime+模型调用 | D 留原生 | 极高 |
| F28 多阶段课程编排 | `lib/server/agent-runtime/curriculum-tools.ts`:196 | PG | B 加工具 → `openmaic_stage_admin` | 中 |
| F29 阶段冻结（准入闸） | `lib/server/agent-runtime/plan-freeze-tools.ts`:225 | 文件系统 | B 加工具 → `openmaic_plan_freeze` | 中 |
| F30 计划依赖校验 | `lib/quiz/plan-check.ts`:102 | 无（纯函数） | B 加工具 → `openmaic_plan_check` | 低 |
| F31 课程级审计（承接率） | `lib/server/agent-runtime/audit-tools.ts`:64 | PG（只读） | B 加工具 → `openmaic_course_audit` | 中 |
| F32 写后诊断（一页） | `lib/server/agent-runtime/scene-diagnostics.ts`:142 | 无（纯函数） | B 加工具 → `openmaic_scene_diagnostics` | 低 |
| F33 覆盖缺口（题干词是否讲过） | `lib/quiz/coverage-gap.ts`:425 | 无（纯函数） | B 加工具 → `openmaic_coverage_gap` | 低 |
| F34 版面检查（溢出/重叠/装不下/字号） | `lib/quiz/layout-check.ts`:275 | 无（纯函数） | B 加工具 → `openmaic_layout_check` | 低 |
| F35 对抗性课程审查 | `lib/server/agent-runtime/review-tools.ts`:325 | 模型调用 | B 加工具 → `openmaic_review_course` | 高 |
| F36 写后带上下文审查（一页+上文） | `lib/server/agent-runtime/page-review.ts`:148 | 模型调用 | B 加工具 → `openmaic_page_review` | 中 |
| F37 草稿纸（source→claim 落点） | `lib/server/agent-runtime/scratch-tools.ts`:211 | 文件系统 | B 加工具 → `openmaic_scratch` | 中 |
| F38 材料库（INDEX + 主题文件） | `lib/server/agent-runtime/materials-library.ts`:239 | 文件系统 | B 加工具 → `openmaic_materials` | 中 |
| F39 材料清单（列/读/搜/抽取/等待） | `lib/server/agent-runtime/material-tools.ts`:615 | PG+文件系统 | B 加工具 → `openmaic_material_ops` | 中 |
| F40 材料库文件夹（建/改名/移动） | `lib/server/agent-runtime/material-library-tools.ts`:142 | PG | B 加工具 → `openmaic_material_folders` | 中 |
| F41 练习脚手架（一页课→可跑文件夹） | `lib/server/agent-runtime/practice-tools.ts`:135 | 文件系统 | B 加工具 → `openmaic_practice_scaffold` | 中 |
| F42 练习结果读回 | `lib/server/agent-runtime/practice-tools.ts`:261 | 文件系统 | B 加工具 → `openmaic_practice_result` | 低 |
| F43 答题记录折叠成学习状态 | `lib/quiz/attempt-fold.ts`:247 | PG（runtime_records 只读） | B 加工具 → `openmaic_quiz_fold` | 高 |
| F44 学习状态渲染器 | `lib/quiz/learner-state.ts`:111 | 无 | D 留原生 | 高 |
| F45 学习者画像注入提示词 | `lib/server/agent-runtime/learner-profile.ts`:1 | 文件系统 | D 留原生 | 高 |
| F46 上下文压缩（durable compaction） | `lib/server/agent-runtime/compaction.ts`:298 | agent-runtime+PG | D 留原生 | 极高 |
| F47 `/compact` 手动挡命令 | `lib/server/agent-runtime/session-commands.ts`:1 | agent-runtime | D 留原生 | 高 |
| F48 外部 MCP 服务器接入 | `lib/server/agent-runtime/mcp-client.ts`:75 | agent-runtime+外部进程 | D 留原生 | 中 |
| F49 向用户提问（ask_user） | `lib/server/agent-runtime/ask-user.ts`:48 | agent-runtime | A 已有 → `ask_user_question` | 低 |
| F50 24 个 SKILL 技能包 | `skills/agent-runtime/` | agent-runtime | D 留原生 | 极高 |
| F51 技能自建 / 读取 / 修改 | `lib/server/agent-runtime/skill-edit-tools.ts`:275 | 文件系统 | A 已有 → `create_skill` | 低 |
| F52 翻自己以前的会话 | `lib/server/agent-runtime/personal-history-tools.ts`:409 | agent-runtime+PG | D 留原生 | 高 |
| F53 花名册 / 音色表 | `lib/server/agent-runtime/roster-tools.ts`:224 | PG | D 留原生 | 中 |
| F54 声音克隆（切片/登记） | `lib/server/agent-runtime/voice-clone-tools.ts`:291 | 文件系统+模型调用 | D 留原生 | 高 |
| F55 图片生成 | `lib/server/agent-runtime/generate-image.ts`:390 | 模型调用+AssetStore | D 留原生 | 高 |
| F56 PPTX 导入成一门课 | `lib/server/agent-runtime/import-pptx.ts`:1 | 文件系统+模型调用 | D 留原生 | 高 |
| F57 页面渲染成 PNG 给 agent 看 | `lib/server/agent-runtime/scene-preview.ts`:140 | 本地 HTTP（RENDER_SERVICE_URL） | D 留原生 | 中 |
| F58 网页搜索 | `lib/server/agent-runtime/web-search.ts`:44 | 模型/搜索供应商 | A 已有 → `web_search` | 低 |
| F59 URL 抓取（含 SSRF 信任闸） | `lib/server/agent-runtime/fetch-url.ts`:190 | agent-runtime+node:dns | D 留原生 | 中 |
| F60 真浏览器抓页 | `lib/server/agent-runtime/browse-url.ts`:153 | 本地 HTTP 8730 | A 已有 → `browse_page` | 低 |
| F61 读文档（整篇） | `lib/chat/pi/tools/read-document.ts`:303 | 本地 HTTP 8720 + 文件系统 | B 加工具 → `openmaic_read_document` | 中 |
| F62 子 agent 调用 | `lib/chat/pi/tools/call-agent.ts`:1 | agent-runtime+模型调用 | D 留原生 | 极高 |
| F63 白板（native-whiteboard） | `lib/chat/pi/tools/native-whiteboard.ts`:1 | 浏览器端 React | E 该删 | — |
| F64 课堂动作（讲到哪/打断） | `lib/chat/pi/tools/classroom-actions.ts`:1 | agent-runtime+浏览器端 | D 留原生 | 高 |
| F65 生成 run 引擎（复刻 1.1.x 预览） | `lib/server/generation/run/engine.ts`:1 | PG+模型调用+3000 API | D 留原生 | 极高 |
| F66 生成十步（research→outline→…→narration） | `lib/server/generation/steps/outline.ts`:1 | PG+模型调用 | D 留原生 | 极高 |
| F67 生成预览页（outline 确认交互） | `app/generation-preview/page.tsx`:1 | Next.js 路由+浏览器端 React | D 留原生 | 高 |
| F68 无头生成 API（generate-classroom） | `app/api/generate-classroom/route.ts` | Next.js 路由+3000 API | D 留原生 | 高 |
| F69 图片 / TTS / 视频 / 语音四个生成 API | `app/api/generate/` | Next.js 路由+模型供应商 | D 留原生 | 高 |
| F70 视频导出（渲染任务） | `app/api/export-video/render/route.ts` | Next.js 路由+本地渲染 | D 留原生 | 高 |
| F71 音频转录 | `app/api/transcription/route.ts` | Next.js 路由+模型供应商 | D 留原生 | 中 |
| F72 媒体字节代理 | `app/api/proxy-media/route.ts` | Next.js 路由 | D 留原生 | 中 |
| F73 PBL v2（五条 API） | `lib/pbl/v2/operations/` | 模型调用+PG | D 留原生 | 极高 |
| F74 圆桌讨论（多人 agent 对话） | `components/roundtable/index.tsx`:1 | 浏览器端 React+模型调用 | D 留原生 | 高 |
| F75 单课导出（pptx / interactive html / maic.zip） | `lib/export/use-export-pptx.ts`:1 | 浏览器端 React+pptxgenjs | B 加工具 → `openmaic_export_course` | 高 |
| F76 批量导出（多课→一个 ZIP） | `lib/export/batch-export.ts`:255 | 无（纯构图）+三个 builder | B 加工具 → `openmaic_export_batch` | 中 |
| F77 批量下载对话框 | `components/workbench/workspace/BatchDownloadDialog.tsx`:1 | 浏览器端 React | C 加面板 | 中 |
| F78 访问码（access-code） | `components/access-code-guard.tsx`:1 | Next.js 路由 | E 该删 | — |
| F79 owner 身份 / 旧数据迁移绑定 | `app/api/identity/claim/route.ts` | PG+Next.js 路由 | D 留原生 | 中 |
| F80 whoami 一次性诊断 | `app/api/whoami/route.ts`:1 | PG+文件系统 | B 加工具 → `openmaic_whoami` | 低 |
| F81 模型设置 / 供应商探测 | `components/settings/` | 浏览器端 React+3000 API | E 该删 | — |
| F82 语言切换 / 主题切换 / 用量统计 | `components/language-switcher.tsx`:1 | 浏览器端 React | E 该删 | — |
| F83 音效 / 音频指示 | `components/audio/` | 浏览器端 React | E 该删 | — |
| F84 三栏工作台外壳 | `components/workbench/workspace/WorkspaceShell.tsx`:1 | 浏览器端 React | C 加面板 | 高 |
| F85 左栏（课程树 / 材料库入口 / 历史） | `components/workbench/workspace/WorkspaceRail.tsx`:1 | 浏览器端 React+PG | C 加面板 | 高 |
| F86 对话主面板 | `components/workbench/WorkbenchChat.tsx`:1 | 浏览器端 React+3000 流 | D 留原生 | 极高 |
| F87 材料库整页 | `components/workbench/workspace/MaterialLibraryPage.tsx`:1 | 浏览器端 React+PG | C 加面板 | 高 |
| F88 课程标签页 | `components/workbench/workspace/WorkspaceCourseTabs.tsx` | 浏览器端 React | C 加面板 | 中 |
| F89 请求活动面板（agent 在干什么） | `components/workbench/workspace/WorkspaceRequestActivity.tsx`:1 | 浏览器端 React+3000 流 | C 加面板 | 高 |
| F90 工作台会话状态存储 | `lib/workbench/session-store.ts` | 浏览器端 React | D 留原生 | 极高 |

### 3.1 关于 agent-runtime 这一坨：老实说

任务简报要求「不要假装很简单」，这里是判断依据与代价。

**它有多大**：`lib/server/agent-runtime/` 共 **25038 行**；`grep -rln "pi-agent-core|streamText|generateText|callModel"`
命中 **38 个文件**；`runner.ts` 单文件 2477 行。49 个工具名里，**只有 7 个**（`course_audit` / `plan_freeze` /
`scratch` / `practice_scaffold` / `practice_result` / `review_course` / `render_scene_preview`）是**自成一体**的，
其余 42 个全是「agent 循环里的一个动作」——它们的执行依赖 `runner.ts` 提供的会话、租约、事件流、
上下文压缩、工具预算、owner 鉴权，脱离那个循环就没有意义。

**为什么循环本身搬不过来**（不是难，是**语义不同**）：

- `runner.ts` 头注释原文：*"Every application process may run this loop. PostgreSQL is the authority for claims,
  lease generations, event ordering, cancellation, and conversation recovery. A client connection is never part of
  the execution lifetime."* —— 它是**自带租约与恢复的独立执行宿主**。
- 系统提示词是 `courseSystemPrompt()` 一次组装出来的**前缀缓存整体**（`runner-contract.ts:14`），
  改一字节整段重算。`plan-freeze-tools.ts:1` 那段注释讲得很清楚：*「`planFreezePromptBlock()` 无参、恒定——
  系统消息是一个前缀缓存整体」*。DSH 的提示词是另一个组装器，**两套无法拼接**。
- `ask_user` 是靠**结束本轮**实现的（`ask-user.ts:1`：*"The runner then terminates the current run"*）；
  `compaction.ts` 的 `usageAnchorIsStale()` 是给 pi 的 durable transcript 设计的。
  这些机制在 DSH 里的对等物是**另一套**（DSH 自带 `ask_user_question`、自带上下文压缩），
  硬搬等于把两套上下文机制叠在一起。

**能在 DSH 里做的是哪些**（这些已经分到 B 类）：

| 类别 | 例子 | 为什么能 |
|---|---|---|
| 纯函数判据 | `plan-check`(251) / `coverage-gap`(457) / `layout-check`(500) / `scene-diagnostics`(271) / `course-audit`(521) | 零模型、零 DB、零网络；`tsx` 从仓根实测可跑 |
| 文件系统工具 | `plan_freeze`(622) / `scratch`(451) / `materials`(388) / `practice_scaffold`(406) | 只读写本机目录，不需要 agent 循环 |
| PG 只读/CRUD | `course_audit` 读全课 / `stage_admin` 建课改名移动 | 与 `patch_stage` 同构，插件已经在这么干了 |
| 需要一次模型调用 | `review_course`(555) / `page_review`(175) | 它们是**隔离调用**（无会话历史/无画像/无工具），DSH 里可以用 DSH 的模型跑同样的提示词 |

**做不了的**：`generate_scene` / `generate_actions` / `runner.ts` / `compaction.ts` / `skills.ts`（1045 行）/
`call-agent.ts`（1046 行）/ `personal-history-tools.ts` / 生成管线 `run`+`steps`（9752 行）。
理由不是「工作量」，是**宿主换了**：这些逻辑绑死在 pi-agent-core 的 `Session` 与 OpenMAIC 自己的
`agent_sessions` 系六张表上；DSH 有自己的 agent loop 与自有会话存储。

**代价**（诚实版本）：如果坚持要在 DSH 里重建「生成课件」这条路，最小可行集是
`runner` 骨架 + 提示词组装 + `generate_scene`/`generate_actions` 两把工具 + `@openmaic/generation` 包的调用面 +
写入闸（`planGate` / `scene-diagnostics` / `overlay` 三闸）+ 24 个 SKILL。
这不是「迁移」，是**在另一个宿主里重写一遍生成器**，而 `@openmaic/generation` 的 `buildCompleteScene()`
本身还依赖 packages 层的 165 文件改动。**建议不做**，理由见 §5。

---

## §4 分批计划

排序原则：**每批都是能独立验收的最小一步**；前一批不改后一批的判据。
「怎么验」一律给可复制的命令或可读的读数，**不接受「看起来对了」**。

### 批次 0 · 收口两条已知未结案（不新增任何功能）

- **做什么**：把 `AGENTS.md` §8 挂着的两条收掉。
  ① 真人在面板里点一页，让 `openmaic_active` 有值；
  ② 重启 DSH 后复验 `markupChanged` 桶与侧栏图标。
- **怎么验**：
  - ① 点完之后在会话里问「当前页是哪一页」，`openmaic_active` 应回 `{ok:true, active:{stageId, sceneId}}`；
    再 `curl http://127.0.0.1:<port>/dsh-openmaic/active` 应回同一个值。★ **不许 curl `/plugins/*`**
    —— 那条路在签名 cookie 认证之后，404 不代表没加载（结论库 1.13）。
  - ② 重启后跑 `node D:/repo/_tools/dsh-plugins/openmaic-course/smoke-render.mjs`，
    末行 `SMOKE: PASS ✅`；再调一次 `openmaic_patch_stage` 只改标签文字，`dryRun` 回包里
    `markupChanged` 计数应 ≥ 1（不是 0）；侧栏那一行应是图标 + 一次「OpenMAIC」，**不是「课件 课件」**。
- **风险**：低。①的唯一风险是「点页」这件事只有人能做，工具替代不了（`browse_page` 对回环地址直接回 `blocked`）。

### 批次 1 · 只读诊断三件套（最低风险的第一批 B 类）

- **做什么**：加三个工具，全部是**纯函数**、只读、不写库、不花模型。
  - `openmaic_plan_check`：参数 `stageId`；返回 `checkPlanDependencies()` 的「补」和「挪」两类建议。
  - `openmaic_layout_check`：参数 `stageId`（可选 `sceneId`）；返回四类读数：溢出 / 重叠 / 文字装不下 / 字号过小。
  - `openmaic_coverage_gap`：参数 `stageId`（可选 `sceneId`）；返回「这题考的词前面讲过吗」的缺口段。
- **怎么验**：
  - 单个函数先在仓根用 `tsx` 跑通（这三个模块实测都能跑），确认在真 `stageId` 上出数不是空数组；
  - 部署后工具数从 12 变 15（`grep -c 'register(' openmaic-course/lib/index.js` = 10，斜杠前 7 + 新 3）；
  - `diff -rq lib <部署目录>` 为空；重启 DSH 后在会话里看工具清单。
- **风险**：低。唯一已知坑是 `layout-check` 与 `coverage-gap` 都**只报可算的**，
  不碰「好不好看」——别在回包里加主观评分，那会把「可复现的判据」变成「编数据」。

### 批次 2 · 写后诊断 + 课程审计

- **做什么**：两个工具。
  - `openmaic_scene_diagnostics`：参数 `stageId` + `sceneId`；返回 `sceneWriteDiagnostics()` 的结论
    （`THIN_PAGE_CHARS=120` / `OVERFLOW_RISK_CHARS=800` 两个阈值）。
  - `openmaic_course_audit`：参数 `stageId`；返回承接率 + `NOVEL_P90=60` 超载页清单。
- **怎么验**：拿一门有 20 页以上的真课跑，`course_audit` 的 `scaffoldPages` 计数应与人工数的 pbl 页数一致；
  `scene_diagnostics` 对一页明显超载的页应报出来、对一页正常的页应不报。
- **风险**：中。★ `course_audit` 的超载线**只对 slide 有效**（`pbl` p50=95、`interactive` p50=11 是别的量纲），
  回包里必须带上页类型，否则模型会把 pbl 页当超载去删内容。这条在 `lib/quiz/course-audit.ts:67` 附近，
  照注释写。

### 批次 3 · 阶段冻结（写入闸，第一步「写」类 B）

- **做什么**：`openmaic_plan_freeze`，五个动作 `status` / `add` / `backfill` / `freeze` / `revise`（`revise` 要写理由）。
  状态落 `data/plan-freeze/`，路径可被 `OPENMAIC_PLAN_FREEZE_DIR` 覆盖。
- **怎么验**：
  - `status` 对一门没冻结的课应回「未冻结」；`freeze` 空计划应被拒（这是**正确行为**不是 bug）；
  - 冻结后再 `freeze` 应回已有版本；`revise` 不写理由应被拒；
  - 落盘读：`data/plan-freeze/` 下应出现该 stage 的文件，且没有残留 `.tmp`（写盘是 `mkdir -p` → 写 `.tmp` → `rename`）。
- **风险**：中。两条：
  ① `planSpecGaps()` 要求作者写的条目必须有 `keyPoints` + `【Unit …】` 抬头、练习条目必须有 `difficulty`——
  闸比想象严，`backfill` 派生的条目不算账。别在这里放宽判据去「让它通过」。
  ② 本部署 `OPENMAIC_PLAN_GATE=1` 是**开着的**；DSH 侧必须复刻同一个开关语义，否则两边行为不一致。

### 批次 4 · 草稿纸 + 材料库

- **做什么**：两个工具。
  - `openmaic_scratch`：编号 `s001` 起、永不复用、两层（`open` 临时 / `promoted` 可复用）。
  - `openmaic_materials`：索引层（材料目录下的 INDEX 文件）+ 主题文件按需读；`update_materials` 只收用户确认过的条目。
- **怎么验**：`scratch` 加一条 → `open` 层出 `s001`；再 `drop` → `s001` **不复用**，下一条是 `s002`；
  `promote` 只记 `promotedTo` 指针，**不写材料库**（边界：材料库规矩是「搜到但没确认的先问」）。
- **风险**：中。两个都是**文件系统**工具，落点不是 `个人数据\` 也不是 `_tools\openmaic\diagnostics\`
  （`OPENMAIC_SCRATCHPAD_DIR` 默认 `<仓库>\data\scratchpad`、`OPENMAIC_MATERIALS_DIR` 默认 `个人数据\材料清单`）。
  在 DSH 里要**先确认目录归属**再动手，别默认往插件目录写。

★ **补记（2026-11-03）**：这一批当时只落了 scratch 与 materials 两件，而盘点表里同批的 `F39 openmaic_material_ops` / `F40 openmaic_material_folders` **从没实现过**（`lib/{index.js,diag.mts,db.mjs}` 逐个 grep 全 0 命中）。同日补齐，两条实测结论写在这里，免得下次又踩：
  - `extract_material` **只排队**：它调 `ensureOwnerMaterialExtraction(..., {fence:'background'})` 把行推到 `extracting` 就返回。真正干活的是 `startOwnerMaterialExtractor()`，只在 Next 进程的 `instrumentation.ts` 里起 —— DSH 宿主没有它，于是六份 PDF 会一直停在 `{"status":"extracting"}` 且 `extraction_claims=0`、`extraction_lease_at` 空，永远没人领。补法是桥自己调上游 `runNextOwnerMaterialExtraction(workerId, {leaseTtlMs, perOwnerLimit})`。
  - `read_material` 的正文是**分页的**：一页 8000 字符，翻页必须带上一页回的 `revision`；不带是 `isError` 的 `revision_required`，`revision` 变了则**不是** error 而是 `revision_changed`（重新从 0 读）。

### 批次 5 · 练习两件

- **做什么**：`openmaic_practice_scaffold`（一页课 → 一个 VS Code 能打开的文件夹）+ `openmaic_practice_result`（读回）。
- **怎么验**：对一个 stage 生成后，文件夹里应有 `check.mjs` / `checks.json` / `README` / `.vscode/`；
  在文件夹里手跑一次 `node check.mjs`，应产出 `result.json`；再用 `practice_result` 读回，结论应与 `result.json` 一致。
- **风险**：中偏高。四条必须照抄的安全判据：① 文件夹名 sanitize ② 每文件路径过 `isSafeRelativePath()`
  ③ 兜底 `resolve(target)` 必须在 `resolve(root)` 之下 ④ **不覆盖已有练习**（已存在且 `overwrite !== true` ⇒ 拒绝）。
  ⑤ **不起进程**——这是设计不是遗漏：跑命令是学习者自己按 Ctrl+Shift+B，这样 web/宿主侧不需要「执行任意命令」的能力。
  在 DSH 里特别要注意第 ⑤ 条：DSH 有 `bash` 工具，**但练习脚手架不该调用它**，否则能力边界就破了。

### 批次 6 · 课程编排 + 诊断 + 读文档 + 答题记录折叠

- **做什么**：四个工具。
  - `openmaic_stage_admin`：`create_stage` / `create_folder` / `move_to_folder` / `rename_stage` /
    `list_folder_stages` / `read_stage_outline` 六个动作合成一把。
  - `openmaic_whoami`：复刻 `/api/whoami` 的读数（5 个运行期目录 + 模块加载时求值的开关真实值）。
  - `openmaic_read_document`：从本地文档层整篇读一份文档（与 `course_search` 的 `peek`/`full` 配套）。
  - `openmaic_quiz_fold`：`attempt-fold`（F43）只读 `runtime_records`，折成学习状态文本。
    ★ 它与本清单的其余 B 类不同：**值导入 `@openmaic/dsl`**，`tsx` 下必报
    `ERR_PACKAGE_PATH_NOT_EXPORTED`（§6.1 第 2 条）⇒ 验收要另找编译路径，不能照抄前三件的 `tsx` 跑法。
- **怎么验**：`stage_admin` 建一门课 → `openmaic_courses` 列表里出现 → 改名 → 再列，名字变了 →
  移到文件夹 → 列表里 `folder` 字段变了。`whoami` 回的目录应等于本机实际目录。
  `quiz_fold` 拿一门有作答记录的课跑，折出来的条目数应等于库里 `runtime_records` 的行数。
- **风险**：中。`stage_admin` 是**第一批真正的 PG 写入**（除了 `patch_stage`），必须走 `lib/db-write.mjs`
  那条唯一写入通道，不许在 `index.js` 里直接 `new Client` 拼 SQL。
  `read_document` 要带 `maxChars` 上限，别把整篇 17443 字的文档一次倒进上下文（那是 N12 的坑）。

### 批次 7 · 审查两件（唯一需要模型调用的 B 类）

- **做什么**：`openmaic_review_course`（整门课，按字符预算分批）+ `openmaic_page_review`（一页 + 上文）。
- **怎么验**：拿一门课跑 `review_course`，回包里的 `fromOrder` 分段应覆盖到最后一页（★ 这条曾经出过错：
  分段的工具把「这一段」当成「整门课」，假阳性是工具自己造的，见 `review-tools.ts:236` 的 `outOfScopeGapClaims()`）；
  `page_review` 必须**输了也不能让写入失败**——先造一次失败（断网/坏模型名），确认 `patch_stage` 照常成功。
- **风险**：**高**。三条：
  ① 输入必须是「学生实际看得见的文字」不是数据库 JSON（interactive 页里 8 页正文只在内联 JS 里）；
  ② `page_review` 抛错必须被吞掉，写入照常（`page-review.ts` 三条纪律）；
  ③ 模型由谁跑：DSH 侧用 DSH 的模型，**不要复用 OpenMAIC 的 model-config 授权链**（那条链是
  `assertWorkspaceModelsAuthorized` + `MODEL_SLOTS`，绑在 3000 那边的配置上）。

### 批次 8 · 导出

- **做什么**：`openmaic_export_batch`（多课 → 一个 ZIP，顶层每课一个文件夹）+ `openmaic_export_course`（单课）。
- **怎么验**：解 ZIP 后顶层应有 N 个课文件夹；每个文件夹里 `<课程>.pptx` / `interactive/NN_标题.html` /
  `<课程>.maic.zip` 三样齐全；`<课程>.maic.zip` 是**唯一**能装下 quiz 与 PBL 页的产物。
- **风险**：**高，且有一块是「不知道」**。`lib/export/batch-export.ts` 的构图部分（`buildBatchExportZip`）
  是纯函数，`tsx` 实测能跑；但三个 builder 的**真实现**在 `lib/export/use-export-pptx.ts`（1621 行），
  它带 `pptxgenjs`、`saveAs`、`toast`，是浏览器端的。
  ★ **不知道**：`pptxgenjs` 在 Node 侧（宿主插件进程）能不能产出与浏览器端逐字节相同的 pptx。
  缺的信息：`buildPptxBlob()` 是否依赖 `Blob`/`URL.createObjectURL`/字体度量；宿主插件进程有没有 DOM。
  落地方案建议：先在 `tsx` 里试 `buildPptxBlob` 的服务端等价路径，跑通了再做 `export_course`；
  `interactive/*.html` 与 `.maic.zip` 两条可以直接搬。

### 批次 9 · 面板（C 类，全部）

- **做什么**：把 §3 里所有 C 类一次性接进 DSH 的 slots：
  左栏课程树（F84/F85）、材料库整页（F87）、课程标签页（F88）、请求活动（F89）、
  批量下载对话框（F77）、页缩略图导航栏（F12）、滚轮翻页（F13）、可视化画布编辑（F18）、
  页面增删排序（F21）、quiz 页交互（F07）。
- **成例**：`D:/repo/engineering/gates/diag/panel-plugin`。可复制的四条：
  ① 座位 = `main` keyed 座 + `sidebar.panellist` 一行，**行 id 必须等于 `main` 的 key**；
  ② 开真实页面走 `ctx.sidebarRight.openTabIn(sessionId, "browser", {params:{url}})`，
  退路才是 `openTab`（本面板占着 `main` 时 `openTab` 必抛 `no session surface is mounted`）；
  ③ 补丁层 `cordis.patch.yml` **必须是顶层 YAML 数组**，三处 id/name 一致；
  ④ 只读缝缺什么说什么，`{ok:false, error}` 绝不用空数据冒充成功。
- **怎么验**：左栏点开 → 课程树出数 → 选中一页 → 画布出这一页的真渲染 → 选中事件让
  `openmaic_active` 立刻有值（F10.5：不滞后一次点击）。
- **风险**：**高，且有一块是「不知道」**。
  ★ **不知道**：画布编辑（拖拽/选框/锚点工具条）能不能塞进 `main` 座。
  `panel-plugin` 只演示了「面板占 main + 开侧栏浏览器页」，没演示过带拖拽的全幅编辑器。
  缺的信息：DSH 的 `main` 座有没有尺寸/滚动/指针事件的约定；`gates/diag/panel-plugin/lib/client.js`
  （1026 行）里没有拖拽实现可参考。**这一步开工前必须先读 DSH 的 slot 声明**，不许猜 API。

### 批次汇总

| 批次 | 新增工具 | 类型 | 难度 | 能独立验收的读数 |
|---|---|---|---|---|
| 0 | — | 收口 | 低 | `openmaic_active` 有值 + `SMOKE: PASS ✅` + `markupChanged ≥ 1` |
| 1 | plan_check / layout_check / coverage_gap | B | 低 | 工具数 12→15；三个纯函数在真课出数 |
| 2 | scene_diagnostics / course_audit | B | 中 | 超载页清单与人工数一致；pbl 页不被误报 |
| 3 | plan_freeze | B | 中 | 空计划被拒；`data/plan-freeze/` 无残留 `.tmp` |
| 4 | scratch / materials | B | 中 | 编号不复用；promote 不写材料库 |
| 5 | practice_scaffold / practice_result | B | 中高 | 文件夹结构齐全；`result.json` 读回一致 |
| 6 | stage_admin / whoami / read_document / quiz_fold | B | 中高 | 建课→改名→移动三步在列表里可见；折叠条目数 == `runtime_records` 行数 |
| 7 | review_course / page_review | B | 高 | 分段覆盖到最后一页；审查失败不影响写入 |
| 8 | export_batch / export_course | B | 高 | ZIP 顶层 N 个文件夹、每课三样产物 |
| 9 | — | C | 高 | 点页 → 画布真渲染 → `openmaic_active` 立刻有值 |

★ **批次 0–9 的落地实况（2026-11-03 核）**：A 类 14 项、B 类 21 项、C 类 11 项**全部已完成**；D 类 39 项留原生、E 类 5 项该删。`openmaic-course` 侧工具 **29 个**、`openmaic-local-capabilities` 侧 **5 个**，合计 **34**。
唯一的未决是批次 0 的第 ① 条 —— 「真人在面板点一页让 `openmaic_active` 有值」这件事只有人能做（`browse_page` 对回环地址直接回 `blocked`）；`POST /dsh-openmaic/active` 已实测可写。

---

## §5 不可迁清单与理由

### 5.1 D 类（必须留原生）—— 按「为什么」分组

| 为什么不迁 | 涉及功能 | 依据 |
|---|---|---|
| **绑在 pi-agent-core 的会话与租约上** | F24 runner、F25 工具装配、F46 压缩、F47 `/compact`、F52 翻历史 | `runner.ts` 头注释 + 38 个文件命中 `pi-agent-core`/`streamText` |
| **绑在 OpenMAIC 的模型调用面与提示词组装上** | F26 / F27 生成、F35 / F36 审查的**提示词部分**、F45 画像注入、F50 24 个 SKILL、F62 子 agent | `courseSystemPrompt()` 是前缀缓存整体；`buildCompleteScene()` 在 packages 层 |
| **绑在浏览器端 React 状态上** | F08 PBL 渲染、F09 interactive、F14 播放引擎、F15 课堂、F19 quiz 表单、F20 元素引用、F74 圆桌、F86 对话面板、F90 会话状态 | `lib/workbench/` 68 文件 12412 行全是客户端状态；`session-store.ts` 单文件 2347 行 |
| **绑在 Next.js 路由与后端配置链上** | F23 发布/撤回、F65 生成 run、F66 十步、F67 生成预览、F68 无头 API、F69 四个生成 API、F70 视频导出、F71 转录、F72 媒体代理、F73 PBL v2、F79 owner 身份 | 83 条 `route.ts`；`run/` 7004 行 + `steps/` 2748 行；`start.ts` 依赖 `assertWorkspaceModelsAuthorized` |
| **是安全判据，不该有第二份实现** | F59 URL 抓取的 SSRF 信任闸 | `fetch-url.ts` 用 `node:dns/promises` 的 `lookup` + `node:net` 的 `isIP` 做本机信任边界；宿主侧再写一份就是两份判据开始漂 |
| **与 TTS / 素材强绑，DSH 侧没有对等物** | F53 花名册 / 音色表、F54 声音克隆、F55 图片生成、F56 PPTX 导入 | `roster-tools.ts` 落 `stage.generatedAgentConfigs`；`clip_audio` 回存 session material |
| **本部署就不具备能力，迁过去也没有** | F57 页面渲染成 PNG | `buildScenePreviewTools()` 没配 `RENDER_SERVICE_URL` 就 `return []`（`scene-preview.ts:140-143`）——工具压根不注册 |

### 5.2 E 类（该删）

| 功能 | 为什么该删 |
|---|---|
| F63 白板（1199 + 3 文件 + 1 路由） | 单机自学场景没有协作白板需求；DSH 侧没有对应物也没必要有 |
| F78 访问码 | DSH 自己有认证墙（签名 cookie，结论库 1.13）。两套认证并存只会打架 |
| F81 模型设置 / 供应商探测（28 个文件） | 模型选择在 DSH 里是 profile 的事；两处并存会互相覆盖 |
| F82 语言/主题切换、用量统计 | DSH 有 locale 扩展点与自己的主题；用量统计是 3000 API 的概念 |
| F83 音效 / 音频指示 | 随 F14 播放引擎一起走，引擎不迁它就没有宿主 |

### 5.3 最难的三个（一句话理由）

1. **F24 `runner.ts`（2477 行）** —— 它不是「生成课件的函数」而是**一个自带租约/恢复/事件流的执行宿主**；
   搬它等于在 DSH 里再养一个 agent 循环，而 DSH 已经有一个。
2. **F65/F66 生成管线（7004 + 2748 行）** —— 每步 checkpoint / next state / events 是**一个事务、按租约代数围栏**，
   这套事务语义与 DSH 的会话模型不对齐；而且它整个建立在 3000 那边的模型授权链上。
3. **F84/F85 工作台外壳（1981 + 2491 行）** —— 全仓最大的两个 UI 组件，而 DSH 的 `main` 座**能不能装下带拖拽的全幅编辑器**
   目前**不知道**（`panel-plugin` 没演示过这种形态）；这条不解决，C 类里最值钱的那部分就只能停在只读。

---

## §6 风险与依赖

### 6.1 会真的咬人的四条

1. **部署副本是实体拷贝**。改源不 cp ⇒ 跑的是旧码。判据 `diff -rq lib <部署目录>` 必须为空。
   历史上踩过一次：进程启动时间 17:22:38 / 部署副本 mtime 18:33:56 —— **旧码仍在跑**（结论库 1.7.1）。
2. **`@openmaic/*` 是 Windows JUNCTION，`tsx` 解不出 `exports`**。
   实测：`@/lib/quiz/attempt-fold`、`@/lib/quiz/learner-state`、`@/lib/export/use-export-pptx` 三者在 `tsx` 下
   报 `ERR_PACKAGE_PATH_NOT_EXPORTED: No "exports" main defined in ...node_modules\@openmaic\dsl\package.json`，
   而 `dist/index.js` 与 `dist/index.d.ts` **都在**。
   ★ 判据是「**值导入** `@openmaic/*` 才会炸」——`batch-export` 也 import `@openmaic/dsl` 却能过，因为它是 type-only。
   **影响**：F43/F44 这两个功能点不能在 DSH 侧靠 `tsx` 现跑，必须走别的编译路径。
   **不知道**：Next 的 bundler 能不能直接吃，因为这需要真跑一次 Next 构建；本轮不跑测试所以没验。
3. **反引号里的 Markdown 文件名会被当真实文件校验**。`scripts/check_layers.py` 的引用判据 的正则只匹配
   反引号内以 dot-m-d 结尾的串（形如：反引号 + 路径 + .md 后缀 + 反引号）；裸文件名还会在 `docs` 下 `rglob`。
   所以写文档时**反引号里只能放真实存在的 Markdown 文件**，举例也不行。判据：`python -X utf8 scripts/check-layers.py`
   末行 `LAYER CHECKS: PASS ✅`，且应打 `[info] 引用完整性：这次实际检查了 N 条引用（断链 0 处）`。
4. **`AGENTS.md` 有 56000 字节硬预算**。实测当前 **55990** 字节 —— 只剩 10 字节，任何增补都会破
   `tests/agent-runtime/docs-map-coverage.test.ts` 的断言。★ 本轮**没有改它**；新增的迁移结论全在这份文件里。
   后续如果要把它接进 `AGENTS.md` 的 §12，必须同时删掉等量的旧内容。

### 6.2 依赖清单（迁移时绕不开的外部件）

| 依赖 | 是什么 | 迁移后的归属 |
|---|---|---|
| PostgreSQL 5433 | 19 张表（`document_*` 6、`agent_session*` 6、`asset_*` 6、`agent_session_materials` 1） | **不变**（单真源，F10.4 禁止影子副本） |
| 8720 | 本地课程 BM25（60072 门课） | 已有 `course_search` |
| 11434 | bge-m3 向量 | 已有 `embed_texts` |
| 8730 | 真浏览器（playwright + msedge） | 已有 `browse_page`（★ 本机被 fake-IP 拦，环境如此） |
| 8010 / 8000 | MinerU 兼容层 / MinerU | 已有 `pdf_to_markdown`（超时 900000ms，分钟级） |
| 3000 | OpenMAIC 应用本身 | **迁移后逐步不需要**；只有 D 类功能还依赖 |
| `@openmaic/renderer` | `SlideCanvas` | **不变**（F10.2 要求原生渲染） |
| `pptxgenjs` | 单课 pptx 导出 | 待定（F75 的「不知道」） |

### 6.3 三条判据口径（写下来免得下个窗口重造）

- **「迁完了」不等于「代码写好了」**：宿主半改完要重启 DSH；浏览器半改完要 `node build.mjs` 再重启；
  `client.js`（13.9 MB）是产物不许手改。
- **「功能对了」不等于「单测过了」**：冒烟要 `smoke-render.mjs`（jsdom + react-dom/client 真跑 effect），
  ★ 别用 `smoke-client.mjs`（`renderToString` 只渲首屏走不到 slide 分支，绿过而 bug 还在）。
- **「写进库了」不等于「能看见」**：B1 那次还原差 1 字节（原文 `<strong>` 只包「使用说明」），
  只比指纹不看原文会把「差一字节」误判成「还原成功」。

### 6.4 这份文件不回答的问题

- DSH 的各 slot 到底有哪些、各自的尺寸与事件约定 —— 需要读 DSH 的 slot 声明，本轮没读全。
- `pptxgenjs` 在宿主插件进程里能不能跑 —— 见 §4 批次 8。
- 画布编辑器能否进 `main` 座 —— 见 §4 批次 9。
- 24 个 SKILL 与新宿主技能体系的对齐方式 —— 本轮的判断是**不迁**（§5.1），但没做代价测算。
