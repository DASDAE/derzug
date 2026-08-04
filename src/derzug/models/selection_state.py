"""Qt-free selection state shared by patch- and spool-based nodes.

The dimension ranges, spool row filters, and the coordinate/sample conversions
that back them are pure Python and numpy. They live here rather than beside the
Qt panel that edits them so a selection task can apply saved state with no
display attached — ``derzug.widgets.selection`` re-exports every name for the
widgets, and holds the panel itself.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from derzug.models.selection import SelectParams
from derzug.utils.display import format_display
from derzug.utils.misc import ordered_pair
from derzug.utils.parsing import parse_coord_text_value
from derzug.utils.spool import normalize_dims_value, series_has_visible_values


def _values_equal(left: Any, right: Any) -> bool:
    """Return True when two scalar-ish selection values are equivalent."""
    try:
        result = left == right
    except Exception:
        return False
    if isinstance(result, np.ndarray):
        return bool(result.all())
    return bool(result)


def _coerce_python_scalar(value: Any) -> Any:
    """Convert NumPy numeric scalars into plain Python scalars for DASCore."""
    if isinstance(value, np.integer | np.floating | np.bool_):
        return value.item()
    return value


def _bound_from_coord_array(values: np.ndarray) -> tuple[Any, Any]:
    """Return monotonic bounds from a coordinate array."""
    arr = np.asarray(values)
    if arr.size == 0:
        return None, None
    if arr.size == 1:
        return arr[0], arr[0]
    return ordered_pair(arr[0], arr[-1])


def _coord_delta(start: Any, value: Any) -> Any:
    """Return an offset value measured from start."""
    try:
        return value - start
    except Exception:
        return value


def _coord_add_offset(start: Any, offset: Any) -> Any:
    """Return an absolute coordinate value from start plus an offset."""
    try:
        return start + offset
    except Exception:
        return offset


def _coord_axis_to_numeric(values: np.ndarray) -> np.ndarray:
    """Convert coordinate values into a numeric axis for interpolation."""
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[ns]").astype(np.float64)
    if np.issubdtype(arr.dtype, np.timedelta64):
        return arr.astype("timedelta64[ns]").astype(np.float64)
    if np.issubdtype(arr.dtype, np.number):
        return arr.astype(np.float64)
    return np.arange(arr.size, dtype=np.float64)


def _interp_with_extrapolation(value: float, x: np.ndarray, y: np.ndarray) -> float:
    """Interpolate y(x) and extrapolate linearly outside x bounds."""
    if x.size == 0 or y.size == 0:
        return float(value)
    if x.size == 1 or y.size == 1:
        return float(y[0])
    if x[0] > x[-1]:
        x = x[::-1]
        y = y[::-1]
    if value < x[0]:
        dx = float(x[1] - x[0])
        if dx == 0:
            return float(y[0])
        slope = float(y[1] - y[0]) / dx
        return float(y[0]) + (value - float(x[0])) * slope
    if value > x[-1]:
        dx = float(x[-1] - x[-2])
        if dx == 0:
            return float(y[-1])
        slope = float(y[-1] - y[-2]) / dx
        return float(y[-1]) + (value - float(x[-1])) * slope
    return float(np.interp(value, x, y))


def _coord_to_sample_index(values: np.ndarray, coord_value: Any) -> float | int:
    """Convert an absolute coordinate into the nearest valid sample index."""
    arr = np.asarray(values)
    if arr.size == 0:
        return 0
    if not (
        np.issubdtype(arr.dtype, np.datetime64)
        or np.issubdtype(arr.dtype, np.timedelta64)
        or np.issubdtype(arr.dtype, np.number)
    ):
        matches = np.flatnonzero(arr == coord_value)
        return int(matches[0]) if matches.size else 0
    numeric_axis = _coord_axis_to_numeric(arr)
    sample_axis = np.arange(arr.size, dtype=np.float64)
    coord_numeric = _coord_axis_to_numeric(np.asarray([coord_value]))[0]
    index = _interp_with_extrapolation(float(coord_numeric), numeric_axis, sample_axis)
    return int(np.clip(round(index), 0, arr.size - 1))


def _sample_index_to_coord(values: np.ndarray, sample_index: Any) -> Any:
    """Convert a sample-space index into an absolute coordinate value."""
    arr = np.asarray(values)
    if arr.size == 0:
        return sample_index
    if arr.size == 1:
        return arr[0]
    sample_axis = np.arange(arr.size, dtype=np.float64)
    numeric_axis = _coord_axis_to_numeric(arr)
    coord_numeric = _interp_with_extrapolation(
        float(sample_index), sample_axis, numeric_axis
    )
    if np.issubdtype(arr.dtype, np.datetime64):
        return np.datetime64(round(coord_numeric), "ns")
    if np.issubdtype(arr.dtype, np.timedelta64):
        return np.timedelta64(round(coord_numeric), "ns")
    if np.issubdtype(arr.dtype, np.integer):
        return round(coord_numeric)
    if np.issubdtype(arr.dtype, np.floating):
        return float(coord_numeric)
    idx = int(np.clip(round(float(sample_index)), 0, arr.size - 1))
    return arr[idx]


def _text_matches_display_value(text: str, sample: Any, value: Any) -> bool:
    """Return True when line-edit text already represents the target value."""
    stripped = text.strip()
    if not stripped:
        return False
    try:
        parsed = _parse_coord_value(stripped, sample, value)
    except Exception:
        return False
    return _values_equal(parsed, value)


def _parse_spool_filter_value(text: str) -> Any | None:
    """Parse the raw spool filter text into a scalar value."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return ast.literal_eval(stripped)
    except Exception:
        return stripped


