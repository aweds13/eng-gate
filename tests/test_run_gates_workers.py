"""worker 分档（卡 E30）的钉子：五档 + 显式优先 + cpu 上限 + 兜底 + 「在跑多少就扣多少」。

为什么单独一个文件：并行度是**墙钟**的第一大项（pytest 占全量门禁 96.6%），而它原来写死在
`min(4, cpu)`。这组钉子钉住三件事，缺一条就退化成「靠人记得敲 `TF_PYTEST_WORKERS=8`」：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 五个档口（≥10 / ≥6 / ≥4 / ≥2.5 / 否则）各一条 | 档位表被抹平 ⇒ 回到 4 的硬顶 |
| ② | `TF_PYTEST_WORKERS` 显式优先（给 2 就 2） | 自适应覆盖人的显式选择（A266 约定） |
| ③ | `cpu_count=4` 时不许超过 4 | 上限算错 ⇒ 小机器上拉满 |
| ④ | 读不到内存 ⇒ 退回兜底（`DEFAULT_PYTEST_WORKERS`） | 读不到就升到 8 ⇒ 换页 |
| ⑤ | 「在跑多少就扣多少」（纯函数 + 真锁文件两半） | 扣在跑那步被删 ⇒ 第二个门禁照样拉满 |
| ⑥ | 分片策略默认 `worksteal`，`TF_PYTEST_DIST` 可覆盖 | 策略偷偷变回 `load` |
| ⑦ | 日志那行 `[并行] …` 的 worker 数**只来自一处** | 日志与真跑两样 ⇒ 看日志以为是 `-n 8` |
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_run_gates():
    target = ROOT / "scripts" / "run_gates.py"
    spec = importlib.util.spec_from_file_location("run_gates_workers_under_test", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_gates_workers_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_run_gates()


def _clean_env(monkeypatch) -> None:
    """把两个开关清掉（宿主环境里设了也不算数，否则钉子跟着机器变）。"""
    monkeypatch.delenv("TF_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv("TF_PYTEST_DIST", raising=False)


# ---------------------------------------------------------------- ① 五个档口
def test_tier_ten_gb_or_more_gives_eight() -> None:
    """≥10 GB ⇒ 8（32 核机器上 4→8 实测 −28%，这是本卡的主要收益档）。"""
    assert rg.workers_for(10.0, 32, 0) == 8
    assert rg.workers_for(15.2, 32, 0) == 8


def test_tier_six_gb_gives_six() -> None:
    """≥6 GB ⇒ 6（不给满档，留出别的门禁与浏览器的口粮）。"""
    assert rg.workers_for(6.0, 32, 0) == 6
    assert rg.workers_for(9.9, 32, 0) == 6


def test_tier_four_gb_gives_four() -> None:
    """≥4 GB ⇒ 4（= 老口径的硬顶，现在只是**中档**）。"""
    assert rg.workers_for(4.0, 32, 0) == 4
    assert rg.workers_for(5.9, 32, 0) == 4


def test_tier_two_and_a_half_gb_gives_two() -> None:
    """≥2.5 GB ⇒ 2。"""
    assert rg.workers_for(2.5, 32, 0) == 2
    assert rg.workers_for(3.9, 32, 0) == 2


def test_low_memory_is_serial() -> None:
    """可用 < 2.5 GB ⇒ 1（★ 卡 A266 的「不许换页」安全网，**不许**取消）。"""
    assert rg.workers_for(2.49, 32, 0) == 1
    assert rg.workers_for(0.3, 32, 0) == 1


# ---------------------------------------------------------------- ② 显式优先
def test_explicit_env_beats_adaptation(monkeypatch) -> None:
    """★ A266：给了 `TF_PYTEST_WORKERS=2` 就是 2 —— 哪怕内存读数够 8 档。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TF_PYTEST_WORKERS", "2")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 40.0)
    monkeypatch.setattr(rg.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(rg, "inflight_workers", lambda root=None: 0)
    assert rg.pytest_workers() == 2


def test_illegal_env_falls_back_to_adaptation(monkeypatch, capsys) -> None:
    """显式值不合法（0 / abc）⇒ 当没设，按内存自适应，并**打出来**（不静默）。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TF_PYTEST_WORKERS", "abc")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 12.0)
    monkeypatch.setattr(rg.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(rg, "inflight_workers", lambda root=None: 0)
    assert rg.pytest_workers() == 8
    assert "TF_PYTEST_WORKERS" in capsys.readouterr().err


# ---------------------------------------------------------------- ③ cpu 是硬上限
def test_cpu_count_caps_the_tier(monkeypatch) -> None:
    """`cpu_count=4` ⇒ 再好内存也不许超过 4（8 档只是**上限**，不是配给）。"""
    assert rg.workers_for(40.0, 4, 0) == 4
    _clean_env(monkeypatch)
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 40.0)
    monkeypatch.setattr(rg.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(rg, "inflight_workers", lambda root=None: 0)
    assert rg.pytest_workers() == 4


# ---------------------------------------------------------------- ④ 兜底
def test_unreadable_memory_falls_back_to_default(monkeypatch) -> None:
    """读不到内存 ⇒ `min(DEFAULT_PYTEST_WORKERS, cpu)`：不升到 8，也不降成 1。"""
    assert rg.workers_for(None, 32, 0) == rg.DEFAULT_PYTEST_WORKERS
    assert rg.workers_for(None, 2, 0) == 2
    _clean_env(monkeypatch)
    monkeypatch.setattr(rg, "available_memory_gb", lambda: None)
    monkeypatch.setattr(rg.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(rg, "inflight_workers", lambda root=None: 0)
    assert rg.pytest_workers() == rg.DEFAULT_PYTEST_WORKERS


# ---------------------------------------------------------------- ⑤ 在跑多少就扣多少
def test_inflight_workers_are_deducted_from_available() -> None:
    """「在跑多少就扣多少」：10 GB 单独跑是 8 档，别人已占 4 个 worker ⇒ 只剩 6 档。"""
    assert rg.workers_for(10.0, 32, 0) == 8
    assert rg.workers_for(10.0, 32, 4) == 6
    # 扣到跨档位也要跟着降（6 GB - 4×0.5 = 4 GB ⇒ 4 档）
    assert rg.workers_for(6.0, 32, 4) == 4


def _lock(diag: Path, name: str, *, workers: int | None, lease: int, age: float) -> Path:
    p = diag / name
    info = {"card": "X1", "pid": os.getpid(), "lease": lease}
    if workers is not None:
        info["workers"] = workers
    p.write_text(json.dumps(info), encoding="utf-8")
    stamp = time.time() - age
    os.utime(p, (stamp, stamp))
    return p


def test_inflight_counts_live_locks_only(tmp_path: Path, monkeypatch) -> None:
    """真锁文件的两半：租约内的活锁算、过期的不算、**本段那把（自己）不算**。"""
    monkeypatch.delenv("TF_GATE_PORT_BASE", raising=False)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    _lock(diag, "gates-9001.lock", workers=4, lease=600, age=0)
    _lock(diag, "gates-9002.lock", workers=2, lease=600, age=0)
    _lock(diag, "gates-9003.lock", workers=8, lease=5, age=600)      # 过期 ⇒ 不算
    _lock(diag, "gates.lock", workers=8, lease=600, age=0)           # 本段（自己）⇒ 不算
    assert rg.inflight_workers(tmp_path) == 6


def test_inflight_without_locks_is_zero(tmp_path: Path) -> None:
    """没有目录 / 没有锁 ⇒ 0（**不扣**：宁快不宁慢，但要如实打「在跑 0」）。"""
    assert rg.inflight_workers(tmp_path) == 0
    (tmp_path / "gates" / "diag").mkdir(parents=True)
    assert rg.inflight_workers(tmp_path) == 0


def test_inflight_old_lock_without_workers_key_is_estimated(tmp_path: Path, monkeypatch) -> None:
    """老锁没写 `workers` 键 ⇒ 按 `DEFAULT_PYTEST_WORKERS` 估（不许当 0 白捡便宜）。"""
    monkeypatch.delenv("TF_GATE_PORT_BASE", raising=False)
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    _lock(diag, "gates-9100.lock", workers=None, lease=600, age=0)
    assert rg.inflight_workers(tmp_path) == rg.DEFAULT_PYTEST_WORKERS


# ---------------------------------------------------------------- ⑥ 分片策略
def test_dist_defaults_to_worksteal(monkeypatch) -> None:
    _clean_env(monkeypatch)
    assert rg.pytest_dist() == "worksteal"


def test_dist_env_overrides(monkeypatch) -> None:
    """`TF_PYTEST_DIST` 覆盖；不认识的值退回默认并**打出来**（不静默当没设）。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TF_PYTEST_DIST", "loadfile")
    assert rg.pytest_dist() == "loadfile"
    monkeypatch.setenv("TF_PYTEST_DIST", "轮转")
    assert rg.pytest_dist() == "worksteal"


# ---------------------------------------------------------------- ⑦ 命令与日志同源
def test_pytest_cmd_carries_workers_and_dist(monkeypatch) -> None:
    """并行时命令里既有 `-n <w>` 也有 `--dist <策略>`；串行时不带任何并行开关。"""
    _clean_env(monkeypatch)
    monkeypatch.setattr(rg, "xdist_available", lambda: True)
    monkeypatch.setattr(rg, "pytest_workers", lambda: 8)
    assert rg.pytest_dist() == "worksteal"
    cmd = rg.pytest_cmd()
    assert cmd[:4] == [rg.PY, "-X", "utf8", "-m"]
    assert cmd[-4:] == ["-n", "8", "--dist", "worksteal"]
    assert "-n" not in rg.pytest_cmd(serial=True)


def test_parallel_note_reports_the_same_workers(monkeypatch) -> None:
    """日志那行 `[并行] workers=…` 的读数必须与 `pytest_workers()` 一致（不许第二份口径）。"""
    _clean_env(monkeypatch)
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 12.0)
    monkeypatch.setattr(rg.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(rg, "inflight_workers", lambda root=None: 0)
    note = rg.parallel_note()
    assert "workers=8" in note
    assert "可用 12.0 GB" in note
    assert "在跑 0" in note
    assert "dist=worksteal" in note


def test_parallel_note_says_explicit_source(monkeypatch) -> None:
    """人显式给了变量时，日志要说清「这是显式优先」，不许冒充内存自适应。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TF_PYTEST_WORKERS", "1")
    note = rg.parallel_note()
    assert "workers=1" in note
    assert "TF_PYTEST_WORKERS=1" in note
