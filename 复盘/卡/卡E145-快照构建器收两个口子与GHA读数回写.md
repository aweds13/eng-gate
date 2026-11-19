# 卡 E145 · 快照构建器收两个口子：不存在的 dest 要干净退 2、冒烟红了要真退 5（并把 GHA 真读数与 OpenMAIC 那条腿写进文书）

> 台账号 `T-AG660`｜分区 E（门禁与可信度）｜树 .wt/E145｜层 判据层｜基准 `7a4cc513`（立卡时主树 HEAD）｜depends 无
> 依据：E144（`99b9a58a`）把构建器/适配器/垫片搬进库后，`scripts/cloud/gha/build_snapshot.py` 的 `main()` 只判「远端 / 私钥 / 适配器 / 垫片」，**不判 dest 存不存在**；`do_smoke()` 三段只打 `SMOKE*_RC` 而**从不因非零退出** ⇒ 冒烟红也退 0。同一条 `--stage smoke` 在 dest 不存在时**退 0 却三段全红**（2026-11-20 00:20 实测，见问题 2）。
> 行号按 2026-11-20 主树 `7a4cc513` 现场复核：`scripts/cloud/gha/build_snapshot.py` 448 行 / `tests/test_gha_cloud_gate.py` 206 行 12 条 / `docs/subsystems/ci/GitHub-Actions-云门禁.md` 171 行。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · `--stage push` 在 dest 不存在时抛 traceback（rc=1，不是 2）

    $ GHA_REMOTE=git@github.com:x/y.git GIT_SSH_COMMAND='ssh -i nowhere' \
        python -X utf8 scripts/cloud/gha/build_snapshot.py --stage push --dest gates/diag/_tmp/nope-e145
    ...
    File "C:/Users/example\\miniconda3\\Lib\\subprocess.py", line 1553, in _execute_child
    NotADirectoryError: [WinError 267] 目录名称无效。
    PUSH_RC=1

`scripts/cloud/gha/build_snapshot.py:433 os.makedirs(a.tmp, exist_ok=True)` 之后直接 `:438-443` 按 stage 派发 ⇒ `do_push()` 的 `git config`（`:342`）在**不存在的 cwd** 上起进程。失败面本该是「缺配置 ⇒ 2」，现在退成 1 + traceback，调用方分不清「环境没准备好」和「脚本自己坏了」。

### 问题 2 · `--stage smoke` 在 dest 不存在时**假绿**（退 0，三段全红）

    同一条命令换 --stage smoke ⇒ SMOKE_RC=0
    SMOKE1_RC 4   ERROR: file or directory not found: tests/test_audit_tightening.py::test_real_repo_history_files_are_all_claimed
    SMOKE2_RC 1   E902 系统找不到指定的文件。 (os error 2) --> examples:1:1
    SMOKE3_RC 2   can't open file '...\\nope-e145\\scripts\\check_docs.py'

根因在 `do_smoke()`（`scripts/cloud/gha/build_snapshot.py:312`）：三段的返回值只经 `log('SMOKE1_RC', …)`（`:324` / `:330` / `:336`）打在日志里，**函数从不因非零返回** ⇒ `main()` 一路 `return EXIT_OK`。这条不是「dest 不存在」专属：任何一次冒烟红的 `--stage smoke` 都退 0。

对照：同文件的 `do_push()` 是**对的**——`SMOKE4` 红时 `log('SMOKE4_FAILED -> refuse to push'); sys.exit(EXIT_POOL)`（`:374-376`）。冒烟段没跟上这个口径。

### 问题 3 · `do_smoke()` 会往仓外写桩与 fixture，所以它更不能静默通过

冒烟段调的是适配器自己的两个 helper（`:315-318`）：`shim._ensure_pool_stub()` 把四件号池桩写到**仓外** `<dest>/../infra/pool`，`_ensure_diag_fixtures()` 写三份 `wb-*.jsonl` 到 `<dest>/gates/diag/`。dest 指错地方时这两步会**在错的地方造出一套桩**，然后三段全红、脚本还退 0 —— 既骗了 CI，又在盘上留垃圾。

### 问题 4 · 文书的真读数是上一版（v17），跟仓里现在这份不配套

