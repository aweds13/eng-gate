"""基准测试工具（SR-NF18）的冒烟测试：

- `tools/bench.py` 能在**小数据集**上跑完并输出可解析的 JSON（工具本身不许坏）；
- 报的数字都有明确含义（毫秒 / MB / 超预算清单）；
- 只跑在临时库上（**绝不碰真实数据**）；
- 默认**不检查预算**（`--check` 才比较护栏）—— 护栏是回归用，不该让单测变脆。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 —— 固定调用自己的脚本，参数由用例写死
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "bench.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(ROOT),
    )


def test_bench_runs_on_small_dataset_and_reports_json() -> None:
    got = _run(["--n", "50", "--facts", "200", "--json"])
    assert got.returncode == 0, got.stderr[-500:]
    report = json.loads(got.stdout)
    assert report["tasks"] == 50 and report["facts"] == 200
    ms = report["ms"]
    for key in ("启动", "GET /api/tasks", "GET /api/summary", "POST /api/tasks"):
        assert isinstance(ms[key], (int, float)) and ms[key] >= 0, f"{key} 没测到"
    assert report["over_budget"] == [], "小数据集不该超护栏"
    assert isinstance(report["peak_memory_mb"], (int, float))
    assert "回归护栏" in report["note"], "必须写清这些数字不是产品指标"


def test_bench_human_output_lists_every_path() -> None:
    got = _run(["--n", "20", "--facts", "50"])
    assert got.returncode == 0, got.stderr[-500:]
    for needle in ("启动", "GET /api/mydays", "GET /api/today/done", "峰值内存"):
        assert needle in got.stdout, f"人类可读输出缺 {needle}"
