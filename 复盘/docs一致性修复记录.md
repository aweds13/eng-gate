# 复盘 · docs 一致性修复记录

> 依据：《docs一致性审查-发现清单》（17 个问题）。
> 原则：**先修元层（口径与护栏），再修内容**——元层不修，后续每改一处都会继续产生新不一致。
> 验收：`python scripts/check_layers.py` → **LAYER CHECKS: PASS ✅**

---

## 一、修复总览

| 编号 | 问题 | 处理 | 状态 |
|---|---|---|---|
| **S2** | 层数口径 3/4/5 不一 | 统一为**五层**：intention / specification(+conventions) / contracts / implementation / taste | ✅ |
| **S3** | check_layers 过时给假 PASS | 扩展为**五层检查** + 引用完整性 + 约定层 N 标注检查 | ✅ |
| **S1** | README 结构描述与实际不符 | 重写结构节，分清 `docs/` 与仓库根 | ✅ |
| **S4** | DESIGN.md 被引用但不存在 | 各引用处标注"尚未建立"；脚本加 KNOWN_MISSING 豁免 | ✅ |
| **S5** | LEARN.md 被要求但不存在 | SR-NF9 改为"待建"并注明；N38 加状态说明 | ✅ |
| **D1** | conventions/contracts 未登记 | 登记进 README / CODING_GUIDELINES / check_layers | ✅ |
| **D2** | AC 未升级到闭环 | ACCEPTANCE 加"已知局限"提示 + 指向契约层闭环验收 | ✅ |
| **L5** | 读法链三处不一 | 统一为三级读法（conventions→contracts→implementation），三处同口径 | ✅ |
| **L3** | MVP 一词两义 | ACCEPTANCE 加术语警告；旧"MVP"改称"组A/组B" | ✅ |
| **L6** | changelog 与版本脱节 | 补 `[未发布]` 条目 | ✅ |
| **D3** | N25 存储"待定"vs"已定" | N25 更新为"已决（混合模式）" | ✅ |
| **L2** | taste 指向项目外绝对路径 | 标注"项目外·仅供参考·应重写进本目录" | ✅ |
| **L4** | AC-11 "MYSQL" 笔误 | 改为"My Day" | ✅ |
| **L1** | README 结构图混淆作用域 | 同 S1 处理 | ✅ |
| **新发现** | conventions 17+ 条规则缺来源 N | 全部补齐 N 标注 | ✅ |
| **S6** | CONTEXT.md 无残留引用 | 核实为无问题，仅记录 | ✅ |

---

## 二、关键修复详解

### 1. 统一"五层"口径（S2）——总口径

**定案**：
```
① intention/        为什么做（N1–N46）
② specification/    必须做到什么（SR-F / SR-NF）+ conventions.md（横切约定）
③ contracts/        怎样才算真的做成（interactions 操作闭环 / flows 动线）
④ implementation/   哪个模块负责
⑤ taste/            技术品味与红线
```

**全库改口径的 11 处**：
| 文件 | 改动 |
|---|---|
| `README.md` ×4 | "三层"→"五层"；结构节重写 |
| `CODING_GUIDELINES.md` ×2 | "三层对齐"→"五层对齐"（并新增 §0 实现前必读顺序） |
| `ACCEPTANCE.md` ×1 | "三层对齐"→"五层对齐" |
| `changelog.md` ×1 | "三层对齐 PASS"→"五层对齐 PASS" |
| `specification/traceability.md` ×1 | 补下游链 → contracts |
| `implementation/traceability.md` ×2 | "三层闭合校验"→"五层"；路径笔误修正 |
| `contracts/flows.md` ×1 | "三层文档关系"→保留（表格对比，指代清晰） |

### 2. 扩展护栏脚本（S3 + D1）

`scripts/check_layers.py` 从**3 项检查**扩为**5 项**：
1. 编号闭合（N→SR→模块）——原有
2. 词表护栏（已砍概念残留）——原有
3. **约定层存在性 + 规则须标来源 N**——新增
4. **契约层存在性 + 引用的 SR 可追溯**——新增
5. **引用完整性（docs 内相对路径必须存在）**——新增

**实测效果**：
- 改前：`THREE-LAYER CHECKS: PASS ✅`（假通过，不检查新层）
- 改后首跑：抓出 **17 条约定缺 N + 多条断链**（真发现问题）
- 修复后：`LAYER CHECKS: PASS ✅`

### 3. 修复脚本自身的 2 处误报（重要）

扩展脚本时，自身暴露 2 个 bug，已修：
1. **基准目录过窄**：把 `flows.md` 里相对 `docs/` 写的 `specification/functional.md` 误判为断链 → 改为**多基准尝试**（相对当前文档 / docs 根 / 仓库根），并对裸文件名递归查找。
2. **待建文件误判**：已标注"尚未建立"的 `DESIGN.md`/`LEARN.md` 仍被扫出 → 加 `KNOWN_MISSING` 豁免。

> **教训：护栏脚本本身也需要"正负样例"验证**，否则会制造噪声（或更糟——虚假通过）。

### 4. 补约定层来源 N（新发现）

原 `conventions.md` 有 **17 条规则未标来源 N**（如「任务状态=…」「债务生命周期=…」等），违背约定层自身的"可追溯"要求。
现已全部补齐，例如：
- `债务 = 逾期天数/程度…（N3）`
- `任务状态 = …（N9）`
- `复习调度：用现成 Python FSRS 库…（N26；SR-F6.1）`
- `贯穿规则：…（N3）`

---

## 三、修复后验收

```
$ python scripts/check_layers.py
LAYER CHECKS: PASS ✅
```
（exitcode=0）

**检查项全绿**：编号闭合 ✅ / 词表护栏 ✅ / 约定层 N 标注 ✅ / 契约层可追溯 ✅ / 引用完整性 ✅

---

## 四、未处理项（明确遗留）

| 项 | 说明 | 建议 |
|---|---|---|
| **DESIGN.md / LEARN.md 待建** | 已被 SR-NF9/N38 要求，当前不存在 | 列入待建；需另行撰写 |
| **taste 层内容为空壳** | 只有"可迁移品味"+待完善清单 | 需为本项目重写系统灵魂与领域品味 |
| **AC 闭环维度未落地** | 已在 ACCEPTANCE 加提示，但 AC 条目本身仍是"功能存在"标准 | 后续按 contracts 验收表重构 AC |

---

## 五、根因与教训

**根因**：文档快速演进，但**管理文档的元层没跟上**——索引层不知新层、护栏检查老三项、口径各处各说。

**教训（可复用）**：
1. **新增一层文档时，必须同步四处**：索引（README）、护栏（check_layers）、验收（ACCEPTANCE）、规范（CODING_GUIDELINES）。只加目录不加登记 = 制造不一致。
2. **护栏脚本必须自测**：扩展后要拿"已知问题"验证它真能抓出（本次首跑抓出 17 条即证明有效）。
3. **口径类修改要全库扫**：改"几层"这种总口径，必须搜遍全库所有出现处，不能只改主文档。
4. **"待建"要显式标注**：被引用但未建的文件，要么补建、要么显式标"待建"，不能让引用悬空。
