# 卡 E56 —— 云机门禁的三处「看宿主脸色」（双门超时已换机消失，判据改判）

> ★ **2026-10-26 换机后重判**（本文件 §3–§5 已按新判据重写，§7 保留原归因纠正，§1–§2 是当时现场）：
>
> - 原症状「两条 pytest 门禁同时撞 1800 s」**在新机器上不再出现**：pass15 对 `34eba7f2`
>   全量 20 门跑完只用了 **417 s**（`pytest 395 s`、`pytest_chain` 未超时），
>   ⇒ §7 的「4 vCPU 只兑现约 1 核算力」是旧机器的病，换机即解；§3 原方案「按泳道分薄 worker」
>   **不必做**（做了也没坏处，但它不是通过云机门禁的必要条件，本卡不再承担）。
> - 换机后仍剩 **2 条云机红**，与本卡的原始疼点不同源，是同一族缺陷（**判据读宿主机的仓外配置**，
>   E49 家族的漏网之鱼）：`tests/test_pool_lib.py::test_wb_plan_cli_and_library_agree`
>   与 `tests/test_wb_dispatch.py::test_account_auth_uses_the_profile_env_and_model`。
> - 顺带在本机抓到第三个缺陷：`tests/test_wb_dispatch.py` 用 `import wb_session` 拿到的
>   模块对象**不是**生产侧 `from tools import wb_session` 那一个 ⇒ 夹具 patch 打空，
>   宿主带 `DSH_SESSION_ID` 时该文件 **69 条红**。

> 来源：云机 pass14（对 `0f80f5bf`）实测。**不是**代码回归，是**调度容量**缺陷。

## 1. 疼点（实测原文）

云机 pass14（`gates/diag/cloud-gate-E49-p14.log`，作业 `bash-d98a1427b25f49cb`，1935 s，exit 1）：

```
pytest        exit=124  1806.11s
pytest_chain  exit=124  1804.94s
acceptance    exit=0     519.76s
mypy          exit=0     278.50s
```

两道门**同时**撞 `DEFAULT_DOOR_TIMEOUT = 1800`，用时只差 1.2 s ⇒ 同一时刻起跑、同时被砍。
`last.json ok=False rev=0f80f5bf python=3.12.8`，其余 18 门全 exit=0。

## 2. 真因（代码级，已读源码确认）

`scripts/run_gates.py:2283` 把门分成两条泳道，**轻门一律先全部 `Popen` 起齐**再并发等输出：

```python
light = [(n, c) for n, c in todo if n not in BROWSER]   # pytest 与 pytest_chain 都在这里
for name, cmd in light:
    proc, t0, why = start_gate(name, cmd)               # ← 逐个起，但起完才等
```

`workers_for(avail_gb, cpu, inflight)` 只按**可用内存**分档、并按 `inflight`（别的门禁在跑）
扣减 —— 它**不知道同一台机器上另一道 pytest 门也在起 worker**。于是 4 vCPU / 13.3 GB 空闲的云机上：

- `pytest` 取 `min(8, cpu=4)` = **4 worker**
- `pytest_chain` 同样取 **4 worker**
- 合计 **8 个 pytest worker 挤 4 vCPU**（实测云机当时 10 个 python 进程 = 2 master + 8 worker），
  外加同泳道的 `acceptance`（519 s）与浏览器层

本机 32 逻辑核能吸收这个超额（本地 `pytest 350 s ∥ pytest_chain 175 s` 双绿），
云机 4 vCPU 不能 ⇒ 双门同时超时。E50 加第 20 道门时只验证了本机，没有 4 vCPU 的读数。

## 3. 做成什么样（2026-10-26 重写）

三处，判据本身**一个字不改**，只把「它要问的东西」从宿主机搬进 tmp 或显式声明：

1. **`tests/test_pool_lib.py::test_wb_plan_cli_and_library_agree` 加上同文件已有的
   `hermetic` 夹具**（它把 `pool_plan.ROOT`/`DIAG` 指到 tmp，并在 tmp 里铺
   `复盘/卡/卡160-台账接进门.md` 与 `batch/B-INVGATE.toml`）。这条用例是**唯一漏掉**该夹具的
   同族用例 —— 开发机上 `gates/diag/batch/` 恰好有文件所以绿，云机 `git clean -xfdq` 之后红。
