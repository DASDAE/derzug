"""Tests for the annotation overlay controller."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
import pytest
from AnyQt.QtCore import QEvent, QPointF, Qt, qInstallMessageHandler
from AnyQt.QtWidgets import QDialog, QWidget
from derzug.annotations_config import AnnotationConfig, save_annotation_config
from derzug.models.annotations import Annotation, BoxGeometry, PathGeometry
from derzug.widgets.annotation_overlay import (
    AnnotationOverlayController,
    _active_pen,
    _AnnotationLineROI,
    _AnnotationPathDisplayItem,
    _AnnotationPathROI,
    _AnnotationPointDisplayItem,
    _AnnotationPointROI,
    _AnnotationRectROI,
)


@dataclass
class _Axes:
    x_dim: str = "distance"
    y_dim: str = "time"
    x_plot: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 2.0, 3.0]))
    y_plot: np.ndarray = field(
        default_factory=lambda: np.array([10.0, 11.0, 12.0, 13.0])
    )
    x_coord: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 2.0, 3.0]))
    y_coord: np.ndarray = field(
        default_factory=lambda: np.array([10.0, 11.0, 12.0, 13.0])
    )


class _ContainsRect:
    @staticmethod
    def contains(_point) -> bool:
        return True


class _OutsideRect:
    @staticmethod
    def contains(_point) -> bool:
        return False


class _FakeSceneEvent:
    """Simple scene event double used by the controller tests."""

    def __init__(
        self,
        event_type,
        *,
        button=Qt.MouseButton.LeftButton,
        scene_pos=None,
        modifiers=Qt.KeyboardModifier.NoModifier,
    ):
        self._type = event_type
        self._button = button
        self._scene_pos = scene_pos or QPointF(1.0, 11.0)
        self._modifiers = modifiers
        self.accepted = False

    def type(self):
        return self._type

    def button(self):
        return self._button

    def scenePos(self):
        return self._scene_pos

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


class _FakeKeyEvent:
    """Simple key event double for Escape/Delete handling."""

    def __init__(self, key):
        self._key = key
        self.accepted = False

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True


class _FakeHoverEvent:
    """Simple hover event double for item-local hover tests."""

    def __init__(self, pos: QPointF):
        self._pos = pos
        self.accepted = False
        self.ignored = False

    def pos(self):
        return self._pos

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class _FakeRoiDragEvent:
    """Minimal drag event for driving ROI translation directly."""

    def __init__(
        self,
        roi: pg.ROI,
        *,
        start_parent: tuple[float, float],
        pos_parent: tuple[float, float],
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
        start: bool = False,
        finish: bool = False,
    ) -> None:
        self._roi = roi
        self._button = Qt.MouseButton.LeftButton
        self._start = start
        self._finish = finish
        self._modifiers = modifiers
        self._accepted = False
        self._ignored = False
        self._button_down_pos = pg.Point(roi.mapFromParent(QPointF(*start_parent)))
        self._pos = pg.Point(roi.mapFromParent(QPointF(*pos_parent)))

    def accept(self) -> None:
        self._accepted = True

    def ignore(self) -> None:
        self._ignored = True

    def isStart(self) -> bool:
        return self._start

    def isFinish(self) -> bool:
        return self._finish

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def buttonDownPos(self):
        return self._button_down_pos

    def pos(self):
        return self._pos

    def buttonDownScenePos(self):
        return self._roi.mapToScene(self._button_down_pos)

    def scenePos(self):
        return self._roi.mapToScene(self._pos)


class _FakeDialogCancel(QDialog):
    def __init__(self, annotation, parent=None):
        super().__init__(parent)

    def exec(self):
        return QDialog.DialogCode.Rejected


class _FakeHost(QWidget):
    """Small plot host used to test the controller directly."""

    def __init__(self):
        super().__init__()
        self._plot_widget = pg.PlotWidget(self)
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.sceneBoundingRect = lambda: _ContainsRect()
        self._plot_widget.scene().installEventFilter = lambda obj: None
        self._axes = _Axes()
        self._patch = object()
        self.cursor_fields = None

    def _set_cursor_readout(self, fields) -> None:
        self.cursor_fields = fields


def _point_coords(geometry) -> tuple[float, ...]:
    return tuple(float(value) for value in geometry.coords.values())


def _path_coords(geometry) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(value) for value in point.values()) for point in geometry.points
    )


def _box_corners(geometry) -> tuple[tuple[float, ...], tuple[float, ...]]:
    return (
        tuple(float(bounds.min) for bounds in geometry.bounds.values()),
        tuple(float(bounds.max) for bounds in geometry.bounds.values()),
    )


@pytest.fixture
def overlay_host(qtbot):
    """Return a fake annotation host and live controller."""
    host = _FakeHost()
    qtbot.addWidget(host)
    host.show()
    controller = AnnotationOverlayController(host)
    return host, controller


@pytest.fixture(autouse=True)
def clear_annotation_settings():
    """Reset global annotation settings around each test."""
    save_annotation_config(AnnotationConfig(annotator="tester", organization="DerZug"))
    yield
    save_annotation_config(AnnotationConfig(annotator="tester", organization="DerZug"))


def test_build_empty_set_returns_none_without_axes(overlay_host):
    """No axes means the controller cannot infer annotation dimensions."""
    host, controller = overlay_host
    host._axes = None

    assert controller.build_empty_set() is None


def test_ensure_annotation_set_preserves_matching_dims(overlay_host):
    """Matching dims should preserve the existing annotation collection."""
    _host, controller = overlay_host
    controller.ensure_annotation_set()
    first = controller.annotation_set

    controller.ensure_annotation_set()

    assert controller.annotation_set is first


def test_ensure_annotation_set_resets_when_dims_change(overlay_host):
    """Changing host dims should recreate the annotation set."""
    host, controller = overlay_host
    controller.ensure_annotation_set()
    first = controller.annotation_set
    host._axes = _Axes(x_dim="offset", y_dim="time")

    controller.ensure_annotation_set()

    assert controller.annotation_set is not first
    assert controller.annotation_set.dims == ("offset", "time")


def test_clear_annotations_resets_set_and_items(overlay_host):
    """Clearing annotations should drop all overlay state."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)

    controller.clear_annotations()

    assert controller.annotation_set is None
    assert controller.active_annotation_id is None
    assert controller.annotation_items == {}


def test_handle_key_press_cancels_draw_and_deletes_active_annotation(overlay_host):
    """Escape should cancel drawing and Delete should remove the active annotation."""
    _host, controller = overlay_host
    controller.draw_start = (1.0, 11.0)
    esc = _FakeKeyEvent(Qt.Key_Escape)

    assert controller.handle_key_press(esc) is True
    assert esc.accepted is True
    assert controller.draw_start is None

    controller.create_point_annotation(1.0, 11.0)
    delete = _FakeKeyEvent(Qt.Key_Delete)

    assert controller.handle_key_press(delete) is True
    assert delete.accepted is True
    assert controller.annotation_set.annotations == ()


