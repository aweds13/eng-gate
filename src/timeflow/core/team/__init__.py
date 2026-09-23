"""团队/AI 协作子包：re-export 领域逻辑。"""
from timeflow.core.team.team import (
    ASSIGN_STATUSES,
    ROLE_EXECUTOR,
    ROLE_MANAGER,
    STATUS_LABELS,
    VIEW_EXECUTOR,
    VIEW_LABELS,
    VIEW_MANAGER,
    assign_task,
    assignments,
    assignments_for_task,
    board,
    update_assignment_status,
    views_meta,
)

__all__ = [
    "ROLE_MANAGER",
    "ROLE_EXECUTOR",
    "VIEW_MANAGER",
    "VIEW_EXECUTOR",
    "VIEW_LABELS",
    "ASSIGN_STATUSES",
    "STATUS_LABELS",
    "assign_task",
    "update_assignment_status",
    "assignments",
    "assignments_for_task",
    "board",
    "views_meta",
]
