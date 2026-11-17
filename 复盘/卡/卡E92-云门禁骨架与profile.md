# 卡 E92 —— 云门禁泛用化：抽「仓无关骨架 + 每仓一份 profile」，让第二个仓能跑（T-AG600）

> 台账号 `T-AG600` ｜ 分区 E ｜ 树 `.wt/E92` ｜ 层 判据层
> 依据：卡 E35（run_gate.sh 从 gates/diag 搬进库、成为被 review 的源码）、卡 E49（空补丁 / 提交号从卡树取）、
> 卡 E54（云机 HEAD ≠ 目标要退 7）、卡 E84（SSH 保活 + 云侧先落盘）、卡 E90（5/5 取回不许冲掉本机现场的头）。
> 用户任务书原文见本卡「要解决的问题」；四条验收由用户逐条点名。

## 要解决的问题

`scripts/cloud/run_gate.sh` 是**只服务本仓**的：cloud_dir、分支 `line/impl-v1`、`TF_PROJECTS_TOML`、
`C:/infra/pool` 的白名单、`pip install -e ".[dev]" -c C:/pins.txt`、`scripts/run_gates.py --seal`、
`gates/diag/seed-<卡>` 播种、`.wt/<卡>` 卡树……全写死在脚本里。第二个仓
（OpenMAIC，独立 package.json / pnpm / vitest，无 `gates/`、无 `scripts/run_gates.py`）一行都用不上。

要求不是「复制一份脚本改改」（两份必定各自漂移），而是：

1. **仓无关骨架**：把「血换来的行为」留在 `scripts/cloud/run_gate.sh`，且**一行本仓字面都不留**；
2. **每仓一份适配层** `scripts/cloud/profiles/<仓>.toml`，只写「这个仓跑什么」；
3. 渲染器 `scripts/cloud/profile.py` 把 profile 的值喂回骨架（`--render` 给人和测试看，真跑走 dump）；
4. 本仓行为**逐字不变**——现有 22 门全绿那趟要能原样重跑（这是判据，不是口号）。

## 判据（6 条，逐条可执行）

1. **骨架零本仓字面**：`scripts/cloud/run_gate.sh` 的**可执行行**不含
   `C:/eng` / `line/impl-v1` / `TF_PROJECTS_TOML` / `models.whitelist` / `C:/infra/pool` /
   `run_gates.py` / `C:/pins.txt` / `Python312` / `cloud-4of5`；
   唯一允许的是 `TF_CLOUD_PROFILE` 的缺省值 `$HERE/profiles/engineering.toml`。
   钉子：`tests/test_cloud_profiles.py`（扫可执行行，逐条点名）。
2. **profile 覆盖全部差异**：`scripts/cloud/profile.py` 的 `dump` 出 **38 个键**；
   `check` 两份 profile 都是 `OK …：共 38 个键，无重复、无换行`；
   `--render` 两份产物都 `bash -n` 退 0 且 stderr 无「profile 没给的键」。
3. **另一仓的 profile 不带本仓键**：`scripts/cloud/profiles/openmaic.toml` 全文零命中
   `TF_PROJECTS_TOML` / `models.whitelist` / `line/impl-v1` / `C:/infra/pool` / `run_gates.py`。
   钉子：`tests/test_cloud_profiles.py::test_second_profile_carries_no_engineering_keys`。
4. **本仓行为逐字不变**：用新骨架真跑一趟，`.wt/<卡>/gates/last.json` 的
   `ok=True` / `host=gates-runner-host` / `n_gates=22` / 阻断门红 `[]` / `tree` 指纹与改造前**逐字节相同**
   （实测 `4d32e9e01ddab872c2f13373af9179e8e3ac45c3`）。
5. **另一仓跑出真读数**：OpenMAIC 在云机跑完 `pnpm exec vitest run`，5/5 之后
   `—— profile 的读数：` 真的打出 `Test Files / Tests / Errors / Duration` 五行（不是「配不上就跳过」）。
6. **fail-fast 退出码可区分**：2（缺仓外配置 / profile 读不出 / 缺日志路径 / 命中残留）、
   9（缺 `CLOUD_HOST`）、4（清进程 / 播种 / 对齐）、5（白名单 / 铺盘 / 补丁打不上）、
   7（云机 HEAD ≠ 目标）—— 每条都实测过。

