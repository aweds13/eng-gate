# 复盘 · 迁移漏档：版本号撒了谎（T-G9）

> 性质：**缺陷复盘**（怎么发现的 / 为什么会漏 / 修法 / 证据 / 教训）。
> 发现时间：2026-09-22，**开始做 AI 接口（T-G6）之前**顺手核了一遍现有库的 schema。
> 影响面：**用户本机那个真实库**（`data/timeflow.db`）。严重度：P0（升级会半途而废且不留痕）。

---

## 一、怎么发现的

准备给 AI 接口加 `created_by`（schema v16）时，我先看了一眼真实库现在停在哪一版 ——
结果发现它**不是**我以为的那样：

```
$ python -c "…PRAGMA table_info(tasks) / groups…"   # 只读打开 data/timeflow.db
库里的 schema_version = 12
  tasks.doing_rank:  ❌ no such column: doing_rank      ← v13（T-F1「进行中」）
  groups.parent_id:  ❌ no such column: parent_id       ← v14（T-F5 分组嵌套）
  groups 索引:       sqlite_autoindex_groups_1/2 (origin='u')  ← v15 的重建也没跑
```

也就是说：**已经上线的 v13/v14/v15 三档迁移，在这个库上从未生效**，而库里的版本号是 12
（还没被"升级"过）。再往下看代码，问题比"没跑过"更严重：

```python
def _upgrade(conn, current):
    ...
    if current < 13:
        _migrate_v13(conn)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))   # ← 直接写 15
```

`_upgrade` 的链**只写到 13**，`< 14` 与 `< 15` 两档**根本不存在**（v14/v15 只挂在 `_create_all`
——也就是"新建库"那条路上）。后果是：这个 v12 的库**下一次连接时**会

1. 跑 v13（加 `doing_rank`）✅、
2. **跳过** v14/v15 ❌、
3. 把版本号写成 **15** ❌ —— 从此 `_migrate` 看到 `current == SCHEMA_VERSION` 什么都不做。

于是这个库会**永久**缺 `groups.parent_id` 与 v15 的 groups 重建，而版本号显示"已是最新"。
表现就是分组嵌套 / 任务树（T-F5）和分组重名（T-F10）在真实数据上"莫名报 no such column"，
而且**没有任何东西提示你 schema 是坏的**。

## 二、为什么一直没被抓到（这一段才是重点）

| 检查 | 为什么抓不到 |
|---|---|
| 单测（757 条） | 全部跑在**新建的临时库**上 → 走 `_create_all` 那条路，结构永远是全的 |
| 台账的 `column:` 断言 | 它读的是 **`db.py` 源码文本**（找 `ALTER` / `_add_column_if_missing` 调用），源码里两档都在 → 断言成立 |
| 真机自检（LF-1 / web_live） | 用的也是**临时库** |
| 备份恢复 | 恢复路径只"写回内容"，结构仍按当前库算 |

**共同点：没有一条检查跑过"把一个老库升级上来"这件事。**这是"结构类缺陷"的典型盲区 ——
所有测试都从"最新结构"出发，于是"升级路径"本身从来没有被测过。

## 三、修法（两条一起做，缺一不可）

1. **补上版本链缺的两档**：`if current < 14` / `if current < 15`；并且把"写版本号"这件事从
   `_upgrade` 里**挪到 `_migrate`**（在结构补齐之后统一写）——免得再出现"结构没到位、版本号先到位"。
2. **结构补齐 `_ensure_schema()`：判据从"版本号"换成"结构在不在"**。
   v1~v3（建表）与 v6 起的加列/重建类迁移**每次连接都跑一遍**（全部幂等；成本就是几轮
   `PRAGMA table_info`），补上了就记一条 `schema_healed` 日志（**不静默**）。
   - 这一条同时救回"**已经被写成 15、但结构缺列**"的库 —— 光修版本链救不回来那种状态；
   - **数据回填（v4/v5）仍留在版本链里**：它们只该跑一次，而且比加列贵（要扫历史行）。
   - `schema_version` 的角色因此变成"**数据回填跑没跑过**的记录"，而不是"结构对不对"的判据 ——
     和项目一贯口径一致：**事实（列在不在）> 解读（版本号写着几）**。
3. 顺带给 v15 加了 `groups` 表存在性守卫（缺表的残缺库不再有可能撞 `no such table`）。

## 四、证据

- **单测 `tests/test_migration_heal_line.py`（14 条）**，其中三条是这次的核心：
  - `test_upgrade_from_every_version_matches_a_fresh_db`：**不变式** —— 从 v1~v15 每一版升上来的库，
    结构指纹必须与新建库**逐项相同**。这条是给"以后再加迁移"兜底的：谁再漏一档，这里就红；
  - `test_the_real_shape_v12_upgrades_and_the_features_actually_work`：造出用户库那个 v12 形状，
    升级后**功能真的能用**（`start_task` 写进 `doing_rank`、分组能嵌套、跨父能重名），**不只是列在了**；
  - `test_version_number_is_not_trusted_when_columns_are_missing`：版本号**谎报成 15** 也能自愈。
  另外覆盖：幂等（连两次结构指纹不变、数据条数不变）、缺 groups 的残缺库不炸、`schema_healed`
  日志内容、新建库**不**报"补齐"、恢复备份后 `db.migrate()` 同样补齐。
- **在用户真实库的副本上跑了一遍真实升级路径**（副本，原文件一个字节没动）：

  ```
  升级前: version=12 | doing_rank: ✗ | parent_id: ✗
  升级后: version=15 | doing_rank: ✓ | parent_id: ✓
  数据条数: tasks 8→8 | facts 31→31 | groups 1→1 | task_groups 0→0
  功能自证: list_tasks=2 | myday=1 | debt_groups=1 | list_groups=['0']（你那个库里的分组名就是 "0"）
  ```
  日志里出现一条 `schema_healed`（was_version=12、added 里有 `tasks.doing_rank` / `groups.parent_id`）。

## 五、边界与后续

1. **原库我没动**：修的是代码；你下次启动 app（或任何走 `db.connect` 的入口）时它会自己升上来，
   并且启动前本来就有自动备份（`data/*.bak-*`）。想先看一眼就启动后查 `schema_version` 与
   `PRAGMA table_info(groups)`。
2. **"结构补齐"不是万能的**：它只保证"声明过的表/列/索引都在"，**不修数据**。
   数据层面的迁移（回填、改值）仍然只能在版本链里做一次 —— 那类迁移写错了，靠结构补齐救不回来。
3. **still 需要一个"迁移链"的长期护栏**：这次补的 `test_upgrade_from_every_version_matches_a_fresh_db`
   是通用兜底；将来若出现"某档迁移需要中间数据状态"的复杂迁移，还得单独为它写升级测试。

## 六、教训

1. **"版本号"是记录，不是事实**：程序里凡是"用一个数字代表一件事已经做完"的地方，都要能
   （便宜地）验证那件事**真的做完了**。这次是 schema，下次可能是"已导出/已同步/已结算"。
2. **只测"最新状态"等于不测升级路径**：老库升级是**用户唯一真实走的那条路**（新库只有我测试时才建），
   却因为"测试都从新库开始"而完全没被覆盖。**不变式测试**（从每一版升上来 = 新建库）是这类
   路径最便宜的兜底。
3. **缺陷清单要往前排**：这一条是在准备新功能时"顺手核一眼"发现的。如果没核，T-G6 的
   `created_by`（v16）会照样加在上面，而你的库里同时缺三档 —— 越晚发现越难对齐。
