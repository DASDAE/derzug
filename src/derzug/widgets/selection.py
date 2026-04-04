"""Shared selection state and control panel for patch- and spool-based widgets."""

from __future__ import annotations

import ast
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from AnyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui

from derzug.utils.display import format_display
from derzug.utils.parsing import parse_coord_text_value
from derzug.utils.spool import normalize_dims_value


def _values_equal(left: Any, right: Any) -> bool:
    """Return True when two scalar-ish selection values are equivalent."""
    try:
        result = left == right
    except Exception:
        return False
    if isinstance(result, np.ndarray):
        return bool(result.all())
    return bool(result)


def _selection_debug(message: str) -> None:
    """Emit selection-state diagnostics for CI debugging."""
    print(f"SELECTION_DEBUG {message}", file=sys.stderr, flush=True)  # noqa: T201


def _ordered_pair(first: Any, second: Any) -> tuple[Any, Any]:
    """Return a comparable pair in ascending order when possible."""
    try:
        return (first, second) if first <= second else (second, first)
    except Exception:
        return first, second


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
    return _ordered_pair(arr[0], arr[-1])


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


def _format_coord_value(value: Any) -> str:
    """Format a selection value for a line edit."""
    return format_display(value)


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
    first_low, first_high = _ordered_pair(*first)
    second_low, second_high = _ordered_pair(*second)
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
        _selection_debug(f"prime_patch_state_from_settings start payload={payload!r}")
        if not isinstance(payload, dict):
            _selection_debug("prime_patch_state_from_settings bail_not_dict")
            return False
        basis_name = str(payload.get("basis", "")).strip()
        rows = payload.get("rows")
        if not basis_name or not isinstance(rows, list):
            _selection_debug(
                "prime_patch_state_from_settings bail_missing_basis_or_rows"
            )
            return False
        try:
            basis = PatchSelectionBasis(basis_name)
        except Exception:
            _selection_debug(
                "prime_patch_state_from_settings bail_invalid_basis "
                f"basis_name={basis_name!r}"
            )
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
            _selection_debug("prime_patch_state_from_settings bail_no_ranges")
            return False
        self.mode = SelectionMode.PATCH
        self.patch = PatchSelectionState(
            basis=basis,
            ranges=ranges,
            enabled=enabled,
        )
        self.spool = SpoolFilterState()
        _selection_debug(
            "prime_patch_state_from_settings applied "
            f"basis={self.patch.basis.value!r} ranges={self.patch.ranges!r}"
        )
        return True

    def set_patch_source(self, patch) -> None:
        """Seed patch ranges from a patch while preserving basis and valid ranges."""
        _selection_debug(
            "set_patch_source start "
            f"patch_present={patch is not None} "
            f"mode_before={self.mode.value!r} "
            f"basis_before={self.patch.basis.value!r} "
            f"ranges_before={self.patch.ranges!r} "
            f"extents_before={self.patch.extents!r}"
        )
        self.spool = SpoolFilterState()
        if patch is None:
            self.patch_source = None
            self.mode = SelectionMode.NONE
            _selection_debug("set_patch_source cleared")
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
        _selection_debug(
            "set_patch_source end "
            f"basis_after={self.patch.basis.value!r} "
            f"ranges_after={self.patch.ranges!r} "
            f"extents_after={self.patch.extents!r} "
            f"selection_active={selection_active}"
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
            visible_cols = [
                c for c in df.columns if df[c].astype(str).str.strip().ne("").any()
            ]
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
            low, high = _ordered_pair(*current)
            full_low, full_high = _ordered_pair(*extent)
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
        return _ordered_pair(
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
        _selection_debug(
            "set_patch_basis start "
            f"basis_before={self.patch.basis.value!r} "
            f"basis_target={basis.value!r} "
            f"patch_present={self.patch_source is not None}"
        )
        if basis is self.patch.basis:
            _selection_debug("set_patch_basis noop_same_basis")
            return
        patch = self.patch_source
        previous_basis = self.patch.basis
        previous_enabled = dict(self.patch.enabled)
        self.patch.basis = basis
        if patch is None:
            return

        previous_ranges = dict(self.patch.ranges)
        absolute_ranges = {
            dim: _ordered_pair(
                self._basis_to_absolute_value(patch, dim, current[0], previous_basis),
                self._basis_to_absolute_value(patch, dim, current[1], previous_basis),
            )
            for dim, current in previous_ranges.items()
        }
        extents = self._patch_extents_in_basis(patch, basis)
        ranges = {
            dim: _ordered_pair(
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
        _selection_debug(
            "set_patch_basis end "
            f"basis_after={self.patch.basis.value!r} "
            f"ranges_after={self.patch.ranges!r}"
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
                extents[dim] = _ordered_pair(
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
        self.patch.ranges[dim] = _ordered_pair(low, high)

    def update_patch_range_absolute(self, dim: str, low: Any, high: Any) -> None:
        """Update one patch dimension range from absolute coordinate values."""
        if self.patch_source is None or dim not in self.patch.ranges:
            return
        low_value, high_value = _ordered_pair(low, high)
        self.patch.ranges[dim] = _ordered_pair(
            self._absolute_to_basis_value(self.patch_source, dim, low_value),
            self._absolute_to_basis_value(self.patch_source, dim, high_value),
        )

    def update_patch_range_absolute_from_roi(
        self, dim: str, low: Any, high: Any
    ) -> None:
        """Update one patch dimension range from ROI-driven absolute coordinates."""
        if self.patch_source is None or dim not in self.patch.ranges:
            return
        low_value, high_value = _ordered_pair(low, high)
        converted_low = self._absolute_to_basis_value(self.patch_source, dim, low_value)
        converted_high = self._absolute_to_basis_value(
            self.patch_source, dim, high_value
        )
        self.patch.ranges[dim] = _ordered_pair(
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


class SelectionPanel(QWidget):
    """Reusable left-side selection panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sync_depth = 0
        self.patch_checkboxes: dict[str, QCheckBox] = {}
        self.patch_edits: dict[str, tuple[QLineEdit, QLineEdit]] = {}
        self._active_dims: tuple[str, ...] = ()
        self.spool_rows: list[tuple[QComboBox, QLineEdit, QPushButton]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.mode_label = QLabel("", self)
        self.hint_label = QLabel("", self)
        self.hint_label.setWordWrap(True)
        self.status_label = QLabel("", self)
        self.reset_button = QPushButton("Reset", self)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.reset_button)

        self.patch_basis_label = QLabel("Basis", self)
        self.patch_basis_combo = QComboBox(self)
        for basis in PatchSelectionBasis:
            self.patch_basis_combo.addItem(basis.value.title(), basis)
        layout.addWidget(self.patch_basis_label)
        layout.addWidget(self.patch_basis_combo)

        self.patch_widget = QWidget(self)
        self.patch_layout = QGridLayout(self.patch_widget)
        self.patch_layout.setContentsMargins(0, 0, 0, 0)
        self.patch_layout.setHorizontalSpacing(6)
        self.patch_layout.setVerticalSpacing(4)
        layout.addWidget(self.patch_widget)

        self.spool_widget = QWidget(self)
        self.spool_layout = QGridLayout(self.spool_widget)
        self.spool_layout.setContentsMargins(0, 0, 0, 0)
        self.spool_layout.setHorizontalSpacing(6)
        self.spool_layout.setVerticalSpacing(4)
        self.spool_layout.addWidget(QLabel("Field", self.spool_widget), 0, 0)
        self.spool_layout.addWidget(QLabel("Value", self.spool_widget), 0, 1)
        self.spool_layout.addWidget(QLabel("", self.spool_widget), 0, 2)
        self.spool_rows_container = QWidget(self.spool_widget)
        self.spool_rows_layout = QGridLayout(self.spool_rows_container)
        self.spool_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.spool_rows_layout.setHorizontalSpacing(6)
        self.spool_rows_layout.setVerticalSpacing(4)
        self.spool_layout.addWidget(self.spool_rows_container, 1, 0, 1, 3)
        self.spool_add_button = QPushButton("+", self.spool_widget)
        self.spool_add_button.setToolTip("Add another spool filter row")
        self.spool_layout.addWidget(self.spool_add_button, 2, 0, 1, 3)
        layout.addWidget(self.spool_widget)

        self.on_patch_range_changed = None
        self.on_patch_enabled_changed = None
        self.on_patch_basis_changed = None
        self.on_spool_filter_changed = None
        self.on_spool_filter_add_requested = None
        self.on_spool_filter_remove_requested = None
        self.on_reset_requested = None

        self.patch_basis_combo.currentIndexChanged.connect(
            self._handle_patch_basis_changed
        )
        self.spool_add_button.clicked.connect(self._handle_spool_add_clicked)
        self.reset_button.clicked.connect(self._handle_reset_clicked)
        self.set_mode(SelectionMode.NONE)

    @contextmanager
    def syncing(self):
        """Suppress callbacks while updating widgets programmatically."""
        self._sync_depth += 1
        try:
            yield
        finally:
            self._sync_depth -= 1

    def is_syncing(self) -> bool:
        """Return True when widget values are being synced programmatically."""
        return self._sync_depth > 0

    def set_mode(self, mode: SelectionMode) -> None:
        """Update visibility and helper text for the active selection mode."""
        patch_mode = mode is SelectionMode.PATCH
        spool_mode = mode is SelectionMode.SPOOL
        self.patch_basis_label.setVisible(patch_mode)
        self.patch_basis_combo.setVisible(patch_mode)
        self.patch_basis_combo.setEnabled(patch_mode)
        self.patch_widget.setVisible(patch_mode)
        self.patch_widget.setEnabled(patch_mode)
        self.spool_widget.setVisible(spool_mode)
        self.spool_widget.setEnabled(spool_mode)
        self.reset_button.setEnabled(mode is not SelectionMode.NONE)
        if mode is SelectionMode.PATCH:
            self.mode_label.setText("Range selection")
            self.hint_label.setText(self._patch_hint_text())
        elif mode is SelectionMode.SPOOL:
            self.mode_label.setText("Metadata selection")
            self.hint_label.setText(
                "Values use Python literal syntax when possible; "
                "bare strings are treated as strings."
            )
        else:
            self.mode_label.setText("No selection source")
            self.hint_label.setText("")
            self.status_label.setText("")

    def set_status(self, text: str) -> None:
        """Set the small status/summary label."""
        self.status_label.setText(text)

    def set_patch_basis(self, basis: PatchSelectionBasis) -> None:
        """Write the current patch basis into the visible combo box."""
        with self.syncing():
            index = self.patch_basis_combo.findData(basis)
            if index >= 0:
                self.patch_basis_combo.setCurrentIndex(index)
        if self.patch_widget.isVisible():
            self.hint_label.setText(self._patch_hint_text())

    def rebuild_patch_rows(
        self,
        dims: tuple[str, ...],
        extents: dict[str, tuple[Any, Any]],
        preferred_dims: tuple[str, ...] = (),
    ) -> None:
        """Recreate patch-range controls with preferred dims listed first."""
        layout = self.patch_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.patch_checkboxes = {}
        self.patch_edits = {}
        self._active_dims = self._ordered_dims(dims, preferred_dims)

        if not self._active_dims:
            layout.addWidget(QLabel("No patch loaded", self.patch_widget), 0, 0)
            return

        for index, dim in enumerate(self._active_dims):
            row = index * 3
            checkbox = QCheckBox(self.patch_widget)
            label = QLabel(f"<b>{dim}</b>", self.patch_widget)
            min_label = QLabel("Min", self.patch_widget)
            max_label = QLabel("Max", self.patch_widget)
            low_edit = QLineEdit(self.patch_widget)
            high_edit = QLineEdit(self.patch_widget)
            low_edit.setPlaceholderText("")
            high_edit.setPlaceholderText("")
            checkbox.toggled.connect(
                lambda checked, dim_name=dim: self._handle_patch_enabled_changed(
                    dim_name, checked
                )
            )
            low_edit.editingFinished.connect(
                lambda dim_name=dim: self._handle_patch_range_changed(dim_name)
            )
            high_edit.editingFinished.connect(
                lambda dim_name=dim: self._handle_patch_range_changed(dim_name)
            )
            # Stack each dimension vertically so the control panel stays narrow.
            layout.addWidget(checkbox, row, 0)
            layout.addWidget(label, row, 1, 1, 3)
            layout.addWidget(min_label, row + 1, 0)
            layout.addWidget(low_edit, row + 1, 1, 1, 3)
            layout.addWidget(max_label, row + 2, 0)
            layout.addWidget(high_edit, row + 2, 1, 1, 3)
            self.patch_checkboxes[dim] = checkbox
            self.patch_edits[dim] = (low_edit, high_edit)

    def set_patch_ranges(
        self,
        ranges: dict[str, tuple[Any, Any]],
        extents: dict[str, tuple[Any, Any]],
    ) -> None:
        """Write current patch ranges into the visible line edits."""
        with self.syncing():
            for dim, edits in self.patch_edits.items():
                if dim not in ranges:
                    continue
                if dim not in extents:
                    continue
                low_edit, high_edit = edits
                low, high = ranges[dim]
                full_low, full_high = extents[dim]
                desired_low = (
                    "" if _values_equal(low, full_low) else _format_coord_value(low)
                )
                desired_high = (
                    "" if _values_equal(high, full_high) else _format_coord_value(high)
                )
                current_low = low_edit.text()
                current_high = high_edit.text()
                if desired_low == "":
                    low_edit.setText("")
                elif not _text_matches_display_value(current_low, full_low, low):
                    low_edit.setText(desired_low)
                if desired_high == "":
                    high_edit.setText("")
                elif not _text_matches_display_value(current_high, full_high, high):
                    high_edit.setText(desired_high)

    def set_patch_enabled(self, enabled: dict[str, bool]) -> None:
        """Write current patch enabled state into the visible controls."""
        with self.syncing():
            for dim, checkbox in self.patch_checkboxes.items():
                is_enabled = enabled.get(dim, True)
                checkbox.setChecked(is_enabled)
                low_edit, high_edit = self.patch_edits[dim]
                low_edit.setEnabled(is_enabled)
                high_edit.setEnabled(is_enabled)

    def set_spool_filters(
        self,
        options: tuple[str, ...],
        filters: list[tuple[str, str]],
    ) -> None:
        """Write spool filter state into the visible controls."""
        with self.syncing():
            while self.spool_rows_layout.count():
                item = self.spool_rows_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.spool_rows = []
            rows = filters or [("", "")]
            for row_index, (key, raw_value) in enumerate(rows):
                combo = QComboBox(self.spool_rows_container)
                combo.addItems(options)
                if key in options:
                    combo.setCurrentText(key)
                else:
                    combo.setCurrentIndex(-1)
                combo.currentIndexChanged.connect(self._handle_spool_changed)
                value_edit = QLineEdit(self.spool_rows_container)
                value_edit.setPlaceholderText("Value")
                value_edit.setText(raw_value)
                value_edit.editingFinished.connect(self._handle_spool_changed)
                remove_button = QPushButton("-", self.spool_rows_container)
                remove_button.setToolTip("Remove this spool filter row")
                remove_button.clicked.connect(
                    lambda _checked=False,
                    index=row_index: self._handle_spool_remove_clicked(index)
                )
                self.spool_rows_layout.addWidget(combo, row_index, 0)
                self.spool_rows_layout.addWidget(value_edit, row_index, 1)
                self.spool_rows_layout.addWidget(remove_button, row_index, 2)
                self.spool_rows.append((combo, value_edit, remove_button))
            for row_index, (_combo, _edit, remove_button) in enumerate(self.spool_rows):
                remove_button.setEnabled(len(self.spool_rows) > 1)

    @staticmethod
    def _ordered_dims(
        dims: tuple[str, ...],
        preferred_dims: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return dims with preferred ones first, preserving relative order."""
        preferred = [dim for dim in preferred_dims if dim in dims]
        remaining = [dim for dim in dims if dim not in preferred]
        return tuple(preferred + remaining)

    def _handle_patch_range_changed(self, dim: str) -> None:
        """Emit the current texts for a patch range row."""
        if self.is_syncing() or self.on_patch_range_changed is None:
            return
        low_edit, high_edit = self.patch_edits[dim]
        self.on_patch_range_changed(dim, low_edit.text(), high_edit.text())

    def _handle_patch_enabled_changed(self, dim: str, enabled: bool) -> None:
        """Emit the current enabled state for a patch range row."""
        if self.is_syncing():
            return
        low_edit, high_edit = self.patch_edits[dim]
        low_edit.setEnabled(enabled)
        high_edit.setEnabled(enabled)
        if self.on_patch_enabled_changed is not None:
            self.on_patch_enabled_changed(dim, enabled)

    def _handle_patch_basis_changed(self, *_args) -> None:
        """Emit the currently selected patch basis."""
        if self.is_syncing() or self.on_patch_basis_changed is None:
            return
        basis = self.patch_basis_combo.currentData()
        if isinstance(basis, PatchSelectionBasis):
            self.on_patch_basis_changed(basis)

    def _handle_spool_changed(self, *_args) -> None:
        """Emit the current spool filter values."""
        if self.is_syncing() or self.on_spool_filter_changed is None:
            return
        self.on_spool_filter_changed(
            [
                (combo.currentText().strip(), value_edit.text().strip())
                for combo, value_edit, _remove_button in self.spool_rows
            ]
        )

    def _handle_spool_add_clicked(self) -> None:
        """Request one additional spool filter row."""
        if self.is_syncing() or self.on_spool_filter_add_requested is None:
            return
        self.on_spool_filter_add_requested()

    def _handle_spool_remove_clicked(self, index: int) -> None:
        """Request removal of one spool filter row."""
        if self.is_syncing() or self.on_spool_filter_remove_requested is None:
            return
        self.on_spool_filter_remove_requested(index)

    def _handle_reset_clicked(self) -> None:
        """Invoke the reset callback."""
        if self.is_syncing() or self.on_reset_requested is None:
            return
        self.on_reset_requested()

    def _patch_hint_text(self) -> str:
        """Return the helper text for the active patch basis."""
        basis = self.patch_basis_combo.currentData()
        if basis is PatchSelectionBasis.RELATIVE:
            unit = "offsets from the first coordinate"
        elif basis is PatchSelectionBasis.SAMPLES:
            unit = "sample indices"
        else:
            unit = "coordinate values"
        return f"Edit min/max {unit}. \nLeave blank to use full extent."


class SelectionControlsMixin:
    """Reusable selection state and left-panel UI for patch/spool widgets."""

    def _init_selection_controls(self) -> None:
        """Initialize selection state before building the panel."""
        self._selection_state = SelectionState()
        self._selection_preferred_patch_dims: tuple[str, ...] = ()
        self._selection_sync_depth = 0
        self._selection_panel: SelectionPanel | None = None
        self._selection_patch_checkboxes: dict[str, QCheckBox] = {}
        self._selection_patch_edits: dict[str, tuple[QLineEdit, QLineEdit]] = {}

    @contextmanager
    def _selection_sync_guard(self):
        """Suppress recursive selection updates while syncing state and visuals."""
        self._selection_sync_depth += 1
        try:
            yield
        finally:
            self._selection_sync_depth -= 1

    def _selection_is_syncing(self) -> bool:
        """Return True when selection state is being synchronized programmatically."""
        return self._selection_sync_depth > 0

    @property
    def _selection_mode(self) -> str | None:
        """Compatibility shim for tests and host widgets."""
        if self._selection_state.mode is SelectionMode.NONE:
            return None
        return self._selection_state.mode.value

    @property
    def _selection_spool_options(self) -> tuple[str, ...]:
        """Compatibility shim exposing current spool options."""
        return self._selection_state.spool.options

    @property
    def _selection_spool_key(self) -> str:
        """Compatibility shim exposing current spool key."""
        return self._selection_state.spool.filters[0].key

    @property
    def _selection_spool_raw(self) -> str:
        """Compatibility shim exposing current spool raw value."""
        return self._selection_state.spool.filters[0].raw_value

    @property
    def _selection_spool_combo(self):
        """Compatibility shim exposing the first spool filter combo."""
        if self._selection_panel is None or not self._selection_panel.spool_rows:
            return None
        return self._selection_panel.spool_rows[0][0]

    @property
    def _selection_spool_value_edit(self):
        """Compatibility shim exposing the first spool filter value edit."""
        if self._selection_panel is None or not self._selection_panel.spool_rows:
            return None
        return self._selection_panel.spool_rows[0][1]

    @property
    def _selection_patch_basis(self) -> str:
        """Compatibility shim exposing the current patch basis."""
        return self._selection_state.patch.basis.value

    @property
    def _selection_patch_enabled(self) -> dict[str, bool]:
        """Compatibility shim exposing per-dimension enabled state."""
        return dict(self._selection_state.patch.enabled)

    def _build_selection_panel(self, parent, *, title: str = "Select") -> QWidget:
        """Create the shared selection controls under an existing parent box."""
        section = gui.widgetBox(parent, title)
        panel = SelectionPanel(section)
        panel.on_patch_range_changed = self._on_selection_patch_range_changed
        panel.on_patch_enabled_changed = self._on_selection_patch_enabled_changed
        panel.on_patch_basis_changed = self._on_selection_patch_basis_changed
        panel.on_spool_filter_changed = self._on_selection_spool_changed
        panel.on_spool_filter_add_requested = self._on_selection_spool_add_requested
        panel.on_spool_filter_remove_requested = (
            self._on_selection_spool_remove_requested
        )
        panel.on_reset_requested = self._on_selection_reset_requested
        section.layout().addWidget(panel)
        self._selection_panel = panel
        self._selection_patch_checkboxes = panel.patch_checkboxes
        return section

    def _selection_set_preferred_patch_dims(self, dims: tuple[str, ...]) -> None:
        """Set patch dims that should appear first in the left panel."""
        self._selection_preferred_patch_dims = dims

    def _selection_set_patch_source(
        self,
        patch,
        *,
        notify: bool = True,
        refresh_ui: bool = True,
    ) -> None:
        """Seed patch-mode selection state from the current patch extents."""
        self._selection_state.set_patch_source(patch)
        self._selection_refresh_panel()
        if refresh_ui:
            self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_set_spool_source(
        self,
        spool,
        *,
        notify: bool = True,
        refresh_ui: bool = True,
    ) -> None:
        """Seed spool-mode selection state from the current spool contents."""
        self._selection_state.set_spool_source(spool)
        self._selection_refresh_panel()
        if refresh_ui:
            self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_refresh_panel(self) -> None:
        """Push the current typed selection state into the Qt controls."""
        if self._selection_panel is None:
            return
        panel = self._selection_panel
        panel.set_mode(self._selection_state.mode)
        panel.set_patch_basis(self._selection_state.patch.basis)
        panel.rebuild_patch_rows(
            tuple(self._selection_state.patch.extents),
            self._selection_state.patch.extents,
            self._selection_preferred_patch_dims,
        )
        panel.set_patch_enabled(self._selection_state.patch.enabled)
        panel.set_patch_ranges(
            self._selection_state.patch.ranges,
            self._selection_state.patch.extents,
        )
        panel.set_spool_filters(
            self._selection_state.spool.options,
            [
                (filter_row.key, filter_row.raw_value)
                for filter_row in self._selection_state.spool.filters
            ],
        )
        self._selection_patch_checkboxes = panel.patch_checkboxes
        self._selection_patch_edits = panel.patch_edits

    def _selection_request_panel_refresh(self) -> None:
        """Request a visible selection-panel refresh through the host widget."""
        self._selection_refresh_panel()
        self._request_ui_refresh()

    def _selection_set_status(self, text: str) -> None:
        """Update the small status label shown in the selection panel."""
        if self._selection_panel is not None:
            self._selection_panel.set_status(text)

    def _selection_apply_to_patch(self, patch):
        """Apply the current patch-mode ranges to a patch."""
        return self._selection_state.apply_to_patch(patch)

    def _selection_apply_to_spool(self, spool):
        """Apply the current spool filter to a spool."""
        return self._selection_state.apply_to_spool(spool)

    def _selection_update_patch_range(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a single patch dimension range and refresh the visible controls."""
        self._selection_state.update_patch_range(dim, low, high)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_update_patch_range_absolute(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a patch range from absolute coordinate values."""
        self._selection_state.update_patch_range_absolute(dim, low, high)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_update_patch_range_absolute_from_roi(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a patch range from ROI-driven absolute coordinate values."""
        self._selection_state.update_patch_range_absolute_from_roi(dim, low, high)
        self._selection_refresh_panel()
        if notify:
            self._selection_on_state_changed()

    def _selection_reset_patch_dims(
        self,
        dims: tuple[str, ...],
        *,
        notify: bool = True,
    ) -> None:
        """Reset selected patch dims back to their full extents."""
        self._selection_state.reset_patch_dims(dims)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_set_patch_dim_enabled(
        self,
        dim: str,
        enabled: bool,
        *,
        notify: bool = True,
    ) -> None:
        """Enable or disable one patch dimension and refresh the controls."""
        self._selection_state.set_patch_dim_enabled(dim, enabled)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_current_patch_range(self, dim: str) -> tuple[Any, Any] | None:
        """Return the current range for a patch dimension."""
        return self._selection_state.current_patch_range(dim)

    def _selection_patch_extent(self, dim: str) -> tuple[Any, Any] | None:
        """Return the full extent for a patch dimension."""
        return self._selection_state.patch_extent(dim)

    def _selection_current_patch_absolute_range(
        self,
        dim: str,
    ) -> tuple[Any, Any] | None:
        """Return the current patch range in absolute coordinate values."""
        return self._selection_state.current_patch_absolute_range(dim)

    def _selection_patch_absolute_extent(
        self,
        dim: str,
    ) -> tuple[Any, Any] | None:
        """Return the full patch extent in absolute coordinate values."""
        return self._selection_state.patch_absolute_extent(dim)

    def _on_selection_patch_range_changed(
        self,
        dim: str,
        low_text: str,
        high_text: str,
    ) -> None:
        """Handle user edits to a patch range row."""
        if self._selection_is_syncing():
            return
        extent = self._selection_state.patch_extent(dim)
        if extent is None:
            return
        try:
            low = _parse_coord_value(low_text, extent[0], extent[0])
            high = _parse_coord_value(high_text, extent[1], extent[1])
        except Exception as exc:
            self._selection_report_error(str(exc))
            self._selection_request_panel_refresh()
            return
        self._selection_state.update_patch_range(dim, low, high)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_patch_basis_changed(self, basis: PatchSelectionBasis) -> None:
        """Handle user changes to the patch selection basis."""
        if self._selection_is_syncing():
            return
        self._selection_state.set_patch_basis(basis)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_patch_enabled_changed(self, dim: str, enabled: bool) -> None:
        """Handle user toggles of a patch dimension checkbox."""
        if self._selection_is_syncing():
            return
        self._selection_state.set_patch_dim_enabled(dim, enabled)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_changed(self, filters: list[tuple[str, str]]) -> None:
        """Handle user edits to the spool filter controls."""
        if self._selection_is_syncing():
            return
        self._selection_state.set_spool_filters(filters)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_add_requested(self) -> None:
        """Handle requests to add one spool filter row."""
        if self._selection_is_syncing():
            return
        self._selection_state.add_spool_filter()
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_remove_requested(self, index: int) -> None:
        """Handle requests to remove one spool filter row."""
        if self._selection_is_syncing():
            return
        self._selection_state.remove_spool_filter(index)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_reset_requested(self) -> None:
        """Reset the current selection back to full extents / no filter."""
        self._selection_state.reset()
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _selection_report_error(self, message: str) -> None:
        """Route selection UI errors to the widget's general error slot if present."""
        error_slot = getattr(getattr(self, "Error", None), "general", None)
        if error_slot is not None:
            error_slot(message)

    def _selection_on_state_changed(self) -> None:
        """Hook for host widgets to react when selection controls change."""
        return None
