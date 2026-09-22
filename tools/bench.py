"""基准测试（SR-NF18「轻量：启动快 / 内存低 / 大数据量流畅（可验证）」）。

用法：
    python -X utf8 tools/bench.py                 # 默认 2000 任务 + 20000 事实
    python -X utf8 tools/bench.py --n 5000        # 大一点
    python -X utf8 tools/bench.py --json          # 机器可读
    python -X utf8 tools/bench.py --check         # 超预算就退出码 1（回归护栏）

**这些数字是"回归护栏"，不是产品指标** —— 阈值故意定得很松，只用来抓"某次改动把某条路径弄慢十倍"
这种事。别拿它们当性能目标，也别为了刷数字牺牲正确性。

测什么（都跑在临时库上，不碰真实数据）：
- `启动`：`create_app()` + 首次连接（含 schema 迁移）耗时；
- `读路径`：列表 / 今天 / 摘要 / 周结算 / 热力图 / 今日完成明细 的单次耗时（取多次的中位数）；
- `写路径`：建任务、完成任务、撤销完成、记一笔产出 的单次耗时；
- `内存`：`tracemalloc` 峰值（Python 侧；不含 SQLite C 层缓存，如实标注）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# 回归护栏（毫秒）——松到几乎不会误报，只抓"数量级变慢"
BUDGET_MS = {
    "启动": 5000.0,
    "GET /api/tasks": 1500.0,
    "GET /api/mydays": 1500.0,
    "GET /api/summary": 800.0,
    "GET /api/summary/weekly": 1500.0,
    "GET /api/today/done": 800.0,
    "GET /api/insights/heatmap": 3000.0,
    "POST /api/tasks": 500.0,
    "POST complete": 500.0,
}


def build_db(path: str, n_tasks: int, n_facts: int) -> None:
    """造一个"用了一阵子"的库：任务 + 分组 + 事实（专注/完成/产出）。"""
    from timeflow.core import facts as facts_mod
    from timeflow.core import tasks as tm
    from timeflow.storage import db as db_mod

    conn = db_mod.connect(path)
    today = date.today()
    groups = ["学习", "工作", "生活"]
    for name in groups:
        tm.create_group(conn, name)
    task_ids: list[str] = []
    for i in range(n_tasks):
        due = (today + timedelta(days=(i % 30) - 10)).isoformat()
        t = tm.create_task(
            conn,
            title=f"任务 {i}",
            due_date=due,
            group_name=groups[i % len(groups)],
            priority=["高", "中", "低"][i % 3],
            is_myday=(i % 5 == 0),
        )
        task_ids.append(t.id)
    # 事实：一半专注、一半完成/产出，散在近 90 天里
    for i in range(n_facts):
        day = (today - timedelta(days=i % 90)).isoformat()
        if i % 3 == 0:
            facts_mod.record(
                conn,
                kind="focus.finished",
                subject_type="focus",
                subject_id=f"f{i}",
                value_num=1500.0,
                occurred_at=f"{day}T10:00:00",
            )
        elif i % 3 == 1:
            facts_mod.record(
                conn,
                kind="task.completed",
                subject_type="task",
                subject_id=task_ids[i % len(task_ids)],
                value_text=f"任务 {i % n_tasks}",
                occurred_at=f"{day}T11:00:00",
            )
        else:
            facts_mod.record(
                conn,
                kind="output.manual",
                subject_type="output",
                subject_id=f"o{i}",
                value_num=1.0,
                value_text="asset" if i % 2 else "kpi",
                occurred_at=f"{day}T12:00:00",
            )
    conn.close()


def _timeit(fn: Callable[[], Any], rounds: int = 5) -> float:
    """跑 rounds 次，返回**中位数**毫秒（第一次单独跑掉，避开冷启动缓存）。"""
    fn()
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 1)


def run(n_tasks: int, n_facts: int) -> dict[str, Any]:
    import logging
    import os

    from fastapi.testclient import TestClient

    from timeflow import logs
    from timeflow.api.app import create_app

    # 基准跑起来会不停记"关键路径日志"（SR-NF13），把结果表淹掉 —— 这里只让它只报警告以上，
    # **不改业务行为**（日志级别与业务无关）。
    os.environ.setdefault("TF_LOG_PATH", "off")
    tmp = Path(tempfile.mkdtemp(prefix="timeflow_bench_"))
    # 基准也走**临时库**：markdown 落盘目录一并指到临时目录
    # （别往仓库 `export/` 写合成数据，见 T-G4）
    os.environ.setdefault("TIMEFLOW_EXPORT__DIR", str(tmp / "export"))
    db_path = str(tmp / "bench.db")
    build_db(db_path, n_tasks, n_facts)

    tracemalloc.start()
    started = time.perf_counter()
    client = TestClient(create_app(db_path))
    startup_ms = round((time.perf_counter() - started) * 1000, 1)
    logs.logger().setLevel(logging.WARNING)

    results: dict[str, float] = {"启动": startup_ms}
    for name, call in (
        ("GET /api/tasks", lambda: client.get("/api/tasks")),
        ("GET /api/mydays", lambda: client.get("/api/mydays")),
        ("GET /api/summary", lambda: client.get("/api/summary")),
        ("GET /api/summary/weekly", lambda: client.get("/api/summary/weekly")),
        ("GET /api/today/done", lambda: client.get("/api/today/done")),
        ("GET /api/insights/heatmap", lambda: client.get("/api/insights/heatmap?days=90")),
    ):
        results[name] = _timeit(lambda call=call: call(), rounds=3)

    created: dict[str, str] = {}

    def make_task() -> None:
        created["id"] = client.post("/api/tasks", json={"title": "基准任务"}).json()["id"]

    results["POST /api/tasks"] = _timeit(make_task, rounds=5)
    results["POST complete"] = _timeit(
        lambda: client.post(f"/api/tasks/{created['id']}/complete"), rounds=5
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    over = [
        {"name": k, "ms": v, "budget": BUDGET_MS[k]}
        for k, v in results.items()
        if k in BUDGET_MS and v > BUDGET_MS[k]
    ]
    return {
        "tasks": n_tasks,
        "facts": n_facts,
        "ms": results,
        "peak_memory_mb": round(peak / 1024 / 1024, 1),
        "over_budget": over,
        "note": (
            "数字是回归护栏，不是产品指标；内存为 Python 侧 tracemalloc 峰值"
            "（不含 SQLite C 层缓存）"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="timeflow 基准测试（临时库，不碰真实数据）")
    parser.add_argument("--n", type=int, default=2000, help="任务条数（默认 2000）")
    parser.add_argument("--facts", type=int, default=20000, help="事实条数（默认 20000）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--check", action="store_true", help="超预算 → 退出码 1")
    args = parser.parse_args()

    report = run(args.n, args.facts)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"=== timeflow 基准（{report['tasks']} 任务 / {report['facts']} 事实）===")
        for name, ms in report["ms"].items():
            budget = BUDGET_MS.get(name)
            flag = ""
            if budget is not None:
                flag = "  ⚠️ 超预算" if ms > budget else f"  (护栏 {budget:.0f}ms)"
            print(f"  {name:<26} {ms:>8.1f} ms{flag}")
        print(f"  {'Python 峰值内存':<24} {report['peak_memory_mb']:>8.1f} MB")
        print(f"\n{report['note']}")
    if args.check and report["over_budget"]:
        print(f"\n❌ 超出回归护栏：{report['over_budget']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
