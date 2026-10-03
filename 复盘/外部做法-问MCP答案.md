# 外部做法（问 MCP 的答案）—— 拿 K3 的问题去问，回来的是**能接进本仓的机制**

> 缘起：用户 2026-10-03 定的三步走 —— ① 12 层 → 便宜工人想问题（148 条，卡 168~172）→ ② Kimi K3 深化（137 条 / A 108 · B 26 · C 3 · 元问题 10，卡 173）→ ③ **问 MCP**。
> ③ 的做法：按**主题成族**拆四路并行去问（判据强度 / CI 门禁完整性 / 静态分析·适应度函数 / 代理授权与凭据），
> 每路都要求：**带真实引用**的已发表做法 + 工业界失败模式 + **落到本仓怎么接（具体到文件或某一道门）**；★ 不许编引用，不确定就明写。
>
> ★ **引用可信度声明（先说清楚）**：下述 arXiv 编号**由检索工具原样返回**，其中**较新的编号（2609.\*/2608.\*/2604.\* 等）我没有逐条打开核对**；
> 已发表、可信度高的几篇我另外标了「核过」。**本文件是"线索 + 落点"，不是"结论"** —— 要动手之前，先打开原文。

---

## 第一族：判据强度（对应元问题 M-02 / M-03 / M-08 / M-09 / M-10）

### ★★ 头条一：「门禁静默通过」是被量化过的**头号杀手**

> 闸门在「**根本没检查任何东西**」的路径上返回 **PASS** —— 把弱陈述「**我什么都没看**」升格成强陈述「**什么都没错**」。
> 补救**不是**心跳看门狗，而是**三值判决**：`ran-pass` / `violate` / `unable-to-determine`，并**显式统计 unverified 的数量**。
> 来源：`arXiv:2609.30307`（九例，含「连续两周全绿」）· `arXiv:2609.39037`（**skip 记为 pass ⇒ 检出率天花板 ~84%**）。

**落到本仓**：`gates/last.json` 现在是**布尔 `ok`** ⇒ 改成**三值 + `unverified` 计数**；`run_gates.py` 里 NOT RUN / skip / 「跳过的引用」都要**计数并显示**；
收口链的放行判据从「`ok=True`」改成「**violate = 0 且 unverified 有账**」。
★ 这一条**正对**我们今晚的三处现场：① 空集绿灯（A-64 / A-85）；② `--no-cov` 被塞进 addopts 时用例「绿」（工人自己报的）；③ 复用/`--affected` 让一部分门不真跑（D-05 / D-18 / D-21）。

### ★★ 头条二：「判据有没有牙」有**现成仪器**

> **refusal-site deletion**：把验证器里的**拒绝语句删掉**，看测试套件是否察觉。
> 实测：某证据包验证器 **112 个拒绝点里 75 个可删而全套测试仍绿（0.330）**；修完 **0.941 → 1.000**。来源：`arXiv:2608.26183`。

**落到本仓**：对 17 道门做「**定向反例夹具**」；再加**常驻金丝雀** —— 一个**故意违规的文件**，任一门对它变绿 = **门死了**。
★ 这正好能把卡 160（台账接进门）与卡 161（门的输入面）合成**一条机器判据**，而不是两条人话。

### 逐条落点

| 问题 | 外部结论 | 落到本仓 |
|---|---|---|
| **Q1 双向审计**（M-02） | ★ **别做语义匹配**：补链那类做法实测 **96% recall / 33% precision**（`arXiv:1804.02433`，核过）。用**集合包含**：每个改动路径必须在台账里，未登记即红 | 收口链加一道门：`git diff --name-status` 的每个路径 ⊆ 卡台账 `allowed_paths` ∪ 豁免；★ **豁免逐条带 expiry**（我们现在 `waive` 是**永久**的 —— 这是缺口） |
| **Q2 判据过期**（M-03） | 最便宜的一族 = **引用解析**：**28.9% 的热仓已有过时引用**（DOCER `arXiv:2212.01479`，核过）· CI 化 `arXiv:2307.04291`；语义级过期用 **document testing**（`arXiv:2406.14836`，核过：把 note 生成测试，跑通即「文档还成立」） | 门禁里跑一遍全仓 `file::symbol` 解析，**note 里被删的符号即红**。★ 正对 **D-28**（`wb_invariants` 只核文件存在、`::符号` 从不核） |
| **Q3 判据的判据**（M-08） | **没有**现成工具做「lint 规则自身的变异测试」；最接近 = 规则**差分测试**（`arXiv:2109.02245`，核过：2728 仓 → 7633 不一致 → **46 个规则 bug**）+ 元变形测试（`arXiv:2408.13855`）。误报控制靠 **baseline 记账只许减不许增** | 卡 159 已做「单向 → 双向」；★ 再补：**规则级差分**（同一条规矩在两处实现必须给同一答案）+ **豁免 baseline 只减不增** |
| **Q4 证据锚定**（M-09） | 行号/整句是**脆弱锚**；最稳 = 多个**语义属性加权定位**（Similo `arXiv:2208.00677`，核过：定位失败 **24% → 12%**；断裂基准 `arXiv:2605.12158`） | 出证主键改 `file::symbol#decl|signature`；★ **内容哈希只写台账做漂移告警，不做硬失败**（否则改一句注释就全打穿）—— 这条与卡 159 的 INV-77 同向，但把「语义锚点」升级成「多属性加权」 |
| **Q5 来源证明**（M-10） | **Sigstore** = 身份 + 透明度；**in-toto** = 操作序列完整性；★ **SLSA 本身不是机制**，只是威胁分类 + 分级（SoK `arXiv:2406.10109`，核过；SBOM 篡改仍可行 `arXiv:2412.05138`，核过）。实测**自称签名极不可靠**：剔除平台代签后 **<6% 开发者自己签过**、约 **1/8 签名无法验证**（`arXiv:2604.14014`，编号新） | `Gates:` / `Task:` trailer **降级为"声称"**；**真证据 = gate 运行日志包的 sha256**；且**诚实标注**：本地构建最多只能算 **SLSA Build L1** |

