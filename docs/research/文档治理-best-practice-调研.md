# 文档治理 · 最佳实践调研（证据留存）

> 2026-10-24 · 目的：给我们自己的「文档架构」（`docs/文档架构.md`）找外部参照，把**证据**留档，
> 后面谁想看「成熟团队怎么管文档」可以直接读这篇，不用再去搜。
>
> 取数方式：秘塔 AI 搜索 4 次（每次 3 积分）+ 搜索 API 3 轮（共命中约 60 条，去重后采信 20 条）。
> 采信标准：要么给出**可执行做法**，要么给出**做错之后的改动**（后者更值钱）。

---

## 0. 十行摘要

1. 决策记录（ADR）标准做法是**放仓内** `docs/decisions/NNNN-slug.md`：跟代码同版本、进 PR 评审、可 grep —— 放 wiki 会变成没人看的孤儿。
2. 目录组织**按"读者要干什么"分（Diátaxis 四象限），不按"读者是谁"分**；按受众分目录的团队后来改掉了（一个功能散成三处、互相漂移）。
3. **Postmortem（复盘）和 Runbook（手册）是两个物种**：一个解释"当时为什么那样"，一个规定"下次照着做"。手册可以从复盘提炼，但不能互相替代。
4. 大仓的常态是**单一事实源 + 生成**：能从代码/配置生成的，绝不手抄；手抄的必然漂移。
5. 文档要进 CI：链接检查、拼写/格式、**弃用标注**、**变更检测触发更新**（代码变了文档没动就报警）。
6. 文档要有**owner**（CODEOWNERS/目录责任人），否则谁都不改。
7. 给 AI 读者要**渐进披露**：入口薄、按需展开、有稳定索引；把 270 篇塞进一个目录等于没有目录。
8. 迁移要**可回滚**：先出 old→new 全表，`git diff -M` 全是 rename 才算干净。
9. 我们（本仓）在这 8 条上已对上 4 条、半对 2 条、缺 2 条（缺：文档门禁、目录 catalog/owner）。
10. 计划拆三期 + 4 张卡（F1 迁移 / F2 文档门禁 / F3 决策记录 / F4 归档退役），见 §5。

---

## 1. 我问了什么（问题清单）

先想清楚"哪些问题值得问"，否则搜回来的都是"要保持更新"这类正确废话。实际有价值的是这 8 条：

| # | 问题 | 为什么值得问 |
|---|---|---|
| Q1 | 决策记录放哪、怎么命名、多大规模适合建 ADR 目录？ | 我们的决策现在散在台账 522 条 + 一堆 md 里，等于没有 |
| Q2 | 目录按"受众"分还是按"文档模式"分？ | 我最初想按受众分（新手/维护者/agent），可能是错的 |
| Q3 | 复盘和手册能不能合成一类？ | 我正打算把 `复盘/` 里的项目书/手册挑出来，边界在哪 |
| Q4 | 大仓怎么防文档漂移？有没有自动检查的先例？ | 我们有 270+217 篇，靠人记不住 |
| Q5 | 谁负责某篇文档？怎么强制？ | 没 owner 的文档 = 死文档 |
| Q6 | 大规模重排目录怎么不炸？ | 二期要搬 217 篇卡规格 + 改写全部引用 |
| Q7 | 给 AI 读的文档要怎么组织才不被上下文吃死？ | 我自己就是那个读者，最能验证 |
| Q8 | 有没有"文档覆盖率"这类指标？ | 想进 CI 需要可判定的指标 |

---

## 2. 证据表（结论 + 原文摘录 + 出处）

### 2.1 决策记录（Q1）

