# T-G98 · My Day 序号「整列写回」的根因：隐藏条目的旧号 vs 可见条目的新号

> **卡**：并发作者卡 009（`gates/diag/卡009-myday根因.md`）。台账号 `T-G98`。
> **输入**：卡 001 的对抗性复核 `gates/diag/wb-review-T-G79.md`（边界 B / 边界 C，**完整读过**）+
> `复盘/幂等写库-T-G86.md`（T-G86 修的是同一片的「没动也写库」那半）。
> **一句话**：完成 / 取消 / 待定 / 归档 / 已删的条目被 `myday_tasks()` 滤掉、`myday_rank` 却留着，
> 而规整只按**可见**条目编号 → ①「撤销完成」回归的那条与当前可见条目**撞号**；② 它**插回旧号的位置**
> （幽灵归位）。这一卡修「撞号」，并把「非排序动作不许动序号列」「排序动作只写真的换了号的行」钉成断言。
>
> 分支 `(detached)`（`1969b46` T-G94）。改的文件见 §6。

---

## §1 数据流：真正参与「读整列 → 算 → 整列写回」的函数（读代码 + 探针确认，不是猜）

```
                   ┌────────────────────────── 读 ──────────────────────────┐
myday_tasks(conn)  ── SELECT * FROM tasks WHERE is_myday=1
                       AND status NOT IN (完成,取消,待定,归档,已删)     ← ★ 隐藏条目被滤掉
                       ORDER BY myday_rank IS NULL, myday_rank, <老口径>  （_MYDAY_ORDER_BY）
_myday_sequence(conn) ── 只读出这份顺序（T-G86 之后**只读**，不再写整列）

                   ┌────────────────────── 算 + 写回 ───────────────────────┐
place_myday(task_id, before_id)   ← 拖拽落点（before=None = 末尾；拖自己=早退）
move_myday(task_id, up|down)      ← 键盘 ↑↓（已在头/尾=早退）
        │  items = _myday_sequence(conn)
        │  order = 把 task 挪到落点算出的新序列
        └─► _apply_myday_order(conn, items, order)
                 │  order == [it.id for it in items] ?  → 一个字节都不写（T-G86）
                 └─► _myday_rank_plan(items, order[, reserved])  → {id: 新号}
                        └─► _write_myday_rank(conn, id, rank)  → UPDATE … SET myday_rank=?, version=version+1

                   ┌──────────────── 隐藏 / 显现（走 update_task）──────────────┐
完成 complete_task / 取消·待定 park / 归档 archive / 已删 delete
        └─► update_task(conn, id, status=…)
进今天 update_task(is_myday=True)   → myday_rank 保持 NULL（新来的排最后）
离今天 update_task(is_myday=False)  → myday_rank = NULL（不留幽灵序号）
```

**结论（如实写）**：真正「读整列 → 算 → 整列写回」的只有 `place_myday` / `move_myday` 两条路
（经 `_myday_sequence` → `_apply_myday_order` → `_myday_rank_plan` → `_write_myday_rank`）。
**完成 / 取消 / 待定 / 归档 / 已删这些隐藏路径本身并不写 `myday_rank`** —— 它们只是让
`myday_tasks()` 少看见一条，而那条的 `myday_rank` **原封不动**。撞号是「**隐藏条目留号**」与
「**规整只按可见条目编号**」两件事**相遇**时发生的，不是隐藏动作自己写的。

## §2 根因与两个症状

根因一句话：**`myday_rank` 是一列「可见清单的显式顺序」，但号是画在整张 `is_myday=1` 表上的**——
隐藏条目占着号不放，可见条目又从 `1` 起重新编号，两个空间一重叠就撞。

- **症状 B（重号 / 幽灵归位）**：`myday_tasks()` 按五个状态过滤（完成 / 取消 / 待定 / 归档 / 已删），
  却不动被滤掉那行的 `myday_rank`；`_myday_rank_plan` 又把可见条目编成 `1..m`。于是——
  ① 一条藏起来的条目留着旧号，可见条目拿到同一个号 → **重号**（今天清单的号不是两两不同的）；
  ② 「撤销完成」时那条带着旧号回来，靠 `_MYDAY_ORDER_BY` 的「并列按老口径兜底」**排到旧号的位置**
  （不是排最后）—— 看起来像「顺序略微不对」，其实是数据结构坏了（没有 UNIQUE 约束、也没有断言兜着）。