★ **一句话总纲**（这三族的交集）：**把「不知道」从「通过」里分出来，并给每条判据配一个"必须能红"的反例** —— 其余都是这条的展开。

### 第一族的完整引用清单（**未逐条打开核对**，按题目分组）

| 题 | 可核的 | 新编号（0 引用预印本，★ 未复现） |
|---|---|---|
| Q1 双向审计 | `1804.02433`（补链 96%/33%） | `2504.15427`（链接有效性验证）· `2603.13999`（双向锚进类型系统）· `2511.18187`（47% release note 缺链）· `2509.05585`（NL↔PL 语义鸿沟）· `2607.24604`（证据不绑版本 ⇒ 拿 N 版证 N+1 版） |
| Q2 判据过期 | `2212.01479`（DOCER）· `2307.04291`（CI 化）· `2406.14836`（document testing） | `2403.00251`（CoCC，精度 >90%）· `2010.01625`（Deep JIT）· `2406.17455`（CI 内 trace 一致性）· `2409.10781`（代码/注释不一致 ⇒ 引入缺陷概率 **1.5×**） |
| Q3 判据的判据 | `2109.02245`（规则差分，**46 个规则级 bug**）· `2408.13855`（元变形测试）· `1901.02819`（Bug-Injector）· `2005.11613`（SolidiFI：单工具漏检 **129~4137** 个注入缺陷） | `2608.26183`（refusal-site deletion）· `2601.18844` / `2310.18532`（学习式过滤降 FP 94%+）· `2202.11861`（无监督分流会把**组织性失败固化**） |
| Q4 锚定 | `2208.00677`（Similo 24%→12%） | `2605.12158`（ReproBreak 449 处断裂）· `2606.26979`（结构化锚优于自由文本）· `2310.07856`（文本相似度是坏代理）· `2307.16023`（oracle 类型误判）· `2401.15788`（文本型匹配在 **230,439 条**失败日志上高度不一致） |
| Q5 来源证明 | `2406.10109`（SLSA SoK：**SLSA 不是机制**）· `2412.05138`（SBOM 已签名 + in-toto/cosign 配好了，**内部人仍可篡改**，且四款主流消费工具**无一做完整性校验**） | `2604.14014`（自称签名 **<6%**、约 **1/8** 验证失败、**>25%** 持死密钥）· `2607.06194`（claimed vs attested identity 属**不同信任层**）· `2605.08363`（Kettle：**TEE 内生成并绑定摘要**是唯一结构性解）· `2409.05014`（1523 个 SLSA issue：卡在实现复杂与沟通） |

★ **两条"反向"结论也很有用**（它们告诉我们**别往哪走**）：
1. **别做语义匹配补链** —— 96% recall / **33% precision**（告警疲劳不可用）；
2. **内容哈希锚定没有任何论文正面处理**，而且**硬失败会把「只改注释」也判红** ⇒ 哈希只做漂移告警。

---

## 第二族：CI 门禁完整性（对应 A-44/45/46/48/49/64/65/85/96）

### ★★ 头条三：《Silent Success》—— 「空集绿灯」被写成了论文（子代理**亲验存在**）

> 生产发布门在「**一个子门的两条检查有一条没跑**」时**仍报 PASS**：根因是判据问的是「**观察到违规了吗**」，而**分母已经把"没跑的那条"剔掉了** —— 于是「缺数据」被回答成「没有」，**连绿两周**。
> 修法：状态机从二值改成 **pass / violate / unable-to-determine** 三值，并**把缺口写进退出码**。
> `arXiv:2609.30307`（★ 子代理打开过 abs 页：27 页短文、零引用）
> 姊妹做法 = **注入式验证**：Bug-Injector `arXiv:1901.02819` · μSE `arXiv:1806.09761` · **StaAgent 用 LLM 变异在五大分析器里找出 64 个坏规则实现** `arXiv:2507.15892`。
> 配套反证：**告警密度与实际缺陷几乎无关** `arXiv:2111.09188`。

