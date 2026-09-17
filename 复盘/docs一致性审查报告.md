# 复盘 · docs 工程管理一致性审查

> 角度：**工程管理**（文档体系的一致性、可维护性、可追溯性），不是内容对错。
> 范围：`docs/` 全部 18 份文档 + 相关脚本。
> 方法：逐份通读 + 交叉引用核对 + 脚本实测。
> 结论：**发现 4 类共 15 个问题**，其中 3 个是"结构性不和谐"（会持续制造混乱），需优先处理。

---

## 一、结构性问题（最严重：体系内部自相矛盾）

### ★S1. `docs/README.md` 描述的目录结构 ≠ 实际结构

**实际**（`docs/` 下）：
```
docs/
├─ intention/     README.md, needs.md
├─ specification/ README, conventions, functional, nonfunctional, traceability
├─ contracts/     interactions.md, flows.md        ← 新加
├─ implementation/ README, architecture, modules, traceability
├─ taste/         README.md
├─ README.md / ACCEPTANCE.md / CODING_GUIDELINES.md / changelog.md
```

**问题**：`docs/README.md` 的"结构"一节把它描述为「三层治理 + 源码」：`intention/ specification/ implementation/ taste/` + 根目录 `CODING_GUIDELINES.md / ACCEPTANCE.md` + `src/ tests/`。
- 该描述**把 taste 与源码写在同一层级**，但 `docs/` 下**没有 `src/`、`tests/`**（它们在仓库根）→ 读者按 docs/README 找会扑空。
- `contracts/` 是我加的（已补进 README），但 **README 没说明它与另四层的关系**——它现在孤零零挂着。

**不和谐点**：README 是"总入口"，却与真实结构不符 → 所有后来者的第一印象就是错的。

---

### ★S2. 文档层级数**不一致**：三处说法互相打架

| 出处 | 说法 |
|---|---|
| `docs/README.md` | 「**三层**治理 + 源码」（intention/specification/implementation） |
| `implementation/README.md` | 「上游 `../specification/`，下游 `src/`」——**两层关系** |
| `CODING_GUIDELINES.md` | 「三层（intent/spec/impl）对齐」 |
| `ACCEPTANCE.md` | 「三层对齐：`scripts/check_layers.py`（intent↔spec↔impl↔**taste**）」← **四个** |
| `scripts/check_layers.py` | 实际只读 `intention/needs.md` + `specification/traceability.md` + `implementation/traceability.md` ← **三个** |
| **实际文档** | 现在有 **6 层**：intention / specification / **conventions**（约定）/ **contracts**（契约）/ implementation / taste |

**不和谐点**：同一个体系，"几层"有 **3、4、6** 三种说法。`check_layers.py` 的 docstring 写"intent→spec→impl←taste"（4 个），但代码只读 3 个文件；且**完全不知道 conventions 和 contracts 的存在**。

---

### ★S3. `scripts/check_layers.py` 已过时，会给出**虚假的"对齐通过"**

实测该脚本只检查 3 个文件：
```
INT      = docs/intention/needs.md
SPEC_TRACE = docs/specification/traceability.md
IMPL_TRACE = docs/implementation/traceability.md
```
- **不检查** `conventions.md`（新约定层）→ 约定层的完整性无人验证
- **不检查** `contracts/`（新契约层）→ 契约层的覆盖无人验证
- 于是它仍会打印「三层对齐 PASS」，给人**虚假的安全感**

**不和谐点**：护栏脚本与被守护的体系脱节——这正是它当初没发现"交叉全断"的原因。

---

## 二、引用断裂（文档指向不存在的东西）

### ★S4. 多处引用 `DESIGN.md`，但该文件**根本不存在**

实测：`docs/DESIGN.md` 不存在、根目录 `DESIGN.md` 不存在。

