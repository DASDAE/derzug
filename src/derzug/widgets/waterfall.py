"""
Interactive pyqtgraph waterfall widget for DASCore patches.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import dascore as dc
import numpy as np
import pyqtgraph as pg
from AnyQt.QtCore import QRectF, Qt, QTimer, Signal
from AnyQt.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPalette
from AnyQt.QtWidgets import (
    QAction,
    QComboBox,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMenuBar,
    QPushButton,
    QShortcut,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from dascore.viz.waterfall import _get_scale as get_dascore_waterfall_scale
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.orange import Setting
from derzug.utils.plot_axes import (
    CursorField,
    build_plot_axis_spec,
    ensure_axis_item,
    format_axis_label,
    map_coord_to_plot_value,
    map_plot_value_to_coord,
    nearest_axis_index,
    set_cursor_label_text,
)
from derzug.widgets.annotation_editor import (
    AnnotationEditorDialog as _AnnotationEditorDialog,
)
from derzug.widgets.annotation_overlay import AnnotationOverlayController
from derzug.widgets.ndim_controls import (
    MultiDimPlotControlsMixin,
    format_nd_coord_value,
)
from derzug.widgets.selection import (
    SelectionControlsMixin,
)
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchPassThroughTask, PatchSelectionTask

_ANNOTATION_ICON_DIR = Path(__file__).resolve().parent / "icons" / "annotations"


@dataclass
class _AxisState:
    """Axis metadata computed from the current patch; None when no patch is loaded."""

    x_dim: str
    y_dim: str
    x_plot: np.ndarray  # numeric axis values for pyqtgraph display
    y_plot: np.ndarray
    x_coord: np.ndarray  # original coordinate values used by patch.select
    y_coord: np.ndarray


@dataclass
class _PreparedPatchRender:
    """Cached render-time arrays for the current patch."""

    data: np.ndarray
    display_data: np.ndarray
    axes: _AxisState


def _format_coord_value(val) -> str:
    """Format a single coordinate value for display inside a slider."""
    return format_nd_coord_value(val)


class _CoordSlider(QSlider):
    """QSlider that draws the current coordinate value as subtle centred text."""

    def __init__(self, coord_values: np.ndarray, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._coord_values = coord_values

    def paintEvent(self, event):
        super().paintEvent(event)
        idx = self.value()
        if 0 <= idx < len(self._coord_values):
            text = _format_coord_value(self._coord_values[idx])
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            painter.setFont(font)

            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(text)
            pad_x, pad_y = 6, 2
            box = text_rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)
            box.moveCenter(self.rect().center())

            bg = QColor(self.palette().color(QPalette.ColorRole.Window))
            bg.setAlpha(180)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(box, 3, 3)

            fg = QColor(self.palette().color(QPalette.ColorRole.WindowText))
            fg.setAlpha(220)
            painter.setPen(fg)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            painter.end()


class _StepButton(QToolButton):
    """QToolButton whose commit_step signal fires only on physical mouse release.

    Qt's autoRepeat fires released() on every repeat interval, making it
    unsuitable for "render once on button-up". Overriding mouseReleaseEvent
    gives the physical-only event needed to commit a single render.
    """

    commit_step = Signal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.commit_step.emit()


@contextmanager
def _block_signals(*widgets):
    """Temporarily block Qt signals on one or more widgets."""
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)


def _default_plot_dims(dims: tuple[str, ...]) -> tuple[str, str]:
    """Return (y_dim, x_dim) defaults: distance x time if present, else first two."""
    if "distance" in dims and "time" in dims:
        return "distance", "time"
    return dims[0], dims[1]


class _SelectionROI(pg.ROI):
    """ROI that can delete itself via keyboard when focused."""

    def __init__(self, *args, on_delete, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._on_delete = on_delete
        self._interactive = True
        self._brush = pg.mkBrush(255, 255, 255, 110)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def set_interactive(self, interactive: bool) -> None:
        """Keep the ROI visible while enabling only active-mode manipulation."""
        self._interactive = interactive
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.translatable = interactive
        self.resizable = interactive
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, interactive)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, interactive)
        if not interactive:
            self.clearFocus()
            self.setSelected(False)
        self._brush = (
            pg.mkBrush(255, 255, 255, 110)
            if interactive
            else pg.mkBrush(255, 255, 255, 70)
        )
        self.setPen(
            pg.mkPen((0, 0, 0), width=3, style=Qt.PenStyle.DashLine)
            if interactive
            else pg.mkPen((0, 0, 0, 180), width=2, style=Qt.PenStyle.DashLine)
        )
        for handle in self.getHandles():
            handle.setVisible(interactive)
            handle.setAcceptedMouseButtons(
                Qt.MouseButton.LeftButton if interactive else Qt.MouseButton.NoButton
            )

    def paint(self, painter, *args) -> None:
        """Draw the ROI with a white fill and dashed black outline."""
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(self.currentPen)
        painter.setBrush(self._brush)
        painter.drawRect(self.boundingRect())

    def hoverEvent(self, ev) -> None:
        """Accept hover for dragging without switching to a hover color."""
        hover = False
        if not ev.isExit():
            if self.translatable and ev.acceptDrags(Qt.MouseButton.LeftButton):
                hover = True
            for btn in (
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.RightButton,
                Qt.MouseButton.MiddleButton,
            ):
                if (self.acceptedMouseButtons() & btn) and ev.acceptClicks(btn):
                    hover = True
        self.setMouseHover(False)
        if hover:
            ev.acceptClicks(Qt.MouseButton.LeftButton)
            ev.acceptClicks(Qt.MouseButton.RightButton)
            ev.acceptClicks(Qt.MouseButton.MiddleButton)
            self.sigHoverEvent.emit(self)

    def mouseClickEvent(self, ev) -> None:
        """Take focus when clicked so Delete/Backspace can target the ROI."""
        if not self._interactive:
            ev.ignore()
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setSelected(True)
            self.setFocus()
            if self.scene() is not None:
                self.scene().setFocusItem(self)
            ev.accept()
            return
        super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev) -> None:
        """Allow center dragging only while the ROI is interactive."""
        if not self._interactive:
            ev.ignore()
            return
        self.setSelected(True)
        self.setFocus()
        if self.scene() is not None:
            self.scene().setFocusItem(self)
        super().mouseDragEvent(ev)

    def keyPressEvent(self, ev) -> None:
        """Delete the ROI when focused and Delete/Backspace is pressed."""
        if not self._interactive:
            ev.ignore()
            return
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._on_delete()
            ev.accept()
            return
        super().keyPressEvent(ev)


class _WaterfallViewBox(pg.ViewBox):
    """ViewBox that keeps middle-drag panning even in rectangle-zoom mode."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._middle_drag_restore_mode: int | None = None

    def mouseDragEvent(self, ev, axis=None) -> None:
        """Translate middle-button drags instead of drawing a rubber-band box."""
        if ev.button() != Qt.MouseButton.MiddleButton:
            super().mouseDragEvent(ev, axis=axis)
            return
        if self._middle_drag_restore_mode is None:
            self._middle_drag_restore_mode = self.state["mouseMode"]
            self.state["mouseMode"] = pg.ViewBox.PanMode
        try:
            super().mouseDragEvent(ev, axis=axis)
        finally:
            if ev.isFinish():
                restore_mode = self._middle_drag_restore_mode
                self._middle_drag_restore_mode = None
                if restore_mode is not None:
                    self.state["mouseMode"] = restore_mode


