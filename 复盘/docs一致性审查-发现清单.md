# 复盘 · docs 工程管理一致性审查（发现清单·完整版）

> 角度：**工程管理**（一致性 / 可维护性 / 可追溯性），不评内容对错。
> 范围：`docs/` 全部 18 份文档 + 仓库根文档 + `scripts/check_layers.py`。
> 方法：逐份通读 + 全库交叉引用搜索（带文件:行号）+ 脚本实测。
> 产出：**17 个问题**，分 4 类。每条附**精确位置**（可用于逐条修复）。
> 状态：本文件是"发现（诊断）"，修复另见《docs一致性修复记录》。

---

## 一、结构性问题（体系内部自相矛盾）

### S1. `docs/README.md` 的结构描述与实际不符

**证据**（`docs/README.md:32-41`）：结构图写
```
intention/ specification/ implementation/ taste/
CODING_GUIDELINES.md / ACCEPTANCE.md
src/  源码
tests/  单元测试
```
**实际**：
- `src/`、`tests/` 在**仓库根**，**不在 `docs/` 内**（实测：仓库根只有 `config.example.toml`、`pyproject.toml`）
- `docs/` 根下实际是：`ACCEPTANCE.md`、`changelog.md`、`CODING_GUIDELINES.md`、`README.md`
- 图里**缺 `contracts/`**（已被我补入，但未说明其与各层关系）

**危害**：README 是总入口，却与真实结构不符 → 后来者第一印象即错。

### S2. "几层"说法不一致：**3 / 4 / 6** 三种

**证据**（全库搜索）：

| 位置 | 原文 | 说法 |
|---|---|---|
| `docs/README.md:19` | 「功能模块（对应治理**三层** SR-F）」 | 3 |
| `docs/README.md:32` | 「结构（**三层**治理 + 源码）」 | 3 |
| `docs/README.md:48` | 「intention / specification / implementation 骨架闭环…**三层**对齐脚本」 | 3 |
| `docs/README.md:50` | 「质量门：…**三层**对齐 PASS」 | 3 |
| `CODING_GUIDELINES.md:3` | 「本项目 TASTE + implementation 模块划分 + **三层**（intent/spec/impl）对齐」 | 3 |
| `CODING_GUIDELINES.md:56` | 「改动必须能通过**三层**对齐：intent→spec→impl」 | 3 |
| `ACCEPTANCE.md:47` | 「**三层**对齐：`check_layers.py`（intent↔spec↔impl↔**taste**）」 | **4**（说法3层，却列4项） |
| `changelog.md:20` | 「**三层**对齐 PASS」 | 3 |
| `specification/traceability.md:22` | 「**三层**闭合校验」 | 3 |
| `implementation/traceability.md:27` | 「**三层**闭环」 | 3 |
| `contracts/flows.md:156` | 「与**三层**文档的关系」 | 3 |
| **实际文档体系** | intention / specification(含 conventions) / **contracts** / implementation / taste | **5**（或按目录算 intention/specification/contracts/implementation/taste = 5；含根目录 4 文档另算） |

**危害**：同一体系三套层数说法；新增的 conventions/contracts 完全不在旧口径里。

### S3. `scripts/check_layers.py` 过时，输出**虚假 PASS**（已实测）

**证据**：
- 改前实测输出：`THREE-LAYER CHECKS: PASS ✅`
- 但其只读 3 个路径：`needs.md`、`specification/traceability.md`、`implementation/traceability.md`
- **不检查** `conventions.md`、**不检查** `contracts/`

**危害**：护栏与被守护体系脱节 → 当初"交叉全断"它没发现；现在仍给假安全感。

---

## 二、引用断裂（文档指向不存在的东西）

### S4. `DESIGN.md` 被 5 处引用，**文件不存在**

**实测**：`docs/DESIGN.md` 不存在；根目录 `DESIGN.md` 不存在。