2. **`tests/test_wb_dispatch.py::test_account_auth_uses_the_profile_env_and_model` 隔离模型开关**：
   `monkeypatch.setenv("TF_MODEL_SWITCHES", <tmp 下不存在的路径>)` 先把宿主开关摘掉，
   再用 `monkeypatch.setattr(wd, "ONE_OFF_MODELS", ("glm-5.2",))` 显式一次性授权该模型。
   ⇒ 「闸门放行」不再取决于宿主机 `infra/pool/model-switches.toml` 里恰好开着谁。
3. **`tests/test_wb_dispatch.py` 的 `wb_session` 导入改成 `from tools import wb_session`**，
   与生产侧 `tools/wb_dispatch.py:2988` 同一条路径 ⇒ 同一个模块对象 ⇒
   `isolated_session_ledger` 夹具的 `LEDGER` 真的指回 tmp_path。
   另外把 `test_the_lease_is_returned_even_when_the_dispatcher_raises` 的**子进程**环境里的
   `DSH_SESSION_ID` 摘掉（子进程拿不到进程内夹具，带指纹会先在会话闸被拦、优雅退 0 ⇒ 假红）。

## 4. 判据

1. **反向验证（开关）**：把第 2 条的两行删掉、并保留宿主机开关文件存在 ⇒ 该用例在本机也红
   （证明它原来真的在看宿主脸色）。
2. **反向验证（夹具）**：把第 1 条的 `hermetic` 参数删掉，并在 `gates/diag/batch/` 取走
   `B-INVGATE.toml` 的情况下跑 ⇒ 红（证明这条用例的红绿取决于外部目录）。
3. **反向验证（模块身份）**：把第 3 条改回 `import wb_session`，在 `DSH_SESSION_ID` 有值的环境下
   跑 `tests/test_wb_dispatch.py` ⇒ 69 条红（今天的实测就是这个数）。
4. **云机复跑**：全量 20 门，`pytest` / `pytest_chain` 都 exit=0，`last.json ok=True`。
5. 本机 `tests/test_wb_dispatch.py` 在 `DSH_SESSION_ID` 有值**与**无值两种环境下都 210 passed。

## 5. 不许做

- 不许把 `DEFAULT_DOOR_TIMEOUT` 从 1800 调高来「解决」超时（体温计泡热水）—— 换机后已不超时，更没理由。
- 不许在 `scripts/cloud/run_gate.sh` 里 export `TF_PYTEST_WORKERS` / `TF_MODEL_SWITCHES`
  （环境渗进子进程，卡 A266 踩过）。判据要自己在测试里声明依赖。
- 不许把 `tests/test_pool_lib.py` 的两条用例改成 `skipif` 跳过（那是拿 skip 掩盖红，
  `tests/test_cloud_sync.py::test_known_env_red_list_covers_only_b_class` 会咬）。
- 不许为了让 `test_account_auth_...` 绿而把 `glm-5.2` 塞进 `MODEL_WHITELIST`
  （名单是下限、轮换链，不是一次性授权；一次性授权走 `ONE_OFF_MODELS`）。

## 6. 证据

- 云机读数：`gates/diag/cloud-gate-E49-p14.log`、`.wt/E49/gates/last.json`、`.wt/E49/gates/logs/pytest.log`
- 代码位置：`scripts/run_gates.py:2283-2305`（泳道与起进程）、`:326 workers_for()`、`:157 DEFAULT_DOOR_TIMEOUT`
- 2026-10-26 换机后：`gates/diag/cloud-gate-E49-p15.log`（417 s，只剩 2 条红）
- 模块身份实测：`sys.path.insert(0,'tools'); import wb_session` 与 `from tools import wb_session` 是**两个不同对象**
- 前一轮对照：pass13（单道 pytest，4 worker）`pytest 807 s` 通过

## 7. 归因纠正（2026-10-26 实测，主控补记）

> 上面 §2 的「8 个 worker 挤 4 vCPU」**不是**根因。本节的读数是实测的，写在最前面防止误导后来人。

### 7.1 决定性读数