`docs/subsystems/ci/GitHub-Actions-云门禁.md:132` 与 `:135` 写的是 job `135331686931` / rev `cdb2c0fa`；而 E144 落地后从仓内构建器跑出来的 v18 推的是 `14220c7c`，读数 job `135640738507`（`:132-156` 那张表、`:155` 的「2650.71 s ≈ 44.2 min / job ≈ 14.7 min」全要按 v18 重算）。文档里那句「真读数（2026-11-19）」必须指到**仓里这份脚本能产出的那一次**，否则读者无法把文档和源码对上。

### 问题 5 · 文书对「OpenMAIC 那条腿」零字，但验收第 2 条要的正是它

    $ grep -c 'OpenMAIC\|om-gate\|vitest' docs/subsystems/ci/GitHub-Actions-云门禁.md
    0

任务书（用户目标）的验收第 2 条是「OpenMAIC 仓能在云上跑出真的 vitest 读数」。今天这条腿的真读数**有**（镜像仓 `aweds13/om-gate`，2026-11-16 run `43902435671` 四分片：`Test Files 14 failed | 1133 passed | 42 skipped` / `Tests 64 failed | 14727 passed | 448 skipped`），但它是「把 OpenMAIC 树推上去触发的 OpenMAIC 自己的 ci.yml」跑出来的，**不是**本仓脚本造的；本仓 `scripts/cloud/gha/` 只有 engineering 的构建器。文书必须把这条边界写成真话，而不是让读者以为同一条路已经两仓通用。

## 判据（6 条，逐条可执行）

### 判据 1 · dest 不存在 ⇒ 干净退 2，打 `MISSING_DEST`，不抛 traceback

`--stage` 取 `all` / `smoke` / `push` 且 `not os.path.isdir(a.dest)` ⇒ `log('MISSING_DEST', a.dest)` 后 `return EXIT_CONFIG`；进程退出码 **2**，stdout 含 `MISSING_DEST`，stderr **不含** `Traceback`。`--stage build` 不受此限（它就是造 dest 的那一步）。

### 判据 2 · 冒烟三段任一非 0 ⇒ 退 5 并打 `SMOKE_FAILED`

`do_smoke()` 里三段各自判非 0（含 `None`＝进程没起来）⇒ `log('SMOKE_FAILED', 'SMOKE<n>', rc)` 后 `sys.exit(EXIT_SNAPSHOT)`；三段全 0 才返回。口径与 `do_push()` 的 `SMOKE4_FAILED -> refuse to push` 一致。

### 判据 3 · 两条缺口都有测试钉住，且测试**真的会红**

`tests/test_gha_cloud_gate.py` 新增两条用例：一条跑 `--stage smoke --dest <不存在的路径>` 断言 rc==2 + `MISSING_DEST` + 无 `Traceback`；一条在**假桩**上把 `do_smoke()` 的三段命令换成一个必然非 0 的进程（monkeypatch `SMOKE_TARGETS`/`sh` 或直接对返回码做函数级断言），断言 `SystemExit.code == 5` 且日志含 `SMOKE_FAILED`。反向自检：把实现里的两处判断注释掉，这两条用例必须转红（当场跑一遍再改回来，把读数写进交接）。

### 判据 4 · 退出码表与标签表跟着更新，不新造码

`build_snapshot.py` 模块头部 docstring 的退出码说明补上「5 也管冒烟红」；`docs/subsystems/ci/GitHub-Actions-云门禁.md` §5 的 `EXIT_CONFIG` 行加 `MISSING_DEST`、`EXIT_SNAPSHOT` 行加 `SMOKE_FAILED`。五个码仍是 `2/3/4/5/6`（加 `0`），**没有新值**；`tests/test_gha_cloud_gate.py::test_exit_codes_are_five_distinct_values` 与 `test_each_failure_has_a_readable_tag` 仍绿（后者把 `MISSING_DEST` / `SMOKE_FAILED` 也列进断言集）。

### 判据 5 · 文书 §6 换成 v18 的真读数，且每个时间数都带 `源：`

