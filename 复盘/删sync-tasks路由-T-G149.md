# 删 sync-tasks 路由（卡 056 · 台账号 `T-G149`）

> 工人卡 · 2026-09-27 · 规格：`gates/diag/卡056-删sync-tasks路由.md`。
> 用户 2026-09-27 当面裁定「删」；历史：09-25 `T-G59` 拍「保留不删」只标弃用 → 现改判删除。

## 为什么这么做

- 用户原要求里的跨端同步只有一条路：**同步包（文件）+ 导出/导入 + 合并规则**
  （已落地，`SR-F9.2` = done，见 `复盘/口径定案-待定清单.md` §3「③ 先做」）。
- `POST /api/sync/tasks` 是被它取代的**更早的老实现**（逐条推任务、按行合并，
  见 `复盘/口径落档-T-G19.md:110`）：界面无入口、`tests/` 零命中、`src/` 里只有它自己的定义。
- 09-25 保留不删的唯一理由是「怕有外部脚本还在打它」；09-27 用户当面改判删。

## 做了什么（六处）

1. `src/timeflow/api/app.py`：删掉 `@app.post("/api/sync/tasks")` 装饰器与 `sync_tasks`
   三行实现，原位置留历史注释（新字面含「已于 2026-09-27 按用户裁定删除」）；
   `from timeflow.core import sync as sync_mod` **保留** —— app.py:2385 的
   `sync_mod.status(conn)`（`GET /api/sync/status`）仍在用。
2. `docs/commands.toml` OP-40：`routes` 去掉 `"POST /api/sync/tasks"`（保留 export/import/status/logs）；
   `note` 保留原句、句末追加「；★ 该路由已于 2026-09-27 按用户裁定删除（原为 2026-09-25 弃用）」。
3. `docs/traceability.toml`：`SR-F9.2` evidence 删掉 `"route:POST /api/sync/tasks",` 整行
   （同组仍有 export/import/status）；`T-G59` 两条 `text:` 机械刷成
   「已于 2026-09-27 按用户裁定删除」（没有换成更松的锚）；`T-G59` gaps 末尾追加改判日期注；
   新增 `[entries."T-G149"]`（`status = "done"`）。
4. `tools/route_ui_gap.py`：`DECIDED` 删掉该路由那条声明（只删两行；
   `("GET", "/api/team/assignments")` 不动）。
5. `docs/changelog.md` 置顶追加一条；`复盘/交接-重构进度.md` 顶部追加 CHECKPOINT（只加不删）；
   `复盘/收口后待用户清单.md` 末尾追加完成注（第 3 项已删）。
6. 交接文档里的台账分布数字行由 `tools/sync_counts.py` 按其专用机制刷新
   （279→280、done 276→277）—— 新增一条 done 使旧数字漂移，audit 红挡提交，此工具就是为这条数字行设的。

## 碰到什么坑 / 怎么发现的

- `pin_check.py --literal "已弃用（deprecated，2026-09-25 用户确认）"` 命中 **2 颗钉子**
  —— 恰好是卡 §2.3/§7.1 预告的 T-G59 两条 evidence（不是意外钉子），已按卡同笔机械刷新。
- 工人第一轮在 bash 里误用 PowerShell 风格 `*>` 重定向，`*` 被 glob 展开把当前目录全部文件
  塞进了 pytest/mypy 参数（假红：not found 一串）；换 bash 重定向后重跑，全绿。
  教训：卡表 §8.2 的「落文件再读」在 bash 下要写 `> 文件 2>&1`。

## 读数（实测）

- `pin_check`：命中 9 处（钉子 2 / 叙述 7）—— 钉子 2 = T-G59 两条 evidence（预告内）。
- `scripts/check_toml.py`：OK（8 份）。
- `scripts/audit_progress.py`：0 失败、豁免 0。
- `pytest tests/test_check_commands.py tests/test_cli_line.py --no-cov`：**42 passed**。
- `ruff check src/ tests/ scripts/ tools/ examples/`：All checks passed。
- `mypy src/`：Success, no issues found in 56 source files。
- `tools/route_ui_gap.py`：后端路由 **154** 条 / 前端没提到 **7** 条（已声明 1 / 未声明 6）
  —— 该路由与它的 DECIDED 声明都不再出现。
- 行为读数 `git grep -n 'sync/tasks' -- src tests tools`：`src/` 只剩历史注释一行
  （app.py:2310），`tests/`、`tools/` 零命中。
- 全量门禁：`python -X utf8 scripts/run_gates.py` 全绿后 `--seal`（读数以 `gates/last.json` 为准）。

## 没动什么

- `src/timeflow/core/**`（同步实现本体）、`tests/**`（预期零改动，实测零命中零改动）、
  `scripts/**`、`复盘/` 的其它文件、主树三个外来未跟踪文件。
- app.py 的 `sync_mod` import（2385 行仍在用）。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G149"]
id = "T-G149"
title = "删掉 POST /api/sync/tasks（旧的行级合并入口）：用户 2026-09-27 裁定 —— 它不符跨端同步的原要求（同步只有包+导出/导入一条路）"
group = "API"
status = "done"
evidence = [
  "text:src/timeflow/api/app.py::已于 2026-09-27 按用户裁定删除",
  "text:docs/commands.toml::已于 2026-09-27 按用户裁定删除",
  "file:复盘/删sync-tasks路由-T-G149.md",
]
gaps = "**为什么有这张卡**：用户 2026-09-27 当面裁定「删」——原要求见 `复盘/口径定案-待定清单.md` §3（同步包+导出/导入+合并规则）；本路由是更早的逐条推任务老实现（`复盘/口径落档-T-G19.md:110`）。**做了什么**：删了 app.py 里 `@app.post` 装饰器（路径为旧的行级合并入口）与其下三行实现（`sync_tasks` 函数体），原位置留一段历史注释（含「已于 2026-09-27 按用户裁定删除」字样）；`docs/commands.toml` OP-40 的 routes 去掉该路由、note 末尾追加删除日期注；`tools/route_ui_gap.py` 的 DECIDED 表删掉该路由那条声明（GET /api/team/assignments 那条不动）。**证据指针**：SR-F9.2 删了 route: 那一行（同组仍有 export/import/status）；T-G59 两条 text: 刷成「已于 2026-09-27 按用户裁定删除」+ gaps 末段日期注。**读数**：pin_check 命中 2 颗钉子（即 T-G59 两条 evidence，卡 §2.3 预告的同笔刷新）；audit 0 失败豁免 0；check_commands 与 cli_line 42 passed；ruff 全过；mypy 56 文件 0 error；route_ui_gap 154 条路由、不再报该路由；交接文档台账分布由 sync_counts.py 刷为 280 条（done 277）。**没动的**：src/timeflow/core/**（同步实现）、tests/**（零改动）、app.py 的 sync_mod import（2385 行 sync/status 仍在用）。"
```
