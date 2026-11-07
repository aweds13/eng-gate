"""卡 E30 尾巴的钉子：payload 里必须留下「这一趟按哪种 dist 跑的」。

## 为什么单开这个文件

卡 E30 的并行度自适应本体已由 E50 落地笔 `b659e2df` 吸收（`workers_for` / `MEM_TIERS` /
`inflight_workers` / `pytest_dist` / `parallel_note`），那张卡只剩两件尾巴：

| # | 尾巴 | 坏掉会红在哪 |
|---|---|---|
| ① | payload 记 `pytest_dist`，排在 `workers` 之后 | 只记 worker 数 ⇒ 按哪种 dist 跑的查不到 |
| ② | `pytest_dist()` 不设环境变量时默认 `worksteal` | 策略偷偷退回 `load`（判据 2 的实测白做） |

第 ① 条的「`"workers": pytest_workers()` 必须在源码里」这一半沿用既有钉子
`tests/test_door_inputs_coverage.py::test_pytest_mode_and_workers_are_recorded_in_payload`
的口径（卡 161 §2 / INV-24），这里多钉一条**顺序**：workers 在前、dist 在后，
免得日后有人把 dist 挪到别的字典里去（那时两个键还在，但不再是同一条 payload）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_run_gates():
    """与 `tests/test_run_gates_workers.py` 同一引入范式：按路径装载，不依赖 sys.path。"""
    target = ROOT / "scripts" / "run_gates.py"
    spec = importlib.util.spec_from_file_location("run_gates_payload_under_test", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_gates_payload_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load_run_gates()


# ---------------------------------------------------------------- ① payload 记 dist
def test_payload_records_pytest_dist() -> None:
    """★ 卡 E30 尾巴：payload 记 `pytest_dist`，且**紧跟在** `workers` 之后。

    证字段进了 payload：构造 payload 的代码路径直接引用了 `pytest_dist()`。
    这里钉的是源码里的那两个键（与 `tests/test_door_inputs_coverage.py:108` 同口径），
    再加一条顺序断言 —— 两个键都在、但不在同一条 payload 里，等于没记。
    """
    src = (ROOT / "scripts" / "run_gates.py").read_text(encoding="utf-8")

    assert '"pytest_dist": pytest_dist()' in src, "payload 没记 pytest_dist（卡 E30 尾巴）"
    assert '"workers": pytest_workers()' in src, "payload 没记 workers（卡 161 §2 / INV-24）"

    i_workers = src.index('"workers": pytest_workers()')
    i_dist = src.index('"pytest_dist": pytest_dist()')
    assert i_workers < i_dist, (
        "payload 里 `pytest_dist` 必须排在 `workers` 之后（同一条 payload；"
        f"实测 workers@{i_workers} / dist@{i_dist}）"
    )


# ---------------------------------------------------------------- ② 默认 dist
def test_default_dist_is_worksteal(monkeypatch: pytest.MonkeyPatch) -> None:
    """不设 `TF_PYTEST_DIST` ⇒ `worksteal`（E30 §判据 2 实测最快的那一档）。

    宿主环境里设了也不算数：先 delenv，否则这条钉子跟着机器变。
    """
    monkeypatch.delenv("TF_PYTEST_DIST", raising=False)
    assert rg.pytest_dist() == "worksteal"
