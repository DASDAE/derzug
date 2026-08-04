"""The Coords node: rename, drop, sort, snap, flip, or transpose coordinates.

One node covers all of DASCore's coordinate operations because they share a
patch-in/patch-out shape and a single widget; ``operation`` selects which one
runs and the remaining parameters configure it.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import dascore as dc
from dascore.core.coords import get_coord
from pydantic import BaseModel, Field

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.parsing import parse_coord_text_value
from derzug.workflow.task import Task


def normalize_mapping_rows(rows: object) -> list[list[str]]:
    """Return persisted mapping-table rows as a list of two-string lists."""
    output: list[list[str]] = []
    for row in rows or []:
        if isinstance(row, list | tuple) and len(row) >= 2:
            output.append([str(row[0]), str(row[1])])
    return output


class CoordsValidationError(ValueError):
    """Raised when persisted coords parameters do not fit the incoming patch.

    ``kind`` and ``label`` let the widget route the failure to the matching
    error banner without re-implementing the validation itself.
    """

    def __init__(self, kind: str, detail: str, label: str = "") -> None:
        super().__init__(detail)
        self.kind = kind
        self.label = label
        self.detail = detail


def resolve_set_coord(patch, dim: str, start: str, stop: str, step: str):
    """Return the replacement coordinate built from sparse set-coords text.

    Raises ``CoordsValidationError`` when the dimension is missing, a value
    does not parse, no value is given, or the coordinate cannot be built.
    Shared by ``CoordsTask.run`` and the widget's draft validation so both
    accept and reject exactly the same inputs.
    """
    if dim not in patch.dims:
        raise CoordsValidationError(
            "set_coords", f"'{dim}' is not an available dimension"
        )
    coord = patch.coords.get_coord(dim)
    parsed: dict[str, object] = {}
    for label, raw in (("start", start), ("stop", stop), ("step", step)):
        text = str(raw).strip()
        if not text:
            continue
        try:
            value = parse_coord_text_value(text, getattr(coord, label), None)
        except Exception as exc:
            raise CoordsValidationError(
                "set_coords", f"could not parse {label}: {exc}"
            ) from exc
        parsed[label] = value
    if not parsed:
        raise CoordsValidationError(
            "set_coords", "at least one of start, stop, and step is required"
        )
    if set(parsed) == {"start"} or set(parsed) == {"stop"}:
        parsed["step"] = coord.step
    elif set(parsed) == {"step"}:
        parsed["start"] = coord.start
    kwargs = {
        "shape": patch.shape[patch.dims.index(dim)],
        "units": coord.units,
        "dtype": coord.dtype,
        **parsed,
    }
    try:
        return get_coord(**kwargs)
    except Exception as exc:
        raise CoordsValidationError("set_coords", str(exc)) from exc


class CoordsTask(Task):
    """Portable coordinate-operation task for the Coords widget."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    operation: str = "rename_coords"
    rename_rows: tuple[tuple[str, str], ...] = ()
    set_dims_rows: tuple[tuple[str, str], ...] = ()
    set_coords_applied_dim: str = ""
    set_coords_applied_start: str = ""
    set_coords_applied_stop: str = ""
    set_coords_applied_step: str = ""
    drop_coords_selected: tuple[str, ...] = ()
    sort_coords_selected: tuple[str, ...] = ()
    sort_reverse: bool = False
    snap_coords_selected: tuple[str, ...] = ()
    snap_reverse: bool = False
    flip_dims_selected: tuple[str, ...] = ()
    flip_data: bool = True
    flip_coords: bool = True
    transpose_order: tuple[str, ...] = ()

    @staticmethod
    def _normalize_rows(rows: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        return [
            (str(left or "").strip(), str(right or "").strip()) for left, right in rows
        ]

    @staticmethod
    def _validate_mapping(
        rows: tuple[tuple[str, str], ...],
        *,
        label: str,
        valid_left: tuple[str, ...],
        valid_right: tuple[str, ...] | None,
        reject_duplicate_right: bool,
    ) -> dict[str, str]:
        def _fail(detail: str):
            raise CoordsValidationError("mapping", detail, label=label)

        mapping: dict[str, str] = {}
        valid_left_set = set(valid_left)
        valid_right_set = None if valid_right is None else set(valid_right)
        used_right: set[str] = set()
        for left, right in CoordsTask._normalize_rows(rows):
            if not left and not right:
                continue
            if not left or not right:
                _fail("both columns must be filled")
            if left not in valid_left_set:
                _fail(f"'{left}' is not available")
            if valid_right_set is not None and right not in valid_right_set:
                _fail(f"'{right}' is not available")
            if left in mapping:
                _fail(f"duplicate source '{left}'")
            if reject_duplicate_right and right in used_right:
                _fail(f"duplicate target '{right}'")
            mapping[left] = right
            used_right.add(right)
        if not mapping:
            _fail("at least one mapping is required")
        return mapping

    @staticmethod
    def _validate_selection(
        selected: tuple[str, ...], valid: tuple[str, ...], *, label: str
    ) -> list[str]:
        valid_set = set(valid)
        out = [str(item) for item in selected]
        invalid = [name for name in out if name not in valid_set]
        if invalid:
            raise CoordsValidationError("selection", ", ".join(invalid), label=label)
        return out

    def _validated_call(self, patch):
        """Validate parameters against ``patch`` and return the deferred call.

        Validation is eager so ``preflight`` can reuse it; the returned
        zero-argument callable performs the actual patch operation.
        """
        operation = str(self.operation or "rename_coords")
        available_dims = tuple(patch.dims)
        available_coords = tuple(patch.coords.coord_map)
        non_dim_coords = tuple(
            name for name in available_coords if name not in available_dims
        )

        if operation == "rename_coords":
            mapping = self._validate_mapping(
                self.rename_rows,
                label="rename",
                valid_left=available_coords,
                valid_right=None,
                reject_duplicate_right=True,
            )
            return lambda: patch.rename_coords(**mapping)
        if operation == "drop_coords":
            selected = self._validate_selection(
                self.drop_coords_selected, non_dim_coords, label="drop"
            )
            return lambda: patch if not selected else patch.drop_coords(*selected)
        if operation == "sort_coords":
            selected = self._validate_selection(
                self.sort_coords_selected, available_coords, label="sort"
            )
            return lambda: (
                patch
                if not selected
                else patch.sort_coords(*selected, reverse=bool(self.sort_reverse))
            )
        if operation == "snap_coords":
            selected = self._validate_selection(
                self.snap_coords_selected, available_coords, label="snap"
            )
            return lambda: (
                patch
                if not selected
                else patch.snap_coords(*selected, reverse=bool(self.snap_reverse))
            )
        if operation == "set_coords":
            if not self.set_coords_applied_dim:
                return lambda: patch
            coord = resolve_set_coord(
                patch,
                self.set_coords_applied_dim,
                self.set_coords_applied_start,
                self.set_coords_applied_stop,
                self.set_coords_applied_step,
            )
            return lambda: patch.update_coords(**{self.set_coords_applied_dim: coord})
        if operation == "set_dims":
            mapping = self._validate_mapping(
                self.set_dims_rows,
                label="set_dims",
                valid_left=available_dims,
                valid_right=available_coords,
                reject_duplicate_right=True,
            )
            return lambda: patch.set_dims(**mapping)
        if operation == "flip":
            selected = self._validate_selection(
                self.flip_dims_selected, available_coords, label="flip"
            )
            if not selected or (not self.flip_data and not self.flip_coords):
                return lambda: patch
            dim_names = tuple(name for name in selected if name in available_dims)
            if self.flip_data and len(dim_names) != len(selected):
                invalid = [name for name in selected if name not in available_dims]
                raise CoordsValidationError(
                    "selection",
                    "data flip requires dimension coordinates; "
                    f"non-dim coords selected: {', '.join(invalid)}",
                    label="flip",
                )

            def _flip():
                out = patch
                if self.flip_data and dim_names:
                    out = out.flip(*dim_names, flip_coords=False)
                if self.flip_coords:
                    out = out.update(coords=out.coords.flip(*tuple(selected)))
                return out

            return _flip
        if operation == "transpose":
            order = list(self.transpose_order)
            if not order:
                return lambda: patch
            if sorted(order) != sorted(available_dims):
                raise CoordsValidationError(
                    "selection",
                    "dimension order does not match the input patch",
                    label="transpose",
                )
            return lambda: patch.transpose(*order)
        raise ValueError(f"Unknown coords operation '{operation}'")

    def preflight(self, patch) -> None:
        """Validate persisted parameters against one patch without running.

        Raises ``CoordsValidationError`` on the first problem, letting the
        widget surface the same failures its banners used to compute itself.
        """
        self._validated_call(patch)

    def run(self, patch):
        """Apply the selected coordinate operation to one patch."""
        return self._validated_call(patch)()


class CoordsParams(BaseModel):
    """Parameters for the Coords widget (all affect the output patch)."""

    operation: Literal[
        "rename_coords",
        "drop_coords",
        "sort_coords",
        "snap_coords",
        "set_coords",
        "set_dims",
        "flip",
        "transpose",
    ] = "rename_coords"
    rename_rows: list = Field(default_factory=lambda: [["", ""]])
    set_dims_rows: list = Field(default_factory=lambda: [["", ""]])
    set_coords_dim: str = ""
    set_coords_start: str = ""
    set_coords_stop: str = ""
    set_coords_step: str = ""
    set_coords_applied_dim: str = ""
    set_coords_applied_start: str = ""
    set_coords_applied_stop: str = ""
    set_coords_applied_step: str = ""
    drop_coords_selected: list = Field(default_factory=list)
    sort_coords_selected: list = Field(default_factory=list)
    sort_reverse: bool = False
    snap_coords_selected: list = Field(default_factory=list)
    snap_reverse: bool = False
    flip_dims_selected: list = Field(default_factory=list)
    flip_data: bool = True
    flip_coords: bool = True
    transpose_order: list = Field(default_factory=list)


def _applied_set_coords_fields(params: CoordsParams) -> tuple[str, str, str, str]:
    """Return the effective applied set-coords fields, promoting drafts.

    On the canvas the draft fields are the source of truth: every patch
    arrival re-derives the ``*_applied_*`` mirror from them. Headlessly the
    same precedence applies — a non-empty draft wins, and the applied fields
    only carry a hand-authored update when no draft is present.
    """
    draft = (
        str(params.set_coords_dim or ""),
        str(params.set_coords_start or ""),
        str(params.set_coords_stop or ""),
        str(params.set_coords_step or ""),
    )
    if draft[0] and any(value.strip() for value in draft[1:]):
        return draft
    return (
        str(params.set_coords_applied_dim or ""),
        str(params.set_coords_applied_start or ""),
        str(params.set_coords_applied_stop or ""),
        str(params.set_coords_applied_step or ""),
    )


def coords_task_from_params(params: CoordsParams | None = None) -> CoordsTask:
    """Build the configured coordinate-operation task."""
    params = CoordsParams() if params is None else params
    applied_dim, applied_start, applied_stop, applied_step = _applied_set_coords_fields(
        params
    )
    return CoordsTask(
        operation=params.operation,
        rename_rows=tuple(
            (str(left), str(right))
            for left, right in normalize_mapping_rows(params.rename_rows)
        ),
        set_dims_rows=tuple(
            (str(left), str(right))
            for left, right in normalize_mapping_rows(params.set_dims_rows)
        ),
        set_coords_applied_dim=applied_dim,
        set_coords_applied_start=applied_start,
        set_coords_applied_stop=applied_stop,
        set_coords_applied_step=applied_step,
        drop_coords_selected=tuple(params.drop_coords_selected or ()),
        sort_coords_selected=tuple(params.sort_coords_selected or ()),
        sort_reverse=bool(params.sort_reverse),
        snap_coords_selected=tuple(params.snap_coords_selected or ()),
        snap_reverse=bool(params.snap_reverse),
        flip_dims_selected=tuple(params.flip_dims_selected or ()),
        flip_data=bool(params.flip_data),
        flip_coords=bool(params.flip_coords),
        transpose_order=tuple(params.transpose_order or ()),
    )


NODE_SPEC = NodeSpec(
    name="Coords",
    widget_qualified_name="derzug.widgets.coords.Coords",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=CoordsParams,
    task_factory=coords_task_from_params,
    category="Processing",
    description="Apply coordinate operations to a patch",
    keywords=(
        "coords",
        "coordinates",
        "flip",
        "rename",
        "transpose",
        "sort",
        "snap",
        "set_coords",
    ),
    icon="icons/Coords.svg",
    priority=24.5,
)