def test_handle_key_press_escape_clears_selected_square_annotation(overlay_host):
    """Escape should clear a highlighted square annotation selection."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    first_id = controller.active_annotation_id
    controller.create_point_annotation(2.0, 12.0)
    second_id = controller.active_annotation_id
    controller.set_selected_annotations({first_id, second_id})

    assert controller.fit_square_from_selection() is True

    square_id = controller.active_annotation_id
    controller.set_selected_annotations({square_id})
    esc = _FakeKeyEvent(Qt.Key_Escape)

    assert controller.handle_key_press(esc) is True
    assert esc.accepted is True
    assert controller.selected_annotation_ids == set()
    assert controller.active_annotation_id is None


def test_handle_key_press_escape_clears_selected_ellipse_annotation(overlay_host):
    """Escape should clear a highlighted ellipse annotation selection."""
    _host, controller = overlay_host
    controller.create_ellipse_annotation((0.5, 10.5), (1.5, 11.5))
    ellipse_id = controller.active_annotation_id
    controller.set_selected_annotations({ellipse_id})
    esc = _FakeKeyEvent(Qt.Key_Escape)

    assert controller.handle_key_press(esc) is True
    assert esc.accepted is True
    assert controller.selected_annotation_ids == set()
    assert controller.active_annotation_id is None


def test_handle_key_press_assigns_numeric_label_to_selection(overlay_host):
    """Number keys should persist label slots onto the selected annotations."""
    save_annotation_config(
        AnnotationConfig(
            annotator="tester",
            organization="DerZug",
            label_names={"3": "p_pick", "1": "1", "2": "2"},
        )
    )
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    first_id = controller.active_annotation_id
    controller.create_point_annotation(2.0, 12.0)
    second_id = controller.active_annotation_id
    controller.set_selected_annotations({first_id, second_id})
    key = _FakeKeyEvent(Qt.Key_3)

    assert controller.handle_key_press(key) is True
    assert key.accepted is True
    assert {
        annotation.id: annotation.label
        for annotation in controller.annotation_set.annotations
    } == {first_id: "p_pick", second_id: "p_pick"}


def test_handle_key_press_zero_clears_label_from_selection(overlay_host):
    """Zero should clear label assignments from the selected annotations."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    controller.set_selected_annotations({annotation_id})
    controller.assign_label_to_selection("4")
    key = _FakeKeyEvent(Qt.Key_0)

    assert controller.handle_key_press(key) is True
    assert key.accepted is True
    assert controller.annotation_by_id(annotation_id).label is None


def test_handle_key_press_label_shortcuts_ignore_empty_selection(overlay_host):
    """Label keys should do nothing without an active selection."""
    _host, controller = overlay_host
    key = _FakeKeyEvent(Qt.Key_1)

    assert controller.handle_key_press(key) is False
    assert key.accepted is False


def test_create_point_annotation_uses_global_identity_settings(overlay_host):
    """New annotations should copy the current global annotator and organization."""
    save_annotation_config(AnnotationConfig(annotator="alice", organization="DASDAE"))
    _host, controller = overlay_host

    controller.create_point_annotation(1.0, 11.0)

    annotation = controller.annotation_set.annotations[0]
    assert annotation.annotator == "alice"
    assert annotation.organization == "DASDAE"


def test_create_point_annotation_prompts_until_identity_is_defined(
    overlay_host, monkeypatch
):
    """Creation should reopen settings until both user and org are defined."""
    save_annotation_config(AnnotationConfig())
    _host, controller = overlay_host
    opened: list[AnnotationConfig] = []
    returned = iter(
        [
            AnnotationConfig(),
            AnnotationConfig(annotator="alice", organization="DASDAE"),
        ]
    )

    class _FakeAnnotationSettingsDialog:
        def __init__(self, config, parent=None):
            opened.append(config)
            self._config = next(returned)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def config(self):
            return self._config

    monkeypatch.setattr(
        "derzug.widgets.annotation_overlay.AnnotationSettingsDialog",
        _FakeAnnotationSettingsDialog,
    )

    controller.create_point_annotation(1.0, 11.0)

    assert len(opened) == 2
    annotation = controller.annotation_set.annotations[0]
    assert annotation.annotator == "alice"
    assert annotation.organization == "DASDAE"


def test_label_shortcuts_fall_back_to_digit_for_blank_slot(overlay_host):
    """Blank slot names should keep the numeric default label."""
    save_annotation_config(
        AnnotationConfig(
            annotator="tester",
            organization="DerZug",
            label_names={"4": ""},
        )
    )
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    controller.set_selected_annotations({annotation_id})

    controller.handle_key_press(_FakeKeyEvent(Qt.Key_4))

    assert controller.annotation_by_id(annotation_id).label == "4"


def test_handle_scene_event_ignores_missing_patch_or_axes(overlay_host):
    """Missing patch/axes should short-circuit scene handling."""
    host, controller = overlay_host
    event = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    host._patch = None

    assert controller.handle_scene_event(event) is False

    host._patch = object()
    host._axes = None

    assert controller.handle_scene_event(event) is False


def test_non_annotation_tool_disables_scene_drawing(overlay_host):
    """Host-provided non-annotation tools should not start draw gestures."""
    _host, controller = overlay_host
    controller.set_tool("select")
    event = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)

    assert controller.handle_scene_event(event) is False


def test_annotation_select_tool_starts_background_selection_drag(overlay_host):
    """Annotation-select mode should start a box-selection drag on press."""
    _host, controller = overlay_host
    controller.set_tool("annotation_select")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)

    assert controller.handle_scene_event(press) is True
    assert controller.tool_buttons["annotation_select"].isChecked() is True
    assert controller.draw_start is not None
    assert controller.preview_item is not None


def test_neutral_tool_state_does_not_start_annotation_selection_drag(overlay_host):
    """No active annotation tool should leave selection gestures disabled."""
    _host, controller = overlay_host
    controller.clear_active_tool()
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)

    assert controller.handle_scene_event(press) is False
    assert controller.draw_start is None
    assert not any(button.isChecked() for button in controller.tool_buttons.values())


def test_annotation_select_drag_box_selects_and_highlights_matching_items(overlay_host):
    """Dragging a selection box should select and restyle intersecting annotations."""
    _host, controller = overlay_host
    controller.create_box_annotation((0.9, 10.9), (1.1, 11.1))
    first_id = controller.active_annotation_id
    controller.create_box_annotation((1.9, 11.9), (2.1, 12.1))
    second_id = controller.active_annotation_id
    controller.create_box_annotation((2.9, 12.9), (3.1, 13.1))
    third_id = controller.active_annotation_id
    controller.set_tool("annotation_select")
    start_scene = controller._host._plot_item.vb.mapViewToScene(pg.Point(0.6, 10.6))
    end_scene = controller._host._plot_item.vb.mapViewToScene(pg.Point(2.4, 12.4))

    press = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMousePress,
        scene_pos=start_scene,
    )
    move = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMouseMove,
        scene_pos=end_scene,
    )
    release = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMouseRelease,
        scene_pos=end_scene,
    )

    assert controller.handle_scene_event(press) is True
    assert controller.handle_scene_event(move) is True
    assert controller.handle_scene_event(release) is True
    assert controller.selected_annotation_ids == {first_id, second_id}

    selected_color = controller.annotation_items[first_id].currentPen.color().getRgb()
    other_selected_color = (
        controller.annotation_items[second_id].currentPen.color().getRgb()
    )
    unselected_color = controller.annotation_items[third_id].currentPen.color().getRgb()
    assert selected_color == other_selected_color
    assert selected_color != unselected_color


def test_labeled_annotations_use_slot_colors(overlay_host):
    """Assigned numeric labels should drive deterministic annotation colors."""
    _host, controller = overlay_host
    controller.create_box_annotation((0.9, 10.9), (1.1, 11.1))
    first_id = controller.active_annotation_id
    controller.create_box_annotation((1.9, 11.9), (2.1, 12.1))
    second_id = controller.active_annotation_id
    controller.create_box_annotation((2.9, 12.9), (3.1, 13.1))
    third_id = controller.active_annotation_id
    controller.set_selected_annotations({first_id})
    controller.assign_label_to_selection("1")
    controller.set_selected_annotations({second_id})
    controller.assign_label_to_selection("2")
    controller.set_selected_annotations(set())

    first_color = controller.annotation_items[first_id].currentPen.color().getRgb()
    second_color = controller.annotation_items[second_id].currentPen.color().getRgb()
    third_color = controller.annotation_items[third_id].currentPen.color().getRgb()

    assert first_color != second_color
    assert first_color != third_color
    assert second_color != third_color


def test_point_tool_double_click_creates_annotation_immediately(overlay_host):
    """Background double-click in point mode should place one fixed point."""
    _host, controller = overlay_host
    controller.set_tool("point")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)
    double_click = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)

    assert controller.handle_scene_event(press) is False
    assert controller.handle_scene_event(release) is False
    assert controller.annotation_set is None

    assert controller.handle_scene_event(double_click) is True
    assert controller.annotation_set is not None
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "point"
    assert controller.draw_start is None
    assert controller.preview_item is None
    assert double_click.accepted is True


