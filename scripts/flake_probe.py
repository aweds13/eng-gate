"""卡 E72 · T-AG561 —— 隔离复核探针：一条红单，一个判定，只读。

门禁的 pytest 门红了之后，「这条红在**隔离跑法**下还红不红」是唯一能把真红与假红
分开的读数（2026-10-30 夜同一棵树三趟全量门禁出了三张互不相同的红单，单跑全绿）。
这份模块只做那一件事：

    probe(["tests/test_x.py::test_y"], root=树根)
    -> {"nodeid": str, "verdict": str, "seconds": float, "tail": str}

三条铁律（卡 E72 判据 1 / 判据 6 / §不许做）：

1. **只读**：不落任何文件、不碰门禁台账、不认识任何门名 —— 它只知道
   nodeid 与退出码；「哪道门该怎么用这个判定」全在 `scripts/run_gates.py` 那一侧。
2. **串行、单进程**：一次一个 nodeid、一次一条 pytest 命令，**不带**任何 xdist 参数；
   父进程环境里的 `PYTEST_ADDOPTS` 会被摘掉（否则外面挂的 `-n auto` 会悄悄混进来，
   判定就失真了）。
3. **判不出就说判不出**：超时 / 起不来 ⇒ `error`，**绝不当绿**。

`repeat > 1` 只用来数「几次里有几次红」，不是「跑到绿为止」。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: 判定只有这三个取值（第四个就是「判不出」，不许再分叉）。
REPRODUCED = "reproduced"
ISOLATED_GREEN = "isolated_green"
ERROR = "error"

#: 隔离跑法固定带上的参数：清掉配置里的 addopts（含覆盖率门槛），并关掉覆盖率。
PROBE_ARGS = ("-q", "-o", "addopts=", "--no-cov")

#: 回传尾部的体积口径（与门禁 `detail` 字段同一量级，卡 E67）。
TAIL_LINES = 20
TAIL_MAX_CHARS = 2000


def probe_cmd(nodeid: str) -> list[str]:
    """隔离跑法的唯一命令形状：单 nodeid、串行、单进程、不挂 xdist。

    ★ 这份命令行是判据的一部分（卡 E72 判据 1 逐字钉死了参数顺序）—— 想加并行参数
    改这里就会被 `tests/test_flake_probe.py` 咬住。
    """
    return [sys.executable, "-X", "utf8", "-m", "pytest", nodeid, *PROBE_ARGS]


def child_env(root: Path) -> dict[str, str]:
    """子进程环境：本树 `src/` 优先 + utf-8 固定 + **摘掉 `PYTEST_ADDOPTS`**。

    摘 `PYTEST_ADDOPTS` 不是洁癖：它是 pytest 唯一能从外部塞参数的通道，留着就等于
    把「串行单进程」这条判据交给人品（`PYTEST_ADDOPTS='-n auto'` 会让隔离跑变成并行）。
    """
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    src = str((root / "src").resolve())
    rest = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != src]
    env["PYTHONPATH"] = os.pathsep.join([src, *rest])
    return env


def _tail(text: str) -> str:
    """尾部若干行（去掉空行），再截到体积上限 —— 与 `gate_detail()` 同一口径。"""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-TAIL_LINES:])[-TAIL_MAX_CHARS:]


def _run_once(nodeid: str, root: Path, timeout_s: float) -> dict[str, object]:
    """真起一次 pytest 子进程，把它压成一个判定（这是唯一的真相来源）。"""
    timeout = timeout_s if timeout_s and timeout_s > 0 else None
    started = time.time()
    try:
        done = subprocess.run(
            probe_cmd(nodeid),
            cwd=str(root),
            env=child_env(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": ERROR,
            "seconds": round(time.time() - started, 2),
            "tail": f"超时 {timeout_s:g} 秒没跑完：{nodeid}",
        }
    except OSError as exc:
        # 起不来（cwd 不在、解释器路径坏了……）：判不出，**不当绿**
        return {
            "verdict": ERROR,
            "seconds": round(time.time() - started, 2),
            "tail": f"起不来：{exc}",
        }
    blob = f"{done.stdout or ''}\n{done.stderr or ''}"
    return {
        "verdict": REPRODUCED if int(done.returncode) != 0 else ISOLATED_GREEN,
        "seconds": round(time.time() - started, 2),
        "tail": _tail(blob),
    }


def probe(
    nodeids: Sequence[str],
    *,
    root: Path,
    repeat: int = 1,
    timeout_s: float = 600.0,
) -> dict[str, object]:
    """隔离跑一遍（或 `repeat` 遍），给出一个判定。

    退出码非 0 ⇒ `reproduced`（隔离跑也红 ⇒ 真红）；0 ⇒ `isolated_green`（隔离跑绿 ⇒
    这条红跟负载/时序有关）；超时或起不来 ⇒ `error`（**不许**当绿）。

    传多个 nodeid 时按「有一条红就算 `reproduced`、都绿才算 `isolated_green`、有判不出
    的算 `error`」汇总 —— 往严的方向收敛，绝不让 error 混成绿。
    """
    ids = [n.strip() for n in nodeids if n and n.strip()]
    if not ids:
        raise ValueError("probe() 至少要一个 nodeid —— 空清单不许被当成绿")
    runs = max(1, int(repeat))
    reds = 0
    errors = 0
    last: dict[str, object] = {"verdict": ERROR, "seconds": 0.0, "tail": "没有跑任何一次"}
    started = time.time()
    for nodeid in ids:
        for _ in range(runs):
            last = _run_once(nodeid, root, timeout_s)
            if last["verdict"] == REPRODUCED:
                reds += 1
            elif last["verdict"] == ERROR:
                errors += 1
    total = runs * len(ids)
    if reds:
        verdict = REPRODUCED
    elif errors:
        verdict = ERROR
    else:
        verdict = ISOLATED_GREEN
    tail = str(last.get("tail") or "")
    if total > 1:
        tail = f"[{reds}/{total} 次红]\n{tail}"
    return {
        "nodeid": ids[0] if len(ids) == 1 else " ".join(ids),
        "verdict": verdict,
        "seconds": round(time.time() - started, 2),
        "tail": tail,
    }
