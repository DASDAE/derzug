"""Floating annotation overlay controller for plot widgets."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

import numpy as np
import pyqtgraph as pg
from AnyQt.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, Signal
from AnyQt.QtGui import QPainterPath, QPainterPathStroker
from AnyQt.QtWidgets import QDialog, QGraphicsItem

from derzug.annotations_config import (
    AnnotationSettingsDialog,
    load_annotation_config,
    save_annotation_config,
)
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    BoxGeometry,
    CoordRange,
    PathGeometry,
    PointGeometry,
    geometry_coord,
    geometry_dims,
    geometry_ordered_coords,
    geometry_point_coords,
    normalize_coord_value,
)
from derzug.utils.annotation_metadata import (
    annotation_label_color,
    annotation_label_from_slot,
)
from derzug.utils.annotations import (
    delete_annotation_by_id,
    replace_annotation_sequence,
    upsert_annotation,
)
from derzug.utils.plot_axes import map_coord_to_plot_value, map_plot_value_to_coord
from derzug.widgets.annotation_editor import AnnotationEditorDialog
from derzug.widgets.annotation_toolbox import AnnotationToolbox

_ANNOTATION_TOOLS = frozenset(
    {"annotation_select", "point", "line", "ellipse", "hyperbola", "box", "delete"}
)
_HYPERBOLA_SAMPLE_COUNT = 96
_HYPERBOLA_EPSILON = 1e-6
_POINT_TARGET_PX = 40.0 * (2.0 / 3.0)
_POINT_FALLBACK_SIZE = 2.0 * (2.0 / 3.0)
_POINT_HIT_RADIUS_FACTOR = 0.75
_ANNOTATION_SNAP_RADIUS_PX = 12.0


class _HyperbolaFitError(ValueError):
    """Raised when a hyperbola cannot be fit from the chosen annotations."""


class _EllipseFitError(ValueError):
    """Raised when an ellipse cannot be fit from the chosen annotations."""


def _normalize_half_turn_angle(angle: float) -> float:
    """Normalize one angle into the [-pi/2, pi/2) range."""
    while angle < (-math.pi / 2.0):
        angle += math.pi
    while angle >= (math.pi / 2.0):
        angle -= math.pi
    return float(angle)


def _format_equation_scalar(value: float | int) -> str:
    """Return one compact scalar string for stored equation text."""
    return format(float(value), ".6g")


def _plot_distance_sq(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Return the squared distance between two plot-space points."""
    dx = float(first[0]) - float(second[0])
    dy = float(first[1]) - float(second[1])
    return (dx * dx) + (dy * dy)


def _point_plot_xy(geometry: PointGeometry, axes) -> tuple[float, float]:
    """Return one point geometry in current plot-axis order."""
    x_coord, y_coord = geometry_ordered_coords(geometry, (axes.x_dim, axes.y_dim))
    return (
        float(map_coord_to_plot_value(x_coord, axes.x_coord, axes.x_plot)),
        float(map_coord_to_plot_value(y_coord, axes.y_coord, axes.y_plot)),
    )


def _path_plot_xy_points(
    geometry: PathGeometry, axes
) -> tuple[tuple[float, float], ...]:
    """Return one path geometry in current plot-axis order."""
    dims = (axes.x_dim, axes.y_dim)
    return tuple(
        (
            float(map_coord_to_plot_value(coords[0], axes.x_coord, axes.x_plot)),
            float(map_coord_to_plot_value(coords[1], axes.y_coord, axes.y_plot)),
        )
        for coords in (
            geometry_point_coords(geometry, i, dims)
            for i in range(len(geometry.points))
        )
    )


def _box_plot_rect(geometry: BoxGeometry, axes) -> tuple[float, float, float, float]:
    """Return one box geometry in current plot-axis order."""
    x_bounds = geometry.bounds[axes.x_dim]
    y_bounds = geometry.bounds[axes.y_dim]
    return (
        float(map_coord_to_plot_value(x_bounds.min, axes.x_coord, axes.x_plot)),
        float(map_coord_to_plot_value(y_bounds.min, axes.y_coord, axes.y_plot)),
        float(map_coord_to_plot_value(x_bounds.max, axes.x_coord, axes.x_plot)),
        float(map_coord_to_plot_value(y_bounds.max, axes.y_coord, axes.y_plot)),
    )


def _color_for_label(label: str | None) -> tuple[int, int, int]:
    """Return the base RGB color for one annotation label."""
    return annotation_label_color(label, load_annotation_config())