def test_point_annotation_double_click_opens_editor_dialog(overlay_host):
    """Double-clicking an existing point should open the metadata editor."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]
    opened: list[str] = []

    controller.edit_annotation = lambda current_id: opened.append(current_id) or True

    controller.on_item_double_clicked(item)

    assert opened == [annotation_id]
    assert controller.draw_start is None
    assert controller.preview_item is None


def test_shift_click_point_tool_creates_annotation_without_double_click(overlay_host):
    """Shift+click should place a point immediately with the point tool active."""
    _host, controller = overlay_host
    controller.set_tool("point")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    press._modifiers = Qt.KeyboardModifier.ShiftModifier

    assert controller.handle_scene_event(press) is True
    assert controller.annotation_set is not None
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "point"
    assert press.accepted is True


def test_set_interactive_false_locks_existing_items(overlay_host):
    """Disabling interaction keeps items visible but non-editable."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    controller.set_interactive(False)

    assert controller.interactive is False
    assert item.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert not any(handle.isVisible() for handle in item.getHandles())


def test_create_point_annotation_builds_render_item_without_brush_error(overlay_host):
    """Creating a point annotation should build one visible ROI item cleanly."""
    _host, controller = overlay_host

    controller.create_point_annotation(1.0, 11.0)

    assert controller.annotation_set is not None
    assert len(controller.annotation_set.annotations) == 1
    assert len(controller.annotation_items) == 1


def test_create_point_annotation_snaps_to_existing_annotation(overlay_host):
    """Point creation should snap to a nearby annotation anchor when enabled."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)

    controller.create_point_annotation(2.02, 12.02)

    created = controller.annotation_by_id(controller.active_annotation_id)
    assert created is not None
    assert _point_coords(created.geometry) == pytest.approx((2.0, 12.0))


def test_handle_scene_event_ignores_non_left_button(overlay_host):
    """Only left-button interaction should create or modify annotations."""
    _host, controller = overlay_host
    event = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMousePress,
        button=Qt.MouseButton.RightButton,
    )

    assert controller.handle_scene_event(event) is False


def test_handle_scene_event_ignores_clicks_outside_plot(overlay_host):
    """Clicks outside the plot bounds should not activate annotation tools."""
    host, controller = overlay_host
    host._plot_item.sceneBoundingRect = lambda: _OutsideRect()
    event = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)

    assert controller.handle_scene_event(event) is False


def test_toolbox_snap_toggle_updates_controller_state(overlay_host):
    """The floating toolbox should own the snap toggle state."""
    _host, controller = overlay_host

    assert controller.toolbox.snap_enabled() is False

    controller.toolbox.snap_button.setChecked(True)
    assert controller._snap_to_annotations_enabled() is True

    controller.toolbox.snap_button.setChecked(False)
    assert controller._snap_to_annotations_enabled() is False


def test_line_draw_preview_snaps_live_and_unsnaps_when_moved_away(overlay_host):
    """Line preview should jump to the snap target before release and leave it later."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.set_tool("line")
    controller.draw_start = (0.0, 10.0)
    controller.start_preview((0.0, 10.0))

    assert isinstance(controller.preview_item, pg.PlotDataItem)

    controller.update_preview((2.04, 12.04))
    xs, ys = controller.preview_item.getData()
    assert (float(xs[-1]), float(ys[-1])) == pytest.approx((2.0, 12.0))

    controller.update_preview((2.4, 12.4))
    xs, ys = controller.preview_item.getData()
    assert (float(xs[-1]), float(ys[-1])) == pytest.approx((2.4, 12.4))


def test_box_draw_preview_snaps_live_and_unsnaps_when_moved_away(overlay_host):
    """Box preview should snap the dragged corner before release and unsnap later."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.set_tool("box")
    controller.draw_start = (0.0, 10.0)
    controller.start_preview((0.0, 10.0))

    assert isinstance(controller.preview_item, pg.ROI)

    controller.update_preview((2.04, 12.04))
    assert (
        float(controller.preview_item.pos().x())
        + float(controller.preview_item.size().x()),
        float(controller.preview_item.pos().y())
        + float(controller.preview_item.size().y()),
    ) == pytest.approx((2.0, 12.0))

    controller.update_preview((2.4, 12.4))
    assert (
        float(controller.preview_item.pos().x())
        + float(controller.preview_item.size().x()),
        float(controller.preview_item.pos().y())
        + float(controller.preview_item.size().y()),
    ) == pytest.approx((2.4, 12.4))


def test_user_places_a_point_on_an_existing_line_endpoint(overlay_host):
    """A reviewer should be able to drop a point directly onto a snapped line end."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_line_annotation((0.0, 10.0), (2.0, 12.0))

    controller.create_point_annotation(2.03, 12.03)

    annotation = controller.annotation_by_id(controller.active_annotation_id)
    assert annotation is not None
    assert _point_coords(annotation.geometry) == pytest.approx((2.0, 12.0))