| 实验 | 云机读数 | 本机对照 |
|---|---|---|
| 4 路 spin 各自 CPU 时间（子进程自报 `os.times()`） | 各 `10.16~10.19 s / 10.00 s 墙钟`，合计 **3.94 核** | 未测 |
| 4 路 spin 指令吞吐（同上，同 10 s） | 合计 **4.05 M iters/s** = 单进程 3.87 M 的 **1.05×** | 4 路 **25.7 M** = 单进程 7.9 M 的 **3.85×** |
| 空闲 120 s 后 4 路 × 30 s（10 s 窗口） | `1.09 → 1.10 → 0.27` 核 | — |
| 空闲 60 s 后 4 路 × 60 s（10 s 窗口） | `1.03 / 1.02 / 1.01 / 0.99 / 1.01` 核 | — |
| `Win32_Processor` | `Intel Xeon Platinum`，**`NumberOfCores=2` / `NumberOfLogicalProcessors=4`**，`MaxClockSpeed=2500`，满载 `CurrentClockSpeed` 仍 2500 | — |
| 满载时系统利用率（`GetSystemTimes`） | **100%（= 4 逻辑处理器全忙）** | — |
| 实例规格（元数据服务 `100.100.100.200`） | `ecs.e-c1m4.xlarge` | — |

脚本留在 `gates/diag/`：`bench_throttle2.py`、`bench_sustained.py`、`bench_childcpu.py`、`bench_cpuutil.py`、`bench_recover.py`、`bench_credits.py`、`bench_clock.py`。

### 7.2 这组读数说明什么

- **不是配额（cgroup/steal）**：4 个子进程各自拿到满核 CPU 时间（3.94 核 / 4 核），系统利用率也报 100%；
  如果是配额或 steal，子进程的 CPU 时间会明显少于墙钟。
- **不是积分突发**：空闲 60/120 s 后立刻量，**没有**任何 >1.1 核的冲高（突发型经济实例的典型特征是开头冲 4× 再衰减）。
- **不是主频被压**：`CurrentClockSpeed` 满载仍 2500 MHz（但 WMI 这个字段在 Hyper-V 客人里常年是标称值，不可当证据 —— 见 §7.3）。
- **是「报给客人 4 vCPU、实际只兑现约 1 核算力」**：同样 10 s 墙钟、同样 4 个满核进程，云机只能完成本机 **1/6.3** 的指令量。

⇒ E56 §2 那套「worker 数相加超卖」的解释**成立不了**：即使把 8 个 worker 砍到 1 个，单核算力仍只有本机
的 1/3（本机单核 7.9 M vs 云机单核 2.6–3.9 M），`pytest` 3414 条在云机上本来就跑不进 1800 s。

### 7.3 诚实边界（没证实的那部分）

- `% Processor Performance` 计数器在中文 Windows 上取不到（PDH 英文名解析失败，`typeperf` 输出 GBK 乱码），
  **没有**拿到「主频占标称百分比」的硬证据。§7.2 的「不是主频被压」只靠「吞吐塌了但 CPU 时间照给」这一条推断。
- 假设「这台机器 4 vCPU 应该兑现 ~4 核算力」，比本机慢是正常的（本机 32 逻辑核、更高主频）；
  但**持续的 1 核**（不是 2 核、也不是 3 核）这个数字本身可疑，像是宿主机侧对这台客人的硬限制。
- 阿里云侧的 CPU 积分状态（`Get-Metric` / 控制台「CPU 积分」页）我在客人机内看不到，需要你在控制台核一眼。

### 7.4 因此 E56 该怎么做（建议，未登记）

原卡 §3 的「按泳道分摊 worker」仍然**值得做**（8 worker 挤 4 vCPU 会加剧抖动），但它**不是**通过云机门禁的充分条件。
真正的两条路：

1. **换机型/加钱**：`ecs.e-c1m4.xlarge` 兑现约 1 核算力，跑不动 3414 条 + 22 条 chain。
   要么换 `c`/`g` 系列（通用型/计算型，不靠积分），要么把门禁退回本机跑。
2. **降门禁预算**：云机只跑**快档**门禁（`--profiles auto` 或 `--fast`），全量留给本机 —— 但这与 E42「门禁默认上云」冲突，得先改口径。

**在拿到你的裁定之前，我不改 E56 的实现方向**（现在卡里 §3/§4 的判据是基于已被推翻的归因）。
