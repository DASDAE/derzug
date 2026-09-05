"""Shared execution for widgets that transform one patch into another."""

from __future__ import annotations

import dascore as dc

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.workflow import Pipe, Task


class PatchWidget(ZugWidget, openclass=True):
    """Execute patch tasks with shared input, output, and preflight handling.

    Subclasses supply their controls, input handler, and ``get_task()``. They
    can override ``_validated_task()`` to report preflight errors or
    ``_on_result()`` to update a preview alongside the output signal.
    """

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the output patch."""
        self.Outputs.patch.send(result)

    def _supports_async_execution(self) -> bool:
        """Run patch-processing widgets off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build the default one-patch execution request."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _validated_task(self) -> Task | Pipe | None:
        """Return the current task after any widget-specific preflight."""
        return self.get_task()

    def _run(self) -> dc.Patch | None:
        """Execute the validated task against the current patch input."""
        patch = self._patch
        if patch is None:
            return None
        return self._execute_workflow_object(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )
