"""
Shared model helpers for the workflow runtime.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WorkflowModel(BaseModel):
    """Base model for workflow-layer data structures."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    def new(self, **update):
        """Return a copy with updated fields."""
        return self.model_copy(update=update)


class WorkflowFrozenModel(WorkflowModel):
    """Immutable workflow base model."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)
