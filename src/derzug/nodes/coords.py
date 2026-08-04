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
        valid_left: tuple[str, ...],
        valid_right: tuple[str, ...] | None,
        reject_duplicate_right: bool,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        valid_left_set = set(valid_left)
        valid_right_set = None if valid_right is None else set(valid_right)
        used_right: set[str] = set()
        for left, right in CoordsTask._normalize_rows(rows):
            if not left and not right:
                continue
            if not left or not right:
                raise ValueError("both columns must be filled")
            if left not in valid_left_set:
                raise ValueError(f"'{left}' is not available")
            if valid_right_set is not None and right not in valid_right_set:
                raise ValueError(f"'{right}' is not available")
            if left in mapping:
                raise ValueError(f"duplicate source '{left}'")
            if reject_duplicate_right and right in used_right:
                raise ValueError(f"duplicate target '{right}'")
            mapping[left] = right
            used_right.add(right)
        if not mapping:
            raise ValueError("at least one mapping is required")
        return mapping

    @staticmethod
    def _validate_selection(
        selected: tuple[str, ...], valid: tuple[str, ...]
    ) -> list[str]:
        valid_set = set(valid)
        out = [str(item) for item in selected]
        invalid = [name for name in out if name not in valid_set]
        if invalid:
            raise ValueError(", ".join(invalid))
        return out

    @staticmethod
    def _parse_set_coord_value(text: str, sample: object) -> object:
        return parse_coord_text_value(str(text), sample, None)

    def _resolved_coord(self, patch):
        dim = self.set_coords_applied_dim
        if dim not in patch.dims:
            raise ValueError(f"'{dim}' is not an available dimension")
        coord = patch.coords.get_coord(dim)
        parsed: dict[str, object] = {}
        for label, raw in (
            ("start", self.set_coords_applied_start),
            ("stop", self.set_coords_applied_stop),
            ("step", self.set_coords_applied_step),
        ):
            text = str(raw).strip()
            if not text:
                continue
            parsed[label] = self._parse_set_coord_value(text, getattr(coord, label))
        if not parsed:
            raise ValueError("at least one of start, stop, and step is required")
        if set(parsed) == {"start"}:
            parsed["step"] = coord.step
        elif set(parsed) == {"stop"}:
            parsed["step"] = coord.step
        elif set(parsed) == {"step"}:
            parsed["start"] = coord.start
        kwargs = {
            "shape": patch.shape[patch.dims.index(dim)],
            "units": coord.units,
            "dtype": coord.dtype,
            **parsed,
        }
        return get_coord(**kwargs)

    def run(self, patch):
        """Apply the selected coordinate operation to one patch."""
        operation = str(self.operation or "rename_coords")
        available_dims = tuple(patch.dims)
        available_coords = tuple(patch.coords.coord_map)
        non_dim_coords = tuple(
            name for name in available_coords if name not in available_dims
        )

        if operation == "rename_coords":
            mapping = self._validate_mapping(
                self.rename_rows,
                valid_left=available_coords,
                valid_right=None,
                reject_duplicate_right=True,
            )
            return patch.rename_coords(**mapping)
        if operation == "drop_coords":
            selected = self._validate_selection(
                self.drop_coords_selected,
                non_dim_coords,
            )
            return patch if not selected else patch.drop_coords(*selected)
        if operation == "sort_coords":
            selected = self._validate_selection(
                self.sort_coords_selected,
                available_coords,
            )
            return (
                patch
                if not selected
                else patch.sort_coords(*selected, reverse=bool(self.sort_reverse))
            )
        if operation == "snap_coords":
            selected = self._validate_selection(
                self.snap_coords_selected,
                available_coords,
            )
            return (
                patch
                if not selected
                else patch.snap_coords(*selected, reverse=bool(self.snap_reverse))
            )
        if operation == "set_coords":
            if not self.set_coords_applied_dim:
                return patch
            return patch.update_coords(
                **{self.set_coords_applied_dim: self._resolved_coord(patch)}
            )
        if operation == "set_dims":
            mapping = self._validate_mapping(
                self.set_dims_rows,
                valid_left=available_dims,
                valid_right=available_coords,
                reject_duplicate_right=True,
            )
            return patch.set_dims(**mapping)
        if operation == "flip":
            selected = self._validate_selection(
                self.flip_dims_selected,
                available_coords,
            )
            if not selected or (not self.flip_data and not self.flip_coords):
                return patch
            dim_names = tuple(name for name in selected if name in available_dims)
            if self.flip_data and len(dim_names) != len(selected):
                invalid = [name for name in selected if name not in available_dims]
                raise ValueError(
                    "data flip requires dimension coordinates; "
                    f"non-dim coords selected: {', '.join(invalid)}"
                )
            out = patch
            if self.flip_data and dim_names:
                out = out.flip(*dim_names, flip_coords=False)
            if self.flip_coords:
                out = out.update(coords=out.coords.flip(*tuple(selected)))
            return out
        if operation == "transpose":
            order = list(self.transpose_order)
            dims = list(available_dims)
            if not order:
                return patch
            if sorted(order) != sorted(dims):
                raise ValueError("dimension order does not match the input patch")
            return patch.transpose(*order)
        raise ValueError(f"Unknown coords operation '{operation}'")


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


def coords_task_from_params(params: CoordsParams | None = None) -> CoordsTask:
    """Build the configured coordinate-operation task."""
    params = CoordsParams() if params is None else params
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
        set_coords_applied_dim=str(params.set_coords_applied_dim or ""),
        set_coords_applied_start=str(params.set_coords_applied_start or ""),
        set_coords_applied_stop=str(params.set_coords_applied_stop or ""),
        set_coords_applied_step=str(params.set_coords_applied_step or ""),
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
