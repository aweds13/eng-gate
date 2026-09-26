# 复盘 · docs 两处漂移（T-G135，卡 044）

> 日期：2026-09-26。缺口来源：勘察卡 S-6 的全仓文档清点（`gates/diag/文档漂移清点-S6.md`）。
> 本卡只改了三份白名单文件：`docs/implementation/modules.md`、`docs/人工验收-照着点.md`、本复盘。

## 一、为什么这么做

- **P5（事实过期）**：`docs/implementation/modules.md:173` 写「跨端同 id 去重（**来源标记尚未落库**，
  见 `traceability.toml` 的 `SR-F2.6b`）」。复核读数：台账里 `SR-F2.6b` 的 `status = "done"`，
  其 evidence 含 `text:src/timeflow/core/sync.py::同 id 去重` 与
  `text:src/timeflow/core/sync.py::来源标记 device_id` —— 原句与真源冲突。
  处置按主控裁定：**只加日期注、原句保留**（读者能看到来龙去脉），不把原句改写。
- **D2（自称的计数没人对过）**：`docs/人工验收-照着点.md` 没有对账表，卡表里「剩 6 项」无从对起。
  处置：文末新增 `## 附录 · 2026-09-26 对账（T-G135 补）`，**先数总数**（20 条：A 组 7 / B 组 2 /
  C 组 3 / D 组 2 / E 组 6；「准备」的 4 条命令不算条目），再逐条给结论。

## 二、对账结果

- 共 **20 条**；分布：`已机器覆盖` **2**（㉒ 删除可选、⑭ 可配置词表 —— 清单原文就写「你不用点」）/
  `未覆盖-需人点` **18** / `台账已 done` **0** / `无法判断` **0**。
- 口径：**人没点过的就是没点过** —— 凡还留有「真设备 / 真网络 / 真系统 / 真口味」那一眼，
  一律 `未覆盖-需人点`，机器那一半的读数写在「机器查的读数/命令」列（给了测试文件 / 门禁名）。
- E 组 6 条是口味/决策（清单原文自己写「这一节不是验证，是决策」），机器判不了，全判 `未覆盖-需人点`。

## 三、只加不删的反证

- `git diff --numstat`（提交前工作区读数）：
  - `docs/implementation/modules.md`：1 处「删 + 加」—— 被删的那一行是**原 173 行整行**，
    新行以**逐字相同的原句开头**、只在句末追加日期注（`-U0` 会把「行尾追加」记成一删一加；
    原文一个字没动，附录里也贴了这条 diff 的删除行原文）。
  - `docs/人工验收-照着点.md`：纯追加（0 删）；新增内容接在原「收尾」节之后，原有每一行原样在。
- 另跑 `git diff -U0 | Select-String '^-'`（排除 `---`）逐行看过：除上面 modules.md 那一行外，无任何删除。

## 四、判「不动」的两处（P6 / P7，主控裁定 + 本卡查证）

- **P6** `docs/implementation/architecture.md:28`（`getaways/` 出站适配器预留位「尚未实现」）：
  - 在台账里搜 `getaway` / `adapter` / `出站`：**0 命中** —— 没有可求值的真源依据说它过期；
  - 顺手看了一眼 `src/timeflow/getaways/`：盘上确实只有 `__init__.py`（真是预留位），
    与「尚未实现」不矛盾 → **不许动**。
- **P7** `docs/implementation/coverage.md:5`（「状态：B0 建骨架；B1-B4 逐域填满」）：
  - 在台账里搜 `B0 ` / `B1-B4`：**0 命中**，没有任何真源读数能证明这句过期 → **不许动**。
- 底线（本卡反复用的尺子）：**没有真源读数，就不许改文档**。

## 五、碰到的坑 / 边界

- PowerShell 里直接 `python -c "…嵌套引号…"` 会被引号转义弄坏（SyntaxError）→ 复核命令改放
  `%TEMP%` 下的临时脚本跑（不进仓库、不占白名单）。
- `人工验收-照着点.md` 的条目是**表格行**不是复选框，卡 §1 给的 `Select-String` 模式只匹配到节标题
  —— 条目清点是整份读出来数的（20 条），不是模式数出来的。
- `git diff --numstat` 的「1 删 1 加」是行尾追加的正常读数，不算删原文（见 §三）。
- **没动的**：`architecture.md`、`coverage.md`、`traceability.toml`、`changelog.md`、
  `docs/**` 其它文件、`复盘/**` 其它文件、`tools/**`、`tests/**`、`scripts/**`、`src/**`、`gates/**`。
- 没跑全量门禁（卡 §0.3）；轻门见 §5 自检读数。

## 六、自检读数

- `python -X utf8 scripts/check_layers.py` → PASS（读数见回报；若红且非本卡造成，如实写回报）。
- 台账条目见下方 TOML 块（供集成者粘贴；无裸 ASCII 双引号）。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G135"]
id = "T-G135"
title = "docs 两处漂移：模块文档「来源标记尚未落库」加日期注（台账 SR-F2.6b 已 done）+ 人工验收-照着点补对账附录（逐条：已机器覆盖/未覆盖-需人点/台账已 done/无法判断）"
group = "DOCS"
status = "done"
evidence = [
  "file:复盘/docs两处漂移-T-G135.md",
  "text:docs/implementation/modules.md::2026-09-26 注",
  "text:docs/人工验收-照着点.md::2026-09-26 对账",
]
gaps = "**为什么有这张卡**：S-6 清点的 P5（modules.md:173 写「来源标记尚未落库」而台账 SR-F2.6b 已 status done，复核读数 status 域取值 done、evidence 含 sync.py 的同 id 去重与来源标记 device_id 两条）与 D2（人工验收清单无对账表，卡表的「剩 6 项」没人对过）。**做了什么**：P5 = 按裁定只在原句句末加日期注（原句逐字保留）；D2 = 文末新增对账附录，共 20 条（A 组 7 / B 组 2 / C 组 3 / D 组 2 / E 组 6），结论分布：已机器覆盖 2（㉒、⑭）/ 未覆盖-需人点 18 / 台账已 done 0 / 无法判断 0。**只加不删的反证**：modules.md 的 numstat 是一删一加 —— 被删的是原 173 行整行、新行以逐字相同的原句开头仅句末追加（行尾追加在 -U0 里长这样）；人工验收-照着点.md 纯追加 0 删；逐行看过 -U0 的删除行，无其它删除。**判「不动」的两处**：P6（architecture.md:28 的 getaways 预留位）= 台账搜 getaway/adapter/出站 全 0 命中、且 src/timeflow/getaways 盘上只有 __init__.py 确为预留位 → 没证据说它过期，不动；P7（coverage.md:5 的 B0/B1-B4 状态行）= 台账搜 B0 与 B1-B4 全 0 命中 → 没有真源读数，不动。**没动的**：architecture.md、coverage.md、traceability.toml、changelog.md、docs 其它文件、复盘其它文件、tools/tests/scripts/src/gates 全部未碰；未跑全量门禁（卡 §0.3，集成时由主控跑）。"
```
