"""The Spool node: load a DASCore spool, then select, chunk, and unpack it.

Everything a saved Spool node needs to reproduce its source lives here: the
example registry, the persisted-settings loader, and the select/chunk steps
applied on top. ``derzug.widgets.spool`` adds the table, the file pickers, and
the parameter dialog.
"""

from __future__ import annotations

import ast
from typing import Any, ClassVar

import dascore as dc
import numpy as np
import pandas as pd
from dascore.clients.dirspool import DirectorySpool
from pydantic import BaseModel, Field

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.example_parameters import build_example_call_kwargs
from derzug.utils.spool import extract_single_patch
from derzug.workflow.task import Task

DEFAULT_EXAMPLE = "example_event_2"

# Examples that aren't terribly interesting so we dont include them in the
# the drop down menu.
IGNORE_EXAMPLES = (
    "diverse_das",
    "random_directory_das",
    "patch_with_null",
    "wacky_dim_coords_patch",
)


def all_examples(ignore=()) -> dict[str, object]:
    """Return a single dict of all registered example callables, spools first."""
    examples = {**dc.examples.EXAMPLE_SPOOLS, **dc.examples.EXAMPLE_PATCHES}
    out = {i: v for i, v in examples.items() if i not in ignore}
    return out


def ordered_contents_df_with_source_rows(spool: dc.BaseSpool) -> pd.DataFrame:
    """Return spool contents in display order with source-row mapping preserved."""
    df = spool.get_contents()
    if df.empty:
        ordered = df.copy()
        ordered["_source_row"] = pd.Series(dtype=np.int64)
        return ordered
    ordered = df.copy()
    ordered["_source_row"] = np.arange(len(ordered), dtype=np.int64)
    if not isinstance(spool, DirectorySpool):
        return ordered
    sort_cols = [
        column
        for column in ("path", "tag", "station", "network", "time_min", "time_max")
        if column in ordered.columns
    ]
    sort_cols.append("_source_row")
    return ordered.sort_values(
        by=sort_cols,
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def spool_indices_for_rows(
    spool: dc.BaseSpool,
    selected_rows: set[int] | frozenset[int],
) -> list[int]:
    """Map visible row indices onto spool indices without loading patch payloads."""
    if not selected_rows:
        return []
    if not hasattr(spool, "get_contents"):
        return sorted(int(row) for row in selected_rows)
    ordered_df = ordered_contents_df_with_source_rows(spool)
    indices = []
    for row in sorted(selected_rows):
        if row < 0 or row >= len(ordered_df):
            raise IndexError(row)
        indices.append(int(ordered_df.iloc[row]["_source_row"]))
    return indices


def spool_rows_to_output(
    spool: dc.BaseSpool,
    selected_rows: set[int] | frozenset[int],
) -> dc.BaseSpool:
    """Return a lazily indexed spool for the selected display rows."""
    indices = spool_indices_for_rows(spool, selected_rows)
    if not indices:
        return spool
    if hasattr(spool, "get_contents"):
        return spool[np.asarray(indices, dtype=np.int64)]
    if len(indices) == 1:
        index = int(indices[0])
        return dc.spool(spool[index : index + 1])
    return dc.spool([spool[int(index)] for index in indices])


def spool_rows_to_patches(
    spool: dc.BaseSpool,
    selected_rows: set[int] | frozenset[int],
) -> list[dc.Patch]:
    """Return selected patch payloads without iterating unrelated rows."""
    return [spool[index] for index in spool_indices_for_rows(spool, selected_rows)]


def load_spool_from_settings(
    *,
    spool_input: str | None,
    example_parameters: dict[str, object] | None,
    file_input: str,
    raw_input: str,
) -> dc.BaseSpool:
    """Load a spool using the widget's persisted source settings."""
    if file_input.strip():
        return dc.spool(file_input.strip())
    if raw_input.strip():
        return dc.spool(raw_input.strip())
    if not spool_input:
        raise ValueError("No spool source configured")
    registry = all_examples(ignore=IGNORE_EXAMPLES)
    fn = registry[spool_input]
    saved = example_parameters or {}
    overrides = saved.get(spool_input, {}) if isinstance(saved, dict) else {}
    kwargs = build_example_call_kwargs(
        fn,
        overrides if isinstance(overrides, dict) else {},
    )
    result = fn(**kwargs)
    if isinstance(result, dc.Patch):
        return dc.spool([result])
    return result


def apply_select_rows(
    spool: dc.BaseSpool,
    select_filters: tuple[dict[str, str], ...],
) -> dc.BaseSpool:
    """Apply persisted select rows to a spool."""
    kwargs = {}
    for filter_data in select_filters:
        key = str(filter_data.get("key", "")).strip()
        raw_value = str(filter_data.get("raw", "")).strip()
        if not key or not raw_value:
            continue
        try:
            value = ast.literal_eval(raw_value)
        except Exception:
            value = raw_value
        if value is None:
            continue
        kwargs[key] = value
    if not kwargs:
        return spool
    return spool.select(**kwargs)


def apply_chunk_settings(
    spool: dc.BaseSpool,
    *,
    chunk_enabled: bool,
    chunk_dim: str,
    chunk_value: str,
    chunk_overlap: str,
    chunk_keep_partial: bool,
    chunk_snap_coords: bool,
    chunk_tolerance: float,
    chunk_conflict: str,
) -> dc.BaseSpool:
    """Apply persisted chunk settings to a spool."""
    if not bool(chunk_enabled):
        return spool
    dim = chunk_dim.strip()
    raw_value = chunk_value.strip()
    if not dim or not raw_value:
        return spool
    try:
        value = ast.literal_eval(raw_value)
    except Exception:
        value = raw_value
    overlap = None
    if chunk_overlap.strip():
        try:
            overlap = ast.literal_eval(chunk_overlap.strip())
        except Exception:
            overlap = chunk_overlap.strip()
    return spool.chunk(
        **{
            dim: value,
            "overlap": overlap,
            "keep_partial": bool(chunk_keep_partial),
            "snap_coords": bool(chunk_snap_coords),
            "tolerance": float(chunk_tolerance),
            "conflict": chunk_conflict,
        }
    )


class SpoolParams(BaseModel):
    """Parameters for the Spool source widget (source + chunk + select config)."""

    spool_input: Any = None
    example_parameters: dict = Field(default_factory=dict)
    file_input: str = ""
    raw_input: str = ""
    chunk_dim: str = ""
    chunk_enabled: bool = True
    chunk_value: str = ""
    chunk_overlap: str = ""
    chunk_keep_partial: bool = False
    chunk_snap_coords: bool = True
    chunk_tolerance: float = 1.5
    chunk_conflict: str = "raise"
    select_filters: list = Field(default_factory=list)
    select_col: str = ""
    select_val: str = ""
    selected_source_row: Any = None
    selected_source_patch_name: str = ""
    unpack_single_patch: bool = True


class SpoolTask(Task):
    """Portable loader task mirroring the widget's bound-source semantics."""

    output_variables: ClassVar[dict[str, object]] = {
        "spool": object,
        "patch": object,
    }

    spool_input: str | None = None
    example_parameters: dict[str, object] = Field(default_factory=dict)
    file_input: str = ""
    raw_input: str = ""
    chunk_enabled: bool = True
    chunk_dim: str = ""
    chunk_value: str = ""
    chunk_overlap: str = ""
    chunk_keep_partial: bool = False
    chunk_snap_coords: bool = True
    chunk_tolerance: float = 1.5
    chunk_conflict: str = "raise"
    select_filters: tuple[dict[str, str], ...] = ()
    selected_source_row: int | None = None
    unpack_single_patch: bool = True

    def run(self):
        """Load and post-process the configured spool source."""
        spool = load_spool_from_settings(
            spool_input=self.spool_input,
            example_parameters=self.example_parameters,
            file_input=self.file_input,
            raw_input=self.raw_input,
        )
        spool = apply_select_rows(spool, self.select_filters)
        spool = apply_chunk_settings(
            spool,
            chunk_enabled=self.chunk_enabled,
            chunk_dim=self.chunk_dim,
            chunk_value=self.chunk_value,
            chunk_overlap=self.chunk_overlap,
            chunk_keep_partial=self.chunk_keep_partial,
            chunk_snap_coords=self.chunk_snap_coords,
            chunk_tolerance=self.chunk_tolerance,
            chunk_conflict=self.chunk_conflict,
        )
        if self.selected_source_row is not None:
            spool = spool_rows_to_output(spool, {int(self.selected_source_row)})
        patch = extract_single_patch(spool) if self.unpack_single_patch else None
        return {"spool": spool, "patch": patch}


class SpoolTransformTask(Task):
    """Apply persisted Spool select/chunk/output settings to an input spool."""

    input_variables: ClassVar[dict[str, object]] = {"spool": object}
    output_variables: ClassVar[dict[str, object]] = {
        "spool": object,
        "patch": object,
    }

    chunk_enabled: bool = True
    chunk_dim: str = ""
    chunk_value: str = ""
    chunk_overlap: str = ""
    chunk_keep_partial: bool = False
    chunk_snap_coords: bool = True
    chunk_tolerance: float = 1.5
    chunk_conflict: str = "raise"
    select_filters: tuple[dict[str, str], ...] = ()
    selected_source_row: int | None = None
    unpack_single_patch: bool = True

    def run(self, spool):
        """Apply select/chunk settings to an input spool."""
        spool = apply_select_rows(spool, self.select_filters)
        spool = apply_chunk_settings(
            spool,
            chunk_enabled=self.chunk_enabled,
            chunk_dim=self.chunk_dim,
            chunk_value=self.chunk_value,
            chunk_overlap=self.chunk_overlap,
            chunk_keep_partial=self.chunk_keep_partial,
            chunk_snap_coords=self.chunk_snap_coords,
            chunk_tolerance=self.chunk_tolerance,
            chunk_conflict=self.chunk_conflict,
        )
        if self.selected_source_row is not None:
            spool = spool_rows_to_output(spool, {int(self.selected_source_row)})
        patch = extract_single_patch(spool) if self.unpack_single_patch else None
        return {"spool": spool, "patch": patch}


def spool_task_from_params(params: SpoolParams | None = None) -> SpoolTask:
    """Build the configured spool-source task."""
    params = SpoolParams() if params is None else params
    row = params.selected_source_row
    return SpoolTask(
        spool_input=params.spool_input,
        example_parameters=dict(params.example_parameters or {}),
        file_input=str(params.file_input or ""),
        raw_input=str(params.raw_input or ""),
        chunk_enabled=bool(params.chunk_enabled),
        chunk_dim=str(params.chunk_dim or ""),
        chunk_value=str(params.chunk_value or ""),
        chunk_overlap=str(params.chunk_overlap or ""),
        chunk_keep_partial=bool(params.chunk_keep_partial),
        chunk_snap_coords=bool(params.chunk_snap_coords),
        chunk_tolerance=float(params.chunk_tolerance),
        chunk_conflict=str(params.chunk_conflict or "raise"),
        select_filters=tuple(params.select_filters or ()),
        selected_source_row=None if row is None else int(row),
        unpack_single_patch=bool(params.unpack_single_patch),
    )


def spool_transform_task_from_params(
    params: SpoolParams | None = None,
) -> SpoolTransformTask:
    """Build the select/chunk-only task used when a spool arrives on a port."""
    source = spool_task_from_params(params)
    fields = set(SpoolTransformTask.model_fields) & set(SpoolTask.model_fields)
    return SpoolTransformTask(
        **{name: getattr(source, name) for name in sorted(fields)}
    )


NODE_SPEC = NodeSpec(
    name="Spool",
    widget_qualified_name="derzug.widgets.spool.Spool",
    inputs=(
        PortSpec(
            name="patch", display_name="Patch", type=dc.Patch, context_only=True
        ),
        PortSpec(
            name="spool",
            display_name="Spool",
            type=dc.BaseSpool,
            context_only=True,
        ),
    ),
    outputs=(
        PortSpec(name="spool", display_name="Spool", type=dc.BaseSpool),
        PortSpec(name="patch", display_name="Patch", type=dc.Patch),
    ),
    params_model=SpoolParams,
    task_factory=spool_task_from_params,
    is_source=True,
    category="IO",
    description="Interact with DASCore Spools",
    keywords=("dascore", "examples", "spool", "patch"),
    icon="icons/Spool.svg",
    priority=15,
)