def test_user_moves_a_point_onto_an_existing_box_corner(overlay_host):
    """A picked point should align cleanly to an already reviewed box corner."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_box_annotation((0.0, 10.0), (2.0, 12.0))
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPointROI)

    size = item.size()
    item.setPos((2.03 - (float(size.x()) / 2), 12.03 - (float(size.y()) / 2)))
    controller.on_item_changing(item)
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _point_coords(annotation.geometry) == pytest.approx((2.0, 12.0))


def test_user_draws_a_line_to_an_existing_point_pick(overlay_host):
    """A drawn line should preview and commit onto a previously placed point pick."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.set_tool("line")
    controller.draw_start = (0.0, 10.0)
    controller.start_preview((0.0, 10.0))

    assert isinstance(controller.preview_item, pg.PlotDataItem)

    controller.update_preview((2.04, 12.04))
    xs, ys = controller.preview_item.getData()
    assert (float(xs[-1]), float(ys[-1])) == pytest.approx((2.0, 12.0))

    controller.finish_draw((2.04, 12.04))

    annotation = controller.annotation_by_id(controller.active_annotation_id)
    assert annotation is not None
    assert _path_coords(annotation.geometry)[0] == pytest.approx((0.0, 10.0))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_user_adjusts_a_line_endpoint_to_a_box_corner(overlay_host):
    """A line endpoint edit should lock onto a box corner used as a reference."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_box_annotation((0.0, 10.0), (2.0, 12.0))
    controller.create_line_annotation((0.0, 11.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationLineROI)

    item.movePoint(item.endpoints[1], QPointF(2.04, 12.04), finish=False)
    controller.on_item_changing(item)
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _path_coords(annotation.geometry)[0] == pytest.approx((0.0, 11.0))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_user_draws_a_box_to_a_line_endpoint(overlay_host):
    """A dragged box corner should preview and commit onto an existing line endpoint."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_line_annotation((0.0, 10.0), (2.0, 12.0))
    controller.set_tool("box")
    controller.draw_start = (0.0, 10.0)
    controller.start_preview((0.0, 10.0))

    assert isinstance(controller.preview_item, pg.ROI)

    controller.update_preview((2.03, 12.03))
    assert (
        float(controller.preview_item.pos().x())
        + float(controller.preview_item.size().x()),
        float(controller.preview_item.pos().y())
        + float(controller.preview_item.size().y()),
    ) == pytest.approx((2.0, 12.0))

    controller.finish_draw((2.03, 12.03))

    annotation = controller.annotation_by_id(controller.active_annotation_id)
    assert annotation is not None
    assert isinstance(annotation.geometry, BoxGeometry)
    assert _box_corners(annotation.geometry)[0] == pytest.approx((0.0, 10.0))
    assert _box_corners(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_user_resizes_a_box_corner_to_an_existing_point_pick(overlay_host):
    """A box resize should snap the active corner onto a nearby point pick."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_box_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    item.setPos((0.0, 10.0), finish=False)
    item.setSize((2.03, 2.03), finish=False)
    controller.on_item_changing(item)
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert isinstance(annotation.geometry, BoxGeometry)
    assert _box_corners(annotation.geometry)[0] == pytest.approx((0.0, 10.0))
    assert _box_corners(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_line_tool_double_click_anchors_then_single_click_creates_annotation(
    overlay_host,
):
    """Line placement should anchor on double-click and commit on later single click."""
    host, controller = overlay_host
    controller.set_tool("line")
    anchor_scene = host._plot_item.vb.mapViewToScene(QPointF(1.0, 11.0))
    end_scene = host._plot_item.vb.mapViewToScene(QPointF(2.0, 12.0))
    anchor = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMouseDoubleClick, scene_pos=anchor_scene
    )
    move = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseMove, scene_pos=end_scene)
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress, scene_pos=end_scene)
    release = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMouseRelease, scene_pos=end_scene
    )

    assert controller.handle_scene_event(anchor) is True
    assert controller.annotation_set is None
    assert controller.draw_start == pytest.approx((1.0, 11.0))
    assert isinstance(controller.preview_item, pg.PlotDataItem)
    assert anchor.accepted is True

    assert controller.handle_scene_event(move) is True
    xs, ys = controller.preview_item.getData()
    assert (float(xs[-1]), float(ys[-1])) == pytest.approx((2.0, 12.0))

    assert controller.handle_scene_event(press) is True
    assert press.accepted is True
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "path"
    assert controller.draw_start is None
    assert controller.preview_item is None

    assert controller.handle_scene_event(release) is True
    assert release.accepted is True
    assert controller.active_annotation_id is not None


def test_line_tool_anchor_preview_and_commit_snap_to_existing_point(overlay_host):
    """The floating line endpoint should preview-snap and commit to a nearby point."""
    host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.set_tool("line")
    anchor_scene = host._plot_item.vb.mapViewToScene(QPointF(1.0, 11.0))
    near_scene = host._plot_item.vb.mapViewToScene(QPointF(2.04, 12.04))

    assert controller.handle_scene_event(
        _FakeSceneEvent(
            QEvent.Type.GraphicsSceneMouseDoubleClick, scene_pos=anchor_scene
        )
    )
    assert controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseMove, scene_pos=near_scene)
    )

    assert isinstance(controller.preview_item, pg.PlotDataItem)
    xs, ys = controller.preview_item.getData()
    assert (float(xs[-1]), float(ys[-1])) == pytest.approx((2.0, 12.0))

    assert controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress, scene_pos=near_scene)
    )
    assert controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease, scene_pos=near_scene)
    )

    annotation = controller.annotation_by_id(controller.active_annotation_id)
    assert annotation is not None
    assert _path_coords(annotation.geometry)[0] == pytest.approx((1.0, 11.0))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_line_tool_single_click_without_anchor_does_not_create_annotation(overlay_host):
    """A lone single click should not create a line before the first anchor exists."""
    _host, controller = overlay_host
    controller.set_tool("line")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)

    assert controller.handle_scene_event(press) is False
    assert controller.handle_scene_event(release) is False
    assert controller.annotation_set is None


def test_shift_click_line_tool_anchors_without_double_click(overlay_host):
    """Shift+click should start the line anchor preview without a double-click."""
    host, controller = overlay_host
    controller.set_tool("line")
    anchor_scene = host._plot_item.vb.mapViewToScene(QPointF(1.0, 11.0))
    end_scene = host._plot_item.vb.mapViewToScene(QPointF(2.0, 12.0))
    anchor = _FakeSceneEvent(
        QEvent.Type.GraphicsSceneMousePress, scene_pos=anchor_scene
    )
    anchor._modifiers = Qt.KeyboardModifier.ShiftModifier
    move = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseMove, scene_pos=end_scene)
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress, scene_pos=end_scene)

    assert controller.handle_scene_event(anchor) is True
    assert controller.annotation_set is None
    assert controller.draw_start == pytest.approx((1.0, 11.0))
    assert isinstance(controller.preview_item, pg.PlotDataItem)
    assert controller.preview_item.opts["symbol"] == "o"
    assert float(controller.preview_item.opts["pen"].widthF()) == pytest.approx(
        float(_active_pen().widthF())
    )
    assert anchor.accepted is True

    assert controller.handle_scene_event(move) is True
    assert controller.handle_scene_event(press) is True
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "path"

    item = controller.annotation_items[controller.active_annotation_id]
    assert isinstance(item, _AnnotationLineROI)
    assert float(item.currentPen.widthF()) == pytest.approx(
        float(_active_pen().widthF())
    )


def test_escape_cancels_pending_line_anchor(overlay_host):
    """Escape should discard a pending anchored line before final commit."""
    _host, controller = overlay_host
    controller.set_tool("line")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )

    assert controller.draw_start is not None
    assert controller.preview_item is not None

    esc = _FakeKeyEvent(Qt.Key_Escape)
    assert controller.handle_key_press(esc) is True

    assert esc.accepted is True
    assert controller.draw_start is None
    assert controller.preview_item is None
    assert controller.annotation_set is None


def test_switching_away_from_line_tool_cancels_pending_line_anchor(overlay_host):
    """Changing tools should discard any pending anchored line preview."""
    _host, controller = overlay_host
    controller.set_tool("line")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )

    assert controller.draw_start is not None
    assert controller.preview_item is not None

    controller.set_tool("box")

    assert controller.draw_start is None
    assert controller.preview_item is None


def test_hyperbola_tool_requires_double_click_to_create_annotation(overlay_host):
    """Hyperbola placement should happen only on background double-click."""
    _host, controller = overlay_host
    controller.set_tool("hyperbola")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)
    double_click = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)

    assert controller.handle_scene_event(press) is False
    assert controller.handle_scene_event(release) is False
    assert controller.annotation_set is None

    assert controller.handle_scene_event(double_click) is True
    annotation = controller.annotation_set.annotations[0]
    assert annotation.semantic_type == "hyperbola"
    assert annotation.geometry.type == "path"
    assert len(annotation.geometry.points) > 10
    assert annotation.properties["fit_model"] == "hyperbola"
    assert annotation.properties["hyperbola_source"] == "manual"
    assert annotation.properties["fit_parameters"]["axis_angle"] == pytest.approx(0.0)
    assert "u = " in annotation.properties["hyperbola_equation"]
    assert "sqrt(1 + (v/" in annotation.properties["hyperbola_equation"]
    assert double_click.accepted is True
    ys = [float(point["time"]) for point in annotation.geometry.points]
    vertex_y = float(annotation.properties["fit_parameters"]["vertex_y"])
    assert min(ys) < vertex_y < max(ys)


def test_shift_click_hyperbola_tool_creates_annotation_without_double_click(
    overlay_host,
):
    """Shift+click should place a hyperbola immediately with that tool active."""
    _host, controller = overlay_host
    controller.set_tool("hyperbola")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    press._modifiers = Qt.KeyboardModifier.ShiftModifier

    assert controller.handle_scene_event(press) is True
    annotation = controller.annotation_set.annotations[0]
    assert annotation.semantic_type == "hyperbola"
    assert annotation.geometry.type == "path"
    assert press.accepted is True


def test_ellipse_tool_requires_double_click_to_create_annotation(overlay_host):
    """Ellipse placement should happen only on background double-click."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)
    double_click = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)

    assert controller.handle_scene_event(press) is False
    assert controller.handle_scene_event(release) is False
    assert controller.annotation_set is None

    assert controller.handle_scene_event(double_click) is True
    annotation = controller.annotation_set.annotations[0]
    assert annotation.semantic_type == "ellipse"
    assert annotation.geometry.type == "path"
    assert len(annotation.geometry.points) > 10
    assert annotation.properties["fit_model"] == "ellipse"
    assert annotation.properties["ellipse_source"] == "manual"
    assert double_click.accepted is True