## 交付

- `scripts/cloud/run_gate.sh`（改成骨架：全部本仓字面搬进 profile，13 道横幅与步骤顺序**一格未动**）
- `scripts/cloud/profile.py`（新：`dump` / `list` / `check` / `render` 四个子命令）
- `scripts/cloud/profiles/engineering.toml`（新，本仓那一份）
- `scripts/cloud/profiles/openmaic.toml`（新，第二仓那一份）
- `tests/_cloud_profile.py`（新，测试侧读法：`render()` / `skeleton()` / `load_profile()`）
- `tests/test_cloud_profiles.py`（新，判据 1/2/3 的钉子）
- `tests/test_cloud_sync.py`、`tests/test_ci_portability.py`、`tests/test_cloud_product_freshness.py`
  （haystack 换成渲染产物；补 `-n "$var"` 空 env 守卫的反向用例；R2 债搬进 profile 后两头都钉）
- `docs/subsystems/ci/云门禁机.md`（新增 §3.1 分界 / §3.2 键表 / §3.3 退出码总表 / §3.4 另一仓怎么接 /
  §3.5 SSH 保活与云侧落盘；修 §2 的 `TF_LAST_SEED` 事实错误）
- `docs/subsystems/ci/云门禁-可复现性清单.md`（R2 改指 profile；扫描面 2→3 条；白名单表 1→3 行）
- `docs/traceability.d/T-AG591.toml`（`remote_out` 那条 text 钉子从「骨架里写绝对路径」改成
  「骨架有 `P_GATE_REMOTE_LOG` 接线 + profile 里那条例样仍在」）

## 验收

- `python -X utf8 -m pytest tests/test_cloud_sync.py tests/test_ci_portability.py tests/test_cloud_profiles.py tests/test_cloud_product_freshness.py -o addopts="" -q --no-cov` ⇒ 73 passed
- `bash scripts/cloud/run_gate.sh --render | bash -n` 与 `TF_CLOUD_PROFILE=scripts/cloud/profiles/openmaic.toml bash scripts/cloud/run_gate.sh --render | bash -n` 都退 0
- `python -X utf8 scripts/audit_progress.py --all` ⇒ `审计通过`
- 云门禁真跑一趟（本仓）与 OpenMAIC 真跑一趟，读数分别落在
  `gates/diag/cloud-run-E89b.log` 与 `gates/diag/cloud-run-OM5.log`

## 不许做

- 不许把 `run_gate.sh` 复制成 `run_gate_openmaic.sh` —— 两份会各自漂移，这正是本卡要消灭的东西。
- 不许改 13 道横幅的编号与顺序（`tests/test_cloud_sync.py` 有 12 条 `index()` + 4 条 region 断言钉着）。
- 不许把 `--check-residue` 挪出「第一段可执行分支、零 env 依赖」（单测不带任何 env 跑它）。
- 不许把 `SSHOPTS` 拆行（`tests/test_ci_portability.py` 的切片靠 `SSHOPTS=` 到 `TMP=` 的位置）。
- 不许为了让测试变绿去放宽 `-n "$var"` 守卫、或把 `seed.files` 的逐件校验改回单件。
- 不许在 `openmaic.toml` 里出现任何本仓键值（判据 3）。

## 直做

`scripts/cloud/run_gate.sh` **工作区全 CRLF**（`git ls-files --eol` 的 `w/crlf`；裸 LF 必须为 0。索引侧在 T-AG600 之后是 `i/lf` —— 那是 `core.autocrlf=true` 下的正常态，与同目录 `profile.py`/`profiles/*.toml` 一致，**不是**缺陷）：
改它一律字节级（`read_bytes` → 按 `\r\n` 切 → 断言旧锚点命中恰好一次 → 替换 → 回写），
改完 `bash -n` + 两份 `--render` 都要复验。`tests/*.py` 是 `i/lf w/crlf`（索引 LF、工作区 CRLF），
用 `pathlib` 的 `newline=""` 读写并按文件自身 EOL 适配，否则替换会 0 命中。