**引用位置（精确）**：
| 文件:行 | 原文片段 |
|---|---|
| `docs/README.md:53` | 「设计决策（know-why）见 `DESIGN.md`」 |
| `CODING_GUIDELINES.md:4` | 「与 `ACCEPTANCE.md`、`DESIGN.md`（know-why）、`taSte/` 配合」 |
| `CODING_GUIDELINES.md:55` | 「同步 `implementation/modules.md` + `docs/changelog.md` + `DESIGN.md`(若 know-why 变化)」 |
| `intention/needs.md:177`（N38） | 「开源文档完整：README / 架构 / **DESIGN.md（know-why）** / LEARN.md / CODING_GUIDELINES」 |
| `specification/nonfunctional.md:30`（SR-NF9） | 「必须提供：…/ DESIGN.md（know-why）/ LEARN.md / CODING_GUIDELINES」 |

### S5. `LEARN.md` 被 SR-NF9（一版必须）要求，**文件不存在**

**引用位置**：`intention/needs.md:177`（N38）、`specification/nonfunctional.md:30`（SR-NF9）。

### S6. `CONTEXT.md` 已被删除，**当前无残留引用**

**实测**：全库搜索 `CONTEXT.md` 引用 = **0 处**。
**结论**：虽然文件在快照里是 `D`（删除），但**无引用残留**（此项**不构成问题**，仅记录）。
> 注：用户已明确"先别恢复"，故仅记录事实。

---

## 三、逻辑不明（读起来矛盾/指代不清）

### L1. `docs/README.md` 结构图混淆「docs/」与「仓库根」
（同 S1，此处记其"逻辑"面）该图未标明作用域，读者无法判断它描述的是 docs/ 还是仓库根。

### L2. `taste/README.md` 指向**项目外绝对路径**，且 taste 层是空壳

**证据**（`taste/README.md:10`）：
> `D:/docs\知识库\Jelly文件_Pro\vibe-coding-1\TASTE.md`

又说（`:12`）「其中内容发现特定部分需要为重写」，`:39-42` 留了「待完善」清单（系统灵魂/领域特定品味/CODING_GUIDELINES 三项全空）。

**危害**：①依赖项目外个人路径，换机器即断链；②taste 层实为空壳，但被 `CODING_GUIDELINES` 与 `ACCEPTANCE` 当作已生效的"品味层"引用。

### L3. "MVP" 一词**两义**，且互相冲突

**证据**：
| 位置 | 含义 |
|---|---|
| `ACCEPTANCE.md:1,5,25` | 「第一版 MVP」= 任务 CRUD/My Day/逾期/分组/子任务/Repeat/轻债务（**功能清单**） |
| `contracts/flows.md:7,19,21`、`interactions.md:7,79` | MVP = **框架 + 2 线 + 交叉**（任务/专注/记账/摘要） |

**危害**：同一词在验收文档与契约文档含义不同，易被误读为同一件事。

### L4. `ACCEPTANCE.md` AC-11 有笔误

**证据**（`ACCEPTANCE.md:20`）：
> 「pywebview 启动出窗口，默认视图=**MYSQL** 清爽的 My Day」——"MYSQL" 应为 "My Day"。

### L5. "实现前先读什么"三处口径不一，无权威

| 位置 | 说法 |
|---|---|
| `CODING_GUIDELINES.md:56` | 「三层对齐：intent→spec→impl，并用 taste 自检」 |
| `implementation/README.md`（新加） | 「实现顺序：conventions → contracts → modules」 |
| `docs/README.md`（新加） | 「先读 conventions → 再读 contracts → 最后 implementation」 |

**危害**：无唯一读法，AI 与人都可能读错顺序。

### L6. `changelog.md` 与当前版本状态脱节

**证据**：`changelog.md` 最新条目为 `[0.1.0] — 第一版完整`；而另一分支 `feat/ui-refactor` 有 `[0.2.0] UI重构`（**未合入**）。
**危害**：当前主线版本状态不明（0.1.0？下一步从哪起算？）。

---

## 四、内容与体系脱节（新加的东西没被纳入管理）

