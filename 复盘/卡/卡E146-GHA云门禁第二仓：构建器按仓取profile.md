# 卡 E146 · GitHub Actions 云门禁第二仓：构建器改成按 profile 取形状（骨架 + 每仓一份）

> 台账号 `T-AG680`｜分区 E（门禁与可信度）｜树 .wt/E146｜层 判据层｜基准 `bc41ba76`（立卡时主树 HEAD `926e9948` 之前）｜depends E145
> 依据：E144（`99b9a58a`）把构建器/适配器/垫片搬进库，E145（`6495fbeb` 前后）给构建器收了「缺 dest 退 2 / 冒烟红退 5」两个口子。两笔之后 `scripts/cloud/gha/build_snapshot.py` 仍然是**一仓一份**：快照形状、适配器文件名、号池桩、台账豁免块、冒烟跑哪 18 条 pytest，全部写死在脚本里。docs/subsystems/ci/GitHub-Actions-云门禁.md §8 当时写的结论就是这个 ——「缺的是**一个 --repo 化的构建器**」。

## 要解决的问题（逐条实测）

### 问题 1 · 骨架里写死着 engineering 的形状

`scripts/cloud/gha/build_snapshot.py`（E145 后 470 行）里：`DEFAULT_TASK = "T-AG526"`、`RUFF_PATHS` 六目录、`SMOKE_TARGETS` 18 条 engineering 定向 pytest、`SMOKE4_TARGETS` 两条、`POOL_NEED` 四件号池桩、适配器落地文件名 `tests/test_windows_autostart_e2e.py`、提交标题 `gate: engineering 23 gates on windows-latest (adapter v18)`。⇒ 换一个仓只能复制一份脚本改改，两份必然各自漂移 —— 这正是任务书（m00001）明令不许的形态。

### 问题 2 · 第二仓（OpenMAIC）在 GHA 这条腿上没有入口

任务书验收②「OpenMAIC 仓能在云上跑出真的 vitest 读数」在 ECS 那条腿成立（OM5 留档：Test Files 22 failed | 1073 passed | 41 skipped (1136) / Tests 46 failed | 13749 passed | 488 skipped (14283)），在 GHA 这条腿**当时不成立**：om-gate 上那几趟（run 43902435671 / 44053767864）都是把 OpenMAIC 树推上去、由**它自己的 ci.yml** 跑的，本仓脚本一行都不认识 vitest。

### 问题 3 · 「一份脚本两仓通用」这件事从来没有被真跑验证过

只有「engineering 能跑」这一个样本时，任何抽象都可能是照着 engineering 长的。第二仓必须真跑出读数，否则「仓无关」只是说法。

## 判据（逐条可执行）

### 判据 1 · 骨架里不许再有 engineering 专属字面

`scripts/cloud/gha/build_snapshot.py` 正文不许含这四个字面：适配器落地文件名 `test_windows_autostart_e2e.py`、`T-AG526`、`gate: engineering`、`models.whitelist.toml`。由 `tests/test_gha_cloud_gate.py::test_skeleton_has_no_repo_specific_literals` 钉住。

### 判据 2 · 仓与仓的差别全在 `scripts/cloud/gha/profiles/<仓>.toml`，且每份都读得动

新增 `scripts/cloud/gha/gate_profile.py`（子命令式加载器：`SCHEMA` 十段 + `_cross_check` 十一条交叉约束 + `load()` / `list_repos()` / `shell_split()`）与两份 profile：engineering 一份（逐字复刻既有行为）、openmaic 一份（node 腿）。未知段 / 未知键一律 `ProfileError`（拼错的键静默生效 = 配置没人读）。由 `test_every_profile_in_the_directory_loads` 钉住。

### 判据 3 · 第二仓那份 profile 里 engineering 专属键一个都不许出现

`profiles/openmaic.toml` 正文（含注释）不许含 `TF_PROJECTS_TOML` / `models.whitelist.toml` / `line/impl-v1`。由 `test_second_repo_profile_has_no_engineering_keys` 钉住。同时该 profile 必须把 python 那套机械**关掉**：`adapter.enabled = false`、`pool.stub = false`、`snapshot.ledger_exempt = []`、`task = ""`（没有台账却写 Task trailer = 伪造出处）。由 `test_second_repo_profile_turns_the_engineering_machinery_off` 钉住。