- **症状 C（真拖整列抬 `version` → 跨端 LWW 翻顺序）**：`version` 是跨端合并（`syncpack` 的
  `newer_is_win`）的首选键。历史上一拖就整列 `version +1`（且 `updated_at` 故意不变），于是别的端
  一次**真实内容改动**会输给这些空写被整条丢掉。这半在 **T-G86** 已经收掉（顺序真变才写、只写排过号
  的那一截）；本卡把「**非排序动作不许动序号列**」「**排序动作只写真的换了号的行**」钉成断言。

### 2.1 复核报告的边界 B 现场（真复现，改之前）

探针（临时库、领域层直调）在**未改的实现**下量到：

```
摆好之后 : [('B2',1), ('B1',2), ('B3',3)]
完成 B2 后: [('B2','完成',1), ('B1',2), ('B3',3)]     ← B2 留着号 1
再拖一次  : [('B2',1), ('B1',3), ('B3',1)]            ← ★ B3 也拿到 1：重号
可见顺序  : ['B3','B1']  rank=[1,2]
所有号    : B2=1,B1=2,B3=1  → 有重号? True
撤销完成  : ['B2','B3','B1']                          ← ★ B2 幽灵归位到第 1 位
```

## §3 修法（只动 `core/tasks/manager.py`，不引 schema 迁移、不改表结构）

| # | 改哪 | 改成什么 |
|---|---|---|
| ① | `_myday_reserved_ranks(conn, items)`（**新增**） | 读出今天清单里**被隐藏条目占着**的号（`is_myday=1 AND myday_rank IS NOT NULL` 里、**不在**可见 `items` 里的那些）。 |
| ② | `_myday_rank_plan(items, order, reserved)` | 头里的行仍按次序拿号，但**跳过 `reserved`**（被隐藏条目占着的号）—— 可见条目的新号从此不会和隐藏条目的旧号撞。 |
| ③ | `_apply_myday_order` | 先算 `reserved`，再交给 `_myday_rank_plan`。 |
| ④ | `update_task` | 从「被藏起来」回到「看得见」（撤销完成 / 取回待定·取消 / 取消归档·撤销删除）→ **清号**（`myday_rank = NULL`）。**进入**隐藏态**不清号**。 |
| ⑤ | `MYDAY_HIDDEN_STATUSES` 常量 | 把 `(完成, 取消, 待定, 归档, 已删)` 抽出来，`myday_tasks` 与 `update_task` 共用一份，免得两处口径漂。 |

### 3.1 为什么是「隐藏条目留号 + 可见条目绕开 + 撤销完成排最后」

三个受限条件逼出了这个组合：

1. **「完成 / 取消」不许动序号列**（卡 §2.3，也是症状 C 的正题）：`myday_rank` 在同步包里是普通字段
   （`src/web/offline.js` 的字段白名单里有它），一次非排序动作若改它，就会跟着 `version` 同步到别的端。
   → 所以隐藏时**不能清号**（清了就是「完成」动了序号列）。
2. **隐藏旧号与可见新号不许撞**（卡 §2.2）：既然隐藏条目留着号，可见条目取号就必须**绕开**它
   （这正是卡 §2.2 举的第二个例子「让可见序号从一个不与隐藏号冲突的空间取」）。→ ②。
3. **撤销完成回到正确位置**（卡 §2.2 让我二选一）：我选 **「排最后」**。理由：与产品既有规矩一致 ——
   「移出今天 → 清号 → 再加回来**排最后**」（`test_myday_order_line.py::test_leaving_today_
   clears_the_rank_and_coming_back_goes_last`）；卡 §1 也把「插回旧位置」列为**症状**、把「排到最后」
   当作期望。号在隐藏期间只是**占位**（防撞号），回来时**还掉**、按老口径排到末尾。→ ④。