### D1. `conventions.md`（约定层）未被索引类文档登记
- `ACCEPTANCE.md` 不知它；`CODING_GUIDELINES.md` 不知它；`check_layers.py` 不查它
- 唯一登记处：`specification/traceability.md` 的"约定层映射"（本次会话加）

### D2. `contracts/`（契约层）未被验收与护栏纳入
- `ACCEPTANCE.md` 的 AC 条目**仍以"功能存在"为标准**（如 AC-13「番茄/普通计时；可绑定任务（时长计入投入）」——**写了"计入投入"但实际未实现也判通过**）
- 无任何 AC 引用 `contracts/`；`check_layers.py` 不查 contracts

**危害**：契约层是为"防做一半"而建，但验收标准没跟着改 → 旧 AC 无法发现"做一半"。

### D3. `needs.md` N25 的存储"待定"与约定层"已定"冲突
**证据**：`intention/needs.md:146`「*衍生*：存储方案是 design 层关键权衡点（SQLite？文件+观察者？）」；而 `conventions.md` 已定「混合：Markdown 真源 + 结构化索引」。

---

## 五、问题汇总表（可直接用于修复分派）

| 优先级 | 编号 | 问题 | 涉及文件 |
|---|---|---|---|
| **P0** | S2 | 层数口径 3/4/5 不一 | README / CODING_GUIDELINES / ACCEPTANCE / changelog / 两个 traceability / flows |
| **P0** | S3 | check_layers 过时给假 PASS | `scripts/check_layers.py`（**已改**） |
| **P0** | S1 | README 结构描述与实际不符 | `docs/README.md` |
| **P1** | S4 | DESIGN.md 被 5 处引用但不存在 | README / CODING_GUIDELINES×2 / needs / nonfunctional |
| **P1** | S5 | LEARN.md 被要求但不存在 | needs / nonfunctional |
| **P1** | D2 | AC 未升级到"操作闭环" | `ACCEPTANCE.md` |
| **P1** | D1 | conventions/contracts 未登记 | ACCEPTANCE / CODING_GUIDELINES / check_layers |
| **P1** | L5 | 读法链三处不一 | CODING_GUIDELINES / impl README / docs README |
| **P2** | L3 | MVP 一词两义 | ACCEPTANCE / contracts |
| **P2** | L6 | changelog 与版本状态脱节 | `changelog.md` |
| **P2** | D3 | N25 存储"待定"vs"已定" | needs |
| **P2** | L2 | taste 指向项目外绝对路径 + 空壳 | `taste/README.md` |
| **P3** | L4 | AC-11 "MYSQL" 笔误 | ACCEPTANCE |
| **P3** | L1 | README 结构图混淆作用域 | docs/README.md |
| — | S6 | CONTEXT.md 无残留引用 | （不构成问题，仅记录） |

---

## 六、根因

**文档快速演进，但"管理文档的元层"没有跟着演进。**

三种断裂：
1. **索引层没跟上**——README / ACCEPTANCE / CODING_GUIDELINES 不知道新加的 conventions、contracts
2. **护栏没跟上**——`check_layers.py` 检查的还是老三样
3. **口径没统一**——"几层"、"读什么"、"MVP 指什么"，各处各说

> **一句话：典型的"增量堆砌快于存量打磨"**——与 `taste/README.md` 自己的品味第 2 条「存量打磨 > 增量堆砌」相矛盾。
> **项目自己的品味，正在被项目自己违反。**

---

## 七、修复顺序原则

**先修元层（口径与护栏），再修内容。** 因为：
- 元层不修，后面每改一处都会继续产生新的不一致
- 层数口径（S2）是"总口径"，必须最先定，其余修复都引用它

建议顺序：
1. **定"五层"口径**（intention / specification(+conventions) / contracts / implementation / taste）→ 全库统一
2. **修 README 结构节**（分清 docs/ 与仓库根）
3. **修 check_layers**（纳入 conventions + contracts）→ **已完成**
4. 补/改 DESIGN.md、LEARN.md 引用
5. 立唯一读法链
6. AC 升级到闭环
7. P2/P3 逐条清理