### 判据 4 · 退出码表不扩充，`--repo` 指到不存在的 profile ⇒ 退 2

仍是 0/2/3/4/5/6 六个值；`PROFILE_INVALID` 走 `EXIT_CONFIG`，不许抛 traceback。由 `test_unknown_repo_fails_fast_with_config_code` 与既有的 `test_exit_codes_are_five_distinct_values` 一起钉住。

### 判据 5 · engineering 行为逐字不变（这是判据，不是口号）

用同一棵主树、同一份仓外号池桩，分别用 **改动前（HEAD 版构建器）** 与 **改动后（profile 驱动）** 各造一次快照，`git ls-tree -r HEAD` 必须**逐行相同**；同一份 `--stage smoke` 也必须同色（实测两边都 rc=0：SMOKE1 46 passed / SMOKE2 All checks passed / SMOKE3 死指针 147 基线 147）。

### 判据 6 · 第二仓（OpenMAIC）在 GHA 上出真 vitest 读数

用新骨架 + `profiles/openmaic.toml` 把 OpenMAIC 树打成快照推上镜像仓，由那边的 ci.yml 四个 `Unit Tests (N/4)` 分片跑出 `Test Files` / `Tests` / `Duration` 三行读数，且与 ECS 侧 OM5 留档同口径。

## 交付

1. `scripts/cloud/gha/gate_profile.py`（新文件）：profile 加载器 + 交叉约束。
2. `scripts/cloud/gha/profiles/engineering.toml` / `openmaic.toml`（新文件）。
3. `scripts/cloud/gha/build_snapshot.py`：改成 profile 驱动 —— `--repo` 选 profile；build 段按 `snapshot.*` 装 workflow / 查 require_files / require_text / 装适配器 / 写豁免块 / 保证据文件 / 跑生成器；smoke 段按 `smoke.*` 跑；push 段按 `sync.mode` 决定「没有第二笔可提交」是不是失败。新增 `_resolve_argv0()`（PATHEXT 解析）、`_exec_bits()` / `_restore_exec_bits()`（Windows 造 Linux 快照保住 100755）。
4. `tests/test_gha_cloud_gate.py`：加判据 1/2/3/4 的六条用例。
5. `docs/subsystems/ci/GitHub-Actions-云门禁.md`：§3 改成 profile 驱动的三段；§8 从「第二仓那条腿不是这份脚本造的」改成「已经由这份脚本造出来，读数如下」，并把判据 5 的逐行对比写成真读数。
6. 文书片段（changelog / traceability / 交接）由 `tools/wb_stage_card.py` 现生成，**不许手写**。

## 验收（落地前自跑）

    cd .wt/E146
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_gha_cloud_gate.py tests/test_cloud_profiles.py tests/test_cloud_sync.py tests/test_ci_portability.py
    python -X utf8 -m ruff check scripts/cloud tests/test_gha_cloud_gate.py
    python -X utf8 scripts/check_derived_docs.py --check

门槛：① 81 passed（本卡现场读数）；② ruff 无告警；③ 派生文档一致；④ 判据 5 的逐行对比与判据 6 的 vitest 读数都要落到交接里（读数不许写成「大概对」）。

## 不许做

- 不许把构建器复制成两份（`build_snapshot_openmaic.py`）：那就是任务书点名不许的形态。
- 不许为了第二仓往 `scripts/cloud/gha` 里塞 engineering 专属键的例外开关；差别只能落在 profile 里。
- 不许给 `EXIT_*` 加新值，也不许把 `run_gate.sh` 的 2/9/4/5/7 往这张表上套（两套失败面不同）。
- 不许改 `scripts/cloud/gha/adapter.py`（它是 runner 上真跑过 23 门全绿的那一份）。
- 不许为了让 vitest 变绿去改 OpenMAIC 的测试或源码：本卡只负责「把树原样搬上去、让它自己的 ci.yml 跑」。
- 不许在文书里用反引号写仓外快照路径或本机日志路径（E144/E145 各因此吃过一次死指针）。

## 直做（已实测）

E146 现场读数：主树 HEAD `926e9948`、`git status --porcelain -uno` 空、台账锁空着；`.wt/E146` 建在 `bc41ba76` 上，未提交 5 件（build_snapshot.py / gate_profile.py / 两份 profile / tests）；`grep -c 'id = "E146"' docs/workbacklog.toml` ⇒ 0；待派 24 张卡与本卡文件零交集。