def _parse_coord_value(text: str, sample: Any, fallback: Any) -> Any:
    """Parse UI text into a coordinate-compatible value."""
    return parse_coord_text_value(text, sample, fallback)


def _absolute_value_matches_coord_type(value: Any, coord_values: np.ndarray) -> bool:
    """Return True when an absolute range value is compatible with coord dtype."""
    coord = np.asarray(coord_values)
    coord_dtype = coord.dtype
    value_dtype = np.asarray(value).dtype
    if np.issubdtype(coord_dtype, np.datetime64):
        return np.issubdtype(value_dtype, np.datetime64)
    if np.issubdtype(coord_dtype, np.timedelta64):
        return np.issubdtype(value_dtype, np.timedelta64)
    if np.issubdtype(coord_dtype, np.number):
        return np.issubdtype(value_dtype, np.number)
    return True


def _range_matches_extent(
    current: tuple[Any, Any] | None,
    extent: tuple[Any, Any] | None,
) -> bool:
    """Return True when a range is effectively the full extent."""
    if current is None or extent is None:
        return False
    return all(
        _values_equal(current_value, extent_value)
        for current_value, extent_value in zip(current, extent, strict=False)
    )


def _ranges_overlap(
    first: tuple[Any, Any] | None,
    second: tuple[Any, Any] | None,
) -> bool:
    """Return True when two ordered scalar ranges overlap."""
    if first is None or second is None:
        return False
    first_low, first_high = ordered_pair(*first)
    second_low, second_high = ordered_pair(*second)
    try:
        return bool(first_low <= second_high and second_low <= first_high)
    except Exception:
        return False


class SelectionMode(Enum):
    """Selection mode for the shared state/panel."""

    NONE = "none"
    PATCH = "patch"
    SPOOL = "spool"


class PatchSelectionBasis(Enum):
    """Selection basis for patch ranges."""

    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    SAMPLES = "samples"


@dataclass
class PatchSelectionState:
    """Current patch range selection."""

    basis: PatchSelectionBasis = PatchSelectionBasis.ABSOLUTE
    extents: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    ranges: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)


@dataclass
class SpoolFilterRowState:
    """One spool metadata filter row."""

    key: str = ""
    raw_value: str = ""


@dataclass
class SpoolFilterState:
    """Current spool metadata filter."""

    options: tuple[str, ...] = ()
    filters: list[SpoolFilterRowState] = field(
        default_factory=lambda: [SpoolFilterRowState()]
    )

    @property
    def key(self) -> str:
        """Compatibility alias for the primary spool filter row key."""
        return self.filters[0].key if self.filters else ""

    @property
    def raw_value(self) -> str:
        """Compatibility alias for the primary spool filter row value."""
        return self.filters[0].raw_value if self.filters else ""