**落到本仓**：给**每道门**配一条 `gates/nails/<门名>.案例`（合成坏样例）；门禁开始时先拿它跑一遍，**样例没被咬红 ⇒ 这道门自己判红**（记 `unable to determine`，**不是 PASS**）。
★ `check_layers_selftest` **已经是这个形状**（2 正 + 5 负）⇒ 把它推广到 `contrast` / `style` / `ui_text` / `audit_titles`。

### 其余七问

| 问题 | 外部结论（含点名） | 落到本仓 |
|---|---|---|
| **陈旧产物冒充当前**（A-46） | OmniBOR 把「产物→源码」做内容寻址依赖图 `arXiv:2402.08980` · BuildFs 划定「声明输入 vs 真实碰到的文件」`arXiv:2005.06881`（亲验）· Kettle/TEE `arXiv:2605.08363` · SLSA v1.0 L3 Unforgeable。★ 唯一有量级的陈旧率：**Travis CI 缓存研究 33% 构建含陈旧产物** `arXiv:2601.19146`。★★ **明确缺口：没有论文研究「把测试报告绑到 rev」**（机制全针对二进制构建物） | `last.json` 有 `rev` + 封存指纹，但**没人独立复算** ⇒ `run_gates.py` 读它之前加一道自检：`tree == tree_without_gates(ROOT,"HEAD",include_worktree=True)` **且** `rev == git rev-parse --short HEAD`，不等 ⇒ **判红并打「产物陈旧」** |
| **skip / NOT RUN 与 pass**（A-49） | pytest 退出码 **5 = 一条都没收集到**（与 0 分开）· Playwright 默认「没找到测试」就失败、`--forbid-only` 拒 `test.only`、`--fail-on-flaky-tests` 把重试过的绿判红 · JUnit XML 用 `<skipped>` vs 根本没有 `<testcase>` 表达两种非执行 | 我们已有「node 缺失记 `not_run`」✓；★ 缺的是 **deselect 基线**：门上吞下 `2051 passed, 2 deselected` 却**无人比** ⇒ 在 `gates_ok()` 旁加：本轮 `passed` 与 `deselected` 须与上次相符或**增加**，**减少就红** |
| **覆盖闸被开关绕过**（A-44） | coverage.py 把 `fail_under` 写在**配置文件**（不是命令行）；pytest-cov 的 `--no-cov` 是命令行开关。工业惯例 = **把闸写进版本控制配置、不留命令行开关** | ★ 我们 `run_gates.py` 的 `acceptance` 那行**就带着 `--no-cov`** ⇒ 改成**必须来自 `gates/waivers.toml`**（含卡号 + 到期日）；core pytest 的 `--cov-fail-under=70` **不许被环境变量覆盖** |
| **复用 / 输入清单完整性**（A-45/41） | BuildFs 实测 **122 个 Gradle + 15,740 个 Make 缺失输入** `arXiv:2005.06881` · LaForge 干脆不让人声明依赖、改 trace 系统调用 `arXiv:2108.12469` · ECHECKER 用 commit diff 预测依赖变化 **85× 提速** `arXiv:2404.13295` · Bazel 沙箱「只挂已知输入」让越界读取现形 | `DOOR_INPUTS` 是**手写清单**（正是 BuildFs 说的声明面）⇒ 加**毒药测试**：在某道门输入 glob **之外**改一个该门**真读到**的文件，断言 `input_hash` **必须变**；**不变即红**。并让 `skip_reused` 连 `verdict` 当时的 `tree` 一起记 |
| **有牙不咬 / 孤立规矩**（A-65） | ★ **这半没有文献**（DeepXiv 明确报 gap）；工业替代 = 把规矩做成**可测对象**（Semgrep 规则要配 test fixture、dependency-cruiser 规则是可执行模块、OPA 策略要 test） | 写 `gates/rule_wiring.toml`：「规矩 → 哪道门 → 钉子文件」，由 `audit_progress.py` 做**双向核对**（每条规矩至少被一道门引用 / 每道门至少背一条规矩）—— `check_commands.py` 那套双向核对就是现成范式，照抄 |
| **flaky 失败分类**（A-47） | FlakyCat 少样本分类（Java 343 例加权 F1 70%，**concurrency 最难**）`arXiv:2208.14799` · FlaKat `arXiv:2403.01003` · FlakyFix `arXiv:2307.00012` · ★★ **关键反例**：Chromium CI 上测试级 flakiness 预测**精确率 99.2% 却漏掉 76.2% 的真回归**，改用**失败特征**后 MCC 0.20→0.42 `arXiv:2302.10594`（亲验）· **只用测试源码（连 LLM）分类接近随机** `arXiv:2602.05465` · Python 分布：顺序依赖 **59%** / 工具基础设施 28% / 网络随机 13%，且需 **~170 次重跑**才有 95% 置信 `arXiv:2101.09077` | 我们 `run_gates.py --serial` 已是好对照装置 ⇒ 任一门失败时**自动同命令重跑 N 次**，把结果记成三值（稳定红 / 间歇 / 工具脆），**留原始失败日志**，★ **别用测试名当特征** |
| **门禁锁的自觉性**（A-53） | ★ **Kleppmann《How to do distributed locking》**（子代理亲取正文）：锁必须区分「为效率」与「为正确性」；**每一次写都要带单调递增的 fencing token，并由被保护资源自己校验、拒绝回退的 token**；Redlock 不可用于正确性正因为**它不产生 fencing token**。原始租约定义 = Gray & Cheriton, SOSP 1989；etcd 用 lease + revision 当 fencing token | `gate_lock.py` 是事实锁 ⇒ 补两处：(a) 写 `gates/last.json` **前**校验租约未过期且 token 单调（**把锁的 revision 写进产物**）；(b) 写完后**原子重读并比对 token，回退即判红**。续租要有 keepalive；★ **租约过期判定用 `time.monotonic()`，不许用 `datetime.now()`**（Kleppmann 点名的 Redis 坑在 Windows 上同样存在） |

