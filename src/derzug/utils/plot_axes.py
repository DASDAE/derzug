"""Shared plot-axis helpers for DerZug widgets."""

from __future__ import annotations

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
    parts = [f"{field.name}={format_cursor_value(field.value)}" for field in fields]
    label.setText("  ".join(parts))


def format_cursor_value(value: Any) -> str:
    """Format one cursor-readout value for display."""
    from derzug.utils.display import format_display

    return format_display(value)


def nearest_axis_index(value: float, axis_values: np.ndarray) -> int:
    """Return the nearest valid axis index for a plotted numeric value."""
    axis = np.asarray(axis_values, dtype=np.float64)
    return int(np.clip(np.argmin(np.abs(axis - value)), 0, axis.size - 1))


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

    if plot[0] > plot[-1]:
        plot = plot[::-1]
        coord = coord[::-1]

    if np.issubdtype(coord.dtype, np.datetime64):
        ns = coord.astype("datetime64[ns]").astype(np.int64)
        mapped = int(interp_with_extrapolation(value, plot, ns))
        return np.datetime64(mapped, "ns")
    if np.issubdtype(coord.dtype, np.timedelta64):
        ns = coord.astype("timedelta64[ns]").astype(np.int64)
        mapped = int(interp_with_extrapolation(value, plot, ns))
        return np.timedelta64(mapped, "ns")
    if np.issubdtype(coord.dtype, np.number):
        coord_float = coord.astype(np.float64)
        return float(interp_with_extrapolation(value, plot, coord_float))

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
        mapped_value = _datetime_value_to_ns(value)
        mapped_axis = coord.astype("datetime64[ns]").astype(np.int64)
        return float(interp_with_extrapolation(mapped_value, mapped_axis, plot))
    if np.issubdtype(coord.dtype, np.timedelta64):
        mapped_value = np.timedelta64(value).astype("timedelta64[ns]").astype(np.int64)
        mapped_axis = coord.astype("timedelta64[ns]").astype(np.int64)
        return float(interp_with_extrapolation(mapped_value, mapped_axis, plot))
    if np.issubdtype(coord.dtype, np.number):
        return float(
            interp_with_extrapolation(
                float(value),
                coord.astype(np.float64),
                plot,
            )
        )

    matches = np.flatnonzero(coord == value)
    idx = int(matches[0]) if matches.size else 0
    return float(plot[idx])


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