§6 的 job 号 / rev / 逐门秒数换成 job `135640738507`（run `44547171433` / head `14220c7c`）那一份；`ok=True / host=runnervmm7ud1 / rev=14220c7c / n_gates=23 / not_run=[] / workers=4` 原样引；逐门 seconds 的原表照抄（同源求和 **4603.51 s ≈ 76.7 min**），job 墙钟按官方时间戳 `2026-11-19T14:45:18Z → 15:07:41Z` = **1343 s ≈ 22.4 min**；每处时间数所在表格块内必须有 `源：`（`tests/test_ci_docs.py` 的 `unsourced_time_blocks()` 只钉 `测试流程.md`，但本卡照同一口径写，别让下一份文档继承坏习惯）。

### 判据 6 · 文书新增一节讲 OpenMAIC 那条腿，边界写成真话

新增一节（建议 §8「第二仓：OpenMAIC 那条腿」），至少写清四件事：① 真读数在哪（镜像仓 `aweds13/om-gate` / run `43902435671` / head `19b46314` / 四分片合计 `Tests 64 failed | 14727 passed | 448 skipped` / 四片 duration 相加 ≈ 778 s，`源：` 指向 GHA job 日志）；② 它是**OpenMAIC 自己的 ci.yml**（`--shard=N/4`）跑的，本仓 `scripts/cloud/gha/` **没有** om 侧构建器；③ 因此「同一套脚本服务两仓」这件事在 GHA 这条腿上**尚未成立**，成立的是 `scripts/cloud/profiles/*.toml` 那条（租机）路线；④ 若要把这条腿补成通用，缺的是什么（一个 `--repo` 化的构建器 + om 侧不冻结 workflow 的事实）。不许把 ② 写成「通用」或省略。

## 交付

1. `scripts/cloud/gha/build_snapshot.py`：`main()` 加 `MISSING_DEST` 前置判；`do_smoke()` 三段判非 0 退 `EXIT_SNAPSHOT`；头部退出码注释同步。
2. `tests/test_gha_cloud_gate.py`：加判据 3 的两条用例；`test_each_failure_has_a_readable_tag` 的标签集加 `MISSING_DEST` / `SMOKE_FAILED`。
3. `docs/subsystems/ci/GitHub-Actions-云门禁.md`：§5 两行、§6 换 v18 读数、新增 §8 讲 OpenMAIC 那条腿。
4. 文书片段（docs/changelog.d/T-AG660.md / docs/traceability.d/T-AG660.toml / 复盘/交接.d/T-AG660.md，落地时由 tools/wb_stage_card.py 现生成）由 `tools/wb_stage_card.py` 生成，**不许手写**。

## 验收（4 条，落地前自跑）

    cd .wt/E145
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_gha_cloud_gate.py
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_ci_portability.py
    python -X utf8 -m ruff check scripts/cloud tests/test_gha_cloud_gate.py
    python -X utf8 scripts/check_derived_docs.py --check

门槛：① 新用例全绿且**证伪过**（注释掉实现即红）；② 可移植性判据仍 20 passed（不许往 `WHITELIST` 加条目）；③ ruff 无告警；④ 派生文档一致（`docs/subsystems/ci/` 篇数不变 ⇒ INDEX 只需重算 `docs/INDEX.md` 内容，不加行）。

## 不许做

- 不许把 `do_smoke()` 的红改成「只警告」或加 `--allow-smoke-red` 之类的开关来绕判据 2。
- 不许给 `EXIT_*` 加新值（五个码是 `tests/test_gha_cloud_gate.py` 钉住的形状）；不要拿 `run_gate.sh` 的 2/9/4/5/7 往这里套（两套失败面不同，文档 §5 末尾已经写明）。
- 不许在本卡的文书里用反引号写「快照内路径」（如快照内那个 autostart 端到端测试的文件名）或 gates/enggate-logs 下的日志 —— E144 因此吃过一次死指针 148 > 147；要写就写不带反引号的说明。
- 不许改 `scripts/cloud/gha/adapter.py`（它是 runner 上真跑过 23 门全绿的那一份）。
- 不许为了写 §8 去动 om-gate 仓（本卡只写本仓文书；om-gate 侧的证据已存在 `gates/diag/_tmp/om-shard-*.log`）。

## 直做（已实测）

E145 现场读数（2026-11-20 00:40）：主树 HEAD `7a4cc513`，`git status --porcelain -uno` 空，锁全空，`.wt/E145` 建在 `7a4cc513` 上、工作区干净；待派卡与三个将碰文件零交集；`grep -c 'id = "E145"' docs/workbacklog.toml` ⇒ 0。