★ 所以：**进入**隐藏态一个字不写（守住 §2.3），**回来**时清号并把位置让到最后（守住 §2.2）。

## §4 ★ 反证：先红后绿（贴的是哪一种红）

新增 `tests/test_myday_rank_line.py`（**5 条**）。判据是**数出来的**：直连库取
`{id: (myday_rank, version)}` 前后逐行比（与 `test_myday_idempotence_line.py` 同一读法）。

**改实现之前（红）** —— 只把 `manager.py` 还原成 `HEAD`（原实现），同一批用例：

```
$ PYTHONPATH="$PWD/src:$PWD/tools/sandbox_shim" python -X utf8 -m pytest \
    tests/test_myday_rank_line.py tests/test_myday_order_line.py tests/test_myday_idempotence_line.py \
    --no-cov -p no:cacheprovider
FAILED tests/test_myday_rank_line.py::test_a_visible_renumber_never_collides_with_a_hidden_rank
FAILED tests/test_myday_rank_line.py::test_uncompleting_goes_last_not_back_to_the_old_slot
2 failed, 21 passed
   ├─ AssertionError: 今天清单里出现了重号：[1, 2, 1]        （assert 3 == 2）
   └─ AssertionError: 撤销完成要排最后，不许幽灵归位到旧号的位置
      assert ['B2', 'B3', 'B1'] == ['B3', 'B1', 'B2']
```

**改完之后（绿）**：

```
$ PYTHONPATH="$PWD/src:$PWD/tools/sandbox_shim" python -X utf8 -m pytest \
    tests/test_myday_rank_line.py tests/test_myday_order_line.py tests/test_myday_idempotence_line.py \
    --no-cov -p no:cacheprovider
23 passed          （5 新 + 12 test_myday_order_line + 6 test_myday_idempotence_line）
```

**顺带跑的（与本改动相邻、怕误伤）**：

```
$ PYTHONPATH="$PWD/src:$PWD/tools/sandbox_shim" python -X utf8 -m pytest \
    tests/test_task_status_line.py tests/test_task_line.py tests/test_tasks.py tests/test_api.py \
    tests/test_sync_pack_line.py tests/test_repeat_rhythm_line.py tests/test_offline_phone_line.py \
    tests/test_unit_of_work.py --no-cov -p no:cacheprovider
108 passed
```

**ruff**：`python -X utf8 -m ruff check` → `All checks passed!`（全仓，不只这两个文件）。

## §5 边界（如实写，含没复现出来的症状）

- ★ **症状 C 的「真拖把 `version` +2」我没能复现成红** —— 那半在 **T-G86** 已经收掉了。改之前我量到的是
  **+1**（只写真的换了号的行），不是 +2；`place_myday` 里 `_myday_sequence` 早已只读、没有第二遍写。
  所以我给 C 写的三条断言（非排序动作不动序号列、排序动作只写换了号的行）在当前实现下**本来就是绿的**
  —— 它们是**回归守卫**，不是本卡跑红的证据。**照实说：C 我没能跑红。**
  本卡真正跑红的是 B 的两条（§4）。
- **没做 sparse index**（卡 §2.1 明说不归本卡）：一次**真拖**仍是把「排过号的那一截（头）」整截重排成
  `1..m`（跳过 reserved），只是头里号没变的行会跳过不写。要做到「只写换位的那一行」得把号改成**有间隙**
  的（sparse index）—— 那是 **A9** 那张卡的事。
- **不是 UNIQUE 约束**：本卡只在**应用层**保证「可见条目取号绕开隐藏号」，没有加 DB 约束（卡 §2.4：
  不改表结构）。若**历史遗留数据**里已经有两行同号（本卡之前产生的），本卡**不负责清洗**（不引迁移）。
- **只 `is_myday=1` 的隐藏条目参与"占号"**：号是 My Day 专属列，非今天条目的 `myday_rank` 本应为 NULL
  （离今天会清）。`_myday_reserved_ranks` 只按 `is_myday=1` 统计 —— 域内自洽。
- **撤销完成 → 排最后**是 T-G98 **选定**的行为（卡 §2.2 允许二选一，见 §3.1 理由）；不是「回到原位」。
- **没验的**：真浏览器里的真拖拽、行为流 `M`、全量门禁（卡 §0.3 明令不跑，只跑轻门）；真手机 / 真离线队列。

## §6 ★ 环境陷阱（会咬下一个在 **worktree** 里干活的工人，务必知会主控）

`pyproject` 没有 `pythonpath` 配置，`timeflow` 是靠一份 **editable 安装**（`site-packages/
__editable__.timeflow-0.1.0.pth`）被解析的 —— 而那份 `.pth` 里写死的路径是
**主树** `D:/repo/engineering\src`，**不是**本 worktree `.wt\core\src`。

后果：在 worktree 里照卡 §0.6 那样敲 `PYTHONPATH="$PWD\tools\sandbox_shim"; pytest …`，
**import 到的是主树的 `manager.py`（原实现），你的改动根本没被跑到** —— 绿是假绿、红是假红。
本次实测（`python -c "import timeflow.core.tasks.manager as m; print(m.__file__)"`）：

```
不加 src  →  D:/repo/engineering\src\timeflow\core\tasks\manager.py   ← 主树
加 $PWD/src → D:/repo/engineering\.wt\core\src\timeflow\core\tasks\manager.py  ← 本树
```

**本卡的对策**：所有命令都写成 `PYTHONPATH="$PWD/src:$PWD/tools/sandbox_shim"`（把本树 src 顶到最前）。
**建议主控**：要么在 worktree 里重新 `pip install -e .`，要么把这条写进下一张卡的必读 —— 否则工人
「改完自己验」验的是**别人树**的代码。

## §7 一次并发事故（如实记录，未污染任何别人的东西）

本卡一度用 `git stash push -- src/…/manager.py` 制造"先红"的现场，随后 `git stash pop` 时
**撞上了并发**：另一张卡（分支 `line/impl-v1`，T-G95）在**我 push 之后、pop 之前**往**共享的 `.git`**
里也 push 了一条 stash，于是 `pop` 弹出的是**它的** `tools/wb_dispatch.py` stash（不是我的），
在**我的工作区**里产生了一处冲突。处置：

- `git restore --source=HEAD --staged --worktree -- tools/wb_dispatch.py` 把工作区**还原成 HEAD**；
  **它的 stash 仍在 `stash@{0}`**（pop 冲突时不会丢弃）——**一个字没动**；
- 从**我自己的** `stash@{1}` 里只取 `manager.py` 恢复，核对与改前备份**逐字节相同**，再 `git stash drop
  stash@{1}`（只丢我自己的），`stash list` 现在只剩它的那条。

**教训**：**在共享 `.git` 的 worktree 里不要用 `git stash`**（stash 是仓库级、不是 worktree 级）。
后续"先红后绿"改用「`cp` 备份 + `git show HEAD:path > path`」的纯文件方式，不再碰 stash。

## §8 台账条目（供集成者粘贴）

