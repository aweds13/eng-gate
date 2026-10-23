"""语言门：任何 Python 仓都该有的五道。换语言 ⇒ 换掉这个文件，`scripts/run_gates.py` 不动。"""

import sys

PY = sys.executable

# `pytest` 是占位：真正的命令按有没有 pytest-xdist 现算（见 `scripts/run_gates.py::pytest_cmd`）。
GATES: list[tuple[str, list[str]]] = [
    ("pytest", []),
    # 验收层只跑 2 个用例，必须关掉全局 addopts 里的覆盖率门，否则"覆盖率不达标"会误判验收失败。
    ("acceptance", [PY, "-X", "utf8", "-m", "pytest", "-m", "acceptance", "--no-cov"]),
    ("ruff", [PY, "-m", "ruff", "check", "src/", "tests/", "scripts/",
              "tools/", "examples/", "harness/"]),
    ("mypy", [PY, "-m", "mypy", "src/"]),
    ("check_layers_selftest", [PY, "-X", "utf8", "scripts/test_check_layers.py"]),
]
