# myday 拖拽无版本守卫：A8 复现成立 + 修法 ① 乐观锁落地（卡 021 / T-G109）

> 2026-09-26 · 工人（.wt/core2，基点 `0ba5953`）。两轮合一：第一轮验证（复现成立，先红）；
> 第二轮按主控 §2.9 裁定落地 **① 乐观锁**（转绿、提交）。行号以本卡提交为准。

## §1 为什么有这张卡

盘点卡 S-1 的 A8（`gates/diag/盘点-20260926.md`；原话 `gates/diag/wb-review-T-G79.md` §3）：
`place_myday`/`move_myday` 是「读整个清单 → 算新顺序 → 写回」，读与写之间**没有版本守卫**
（`_write_myday_rank` 的 UPDATE 只抬 `version`、不比较它）——「只是怀疑，没验」。

## §2 复现怎么造的（确定性，不靠 sleep）

`tests/test_myday_version_guard_line.py`（新建）：
两线程、各持 `db_mod.connect()` 独立连接，直调 `manager.place_myday`；`monkeypatch` 换掉
`manager._apply_myday_order` —— 两边在**写之前**用 `Barrier(2)` 会合（读到同一份快照），
leader 写完后 follower 才写（`Event`）。屏障只把「A 读 → B 读 → A 写 → B 写」钉成必然，
不改被测路径。初态：戊 甲 乙 丙 丁（号 1..5）；两程移动：丁→戊前、丙→甲前。
**两种到达次序下，两次都生效的串行正解都是 丁 戊 丙 甲 乙**（对照用例钉死，绿）。

## §3 复现结果（第一轮，旧实现）：成立，两形态都撞出

- follower = 丙→甲前：实测快照 ranks 多重集 **{1,2,2,3,4}** —— **重号 2（戊与丙并存）、
  号 5 缺失**；三行 version=4（被写两次）、两行 version=3（leader 写的没被盖）。
  原始输出：`AssertionError: 并发之后 myday_rank 撞出重号： {…: (3, 4), …: (4, 4),
  …: (2, 4), …: (1, 3), …: (2, 3)}`。
- follower = 丁→戊前（反向探针，同装置互换到达序）：最终 **丁 戊 甲 乙 丙**，号 1..5 不重不缺
  —— 但「丙→甲前」那一程**整段丢更新**（正解是 丁 戊 丙 甲 乙）。

## §4 修法（第二轮，主控 §2.9 裁定 ① 乐观锁）— 落在 `manager.py`

1. **`_write_myday_rank` 的 UPDATE 加 `AND version = ?`**（期望版本来自 `_myday_sequence`
   读出的那份快照）；影响行数 0 = 快照过期 → 抛新增的 `MydayConflictError`（带 task_id 与
   期望/实际 version —— 「报 409 并带上原因」的原因部分）。
2. **`place_myday` / `move_myday` 撞了就重读重算、重试一次**（`_place_myday_order` /
   `_swap_myday_order` 把「落点意图 → 目标顺序」从快照里重算）；**再撞原样抛
   `MydayConflictError`**（不静默吞、不无限重试）。重试直接调 `_write_myday_plan`、
   不再过 `_apply_myday_order` —— 那是并发用例钉交错时机的接缝，重进会让那道为两方
   会合设计的屏障白等一个人。
3. ★ **整份调序计划原子化（本轮探针逼出来的、裁定字面之外的一层）**：第一版按裁定只加
   守卫 + 重试，强制 leader=丙→甲前 的探针立刻打穿 —— follower 的计划**逐行提交**，
   写完 丁/戊 两行才撞上守卫，**已提交的过期计划把号列写花（戊/丙 重号 2）**，重试拿
   被污染的快照当真相、算出 丙丁戊甲乙。修法：`_write_myday_plan` 包成一笔事务，
   任何一行抛错 `rollback` 整笔撤掉再抛；`_write_myday_rank` 不再逐行 commit。
   T-G79「连接上不挂未提交的写」的防线**仍在**（成功 → `place_myday`/`move_myday`
   末尾 commit；失败 → 整笔 rollback），只是从逐行提交上移成整笔提交。
   `tests/test_unit_of_work.py` 冻结清单 11 passed 未动。

## §5 先红后绿（原始结论）

- **先红**（修法前，`0ba5953` 的实现）：`pytest tests/test_myday_version_guard_line.py`
  → **1 failed, 1 passed**（`并发之后 myday_rank 撞出重号： {…: (3, 4), …: (4, 4),
  …: (2, 4), …: (1, 3), …: (2, 3)}`）。
- **后绿**（本卡实现）：同文件 → **2 passed**；并发用例**连跑 10 次全绿**
  （到达序不钉死，两种序都覆盖到）；两个方向的强制序探针（leader=丁 / leader=丙，
  探针在 %TEMP% 未进库）都收敛到 丁戊丙甲乙、errors 空、号 1..5。
