# GitHub Actions 云门禁 —— 判据留在仓里，runner 租外面

> 这份文档回答一件事：**没有云机了，凭什么还能「在别人的机器上跑一遍全量门禁、把读数拿回来当证据」。**
> 与 [云门禁机](云门禁机.md) 的分工：那份讲**租来的 ECS**（SSH 过去跑、`scripts/cloud/run_gate.sh` 那条路）；
> 本页讲**租来的 runner**（推快照、让冻结的 workflow 跑）。两条路的判据同一份 —— 都是 `scripts/run_gates.py` 那 23 道门。

> 关联：[CI 项目书](README.md) · [可复现性清单](云门禁-可复现性清单.md) · [测试流程五维](测试流程.md)。
> 跑门禁的操作顺序见 [`skills/pipe-gate/SKILL.md`](../../../skills/pipe-gate/SKILL.md)。

## 0. 一句话

**外部 runner 可以租，判据不许搬出去。** GitHub Actions 那边只提供「一台 windows-latest、4 核 / 16 GB 的干净机器」；
跑什么、怎么判、红门长什么样，全部还是仓里这份 `scripts/run_gates.py` 说了算 ——
runner 上唯一的入口是一个**适配器**（`scripts/cloud/gha/adapter.py`），它只做四件事：装钉版本的依赖、铺仓外号池桩、
跑一遍全量门禁、把 `gates/last.json` 原样打回日志。它**不改判定**。

## 1. 两条路的分工

| | 租 ECS（旧） | 租 runner（本页） |
|---|---|---|
| 入口 | `scripts/cloud/run_gate.sh` | `scripts/cloud/gha/build_snapshot.py` |
| 机器怎么来 | 人先开一台、SSH 过去 | GitHub 按 push 自动起、跑完销毁 |
| 代码怎么上去 | `git bundle` + scp 一个补丁 | 造一棵快照树、`push --force` 到镜像仓 |
| 跑什么 | profile 的 `gate.cmd` | 冻结 workflow 的最后一步（写死） |
| 读数怎么回来 | scp 回 `gates/last.json` + 日志 | job 日志里的 `=== GHA-GATE-READING-BEGIN/END ===` 夹的 JSON |
| 判据 | `scripts/run_gates.py` | **同一份** |

ECS 那条路没被删：`scripts/cloud/run_gate.sh` 与两份 profile 原地不动，机器回来就能用。
本页这条是**在没有云机的时候**把同一套判据跑起来的第二条腿。

## 2. 为什么 workflow 改不了（这条决定了后面所有形状）

镜像仓 `aweds13/eng-gate` 是从一个模板仓 generate 出来的。它在镜像仓里的 `.github` 目录下那份 ci.yml（engineering 本仓没有这个文件）那个作业写死四步：

```yaml
  windows-autostart-e2e:
    name: Windows HKCU autostart E2E
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6      # python-version: "3.12"
      - run: python -m pip install -e . "pytest>=8"
      - run: python -m pytest -q tests/test_windows_autostart_e2e.py
```

**改不了**：推 `.github/workflows/**` 一律 404 —— 用的 token 没有 workflow scope，而连「私仓 + admin + 非 fork」也不放开
（2026-11-18 实测，探针记录在卡 E144 规格里）。

所以形状是被**倒推**出来的：

- 最后一步写死 tests/test_windows_autostart_e2e.py（快照内路径，engineering 本仓没有这个文件） ⇒ **适配器必须装成这个名字**。改名 ⇒ pytest 一条都收集不到、
  进程退出码 4、「整趟绿」绿得毫无意义。所以 `scripts/cloud/gha/adapter.py` 里真正干活的那个用例叫
  `test_windows_runner_runs_the_gates`，但它**落地的文件名**不许动。