★ **诚实标注（子代理自己写的）**：① DeepXiv 语料里**没有**「报告↔rev 绑定」的论文，**别把这问题说成有文献支撑**；② `2609.30307` 是 27 页短文、零引用，但它**亲验过 abs 页**；③ 未逐一打开每个返回的 id，引用前先复核；④ 第 6 问「没有工具能机器发现规矩与 CI 接线缺口」是**语料内**结论，不等于世上没有。

---

## 第三族：静态分析 / 架构适应度函数（对应 A-16/20/22/26/30/35/37/38）

| 问题 | 成熟工具 / 已发表做法 | 失败模式（别踩） | **落到本仓** |
|---|---|---|---|
| **写语句只许出现在指定层**（A-16） | `import-linter`（forbidden/layers 契约）· `Tach` · `ArchUnitPython` · `pytest-archon` · JS 侧 `dependency-cruiser`。架构符合性检查（ACC）在中小企业可 <1 人时落地 `arXiv:1611.07549`；规则可自动修复 `arXiv:1506.07589`；分层违约的可度量指标（back call / skip call / 环）`arXiv:2106.03079` | ★ 六个静态工具**精度 18%~86%**、行级几乎不一致 `arXiv:2101.08832`；466 条规则里**只有 19% 是设计类、26% 歧义** `arXiv:1705.11087`。★ 本类独有的坑：`INSERT/UPDATE/.commit()` 在**迁移脚本 / 测试夹具 / 备份恢复**里是**合法**的 ⇒ 必须**白名单化**，不许用豁免注释糊 | `scripts/check_layers.py` 加一节 **AST 扫描**（只扫 `src/timeflow/core/**` 与数据访问模块），产出**两个数**：「白名单外命中数」+「本次实际扫描文件数」；★ **先只报数、不判红** |
| **import 方向 + 删规则必须红**（A-30/37） | 单向禁依赖：上面四个工具都能做；★ **双向没有现成工具**，最接近的是「把追溯做成代码结构属性、靠类型系统与构建期验证强制」`arXiv:2603.13999` | ★★ **import-linter / Tach 没有「规则里声明的层/包必须真实存在且被覆盖」这一半** ⇒ **删掉规则或删掉依赖，门照样绿**；而且只认同文件里的 `import`，**动态 `importlib.import_module("…")` 一律漏** | 在架构清单（`harness.toml` 或新 `docs/architecture.toml`）登记「层 → 允许依赖」；`check_layers.py` 加三项：① 规则路径存在 ② **每个层至少被一条 import 规则覆盖**（层声明 vs 实际目录 diff 为空）③ **本次实际下过的 import 判定条数 > 0** |
| **lost update / 读-改-写缺版本守卫**（A-20） | 静态可行：ANODE 把弱一致下的可串行化归约成 SMT，在 TPC-C 上**静态发现 lost update** `arXiv:1806.08416`；源码级原子性违例 Clover **P 91.0% / R 96.4%**、11 个真实航天项目发现 12 处 `arXiv:2504.00521`；契约式静态验证 `arXiv:1505.02951`；版本守卫规范形态（`WHERE version=?` + 版本自增）`arXiv:2308.09030` | 单进程/全局锁下的读-改-写**本来安全**；`UPDATE … SET x=x+1` 是**原子写、无需守卫**；跨函数或被 ORM flush 顺序一挡就漏；内核级静态竞态**确认率仅 ~2%**（1214 报 → 24 确认）`arXiv:2404.00350`。★ **Python/ORM「缺版本守卫」没有现成检测器**（语料为空） | 把它**模式化**进 `tools/seam_check.py`：`UPDATE` 无 `WHERE version` ⇒ 报；★ **默认非阻断**，等有了反例钉子再升成硬门（避免又一个 18% 精度的告警机） |
| **TOCTOU / 两次现读之间世界可变**（A-39） | 没有专门讲文件系统 TOCTOU 静态检测的论文；用通用竞态工具箱：RacerF 只报 must-race（**674 真阳 / 4 假阳**）`arXiv:2502.20052`；SMT 判路径可行性以剪掉不可达竞态 `arXiv:2503.13864`；二十年竞态检测器综述 `arXiv:2312.14479` | 缺别名/可行性分析会把**不可能路径**报成洞；「检查=读、使用=二次读」的语义等价判定**本身不可判**，工具普遍保守近似 | ★ 静态只作**提示**；**有牙的判据放「恶意探针」** —— 在两次读之间**改库/改盘**，第一次读过期**必须红**（把「世界可变」变成**可执行反例**） |
| **事务边界**（A-26） | MeCheck/RSL：DSL 写框架元数据一致性规则、跨文件静态检查，115 个应用上 **P 100% / R 96%**（注入缺陷）`arXiv:2502.14463`；契约式原子性验证 `arXiv:1505.02951`；cLOTHO `arXiv:1908.05655`；Java DB 访问缺陷实证（SQL 54% / API 38.7%）`arXiv:2405.15008` | 框架**隐式事务**（请求级 session）、只读路径混入、嵌套调用重复计数；调用图对**动态派发/跨进程**（HTTP、MCP）无解 ⇒ 跨进程边必须**显式排除或显式连接** | 新建 `scripts/check_tx_boundary.py`：只对「处理函数**直调 ≥2 个不同写函数**」报；★ 写函数真源用 `docs/commands.toml` 的 `kind=write`，**别造第二份清单** |
| **死代码 / 无人调用 / 未用配置键**（A-22/35） | `vulture`（AST + 可达性、按置信度报，**Python 死代码检测的默认基线**）· Scalpel（CFG/SSA/常量传播）`arXiv:2202.11840` · Python 不做完全健全性分析、走库级抽象是常态 `arXiv:2301.05108` · DCE-LLM >94% F1 `arXiv:2506.11076` · 未用依赖 PyTrim（源码 + requirements + TOML）`arXiv:2510.00674` | CLI 入口 / 路由装饰器 / pytest fixture / `getattr` / 动态注册 **全是假阳**；★ **未使用配置键没有成熟专文** | 把 `harness.toml` / `config.example.toml` 与代码做**双向 diff**（`cfg.get("…")` 当读取面真源），**未用键只报数**；vulture 接 `run_gates.py --fast` 并带 `whitelist.py` |
| **双向登记对账**（A-25） | ★ **没有**面向代码库的现成 bidirectional registry reconciliation；最接近：LLM 双向追溯只能链接不能维持 `arXiv:2309.14992` · 结构属性靠构建期强制 `arXiv:2603.13999` · LSI+FCA `arXiv:2307.05188` · LLM+RAG 98.87%/85.50% `arXiv:2504.15427`；工业界**因缺工具而无法验证追溯收益** `arXiv:2206.04462` | 事后恢复的方法都对**需求质量**敏感：28 类质量缺陷会系统性影响 5 种自动恢复方法 `arXiv:2606.11834` | `scripts/check_commands.py` 已有两向，**缺的是中间态**：把 `unregistered` 从「只报数」改成 `--check` 下**退 1**（或加 `severity` 配置）；并让 `wb_invariants.py --check` 的指针存在性**覆盖 OP/路由条目**（登记烂掉即红） |
| **断言有没有牙 / mutation**（A-38/100） | Google 分析近 **1500 万突变体**：**70% 高优先级 bug 与突变体耦合**，开发者接触后真的会补测试 `arXiv:2103.07189`；半导体 11000+ 单测：**37min→13min、分数 73%→85%、存活 2176→291、14% 方法是 pseudo-tested** `arXiv:2103.08480`；每行一个 mutant 足够；长期存活突变体 `arXiv:2212.11762`；等价突变体 <10%，但**人工判断近 2/3 会判错** `arXiv:2404.09241` | 全量跑**在 3 分钟门禁里不可能**；「存活 = 测试弱」不总成立；套件会随时间退化（52% 突变体失去相关性）`arXiv:2212.11762` | ★ **别把 cosmic-ray/mutmut 塞进全量门禁**；按 Google 口径做**增量** —— 只对**本次 diff 覆盖行**生成每行一个 mutant，挂**手工/夜间**任务，结果进 `复盘/不变量台账.toml` 当 `nail` 的**反面证据** |



