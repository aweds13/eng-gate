# 卡 E9 —— 队列补 `status` 行（11 块）+ 体检第 ⑧ 条放开全判

> 台账号 T-AG455 · 分区 E（CI 子系统）· 依赖 E1 · 来源：卡 E1 顺手发现的真实欠账

## 现在疼在哪（实测）

卡 E1 把 `--preflight` 的第 ⑧ 条（「队列卡块有 `status` 行」）**收窄成只判这一趟要落的那张卡**，
理由是队列里有 11 个卡块根本没有 `status` 行，全判会让本仓**永久红灯**：

```
B1, D1, D2, D3, D4, D5, D6, D7, D8, C1, C2     ← 11 块，`docs/workbacklog.toml`
```

后果：①`wb_land.flip_card_status()` 对这些卡**静默跳过**（已落却仍算 pending 的那种红我们踩过两次）；
②`wb_plan.py check` 只在被点名时才报；③体检的这条判据长期是**半瞎的**（只看一张卡）。

## 目标

把队列数据补对，然后把第 ⑧ 条恢复成**全判**——判据不该为了迁就数据而降级。

## 判据

1. **补齐 11 块**：每块按**真实状态**补 `  status = "..."`（已落地 ⇒ `"done"`；未派 ⇒ `"pending"`；
   在跑 ⇒ `"doing"`）。判据：`python -X utf8 tools/wb_plan.py check` 对这 11 块不再报「缺 status」，
   且**不许**把已落地的卡改成 pending（用 `git log --oneline -- .wt/<卡>` 与台账交叉核对后再写）。
2. **第 ⑧ 条放开**：`tools/pool/landing.py` 的 preflight 第 ⑧ 条从「只看目标卡」改成
   **全队列扫描**（复用 `_scan_blocks()` 的结果，不额外读文件），有任何一块缺 `status` ⇒ ❌ 并点名。
3. **钉子**（`tests/test_wb_land.py`）：
   - 全队列干净 ⇒ 第 ⑧ 条 ✅；
   - 注入一块缺 `status` ⇒ 第 ⑧ 条 ❌ 且**点名**那块卡；
   - 目标卡之外的那块缺 `status` 也要被判出来（这条钉子就是本轮的关键：半瞎→全判）。
4. **现有钉子不许变红**：`python -X utf8 -m pytest tests/test_wb_land.py tests/test_plan_consistency.py -q` 全绿
   （`test_plan_consistency.py` 若无此文件，改成 `tests/test_wb_plan.py`，回话里写清真名）。

## 交付

- `docs/workbacklog.toml`：11 块补 `status`（**只加这一行**，不许顺手改别字段）。
- `tools/pool/landing.py`：第 ⑧ 条改全判。
- `tests/test_wb_land.py`：三条钉子。

## 验收

```bash
cd .wt/E9
python -X utf8 tools/wb_plan.py check
python -X utf8 -m pytest tests/test_wb_land.py -q
python -X utf8 tools/wb_land.py --preflight --task T-AG455 --allow tools/pool/landing.py tests/test_wb_land.py docs/workbacklog.toml
```

## 不许做

- 不许为了让判据变绿而把「缺 status」当成合法状态（要么补数据，要么改判据——本卡选补数据）。
- 不许改 `status` 之外的工作队列字段（标题/flex 域/依赖都不动）。
- 不许把第 ⑧ 条改成「只报警告」。
