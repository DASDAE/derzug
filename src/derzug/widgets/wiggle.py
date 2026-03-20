"""Interactive pyqtgraph wiggle widget for DASCore patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

import dascore as dc
import numpy as np
import pyqtgraph as pg
from AnyQt.QtCore import Qt, Signal
from AnyQt.QtWidgets import QComboBox, QLabel, QSlider, QVBoxLayout, QWidget
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting
from derzug.utils.plot_axes import (
    CursorField,
    build_plot_axis_spec,
    ensure_axis_item,
    format_axis_label,
    map_plot_value_to_coord,
    nearest_axis_index,
    set_cursor_label_text,
)


@dataclass(frozen=True)
class _OffsetRenderState:
    """Computed plotting metadata for offset-mode rendering."""

    mode: str
    x_dim: str
    x_plot: np.ndarray
    x_coord: np.ndarray
    y_dim: str
    left_axis_kind: str
    bottom_axis_kind: str
    title: str
    trace_offsets: np.ndarray
    trace_indices: np.ndarray
    flat_x: np.ndarray
    flat_y: np.ndarray


@dataclass(frozen=True)
class _TimeSeriesRenderState:
    """Computed plotting metadata for time-series rendering."""

    mode: str
    x_dim: str
    x_plot: np.ndarray
    x_coord: np.ndarray
    y_dim: str
    bottom_axis_kind: str
    title: str
    line_values: np.ndarray
    full_line_values: np.ndarray
    series_dim: str | None = None
    series_plot: np.ndarray | None = None
    series_coord: np.ndarray | None = None
    series_indices: np.ndarray | None = None
    percentiles_enabled: bool = False
    color_levels: tuple[float, float] | None = None


_WiggleRenderState: TypeAlias = _OffsetRenderState | _TimeSeriesRenderState


class _ExpandableGainSlider(QSlider):
    """Horizontal slider that can request range expansion while dragging at edges."""

    edge_dragged = Signal(int)

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None):
        super().__init__(orientation, parent)
        self._last_edge_direction = 0

    def mousePressEvent(self, event) -> None:
        """Reset edge state for a fresh drag gesture."""
        self._last_edge_direction = 0
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Clear remembered edge state when dragging stops."""
        self._last_edge_direction = 0
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Emit once per edge hit while the handle is dragged against a boundary."""
        super().mouseMoveEvent(event)
        if self.orientation() != Qt.Horizontal:
            return
        if not (event.buttons() & Qt.LeftButton):
            self._last_edge_direction = 0
            return

        direction = 0
        x_pos = event.position().x()
        if x_pos <= 0 and self.sliderPosition() == self.minimum():
            direction = -1
        elif x_pos >= self.width() - 1 and self.sliderPosition() == self.maximum():
            direction = 1

        if direction == 0:
            self._last_edge_direction = 0
            return
        if direction != self._last_edge_direction:
            self.edge_dragged.emit(direction)
            self._last_edge_direction = direction


class Wiggle(ZugWidget):
    """Display DASCore patches as wiggle or time-series plots."""

    _AUTO_STRIDE_TRACE_CAP = 300
    _GAIN_MIN = 1
    _GAIN_MAX = 1200

    name = "Wiggle"
    description = "Interactive pyqtgraph wiggle view for DAS patches"
    icon = "icons/Wiggle.svg"
    category = "Visualize"
    keywords = ("wiggle", "patch", "pyqtgraph", "dascore")
    priority = 21

    _COLORMAPS = (
        "CET-D1",
        "CET-D1A",
        "CET-L1",
        "viridis",
        "cividis",
        "inferno",
        "magma",
        "plasma",
        "turbo",
    )

    mode = Setting("offset")
    selected_trace_dim = Setting("")
    selected_x_dim = Setting("")
    stride = Setting(8)
    gain = Setting(150)
    colormap = Setting("viridis")
    series_color_limits = Setting(None)
    percentiles = Setting(False)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("Could not render patch: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        unknown_colormap = Msg("Unknown colormap '{}'; falling back to viridis")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="DAS patch to visualize")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch passed through unchanged")

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._render_state: _WiggleRenderState | None = None
        self._auto_stride_initialized = False
        self._preserve_view_on_refresh = False
        self._stride_ui_dirty = False
        self._colormap_ui_dirty = False
        self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
        self._axis_dims = {"bottom": "Sample", "left": "Trace"}
        self._series_curves: list[pg.PlotCurveItem] = []
        self._ignore_color_level_changes = 0
        self._current_colormap = pg.colormap.get("viridis")

        self._display_box = gui.widgetBox(self.controlArea, "Display")
        gui.widgetLabel(self._display_box, "Mode:")
        self._mode_combo = QComboBox(self._display_box)
        self._mode_combo.addItems(["offset", "time series"])
        self._display_box.layout().addWidget(self._mode_combo)

        self._offset_box = gui.widgetBox(self.controlArea, "Offset")
        gui.widgetLabel(self._offset_box, "Trace axis:")
        self._trace_axis_combo = QComboBox(self._offset_box)
        self._offset_box.layout().addWidget(self._trace_axis_combo)
        self._stride_spin = gui.spin(
            self._offset_box,
            self,
            "stride",
            minv=1,
            maxv=2048,
            label="Stride",
            callback=self._on_plot_setting_changed,
        )
        gui.widgetLabel(self._offset_box, "Gain (%):")
        self._gain_slider = _ExpandableGainSlider(Qt.Horizontal, self._offset_box)
        self._gain_slider.setRange(self._GAIN_MIN, self._GAIN_MAX)
        self._gain_slider.setSingleStep(1)
        self._gain_slider.setPageStep(1)
        self._gain_slider.setTickInterval(1)
        self._offset_box.layout().addWidget(self._gain_slider)
        self._gain_label = gui.widgetLabel(self._offset_box, "")

        self._time_series_box = gui.widgetBox(self.controlArea, "Time Series")
        gui.widgetLabel(self._time_series_box, "X axis:")
        self._x_axis_combo = QComboBox(self._time_series_box)
        self._time_series_box.layout().addWidget(self._x_axis_combo)
        gui.widgetLabel(self._time_series_box, "Colormap:")
        self._cmap_combo = QComboBox(self._time_series_box)
        self._cmap_combo.addItems(self._COLORMAPS)
        self._time_series_box.layout().addWidget(self._cmap_combo)
        self._percentiles_checkbox = gui.checkBox(
            self._time_series_box,
            self,
            "percentiles",
            "Percentiles",
            callback=self._on_plot_setting_changed,
        )
        if self.colormap not in self._COLORMAPS:
            self.colormap = "viridis"
        self._cmap_combo.setCurrentText(self.colormap)
        self._sync_gain_control()
        self._update_gain_label()

        plot_panel = QWidget(self.mainArea)
        panel_layout = QVBoxLayout(plot_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)

        self._plot_widget = pg.PlotWidget(plot_panel, background="w")
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._plot_item.setLabel("left", "Trace")
        self._plot_item.setLabel("bottom", "Sample")
        self._cursor_label = QLabel("Cursor: --", plot_panel)
        self._cursor_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        panel_layout.addWidget(self._plot_widget)
        panel_layout.addWidget(self._cursor_label)
        self.mainArea.layout().addWidget(plot_panel)

        self._curve = pg.PlotCurveItem(pen=pg.mkPen(color=(15, 15, 15, 255), width=2))
        self._plot_item.addItem(self._curve)
        self._color_bar = pg.ColorBarItem(
            values=(0.0, 1.0),
            colorMap=self.colormap,
            label="",
            interactive=True,
            colorMapMenu=False,
        )
        self._plot_item.layout.addItem(self._color_bar, 2, 5)
        self._plot_item.layout.setColumnFixedWidth(4, 5)
        self._color_bar.hide()

        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self._x_axis_combo.currentTextChanged.connect(self._on_x_axis_changed)
        self._trace_axis_combo.currentTextChanged.connect(self._on_trace_axis_changed)
        self._gain_slider.valueChanged.connect(self._on_gain_slider_value_changed)
        self._gain_slider.edge_dragged.connect(self._expand_gain_slider_range)
        self._cmap_combo.currentTextChanged.connect(self._on_colormap_changed)
        self._color_bar.sigLevelsChanged.connect(self._on_color_bar_levels_changed)
        self._mouse_proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_plot_mouse_moved,
        )
        self._plot_item.vb.sigRangeChanged.connect(self._on_view_range_changed)
        self._apply_colormap(self.colormap)
        self._refresh_controls()

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch, render it, and emit output."""
        self._patch = patch
        if patch is not None and np.asarray(patch.data).ndim == 1:
            self.mode = "time series"
        self._initialize_stride_from_first_patch()
        self._request_ui_refresh()
        self._emit_current_patch()

    def _initialize_stride_from_first_patch(self) -> None:
        """Choose a one-time default stride from the first 2D patch."""
        if self._auto_stride_initialized or self._patch is None:
            return
        data = np.asarray(self._patch.data)
        if data.ndim != 2:
            return
        self._auto_stride_initialized = True
        dims = tuple(self._patch.dims)
        trace_dim = (
            self.selected_trace_dim
            if self.selected_trace_dim in dims
            else ("distance" if "distance" in dims else dims[0])
        )
        trace_count = self._trace_count_for_dim(self._patch, trace_dim)
        stride = self._auto_stride_for_trace_count(trace_count)
        self.stride = stride
        if not self._is_ui_visible():
            self._stride_ui_dirty = True
            return
        self._sync_stride_control()

    @staticmethod
    def _auto_stride_for_trace_count(trace_count: int) -> int:
        """Return the smallest stride that caps plotted traces at 300."""
        trace_count = max(int(trace_count), 1)
        if trace_count <= Wiggle._AUTO_STRIDE_TRACE_CAP:
            return 1
        return int(np.ceil(trace_count / Wiggle._AUTO_STRIDE_TRACE_CAP))

    @staticmethod
    def _trace_count_for_dim(patch: dc.Patch, trace_dim: str) -> int:
        """Return how many traces offset mode would plot for the given trace dim."""
        _dim0, dim1 = patch.dims
        if trace_dim == dim1:
            return int(patch.shape[1])
        return int(patch.shape[0])

    def _patch_ndim(self) -> int | None:
        """Return the dimensionality of the current patch data, if any."""
        if self._patch is None:
            return None
        return int(np.asarray(self._patch.data).ndim)

    def _available_modes(self) -> tuple[str, ...]:
        """Return the mode options supported by the current patch."""
        ndim = self._patch_ndim()
        if ndim == 1:
            return ("time series",)
        if ndim == 2:
            return ("offset", "time series")
        return ()

    def _preferred_x_dim(self, dims: tuple[str, ...]) -> str:
        """Return the preferred X dimension for time-series mode."""
        if "time" in dims:
            return "time"
        if len(dims) > 1:
            return dims[1]
        return dims[0]

    @staticmethod
    def _data_label_for_patch(patch: dc.Patch) -> str:
        """Return the y-axis label for time-series data."""
        data_units = getattr(patch.attrs, "data_units", None)
        if not data_units:
            return "value"
        units = getattr(data_units, "units", None)
        if units:
            return str(units)
        return str(data_units)

    def _refresh_controls(self) -> None:
        """Refresh mode and axis controls from the current patch."""
        dims = tuple(self._patch.dims) if self._patch is not None else ()
        modes = self._available_modes()

        self._mode_combo.blockSignals(True)
        self._mode_combo.clear()
        self._mode_combo.addItems(modes)
        if modes and self.mode not in modes:
            self.mode = modes[0]
        if self.mode:
            self._mode_combo.setCurrentText(self.mode)
        self._mode_combo.blockSignals(False)

        self._x_axis_combo.blockSignals(True)
        self._x_axis_combo.clear()
        self._x_axis_combo.addItems(dims)
        if dims and self.selected_x_dim not in dims:
            self.selected_x_dim = self._preferred_x_dim(dims)
        if dims:
            self._x_axis_combo.setCurrentText(self.selected_x_dim)
        self._x_axis_combo.blockSignals(False)

        self._trace_axis_combo.blockSignals(True)
        self._trace_axis_combo.clear()
        self._trace_axis_combo.addItems(dims)
        if dims and self.selected_trace_dim not in dims:
            self.selected_trace_dim = "distance" if "distance" in dims else dims[0]
        if dims:
            self._trace_axis_combo.setCurrentText(self.selected_trace_dim)
        self._trace_axis_combo.blockSignals(False)

        ndim = self._patch_ndim()
        is_time_series = self.mode == "time series"
        allow_mode_change = ndim == 2
        self._mode_combo.setEnabled(allow_mode_change)
        self._x_axis_combo.setEnabled(bool(dims) and is_time_series)
        self._trace_axis_combo.setEnabled(
            bool(dims) and ndim == 2 and not is_time_series
        )
        self._stride_spin.setEnabled(ndim == 2 and not is_time_series)
        self._gain_slider.setEnabled(ndim == 2 and not is_time_series)
        self._cmap_combo.setEnabled(ndim == 2 and is_time_series)
        self._percentiles_checkbox.setEnabled(ndim == 2 and is_time_series)
        self._update_mode_sections()

    def _update_mode_sections(self) -> None:
        """Show only the parameter section relevant to the active render mode."""
        ndim = self._patch_ndim()
        has_modes = bool(self._available_modes())
        self._display_box.setVisible(has_modes)
        show_offset = ndim == 2 and self.mode == "offset"
        show_time_series = self.mode == "time series" and ndim in (1, 2)
        self._offset_box.setVisible(show_offset)
        self._time_series_box.setVisible(show_time_series)

    def _on_mode_changed(self, value: str) -> None:
        """Persist selected render mode and re-render."""
        self.mode = value
        self._request_ui_refresh()
        self._emit_current_patch()

    def _on_x_axis_changed(self, value: str) -> None:
        """Persist selected X dimension and re-render."""
        self.selected_x_dim = value
        self._request_ui_refresh()
        self._emit_current_patch()

    def _on_trace_axis_changed(self, value: str) -> None:
        """Persist selected trace dimension and re-render."""
        self.selected_trace_dim = value
        self._request_ui_refresh()
        self._emit_current_patch()

    def _on_plot_setting_changed(self) -> None:
        """Re-render when stride or gain controls change."""
        self._preserve_view_on_refresh = True
        self._request_ui_refresh()
        self._emit_current_patch()

    def _on_gain_changed(self) -> None:
        """Re-render after gain changes without resetting the current view."""
        self._on_plot_setting_changed()

    def _on_gain_slider_value_changed(self, value: int) -> None:
        """Persist slider-driven gain updates before re-rendering."""
        self.gain = int(value)
        self._on_gain_changed()

    def _on_colormap_changed(self, name: str) -> None:
        """Update the time-series colormap and redraw any colored traces."""
        self.colormap = name
        if not self._is_ui_visible():
            self._colormap_ui_dirty = True
            self._request_ui_refresh()
            return
        self._apply_colormap(name)
        if self._render_state is not None and self._render_state.mode == "time series":
            self._apply_series_colors()

    def _refresh_ui(self) -> None:
        """Synchronize controls and redraw the current patch."""
        self._refresh_controls()
        if self._stride_ui_dirty:
            self._sync_stride_control()
            self._stride_ui_dirty = False
        if self._colormap_ui_dirty:
            self._apply_colormap(self.colormap)
            self._colormap_ui_dirty = False
        self._sync_gain_control()
        self._update_gain_label()
        preserve_view = self._preserve_view_on_refresh
        try:
            self._render_patch(preserve_view_range=preserve_view)
        finally:
            self._preserve_view_on_refresh = False

    def _sync_stride_control(self) -> None:
        """Write the current stride setting into the visible control once."""
        self._stride_spin.blockSignals(True)
        try:
            self._stride_spin.setValue(int(self.stride))
        finally:
            self._stride_spin.blockSignals(False)

    def _sync_colormap_control(self) -> None:
        """Write the current colormap setting into the visible control once."""
        self._cmap_combo.blockSignals(True)
        try:
            self._cmap_combo.setCurrentText(self.colormap)
        finally:
            self._cmap_combo.blockSignals(False)

    def _sync_gain_control(self) -> None:
        """Write the current gain setting into the visible slider."""
        self._ensure_gain_slider_covers(self.gain)
        self._gain_slider.blockSignals(True)
        try:
            self._gain_slider.setValue(self._normalize_gain(self.gain))
        finally:
            self._gain_slider.blockSignals(False)

    def _expand_gain_slider_range(self, direction: int) -> None:
        """Extend the gain slider range outward when dragged against an edge."""
        current_min = self._gain_slider.minimum()
        current_max = self._gain_slider.maximum()
        span = max(current_max - current_min, 1)
        step = max(50, span // 2)

        if direction > 0:
            self._gain_slider.setMaximum(current_max + step)
            self._gain_slider.setValue(self._gain_slider.maximum())
            return

        new_min = max(self._GAIN_MIN, current_min - step)
        self._gain_slider.setMinimum(new_min)
        self._gain_slider.setValue(self._gain_slider.minimum())

    def _ensure_gain_slider_covers(self, gain: int | float) -> None:
        """Expand the visible slider range if the persisted gain lies outside it."""
        normalized = self._normalize_gain(gain)
        if normalized > self._gain_slider.maximum():
            self._gain_slider.setMaximum(normalized)
        if normalized < self._gain_slider.minimum():
            self._gain_slider.setMinimum(normalized)

    def _on_color_bar_levels_changed(self, _bar) -> None:
        """Persist interactive colorbar levels and recolor 2D time-series lines."""
        if self._ignore_color_level_changes:
            return
        levels = self._color_bar.levels()
        if levels is None or not np.isfinite(levels).all():
            self.series_color_limits = None
        else:
            self.series_color_limits = [float(levels[0]), float(levels[1])]
        self._apply_series_colors()

    def _apply_colormap(self, name: str) -> None:
        """Apply a pyqtgraph colormap to the time-series colorbar."""
        self.Warning.clear()
        try:
            cmap = pg.colormap.get(name)
        except Exception:
            self.Warning.unknown_colormap(name)
            cmap = pg.colormap.get("viridis")
            self.colormap = "viridis"
            self._cmap_combo.blockSignals(True)
            self._cmap_combo.setCurrentText("viridis")
            self._cmap_combo.blockSignals(False)
        self._current_colormap = cmap
        self._color_bar.setColorMap(cmap)

    def _set_color_bar_levels(self, levels: tuple[float, float] | None) -> None:
        """Update the colorbar range without persisting render-time changes."""
        if levels is None:
            return
        low, high = levels
        if low == high:
            low -= 0.5
            high += 0.5
        self._ignore_color_level_changes += 1
        try:
            self._color_bar.setLevels((float(low), float(high)))
        finally:
            self._ignore_color_level_changes -= 1

    def _render_patch(self, preserve_view_range: bool = False) -> None:
        """Render the current patch in the selected mode."""
        self.Error.clear()
        view_range = self._get_view_range() if preserve_view_range else None
        self._clear_curves()
        self._hide_color_bar()

        if self._patch is None:
            self._render_state = None
            self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
            self._axis_dims = {"bottom": "Sample", "left": "Trace"}
            self._plot_item.setTitle("No patch")
            self._set_cursor_readout(None)
            self._refresh_axis_labels()
            return

        try:
            data = np.asarray(self._patch.data)
            if data.ndim == 1:
                self.mode = "time series"
                self._refresh_controls()
                state = self._build_time_series_state_1d(self._patch)
                self._apply_time_series_state(state)
            elif data.ndim == 2 and self.mode == "time series":
                state = self._build_time_series_state_2d(
                    self._patch,
                    selected_x_dim=self.selected_x_dim,
                    percentiles_enabled=bool(self.percentiles),
                    color_limits=self.series_color_limits,
                )
                self._apply_time_series_state(state)
            elif data.ndim == 2:
                state = self._build_offset_state_2d(
                    self._patch,
                    selected_trace_dim=self.selected_trace_dim,
                    stride=self.stride,
                    gain=self.gain,
                )
                self._apply_offset_state(state)
            else:
                raise ValueError(f"expected 1D or 2D data, got shape {data.shape}")

            self._refresh_axis_labels()
            if view_range is None:
                self._plot_item.vb.enableAutoRange(x=True, y=True)
                self._plot_item.vb.autoRange()
            else:
                self._plot_item.vb.disableAutoRange()
                self._plot_item.vb.setRange(
                    xRange=view_range[0],
                    yRange=view_range[1],
                    padding=0,
                )
        except Exception as exc:
            self._render_state = None
            self._clear_curves()
            self._hide_color_bar()
            self._plot_item.setTitle("Render failed")
            self._set_cursor_readout(None)
            self._show_exception("invalid_patch", exc)

    @staticmethod
    def _build_time_series_state_1d(patch: dc.Patch) -> _TimeSeriesRenderState:
        """Build plotting metadata for a 1D time-series patch."""
        data = np.asarray(patch.data)
        x_dim = patch.dims[0]
        x_coord = np.asarray(patch.get_array(x_dim))
        x_axis = build_plot_axis_spec(x_coord)
        y_dim = Wiggle._data_label_for_patch(patch)
        return _TimeSeriesRenderState(
            mode="time series",
            x_dim=x_dim,
            x_plot=x_axis.plot_values,
            x_coord=x_coord,
            y_dim=y_dim,
            bottom_axis_kind=x_axis.kind,
            title=f"Time Series ({x_dim})",
            line_values=np.asarray(data, dtype=np.float64)[np.newaxis, :],
            full_line_values=np.asarray(data, dtype=np.float64)[np.newaxis, :],
        )

    @classmethod
    def _build_time_series_state_2d(
        cls,
        patch: dc.Patch,
        *,
        selected_x_dim: str,
        percentiles_enabled: bool,
        color_limits: list[float] | tuple[float, float] | None,
    ) -> _TimeSeriesRenderState:
        """Build plotting metadata for a 2D time-series patch."""
        data = np.asarray(patch.data)
        dim0, dim1 = patch.dims
        coords0 = np.asarray(patch.get_array(dim0))
        coords1 = np.asarray(patch.get_array(dim1))
        axis0 = build_plot_axis_spec(coords0)
        axis1 = build_plot_axis_spec(coords1)

        if selected_x_dim == dim0:
            x_dim = dim0
            x_plot = axis0.plot_values
            x_coord = coords0
            x_kind = axis0.kind
            series_dim = dim1
            series_plot = axis1.plot_values
            series_coord = coords1
            series_values = data.T
            series_indices = np.arange(data.shape[1], dtype=int)
        else:
            x_dim = dim1
            x_plot = axis1.plot_values
            x_coord = coords1
            x_kind = axis1.kind
            series_dim = dim0
            series_plot = axis0.plot_values
            series_coord = coords0
            series_values = data
            series_indices = np.arange(data.shape[0], dtype=int)

        if series_values.size == 0:
            raise ValueError("no time-series traces available to plot")

        full_line_values = np.asarray(series_values, dtype=np.float64)
        series_plot = np.asarray(series_plot, dtype=np.float64)
        series_coord = np.asarray(series_coord)
        series_indices = np.asarray(series_indices, dtype=int)
        if percentiles_enabled:
            percentile_values = np.asarray([0.0, 5.0, 25.0, 50.0, 75.0, 95.0, 100.0])
            rendered_values = np.nanpercentile(
                full_line_values, percentile_values, axis=0
            )
            rendered_series_plot = percentile_values
            rendered_series_coord = percentile_values
            rendered_series_indices = np.arange(len(percentile_values), dtype=int)
            rendered_series_dim = "percentile"
        else:
            rendered_values = full_line_values
            rendered_series_plot = series_plot
            rendered_series_coord = series_coord
            rendered_series_indices = series_indices
            rendered_series_dim = series_dim
        default_levels = cls._default_series_color_levels(rendered_series_plot)
        resolved_levels = cls._resolve_series_color_levels(
            series_plot=rendered_series_plot,
            color_limits=color_limits,
            default_levels=default_levels,
        )
        y_dim = cls._data_label_for_patch(patch)
        return _TimeSeriesRenderState(
            mode="time series",
            x_dim=x_dim,
            x_plot=x_plot,
            x_coord=x_coord,
            y_dim=y_dim,
            bottom_axis_kind=x_kind,
            title=f"Time Series ({x_dim})",
            line_values=np.asarray(rendered_values, dtype=np.float64),
            full_line_values=full_line_values,
            series_dim=rendered_series_dim,
            series_plot=np.asarray(rendered_series_plot, dtype=np.float64),
            series_coord=np.asarray(rendered_series_coord),
            series_indices=np.asarray(rendered_series_indices, dtype=int),
            percentiles_enabled=percentiles_enabled,
            color_levels=resolved_levels,
        )

    def _render_series_lines(
        self, x_plot: np.ndarray, series_values: np.ndarray
    ) -> None:
        """Render one curve per row in a 2D series matrix."""
        # This assumes _clear_curves() removed any prior extra line items first.
        if series_values.shape[0] == 0:
            self._curve.setData([], [])
            return

        self._curve.setData(x_plot, series_values[0])
        for row in series_values[1:]:
            curve = pg.PlotCurveItem()
            curve.setData(x_plot, row)
            self._plot_item.addItem(curve)
            self._series_curves.append(curve)

    @staticmethod
    def _build_offset_state_2d(
        patch: dc.Patch,
        *,
        selected_trace_dim: str,
        stride: int,
        gain: int,
    ) -> _OffsetRenderState:
        """Build plotting metadata for a 2D offset wiggle patch."""
        data = np.asarray(patch.data)
        dim0, dim1 = patch.dims
        coords0 = np.asarray(patch.get_array(dim0))
        coords1 = np.asarray(patch.get_array(dim1))
        axis0 = build_plot_axis_spec(coords0)
        axis1 = build_plot_axis_spec(coords1)
        stride = max(int(stride), 1)
        if selected_trace_dim == dim1:
            traces = data[:, ::stride].T
            offsets = axis1.plot_values[::stride]
            x_axis = axis0.plot_values
            x_coord = coords0
            trace_indices = np.arange(data.shape[1], dtype=int)[::stride]
            left_axis_kind = axis1.kind
            bottom_axis_kind = axis0.kind
            x_label = dim0
        else:
            traces = data[::stride, :]
            offsets = axis0.plot_values[::stride]
            x_axis = axis1.plot_values
            x_coord = coords1
            trace_indices = np.arange(data.shape[0], dtype=int)[::stride]
            left_axis_kind = axis0.kind
            bottom_axis_kind = axis1.kind
            x_label = dim1

        if traces.size == 0:
            raise ValueError("no traces available to plot")

        trace_scale = float(gain) / 100.0
        max_abs = np.nanmax(np.abs(traces), axis=1, keepdims=True)
        max_abs[~np.isfinite(max_abs) | (max_abs == 0)] = 1.0
        normalized = traces / max_abs
        y_values = normalized * trace_scale + offsets[:, np.newaxis]

        n_traces, _ = y_values.shape
        x_rows = np.tile(x_axis, (n_traces, 1))
        if n_traces > 1:
            x_rows[1::2] = x_rows[1::2, ::-1]
            y_values = y_values.copy()
            y_values[1::2] = y_values[1::2, ::-1]
        nans_col = np.full((n_traces, 1), np.nan)
        x_with_nan = np.concatenate([x_rows, nans_col], axis=1)
        flat_x = x_with_nan.ravel()
        flat_y = np.concatenate([y_values, nans_col], axis=1).ravel()
        return _OffsetRenderState(
            mode="offset",
            x_dim=x_label,
            x_plot=x_axis,
            x_coord=x_coord,
            y_dim=selected_trace_dim,
            left_axis_kind=left_axis_kind,
            bottom_axis_kind=bottom_axis_kind,
            title=f"Wiggle ({selected_trace_dim})",
            trace_offsets=offsets,
            trace_indices=trace_indices,
            flat_x=flat_x,
            flat_y=flat_y,
        )

    def _apply_time_series_state(self, state: _TimeSeriesRenderState) -> None:
        """Apply time-series plotting metadata to the live plot."""
        self._render_series_lines(state.x_plot, state.line_values)
        self._render_state = state
        self._axis_kinds = {"bottom": state.bottom_axis_kind, "left": "numeric"}
        self._axis_dims = {"bottom": state.x_dim, "left": state.y_dim}
        ensure_axis_item(self._plot_item, "bottom", state.bottom_axis_kind)
        ensure_axis_item(self._plot_item, "left", "numeric")
        self._plot_item.setTitle(state.title)
        if state.series_dim is None:
            return
        if state.color_levels is None or state.series_plot is None:
            self._hide_color_bar()
            return
        self._set_color_bar_levels(state.color_levels)
        self._color_bar.getAxis("left").setLabel(state.series_dim)
        self._show_color_bar()
        self._apply_series_colors()

    def _apply_offset_state(self, state: _OffsetRenderState) -> None:
        """Apply offset plotting metadata to the live plot."""
        self._curve.setData(state.flat_x, state.flat_y)
        self._curve.setPen(pg.mkPen(color=(15, 15, 15, 255), width=2))
        self._render_state = state
        self._plot_item.setTitle(state.title)
        self._axis_kinds = {
            "left": state.left_axis_kind,
            "bottom": state.bottom_axis_kind,
        }
        self._axis_dims = {"left": state.y_dim, "bottom": state.x_dim}
        ensure_axis_item(self._plot_item, "left", state.left_axis_kind)
        ensure_axis_item(self._plot_item, "bottom", state.bottom_axis_kind)

    @staticmethod
    def _default_series_color_levels(
        series_plot: np.ndarray,
    ) -> tuple[float, float] | None:
        """Return default colorbar limits for time-series line coloring."""
        values = np.asarray(series_plot, dtype=np.float64)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return None
        low = float(np.min(finite))
        high = float(np.max(finite))
        return (low, high)

    @classmethod
    def _resolve_series_color_levels(
        cls,
        *,
        series_plot: np.ndarray,
        color_limits: list[float] | tuple[float, float] | None,
        default_levels: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        """Resolve colorbar levels, discarding stale ranges outside the data."""
        if color_limits is None:
            return default_levels
        if len(color_limits) != 2:
            return default_levels
        low, high = sorted((float(color_limits[0]), float(color_limits[1])))
        if not np.isfinite([low, high]).all():
            return default_levels
        values = np.asarray(series_plot, dtype=np.float64)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return default_levels
        data_low = float(np.min(finite))
        data_high = float(np.max(finite))
        if high < data_low or low > data_high:
            return default_levels
        return (low, high)

    def _show_color_bar(self) -> None:
        """Show the time-series colorbar."""
        self._color_bar.show()

    def _hide_color_bar(self) -> None:
        """Hide the time-series colorbar."""
        self._color_bar.hide()

    def _all_line_curves(self) -> list[pg.PlotCurveItem]:
        """Return the currently active line curves in render order."""
        return [self._curve, *self._series_curves]

    @staticmethod
    def _series_pen_for_value(
        *, color, value: float, percentiles_enabled: bool
    ) -> pg.QtGui.QPen:
        """Return the styled pen for a rendered time-series line."""
        if percentiles_enabled and np.isfinite(value) and np.isclose(value, 50.0):
            return pg.mkPen(color=color, width=6, style=Qt.PenStyle.DotLine)
        return pg.mkPen(color=color, width=2)

    def _apply_series_colors(self) -> None:
        """Color active time-series lines from the series coordinate values."""
        state = self._render_state
        if (
            state is None
            or state.mode != "time series"
            or state.series_plot is None
            or state.series_plot.size == 0
        ):
            return

        levels = self._color_bar.levels()
        if levels is None:
            return
        low, high = levels
        span = high - low
        for curve, value in zip(
            self._all_line_curves(), state.series_plot, strict=False
        ):
            if not np.isfinite(value):
                color = pg.mkColor("k")
            elif span == 0:
                color = self._current_colormap.mapToQColor(0.5)
            else:
                fraction = float(np.clip((value - low) / span, 0.0, 1.0))
                color = self._current_colormap.mapToQColor(fraction)
            curve.setPen(
                self._series_pen_for_value(
                    color=color,
                    value=float(value),
                    percentiles_enabled=state.percentiles_enabled,
                )
            )

    def _on_view_range_changed(self, _view_box, _view_range) -> None:
        """Refresh datetime axis labels when zoom/pan changes."""
        self._refresh_axis_labels()

    def _on_plot_mouse_moved(self, event) -> None:
        """Update the cursor readout from the current mouse position."""
        if self._patch is None or self._render_state is None:
            self._set_cursor_readout(None)
            return
        scene_pos = event[0]
        if not self._plot_item.sceneBoundingRect().contains(scene_pos):
            self._set_cursor_readout(None)
            return
        view_pos = self._plot_item.vb.mapSceneToView(scene_pos)
        self._update_cursor_readout(
            plot_x=float(view_pos.x()),
            plot_y=float(view_pos.y()),
        )

    def _update_cursor_readout(self, *, plot_x: float, plot_y: float) -> None:
        """Show the plotted cursor position and nearest raw sample amplitude."""
        if self._patch is None or self._render_state is None:
            self._set_cursor_readout(None)
            return
        data = np.asarray(self._patch.data)
        if data.size == 0:
            self._set_cursor_readout(None)
            return

        if isinstance(self._render_state, _OffsetRenderState):
            self._update_offset_cursor_readout(data, plot_x=plot_x, plot_y=plot_y)
            return
        if data.ndim == 1:
            self._update_time_series_cursor_readout_1d(data, plot_x=plot_x)
            return
        if data.ndim == 2:
            self._update_time_series_cursor_readout_2d(
                data, plot_x=plot_x, plot_y=plot_y
            )
            return
        self._set_cursor_readout(None)

    def _update_offset_cursor_readout(
        self, data: np.ndarray, *, plot_x: float, plot_y: float
    ) -> None:
        """Show offset-mode cursor information."""
        state = self._render_state
        sample_index = nearest_axis_index(plot_x, state.x_plot)
        trace_offset_index = nearest_axis_index(plot_y, state.trace_offsets)
        trace_index = int(state.trace_indices[trace_offset_index])
        value = self._raw_trace_value(
            data,
            x_index=sample_index,
            trace_index=trace_index,
        )
        x_value = map_plot_value_to_coord(
            plot_x,
            state.x_plot,
            state.x_coord,
        )
        self._set_cursor_readout(
            [
                CursorField(state.x_dim, x_value),
                CursorField("y", plot_y),
                CursorField("value", value),
            ]
        )

    def _update_time_series_cursor_readout_1d(
        self, data: np.ndarray, *, plot_x: float
    ) -> None:
        """Show 1D time-series cursor information."""
        state = self._render_state
        sample_index = nearest_axis_index(plot_x, state.x_plot)
        x_value = map_plot_value_to_coord(
            plot_x,
            state.x_plot,
            state.x_coord,
        )
        self._set_cursor_readout(
            [
                CursorField(state.x_dim, x_value),
                CursorField("value", data[sample_index]),
            ]
        )

    def _update_time_series_cursor_readout_2d(
        self, data: np.ndarray, *, plot_x: float, plot_y: float
    ) -> None:
        """Show 2D time-series cursor information."""
        state = self._render_state
        if (
            state.line_values.shape[0] == 0
            or state.series_coord is None
            or len(state.series_coord) == 0
        ):
            self._set_cursor_readout(None)
            return
        sample_index = nearest_axis_index(plot_x, state.x_plot)
        x_value = map_plot_value_to_coord(plot_x, state.x_plot, state.x_coord)
        line_values = state.line_values[:, sample_index]
        series_offset_index = nearest_axis_index(plot_y, line_values)
        series_coord = state.series_coord[series_offset_index]
        self._set_cursor_readout(
            [
                CursorField(state.x_dim, x_value),
                CursorField(state.series_dim, series_coord),
            ]
        )

    def _set_cursor_readout(self, fields: list[CursorField] | None) -> None:
        """Update the footer text used for cursor inspection."""
        set_cursor_label_text(self._cursor_label, fields)

    def _raw_trace_value(self, data: np.ndarray, *, x_index: int, trace_index: int):
        """Return the raw patch amplitude nearest the cursor."""
        _dim0, dim1 = self._patch.dims
        if self.selected_trace_dim == dim1:
            # When dim1 is the trace dimension, each trace lives in
            # data[:, trace_index].
            return data[x_index, trace_index]
        return data[trace_index, x_index]

    def _update_gain_label(self) -> None:
        """Update the visible gain label text from the current setting."""
        self._gain_label.setText(f"{int(self.gain)}%")

    @classmethod
    def _normalize_gain(cls, gain: int | float) -> int:
        """Convert persisted gain to an integer percent with a 1% floor."""
        return int(max(round(float(gain)), cls._GAIN_MIN))

    def _emit_current_patch(self) -> None:
        """Emit the input patch when present, even if rendering reported an error."""
        if self._patch is None:
            self.Outputs.patch.send(None)
            return
        self.Outputs.patch.send(self._patch)

    def _clear_curves(self) -> None:
        """Clear all plotted trace data."""
        self._curve.setData([], [])
        self._curve.setPen(pg.mkPen(color=(15, 15, 15, 255), width=2))
        for curve in self._series_curves:
            self._plot_item.removeItem(curve)
        self._series_curves.clear()

    def _get_view_range(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return the current finite x/y plot ranges, if available."""
        x_range, y_range = self._plot_item.vb.viewRange()
        if not np.all(np.isfinite([*x_range, *y_range])):
            return None
        return tuple(x_range), tuple(y_range)

    def _refresh_axis_labels(self) -> None:
        """Update axis labels, adding datetime context when useful."""
        view_range = self._get_view_range()
        if view_range is None:
            left_label = self._axis_dims["left"]
            bottom_label = self._axis_dims["bottom"]
        else:
            bottom_label = format_axis_label(
                self._plot_item,
                "bottom",
                self._axis_dims["bottom"],
                self._axis_kinds["bottom"],
                tuple(view_range[0]),
            )
            left_label = format_axis_label(
                self._plot_item,
                "left",
                self._axis_dims["left"],
                self._axis_kinds["left"],
                tuple(view_range[1]),
            )
        self._plot_item.setLabel("left", left_label)
        self._plot_item.setLabel("bottom", bottom_label)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Wiggle).run()