---

## 第四族：代理授权与凭据（对应 A-01/03/04/90/101/103/107）

### ★★ 头条四：**模型不能是授权边界**

> **CapScope**：把「自然语言授权」在**受信预检期**编译成 **capability 集合**并**冻结**（`Cap[e,φ]`，e = 效果类型、φ = 参数谓词；**委派只能单调收窄** —— `src/**` 可窄化为 `src/parser.py`，反之不行）；**模型只看得到效果、不持有 capability**。`arXiv:2609.08371`（★DBLP 未命中，未二次核实）
> **MetaPermit**：NL → **固定五元类型词汇表** → 固定 ABAC 引擎裁决；`intent_is_action` / `intent_clarity` **只读受信用户请求**，检索内容无法影响。`arXiv:2609.31039` · 形式化底子（task/action/source/data 四性质 + oracle 每步校验，映射 **87 个已知攻击**）`arXiv:2603.19469`
>
> ★★ **失败模式点的是真实产品**：审计发现 **LangChain / LangGraph、LlamaIndex、Stripe Agent Toolkit 默认都只有 capability gating，没有 per-call、fail-closed、看参数值的授权闸** ⇒ **同一笔未授权付款在默认 dispatch 下直接执行** `arXiv:2606.28679`（未复核）。注入放大：malfunction amplification 失败率 **>80%** 且**多代理传播** `arXiv:2407.20859`（DBLP 核验）

