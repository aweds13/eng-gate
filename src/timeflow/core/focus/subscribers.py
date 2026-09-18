"""专注线订阅器：把 `focus.finished` 事实传导到其它线（第 2 步）。

设计（见 `复盘/长任务执行协议.md` §七「第 2 步」）：
- 业务线只**发事实**，跨线联动由**订阅者**在事实层之上接线，避免各线互相直接调用。
- 订阅器是**同步执行**（事件总线约定），因此 `finish_session` 返回时联动已生效。
- 注册**幂等且与总线状态一致**：重复调用不会叠加订阅；总线被 `clear()` 后再次注册会恢复。
- 订阅器不吞异常：出错由事件总线记入 `facts.errors`（局部隔离，不影响其它订阅者）。

当前接线：
- `focus.finished` → 当日反馈 `focus_minutes` 自动累加（FLOW-4 / F4 OP-17）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core.focus import timer

if TYPE_CHECKING:
    import sqlite3

_TAG = "_timeflow_focus_line"


def _on_focus_finished(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    """正常结束专注 → 该完成日的反馈 focus_minutes 按事实重算落库。

    重算（而非累加）保证幂等：同一会话重复发布、或历史回填都不会重复计量。
    """
    occurred = str(payload.get("occurred_at") or "")
    day = occurred[:10] or datetime.now().date().isoformat()
    minutes = timer.focus_minutes_from_facts(conn, day)
    fb.upsert_focus_minutes(conn, day, minutes)


def register(conn: sqlite3.Connection) -> bool:
    """把专注线订阅器接到事件总线；已在总线上则返回 False（幂等）。"""
    if any(getattr(handler, _TAG, False) for _pattern, handler in facts_mod.list_subscribers()):
        return False

    def handler(_kind: str, payload: dict[str, Any]) -> None:
        _on_focus_finished(conn, payload)

    setattr(handler, _TAG, True)  # noqa: B010 —— 用标记做与总线状态一致的幂等判断
    facts_mod.subscribe("focus.finished", handler)
    return True