@dataclass
class SelectionState:
    """Typed selection state independent of Qt widgets."""

    mode: SelectionMode = SelectionMode.NONE
    patch: PatchSelectionState = field(default_factory=PatchSelectionState)
    spool: SpoolFilterState = field(default_factory=SpoolFilterState)
    patch_source: Any | None = field(default=None, repr=False, compare=False)

    def patch_settings_payload(
        self, *, include_inactive: bool = False
    ) -> dict[str, Any] | None:
        """Return a workflow-safe payload for the current patch selection state."""
        if self.mode is not SelectionMode.PATCH and not include_inactive:
            return None
        if not self.patch.ranges:
            return None
        rows: list[dict[str, Any]] = []
        for dim, current in self.patch.ranges.items():
            rows.append(
                {
                    "dim": dim,
                    "enabled": bool(self.patch.enabled.get(dim, True)),
                    "low": self._serialize_value(current[0]),
                    "high": self._serialize_value(current[1]),
                }
            )
        if not rows:
            return None
        return {"basis": self.patch.basis.value, "rows": rows}

    def prime_patch_state_from_settings(self, payload: dict[str, Any] | None) -> bool:
        """Seed patch selection state from a serialized workflow payload."""
        if not isinstance(payload, dict):
            return False
        basis_name = str(payload.get("basis", "")).strip()
        rows = payload.get("rows")
        if not basis_name or not isinstance(rows, list):
            return False
        try:
            basis = PatchSelectionBasis(basis_name)
        except Exception:
            return False
        ranges: dict[str, tuple[Any, Any]] = {}
        enabled: dict[str, bool] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            dim = row.get("dim")
            if not isinstance(dim, str) or not dim:
                continue
            ranges[dim] = (
                self._deserialize_value(row.get("low")),
                self._deserialize_value(row.get("high")),
            )
            enabled[dim] = bool(row.get("enabled", True))
        if not ranges:
            return False
        self.mode = SelectionMode.PATCH
        self.patch = PatchSelectionState(
            basis=basis,
            ranges=ranges,
            enabled=enabled,
        )
        self.spool = SpoolFilterState()
        return True

    def set_patch_source(self, patch) -> None:
        """Seed patch ranges from a patch while preserving basis and valid ranges."""
        self.spool = SpoolFilterState()
        if patch is None:
            self.patch_source = None
            self.mode = SelectionMode.NONE
            return
        self.patch_source = patch

        previous_extents = dict(self.patch.extents)
        previous_ranges = dict(self.patch.ranges)
        previous_enabled = dict(self.patch.enabled)
        selection_active = any(
            previous_enabled.get(dim, True) is False
            or not _range_matches_extent(
                previous_ranges.get(dim), previous_extents.get(dim)
            )
            for dim in previous_ranges
        )
        previous_basis = (
            self.patch.basis if selection_active else PatchSelectionBasis.ABSOLUTE
        )
        extents = self._patch_extents_in_basis(patch, previous_basis)
        enabled = {dim: previous_enabled.get(dim, True) for dim in patch.dims}
        if not selection_active:
            ranges = dict(extents)
        else:
            ranges = {
                dim: self._reseed_patch_range(
                    patch,
                    dim,
                    previous_ranges.get(dim),
                    previous_extents.get(dim),
                    extents,
                )
                for dim in patch.dims
            }
        self.mode = SelectionMode.PATCH
        self.patch = PatchSelectionState(
            basis=previous_basis,
            extents=extents,
            ranges=ranges,
            enabled=enabled,
        )

    def set_spool_source(self, spool) -> None:
        """Seed spool filter choices from a spool's contents table."""
        self.patch = PatchSelectionState()
        self.patch_source = None
        if spool is None:
            self.mode = SelectionMode.NONE
            self.spool = SpoolFilterState()
            return

        try:
            df = spool.get_contents()
        except Exception:
            options: tuple[str, ...] = ()
        else:
            visible_cols = [c for c in df.columns if series_has_visible_values(df[c])]
            dims: list[str] = []
            if "dims" in df.columns:
                seen: set[str] = set(visible_cols)
                for value in df["dims"]:
                    for dim in normalize_dims_value(value):
                        if dim not in seen:
                            seen.add(dim)
                            dims.append(dim)
            options = tuple(sorted(visible_cols + dims, key=str.casefold))
        existing_filters = [
            SpoolFilterRowState(
                key=flt.key if flt.key in options else "",
                raw_value=flt.raw_value,
            )
            for flt in self.spool.filters
        ]
        self.mode = SelectionMode.SPOOL
        self.spool = SpoolFilterState(
            options=options,
            filters=existing_filters or [SpoolFilterRowState()],
        )

    def patch_kwargs(self) -> dict[str, tuple[Any, Any]]:
        """Return patch.select kwargs implied by the current narrowed ranges."""
        kwargs: dict[str, tuple[Any, Any]] = {}
        for dim, current in self.patch.ranges.items():
            if not self.patch.enabled.get(dim, True):
                continue
            extent = self.patch.extents.get(dim)
            if extent is None:
                continue
            low, high = ordered_pair(*current)
            full_low, full_high = ordered_pair(*extent)
            if _values_equal(low, full_low) and _values_equal(high, full_high):
                continue
            kwargs[dim] = (_coerce_python_scalar(low), _coerce_python_scalar(high))
        return kwargs

    def patch_enabled_dims(self) -> tuple[str, ...]:
        """Return enabled patch dimensions in display order."""
        return tuple(
            dim for dim in self.patch.ranges if self.patch.enabled.get(dim, True)
        )

    def set_patch_dim_enabled(self, dim: str, enabled: bool) -> None:
        """Enable or disable one patch dimension without losing its range."""
        if dim not in self.patch.ranges:
            return
        self.patch.enabled[dim] = bool(enabled)

    def patch_dim_enabled(self, dim: str) -> bool:
        """Return True when a patch dimension is enabled."""
        return self.patch.enabled.get(dim, True)

    def reset_patch_dims(self, dims: tuple[str, ...]) -> None:
        """Reset selected patch dims back to their full extents and re-enable them."""
        for dim in dims:
            if dim in self.patch.extents:
                self.patch.ranges[dim] = self.patch.extents[dim]
                self.patch.enabled[dim] = True

    def current_patch_range(self, dim: str) -> tuple[Any, Any] | None:
        """Return the current range for a patch dimension."""
        return self.patch.ranges.get(dim)

    def patch_extent(self, dim: str) -> tuple[Any, Any] | None:
        """Return the full extent for a patch dimension."""
        return self.patch.extents.get(dim)

    def current_patch_absolute_range(self, dim: str) -> tuple[Any, Any] | None:
        """Return the current patch range converted to absolute coordinates."""
        if self.patch_source is None or dim not in self.patch.ranges:
            return None
        low, high = self.patch.ranges[dim]
        return ordered_pair(
            self._basis_to_absolute_value(self.patch_source, dim, low),
            self._basis_to_absolute_value(self.patch_source, dim, high),
        )

    def patch_absolute_extent(self, dim: str) -> tuple[Any, Any] | None:
        """Return the full patch extent for a dimension in absolute coordinates."""
        if self.patch_source is None:
            return None
        return _bound_from_coord_array(np.asarray(self.patch_source.get_array(dim)))

    def set_patch_basis(self, basis: PatchSelectionBasis) -> None:
        """Switch patch basis while preserving the logical selected window."""
        if basis is self.patch.basis:
            return
        patch = self.patch_source
        previous_basis = self.patch.basis
        previous_enabled = dict(self.patch.enabled)
        self.patch.basis = basis
        if patch is None:
            return

        previous_ranges = dict(self.patch.ranges)
        absolute_ranges = {
            dim: ordered_pair(
                self._basis_to_absolute_value(patch, dim, current[0], previous_basis),
                self._basis_to_absolute_value(patch, dim, current[1], previous_basis),
            )
            for dim, current in previous_ranges.items()
        }
        extents = self._patch_extents_in_basis(patch, basis)
        ranges = {
            dim: ordered_pair(
                self._absolute_to_basis_value(patch, dim, current[0], basis),
                self._absolute_to_basis_value(patch, dim, current[1], basis),
            )
            for dim, current in absolute_ranges.items()
        }
        self.patch = PatchSelectionState(
            basis=basis,
            extents=extents,
            ranges=ranges,
            enabled=previous_enabled,
        )

    def set_spool_filter(self, key: str, raw_value: str) -> None:
        """Update the currently selected spool filter."""
        self.set_spool_filters([(key, raw_value)])

    def set_spool_filters(self, filters: list[tuple[str, str]]) -> None:
        """Replace the current spool filter rows."""
        self.spool.filters = [
            SpoolFilterRowState(key=key, raw_value=raw_value)
            for key, raw_value in filters
        ] or [SpoolFilterRowState()]

    def add_spool_filter(self) -> None:
        """Append one empty spool filter row."""
        self.spool.filters.append(SpoolFilterRowState())

    def remove_spool_filter(self, index: int) -> None:
        """Remove one spool filter row while keeping at least one visible row."""
        if 0 <= index < len(self.spool.filters):
            del self.spool.filters[index]
        if not self.spool.filters:
            self.spool.filters.append(SpoolFilterRowState())

    def reset(self) -> None:
        """Reset the active selection back to its full extent / no filter state."""
        if self.mode is SelectionMode.PATCH:
            self.reset_patch_dims(tuple(self.patch.extents))
            return
        if self.mode is SelectionMode.SPOOL:
            self.spool.filters = [SpoolFilterRowState()]

    def _patch_extents_in_basis(
        self,
        patch,
        basis: PatchSelectionBasis,
    ) -> dict[str, tuple[Any, Any]]:
        """Return full patch extents represented in the requested basis."""
        extents: dict[str, tuple[Any, Any]] = {}
        for dim in patch.dims:
            values = np.asarray(patch.get_array(dim))
            absolute = _bound_from_coord_array(values)
            if basis is PatchSelectionBasis.ABSOLUTE:
                extents[dim] = absolute
                continue
            if basis is PatchSelectionBasis.RELATIVE:
                extents[dim] = ordered_pair(
                    self._absolute_to_basis_value(patch, dim, absolute[0], basis),
                    self._absolute_to_basis_value(patch, dim, absolute[1], basis),
                )
                continue
            extents[dim] = (0, max(values.size - 1, 0))
        return extents

    def patch_select_flags(self) -> dict[str, bool]:
        """Return the basis flags to pass into patch.select."""
        return {
            "relative": self.patch.basis is PatchSelectionBasis.RELATIVE,
            "samples": self.patch.basis is PatchSelectionBasis.SAMPLES,
        }

    def to_select_params(self) -> SelectParams:
        """Return public patch.select parameters for the current patch selection."""
        flags = self.patch_select_flags()
        return SelectParams(
            kwargs=self.patch_kwargs(),
            relative=flags["relative"],
            samples=flags["samples"],
        )

    def apply_select_params(self, params: SelectParams, patch) -> None:
        """Seed patch-mode selection state from public patch.select parameters."""
        basis = PatchSelectionBasis.ABSOLUTE
        if params.relative:
            basis = PatchSelectionBasis.RELATIVE
        elif params.samples:
            basis = PatchSelectionBasis.SAMPLES
        self.set_patch_source(patch)
        self.set_patch_basis(basis)
        for dim, value_range in params.kwargs.items():
            if dim not in self.patch.ranges:
                continue
            try:
                low, high = value_range
            except (TypeError, ValueError):
                continue
            self.update_patch_range(dim, low, high)
            self.patch.enabled[dim] = True

    def apply_to_patch(self, patch):
        """Apply the current patch-mode ranges to a patch."""
        kwargs = self.patch_kwargs()
        if not kwargs:
            return patch
        return patch.select(copy=False, **self.patch_select_flags(), **kwargs)

    def apply_to_spool(self, spool):
        """Apply the current spool filter to a spool."""
        selected = spool
        for filter_row in self.spool.filters:
            value = _parse_spool_filter_value(filter_row.raw_value)
            if not filter_row.key or value is None:
                continue
            selected = selected.select(**{filter_row.key: value})
        return selected

    def update_patch_range(self, dim: str, low: Any, high: Any) -> None:
        """Update one patch dimension range."""
        if dim not in self.patch.ranges:
            return
        self.patch.ranges[dim] = ordered_pair(low, high)

    def update_patch_range_absolute(self, dim: str, low: Any, high: Any) -> None:
        """Update one patch dimension range from absolute coordinate values."""
        if self.patch_source is None or dim not in self.patch.ranges:
            return
        low_value, high_value = ordered_pair(low, high)
        self.patch.ranges[dim] = ordered_pair(
            self._absolute_to_basis_value(self.patch_source, dim, low_value),
            self._absolute_to_basis_value(self.patch_source, dim, high_value),
        )

    def update_patch_range_absolute_from_roi(
        self, dim: str, low: Any, high: Any
    ) -> None:
        """Update one patch dimension range from ROI-driven absolute coordinates."""
        if self.patch_source is None or dim not in self.patch.ranges:
            return
        low_value, high_value = ordered_pair(low, high)
        converted_low = self._absolute_to_basis_value(self.patch_source, dim, low_value)
        converted_high = self._absolute_to_basis_value(
            self.patch_source, dim, high_value
        )
        self.patch.ranges[dim] = ordered_pair(
            self._clamp_roi_basis_value(converted_low),
            self._clamp_roi_basis_value(converted_high),
        )

    def _reseed_patch_range(
        self,
        patch,
        dim: str,
        previous_range: tuple[Any, Any] | None,
        previous_extent: tuple[Any, Any] | None,
        extents: dict[str, tuple[Any, Any]],
    ) -> tuple[Any, Any]:
        """Return the seeded range for a replacement patch source."""
        extent = extents[dim]
        if previous_range is None:
            return extent
        if self.patch.basis is not PatchSelectionBasis.ABSOLUTE:
            return previous_range
        if previous_extent is not None and all(
            _values_equal(current, previous)
            for current, previous in zip(previous_range, previous_extent, strict=False)
        ):
            return extent

        coord = np.asarray(patch.get_array(dim))
        low, high = previous_range
        if not _absolute_value_matches_coord_type(low, coord):
            return extent
        if not _absolute_value_matches_coord_type(high, coord):
            return extent
        if not _ranges_overlap(previous_range, extent):
            return extent
        return previous_range

    def _basis_to_absolute_value(
        self,
        patch,
        dim: str,
        value: Any,
        basis: PatchSelectionBasis | None = None,
    ) -> Any:
        """Convert one basis-space value into an absolute coordinate value."""
        basis = basis or self.patch.basis
        coord = np.asarray(patch.get_array(dim))
        if basis is PatchSelectionBasis.ABSOLUTE:
            return value
        if basis is PatchSelectionBasis.RELATIVE:
            # For datetime64 coords, relative values are stored as float seconds;
            # reconstruct absolute datetime64 from that offset.
            if np.issubdtype(coord.dtype, np.datetime64) and isinstance(
                value, int | float | np.integer | np.floating
            ):
                ns = int(float(value) * 1e9)
                return coord[0] + np.timedelta64(ns, "ns")
            if np.issubdtype(coord.dtype, np.timedelta64) and isinstance(
                value, int | float | np.integer | np.floating
            ):
                ns = int(float(value) * 1e9)
                return coord[0] + np.timedelta64(ns, "ns")
            return _coord_add_offset(coord[0], value)
        return _sample_index_to_coord(coord, value)

    def _absolute_to_basis_value(
        self,
        patch,
        dim: str,
        value: Any,
        basis: PatchSelectionBasis | None = None,
    ) -> Any:
        """Convert one absolute coordinate value into the requested basis."""
        basis = basis or self.patch.basis
        coord = np.asarray(patch.get_array(dim))
        if basis is PatchSelectionBasis.ABSOLUTE:
            return value
        if basis is PatchSelectionBasis.RELATIVE:
            delta = _coord_delta(coord[0], value)
            # DASCore's patch.select(relative=True) expects float seconds for
            # datetime dimensions, not timedelta64; convert here.
            arr = np.asarray(delta)
            if np.issubdtype(arr.dtype, np.timedelta64):
                return float(arr.astype("timedelta64[ns]").astype(np.int64)) / 1e9
            return delta
        return _coord_to_sample_index(coord, value)

    def _clamp_roi_basis_value(self, value: Any) -> Any:
        """Clamp ROI-driven relative/sample basis values to be non-negative."""
        if self.patch.basis is PatchSelectionBasis.ABSOLUTE:
            return value
        try:
            return max(value, 0)
        except Exception:
            return value

    @staticmethod
    def _serialize_value(value: Any) -> dict[str, Any]:
        """Convert one selection value into a workflow-safe payload."""
        arr = np.asarray(value)
        dtype = arr.dtype
        if np.issubdtype(dtype, np.datetime64):
            ns_value = arr.astype("datetime64[ns]").astype(np.int64).item()
            return {"kind": "datetime64", "value": int(ns_value)}
        if np.issubdtype(dtype, np.timedelta64):
            ns_value = arr.astype("timedelta64[ns]").astype(np.int64).item()
            return {"kind": "timedelta64", "value": int(ns_value)}
        if np.issubdtype(dtype, np.integer):
            return {"kind": "int", "value": int(arr.item())}
        if np.issubdtype(dtype, np.floating):
            return {"kind": "float", "value": float(arr.item())}
        if np.issubdtype(dtype, np.bool_):
            return {"kind": "bool", "value": bool(arr.item())}
        return {"kind": "text", "value": str(value)}

    @staticmethod
    def _deserialize_value(payload: Any) -> Any:
        """Rebuild one selection value from serialized workflow-safe data."""
        if not isinstance(payload, dict):
            return payload
        kind = payload.get("kind")
        value = payload.get("value")
        if kind == "datetime64":
            return np.datetime64(int(value), "ns")
        if kind == "timedelta64":
            return np.timedelta64(int(value), "ns")
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "bool":
            return bool(value)
        return value
