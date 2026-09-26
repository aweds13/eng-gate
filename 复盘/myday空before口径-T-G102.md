# myday-move 的空 `before` 口径：实现与契约对齐（T-G102 · 外包卡 015）

> 一句话：同一个形状（**给了 `before` 键却没给值**）原来有两种答案 —— 复盘说「给空 → 400」、
> 实现静默当末尾回 200。主控裁定**先查证据再定方向**：没有任何调用方发空串 → **改代码对齐契约**，
> 并把语义登记到**契约**这一处（`commands.toml` 只留一句 note 指向它）。

---

## §1 为什么有这张卡（背景 + 出处）

料来自盘点卡 S-1 的 **A5**（`gates/diag/盘点-20260926.md`）。

- **实现**：`src/timeflow/api/app.py` 的 `POST /api/tasks/{task_id}/myday-move` ——
  原来一句 `before = None if raw in (None, "") else str(raw)`，把 **空串** 与 **null** 一把抓 →
  `{"before": ""}` 被静默当"末尾"、回 200 并挪到末尾。
- **文档 A**：`复盘/拖拽排序-T-G79.md` 写「两个键要么给一个、要么不给（**都给 / 都给空** → **400**）」。
- **文档 B**：契约 `docs/contracts/domains/F1-tasks.md` 只写「两键要么给一个要么不给，都给 → 400；
  任务不存在 → 404 先于『不在今天』那一步」—— 没提空串。
- **复核报告**：`gates/diag/wb-review-T-G79.md` 边界 E 复现：`before=""（空串）→ 200`
  （对照 `body={}` → 400）。原话：「算不算缺陷由你定（我倾向『要么在文档里登记它 = 末尾，要么 400』，
  别两处不一致）」。

## §2 方向：据证据定（卡 §2.9① 要求，不许猜）

卡把方向列为「待主控定」，主控的裁定是：**先查界面与现有调用方有没有真的发 `before=""`** ——
有 → 改文档承认「空 = 末尾」；没有 → 改代码让它 400。

**查证结果：没有任何调用方发空串。**

- **界面**（唯一调用方）：`src/web/index.html:2037` 拖拽落点取
  `d.before = target ? target.dataset.mydayId : null;` —— 落点要么是**真任务 id**，要么是 **null**
  （拖到末尾），**从不发空串**；`:2055` `placeMyDay(d.id, d.before)` → `:2059`
  `JSON.stringify({before:beforeId})`。键盘那条路（↑↓）走的是 `{"direction": ...}`，根本不带 `before`。
- **测试**：`grep before` 全仓，所有 `myday-move` 调用的 `before` 值是**真 id** 或 **`None`**
  （`tests/test_myday_order_line.py` / `test_myday_rank_line.py` / `test_myday_idempotence_line.py`），
  没有一条发空串。
- **契约示例**：`{"before": "<id>"}` / `{"before": null}` —— 也没有空串这一路。

→ **没有人在用「空 = 末尾」** → **改代码对齐契约**：空串退回 **400**（与 `拖拽排序-T-G79.md`
的「都给空 → 400」一致）。

## §3 做了什么

### 3.1 改代码（`src/timeflow/api/app.py`）

把「空串」与「null」分开，改动**留在原来的 `with db.unit_of_work(...)` 里**（卡 §7-5）：

```python
if has_before:
    raw = body.get("before")
    if raw is None:
        before = None          # 显式 null = 末尾（契约点名的合法值）
    elif raw == "":
        # ★ T-G102：空串与 null 分开 —— 给了键却是空串不再静默当末尾
        raise HTTPException(
            status_code=400,
            detail="before 不能是空串；拖到末尾请传 null",
        )
    else:
        before = str(raw)
    moved = tm.place_myday(conn, task_id, before)
```

docstring 补一句指向契约（**引用不重述**）：`before` 给 `null` = 末尾；给空串 → 400，
口径以契约 OP-2 为准。

### 3.2 登记到一处（卡 §2.9②：以契约为单一真源）

- **契约**（单一真源）：`docs/contracts/domains/F1-tasks.md` OP-2 那节写清 ——
  「`before` 给空串也 → 400；**空串不静默当末尾**，只有 `before: null` 才是末尾」。
- **命令表**：`docs/commands.toml` 的 `OP-2` 只加**一句 note 指向契约**，**不另抄一套语义**。

### 3.3 判据（卡 §2.9③：把 `tests/test_myday_move_line.py` 加进白名单）

新建 `tests/test_myday_move_line.py`（3 条）：

1. ★ **空串 → 400 且不挪动**（本卡的核心，改前必红）；
2. ★ **`null` 仍是末尾**（别把 `null` 一起改坏 → 200 且落末尾）；
3. **别的形状照旧**：`{}` → 400、`{"direction": "up"}` 正常、真 id 落点正常。

## §4 真机证据（先红后绿）

口径照卡 §5：`TestClient(create_app(临时库))` 打**真路由**，库落 `%TEMP%/timeflow_probe015_*`，
真实库/备份一个字节没碰。探针脚本在 `%TEMP%/tf_probe_015.py`（**一次性、不进仓库**）。

