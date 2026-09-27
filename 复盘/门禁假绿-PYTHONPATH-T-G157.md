# 门禁假绿 · PYTHONPATH（卡 063 · 台账号 `T-G157`）

> 一句话：`scripts/run_gates.py` 给子进程构造环境时只塞了 `tools/sandbox_shim`、**没塞本树
> `ROOT/src`**；而本仓是可编辑安装（`pip install -e .`）指向**主树**的 `src` —— 于是在 worktree 里，
> `render` / `ui_flow` / `ui_dom_probe` / `web_live` / `lf1_live` 这几道**真机门验的是主树的页面**，
> 黄金又是在同一个错页面上采的 → 两边一致 → **假绿**。修法：把本树 `src` 放进子进程 `PYTHONPATH` 首位。

## §1 根因（改前实读）

- `scripts/run_gates.py`（改前）：`env()` 里唯一一行
  `e["PYTHONPATH"] = shim + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")`
  —— 只补 `tools/sandbox_shim`，**没有 `ROOT/src`**。改后见 `tree_pythonpath()`
  （`scripts/run_gates.py:293`）。
- 页面从哪来：`src/timeflow/api/app.py:343` `web_dir = Path(__file__).resolve().parent.parent.parent / "web"`
  —— `web_dir` 取决于**导入了哪一份 `timeflow` 包**。worktree 里 `import timeflow` 解析到主树 → `web_dir`
  = 主树 `src/web` → 服务发的是主树页面。
- node 门怎么起服务：`tools/tf_browser.mjs:98-110` `startServer()` 用 `env = { ...process.env }` 再
  `env.PYTHONPATH = shim + ';' + env.PYTHONPATH`（`:102`）→ **继承** `run_gates.py` 传下来的
  `PYTHONPATH`（`<本树>/src` 会被保留，只是排在 `shim` 之后）；随后 `spawn python tools/serve.py --fresh`
  （`:108`，`cwd=ROOT`）。两个 live 检查（`tools/lf1_live_check.py` / `tools/web_live_check.py`）是
  `run_gates.py` 直接用 `env=env()` 起的 python 进程 → 走同一个 `PYTHONPATH`。
- `serve.py --fresh`（`tools/serve.py:117-129`）**不走 `backup()`**，所以它自己那句
  `sys.path.insert(0, ROOT/"src")`（`:52`）在 `from timeflow.api.app import create_app`（`:150`）之前
  **不会执行** → `timeflow` 仍从可编辑安装（主树）解析。这就是假绿的机制。

**改前实测（worktree 里）**：`python -X utf8 -c "import timeflow; print(timeflow.__file__)"` →
`D:/repo/engineering\src\timeflow\__init__.py`（**主树**）。

## §2 改法（最小）

1. 新增 `tree_pythonpath(e)`（`scripts/run_gates.py:293`）：把 `e["PYTHONPATH"]` 设为
   `<ROOT>/src` → `<ROOT>/tools/sandbox_shim` → **原有的 `PYTHONPATH`**（前者优先）。
   `shim` 目录里只有 `sitecustomize.py`（无 `timeflow`），`<ROOT>/src` 里没有 `sitecustomize.py`
   → 两者互不遮蔽，`site` 仍扫得到 `shim` 的 `sitecustomize`。
2. **每一处** `os.environ` 副本都过它（`git grep -n 'os.environ' -- scripts/run_gates.py` 自查）：
   - `env()`（`scripts/run_gates.py:315`）—— 所有门（含 node 门再 spawn 的 `serve.py`）；
   - `staged_tree()` 里的 `env_with_index`（`scripts/run_gates.py:352`）—— git 子进程用（对 git 无影响，
     一并统一，避免"还有一处漏网"）。
3. 开跑印一行"验的是哪棵树"（`scripts/run_gates.py:817-818`）：
   `=== 本树 src = <路径>（子进程 PYTHONPATH 首位，T-G157）===`。

★ **没动**任何门的判据、端口（`port_base`/`TF_GATE_PORT_BASE`）、复用键（`REUSE_INPUTS`）、`--seal`、
`src/**`、`tools/**`、`tests/**`。（本卡与 062 同改 `run_gates.py`，底座 = 062 的提交 `6d41e0e`，
与其改动天然共存。）

## §3 先绿后红的反证（★ 这一对是本卡的牙）

**反证 A（假绿现场，改代码之前做）**：在**未改**的 `run_gates.py` 上，故意把
`src/web/index.html:16` 的 `<h1>timeflow ·</h1>` 改成 `<h1>timeflow · FALSGREENPROBE063</h1>`，
**不设** `PYTHONPATH`，跑 `python -X utf8 scripts/run_gates.py`：
- 结果：17 门全 exit 0，`render` **exit=0**（`45 份清单与黄金逐字节一致`）、`ui_flow` **exit=0**。
- `ok=False` 只因 `docs_sync_ok=False`（改了 `src` 没同步文档）—— **不是**真机门红。
- ⇒ 故意改坏了本树页面，真机门却照绿：**这就是假绿**
  （日志 `gates/logs/063-A.log`，读数 `gates/last.json` 那轮 `rev=6d41e0e`）。

