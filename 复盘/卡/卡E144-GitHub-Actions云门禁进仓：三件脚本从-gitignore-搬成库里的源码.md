# 卡 E144 · GitHub Actions 云门禁进仓：把「只在 gates/diag/_tmp 里活着的三件脚本」搬成库里的可执行源码

> 台账号 `T-AG659`｜分区 E（门禁与可信度）｜树 .wt/E144｜层 判据层｜基准 `a1c5f930`（立卡时主树 HEAD）｜depends 无
> 依据：engineering 23 道门已在 GitHub Actions 的 windows-latest 上跑出真读数（run `44456198821` / job `135331686931` / rev `cdb2c0fa` / `ok=true` / `host=runnervmm7ud1` / `not_run=[]`），但产出这个读数的三件脚本住在 `gates/diag/_tmp/`（`.gitignore:70 gates/diag/` 忽略）⇒ 换一台机器、换一个人，这条路线**不存在于仓里**。
> 行号按 2026-11-19 主树 `a1c5f930` 现场复核：`gates/diag/_tmp/gha_eng_build4.py`（297 行）/ `gha_shim_autostart.py`（579 行）/ `gha_conftest_shim.txt`（2003 B）。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · 这条路线今天不在仓里，只在一个人机器的 gitignore 目录里

    $ git check-ignore -v gates/diag/_tmp/gha_eng_build4.py
    .gitignore:70:gates/diag/	gates/diag/_tmp/gha_eng_build4.py

三件脚本的指纹（`sha256`）：`gha_eng_build4.py` `4e4e5a12…`（15797 B）、`gha_shim_autostart.py` `712d5eae…`（24730 B）、`gha_conftest_shim.txt` `d0553fb4…`（2003 B）。都**未被跟踪**。

### 问题 2 · 构建器里写着四个本机字面，搬进 `scripts/cloud/` 必被可移植性判据咬

`tests/test_ci_portability.py:231 SCAN_SUFFIXES = {".sh", ".ps1", ".py", ".bash"}` + `:306-321 _scan_targets()` 对 `scripts/cloud/**` 逐个 `rglob` ⇒ 放进 `scripts/cloud/gha/` 的 `.py` 会被逐行扫。当前四处命中：

| 行 | 原文 | 规则 |
|---|---|---|
| `:4` | `ROOT = r'D:/repo/engineering'` | 本机 D 盘 |
| `:33` | `IPS = ['4.237.22.38', '140.82.116.4', …]` | 硬编码 IP |
| `:42` | 注释里的 `~/.ssh/id_ed25519_enggate` | 裸 ~/.ssh |
| `:46` | `'ssh -i C:/Users/example/.ssh/id_ed25519_enggate …'` | 用户目录 |

另外 `:33-37` 的 `IPS` / `GH_IP` / `def net(ip)` 是**死代码**：全文 `grep -n 'net('` 只命中定义那一行，一次都没被调用（2026-11-18 16:30 之后改走 SSH + deploy key）。

### 问题 3 · 适配器自己写着「只存在于 GHA 快照里，不进 engineering 主树」

`gha_shim_autostart.py:1` 的 docstring 第一行就是这句话。搬进库之后这句必须改成真话，否则下一个读者会以为它是临时件、随手删掉。

### 问题 4 · 仓库文档还写着「不引入外部 CI 服务」，与今天的做法相反

`docs/subsystems/ci/README.md:78` 原文：`- 不引入外部 CI 服务：这套的价值是"判据在仓内、可读可改"。`（`git grep '外部 CI'` 全仓唯此一处，**没有测试钉它**）。这条边界要么改口、要么说明为什么现在破了 —— 不能装作不存在。

### 问题 5 · 退出码表是血换来的，但只活在注释里，没有一条判据钉住

构建器的失败码：`3`（bundle/fetch/workflow 取不回来）、`4`（提交失败）、`5`（conftest 已有 `pytest_addoption` / 台账已豁免 / 缺证据文件）、`6`（池桩缺失或不完整 / `projects.toml` root 没改写 / 快照里出现 `infra/`）。这些今天只由 `log('XXX'); sys.exit(n)` 表达，**没有任何测试**读它们 ⇒ 下次改脚本把 `6` 写成 `5`，没人会知道。

## 判据（7 条，逐条可执行）

### 判据 1 · 三件脚本进库，且命名与职责一一对应

scripts/cloud/gha/build_snapshot.py（计划建）（构建 + 冒烟 + 推送）、scripts/cloud/gha/adapter.py（计划建）（runner 侧的适配器）、scripts/cloud/gha/conftest_shim.txt（计划建）（覆盖率选项垫片）三份都在 `git ls-files` 里，且 `build_snapshot.py --help` 能跑（`--stage` / `--dest` / `--remote` 三个选项在）。

### 判据 2 · 零本机路径、零硬编码 IP

`scripts/cloud/gha/*.py` 里 `D:[\/]`、`C:[\/]Users[\/]`、`~[\/]\.ssh[\/]`、四段式 IP 全部 0 命中（`tests/test_ci_portability.py` 自动覆盖，且**不许往 `WHITELIST` 里加条目**）。`ROOT` 改由 `git rev-parse --show-toplevel` 现算；远端 URL 与 `GIT_SSH_COMMAND` 走环境变量，缺了就退 2 并说清缺哪个。

