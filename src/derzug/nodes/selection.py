"""Selection tasks shared by the Select and Waterfall nodes.

Both nodes persist their dimension ranges as one serialized payload and replay
it against whatever patch arrives. The payload format and the coordinate maths
belong to :mod:`derzug.models.selection_state`; this module only wraps them as
workflow tasks.
"""

from __future__ import annotations

from typing import Any, ClassVar

from derzug.models.selection import SelectParams
from derzug.models.selection_state import SelectionState
from derzug.workflow.task import Task


def selection_payload_from_settings(
    basis: object, rows: object
) -> dict[str, Any] | None:
    """Return the serialized selection payload for persisted basis and rows.

    ``None`` means "no selection was saved", which the tasks read as "pass the
    patch through untouched".
    """
    basis_name = str(basis or "").strip()
    row_list = rows if isinstance(rows, list) else []
    if not basis_name or not row_list:
        return None
    return {"basis": basis_name, "rows": row_list}


def _primed_state(payload: dict[str, Any] | None, patch) -> SelectionState | None:
    """Return selection state primed from ``payload``, or None if inapplicable."""
    if not payload:
        return None
    state = SelectionState()
    if not state.prime_patch_state_from_settings(payload):
        return None
    state.set_patch_source(patch)
    return state


class PatchSelectionTask(Task):
    """Apply persisted patch-selection state to one patch."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    selection_payload: dict[str, Any] | None = None

    def run(self, patch):
        """Apply serialized patch-selection state to one patch."""
        state = _primed_state(self.selection_payload, patch)
        return patch if state is None else state.apply_to_patch(patch)


class PatchSelectionWithParamsTask(Task):
    """Apply patch-selection state and also expose public select parameters."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "select_params": object,
    }

    selection_payload: dict[str, Any] | None = None

    def run(self, patch):
        """Return the selected patch and matching SelectParams."""
        state = _primed_state(self.selection_payload, patch)
        if state is None:
            return {"patch": patch, "select_params": SelectParams()}
        return {
            "patch": state.apply_to_patch(patch),
            "select_params": state.to_select_params(),
        }


__all__ = (
    "PatchSelectionTask",
    "PatchSelectionWithParamsTask",
    "selection_payload_from_settings",
)