```toml
[entries."T-G98"]
id = "T-G98"
title = "My Day 序号「整列写回」的根因：隐藏条目旧号与可见条目撞号 / 撤销完成幽灵归位 —— 可见条目取号绕开被隐藏条目占着的号 + 回可见态清号排最后 + 非排序动作不动序号列的断言（5 条 pytest）"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/myday序号根因-T-G98.md",
  "text:src/timeflow/core/tasks/manager.py::def _myday_reserved_ranks(conn: sqlite3.Connection, items: list[Task]) -> set[int]:",
  "text:src/timeflow/core/tasks/manager.py::MYDAY_HIDDEN_STATUSES = (STATUS_DONE, *PARKED_STATUSES, *HIDDEN_STATUSES)",
  "text:src/timeflow/core/tasks/manager.py::reserved = _myday_reserved_ranks(conn, items)",
  "text:src/timeflow/core/tasks/manager.py::and before.status in MYDAY_HIDDEN_STATUSES",
  "test:test_myday_rank_line.py",
]
gaps = "**为什么有这张卡**：卡 001 的独立复核（`gates/diag/wb-review-T-G79.md` 边界 B / 边界 C）＋`复盘/幂等写库-T-G86.md` 指出，T-G79 那片「读整列 → 算 → 整列写回」在 T-G86 修掉「没动也写库」之后，还长着另一半。**根因**：真正参与「读整列 → 算 → 整列写回」的只有 `place_myday` / `move_myday`（经 `_myday_sequence` → `_apply_myday_order` → `_myday_rank_plan` → `_write_myday_rank`）；完成 / 取消 / 待定 / 归档 / 已删这些隐藏路径本身**不写** `myday_rank`，它们只是让 `myday_tasks()` 少看见一条、而那条的号**原封不动**（`myday_tasks` 按五个状态过滤但不清号）。于是「隐藏条目留号」与「规整只按可见条目从 1 编号」相遇 → ① 一条藏起来的条目留着旧号、可见条目拿到同一个号 = **重号**（号不是两两不同的，没有 UNIQUE 也没断言兜着）；②「撤销完成」那条带旧号回来、靠并列兜底**插回旧号的位置**（幽灵归位），而不是排最后。**怎么修（只动 `src/timeflow/core/tasks/manager.py`，不引 schema 迁移、不改表结构）**：① 新增 `_myday_reserved_ranks(conn, items)` 读出被隐藏条目占着的号；② `_myday_rank_plan(items, order, reserved)` 里可见条目取号**跳过** reserved（卡 §2.2 的第二个例子「让可见序号从一个不与隐藏号冲突的空间取」）；③ `_apply_myday_order` 先算 reserved；④ `update_task` 里「从隐藏态回到可见态」（撤销完成 / 取回待定·取消 / 取消归档·撤销删除）→ **清号**（`myday_rank=NULL`，排最后），**进入**隐藏态**不清号**；⑤ 抽 `MYDAY_HIDDEN_STATUSES` 常量给 `myday_tasks` 与 `update_task` 共用。**为什么这么选**：卡 §2.3 要求「完成 / 取消这类**非排序动作不许动序号列**」（`myday_rank` 是同步包里的普通字段、`version` 是跨端 LWW 首选键，乱写会把别的端的真改动顶掉）→ 隐藏时**不能清号**；既然留号，可见条目取号就必须绕开它（防撞）；撤销完成的落点卡 §2.2 允许二选一，选**排最后**，与「移出今天再加回来排最后」同一条产品规矩、也是卡 §1 把「插回旧位置」列为症状所指向的期望。**反证（先红后绿）**：新增 `tests/test_myday_rank_line.py` 5 条（判据=直连库取 `{id:(myday_rank,version)}` 前后逐行比）——把 `manager.py` 还原成 HEAD（原实现）跑：`2 failed, 21 passed`，红的正是 B 的两条（`今天清单里出现了重号：[1, 2, 1]` / `assert ['B2','B3','B1'] == ['B3','B1','B2']`），修完 `23 passed`。**边界（如实写）**：★ 症状 C 的「真拖 version +2」**没能跑红** —— 那半在 T-G86 已收掉，改前量到的是 +1（不是 +2），故给 C 写的三条断言（非排序动作不动序号列、排序动作只写换了号的行）本来即绿、是**回归守卫**；本卡只做「根因 + 断言」，**不做 sparse index**（真拖仍把头那截重排成跳过 reserved 的紧凑号，sparse 属 A9）；只做应用层绕号、**不加 UNIQUE**、**不清洗历史遗留的重号**（不引迁移）；只统计 `is_myday=1` 的隐藏条目占号。**没动的**：`_MYDAY_ORDER_BY` / `myday_tasks` 的排序口径、路由语义（`api/app.py`）、界面（`src/web/**`）、`move_doing`/`doing_rank`、跨端合并规则，全部一字未改。★ **环境陷阱**：worktree 里 editable 安装的 `.pth` 指向**主树** src，不显式 `PYTHONPATH=「$PWD/src:…」` 会 import 到主树的旧代码（详见复盘 §6）。"
```