def _mix_rgb(
    rgb: tuple[int, int, int],
    target: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    """Blend one RGB tuple toward another."""
    return tuple(
        max(0, min(255, round((1 - amount) * src + amount * dst)))
        for src, dst in zip(rgb, target, strict=True)
    )


def _scene_stroked_local_shape(
    item: QGraphicsItem,
    local_path: QPainterPath,
    *,
    pen_width: float,
    extra_scene_px: float = 8.0,
) -> QPainterPath:
    """Return one local hit path with a fixed scene-pixel tolerance."""
    scene_width = max(float(pen_width), 1.0) + float(extra_scene_px)
    scene_path = item.sceneTransform().map(local_path)
    stroker = QPainterPathStroker()
    stroker.setWidth(scene_width)
    stroked_scene = stroker.createStroke(scene_path)
    inverse, invertible = item.sceneTransform().inverted()
    if invertible:
        return inverse.map(stroked_scene)

    fallback = QPainterPathStroker()
    fallback.setWidth(scene_width)
    return fallback.createStroke(local_path)


def _local_hit_stroke_width(
    item: QGraphicsItem,
    *,
    pen_width: float,
    extra_scene_px: float = 8.0,
) -> float:
    """Return one conservative local hit width for scene event dispatch."""
    transform = item.sceneTransform()
    origin = transform.map(QPointF(0.0, 0.0))
    unit_x = transform.map(QPointF(1.0, 0.0))
    unit_y = transform.map(QPointF(0.0, 1.0))
    scale_x = math.hypot(float(unit_x.x() - origin.x()), float(unit_x.y() - origin.y()))
    scale_y = math.hypot(float(unit_y.x() - origin.x()), float(unit_y.y() - origin.y()))
    valid_scales = [value for value in (scale_x, scale_y) if value > 1e-12]
    scene_units_per_local = max(valid_scales) if valid_scales else 1.0
    return max(
        (max(float(pen_width), 1.0) + extra_scene_px) / scene_units_per_local, 1e-6
    )


def _scene_path_contains(
    item: QGraphicsItem,
    local_path: QPainterPath,
    *,
    local_pos: QPointF,
    pen_width: float,
    extra_scene_px: float = 8.0,
) -> bool:
    """Return True when a local point lands within the scaled local hit stroke."""
    stroker = QPainterPathStroker()
    stroker.setWidth(
        _local_hit_stroke_width(
            item,
            pen_width=pen_width,
            extra_scene_px=extra_scene_px,
        )
    )
    return stroker.createStroke(local_path).contains(local_pos)


def _inactive_pen(*, interactive: bool, label: str | None = None) -> pg.QtGui.QPen:
    """Return the default high-visibility pen for inactive annotations."""
    alpha = 255 if interactive else 165
    return pg.mkPen((*_color_for_label(label), alpha), width=3)


def _inactive_hover_pen(
    *, interactive: bool, label: str | None = None
) -> pg.QtGui.QPen:
    """Return the hover pen for inactive annotations."""
    alpha = 255 if interactive else 165
    return pg.mkPen(
        (*_mix_rgb(_color_for_label(label), (255, 255, 255), 0.65), alpha), width=4
    )


def _active_pen(*, label: str | None = None) -> pg.QtGui.QPen:
    """Return the active high-contrast pen."""
    return pg.mkPen(
        (*_mix_rgb(_color_for_label(label), (255, 255, 255), 0.8), 255), width=5
    )


def _active_hover_pen(*, label: str | None = None) -> pg.QtGui.QPen:
    """Return the active hover pen."""
    return pg.mkPen(
        (*_mix_rgb(_color_for_label(label), (255, 255, 255), 0.92), 255), width=6
    )


def _selected_pen(*, interactive: bool, label: str | None = None) -> pg.QtGui.QPen:
    """Return the pen used for selected-but-not-active annotations."""
    alpha = 255 if interactive else 165
    return pg.mkPen(
        (*_mix_rgb(_color_for_label(label), (255, 255, 255), 0.35), alpha), width=4
    )


def _selected_hover_pen(
    *, interactive: bool, label: str | None = None
) -> pg.QtGui.QPen:
    """Return the hover pen used for selected-but-not-active annotations."""
    alpha = 255 if interactive else 165
    return pg.mkPen(
        (*_mix_rgb(_color_for_label(label), (255, 255, 255), 0.6), alpha), width=5
    )


class AnnotationHost(Protocol):
    """Host API required by the annotation overlay controller."""

    _patch: Any
    _axes: Any
    _plot_widget: Any
    _plot_item: Any

    def _set_cursor_readout(self, fields) -> None: ...


def _handle_modified_translate_drag(roi: pg.ROI, ev) -> bool:
    """Translate an ROI while Shift or Control is held.

    Bypasses pyqtgraph's default modifier map.
    """
    modifiers = ev.modifiers() if hasattr(ev, "modifiers") else Qt.NoModifier
    modified_drag = bool(
        modifiers
        & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
    ) or getattr(roi, "_shift_translate_active", False)
    if not modified_drag or ev.button() != Qt.MouseButton.LeftButton:
        return False
    if ev.isStart():
        if not getattr(roi, "translatable", False):
            ev.ignore()
            return True
        roi.setSelected(True)
        roi._moveStarted()
        roi._shift_translate_active = True
        roi._shift_translate_cursor_offset = roi.pos() - roi.mapToParent(
            ev.buttonDownPos()
        )
        ev.accept()
        return True
    if not getattr(roi, "_shift_translate_active", False):
        return True
    if ev.isFinish():
        roi._moveFinished()
        roi._shift_translate_active = False
        return True
    new_pos = roi.mapToParent(ev.pos()) + roi._shift_translate_cursor_offset
    roi.translate(new_pos - roi.pos(), finish=False)
    ev.accept()
    return True


class _AnnotationPointROI(pg.EllipseROI):
    """One draggable point annotation item."""

    sigDoubleClicked = Signal(object)  # noqa: N815

    def __init__(self, annotation_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.annotation_id = annotation_id
        self._group_drag_pending = False
        self._group_drag_active = False

    def mouseDragEvent(self, ev) -> None:
        """Remember when a Shift-drag should translate the whole selection."""
        if _handle_modified_translate_drag(self, ev):
            if ev.isFinish():
                self._group_drag_pending = self._group_drag_active
                self._group_drag_active = False
            elif ev.isStart():
                self._group_drag_active = True
            return
        super().mouseDragEvent(ev)

    def consume_group_drag_pending(self) -> bool:
        """Return and clear the pending Shift-drag state."""
        pending = self._group_drag_pending
        self._group_drag_pending = False
        return pending

    def mouseDoubleClickEvent(self, ev) -> None:
        self.sigDoubleClicked.emit(self)
        ev.accept()

    def paint(self, painter, *args) -> None:
        """Draw the point circle with a center crosshair for precise placement."""
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(self.currentPen)
        painter.setBrush(pg.mkBrush(0, 0, 0, 0))
        bounds = self.boundingRect()
        painter.drawEllipse(bounds)

        center = bounds.center()
        radius_x = bounds.width() / 2
        radius_y = bounds.height() / 2
        painter.drawLine(
            QLineF(
                QPointF(center.x() - radius_x, center.y()),
                QPointF(center.x() + radius_x, center.y()),
            )
        )
        painter.drawLine(
            QLineF(
                QPointF(center.x(), center.y() - radius_y),
                QPointF(center.x(), center.y() + radius_y),
            )
        )


class _AnnotationPointDisplayItem(pg.GraphicsObject):
    """Lightweight screen-stable item for non-active point annotations."""

    sigClicked = Signal(object, object)  # noqa: N815
    sigDoubleClicked = Signal(object)  # noqa: N815
    _HIT_PADDING = 8.0

    def __init__(
        self,
        annotation_id: str,
        *,
        pos: tuple[float, float],
        size: float = _POINT_TARGET_PX,
        pen=None,
        hoverPen=None,  # noqa: N803
    ) -> None:
        super().__init__()
        self.annotation_id = annotation_id
        self._size = float(size)
        self.currentPen = pen or _inactive_pen(interactive=True)
        self._hover_pen = hoverPen or self.currentPen
        self._hovered = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setPos(*pos)

    def boundingRect(self) -> QRectF:
        """Return the local paint bounds centered on the annotation point."""
        half = (self._size / 2) + self._HIT_PADDING
        return QRectF(-half, -half, half * 2, half * 2)

    def _paint_bounds(self) -> QRectF:
        """Return the visible dot bounds centered on the annotation point."""
        half = self._size / 2
        return QRectF(-half, -half, self._size, self._size)

    def shape(self) -> QPainterPath:
        """Return an elliptical hit region for hover and click handling."""
        path = QPainterPath()
        path.addEllipse(self.boundingRect())
        return path

    def paint(self, painter, *_args) -> None:
        """Draw the point circle with a center crosshair for precise placement."""
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(self._hover_pen if self._hovered else self.currentPen)
        painter.setBrush(pg.mkBrush(0, 0, 0, 0))
        bounds = self._paint_bounds()
        painter.drawEllipse(bounds)
        center = bounds.center()
        radius = bounds.width() / 2
        painter.drawLine(
            QLineF(
                QPointF(center.x() - radius, center.y()),
                QPointF(center.x() + radius, center.y()),
            )
        )
        painter.drawLine(
            QLineF(
                QPointF(center.x(), center.y() - radius),
                QPointF(center.x(), center.y() + radius),
            )
        )

    def setPen(self, pen) -> None:
        """Update the item pen and repaint."""
        self.currentPen = pen
        self.update()

    def setHoverPen(self, pen) -> None:
        """Update the item hover pen and repaint if needed."""
        self._hover_pen = pen
        if self._hovered:
            self.update()

    def getHandles(self) -> list:
        """Match the ROI API used by shared style-refresh paths."""
        return []

    def hoverEnterEvent(self, event) -> None:
        """Switch to the hover pen on pointer enter."""
        self._hovered = True
        self.update()
        event.accept()

    def hoverLeaveEvent(self, event) -> None:
        """Restore the normal pen on pointer exit."""
        self._hovered = False
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        """Emit click selection on left-button press."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.sigClicked.emit(self, event)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        """Emit metadata-edit activation on double-click."""
        self.sigDoubleClicked.emit(self)
        event.accept()


class _AnnotationRectROI(pg.RectROI):
    """One draggable/resizable box annotation item."""

    sigDoubleClicked = Signal(object)  # noqa: N815

    def __init__(self, annotation_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.annotation_id = annotation_id
        self._group_drag_pending = False
        self._group_drag_active = False

    def mouseDragEvent(self, ev) -> None:
        """Remember when a Shift-drag should translate the whole selection."""
        if _handle_modified_translate_drag(self, ev):
            if ev.isFinish():
                self._group_drag_pending = self._group_drag_active
                self._group_drag_active = False
            elif ev.isStart():
                self._group_drag_active = True
            return
        super().mouseDragEvent(ev)

    def consume_group_drag_pending(self) -> bool:
        """Return and clear the pending Shift-drag state."""
        pending = self._group_drag_pending
        self._group_drag_pending = False
        return pending

    def mouseDoubleClickEvent(self, ev) -> None:
        self.sigDoubleClicked.emit(self)
        ev.accept()


class _AnnotationLineROI(pg.LineSegmentROI):
    """One draggable/resizable line annotation item."""

    sigDoubleClicked = Signal(object)  # noqa: N815

    def __init__(self, annotation_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.annotation_id = annotation_id
        self._group_drag_pending = False
        self._group_drag_active = False

    def mouseDragEvent(self, ev) -> None:
        """Remember when a Shift-drag should translate the whole selection."""
        if _handle_modified_translate_drag(self, ev):
            if ev.isFinish():
                self._group_drag_pending = self._group_drag_active
                self._group_drag_active = False
            elif ev.isStart():
                self._group_drag_active = True
            return
        super().mouseDragEvent(ev)

    def consume_group_drag_pending(self) -> bool:
        """Return and clear the pending Shift-drag state."""
        pending = self._group_drag_pending
        self._group_drag_pending = False
        return pending

    def mouseDoubleClickEvent(self, ev) -> None:
        self.sigDoubleClicked.emit(self)
        ev.accept()

    def plot_endpoints(self) -> tuple[QPointF, QPointF]:
        """Return the current line endpoints in parent/plot coordinates."""
        start, end = self.endpoints
        return self.mapToParent(start.pos()), self.mapToParent(end.pos())


class _AnnotationPathROI(pg.ROI):
    """One transformable ROI wrapper for sampled path annotations."""

    sigDoubleClicked = Signal(object)  # noqa: N815

    def __init__(
        self,
        annotation_id: str,
        *,
        points: tuple[tuple[float, float], ...],
        roi_kind: str = "path",
        pen=None,
        hoverPen=None,  # noqa: N803
        handlePen=None,  # noqa: N803
        handleHoverPen=None,  # noqa: N803
        **kwargs,
    ) -> None:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        width = max(xmax - xmin, 1e-12)
        height = max(ymax - ymin, 1e-12)
        super().__init__(
            (xmin, ymin),
            size=(width, height),
            pen=pen,
            hoverPen=hoverPen,
            handlePen=handlePen,
            handleHoverPen=handleHoverPen,
            **kwargs,
        )
        self.annotation_id = annotation_id
        self.roi_kind = roi_kind
        self._normalized_points = tuple(
            ((float(x) - xmin) / width, (float(y) - ymin) / height) for x, y in points
        )
        self.handleSize = 14
        self._group_drag_pending = False
        self._group_drag_active = False

    def normalized_center(self) -> tuple[float, float]:
        """Return the ROI center in normalized local coordinates."""
        return (0.5, 0.5)

    def local_center(self) -> QPointF:
        """Return the ROI center in local coordinates."""
        size = self.size()
        return QPointF(float(size.x()) / 2.0, float(size.y()) / 2.0)

    def centroid_plot_pos(self) -> QPointF:
        """Return the current ROI center in parent/plot coordinates."""
        return self.mapToParent(self.local_center())

    def set_angle_about_center(
        self, angle: float, *, update: bool = True, finish: bool = True
    ) -> None:
        """Rotate the ROI around its geometric center."""
        self.setAngle(
            angle,
            center=self.normalized_center(),
            update=update,
            finish=finish,
        )

    def set_size_about_center(
        self, size: tuple[float, float], *, update: bool = True, finish: bool = True
    ) -> None:
        """Resize the ROI while keeping its geometric center fixed."""
        self.setSize(
            size,
            center=self.normalized_center(),
            update=update,
            finish=finish,
        )

    def _path(self) -> QPainterPath:
        """Return the current path in local ROI coordinates."""
        size = self.size()
        width = float(size.x())
        height = float(size.y())
        path = QPainterPath()
        first_x, first_y = self._normalized_points[0]
        path.moveTo(first_x * width, first_y * height)
        for point_x, point_y in self._normalized_points[1:]:
            path.lineTo(point_x * width, point_y * height)
        return path

    def _hit_path(self) -> QPainterPath:
        """Return the local path used for hover and click hit testing."""
        if self.roi_kind != "ellipse":
            return self._path()
        size = self.size()
        width = float(size.x())
        height = float(size.y())
        path = QPainterPath()
        path.addEllipse(QRectF(0.0, 0.0, width, height))
        return path

    def boundingRect(self) -> QRectF:
        """Return the painted path bounds with a small interaction margin."""
        return self.shape().boundingRect()

    def shape(self) -> QPainterPath:
        """Return a widened stroke path for hover and click handling."""
        stroker = QPainterPathStroker()
        stroker.setWidth(
            _local_hit_stroke_width(self, pen_width=float(self.currentPen.widthF()))
        )
        return stroker.createStroke(self._hit_path())

    def contains(self, point: QPointF) -> bool:
        """Limit hit testing to the visible stroked path, not the ROI bounds/handles."""
        return _scene_path_contains(
            self,
            self._hit_path(),
            local_pos=point,
            pen_width=float(self.currentPen.widthF()),
        )

    def paint(self, painter, *_args) -> None:
        """Draw the sampled path with the current transform-aware ROI state."""
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(self.currentPen)
        painter.setBrush(pg.mkBrush(0, 0, 0, 0))
        painter.drawPath(self._path())

    def plot_points(self) -> tuple[tuple[float, float], ...]:
        """Return the transformed path in parent plot coordinates."""
        size = self.size()
        width = float(size.x())
        height = float(size.y())
        return tuple(
            (
                float(self.mapToParent(QPointF(point_x * width, point_y * height)).x()),
                float(self.mapToParent(QPointF(point_x * width, point_y * height)).y()),
            )
            for point_x, point_y in self._normalized_points
        )

    def mouseDragEvent(self, ev) -> None:
        """Remember when a Shift-drag should translate the whole selection."""
        if _handle_modified_translate_drag(self, ev):
            if ev.isFinish():
                self._group_drag_pending = self._group_drag_active
                self._group_drag_active = False
            elif ev.isStart():
                self._group_drag_active = True
            return
        super().mouseDragEvent(ev)

    def consume_group_drag_pending(self) -> bool:
        """Return and clear the pending Shift-drag state."""
        pending = self._group_drag_pending
        self._group_drag_pending = False
        return pending

    def mouseDoubleClickEvent(self, ev) -> None:
        self.sigDoubleClicked.emit(self)
        ev.accept()


class _AnnotationPathDisplayItem(pg.GraphicsObject):
    """Static clickable path item for sampled multi-point annotations."""

    sigClicked = Signal(object, object)  # noqa: N815
    sigDoubleClicked = Signal(object)  # noqa: N815

    def __init__(
        self,
        annotation_id: str,
        *,
        points,
        pen=None,
        hover_pen=None,
        roi_kind: str = "path",
    ) -> None:
        super().__init__()
        self.annotation_id = annotation_id
        self.roi_kind = roi_kind
        self.currentPen = pen or _inactive_pen(interactive=True)
        self._hover_pen = hover_pen or self.currentPen
        self._hovered = False
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        self._width = max(xmax - xmin, 1e-12)
        self._height = max(ymax - ymin, 1e-12)
        self._normalized_points = tuple(
            (
                (float(point_x) - xmin) / self._width,
                (float(point_y) - ymin) / self._height,
            )
            for point_x, point_y in points
        )
        self.setPos(xmin, ymin)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def boundingRect(self) -> QRectF:
        """Return the painted path bounds with a small interaction margin."""
        return self.shape().boundingRect()

    def _path(self) -> QPainterPath:
        """Return the current path in local item coordinates."""
        path = QPainterPath()
        first_x, first_y = self._normalized_points[0]
        path.moveTo(first_x * self._width, first_y * self._height)
        for point_x, point_y in self._normalized_points[1:]:
            path.lineTo(point_x * self._width, point_y * self._height)
        return path

    def _hit_path(self) -> QPainterPath:
        """Return the local path used for hover and click hit testing."""
        if self.roi_kind != "ellipse":
            return self._path()
        path = QPainterPath()
        path.addEllipse(QRectF(0.0, 0.0, self._width, self._height))
        return path

    def _hit_contains(self, local_pos: QPointF) -> bool:
        """Return True when one local point should count as a hover/click hit."""
        return _scene_path_contains(
            self,
            self._hit_path(),
            local_pos=local_pos,
            pen_width=float(self.currentPen.widthF()),
        )

    def shape(self) -> QPainterPath:
        """Return a widened stroke path for hover and click handling."""
        stroker = QPainterPathStroker()
        stroker.setWidth(
            _local_hit_stroke_width(self, pen_width=float(self.currentPen.widthF()))
        )
        return stroker.createStroke(self._hit_path())

    def contains(self, point: QPointF) -> bool:
        """Limit scene hit testing to the visible stroked path."""
        return self._hit_contains(point)

    def paint(self, painter, *_args) -> None:
        """Draw the sampled polyline with the current hover-aware pen."""
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(self._hover_pen if self._hovered else self.currentPen)
        painter.setBrush(pg.mkBrush(0, 0, 0, 0))
        painter.drawPath(self._path())

    def setPen(self, pen) -> None:
        """Update the line pen and repaint."""
        self.prepareGeometryChange()
        self.currentPen = pen
        self.update()

    def setHoverPen(self, pen) -> None:
        """Update the hover pen and repaint if active."""
        self._hover_pen = pen
        if self._hovered:
            self.update()

    def getHandles(self) -> list:
        """Match the ROI API used by shared style-refresh paths."""
        return []

    def hoverEnterEvent(self, event) -> None:
        """Switch to the hover pen on pointer enter."""
        hovered = self._hit_contains(event.pos())
        self._hovered = hovered
        self.update()
        if hovered:
            event.accept()
        else:
            event.ignore()

    def hoverMoveEvent(self, event) -> None:
        """Track hover only while the pointer stays near the visible path."""
        hovered = self._hit_contains(event.pos())
        if hovered != self._hovered:
            self._hovered = hovered
            self.update()
        if hovered:
            event.accept()
        else:
            event.ignore()

    def hoverLeaveEvent(self, event) -> None:
        """Restore the normal pen on pointer exit."""
        self._hovered = False
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        """Emit click selection on left-button press."""
        if event.button() != Qt.MouseButton.LeftButton or not self._hit_contains(
            event.pos()
        ):
            event.ignore()
            return
        self.sigClicked.emit(self, event)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        """Emit metadata-edit activation on double-click."""
        if not self._hit_contains(event.pos()):
            event.ignore()
            return
        self.sigDoubleClicked.emit(self)
        event.accept()


class AnnotationOverlayController:
    """Owns floating toolbox UI, annotation items, and edit interactions."""

    def __init__(
        self,
        host: AnnotationHost,
        *,
        editor_class: type[QDialog] = AnnotationEditorDialog,
        tools: tuple[str, ...] = (
            "annotation_select",
            "point",
            "line",
            "box",
            "ellipse",
            "hyperbola",
            "delete",
        ),
        default_tool: str | None = None,
        on_tool_changed: Callable[[str], None] | None = None,
        on_annotation_set_changed: Callable[[], None] | None = None,
    ) -> None:
        self._host = host
        self._editor_class = editor_class
        self._tools = tools
        self._on_tool_changed = on_tool_changed
        self._on_annotation_set_changed = on_annotation_set_changed
        self._interactive = True
        self.tool: str | None = default_tool
        self.layer_active = False
        self.toolbox_hidden = True
        self.annotation_set: AnnotationSet | None = None
        self.annotation_items: dict[str, pg.GraphicsObject] = {}
        self.active_annotation_id: str | None = None
        self.selected_annotation_ids: set[str] = set()
        self.draw_start: tuple[float, float] | None = None
        self.preview_item: pg.GraphicsObject | pg.PlotDataItem | None = None
        self._consume_next_release = False
        self._group_drag_state: dict[str, Any] | None = None
        self._point_drag_state: dict[str, Any] | None = None
        self._snap_to_annotations = False
        self._applying_live_snap = False
        self._slice_coords: dict[str, Any] = {}

        self.toolbox = AnnotationToolbox(self._host._plot_widget, tools=self._tools)
        self.toolbox.toolChanged.connect(self.set_tool)
        self.toolbox.hideRequested.connect(self.hide_toolbox)
        self.toolbox.snapToggled.connect(self.set_snap_to_annotations)
        self.tool_buttons = self.toolbox.tool_buttons
        self._install_viewbox_hooks()
        self.position_toolbox()
        if default_tool is None:
            self.clear_active_tool(notify=False)
        else:
            self.set_tool(default_tool, notify=False)

    def _notify_annotation_set_changed(self) -> None:
        """Notify the host that local annotation state changed."""
        if self._on_annotation_set_changed is not None:
            self._on_annotation_set_changed()

    def _install_viewbox_hooks(self) -> None:
        """Track host view-range changes for screen-stable overlay items."""
        view_box = getattr(self._host._plot_item, "vb", None)
        if view_box is None:
            return
        view_box.sigRangeChanged.connect(self._on_view_range_changed)

    def handle_event_filter(self, obj, event) -> bool:
        """Handle toolbox positioning and annotation gestures."""
        if obj is self._host._plot_widget and event.type() == QEvent.Type.Resize:
            self.position_toolbox()
            return False
        if obj is self._host._plot_widget.scene() and self._interactive:
            return self.handle_scene_event(event)
        return False

    def handle_key_press(self, event) -> bool:
        """Handle delete/cancel keyboard shortcuts for annotation editing."""
        if not self._interactive:
            return False
        if event.key() == Qt.Key_Escape and self.draw_start is not None:
            self.cancel_draw()
            event.accept()
            return True
        if event.key() == Qt.Key_Escape and self.selected_annotation_ids:
            self.set_selected_annotations(set())
            event.accept()
            return True
        if Qt.Key_0 <= event.key() <= Qt.Key_9 and self.selected_annotation_ids:
            label = None if event.key() == Qt.Key_0 else str(event.key() - Qt.Key_0)
            if self.assign_label_to_selection(label):
                event.accept()
                return True
        if event.key() == Qt.Key_E and self.selected_annotation_ids:
            if self.fit_ellipse_from_selection():
                event.accept()
                return True
        if event.key() == Qt.Key_H and self.selected_annotation_ids:
            if self.fit_hyperbola_from_selection():
                event.accept()
                return True
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.active_annotation_id is not None:
                self.delete_annotation(self.active_annotation_id)
                event.accept()
                return True
            if self.selected_annotation_ids:
                for annotation_id in tuple(self.selected_annotation_ids):
                    self.delete_annotation(annotation_id)
                event.accept()
                return True
        return False

    def assign_label_to_selection(self, label: str | None) -> bool:
        """Assign one persisted label to the current annotation selection."""
        if self.annotation_set is None or not self.selected_annotation_ids:
            return False
        selected = set(self.selected_annotation_ids)
        normalized_label = annotation_label_from_slot(label, load_annotation_config())
        changed = False
        updated_annotations: list[Annotation] = []
        for annotation in self.annotation_set.annotations:
            if annotation.id not in selected:
                updated_annotations.append(annotation)
                continue
            if annotation.label == normalized_label:
                updated_annotations.append(annotation)
                continue
            updated_annotations.append(
                annotation.model_copy(update={"label": normalized_label})
            )
            changed = True
        if not changed:
            return False
        self.annotation_set = self.annotation_set.model_copy(
            update={"annotations": tuple(updated_annotations)}
        )
        self.rebuild_items()
        self._notify_annotation_set_changed()
        return True

    def _ensure_annotation_identity_config(self):
        """Return identity config, prompting until both fields are defined."""
        config = load_annotation_config()
        while not (config.annotator and config.organization):
            dialog = AnnotationSettingsDialog(config, self._host)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            config = dialog.config()
            if config.annotator and config.organization:
                save_annotation_config(config)
                break
        return config

    def _annotation_identity_fields(self) -> dict[str, str | None] | None:
        """Return current global identity fields copied onto new annotations."""
        config = self._ensure_annotation_identity_config()
        if config is None:
            return None
        return {
            "annotator": config.annotator or None,
            "organization": config.organization or None,
        }

    def _extend_geometry_with_slice(self, geometry):
        """Extend geometry dims with current slice coordinate constraints."""
        if not self._slice_coords:
            return geometry
        if isinstance(geometry, PointGeometry):
            return PointGeometry(coords={**geometry.coords, **self._slice_coords})
        if isinstance(geometry, BoxGeometry):
            return BoxGeometry(
                bounds={
                    **geometry.bounds,
                    **{
                        dim: CoordRange(min=value, max=value)
                        for dim, value in self._slice_coords.items()
                    },
                },
            )
        if isinstance(geometry, PathGeometry):
            return PathGeometry(
                points=tuple(
                    {**point, **self._slice_coords} for point in geometry.points
                ),
            )
        return geometry

    def _annotation_matches_slice(self, annotation: Annotation) -> bool:
        """Return True if the annotation is visible at the current slice position."""
        if not self._slice_coords:
            return True
        geom = annotation.geometry
        geom_dims = geometry_dims(geom)
        if not geom_dims:
            return True  # SpanGeometry or unknown — no slice constraint
        for slice_dim, current_val in self._slice_coords.items():
            if slice_dim not in geom_dims:
                continue  # geometry has no constraint on this dim → always visible
            stored_val = geometry_coord(geom, slice_dim)
            if stored_val != current_val:
                return False
        return True

    def _new_annotation(
        self,
        *,
        geometry,
        semantic_type: str = "generic",
        properties: dict[str, Any] | None = None,
    ) -> Annotation | None:
        """Build one new annotation with shared default identity metadata."""
        identity_fields = self._annotation_identity_fields()
        if identity_fields is None:
            return None
        return Annotation(
            id=f"annotation-{uuid4().hex[:8]}",
            geometry=self._extend_geometry_with_slice(geometry),
            semantic_type=semantic_type,
            properties=properties or {},
            **identity_fields,
        )

    def fit_shape_from_selection(self, shape: str) -> bool:
        """Fit one named shape from the currently selected point annotations."""
        handlers = {
            "line": self.fit_line_from_selection,
            "ellipse": self.fit_ellipse_from_selection,
            "square": self.fit_square_from_selection,
            "hyperbola": self.fit_hyperbola_from_selection,
        }
        handler = handlers.get(shape)
        if handler is None:
            raise ValueError(f"unsupported fitted shape {shape!r}")
        return handler()

    def build_empty_set(self) -> AnnotationSet | None:
        """Return one empty annotation set for the current host dims."""
        dims = self.annotation_dims()
        if dims is None:
            return None
        return AnnotationSet(
            dims=dims,
            annotations=(),
            provenance={"data_kind": "patch", "dims": dims},
        )

    def annotation_dims(self) -> tuple[str, ...] | None:
        """Return annotation dimensions: plot dims first, then slice dims."""
        axes = self._host._axes
        if axes is None:
            return None
        dims: list[str] = []
        for dim in (axes.x_dim, axes.y_dim, *tuple(self._slice_coords.keys())):
            if dim not in dims:
                dims.append(dim)
        return tuple(dims)

    @property
    def slice_coords(self) -> dict[str, Any]:
        """Current slice coordinate values keyed by dim name."""
        return self._slice_coords

    @slice_coords.setter
    def slice_coords(self, value: dict[str, Any]) -> None:
        normalized = {k: normalize_coord_value(v) for k, v in value.items()}
        if normalized == self._slice_coords:
            return
        self._slice_coords = normalized
        self.ensure_annotation_set()
        self.rebuild_items()

    def ensure_annotation_set(self) -> None:
        """Ensure an annotation set exists for the host's current dims."""
        dims = self.annotation_dims()
        if dims is None:
            self.annotation_set = None
            return
        if self.annotation_set is not None and set(self.annotation_set.dims) == set(
            dims
        ):
            if self.annotation_set.dims != dims:
                self.annotation_set = self.annotation_set.model_copy(
                    update={
                        "dims": dims,
                        "provenance": {**self.annotation_set.provenance, "dims": dims},
                    }
                )
            return
        self.clear_annotation_items()
        self.annotation_set = self.build_empty_set()
        self.active_annotation_id = None
        self.selected_annotation_ids.clear()

    def clear_annotation_items(self) -> None:
        """Remove all overlay items from the host plot."""
        for item in self.annotation_items.values():
            self._host._plot_item.removeItem(item)
        self.annotation_items.clear()
        self.clear_preview()

    def clear_annotations(self) -> None:
        """Clear all annotations and overlay state."""
        self.clear_annotation_items()
        self.annotation_set = None
        self.active_annotation_id = None
        self.selected_annotation_ids.clear()

    def rebuild_items(self) -> None:
        """Re-render overlay items from the current annotation set."""
        self.clear_annotation_items()
        if self.annotation_set is None:
            return
        dims = self.annotation_dims()
        if dims is None or set(self.annotation_set.dims) != set(dims):
            return
        for annotation in self.annotation_set.annotations:
            if not self._annotation_matches_slice(annotation):
                continue
            item = self._build_item_for_annotation(annotation)
            if item is None:
                continue
            self.annotation_items[annotation.id] = item
            self._host._plot_item.addItem(item)
        available_ids = set(self.annotation_items)
        self.selected_annotation_ids &= available_ids
        if self.active_annotation_id not in available_ids:
            self.active_annotation_id = None
        self.refresh_item_styles()

    def activate_layer(self) -> None:
        """Activate the annotation layer and show the toolbox."""
        self.layer_active = True
        if self.toolbox_hidden:
            self.show_toolbox()

    def show_toolbox(self) -> None:
        """Show the floating toolbox."""
        self.toolbox_hidden = False
        self.toolbox.show()
        self.position_toolbox()

    def hide_toolbox(self) -> None:
        """Hide the floating toolbox."""
        self.toolbox_hidden = True
        self.toolbox.hide()

    @property
    def interactive(self) -> bool:
        """Return True when annotation items should respond to user input."""
        return self._interactive

    def set_interactive(self, interactive: bool) -> None:
        """Enable or disable annotation interaction while keeping items visible."""
        self._interactive = interactive
        if not interactive:
            self.cancel_draw()
        self.refresh_item_styles()
        for item in self.annotation_items.values():
            item.setAcceptedMouseButtons(
                Qt.MouseButton.LeftButton if interactive else Qt.MouseButton.NoButton
            )

    def set_tool(self, tool: str | None, *, notify: bool = True) -> None:
        """Switch the active annotation tool."""
        if tool == "annotation_select":
            self.enter_annotation_selection_mode(notify=notify)
            return
        if tool is None:
            self.clear_active_tool(notify=notify)
            return
        if tool != self.tool:
            self.cancel_draw()
        self.tool = tool
        button = self.tool_buttons.get(tool)
        if button is not None:
            button.setChecked(True)
        if notify and self._on_tool_changed is not None:
            self._on_tool_changed(tool)

    def enter_annotation_selection_mode(self, *, notify: bool = True) -> None:
        """Activate the arrow tool for annotation selection gestures."""
        self.cancel_draw()
        self.tool = "annotation_select"
        self.toolbox.set_tool("annotation_select")
        if notify and self._on_tool_changed is not None:
            self._on_tool_changed("annotation_select")

    def clear_active_tool(self, *, notify: bool = True) -> None:
        """Return to the neutral no-annotation-tool state."""
        self.cancel_draw()
        self.tool = None
        self.toolbox.clear_tool()
        if notify and self._on_tool_changed is not None:
            self._on_tool_changed("")

    def set_snap_to_annotations(self, enabled: bool) -> None:
        """Enable or disable snapping to existing annotation anchors."""
        self._snap_to_annotations = bool(enabled)
        self.toolbox.set_snap_enabled(self._snap_to_annotations)

    def clear_tool_selection(self) -> None:
        """Clear the visible toolbox selection without changing the remembered tool."""
        self.toolbox.clear_tool()

    def is_annotation_tool(self, tool: str | None = None) -> bool:
        """Return True when the given tool name is an annotation-editing tool."""
        current_tool = self.tool if tool is None else tool
        return current_tool in _ANNOTATION_TOOLS

    def in_annotation_selection_mode(self) -> bool:
        """Return True when annotation interactions should select, not draw."""
        return self.tool == "annotation_select"

    def scene_to_plot(self, scene_pos) -> tuple[float, float] | None:
        """Map a scene position into plot coordinates when inside the plot."""
        if not self._host._plot_item.sceneBoundingRect().contains(scene_pos):
            return None
        view_pos = self._host._plot_item.vb.mapSceneToView(scene_pos)
        return float(view_pos.x()), float(view_pos.y())

    def _activate_current_tool_from_plot_pos(
        self, plot_pos: tuple[float, float]
    ) -> bool:
        """Run the current annotation tool from one plot-space click position."""
        self.activate_layer()
        if self.tool == "point":
            self.create_point_annotation(*plot_pos)
            return True
        if self.tool == "line":
            self.draw_start = plot_pos
            self.start_preview(plot_pos)
            return True
        if self.tool == "ellipse":
            self.create_default_ellipse_annotation(*plot_pos)
            return True
        if self.tool == "hyperbola":
            self.create_default_hyperbola_annotation(*plot_pos)
            return True
        if self.tool == "box":
            self.create_default_box_annotation(*plot_pos)
            return True
        return False

    def handle_scene_event(self, event) -> bool:
        """Drive annotation draw gestures from scene events."""
        if not self._interactive:
            return False
        if self._host._axes is None or self._host._patch is None:
            return False
        event_type = event.type()
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        if event_type == QEvent.Type.GraphicsSceneMouseDoubleClick:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if not self._host._plot_item.sceneBoundingRect().contains(event.scenePos()):
                return False
            plot_pos = self.scene_to_plot(event.scenePos())
            if plot_pos is None:
                return False
            if self._activate_current_tool_from_plot_pos(plot_pos):
                self._consume_next_release = True
                event.accept()
                return True
            return False
        if event_type == QEvent.Type.GraphicsSceneMousePress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if not self._host._plot_item.sceneBoundingRect().contains(event.scenePos()):
                return False
            plot_pos = self.scene_to_plot(event.scenePos())
            if plot_pos is None:
                return False
            if self.tool in {"point", "line"} and self.draw_start is not None:
                self.activate_layer()
                self.finish_draw(plot_pos)
                self._consume_next_release = True
                event.accept()
                return True
            item_at_pos = self._annotation_item_at_scene_pos(event.scenePos())
            if item_at_pos is None and modifiers & Qt.KeyboardModifier.ShiftModifier:
                item_at_pos = self._point_item_near_plot_pos(plot_pos)
            clicked_annotation = (
                None
                if item_at_pos is None
                else self.annotation_by_id(item_at_pos.annotation_id)
            )
            if (
                self.in_annotation_selection_mode()
                and clicked_annotation is not None
                and isinstance(clicked_annotation.geometry, PointGeometry)
            ):
                drag_ids = (
                    set(self.selected_annotation_ids)
                    if (
                        modifiers & Qt.KeyboardModifier.ShiftModifier
                        and item_at_pos.annotation_id in self.selected_annotation_ids
                        and len(self.selected_annotation_ids) > 1
                    )
                    else {item_at_pos.annotation_id}
                )
                self._point_drag_state = {
                    "start_plot": plot_pos,
                    "annotation_id": item_at_pos.annotation_id,
                    "drag_ids": drag_ids,
                    "original_annotations": {
                        annotation.id: annotation
                        for annotation in (self.annotation_set.annotations or ())
                        if annotation.id in drag_ids
                    }
                    if self.annotation_set is not None
                    else {},
                }
                event.accept()
                return True
            if (
                modifiers & Qt.KeyboardModifier.ShiftModifier
                and item_at_pos is not None
                and item_at_pos.annotation_id in self.selected_annotation_ids
                and len(self.selected_annotation_ids) > 1
            ):
                self._group_drag_state = {
                    "start_plot": plot_pos,
                    "selected_ids": set(self.selected_annotation_ids),
                    "original_annotations": {
                        annotation.id: annotation
                        for annotation in (self.annotation_set.annotations or ())
                        if annotation.id in self.selected_annotation_ids
                    }
                    if self.annotation_set is not None
                    else {},
                }
                event.accept()
                return True
            if item_at_pos is not None:
                return False
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                if self.in_annotation_selection_mode():
                    self.create_point_annotation(*plot_pos)
                    event.accept()
                    return True
                if self.tool == "point":
                    self.create_point_annotation(*plot_pos)
                    event.accept()
                    return True
                if self._activate_current_tool_from_plot_pos(plot_pos):
                    event.accept()
                    return True
            if self.in_annotation_selection_mode():
                self.activate_layer()
                self.draw_start = plot_pos
                self.start_preview(plot_pos)
                event.accept()
                return True
            return False
        if event_type == QEvent.Type.GraphicsSceneMouseMove:
            if self._point_drag_state is not None:
                plot_pos = self.scene_to_plot(event.scenePos())
                if plot_pos is not None and self._host._axes is not None:
                    delta_x = float(
                        plot_pos[0] - self._point_drag_state["start_plot"][0]
                    )
                    delta_y = float(
                        plot_pos[1] - self._point_drag_state["start_plot"][1]
                    )
                    self._preview_drag_translation(
                        self._point_drag_state["original_annotations"],
                        delta_x,
                        delta_y,
                    )
                event.accept()
                return True
            if self._group_drag_state is not None:
                plot_pos = self.scene_to_plot(event.scenePos())
                if plot_pos is not None and self._host._axes is not None:
                    delta_x = float(
                        plot_pos[0] - self._group_drag_state["start_plot"][0]
                    )
                    delta_y = float(
                        plot_pos[1] - self._group_drag_state["start_plot"][1]
                    )
                    self._preview_drag_translation(
                        self._group_drag_state["original_annotations"],
                        delta_x,
                        delta_y,
                    )
                event.accept()
                return True
            if self.draw_start is None:
                return False
            plot_pos = self.scene_to_plot(event.scenePos())
            if plot_pos is None:
                return False
            self.update_preview(plot_pos)
            event.accept()
            return True
        if event_type == QEvent.Type.GraphicsSceneMouseRelease:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if self._consume_next_release:
                self._consume_next_release = False
                event.accept()
                return True
            if self._point_drag_state is not None:
                if not self._host._plot_item.sceneBoundingRect().contains(
                    event.scenePos()
                ):
                    self._point_drag_state = None
                    return False
                plot_pos = self.scene_to_plot(event.scenePos())
                if plot_pos is None:
                    self._point_drag_state = None
                    return False
                delta_x = float(plot_pos[0] - self._point_drag_state["start_plot"][0])
                delta_y = float(plot_pos[1] - self._point_drag_state["start_plot"][1])
                point_drag_state = self._point_drag_state
                annotation_id = str(point_drag_state["annotation_id"])
                drag_ids = set(point_drag_state["drag_ids"])
                self._point_drag_state = None
                if (
                    self.annotation_set is not None
                    and self._host._axes is not None
                    and (abs(delta_x) > 0.0 or abs(delta_y) > 0.0)
                ):
                    updated_annotations = [
                        self._translate_annotation_by_plot_delta(
                            point_drag_state["original_annotations"].get(
                                annotation.id, annotation
                            ),
                            delta_x,
                            delta_y,
                            self._host._axes,
                        )
                        if annotation.id in drag_ids
                        else annotation
                        for annotation in self.annotation_set.annotations
                    ]
                    self._store_annotation_set(updated_annotations)
                    self.selected_annotation_ids = drag_ids
                    self.active_annotation_id = annotation_id
                    self.refresh_item_styles()
                else:
                    self.set_active_annotation(annotation_id)
                event.accept()
                return True
            if self._group_drag_state is not None:
                if not self._host._plot_item.sceneBoundingRect().contains(
                    event.scenePos()
                ):
                    self._group_drag_state = None
                    return False
                plot_pos = self.scene_to_plot(event.scenePos())
                if plot_pos is None:
                    self._group_drag_state = None
                    return False
                delta_x = float(plot_pos[0] - self._group_drag_state["start_plot"][0])
                delta_y = float(plot_pos[1] - self._group_drag_state["start_plot"][1])
                group_drag_state = self._group_drag_state
                selected_ids = set(group_drag_state["selected_ids"])
                self._group_drag_state = None
                if (
                    self.annotation_set is not None
                    and self._host._axes is not None
                    and (abs(delta_x) > 0.0 or abs(delta_y) > 0.0)
                ):
                    updated_annotations = [
                        self._translate_annotation_by_plot_delta(
                            group_drag_state["original_annotations"].get(
                                annotation.id, annotation
                            ),
                            delta_x,
                            delta_y,
                            self._host._axes,
                        )
                        if annotation.id in selected_ids
                        else annotation
                        for annotation in self.annotation_set.annotations
                    ]
                    self._store_annotation_set(updated_annotations)
                event.accept()
                return True
            if self.draw_start is not None and self.in_annotation_selection_mode():
                plot_pos = self.scene_to_plot(event.scenePos())
                if plot_pos is None:
                    self.cancel_draw()
                    return False
                self.finish_selection(plot_pos)
                event.accept()
                return True
            if not self._host._plot_item.sceneBoundingRect().contains(event.scenePos()):
                self.cancel_draw()
                return False
            item_at_pos = self._annotation_item_at_scene_pos(event.scenePos())
            if item_at_pos is not None:
                return False
            plot_pos = self.scene_to_plot(event.scenePos())
            if plot_pos is None:
                self.cancel_draw()
                return False
            self.activate_layer()
            self.set_active_annotation(None)
        return False

    def start_preview(self, start: tuple[float, float]) -> None:
        """Start a temporary preview item for selection or drawing."""
        self.clear_preview()
        x0, y0 = start
        preview_pen = pg.mkPen((55, 125, 255, 200), width=2, style=Qt.PenStyle.DashLine)
        if self.in_annotation_selection_mode():
            preview = pg.RectROI(
                [x0, y0],
                [1e-12, 1e-12],
                movable=False,
                resizable=False,
                rotatable=False,
                pen=preview_pen,
            )
            self._host._plot_item.addItem(preview)
            self.preview_item = preview
            return
        if self.tool == "line":
            line_preview_pen = _active_pen()
            preview = pg.PlotDataItem(
                [x0, x0],
                [y0, y0],
                pen=line_preview_pen,
                symbol="o",
                symbolSize=10,
                symbolPen=line_preview_pen,
                symbolBrush=pg.mkBrush(0, 0, 0, 0),
            )
            self._host._plot_item.addItem(preview)
            self.preview_item = preview
            return
        if self.tool == "point":
            preview = _AnnotationPointDisplayItem(
                "preview-point",
                pos=(x0, y0),
                size=self._point_display_size(),
                pen=_active_pen(),
                hoverPen=_active_hover_pen(),
            )
            self._host._plot_item.addItem(preview)
            self.preview_item = preview
            return
        if self.tool == "ellipse":
            xs, ys = self._sample_ellipse_plot_points(
                self._ellipse_parameters_from_drag(start, start)
            )
            preview = pg.PlotDataItem(xs, ys, pen=preview_pen)
            self._host._plot_item.addItem(preview)
            self.preview_item = preview
            return
        if self.tool == "hyperbola":
            xs, ys = self._sample_hyperbola_plot_points(
                self._hyperbola_parameters_from_drag(start, start)
            )
            preview = pg.PlotDataItem(xs, ys, pen=preview_pen)
            self._host._plot_item.addItem(preview)
            self.preview_item = preview
            return
        if self.tool == "box":
            preview = pg.RectROI(
                [x0, y0],
                [1e-12, 1e-12],
                movable=False,
                resizable=False,
                rotatable=False,
                pen=preview_pen,
            )
            self._host._plot_item.addItem(preview)
            self.preview_item = preview

    def update_preview(self, end: tuple[float, float]) -> None:
        """Update the temporary preview during a draw gesture."""
        if self.draw_start is None or self.preview_item is None:
            return
        x0, y0 = self.draw_start
        x1, y1 = end
        if self.tool in {"line", "box"}:
            x1, y1 = self._snap_plot_pos((x1, y1))
        if self.tool == "point" and isinstance(
            self.preview_item, _AnnotationPointDisplayItem
        ):
            x1, y1 = self._snap_plot_pos((x1, y1))
            self.preview_item.setPos(x1, y1)
            return
        if self.tool == "line" and isinstance(self.preview_item, pg.PlotDataItem):
            self.preview_item.setData([x0, x1], [y0, y1])
            return
        if self.tool == "ellipse" and isinstance(self.preview_item, pg.PlotDataItem):
            xs, ys = self._sample_ellipse_plot_points(
                self._ellipse_parameters_from_drag((x0, y0), (x1, y1))
            )
            self.preview_item.setData(xs, ys)
            return
        if self.tool == "hyperbola" and isinstance(self.preview_item, pg.PlotDataItem):
            xs, ys = self._sample_hyperbola_plot_points(
                self._hyperbola_parameters_from_drag((x0, y0), (x1, y1))
            )
            self.preview_item.setData(xs, ys)
            return
        if (self.in_annotation_selection_mode() or self.tool == "box") and isinstance(
            self.preview_item, pg.ROI
        ):
            xmin, xmax = sorted((x0, x1))
            ymin, ymax = sorted((y0, y1))
            self.preview_item.setPos((xmin, ymin))
            self.preview_item.setSize(
                (max(xmax - xmin, 1e-12), max(ymax - ymin, 1e-12))
            )

    def finish_draw(self, end: tuple[float, float]) -> None:
        """Finish a line or box draw gesture."""
        start = self.draw_start
        self.cancel_draw(clear_only=True)
        if start is None:
            return
        if self.tool == "point":
            self.create_point_annotation(*end)
        elif self.tool == "line":
            self.create_line_annotation(start, end)
        elif self.tool == "ellipse":
            self.create_ellipse_annotation(start, end)
        elif self.tool == "hyperbola":
            self.create_hyperbola_annotation(start, end)
        elif self.tool == "box":
            self.create_box_annotation(start, end)

    def finish_selection(self, end: tuple[float, float]) -> None:
        """Select annotations intersecting the dragged selection box."""
        start = self.draw_start
        self.cancel_draw(clear_only=True)
        if start is None:
            return
        scene_rect = self._selection_scene_rect(start, end)
        selected_ids = {
            annotation_id
            for annotation_id, item in self.annotation_items.items()
            if self._item_matches_selection_rect(item, scene_rect)
        }
        self.set_selected_annotations(selected_ids)

    def _item_matches_selection_rect(self, item, scene_rect: QRectF) -> bool:
        """Return True when an annotation item should be included in box selection."""
        if isinstance(item, _AnnotationPointDisplayItem | _AnnotationPointROI):
            center = item.mapToScene(item.boundingRect().center())
            return scene_rect.contains(center)
        return scene_rect.intersects(item.sceneBoundingRect())

    def cancel_draw(self, *, clear_only: bool = False) -> None:
        """Cancel the current draw gesture."""
        self.draw_start = None
        self._consume_next_release = False
        self.clear_preview()
        if not clear_only:
            self._host._set_cursor_readout(None)

    def clear_preview(self) -> None:
        """Remove the current draw preview."""
        if self.preview_item is None:
            return
        self._host._plot_item.removeItem(self.preview_item)
        self.preview_item = None

    def annotation_by_id(self, annotation_id: str) -> Annotation | None:
        """Return one annotation from the current set."""
        if self.annotation_set is None:
            return None
        for annotation in self.annotation_set.annotations:
            if annotation.id == annotation_id:
                return annotation
        return None

    def set_active_annotation(self, annotation_id: str | None) -> None:
        """Switch active annotation state and refresh item styling."""
        old_active = self.active_annotation_id
        old_selected = set(self.selected_annotation_ids)
        self.active_annotation_id = annotation_id
        self.selected_annotation_ids = (
            {annotation_id} if annotation_id is not None else set()
        )
        if self._point_ids_require_rebuild(
            old_selected | self.selected_annotation_ids | {old_active, annotation_id}
        ):
            self.rebuild_items()
            return
        self.refresh_item_styles()

    def set_selected_annotations(self, annotation_ids: set[str]) -> None:
        """Highlight a set of selected annotations."""
        old_active = self.active_annotation_id
        old_selected = set(self.selected_annotation_ids)
        selected = {
            annotation_id
            for annotation_id in annotation_ids
            if annotation_id in self.annotation_items
        }
        self.selected_annotation_ids = selected
        self.active_annotation_id = next(iter(selected)) if len(selected) == 1 else None
        if self._point_ids_require_rebuild(
            old_selected | selected | {old_active, self.active_annotation_id}
        ):
            self.rebuild_items()
            return
        self.refresh_item_styles()

    def _point_ids_require_rebuild(self, annotation_ids) -> bool:
        """Return True when selection changes swap render/edit implementations."""
        for annotation_id in annotation_ids:
            if annotation_id is None:
                continue
            annotation = self.annotation_by_id(annotation_id)
            geometry = None if annotation is None else annotation.geometry
            if isinstance(geometry, PointGeometry):
                return True
            if isinstance(geometry, PathGeometry) and len(geometry.points) > 2:
                return True
        return False

    def store_annotation(self, annotation: Annotation) -> None:
        """Insert or replace one annotation in the current set."""
        self.ensure_annotation_set()
        if self.annotation_set is None:
            return
        self.annotation_set = upsert_annotation(self.annotation_set, annotation)
        self.rebuild_items()
        self.set_active_annotation(annotation.id)
        self._notify_annotation_set_changed()

    def _store_annotation_set(self, annotations: list[Annotation]) -> None:
        """Replace the full annotation collection without changing selection state."""
        if self.annotation_set is None:
            return
        self.annotation_set = replace_annotation_sequence(
            self.annotation_set, annotations
        )
        self.rebuild_items()
        self._notify_annotation_set_changed()

    def delete_annotation(self, annotation_id: str) -> None:
        """Delete one annotation from the current set."""
        if self.annotation_set is None:
            return
        self.annotation_set = delete_annotation_by_id(
            self.annotation_set, annotation_id
        )
        self.rebuild_items()
        self.set_active_annotation(None)
        self._notify_annotation_set_changed()

    def edit_annotation(self, annotation_id: str) -> bool:
        """Open the modal editor and update the chosen annotation."""
        annotation = self.annotation_by_id(annotation_id)
        if annotation is None:
            return False
        dialog = self._editor_class(annotation, self._host)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
        self.store_annotation(annotation.model_copy(update=values))
        return True

    def create_point_annotation(self, plot_x: float, plot_y: float) -> None:
        """Create one point annotation from plot coordinates."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        plot_x, plot_y = self._snap_plot_pos((plot_x, plot_y))
        annotation = self._new_annotation(
            geometry=PointGeometry(
                coords={
                    axes.x_dim: map_plot_value_to_coord(
                        plot_x, axes.x_plot, axes.x_coord
                    ),
                    axes.y_dim: map_plot_value_to_coord(
                        plot_y, axes.y_plot, axes.y_coord
                    ),
                },
            ),
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_box_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Create one box annotation from plot coordinates."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        end = self._snap_plot_pos(end)
        x0, x1 = sorted((start[0], end[0]))
        y0, y1 = sorted((start[1], end[1]))
        if abs(x1 - x0) < 1e-12 or abs(y1 - y0) < 1e-12:
            return
        annotation = self._new_annotation(
            geometry=BoxGeometry(
                bounds={
                    axes.x_dim: CoordRange(
                        min=map_plot_value_to_coord(x0, axes.x_plot, axes.x_coord),
                        max=map_plot_value_to_coord(x1, axes.x_plot, axes.x_coord),
                    ),
                    axes.y_dim: CoordRange(
                        min=map_plot_value_to_coord(y0, axes.y_plot, axes.y_coord),
                        max=map_plot_value_to_coord(y1, axes.y_plot, axes.y_coord),
                    ),
                },
            ),
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_line_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Create one two-point path annotation from plot coordinates."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        end = self._snap_plot_pos(end)
        if abs(end[0] - start[0]) < 1e-12 and abs(end[1] - start[1]) < 1e-12:
            return
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            start[0], axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            start[1], axes.y_plot, axes.y_coord
                        ),
                    },
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            end[0], axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            end[1], axes.y_plot, axes.y_coord
                        ),
                    },
                ),
            ),
            semantic_type="line",
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_hyperbola_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Create one visible hyperbola branch from plot coordinates."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        params = self._hyperbola_parameters_from_drag(start, end)
        xs, ys = self._sample_hyperbola_plot_points(params)
        if len(xs) < 2:
            return
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=tuple(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(plot_x), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(plot_y), axes.y_plot, axes.y_coord
                        ),
                    }
                    for plot_x, plot_y in zip(xs, ys, strict=True)
                ),
            ),
            semantic_type="hyperbola",
            properties={
                "fit_model": "hyperbola",
                "fit_parameters": params,
                "hyperbola_equation": self._hyperbola_equation(params),
                "hyperbola_source": "manual",
            },
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_default_hyperbola_annotation(self, plot_x: float, plot_y: float) -> None:
        """Create one default hyperbola annotation near the target position."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        dx, dy = self._default_shape_half_spans()
        params = {
            "axis_angle": 0.0,
            "direction": 1,
            "vertex_x": float(plot_x),
            "vertex_y": float(plot_y),
            "a": float(max(dx, _HYPERBOLA_EPSILON)),
            "b": float(max(dy, _HYPERBOLA_EPSILON)),
            "extent": float(max(dy * 1.25, _HYPERBOLA_EPSILON)),
            "samples": _HYPERBOLA_SAMPLE_COUNT,
        }
        xs, ys = self._sample_hyperbola_plot_points(params)
        if len(xs) < 2:
            return
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=tuple(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(plot_x), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(plot_y), axes.y_plot, axes.y_coord
                        ),
                    }
                    for plot_x, plot_y in zip(xs, ys, strict=True)
                ),
            ),
            semantic_type="hyperbola",
            properties={
                "fit_model": "hyperbola",
                "fit_parameters": params,
                "hyperbola_equation": self._hyperbola_equation(params),
                "hyperbola_source": "manual",
            },
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_ellipse_annotation(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Create one ellipse annotation from plot coordinates."""
        axes = self._host._axes
        if self.annotation_dims() is None or axes is None:
            return
        params = self._ellipse_parameters_from_drag(start, end)
        xs, ys = self._sample_ellipse_plot_points(params)
        if len(xs) < 3:
            return
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=tuple(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(plot_x), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(plot_y), axes.y_plot, axes.y_coord
                        ),
                    }
                    for plot_x, plot_y in zip(xs, ys, strict=True)
                ),
            ),
            semantic_type="ellipse",
            properties={
                "fit_model": "ellipse",
                "fit_parameters": params,
                "ellipse_source": "manual",
            },
        )
        if annotation is None:
            return
        self.store_annotation(annotation)

    def create_default_ellipse_annotation(self, plot_x: float, plot_y: float) -> None:
        """Create one default ellipse annotation centered on the target position."""
        dx, dy = self._default_shape_half_spans()
        self.create_ellipse_annotation(
            (plot_x - dx, plot_y - dy), (plot_x + dx, plot_y + dy)
        )

    def create_default_box_annotation(self, plot_x: float, plot_y: float) -> None:
        """Create one default box annotation centered on the target position."""
        dx, dy = self._default_shape_half_spans()
        self.create_box_annotation(
            (plot_x - dx, plot_y - dy), (plot_x + dx, plot_y + dy)
        )

    def fit_ellipse_from_selection(self) -> bool:
        """Fit one axis-aligned ellipse from the selected point annotations."""
        selected = self._selected_point_annotations()
        if selected is None:
            return False
        self._show_host_warning("ellipse_fit_requires_points", clear_only=True)
        self._show_host_warning("ellipse_fit_failed", clear_only=True)
        point_annotations, points, axes = selected
        if len(point_annotations) < 3:
            self._show_host_warning("ellipse_fit_requires_points")
            return False
        try:
            params = self._fit_ellipse_plot_parameters(points)
        except _EllipseFitError:
            self._show_host_warning("ellipse_fit_failed")
            return False
        xs, ys = self._sample_ellipse_plot_points(params)
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=tuple(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(plot_x), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(plot_y), axes.y_plot, axes.y_coord
                        ),
                    }
                    for plot_x, plot_y in zip(xs, ys, strict=True)
                ),
            ),
            semantic_type="ellipse",
            properties={
                "fit_model": "ellipse",
                "fit_parameters": params,
                "ellipse_source": "fit",
                "derived_from": [annotation.id for annotation in point_annotations],
            },
        )
        if annotation is None:
            return False
        self.store_annotation(annotation)
        self._show_host_warning("ellipse_fit_failed", clear_only=True)
        return True

    def fit_line_from_selection(self) -> bool:
        """Fit one best-fit line through the selected point annotations."""
        selected = self._selected_point_annotations()
        if selected is None:
            return False
        self._show_host_warning("line_fit_requires_points", clear_only=True)
        self._show_host_warning("line_fit_failed", clear_only=True)
        point_annotations, points, axes = selected
        if len(point_annotations) < 2:
            self._show_host_warning("line_fit_requires_points")
            return False
        try:
            start, end = self._fit_line_plot_endpoints(points)
        except ValueError:
            self._show_host_warning("line_fit_failed")
            return False
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(start[0]), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(start[1]), axes.y_plot, axes.y_coord
                        ),
                    },
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(end[0]), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(end[1]), axes.y_plot, axes.y_coord
                        ),
                    },
                ),
            ),
            semantic_type="line",
            properties={
                "fit_model": "line",
                "line_source": "fit",
                "derived_from": [annotation.id for annotation in point_annotations],
            },
        )
        if annotation is None:
            return False
        self.store_annotation(annotation)
        self._show_host_warning("line_fit_failed", clear_only=True)
        return True

    def fit_square_from_selection(self) -> bool:
        """Fit one axis-aligned square that encloses the selected point annotations."""
        selected = self._selected_point_annotations()
        if selected is None:
            return False
        self._show_host_warning("square_fit_requires_points", clear_only=True)
        point_annotations, points, axes = selected
        if len(point_annotations) < 2:
            self._show_host_warning("square_fit_requires_points")
            return False
        min_x = float(points[:, 0].min())
        max_x = float(points[:, 0].max())
        min_y = float(points[:, 1].min())
        max_y = float(points[:, 1].max())
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        side = max(max_x - min_x, max_y - min_y, _HYPERBOLA_EPSILON)
        half_side = side / 2.0
        annotation = self._new_annotation(
            geometry=BoxGeometry(
                bounds={
                    axes.x_dim: CoordRange(
                        min=map_plot_value_to_coord(
                            center_x - half_side, axes.x_plot, axes.x_coord
                        ),
                        max=map_plot_value_to_coord(
                            center_x + half_side, axes.x_plot, axes.x_coord
                        ),
                    ),
                    axes.y_dim: CoordRange(
                        min=map_plot_value_to_coord(
                            center_y - half_side, axes.y_plot, axes.y_coord
                        ),
                        max=map_plot_value_to_coord(
                            center_y + half_side, axes.y_plot, axes.y_coord
                        ),
                    ),
                },
            ),
            semantic_type="square",
            properties={
                "fit_model": "square",
                "square_source": "fit",
                "derived_from": [annotation.id for annotation in point_annotations],
            },
        )
        if annotation is None:
            return False
        self.store_annotation(annotation)
        return True

    def fit_hyperbola_from_selection(self) -> bool:
        """Fit one visible hyperbola branch from the selected point annotations."""
        selected = self._selected_point_annotations()
        if selected is None:
            return False
        self._show_host_warning("hyperbola_fit_requires_points", clear_only=True)
        self._show_host_warning("hyperbola_fit_failed", clear_only=True)
        point_annotations, points, axes = selected
        if len(point_annotations) < 3:
            self._show_host_warning("hyperbola_fit_requires_points")
            return False
        try:
            params = self._fit_hyperbola_plot_parameters(points)
        except _HyperbolaFitError:
            self._show_host_warning("hyperbola_fit_failed")
            return False
        xs, ys = self._sample_hyperbola_plot_points(params)
        annotation = self._new_annotation(
            geometry=PathGeometry(
                points=tuple(
                    {
                        axes.x_dim: map_plot_value_to_coord(
                            float(plot_x), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(plot_y), axes.y_plot, axes.y_coord
                        ),
                    }
                    for plot_x, plot_y in zip(xs, ys, strict=True)
                ),
            ),
            semantic_type="hyperbola",
            properties={
                "fit_model": "hyperbola",
                "fit_parameters": params,
                "hyperbola_equation": self._hyperbola_equation(params),
                "hyperbola_source": "fit",
                "derived_from": [annotation.id for annotation in point_annotations],
            },
        )
        if annotation is None:
            return False
        self.store_annotation(annotation)
        self._show_host_warning("hyperbola_fit_failed", clear_only=True)
        return True

    def _selected_point_annotations(
        self,
    ) -> tuple[list[Annotation], np.ndarray, Any] | None:
        """Return selected point annotations with their plot-space coordinates."""
        if self.annotation_set is None or self._host._axes is None:
            return None
        selected_ids = set(self.selected_annotation_ids)
        point_annotations = [
            annotation
            for annotation in self.annotation_set.annotations
            if annotation.id in selected_ids
            and isinstance(annotation.geometry, PointGeometry)
        ]
        axes = self._host._axes
        points = np.array(
            [
                _point_plot_xy(annotation.geometry, axes)
                for annotation in point_annotations
            ],
            dtype=float,
        )
        return point_annotations, points, axes

    def on_item_clicked(self, item, _event) -> None:
        """Activate or delete the clicked annotation."""
        if not self._interactive:
            return
        self.activate_layer()
        if self.tool == "delete":
            self.delete_annotation(item.annotation_id)
            return
        self.set_active_annotation(item.annotation_id)

    def on_item_double_clicked(self, item) -> None:
        """Open the metadata editor for the clicked annotation."""
        if not self._interactive:
            return
        self.set_active_annotation(item.annotation_id)
        self.edit_annotation(item.annotation_id)

    def on_item_changing(self, item) -> None:
        """Apply live snap preview while a point/line/box ROI is being dragged."""
        if not self._interactive or self._applying_live_snap:
            return
        existing = self.annotation_by_id(item.annotation_id)
        if existing is None:
            return
        try:
            annotation = self._annotation_from_item(item.annotation_id, item)
        except Exception:
            return
        snapped = self._snap_annotation_edit(existing, annotation)
        if snapped == annotation:
            return
        self._applying_live_snap = True
        try:
            self._apply_annotation_to_item(item, snapped)
        finally:
            self._applying_live_snap = False

    def on_item_changed(self, item) -> None:
        """Persist geometry changes from a moved or resized annotation item."""
        if not self._interactive:
            return
        existing = self.annotation_by_id(item.annotation_id)
        if existing is None:
            return
        try:
            annotation = self._annotation_from_item(item.annotation_id, item)
        except Exception:
            return
        if (
            hasattr(item, "consume_group_drag_pending")
            and item.consume_group_drag_pending()
            and len(self.selected_annotation_ids) > 1
            and self.annotation_set is not None
            and self._host._axes is not None
        ):
            delta_x, delta_y = self._annotation_translation_delta_plot(
                existing, annotation, self._host._axes
            )
            if abs(delta_x) > 0.0 or abs(delta_y) > 0.0:
                selected_ids = set(self.selected_annotation_ids)
                updated_annotations = []
                for current in self.annotation_set.annotations:
                    if current.id == annotation.id:
                        updated_annotations.append(annotation)
                    elif current.id in selected_ids:
                        updated_annotations.append(
                            self._translate_annotation_by_plot_delta(
                                current, delta_x, delta_y, self._host._axes
                            )
                        )
                    else:
                        updated_annotations.append(current)
                self._store_annotation_set(updated_annotations)
                return
        annotation = self._snap_annotation_edit(existing, annotation)
        self.store_annotation(annotation)

    def _snap_to_annotations_enabled(self) -> bool:
        """Return True when annotation snapping is enabled in global settings."""
        return self._snap_to_annotations

    def _plot_to_scene(self, plot_pos: tuple[float, float]) -> QPointF | None:
        """Map one plot-space point into the scene for screen-space comparisons."""
        view_box = getattr(self._host._plot_item, "vb", None)
        if view_box is None:
            return None
        return view_box.mapViewToScene(pg.Point(*plot_pos))

    def _snap_candidates_plot(
        self, *, exclude_annotation_id: str | None = None
    ) -> list[tuple[float, float]]:
        """Return snap target anchors from the current annotation set in plot space."""
        if self.annotation_set is None or self._host._axes is None:
            return []
        axes = self._host._axes
        candidates: list[tuple[float, float]] = []
        for annotation in self.annotation_set.annotations:
            if annotation.id == exclude_annotation_id:
                continue
            geometry = annotation.geometry
            if isinstance(geometry, PointGeometry):
                candidates.append(_point_plot_xy(geometry, axes))
            elif isinstance(geometry, BoxGeometry):
                xmin, ymin, xmax, ymax = _box_plot_rect(geometry, axes)
                candidates.extend(
                    ((xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax))
                )
            elif isinstance(geometry, PathGeometry) and len(geometry.points) == 2:
                candidates.extend(_path_plot_xy_points(geometry, axes))
        return candidates

    def _snap_plot_pos(
        self,
        plot_pos: tuple[float, float],
        *,
        exclude_annotation_id: str | None = None,
    ) -> tuple[float, float]:
        """Snap one plot-space position to the nearest eligible annotation anchor."""
        if not self._snap_to_annotations_enabled():
            return plot_pos
        source_scene = self._plot_to_scene(plot_pos)
        if source_scene is None:
            return plot_pos
        best = plot_pos
        best_distance_sq = _ANNOTATION_SNAP_RADIUS_PX * _ANNOTATION_SNAP_RADIUS_PX
        found = False
        for candidate in self._snap_candidates_plot(
            exclude_annotation_id=exclude_annotation_id
        ):
            candidate_scene = self._plot_to_scene(candidate)
            if candidate_scene is None:
                continue
            dx = float(candidate_scene.x() - source_scene.x())
            dy = float(candidate_scene.y() - source_scene.y())
            distance_sq = (dx * dx) + (dy * dy)
            if distance_sq <= best_distance_sq:
                if not found or distance_sq < best_distance_sq:
                    best = candidate
                    best_distance_sq = distance_sq
                    found = True
        return best

    def _snap_point_annotation(self, annotation: Annotation) -> Annotation:
        """Return a point annotation snapped to the nearest eligible anchor."""
        axes = self._host._axes
        geometry = annotation.geometry
        if axes is None or not isinstance(geometry, PointGeometry):
            return annotation
        plot_pos = _point_plot_xy(geometry, axes)
        snapped = self._snap_plot_pos(plot_pos, exclude_annotation_id=annotation.id)
        if snapped == plot_pos:
            return annotation
        return annotation.model_copy(
            update={
                "geometry": PointGeometry(
                    coords={
                        **geometry.coords,
                        axes.x_dim: map_plot_value_to_coord(
                            float(snapped[0]), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(snapped[1]), axes.y_plot, axes.y_coord
                        ),
                    },
                )
            }
        )

    @staticmethod
    def _line_plot_points(
        annotation: Annotation, axes
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return one two-point path annotation in plot coordinates."""
        geometry = annotation.geometry
        if not isinstance(geometry, PathGeometry) or len(geometry.points) != 2:
            return None
        return _path_plot_xy_points(geometry, axes)

    @staticmethod
    def _box_plot_corners(
        annotation: Annotation, axes
    ) -> (
        tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ]
        | None
    ):
        """Return canonical box corners in plot coordinates."""
        geometry = annotation.geometry
        if not isinstance(geometry, BoxGeometry):
            return None
        xmin, ymin, xmax, ymax = _box_plot_rect(geometry, axes)
        return ((xmin, ymin), (xmax, ymin), (xmin, ymax), (xmax, ymax))

    @staticmethod
    def _is_line_translation(
        before: tuple[tuple[float, float], tuple[float, float]],
        after: tuple[tuple[float, float], tuple[float, float]],
    ) -> bool:
        """Return True when both line endpoints moved by the same delta."""
        delta0 = (
            float(after[0][0] - before[0][0]),
            float(after[0][1] - before[0][1]),
        )
        delta1 = (
            float(after[1][0] - before[1][0]),
            float(after[1][1] - before[1][1]),
        )
        return math.isclose(delta0[0], delta1[0], abs_tol=1e-9) and math.isclose(
            delta0[1], delta1[1], abs_tol=1e-9
        )

    @staticmethod
    def _is_box_translation(
        before: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ],
        after: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ],
    ) -> bool:
        """Return True when all canonical box corners moved by the same delta."""
        deltas = [
            (
                float(after_corner[0] - before_corner[0]),
                float(after_corner[1] - before_corner[1]),
            )
            for before_corner, after_corner in zip(before, after, strict=True)
        ]
        first_dx, first_dy = deltas[0]
        return all(
            math.isclose(delta_x, first_dx, abs_tol=1e-9)
            and math.isclose(delta_y, first_dy, abs_tol=1e-9)
            for delta_x, delta_y in deltas[1:]
        )

    def _snap_line_annotation(
        self, existing: Annotation, updated: Annotation
    ) -> Annotation:
        """Snap the edited line endpoint while leaving whole-line moves free."""
        axes = self._host._axes
        if axes is None:
            return updated
        before_points = self._line_plot_points(existing, axes)
        after_points = self._line_plot_points(updated, axes)
        if before_points is None or after_points is None:
            return updated
        if self._is_line_translation(before_points, after_points):
            return updated
        moved_distances = [
            _plot_distance_sq(before_point, after_point)
            for before_point, after_point in zip(
                before_points, after_points, strict=True
            )
        ]
        moved_index = 0 if moved_distances[0] >= moved_distances[1] else 1
        snapped_point = self._snap_plot_pos(
            after_points[moved_index], exclude_annotation_id=existing.id
        )
        if snapped_point == after_points[moved_index]:
            return updated
        snapped_points = list(after_points)
        snapped_points[moved_index] = snapped_point
        geometry = updated.geometry
        assert isinstance(geometry, PathGeometry)
        return updated.model_copy(
            update={
                "geometry": PathGeometry(
                    points=tuple(
                        {
                            **geometry.points[index],
                            axes.x_dim: map_plot_value_to_coord(
                                float(point[0]), axes.x_plot, axes.x_coord
                            ),
                            axes.y_dim: map_plot_value_to_coord(
                                float(point[1]), axes.y_plot, axes.y_coord
                            ),
                        }
                        for index, point in enumerate(snapped_points)
                    ),
                )
            }
        )

    def _snap_box_annotation(
        self, existing: Annotation, updated: Annotation
    ) -> Annotation:
        """Snap the resized box corner while leaving translations and rotations free."""
        axes = self._host._axes
        if axes is None:
            return updated
        before_rotation = float(existing.properties.get("rotation_angle", 0.0))
        after_rotation = float(updated.properties.get("rotation_angle", 0.0))
        if not math.isclose(before_rotation, after_rotation, abs_tol=1e-9):
            return updated
        before_corners = self._box_plot_corners(existing, axes)
        after_corners = self._box_plot_corners(updated, axes)
        if before_corners is None or after_corners is None:
            return updated
        if self._is_box_translation(before_corners, after_corners):
            return updated
        corner_displacements = [
            _plot_distance_sq(before_corner, after_corner)
            for before_corner, after_corner in zip(
                before_corners, after_corners, strict=True
            )
        ]
        anchor_index = min(
            range(len(corner_displacements)), key=corner_displacements.__getitem__
        )
        opposite_by_index = {0: 3, 1: 2, 2: 1, 3: 0}
        dragged_index = opposite_by_index[anchor_index]
        anchor_corner = after_corners[anchor_index]
        dragged_corner = self._snap_plot_pos(
            after_corners[dragged_index], exclude_annotation_id=existing.id
        )
        if dragged_corner == after_corners[dragged_index]:
            return updated
        xmin, xmax = sorted((float(anchor_corner[0]), float(dragged_corner[0])))
        ymin, ymax = sorted((float(anchor_corner[1]), float(dragged_corner[1])))
        geometry = updated.geometry
        assert isinstance(geometry, BoxGeometry)
        return updated.model_copy(
            update={
                "geometry": BoxGeometry(
                    bounds={
                        **geometry.bounds,
                        axes.x_dim: CoordRange(
                            min=map_plot_value_to_coord(
                                xmin, axes.x_plot, axes.x_coord
                            ),
                            max=map_plot_value_to_coord(
                                xmax, axes.x_plot, axes.x_coord
                            ),
                        ),
                        axes.y_dim: CoordRange(
                            min=map_plot_value_to_coord(
                                ymin, axes.y_plot, axes.y_coord
                            ),
                            max=map_plot_value_to_coord(
                                ymax, axes.y_plot, axes.y_coord
                            ),
                        ),
                    },
                )
            }
        )

    def _snap_annotation_edit(
        self, existing: Annotation, updated: Annotation
    ) -> Annotation:
        """Apply commit-time annotation snapping for eligible edited geometries."""
        if not self._snap_to_annotations_enabled():
            return updated
        if isinstance(updated.geometry, PointGeometry):
            return self._snap_point_annotation(updated)
        if (
            isinstance(updated.geometry, PathGeometry)
            and len(updated.geometry.points) == 2
        ):
            return self._snap_line_annotation(existing, updated)
        if isinstance(updated.geometry, BoxGeometry):
            return self._snap_box_annotation(existing, updated)
        return updated

    def _apply_annotation_to_item(self, item, annotation: Annotation) -> None:
        """Update a live ROI to match one snapped annotation geometry."""
        axes = self._host._axes
        if axes is None:
            return
        geometry = annotation.geometry
        if isinstance(item, _AnnotationPointDisplayItem) and isinstance(
            geometry, PointGeometry
        ):
            plot_x, plot_y = _point_plot_xy(geometry, axes)
            item.setPos(plot_x, plot_y)
            return
        if isinstance(item, _AnnotationPointROI) and isinstance(
            geometry, PointGeometry
        ):
            width = float(item.size().x())
            height = float(item.size().y())
            plot_x, plot_y = _point_plot_xy(geometry, axes)
            item.setPos((plot_x - (width / 2.0), plot_y - (height / 2.0)), finish=False)
            return
        if isinstance(item, _AnnotationLineROI) and isinstance(geometry, PathGeometry):
            if len(geometry.points) != 2:
                return
            plot_points = [
                QPointF(*point) for point in _path_plot_xy_points(geometry, axes)
            ]
            item.movePoint(
                item.endpoints[0], plot_points[0], finish=False, coords="parent"
            )
            item.movePoint(
                item.endpoints[1], plot_points[1], finish=False, coords="parent"
            )
            return
        if isinstance(item, _AnnotationRectROI) and isinstance(geometry, BoxGeometry):
            xmin, ymin, xmax, ymax = _box_plot_rect(geometry, axes)
            item.setPos((xmin, ymin), finish=False)
            item.setSize(
                (max(xmax - xmin, 1e-12), max(ymax - ymin, 1e-12)), finish=False
            )
            return
        if isinstance(geometry, PathGeometry) and len(geometry.points) >= 2:
            plot_points = _path_plot_xy_points(geometry, axes)
            xs = [float(point[0]) for point in plot_points]
            ys = [float(point[1]) for point in plot_points]
            xmin = min(xs)
            ymin = min(ys)
            if isinstance(item, _AnnotationPathROI):
                item.setPos((xmin, ymin), finish=False)
                return
            if isinstance(item, _AnnotationPathDisplayItem):
                item.setPos(xmin, ymin)
                return

    def _preview_drag_translation(
        self,
        original_annotations: dict[str, Annotation],
        delta_x: float,
        delta_y: float,
    ) -> None:
        """Apply one transient translated preview to currently dragged items."""
        axes = self._host._axes
        if axes is None:
            return
        for annotation_id, original in original_annotations.items():
            item = self.annotation_items.get(annotation_id)
            if item is None:
                continue
            translated = self._translate_annotation_by_plot_delta(
                original, delta_x, delta_y, axes
            )
            self._apply_annotation_to_item(item, translated)

    @staticmethod
    def _annotation_anchor_plot(annotation: Annotation, axes) -> tuple[float, float]:
        """Return one stable plot-space anchor point for a persisted annotation."""
        geometry = annotation.geometry
        if isinstance(geometry, PointGeometry):
            return _point_plot_xy(geometry, axes)
        if isinstance(geometry, BoxGeometry):
            xmin, ymin, _xmax, _ymax = _box_plot_rect(geometry, axes)
            return (xmin, ymin)
        if isinstance(geometry, PathGeometry) and geometry.points:
            return _path_plot_xy_points(geometry, axes)[0]
        raise TypeError(f"unsupported annotation geometry {type(geometry)!r}")

    def _annotation_translation_delta_plot(
        self, before: Annotation, after: Annotation, axes
    ) -> tuple[float, float]:
        """Return the plot-space translation between two versions of one annotation."""
        before_x, before_y = self._annotation_anchor_plot(before, axes)
        after_x, after_y = self._annotation_anchor_plot(after, axes)
        return after_x - before_x, after_y - before_y

    def _translate_annotation_by_plot_delta(
        self, annotation: Annotation, delta_x: float, delta_y: float, axes
    ) -> Annotation:
        """Translate one annotation by a plot-space delta."""
        geometry = annotation.geometry
        properties = dict(annotation.properties or {})
        if isinstance(geometry, PointGeometry):
            translated_geometry = PointGeometry(
                coords={
                    **geometry.coords,
                    axes.x_dim: map_plot_value_to_coord(
                        _point_plot_xy(geometry, axes)[0] + delta_x,
                        axes.x_plot,
                        axes.x_coord,
                    ),
                    axes.y_dim: map_plot_value_to_coord(
                        _point_plot_xy(geometry, axes)[1] + delta_y,
                        axes.y_plot,
                        axes.y_coord,
                    ),
                },
            )
        elif isinstance(geometry, BoxGeometry):
            xmin, ymin, xmax, ymax = _box_plot_rect(geometry, axes)
            translated_geometry = BoxGeometry(
                bounds={
                    **geometry.bounds,
                    axes.x_dim: CoordRange(
                        min=map_plot_value_to_coord(
                            xmin + delta_x, axes.x_plot, axes.x_coord
                        ),
                        max=map_plot_value_to_coord(
                            xmax + delta_x, axes.x_plot, axes.x_coord
                        ),
                    ),
                    axes.y_dim: CoordRange(
                        min=map_plot_value_to_coord(
                            ymin + delta_y, axes.y_plot, axes.y_coord
                        ),
                        max=map_plot_value_to_coord(
                            ymax + delta_y, axes.y_plot, axes.y_coord
                        ),
                    ),
                },
            )
        elif isinstance(geometry, PathGeometry):
            plot_points = _path_plot_xy_points(geometry, axes)
            translated_geometry = PathGeometry(
                points=tuple(
                    {
                        **geometry.points[index],
                        axes.x_dim: map_plot_value_to_coord(
                            point[0] + delta_x, axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            point[1] + delta_y, axes.y_plot, axes.y_coord
                        ),
                    }
                    for index, point in enumerate(plot_points)
                ),
            )
        else:
            return annotation
        fit_parameters = properties.get("fit_parameters")
        if isinstance(fit_parameters, dict):
            fit_parameters = dict(fit_parameters)
            if "center_x" in fit_parameters:
                fit_parameters["center_x"] = float(fit_parameters["center_x"]) + delta_x
            if "center_y" in fit_parameters:
                fit_parameters["center_y"] = float(fit_parameters["center_y"]) + delta_y
            if "vertex_x" in fit_parameters:
                fit_parameters["vertex_x"] = float(fit_parameters["vertex_x"]) + delta_x
            if "vertex_y" in fit_parameters:
                fit_parameters["vertex_y"] = float(fit_parameters["vertex_y"]) + delta_y
            if "slope" in fit_parameters and "intercept" in fit_parameters:
                fit_parameters["intercept"] = (
                    float(fit_parameters["intercept"])
                    + delta_y
                    - (float(fit_parameters["slope"]) * delta_x)
                )
            properties["fit_parameters"] = fit_parameters
            if properties.get("fit_model") == "hyperbola":
                properties["hyperbola_equation"] = self._hyperbola_equation(
                    fit_parameters
                )
        return annotation.model_copy(
            update={"geometry": translated_geometry, "properties": properties}
        )

    def position_toolbox(self) -> None:
        """Keep the toolbox near the plot's top-left corner."""
        self.toolbox.adjustSize()
        if not self.toolbox.user_moved:
            self.toolbox.move(12, 12)
        self.toolbox.raise_()

    def refresh_item_styles(self) -> None:
        """Update pen and handle visibility based on active state."""
        for annotation_id, item in self.annotation_items.items():
            annotation = self.annotation_by_id(annotation_id)
            label = None if annotation is None else annotation.label
            active = self._interactive and annotation_id == self.active_annotation_id
            selected = (
                self._interactive and annotation_id in self.selected_annotation_ids
            )
            if active:
                pen = _active_pen(label=label)
                hover_pen = _active_hover_pen(label=label)
            elif selected:
                pen = _selected_pen(interactive=self._interactive, label=label)
                hover_pen = _selected_hover_pen(
                    interactive=self._interactive, label=label
                )
            else:
                pen = _inactive_pen(interactive=self._interactive, label=label)
                hover_pen = _inactive_hover_pen(
                    interactive=self._interactive, label=label
                )
            item.setPen(pen)
            if hasattr(item, "setHoverPen"):
                item.setHoverPen(hover_pen)
            if hasattr(item, "getHandles"):
                for handle in item.getHandles():
                    handle.setVisible(active)
            item.setAcceptedMouseButtons(
                Qt.MouseButton.LeftButton
                if self._interactive
                else Qt.MouseButton.NoButton
            )

    def refresh_active_point_item_size(self) -> None:
        """Keep the active point ROI at a constant screen size across zoom changes."""
        width, height = self._point_plot_size()
        for item in self.annotation_items.values():
            if not isinstance(item, _AnnotationPointROI):
                continue
            pos = item.pos()
            size = item.size()
            center_x = float(pos.x()) + (float(size.x()) / 2)
            center_y = float(pos.y()) + (float(size.y()) / 2)
            item.setPos((center_x - (width / 2), center_y - (height / 2)))
            item.setSize((width, height))

    def _on_view_range_changed(self, _view_box, _view_range) -> None:
        """Refresh any overlay items whose render size depends on the view."""
        self.refresh_active_point_item_size()

    def _point_display_size(self) -> float:
        """Return the screen-space diameter used for rendered point annotations."""
        return _POINT_TARGET_PX

    def _point_plot_size(self) -> tuple[float, float]:
        """Return one point size in plot coordinates for active ROI rendering."""
        axes = self._host._axes
        if axes is None:
            return _POINT_FALLBACK_SIZE, _POINT_FALLBACK_SIZE
        x_span = abs(float(axes.x_plot[-1] - axes.x_plot[0]))
        y_span = abs(float(axes.y_plot[-1] - axes.y_plot[0]))
        x_step = (
            abs(float(axes.x_plot[1] - axes.x_plot[0])) if len(axes.x_plot) > 1 else 1.0
        )
        y_step = (
            abs(float(axes.y_plot[1] - axes.y_plot[0])) if len(axes.y_plot) > 1 else 1.0
        )
        view_range = self._host._plot_item.vb.viewRange()
        if view_range is not None and len(view_range) == 2:
            view_x_span = abs(float(view_range[0][1] - view_range[0][0])) or x_span
            view_y_span = abs(float(view_range[1][1] - view_range[1][0])) or y_span
        else:
            view_x_span = x_span
            view_y_span = y_span
        viewport = self._host._plot_widget.viewport().rect()
        target_px = self._point_display_size()
        # Fall back to a nominal 800-pixel viewport in headless environments where
        # the real viewport collapses to 1 pixel, which would otherwise produce an
        # astronomically large hit-tolerance and break box-select in offscreen tests.
        eff_w = viewport.width() if viewport.width() >= 10 else 800
        eff_h = viewport.height() if viewport.height() >= 10 else 800
        x_from_px = view_x_span * target_px / eff_w
        y_from_px = view_y_span * target_px / eff_h
        return (
            max(x_from_px, x_step * 2, 1e-6),
            max(y_from_px, y_step * 2, 1e-6),
        )

    def _default_shape_half_spans(self) -> tuple[float, float]:
        """Return one default half-size for placed annotations."""
        axes = self._host._axes
        if axes is None:
            return 1.0, 1.0
        x_span = (
            abs(float(axes.x_plot[-1] - axes.x_plot[0])) if len(axes.x_plot) else 1.0
        )
        y_span = (
            abs(float(axes.y_plot[-1] - axes.y_plot[0])) if len(axes.y_plot) else 1.0
        )
        x_step = (
            abs(float(axes.x_plot[1] - axes.x_plot[0])) if len(axes.x_plot) > 1 else 1.0
        )
        y_step = (
            abs(float(axes.y_plot[1] - axes.y_plot[0])) if len(axes.y_plot) > 1 else 1.0
        )
        view_range = self._host._plot_item.vb.viewRange()
        if view_range is not None and len(view_range) == 2:
            view_x_span = abs(float(view_range[0][1] - view_range[0][0])) or x_span
            view_y_span = abs(float(view_range[1][1] - view_range[1][0])) or y_span
        else:
            view_x_span = x_span or 1.0
            view_y_span = y_span or 1.0
        return (
            max(view_x_span * 0.08, x_step * 2, 1e-6),
            max(view_y_span * 0.08, y_step * 2, 1e-6),
        )

    def _annotation_from_item(self, annotation_id: str, item: pg.ROI) -> Annotation:
        """Convert one rendered item back into persisted annotation geometry."""
        axes = self._host._axes
        if axes is None:
            raise ValueError("cannot serialize annotations without axis metadata")
        existing = self.annotation_by_id(annotation_id)
        if existing is None:
            raise KeyError(annotation_id)
        properties = dict(existing.properties or {})
        if isinstance(item, _AnnotationPointROI):
            pos = item.pos()
            size = item.size()
            center_x = float(pos.x()) + (float(size.x()) / 2)
            center_y = float(pos.y()) + (float(size.y()) / 2)
            geometry = PointGeometry(
                coords={
                    **{
                        dim: existing.geometry.coords[dim]
                        for dim in geometry_dims(existing.geometry)
                        if dim not in {axes.x_dim, axes.y_dim}
                    },
                    axes.x_dim: map_plot_value_to_coord(
                        center_x, axes.x_plot, axes.x_coord
                    ),
                    axes.y_dim: map_plot_value_to_coord(
                        center_y, axes.y_plot, axes.y_coord
                    ),
                },
            )
        elif isinstance(item, _AnnotationRectROI):
            pos = item.pos()
            size = item.size()
            x0 = float(pos.x())
            y0 = float(pos.y())
            x1 = x0 + float(size.x())
            y1 = y0 + float(size.y())
            xmin, xmax = sorted((x0, x1))
            ymin, ymax = sorted((y0, y1))
            geometry = BoxGeometry(
                bounds={
                    **{
                        dim: existing.geometry.bounds[dim]
                        for dim in geometry_dims(existing.geometry)
                        if dim not in {axes.x_dim, axes.y_dim}
                    },
                    axes.x_dim: CoordRange(
                        min=map_plot_value_to_coord(xmin, axes.x_plot, axes.x_coord),
                        max=map_plot_value_to_coord(xmax, axes.x_plot, axes.x_coord),
                    ),
                    axes.y_dim: CoordRange(
                        min=map_plot_value_to_coord(ymin, axes.y_plot, axes.y_coord),
                        max=map_plot_value_to_coord(ymax, axes.y_plot, axes.y_coord),
                    ),
                },
            )
            properties["rotation_angle"] = 0.0
        elif isinstance(item, _AnnotationLineROI):
            start, end = item.plot_endpoints()
            geometry = PathGeometry(
                points=(
                    {
                        **existing.geometry.points[0],
                        axes.x_dim: map_plot_value_to_coord(
                            float(start.x()), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(start.y()), axes.y_plot, axes.y_coord
                        ),
                    },
                    {
                        **existing.geometry.points[1],
                        axes.x_dim: map_plot_value_to_coord(
                            float(end.x()), axes.x_plot, axes.x_coord
                        ),
                        axes.y_dim: map_plot_value_to_coord(
                            float(end.y()), axes.y_plot, axes.y_coord
                        ),
                    },
                ),
            )
        elif isinstance(item, _AnnotationPathROI):
            if item.roi_kind == "ellipse":
                size = item.size()
                width = max(float(size.x()), _HYPERBOLA_EPSILON)
                height = max(float(size.y()), _HYPERBOLA_EPSILON)
                center = item.centroid_plot_pos()
                params = {
                    "center_x": float(center.x()),
                    "center_y": float(center.y()),
                    "radius_x": width / 2.0,
                    "radius_y": height / 2.0,
                    "axis_angle": 0.0,
                    "samples": _HYPERBOLA_SAMPLE_COUNT,
                }
                xs, ys = self._sample_ellipse_plot_points(params)
                geometry = PathGeometry(
                    points=tuple(
                        {
                            **existing.geometry.points[index],
                            axes.x_dim: map_plot_value_to_coord(
                                float(plot_x), axes.x_plot, axes.x_coord
                            ),
                            axes.y_dim: map_plot_value_to_coord(
                                float(plot_y), axes.y_plot, axes.y_coord
                            ),
                        }
                        for index, (plot_x, plot_y) in enumerate(
                            zip(xs, ys, strict=True)
                        )
                    ),
                )
                properties["fit_parameters"] = params
            else:
                plot_points = item.plot_points()
                geometry = PathGeometry(
                    points=tuple(
                        {
                            **existing.geometry.points[index],
                            axes.x_dim: map_plot_value_to_coord(
                                plot_x, axes.x_plot, axes.x_coord
                            ),
                            axes.y_dim: map_plot_value_to_coord(
                                plot_y, axes.y_plot, axes.y_coord
                            ),
                        }
                        for index, (plot_x, plot_y) in enumerate(plot_points)
                    ),
                )
        else:
            raise TypeError(f"unsupported annotation item {type(item)!r}")
        return existing.model_copy(
            update={"geometry": geometry, "properties": properties}
        )

    def _selection_scene_rect(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> QRectF:
        """Return the current selection drag box in scene coordinates."""
        start_scene = self._host._plot_item.vb.mapViewToScene(pg.Point(*start))
        end_scene = self._host._plot_item.vb.mapViewToScene(pg.Point(*end))
        # Give box-select a tiny scene-space tolerance so points that land on the
        # drag edge are still included under offscreen/headless rounding noise.
        return (
            QRectF(start_scene, end_scene).normalized().adjusted(-1.0, -1.0, 1.0, 1.0)
        )

    def _annotation_item_at_scene_pos(self, scene_pos) -> pg.GraphicsObject | None:
        """Return the topmost annotation item under the given scene position."""
        annotation_items = set(self.annotation_items.values())
        for item in self._host._plot_widget.scene().items(scene_pos):
            if item in annotation_items and item.contains(item.mapFromScene(scene_pos)):
                return item
            parent = item.parentItem()
            if parent in annotation_items and parent.contains(
                parent.mapFromScene(scene_pos)
            ):
                return parent
        plot_pos = self.scene_to_plot(scene_pos)
        if plot_pos is not None:
            return self._point_item_near_plot_pos(plot_pos)
        return None

    def _point_item_near_plot_pos(
        self, plot_pos: tuple[float, float]
    ) -> pg.GraphicsObject | None:
        """Return one point item near the given plot position."""
        axes = self._host._axes
        if axes is None:
            return None
        width, height = self._point_plot_size()
        tolerance_x = width * _POINT_HIT_RADIUS_FACTOR
        tolerance_y = height * _POINT_HIT_RADIUS_FACTOR
        for annotation_id, item in self.annotation_items.items():
            annotation = self.annotation_by_id(annotation_id)
            if annotation is None or not isinstance(annotation.geometry, PointGeometry):
                continue
            point_x, point_y = _point_plot_xy(annotation.geometry, axes)
            if (
                abs(float(plot_pos[0]) - float(point_x)) <= tolerance_x
                and abs(float(plot_pos[1]) - float(point_y)) <= tolerance_y
            ):
                return item
        return None

    def _build_item_for_annotation(
        self, annotation: Annotation
    ) -> pg.GraphicsObject | None:
        """Create one ROI-like item for a persisted annotation."""
        axes = self._host._axes
        if axes is None:
            return None
        geometry = annotation.geometry
        pen = _inactive_pen(interactive=True, label=annotation.label)
        hover_pen = _inactive_hover_pen(interactive=True, label=annotation.label)
        if isinstance(geometry, PointGeometry):
            plot_x, plot_y = _point_plot_xy(geometry, axes)
            width, height = self._point_plot_size()
            if self._interactive and annotation.id in self.selected_annotation_ids:
                item = _AnnotationPointROI(
                    annotation.id,
                    pos=(plot_x - (width / 2), plot_y - (height / 2)),
                    size=(width, height),
                    movable=True,
                    resizable=False,
                    rotatable=False,
                    pen=pen,
                    hoverPen=hover_pen,
                )
            else:
                item = _AnnotationPointDisplayItem(
                    annotation.id,
                    pos=(plot_x, plot_y),
                    size=self._point_display_size(),
                    pen=pen,
                    hoverPen=hover_pen,
                )
        elif isinstance(geometry, BoxGeometry):
            plot_x0, plot_y0, plot_x1, plot_y1 = _box_plot_rect(geometry, axes)
            xmin, xmax = sorted((plot_x0, plot_x1))
            ymin, ymax = sorted((plot_y0, plot_y1))
            item = _AnnotationRectROI(
                annotation.id,
                pos=(xmin, ymin),
                size=(max(xmax - xmin, 1e-12), max(ymax - ymin, 1e-12)),
                movable=True,
                resizable=True,
                rotatable=False,
                pen=pen,
                hoverPen=hover_pen,
                handlePen=pg.mkPen((255, 255, 255), width=2),
            )
            item.handleSize = 14
            item.addScaleHandle((0, 0), (1, 1))
            item.addScaleHandle((1, 0), (0, 1))
            item.addScaleHandle((0, 1), (1, 0))
            item.addScaleHandle((1, 1), (0, 0))
        elif isinstance(geometry, PathGeometry) and len(geometry.points) >= 2:
            params = None
            if annotation.semantic_type == "ellipse":
                raw_params = annotation.properties.get("fit_parameters") or {}
                if raw_params:
                    params = dict(raw_params)
            plot_points = _path_plot_xy_points(geometry, axes)
            if len(plot_points) == 2:
                start = plot_points[0]
                end = plot_points[1]
                item = _AnnotationLineROI(
                    annotation.id,
                    positions=(start, end),
                    pen=pen,
                    hoverPen=hover_pen,
                    handlePen=pg.mkPen((255, 255, 255), width=2),
                )
                item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            else:
                if self._interactive and annotation.id in self.selected_annotation_ids:
                    roi_kind = "path"
                    roi_points = plot_points
                    if params is not None:
                        roi_kind = "ellipse"
                        canonical_params = dict(params)
                        canonical_params["axis_angle"] = 0.0
                        xs, ys = self._sample_ellipse_plot_points(canonical_params)
                        roi_points = tuple(
                            (float(plot_x), float(plot_y))
                            for plot_x, plot_y in zip(xs, ys, strict=True)
                        )
                    item = _AnnotationPathROI(
                        annotation.id,
                        points=roi_points,
                        roi_kind=roi_kind,
                        movable=True,
                        resizable=True,
                        rotatable=(roi_kind != "ellipse"),
                        pen=pen,
                        hoverPen=hover_pen,
                        handlePen=pg.mkPen((255, 255, 255), width=2),
                        handleHoverPen=pg.mkPen((255, 255, 255), width=3),
                    )
                    item.addScaleHandle((0, 0), (1, 1))
                    item.addScaleHandle((1, 0), (0, 1))
                    item.addScaleHandle((0, 1), (1, 0))
                    item.addScaleHandle((1, 1), (0, 0))
                    if roi_kind != "ellipse":
                        item.addRotateHandle((0.5, -0.2), (0.5, 0.5))
                else:
                    item = _AnnotationPathDisplayItem(
                        annotation.id,
                        points=plot_points,
                        roi_kind="ellipse" if params is not None else "path",
                        pen=pen,
                        hover_pen=hover_pen,
                    )
        else:
            return None

        item.sigClicked.connect(self.on_item_clicked)
        item.sigDoubleClicked.connect(self.on_item_double_clicked)
        if hasattr(item, "sigRegionChanged"):
            item.sigRegionChanged.connect(self.on_item_changing)
        if hasattr(item, "sigRegionChangeFinished"):
            item.sigRegionChangeFinished.connect(self.on_item_changed)
        item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        return item

    def _hyperbola_parameters_from_drag(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> dict[str, float | str | int]:
        """Infer one single-branch hyperbola parameter set from a drag gesture."""
        vx, vy = start
        dx = float(end[0] - vx)
        dy = float(end[1] - vy)
        axis_angle = math.atan2(dy, dx) if abs(dx) > 0.0 or abs(dy) > 0.0 else 0.0
        primary = max(math.hypot(dx, dy), _HYPERBOLA_EPSILON)
        normal_x = -math.sin(axis_angle)
        normal_y = math.cos(axis_angle)
        secondary = abs((dx * normal_x) + (dy * normal_y))
        if secondary > _HYPERBOLA_EPSILON:
            b = secondary
            a = max(primary / (math.sqrt(2.0) - 1.0), _HYPERBOLA_EPSILON)
            extent = max(secondary * 1.25, b)
        else:
            a = primary
            b = max(primary * 0.35, _HYPERBOLA_EPSILON)
            extent = max(b * 1.5, _HYPERBOLA_EPSILON)
        return {
            "axis_angle": float(axis_angle),
            "direction": 1,
            "vertex_x": float(vx),
            "vertex_y": float(vy),
            "a": float(a),
            "b": float(b),
            "extent": float(extent),
            "samples": _HYPERBOLA_SAMPLE_COUNT,
        }

    def _ellipse_parameters_from_drag(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> dict[str, float | int]:
        """Infer one ellipse from a drag gesture."""
        x0, y0 = start
        x1, y1 = end
        radius_x = max(abs(x1 - x0) / 2, _HYPERBOLA_EPSILON)
        radius_y = max(abs(y1 - y0) / 2, _HYPERBOLA_EPSILON)
        return {
            "center_x": float((x0 + x1) / 2),
            "center_y": float((y0 + y1) / 2),
            "radius_x": float(radius_x),
            "radius_y": float(radius_y),
            "axis_angle": 0.0,
            "samples": _HYPERBOLA_SAMPLE_COUNT,
        }

    def _sample_ellipse_plot_points(
        self, params: dict[str, float | int]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return sampled plot-space points for one stored ellipse."""
        center_x = float(params["center_x"])
        center_y = float(params["center_y"])
        radius_x = max(float(params["radius_x"]), _HYPERBOLA_EPSILON)
        radius_y = max(float(params["radius_y"]), _HYPERBOLA_EPSILON)
        axis_angle = float(params.get("axis_angle", 0.0))
        samples = max(int(params.get("samples", _HYPERBOLA_SAMPLE_COUNT)), 12)
        theta = np.linspace(0.0, 2 * math.pi, samples, endpoint=True, dtype=float)
        cos_angle = math.cos(axis_angle)
        sin_angle = math.sin(axis_angle)
        local_x = radius_x * np.cos(theta)
        local_y = radius_y * np.sin(theta)
        xs = center_x + (local_x * cos_angle) - (local_y * sin_angle)
        ys = center_y + (local_x * sin_angle) + (local_y * cos_angle)
        return xs, ys

    def _sample_hyperbola_plot_points(
        self, params: dict[str, float | str | int]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return sampled plot-space points for one stored hyperbola branch."""
        axis_angle = float(params["axis_angle"])
        direction = 1 if float(params.get("direction", 1)) >= 0 else -1
        vertex_x = float(params["vertex_x"])
        vertex_y = float(params["vertex_y"])
        a = max(float(params["a"]), _HYPERBOLA_EPSILON)
        b = max(float(params["b"]), _HYPERBOLA_EPSILON)
        extent = max(float(params["extent"]), _HYPERBOLA_EPSILON)
        samples = max(int(params.get("samples", _HYPERBOLA_SAMPLE_COUNT)), 8)
        independent = np.linspace(-extent, extent, samples, dtype=float)
        growth = direction * a * (np.sqrt(1.0 + (independent / b) ** 2) - 1.0)
        axis_x = math.cos(axis_angle)
        axis_y = math.sin(axis_angle)
        normal_x = -axis_y
        normal_y = axis_x
        xs = vertex_x + (growth * axis_x) + (independent * normal_x)
        ys = vertex_y + (growth * axis_y) + (independent * normal_y)
        return xs, ys

    def _hyperbola_equation(self, params: dict[str, float | str | int]) -> str:
        """Return one readable branch equation matching the sampled hyperbola."""
        axis_angle = _format_equation_scalar(float(params["axis_angle"]))
        vertex_x = _format_equation_scalar(float(params["vertex_x"]))
        vertex_y = _format_equation_scalar(float(params["vertex_y"]))
        a = _format_equation_scalar(max(float(params["a"]), _HYPERBOLA_EPSILON))
        b = _format_equation_scalar(max(float(params["b"]), _HYPERBOLA_EPSILON))
        direction = "1" if float(params.get("direction", 1)) >= 0 else "-1"
        return (
            f"u = cos({axis_angle})*(x - {vertex_x}) + sin({axis_angle})*(y - {vertex_y}); "  # noqa: E501
            f"v = -sin({axis_angle})*(x - {vertex_x}) + cos({axis_angle})*(y - {vertex_y}); "  # noqa: E501
            f"u = {direction}*{a}*(sqrt(1 + (v/{b})^2) - 1)"
        )

    def _fit_hyperbola_plot_parameters(
        self, points: np.ndarray
    ) -> dict[str, float | str | int]:
        """Fit one visible branch from selected plot-space points."""
        best: dict[str, float | str | int] | None = None
        best_error = math.inf
        coarse_angles = np.linspace(0.0, math.pi, num=181, endpoint=False, dtype=float)
        for direction in (1, -1):
            for axis_angle in coarse_angles:
                try:
                    params, error = self._fit_hyperbola_candidate(
                        points, axis_angle=float(axis_angle), direction=direction
                    )
                except _HyperbolaFitError:
                    continue
                if error < best_error:
                    best = params
                    best_error = error
        if best is not None:
            center = float(best["axis_angle"])
            fine_angles = np.linspace(
                center - (math.pi / 90.0),
                center + (math.pi / 90.0),
                num=61,
                endpoint=True,
                dtype=float,
            )
            for axis_angle in fine_angles:
                try:
                    params, error = self._fit_hyperbola_candidate(
                        points,
                        axis_angle=float(axis_angle),
                        direction=int(best["direction"]),
                    )
                except _HyperbolaFitError:
                    continue
                if error < best_error:
                    best = params
                    best_error = error
        if best is None:
            raise _HyperbolaFitError("no valid hyperbola fit found")
        return best

    def _fit_hyperbola_candidate(
        self,
        points: np.ndarray,
        *,
        axis_angle: float,
        direction: int,
    ) -> tuple[dict[str, float | str | int], float]:
        """Fit one axis-angle/direction hypothesis for a selected point cloud."""
        if points.shape[0] < 3:
            raise _HyperbolaFitError("at least three points are required")
        axis_x = math.cos(axis_angle)
        axis_y = math.sin(axis_angle)
        normal_x = -axis_y
        normal_y = axis_x
        axial = (points[:, 0] * axis_x) + (points[:, 1] * axis_y)
        lateral = (points[:, 0] * normal_x) + (points[:, 1] * normal_y)
        vertex_index = int(np.argmin(axial) if direction > 0 else np.argmax(axial))
        vertex_x = float(points[vertex_index, 0])
        vertex_y = float(points[vertex_index, 1])
        vertex_axial = float(axial[vertex_index])
        vertex_lateral = float(lateral[vertex_index])
        primary = direction * (axial - vertex_axial)
        secondary = lateral - vertex_lateral
        usable = primary >= -1e-8
        if usable.sum() < 3:
            raise _HyperbolaFitError("insufficient points on visible branch")
        primary = primary[usable]
        secondary = secondary[usable]
        secondary_span = float(np.max(np.abs(secondary)))
        primary_span = float(np.max(primary))
        if secondary_span < _HYPERBOLA_EPSILON or primary_span < _HYPERBOLA_EPSILON:
            raise _HyperbolaFitError("degenerate hyperbola selection")
        b_grid = np.geomspace(
            max(secondary_span / 20.0, _HYPERBOLA_EPSILON),
            max(secondary_span * 5.0, secondary_span + _HYPERBOLA_EPSILON),
            num=96,
        )
        best_error = math.inf
        best_a = None
        best_b = None
        for b in b_grid:
            feature = np.sqrt(1.0 + (secondary / b) ** 2) - 1.0
            denom = float(np.dot(feature, feature))
            if denom <= _HYPERBOLA_EPSILON:
                continue
            a = float(np.dot(primary, feature) / denom)
            if a <= _HYPERBOLA_EPSILON:
                continue
            residual = primary - (a * feature)
            error = float(np.mean(residual**2))
            if error < best_error:
                best_error = error
                best_a = a
                best_b = float(b)
        if best_a is None or best_b is None:
            raise _HyperbolaFitError("could not solve hyperbola scales")
        extent = max(secondary_span * 1.1, best_b)
        return (
            {
                "axis_angle": float(
                    math.atan2(math.sin(axis_angle), math.cos(axis_angle))
                ),
                "direction": int(direction),
                "vertex_x": vertex_x,
                "vertex_y": vertex_y,
                "a": float(best_a),
                "b": float(best_b),
                "extent": float(extent),
                "samples": _HYPERBOLA_SAMPLE_COUNT,
            },
            best_error,
        )

    def _fit_ellipse_plot_parameters(
        self, points: np.ndarray
    ) -> dict[str, float | int]:
        """Fit one axis-aligned ellipse from selected plot-space points."""
        if points.shape[0] < 3:
            raise _EllipseFitError("at least three points are required")
        center = points.mean(axis=0)
        centered = points - center
        design = np.column_stack((centered[:, 0] ** 2, centered[:, 1] ** 2))
        coeffs, *_ = np.linalg.lstsq(design, np.ones(points.shape[0]), rcond=None)
        coeff_x, coeff_y = (float(coeffs[0]), float(coeffs[1]))
        if coeff_x <= _HYPERBOLA_EPSILON or coeff_y <= _HYPERBOLA_EPSILON:
            raise _EllipseFitError("ellipse scales must be positive")
        radius_x = math.sqrt(1.0 / coeff_x)
        radius_y = math.sqrt(1.0 / coeff_y)
        if not np.isfinite((radius_x, radius_y)).all():
            raise _EllipseFitError("ellipse radii are not finite")
        residual = (design @ coeffs) - 1.0
        if float(np.mean(residual**2)) > 0.5:
            raise _EllipseFitError("ellipse residual too large")
        return {
            "center_x": float(center[0]),
            "center_y": float(center[1]),
            "radius_x": float(radius_x),
            "radius_y": float(radius_y),
            "axis_angle": 0.0,
            "samples": _HYPERBOLA_SAMPLE_COUNT,
        }

    def _fit_line_plot_endpoints(
        self, points: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Fit one principal-axis line through the selected plot-space points."""
        if points.shape[0] < 2:
            raise ValueError("at least two points are required")
        center = points.mean(axis=0)
        centered = points - center
        covariance = np.cov(centered, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        axis = eigenvectors[:, int(np.argmax(eigenvalues))]
        norm = float(np.linalg.norm(axis))
        if not np.isfinite(norm) or norm <= _HYPERBOLA_EPSILON:
            raise ValueError("degenerate line fit")
        axis = axis / norm
        projections = centered @ axis
        if np.ptp(projections) <= _HYPERBOLA_EPSILON:
            raise ValueError("degenerate line fit")
        start = center + (float(projections.min()) * axis)
        end = center + (float(projections.max()) * axis)
        return start, end

    def _fit_rotated_ellipse_plot_parameters(
        self, points: np.ndarray
    ) -> dict[str, float | int]:
        """Fit one rotated ellipse from sampled plot-space points."""
        if points.shape[0] < 3:
            raise _EllipseFitError("at least three points are required")
        center = points.mean(axis=0)
        centered = points - center
        covariance = np.cov(centered, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        major_axis = eigenvectors[:, int(np.argmax(eigenvalues))]
        axis_angle = math.atan2(float(major_axis[1]), float(major_axis[0]))
        axis_angle = _normalize_half_turn_angle(axis_angle)
        cos_angle = math.cos(axis_angle)
        sin_angle = math.sin(axis_angle)
        rotated = np.column_stack(
            (
                (centered[:, 0] * cos_angle) + (centered[:, 1] * sin_angle),
                (-centered[:, 0] * sin_angle) + (centered[:, 1] * cos_angle),
            )
        )
        params = self._fit_ellipse_plot_parameters(rotated)
        return {
            "center_x": float(center[0]),
            "center_y": float(center[1]),
            "radius_x": float(params["radius_x"]),
            "radius_y": float(params["radius_y"]),
            "axis_angle": _normalize_half_turn_angle(axis_angle),
            "samples": _HYPERBOLA_SAMPLE_COUNT,
        }

    def _show_host_warning(self, name: str, *args, clear_only: bool = False) -> None:
        """Best-effort helper for host widget warnings."""
        warning = getattr(getattr(self._host, "Warning", None), name, None)
        if warning is None:
            return
        if clear_only:
            warning.clear()
            return
        warning(*args)


__all__ = ("AnnotationEditorDialog", "AnnotationOverlayController")
