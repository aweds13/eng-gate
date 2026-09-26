# 外包卡 003 · 修 `--detach` 的前置检查顺序（台账号 `T-G92`）

> 这是**写卡**：按 §2 的口径改实现、按 §3 的白名单改文件、按 §4 提交、按 §6 回报。
> 八条铁律在你的系统提示里（以卡规格为准）；**越界改文件 = 这一轮作废**（主控会用白名单卡复核）。
> 卡号 003。干完把 §6 那六项回报给主控。

## §1 背景：事实与证据（这些都是主控实测过的，不用你再验一遍）

`tools/wb_dispatch.py` 的 `--detach`（把派活扔成脱离窗口的进程，过夜/长任务用）有一个**顺序错**：

```python
    if args.detach and not args.detach_done:      # ← 现在在**前置检查之前**
        detach_log = ...
        pid = spawn_detached(detached_argv(sys.argv[1:]), detach_log)
        print(f"[扔 ] 已扔出去单独跑（pid {pid}）…")
        return 0                                  # ← 父进程就此退 0
    problems, log = preflight(...)                # ← 检查其实在**子进程**里才做
```

后果（主控在 `复盘/长跑保命-T-G91.md` §5 里如实记过）：

1. 父进程打印"已扔出去"并**退 0** —— 但那**不代表前置检查过了**（检查在子进程里）；
2. 前置检查没过时，子进程退 2 但**不写判决文件** `wb-<卡>.verdict.txt` —— 于是过夜之后
   `python -X utf8 tools/wb_dispatch.py --card <卡> --status` 只会说"判决：还没有"，
   **分不清"没跑"和"跑挂了"**；
3. `detached_argv()` 不给子进程补 `--no-preflight`：父进程已经查过登录了，子进程还要再花
   十几秒重查一次（`auth_ok()` 是真发一条 CLI 请求）。

现状（HEAD = `162e376`）：`detached_argv` 的返回是
`[sys.executable, "-X", "utf8", *[a for a in argv if a != "--detach"], "--detach-done"]`；
测试 `tests/test_wb_dispatch.py` 里 `test_detach_throws_the_work_out_and_returns_immediately`
只验"扔一次就返回"，**没验顺序**，所以在当前实现下是**绿**的（这正是要补的洞）。

## §2 口径（六条，逐条可验收）

1. **前置检查必须先在父进程做完**：`--detach` 的那个分支要挪到 `problems` 判断**之后**；
   没过就**打印原因 + 退 2 + 绝不 detach**（不留孤儿进程）。
2. **没过也要留痕**：前置检查没过时也要写判决文件 `wb-<卡>.verdict.txt`，内容至少包含
   「前置检查没过 → 没派活」+ 失败原因（`'；'.join(problems)`）。理由：过夜跑时
   "没跑"和"跑挂了"必须一眼分得清（`--status` 读的就是这个文件）。
3. **子进程补 `--no-preflight`**：`detached_argv()` 的返回值里 `--no-preflight` **恰好出现一次**
   （输入里已有的要去掉，免得重复）；并且 `--detach` 不在里面、末尾是 `--detach-done`。
4. **过了才扔，且话说清楚**：打印改成「前置检查全过 → 扔出去单独跑（pid …）」，并照旧给出
   `--status` 提示与 dispatch.log 路径；退出码仍 0。
5. **其它行为一个字不许改**：看门狗 / 心跳 / 回合上限（写卡 240、只读 80）/ 续跑
   （`--resume` / `--retry`）/ 铁律进系统提示 / 模型默认值 / `--autocompact 1m` / 超时默认 7200
   —— 全部保持现状。**只动 `--detach` 那条路**。
6. **不许为了省事把检查挪进子进程**（那是现状）；也不许把 `--detach` 删掉。

## §3 允许改哪些文件（白名单）

**可以改：**
- `tools/wb_dispatch.py`（只动 `detached_argv()` 与 `main()` 里 `--detach` 那几行）
- `tests/test_wb_dispatch.py`（适配现有 detach 用例 + 新增覆盖 §2 的用例）
- `docs/traceability.toml`（**只**：新增 `T-G92` 条目；并把 `T-G91` 的 `gaps` 尾巴追加一句
  「★ 2026-09-26 更正（T-G92）：…」说清那处顺序已修）
- `复盘/长跑保命-T-G91.md`（**只**：把 §5 边界里"前置检查在子进程里"那条更正成事实）
- `复盘/detach前置检查-T-G92.md`（新建复盘：现象 / 根因 / 修法 / 反证 / 边界）
- `docs/changelog.md`（加一条）
- `复盘/交接-重构进度.md` + `复盘/新窗口交接卡.md`（最新 CHECKPOINT + 用
  `python -X utf8 tools/sync_counts.py` 同步数字）
- `复盘/外包卡-003-修detach前置检查.md`（本卡规格，跟着提交）
- `gates/last.json` / `gates/reuse.json`（门禁产物，必须跟着提交）

