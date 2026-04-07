"""Shared multidimensional plot-dimension and slice controls for plot widgets."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from contextlib import contextmanager

import dascore as dc
import numpy as np
from AnyQt.QtCore import Qt, Signal
from AnyQt.QtGui import QColor, QFont, QPainter, QPalette
from AnyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def format_nd_coord_value(value) -> str:
    """Format one coordinate value for display in a slice slider."""
    if isinstance(value, np.datetime64):
        text = str(value)
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    if isinstance(value, datetime.timedelta | np.timedelta64):
        return str(value)[:20]
    if isinstance(value, np.floating | float):
        return f"{float(value):.4g}"
    if isinstance(value, np.integer | int):
        return str(int(value))
    return str(value)[:20]


class _CoordSlider(QSlider):
    """QSlider that draws the current coordinate value as centred overlay text."""

    def __init__(
        self,
        coord_values: np.ndarray,
        *,
        formatter: Callable[[object], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._coord_values = coord_values
        self._formatter = formatter

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        index = self.value()
        if not 0 <= index < len(self._coord_values):
            return
        text = self._formatter(self._coord_values[index])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(text)
        pad_x, pad_y = 6, 2
        box = text_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)
        box.moveCenter(self.rect().center())

        background = QColor(self.palette().color(QPalette.ColorRole.Window))
        background.setAlpha(180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(box, 3, 3)

        foreground = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        foreground.setAlpha(220)
        painter.setPen(foreground)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class _StepButton(QToolButton):
    """QToolButton whose commit signal only fires on physical mouse release."""

    commit_step = Signal()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.commit_step.emit()


@contextmanager
def _block_signals(*widgets):
    """Temporarily block Qt signals on one or more widgets."""
    for widget in widgets:
        widget.blockSignals(True)
    try:
        yield
    finally:
        for widget in widgets:
            widget.blockSignals(False)


class MultiDimPlotControlsMixin:
    """Shared plot-dim combos and slice controls for ND plotting widgets."""

    _patch: dc.Patch | None
    _dim_strip: QWidget
    _y_dim_combo: QComboBox
    _x_dim_combo: QComboBox
    _plot_y_dim: str | None
    _plot_x_dim: str | None
    _slice_dims: tuple[str, ...]
    _slice_indices: dict[str, int]
    _slice_sliders: dict[str, QSlider]

    def _init_nd_plot_controls_state(self) -> None:
        """Initialize shared ND control state."""
        self._plot_y_dim = None
        self._plot_x_dim = None
        self._slice_dims = ()
        self._slice_indices = {}
        self._slice_sliders = {}

    def _build_nd_plot_controls(self, parent: QWidget) -> QWidget:
        """Build the shared dim strip and return it."""
        self._init_nd_plot_controls_state()

        dim_strip = QWidget(parent)
        dim_strip.setVisible(False)
        strip_layout = QVBoxLayout(dim_strip)
        strip_layout.setContentsMargins(4, 2, 4, 2)
        strip_layout.setSpacing(4)

        axis_row = QWidget(dim_strip)
        axis_row_layout = QHBoxLayout(axis_row)
        axis_row_layout.setContentsMargins(0, 0, 0, 0)
        axis_row_layout.setSpacing(8)
        axis_row_layout.addStretch()
        axis_row_layout.addWidget(QLabel("Y:"))
        self._y_dim_combo = QComboBox(axis_row)
        self._y_dim_combo.setMinimumWidth(80)
        axis_row_layout.addWidget(self._y_dim_combo)
        axis_row_layout.addWidget(QLabel("X:"))
        self._x_dim_combo = QComboBox(axis_row)
        self._x_dim_combo.setMinimumWidth(80)
        axis_row_layout.addWidget(self._x_dim_combo)
        axis_row_layout.addStretch()
        strip_layout.addWidget(axis_row)

        self._dim_strip = dim_strip
        self._y_dim_combo.currentTextChanged.connect(self._on_nd_y_dim_changed)
        self._x_dim_combo.currentTextChanged.connect(self._on_nd_x_dim_changed)
        return dim_strip

    def _nd_default_plot_dims(self, dims: tuple[str, ...]) -> tuple[str, str]:
        """Return default plot dims for one patch."""
        if "distance" in dims and "time" in dims:
            return "distance", "time"
        return dims[0], dims[1]

    def _nd_coord_formatter(self, value) -> str:
        """Return one coordinate label string for shared slice sliders."""
        return format_nd_coord_value(value)

    def _nd_controls_are_applicable(self, patch: dc.Patch | None) -> bool:
        """Return True when a patch should use shared ND controls."""
        return patch is not None and np.asarray(patch.data).ndim > 2

    def _on_nd_plot_state_changed(self, *, kind: str) -> None:
        """Handle one plot-dim or slice-dim state change."""
        raise NotImplementedError

    def _refresh_nd_plot_controls(self, patch: dc.Patch | None) -> None:
        """Rebuild plot-dim combos and slice sliders for the current patch."""
        for slider in self._slice_sliders.values():
            slider.parentWidget().deleteLater()
        self._slice_sliders.clear()

        if not self._nd_controls_are_applicable(patch):
            self._dim_strip.setVisible(False)
            self._slice_dims = ()
            self._slice_indices = {}
            self._plot_y_dim = None
            self._plot_x_dim = None
            with _block_signals(self._y_dim_combo, self._x_dim_combo):
                self._y_dim_combo.clear()
                self._x_dim_combo.clear()
            return

        assert patch is not None
        with _block_signals(self._y_dim_combo, self._x_dim_combo):
            self._y_dim_combo.clear()
            self._x_dim_combo.clear()
            for dim in patch.dims:
                self._y_dim_combo.addItem(dim)
                self._x_dim_combo.addItem(dim)

        default_y, default_x = self._nd_default_plot_dims(tuple(patch.dims))
        y_dim = self._plot_y_dim if self._plot_y_dim in patch.dims else default_y
        x_dim = self._plot_x_dim if self._plot_x_dim in patch.dims else default_x
        if y_dim == x_dim:
            x_dim = next(dim for dim in patch.dims if dim != y_dim)

        with _block_signals(self._y_dim_combo, self._x_dim_combo):
            self._y_dim_combo.setCurrentText(y_dim)
            self._x_dim_combo.setCurrentText(x_dim)
        self._plot_y_dim = y_dim
        self._plot_x_dim = x_dim

        slice_dims = tuple(dim for dim in patch.dims if dim not in {y_dim, x_dim})
        self._slice_dims = slice_dims

        strip_layout = self._dim_strip.layout()
        assert strip_layout is not None
        for dim in slice_dims:
            size = np.asarray(patch.data).shape[patch.dims.index(dim)]
            index = min(self._slice_indices.get(dim, 0), size - 1)
            self._slice_indices[dim] = index
            if size <= 1:
                continue

            row = QWidget(self._dim_strip)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            coord_values = np.asarray(patch.get_array(dim))
            label = QLabel(f"{dim}:", row)
            slider = _CoordSlider(
                coord_values,
                formatter=self._nd_coord_formatter,
                parent=row,
            )
            slider.setRange(0, size - 1)
            slider.setValue(index)

            button_style = "border: none; background: transparent;"
            btn_prev = _StepButton(row)
            btn_prev.setText("◀")
            btn_prev.setStyleSheet(button_style)
            btn_prev.setAutoRepeat(True)
            btn_prev.setAutoRepeatDelay(400)
            btn_prev.setAutoRepeatInterval(80)
            btn_prev.setToolTip(f"Step {dim} back one index (hold to advance)")

            btn_next = _StepButton(row)
            btn_next.setText("▶")
            btn_next.setStyleSheet(button_style)
            btn_next.setAutoRepeat(True)
            btn_next.setAutoRepeatDelay(400)
            btn_next.setAutoRepeatInterval(80)
            btn_next.setToolTip(f"Step {dim} forward one index (hold to advance)")

            slider.setToolTip(
                f"Drag to select a {dim} index\n"
                f"Scroll wheel or arrow keys also work"
            )

            row_layout.addWidget(label)
            row_layout.addWidget(btn_prev)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(btn_next)
            strip_layout.addWidget(row)

            def _on_drag(value, *, slice_dim=dim, active_slider=slider):
                active_slider.update()
                if active_slider.isSliderDown():
                    return
                self._slice_indices[slice_dim] = value
                self._on_nd_plot_state_changed(kind="slice")

            def _on_release(*, slice_dim=dim, active_slider=slider):
                self._slice_indices[slice_dim] = active_slider.value()
                self._on_nd_plot_state_changed(kind="slice")

            def _btn_step(delta, *, active_slider=slider):
                active_slider.blockSignals(True)
                active_slider.setValue(active_slider.value() + delta)
                active_slider.blockSignals(False)
                active_slider.update()

            btn_prev.clicked.connect(
                lambda checked=False, step=-1, fn=_btn_step: fn(step)
            )
            btn_next.clicked.connect(
                lambda checked=False, step=1, fn=_btn_step: fn(step)
            )
            btn_prev.commit_step.connect(_on_release)
            btn_next.commit_step.connect(_on_release)

            slider.valueChanged.connect(_on_drag)
            slider.sliderReleased.connect(_on_release)
            self._slice_sliders[dim] = slider

        self._dim_strip.setVisible(True)

    def _on_nd_y_dim_changed(self, dim: str) -> None:
        """Handle one Y-axis plot-dim change."""
        if self._patch is None or not dim:
            return
        if dim == self._plot_x_dim:
            with _block_signals(self._x_dim_combo):
                self._x_dim_combo.setCurrentText(self._plot_y_dim)
            self._plot_x_dim = self._plot_y_dim
        self._plot_y_dim = dim
        self._refresh_nd_plot_controls(self._patch)
        self._on_nd_plot_state_changed(kind="plot_dims")

    def _on_nd_x_dim_changed(self, dim: str) -> None:
        """Handle one X-axis plot-dim change."""
        if self._patch is None or not dim:
            return
        if dim == self._plot_y_dim:
            with _block_signals(self._y_dim_combo):
                self._y_dim_combo.setCurrentText(self._plot_x_dim)
            self._plot_y_dim = self._plot_x_dim
        self._plot_x_dim = dim
        self._refresh_nd_plot_controls(self._patch)
        self._on_nd_plot_state_changed(kind="plot_dims")

    def _apply_nd_slice_dims(self, patch: dc.Patch) -> dc.Patch:
        """Select one index along each active slice dimension."""
        for dim in self._slice_dims:
            if dim not in patch.dims:
                continue
            coord_values = patch.get_array(dim)
            index = min(self._slice_indices.get(dim, 0), len(coord_values) - 1)
            patch = patch.select(**{dim: np.array([coord_values[index]])}).squeeze(dim)
        return patch

    def _nd_display_patch(self, patch: dc.Patch | None) -> dc.Patch | None:
        """Return the current patch reduced to the selected plot dimensions."""
        if patch is None:
            return None
        if not self._nd_controls_are_applicable(patch):
            return patch
        patch = self._apply_nd_slice_dims(patch)
        if (
            self._plot_y_dim
            and self._plot_x_dim
            and patch.dims != (self._plot_y_dim, self._plot_x_dim)
        ):
            patch = patch.transpose(self._plot_y_dim, self._plot_x_dim)
        return patch
