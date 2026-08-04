"""The Select node: narrow a patch or filter a spool from persisted state.

Select accepts either kind of input and one of two ways to describe the
selection — its own persisted ranges, or a :class:`SelectParams` arriving on a
port from an upstream viewer — so the task branches on what it actually gets.
"""

from __future__ import annotations

from copy import deepcopy
from typing import ClassVar

import dascore as dc
import numpy as np
from pydantic import BaseModel, Field

from derzug.models.annotations import AnnotationSet
from derzug.models.selection import SelectParams
from derzug.models.selection_state import SelectionState
from derzug.nodes.selection import PatchSelectionTask, selection_payload_from_settings
from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.spool import annotation_overlap_mask, extract_single_patch
from derzug.workflow.task import Task


class SelectTask(Task):
    """Workflow task mirroring Select's persisted patch/spool semantics."""

    input_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "spool": object,
        "annotation_set": object,
        "select_params": object,
    }
    output_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "spool": object,
    }

    patch_selection_payload: dict[str, object] | None = None
    spool_filters: tuple[tuple[str, str], ...] = ()
    unpack_single_patch: bool = True

    def run(self, patch=None, spool=None, annotation_set=None, select_params=None):
        """Apply persisted selection state to a patch or spool input."""
        if patch is not None:
            if select_params is not None:
                return {"patch": select_params.apply_to_patch(patch), "spool": None}
            selected = PatchSelectionTask(
                selection_payload=self.patch_selection_payload
            ).run(patch)
            return {"patch": selected, "spool": None}

        if spool is not None:
            selected = spool
            if select_params is not None:
                selected = select_params.apply_to_spool(selected)
            if annotation_set is not None:
                contents = selected.get_contents()
                mask = annotation_overlap_mask(contents, annotation_set)
                if not bool(mask.all()):
                    positions = np.flatnonzero(mask.to_numpy(dtype=bool, copy=False))
                    if not positions.size:
                        selected = dc.spool([])
                    else:
                        selected = selected[positions.astype(np.int64, copy=False)]
            state = SelectionState()
            state.set_spool_source(selected)
            state.set_spool_filters(list(self.spool_filters))
            selected = state.apply_to_spool(selected)
            selected_patch = None
            if self.unpack_single_patch:
                selected_patch = extract_single_patch(selected)
            return {"patch": selected_patch, "spool": selected}

        return {"patch": None, "spool": None}


class SelectWidgetParams(BaseModel):
    """Parameters for the Select node (named to avoid the models.SelectParams)."""

    unpack_single_patch: bool = True
    saved_patch_selection: dict = Field(default_factory=dict)
    saved_selection_basis: str = ""
    saved_selection_ranges: list = Field(default_factory=list)
    saved_spool_filters: list = Field(default_factory=list)


def saved_patch_selection_payload(
    payload: object, basis: object, rows: object
) -> dict[str, object] | None:
    """Return the patch-selection payload for persisted Select settings.

    ``saved_patch_selection`` is the current single-blob form; the separate
    basis and ranges are the older shape, kept as a fallback so a workflow
    saved before the merge still restores its selection.
    """
    if isinstance(payload, dict):
        basis_name = str(payload.get("basis", "")).strip()
        payload_rows = payload.get("rows")
        if basis_name and isinstance(payload_rows, list) and payload_rows:
            return {"basis": basis_name, "rows": deepcopy(payload_rows)}
    resolved = selection_payload_from_settings(basis, rows)
    if resolved is None:
        return None
    return {"basis": resolved["basis"], "rows": deepcopy(resolved["rows"])}


def saved_spool_filter_rows(rows: object) -> list[tuple[str, str]]:
    """Return persisted spool filter rows as (key, raw value) pairs."""
    restored: list[tuple[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        raw_value = str(row.get("raw_value", ""))
        if not key and not raw_value:
            continue
        restored.append((key, raw_value))
    return restored


def select_task_from_params(params: SelectWidgetParams | None = None) -> SelectTask:
    """Build the configured selection task from persisted Select settings."""
    params = SelectWidgetParams() if params is None else params
    return SelectTask(
        patch_selection_payload=saved_patch_selection_payload(
            params.saved_patch_selection,
            params.saved_selection_basis,
            params.saved_selection_ranges,
        ),
        spool_filters=tuple(saved_spool_filter_rows(params.saved_spool_filters)),
        unpack_single_patch=bool(params.unpack_single_patch),
    )


NODE_SPEC = NodeSpec(
    name="Select",
    widget_qualified_name="derzug.widgets.select.Select",
    inputs=(
        PortSpec(name="patch", display_name="Patch", type=dc.Patch),
        PortSpec(name="spool", display_name="Spool", type=dc.BaseSpool),
        PortSpec(name="annotation_set", display_name="Annotations", type=AnnotationSet),
        PortSpec(name="select_params", display_name="Select Params", type=SelectParams),
    ),
    outputs=(
        PortSpec(name="patch", display_name="Patch", type=dc.Patch),
        PortSpec(name="spool", display_name="Spool", type=dc.BaseSpool),
    ),
    params_model=SelectWidgetParams,
    task_factory=select_task_from_params,
    category="Processing",
    description="Select subsets of patches or spools",
    keywords=("select", "patch", "spool", "subset", "filter"),
    icon="icons/SelectRows.svg",
    priority=23,
)
