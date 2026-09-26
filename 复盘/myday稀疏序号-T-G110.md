# myday 稀疏序号：真拖只写换位那一行（卡 022 · 台账号 `T-G110`）

## §1 为什么有这张卡

出处两处（照卡 022 §1）：盘点卡 S-1 的 A9（`gates/diag/盘点-20260926.md`）+
`docs/traceability.toml` `T-G86.gaps`（`复盘/幂等写库-T-G86.md` §3 66-69 行原话：
一次真拖仍把「排过号的那一截（头）」整截重排成 `1..m`，m 行 version 全抬 ——
「只写真换位的那一行」要把序号改成有间隙的 sparse index，「那是另一张卡的事」）。
本卡就是那张卡。

## §2 做了什么

裁定参数（照卡 §2.9，未动）：**首号 `1000`、步长 `1000`、插入取中点、间隙耗尽只对冲突
那一小段局部 renormalize 且不动 version、`_myday_reserved_ranks` 保留并协同、A7 跨端
断言并进本卡（库级）**。`storage/db.py` 一个字没动（INTEGER 装得下）。

`src/timeflow/core/tasks/manager.py` 改了四处（行号以本工作区为准）：

| 位置 | 内容 |
|---|---|
| `manager.py:1401-1405` | 新增裁定常量 `_MYDAY_RANK_FIRST = 1000` / `_MYDAY_RANK_STEP = 1000` |
| `manager.py:1407-1466` | 新增 `_fit_run(count, lo, hi, reserved)`：给连续 count 行在开区间 (lo, hi) 取一串严格递增的稀疏号 —— 两侧无界从首号按步长链；单侧有界按步长向外延伸；双侧有界取中点（多行按比例均分），撞 `reserved` 顺移避开；塞不下返回 `None`（= 间隙耗尽）。中点用整数地板除，`hi - lo >= 2` 时必然严格落在区间内（负数也一样，卡 §7.1 的坑） |
| `manager.py:1500-1521` | `_write_myday_rank` 加 `bump_version` 开关：renormalize 的重排行**只改数字、version 不抬**，但 `AND version = ?` 乐观锁守卫仍在 |
| `manager.py:1522-1641` | `_myday_rank_plan` 重写（**函数名与头/尾判定保留**，T-G86 的台账证据是片段式 `def _myday_rank_plan(`，未破坏）。头检测三条不变；头里的行分两类：**保留集** = 已带号、沿目标次序号值严格递增的最长一组（LIS）—— 保留集每多一行就少写一行；其余按连续段交给 `_fit_run` 定号，塞不下就把两侧最近的已带号邻居逐行拉进来重新拉开（局部 renormalize，拉到头必塞得下，永不全列重排） |

**写不写 version 的判据**：被写的行里 —— 第一次拿号的行、显示位置真变了的行 = 真改动，
照常 `version + 1`；位置没变、只被重排拉开间隙的行 = 顺序语义没变，**不抬 version**
（卡 §2.9 裁定）。这同时把「非换位行 version 白涨」压到最小。

**T-G98 协同**：`_myday_reserved_ranks` 原样保留（精确相等判定）；`_fit_run` 所有取号
分支都绕开 `reserved`。★ 保留集（LIS）并列时取**靠后收尾**的那条链 —— 让真换位的行
重取新号、没动的行一个字节不动；没有这条 tie-break，`test_a_visible_renumber…` 的现场
里 B3 会保住旧号、T-G98 护栏在稀疏空间里就再也行使不到（突变 ① 依赖它，见 §5）。

## §3 先红后绿：新旧实现对照读数（真机探针，同一场景同一读法）

场景：五条任务（截止日定序 甲乙丙丁戊），①把「戊」拖到「甲」前；②再把「丁」拖到「乙」前。
探针动作前后各取一次 `{title: (myday_rank, version)}` 直连库逐行比。

旧实现（提交 `bfaa3f6` 的代码）：

```
== [old] 真拖①：戊 → 甲 前
   写入行数 = 5 / 共 5 行
   甲: (None, 1) -> (2, 2)      乙: (None, 1) -> (3, 2)      丙: (None, 1) -> (4, 2)
   丁: (None, 1) -> (5, 2)      戊: (None, 1) -> (1, 2)
== [old] 真拖②：丁 → 乙 前
   写入行数 = 3 / 共 5 行
   乙: (3, 2) -> (4, 3)   丙: (4, 2) -> (5, 3)   丁: (5, 2) -> (3, 3)   ← 整截重排
```

新实现（本卡）：