class Waterfall(SelectionControlsMixin, MultiDimPlotControlsMixin, ZugWidget):
    """
    Display a 2D DAS patch as an interactive pyqtgraph waterfall image.

    The widget passes incoming patches through unchanged on output, while
    rendering the input in the main area. A dropdown in the control area lets
    users change the colormap interactively.
    """

    name = "Waterfall"
    description = "Interactive pyqtgraph waterfall view for DAS patches"
    icon = "icons/Waterfall.svg"
    category = "Visualize"
    keywords = ("waterfall", "patch", "pyqtgraph", "dascore")
    priority = 20

    _COLORMAPS: ClassVar[tuple[str, ...]] = (
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
    colormap = Setting(_COLORMAPS[0])
    color_limits = Setting(None)
    reset_on_new = Setting(True)
    # Keep selection state inside saved workflows only; do not promote it to
    # future widget defaults.
    saved_selection_basis = Setting("", schema_only=True)
    saved_selection_ranges = Setting([], schema_only=True)
    saved_selection_has_roi = Setting(None, schema_only=True)
    saved_annotation_set = Setting(None, schema_only=True)
    saved_view_range = Setting(None, schema_only=True)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("Could not render patch: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        unknown_colormap = Msg("Unknown colormap '{}'; falling back to viridis")
        empty_selection = Msg(
            "Selection does not overlap the current patch; emitting an empty patch"
        )
        line_fit_requires_points = Msg(
            "Select at least two point annotations to fit a line"
        )
        line_fit_failed = Msg("Could not fit a line from the selected points")
        square_fit_requires_points = Msg(
            "Select at least two point annotations to fit a square"
        )
        ellipse_fit_requires_points = Msg(
            "Select at least three point annotations to fit an ellipse"
        )
        ellipse_fit_failed = Msg("Could not fit an ellipse from the selected points")
        hyperbola_fit_requires_points = Msg(
            "Select at least three point annotations to fit a hyperbola"
        )
        hyperbola_fit_failed = Msg("Could not fit a hyperbola from the selected points")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)
        annotation_set = Input("Annotations", AnnotationSet)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)
        annotation_set = Output("Annotations", AnnotationSet)

    def get_task(self) -> Task:
        """Return the compiled patch-only semantics for the current widget state."""
        self._sync_settings_from_controls()
        payload = self._load_saved_selection_state()
        if payload is None:
            return PatchPassThroughTask()
        return PatchSelectionTask(selection_payload=payload)

    def _apply_settings_to_controls(self) -> None:
        """Hydrate visible controls from persisted widget settings."""
        if self.colormap not in self._COLORMAPS:
            self.colormap = self._COLORMAPS[0]
        self._set_combo_value(self._cmap_combo, self.colormap)
        self._set_checkbox_value(self._reset_on_new_checkbox, self.reset_on_new)

    def _sync_settings_from_controls(self) -> None:
        """Persist visible controls and saved view/selection state."""
        self.colormap = self._cmap_combo.currentText().strip() or self._COLORMAPS[0]
        self.reset_on_new = bool(self._reset_on_new_checkbox.isChecked())
        self._persist_selection_settings()
        self._persist_annotation_settings()
        self._persist_view_range_settings()

    def _rebind_dynamic_controls(self) -> None:
        """Rebuild patch-dependent axis and slice controls from the current patch."""
        self._rebuild_slice_panel(self._patch)
        self._update_axis_state_from_patch(self._patch)

    def widget_shortcuts(self) -> list[tuple[str, str]]:
        """Return Waterfall-specific keyboard and pointer shortcuts."""
        return [
            ("A", "Show or hide the annotation toolbox"),
            ("Esc", "Clear selection or annotation-select focus"),
            ("Shift+Left Click", "Place a point annotation"),
            ("E", "Fit an ellipse from the selected point annotations"),
            ("H", "Fit a hyperbola from the selected point annotations"),
            ("1-9", "Assign selected annotations to label slots"),
            ("0", "Clear label assignment from selected annotations"),
        ]

    def __init__(self) -> None:
        super().__init__()
        self._init_selection_controls()
        self._restore_saved_roi_after_render = False
        self._pending_saved_selection_restore = False
        self._pending_saved_selection_has_roi: bool | None = None
        self._prime_saved_selection_state()
        self._pending_saved_annotation_set = self._load_saved_annotation_state()
        self._pending_saved_view_range = self._load_saved_view_range()
        self._patch: dc.Patch | None = None
        self._init_nd_plot_controls_state()
        self._prepared_render: _PreparedPatchRender | None = None
        self._pending_view_range: (
            tuple[tuple[float, float], tuple[float, float]] | None
        ) = None
        self._force_preserve_pending_view_range = False
        self._colormap_dirty = False
        self._roi: pg.ROI | None = None
        # All axis metadata in one place; None when no patch is loaded.
        self._axes: _AxisState | None = None
        self._ignore_level_changes = 0
        self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
        self._overlay_mode = "select"

        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Colormap:")
        self._cmap_combo = QComboBox(box)
        self._cmap_combo.addItems(self._COLORMAPS)
        box.layout().addWidget(self._cmap_combo)
        self._reset_on_new_checkbox = gui.checkBox(
            box,
            self,
            "reset_on_new",
            "reset on new",
        )
        self._reset_on_new_checkbox.setToolTip(
            "reset plot and color bar extents when receiving a new patch"
        )

        self._build_selection_panel(box)
        self._add_selection_button = QToolButton(box)
        self._add_selection_button.setCheckable(True)
        self._add_selection_button.setFixedSize(28, 28)
        self._add_selection_button.setIcon(
            QIcon(str(_ANNOTATION_ICON_DIR / "select.svg"))
        )
        self._add_selection_button.setToolTip(
            "Place a selection ROI in the current view"
        )
        selection_layout = self._selection_panel.layout()
        reset_index = selection_layout.indexOf(self._selection_panel.reset_button)
        selection_layout.removeWidget(self._selection_panel.reset_button)
        button_row = QWidget(self._selection_panel)
        button_row_layout = QHBoxLayout(button_row)
        button_row_layout.setContentsMargins(0, 0, 0, 0)
        button_row_layout.setSpacing(6)
        button_row_layout.addWidget(self._selection_panel.reset_button)
        button_row_layout.addWidget(self._add_selection_button)
        selection_layout.insertWidget(reset_index, button_row)
        self._selection_button_row = button_row

        ann_box = gui.widgetBox(self.controlArea, "Annotations")
        self._open_annotations_button = QPushButton("Open Annotations (A)", ann_box)
        self._open_annotations_button.setCheckable(True)
        self._open_annotations_button.setToolTip("Show/hide the annotation toolbox (A)")
        self._open_annotations_button.setChecked(False)
        ann_box.layout().addWidget(self._open_annotations_button)

        self._plot_widget = pg.PlotWidget(
            self.mainArea,
            viewBox=_WaterfallViewBox(),
        )
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._plot_item.addItem(self._image_item)
        self._plot_item.setLabel("left", "Dim 0")
        self._plot_item.setLabel("bottom", "Dim 1")
        self._hist_lut = pg.HistogramLUTWidget(self.mainArea)
        self._hist_lut.setImageItem(self._image_item)
        self._hist_lut.item.sigLevelsChanged.connect(self._on_levels_changed)
        self._hist_lut.item.vb.menu.viewAll.triggered.connect(
            self._reset_histogram_levels_to_default
        )
        self._cursor_label = QLabel("Cursor: --", self.mainArea)
        self._cursor_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Main container: plot panel on top, dim-selector strip on bottom.
        main_container = QWidget(self.mainArea)
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        plot_panel = QWidget(main_container)
        panel_layout = QVBoxLayout(plot_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        plot_row = QWidget(plot_panel)
        row_layout = QHBoxLayout(plot_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(self._plot_widget, 1)
        row_layout.addWidget(self._hist_lut, 0)
        panel_layout.addWidget(plot_row)
        panel_layout.addWidget(self._cursor_label)
        main_layout.addWidget(plot_panel, 1)

        main_layout.addWidget(self._build_nd_plot_controls(main_container), 0)

        self.mainArea.layout().addWidget(main_container)

        self._annotation_controller = AnnotationOverlayController(
            self,
            tools=(
                "annotation_select",
                "point",
                "line",
                "box",
                "ellipse",
                "hyperbola",
            ),
            default_tool=None,
            on_tool_changed=self._on_overlay_tool_changed,
            on_annotation_set_changed=self._on_local_annotation_set_changed,
        )
        self._annotation_controller._editor_class = _AnnotationEditorDialog

        self._cmap_combo.currentTextChanged.connect(self._on_colormap_changed)
        self._add_selection_button.clicked.connect(self._add_selection_from_view)
        self._open_annotations_button.toggled.connect(self._toggle_annotation_toolbox)
        self._plot_widget.scene().sigMouseClicked.connect(self._on_plot_mouse_clicked)
        self._plot_widget.scene().installEventFilter(self)
        self._mouse_proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_plot_mouse_moved,
        )
        self._plot_item.vb.menu.viewAll.triggered.connect(self._delete_active_roi)
        self._plot_item.vb.sigRangeChanged.connect(self._on_view_range_changed)
        self._apply_settings_to_controls()
        self._apply_colormap(self.colormap)
        self._set_overlay_mode("select")
        self._install_view_menu_actions()
        self._install_delete_shortcuts()
        self._open_annotations_button.setChecked(not self._annotation_toolbox_hidden)
        self._toggle_annotations_action.setChecked(not self._annotation_toolbox_hidden)

    def eventFilter(self, obj, event) -> bool:
        """Handle floating toolbox placement and annotation draw gestures."""
        if self._annotation_controller.handle_event_filter(obj, event):
            return True
        if obj is self._plot_widget.scene():
            return False
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """Delete active annotations or cancel in-progress draws."""
        if self._handle_widget_key_press(event):
            return
        super().keyPressEvent(event)

    def _handle_escape(self) -> None:
        """Cancel Waterfall interactions and clear active annotation selection mode."""
        clear_annotation_select = (
            self._annotation_controller.in_annotation_selection_mode()
        )
        self._cancel_active_interactions()
        if clear_annotation_select:
            self._annotation_controller.clear_active_tool(notify=False)
            self._sync_overlay_mode_from_annotation_tool()
        self._restore_window_focus()

    def _handle_widget_key_press(self, event) -> bool:
        """Handle Waterfall-specific keys from either the widget or plot viewport."""
        if event.key() == Qt.Key_A:
            self._toggle_annotation_toolbox(self._annotation_toolbox_hidden)
            event.accept()
            return True
        if event.key() == Qt.Key_Escape:
            self._handle_escape()
            event.accept()
            return True
        if self._annotation_controller.handle_key_press(event):
            if event.key() in (
                Qt.Key_0,
                Qt.Key_1,
                Qt.Key_2,
                Qt.Key_3,
                Qt.Key_4,
                Qt.Key_5,
                Qt.Key_6,
                Qt.Key_7,
                Qt.Key_8,
                Qt.Key_9,
                Qt.Key_E,
                Qt.Key_H,
                Qt.Key_Delete,
                Qt.Key_Backspace,
            ):
                self._mark_output_dirty("annotation_set")
            return True
        if (
            self._overlay_mode == "select"
            and self._roi is not None
            and event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
        ):
            self._delete_active_roi()
            event.accept()
            return True
        return False

    def _install_delete_shortcuts(self) -> None:
        """Catch Delete/Backspace even when the focused child is the plot viewport."""
        self._delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self._delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._delete_shortcut.activated.connect(self._on_delete_shortcut)
        self._backspace_shortcut = QShortcut(QKeySequence(Qt.Key_Backspace), self)
        self._backspace_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._backspace_shortcut.activated.connect(self._on_delete_shortcut)

    def _on_delete_shortcut(self) -> None:
        """Remove the active selection ROI from a child-focus shortcut."""
        if self._annotation_controller.interactive:
            active_annotation_id = self._annotation_controller.active_annotation_id
            selected_annotation_ids = set(
                self._annotation_controller.selected_annotation_ids
            )
            if active_annotation_id is not None:
                self._annotation_controller.delete_annotation(active_annotation_id)
                self._mark_output_dirty("annotation_set")
                return
            if selected_annotation_ids:
                for annotation_id in tuple(selected_annotation_ids):
                    self._annotation_controller.delete_annotation(annotation_id)
                self._mark_output_dirty("annotation_set")
                return
        if self._overlay_mode == "select" and self._roi is not None:
            self._delete_active_roi()

    def _deactivate_selection_roi(self) -> None:
        """Clear ROI focus and restore the default mode for toolbox visibility."""
        if self._roi is not None:
            self._roi.clearFocus()
            self._roi.setSelected(False)
            scene = self._plot_widget.scene()
            if scene is not None and scene.focusItem() is self._roi:
                scene.setFocusItem(None)
        self._restore_default_interaction_mode()

    def _cancel_active_interactions(self) -> None:
        """Cancel active annotation draws and selection-focused overlay state."""
        if self._annotation_controller.draw_start is not None:
            self._annotation_controller.cancel_draw()
        if self._annotation_controller.selected_annotation_ids:
            self._annotation_controller.set_selected_annotations(set())
        self._deactivate_selection_roi()

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch, render it, and emit the current selection."""
        should_reset_on_new = (
            self.reset_on_new
            and patch is not None
            and self._patch is not None
            and self._should_reset_view_for_new_patch(self._patch, patch)
        )
        self._pending_view_range = (
            None if should_reset_on_new else self._get_view_range()
        )
        if (
            not should_reset_on_new
            and self._patch is None
            and self._pending_saved_view_range is not None
        ):
            self._pending_view_range = self._pending_saved_view_range
            self._force_preserve_pending_view_range = True
        if should_reset_on_new:
            self.color_limits = None
        had_active_selection = self._has_active_narrowed_selection()
        previous_patch_basis = self._selection_patch_basis
        previous_patch_ranges = {
            dim: self._selection_current_patch_range(dim)
            for dim in tuple(self._selection_state.patch.ranges)
        }
        self._patch = patch
        self._rebind_dynamic_controls()
        prepared = self._prepared_render
        if prepared is not None:
            x_dim = prepared.axes.x_dim
            y_dim = prepared.axes.y_dim
            self._selection_set_preferred_patch_dims((x_dim, y_dim))
        else:
            self._selection_set_preferred_patch_dims(())
        self._selection_set_patch_source(patch, notify=False, refresh_ui=False)
        self._restore_absolute_selection_ranges(
            patch,
            had_active_selection=had_active_selection,
            previous_basis=previous_patch_basis,
            previous_ranges=previous_patch_ranges,
        )
        self._restore_saved_roi_after_render = patch is not None
        self._apply_pending_saved_selection_restore(patch)
        if patch is None:
            self._clear_annotations(emit=True)
        else:
            self._ensure_annotation_set()
            self._apply_pending_saved_annotation_restore()
            self._emit_annotation_set()
        self._persist_selection_settings()
        self._request_ui_refresh()
        self._emit_current_selection()

    @Inputs.annotation_set
    def set_annotation_set(self, annotation_set: AnnotationSet | None) -> None:
        """Receive an annotation set and render it when it matches current axes."""
        if (
            annotation_set is not None
            and self._axes is not None
            and set(annotation_set.dims)
            != set(self._annotation_controller.annotation_dims() or ())
        ):
            self._annotation_set = None
            self._rebuild_annotation_items()
            self._clear_output_dirty("annotation_set")
            return
        self._annotation_set = annotation_set
        self._active_annotation_id = None
        self._rebuild_annotation_items()
        self._clear_output_dirty("annotation_set")
        self._persist_annotation_settings()

    def _rebuild_slice_panel(self, patch: dc.Patch | None) -> None:
        """Rebuild dim-axis combos and slice sliders in the bottom strip."""
        self._refresh_nd_plot_controls(patch)
        self._update_annotation_slice_coords()

    def _on_y_dim_changed(self, dim: str) -> None:
        """Handle Y-axis dim combo change; auto-swap X if collision."""
        self._on_nd_y_dim_changed(dim)

    def _on_x_dim_changed(self, dim: str) -> None:
        """Handle X-axis dim combo change; auto-swap Y if collision."""
        self._on_nd_x_dim_changed(dim)

    def _on_nd_plot_state_changed(self, *, kind: str) -> None:
        """Refresh Waterfall state after shared ND controls change."""
        self._annotation_controller.active_annotation_id = None
        self._annotation_controller.selected_annotation_ids.clear()
        self._update_annotation_slice_coords()
        self._update_axis_state_from_patch(self._patch)
        if kind == "slice":
            self._pending_view_range = self._get_view_range()
        self._request_ui_refresh()

    def _update_annotation_slice_coords(self) -> None:
        """Push current slice position into the annotation controller."""
        if self._patch is None or not self._slice_dims:
            self._annotation_controller.slice_coords = {}
            return
        coords = {}
        for dim in self._slice_dims:
            idx = self._slice_indices.get(dim, 0)
            coords[dim] = self._patch.get_array(dim)[idx]
        self._annotation_controller.slice_coords = coords

    def _apply_slice_dims(self, patch: dc.Patch) -> dc.Patch:
        """Select a single index along each slice dimension to produce a 2D patch."""
        return self._apply_nd_slice_dims(patch)

    def _update_axis_state_from_patch(self, patch: dc.Patch | None) -> None:
        """Precompute axis metadata without forcing an immediate render."""
        if patch is None:
            self._prepared_render = None
            self._axes = None
            self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
            return

        try:
            patch = self._nd_display_patch(patch)
            assert patch is not None
            data = np.asarray(patch.data)
            if data.ndim != 2:
                raise ValueError(f"expected 2D data, got shape {data.shape}")
            display_data = np.abs(data) if np.iscomplexobj(data) else data
            y_dim, x_dim = patch.dims
            x_coord_values = np.asarray(patch.get_array(x_dim))
            y_coord_values = np.asarray(patch.get_array(y_dim))
            x_axis = build_plot_axis_spec(x_coord_values)
            y_axis = build_plot_axis_spec(y_coord_values)
            axes = _AxisState(
                x_dim=x_dim,
                y_dim=y_dim,
                x_plot=x_axis.plot_values,
                y_plot=y_axis.plot_values,
                x_coord=x_coord_values,
                y_coord=y_coord_values,
            )
            self._prepared_render = _PreparedPatchRender(
                data=data,
                display_data=display_data,
                axes=axes,
            )
            self._axes = axes
            self._axis_kinds = {"bottom": x_axis.kind, "left": y_axis.kind}
        except Exception:
            self._prepared_render = None
            self._axes = None
            self._axis_kinds = {"bottom": "numeric", "left": "numeric"}

    @property
    def _annotation_tool(self) -> str | None:
        """Compatibility shim for tests and host access."""
        return self._annotation_controller.tool

    @_annotation_tool.setter
    def _annotation_tool(self, value: str | None) -> None:
        if value in {"select", None}:
            self._toggle_annotation_toolbox(False)
            return
        if value == "annotation_select":
            self._toggle_annotation_toolbox(True)
            self._annotation_controller.enter_annotation_selection_mode(notify=False)
            self._sync_overlay_mode_from_annotation_tool()
            return
        self._toggle_annotation_toolbox(True)
        self._annotation_controller.set_tool(value)
        self._sync_overlay_mode_from_annotation_tool()

    @property
    def _annotation_layer_active(self) -> bool:
        return self._annotation_controller.layer_active

    @_annotation_layer_active.setter
    def _annotation_layer_active(self, value: bool) -> None:
        self._toggle_annotation_toolbox(value)

    @property
    def _annotation_toolbox_hidden(self) -> bool:
        return self._annotation_controller.toolbox_hidden

    @property
    def _annotation_toolbox(self):
        return self._annotation_controller.toolbox

    @property
    def _annotation_set(self) -> AnnotationSet | None:
        return self._annotation_controller.annotation_set

    @_annotation_set.setter
    def _annotation_set(self, value: AnnotationSet | None) -> None:
        self._annotation_controller.annotation_set = value

    @property
    def _annotation_items(self) -> dict[str, pg.ROI]:
        return self._annotation_controller.annotation_items

    @property
    def _active_annotation_id(self) -> str | None:
        return self._annotation_controller.active_annotation_id

    @_active_annotation_id.setter
    def _active_annotation_id(self, value: str | None) -> None:
        self._annotation_controller.active_annotation_id = value

    def _ensure_annotation_set(self) -> None:
        self._annotation_controller.ensure_annotation_set()

    def _clear_annotations(self, *, emit: bool = True) -> None:
        self._annotation_controller.clear_annotations()
        if emit:
            self._emit_annotation_set()
        else:
            self._clear_output_dirty("annotation_set")
            self._sync_annotation_toolbox_dirty_state()
        self._persist_annotation_settings()

    def _emit_annotation_set(self) -> None:
        self.Outputs.annotation_set.send(self._annotation_controller.annotation_set)
        self._clear_output_dirty("annotation_set")
        self._sync_annotation_toolbox_dirty_state()

    def _delayed_output_names(self) -> tuple[str, ...]:
        """Return the delayed outputs for Waterfall."""
        return ("annotation_set",)

    def _flush_delayed_output(self, name: str) -> bool:
        """Flush one delayed Waterfall output by name."""
        if name != "annotation_set":
            return False
        self._emit_annotation_set()
        return True

    def _mark_output_dirty(self, name: str) -> None:
        """Mark one delayed output dirty and update the toolbox title."""
        super()._mark_output_dirty(name)
        if name == "annotation_set":
            self._sync_annotation_toolbox_dirty_state()
            self._persist_annotation_settings()

    def _clear_output_dirty(self, name: str) -> None:
        """Clear one delayed output dirty flag and update the toolbox title."""
        super()._clear_output_dirty(name)
        if name == "annotation_set":
            self._sync_annotation_toolbox_dirty_state()
            self._persist_annotation_settings()

    def _sync_annotation_toolbox_dirty_state(self) -> None:
        """Mirror unsent annotation state into the toolbox title."""
        controller = getattr(self, "_annotation_controller", None)
        if controller is None:
            return
        self._annotation_toolbox.set_dirty(self._is_output_dirty("annotation_set"))

    def _rebuild_annotation_items(self) -> None:
        self._annotation_controller.rebuild_items()

    def _annotation_by_id(self, annotation_id: str) -> Annotation | None:
        return self._annotation_controller.annotation_by_id(annotation_id)

    def _on_local_annotation_set_changed(self) -> None:
        """Record local overlay mutations as unsent Waterfall annotation changes."""
        self._mark_output_dirty("annotation_set")
        QTimer.singleShot(0, self._restore_window_focus)

    def _delete_annotation(self, annotation_id: str) -> None:
        self._annotation_controller.delete_annotation(annotation_id)

    def _create_point_annotation(self, plot_x: float, plot_y: float) -> None:
        self._activate_annotation_layer()
        self._annotation_controller.create_point_annotation(plot_x, plot_y)

    def _create_box_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        self._activate_annotation_layer()
        self._annotation_controller.create_box_annotation(start, end)

    def _create_line_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        self._activate_annotation_layer()
        self._annotation_controller.create_line_annotation(start, end)

    def _set_active_annotation(self, annotation_id: str | None) -> None:
        self._annotation_controller.set_active_annotation(annotation_id)

    def _edit_annotation(self, annotation_id: str) -> bool:
        self._annotation_controller._editor_class = _AnnotationEditorDialog
        return self._annotation_controller.edit_annotation(annotation_id)

    def _activate_annotation_layer(self) -> None:
        if self._annotation_toolbox_hidden:
            self._annotation_controller.show_toolbox()
            action = getattr(self, "_toggle_annotations_action", None)
            if action is not None and not action.isChecked():
                action.setChecked(True)
            btn = getattr(self, "_open_annotations_button", None)
            if btn is not None and not btn.isChecked():
                btn.setChecked(True)
        self._set_overlay_mode("annotate")

    def _hide_annotation_toolbox(self) -> None:
        self._toggle_annotation_toolbox(False)

    def _refresh_ui(self) -> None:
        """Render the current patch and synchronize visible controls."""
        self._selection_refresh_panel()
        self._apply_settings_to_controls()
        if self._colormap_dirty:
            self._apply_colormap(self.colormap)
            self._colormap_dirty = False
        try:
            self._render_patch(view_range=self._pending_view_range)
        finally:
            self._pending_view_range = None
            self._force_preserve_pending_view_range = False

    def _on_colormap_changed(self, name: str) -> None:
        """Update persisted colormap and reapply it to the current image."""
        self.colormap = name
        if self._is_ui_visible():
            self._apply_colormap(name)
            return
        self._colormap_dirty = True
        self._request_ui_refresh()

    def _on_levels_changed(self, *_args) -> None:
        """Persist the histogram min/max levels whenever the user changes them."""
        if self._ignore_level_changes:
            return
        levels = self._hist_lut.item.getLevels()
        if levels is None:
            self.color_limits = None
            return
        low, high = levels
        if low is None or high is None:
            self.color_limits = None
            return
        if not np.isfinite((low, high)).all():
            self.color_limits = None
            return
        self.color_limits = [float(low), float(high)]

    def _apply_persisted_levels(self) -> None:
        """Restore saved histogram levels after loading a new image."""
        if self.color_limits is None:
            return
        low, high = self.color_limits
        with self._suspend_level_persistence():
            self._hist_lut.item.setLevels(float(low), float(high))

    @staticmethod
    def _compute_default_levels(display_data: np.ndarray) -> tuple[float, float] | None:
        """Return default color levels from DASCore's waterfall helper."""
        scale = get_dascore_waterfall_scale(None, "relative", display_data)
        if scale is None or len(scale) != 2:
            return None
        low, high = float(scale[0]), float(scale[1])
        if not np.isfinite((low, high)).all():
            return None
        return low, high

    def _apply_default_levels(self, display_data: np.ndarray) -> None:
        """Apply DASCore's default color limits to the histogram region."""
        levels = self._compute_default_levels(display_data)
        if levels is None:
            return
        with self._suspend_level_persistence():
            self._hist_lut.item.setLevels(*levels)

    def _reset_histogram_levels_to_default(self) -> None:
        """Reset the histogram levels using DASCore's default waterfall scaling."""
        prepared = self._prepared_render
        if prepared is None:
            return
        if prepared.data.size == 0:
            return
        self.color_limits = None
        self._apply_default_levels(prepared.display_data)

    @contextmanager
    def _suspend_level_persistence(self):
        """Ignore histogram change signals during internal render-time updates."""
        self._ignore_level_changes += 1
        try:
            yield
        finally:
            self._ignore_level_changes -= 1

    def _apply_colormap(self, name: str) -> None:
        """Apply a pyqtgraph colormap to the image item and histogram."""
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
        self._image_item.setColorMap(cmap)
        self._hist_lut.item.gradient.setColorMap(cmap)

    def _render_patch(
        self,
        view_range: tuple[tuple[float, float], tuple[float, float]] | None = None,
    ) -> None:
        """Render the current patch in the pyqtgraph image view."""
        self.Error.clear()
        if self._patch is None:
            self._prepared_render = None
            self._image_item.clear()
            self._plot_item.setTitle("No patch")
            self._axes = None
            self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
            self._set_cursor_readout(None)
            self._clear_roi()
            self._clear_annotations(emit=False)
            return

        try:
            prepared = self._prepared_render
            if prepared is None:
                raise ValueError("expected 2D data, got no prepared render state")
            display_data = prepared.display_data
            axes = prepared.axes
            x_values = axes.x_plot
            y_values = axes.y_plot
            preserve_view = self._view_range_contains_data(
                view_range, x_values, y_values
            )
            x0, x_step = self._axis_origin_and_step(x_values)
            y0, y_step = self._axis_origin_and_step(y_values)

            with self._suspend_level_persistence():
                self._image_item.setImage(display_data, autoLevels=True)
            if self.color_limits is None:
                self._apply_default_levels(display_data)
            else:
                self._apply_persisted_levels()
            rect = QRectF(
                x0 - (x_step / 2),
                y0 - (y_step / 2),
                x_step * display_data.shape[1],
                y_step * display_data.shape[0],
            )
            self._image_item.setRect(rect)
            self._axes = axes
            ensure_axis_item(self._plot_item, "bottom", self._axis_kinds["bottom"])
            ensure_axis_item(self._plot_item, "left", self._axis_kinds["left"])
            self._refresh_axis_labels()
            self._plot_item.setTitle(f"{axes.y_dim} x {axes.x_dim}")
            if self._force_preserve_pending_view_range and preserve_view:
                self._plot_item.vb.disableAutoRange()
                self._plot_item.vb.setRange(
                    xRange=view_range[0],
                    yRange=view_range[1],
                    padding=0,
                )
            else:
                target_view_range = self._target_view_range(
                    previous_view_range=view_range,
                    image_rect=rect,
                )
                if target_view_range is None:
                    if not preserve_view:
                        self._plot_item.vb.enableAutoRange(x=True, y=True)
                        self._plot_item.vb.autoRange()
                    else:
                        self._plot_item.vb.disableAutoRange()
                        self._plot_item.vb.setRange(
                            xRange=view_range[0],
                            yRange=view_range[1],
                            padding=0,
                        )
                else:
                    self._plot_item.vb.disableAutoRange()
                    self._plot_item.vb.setRange(
                        xRange=target_view_range[0],
                        yRange=target_view_range[1],
                        padding=0,
                    )
            if self._restore_saved_roi_after_render:
                self._sync_roi_to_selection()
                self._restore_saved_roi_after_render = False
            self._ensure_annotation_set()
            self._rebuild_annotation_items()
            self._persist_annotation_settings()
        except Exception as exc:
            self._image_item.clear()
            self._axes = None
            self._axis_kinds = {"bottom": "numeric", "left": "numeric"}
            self._set_cursor_readout(None)
            self._clear_roi()
            self._clear_annotations(emit=False)
            self._show_exception("invalid_patch", exc)

    def _on_view_range_changed(self, _view_box, _view_range) -> None:
        """Refresh axis labels when zoom/pan changes datetime context."""
        self._persist_view_range_settings()
        self._refresh_axis_labels()

    def _refresh_axis_labels(self) -> None:
        """Update axis labels, adding datetime context when useful."""
        if self._axes is None:
            self._plot_item.setLabel("left", "Dim 0")
            self._plot_item.setLabel("bottom", "Dim 1")
            return
        view_range = self._get_view_range()
        if view_range is None:
            left_label = self._axes.y_dim
            bottom_label = self._axes.x_dim
        else:
            bottom_label = format_axis_label(
                self._plot_item,
                "bottom",
                self._axes.x_dim,
                self._axis_kinds["bottom"],
                tuple(view_range[0]),
            )
            left_label = format_axis_label(
                self._plot_item,
                "left",
                self._axes.y_dim,
                self._axis_kinds["left"],
                tuple(view_range[1]),
            )
        self._plot_item.setLabel("left", left_label)
        self._plot_item.setLabel("bottom", bottom_label)

    def _on_plot_mouse_clicked(self, ev) -> None:
        """Handle plot clicks for annotation selection or ROI creation."""
        if self._should_show_annotation_context_menu(ev):
            self._show_annotation_context_menu(ev)
            ev.accept()
            return
        if (
            self._overlay_mode == "annotate"
            and ev.button() == Qt.LeftButton
            and not ev.double()
        ):
            item = self._annotation_controller._annotation_item_at_scene_pos(
                ev.scenePos()
            )
            if item is not None:
                self._annotation_controller.on_item_clicked(item, None)
                ev.accept()
                return
        if (
            self._overlay_mode != "select"
            or self._patch is None
            or ev.button() != Qt.LeftButton
        ):
            return
        if not self._plot_item.sceneBoundingRect().contains(ev.scenePos()):
            return
        if (
            not ev.double()
            and isinstance(self._roi, _SelectionROI)
            and self._roi.sceneBoundingRect().contains(ev.scenePos())
        ):
            self._roi.setSelected(True)
            self._roi.setFocus()
            scene = self._plot_widget.scene()
            if scene is not None:
                scene.setFocusItem(self._roi)
            ev.accept()
            return
        view_pos = self._plot_item.vb.mapSceneToView(ev.scenePos())
        if not ev.double():
            return
        self._create_selection_roi(float(view_pos.x()), float(view_pos.y()))
        ev.accept()

    def _should_show_annotation_context_menu(self, ev) -> bool:
        """Return True when an annotation menu should override the default."""
        if self._overlay_mode != "annotate" or ev.button() != Qt.RightButton:
            return False
        selected_ids = set(self._annotation_controller.selected_annotation_ids)
        if not selected_ids:
            return False
        selected_annotations = [
            annotation
            for annotation in (
                self._annotation_by_id(annotation_id) for annotation_id in selected_ids
            )
            if annotation is not None
        ]
        return bool(selected_annotations) and all(
            isinstance(annotation.geometry, PointGeometry)
            for annotation in selected_annotations
        )

    def _annotation_context_menu(self) -> QMenu:
        """Build the annotation-specific context menu for selected point annotations."""
        menu = QMenu(self)
        fit_menu = menu.addMenu("Fit")
        for shape in ("line", "ellipse", "square", "hyperbola"):
            action = fit_menu.addAction(shape.capitalize())
            action.triggered.connect(
                lambda _checked=False, fit_shape=shape: (
                    self._on_annotation_fit_requested(fit_shape)
                )
            )
        return menu

    def _show_annotation_context_menu(self, ev) -> None:
        """Show one annotation-specific context menu near the pointer."""
        menu = self._annotation_context_menu()
        screen_pos = getattr(ev, "screenPos", None)
        if callable(screen_pos):
            global_pos = screen_pos().toPoint()
        else:
            global_pos = self._plot_widget.mapToGlobal(
                self._plot_widget.mapFromScene(ev.scenePos())
            )
        menu.exec(global_pos)

    def _on_plot_mouse_moved(self, event) -> None:
        """Update the cursor readout from the current mouse position."""
        if self._patch is None or self._axes is None:
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
        """Show the nearest plotted sample and value under the cursor."""
        prepared = self._prepared_render
        if prepared is None or self._axes is None:
            self._set_cursor_readout(None)
            return
        data = prepared.data
        if data.size == 0:
            self._set_cursor_readout(None)
            return
        x_index = self._nearest_axis_index(plot_x, self._axes.x_plot)
        y_index = self._nearest_axis_index(plot_y, self._axes.y_plot)
        x_coord = self._axes.x_coord[x_index]
        y_coord = self._axes.y_coord[y_index]
        value = data[y_index, x_index]
        self._set_cursor_readout(
            [
                CursorField(self._axes.x_dim, x_coord),
                CursorField(self._axes.y_dim, y_coord),
                CursorField("value", value),
            ]
        )

    def _set_cursor_readout(self, fields: list[CursorField] | None) -> None:
        """Update the footer text used for cursor inspection."""
        set_cursor_label_text(self._cursor_label, fields)

    def _view_menu(self) -> QMenu | None:
        """Return the widget-window View menu, creating it when needed."""
        menu_bar = self.menuBar()
        if not isinstance(menu_bar, QMenuBar):
            return None
        view_menu = menu_bar.findChild(QMenu, "view-menu")
        if view_menu is not None:
            return view_menu
        for action in menu_bar.actions():
            existing_menu = action.menu()
            if existing_menu is None:
                continue
            if existing_menu.title().replace("&", "") != "View":
                continue
            existing_menu.setObjectName("view-menu")
            return existing_menu
        view_menu = menu_bar.addMenu("View")
        view_menu.setObjectName("view-menu")
        return view_menu

    def _install_view_menu_actions(self) -> None:
        """Install Waterfall-specific view toggles in the View menu."""
        view_menu = self._view_menu()
        if view_menu is None:
            return
        if getattr(self, "_toggle_annotations_action", None) is not None:
            return
        action = QAction("Annotations", self)
        action.setObjectName("toggle-annotations-action")
        action.setCheckable(True)
        action.setChecked(not self._annotation_toolbox_hidden)
        action.toggled.connect(self._toggle_annotation_toolbox)
        view_menu.addAction(action)
        self._toggle_annotations_action = action
        self._ensure_menu_bar_visible()

    def _toggle_annotation_toolbox(self, visible: bool) -> None:
        """Show or hide the floating annotation toolbox from the View menu."""
        if visible:
            self._annotation_controller.show_toolbox()
            self._annotation_controller.enter_annotation_selection_mode(notify=False)
        else:
            self._annotation_controller.hide_toolbox()
            self._annotation_controller.clear_active_tool(notify=False)
        self._sync_overlay_mode_from_annotation_tool()
        action = getattr(self, "_toggle_annotations_action", None)
        if action is not None and action.isChecked() != visible:
            action.setChecked(visible)
        btn = getattr(self, "_open_annotations_button", None)
        if btn is not None and btn.isChecked() != visible:
            btn.setChecked(visible)

    def _on_annotation_fit_requested(self, shape: str) -> None:
        """Fit one shape from the selected point annotations."""
        if self._annotation_controller.fit_shape_from_selection(shape):
            self._mark_output_dirty("annotation_set")

    def _on_overlay_tool_changed(self, tool: str) -> None:
        """Keep the interaction mode aligned with toolbox visibility."""
        _ = tool
        self._sync_overlay_mode_from_annotation_tool()

    def _restore_default_interaction_mode(self) -> None:
        """Restore the default mode implied by the annotation toolbox state."""
        if self._annotation_toolbox_hidden:
            self._annotation_controller.clear_active_tool(notify=False)
        else:
            self._annotation_controller.enter_annotation_selection_mode(notify=False)
        self._sync_overlay_mode_from_annotation_tool()

    def _sync_overlay_mode_from_annotation_tool(self) -> None:
        """Keep plot interaction in sync with the active annotation tool."""
        annotate = not self._annotation_toolbox_hidden
        self._set_overlay_mode("annotate" if annotate else "select")

    def _set_overlay_mode(self, mode: str) -> None:
        """Switch between selection-ROI and annotation interaction."""
        self._overlay_mode = mode
        annotation_interactive = mode == "annotate"
        self._annotation_controller.layer_active = annotation_interactive
        self._annotation_controller.set_interactive(annotation_interactive)
        self._set_roi_interactive(mode == "select")
        self._add_selection_button.setChecked(mode == "select")

    def _set_roi_interactive(self, interactive: bool) -> None:
        """Keep the ROI visible while enabling only active-mode affordances."""
        if isinstance(self._roi, _SelectionROI):
            self._roi.set_interactive(interactive)

    def _create_selection_roi(self, center_x: float, center_y: float) -> None:
        """Create or replace the rectangular ROI centered on the given plot coords."""
        if self._axes is None:
            return
        view_range = self._get_view_range()
        self._selection_set_patch_dim_enabled(self._axes.x_dim, True, notify=False)
        self._selection_set_patch_dim_enabled(self._axes.y_dim, True, notify=False)
        x_span = max(abs(float(self._axes.x_plot[-1] - self._axes.x_plot[0])), 1e-12)
        y_span = max(abs(float(self._axes.y_plot[-1] - self._axes.y_plot[0])), 1e-12)
        width = x_span * 0.25
        height = y_span * 0.25

        if self._roi is not None:
            self._plot_item.removeItem(self._roi)

        self._roi = self._make_roi(
            center_x - (width / 2),
            center_y - (height / 2),
            width,
            height,
        )
        self._set_roi_interactive(self._overlay_mode == "select")
        self._update_selection_from_roi()
        if view_range is not None:
            self._plot_item.vb.disableAutoRange()
            self._plot_item.vb.setRange(
                xRange=view_range[0],
                yRange=view_range[1],
                padding=0,
            )

    def _on_roi_change_finished(self) -> None:
        """Recompute and emit output when ROI bounds change."""
        self._update_selection_from_roi()

    def _emit_current_selection(self) -> None:
        """Emit the current patch selection based on shared selection state."""
        self.Warning.empty_selection.clear()
        if self._patch is None:
            self.Outputs.patch.send(None)
            return
        if self._roi is not None and not self._restore_saved_roi_after_render:
            self._update_selection_from_roi(notify=False)
        try:
            selected = self._selection_apply_to_patch(self._patch)
            if self._is_empty_patch(selected) and self._has_active_narrowed_selection():
                self.Warning.empty_selection()
        except Exception as exc:
            self._show_exception("invalid_patch", exc)
            selected = self._patch
        self.Outputs.patch.send(selected)

    def _selection_on_state_changed(self) -> None:
        """Keep ROI geometry and emitted patch output in sync with left-panel edits."""
        if self._selection_is_syncing():
            return
        self._persist_selection_settings()
        self._sync_roi_to_selection()
        self._emit_current_selection()

    def _selection_request_panel_refresh(self) -> None:
        """Refresh selection controls without dropping the current plot zoom."""
        if self._patch is not None:
            self._pending_view_range = self._get_view_range()
            self._force_preserve_pending_view_range = True
        super()._selection_request_panel_refresh()

    def _on_selection_reset_requested(self) -> None:
        """Reset the current selection and remove any active ROI."""
        super()._on_selection_reset_requested()

    def _clear_roi(self) -> None:
        """Remove any active ROI from the plot and clear its reference."""
        if self._roi is None:
            return
        self._plot_item.removeItem(self._roi)
        self._roi = None

    def _delete_active_roi(self) -> None:
        """Delete the active ROI and restore full plotted-dimension extents."""
        if self._roi is None or self._axes is None:
            return
        self._selection_reset_patch_dims((self._axes.x_dim, self._axes.y_dim))

    def _add_selection_from_view(self) -> None:
        """Place a default ROI in the visible view or over the full data center."""
        if self._axes is None:
            return
        self._annotation_tool = "select"

        # Prefer the current visible window so the new ROI appears where the user
        # is already looking; fall back to the full plotted extent otherwise.
        view_range = self._get_view_range()
        if self._view_range_contains_data(
            view_range, self._axes.x_plot, self._axes.y_plot
        ):
            x_range, y_range = view_range
            center_x = float(sum(x_range) / 2)
            center_y = float(sum(y_range) / 2)
        else:
            x_low, x_high = self._axis_bounds(self._axes.x_plot)
            y_low, y_high = self._axis_bounds(self._axes.y_plot)
            center_x = float((x_low + x_high) / 2)
            center_y = float((y_low + y_high) / 2)

        self._create_selection_roi(center_x, center_y)

    @staticmethod
    def _is_empty_patch(patch: dc.Patch) -> bool:
        """Return True if any patch dimension has zero length."""
        return any(size == 0 for size in patch.shape)

    def _selection_kwargs_from_roi(self) -> dict[str, tuple]:
        """Build patch.select keyword ranges from the current ROI bounds."""
        if self._roi is None or self._axes is None:
            return {}

        pos = self._roi.pos()
        size = self._roi.size()
        x0 = float(pos.x())
        x1 = x0 + float(size.x())
        y0 = float(pos.y())
        y1 = y0 + float(size.y())
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y0, y1))

        x_min_coord = map_plot_value_to_coord(
            xmin, self._axes.x_plot, self._axes.x_coord
        )
        x_max_coord = map_plot_value_to_coord(
            xmax, self._axes.x_plot, self._axes.x_coord
        )
        y_min_coord = map_plot_value_to_coord(
            ymin, self._axes.y_plot, self._axes.y_coord
        )
        y_max_coord = map_plot_value_to_coord(
            ymax, self._axes.y_plot, self._axes.y_coord
        )
        return {
            self._axes.x_dim: (x_min_coord, x_max_coord),
            self._axes.y_dim: (y_min_coord, y_max_coord),
        }

    def _update_selection_from_roi(self, *, notify: bool = True) -> None:
        """Write the current ROI bounds back into the shared selection state."""
        if self._roi is None or self._axes is None or self._selection_is_syncing():
            return
        kwargs = self._selection_kwargs_from_roi()
        if not kwargs:
            return
        with self._selection_sync_guard():
            for dim, (low, high) in kwargs.items():
                self._selection_update_patch_range_absolute_from_roi(
                    dim, low, high, notify=False
                )
        if notify:
            self._selection_on_state_changed()

    def _sync_roi_to_selection(self) -> None:
        """
        Update the ROI geometry from the current plotted-dimension selection state.
        """
        if self._axes is None:
            self._clear_roi()
            return
        x_enabled = self._selection_state.patch_dim_enabled(self._axes.x_dim)
        y_enabled = self._selection_state.patch_dim_enabled(self._axes.y_dim)
        if not x_enabled and not y_enabled:
            self._clear_roi()
            return
        x_range = self._selection_current_patch_absolute_range(self._axes.x_dim)
        y_range = self._selection_current_patch_absolute_range(self._axes.y_dim)
        x_extent = self._selection_patch_absolute_extent(self._axes.x_dim)
        y_extent = self._selection_patch_absolute_extent(self._axes.y_dim)
        if x_range is None or y_range is None or x_extent is None or y_extent is None:
            self._clear_roi()
            return
        if self._selection_covers_full_plot_extent(
            x_enabled=x_enabled,
            y_enabled=y_enabled,
            x_range=x_range,
            y_range=y_range,
            x_extent=x_extent,
            y_extent=y_extent,
        ):
            self._clear_roi()
            return

        if x_enabled:
            x_low = map_coord_to_plot_value(
                x_range[0], self._axes.x_coord, self._axes.x_plot
            )
            x_high = map_coord_to_plot_value(
                x_range[1], self._axes.x_coord, self._axes.x_plot
            )
        else:
            x_low, x_high = self._axis_bounds(self._axes.x_plot)
        if y_enabled:
            y_low = map_coord_to_plot_value(
                y_range[0], self._axes.y_coord, self._axes.y_plot
            )
            y_high = map_coord_to_plot_value(
                y_range[1], self._axes.y_coord, self._axes.y_plot
            )
        else:
            y_low, y_high = self._axis_bounds(self._axes.y_plot)
        xmin, xmax = sorted((x_low, x_high))
        ymin, ymax = sorted((y_low, y_high))
        self._roi = self._make_roi(
            xmin,
            ymin,
            max(xmax - xmin, 1e-12),
            max(ymax - ymin, 1e-12),
        )
        self._set_roi_interactive(self._overlay_mode == "select")

    def _make_roi(
        self,
        x_pos: float,
        y_pos: float,
        width: float,
        height: float,
    ) -> pg.ROI:
        """Create a standard ROI instance and install it on the plot."""
        self._clear_roi()
        with self._selection_sync_guard():
            roi = _SelectionROI(
                [x_pos, y_pos],
                [width, height],
                on_delete=self._delete_active_roi,
                pen=pg.mkPen((235, 250, 255), width=3, style=Qt.PenStyle.DashLine),
                handlePen=pg.mkPen((255, 255, 255), width=2),
            )
            roi.handleSize = 12
            roi.addScaleHandle((0, 0), (1, 1))
            roi.addScaleHandle((1, 0), (0, 1))
            roi.addScaleHandle((0, 1), (1, 0))
            roi.addScaleHandle((1, 1), (0, 0))
            roi.addScaleHandle((0.5, 0), (0.5, 1))
            roi.addScaleHandle((0.5, 1), (0.5, 0))
            roi.addScaleHandle((0, 0.5), (1, 0.5))
            roi.addScaleHandle((1, 0.5), (0, 0.5))
            roi.sigRegionChangeFinished.connect(self._on_roi_change_finished)
            self._plot_item.addItem(roi, ignoreBounds=True)
        return roi

    @staticmethod
    def _axis_origin_and_step(values: np.ndarray) -> tuple[float, float]:
        """Return axis origin and step for mapping image coordinates."""
        if values.size <= 1:
            return float(values[0]) if values.size else 0.0, 1.0
        step = float((values[-1] - values[0]) / (values.size - 1))
        if step == 0:
            step = 1.0
        return float(values[0]), step

    def _get_view_range(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return the current finite x/y plot ranges, if available."""
        x_range, y_range = self._plot_item.vb.viewRange()
        if not np.all(np.isfinite([*x_range, *y_range])):
            return None
        return tuple(x_range), tuple(y_range)

    @staticmethod
    def _nearest_axis_index(value: float, axis_values: np.ndarray) -> int:
        """Return the nearest plotted sample index for a numeric plot coordinate."""
        if axis_values.size == 0:
            return 0
        return nearest_axis_index(value, axis_values)

    @classmethod
    def _view_range_contains_data(
        cls,
        view_range: tuple[tuple[float, float], tuple[float, float]] | None,
        x_values: np.ndarray,
        y_values: np.ndarray,
    ) -> bool:
        """Return True when the current view contains plotted samples on both axes."""
        if view_range is None:
            return False
        return cls._range_contains_axis_values(
            view_range[0], x_values
        ) and cls._range_contains_axis_values(view_range[1], y_values)

    @staticmethod
    def _range_contains_axis_values(
        value_range: tuple[float, float],
        axis_values: np.ndarray,
    ) -> bool:
        """Return True when at least one plotted sample lies inside the view range."""
        if axis_values.size == 0:
            return False
        low, high = sorted(value_range)
        values = np.asarray(axis_values, dtype=np.float64)
        return bool(np.any((values >= low) & (values <= high)))

    def _has_active_narrowed_selection(self) -> bool:
        """Return True when current selection state narrows the emitted patch."""
        return bool(self._selection_state.patch_kwargs())

    def _restore_absolute_selection_ranges(
        self,
        patch: dc.Patch | None,
        *,
        had_active_selection: bool,
        previous_basis: str,
        previous_ranges: dict[str, tuple[object, object] | None],
    ) -> None:
        """Restore preserved absolute ranges for waterfall-specific patch changes."""
        if patch is None or previous_basis != "absolute" or not had_active_selection:
            return
        for dim, previous_range in previous_ranges.items():
            if previous_range is None or dim not in patch.dims:
                continue
            coord = np.asarray(patch.get_array(dim))
            low, high = previous_range
            if not self._absolute_value_matches_coord_type(low, coord):
                continue
            if not self._absolute_value_matches_coord_type(high, coord):
                continue
            self._selection_state.update_patch_range(dim, low, high)

    def _apply_pending_saved_selection_restore(self, patch: dc.Patch | None) -> None:
        """Apply one-time ROI restore semantics from saved workflow settings."""
        if not self._pending_saved_selection_restore:
            return
        self._pending_saved_selection_restore = False
        saved_has_roi = self._pending_saved_selection_has_roi
        self._pending_saved_selection_has_roi = None
        if patch is None:
            return
        if saved_has_roi is None:
            saved_has_roi = self._selection_state_implies_visual_roi()
        if saved_has_roi:
            self._restore_saved_roi_after_render = True
            return
        if self._axes is None:
            self._restore_saved_roi_after_render = False
            return
        for dim in (self._axes.x_dim, self._axes.y_dim):
            extent = self._selection_state.patch.extents.get(dim)
            if extent is None:
                continue
            self._selection_state.patch.ranges[dim] = extent
            self._selection_state.patch.enabled[dim] = True
        self._restore_saved_roi_after_render = False

    def _load_saved_annotation_state(self) -> dict[str, object] | None:
        """Return one serialized Waterfall annotation set staged from settings."""
        payload = self.saved_annotation_set
        return payload if isinstance(payload, dict) else None

    def _load_saved_view_range(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return one serialized Waterfall view range staged from settings."""
        payload = self.saved_view_range
        if not isinstance(payload, (list | tuple)) or len(payload) != 2:
            return None
        try:
            x_range_raw, y_range_raw = payload
            x_range = tuple(float(value) for value in x_range_raw)
            y_range = tuple(float(value) for value in y_range_raw)
        except (TypeError, ValueError):
            return None
        if len(x_range) != 2 or len(y_range) != 2:
            return None
        if not np.all(np.isfinite([*x_range, *y_range])):
            return None
        return x_range, y_range

    def _apply_pending_saved_annotation_restore(self) -> None:
        """Restore one saved Waterfall annotation set when axes are available."""
        payload = self._pending_saved_annotation_set
        if payload is None:
            return
        self._pending_saved_annotation_set = None
        try:
            annotation_set = AnnotationSet.model_validate(payload)
        except Exception:
            self.saved_annotation_set = None
            return
        dims = self._annotation_controller.annotation_dims()
        if dims is None or set(annotation_set.dims) != set(dims):
            self.saved_annotation_set = None
            return
        self._annotation_set = annotation_set
        self._active_annotation_id = None
        self._rebuild_annotation_items()
        self.saved_annotation_set = annotation_set.model_dump(mode="json")
        self._clear_output_dirty("annotation_set")

    def _persist_annotation_settings(self) -> None:
        """Mirror the current Waterfall annotation set into workflow settings."""
        annotation_set = self._annotation_set
        self.saved_annotation_set = (
            None if annotation_set is None else annotation_set.model_dump(mode="json")
        )

    def _persist_view_range_settings(self) -> None:
        """Mirror the current Waterfall plot extents into workflow settings."""
        view_range = self._get_view_range()
        self.saved_view_range = (
            None if view_range is None else [list(view_range[0]), list(view_range[1])]
        )

    @staticmethod
    def _absolute_value_matches_coord_type(
        value: object, coord_values: np.ndarray
    ) -> bool:
        """Return True when an absolute selection value matches coord dtype."""
        coord_dtype = np.asarray(coord_values).dtype
        value_dtype = np.asarray(value).dtype
        if np.issubdtype(coord_dtype, np.datetime64):
            return np.issubdtype(value_dtype, np.datetime64)
        if np.issubdtype(coord_dtype, np.timedelta64):
            return np.issubdtype(value_dtype, np.timedelta64)
        if np.issubdtype(coord_dtype, np.number):
            return np.issubdtype(value_dtype, np.number)
        return True

    def _current_roi_plot_bounds(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return current ROI bounds in plot coordinates for the rendered axes."""
        if self._axes is None:
            return None
        x_enabled = self._selection_state.patch_dim_enabled(self._axes.x_dim)
        y_enabled = self._selection_state.patch_dim_enabled(self._axes.y_dim)
        if not x_enabled and not y_enabled:
            return None
        x_range = self._selection_current_patch_absolute_range(self._axes.x_dim)
        y_range = self._selection_current_patch_absolute_range(self._axes.y_dim)
        x_extent = self._selection_patch_absolute_extent(self._axes.x_dim)
        y_extent = self._selection_patch_absolute_extent(self._axes.y_dim)
        if x_range is None or y_range is None or x_extent is None or y_extent is None:
            return None
        if self._selection_covers_full_plot_extent(
            x_enabled=x_enabled,
            y_enabled=y_enabled,
            x_range=x_range,
            y_range=y_range,
            x_extent=x_extent,
            y_extent=y_extent,
        ):
            return None

        if x_enabled:
            x_low = map_coord_to_plot_value(
                x_range[0], self._axes.x_coord, self._axes.x_plot
            )
            x_high = map_coord_to_plot_value(
                x_range[1], self._axes.x_coord, self._axes.x_plot
            )
        else:
            x_low, x_high = self._axis_bounds(self._axes.x_plot)
        if y_enabled:
            y_low = map_coord_to_plot_value(
                y_range[0], self._axes.y_coord, self._axes.y_plot
            )
            y_high = map_coord_to_plot_value(
                y_range[1], self._axes.y_coord, self._axes.y_plot
            )
        else:
            y_low, y_high = self._axis_bounds(self._axes.y_plot)
        return tuple(sorted((x_low, x_high))), tuple(sorted((y_low, y_high)))

    def _target_view_range(
        self,
        *,
        previous_view_range: tuple[tuple[float, float], tuple[float, float]] | None,
        image_rect: QRectF,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return an explicit x/y view range when selection framing is needed."""
        roi_bounds = self._current_roi_plot_bounds()
        if roi_bounds is None:
            if previous_view_range is None:
                return None
            if self._axes is None:
                return None
            if not self._view_range_contains_data(
                previous_view_range, self._axes.x_plot, self._axes.y_plot
            ):
                return None
            return previous_view_range

        patch_bounds = (
            tuple(sorted((image_rect.left(), image_rect.right()))),
            tuple(sorted((image_rect.top(), image_rect.bottom()))),
        )
        if (
            previous_view_range is not None
            and self._view_range_contains_region(previous_view_range, patch_bounds)
            and self._view_range_contains_region(previous_view_range, roi_bounds)
        ):
            return previous_view_range

        return (
            self._union_ranges(patch_bounds[0], roi_bounds[0]),
            self._union_ranges(patch_bounds[1], roi_bounds[1]),
        )

    @classmethod
    def _view_range_contains_region(
        cls,
        view_range: tuple[tuple[float, float], tuple[float, float]],
        region: tuple[tuple[float, float], tuple[float, float]],
    ) -> bool:
        """Return True when the current view fully contains a rectangular region."""
        return cls._range_contains_range(
            view_range[0], region[0]
        ) and cls._range_contains_range(view_range[1], region[1])

    @staticmethod
    def _range_contains_range(
        outer: tuple[float, float],
        inner: tuple[float, float],
    ) -> bool:
        """Return True when one 1D range fully contains another."""
        outer_low, outer_high = sorted(outer)
        inner_low, inner_high = sorted(inner)
        return outer_low <= inner_low and outer_high >= inner_high

    @staticmethod
    def _union_ranges(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> tuple[float, float]:
        """Return the bounding 1D range that contains both inputs."""
        first_low, first_high = sorted(first)
        second_low, second_high = sorted(second)
        return min(first_low, second_low), max(first_high, second_high)

    def _load_saved_selection_state(self) -> dict[str, Any] | None:
        """Return serialized selection settings staged from stored widget settings."""
        basis_name = str(self.saved_selection_basis or "").strip()
        rows = (
            self.saved_selection_ranges
            if isinstance(self.saved_selection_ranges, list)
            else []
        )
        if not basis_name or not rows:
            return None
        return {"basis": basis_name, "rows": rows}

    def _prime_saved_selection_state(self) -> None:
        """Seed selection state from stored workflow settings before patch input."""
        primed = self._selection_state.prime_patch_state_from_settings(
            self._load_saved_selection_state()
        )
        self._pending_saved_selection_restore = primed
        self._pending_saved_selection_has_roi = (
            self.saved_selection_has_roi if primed else None
        )
        self._restore_saved_roi_after_render = primed

    def _persist_selection_settings(self) -> None:
        """Mirror the current shared selection state into schema-backed settings."""
        payload = self._selection_state.patch_settings_payload(include_inactive=True)
        if payload is None:
            self.saved_selection_basis = ""
            self.saved_selection_ranges = []
            self.saved_selection_has_roi = False
            return
        self.saved_selection_basis = str(payload["basis"])
        self.saved_selection_ranges = list(payload["rows"])
        self.saved_selection_has_roi = self._selection_state_implies_visual_roi()

    def _selection_state_implies_visual_roi(self) -> bool:
        """Return True when current selection state should display an ROI."""
        if self._axes is None:
            return False
        x_enabled = self._selection_state.patch_dim_enabled(self._axes.x_dim)
        y_enabled = self._selection_state.patch_dim_enabled(self._axes.y_dim)
        if not x_enabled and not y_enabled:
            return False
        x_range = self._selection_current_patch_absolute_range(self._axes.x_dim)
        y_range = self._selection_current_patch_absolute_range(self._axes.y_dim)
        x_extent = self._selection_patch_absolute_extent(self._axes.x_dim)
        y_extent = self._selection_patch_absolute_extent(self._axes.y_dim)
        if x_range is None or y_range is None or x_extent is None or y_extent is None:
            return False
        return not self._selection_covers_full_plot_extent(
            x_enabled=x_enabled,
            y_enabled=y_enabled,
            x_range=x_range,
            y_range=y_range,
            x_extent=x_extent,
            y_extent=y_extent,
        )

    @classmethod
    def _axis_bounds(cls, values: np.ndarray) -> tuple[float, float]:
        """Return the plotted min/max bounds of an axis including half-step edges."""
        origin, step = cls._axis_origin_and_step(values)
        edge_low = origin - (step / 2)
        edge_high = edge_low + (step * values.size)
        return tuple(sorted((edge_low, edge_high)))

    def _selection_covers_full_plot_extent(
        self,
        *,
        x_enabled: bool,
        y_enabled: bool,
        x_range: tuple[object, object],
        y_range: tuple[object, object],
        x_extent: tuple[object, object],
        y_extent: tuple[object, object],
    ) -> bool:
        """Return True when enabled plotted dimensions are effectively unbounded."""
        if self._axes is None or not x_enabled or not y_enabled:
            return False
        return bool(
            self._absolute_range_matches_extent(x_range, x_extent, self._axes.x_coord)
            and self._absolute_range_matches_extent(
                y_range, y_extent, self._axes.y_coord
            )
        )

    @classmethod
    def _absolute_range_matches_extent(
        cls,
        current: tuple[object, object],
        extent: tuple[object, object],
        coord_values: np.ndarray,
    ) -> bool:
        """Return True when an absolute range is effectively the full axis extent."""
        current_low, current_high = current
        extent_low, extent_high = extent
        coord = np.asarray(coord_values)
        if np.issubdtype(coord.dtype, np.datetime64):
            return current_low == extent_low and current_high == extent_high
        if np.issubdtype(coord.dtype, np.timedelta64):
            return current_low == extent_low and current_high == extent_high
        if np.issubdtype(coord.dtype, np.number):
            atol = cls._numeric_coord_tolerance(coord)
            return bool(
                np.isclose(float(current_low), float(extent_low), rtol=0.0, atol=atol)
                and np.isclose(
                    float(current_high), float(extent_high), rtol=0.0, atol=atol
                )
            )
        return current_low == extent_low and current_high == extent_high

    @staticmethod
    def _numeric_coord_tolerance(coord_values: np.ndarray) -> float:
        """Return a small absolute tolerance for numeric full-extent comparisons."""
        coord = np.asarray(coord_values, dtype=np.float64)
        if coord.size <= 1:
            return 1e-12
        diffs = np.diff(coord)
        nonzero_diffs = np.abs(diffs[np.nonzero(diffs)])
        step = (
            float(nonzero_diffs.min())
            if nonzero_diffs.size
            else abs(float(coord[-1] - coord[0])) or 1.0
        )
        endpoint_spacing = max(
            abs(np.spacing(float(coord[0]))),
            abs(np.spacing(float(coord[-1]))),
        )
        return max(step * 1e-9, endpoint_spacing * 16, 1e-12)

    @staticmethod
    def _should_reset_view_for_new_patch(
        previous_patch: dc.Patch,
        new_patch: dc.Patch,
    ) -> bool:
        """Return True when a replacement patch should drop prior view/levels."""
        if previous_patch is new_patch:
            return False
        previous_data = np.asarray(previous_patch.data)
        new_data = np.asarray(new_patch.data)
        if previous_data.ndim != 2 or new_data.ndim != 2:
            return False
        if previous_patch.dims != new_patch.dims:
            return True
        if not all(
            np.array_equal(
                np.asarray(previous_patch.get_array(dim)),
                np.asarray(new_patch.get_array(dim)),
            )
            for dim in previous_patch.dims
        ):
            return True
        try:
            attrs_equal = previous_patch.attrs == new_patch.attrs
        except Exception:
            attrs_equal = False
        if attrs_equal and not np.array_equal(previous_data, new_data):
            return True
        return False

    @staticmethod
    def _ranges_overlap(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> bool:
        """Return True when two 1D ranges intersect."""
        first_low, first_high = sorted(first)
        second_low, second_high = sorted(second)
        return max(first_low, second_low) <= min(first_high, second_high)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Waterfall).run()
