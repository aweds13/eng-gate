"""团队/AI 协作子包：re-export 领域逻辑。"""
from timeflow.core.team.team import (
    ROLE_EXECUTOR,
    ROLE_MANAGER,
    assign_task,
    assignments,
    assignments_for_task,
    update_assignment_status,
)

__all__ = [
    "ROLE_MANAGER",
    "ROLE_EXECUTOR",
    "assign_task",
    "update_assignment_status",
    "assignments",
    "assignments_for_task",
]