- 第三步只装 `-e . "pytest>=8"` ⇒ 门禁要的 `mypy` / `ruff` / `pytest-cov` / `pytest-xdist` **不在盘上**，
  而根 `pyproject.toml` 的 `addopts` 带 `--cov=timeflow --cov-fail-under=70` ⇒ pytest 在**收集之前**就撞
  `unrecognized arguments: --cov`。适配器的`EXTRA` 那八条钉版本就是补这个洞，`conftest_shim.txt` 是兜底
  （见 §4）。
- 没有 `workflow_dispatch` ⇒ **不能点按钮触发**，只能靠 push 到 `main`。

## 3. 一趟怎么跑：`build_snapshot.py` 三段

```powershell
$env:GHA_REMOTE = "git@github.com:<owner>/<repo>.git"
$env:GIT_SSH_COMMAND = "ssh -i <deploy key> -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
python -X utf8 scripts/cloud/gha/build_snapshot.py --stage all
```

`--stage` 四选：`build` / `smoke` / `push` / `all`。三段各自能单跑，`all` 是串起来。
除 `build` 之外的每一段都**在已有的快照目录上干活**（`smoke` 还会往 `<快照的父目录>/infra/pool` 造桩、
往 `<快照>/gates/diag` 写 fixture）⇒ 目录不在就**先退 2**（`MISSING_DEST`），不往下走：
以前这里不判，`push` 会甩一个 `NotADirectoryError: [WinError 267]` 的栈、`smoke` 更糟 ——
三段全红却退 0（卡 E145 实测）。

**build —— 造一棵能推的快照树**（默认落在 `gates/diag/_tmp/enggate`，被 `.gitignore` 挡住）：

1. `git bundle create` 把**当前 HEAD 的完整历史**打成一个包（只要 HEAD 那一层也行，但 11 条历史判据要 `git log`，
   所以走 bundle + 后续 `fetch --unshallow`，见适配器的 `_ensure_history()`）。
2. `git init` 一棵空树，从 bundle 里 `fetch` + `checkout` —— 这是「engineering 的树」。
3. 再从镜像仓**浅 fetch** 一次 `origin/main`，只把 `.github/` 拷过来 —— 因为冻结的 workflow 只在那边有。
4. 铺**仓外**号池桩：`<快照的父目录>/infra/pool/` 五件（`pool_models.py` / `models.whitelist.toml` /
   `models.live.json` / `accounts.toml` / `projects.toml`），**零凭据**。`tools/pool/projects.py::index_path()`
   是从本树逐级向上找 `infra/pool/projects.toml` 的，所以桩必须住在仓**外**：仓内一旦出现 `infra/`，
   它就变成被跟踪的路径，`test_own_exts_covers...` 与 README 的派活日志计数会一起红。
5. 装适配器（`adapter.py` → 快照里的 tests/test_windows_autostart_e2e.py），给 `tests/conftest.py` 尾部追加 `conftest_shim.txt`。
6. 往 `docs/traceability.toml` 的 `[meta]` 前插 `claimed_files_exempt`（三条：适配器 / `tests/conftest.py` / `.github/**`）——
   这三样是**快照才有的文件**，台账没声称过，审计门的反向判据会逐个点名。
7. **保留** `gates/last.json` 与 `gates/reuse.json`（它们是被 `docs/traceability.toml` 的 `file:` 证据指着的入库证据，
   删了 docs 门会报死指针暴涨）。
8. 现造三份 diag fixture（`wb-E14.trae.jsonl` 等），再重算 `docs/subsystems/pool/README.md` 与 `docs/INDEX.md`。
   ★ 顺序不能反：生成器读的是**盘上真实有几份**派活日志，fixture 不先落盘，README 里的计数就差 239。

