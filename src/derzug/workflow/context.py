"""
A class for managing context of runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..core import DerzugModel

if TYPE_CHECKING:
    from .pipe import Pipe


class ExecutionContext(DerzugModel):
    """
    Execution context provided to context-aware tasks during pipeline execution.

    This context allows tasks to access pipeline state, intermediate results,
    and execution metadata during runtime.
    """

    pipe: Pipe
    results: dict[str, Any] = Field(default_factory=dict)

    @property
    def task_count(self) -> int:
        """Total number of tasks in the pipeline."""
        return len(self.pipe.tasks)

    @property
    def completed_count(self) -> int:
        """Number of completed tasks."""
        return len(self.results)