**落到本仓**：dispatch 前放一个**确定性、看参数值、默认拒绝**的 PEP —— `capabilities.yaml`（效果 + scope 谓词）+ `preflight.py` 把用户那句授权**编译成集合**、写 `gates/policy.<session>.json` 后**冻结**。

| 问题 | 关键结论 | 落到本仓 |
|---|---|---|
| **无人值守：可做 vs 必须等人**（A-04） | 判据**不是任务类型**，是**可逆性 + 外部可见性**：Autonomous Capability Levels ≠ Allowed Autonomy Levels `arXiv:2607.23438`；五级角色（operator/collaborator/consultant/approver/observer）+ autonomy certificate `arXiv:2506.12469`（DBLP 核验）。★ 两个**反向**坑：① **审批门可被可变状态替换**（Loopjacking：审批 A、执行 B）`arXiv:2609.21081`；② **监督有容量上限** —— 无差别升级每个动作会造**倒 U 安全曲线**，反而更不安全 `arXiv:2606.08919`（DBLP 核验） | `gates/autonomy.md` 定**三档**：**自动** = 仅写 worktree / 读；**需预告** = 推分支、装依赖；**禁止无人值守** = push main、发凭据、删数据、改 `.git/config`、**改策略文件**。无人值守只走前两档，第三档 **fail-closed 排队等人在线** |
| **强制人专属文件（本地无 CI）**（A-03） | GitHub 官方：CODEOWNERS **只产生 review 请求**，真强制靠服务端 ruleset；★ 官方警告**必须同时给 CODEOWNERS 自己指定 owner**。且官方明说 hooks「**不显式打开就不跑**」、hook 属**仓库内容可被改** ⇒ **本地脚本/钩子不是边界**。⇒ 本地唯一不靠自觉的 = **OS 身份分离 + ACL/SACL** | 受保护路径（`policy/`、`.github/`、`.git/hooks`）**删掉工人身份的写 ACE**、只保留你；工人对它们**只读**（只读挂载 / ACL）；开 **SACL 审计写事件** |
| **策略下沉：直连 CLI 也绕不过**（A-90） | Claude Code 的 managed settings：优先级**高于一切**（`--settings`、flag、用户/项目文件都盖不过）+ `allowManagedPermissionRulesOnly` / `sandbox.network.allowManagedDomainsOnly` / `allowManagedHooksOnly` / `disableSideloadFlags`。★ 官方原文：**沙箱会话若可写这些路径，就能持久化 hooks/权限规则/MCP，下次启动时它们在沙箱外运行** ⇒ runtime **默认拒绝**写 `.git/hooks`、`.git/config`、`.mcp.json`、shell 启动文件。内核材料：seccomp-BPF 官方明说「**system call filtering isn't a sandbox**」，且基于 ptrace 的通知可逃逸；真正贴合需求的是 **Landlock**（非特权进程自我施加文件层级 + 端口限制，**一旦施加不可撤销、只能叠加**，并继承给子进程；官方点名不设 `no_new_privs` 会造 confused deputy） | 闸门**下到容器/VM，或 Landlock + `no_new_privs`**；把策略目录与 managed 配置路径设 **denyWrite**；用一个**不在 PATH** 的包装器注入 `--settings` |
| **凭据落点（产品事实）**（A-101） | ★ **Claude Code 有官方权威清单**（子代理已核实）：macOS = 加密 **Keychain**（写失败才落 `~/.claude/.credentials.json`，0600）；Linux/Windows = `.claude/.credentials.json`；设 `CLAUDE_CONFIG_DIR` 则跟着移；另有第五个文件 `~/.claude.json`（sign-in session / MCP / 全局配置）。★ 失败模式：**双写不一致**（官方 changelog 记录过 macOS「残留 `.credentials.json` ⇒ 已登录仍报 not logged in」）；★ **凭据进 transcript 就泄**（`~/.claude/projects/*.jsonl` 明文记下工具读到的一切） | `policy/credentials.md` 列死这几条路径并在沙箱里 **denyRead**；工人**永远不挂载 home 的凭据目录** |
| **配置开关的来源证明**（A-103） | 成熟形态 = **写入路径即证明**，不是事后猜：① 分层 + **只读受管源**（HKCU 是用户可写降级项，官方标注 **not an admin source**）；② **SACL** 记录受保护对象的访问尝试 ⇒ **事件日志即凭证**；③ W3C PROV 数据出处模型；④ IP 出处 + 防篡改审计。★ 失败模式：**同一身份既写文件又写日志** ⇒ 审计日志被代理改写，「来源证明」归零；★ **mtime 不能区分作者** | 策略文件放**受管目录**（工人 ACL 只读）+ 开 **SACL** + 每次策略变更由**你的身份**写一条 **append-only** `gates/audit.jsonl`（含 `who=human` / worker 进程 pid + 镜像校验），**代理不得写该文件** |
| **配额预警**（A-107） | 服务端**确有**定额查询面：OpenAI 组织级 Usage/Costs API、Anthropic Usage & Cost Admin API；两家普通响应都带 rate-limit 头。★ 子代理**没取到** OpenAI / Gemini 官方页原文（Cloudflare 403 拦截）⇒ **那两个品牌的细节不要当已核实引用**。★ 失败模式：只记账**经过代理**的流量 ⇒ **你手工直连同一账号那部分没有本地记录**，预警必然漏；把非官方逆向接口当权威（只回百分比 + 重置时间、**不含 token 数**、无版本承诺） | **服务端为权威** —— 按 key/project 维度定时拉 Usage API，与本地 `gates/quota.jsonl` **对账**，差额即「手工命中」；阈值（70% / 85%）触发告警；**本地只做提前量估算，不作判据** |