**smoke —— 推之前先在本机把最容易被快照形状弄红的那批判据跑一遍**：18 条定向 pytest + `ruff check` 六目录 +
`scripts/check_docs.py --mode report`。冒烟必须**复刻适配器在 runner 上做的事**（同一个 `_ensure_pool_stub()` /
`_ensure_diag_fixtures()` 函数，`importlib` 直接 import 适配器本身）—— 抄一份逻辑就会各自漂。
三段**任一段非 0 就退 5**（`SMOKE_FAILED`）：以前只把 `SMOKE*_RC` 打进日志、函数照常返回，
于是「本机冒烟红、快照照样推上去」可以无声发生（卡 E145 实测：`--stage smoke` 指到不存在的目录时
三段全红、脚本退 0）。

**push —— 提交 + 再跑两条提交后判据 + `push --force`**：commit message 必须带合规的 `Task:` trailer
（审计门 ⑧ 与 `tools/pytest_select.py` 都读它，缺了会报「没有 Task: trailer」并把 task 读成 `\x00`）；
提交之后**还要**再跑两条只在提交后成立判据（`test_pytest_select.py::test_log_batch_agrees_with_the_per_commit_reads` 与
`test_docs_fragments.py::test_audit_verdict_unchanged_by_sync`），红了就**拒绝推**。

推上去之后 GitHub 立刻起 job；适配器在日志里打 `=== GHA-GATE-READING-BEGIN ===` ／ JSON ／ `=== … END ===`，
外层再断言三条：`ok is True`、`not_run` 为空、`host` 非空。**红门会被逐道打出来**（失败行 + 门日志尾 9 KB +
隔离重跑的最多 6 条 nodeid）。

## 4. 两块垫片，各治一个洞

| 垫片 | 治什么 | 没了会怎样 |
|---|---|---|
| 适配器的 `EXTRA`（八条钉版本） | runner 只装了 `-e .` + `pytest>=8` | `mypy`/`ruff`/`pytest-cov`/`pytest-xdist` 缺失 ⇒ 一片「命令不存在」的假红 |
| `conftest_shim.txt`（追加进 `tests/conftest.py`） | 根 `pyproject.toml` 的 `addopts` 带 `--cov-*`，而插件可能不在 | pytest **在收集之前**就退 2：`unrecognized arguments: --cov=timeflow` —— 适配器根本没机会跑 |

`conftest_shim.txt` 的写法值得记一笔：`pytest_addoption` 里先 `try: import pytest_cov; return`，
**插件在就立刻返回**（绝不覆盖真选项），不在才注册六个同名占位。这样两种 runner 上用同一份垫片都成立。
它另外还挂了 `pytest_terminal_summary`：全绿时 pytest 不会打 Captured stdout，读数就藏在文件里没人看得见 ——
这个钩子把 `gates/diag/_gha_reading.json` 的内容打进终端摘要，于是「绿的」和「红的」都能从日志里抠出读数。

## 5. 退出码（本工具自己的表，与 `run_gate.sh` 不是一套）

`build_snapshot.py` 的码是模块常量（`EXIT_*`），`tests/test_gha_cloud_gate.py::test_exit_codes_are_five_distinct_values`
逐条钉住它们互不相同、且每个都真有 `sys.exit` 路径：

| 码 | 常量 | 含义 | 典型日志记号 |
|---|---|---|---|
| 0 | `EXIT_OK` | 跑完了 | `BUILD_DONE` |
| 2 | `EXIT_CONFIG` | 缺配置：没给远端 / 没给 `GIT_SSH_COMMAND` / 适配器或垫片文件不在 / 快照目录不在 | `MISSING_REMOTE` / `MISSING_GIT_SSH_COMMAND` / `MISSING_ADAPTER` / `MISSING_DEST` |
| 3 | `EXIT_HISTORY` | 历史或 workflow 拿不到（bundle / fetch / `.github` checkout） | `BUNDLE_FAILED` / `FETCH_FAILED` / `WORKFLOW_CHECKOUT_FAILED` |
| 4 | `EXIT_COMMIT` | 本地提交失败 | `COMMIT_FAILED` |
| 5 | `EXIT_SNAPSHOT` | 快照形状不对（垫片撞车 / 豁免块已在 / 证据文件不在），或冒烟有红色 | `CONFTEST_ALREADY_HAS_ADDOPTION` / `LEDGER_ALREADY_EXEMPT` / `MISSING_EVIDENCE_FILE` / `SMOKE_FAILED` |
| 6 | `EXIT_POOL` | 号池桩不对，或仓内混进了 `infra/`，或推前判据红 / 推失败 | `MISSING_POOL_STUB` / `POOL_STUB_INCOMPLETE` / `INFRA_INSIDE_SNAPSHOT` / `SMOKE4_FAILED` / `PUSH_FAILED` |

