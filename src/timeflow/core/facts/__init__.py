"""事实层：与心智模型无关的「发生了什么」。

设计要点（见 复盘/事实层架构设计复盘.md）：
- 事实只记「发生了什么」，不含「算成什么」（那是解读层 ledger 的事）。
- kind 为自由字符串（"域.动作"），加新事实类型**不改表**。
- 高频数值/文本放固定列（可索引），罕见字段放 extra(JSON) 兜底。
- revision/supersedes 为修正机制**预留**，MVP 不实现逻辑。

本层不属于任何解读层——它是各业务线（focus/tasks/review/…）与框架（ledger）
之间的解耦通道。
"""

from timeflow.core.facts.bus import (
    clear,
    errors,
    list_subscribers,
    publish,
    subscribe,
    unsubscribe,
)
from timeflow.core.facts.store import (
    count,
    latest_by_subject,
    query,
    record,
)

__all__ = [
    "record",
    "query",
    "count",
    "latest_by_subject",
    "publish",
    "subscribe",
    "unsubscribe",
    "list_subscribers",
    "clear",
    "errors",
]
