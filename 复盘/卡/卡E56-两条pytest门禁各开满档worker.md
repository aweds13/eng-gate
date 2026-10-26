# 卡 E56 —— 两条 pytest 门禁各开满档 worker，4 vCPU 上互相饿死

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

## 3. 做成什么样

1. **pytest 家族共享一份 worker 预算**：`build_jobs` 时把「会同时跑的 pytest 门」数量算进来，
   每道门拿 `max(1, tier // n_pytest_doors)`。判据放在 `scripts/run_gates.py` 里（`workers_for`
   的入参加一个 `siblings` 或调用点先算好），**不许**在云机脚本里写死 `TF_PYTEST_WORKERS` ——
   那是「环境渗进子进程」的老雷（卡 A266）。
2. **门禁自己的日志要说清楚**：`[并行] workers=… dist=…（同泳道还有 N 道 pytest 门 ⇒ 各分 W）`，
   让下一次看日志就能判断是不是被分薄了。
3. 云机 `run_gate.sh` 不需要改（判据在库里，不在调用点）。

## 4. 判据

1. `workers_for(avail_gb=13.3, cpu=4, siblings=2)` ⇒ **2**；`siblings=1` ⇒ 4（单跑不吃亏）。
2. `pytest` 与 `pytest_chain` 两条命令里的 `-n` 数值之和 ≤ 该档位（钉子直接解析 `build_jobs` 产物）。
3. 反向验证：把 `siblings` 恒写成 1 ⇒ 钉子① 红（说明这条判据真的在起作用）。
4. 云机复跑一趟（同 commit）：两道门都 exit=0，且 `pytest` 用时 < 1800 s。本机读数不许退化
   （`pytest` 用时不得比现状 350 s 高出 20%）。
5. 日志行含 `siblings` 或「同泳道」字样（可核对，不靠猜）。

## 5. 不许做

- 不许把 `DEFAULT_DOOR_TIMEOUT` 从 1800 调高来"解决"（那是把体温计泡热水）。
- 不许在 `scripts/cloud/run_gate.sh` 里 export `TF_PYTEST_WORKERS`（环境渗进子进程，卡 A266 踩过）。
- 不许把 `pytest_chain` 挪回默认门（那是 E50 刚拆出来的，覆盖面会丢）。
- 不许把两道门改成串行就算了 —— 本机那趟并行是免费的一半，退回去等于白丢。

## 6. 证据

- 云机读数：`gates/diag/cloud-gate-E49-p14.log`、`.wt/E49/gates/last.json`、`.wt/E49/gates/logs/pytest.log`
- 代码位置：`scripts/run_gates.py:2283-2305`（泳道与起进程）、`:326 workers_for()`、`:157 DEFAULT_DOOR_TIMEOUT`
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
