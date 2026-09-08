"""任务管理子包：re-export 领域逻辑，方便 `timeflow.core.tasks` 直接使用。"""

from timeflow.core.tasks.groups import (
    create_group,
    get_task_groups,
    list_groups,
    set_task_groups,
)
from timeflow.core.tasks.manager import (
    STATUS_ARCHIVED,
    STATUS_CANCELLED,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_TODO,
    Task,
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    myday_tasks,
    overdue_tasks,
    process_repeats,
    update_task,
)

__all__ = [
    "Task",
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "delete_task",
    "myday_tasks",
    "overdue_tasks",
    "complete_task",
    "process_repeats",
    "create_group",
    "list_groups",
    "set_task_groups",
    "get_task_groups",
    "STATUS_TODO",
    "STATUS_DOING",
    "STATUS_DONE",
    "STATUS_OVERDUE",
    "STATUS_CANCELLED",
    "STATUS_ARCHIVED",
]
