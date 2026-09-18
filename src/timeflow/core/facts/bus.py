"""事件总线：业务线「发事实」，解读层「订阅事实」。

设计要点（见 复盘/事实层架构设计复盘.md §四）：
- **同步执行**：publish 当场、按注册顺序通知所有订阅者。本地单机无性能压力，
  换来「强一致」（发布返回时订阅者已处理完）与「易调试」（同步堆栈）。
- **异常隔离**：单个订阅者抛异常不影响其它订阅者（对应 SR-NF6 局部错误隔离），
  异常被记录到 errors 列表供排查，不向上抛。
- **通配订阅**：支持 "focus.*" 匹配 "focus.finished"。

本模块是纯进程内总线（不持久化）。事实的持久化在 facts.store。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# payload 允许携带任意值（含 sqlite 连接）：发布方常需把「用哪个库」一并交给订阅者，
# 否则订阅者只能靠全局单例猜连接，多个 app/连接并存时会串库。
Handler = Callable[[str, dict[str, Any]], None]

_subscribers: list[tuple[str, Handler]] = []
errors: list[tuple[str, BaseException]] = []


def subscribe(kind_pattern: str, handler: Handler) -> None:
    """订阅某类事实。kind_pattern 支持后缀 "*" 通配（如 "focus.*"）。"""
    if not kind_pattern:
        raise ValueError("订阅的 kind 不能为空")
    _subscribers.append((kind_pattern, handler))


def unsubscribe(kind_pattern: str, handler: Handler) -> bool:
    """取消订阅；存在并移除则返回 True。"""
    for i, (pat, h) in enumerate(_subscribers):
        if pat == kind_pattern and h is handler:
            _subscribers.pop(i)
            return True
    return False


def list_subscribers() -> list[tuple[str, Handler]]:
    """当前订阅者快照（只读，供排查/自检/幂等注册判断）。"""
    return list(_subscribers)


def publish(kind: str, payload: dict[str, Any] | None = None) -> int:
    """发布一条事实（同步通知订阅者），返回被通知的订阅者数量。

    订阅者异常被捕获并记入 errors，不中断其它订阅者。
    """
    data = payload or {}
    notified = 0
    for pattern, handler in list(_subscribers):
        if not _matches(pattern, kind):
            continue
        notified += 1
        try:
            handler(kind, data)
        except Exception as exc:  # noqa: BLE001 —— 刻意隔离，避免单点故障扩散
            errors.append((kind, exc))
    return notified


def _matches(pattern: str, kind: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return kind.startswith(pattern[:-1])
    return pattern == kind


def clear() -> None:
    """清空订阅者与错误记录（主要供测试用）。"""
    _subscribers.clear()
    errors.clear()
