"""Public selection parameter models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SelectParams(BaseModel):
    """Arguments that can be fed into ``patch.select``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kwargs: dict[str, tuple[Any, Any]] = Field(default_factory=dict)
    relative: bool = False
    samples: bool = False

    @model_validator(mode="after")
    def _validate_basis_flags(self) -> SelectParams:
        """Reject mutually exclusive DASCore selection bases."""
        if self.relative and self.samples:
            raise ValueError("relative and samples cannot both be true")
        return self

    def apply_to_patch(self, patch):
        """Apply these parameters to a patch."""
        if not self.kwargs:
            return patch
        return patch.select(
            copy=False,
            relative=self.relative,
            samples=self.samples,
            **self.kwargs,
        )
