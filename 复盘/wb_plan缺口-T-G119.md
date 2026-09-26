# 调度器补两个缺口（`T-G119` = 卡 032）

> 2026-09-26。这两条**不是想出来的**，是把 backlog 收敛成"待派队列"（T-G118）时**真撞出来的**。
> 一句话：**`workbacklog.toml` 叫队列，但调度器原先只能表达"一批互不相交的卡"** —— 名不副实。

## 1 两个缺口（真撞到的现场）

1. ★★ **`check` 忽略 `status`** —— 它把整份 backlog 当「**全部已排班**」。于是**已完成的卡**
   （`status = done`）仍与待派卡报「同一文件两个写者」：实测 `007↔024`（都碰 `tools/wb_dispatch.py`）、
   `009↔022`（都碰 `src/timeflow/core/tasks/manager.py`）。
   当时的"解法"是**把 11 张已完成的卡整块移出队列** —— 那是**绕过**，不是解决。
2. ★★ **只要 `files` 相交就一律拒单，`depends` 救不了** —— 于是**装不下「队列里有同域串行」**
   这种**正常情形**（例：`024` 与 `029` 都要改 `tools/wb_dispatch.py`，只能一张张往队列里放）。

## 2 改了什么（`tools/wb_plan.py`，10 处）

| 改动 | 语义 |
|---|---|
| 新增 `ACTIVE_STATUS = ("pending", "running")` + `_in_flight()` | "还在队列里"的定义，一处收口 |
| 新增 `dependency_path()`（含 `_reachable()`，传递、兜环） | 两卡之间有没有依赖路径（任一方向） |
| **`validate()` 的冲突类只判在队列里的卡** | ★ `done`/`failed` 占过的**文件与树已经释放** |
| **`validate()` 的 `files` 相交 = 相交 **且** 无依赖路径** | ★ 有路径 → `topo_layers()` 把它们分到不同层、`greedy_pack()` 又不跨层 → **不可能同批** |
| **`plan_batches()` 只排 `pending`/`running`** | backlog 是**队列**，`done` 是历史、不进批次 |
| `worktree_commands()` 同样只给待派卡建树 | 别给已完成的卡建树 |
| 新增只读子命令 **`stats`** | 一条命令看队列全貌（待派/其它/批数/最大一批/占用的树）——"少读"的精神 |
| `cmd_check()` **加一行**队列读数 | ★ **既有那行格式一个字没动**（主控的卡在照抄它） |

★ **字段类校验一条都没松**：`files` 为空 / 含受保护共享文件 / `depends` 指向不存在 / 成环 /
`risk`·`status` 取值非法 —— **`done` 的卡照样要过**（★「跳过冲突」**不是**「跳过校验」，
这条有专门用例钉着）。

## 3 反证（★ 判据必须有牙 —— 卡 §2.1/§2.2 都要求）

**丢二：两条突变检验（先改坏 → 应当红 → 精确还原）**

| 突变 | 结果 |
|---|---|
| ① 把「跳过 done」改回「全都算」（`active = list(cards)`） | ✅ **咬住了**：`test_done_cards_do_not_conflict_with_pending` FAILED |
| ② 把「有依赖路径就不算冲突」改回「一律拒单」（去掉 `and not dependency_path(...)`） | ✅ **咬住了**：`test_overlapping_cards_need_a_dependency_path` + `test_transitive_dependency_also_allows_overlap` FAILED |

还原后**逐字符一致**（脚本核对 `after == good`），50 条测试全绿。

**丢一：真机验证（用真 backlog，塞一张 `done` 的卡回去）**

```
（塞回前）[OK ] backlog 校验通过：2 张卡，无冲突 ／ [队列] 待派 2 张 / 其它 0 张
（塞回 007，done，与 024 同域 wb_dispatch.py）
         [OK ] backlog 校验通过：3 张卡，无冲突 ／ [队列] 待派 2 张 / 其它 1 张   ← ★ 当初正是这个组合被拒
（还原后）[OK ] backlog 校验通过：2 张卡，无冲突 ／ [队列] 待派 2 张 / 其它 0 张
```

`stats` 的真实输出：

```
[统计] 队列共 2 张：待派 2 / 其它（done/failed）0
[统计] 并发上限 2 → 1 批；最大一批 2 张
[统计] 待派占用的树：.wt/sparse、.wt/watchdog
```

## 4 边界（如实写）

- ★ **队列仍是"精简队列"**：这一条**没有把已完成的 11 张卡塞回 `workbacklog.toml`** ——
  那份文件的头注口径就是「只登记**没编过**的卡」，历史在 git 里。这一条保证的是
  **"若有人把 done 的卡登记进来，`check` 不再误报"**，不是"把历史塞回队列"。
- ★ **依赖必须真的存在**才能靠它分批：两卡同域但**没有** `depends` → **照样拒单**
  （那才是真冲突：没人定顺序）。
- ★ **`depends` 分批只在同层内不成立**：`topo_layers()` 用**最长路径**分层，所以 A→B→C 里
  A 与 C 同域也允许（C 在第 2 层）；但**同层内两卡同域且互相没有路径**仍会被 `greedy_pack()` 拆开
  （那是运行时的第二道防御，`validate` 已经先拦了）。
- ★ **`check` 既有输出格式保留**（`[OK ] backlog 校验通过：N 张卡，无冲突（基点 X）`）——
  队列读数**另起一行**，免得打碎照抄它的卡。
- **没动的**：`PROTECTED_FILES`、四个既有子命令名与输出格式、`tools/wb_dispatch.py`、
  `tools/wb_dash.py`、`scripts/**`、`src/**`、`docs/traceability.toml`、changelog、两张交接文档。
