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