```
== [new] 真拖①：戊 → 甲 前
   写入行数 = 5 / 共 5 行
   甲: (None, 1) -> (2000, 2)   乙: (None, 1) -> (3000, 2)   丙: (None, 1) -> (4000, 2)
   丁: (None, 1) -> (5000, 2)   戊: (None, 1) -> (1000, 2)   ← T-G86 头语义不变，值改稀疏
== [new] 真拖②：丁 → 乙 前
   写入行数 = 1 / 共 5 行
   丁: (5000, 2) -> (2500, 3)   ← 只写换位那一行，甲乙中点；其余四行一个字节没动
```

★ 真拖一次从「头里 m 行全写」变成「只写 1 行」。真拖①（从全 NULL 清单第一次拖）仍是
5 行 —— 那是 T-G86 头判定的既有语义（被拖过的行把中间行扫进头，见 §6 边界 3），本卡
不改头判定，只把取号改稀疏。

## §4 §2.10 的 7 处断言改写对照 + 自查 + 突变

### 4.1 七行对照表

| 文件:行 | 旧断言 | 新断言 | 保住的意图 |
|---|---|---|---|
| `test_myday_order_line.py:68` | `moved.json()["myday_rank"] == 1` | `is not None` 且 ≤ 场景内其余全部号 | 真换位才有号，且是最靠前的那个（P1） |
| `test_myday_order_line.py:160` | `…["myday_rank"] == 1` | `is not None` 且 < 甲 的号 | 真换了位置才有号、拿到最靠前的号（P1） |
| `test_myday_idempotence_line.py:151` | `_rank(丁) == 2` | `is not None` 且 甲 < 丁 | 丁 拿到号、排在甲后面（P1+P2） |
| `test_myday_idempotence_line.py:177` | `_rank(丁) == 3` | 甲 < 丁 < 乙 | 丁 的号落在两邻之间（P2，稀疏取号的本质） |
| `test_myday_rank_line.py:157` | `B2==1 and B3==3` | 三条有号、互不相同、B2<B1<B3，并把 B2 的号存进 `b2_before` | 摆好现场（P1'） |
| `test_myday_rank_line.py:166` | `_rank(B3) == 2` | `is not None` 且 `!= _rank(B2)` | 可见条目不撞隐藏条目的号（P3） |
| `test_myday_rank_line.py:167` | `_rank(B2) == 1` | `_rank(B2) == b2_before` | 非排序动作没动它（P4） |

★ 两处偏离裁定字面（都是字面不可满足，详见 §6 边界 1/2）：#2 的「顺手补 甲/乙 is None」
改成了「丙 < 甲」；#3 的「=已分配号的最小值」改成了「甲 < 丁」。P5（`_order` 次序断言）
一处没动。

### 4.2 §2.10.3 两条自查（原始输出）

```
$ grep -nE 'myday_rank.*==\s*[0-9]|_rank\(.*\)\s*==\s*[0-9]' tests/test_myday*.py
（无任何命中，exit=1）
$ git diff --stat
 tests/test_myday_idempotence_line.py |   7 +-
 tests/test_myday_order_line.py       |  15 ++-
 tests/test_myday_rank_line.py        |  12 +-
（逐行看过：三份文件的改动只落在上表 7 处，其余行一个字没碰）
```

三份测试文件的完整 diff（`git -c core.quotepath=false diff -U2 --` 摘录，7 处之外无改动）：

```diff
--- a/tests/test_myday_idempotence_line.py
-    assert _rank(client, ids["丁"]) == 2, "真换了位置的那条要拿到新号"
+    rank_ding = _rank(client, ids["丁"])
+    assert rank_ding is not None, "真换了位置的那条要拿到新号"
+    assert _rank(client, ids["甲"]) < rank_ding, "丁 的号要排在甲后面（相对判据，不钉具体值）"
-    assert _rank(client, ids["丁"]) == 3, "拖过去的那条要拿到新号"
+    assert _rank(client, ids["甲"]) < _rank(client, ids["丁"]) < _rank(client, ids["乙"]), \
+        "丁 的号要落在甲与乙之间（稀疏取号的本质，相对判据）"
--- a/tests/test_myday_order_line.py
-    assert moved.json()["myday_rank"] == 1, "拖到最前面 → 序号 1"
+    moved_rank = moved.json()["myday_rank"]
+    other_ranks = [ … 四行取其余行的号 … ]
+    assert moved_rank is not None, "拖到最前面 → 真换位的那条要拿到号"
+    assert all(r is None or moved_rank <= r for r in other_ranks), …
-    assert client.get(f"/api/tasks/{last}").json()["myday_rank"] == 1, "真换了位置才有号"
+    rank_bing = client.get(f"/api/tasks/{last}").json()["myday_rank"]
+    assert rank_bing is not None, "真换了位置才有号"
+    assert rank_bing < client.get(f"/api/tasks/{first}").json()["myday_rank"], …
--- a/tests/test_myday_rank_line.py
-    assert _snap(path)[ids["B2"]][0] == 1 and _snap(path)[ids["B3"]][0] == 3
+    ranks_setup = {t: _snap(path)[tid][0] for t, tid in ids.items()}
+    assert all(r is not None for r in ranks_setup.values()), …
+    assert len(set(ranks_setup.values())) == 3, …
+    assert ranks_setup["B2"] < ranks_setup["B1"] < ranks_setup["B3"], …
+    b2_before = ranks_setup["B2"]
-    assert _rank(client, ids["B3"]) == 2, …
-    assert _rank(client, ids["B2"]) == 1, …
+    assert _rank(client, ids["B3"]) is not None and _rank(client, ids["B3"]) != _rank(client, ids["B2"]), …
+    assert _rank(client, ids["B2"]) == b2_before, …
```

### 4.3 §2.10.4 三条突变（各：改坏 → 红 → 还原 → 全绿）

```
突变① 关掉 _myday_reserved_ranks（return set()）：
  pytest tests/test_myday_rank_line.py::test_a_visible_renumber_never_collides_with_a_hidden_rank
  → exit=1  AssertionError: 今天清单里出现了重号：[2000, 3000, 2000]
  还原后该文件全绿。

突变② 改坏「回可见态清号」（update_task 的 hidden→visible 分支改 pass）：
  pytest tests/test_myday_rank_line.py::test_uncompleting_goes_last_not_back_to_the_old_slot
  → exit=1  AssertionError: 撤销完成要排最后，不许幽灵归位到旧号的位置
  还原后该文件全绿。

突变③ 稀疏取号改回整截 1..m 重排（保留集清空 + _fit_run 忽略间隙返回 1..count）：
  pytest tests/test_myday_sparse_line.py::test_a_real_drag_writes_only_the_moved_row
  → exit=1  AssertionError: 真拖只许写换位那一行，实际写了：['丁', '丙', '乙']
  还原后四份测试文件 28 passed。
```

## §5 轻门与测试汇总

```
ruff（6 份文件）           → All checks passed!
pytest 5 份测试文件 --no-cov → 30 passed（sparse 5 + order 12 + idempotence 6 + rank 5
                              + version_guard 2）
```

### §4.4 裁定 V2：第 8/9 处对照（`tests/test_myday_version_guard_line.py`，主控有限开白）

| 文件:行 | 旧断言 | 新断言 | 保住的意图 |
|---|---|---|---|
| `test_myday_version_guard_line.py:94` | `sorted(ranks) == [1, 2, 3, 4, 5]` | 五条都有号（`len(ranks) == 5` + 逐条 `is not None`）、`len(set) == len`、按清单次序逐对 `a < b` 严格递增（丁戊丙甲乙） | 原意图「五条都有号、互不相同、号按清单次序递增」，不钉字面值 |
| `test_myday_version_guard_line.py:152` | `sorted(ranks) == [1, 2, 3, 4, 5]` | 同上（`snap` 版；「互不相同」由紧邻的既有 `:151` 断言承担，本行不重复） | 同上（并发交错之后） |

★ 两处都**没有**换成 `[1000,2000,…]` 这类换个写法的写死值；该文件除这 2 处外一行未碰
（乐观锁 / 丢更新 / 幽灵归位断言原样）。

### §4.5 突变④（裁定 V2 §2：改松新判据 → 用例必须红）

改松态 = 两处新判据只留「五条都有号」（`len(ranks) == 5 and all(is not None)`，去掉
互不相同与递增）；同时把实现改坏回 **A8 原病**（去乐观锁 + 保留集清空 + 稠密 1..m 重排）：

```
pytest tests/test_myday_version_guard_line.py --no-cov -q     （改松态 + 坏实现）
→ exit=1（1 failed）
E  AssertionError: 两次移动都生效的串行正解（对照用例已钉）；实际：
   ['丁', '戊', '甲', '乙', '丙'] / {…: (3, 4), …: (4, 4), …: (5, 4), …: (1, 3), …: (2, 3)}
E  assert ['丁', '戊', '甲', '乙', '丙'] == ['丁', '戊', '丙', '甲', '乙']
   （follower 的过期计划把「丙 → 甲前」整段盖掉 = 丢更新，version 被写花到 4）
```

还原（完整相对判据 + 正确实现）：

```
pytest tests/test_myday_version_guard_line.py --no-cov -q     （还原态）
→ exit=0  ..  [100%]   （2 passed）
```

★ 如实说明：改松态下先红的是**既有**断言（`:153` 顺序 / `:151` 不重号）——「只留
is not None」的松判据本身抓不住丢更新（rank 全非空、还互异）；新判据里真正新增的牙是
「互不相同 + 清单次序递增」，与既有断言互为补集。还原后五份文件 30 passed。

## §6 边界（如实写，不假装）

1. **#2 的「顺手补 甲/乙 is None」没有采纳（字面不可满足）**：该场景（丙 拖到最前）在
   T-G86 头判定下会把 甲/乙 扫进头、拿到号 —— **旧代码今天就是如此**（丙=1、甲=2、
   乙=3；`test_myday_order_line.py` 那句 docstring「甲/乙 仍是 NULL」在今天就是错的，
   只是没有断言戳穿它）。稀疏化之后同样 甲=2000、乙=3000。我改成了相对判据
   「丙 < 甲 且 丙 的号存在」。★ 若主控坚持 is None，需要把头判定放掉「位置没变」条件
   （改成按 NULL 相对次序）—— 但那会让 `test_myday_idempotence_line.py:174-176`
   （甲 的号与位置都没变）与 #4 的 P2（乙 必须有号）双双失效，三处要一起动。**待主控裁定。**
2. **#3 的「= 已分配号的最小值」同样字面不可满足**：该场景 `_order` 要求 甲 < 丁（P5
   断言不动），丁 不可能拿到最小号。改成 `is not None` + `甲 < 丁`，意图（真换位拿到号）
   不变。
3. **T-G86 头判定原样保留**（含「夹在中间的行会被冻结」）：从全 NULL 清单的第一次真拖
   仍写 m 行（值改稀疏）；一旦全列有号，之后的真拖只写换位行 —— 卡标题的承诺在
   「已排过序的清单」上成立。放掉头判定的位置条件是另一族改动（见边界 1），本卡未做。
4. ~~**`version_guard`（卡 021 的 `tests/test_myday_version_guard_line.py`，白名单外）
   有 2 处必红**~~ **已由主控裁定 V2 处置**（`gates/diag/卡022-裁定V2-版本守卫判定.md`）：
   有限开白把 `:94`/`:152` 两处稠密号段断言改为相对判据（§4.4），突变④验过牙口（§4.5）。
   该文件其余行（乐观锁 / 丢更新 / 幽灵归位断言）一行未碰。
5. **renormalize 不动 version 与 `test_a_real_drag_only_bumps…:214`（变号必抬 version）
   在判据上互斥**：现有用例没有把两者放进同一场景（已逐场景核对），`test_myday_sparse_line.py`
   对 renorm 行只断言 version 不变。若未来有场景同时踩两者，需要主控定优先级。
6. **间隙耗尽路径已真触发**（`test_gap_exhaustion_renormalizes…`：连续中点插入 10 次后
   逼到相邻，renorm 签名 = 旧行变号而 version 不动；另有旧版稠密号 1、2 插入场景
   `test_inserting_into_a_legacy_dense_gap_still_renormalizes`）。
7. A7 跨端断言按裁定**只做库级**（两条连接交错），未引真网络/真客户端；没碰同步层文件。

## §7 没动的

排序口径与读函数（`_MYDAY_ORDER_BY` / `myday_tasks`）、NULL 语义、三份既有 myday 测试的
非点名断言、`tests/test_unit_of_work.py`、`tests/test_myday_version_guard_line.py`
（除裁定 V2 开白的那 2 处外一行未碰）、`storage/db.py`、`tools/**`、`scripts/**`、
`docs/**`、`gates/**`、共享文件（台账/changelog/两份交接文档）、真实库与真实备份目录、
三个外来未跟踪文件。

## §8 mypy 修复（集成者 I-4 退回：全量门禁 mypy strict 8 errors → 0）

**前**：`python -X utf8 -m mypy src/` → `Found 8 errors in 1 file (checked 56 source files)`
（6 个位置，全在本卡新增的稀疏取号代码里）。**后**：`Success: no issues found in 56
source files`（0 error）。★ 只修类型、零行为变化；没用一处 `# type: ignore`（用的是
`assert … is not None` 收窄 + 局部变量改名，`assert x is not None` 与 src 既有惯例一致：
`notify.py:273`、`review.py:401`）。逐处收窄：

| 位置 | mypy 报错 | 收窄方式 |
|---|---|---|
| `_fit_run` 的 `lo is None` 分支 | `upper - …`：`upper`（= `hi`）是 `int \| None` | 加 `assert hi is not None`（「两侧都无界」已被上一分支 return 挡掉，mypy 不传播否定合取的收窄） |
| `_myday_rank_plan` LIS 段 | `prev[k] = m` / `prev[end]`：`prev` 是 `int \| None` | **改名**：LIS 回溯指针 `prev` → `prev_at` —— 它**遮蔽**了头检测里那个 `prev: int \| None`（类型错误的真正根因） |
| `_myday_rank_plan` LIS 段 | `ranked[m][1] < ranked[k][1]`：元素 `int \| None` | 构建 `ranked` 改为显式循环 + 局部变量 `rank_of` 收窄后 append，显式标注 `list[tuple[str, int]]`（第一版用 `int(…)` 强转被 mypy 拒：`int()` 不收 `None`） |
| `assign_span` 耗尽回退分支 | `zip` 第 2 参 `list[int] \| None` | 该分支两侧都无界，`_fit_run` 契约上必给出一串号 → 加 `assert vals is not None`（收窄 + 把契约写成断言） |

★ 行为等价性：改动只有 `assert`（不变量，正常路径永不触发）、变量改名、推导式改循环
——四份突变后全绿的测试原样重跑仍全绿（见下）。

**修后轻门**：

```
python -X utf8 -m mypy src/                       → Success: no issues found in 56 source files
python -X utf8 -m ruff check …6 份文件             → All checks passed!
python -X utf8 -m pytest tests/test_myday_*.py
  --no-cov -q                                     → exit=0，73 个用例全过（sparse 5 + order 12
                                                     + idempotence 6 + rank 5 + version_guard 2
                                                     + move_line 43），无任何 F/E
```

（注：主控提到的 `test_myday_conflict_409.py` 无同名文件 —— 409/冲突覆盖在
`tests/test_myday_version_guard_line.py`，已跑、2 passed。）

**台账 `text:` 指针核对**：本节改动只动 `_fit_run` 体内一行插入、LIS 段改名、`assign_span`
一行插入 —— 台账条目的 `text:` 指针 `::_MYDAY_RANK_FIRST = 1000` 与 `::def _fit_run(`
字面**仍然命中**（都指向未被本节触碰的行），`test:` / `file:` 指针不变。**无需更新指针。**

## 台账条目（供集成者粘贴）

```toml
[entries."T-G110"]
id = "T-G110"
title = "myday 稀疏序号：真拖只写换位那一行（T-G86.gaps 说的「另一张卡」）—— 有间隙取号 + 间隙耗尽策略（主控定参）"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/myday稀疏序号-T-G110.md",
  "text:src/timeflow/core/tasks/manager.py::_MYDAY_RANK_FIRST = 1000",
  "text:src/timeflow/core/tasks/manager.py::def _fit_run(",
  "test:test_myday_sparse_line.py",
]
gaps = "**为什么有这张卡**：盘点 A9；T-G86.gaps / 复盘/幂等写库-T-G86.md §3（66-69 行）「那是另一张卡的事」。**做了什么**：稀疏参数照主控裁定（首号 1000、步长 1000、插入取中点、耗尽只局部 renormalize 且不动 version、reserved 保留协同、A7 库级断言并进）；真拖一次从「头里 m 行全写」变成「只写 1 行」的实测对照见复盘 §3（旧 3 行 → 新 1 行，附原始读数）。**反证（先红后绿）**：三条突变（关 reserved / 不清号 / 改回整截 1..m）各自改坏→红→还原→绿，原始输出贴复盘 §4.3；新用例 test_myday_sparse_line.py 钉住写入行数与取号口径。**边界（如实写）**：耗尽路径已真触发（稀疏中点收敛 + 旧版稠密号两场景）；#2 的「甲/乙 is None」与 #3 的「=最小值」字面不可满足、改相对判据（复盘 §6.1/6.2，待主控追认）；T-G86 头判定原样保留、全 NULL 首拖仍写 m 行（§6.3）；version_guard 两处稠密号段断言经裁定 V2 有限开白改相对判据、突变④验过牙口（§4.4/§4.5）；renorm 不动 version 与变号必抬 version 的判据不可同场景混用（§6.5）。**没动的**：排序口径与读函数、NULL 语义、三份既有测试的非点名断言、test_unit_of_work.py、storage/db.py、tools/scripts/docs/gates、共享文件（台账/changelog 由集成者收口）、真实库/备份、三个外来未跟踪文件。version_guard 的 :94/:152 两处经主控裁定 V2 有限开白改为相对判据（复盘 §4.4/§4.5），其余行未碰。"
```
