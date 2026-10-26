"""语言门：任何 Python 仓都该有的五道。换语言 ⇒ 换掉这个文件，`scripts/run_gates.py` 不动。"""

import sys

PY = sys.executable

# `pytest` 是占位：真正的命令按有没有 pytest-xdist 现算（见 `scripts/run_gates.py::pytest_cmd`）。
GATES: list[tuple[str, list[str]]] = [
    ("pytest", []),
    # 验收层只跑 2 个用例，必须关掉全局 addopts 里的覆盖率门，否则"覆盖率不达标"会误判验收失败。
    ("acceptance", [PY, "-X", "utf8", "-m", "pytest", "-m", "acceptance", "--no-cov"]),
    # ★ 卡 E50 段2（并 E32）：快慢分层的**慢那一半** —— 22 条「起真子进程跑完整链路」的 e2e。
    #   `addopts` 里有 `not chain`，所以默认 pytest 门不再背它们；这一道单独跑，**必须**在
    #   落地档里（否则 e2e 就永远不跑 = 把安全网摘掉）。`--no-cov` 同理：覆盖率由 pytest 门判。
    ("pytest_chain", [PY, "-X", "utf8", "-m", "pytest", "-m", "chain", "--no-cov"]),
    ("ruff", [PY, "-m", "ruff", "check", "src/", "tests/", "scripts/",
              "tools/", "examples/", "harness/"]),
    ("mypy", [PY, "-m", "mypy", "src/"]),
    ("check_layers_selftest", [PY, "-X", "utf8", "scripts/test_check_layers.py"]),
]