def test_shift_click_ellipse_tool_creates_annotation_without_double_click(overlay_host):
    """Shift+click should place an ellipse immediately with that tool active."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    press._modifiers = Qt.KeyboardModifier.ShiftModifier

    assert controller.handle_scene_event(press) is True
    annotation = controller.annotation_set.annotations[0]
    assert annotation.semantic_type == "ellipse"
    assert annotation.geometry.type == "path"
    assert press.accepted is True


def test_multi_point_paths_render_as_display_items(overlay_host):
    """Sampled paths should render instead of being skipped by the overlay."""
    _host, controller = overlay_host
    controller.annotation_set = controller.build_empty_set()
    controller.annotation_set = controller.annotation_set.model_copy(
        update={
            "annotations": (
                Annotation(
                    id="curve-1",
                    geometry=PathGeometry(
                        points=(
                            {"distance": 0.5, "time": 10.5},
                            {"distance": 1.0, "time": 11.0},
                            {"distance": 1.5, "time": 11.5},
                            {"distance": 2.0, "time": 12.0},
                        ),
                    ),
                    semantic_type="hyperbola",
                ),
            )
        }
    )

    controller.rebuild_items()

    assert isinstance(
        controller.annotation_items["curve-1"], _AnnotationPathDisplayItem
    )


def test_h_key_fits_hyperbola_from_selected_points(overlay_host):
    """The fit shortcut should create one hyperbola annotation from selected picks."""
    _host, controller = overlay_host
    for point_x, point_y in (
        (1.0, 10.8),
        (1.15, 11.0),
        (1.55, 11.3),
        (2.1, 11.7),
    ):
        controller.create_point_annotation(point_x, point_y)
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)
    key = _FakeKeyEvent(Qt.Key_H)

    assert controller.handle_key_press(key) is True
    assert key.accepted is True
    assert len(controller.annotation_set.annotations) == 5
    hyperbola = controller.annotation_set.annotations[-1]
    assert hyperbola.semantic_type == "hyperbola"
    assert hyperbola.properties["fit_model"] == "hyperbola"
    assert hyperbola.properties["hyperbola_source"] == "fit"
    assert "u = " in hyperbola.properties["hyperbola_equation"]
    assert set(hyperbola.properties["derived_from"]) == source_ids


def test_fit_shape_from_selection_creates_line_from_selected_points(overlay_host):
    """Fit dispatch creates one fitted line annotation from selected points."""
    _host, controller = overlay_host
    for point_x, point_y in (
        (0.9, 10.8),
        (1.3, 11.2),
        (1.8, 11.7),
        (2.2, 12.1),
    ):
        controller.create_point_annotation(point_x, point_y)
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)

    assert controller.fit_shape_from_selection("line") is True

    assert len(controller.annotation_set.annotations) == 5
    line = controller.annotation_set.annotations[-1]
    assert line.semantic_type == "line"
    assert line.geometry.type == "path"
    assert len(line.geometry.points) == 2
    assert line.properties["fit_model"] == "line"
    assert line.properties["line_source"] == "fit"
    assert set(line.properties["derived_from"]) == source_ids


def test_fit_shape_from_selection_creates_square_from_selected_points(overlay_host):
    """The fit dispatch should create one enclosing square from selected points."""
    _host, controller = overlay_host
    for point_x, point_y in (
        (1.0, 10.8),
        (1.3, 11.2),
        (1.8, 11.1),
        (1.5, 10.9),
    ):
        controller.create_point_annotation(point_x, point_y)
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)

    assert controller.fit_shape_from_selection("square") is True

    square = controller.annotation_set.annotations[-1]
    assert square.semantic_type == "square"
    assert square.geometry.type == "box"
    assert square.properties["fit_model"] == "square"
    assert square.properties["square_source"] == "fit"
    assert set(square.properties["derived_from"]) == source_ids
    min_corner, max_corner = _box_corners(square.geometry)
    width = float(max_corner[0]) - float(min_corner[0])
    height = float(max_corner[1]) - float(min_corner[1])
    assert width == pytest.approx(height)


def test_h_key_fits_horizontal_hyperbola_from_selected_points(overlay_host):
    """The fit shortcut should recover a branch that opens along x."""
    _host, controller = overlay_host
    vertex_x = 1.0
    vertex_y = 10.0
    a = 0.8
    b = 0.5
    for offset in (-0.8, -0.35, 0.0, 0.4, 0.9):
        growth = a * (math.sqrt(1.0 + (offset / b) ** 2) - 1.0)
        controller.create_point_annotation(vertex_x + growth, vertex_y + offset)
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)
    key = _FakeKeyEvent(Qt.Key_H)

    assert controller.handle_key_press(key) is True
    hyperbola = controller.annotation_set.annotations[-1]

    assert hyperbola.semantic_type == "hyperbola"
    assert hyperbola.properties["fit_parameters"]["axis_angle"] == pytest.approx(
        0.0, abs=0.08
    )


def test_h_key_fits_rotated_hyperbola_from_selected_points(overlay_host):
    """The fit shortcut should recover a rotated hyperbola branch."""
    _host, controller = overlay_host
    vertex = np.array((2.0, 5.0), dtype=float)
    axis_angle = math.radians(35.0)
    axis = np.array((math.cos(axis_angle), math.sin(axis_angle)), dtype=float)
    normal = np.array((-axis[1], axis[0]), dtype=float)
    a = 1.2
    b = 0.7
    for offset in (-1.1, -0.6, 0.0, 0.5, 1.0):
        growth = a * (math.sqrt(1.0 + (offset / b) ** 2) - 1.0)
        point = vertex + (growth * axis) + (offset * normal)
        controller.create_point_annotation(float(point[0]), float(point[1]))
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)
    key = _FakeKeyEvent(Qt.Key_H)

    assert controller.handle_key_press(key) is True
    hyperbola = controller.annotation_set.annotations[-1]
    fitted_angle = hyperbola.properties["fit_parameters"]["axis_angle"]

    assert hyperbola.semantic_type == "hyperbola"
    assert fitted_angle == pytest.approx(axis_angle, abs=0.12)


def test_e_key_fits_ellipse_from_selected_points(overlay_host):
    """The fit shortcut should create one ellipse annotation from selected picks."""
    _host, controller = overlay_host
    for point_x, point_y in (
        (0.9, 11.0),
        (1.2, 11.4),
        (1.7, 11.4),
        (2.0, 11.0),
        (1.7, 10.6),
        (1.2, 10.6),
    ):
        controller.create_point_annotation(point_x, point_y)
    source_ids = {annotation.id for annotation in controller.annotation_set.annotations}
    controller.set_selected_annotations(source_ids)
    key = _FakeKeyEvent(Qt.Key_E)

    assert controller.handle_key_press(key) is True
    assert key.accepted is True
    assert len(controller.annotation_set.annotations) == 7
    ellipse = controller.annotation_set.annotations[-1]
    assert ellipse.semantic_type == "ellipse"
    assert ellipse.properties["fit_model"] == "ellipse"
    assert ellipse.properties["ellipse_source"] == "fit"
    assert set(ellipse.properties["derived_from"]) == source_ids


def test_box_tool_requires_double_click_to_create_annotation(overlay_host):
    """Box placement should happen only on background double-click."""
    _host, controller = overlay_host
    controller.set_tool("box")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)
    double_click = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)

    assert controller.handle_scene_event(press) is False
    assert controller.handle_scene_event(release) is False
    assert controller.annotation_set is None

    assert controller.handle_scene_event(double_click) is True

    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "box"
    assert double_click.accepted is True


def test_shift_click_box_tool_creates_annotation_without_double_click(overlay_host):
    """Shift+click should place a box immediately with that tool active."""
    _host, controller = overlay_host
    controller.set_tool("box")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    press._modifiers = Qt.KeyboardModifier.ShiftModifier

    assert controller.handle_scene_event(press) is True
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "box"
    assert press.accepted is True


def test_shift_click_with_non_point_tool_does_not_create_point_annotation(overlay_host):
    """Shift+click should use the active tool instead of always creating a point."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    press = _FakeSceneEvent(QEvent.Type.GraphicsSceneMousePress)
    press._modifiers = Qt.KeyboardModifier.ShiftModifier

    assert controller.handle_scene_event(press) is True
    assert controller.annotation_set is not None
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type != "point"


def test_release_over_selected_hyperbola_does_not_clear_active_handles(overlay_host):
    """Releasing over a selected annotation should not clear the active ROI."""
    _host, controller = overlay_host
    controller.set_tool("hyperbola")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]
    release = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseRelease)
    controller._annotation_item_at_scene_pos = lambda _scene_pos: item

    assert isinstance(item, _AnnotationPathROI)

    controller.handle_scene_event(release)

    assert controller.active_annotation_id == annotation_id
    assert isinstance(controller.annotation_items[annotation_id], _AnnotationPathROI)
    assert any(
        handle.isVisible()
        for handle in controller.annotation_items[annotation_id].getHandles()
    )