### 判据 3 · 退出码仍然可区分，并且有判据钉住

tests/test_gha_cloud_gate.py（计划建） 对每个失败码断言一次：源文件里有 `exit_code("XXX", 3)` 之类的**可读常量表**（`EXIT_*`），并逐条对应到真实 `sys.exit()` 调用点；同时断言 `2`（缺环境）、`3`、`4`、`5`、`6` 五个值互不相同。

### 判据 4 · 适配器在本机是惰性的（收集得到、不干活）

`python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider <本机路径下的 adapter 副本>` 在没有 `GITHUB_ACTIONS=true` 时**必须绿**（`test_windows_runner_runs_the_gates` 直接 return），且不许写任何文件。反向：`GHA_GATE_ADAPTER=1` 时也不干活（防递归）。

### 判据 5 · 适配器的两个 helper 行为不靠 runner 才能验

`_ensure_pool_stub()` 与 `_ensure_diag_fixtures()` 在两个临时目录上可跑（ROOT 指向 `tmp_path`）：前者把四件桩写到 `ROOT/../infra/pool` 并返回 `projects.toml` 路径（且**仓内**出现不了 `infra/`），后者写三份 `wb-*.jsonl` 到 `ROOT/gates/diag/`。

### 判据 6 · 文档改口，且是对的改口

docs/subsystems/ci/GitHub-Actions-云门禁.md（计划建） 存在，写明：外部 runner + 判据仍在仓内、冻结 workflow 为什么不能改（token 无 workflow scope）、tests/test_windows_autostart_e2e.py（计划建） 这个文件名为什么不能改、23 门真读数（带 `源：`）、以及**它服务的是 engineering**（OpenMAIC 走另外一条）。`README.md:78` 那条边界改成「外部 runner 可以，判据必须在仓内」，并链到新文档。

### 判据 7 · 派生文档跟着重算

`docs/INDEX.md` 的 `| docs/subsystems/ci/ | 6 | 0 | 6 |` 与清单块跟着变成 7；`python -X utf8 scripts/check_derived_docs.py --check` 绿（或在落地链 ⓪ 里被重算成绿）。

## 交付

1. scripts/cloud/gha/build_snapshot.py（计划建）：由 `gha_eng_build4.py` 改写（删 `IPS`/`net()`/本机 `ROOT`/`C:/Users` 私钥；`ROOT` 走 `git rev-parse --show-toplevel`；`--dest`/`--remote`/`--stub`/`--adapter`/`--conftest-shim`/`--stage` 五个参数 + 环境变量兜底；失败码表提成模块常量）。
2. scripts/cloud/gha/adapter.py（计划建）：由 `gha_shim_autostart.py` 改写（docstring 改口；其余逐字保留——它是**在 runner 上真跑过 23 门全绿**的那一份）。
3. scripts/cloud/gha/conftest_shim.txt（计划建）：原样搬（2003 B，逐字节）。
4. tests/test_gha_cloud_gate.py（计划建）：判据 1/3/4/5 的钉子。
5. docs/subsystems/ci/GitHub-Actions-云门禁.md（计划建）（新）+ `docs/subsystems/ci/README.md` §6 改口。
6. `docs/INDEX.md` 与清单块（派生，落地链 ⓪ 重算）。

## 验收（4 条，落地前自跑）

    cd .wt/E144
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_gha_cloud_gate.py
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_ci_portability.py
    python -X utf8 -m ruff check scripts/cloud tests/test_gha_cloud_gate.py
    python -X utf8 scripts/check_derived_docs.py --check

门槛：① 新测试全绿；② 可移植性判据仍 20 passed（**没往白名单加条目**）；③ ruff 无告警；④ 派生文档一致。

## 不许做

- 不许改 tests/test_windows_autostart_e2e.py（计划建） 这个名字（冻结 workflow 的最后一个步骤写死它；本 token 无 workflow scope，改不了 workflow）。
- 不许往 `tests/test_ci_portability.py:WHITELIST` 里加条目来绕判据 2。
- 不许动 `gates/diag/_tmp/` 下的原件（它们是已经跑绿过的那一份；搬库是**复制+改造**，不是剪切）。
- 不许把适配器的 `pip install` 清单改成不钉版本（`scripts/cloud/bootstrap.ps1:50-62` 那十一条是一路试出来的）。
- 不许在适配器里设 `TF_WEB_LIVE_JSON_RETRY`（`tests/test_web_live_json_retry.py:204` 硬断言默认只重放 1 次）。

## 直做（已实测）

- 三件源的真实大小与 sha256 见「问题 1」。
- `net()` 是死代码：`grep -n 'net('` 只命中 `:37`。
- `tests/test_ci_portability.py` 当前基线 **20 passed (1.79s)**。
- `docs/subsystems/ci/` 现有六份，`docs/INDEX.md:36` 是 `| docs/subsystems/ci/ | 6 | 0 | 6 |`。
- 23 门真读数（不入库的读数产物 gates/enggate-logs/win-135331686931.reading.json）：`ok=True / host=runnervmm7ud1 / rev=cdb2c0fa / n_gates=23 / not_run=[] / workers=4`。
