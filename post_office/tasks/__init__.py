"""Work as data: what has to be done, by whom, and what became of it."""

from .task import (ALLOWED_TRANSITIONS, IllegalTransition, Task, TaskStatus,
                   TaskType, TERMINAL_STATUSES)
from .registry import TaskRegistry

__all__ = [
    "Task", "TaskType", "TaskStatus", "TERMINAL_STATUSES",
    "ALLOWED_TRANSITIONS", "IllegalTransition", "TaskRegistry",
]
