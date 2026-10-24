# 卡 E12 —— 跨分区写者判据不认 `depends`：同一判据两处实现不一致

> 台账号 T-AG463 · 分区 E（CI）· 依赖：无

## 现在疼在哪（实测）

- 登记提交 `dc1f024c`（分区 G + 卡 E7/E8/E9 与七条台账）之后，`python -X utf8 tools/wb_plan.py check`
  退 **1**，stderr 五条 `[跨分区]`：

  ```
  [跨分区] 卡 B1（分区 B）与 E9（分区 E）：files 相交 ['docs/workbacklog.toml']
  [跨分区] 卡 E7（分区 E）与 G2（分区 G）：files 相交 ['skills/README.md', 'skills/pipe-card/references/dispatch.md', 'skills/pipe-land/SKILL.md']
  [跨分区] 卡 E7（分区 E）与 G3（分区 G）：files 相交 ['skills/pipe-land/SKILL.md']
  [跨分区] 卡 E7（分区 E）与 G4（分区 G）：files 相交 ['skills/README.md']
  [跨分区] 卡 E9（分区 E）与 G3（分区 G）：files 相交 ['tests/test_wb_land.py']
  ```

- **这五对全都已经用 `depends` 串起来了**（`B1 depends ["E9"]`、`G2 depends ["E1","E7","G1"]`、
  `G3 depends ["E1","E7","G2","E9"]`、`G4 depends ["G2","E7"]`）—— 串起来就是「后动手的那张等前面落完」，
  同一个文件仍然只有一个写者。判据却没看这一层。
- **同一判据两处实现不一致**：`tools/pool/plan.py` 的 `validate()`（`tools/pool/plan.py:313-320`）判同文件相交时
  写的是 `if hit and not dependency_path(first, second, cards):` —— **认** `depends`；而
  `tools/wb_plan.py:346 cross_partition_writers()` 只按 `files_intersect` 判、**不看** `depends`。
- 后果（实测）：`tests/test_wb_plan.py::test_check_command_passes_on_seed` 断言
  `wb_plan.main(["check", "--backlog", SEED]) == 0`，现在拿到 1 ⇒ **E7 第三趟落地 pytest 红**
  （`2 failed, 2987 passed`）—— 挡住的不只是 E7，之后每张卡的落地都会被这条钉子挡住。

## 目标

同一个判据只有一套语义：**`depends` 串起来的对子不算「同一文件两个写者」**（分区那一层也一样）。

## 判据

1. `cross_partition_writers()`（`tools/wb_plan.py:346`）跳过
   `dependency_path(first, second, backlog.cards)` 为真的对子 —— 与 `validate()` 用**同一条规则**，
   方向无关（前者依赖后者、后者依赖前者都算串起来了）。
2. **没有依赖路径的对子照旧报**，`cmd_check()` 仍退 1 —— 不许把跨分区判据整体废掉或降级成只报。
3. 报行文案保留「分区只避免号撞，不避免文件撞」，并补一句「（有 `depends` 串起来的对子不报）」，
   让人一眼看出为什么这次没报。
4. **钉子 ≥3**（`tests/test_wb_plan.py`）：① 两张跨分区卡 files 相交 + `depends` ⇒ 不报且 `check` 退 0；
   ② 同样相交但没有 `depends` ⇒ 报且退 1；③ 反向依赖（后一张依赖前一张）同样不报。
5. **真队列实测**：改完在仓库根跑 `python -X utf8 tools/wb_plan.py check` 退 **0** 并打印 `[OK ] …`；
   把这条输出原样抄进回话（判据要能自证）。

## 不许做

- 不许改成「只报不拒」（那等于把 `check` 的退出码废掉，E7 落地照样红）。
- 不许动 `tools/pool/plan.py` 的 `validate()`（它已经是「认 `depends`」的正确形态，本卡只把另一处对齐）。
- 不许为了让 `check` 变绿去改队列里的 `depends` / `files`（判据要和队列脱钩）。