def test_point_annotation_created_on_double_click(overlay_host):
    """Point tool should create one fixed annotation on background double-click."""
    _host, controller = overlay_host
    controller.set_tool("point")
    start = _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)

    assert controller.handle_scene_event(start) is True
    assert len(controller.annotation_set.annotations) == 1
    assert controller.annotation_set.annotations[0].geometry.type == "point"


def test_edit_annotation_returns_false_for_missing_or_cancelled_dialog(overlay_host):
    """Editing should fail cleanly for a missing annotation or rejected dialog."""
    _host, controller = overlay_host

    assert controller.edit_annotation("missing") is False

    controller.create_point_annotation(1.0, 11.0)
    controller._editor_class = _FakeDialogCancel

    assert controller.edit_annotation(controller.active_annotation_id) is False


def test_zero_size_box_and_line_are_ignored(overlay_host):
    """Degenerate line/box gestures should not create annotations."""
    _host, controller = overlay_host
    controller.create_box_annotation((1.0, 11.0), (1.0, 11.0))
    controller.create_line_annotation((1.0, 11.0), (1.0, 11.0))

    assert (
        controller.annotation_set is None or controller.annotation_set.annotations == ()
    )


def test_rebuild_items_renders_multi_point_path_geometry(overlay_host):
    """Sampled multi-point paths should render as passive overlay items."""
    _host, controller = overlay_host
    controller.annotation_set = controller.build_empty_set().model_copy(
        update={
            "annotations": (
                Annotation(
                    id="path-3",
                    geometry=PathGeometry(
                        points=(
                            {"distance": 0.0, "time": 10.0},
                            {"distance": 1.0, "time": 11.0},
                            {"distance": 2.0, "time": 12.0},
                        ),
                    ),
                ),
            )
        }
    )

    controller.rebuild_items()

    assert set(controller.annotation_items) == {"path-3"}
    assert isinstance(controller.annotation_items["path-3"], _AnnotationPathDisplayItem)


def test_annotation_from_item_error_paths(overlay_host):
    """Missing axes, missing ids, and unsupported items should raise clean errors."""
    host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    host._axes = None
    with pytest.raises(ValueError, match="axis metadata"):
        controller._annotation_from_item(annotation_id, item)

    host._axes = _Axes()
    with pytest.raises(KeyError):
        controller._annotation_from_item("missing", item)

    with pytest.raises(TypeError, match="unsupported annotation item"):
        controller._annotation_from_item(annotation_id, pg.RectROI([0, 0], [1, 1]))


def test_point_size_falls_back_without_axes(overlay_host):
    """A missing axes object should use the fixed point-size fallback."""
    host, controller = overlay_host
    host._axes = None

    assert controller._point_plot_size() == pytest.approx((4.0 / 3.0, 4.0 / 3.0))


def test_point_items_resize_from_view_range_changes(overlay_host, qtbot):
    """The active point ROI should resize when the host zoom changes."""
    host, controller = overlay_host
    host._plot_item.vb.setRange(xRange=(-10.0, 10.0), yRange=(0.0, 20.0), padding=0)
    qtbot.wait(10)
    controller.create_point_annotation(1.0, 11.0)
    item = controller.annotation_items[controller.active_annotation_id]
    before = (float(item.size().x()), float(item.size().y()))

    host._plot_item.vb.setRange(xRange=(0.9, 1.1), yRange=(10.9, 11.1), padding=0)
    qtbot.wait(10)

    after = (float(item.size().x()), float(item.size().y()))
    assert after != pytest.approx(before)
    assert after[0] < before[0]
    assert after[1] < before[1]


def test_only_active_point_uses_roi_item(overlay_host):
    """Non-active points should use lightweight display items."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    first_id = controller.active_annotation_id
    controller.create_point_annotation(2.0, 12.0)
    second_id = controller.active_annotation_id

    assert isinstance(
        controller.annotation_items[first_id], _AnnotationPointDisplayItem
    )
    assert isinstance(controller.annotation_items[second_id], _AnnotationPointROI)

    controller.set_active_annotation(first_id)

    assert isinstance(controller.annotation_items[first_id], _AnnotationPointROI)
    assert isinstance(
        controller.annotation_items[second_id], _AnnotationPointDisplayItem
    )


def test_creating_new_point_does_not_resize_existing_passive_point(overlay_host):
    """Creating another point should not make the first passive point jump in size."""
    _host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)
    first_id = controller.active_annotation_id
    controller.set_active_annotation(None)
    first_item = controller.annotation_items[first_id]

    assert isinstance(first_item, _AnnotationPointDisplayItem)
    before_size = float(first_item._paint_bounds().width())

    controller.create_point_annotation(2.0, 12.0)

    updated_first_item = controller.annotation_items[first_id]
    assert isinstance(updated_first_item, _AnnotationPointDisplayItem)
    assert float(updated_first_item._paint_bounds().width()) == pytest.approx(
        before_size
    )


def test_active_sampled_path_uses_transform_roi_with_handles(overlay_host):
    """Active sampled paths expose an editable ROI instead of a passive display item."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )

    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPathROI)
    assert any(handle.isVisible() for handle in item.getHandles())


def test_active_ellipse_has_no_rotate_handle(overlay_host):
    """Editable ellipses should support move/resize only, not rotation."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPathROI)
    assert all(handle["type"] != "r" for handle in item.handles)


def test_active_ellipse_persists_axis_aligned_parameters_after_edit(overlay_host):
    """Editable ellipses should stay axis-aligned after resize/translate edits."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPathROI)
    original = controller.annotation_by_id(annotation_id).properties["fit_parameters"]
    item.setPos((float(item.pos().x()) + 1.0, float(item.pos().y()) + 0.5))
    item.setSize(
        (float(item.size().x()) * 1.5, float(item.size().y()) * 0.75),
        center=(0.5, 0.5),
    )
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    params = annotation.properties["fit_parameters"]
    assert params["center_x"] != pytest.approx(original["center_x"])
    assert params["center_y"] != pytest.approx(original["center_y"])
    assert params["radius_x"] != pytest.approx(original["radius_x"])
    assert params["radius_y"] != pytest.approx(original["radius_y"])
    assert params["axis_angle"] == pytest.approx(0.0)


def test_active_ellipse_hit_area_is_localized_to_the_ring(overlay_host):
    """Ellipse hover/click hit testing should stay near the visible ring."""
    _host, controller = overlay_host
    controller.set_tool("ellipse")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPathROI)
    params = controller.annotation_by_id(annotation_id).properties["fit_parameters"]
    center_x = float(params["center_x"])
    center_y = float(params["center_y"])
    radius_x = float(params["radius_x"])

    edge_local = item.mapFromParent(QPointF(center_x + radius_x, center_y))
    center_local = item.mapFromParent(QPointF(center_x, center_y))
    far_local = item.mapFromParent(QPointF(center_x + (radius_x * 4.0), center_y))

    assert item.shape().contains(edge_local)
    assert item.contains(edge_local)
    assert not item.shape().contains(center_local)
    assert not item.contains(center_local)
    assert not item.shape().contains(far_local)
    assert not item.contains(far_local)


def test_active_ellipse_scene_hit_testing_ignores_distant_orbit_points(overlay_host):
    """Scene hit testing should not re-select an ellipse when the pointer is far."""
    host, controller = overlay_host
    controller.set_tool("ellipse")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPathROI)
    params = controller.annotation_by_id(annotation_id).properties["fit_parameters"]
    center_x = float(params["center_x"])
    center_y = float(params["center_y"])
    radius_x = float(params["radius_x"])
    radius_y = float(params["radius_y"])

    for angle_deg in range(0, 360, 15):
        angle_rad = math.radians(angle_deg)
        orbit_plot = QPointF(
            center_x + (math.cos(angle_rad) * radius_x * 2.0),
            center_y + (math.sin(angle_rad) * radius_y * 2.0),
        )
        orbit_scene = host._plot_item.vb.mapViewToScene(orbit_plot)
        assert controller._annotation_item_at_scene_pos(orbit_scene) is None


