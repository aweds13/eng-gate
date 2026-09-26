# 外包卡 004 · 把状态面板转正（台账号 `T-G93`）

> 八条铁律在你的系统提示里（以卡规格为准）。**你的工作目录是这棵 git worktree（分支 `wt/004`），
> 不许碰主工作区**。卡号 004。干完按 §6 回报给主控。

## §1 背景

主控做了一个**原型**状态面板 `gates/diag/wb_dash.proto.py`（在你这棵树里已经放好了）：
它把 `gates/diag/wb-*` 那堆状态文件读成一块**会自动刷新**的表，让主控/用户一眼看到
"每个工人在不在动、跑到哪了、有没有被掐"。原型能用，但它是原型：文件名、参数、测试、边界都没定。

你的活：**把它转正成 `tools/wb_dash.py` + `tests/test_wb_dash.py`**，保持"零依赖、只读、2 秒刷新"。

## §2 口径（六条，逐条可验收）

1. **只读**：它只读状态文件（`gates/diag/wb-*.jsonl` / `*.heartbeat.txt` / `*.verdict.txt` /
   `*.session.txt`），**绝不**调用或杀工人、**绝不**写仓库里任何被跟踪的文件。
2. **状态四档**（与派活器的看门狗同一口径）：`在跑`（日志静默 < 60 秒）/ `安静`（60~480 秒）/
   `静默 N 分钟（可能卡死）`（≥ 480 秒）/ `收工·结束`。
   ★ `收工` 有两个来源：**判决文件存在**，**或日志里已经出现 `result` 事件** ——
   老卡没有判决文件，少了第二条就会把早已收工的卡误报成"可能卡死"（主控第一版就误报了）。
3. **多卡 + 多树**：一张卡一行；除了本仓库的 `gates/diag/`，还要能读**worktree 里的**
   `<仓库根>/.wt/*/gates/diag/wb-*.jsonl`（这是并发跑多个工人的前提）；行里要标出它来自哪棵树。
4. **零依赖 + 参数**：只用标准库；`--port`（默认 8787）、`--host`（默认 127.0.0.1）；
   根路径必须是"从本文件位置推出来的仓库根"，**不许**硬编码 `D:\...`。
5. **解析复用**：时间线/摘要一律用 `tools/wb_status.py` 的 `parse_events`（别写第二份解析器）；
   回合数按 `assistant` 事件的 `message.id` 去重（与派活器同一口径）。
6. **测试 ≥ 6 条**（`tests/test_wb_dash.py`，用 `tmp_path` 造假状态文件 + `monkeypatch` 换根）：
   状态四档各一条 / 有 `result` 事件（无判决文件）也算收工 / 多卡多树都能被发现 /
   `/api/state` 的 JSON 结构（含卡片列表与字段名）/ 没卡时给空表而不是崩。

## §3 允许改哪些文件（白名单）

**只能新建/改这三个：**
- `tools/wb_dash.py`（新建，从原型转正）
- `tests/test_wb_dash.py`（新建）
- `复盘/wb_dash转正-T-G93.md`（新建复盘：原型怎么来的 / 四档判定怎么定 / 边界）

**★ 一个字都不许碰：** `docs/traceability.toml`、`docs/changelog.md`、`复盘/交接-重构进度.md`、
`复盘/新窗口交接卡.md`、`gates/last.json`、`tools/wb_status.py`、`tools/wb_dispatch.py`、`src/**`、
主工作区的任何文件、真实库/备份目录、别人的未跟踪文件。
（理由：这是在**并发**跑的另一张卡要动的共享文件 —— 那些由主控串行收口。）

## §4 怎么交付（★ 与平时的卡不同，注意）

**不许提交**（没有台账条目，提交会过不了 audit）。你只做三件事：

1. 把三个文件写好；
2. 跑轻门自检（见 §5）—— **不要**跑 `scripts/run_gates.py`（并发时别抢 CPU/端口，全量门禁由主控
   收口时跑）；
3. 按 §6 回报，把改动**留在工作区**（主控会从你这棵 worktree 收口合并）。

## §5 自检 + 真机证据（都要贴输出）

```powershell
python -m ruff check tools/wb_dash.py tests/test_wb_dash.py
$env:PYTHONPATH = "$PWD\tools\sandbox_shim"
python -X utf8 -m pytest tests/test_wb_dash.py -q --no-cov
# 真机：起一次面板（用 8899 这种不冲突的端口），抓一次 /api/state，然后**把它停掉**
python -X utf8 tools/wb_dash.py --port 8899
python -X utf8 -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8899/api/state', timeout=10))['cards'])"
```
★ 三个硬要求：(a) 面板真能起、真能返回 JSON；(b) 抓完**停掉**那个进程（别留后台服务）；
(c) 别把端口占着（主控的面板在 8787）。

## §6 回报格式（只这六项）

```
卡号：004
改了什么文件：（一行一个，含新建）
跑了什么命令：（ruff / pytest 的关键行 + 真机 /api/state 的片段）
测试：几 passed（几条，各自验什么）
面板证据：端口 / 返回的 cards 片段 / 有没有停掉进程
提交：未提交（按 §4 —— 共享文件与台账由主控收口）
疑问/需要决策：（没有就写"无"）
```

## §7 已知的坑（主控替你踩过）

1. ★ **`gates/diag/` 里有个 `inspect.py`**，会把标准库 `inspect` 顶掉（跑到那儿就
   `AttributeError: module 'inspect' has no attribute 'signature'`）。原型里已经加了
   "把脚本自己所在目录从 `sys.path` 摘掉"的护栏 —— **转正后（放到 `tools/`）这行可以删，
   但要在复盘里说明为什么原来需要它**。
2. ruff 的 `E501` 按宽度算：中文注行长句容易超 100 字符。
3. 一律 `python -X utf8`；Windows 路径下看 git 加 `-c core.quotepath=false`。
4. 测试里**不许**真的去连接网络/起服务（用 `tmp_path` 造假文件）；真机那一步是**手工证据**，
   不进测试。

---

## 附：给你的额外提示（主控备注）

- 原型里 `_state()` / `card_state()` 两个函数是核心，转正时**先给它们写测试**（四档判定最容易错）。
- "多树"那一条：主工作区的 `gates/diag/` 与 `.wt/*/gates/diag/` 都要扫；行的 `card` 字段建议
  在跨树时带上树名（例如 `004@.wt/004`），免得两张卡同号时看串。
