# 工人状态面板转正（外包卡 004 · 台账号 T-G93）

> 一句话：把原型 `gates/diag/wb_dash.py` 转正成 `tools/wb_dash.py` + `tests/test_wb_dash.py`，
> 保持"零依赖、只读、2 秒刷新"，并把**四档状态判定**与**多卡多树**这两件最会出错的事钉成测试。
> **未提交**（按卡 §4 —— 没有台账条目，且有共享文件由主控串行收口）。

## 1. 原型怎么来的、为什么要转正

主控做了块状态面板（`gates/diag/wb_dash.py`）：把 `gates/diag/wb-*` 那堆状态文件读成
一块会自动刷新的表，让主控/用户一眼看到"每个工人在不在动、跑到哪了、有没有被掐"。
它当时**故意放在 `gates/diag/`** 里 —— 因为并发在跑的另一张卡要动 `tools/`，动那儿会污染那张卡的门禁。
原型能用，但**文件名、参数、测试、边界都没定**，所以这一张卡把它转正。

## 2. 转正改了什么（与原型逐条对照）

| 项 | 原型 | 转正后 | 为什么 |
|---|---|---|---|
| 位置 | `gates/diag/wb_dash.py` | `tools/wb_dash.py` | 正式工具的位置；`tools/` 与 `wb_status.py` 同目录 |
| 根路径 | `parents[2]`（`gates/diag/` 往上两层） | `parents[1]`（`tools/` 往上一级 = 仓库根） | ★ 卡 §2.4：**从本文件位置推出来**，不硬编码盘符 |
| 绑定地址 | 写死 `127.0.0.1` | 新增 `--host`（默认 `127.0.0.1`） | 卡 §2.4：`--port` / `--host` 都要能调 |
| 多树 | 只扫本仓库 `gates/diag/` | 再扫 `<仓库根>/.wt/*/gates/diag/`，行里带 `tree` 字段 | 卡 §2.3：并发跑多个工人时每棵树各有 `gates/diag/`，少扫一棵就少一个工人 |
| 卡的标识 | `wb-004.jsonl` → `004` | 主树 `004`；跨树 `004@.wt/004` | 卡附录建议：两张卡同号时靠树名区分，免得看串 |
| 收工口径 | 判决文件 **或** 日志里有 `result` 事件 | 不变（保留） | 卡 §2.2：老卡没有判决文件，少了 `result` 这条会把早已收工的卡误报成"可能卡死" |
| 状态字 | `收工/结束` | `收工·结束` | 与卡 §2.2 的写法对齐 |
| `/api/state` | 直接写在 Handler 里 | 抽成 `api_state()`，Handler 调它 | 卡 §2.6 要验 JSON 结构，抽出来才能在**不起服务**的前提下测（卡 §7.4 禁止测试连网） |

### ★ 关于原型里那行"把脚本自己所在目录从 sys.path 摘掉"（卡 §7.1）

原型里有：

```python
sys.path = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
```

**为什么原来需要它**：原型住在 `gates/diag/`，而那个目录里有一个 `inspect.py`。
脚本运行时它自己所在的目录会被塞进 `sys.path[0]`，于是**标准库的 `inspect` 被这个同名文件顶掉** ——
`argparse` 一构造就去 `import inspect`，当场 `AttributeError: module 'inspect' has no attribute 'signature'`，
面板根本起不来。

**转正后为什么可以删**：搬到 `tools/` 之后，脚本自己的目录是 `tools/`，那里**没有** `inspect.py`，
不会再遮蔽标准库。所以转正版**去掉了那行"摘除自己目录"**，只保留
`tools/` 的 `sys.path.insert`（为了 `import wb_status`）。那一行不是"没用了随手删"，而是
**它要防的那个具体文件不在新目录里了**。

## 3. 四档判定怎么定的

口径**照抄派活器的看门狗**（卡 §2.2，不另起一套）：

```
收工·结束   ← 有判决文件，或日志里出现 result 事件（两者满足其一）
在跑        ← 日志静默 < 60 秒
安静        ← 60 ≤ 静默 < 480 秒
静默 N 分钟（可能卡死）  ← 静默 ≥ 480 秒
```

顺序很重要：**先看收工证据，再看静默多久**。反过来的话，一个才收工 3 秒的卡会被算成"在跑"，
而一个静默很久但早已 `result` 的卡会被算成"可能卡死"——后者正是主控第一版踩的坑（误报了卡 002）。

`收工` 的两个来源各钉了一条测试，其中"**有 result 事件、但没有判决文件**"是重点
（我把它单独做成一条，并在 `_state` 的收工判断那里留了注释）。

## 4. 证据（先红后绿 + 真机）

**轻门（卡 §5）：**

- `python -m ruff check tools/wb_dash.py tests/test_wb_dash.py` → **All checks passed!**
  （中途修了 2 条 `E501`：一条是长中文 docstring，一条是 `PAGE` 里那行长 CSS —— 后者在原型里
  住在 `gates/diag/`，没被 ruff 扫到，搬到 `tools/` 才暴露。）
- `PYTHONPATH=$PWD/tools/sandbox_shim python -X utf8 -m pytest tests/test_wb_dash.py -q --no-cov`
  → **11 passed**。