**★ 一个必须记下来的环境坑**：本仓 `timeflow` 是 **editable 安装**，`.pth` 把
`D:/repo/engineering\src`（**主树**）追加进 `sys.path`。在 `.wt/api` 这棵
worktree 里直接跑 pytest，**import 到的是主树的 `app.py`** —— 改了 worktree 的源码却不生效。
必须把**本树** `src` 用 **Windows 风格路径**前置到 `PYTHONPATH`（MSYS 的 `/d/...` 形式
Windows 版 Python 不认）：

```powershell
$W = (Get-Location).Path                 # 或 bash: W="$(pwd -W)"
$env:PYTHONPATH = "$W/src;$W/tools/sandbox_shim"
```

改前（`git stash` 掉 app.py 的改动后跑）：

```
     {"before":""} -> 200  order=['乙', '丙', '甲']   ← 静默当末尾（病灶）
   {"before":null} -> 200  order=['乙', '丙', '甲']
                {} -> 400  order=['甲', '乙', '丙']
{"direction":"up"} -> 200  order=['甲', '乙', '丙']
pytest tests/test_myday_move_line.py → 1 failed, 2 passed
```

改后：

```
     {"before":""} -> 400  order=['甲', '乙', '丙']   ← 拒绝，顺序一个不动
   {"before":null} -> 200  order=['乙', '丙', '甲']
                {} -> 400  order=['甲', '乙', '丙']
{"direction":"up"} -> 200  order=['甲', '乙', '丙']
pytest tests/test_myday_move_line.py + tests/test_myday_order_line.py → 15 passed
```

## §5 轻门（照卡 §0.3、§5，不跑 `run_gates.py`）

| 门 | 命令 | 结果 |
|---|---|---|
| ruff | `python -X utf8 -m ruff check src/timeflow/api/app.py tests/test_myday_move_line.py` | **All checks passed** |
| pytest（新判据） | `pytest tests/test_myday_move_line.py --no-cov` | 改前 **1 failed, 2 passed** → 改后与 order_line 合计 **15 passed** |
| TOML | `python -X utf8 scripts/check_toml.py` | **通过（8 份）** |
| 命令表 | `python -X utf8 scripts/check_commands.py` | **命令表与四个真源一致 ✅**（加 note 未带红） |

## §6 边界（如实写，不假装）

- ★ `POST /api/tasks/{task_id}/myday-move` **仍未登记进 `docs/commands.toml`** ——
  表里只有 `OP-2` 的 `POST /api/tasks/{task_id}/myday`（那是「加入/移出 My Day」的切换）。
  本卡**没有新增 OP 条目**（新增 OP 会不会让六处对账门变红是另一口径，卡 §2.2/§7-4 明确要主控定）。
  所以命令表侧只**在同一节加一句指向契约的 note**。
- 路由**次序语义一字未动**：任务不存在 → **404 先于**「不在今天」那一步（复核"主张 4"验过）。
- **只碰空串那一支**：`null`=末尾、`direction` 那条路、幂等、事务包裹全部原样。
- 这是**口径统一**卡，不是新功能：修的是"同一形状两种答案"。

## §7 没动的

`manager.py` 等 `src/**` 里除 `app.py` 以外的文件、`src/web/**`、`tools/**`、`scripts/**`、
其它 `docs/**`、其它 `复盘/*.md`（含 `复盘/拖拽排序-T-G79.md` —— 它**不在**白名单）、
`gates/**`、共享文件（台账 / changelog / 两份交接文档 / `gates/last.json`）、
真实库 / 真实备份目录、三个外来未跟踪文件。

---

## 台账条目（供集成者粘贴）

```toml
[entries."T-G102"]
id = "T-G102"
title = "myday-move 的空 `before` 口径：实现（静默当末尾）与文档（给空应 400）对齐，并登记到一处"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/myday空before口径-T-G102.md",
  "text:src/timeflow/api/app.py::空串与 null 分开",
  "route:POST /api/tasks/{task_id}/myday-move",
]
gaps = "**为什么有这张卡**：盘点卡 S-1 的 A5 —— 同一形状（给了 before 键却没给值）有两种答案：复盘 `拖拽排序-T-G79.md` 说「都给空 → 400」，而实现把空串与 null 一把抓（`raw is None 或 raw 是空串` 一并当 None）静默当末尾回 200；复核报告 `gates/diag/wb-review-T-G79.md` 边界 E 复现。**方向（据证据定）**：查界面与现有调用方 —— 唯一调用方 `src/web/index.html:2037` 落点取 `target ? target.dataset.mydayId : null`（真 id 或 null，从不发空串），现有测试也只传真 id / None → 没有人在用「空 = 末尾」→ **改代码对齐契约**（空串退回 400）。**登记到一处**：语义以契约 `docs/contracts/domains/F1-tasks.md` 的 OP-2 为单一真源；`docs/commands.toml` 的 OP-2 只加一句 note 指向契约，不另抄。**反证（先红后绿）**：空串改前→200（且把任务挪到末尾）、改后→400（顺序一个不动）；null 仍→200 落末尾。**边界（如实写）**：`POST /api/tasks/{task_id}/myday-move` 至今未登记进 `docs/commands.toml`（表里只有 OP-2 的 `POST /api/tasks/{task_id}/myday`），本卡未新增 OP 条目；路由次序语义（任务不存在 404 先于「不在今天」）与 null=末尾 一字未动。**没动的**：`manager.py` 领域层、`src/web/**`、`tools/**`、其它 `docs/**`、其它 `复盘/*.md`、真实库/备份目录、三个外来未跟踪文件。"
```
