# myday 撞击 409 映射（卡 035 · `T-G126`）

## §1 为什么有这张卡

T-G109 给 myday 排序焊上乐观锁：重读重算**重试一次仍撞**时原样抛 `MydayConflictError`
（`src/timeflow/core/tasks/manager.py:1391`，docstring 写明它是「报 409 的载体」）。
但那张卡的白名单只有 core，接口层映射留给集成者；其复盘
（`复盘/myday版本守卫-T-G109.md:66-70`）如实记了这条边界：「重试一次仍撞的路径经 HTTP
会显成 500。需要主控决定」→ **主控裁定另立卡**（本卡，接口层域，与 022 的 core 域分开）。

## §2 现状查证（先证实，不照抄别人的话）

- **谁抛**：`manager._write_myday_rank`（manager.py:1426，乐观锁 UPDATE 影响行数 0 时）；
  `place_myday` / `move_myday` 内部重试一次仍撞 → 原样抛出（manager.py:1601-1605 / 1641-1645）。
- **谁该接**：接口层只有 `POST /api/tasks/{task_id}/myday-move`
  （`src/timeflow/api/app.py` 的 `move_myday` 端点）调这两个 core 函数；
  它的 except 链原来只接 `KeyError`（404）与 `ValueError`（400），
  `MydayConflictError` 是 `RuntimeError` 子类 → 无人接 → 冒泡成 500。
  app 没有全局异常兜底（无 `add_exception_handler`；唯一的 `except Exception` 只护 `/api/health`）。
- ★ **真机证实（TestClient，`raise_server_exceptions=False`）**：装置 = 把
  `manager._write_myday_rank` 换成「每次调用都抛真异常」的桩（第 1 次调用 = 初写撞、
  第 2 次 = 重试仍撞，正是 T-G109 口径里「重试一次仍撞」那条路；确定性，不靠真并发碰运气）。
  制造一次撞车请求 `POST /api/tasks/{id}/myday-move`（`{"before": <真id>}`）：
  - **加映射前**：`status = 500`，`body = 'Internal Server Error'`（纯文本，连 JSON 都不是）
    → **台账那句「会显成 500」属实**。

## §3 做了什么

`src/timeflow/api/app.py` 两处（**5 行**，`git show` 可验）：

1. `from timeflow.core.tasks.manager import MydayConflictError`（app.py:45）
   —— ★ 它没被 `core/tasks/__init__.py` re-export，而 `__init__.py` 属 `core/**`（022 的域，
   禁区），所以从 `manager` 模块直接导入，**没碰 core 一个字**。
2. `move_myday` 端点的 except 链在 `KeyError` 与 `ValueError` 之间加一条
   （app.py:1736-1739）：

   ```python
   except MydayConflictError as e:
       raise HTTPException(status_code=409, detail=str(e)) from e
   ```

   detail 用 `str(e)` —— **照本端点既有 `ValueError` 分支的写法**，core 那句报错文案
   本来就是按「给用户看」写的（说清是哪一条拖拽建立在过期快照上），没发明新格式；
   只动这一条映射，**其它异常一个都没改**（409 lan 配对 / 400 / 404 的行为不变）。

## §4 真机证据（先红后绿 + 突变检验）

命令（本 worktree；★ 坑见 §5-1）：

```powershell
$env:PYTHONPATH = "<本树>\src;<本树>\tools\sandbox_shim"
python -X utf8 -m pytest tests/test_myday_conflict_409.py --no-cov
```

1. **先红**（还原 app.py 到 HEAD = 未加映射）：`1 failed, 1 passed` ——
   红的那条 `AssertionError: Internal Server Error` / `assert 500 == 409`。
2. **加映射后**：`2 passed`。同一撞车请求的原始响应：
   `status = 409`，
   `body = {"detail":"myday 排序撞上并发更新：写 e8c9bc49e187 时快照 version=1，库里已是 999 —— 这次拖拽建立在过期快照上（探针注入第 2 次调用）"}`
   —— 人话、JSON、不泄露超出 task_id/version 的内部细节。
3. **突变检验**：把新映射三行删掉 → 核心用例**红**（`1 failed`，`assert 500 == 409`，
   日志 `C:/Users/example\AppData\Local\Temp\mutation_red.log`）；
   还原 → **全绿**（`2 passed`；还原后与还原前逐字节 `diff` 一致）。
   —— 判据真会咬，不是摆设。

## §5 碰到的坑（真踩，记录给后来的树）

1. ★★ **本仓是 editable 安装指向主树**：`site-packages/__editable__.timeflow-0.1.0.pth`
   写死 `D:/repo/engineering\src` → 在 worktree 里**裸跑 pytest/probe
   导入的是主树的 timeflow**（本卡第一次「红」就红错了树，行为巧合一致才没当场穿帮）。
   在 worktree 干活必须把**本树 src 前置**：`PYTHONPATH="<本树>\src;<本树>\tools\sandbox_shim"`，
   且 Git Bash 里 `$PWD` 展开成 `/d/...`（MSYS 形式）Windows Python **不认** —— 要写
   `d:/...` 形式。判据：`python -c "import timeflow; print(timeflow.__file__)"` 必须指到本树。