- **突变检验**：把 `AND version = ?` 从 UPDATE 里删掉 → 并发用例 **3 连跑全 FAILED**
  （咬得动）；还原 → 全绿。
- 回归：`test_myday_order_line / test_myday_idempotence_line / test_myday_rank_line`
  共 23 条 + 本卡 2 条 → **25 passed**；`tests/test_unit_of_work.py` → **11 passed**；
  `ruff check src/timeflow/core/tasks/manager.py tests/test_myday_version_guard_line.py`
  → All checks passed。

## §6 边界与没动的（如实写）

- **「报 409」目前只到 core 层**：`MydayConflictError` 从 `manager.py` 抛出，但「这个异常
  → HTTP 409」的映射要动 `src/timeflow/api/app.py:1733-1736` 那一带（现在只把
  `ValueError` 映 400）—— **app.py 不在本卡白名单**，且 core 层全仓不引 fastapi
  （在 core 里 raise HTTPException 是架构决策，不停下来自定）。在那行映射补上之前，
  重试一次仍撞的路径经 HTTP 会显成 500。**需要主控决定**：扩白名单补映射，或另立卡。
  （触发条件是两轮都撞，真机上极罕见；core 直调方拿到的就是带原因的异常本身。）
- ★ **worktree 里跑 pytest 必须把本树的 `src` 放 PYTHONPATH 最前**
  （`PYTHONPATH=$PWD/src:$PWD/tools/sandbox_shim`）—— editable 安装把 `timeflow`
  解析到**主树** `engineering/src`，卡 §5 的自检命令（只放 sandbox_shim）在 worktree 里
  测到的是**主树的码**：本轮第一版实现跑 pytest「还红」就是这么来的（红得还跟旧实现
  一模一样）。主树里无所谓，worktree 里是哑巴坑，后续 worktree 卡都要注意。
- **没动的**：`tests/test_unit_of_work.py`（冻结清单 11 passed）、三份既有 myday 测试的
  断言、并发用例的装置与断言（只动 docstring 里「待主控定」那句过时话）、排序口径
  `_MYDAY_ORDER_BY`、T-G98 reserved-rank 逻辑、`version` 语义（只比较、不多加）、
  tools/scripts/docs/gates、共享文件、真实库/备份、三个外来未跟踪文件。
- 跨端 LWW 合并语义（盘点 A7 那族）不在本卡；本卡只管 myday 排序列的进程内并发。
- 复现与验证都走 `manager.place_myday` 直调（不经 HTTP）—— HTTP 那条路
  （`thread_local` 每线程一连接）结构相同；`unit_of_work` 路径上 core 的 `rollback()`
  语义与 db.py:167 明写的「有事就全撤」一致。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G109"]
id = "T-G109"
title = "myday 拖拽无版本守卫：验证并发丢更新/重号（A8）成立，按主控裁定 ① 加乐观锁"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/myday版本守卫-T-G109.md",
  "text:src/timeflow/core/tasks/manager.py::AND version = ?",
  "test:test_myday_version_guard_line.py",
]
gaps = "**为什么有这张卡**：A8；wb-review-T-G79.md §3「只是怀疑，没验」。**做了什么**：屏障交错两线程各持独立连接直调 place_myday —— 复现成立（重号 {1,2,2,3,4} 与整段丢更新两形态）；按主控 §2.9 裁定 ① 落地乐观锁：UPDATE 加 AND version = ?、撞了重读重算重试一次、再撞抛 MydayConflictError（带原因）；另把整份调序计划原子化（半路撞守卫时逐行已提交的过期计划会把号列写花、重试拿脏快照 —— 探针实测逼出，rollback 整笔撤掉）。**反证（先红后绿）**：先红 1 failed（重号 {1,2,2,3,4}）→ 后绿 2 passed 且并发用例 10 连跑全绿；突变（删 AND version = ?）3 连跑全 FAILED，还原全绿；回归 25 passed、test_unit_of_work 11 passed、ruff 过。**边界（如实写）**：「报 409」只到 core 层 —— HTTP 映射要动 app.py（白名单外），映射未补前重试仍撞的路径经 HTTP 显 500，待主控定；跨端 LWW（A7）不在本卡；复现走 core 直调未走 HTTP；worktree 跑 pytest 需把本树 src 放 PYTHONPATH 最前（否则 editable 安装解析到主树、测的是主树的码）。**没动的**：tests/test_unit_of_work.py、三份既有 myday 测试断言、排序口径、reserved-rank 逻辑、version 语义、tools/**、真实库/备份、三个外来未跟踪文件。"
```
