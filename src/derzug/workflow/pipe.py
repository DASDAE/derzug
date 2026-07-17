"""
Public workflow graph and execution entrypoints.
"""

from __future__ import annotations

import platform
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import cache

import derzug

from .executor import STREAM_END, StreamingExecutor, build_task_runtime_specs
from .graph import Edge, PipeBuilder, PipeGraph
from .provenance import Provenance
from .results import Results


class Pipe(PipeGraph):
    """A static DAG of tasks with streaming-aware execution."""

    def run(
        self,
        *args,
        output_keys: list[str] | tuple[str, ...] | None = None,
        strict: bool = True,
        provenance: Provenance | tuple[Provenance, ...] | None = None,
        **kwargs,
    ) -> Results:
        """Execute one workflow invocation."""
        source_provenance = _normalize_source_provenance(provenance)
        return StreamingExecutor(
            self,
            requested_outputs=list(output_keys or []),
            strict=strict,
            source_provenance=source_provenance,
        ).execute(*args, **kwargs)

    def map(
        self,
        source: Iterable[object],
        *,
        output_keys: list[str] | tuple[str, ...] | None = None,
        strict: bool = True,
        provenance: Provenance | tuple[Provenance, ...] | None = None,
    ) -> Iterable[Results]:
        """Apply the pipe to each item in a source."""
        source_provenance = _normalize_source_provenance(provenance)
        if isinstance(source, derzug.Source):
            source_provenance = (
                _normalize_source_provenance(source.provenance) + source_provenance
            )
        task_specs = build_task_runtime_specs(self)
        for item in source:
            yield StreamingExecutor(
                self,
                requested_outputs=list(output_keys or []),
                strict=strict,
                source_provenance=source_provenance,
                task_specs=task_specs,
            ).execute(item)

    def get_provenance(
        self,
        source_provenance: tuple[Provenance, ...] = (),
        **additional_metadata,
    ) -> Provenance:
        """Create a provenance record for this workflow run."""
        return Provenance(
            pipe=self,
            derzug_version=getattr(derzug, "__version__", "unknown"),
            created_at=datetime.now(UTC),
            python_version=_runtime_environment()[0],
            system_info=dict(_runtime_environment()[1]),
            metadata=additional_metadata,
            source_provenance=source_provenance,
        )


@cache
def _runtime_environment() -> tuple[str, tuple[tuple[str, str], ...]]:
    """Return process-level provenance fields that do not change per run."""
    return (
        platform.python_version(),
        (
            ("platform", platform.platform()),
            ("machine", platform.machine()),
            ("processor", platform.processor()),
        ),
    )


def _normalize_source_provenance(
    provenance: Provenance | tuple[Provenance, ...] | None,
) -> tuple[Provenance, ...]:
    """Normalize source provenance inputs into a tuple."""
    if provenance is None:
        return ()
    if hasattr(provenance, "to_source_provenance"):
        return provenance.to_source_provenance()
    if isinstance(provenance, tuple):
        return provenance
    return (provenance,)


Pipe.model_rebuild()
Provenance.model_rebuild(_types_namespace={"Pipe": Pipe})

__all__ = ("STREAM_END", "Edge", "Pipe", "PipeBuilder", "Results")