★ **子代理自己标的知识缺口（值得记）**：**CodeBuddy 的凭据清单它没拿到官方依据**（文档站是 JS 渲染 SPA，抓下来只有导航；搜到的都是第三方来源）⇒ 它建议**实地枚举** `%USERPROFILE%\.codebuddy`。**这一条我在本机就能做**（下一节就是实测）。

---

## ★ 补：本机实测 —— CodeBuddy / WorkBuddy 的登录态到底住在哪（填上子代理唯一的知识缺口）

子代理说得对：**官方文档拿不到**（文档站是 JS 渲染 SPA）。但**这台机器上有** —— 实测（2026-10-03 11:5x）：

```
C:/Users/example\.workbuddy\app\session\Network\Cookies            20,480 B   mtime 10:50:00  ← ★ 登录态真身（Chromium 会话库）
C:/Users/example\.workbuddy\app\session\Network\Cookies-journal         0 B
C:/Users/example\.workbuddy\app\session\Network\Network Persistent State  6,200 B  mtime 10:50
C:/Users/example\.workbuddy\app\session\Network\TransportSecurity       1,864 B  mtime 10:23
C:/Users/example\.workbuddy\connectors\<uuid>\.credentials.v3.json        507 B  ← 连接器凭据（键：version / encryption / mcpClientInfo，加密态）
C:/Users/example\.workbuddy\usage-log.json                                981 B  ← ★ 本地用量记账（配额预警的现成输入）
C:/Users/example\.workbuddy\failover.json                               1,052 B  ← 故障切换链（"数据驱动 failover" 的现成落点）
C:/Users/example\.workbuddy\models.json                                     2 B  ← 空的（`{}`）
```

★ **`~/.codebuddy/` 里根本没有凭据文件**（这正好解释了子代理为什么查不到）——里面只有：
`user-state.json`（130 B，纯遥测计数：`numStartups` / `sessionsSinceLastTip` …）· `settings.json`（79 B，只有 `trustedDirectories`）· 空的 `sessions/` · `web-ui-port.json` · `plugins/known_marketplaces.json`。
⇒ **结论**：CodeBuddy（CLI 侧）把**登录态借住在 WorkBuddy 那个 Electron 应用的 Chromium 会话里**（`app/session/Network/Cookies`），
`.codebuddy` 只管插件/受信目录/遥测。★ 这条把外部报告的空白补上了，也**解释了为什么"把登录态搬到别处"做不到**（它不是一份可搬的凭据文件，而是**应用级会话库**）。

★ 与外部结论**互相印证**的一条：Claude Code 的凭据**跟着 `CLAUDE_CONFIG_DIR` 走**；CodeBuddy 同理 —— 我们把
`USERPROFILE`/`HOME`/`APPDATA`/`LOCALAPPDATA`/`WORKBUDDY_CONFIG_DIR`/`CODEBUDDY_CONFIG_DIR` **六个变量一起重定向**时，
登录态跟着走；**只挪 `USERPROFILE`+`HOME` 时它变未登录、外面那个号一字未动** ⇒ 这正是「**并存**」（一个号一个 home）能成立的原因
（三组对照实验写在 `infra/pool/codebuddy_accounts.py` 文件头）。

---

## ★★ 对照表：这些外部落点里，**哪些已有卡在管 / 哪些是新账**