def test_active_line_scene_hit_testing_stays_near_the_segment(overlay_host):
    """Active line hit testing should reject scene points far from the segment."""
    host, controller = overlay_host
    controller.create_line_annotation((0.5, 10.5), (1.5, 11.5))

    far_scene = host._plot_item.vb.mapViewToScene(QPointF(3.0, 11.0))

    assert controller._annotation_item_at_scene_pos(far_scene) is None


def test_active_box_scene_hit_testing_rejects_distant_points(overlay_host):
    """Active box hit testing should ignore scene points well outside the box."""
    host, controller = overlay_host
    controller.create_box_annotation((0.5, 10.5), (1.5, 11.5))

    far_scene = host._plot_item.vb.mapViewToScene(QPointF(3.0, 13.0))

    assert controller._annotation_item_at_scene_pos(far_scene) is None


def test_point_scene_hit_testing_keeps_padding_local_to_the_point(overlay_host):
    """Point hit testing should stay easy to hit without reaching distant positions."""
    host, controller = overlay_host
    controller.create_point_annotation(1.0, 11.0)

    near_scene = host._plot_item.vb.mapViewToScene(QPointF(1.0, 11.0))
    far_scene = host._plot_item.vb.mapViewToScene(QPointF(3.0, 13.0))

    assert controller._annotation_item_at_scene_pos(near_scene) is not None
    assert controller._annotation_item_at_scene_pos(far_scene) is None


def test_passive_ellipse_hover_hit_area_stays_localized_to_the_ring(overlay_host):
    """Deselected ellipse hover should stay near the visible ring."""
    host, controller = overlay_host
    controller.create_ellipse_annotation((0.5, 10.5), (1.5, 11.5))
    annotation_id = controller.active_annotation_id

    assert controller.handle_key_press(_FakeKeyEvent(Qt.Key_Escape)) is True

    item = controller.annotation_items[annotation_id]
    assert isinstance(item, _AnnotationPathDisplayItem)

    params = controller.annotation_by_id(annotation_id).properties["fit_parameters"]
    center_x = float(params["center_x"])
    center_y = float(params["center_y"])
    radius_x = float(params["radius_x"])
    radius_y = float(params["radius_y"])

    edge_local = item.mapFromParent(QPointF(center_x + radius_x, center_y))
    far_local = item.mapFromParent(QPointF(center_x + (radius_x * 4.0), center_y))

    item.hoverEnterEvent(_FakeHoverEvent(edge_local))
    assert item._hovered is True

    item.hoverMoveEvent(_FakeHoverEvent(far_local))
    assert item._hovered is False

    far_left_scene = host._plot_item.vb.mapViewToScene(
        QPointF(center_x - (radius_x * 4.0), center_y)
    )
    far_right_scene = host._plot_item.vb.mapViewToScene(
        QPointF(center_x + (radius_x * 4.0), center_y)
    )
    far_vertical_scene = host._plot_item.vb.mapViewToScene(
        QPointF(center_x, center_y + (radius_y * 4.0))
    )

    assert controller._annotation_item_at_scene_pos(far_left_scene) is None
    assert controller._annotation_item_at_scene_pos(far_right_scene) is None
    assert controller._annotation_item_at_scene_pos(far_vertical_scene) is None


def test_passive_hyperbola_hit_testing_stays_near_visible_branch(overlay_host):
    """Deselected hyperbola should not hit empty space across the apex row."""
    host, controller = overlay_host
    controller.create_default_hyperbola_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id

    assert controller.handle_key_press(_FakeKeyEvent(Qt.Key_Escape)) is True

    item = controller.annotation_items[annotation_id]
    assert isinstance(item, _AnnotationPathDisplayItem)

    params = controller.annotation_by_id(annotation_id).properties["fit_parameters"]
    vertex_x = float(params["vertex_x"])
    vertex_y = float(params["vertex_y"])
    a = float(params["a"])
    xs, ys = controller._sample_hyperbola_plot_points(params)
    branch_idx = len(xs) // 4
    branch_local = item.mapFromParent(
        QPointF(float(xs[branch_idx]), float(ys[branch_idx]))
    )
    false_local = item.mapFromParent(QPointF(vertex_x + max(a * 0.5, 0.25), vertex_y))

    item.hoverEnterEvent(_FakeHoverEvent(branch_local))
    assert item._hovered is True

    item.hoverMoveEvent(_FakeHoverEvent(false_local))
    assert item._hovered is False

    false_scene = host._plot_item.vb.mapViewToScene(
        QPointF(vertex_x + max(a * 0.5, 0.25), vertex_y)
    )

    assert controller._annotation_item_at_scene_pos(false_scene) is None


def test_passive_path_display_item_avoids_painter_overflow_for_large_coords(qtbot):
    """Passive path items should paint without overflow warnings at large coords."""
    plot_widget = pg.PlotWidget()
    qtbot.addWidget(plot_widget)
    plot_widget.show()
    plot_item = plot_widget.getPlotItem()
    warnings: list[str] = []
    previous = qInstallMessageHandler(None)

    def _handler(msg_type, context, message) -> None:
        if "Painter path exceeds" in message:
            warnings.append(message)
        if previous is not None:
            previous(msg_type, context, message)

    qInstallMessageHandler(_handler)
    try:
        points = tuple(
            (1.7e9 + (index * 10.0), 1.7e9 + (((index - 50) ** 2) * 0.1))
            for index in range(100)
        )
        item = _AnnotationPathDisplayItem(
            "annotation-large-path",
            points=points,
            roi_kind="path",
        )
        plot_item.addItem(item)
        plot_item.vb.setRange(
            xRange=(1.7e9, 1.7e9 + 1000.0),
            yRange=(1.7e9, 1.7e9 + 500.0),
            padding=0,
        )
        qtbot.wait(20)

        assert warnings == []
        assert item.boundingRect().width() > 0.0
        assert item.boundingRect().height() > 0.0
    finally:
        qInstallMessageHandler(previous)


def test_active_box_has_no_rotate_handle(overlay_host):
    """Editable boxes should support move/resize only, not rotation."""
    _host, controller = overlay_host
    controller.set_tool("box")
    controller.handle_scene_event(
        _FakeSceneEvent(QEvent.Type.GraphicsSceneMouseDoubleClick)
    )
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)
    assert all(handle["type"] != "r" for handle in item.handles)