**反空转（证明判据真会咬，不是"它什么都没查"）：** 故意把实现改坏两次，各跑一次：

1. 把收工判断里的 `or bool(summary["final"])` 删掉 →
   `test_result_event_means_finished_without_verdict` **FAILED**：
   `assert '静默 10.0 分钟（可能卡死）' == '收工·结束'`（正是卡里说的那种误报）；
2. 把多树扫描 `if wt.is_dir()` 改成 `if False and wt.is_dir()`（不扫 `.wt/`）→
   `test_multi_card_multi_tree_are_discovered` **FAILED**：
   `assert {'001'} == {'001', '004@.wt/004'}`。

两次都还原后重跑 → `ruff All checks passed!` + `11 passed`。

**真机（卡 §5）：** 用 `python -X utf8 tools/wb_dash.py --port 8899` 起面板，
抓 `http://127.0.0.1:8899/api/state`，然后**按 PID 停掉**（不是按进程名）：

```
端口 8899 有回话，卡片数 = 1
  card=004 tree='' state=在跑 turns=23 tool_calls=35 size_kb=367.4
cards JSON 片段: [{"card": "004", "tree": "", "log": "wb-004.jsonl", "state": "在跑",
  "color": "run", ..., "model": "deepseek-v4.1-flash", ...}]
已停止面板 pid = 34848 退出码 = 1
8899 已释放（连不上 = URLError）
```

（退出码 1 是 `terminate()` 掐进程的正常结果，不是报错；随后再连 8899 已经连不上 = 端口没占着。）

## 5. 边界（如实写）

- **只读**：只读 `gates/diag/wb-*.jsonl` / `*.heartbeat.txt` / `*.verdict.txt` / `*.session.txt`，
  不调用/不杀工人、不写任何被跟踪的文件。面板本身**不落任何文件**。
- **它只报"在不在动"，不判断"内容对不对"** —— 那是主控复核的事。
- **续跑日志（`wb-<卡>.r2.jsonl`）按文件各占一行，不按卡合并**：合并口径没定，
  卡里也没要求，所以**故意没做**（谁要合并，先定口径）。
- **从某棵 worktree 内部运行时**，根是那棵 worktree（`.wt/004`），找得到它自己的 `gates/diag/`，
  找**不到兄弟 worktree**（`<root>/.wt/*` 在它下面不存在）。面板的常规跑法是从**主工作区**起 ——
  那时主树 + 全部 `.wt/*` 都能扫到。测试用 `tmp_path` 造出主树 + `.wt/004` 的布局来验多树。
- **多树只认 `.wt/<一层子目录>/gates/diag/`**，不递归更深。

## 6. 没动的（一个字都没碰）

`docs/traceability.toml`、`docs/changelog.md`、`复盘/交接-重构进度.md`、`复盘/新窗口交接卡.md`、
`gates/last.json`、`tools/wb_status.py`、`tools/wb_dispatch.py`、`src/**`、主工作区、真实库/备份目录。
**没有跑 `scripts/run_gates.py`**（卡 §4：并发时别抢 CPU/端口，全量门禁由主控收口时跑）。
**没有提交**（卡 §4）。

## 7. 交付物

- `tools/wb_dash.py`（新建，从原型转正）
- `tests/test_wb_dash.py`（新建，11 条）
- 本复盘

改动**留在工作区**（分支 `wt/004`），由主控收口合并。

## 8 主控收口（2026-09-26，T-G93）

**怎么收的**：**按文件**把这三个（+ 本卡的卡规格）从 `.wt/004` 复制进主工作区 —— **不是**按分支合并
（`wt/004` 的基点是 `3333404`，而工人 A 后来 `git reset --soft` 让那一笔成了孤儿提交，按分支合会带进脏东西）。
两个工人在并发时各写各的树，共享文件（`docs/traceability.toml` / `docs/changelog.md` / 两张交接文档 /
`gates/last.json`）**只由主控串行改** —— 所以工人 B 的白名单里**没有**这些文件，它也确实一个都没碰。

**主控自己验的（不是看它的报告）**：

- `git status --porcelain`：树里只有它那三个新文件（+ 我放的卡规格）—— **没有**任何被跟踪文件被改；
- `python -m ruff check tools/wb_dash.py tests/test_wb_dash.py` → `All checks passed!`；
- `PYTHONPATH=$PWD/tools/sandbox_shim python -X utf8 -m pytest tests/test_wb_dash.py -q --no-cov` → **11 passed**。

**主控改了这一份文档的一处事实错误**：原型住在 `gates/diag/wb_dash.py`，工人 B 写成了
`gates/diag/wb_dash.proto.py`（这名字**从来不存在**）。已全文改正 —— 记录在此，免得日后有人照着去找。
它的技术描述（`parents[2]`、那行 `sys.path` 摘除、为什么要删）与原型逐条对得上。**

**遗留（如实写）**：续跑日志 `wb-<卡>.r2.jsonl` 仍是**一个文件一行**（合并口径未定，故意没做）；
面板只扫 `.wt/<一层>/gates/diag/`，不递归更深；它**不判断内容对不对**，只报"在不在动"。