| 外部落点 | 状态 | 归属 |
|---|---|---|
| 门的输入清单完整性 + **毒药测试**（改一个门真读到的文件，`input_hash` 必须变） | ★ **已有卡** | **卡 161「门的输入面」**（它整张卡就是这个）——把「毒药测试」补进它的规格即可 |
| 锁的自觉性 + 续租 keepalive | ★ **已有卡** | **卡 163「锁与租约接线」**——**新增两条**：fencing token（写产物前校验 token 单调）+ 过期判定用 `time.monotonic()` |
| 台账/指针的引用解析门（note 里的符号被删即红） | ★ **已有卡** | **卡 160「台账接进门」** |
| 观测面：`log 0 字节 = 失败`、把「不知道」渲染成「卡死」 | ★ **已有卡** | **卡 164「观测面与通则」**——补上「**三值判决**（ran-pass / violate / unable-to-determine）」 |
| 陈旧产物冒充当前状态（旧判决、旧 `last.json`） | ★ **已有卡** | **卡 156「旧判决冒充当前状态」**——补上「**读取前独立复算 tree/rev**」 |
| 豁免要带到期日 | ★ **部分已有** | 卡 159 已做「实际改动 ⊆ 证据 ∪ 豁免」；★ **豁免本身没有 expiry 是新账** |
| **三值判决写进 `gates/last.json`** + 缺口进退出码 | ☆ **新账（最高优先）** | 新建卡：`Silent Success` 那条 |
| **每道门配反例夹具 + 常驻金丝雀**（门对坏样例不红 ⇒ 门自己判红） | ☆ **新账（最高优先）** | 新建卡：把 `check_layers_selftest` 的形状推广到 `contrast`/`style`/`ui_text`/`audit_titles` |
| `--no-cov` 必须来自 `gates/waivers.toml`（卡号+到期日） | ☆ 新账 | 我们 `run_gates.py` 的 `acceptance` 那行正带着它 |
| **deselect 基线**（`passed`/`deselected` 只许相符或增加） | ☆ 新账 | 门上 `2051 passed, 2 deselected` 现在无人比 |
| `last.json` 的 tree/rev **独立复算** | ☆ 新账 | 与卡 156 同族，但判据是新的 |
| `gates/rule_wiring.toml`（规矩 → 门 → 钉子，**双向核对**） | ☆ 新账 | 可并入卡 160 |
| flaky **三值分类**（同命令重跑 N 次、按失败特征分类、别用测试名） | ☆ 新账 | 与卡 164 同族 |
| 证据锚定升级成**多属性语义锚** + 内容哈希只告警 | ☆ 新账 | 卡 159 已把 `text:` 改成语义锚点，这是下一步 |
| trailer 降级为"声称" + **真证据 = 门禁日志包 sha256** | ☆ 新账 | 卡 133 治过 trailer 真伪（已落地），这条更进一步 |
| **mutation testing 增量**（只对本次 diff 覆盖行，挂夜间） | ☆ 新账 | 别塞进全量门禁 |
| import 规则**三项覆盖判据**（规则路径存在 / 每层被覆盖 / 判定条数 >0） | ☆ 新账 | 卡 159 只到"判据有反向" |
| **写语句 AST 扫描**（只扫 core + 数据访问，先只报数） | ☆ 新账 | 白名单化，不许豁免注释 |
| lost update **模式化**（非阻断起步） | ☆ 新账 | Python/ORM 没有现成检测器 |
| TOCTOU **恶意探针**（两次读之间改盘，必须红） | ☆ 新账 | 比任何 lint 都硬 |
| 事务边界 `check_tx_boundary.py` | ☆ 新账 | 写函数真源用 `docs/commands.toml` |
| 死代码 `vulture` + 未用配置键双向 diff | ☆ 新账 | vulture 接 `--fast` |
| 双向登记的**中间态**（`unregistered` 在 `--check` 下退 1） | ☆ 新账 | |
| **capability 授权 + PEP**（`capabilities.yaml` + `preflight.py`，默认拒绝、看参数值） | ☆ **新账（大）** | 外部点名的头号失败模式 |
| 无人值守**三档**（`gates/autonomy.md`，第三档 fail-closed） | ☆ 新账 | |
| 人专属文件用 **ACL/SACL**（钩子/CODEOWNERS 不算边界） | ☆ 新账 | |
| 策略下沉（Landlock + `no_new_privs` / denyWrite 钩子与配置） | ☆ 新账 | |
| 凭据落点清单 `policy/credentials.md` + 沙箱 denyRead | ★ **可并入** | **卡 149/155**（登录态与 profile 隔离）；本机实测见上一节 |
| 配置开关的**来源证明**（append-only `gates/audit.jsonl`、SACL、mtime 不认作者） | ☆ 新账 | |
| 配额预警（服务端 Usage API ↔ 本地 `usage-log.json` 对账，70%/85% 阈值） | ☆ 新账 | ★ 本机已有 `~/.workbuddy/usage-log.json` 可用 |

**小结**：**6 条已有卡在管**（161 / 163 / 160 / 164 / 156 / 149-155），**约 22 条是新账** —— 其中**最该先做的两条**是
①「**三值判决**」（把"不知道"从"通过"里分出来）②「**每道门配反例夹具 + 常驻金丝雀**」（证明门没死）。
★ 这两条不需要新工具、不需要联网，是**当天就能开工**的。