**不许改：** `src/**`（一行都不许动）、`tools/` 下别的文件、`docs/contracts/**`、真实库/备份目录、
别人的未跟踪文件（`DSH-窗口化方案.md`、`dsh-skill-docs-report.zh.md` 一个字都不许碰）。

## §4 怎么提交（本项目的硬流程，错一步 audit 会红）

```powershell
$env:PYTHONPATH = "$PWD\tools\sandbox_shim"
python -X utf8 -m pytest tests/test_wb_dispatch.py -q --no-cov     # 先单跑这一族
python -X utf8 scripts/run_gates.py            # 全量门禁（真跑；约 3 分钟，多数门会复用）
python -X utf8 scripts/run_gates.py --seal     # 把树封进 gates/last.json
git add -A -- <§3 白名单里的那些文件> gates/last.json gates/reuse.json
git commit -F gates/diag/msg-T-G92.txt
```

提交信息末尾**四行 trailer**：

```
Task: T-G92
Refs: T-G91, T-G82
Ledger: 新增 T-G92；<改成事实后的分布>
Gates: <把 gates/last.json 的 summary 摘要抄进来>
```

注意：提交信息用**文件**给（`git commit -F gates/diag/msg-T-G92.txt`）—— bug 那种 heredoc 在
PowerShell 里不可靠。★ **门禁不过就不许提交**；`python -X utf8 scripts/audit_progress.py --all`
必须 **PASS 且豁免 0**。工作区必须干净（`git status --porcelain -uno` 空）。

## §5 反证（必须做，做了才算数）

先写**在当前实现下必然失败**的用例，跑红，再改实现让它绿，并把**两条输出**都贴进复盘：

1. `--detach` + 一个不存在的 `--spec` → **当前退 0**（错），要退 2；
2. 紧接着 `wb-<卡>.verdict.txt` 应当存在且含「前置检查没过」→ 当前**文件不存在**；
3. `detached_argv([...])` 里 `--no-preflight` 恰好一次 → 当前**0 次**。

（用 `tmp_path` + `monkeypatch` 就行；`tests/test_wb_dispatch.py` 里已有现成的沙盒 fixture
`sandbox` 与假 runner `_fake_runner`，照它们的写法来。**不许**为了过测试去改被测语义。）

**真机三条证据**（都便宜、都别真花钱派活）：

```powershell
# (a) 前置检查没过：应当立刻退 2、不 detach、并且留下 verdict
python -X utf8 tools/wb_dispatch.py --card 900 --spec 没有这张卡.md --detach --execute --no-preflight
python -X utf8 tools/wb_dispatch.py --card 900 --status

# (b) 检查过了再扔：用 --detach **但不加 --execute**（子进程只干跑，不真派活、不花钱）
python -X utf8 tools/wb_dispatch.py --card 900 --spec 复盘/外包卡-003-修detach前置检查.md --detach --no-preflight
#     等 2~3 秒后看子进程的输出（应当能看到 dry-run 那几行）
Get-Content gates\diag\wb-900.dispatch.log
```

★ **不许**为了做证据而真派一次活（那是花钱的）。要看"扔出去的进程真活着"，用上面 (b) 的干跑就够。

## §6 回报格式（给主控，只这六项）

```
卡号：003
改了什么文件：（一行一个）
跑了什么命令：（含先红后绿两条输出，贴关键行；真机 (a)(b) 的证据也贴）
门禁：python -X utf8 scripts/run_gates.py 的结果（哪几门绿 / 有没有红 / gates/last.json 的 ok 与 rev）
提交：<sha>（没提交就写"未提交"并说明卡在哪）
疑问/需要决策：（没有就写"无"）
```

## §7 已知的坑（主控替你踩过，别再踩）

1. ★ **台账里的裸 ASCII 双引号**：`docs/traceability.toml` 的 `gaps = "…"` 是 TOML 基本串，
   里面**不许出现裸的 `"`**（那会当场把 TOML 弄坏、`audit` 报 `TOMLDecodeError`）—— 要引用就用
   「」或反引号。主控为此栽过十几次。
2. **改了台账数字就要同步交接文档**：`python -X utf8 tools/sync_counts.py`（否则 audit 第 ⑦ 条红）。
3. pytest 要挂沙盒：`$env:PYTHONPATH = "$PWD\tools\sandbox_shim"`（Windows 路径、UTF-8 一律用
   `python -X utf8`）。
4. 中文路径下看 git：`git -c core.quotepath=false status --short`（否则 `\345\244…` 看不懂）。
5. ruff 的 `E501` 按**宽度**算：中文注行长句容易被判超长（上限 100）—— 写完先
   `python -m ruff check tools/wb_dispatch.py tests/test_wb_dispatch.py`。
6. 卡 900 是**占位卡号**（探针用），别真拿它派活；`--force` 只在 log 已存在、你要覆盖证据时用。
