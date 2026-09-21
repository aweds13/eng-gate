"""扩展示例守卫（SR-NF10 / GAP-NF-06）：三个 `examples/*.py` **必须真的能跑**。

为什么要有这个测试：文档里的示例会腐烂 —— 接口改名、参数变化、口径调整，
示例照旧躺在那里"看着对"。所以把示例当**子进程**跑一遍，断言它自己的输出与结论。

跑法：`python -X utf8 -m pytest tests/test_examples.py`
每个示例都是独立进程：它们会注册进程内的事件订阅者，隔开才不会互相串。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
NAMES = ["01_add_a_fact_kind.py", "02_add_a_config_option.py", "03_add_a_ledger_view.py"]


def run_example(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(EXAMPLES / name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        timeout=180,
        check=False,
    )


def test_all_examples_exist_and_are_listed_in_readme() -> None:
    """`examples/` 里每个 .py 都要在 README 里被点名 —— 免得加完示例忘了写说明。"""
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for name in NAMES:
        assert (EXAMPLES / name).exists(), f"缺示例 {name}"
        assert name in readme, f"examples/README.md 没提到 {name}"


@pytest.mark.parametrize("name", NAMES)
def test_example_runs_green_and_prints_ok(name: str) -> None:
    got = run_example(name)
    tail = f"{got.stdout[-800:]}\n{got.stderr[-800:]}"
    assert got.returncode == 0, f"{name} 退出码 {got.returncode}\n{tail}"
    assert "OK 例" in got.stdout, f"{name} 没打印结论行：\n{got.stdout[-800:]}"
    assert "Traceback" not in got.stderr, got.stderr[-800:]


def test_example_3_matches_the_ledger_wording() -> None:
    """示例 3 是我自己写的口径 —— 它必须与账本同源：按 subject_id 去重 + 撤销照扣。"""
    out = run_example("03_add_a_ledger_view.py").stdout
    assert "知识资产 1" in out and "学校 KPI 1" in out, out
    assert "原事实仍在库里" in out, out


def test_examples_are_in_chinese_and_documented() -> None:
    """SR-NF10 的两条字面要求：**中文注释** + 「如何加一个功能」模板存在。"""
    for name in NAMES:
        head = (EXAMPLES / name).read_text(encoding="utf-8")[:1500]
        assert "用法" in head or "跑法" in head, f"{name} 开头没写跑法（零基础的人先看这个）"
        assert any("\u4e00" <= c <= "\u9fff" for c in head), f"{name} 没有中文说明"
    template = (ROOT / "docs" / "EXTENDING.md").read_text(encoding="utf-8")
    for needle in ("五步模板", "三条红线", "反模式", "如何加一个功能"):
        assert needle in template, f"docs/EXTENDING.md 缺 {needle}"