2. **Git Bash 里没有 PowerShell 的 `*>`**：`命令 *> 日志` 的 `*` 会被 glob 成「当前目录所有
   文件」塞进 argv（pytest 于是去收集 `config.example.toml`/`pyproject.toml` 报 not found）。
   Git Bash 用 `> 日志 2>&1`。
3. `raise_server_exceptions=False` 才钉得住「显成什么状态码」——默认 True 会把未接异常
   直接抛进测试，钉不到 500 那个面。

## §6 边界（如实写）

- **其它异常映射没动**：除上面 5 行外 `app.py` 零改动；既有 409/400/404 用例全绿
  （`pytest tests/test_api.py tests/test_lan_pairing_line.py --no-cov` → **28 passed**，
  `pytest tests -k "myday or conflict" --no-cov` → **56 passed**，ruff 两文件 **All checks passed**）。
- `tests/test_myday_sparse_line.py` **本树不存在**（022 还没合进来）→ 卡 §5 那条「只跑不改」
  无从跑起，如实记。
- **装置是确定性桩，不是真并发 HTTP**：真并发交错（两线程 + 屏障）的复现与钉子另在
  `tests/test_myday_version_guard_line.py`（T-G109）；本卡只钉 HTTP 面。没有做真机并发压测。
- **没查 UI**：前端拿到 409 后显示什么不在本卡白名单内，没动也没验。
- **没动的**：`core/**`（022 的域）、`storage/**`、`tools/**`、`scripts/**`、`docs/**`、
  共享文件（台账 / changelog / 交接文档 / `gates/**`）、其它 `复盘/*.md`、三个外来未跟踪文件。
- **全量门禁没跑**（卡 §0-3 明令禁止，由主控集成时跑）；本卡轻门 = ruff + 上面那几条 pytest。

## 台账条目（供集成者粘贴）

```toml
[entries."T-G126"]
id = "T-G126"
title = "`MydayConflictError` 经 HTTP 显 **409**（原为 500）：补接口层异常映射 + 真机证实与钉子用例"
group = "PROCESS"
status = "done"
evidence = [
  "file:复盘/myday撞击409映射-T-G126.md",
  "text:src/timeflow/api/app.py::except MydayConflictError as e:",
  "test:tests/test_myday_conflict_409.py",
]
gaps = "**为什么有这张卡**：T-G109 落地乐观锁时如实记的边界 —— 「重试一次仍撞的路径经 HTTP 会显成 500。需要主控决定」（`复盘/myday版本守卫-T-G109.md:66-70`），主控裁定另立卡（接口层域，与 022 的 core 域分开）。**做了什么**：映射加在 `src/timeflow/api/app.py` 的 `move_myday` 端点 except 链（KeyError 与 ValueError 之间插 `except MydayConflictError` → 409 + `str(e)`，照既有 `detail=str(e)` 写法，core 的报错文案本就是给用户看的）；异常类从 `manager` 模块直接导入（它没被 `core/tasks/__init__` re-export，而那文件在 `core/**` 禁区）—— 全卡只动 app.py 5 行。**现状证实**：台账那句属实 —— TestClient 真机探针（`_write_myday_rank` 换成每次都抛真异常的桩 = 初写撞 + 重试仍撞）读数：加映射前 `status = 500`、`body = 'Internal Server Error'`（纯文本）。**真机证据（先红后绿）**：加映射前同一请求 `500` + 纯文本 `Internal Server Error`；加映射后同一请求 `409`，body 的 detail 字段为「myday 排序撞上并发更新：写 <task_id> 时快照 version=1，库里已是 999 —— 这次拖拽建立在过期快照上（探针注入第 2 次调用）」。**反证（突变检验）**：删掉新映射三行 → 钉子用例红（`assert 500 == 409`，`1 failed`）；还原 → 全绿（`2 passed`），还原后逐字节 diff 一致。**边界（如实写）**：其它异常映射一个没动（既有 409/400/404 全绿：`tests/test_api.py` + `tests/test_lan_pairing_line.py` 28 passed、`-k 「myday or conflict」` 56 passed、ruff 两文件过）；装置是确定性桩不是真并发 HTTP（真并发交错的钉子在 T-G109 的屏障用例），没做真机并发压测；`tests/test_myday_sparse_line.py` 本树不存在（022 未合入）无从跑起；UI 拿到 409 后显示什么没查没动。**没动的**：`core/**`（022 的域）、`storage/**`、`tools/**`、`scripts/**`、`docs/**`、共享文件（台账 / changelog / 交接文档 / `gates/**`）、其它 `复盘/*.md`、三个外来未跟踪文件。"
```
