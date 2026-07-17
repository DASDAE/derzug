"""Shared plot-axis helpers for DerZug widgets."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pyqtgraph as pg
from AnyQt.QtGui import QFontMetrics
from AnyQt.QtWidgets import QLabel
from pyqtgraph.graphicsItems.DateAxisItem import SEC_PER_YEAR


@dataclass(frozen=True)
class PlotAxisSpec:
    """Describe one plotted axis and how pyqtgraph should render it."""

    plot_values: np.ndarray
    kind: str


@dataclass(frozen=True)
class CursorField:
    """One labelled field in a cursor readout."""

    name: str
    value: Any
    visible_span: float | None = None


def _datetime_value_to_ns(value: Any) -> np.int64:
    """Normalize one datetime-like value into integer nanoseconds since epoch."""
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[ns]").astype(np.int64)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return np.datetime64(value, "ns").astype(np.int64)
    return np.datetime64(value, "ns").astype(np.int64)


class ContextDateAxisItem(pg.DateAxisItem):
    """Date axis item that can derive compact higher-level datetime context."""

    def __init__(self, orientation="bottom", **kwargs):
        """
        Create a datetime axis for timezone-naive patch coordinates.

        Pyqtgraph's default date axis places day/month ticks at local-time
        boundaries. DerZug plots patch datetimes as naive wall-clock values, so
        tick placement must stay in the same UTC-like numeric coordinate system
        used by tick label formatting.
        """
        kwargs.setdefault("utcOffset", 0)
        super().__init__(orientation=orientation, **kwargs)

    def tickValues(self, min_val, max_val, size):
        """Return date ticks without applying the host local timezone offset."""
        self._ensure_font_metrics()
        previous_offset = self.utcOffset
        self.utcOffset = 0
        try:
            return super().tickValues(min_val, max_val, size)
        finally:
            self.utcOffset = previous_offset

    def tickStrings(self, values, scale, spacing):
        """
        Format tick labels from naive wall-clock timestamps without local shifts.

        DerZug patch datetimes are timezone-naive wall-clock values. Pyqtgraph's
        default DateAxisItem applies a UTC offset during formatting, which shifts
        the displayed hour based on the machine locale. Preserve the stored
        timestamp text instead.
        """
        tick_specs = self.zoomLevel.tickSpecs
        tick_spec = next((spec for spec in tick_specs if spec.spacing == spacing), None)
        if tick_spec is None:
            return super().tickStrings(values, scale, spacing)
        try:
            dates = [
                datetime.fromtimestamp(value, tz=UTC).replace(tzinfo=None)
                for value in values
            ]
        except (OverflowError, ValueError, OSError):
            return [f"{value // SEC_PER_YEAR + 1970:g}" for value in values]

        format_strings: list[str] = []
        for value in dates:
            try:
                text = value.strftime(tick_spec.format)
                if "%f" in tick_spec.format:
                    text = text[:-3]
                elif "%Y" in tick_spec.format:
                    text = text.lstrip("0")
                format_strings.append(text)
            except ValueError:
                format_strings.append("")
        return format_strings

    def current_context_label(self, low: float, high: float) -> str:
        """Return compact omitted datetime context for the visible range."""
        if not np.all(np.isfinite([low, high])):
            return ""
        if low == high:
            return ""
        span = abs(high - low)
        self._set_zoom_level_for_span(span)
        fine_format = self.zoomLevel.tickSpecs[-1].format
        midpoint = (low + high) / 2.0
        dt = datetime.fromtimestamp(midpoint, tz=UTC).replace(tzinfo=None)
        return _context_for_tick_format(dt, fine_format)

    def _set_zoom_level_for_span(self, span: float) -> None:
        """Update the active zoom level using the linked view size when possible."""
        self._ensure_font_metrics()
        axis_size = self._axis_pixel_size()
        density = span / axis_size if axis_size > 0 else span
        self.setZoomLevelForDensity(max(density, 1e-12))

    def _axis_pixel_size(self) -> float:
        """Return the current axis length in pixels."""
        linked = self.linkedView()
        if linked is None:
            return 1.0
        rect = linked.sceneBoundingRect()
        if self.orientation in ("bottom", "top"):
            return max(rect.width(), 1.0)
        return max(rect.height(), 1.0)

    def _ensure_font_metrics(self) -> None:
        """Seed font metrics so zoom-level selection works before first paint."""
        if hasattr(self, "fontMetrics"):
            return
        font = self.style.get("tickFont") or self.font()
        self.fontMetrics = QFontMetrics(font)


def build_plot_axis_spec(values: np.ndarray) -> PlotAxisSpec:
    """Convert coordinate arrays into numeric pyqtgraph axis values."""
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.datetime64):
        ns = arr.astype("datetime64[ns]").astype(np.int64)
        plot_values = ns.astype(np.float64) / 1e9
        if np.isfinite(plot_values).all():
            return PlotAxisSpec(plot_values=plot_values, kind="datetime")
        return PlotAxisSpec(
            plot_values=np.arange(arr.size, dtype=np.float64),
            kind="index",
        )
    if np.issubdtype(arr.dtype, np.timedelta64):
        ns = arr.astype("timedelta64[ns]").astype(np.int64)
        plot_values = ns.astype(np.float64) / 1e9
        if np.isfinite(plot_values).all():
            return PlotAxisSpec(plot_values=plot_values, kind="timedelta")
        return PlotAxisSpec(
            plot_values=np.arange(arr.size, dtype=np.float64),
            kind="index",
        )
    if np.issubdtype(arr.dtype, np.number):
        plot_values = arr.astype(np.float64)
        if np.isfinite(plot_values).all():
            return PlotAxisSpec(plot_values=plot_values, kind="numeric")
        return PlotAxisSpec(
            plot_values=np.arange(arr.size, dtype=np.float64),
            kind="index",
        )
    warnings.warn(
        "Non-numeric coordinates detected; using sample index for axes.",
        RuntimeWarning,
        stacklevel=2,
    )
    return PlotAxisSpec(
        plot_values=np.arange(arr.size, dtype=np.float64),
        kind="index",
    )


def ensure_axis_item(plot_item: pg.PlotItem, orientation: str, axis_kind: str) -> None:
    """Install a matching pyqtgraph axis item for the requested axis kind."""
    current = plot_item.getAxis(orientation)
    wants_date_axis = axis_kind == "datetime"
    if wants_date_axis and isinstance(current, ContextDateAxisItem):
        return
    if not wants_date_axis and type(current) is pg.AxisItem:
        return
    axis_item: pg.AxisItem
    if wants_date_axis:
        axis_item = ContextDateAxisItem(orientation=orientation)
    else:
        axis_item = pg.AxisItem(orientation=orientation)
    plot_item.setAxisItems({orientation: axis_item})


def format_axis_label(
    plot_item: pg.PlotItem,
    orientation: str,
    dim_name: str,
    axis_kind: str,
    axis_range: tuple[float, float],
) -> str:
    """Return the label text for an axis, adding datetime context when needed."""
    if axis_kind != "datetime":
        return dim_name
    axis_item = plot_item.getAxis(orientation)
    if not isinstance(axis_item, ContextDateAxisItem):
        return dim_name
    context = axis_item.current_context_label(*axis_range)
    return dim_name if not context else f"{dim_name} ({context})"


def set_cursor_label_text(label: QLabel, fields: list[CursorField] | None) -> None:
    """Write a standardized cursor readout into a QLabel."""
    if not fields:
        label.setText("Cursor: --")
        return
    parts = [
        f"{field.name}={format_cursor_value(field.value, field.visible_span)}"
        for field in fields
    ]
    label.setText("  ".join(parts))


def format_cursor_value(value: Any, visible_span: float | None = None) -> str:
    """Format one cursor-readout value for display."""
    from derzug.utils.display import format_display

    quantum = _cursor_display_quantum(visible_span)
    if quantum is None:
        return format_display(value)

    arr = np.asarray(value)
    if np.issubdtype(arr.dtype, np.datetime64):
        unit = _time_unit_for_quantum(quantum)
        return np.datetime_as_string(
            arr.astype(f"datetime64[{unit}]"),
            unit=unit,
            timezone="naive",
        )
    if np.issubdtype(arr.dtype, np.timedelta64):
        seconds = float(arr.astype("timedelta64[ns]").astype(np.int64)) / 1e9
        return _format_cursor_float(seconds, quantum, suffix=" s")

    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return _format_cursor_float(value, quantum)
    return format_display(value)


def _cursor_display_quantum(visible_span: float | None) -> float | None:
    """Return the smallest useful cursor increment for a visible extent."""
    if visible_span is None:
        return None
    try:
        span = abs(float(visible_span))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(span) or span <= 0:
        return None
    return span / 1000.0


def _decimal_places_for_quantum(quantum: float) -> int:
    """Return fixed decimal places needed to show one display quantum."""
    return max(0, math.ceil(-math.log10(quantum)))


def _format_cursor_float(value: float, quantum: float, suffix: str = "") -> str:
    """Format a cursor float using fixed decimals derived from quantum."""
    decimals = _decimal_places_for_quantum(quantum)
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text}{suffix}"


def _time_unit_for_quantum(quantum_seconds: float) -> str:
    """Return the finest datetime unit worth showing for a seconds quantum."""
    if quantum_seconds >= 1.0:
        return "s"
    if quantum_seconds >= 1e-3:
        return "ms"
    if quantum_seconds >= 1e-6:
        return "us"
    return "ns"


def nearest_axis_index(value: float, axis_values: np.ndarray) -> int:
    """Return the nearest index in a monotonic plotted numeric axis."""
    axis = np.asarray(axis_values, dtype=np.float64)
    if axis.size <= 1:
        return 0
    if not math.isfinite(float(value)):
        return 0

    descending = bool(axis[0] > axis[-1])
    ordered = axis[::-1] if descending else axis
    insertion = int(np.searchsorted(ordered, value, side="left"))
    if insertion <= 0:
        ordered_index = 0
    elif insertion >= ordered.size:
        ordered_index = ordered.size - 1
    else:
        left = insertion - 1
        right = insertion
        ordered_index = (
            left if value - ordered[left] <= ordered[right] - value else right
        )
    if descending:
        return int(axis.size - ordered_index - 1)
    return int(ordered_index)


def nearest_value_index(value: float, values: np.ndarray) -> int:
    """Return the index of the value nearest ``value`` in an unsorted array.

    Unlike :func:`nearest_axis_index`, this makes no monotonicity assumption
    and scans every element, so use it for arbitrary data (e.g. amplitudes)
    rather than plotted axes.
    """
    array = np.asarray(values, dtype=np.float64)
    if array.size <= 1:
        return 0
    if not math.isfinite(float(value)):
        return 0
    deltas = np.abs(array - value)
    if not np.any(np.isfinite(deltas)):
        return 0
    return int(np.nanargmin(deltas))


def interp_with_extrapolation(
    value: float,
    x: np.ndarray,
    y: np.ndarray,
) -> float:
    """Interpolate y(x) and extrapolate linearly outside x bounds."""
    if x.size == 0 or y.size == 0:
        return float(value)
    if x.size == 1 or y.size == 1:
        return float(y[0])

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


def map_plot_value_to_coord(
    value: float,
    plot_axis: np.ndarray,
    coord_axis: np.ndarray,
):
    """
    Map a plotted axis position back to a coordinate value.

    Uses interpolation for numeric/time-like coordinates and nearest-index
    fallback for unsupported dtypes.
    """
    if plot_axis.size == 0 or coord_axis.size == 0:
        return value

    plot = np.asarray(plot_axis, dtype=np.float64)
    coord = np.asarray(coord_axis)
    left, right, fraction = _interpolation_position(value, plot)
    if np.issubdtype(coord.dtype, np.datetime64):
        left_ns = coord[left].astype("datetime64[ns]").astype(np.int64)
        right_ns = coord[right].astype("datetime64[ns]").astype(np.int64)
        mapped = int(left_ns + ((right_ns - left_ns) * fraction))
        return np.datetime64(mapped, "ns")
    if np.issubdtype(coord.dtype, np.timedelta64):
        left_ns = coord[left].astype("timedelta64[ns]").astype(np.int64)
        right_ns = coord[right].astype("timedelta64[ns]").astype(np.int64)
        mapped = int(left_ns + ((right_ns - left_ns) * fraction))
        return np.timedelta64(mapped, "ns")
    if np.issubdtype(coord.dtype, np.number):
        left_value = float(coord[left])
        right_value = float(coord[right])
        return left_value + ((right_value - left_value) * fraction)

    idx = nearest_axis_index(value, plot)
    return coord[idx]


def map_coord_to_plot_value(
    value: float | np.datetime64 | np.timedelta64,
    coord_axis: np.ndarray,
    plot_axis: np.ndarray,
) -> float:
    """Map a coordinate value into the numeric plot axis used by pyqtgraph."""
    coord = np.asarray(coord_axis)
    plot = np.asarray(plot_axis, dtype=np.float64)
    if coord.size == 0 or plot.size == 0:
        return 0.0

    if np.issubdtype(coord.dtype, np.datetime64):
        mapped_value = np.datetime64(value, "ns")
    elif np.issubdtype(coord.dtype, np.timedelta64):
        mapped_value = np.timedelta64(value).astype("timedelta64[ns]")
    elif np.issubdtype(coord.dtype, np.number):
        mapped_value = float(value)
    else:
        matches = np.flatnonzero(coord == value)
        idx = int(matches[0]) if matches.size else 0
        return float(plot[idx])
    left, right, fraction = _interpolation_position(mapped_value, coord)
    left_value = float(plot[left])
    right_value = float(plot[right])
    return left_value + ((right_value - left_value) * fraction)


def _interpolation_position(value: Any, axis: np.ndarray) -> tuple[int, int, float]:
    """Return source neighbor indices and interpolation fraction on a monotonic axis."""
    axis = np.asarray(axis)
    if axis.size <= 1:
        return 0, 0, 0.0
    descending = bool(axis[0] > axis[-1])
    ordered = axis[::-1] if descending else axis
    insertion = int(np.searchsorted(ordered, value, side="left"))
    if insertion <= 0:
        ordered_left, ordered_right = 0, 1
    elif insertion >= ordered.size:
        ordered_left, ordered_right = ordered.size - 2, ordered.size - 1
    else:
        ordered_left, ordered_right = insertion - 1, insertion
    if descending:
        left = axis.size - ordered_left - 1
        right = axis.size - ordered_right - 1
    else:
        left, right = ordered_left, ordered_right
    delta = axis[right] - axis[left]
    if delta == 0:
        return int(left), int(right), 0.0
    fraction = float((value - axis[left]) / delta)
    return int(left), int(right), fraction


def _context_for_tick_format(dt: datetime, tick_format: str) -> str:
    """Return omitted higher-level datetime context for the finest tick format."""
    if "%f" in tick_format:
        return dt.strftime("%Y-%m-%d %H:%M")
    if "%H" in tick_format or "%M" in tick_format or "%S" in tick_format:
        return dt.strftime("%Y-%m-%d")
    if "%d" in tick_format:
        return dt.strftime("%Y-%m")
    if "%b" in tick_format or "%m" in tick_format:
        return dt.strftime("%Y")
    return ""
