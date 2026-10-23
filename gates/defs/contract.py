"""契约门：台账与证据的形状。**判据按本仓实现写**——换仓要重写实现，只借形状。"""

import sys

PY = sys.executable

GATES: list[tuple[str, list[str]]] = [
    # 证据审计：每个声称都要有可解析的指针（`file:` / `text:` / `test:`）。
    ("audit", [PY, "-X", "utf8", "scripts/audit_progress.py", "--all"]),
    # 不变量台账：新能力没进 `复盘/不变量台账.toml` 就不算做完；只核指针存在性，不真跑门。
    ("invariants", [PY, "-X", "utf8", "tools/wb_invariants.py", "--check"]),
    # 台账 ↔ 规格 标题对账：确定错位或无规格对应的 SR 卡就退 1。
    ("audit_titles", [PY, "-X", "utf8", "scripts/audit_titles.py", "--check"]),
]