★ 与 `scripts/cloud/run_gate.sh` 的 2/9/4/5/7 **不通用**：那套是「租 ECS」的失败面（缺仓外配置 / 缺云机 / 播种对齐 /
补丁打不上 / 树陈旧），这套是「造快照」的失败面。两张表各自钉在自己的测试里，别混着记。

## 6. 真读数（2026-11-19）

镜像仓 `aweds13/eng-gate` 上真跑过**两**趟：先 job `135331686931`（run `44456198821`，head `cdb2c0fa`），
再 job `135640738507`（run `44547171433`，head `14220c7c` —— 这一趟的树是**仓里这份构建器**造的，
即 `scripts/cloud/gha/build_snapshot.py --stage all` 的产物）。两趟结论相同：23 门、`not_run` 空、全绿。

第二趟的读数原文（源：job `135640738507` 日志里 `=== GHA-GATE-READING-BEGIN/END ===` 之间那段 JSON，
本机落盘在 gates/enggate-logs 下的 win-135640738507.reading.json，不进仓）：

```
ok=True  host=runnervmm7ud1  rev=14220c7c  branch=main  n_gates=23  not_run=[]  at=2026-11-19T15:07:35
py=3.12.10  workers=4  bad=[]
```

逐门耗时（秒）。源：同一份读数的 `gates[].seconds`，全部 `exit_code=0`：

| 门 | 秒 | 门 | 秒 |
|---|---|---|---|
| `pytest` | 1256.27 | `ui_dom_probe` | 96.19 |
| `pytest_chain` | 884.91 | `proxy` | 96.76 |
| `ui_flow` | 787.57 | `commands` | 95.85 |
| `acceptance` | 157.29 | `ui_text` | 95.54 |
| `check_layers_selftest` | 151.62 | `style` | 95.21 |
| `audit` | 148.73 | `contrast` | 94.90 |
| `check_layers` | 137.99 | `skills_claims` | 94.45 |
| `web_live` | 132.38 | `lf1_live` | 97.14 |
| `docs` | 52.87 | `mypy` | 50.26 |
| `contract_doc_table` | 53.14 | `audit_titles` | 8.79 |
| `invariants` | 8.09 | `ruff` | 7.56 |
| `render` | 0（本机专用，复用） | | |

同源求和 **4603.51 s ≈ 76.7 min**；job 从起跑到结束 **1343 s ≈ 22.4 min**（源：GitHub Actions job 接口的
`started_at 2026-11-19T14:45:18Z` / `completed_at 2026-11-19T15:07:41Z`）—— 逐门 `seconds` 是**墙钟相加**，
4 worker 并行下远大于总时长，别拿它当 SLA。两趟差这么多是 **runner 负载差**，不是判据变严：
同一套门、同一份 `run_gates.py`，`pytest` 这一道从 821.79 s 涨到 1256.27 s。

## 7. 已知边界 / 债

1. **改不了 workflow** ⇒ 触发条件只能是 push `main`，没有 `workflow_dispatch`；要改判据集合、改 `runs-on`、加超时，
   必须换一个有 workflow scope 的 token 重建镜像仓（现在这条路是为了绕开那个 scope 才长成这样的）。
2. **镜像仓里还有三个继承来的作业**（`test` / `Smoke-build Firefox extension` / `Web guided-init E2E`），
   它们跑的是模板仓的代码，在本仓树上没意义、一直红 / skip ⇒ **整 run 的结论会显示 failure**，
   要看的是那个 `Windows HKCU autostart E2E` 作业本身，不是 run 的汇总脸色。