引用它的地方：
| 文件 | 引用原文 |
|---|---|
| `docs/README.md` | 「设计决策（know-why）见 `DESIGN.md`」 |
| `CODING_GUIDELINES.md` | 第 4 行「与 `ACCEPTANCE.md`（功能验收）、**`DESIGN.md`（know-why）**、`taSte/`（品味）配合」；第 9 条「同步…+ **`DESIGN.md`**(若 know-why 变化)」 |
| `specification/nonfunctional.md` | SR-NF9「必须提供：…/**DESIGN.md**（记 know-why）/ **LEARN.md**（零基础定制）/ CODING_GUIDELINES」 |

### ★S5. `LEARN.md` 被 SR-NF9 要求，但不存在

`SR-NF9`（一版必须）明确列了 `LEARN.md`（零基础定制），实际**不存在**。

### S6. `CONTEXT.md` 被删除但仍可能被引用

`docs/CONTEXT.md` 在快照里显示为 `D`（已删）。需全库核查是否还有文档引用它。

---

## 三、逻辑不明（读起来矛盾或指代不清）

### L1. `docs/README.md` 说 taste 在 docs 内，但"结构"图把它与 src 并列

```
intention/
specification/
implementation/
taste/            ← 在 docs/ 内 ✅
CODING_GUIDELINES.md / ACCEPTANCE.md   ← 实际在 docs/ 内 ✅
src/  源码         ← ❌ 在仓库根，不在 docs/
tests/  单元测试    ← ❌ 在仓库根，不在 docs/
```
**逻辑不明**：这段到底是描述 `docs/` 还是仓库根？读者无法判断。

### L2. `taste/README.md` 指向仓库外的绝对路径

> `D:/docs\知识库\Jelly文件_Pro\vibe-coding-1\TASTE.md`

**逻辑不明**：项目文档依赖**项目外**的个人路径。换机器/换人打开即断链；且它说"完整 TASTE 在那里"，但本项目 taste 层目前是**空壳**（只有"待完善"清单）。

### L3. `ACCEPTANCE.md` 的范围与"第一版范围"用词冲突

- `ACCEPTANCE.md` 标题：「第一版 **MVP**」
- 其 §第一版 MVP 范围写：「任务 CRUD / My Day / 逾期 / 分组 / 子任务 / Repeat / 轻债务」
- 但紧接着又有「第一版**完整**验收（SR-F3~F9）」AC-13~AC-23
- 而 `docs/README.md` 说「✅ **第一版完整**」

**逻辑不明**：到底是"MVP 只含任务"还是"第一版完整含 F1–F9"？"MVP"一词在此**与我们现在讨论的 MVP 含义冲突**（我们的 MVP = 框架+2线+交叉）。

### L4. `ACCEPTANCE.md` 有一处笔误级错误

> AC-11 桌面窗口界面 | …默认视图=**MYSQL** 清爽的 My Day

**"MYSQL"** 显然是 "My Day" 的误写（或复制粘贴事故）。属"不和谐"，虽小但会让人困惑。

### L5. `CODING_GUIDELINES.md` 与 `implementation/README.md` 对"实现前读什么"的口径不一

- `CODING_GUIDELINES.md` §9：「改动必须能通过三层对齐：intent→spec→impl，并用 `taSte/` 品味自检」
- `implementation/README.md`（我加的）：「实现顺序：conventions → contracts → modules」
- `docs/README.md`（我加的）：「先读 conventions → 再读 contracts → 最后 implementation」

**逻辑不明**：三处各说一套"应先读什么"，没有一个**权威的读法**。

### L6. `changelog.md` 只记到 0.1.0，与"第一版完整"状态脱节

- changelog 最新条目：`[0.1.0] — 第一版完整`
- 但 `docs/README.md` 状态区写「✅ 第一版完整」+ 质量门数字
- 而 `feat/ui-refactor` 分支有 `[0.2.0] UI重构` 的 changelog（**未合入**）

**逻辑不明**：当前主线的版本号状态不明——是 0.1.0？下一步重构从哪个版本起？

---

## 四、内容与体系脱节（新加的东西没被纳入管理）

### D1. `conventions.md` 未在任何"索引类"文档中被登记

它被 `specification/README.md` 的目录行提到、被 `docs/README.md` 的结构图提到，但：
- `ACCEPTANCE.md` 不知道它
- `CODING_GUIDELINES.md` 不知道它
- `check_layers.py` 不检查它
- `specification/traceability.md` 有"约定层映射"（我加的）✅ —— 这是唯一登记处

### D2. `contracts/` 未被纳入验收与管理

- `ACCEPTANCE.md` 的 AC 条目**仍以"功能存在"为标准**（如 AC-13「番茄/普通计时；可绑定任务（时长计入投入）」——注意它**写了**"时长计入投入"，但实际未实现也判通过）
- 没有任何 AC 引用 `contracts/`
- `check_layers.py` 不检查 contracts

**不和谐点**：契约层是为"防做一半"而建的，但**验收标准没跟着改**——旧 AC 无法发现"做一半"。

### D3. `needs.md` 中 N25 写着"存储方案待设计（SQLite？文件+观察者？）"，与已定决策冲突

- `needs.md:146`：「*衍生*：存储方案是 design 层关键权衡点（SQLite？文件+观察者？）」
- 但本会话已决策：**混合模式（Markdown 真源 + 结构化索引）**，并写入了 `conventions.md`
- **逻辑不明**：同一体系的 intent 层还挂着"待定"，约定层已"已定"

---

## 五、问题优先级与处理建议

| 优先级 | 编号 | 问题 | 建议处理 |
|---|---|---|---|
| **P0** | S2 | 层级数说法不一（3/4/6 层） | 统一为**六层**（intention/specification/conventions/contracts/implementation/taste），全库改口径 |
| **P0** | S3 | `check_layers.py` 过时，给虚假 PASS | 扩展脚本：纳入 conventions + contracts 检查 |
| **P0** | S1 | `docs/README.md` 结构描述与实际不符 | 重写结构节（区分 docs/ 与仓库根） |
| **P1** | S4/S5 | `DESIGN.md`/`LEARN.md` 被引用但不存在 | 二选一：补建文件 / 或把引用改为"待建" |
| **P1** | L5 | 三处"实现前读什么"口径不一 | 确立唯一权威读法链 |
| **P1** | D2 | 验收标准未升级到"闭环" | AC 补"操作闭环"验收维度 |
| **P1** | D1 | conventions 未登记进索引类文档 | 补登 |
| **P2** | L3 | "MVP"一词两义（旧=功能清单，新=框架+交叉） | 明确区分/改名 |
| **P2** | L6 | changelog 与版本状态脱节 | 补条目录入 |
| **P2** | D3 | N25 存储"待定"与约定层"已定"冲突 | 更新 N25 衍生说明或标注已决 |
| **P2** | L2 | taste 指向项目外绝对路径 | 改为相对路径或本地化 |
| **P3** | S6 | CONTEXT.md 删除后引用残留 | 全库核查 |
| **P3** | L1 | README 结构图混淆 docs/ 与仓库根 | 同 S1 处理 |
| **P3** | L4 | AC-11 "MYSQL" 笔误 | 改 "My Day" |

---

## 六、根因

**文档在快速演进，但"管理文档的元层"没有跟着演进。**

具体表现为三种断裂：
1. **索引层没跟上**（README/ACCEPTANCE/CODING_GUIDELINES 不知道新加的 conventions/contracts）
2. **护栏没跟上**（check_layers.py 检查的还是老三样）
3. **口径没统一**（"几层"、"读什么"、"MVP 指什么"，各处各说）

> **一句话：这是一次典型的"增量堆砌快于存量打磨"**——与 `taste/README.md` 自己的品味第 2 条「存量打磨 > 增量堆砌」相矛盾。项目自己的品味，正在被项目自己违反。

---

## 七、建议的下一步顺序

按"先修元层，再修内容"的顺序：

1. **统一层级口径**（P0-S2）：定"六层"并全库改口径
2. **修 `docs/README.md` 结构节**（P0-S1）：分清 docs/ 与仓库根
3. **扩展 `check_layers.py`**（P0-S3）：纳入 conventions + contracts
4. **补/改 `DESIGN.md`、`LEARN.md` 引用**（P1-S4/S5）
5. **确立唯一读法链**（P1-L5）
6. **AC 升级到闭环验收**（P1-D2）
7. 其余 P2/P3 逐条清理

> 建议 1–3 一起做（都是"元层"问题，一次改完口径一致）。
