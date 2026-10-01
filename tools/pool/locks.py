r"""门禁锁的**薄封装**（卡 106 · T-G202）—— 只给"看锁"这一条只读路径。

**防什么**：同一端口段两条线同时跑门禁会互相把服务掐掉 → **假红**（铁律 13 / 卡 051 撞过）。
`gates/diag/gate_lock.py` 已经把这套做全了；这里只抽出**看锁**（`status`，只列不拿）那一条，
让 CLI 与号池 MCP 共用**同一处命令与判据**，不再各写一份。

★ 边界（如实写）：锁的**真逻辑**（拿/放/续租/租约）仍住在 `gates/diag/gate_lock.py` —— 那是
`python -P -X utf8` 跑的**独立脚本**（`-P` 是铁律 24：`gates/diag/` 里若放了与标准库同名的
脚本会被顶掉），不 import 进来；本模块只提供**命令 argv** 与**"空着"的判据**。
"""

from __future__ import annotations

import sys

#: `gate_lock.py` 相对仓库根的位置（与 `run_gates.py` 的口径一致）。
GATE_LOCK_REL = "gates/diag/gate_lock.py"


def status_argv() -> list[str]:
    """看锁的命令 argv（**只列不拿**）—— `python -P -X utf8 gates/diag/gate_lock.py status`。

    ★ `-P` 与公开命令里的写法逐字一致（铁律 24）；调用方在**仓库根**下跑它。
    """
    return [sys.executable, "-P", "-X", "utf8", GATE_LOCK_REL, "status"]


def is_empty(body: str) -> bool:
    """`gate_lock.py status` 的原文里说"空着"吗 —— 判据就这一条（不另立一套）。"""
    return "空着（没有任何段的锁）" in body