3. **快照是 `--force` 推的** ⇒ 镜像仓的历史**不是**本仓历史，只有 bundle 里带过去的那几笔 + 一笔快照提交。
   它是**证据仓**，不是镜像备份。
4. **`TZ=UTC` 是硬钉的**：runner 是 UTC、本机是 +08，`scripts/gen_pool_readme.py` 的 `resolve_date()` 只认
   `datetime.date.today()` ⇒ 不钉就会让快照里 README 的日期与 runner 现算差一天，连带一批 pytest 红。
5. **仓外号池桩每次现造**：它是零凭据的合成件，只为了让「号池目录在哪」这类判据有东西可读；
   它证明不了真号池能派活。

## 8. 第二仓（OpenMAIC）那条腿：真读数在，但**不是**这份脚本造的

任务书的验收里有一条是「OpenMAIC 仓能在云上跑出真的 vitest 读数」。这条腿今天的实际情况：

**有真读数**（源：镜像仓 `aweds13/om-gate` 的 run `43902435671`，head `19b46314`，
2026-11-16 四个 `Unit Tests (N/4)` 作业的日志汇总）：

| 分片 | Test Files | Tests | Duration |
|---|---|---|---|
| 1/4 | 4 failed / 277 passed / 17 skipped (298) | 14 failed / 3535 passed / 195 skipped (3744) | 144.13 s |
| 2/4 | 285 passed / 12 skipped (297) | 3483 passed / 80 skipped (3563) | 189.25 s |
| 3/4 | 5 failed / 284 passed / 8 skipped (297) | 8 failed / 3586 passed / 87 skipped (3681) | 224.03 s |
| 4/4 | 5 failed / 287 passed / 5 skipped (297) | 42 failed / 4123 passed / 86 skipped (4251) | 220.66 s |
| 合计 | 14 failed / 1133 passed / 42 skipped | 64 failed / 14727 passed / 448 skipped | 四片相加 ≈ 778 s |

**但它是 OpenMAIC 自己的 `ci.yml` 跑的**，不是本仓这份构建器：那次是把 OpenMAIC 树原样推上 om-gate、
由它仓里那份完整的 workflow（`--shard=N/4`、`setup-workspace` 复合 action、node 22）跑出来的。
本仓 `scripts/cloud/gha/` 下**只有 engineering 的构建器**（快照形状、适配器文件名、号池桩、23 道门全是
engineering 的），没有任何一行认识 vitest。

两条腿要分清：

| | 租 ECS（`run_gate.sh`） | 租 runner（本页） |
|---|---|---|
| 是否已经两仓通用 | **是**：`scripts/cloud/profiles/engineering.toml` 与 `openmaic.toml` 两份，骨架同一份 | **否**：只有 engineering 的构建器 |
| 证据 | `tests/test_cloud_profiles.py`（骨架里不许出现 engineering 字面、第二份 profile 禁 5 个专属键、渲染无缺键） | 本页 §6（engineering 两趟）+ 本节（OpenMAIC 是它自己的 CI 跑的） |

要把这条腿也做成通用，缺的是**一个 `--repo` 化的构建器**：快照从哪个仓取、适配器叫什么名字、
开跑前装什么、跑什么命令、产物在哪 —— 这些在这条路上今天全是硬编码，等价于 ECS 那条路的
`profiles/<仓>.toml`。另外 om-gate **没有** eng-gate 那种「workflow 被冻结、推不上去」的约束
（它那份 `ci.yml` 是可以改的），所以第二仓的适配层不需要绕 workflow scope，形状可以不一样。

**别把这一节读成「已经通用」**：工程上成立的只有「判据仍在仓内、runner 只在外面跑」这一条原则两仓共享；
脚本层面，今天是一仓一份。

