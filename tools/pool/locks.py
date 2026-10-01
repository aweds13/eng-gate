r"""门禁锁的**薄封装**（卡 106 · T-G202；卡 108 加 `parse_entries`）—— 只给"看锁"这一条只读路径。

**防什么**：同一端口段两条线同时跑门禁会互相把服务掐掉 → **假红**（铁律 13 / 卡 051 撞过）。
`gates/diag/gate_lock.py` 已经把这套做全了；这里只抽出**看锁**（`status`，只列不拿）那一条，
让 CLI 与号池 MCP 共用**同一处命令与判据**，不再各写一份。

★ 卡 108（T-G205）新增 `parse_entries(body)`：把 `status` 的**原文**解析成结构化条目 ——
守卫（`tools/pool/guards.py::lock_guard`）与写面 CLI 靠它回答「这趟门禁还在跑吗」。
`is_empty()` 保持原样、行为未变。

★ 边界（如实写）：锁的**真逻辑**（拿/放/续租/租约）仍住在 `gates/diag/gate_lock.py` —— 那是
`python -P -X utf8` 跑的**独立脚本**（`-P` 是铁律 24：`gates/diag/` 里若放了与标准库同名的
脚本会被顶掉），不 import 进来；本模块只提供**命令 argv** 与**从原文解析/判断**的那两条。
"""

from __future__ import annotations

import re
import sys

#: `gate_lock.py` 相对仓库根的位置（与 `run_gates.py` 的口径一致）。
GATE_LOCK_REL = "gates/diag/gate_lock.py"

#: `gate_lock.py status` 里每段锁那一行的形状（卡 108 照它解析，别猜）：
#:   `[锁] 段 base=9034 文件=…: card=108 pid=… 起于 …（已 12s / 租约剩 …s；租约内） cwd=D:\…`
#: ★ `租约剩` 可为负（`lease - age`），所以 `remain` 收 `-?`；`起于` 里带空格 → 非贪婪到 `（`。
_ENTRY_RE = re.compile(
    r"^\[锁\] 段 base=(?P<base>\S+) 文件=(?P<file>.+?): "
    r"card=(?P<card>\S+) pid=(?P<pid>\S+) 起于 (?P<at>.+?)"
    r"（已 (?P<age>\d+)s / 租约剩 (?P<remain>-?\d+)s；(?P<lease>[^）]*)）"
    r" cwd=(?P<cwd>.*)$"
)


def status_argv() -> list[str]:
    """看锁的命令 argv（**只列不拿**）—— `python -P -X utf8 gates/diag/gate_lock.py status`。

    ★ `-P` 与公开命令里的写法逐字一致（铁律 24）；调用方在**仓库根**下跑它。
    """
    return [sys.executable, "-P", "-X", "utf8", GATE_LOCK_REL, "status"]


def is_empty(body: str) -> bool:
    """`gate_lock.py status` 的原文里说"空着"吗 —— 判据就这一条（不另立一套）。

    ★ 卡 108：行为**一字不改**（既有调用方还在用）；要结构化那一份用 `parse_entries`。
    """
    return "空着（没有任何段的锁）" in body


def parse_entries(body: str) -> list[dict]:
    """把 `gate_lock.py status` 的**原文**解析成每段锁一条（卡 108 · T-G205）。

    认不出的行（`空着` 那行、末尾的两行说明、`[锁] ★ 别看 pid 判活…`）**跳过** —— 不猜、不编。
    返回的每条键：`base` / `file` / `card` / `pid` / `at` / `age` / `remain` / `lease` / `cwd`。

    ★ 为什么解析在这里而不在 `guards`：`guards` 是**纯函数**（吃数据回问题），"锁的原文长什么样"
      属于 `locks` 这一层（本模块已经在管 `status` 的说辞与判据）；守卫只吃 `parse_entries` 的产物。
    """
    entries: list[dict] = []
    for raw in body.splitlines():
        hit = _ENTRY_RE.match(raw.strip())
        if hit is None:
            continue
        entries.append({
            "base": hit.group("base"),
            "file": hit.group("file"),
            "card": hit.group("card"),
            "pid": hit.group("pid"),
            "at": hit.group("at"),
            "age": int(hit.group("age")),
            "remain": int(hit.group("remain")),
            "lease": hit.group("lease"),
            "cwd": hit.group("cwd"),
        })
    return entries