def test_active_box_persists_axis_aligned_geometry_after_edit(overlay_host):
    """Editable boxes should stay axis-aligned after move/resize edits."""
    _host, controller = overlay_host
    controller.create_box_annotation((1.0, 11.0), (2.0, 12.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    item.setPos((1.5, 11.5))
    item.setSize((2.0, 0.5))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation.geometry.type == "box"
    assert _box_corners(annotation.geometry)[0] == pytest.approx((1.5, 11.5))
    assert _box_corners(annotation.geometry)[1] == pytest.approx((3.5, 12.0))
    assert annotation.properties["rotation_angle"] == pytest.approx(0.0)


def test_ctrl_drag_translates_box_roi_in_both_axes(overlay_host):
    """Control-dragging a box ROI should translate freely in x and y."""
    _host, controller = overlay_host
    controller.create_box_annotation((1.0, 11.0), (2.0, 12.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    before = (float(item.pos().x()), float(item.pos().y()))
    center_plot = QPointF(
        before[0] + (float(item.size().x()) / 2),
        before[1] + (float(item.size().y()) / 2),
    )
    end_plot = QPointF(float(center_plot.x()) + 0.6, float(center_plot.y()) + 0.4)

    item.mouseDragEvent(
        _FakeRoiDragEvent(
            item,
            start_parent=(float(center_plot.x()), float(center_plot.y())),
            pos_parent=(float(center_plot.x()), float(center_plot.y())),
            modifiers=Qt.KeyboardModifier.ControlModifier,
            start=True,
        )
    )
    item.mouseDragEvent(
        _FakeRoiDragEvent(
            item,
            start_parent=(float(center_plot.x()), float(center_plot.y())),
            pos_parent=(float(end_plot.x()), float(end_plot.y())),
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
    )
    item.mouseDragEvent(
        _FakeRoiDragEvent(
            item,
            start_parent=(float(center_plot.x()), float(center_plot.y())),
            pos_parent=(float(end_plot.x()), float(end_plot.y())),
            modifiers=Qt.KeyboardModifier.ControlModifier,
            finish=True,
        )
    )
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _box_corners(annotation.geometry)[0][0] > before[0]
    assert _box_corners(annotation.geometry)[0][1] > before[1]


def test_moving_point_snaps_to_existing_annotation_anchor(overlay_host):
    """Point edits should snap to a nearby existing annotation anchor."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_point_annotation(0.0, 10.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPointROI)

    size = item.size()
    item.setPos((2.03 - (float(size.x()) / 2), 12.03 - (float(size.y()) / 2)))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _point_coords(annotation.geometry) == pytest.approx((2.0, 12.0))


def test_moving_point_previews_snap_live_and_unsnaps_when_moved_away(overlay_host):
    """Point ROI drags should preview snapping before mouse release."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_point_annotation(0.0, 10.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPointROI)

    size = item.size()
    item.setPos((2.03 - (float(size.x()) / 2), 12.03 - (float(size.y()) / 2)))
    controller.on_item_changing(item)
    center = (
        float(item.pos().x()) + (float(size.x()) / 2),
        float(item.pos().y()) + (float(size.y()) / 2),
    )
    assert center == pytest.approx((2.0, 12.0))

    item.setPos((2.4 - (float(size.x()) / 2), 12.4 - (float(size.y()) / 2)))
    controller.on_item_changing(item)
    center = (
        float(item.pos().x()) + (float(size.x()) / 2),
        float(item.pos().y()) + (float(size.y()) / 2),
    )
    assert center == pytest.approx((2.4, 12.4))


def test_moving_point_does_not_snap_to_itself(overlay_host):
    """Point edits should ignore the annotation being edited as a snap target."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(1.0, 11.0)
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationPointROI)

    size = item.size()
    item.setPos((1.04 - (float(size.x()) / 2), 11.04 - (float(size.y()) / 2)))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _point_coords(annotation.geometry) == pytest.approx((1.04, 11.04))


def test_line_endpoint_edit_snaps_to_existing_annotation_anchor(overlay_host):
    """Line endpoint edits should snap the moved endpoint to a nearby anchor."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_line_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationLineROI)

    item.movePoint(item.endpoints[1], QPointF(2.04, 12.04))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _path_coords(annotation.geometry)[0] == pytest.approx((0.0, 10.0))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_line_endpoint_previews_snap_live_and_unsnaps_when_moved_away(overlay_host):
    """Line endpoint drags should preview snapping before mouse release."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_line_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationLineROI)

    item.movePoint(item.endpoints[1], QPointF(2.04, 12.04), finish=False)
    controller.on_item_changing(item)
    assert [
        (float(point.x()), float(point.y())) for point in item.plot_endpoints()
    ] == pytest.approx([(0.0, 10.0), (2.0, 12.0)])

    item.movePoint(item.endpoints[1], QPointF(2.4, 12.4), finish=False)
    controller.on_item_changing(item)
    assert [
        (float(point.x()), float(point.y())) for point in item.plot_endpoints()
    ] == pytest.approx([(0.0, 10.0), (2.4, 12.4)])


def test_translating_line_body_persists_translated_endpoints(overlay_host):
    """Dragging a line ROI should persist its translated parent-space endpoints."""
    _host, controller = overlay_host
    controller.create_line_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationLineROI)

    item.setPos((1.5, 0.5))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert annotation.geometry.type == "path"
    assert _path_coords(annotation.geometry)[0] == pytest.approx((1.5, 10.5))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((2.5, 11.5))

    controller.rebuild_items()

    rebuilt_item = controller.annotation_items[annotation_id]
    assert isinstance(rebuilt_item, _AnnotationLineROI)
    assert [
        (float(point.x()), float(point.y())) for point in rebuilt_item.plot_endpoints()
    ] == pytest.approx([(1.5, 10.5), (2.5, 11.5)])


def test_translating_line_body_does_not_snap_when_enabled(overlay_host):
    """Whole-line translations should remain free even when snapping is enabled."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_line_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationLineROI)

    item.setPos((2.03, 2.03))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert _path_coords(annotation.geometry)[0] == pytest.approx((2.03, 12.03))
    assert _path_coords(annotation.geometry)[1] == pytest.approx((3.03, 13.03))


def test_box_corner_edit_snaps_to_existing_annotation_anchor(overlay_host):
    """Box corner edits should snap the dragged corner to a nearby anchor."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_box_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    item.setPos((0.0, 10.0))
    item.setSize((2.03, 2.03))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert isinstance(annotation.geometry, BoxGeometry)
    assert _box_corners(annotation.geometry)[0] == pytest.approx((0.0, 10.0))
    assert _box_corners(annotation.geometry)[1] == pytest.approx((2.0, 12.0))


def test_box_corner_previews_snap_live_and_unsnaps_when_moved_away(overlay_host):
    """Box corner drags should preview snapping before mouse release."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_box_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    item.setPos((0.0, 10.0), finish=False)
    item.setSize((2.04, 2.04), finish=False)
    controller.on_item_changing(item)
    assert (
        float(item.pos().x()) + float(item.size().x()),
        float(item.pos().y()) + float(item.size().y()),
    ) == pytest.approx((2.0, 12.0))

    item.setPos((0.0, 10.0), finish=False)
    item.setSize((2.4, 2.4), finish=False)
    controller.on_item_changing(item)
    assert (
        float(item.pos().x()) + float(item.size().x()),
        float(item.pos().y()) + float(item.size().y()),
    ) == pytest.approx((2.4, 12.4))


def test_translating_box_body_does_not_snap_when_enabled(overlay_host):
    """Whole-box translations should remain free even when snapping is enabled."""
    _host, controller = overlay_host
    controller.set_snap_to_annotations(True)
    controller.create_point_annotation(2.0, 12.0)
    controller.create_box_annotation((0.0, 10.0), (1.0, 11.0))
    annotation_id = controller.active_annotation_id
    item = controller.annotation_items[annotation_id]

    assert isinstance(item, _AnnotationRectROI)

    item.setPos((2.04, 12.04))
    controller.on_item_changed(item)

    annotation = controller.annotation_by_id(annotation_id)
    assert annotation is not None
    assert isinstance(annotation.geometry, BoxGeometry)
    assert _box_corners(annotation.geometry)[0] == pytest.approx((2.04, 12.04))
    assert _box_corners(annotation.geometry)[1] == pytest.approx((3.04, 13.04))


def test_passive_point_item_uses_larger_hit_area_than_visible_dot():
    """Passive point items should be easier to hit than the visible dot alone."""
    item = _AnnotationPointDisplayItem(
        "p1",
        pos=(0.0, 0.0),
        size=40.0,
    )

    assert item.shape().contains(QPointF(24.0, 0.0))
    assert not item._paint_bounds().contains(QPointF(24.0, 0.0))


def test_roi_double_click_items_emit_and_accept(qtbot):
    """Each ROI subclass should emit its double-click signal and accept the event."""
    accepted: list[str] = []

    class _FakeEvent:
        def accept(self):
            accepted.append("accepted")

    point = _AnnotationPointROI("p1", pos=(0, 0), size=(1, 1))
    rect = _AnnotationRectROI("r1", pos=(0, 0), size=(1, 1))
    line = _AnnotationLineROI("l1", positions=((0, 0), (1, 1)))
    for item in (point, rect, line):
        qtbot.addWidget(pg.PlotWidget())  # ensure Qt app is primed for graphics items
    emitted: list[str] = []
    point.sigDoubleClicked.connect(lambda _item: emitted.append("point"))
    rect.sigDoubleClicked.connect(lambda _item: emitted.append("rect"))
    line.sigDoubleClicked.connect(lambda _item: emitted.append("line"))

    point.mouseDoubleClickEvent(_FakeEvent())
    rect.mouseDoubleClickEvent(_FakeEvent())
    line.mouseDoubleClickEvent(_FakeEvent())

    assert emitted == ["point", "rect", "line"]
    assert accepted == ["accepted", "accepted", "accepted"]