**反证 B（改后必须红）**：保留同一处故意改动、应用修复，跑
`python -X utf8 scripts/run_gates.py --no-reuse`（`--no-reuse`：A 轮把 `render` 的"通过"写进了复用记录，
而 `run_gates.py` 不在 `render` 的复用输入里，不强制真跑就会被复用、看不出红）：
- `render` **exit=1** —— 服务的是**本树**页面了：
  `body>div.shell>aside.rail>h1   timeflow ·`（黄金）vs 本树的 `timeflow · FALSGREENPROBE063`，
  `desktop/memo -48 +48` … `…另有 39 份不同`（45 份清单全不同），失败输出在 `gates/logs/render.log`。
- `ui_flow` 仍 exit=0（它验的是功能流、不钉 h1 文案）—— 门终于在看本树，**render 这一半就够了**。

**反证 C（还原后全绿）**：`git checkout -- src/web/index.html` 还原后，跑
`python -X utf8 scripts/run_gates.py`：
- `ok=true`、**17 门**、`reused` 为空（全部真跑）、`render`/`ui_flow` exit=0；
  启动行打印 `本树 src = .wt/pypath1\src`（日志 `gates/logs/063-C.log`）。

## §4 主树对照（行为等价，门数与结论不变）

主树里 `ROOT/src` 就是可编辑安装指向的那份 → 把 `ROOT/src` 放进 `PYTHONPATH` 首位**是 no-op**：

- 主树 `python -X utf8 -c "import timeflow; print(timeflow.__file__)"` →
  `D:/repo/engineering\src\timeflow\__init__.py`（= `ROOT/src` 自身）。
- 两树 `src` 在 **git 对象层逐字节相同**：
  `git ls-tree -r 6f7d4d0 -- src | git hash-object --stdin` = 本树 `HEAD` 同法 =
  `a4e94eaf5bda96760a77b0ff2eaba300891f1b95`（`git diff --stat 6f7d4d0 6d41e0e -- src/` 为空；
  062 也没动 `src/`）。★ `diff -rq` 会报一堆"不同"，那是**工作区行尾 CRLF/LF** 噪声
  （`git ls-files --eol`：主树 `w/lf`、worktree `w/crlf`），与内容无关。
- 主树侧已有的门禁读数：提交在案的 `gates/last.json`（`rev=6f7d4d0` = 主树 HEAD）=`ok=true`、**17 门**；
  与本卡反证 C 的 `ok=true`、**17 门**一致。

## §5 边界（没做到 / 有待集成者）

- **台账条目**：卡 §4 要求"放复盘末尾，供集成者粘贴"，但 `tools/wb_review.py` 复核时用
  `scripts/audit_progress.py`（**无 `--all`**）会查「HEAD 提交的 `Task:` 是否在台账里」（`audit_progress.py:502`），
  不粘就**审计必红**、这一笔不算数 → 本卡**已直接粘进 `docs/traceability.toml`**（在 `T-G156` 之后），
  复盘末尾留一份副本供核对；`done` 数字用 `tools/sync_counts.py` **现刷**（非手写）：
  `done=279 / partial=1 / todo=0 / deferred=2（共 282）`。
- `run_gates.py` 在 `scripts/` 下，**不在** `mypy src/` 这道门内；`mypy scripts/run_gates.py` 有 7 个
  `_psutil` 相关的 `no-untyped-call` **改前就在**（base 同为 7 个），本卡没新增也没消。
- 别的门是否也依赖"跑在主树"这个假设：`web_live` / `lf1_live` / `ui_dom_probe` 都由同一个 `env()` /
  同一份 `PYTHONPATH` 起，已被本修复一并覆盖；未发现还有别的门读主树固定路径。
- 真机门验的是"这棵树自己的页面"了，但**黄金仍以主树口径采的时间戳/归一化**照旧，本卡没重采黄金
  （页面未变 → 不必）。

## 台账条目（已粘进 `docs/traceability.toml`，此处留档）

```toml
[entries."T-G157"]
id = "T-G157"
title = "修 run_gates 在 worktree 里验主树页面的假绿：把本树 src 放进子进程 PYTHONPATH"
group = "PROCESS"
status = "done"
evidence = [
  "text:scripts/run_gates.py::PYTHONPATH",
  "file:复盘/门禁假绿-PYTHONPATH-T-G157.md",
]
gaps = "根因＝可编辑安装指向主树 src，run_gates 只塞 tools/sandbox_shim 没塞 ROOT/src → worktree 里 render/ui_flow/ui_dom_probe/web_live/lf1_live 服务的是主树页面、同源黄金一比必绿（假绿）。改法＝tree_pythonpath() 把 ROOT/src 放 PYTHONPATH 首位（env() 与 staged_tree 的 env_with_index 两处都过），加一行开跑日志。反证 A（未改代码＋故意改 index.html h1＋不设 PYTHONPATH）render/ui_flow 仍绿＝假绿现场；反证 B（改后同改动）render exit=1、45 份清单全不同；反证 C（还原）ok=true 17 门全绿。没动判据/端口/复用键/seal/src/tools/tests。台账条目由集成者粘贴；done 数字以 sync_counts --check 实测为准。"
```
