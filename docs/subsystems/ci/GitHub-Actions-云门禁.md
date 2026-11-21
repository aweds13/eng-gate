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
python -X utf8 scripts/cloud/gha/build_snapshot.py --repo engineering --stage all
```

`--repo` 选哪一份 profile（默认 `engineering`，`GHA_REPO` 同效）；仓与仓的差别全在那份 profile 里，见 §8。

`--stage` 四选：`build` / `smoke` / `push` / `all`。三段各自能单跑，`all` 是串起来。
除 `build` 之外的每一段都**在已有的快照目录上干活**（`smoke` 还会往 `<快照的父目录>/infra/pool` 造桩、
往 `<快照>/gates/diag` 写 fixture）⇒ 目录不在就**先退 2**（`MISSING_DEST`），不往下走：
以前这里不判，`push` 会甩一个 `NotADirectoryError: [WinError 267]` 的栈、`smoke` 更糟 ——
三段全红却退 0（卡 E145 实测）。

**build —— 造一棵能推的快照树**（默认落在 `<tmp>/<profile 的 snapshot.dir_name>`，被 `.gitignore` 挡住）。
下面以 engineering 那份 profile 为例；哪几步做、做多少，全由 profile 的键决定（§8.1）：

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

第 2 步之后还有一道**静态体检**（`[snapshot].require_files` 与 `require_text`）：profile 说「快照里必须真有这几件 / 必须含这几行字样」，
缺一件就退 5。它挡的是「装错树」—— 装依赖要十几分钟，装完才发现跑的不是那个仓，是最贵的失败方式。
这一步不联网、不装依赖，几秒钟。

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
| 2 | `EXIT_CONFIG` | 缺配置：profile 不成立 / 没给远端 / 没给 `GIT_SSH_COMMAND` / 适配器、垫片或要装的 workflow 文件不在 / 快照目录不在 | `PROFILE_INVALID` / `MISSING_REMOTE` / `MISSING_GIT_SSH_COMMAND` / `MISSING_ADAPTER` / `MISSING_WORKFLOW_SRC` / `MISSING_DEST` |
| 3 | `EXIT_HISTORY` | 历史或 workflow 拿不到（bundle / fetch / `.github` checkout） | `BUNDLE_FAILED` / `FETCH_FAILED` / `WORKFLOW_CHECKOUT_FAILED` |
| 4 | `EXIT_COMMIT` | 本地提交失败 | `COMMIT_FAILED` |
| 5 | `EXIT_SNAPSHOT` | 快照形状不对（垫片撞车 / 豁免块已在 / 证据文件不在 / profile 点的必存文件或必含字样缺了），或冒烟有红色 | `CONFTEST_ALREADY_HAS_ADDOPTION` / `LEDGER_ALREADY_EXEMPT` / `MISSING_EVIDENCE_FILE` / `MISSING_REQUIRED_FILE` / `MISSING_REQUIRED_TEXT` / `SMOKE_FAILED` |
| 6 | `EXIT_POOL` | 号池桩不对，或仓内混进了 `infra/`，或推前判据红 / 推失败 | `MISSING_POOL_STUB` / `POOL_STUB_INCOMPLETE` / `INFRA_INSIDE_SNAPSHOT` / `SMOKE4_FAILED` / `PUSH_FAILED` |

★ 与 `scripts/cloud/run_gate.sh` 的 2/9/4/5/7 **不通用**：那套是「租 ECS」的失败面（缺仓外配置 / 缺云机 / 播种对齐 /
补丁打不上 / 树陈旧），这套是「造快照」的失败面。两张表各自钉在自己的测试里，别混着记。

## 6. 真读数（最近一趟 2026-11-21：23 门全绿，骨架自己跑的那一趟）

镜像仓 `aweds13/eng-gate` 上**最近一趟**是 job `136685943795`（run `44852205296`，head `97d009e5`）。
这一趟就是**仓里这份 profile 骨架**自己跑出来的：`scripts/cloud/gha/build_snapshot.py` 带
`--repo engineering --stage all` 从主树 `37a09b98` 造快照、提交成 `97d009e5`、推 `main`，再由镜像仓那个冻结的
`Windows HKCU autostart E2E` 作业执行。读数：23 门、`not_run` 空、**红门 0 个**；`render` 是唯一 `EXCLUDED`
（金样本采集自主机 `DEV-HOST`，runner 上不跑，**不算红**）。

读数原文（源：job `136685943795` 日志里 `=== GHA-GATE-READING-BEGIN/END ===` 之间那段 JSON；
本机落盘在 gates/enggate-logs 下，不进仓）：

```
ok=True  host=runnervmbpeip  rev=97d009e5  branch=main  n_gates=23  not_run=[]  at=2026-11-21T02:04:05
py=3.12.10  workers=4
```

逐门耗时（秒）。源：同一份读数的 `gates[].seconds`，22 门 `exit_code=0`、`render` 为 `EXCLUDED`：

| 门 | 秒 | 门 | 秒 |
|---|---|---|---|
| `pytest` | 938.20 | `contrast` | 90.77 |
| `pytest_chain` | 583.66 | `style` | 91.17 |
| `ui_flow` | 636.37 | `check_layers_selftest` | 90.53 |
| `web_live` | 104.73 | `skills_claims` | 95.41 |
| `acceptance` | 105.15 | `contract_doc_table` | 37.88 |
| `audit` | 106.18 | `mypy` | 37.65 |
| `check_layers` | 105.02 | `docs` | 33.43 |
| `lf1_live` | 92.93 | `audit_titles` | 7.11 |
| `proxy` | 92.59 | `invariants` | 6.62 |
| `ui_dom_probe` | 92.26 | `ruff` | 5.74 |
| `commands` | 91.81 | `render` | 0（本机专用，`EXCLUDED`） |
| `ui_text` | 91.49 | | |

同源求和 **3536.7 s ≈ 58.9 min**；job 从起跑到结束 **1015 s ≈ 16.9 min**（源：GitHub Actions job 接口的
`started_at 2026-11-21T01:47:16Z` / `completed_at 2026-11-21T02:04:11Z`）—— 逐门 `seconds` 是**墙钟相加**，
4 worker 并行下远大于总时长，别拿它当 SLA。

两处要看清楚，别把这张表读成「每门都判完了」：

- `docs` 那门的 `summary` 原文是 `CHECK_DOCS: 没判完（有 skip）—— 不许当 PASS`，`exit_code=0` 只说明
  它没超基线；「判不出」的那批条目在 runner 上照样判不出。
- `pytest` 那门的 `summary` 原文是 `5458 passed, 5 skipped, 1 xfailed`，与更早几趟的数字不同属正常
  （树在变），能比的是「红门 0 个」这一条。

前一趟（同一份构建器、profile 骨架落地后的第一趟）是 job `136613578025`（run `44830398970`，head
`190903a0`）：同为 23 门全绿、`pytest` 1135.26 s、同源求和 4464.59 s、job 1217 s。两趟连着全绿，
说明那一趟不是侥幸。

再往前，2026-11-19 真跑过两趟：job `135331686931`（run `44456198821`，head `cdb2c0fa`，886 s）与
job `135640738507`（run `44547171433`，head `14220c7c`，1343 s），同为 23 门全绿；那两趟的 `pytest` 分别
821.79 s / 1256.27 s，同源求和 4603.51 s。四趟之间差这么多是 **runner 负载差**，不是判据变严 ——
同一套门、同一份 `run_gates.py`。

最早 head `1e815a96` 那趟（job `136403301980`）是 22 绿 1 红：唯一红门
`tests/test_pool_limits_data.py::test_limits_path_is_the_one_we_document`（判据把「宿主机绝对路径」写死成
本机那一条，runner 上必然不等），已由卡 E148（`T-AG681`）改成位址规则修掉 —— 上面这几趟全绿都在它之后。

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

## 8. 每仓一份 profile：同一份骨架服务第二个仓

§2 那种「形状被冻结的 workflow 倒推出来」的做法是 **engineering 专有的**。第二仓不该复制一遍它 ——
复制两份脚本就会各自漂，这正是 ECS 那条路当初抽出 `profiles/<仓>.toml` 的理由。所以这里也一样：
骨架只认键，仓与仓的差别全在 `scripts/cloud/gha/profiles/<仓>.toml`，由 `--repo` 选。

```powershell
$env:GHA_REMOTE = "<远端仓 URL>"
python -X utf8 scripts/cloud/gha/build_snapshot.py --repo engineering --stage all
python -X utf8 scripts/cloud/gha/build_snapshot.py --repo openmaic    --stage all
```

`--repo` 收仓名（`profiles/<仓>.toml`）或一份 `.toml` 的路径；名字与文件名对不上、出现未知的段 / 未知的键、
跨键自相矛盾（例如 `from_remote_workflows = true` 同时又要装自己的 workflow）一律退 2 + `PROFILE_INVALID` ——
拼错的键静默生效就等于「profile 写了但没人读」。

### 8.1 两份 profile 的差别（就是「仓无关」的全部内容）

| 键 | `profiles/engineering.toml` | `profiles/openmaic.toml` | 为什么不同 |
|---|---|---|---|
| `sync.mode` | `bundle`（整段历史） | `tree`（只要当前树内容） | OpenMAIC 的源树是**浅克隆**，`git bundle create` 打出来是断链，fetch 报 `did not send all necessary objects` —— 那不是网络坏，是历史不完整；这条路本来也不要它的历史 |
| `snapshot.from_remote_workflows` | `true` | `false` | engineering 的 workflow 在镜像仓冻结（§2）；OpenMAIC 的 workflow 归它自己，树里带过来的就是对的 |
| `adapter.enabled` | `true`（快照里装成 `test_windows_autostart_e2e.py`，路径见 `adapter.snapshot_name`） | `false` | 只有冻结作业那一步写死了文件名才需要适配器；OpenMAIC 由它自己 `ci.yml` 的 `unit` 作业跑 |
| `pool.stub` | `true`（五件号池桩 + 改写 root） | `false` | 号池是 engineering 的仓外依赖 |
| `snapshot.ledger_exempt` / `task` | 三条 + `T-AG526` | 空 | 审计门的 trailer 判据只在有台账的仓成立；没台账还写 `Task:` 就是伪造出处 |
| `snapshot.require_text` | 空 | 三条（`engines.node` / vitest include / ci.yml 的 `--shard=`） | 「这棵树是不是我以为的那棵」按仓各自的锚点判，几秒钟、不装依赖 |
| `smoke` | 18 条定向 pytest + ruff 六目录 + `check_docs` | 两条不装依赖的命令（node 版本契约、`pnpm --lockfile-only`） | 冒烟要「几秒、但真的会红」，不能付十几分钟的安装费 |

两套 profile 目录**刻意分开**（`scripts/cloud/profiles/` 是 ECS 那条路的，`scripts/cloud/gha/profiles/` 是本页的）：
它们认的键不是一套，混在一起会让「这份 profile 喂给哪个骨架」只能靠猜。

### 8.2 判据：engineering 逐字不变

「不复制脚本」的代价是「抽骨架时会不会顺手改了 engineering 的行为」。这条不靠眼力，靠两趟对比：
同一 HEAD 上分别用**改动前**的构建器与**改动后**的骨架各造一棵快照，再逐行比：

```
git ls-tree -r HEAD  # 两边各 2793 条
only old 0 / only new 0
```

另外 `tests/test_gha_cloud_gate.py` 里三条钉子盯着这一层：`test_skeleton_has_no_repo_specific_literals`
（骨架源码里不许出现 `test_windows_autostart_e2e.py` / `T-AG526` / `gate: engineering` / `models.whitelist.toml`）、
`test_every_profile_in_the_directory_loads`（每份都得读得动）、
`test_second_repo_profile_has_no_engineering_keys`（第二仓禁 `TF_PROJECTS_TOML` / `models.whitelist.toml` / `line/impl-v1`）。

### 8.3 真读数：OpenMAIC 的 vitest 是它自己 `ci.yml` 跑的（这一节要说清楚边界）

源：镜像仓 `aweds13/om-gate` 的 run `44753382083`，head `92f3c6fe`（2026-11-20），
四个 `Unit Tests (N/4)` 作业的日志汇总（runner 上 `node v22.23.4`）：

| 分片 | Test Files | Tests | Duration |
|---|---|---|---|
| 1/4 | 4 failed / 277 passed / 17 skipped (298) | 14 failed / 3535 passed / 195 skipped (3744) | 184.06 s |
| 2/4 | 285 passed / 12 skipped (297) | 3483 passed / 80 skipped (3563) | 133.54 s |
| 3/4 | 5 failed / 284 passed / 8 skipped (297) | 8 failed / 3586 passed / 87 skipped (3681) | 184.63 s |
| 4/4 | 5 failed / 287 passed / 5 skipped (297) | 42 failed / 4123 passed / 86 skipped (4251) | 215.49 s |
| 合计 | 14 failed / 1133 passed / 42 skipped | 64 failed / 14727 passed / 448 skipped | 四片相加 ≈ 717.7 s |

★ **边界**：这一趟的树是本页这份构建器推上去的（`--repo openmaic --stage push`），但**读数不是它打的** ——
是 OpenMAIC 自己那份 `ci.yml` 的 `unit` 作业打的。骨架在这条腿上的职责只是「把正确的树送上正确的仓」，
「跑什么」由那个仓自己的 workflow 说了算。这不是妥协：判据仍在仓内（`vitest.config.ts` + `tests/**/*.test.ts`），
runner 只在外面跑 —— 与 §0 那条原则一致。

所以「构建器认不认 vitest」这件事，答案是**它不需要认**：骨架里没有一行 vitest，`--repo openmaic` 与
`--repo engineering` 走的是同一段代码，差别全在上表那些键里。

### 8.4 这条腿今天的边界

1. **仍然改不了 workflow**：本机的 token 没有 workflow scope（§2、§7.1）。om-gate 的 `ci.yml` 不是我们改的，
   它原本就在那棵树里、原本就按 `--shard=N/4` 跑。要换触发条件 / 换 `runs-on`，同样得有 workflow scope。
2. **`[workflow].install` 这条键今天没有使用者**：它是给「仓自己的 workflow 不认我们这套 BEGIN/END 读数、
   但仓又能自己写 workflow」的那种仓准备的。两个仓都不在这个交集里 —— engineering 改不了，OpenMAIC 不需要。
   键留着，但没跑过就别说它行。
3. **读数的形状不一样**：engineering 那边是适配器把 `gates/last.json` 包在 `=== GHA-GATE-READING-BEGIN/END ===`
   里打出来（一个 JSON，23 道门）；OpenMAIC 那边是 vitest 自己的四段汇总行，没有统一的 JSON 外壳。
   想要统一形状，得给第二仓写一个适配器 + 装一份自己的 workflow —— 那是另一张卡的活。

