"""专注线订阅器：把 `focus.finished` 事实传导到其它线（第 2 步）。

设计（见 `复盘/长任务执行协议.md` §七「第 2 步」）：
- 业务线只**发事实**，跨线联动由**订阅者**在事实层之上接线，避免各线互相直接调用。
- 订阅器是**同步执行**（事件总线约定），因此 `finish_session` 返回时联动已生效。
- 订阅器不吞异常：出错由事件总线记入 `facts.errors`（局部隔离，不影响其它订阅者）。

接线方式（重要）：
- `facts.publish(kind, payload)` 只带 payload，不带数据库连接；因此 handler 需要知道用哪个连接。
- 这里维护**连接注册表**而非全局单例：每个 app 启动时 `register(conn)` 注册自己的连接，
  handler 按 payload 语义路由到对应连接。测试里多个 app/连接并存时不会互相串库。
- 注册**幂等**：同一连接重复注册不叠加订阅（`_installed` 标记）。

当前接线：
- `focus.finished` → 当日反馈 `focus_minutes` 按事实重算落库（FLOW-4 / F4 OP-17）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from timeflow import clock
from timeflow.core import facts as facts_mod
from timeflow.core import feedback as fb
from timeflow.core.focus import timer

_conns: list[sqlite3.Connection] = []
_installed = False
_TAG = "_timeflow_focus_line"


def _remember(conn: sqlite3.Connection) -> None:
    if all(existing is not conn for existing in _conns):
        _conns.append(conn)


def _pick_conn(event_conn: sqlite3.Connection | None = None) -> sqlite3.Connection | None:
    """选一条可用连接：优先事件自带的，其次唯一/最近注册的。"""
    if event_conn is not None:
        return event_conn
    if not _conns:
        return None
    return _conns[-1]


def _on_focus_finished(payload: dict[str, Any]) -> None:
    """正常结束专注 → 该完成日的反馈 focus_minutes 按事实重算落库。

    重算（而非累加）保证幂等：同一会话重复发布、或历史回填都不会重复计量。
    """
    event_conn = payload.get("conn")
    conn = _pick_conn(event_conn if isinstance(event_conn, sqlite3.Connection) else None)
    if conn is None:
        return
    occurred = str(payload.get("occurred_at") or "")
    day = occurred[:10] or clock.today_iso()
    minutes = timer.focus_minutes_from_facts(conn, day)
    fb.upsert_focus_minutes(conn, day, minutes)


def register(conn: sqlite3.Connection) -> bool:
    """注册一条连接并（首次）把订阅器接到事件总线；已接线则返回 False。"""
    _remember(conn)
    if _installed and any(
        getattr(handler, _TAG, False) for _pattern, handler in facts_mod.list_subscribers()
    ):
        return False

    def handler(_kind: str, payload: dict[str, Any]) -> None:
        _on_focus_finished(payload)

    setattr(handler, _TAG, True)  # noqa: B010 —— 用标记做幂等判断
    facts_mod.subscribe("focus.finished", handler)
    globals()["_installed"] = True
    return True


def registered_connections() -> list[sqlite3.Connection]:
    """只读：当前注册的连接（供排查/测试）。"""
    return list(_conns)


def reset_for_tests() -> None:
    """仅供测试：清空连接注册表与接线标记（配合 `facts.clear()`）。"""
    _conns.clear()
    globals()["_installed"] = False