| 结论 | 摘录 | 出处 |
|---|---|---|
| 放仓内 `docs/adr/` 或 `docs/decisions/`，编号 + slug 命名 | "将ADR存放在仓库中的docs/adr/或docs/decisions/。这是最流行的方法，理由充分：ADR与它们描述的代码一起版本控制…它们不会在没人访问的wiki中成为孤儿" | [架构决策记录完全指南](https://www.archyl.com/zh/blog/architecture-decision-records-complete-guide) |
| 跨领域的放根、局部放子目录 | "At the root of the ADR folder (/design/adr) are decisions that are relevant to multiple parts of the project (aka "cross cutting concerns"). Sub folders … contain decisions relevant to the specific area" | [EdgeX ADR 目录](https://docs.edgexfoundry.org/2.2/design/) |
| 规模不是问题，200+ 条很正常；同一模板 | "根据我们在多个项目中实施 200 多项 ADR 的经验…" | [AWS ADR 最佳实践](https://aws.amazon.com/blogs/architecture/master-architecture-decision-records-adrs-best-practices-for-effective-decision-making/) |
| 四段式就够了 | Context / Decision / Status / Consequences | [ADR 轻量实践](https://www.raphaelbauer.com/posts/architecture-decision-records/) |
| 可以按子系统分子目录，但不必 | "MADR logs may be categorized ADRs by defining subdirectories" | [MADR](https://adr.github.io/madr/) |

**判决**：我们该建 `docs/decisions/NNNN-*.md`，四段式 + `Status: accepted/superseded`；跨域放根、`ci`/`dsmate` 这类局部放子目录（跟 EdgeX 一致）。

### 2.2 目录按什么分（Q2 —— 最有价值的一条）

ADR-908 这个案例几乎是我们问题的镜像：团队最初按受众分目录，一年后**自己推翻了**：

- 原决策：「Organize by Audience, Not Feature」，树是 `docs/{concepts,using,operating,architecture,reference}`。
- 修正案：「organizing the folder tree by audience (`concepts/`, `using/`, `operating/`) made every feature live in several places at once — an operator's TLS page and a user's TLS page drift apart, and a contributor never knows which one to edit. **Audience is a real lens, but it is the wrong axis for the directory structure.**」
- 改成 Diátaxis 四模式（Tutorial / How-to / Reference / Explanation），并强调这是**封闭的 2×2**（action vs cognition × acquisition vs application），"There is no fifth quadrant"。
- 附带一条：他们把 `operations/` 当第五模式用了一次，又自己纠正 ——「operations 是 audience facet，不是 mode」。
- 效果：154 篇手写页压到 47 篇，reference 改为**从代码生成**。

同时期 Diátaxis 被多个标准仓采用：[SCS 标准仓](https://docs.scs.community/standards/scs-0002-v2-standards-docs-org)、[IOTA wiki](https://wiki.iota.org/community/contribute-to-wiki/reference/structure/overview/)、[GitBook 结构建议](https://gitbook.com/docs/guides/best-practices/documentation-structure-tips)、[cometbft 的 Diátaxis 重构 issue](https://github.com/cometbft/cometbft/issues/1613)。

**判决**：我原来写的 L0–L4 是"按模式分"，方向对；但**要把"受众"从目录轴降级成标签**（受众 = who，模式 = what job）。另外 `docs/taste/` 这种"品味"页在四象限里属于 Explanation，不必单开。

### 2.3 复盘 vs 手册（Q3）

| 结论 | 摘录 | 出处 |
|---|---|---|
| 两个物种，别混 | "Runbooks can be adapted directly from postmortems but this doesn't mean that they should replace them." | [BMC: What is an Operations Runbook](https://blogs.bmc.com/operations-runbook/) |
| 手册的必备内容 | 触发条件、服务是什么、谁负责、依赖、基础设施、指标日志、告警 | [Runbook 要点](https://www.cnblogs.com/evan-blog/p/10264037.html) |
| 无责备 + 统一模板 + 现场记录 | "Start the postmortem during incident resolution… Standardize your template… Keep everything in one workspace." | [结构化 postmortem 评审](https://titanapps.io/blog/post-mortem-incident-review/) |
| 手册要演练、要与告警系统连 | "定期进行演练…将运行手册与警报和事件管理集成" | [Runbook 指南](https://www.shadecoder.com/zh/topics/runbook-a-comprehensive-guide-for-2025) |

**判决**：`复盘/` 只放"事后"（postmortem + 交接），项目书/卡规格/手册全部搬走；这是我们 P1 问题的外部依据。

### 2.4 单一事实源与生成（Q4 的一半）

| 结论 | 摘录 | 出处 |
|---|---|---|
| 能从代码生成的别手抄 | "从代码生成文档减少手动工作。OpenAPI/Swagger生成API文档…" | [AI 基础设施文档最佳实践](https://introl.com/zh/blog/documentation-best-practices-ai-infrastructure-knowledge-management-systems) |
| 文档要"活"在代码边上 | "README文件完整全面" / "行内注释解释为什么，而非是什么" | 同上 |
| 大规模收敛有先例 | 154 页压到 47 页 + reference 生成 | [ADR-908](https://aaronsb.github.io/knowledge-graph-system/architecture/access-workflow/ADR-908-documentation-strategy/) |
| 元数据便于检索 | 标题/作者/日期/标签/版本/审查日期/批准状态 | [introl](https://introl.com/zh/blog/documentation-best-practices-ai-infrastructure-knowledge-management-systems) |

**判决**：我们已有 `docs/traceability.d/` 与 `changelog.d/` 这类"片段 → 汇总"的生成机制（`tools/sync_docs.py` 合并），方向正确；**下一步是把"同一事实的两处投影"改成"一处源 + 生成"**（例：队列里的卡状态 vs 台账里的条目状态 vs `交接-重构进度.md` 的分布数字，现在三处各写一遍）。

### 2.5 文档进 CI：漂移检测与校验（Q4 的另一半 + Q8）★ 我们缺的一条

摘录（同一篇，多家实践汇总）：

- 「持续文档验证确保准确性。链接检查防止404错误。拼写检查捕获错别字。格式验证确保标准。截图自动更新。版本同步维护。**添加弃用警告**。GitLab的持续验证防止95%的文档错误。」
- 「**变更检测触发文档更新**。代码变更需要文档更新。配置漂移检测。API变更被跟踪。」
- 「HashiCorp的测试每季度验证100%的文档。」

另见同类「docs as code」流水线清单：[docs-as-code 构建镜像](https://github.com/doughgle/docs-as-code)。

**判决**：这一块我们**完全没有**（`gates/defs/` 里没有文档门）。可加的最小集合：
①死链/失效指针（我们已有 `card_doc_budget.check_pointers` 的雏形，但只覆盖卡文书）；
②`Status: superseded` 的文档必须被索引标注；
③「代码改了、对应文档没改」的 detection（用台账 `file:` 证据 + 域映射反查）；
④覆盖率矩阵（domain × mode，哪格空着）。

### 2.6 归属与评审（Q5）

| 结论 | 摘录 | 出处 |
|---|---|---|
| 有 owner 才有维护 | CODEOWNERS 支持按路径/子段指派（GitLab 高级用法） | [GitLab CODEOWNERS](https://gitlab.cn/docs/jh/user/project/codeowners/advanced/) |
| 评审清单标准化 | 草稿→技术评审→编辑评审→批准；"Review checklist standardized" | [introl](https://introl.com/zh/blog/documentation-best-practices-ai-infrastructure-knowledge-management-systems) |
| 只允许"单一事实源"的 PR 合入 | 需团队约定 | 同上（Stripe/Red Hat 案例） |

**判决**：我们是一个人 + 多窗口的形态，业主 = 用户本人，所以"CODEOWNERS"应翻译成**目录责任人写在 `docs/OWNERS.md` + 门禁读它**（谁改谁的目录，改别人的要 `--take-over` 式的显式动作）。这一条和已有的卡归窗口（A324）是同一套思路，可以复用。

### 2.7 给 AI 读者的组织方式（Q7）

| 结论 | 摘录 | 出处 |
|---|---|---|
| 入口要薄、渐进披露 | "Progressive disclosure - Overview first, details on demand" | [ADR-908 §5](https://aaronsb.github.io/knowledge-graph-system/architecture/access-workflow/ADR-908-documentation-strategy/) |
| 文档要有稳定 ID（维护者视角） | `DD.NNN.P`：域号+序号+模式字母，序号域内唯一、永不复用；"management metadata, not display" | 同上 |
| 别把一切塞进一个 md | "Single comprehensive README … Rejected: Doesn't scale." | 同上 |
| agent 侧上下文是稀缺资源 | `.agents/CONTEXT.md` 这类"上下文文件"需明确边界与加载时机 | [EAF CONTEXT.md](https://github.com/afonsoft/EAF/blob/05945f3c/.agents/CONTEXT.md) |
| 知识"编译"而非堆积 | 把散落笔记编译成可检索结构 | [knowledge-compiler](https://raw.githubusercontent.com/eliharoun/agent-smith/4ef532dcbbbaffd2e754afadd2d4f96e0d1f58f7/guide/16-knowledge-compiler.md) |

**判决**：给 agent 的入口三层：`AGENTS.md`（≤120 行，只路由）→ `docs/INDEX.md`（全仓文档地图 + 一句话定位）→ 具体页。**索引必须机器重算**（不手写），否则必然过期。

---

## 3. 我的架构 vs 最佳实践：逐条对照

| 最佳实践 | 我们的现状 | 状态 |
|---|---|---|
| ADR 进仓、编号、四段式 | 决策散在台账 522 条 + 若干 md，无 `docs/decisions/` | ❌ 缺 |
| 目录按模式分、受众作标签 | `docs/` 五层（intention/spec/contracts/implementation）≈ 模式分法；`复盘/` 混三类 | 🟡 半对 |
| 复盘 ≠ 手册 ≠ 项目书 | `复盘/` 270 篇：157 复盘 + 217 卡规格 + 176 交接 + ≈40 项目书 | ❌ 要拆 |
| 单一事实源 + 生成 | 已有 `changelog.d/`/`traceability.d/` 合并；但"卡状态/条目状态/分布数字"三处手写 | 🟡 半对 |
| 文档进 CI（死链、弃用、漂移） | 只有 `scripts/audit_progress.py` 查台账证据存在性 | ❌ 缺 |
| 文档有 owner | 无 | ❌ 缺 |
| 给 agent 渐进披露 | `AGENTS.md` 薄 ✅，但 `复盘/` 无机器索引 | 🟡 半对 |
| 迁移可回滚 | `复盘/归置地图.md` 有映射习惯，但没有 old→new 全表 + revert | 🟡 半对 |
| 归档/退役 | 已有 `docs/tombstones.toml`（墓碑机制）| ✅ 对上了，可以复用 |

---

## 4. 这次调研改掉了我原来的两个判断

1. **原本想把"受众"当目录轴**（`docs/新手/`、`docs/维护者/`、`docs/agent/`）—— 放弃了。理由：ADR-908 的翻车记录（一个功能散在三处、互相漂移）。受众改成**每篇页头的标签**。
2. **原本想把"项目书"也放进 `docs/` 的一级目录** —— 改成 `docs/subsystems/<名>/`，因为项目书天然是"某个子系统的一套文档"，而 `docs/` 一级目录应该只放**模式**（规范/决策/手册/复盘），不放"某个东西的全部材料"。

顺带确认了两件我们已经做对的事：
- `gates/diag/` 扁平目录本身是**工具契约**（`wb_brief.py` glob `卡<号>-*.md`），别为了好看去改 —— 这与"迁移要可回滚、别动契约"一致。
- 已有的 `docs/tombstones.toml` 就是"弃用标注"的落地形态，最佳实践里管这叫 deprecation warning，我们已经有了。

---

## 5. 计划（三期 + 四张卡）

### 一期（已完成，未提交）
- [x] CI 子系统项目书搬出 `复盘/` → `docs/subsystems/ci/`
- [x] 写 `docs/文档架构.md`（现状图 + P1–P5 + 目标结构 + 迁移表）
- [x] 本篇调研（证据留存）

### 二期：把三类东西拆开（卡 F1，`T-AG449`）
- `复盘/卡/*.md`（217 篇）→ `docs/cards/`；脚本改写全部引用（队列 `spec=`、台账 `file:`/`test:`、`skills/**` 示例、`wb_brief.py` glob）
- 门禁三条一起过：`audit_progress.py --all` / `wb_plan.py check` / `pytest tests/test_card_specs_tracked.py`
- 判据：`git diff -M --stat` ≥95% 判为 rename；`--revert` 能依 `gates/diag/doc-migration.json` 还原

### 三期：项目书归位 + 索引机器化（卡 F4）
- 40 篇项目书按"回头看（→ `复盘/`）/ 往前做（→ `docs/subsystems/<名>/`）"分流
- `docs/INDEX.md` + `复盘/INDEX.md` 由脚本从**文件头 frontmatter**生成（不手写）
- 退役：一份退役时进 `docs/tombstones.toml` 并让 INDEX 标注

### 并行两张新卡（本次调研新增）
- **F2 文档门禁**（`T-AG450`）：`scripts/check_docs.py` —— 死链、失效指针、`Status: superseded` 未标注、卡片不在一处、覆盖率矩阵（domain × mode 空格）。挂在 audit 档。
- **F3 决策记录**（`T-AG451`）：`docs/decisions/` + 模板 + 从今天台账里回溯出 13 条真决策（D12 搜索走官方 / D16 MCP 只留扩展位 / C14 域红线 / 封存口径 / 两根切分 / 按域门禁 / 卡归窗口 …）。

### 顺序与依赖
```
F1（迁移，纯搬家）→ F2（门禁，读新路径）→ F4（索引生成）→ F3（决策回溯，最后做，因为它要给其他文档打 Status）
```

---

## 6. 未决问题（留给下一轮）

1. 目录 ID（`DD.NNN.P`）要不要上？好处是重排不churn，坏处是给 500 篇加 frontmatter 很容易做成形式的。**倾向：只给 `docs/` 下的正式页加，`复盘/` 不加。**
2. 覆盖率矩阵的"域"怎么划？现在有 A（框架）/B/C（数学预设）/D（dsmate）/E（CI）/F（文档治理），域和模式交叉是 6×4=24 格，会不会太重。
3. `复盘/` 里 157 篇真复盘要不要也迁移到 `docs/postmortems/`？按 Diátaxis 它们属于 Explanation，但它们是"历史"，迁移收益低、破坏 INDEX 的风险高。**倾向：留在原处，只重算 INDEX。**
4. 文档门禁挂哪一档（audit 还是 lang）？挂 audit 会被每次改 `tools/**` 触发，可能太吵。

---

## 7. 检索日志（可复现）

| 时间 | 工具 | 查询 | 命中 | 采信 |
|---|---|---|---|---|
| 2026-10-24 | 秘塔（3 积分） | 文档架构/工程仓库 docs 目录分层 ADR 运行手册 postmortem | 19 | 6 |
| 2026-10-24 | 秘塔（3 积分） | postmortem runbook RFC 文档分目录 handbook 结构 | 21 | 4 |
| 2026-10-24 | 秘塔（3 积分） | 单一事实源 文档漂移 检测 链接检查 文档债 归档 | 26 | 2 |
| 2026-10-24 | 搜索 API | docs structure decisions runbooks postmortems best practice | 8 | 3 |
| 2026-10-24 | 搜索 API | docs drift detection link checker vale markdownlint | 8 | 2 |
| 2026-10-24 | 搜索 API | AGENTS.md context budget progressive disclosure | 8 | 2 |
| 2026-10-24 | web_fetch | ADR-908 全文 | 1 | 1（本篇最重要的证据） |
| 2026-10-24 | web_fetch | introl AI 基础设施文档最佳实践 | 1 | 1 |

> 注：秘塔 3 次检索里有 2 次命中大量"政府采购/SPOC 教学"噪声（因为"单一来源""在线"这类词撞车），
> 有效信息集中在第 3 条命中的第 8 项。⇒ **中文检索要避免"单一来源""在线"这类多义词**。

---

## 8. 补充轮（用户要求"再搜一轮、再想想有什么问题值得问"）

这一轮问了 4 个新问题，专门补上一版**没答**的空缺：怎么补记历史决策、文档债怎么量化、
"陈旧检测"到底能做到什么、模型写的文档怎么管。

### Q9 已经有的一堆决策，要不要/怎么回溯补成 ADR？

- 微软 Well-Architected 明确支持补记：「An ADR should be started for brownfield workloads, and **if the data is available, it should be retroactively generated based on known past decisions**.」[原文](https://learn.microsoft.com/et-ee/azure/well-architected/architect-role/architecture-decision-record)
- 而且给了三条我们马上能用的硬约束：
  - 「The ADR serves as an **append-only log**. Don't go back and edit accepted records. If a decision changes, write a new record that supersedes the original and link the two together.」⇒ 我们的 `docs/traceability.toml` 是**可改**的台账，不能直接当 ADR 用；ADR 要另起目录。
  - 单条记录要含「Problem statement with context / Options considered / Decision outcome（含取舍）/ **confidence level** / Status: Proposed、Accepted、Superseded」⇒ **confidence 这一栏我们没有**，而它恰好治我们"拍板时其实没把握"的毛病。
  - 「Avoid making decision records design guides… the decision must be clear and stand alone」⇒ ADR 只记"选了什么、为什么、代价"，设计细节外链。
- 判决：**回溯是可做的（不是仪式感）**，但要按主题分批补，一批 1 条真决策，别想一次补齐 500 条。

### Q10 文档债 / 覆盖率怎么量化，能不能设阈值？

| 做法 | 摘录 | 出处 |
|---|---|---|
| 文档覆盖率门槛 + 变更同步延迟 | `doc_coverage = calculate_coverage()`，`if doc_coverage < 98%: exit 1`；指标含「参数完备率 / 示例覆盖率 / **变更同步延迟**」 | [腾讯云：接口文档完整性与准确性](https://cloud.tencent.com.cn/developer/article/2521146) |
| 签名比对做漂移 | `detect_drift(implementation, spec)`：抽实现签名与规格签名，算 `SequenceMatcher(...).ratio()` | 同上 |
| **baseline ratchet**（只许涨不许跌）+ 增量行覆盖率 | 「按源码口径统计覆盖率、执行 baseline ratchet、报告目标差距，并对**新增/变更**的可执行生产代码行执行 changed-line coverage」；baseline 存 `coverage-baseline.json`，改它必须维护者放行 | [cc-haha contributing](https://github.com/Tonykeng/cc-haha/blob/main/docs/guide/contributing.md) |
| 隔离区必须带 owner / 复看日期 / 退出条件 | 「Quarantine 条目必须有 owner、reviewAfter 和 exitCriteria；reviewAfter 过期后默认 … 会阻断，直到维护者处理」 | 同上 |
| 漂移检测要闭环，否则文档越写越假 | 「CI 门控失败，如果漂移超过阈值 → 团队更新文档以反映现实 → Agent 读取更新后的架构——循环闭合。**没有第 4 步，循环就是开放的**。文档变得越来越虚构」 | [架构漂移检测](https://www.archyl.com/zh/blog/architecture-drift-detection-guide) |

- 判决（对我们可落地的最小集）：
  1. **覆盖率不按行，按"域 × 模式格子"**（我们文档不是代码生成的，行覆盖率无意义）；
  2. **ratchet 思路照抄**：`docs/doc-debt-baseline.toml` 记当前欠账条数，只许降不许升；
  3. 「变更同步延迟」翻译成我们的口径：**台账里 `file:` 证据指向的代码变了、对应文档没变 ⇒ 记一条 drift 债**；
  4. 借 cc-haha 的 quarantine：暂缓的文档债必须带 `owner / reviewAfter / exitCriteria`，过期自动变红（这比"记得改"可靠）。
- **反例警告**：cc-haha 那种"覆盖率 85% 阻断"对我们是错的 —— 我们多数文档是决策与复盘，不是覆盖率能表达的东西。别照抄阈值。

### Q11 「陈旧检测」到底能做到什么、做不到什么（这条最该记住）

[ADDA 0.5.0](https://pypi.org/project/adda/0.5.0/)（anti-drift documentation architecture）把边界写得很明白：

- 判定陈旧用 **git 祖先关系**：「if the code's last commit is a descendant of the doc's last commit, the doc was written first and has not been touched since」。
- **判不出来时必须说"判不出来"**：「when two commits are unordered (divergent branches, a rebase, a shallow clone) the answer is _cannot tell_, reported as **a skip rather than a pass**. **A green check that was structurally blind is worse than no check.**」⇒ 与我们 `domains.required_profiles()` 的 fail-closed 是同一条哲学，可以直接引用为设计依据。
- `--refs` 检查文档里点到的名字/路径是否还存在，**包括 `AGENTS.md` / `README.md` 这类 agent 入口文件**：「every code name a doc cites must still exist somewhere in the source」「the files an agent reads before any code — AGENTS.md, CLAUDE.md…」。
- 边界（原文）：「**ADDA detects the doc nobody touched. It does not detect the doc someone touched carelessly.** The first is the common failure and is worth automating. The second still needs review.」⇒ 别指望门禁抓"改了但改错了"。
- 还有个细节值得抄：`adda doctor` —— 「prove the gate is on: hook where git looks, runnable, map non-empty (exit 1 if not)」⇒ **门禁自己要能被证明是开着的**，否则"什么都没报"和"没在跑"分不清。我们今天的 `gates/last.json` 就吃过这个亏（封存 rev 指向更早的提交，看起来绿，其实早失效了）。

### Q12 模型写的文档要不要隔离？

[A Quarantine for Model-Drafted Docs](https://dev.to/github_7727/a-quarantine-for-model-drafted-docs-free-model-human-merge-29c2) 的做法是：模型起草 → 进隔离区 → 人审合并，作者署名与合并动作分离。

对我们：卡文书（`gates/diag/_text_*.md`）本来就是模型起草 + 人工（我）核对 + 门禁复核，**已经是这个形态**，不需要再造一层。

---

## 9. 计划 v2（把 §5 的分期改成可验收的条目）

约束：用户已明确不做大重构、不搬家式返工；所以下面每条都带"验收命令"与"退出条件"。

### 期 0（已完成，今天）
- [x] CI 子系统立项文档搬到 `docs/subsystems/ci/`
- [x] `docs/文档架构.md`（现状 + P1–P5 + 目标 L0–L4 + 迁移表）
- [x] 本篇调研（两轮证据 + 计划）

### 期 1：索引机器化（1 张卡 · 半天）
- 目标：`docs/INDEX.md` 由脚本从文件头 frontmatter（`title / mode / status / owner / supersedes`）生成，`复盘/INDEX.md` 同样生成。
- 验收：`python -X utf8 scripts/gen_doc_index.py --check` 退 0；手改 INDEX 后 `--check` 必须退 1。
- 退出条件：连续两次改动后 INDEX 无需人工编辑。

### 期 2：文档门禁（1 张卡 · 一天）
- `scripts/check_docs.py` 四类检查，全部**判不出来就报 skip、不报 pass**（照 ADDA）：
  1. **死指针**：所有 md 里出现的仓内相对路径/文件名必须存在（含 `AGENTS.md`、`skills/**`）。
  2. **drift 债**：台账 `file:` 证据指向的源文件，其最近提交晚于文档最近提交 ⇒ 记一条（只报告，先不阻断）。
  3. **superseded 未标注**：正文里出现"已废弃/被取代"却没有 frontmatter `status: superseded` + `supersedes:` 链接。
  4. **格子空缺**：`域 × 模式`（A/B/C/D/E/F × T/H/R/E）空格清单 —— 只做报告，不设阈值。
- 门禁自证：`check_docs.py --doctor` 打印"我在跑、我覆盖了多少文件、有几条判不出来"（照 `adda doctor`）。
- 挂在 **audit 档**（只改 `docs/**`、`复盘/**` 时跑，约 3–5 秒）。
- 阈值：先 `--mode report`（只打印不红），跑一周后改 `--mode block`，且用 `docs/doc-debt-baseline.toml` ratchet。

### 期 3：决策记录（1 张卡 · 半天）
- `docs/decisions/NNNN-slug.md`，模板照微软那条：Problem / Options / Decision（含取舍）/ **Confidence** / Status（Proposed·Accepted·Superseded）+ `supersedes` 链接；**append-only，改决定就写新的一条并互相链接**。
- 回溯清单（从今天的台账里挑，不贪多，先 8 条）：D12 搜索走官方 / D16 MCP 只留扩展位 / C14 域红线 / 封存口径（比提交不比长度）/ 两根切分 / 按域门禁 / 卡归窗口 / 复盘不收项目书。
- 验收：`python -X utf8 scripts/check_docs.py --decisions` 退 0（编号连续、status 合法、supersedes 成对）。

### 期 4：搬迁（1 张卡 · 一天，**可选**、放最后）
- 只搬两类：`复盘/卡/*.md`（217）→ `docs/cards/`；≈40 篇项目书按"回头看 / 往前做"分流。
- 必带：`docs/migration-map.json`（old→new 全表）+ `--revert` 子命令 + `git diff -M --stat` 判 rename。
- 验收：`scripts/audit_progress.py --all` 绿、`wb_plan check` 绿、`pytest tests/test_card_specs_tracked.py` 绿、`git diff -M --stat` rename 率 ≥95%。
- 不做也可以：期 1–3 完成后，`复盘/` 只是"历史"，不再承担导航职责 —— 搬它是**收益递减**的。用户若嫌折腾，可只做期 1–3。
