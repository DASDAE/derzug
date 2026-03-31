"""
Tests for the Waterfall widget.
"""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
import numpy as np
import pyqtgraph as pg
import pytest
from AnyQt.QtCore import QEvent, QPointF, Qt
from AnyQt.QtGui import QKeyEvent
from AnyQt.QtTest import QTest
from AnyQt.QtWidgets import QMenu
from dascore.viz.waterfall import _get_scale as get_dascore_waterfall_scale
from derzug.annotations_config import AnnotationConfig, save_annotation_config
from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.utils.testing import (
    TestPatchInputStateDefaults,
    widget_context,
)
from derzug.widgets.selection import PatchSelectionBasis
from derzug.widgets.waterfall import Waterfall


class _FakePatch3D:
    """Minimal patch-like object that forces render failure with 3D data."""

    data: ClassVar[list[list[list[float]]]] = [[[0.0]]]
    dims: ClassVar[tuple[str, str, str]] = ("x", "y", "z")

    @staticmethod
    def get_array(_):
        return [0.0]


class _FakeMouseEvent:
    """Minimal event implementing the pyqtgraph mouse-click API the widget uses."""

    def __init__(
        self,
        x: float,
        y: float,
        *,
        double: bool,
        button: Qt.MouseButton = Qt.LeftButton,
    ) -> None:
        self._scene_pos = QPointF(x, y)
        self._double = double
        self._button = button
        self._accepted = False

    def button(self):
        return self._button

    def double(self) -> bool:
        return self._double

    def scenePos(self):
        return self._scene_pos

    def screenPos(self):
        return self._scene_pos

    def accept(self) -> None:
        self._accepted = True


class _AlwaysContainsRect:
    """Stub scene rect whose contains() check always succeeds."""

    @staticmethod
    def contains(_point) -> bool:
        return True


class _FakeSceneEvent:
    """Minimal scene event for driving annotation controller interactions."""

    def __init__(
        self,
        event_type,
        x: float,
        y: float,
        *,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        self._type = event_type
        self._scene_pos = QPointF(x, y)
        self._modifiers = modifiers
        self._accepted = False

    def type(self):
        return self._type

    def button(self):
        return Qt.LeftButton

    def scenePos(self):
        return self._scene_pos

    def modifiers(self):
        return self._modifiers

    def accept(self) -> None:
        self._accepted = True


class _FakeViewBoxDragEvent:
    """Minimal drag event for driving ViewBox mouse-drag logic directly."""

    def __init__(
        self,
        *,
        button: Qt.MouseButton,
        last_pos: tuple[float, float],
        pos: tuple[float, float],
        finish: bool = False,
    ) -> None:
        self._button = button
        self._last_pos = pg.Point(*last_pos)
        self._pos = pg.Point(*pos)
        self._finish = finish
        self._accepted = False

    def accept(self) -> None:
        self._accepted = True

    def button(self):
        return self._button

    def pos(self):
        return self._pos

    def lastPos(self):
        return self._last_pos

    def buttonDownPos(self, _button=None):
        return self._last_pos

    def isFinish(self) -> bool:
        return self._finish


class _FakeRoiDragEvent:
    """Minimal drag event for driving ROI translation directly."""

    def __init__(
        self,
        roi: pg.ROI,
        *,
        start_parent: tuple[float, float],
        pos_parent: tuple[float, float],
        start: bool = False,
        finish: bool = False,
    ) -> None:
        self._roi = roi
        self._button = Qt.MouseButton.LeftButton
        self._start = start
        self._finish = finish
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
        return Qt.KeyboardModifier.NoModifier

    def buttonDownPos(self):
        return self._button_down_pos

    def pos(self):
        return self._pos

    def buttonDownScenePos(self):
        return self._roi.mapToScene(self._button_down_pos)

    def scenePos(self):
        return self._roi.mapToScene(self._pos)


@pytest.fixture(autouse=True)
def clear_annotation_settings():
    """Reset global annotation settings around each test."""
    save_annotation_config(AnnotationConfig(annotator="tester", organization="DerZug"))
    yield
    save_annotation_config(AnnotationConfig(annotator="tester", organization="DerZug"))


@pytest.fixture
def waterfall_widget(qtbot):
    """Return a live Waterfall widget."""
    with widget_context(Waterfall) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def _capture_patch_output(waterfall_widget, monkeypatch) -> list:
    """Patch the patch output slot with a capture function and return the sink."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(waterfall_widget.Outputs.patch, "send", _sink)
    return received


def _capture_annotation_output(waterfall_widget, monkeypatch) -> list:
    """Patch the annotation output slot with a capture function and return the sink."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(waterfall_widget.Outputs.annotation_set, "send", _sink)
    return received


def _with_datetime_coord(patch: dc.Patch, dim: str) -> dc.Patch:
    """Return a patch with the requested dimension replaced by datetimes."""
    count = len(patch.get_array(dim))
    values = np.datetime64("2024-01-02T03:04:05") + np.arange(count).astype(
        "timedelta64[s]"
    )
    return patch.update_coords(**{dim: values})


def _with_millisecond_datetime_coord(patch: dc.Patch, dim: str) -> dc.Patch:
    """Return a patch with millisecond datetime spacing on the requested dimension."""
    count = len(patch.get_array(dim))
    values = np.datetime64("2024-01-02T03:04:05") + (np.arange(count) * 100).astype(
        "timedelta64[ms]"
    )
    return patch.update_coords(**{dim: values})


def _with_timedelta_coord(patch: dc.Patch, dim: str) -> dc.Patch:
    """Return a patch with the requested dimension replaced by timedeltas."""
    count = len(patch.get_array(dim))
    values = np.arange(count).astype("timedelta64[s]")
    return patch.update_coords(**{dim: values})


def _set_absolute_selection_range(
    waterfall_widget: Waterfall,
    dim: str,
    low: object,
    high: object,
) -> None:
    """Apply one absolute selection range through the shared selection state."""
    waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Absolute")
    waterfall_widget._selection_update_patch_range_absolute(dim, low, high)


def _build_point_annotation_set(patch: dc.Patch) -> AnnotationSet:
    """Build one simple point annotation set aligned to the example patch axes."""
    time_values = np.asarray(patch.get_array("time"))
    distance_values = np.asarray(patch.get_array("distance"))
    return AnnotationSet(
        dims=("time", "distance"),
        annotations=(
            Annotation(
                id="input-point",
                geometry=PointGeometry(
                    dims=("time", "distance"),
                    values=(
                        float(time_values[len(time_values) // 2]),
                        float(distance_values[len(distance_values) // 2]),
                    ),
                ),
                semantic_type="generic",
            ),
        ),
    )


def _double_click_viewport_point(
    waterfall_widget: Waterfall, *, x_index: int, y_index: int
) -> None:
    """Create one point annotation via the real viewport point-preview gesture."""
    axes = waterfall_widget._axes
    assert axes is not None
    waterfall_widget._annotation_tool = "point"
    scene_pos = waterfall_widget._plot_item.vb.mapViewToScene(
        QPointF(float(axes.x_plot[x_index]), float(axes.y_plot[y_index]))
    )
    viewport_pos = waterfall_widget._plot_widget.mapFromScene(scene_pos)
    QTest.mouseDClick(
        waterfall_widget._plot_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        viewport_pos,
    )
    QTest.mouseClick(
        waterfall_widget._plot_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        viewport_pos,
    )


class TestWaterfall:
    """Tests for the Waterfall widget."""

    def test_widget_instantiates(self, waterfall_widget):
        """Widget creates with a non-empty colormap dropdown and valid default."""
        assert waterfall_widget._cmap_combo.count() > 0
        assert waterfall_widget.colormap in Waterfall._COLORMAPS

    def test_reset_on_new_checkbox_has_expected_label_tooltip_and_default(
        self, waterfall_widget
    ):
        """Reset-on-new should be exposed and enabled by default."""
        checkbox = waterfall_widget._reset_on_new_checkbox

        assert checkbox.text() == "reset on new"
        assert checkbox.toolTip() == (
            "reset plot and color bar extents when receiving a new patch"
        )
        assert waterfall_widget.reset_on_new is True
        assert checkbox.isChecked() is True

    def test_reset_on_new_false_restores_from_stored_settings(self, qtbot):
        """Saved disabled reset-on-new should override the new default."""
        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first._reset_on_new_checkbox.setChecked(False)
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)

            assert second.reset_on_new is False
            assert second._reset_on_new_checkbox.isChecked() is False

    def test_annotation_toolbox_is_hidden_on_startup(self, waterfall_widget):
        """The floating annotation toolbox should start hidden when Waterfall opens."""
        assert waterfall_widget._annotation_toolbox.isVisible() is False

    def test_view_menu_includes_annotations_toggle(self, waterfall_widget):
        """Waterfall should expose an Annotations toggle in the View menu."""
        view_menu = waterfall_widget.menuBar().findChild(QMenu, "view-menu")
        assert view_menu is not None

        labels = [
            action.text().replace("&", "")
            for action in view_menu.actions()
            if not action.isSeparator()
        ]

        assert "Annotations" in labels

    def test_waterfall_reuses_existing_view_menu(self, waterfall_widget):
        """Waterfall should attach its actions to the existing top-level View menu."""
        labels = [
            action.text().replace("&", "")
            for action in waterfall_widget.menuBar().actions()
            if action.menu() is not None
        ]

        assert labels.count("View") == 1

    def test_view_menu_annotations_toggle_shows_and_hides_toolbox(
        self, waterfall_widget
    ):
        """The View menu Annotations action should toggle toolbox visibility."""
        view_menu = waterfall_widget.menuBar().findChild(QMenu, "view-menu")
        action = next(
            action
            for action in view_menu.actions()
            if action.text().replace("&", "") == "Annotations"
        )

        assert waterfall_widget._annotation_toolbox.isVisible() is False
        assert action.isChecked() is False

        action.trigger()
        assert waterfall_widget._annotation_toolbox.isVisible() is True
        assert action.isChecked() is True

        action.trigger()
        assert waterfall_widget._annotation_toolbox.isVisible() is False
        assert action.isChecked() is False

    def test_a_key_toggles_annotation_toolbox(self, waterfall_widget, qtbot):
        """Pressing A should toggle the annotation toolbox visibility."""
        assert waterfall_widget._annotation_toolbox.isVisible() is False

        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_A)

        assert waterfall_widget._annotation_toolbox.isVisible() is True
        assert waterfall_widget._toggle_annotations_action.isChecked() is True

        QTest.keyClick(waterfall_widget, Qt.Key_A)

        assert waterfall_widget._annotation_toolbox.isVisible() is False
        assert waterfall_widget._toggle_annotations_action.isChecked() is False

    def test_opening_annotation_toolbox_defaults_to_annotation_selection(
        self, waterfall_widget
    ):
        """Showing the toolbox should switch into explicit annotation selection."""
        waterfall_widget._toggle_annotation_toolbox(True)

        assert waterfall_widget._annotation_toolbox.isVisible() is True
        assert waterfall_widget._annotation_tool == "annotation_select"
        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_toolbox.tool_buttons[
            "annotation_select"
        ].isChecked()

    def test_patch_is_forwarded(self, waterfall_widget, monkeypatch):
        """Input patch is emitted unchanged on the output signal."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        waterfall_widget.set_patch(patch)

        assert received == [patch]

    def test_patch_emits_empty_annotation_set(self, waterfall_widget, monkeypatch):
        """Loading a patch should also emit one empty annotation set."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)

        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))

        assert len(received) == 1
        assert received[0] is not None
        assert received[0].dims == ("time", "distance")
        assert received[0].annotations == ()

    def test_annotation_input_renders_existing_annotations(
        self, waterfall_widget, monkeypatch
    ):
        """Incoming annotation input should render locally without deferred send."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        annotation_set = _build_point_annotation_set(patch)
        waterfall_widget.set_patch(patch)
        received.clear()

        waterfall_widget.set_annotation_set(annotation_set)

        assert waterfall_widget._annotation_set == annotation_set
        assert list(waterfall_widget._annotation_items) == ["input-point"]
        assert received == []

    def test_annotation_input_does_not_become_pending_local_output(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Pressing s after receiving input should do nothing until a local edit."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        annotation_set = _build_point_annotation_set(patch)
        waterfall_widget.set_patch(patch)
        received.clear()

        waterfall_widget.set_annotation_set(annotation_set)
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert received == []

    def test_annotation_input_before_patch_renders_after_matching_patch_arrives(
        self, waterfall_widget
    ):
        """Annotation input received before the patch should render once dims match."""
        patch = dc.get_example_patch("example_event_2")
        annotation_set = _build_point_annotation_set(patch)

        waterfall_widget.set_annotation_set(annotation_set)
        assert waterfall_widget._annotation_set == annotation_set
        assert waterfall_widget._annotation_items == {}

        waterfall_widget.set_patch(patch)

        assert waterfall_widget._annotation_set == annotation_set
        assert list(waterfall_widget._annotation_items) == ["input-point"]

    def test_hidden_set_patch_defers_render_until_show(self, qtbot):
        """Hidden widgets should not build the waterfall image until shown."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as widget:
            calls: list[bool] = []
            original = widget._render_patch

            def _wrapped(*args, **kwargs):
                calls.append(True)
                return original(*args, **kwargs)

            widget._render_patch = _wrapped  # type: ignore[method-assign]
            widget.set_patch(patch)
            assert calls == []

            widget.show()
            qtbot.wait(10)

            assert calls == [True]

    def test_dft_patch_renders_with_fourier_axis(self, waterfall_widget, monkeypatch):
        """Fourier-domain patches should render using their actual dimensions."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").dft("time")

        waterfall_widget.set_patch(patch)

        assert received == [patch]
        assert waterfall_widget._axes is not None
        assert waterfall_widget._axes.y_dim == "distance"
        assert waterfall_widget._axes.x_dim == "ft_time"
        assert waterfall_widget._plot_item.getAxis("left").labelText == "distance"
        assert waterfall_widget._plot_item.getAxis("bottom").labelText == "ft_time"
        assert not waterfall_widget.Error.invalid_patch.is_shown()

    def test_datetime_x_axis_uses_date_axis_item(self, waterfall_widget):
        """Datetime x coordinates should render with an absolute-time date axis."""
        patch = _with_datetime_coord(dc.get_example_patch("example_event_2"), "time")

        waterfall_widget.set_patch(patch)

        assert isinstance(
            waterfall_widget._plot_item.getAxis("bottom"), pg.DateAxisItem
        )
        assert waterfall_widget._axes is not None
        assert waterfall_widget._axes.x_plot[0] > 1_000_000_000
        assert "2024-01-02" in waterfall_widget._plot_item.getAxis("bottom").labelText

    def test_datetime_y_axis_uses_date_axis_item(self, waterfall_widget):
        """Datetime y coordinates should render with an absolute-time date axis."""
        patch = _with_datetime_coord(
            dc.get_example_patch("example_event_2"), "distance"
        )

        waterfall_widget.set_patch(patch)

        assert isinstance(waterfall_widget._plot_item.getAxis("left"), pg.DateAxisItem)
        assert waterfall_widget._axes is not None
        assert waterfall_widget._axes.y_plot[0] > 1_000_000_000
        assert "2024-01-02" in waterfall_widget._plot_item.getAxis("left").labelText

    def test_datetime_axis_point_annotation_emits_persistable_datetime_value(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Datetime point annotations should serialize persistably after s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = _with_datetime_coord(dc.get_example_patch("example_event_2"), "time")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[150]),
            float(axes.y_plot[150]),
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        annotation = received[-1].annotations[0]
        assert annotation.geometry.type == "point"
        assert str(annotation.geometry.values[0]).startswith("2024-01-02 03:")
        dumped = received[-1].model_dump(mode="json")
        assert dumped["annotations"][0]["geometry"]["values"][0].startswith(
            "2024-01-02T03:"
        )

    def test_timedelta_axis_stays_numeric(self, waterfall_widget):
        """Timedelta coordinates should keep the standard numeric axis item."""
        patch = _with_timedelta_coord(dc.get_example_patch("example_event_2"), "time")

        waterfall_widget.set_patch(patch)

        assert type(waterfall_widget._plot_item.getAxis("bottom")) is pg.AxisItem
        assert waterfall_widget._plot_item.getAxis("bottom").labelText == "time"

    def test_datetime_x_label_shows_hour_minute_context_when_zoomed(
        self, waterfall_widget
    ):
        """Fine datetime zooms should add omitted hour/minute context to the label."""
        patch = _with_millisecond_datetime_coord(
            dc.get_example_patch("example_event_2"), "time"
        )
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[10]), float(axes.x_plot[12])),
            yRange=(400.0, 1000.0),
            padding=0,
        )

        assert (
            "2024-01-02 03:04"
            in waterfall_widget._plot_item.getAxis("bottom").labelText
        )

    def test_patch_none_clears_output(self, waterfall_widget, monkeypatch):
        """Sending None clears the display and emits None."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        received.clear()

        waterfall_widget.set_patch(None)

        assert received == [None]
        assert waterfall_widget._axes is None

    def test_patch_none_clears_annotation_output(self, waterfall_widget, monkeypatch):
        """Sending None should also clear the annotation-set output."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        received.clear()

        waterfall_widget.set_patch(None)

        assert received == [None]

    def test_single_click_activates_annotation_layer_and_shows_toolbox(
        self, waterfall_widget
    ):
        """Single clicks should activate the annotation layer and reveal the toolbox."""
        waterfall_widget._hide_annotation_toolbox()
        waterfall_widget._annotation_layer_active = False

        waterfall_widget._activate_annotation_layer()

        assert waterfall_widget._annotation_layer_active is True
        assert waterfall_widget._annotation_toolbox.isVisible()
        assert waterfall_widget._overlay_mode == "annotate"

    def test_middle_drag_pans_view_across_successive_gestures(self, waterfall_widget):
        """Middle-drag should pan repeatedly without falling back to zoom-box mode."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        view_box = waterfall_widget._plot_item.vb
        initial_mouse_mode = view_box.state["mouseMode"]
        view_box.setRange(
            xRange=(float(axes.x_plot[20]), float(axes.x_plot[40])),
            yRange=(float(axes.y_plot[20]), float(axes.y_plot[40])),
            padding=0,
        )
        before_first = view_box.viewRange()

        first_move = _FakeViewBoxDragEvent(
            button=Qt.MouseButton.MiddleButton,
            last_pos=(0.0, 0.0),
            pos=(10.0, 0.0),
        )
        first_finish = _FakeViewBoxDragEvent(
            button=Qt.MouseButton.MiddleButton,
            last_pos=(10.0, 0.0),
            pos=(10.0, 0.0),
            finish=True,
        )
        view_box.mouseDragEvent(first_move)
        after_first = view_box.viewRange()
        view_box.mouseDragEvent(first_finish)

        second_move = _FakeViewBoxDragEvent(
            button=Qt.MouseButton.MiddleButton,
            last_pos=(0.0, 0.0),
            pos=(10.0, 0.0),
        )
        second_finish = _FakeViewBoxDragEvent(
            button=Qt.MouseButton.MiddleButton,
            last_pos=(10.0, 0.0),
            pos=(10.0, 0.0),
            finish=True,
        )
        before_second = view_box.viewRange()
        view_box.mouseDragEvent(second_move)
        after_second = view_box.viewRange()
        view_box.mouseDragEvent(second_finish)

        assert first_move._accepted is True
        assert second_move._accepted is True
        assert after_first[0] != pytest.approx(before_first[0])
        assert after_first[1] == pytest.approx(before_first[1])
        assert (after_first[0][1] - after_first[0][0]) == pytest.approx(
            before_first[0][1] - before_first[0][0]
        )
        assert after_second[0] != pytest.approx(before_second[0])
        assert after_second[1] == pytest.approx(before_second[1])
        assert (after_second[0][1] - after_second[0][0]) == pytest.approx(
            before_second[0][1] - before_second[0][0]
        )
        assert view_box.state["mouseMode"] == initial_mouse_mode

    def test_select_tool_keeps_selection_mode_active(self, waterfall_widget):
        """The select tool should switch the host back into ROI interaction mode."""
        waterfall_widget._activate_annotation_layer()

        waterfall_widget._annotation_tool = "select"

        assert waterfall_widget._overlay_mode == "select"
        assert waterfall_widget._annotation_layer_active is False

    def test_annotation_tool_switches_host_into_annotation_mode(self, waterfall_widget):
        """Picking an annotation tool should enable annotation interaction."""
        waterfall_widget._annotation_tool = "point"

        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_layer_active is True

    def test_hyperbola_tool_switches_host_into_annotation_mode(self, waterfall_widget):
        """Picking the hyperbola tool should enable annotation interaction."""
        waterfall_widget._annotation_tool = "hyperbola"

        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_layer_active is True

    def test_ellipse_tool_switches_host_into_annotation_mode(self, waterfall_widget):
        """Picking the ellipse tool should enable annotation interaction."""
        waterfall_widget._annotation_tool = "ellipse"

        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_layer_active is True

    def test_annotation_select_tool_switches_host_into_annotation_mode(
        self, waterfall_widget
    ):
        """The annotation-select tool should enable annotation interaction."""
        waterfall_widget._annotation_tool = "annotation_select"

        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_layer_active is True

    def test_annotation_select_drag_box_selects_annotations(self, waterfall_widget):
        """The pointer tool should box-select and highlight enclosed annotations."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )
        second_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[220]),
            float(axes.y_plot[220]),
        )
        third_id = waterfall_widget._active_annotation_id
        waterfall_widget._annotation_tool = "annotation_select"

        start_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[70]), float(axes.y_plot[70]))
        )
        end_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[170]), float(axes.y_plot[170]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                start_scene.x(),
                start_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                end_scene.x(),
                end_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                end_scene.x(),
                end_scene.y(),
            )
        )

        selected_ids = waterfall_widget._annotation_controller.selected_annotation_ids
        assert selected_ids == {first_id, second_id}
        selected_color = (
            waterfall_widget._annotation_items[first_id].currentPen.color().getRgb()
        )
        unselected_color = (
            waterfall_widget._annotation_items[third_id].currentPen.color().getRgb()
        )
        assert selected_color != unselected_color

    def test_annotation_select_drag_box_only_selects_points_inside_window(
        self, waterfall_widget
    ):
        """Point box-selection should only include dots whose centers are inside."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "annotation_select"

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        inside_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[150]),
            float(axes.y_plot[150]),
        )
        outside_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[220]),
            float(axes.y_plot[220]),
        )
        far_id = waterfall_widget._active_annotation_id

        start_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[112]), float(axes.y_plot[112]))
        )
        end_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[128]), float(axes.y_plot[128]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                start_scene.x(),
                start_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                end_scene.x(),
                end_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                end_scene.x(),
                end_scene.y(),
            )
        )

        assert waterfall_widget._annotation_controller.selected_annotation_ids == {
            inside_id
        }
        assert (
            outside_id
            not in waterfall_widget._annotation_controller.selected_annotation_ids
        )
        assert (
            far_id
            not in waterfall_widget._annotation_controller.selected_annotation_ids
        )

    def test_create_point_annotation_does_not_emit_until_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Creating one point annotation should stay local until the user presses s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )

        assert received == []
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert len(received) == 1
        annotation_set = received[-1]
        assert annotation_set is not None
        assert len(annotation_set.annotations) == 1
        assert annotation_set.annotations[0].geometry.type == "point"

    def test_unsent_annotations_mark_toolbox_title_until_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """The toolbox title should show unsent state until annotations are sent."""
        _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes

        assert waterfall_widget._annotation_toolbox.title_label.text() == "Annotations"

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )

        assert (
            waterfall_widget._annotation_toolbox.title_label.text() == "Annotations *"
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert waterfall_widget._annotation_toolbox.title_label.text() == "Annotations"

    def test_s_without_new_annotation_changes_does_not_reemit(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Pressing s twice without new annotation changes should emit only once."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_S)
        assert len(received) == 1
        received.clear()

        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert received == []

    def test_second_annotation_change_requires_second_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """A later annotation change should remain unsent until another s press."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)
        assert len(received) == 1
        received.clear()

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )

        assert received == []
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert len(received) == 1
        assert len(received[-1].annotations) == 2

    def test_point_tool_single_click_does_not_create_annotation(self, waterfall_widget):
        """Single-click release in point mode should leave navigation untouched."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        scene_pos = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[150]), float(axes.y_plot[150]))
        )

        handled = waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                scene_pos.x(),
                scene_pos.y(),
            )
        )

        assert handled is False
        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()

    def test_point_tool_double_click_starts_floating_preview(self, waterfall_widget):
        """Double-click in point mode should start a floating point preview."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        scene_pos = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[150]), float(axes.y_plot[150]))
        )

        handled = waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                scene_pos.x(),
                scene_pos.y(),
            )
        )

        assert handled is True
        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()
        assert waterfall_widget._annotation_controller.draw_start is not None
        assert waterfall_widget._annotation_controller.preview_item is not None

    def test_point_tool_places_annotation_on_click_after_preview(
        self, waterfall_widget
    ):
        """A floating point preview should place on the next left click."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        start_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[150]), float(axes.y_plot[150]))
        )
        end_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[170]), float(axes.y_plot[165]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                start_scene.x(),
                start_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                end_scene.x(),
                end_scene.y(),
            )
        )

        handled = waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                end_scene.x(),
                end_scene.y(),
            )
        )

        assert handled is True
        assert waterfall_widget._annotation_set is not None
        assert len(waterfall_widget._annotation_set.annotations) == 1
        assert waterfall_widget._annotation_set.annotations[0].geometry.type == "point"

    def test_shift_click_creates_point_annotation_from_annotation_select(
        self, waterfall_widget
    ):
        """Shift-left-click should place a point without switching to point tool."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "annotation_select"
        scene_pos = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[150]), float(axes.y_plot[150]))
        )

        handled = waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                scene_pos.x(),
                scene_pos.y(),
                modifiers=Qt.KeyboardModifier.ShiftModifier,
            )
        )

        assert handled is True
        assert waterfall_widget._annotation_tool == "annotation_select"
        assert waterfall_widget._annotation_set is not None
        assert len(waterfall_widget._annotation_set.annotations) == 1
        assert waterfall_widget._annotation_set.annotations[0].geometry.type == "point"

    def test_ui_created_points_mark_dirty_and_restore_from_stored_settings(self, qtbot):
        """Real scene-created points should mark dirty, restore, and keep zoom."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            axes = first._axes
            first._annotation_tool = "point"
            first._plot_item.vb.setRange(
                xRange=(float(axes.x_plot[100]), float(axes.x_plot[220])),
                yRange=(float(axes.y_plot[90]), float(axes.y_plot[210])),
                padding=0,
            )
            before_view = first._plot_item.vb.viewRange()

            for x_index, y_index in ((120, 120), (140, 140), (160, 160)):
                scene_pos = first._plot_item.vb.mapViewToScene(
                    QPointF(float(axes.x_plot[x_index]), float(axes.y_plot[y_index]))
                )
                started = first._annotation_controller.handle_scene_event(
                    _FakeSceneEvent(
                        QEvent.Type.GraphicsSceneMouseDoubleClick,
                        scene_pos.x(),
                        scene_pos.y(),
                    )
                )
                placed = first._annotation_controller.handle_scene_event(
                    _FakeSceneEvent(
                        QEvent.Type.GraphicsSceneMousePress,
                        scene_pos.x(),
                        scene_pos.y(),
                    )
                )
                assert started is True
                assert placed is True

            assert first._annotation_set is not None
            assert len(first._annotation_set.annotations) == 3
            assert first._annotation_toolbox.title_label.text() == "Annotations *"

            saved = first.settingsHandler.pack_data(first)

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)
            after_view = second._plot_item.vb.viewRange()

            assert second._annotation_set is not None
            assert len(second._annotation_set.annotations) == 3
            assert len(second._annotation_items) == 3
            assert second._annotation_toolbox.title_label.text() == "Annotations"
            assert np.allclose(after_view[0], before_view[0])
            assert np.allclose(after_view[1], before_view[1])

    def test_viewport_double_click_restores_focus_for_s_shortcut(
        self, waterfall_widget, qtbot
    ):
        """Real viewport annotation creation should return focus to Waterfall."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        _double_click_viewport_point(waterfall_widget, x_index=120, y_index=120)

        assert waterfall_widget._annotation_set is not None
        assert len(waterfall_widget._annotation_set.annotations) == 1
        qtbot.waitUntil(lambda: waterfall_widget.hasFocus(), timeout=1000)

    def test_creating_point_annotation_does_not_change_view_extents(
        self, waterfall_widget
    ):
        """Adding a point annotation should not change the current zoom."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
            yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
            padding=0,
        )
        before = waterfall_widget._plot_item.vb.viewRange()

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[150]),
            float(axes.y_plot[150]),
        )

        after = waterfall_widget._plot_item.vb.viewRange()
        assert waterfall_widget._annotation_set is not None
        assert len(waterfall_widget._annotation_set.annotations) == 1
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_point_annotation_has_visible_centered_render_item(self, waterfall_widget):
        """A placed point annotation renders with non-zero bounds at its center."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[150]),
            float(axes.y_plot[150]),
        )

        item = waterfall_widget._annotation_items[
            waterfall_widget._active_annotation_id
        ]
        bounds = item.sceneBoundingRect()
        expected_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[150]), float(axes.y_plot[150]))
        )
        item_center_scene = item.mapToScene(item.boundingRect().center())
        assert bounds.width() > 0
        assert bounds.height() > 0
        assert abs(item_center_scene.x() - expected_scene.x()) < 2
        assert abs(item_center_scene.y() - expected_scene.y()) < 2

    def test_activated_point_annotation_can_then_be_dragged(
        self, waterfall_widget, qtbot
    ):
        """Activating a passive point should allow a later drag to move it."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[170]),
            float(axes.y_plot[170]),
        )
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)
        assert waterfall_widget._annotation_tool == "annotation_select"

        first_item = waterfall_widget._annotation_items[first_id]
        waterfall_widget._annotation_controller.on_item_clicked(first_item, None)
        qtbot.wait(10)

        assert waterfall_widget._active_annotation_id == first_id
        waterfall_widget._annotation_tool = "annotation_select"

        active_item = waterfall_widget._annotation_items[first_id]
        before = waterfall_widget._annotation_set.annotations[0].geometry.values
        active_center_scene = active_item.sceneBoundingRect().center()
        active_center_viewport = waterfall_widget._plot_widget.mapFromScene(
            active_center_scene
        )
        end_viewport = active_center_viewport + QPointF(18, -14).toPoint()

        QTest.mousePress(
            waterfall_widget._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            active_center_viewport,
        )
        QTest.mouseMove(waterfall_widget._plot_widget.viewport(), end_viewport)
        QTest.mouseRelease(
            waterfall_widget._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            end_viewport,
        )
        qtbot.wait(10)

        after_annotation = next(
            annotation
            for annotation in waterfall_widget._annotation_set.annotations
            if annotation.id == first_id
        )
        assert after_annotation.geometry.values != pytest.approx(before)

    def test_shift_drag_moves_all_selected_annotations_together(
        self, waterfall_widget, qtbot
    ):
        """Shift-dragging one selected annotation should move the whole selection."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[170]),
            float(axes.y_plot[170]),
        )
        second_id = waterfall_widget._active_annotation_id
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)
        assert waterfall_widget._annotation_tool == "annotation_select"

        waterfall_widget._annotation_controller.set_selected_annotations(
            {first_id, second_id}
        )
        qtbot.wait(10)

        before = {
            annotation.id: annotation.geometry.values
            for annotation in waterfall_widget._annotation_set.annotations
            if annotation.id in {first_id, second_id}
        }

        active_item = waterfall_widget._annotation_items[first_id]
        active_center_scene = active_item.mapToScene(
            active_item.boundingRect().center()
        )
        end_scene = active_center_scene + QPointF(18.0, -14.0)

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                active_center_scene.x(),
                active_center_scene.y(),
                modifiers=Qt.KeyboardModifier.ShiftModifier,
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                end_scene.x(),
                end_scene.y(),
                modifiers=Qt.KeyboardModifier.ShiftModifier,
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                end_scene.x(),
                end_scene.y(),
                modifiers=Qt.KeyboardModifier.ShiftModifier,
            )
        )
        qtbot.wait(10)

        after = {
            annotation.id: annotation.geometry.values
            for annotation in waterfall_widget._annotation_set.annotations
            if annotation.id in {first_id, second_id}
        }
        first_delta = (
            float(after[first_id][0]) - float(before[first_id][0]),
            float(after[first_id][1]) - float(before[first_id][1]),
        )
        second_delta = (
            float(after[second_id][0]) - float(before[second_id][0]),
            float(after[second_id][1]) - float(before[second_id][1]),
        )

        assert first_delta != pytest.approx((0.0, 0.0))
        assert second_delta == pytest.approx(first_delta)

    def test_point_annotation_stays_roughly_constant_screen_size_when_zooming(
        self, waterfall_widget, qtbot
    ):
        """Point annotations should recompute plot-space size when the zoom changes."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[150]),
            float(axes.y_plot[150]),
        )
        item = waterfall_widget._annotation_items[
            waterfall_widget._active_annotation_id
        ]
        before = (float(item.size().x()), float(item.size().y()))
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[120]), float(axes.x_plot[180])),
            yRange=(float(axes.y_plot[120]), float(axes.y_plot[180])),
            padding=0,
        )
        qtbot.wait(10)
        after = (float(item.size().x()), float(item.size().y()))

        assert after != pytest.approx(before)
        assert after[0] < before[0]
        assert after[1] < before[1]

    def test_hyperbola_tool_double_click_creates_sampled_path_annotation(
        self, waterfall_widget
    ):
        """Double-clicking with the hyperbola tool should create one branch."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "hyperbola"
        target_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                target_scene.x(),
                target_scene.y(),
            )
        )

        annotation = waterfall_widget._annotation_set.annotations[0]
        assert annotation.semantic_type == "hyperbola"
        assert annotation.geometry.type == "path"
        assert len(annotation.geometry.points) > 10
        assert annotation.properties["fit_model"] == "hyperbola"
        assert annotation.properties["hyperbola_source"] == "manual"
        assert "u = " in annotation.properties["hyperbola_equation"]

    def test_line_tool_double_click_anchors_then_single_click_commits_annotation(
        self, waterfall_widget
    ):
        """The line tool should anchor on double-click and commit on a later click."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "line"
        anchor_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )
        end_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[170]), float(axes.y_plot[165]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                anchor_scene.x(),
                anchor_scene.y(),
            )
        )
        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()
        assert waterfall_widget._annotation_controller.draw_start is not None

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                end_scene.x(),
                end_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                end_scene.x(),
                end_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                end_scene.x(),
                end_scene.y(),
            )
        )

        annotation = waterfall_widget._annotation_set.annotations[0]
        assert annotation.semantic_type == "line"
        assert annotation.geometry.type == "path"
        assert len(annotation.geometry.points) == 2

    def test_line_tool_anchor_preview_and_commit_snap_to_existing_point(
        self, waterfall_widget
    ):
        """
        The pending line endpoint should preview-snap and commit to a nearby
        point.
        """
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._toggle_annotation_toolbox(True)
        waterfall_widget._annotation_toolbox.snap_button.setChecked(True)
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[170]),
            float(axes.y_plot[165]),
        )
        waterfall_widget._annotation_tool = "line"
        anchor_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )
        point_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[170]), float(axes.y_plot[165]))
        )
        near_scene = point_scene + QPointF(5.0, 5.0)

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                anchor_scene.x(),
                anchor_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseMove,
                near_scene.x(),
                near_scene.y(),
            )
        )

        preview = waterfall_widget._annotation_controller.preview_item
        assert isinstance(preview, pg.PlotDataItem)
        xs, ys = preview.getData()
        assert (float(xs[-1]), float(ys[-1])) == pytest.approx(
            (float(axes.x_plot[170]), float(axes.y_plot[165]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMousePress,
                near_scene.x(),
                near_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseRelease,
                near_scene.x(),
                near_scene.y(),
            )
        )

        annotation = waterfall_widget._annotation_set.annotations[-1]
        assert annotation.semantic_type == "line"
        assert annotation.geometry.points[1] == pytest.approx(
            (float(axes.x_plot[170]), float(axes.y_plot[165]))
        )

    def test_escape_cancels_pending_line_anchor_in_waterfall(
        self, waterfall_widget, qtbot
    ):
        """Escape should cancel an anchored line preview before the final click."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "line"
        anchor_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                anchor_scene.x(),
                anchor_scene.y(),
            )
        )
        assert waterfall_widget._annotation_controller.draw_start is not None
        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()

        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert waterfall_widget._annotation_controller.draw_start is None
        assert waterfall_widget._annotation_controller.preview_item is None
        assert waterfall_widget._annotation_set.annotations == ()

    def test_ellipse_tool_double_click_creates_sampled_path_annotation(
        self, waterfall_widget
    ):
        """Double-clicking with the ellipse tool should create one sampled path loop."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "ellipse"
        target_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                target_scene.x(),
                target_scene.y(),
            )
        )

        annotation = waterfall_widget._annotation_set.annotations[0]
        assert annotation.semantic_type == "ellipse"
        assert annotation.geometry.type == "path"
        assert len(annotation.geometry.points) > 10
        assert annotation.properties["fit_model"] == "ellipse"
        assert annotation.properties["ellipse_source"] == "manual"

    def test_escape_deselected_hyperbola_does_not_hit_across_apex_row(
        self, waterfall_widget, qtbot
    ):
        """After Escape, hyperbola hover/click selection should stay near the branch."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "hyperbola"
        target_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                target_scene.x(),
                target_scene.y(),
            )
        )

        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        annotation = waterfall_widget._annotation_set.annotations[0]
        params = annotation.properties["fit_parameters"]
        vertex_x = float(params["vertex_x"])
        vertex_y = float(params["vertex_y"])
        a = float(params["a"])
        xs, ys = waterfall_widget._annotation_controller._sample_hyperbola_plot_points(
            params
        )
        branch_idx = len(xs) // 4
        item = waterfall_widget._annotation_controller.annotation_items[annotation.id]
        branch_local = item.mapFromParent(
            QPointF(float(xs[branch_idx]), float(ys[branch_idx]))
        )
        false_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(vertex_x + max(a * 0.5, 0.25), vertex_y)
        )
        branch_scene = item.mapToScene(branch_local)

        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                false_scene
            )
            is None
        )
        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                branch_scene
            )
            is not None
        )

    def test_escape_deselected_ellipse_does_not_hit_across_center_row(
        self, waterfall_widget, qtbot
    ):
        """After Escape, ellipse hover/click selection should stay near the ring."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "ellipse"
        target_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[145]), float(axes.y_plot[130]))
        )

        assert waterfall_widget._annotation_controller.handle_scene_event(
            _FakeSceneEvent(
                QEvent.Type.GraphicsSceneMouseDoubleClick,
                target_scene.x(),
                target_scene.y(),
            )
        )

        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        annotation = waterfall_widget._annotation_set.annotations[0]
        params = annotation.properties["fit_parameters"]
        center_x = float(params["center_x"])
        center_y = float(params["center_y"])
        radius_x = float(params["radius_x"])
        item = waterfall_widget._annotation_controller.annotation_items[annotation.id]
        ring_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(center_x + radius_x, center_y)
        )
        far_left_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(center_x - (radius_x * 4.0), center_y)
        )
        far_right_scene = waterfall_widget._plot_item.vb.mapViewToScene(
            QPointF(center_x + (radius_x * 4.0), center_y)
        )
        ring_local = item.mapFromParent(QPointF(center_x + radius_x, center_y))
        ring_branch_scene = item.mapToScene(ring_local)

        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                far_left_scene
            )
            is None
        )
        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                far_right_scene
            )
            is None
        )
        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                ring_scene
            )
            is not None
        )
        assert (
            waterfall_widget._annotation_controller._annotation_item_at_scene_pos(
                ring_branch_scene
            )
            is not None
        )

    def test_delete_active_annotation_removes_it(self, waterfall_widget, monkeypatch):
        """Delete should stay local until the user presses s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )
        annotation_id = waterfall_widget._active_annotation_id
        received.clear()

        waterfall_widget._delete_annotation(annotation_id)

        assert received == []

    def test_delete_active_annotation_sends_after_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Deleting one annotation should emit only after pressing s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )
        annotation_id = waterfall_widget._active_annotation_id
        waterfall_widget._delete_annotation(annotation_id)
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        assert len(received) == 1
        assert received[-1] is not None
        assert received[-1].annotations == ()

    def test_selected_annotation_deletes_with_delete_key_without_tool_button(
        self, waterfall_widget, qtbot
    ):
        """Waterfall relies on Delete for annotation removal, not a toolbar button."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )
        annotation_id = waterfall_widget._active_annotation_id
        assert annotation_id is not None
        assert "delete" not in waterfall_widget._annotation_toolbox.tool_buttons

        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()

    def test_annotation_toolbox_orders_tools_point_line_box_ellipse_hyperbola(
        self, waterfall_widget
    ):
        """Waterfall should present annotation tools in the requested working order."""
        assert tuple(waterfall_widget._annotation_toolbox.tool_buttons) == (
            "annotation_select",
            "point",
            "line",
            "box",
            "ellipse",
            "hyperbola",
        )

    def test_number_key_labels_selected_annotations_and_sends_after_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Number keys should stay local until the user presses s."""
        save_annotation_config(
            AnnotationConfig(
                annotator="tester",
                organization="DerZug",
                label_names={"1": "p_pick"},
            )
        )
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )
        second_id = waterfall_widget._active_annotation_id
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            {first_id, second_id}
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_1)
        assert received == []
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        labeled = {annotation.id: annotation.label for annotation in latest.annotations}
        assert labeled[first_id] == "p_pick"
        assert labeled[second_id] == "p_pick"

    def test_zero_key_clears_selected_annotation_labels_and_sends_after_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Zero should stay local until the user presses s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        annotation_id = waterfall_widget._active_annotation_id
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            {annotation_id}
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_2)
        QTest.keyClick(waterfall_widget, Qt.Key_S)
        received.clear()

        QTest.keyClick(waterfall_widget, Qt.Key_0)
        assert received == []
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        assert latest.annotations[0].id == annotation_id
        assert latest.annotations[0].label is None

    def test_created_annotations_send_global_identity_fields_after_s(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Created annotations should include global metadata when sent with s."""
        save_annotation_config(
            AnnotationConfig(annotator="alice", organization="DASDAE")
        )
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes

        waterfall_widget._create_point_annotation(
            float(axes.x_plot[120]),
            float(axes.y_plot[120]),
        )
        assert received == []
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        assert latest.annotations[0].annotator == "alice"
        assert latest.annotations[0].organization == "DASDAE"

    def test_h_key_fits_hyperbola_from_selected_points_and_emits(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """H should fit locally, then emit after the user presses s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        point_indices = ((110, 108), (126, 120), (155, 138), (188, 160))
        source_ids = []
        for x_index, y_index in point_indices:
            waterfall_widget._create_point_annotation(
                float(axes.x_plot[x_index]),
                float(axes.y_plot[y_index]),
            )
            source_ids.append(waterfall_widget._active_annotation_id)
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            set(source_ids)
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        received.clear()

        QTest.keyClick(waterfall_widget, Qt.Key_H)
        assert received == []
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        assert len(latest.annotations) == len(source_ids) + 1
        hyperbola = latest.annotations[-1]
        assert hyperbola.semantic_type == "hyperbola"
        assert hyperbola.properties["fit_model"] == "hyperbola"
        assert hyperbola.properties["hyperbola_source"] == "fit"
        assert "u = " in hyperbola.properties["hyperbola_equation"]
        assert set(hyperbola.properties["derived_from"]) == set(source_ids)
        assert len(hyperbola.geometry.points) > 10

    def test_fit_menu_line_creates_annotation_and_emits(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Fit requests should create locally, then emit after s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        point_indices = ((110, 108), (126, 120), (155, 138), (188, 160))
        source_ids = []
        for x_index, y_index in point_indices:
            waterfall_widget._create_point_annotation(
                float(axes.x_plot[x_index]),
                float(axes.y_plot[y_index]),
            )
            source_ids.append(waterfall_widget._active_annotation_id)
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            set(source_ids)
        )
        received.clear()

        waterfall_widget._on_annotation_fit_requested("line")
        assert received == []
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        line = latest.annotations[-1]
        assert len(latest.annotations) == len(source_ids) + 1
        assert line.semantic_type == "line"
        assert line.geometry.type == "path"
        assert len(line.geometry.points) == 2
        assert line.properties["fit_model"] == "line"
        assert set(line.properties["derived_from"]) == set(source_ids)

    def test_fit_menu_square_creates_annotation_and_emits(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Fit requests should create locally, then emit after s."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        point_indices = ((130, 140), (150, 170), (175, 150), (145, 130))
        source_ids = []
        for x_index, y_index in point_indices:
            waterfall_widget._create_point_annotation(
                float(axes.x_plot[x_index]),
                float(axes.y_plot[y_index]),
            )
            source_ids.append(waterfall_widget._active_annotation_id)
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            set(source_ids)
        )
        received.clear()

        waterfall_widget._on_annotation_fit_requested("square")
        assert received == []
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        square = latest.annotations[-1]
        assert len(latest.annotations) == len(source_ids) + 1
        assert square.semantic_type == "square"
        assert square.geometry.type == "box"
        assert square.properties["fit_model"] == "square"
        assert set(square.properties["derived_from"]) == set(source_ids)

    def test_right_click_selected_points_shows_annotation_fit_menu(
        self, waterfall_widget, monkeypatch
    ):
        """Selected points should override the default context menu with Fit."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        source_ids = []
        for x_index, y_index in ((120, 150), (140, 170), (170, 170)):
            waterfall_widget._create_point_annotation(
                float(axes.x_plot[x_index]),
                float(axes.y_plot[y_index]),
            )
            source_ids.append(waterfall_widget._active_annotation_id)
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            set(source_ids)
        )
        shown: list[QMenu] = []

        def _fake_exec(menu, *_args, **_kwargs):
            shown.append(menu)

        monkeypatch.setattr(QMenu, "exec", _fake_exec)
        event = _FakeMouseEvent(
            0.0,
            500.0,
            double=False,
            button=Qt.RightButton,
        )

        waterfall_widget._on_plot_mouse_clicked(event)

        assert event._accepted is True
        assert len(shown) == 1
        fit_menu = next(
            action.menu()
            for action in shown[0].actions()
            if action.text().replace("&", "") == "Fit"
        )
        assert fit_menu is not None
        assert [action.text().replace("&", "") for action in fit_menu.actions()] == [
            "Line",
            "Ellipse",
            "Square",
            "Hyperbola",
        ]

    def test_e_key_fits_ellipse_from_selected_points_and_emits(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """E should fit one ellipse annotation from the selected point picks."""
        received = _capture_annotation_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        point_indices = (
            (120, 150),
            (140, 170),
            (170, 170),
            (190, 150),
            (170, 130),
            (140, 130),
        )
        source_ids = []
        for x_index, y_index in point_indices:
            waterfall_widget._create_point_annotation(
                float(axes.x_plot[x_index]),
                float(axes.y_plot[y_index]),
            )
            source_ids.append(waterfall_widget._active_annotation_id)
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            set(source_ids)
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)
        received.clear()

        QTest.keyClick(waterfall_widget, Qt.Key_E)
        assert received == []
        QTest.keyClick(waterfall_widget, Qt.Key_S)

        latest = received[-1]
        assert len(latest.annotations) == len(source_ids) + 1
        ellipse = latest.annotations[-1]
        assert ellipse.semantic_type == "ellipse"
        assert ellipse.properties["fit_model"] == "ellipse"
        assert ellipse.properties["ellipse_source"] == "fit"
        assert set(ellipse.properties["derived_from"]) == set(source_ids)
        assert len(ellipse.geometry.points) > 10

    def test_h_key_requires_three_selected_point_annotations(
        self, waterfall_widget, qtbot
    ):
        """Hyperbola fitting should refuse underspecified selections."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[110]),
            float(axes.y_plot[110]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[126]),
            float(axes.y_plot[120]),
        )
        second_id = waterfall_widget._active_annotation_id
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            {first_id, second_id}
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_H)

        assert waterfall_widget.Warning.hyperbola_fit_requires_points.is_shown()
        assert len(waterfall_widget._annotation_set.annotations) == 2

    def test_e_key_requires_three_selected_point_annotations(
        self, waterfall_widget, qtbot
    ):
        """Ellipse fitting should refuse underspecified selections."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[110]),
            float(axes.y_plot[110]),
        )
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[126]),
            float(axes.y_plot[120]),
        )
        second_id = waterfall_widget._active_annotation_id
        waterfall_widget._annotation_tool = "annotation_select"
        waterfall_widget._annotation_controller.set_selected_annotations(
            {first_id, second_id}
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_E)

        assert waterfall_widget.Warning.ellipse_fit_requires_points.is_shown()
        assert len(waterfall_widget._annotation_set.annotations) == 2

    def test_highlighted_annotation_deletes_with_delete_key(
        self, waterfall_widget, qtbot
    ):
        """Delete should remove a highlighted annotation even without an active id."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )
        annotation_id = waterfall_widget._active_annotation_id
        assert annotation_id is not None

        waterfall_widget._annotation_tool = "annotation_select"
        selected = {annotation_id}
        waterfall_widget._annotation_controller.selected_annotation_ids = selected
        waterfall_widget._annotation_controller.active_annotation_id = None
        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._annotation_set is not None
        assert waterfall_widget._annotation_set.annotations == ()

    def test_edit_annotation_updates_metadata(self, waterfall_widget, monkeypatch):
        """Double-click editing should update only metadata fields."""

        class _FakeDialog:
            def __init__(self, annotation, parent=None):
                self.annotation = annotation

            def exec(self):
                return 1

            def values(self):
                return {
                    "semantic_type": "arrival_pick",
                    "notes": "picked",
                    "tags": ("arrival", "manual"),
                    "group": "event-1",
                    "label": "p_pick",
                    "properties": {"confidence": 0.9},
                }

        monkeypatch.setattr(
            "derzug.widgets.waterfall._AnnotationEditorDialog", _FakeDialog
        )
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[len(axes.x_plot) // 2]),
            float(axes.y_plot[len(axes.y_plot) // 2]),
        )
        annotation_id = waterfall_widget._active_annotation_id

        assert waterfall_widget._edit_annotation(annotation_id) is True

        annotation = waterfall_widget._annotation_by_id(annotation_id)
        assert annotation is not None
        assert annotation.semantic_type == "arrival_pick"
        assert annotation.notes == "picked"
        assert annotation.tags == ("arrival", "manual")
        assert annotation.group == "event-1"
        assert annotation.label == "p_pick"
        assert annotation.properties == {"confidence": 0.9}

    def test_only_active_box_shows_resize_handles(self, waterfall_widget):
        """Resize handles should only be visible on the active annotation."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        start = (float(axes.x_plot[5]), float(axes.y_plot[5]))
        end = (float(axes.x_plot[15]), float(axes.y_plot[15]))
        waterfall_widget._create_box_annotation(start, end)
        first_id = waterfall_widget._active_annotation_id
        waterfall_widget._create_box_annotation(
            (float(axes.x_plot[20]), float(axes.y_plot[20])),
            (float(axes.x_plot[30]), float(axes.y_plot[30])),
        )
        second_id = waterfall_widget._active_annotation_id
        first_item = waterfall_widget._annotation_items[first_id]
        second_item = waterfall_widget._annotation_items[second_id]

        assert not any(handle.isVisible() for handle in first_item.getHandles())
        assert any(handle.isVisible() for handle in second_item.getHandles())

    def test_select_mode_locks_existing_annotations(self, waterfall_widget):
        """Annotations stay visible but stop accepting clicks in select mode."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_box_annotation(
            (float(axes.x_plot[5]), float(axes.y_plot[5])),
            (float(axes.x_plot[15]), float(axes.y_plot[15])),
        )
        item = waterfall_widget._annotation_items[
            waterfall_widget._active_annotation_id
        ]

        waterfall_widget._annotation_tool = "select"

        assert waterfall_widget._overlay_mode == "select"
        assert item.acceptedMouseButtons() == Qt.MouseButton.NoButton
        assert not any(handle.isVisible() for handle in item.getHandles())

    def test_roi_selection_emits_clipped_patch(self, waterfall_widget, monkeypatch):
        """Creating an ROI emits a patch clipped to the selected window."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        x_center = float((axes.x_plot[0] + axes.x_plot[-1]) / 2)
        y_center = float((axes.y_plot[0] + axes.y_plot[-1]) / 2)
        waterfall_widget._create_selection_roi(center_x=x_center, center_y=y_center)

        assert len(received) >= 2
        selected = received[-1]
        assert selected is not None
        assert selected.shape[0] < patch.shape[0]
        assert selected.shape[1] < patch.shape[1]

    def test_annotation_mode_locks_existing_roi(self, waterfall_widget):
        """The selection ROI should remain visible but stop accepting input."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        waterfall_widget._annotation_tool = "point"

        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._roi is not None
        assert waterfall_widget._roi.acceptedMouseButtons() == Qt.MouseButton.NoButton
        assert not any(
            handle.isVisible() for handle in waterfall_widget._roi.getHandles()
        )

    def test_user_can_drag_roi_from_center_in_select_mode(self, waterfall_widget):
        """Press-dragging the ROI center through the viewport should move the ROI."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None

        before = (float(roi.pos().x()), float(roi.pos().y()))
        center_plot = QPointF(
            before[0] + (float(roi.size().x()) / 2),
            before[1] + (float(roi.size().y()) / 2),
        )
        start_scene = waterfall_widget._plot_item.vb.mapViewToScene(center_plot)
        start_viewport = waterfall_widget._plot_widget.mapFromScene(start_scene)
        end_viewport = start_viewport + QPointF(24, 18).toPoint()
        end_scene = waterfall_widget._plot_widget.mapToScene(end_viewport)
        end_plot = waterfall_widget._plot_item.vb.mapSceneToView(end_scene)

        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(center_plot.x()), float(center_plot.y())),
                start=True,
            )
        )
        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(end_plot.x()), float(end_plot.y())),
            )
        )
        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(end_plot.x()), float(end_plot.y())),
                finish=True,
            )
        )

        after = (float(roi.pos().x()), float(roi.pos().y()))
        assert after != pytest.approx(before)

    def test_dragging_roi_does_not_change_view_extents(self, waterfall_widget):
        """Dragging the ROI should not reset the current waterfall zoom."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
            yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
            padding=0,
        )
        x_center = float((axes.x_plot[100] + axes.x_plot[200]) / 2)
        y_center = float((axes.y_plot[100] + axes.y_plot[200]) / 2)
        waterfall_widget._create_selection_roi(
            center_x=x_center,
            center_y=y_center,
        )
        before_view = waterfall_widget._plot_item.vb.viewRange()
        roi = waterfall_widget._roi
        assert roi is not None

        before_pos = (float(roi.pos().x()), float(roi.pos().y()))
        center_plot = QPointF(
            before_pos[0] + (float(roi.size().x()) / 2),
            before_pos[1] + (float(roi.size().y()) / 2),
        )
        start_scene = waterfall_widget._plot_item.vb.mapViewToScene(center_plot)
        start_viewport = waterfall_widget._plot_widget.mapFromScene(start_scene)
        end_viewport = start_viewport + QPointF(24, 18).toPoint()
        end_scene = waterfall_widget._plot_widget.mapToScene(end_viewport)
        end_plot = waterfall_widget._plot_item.vb.mapSceneToView(end_scene)

        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(center_plot.x()), float(center_plot.y())),
                start=True,
            )
        )
        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(end_plot.x()), float(end_plot.y())),
            )
        )
        roi.mouseDragEvent(
            _FakeRoiDragEvent(
                roi,
                start_parent=(float(center_plot.x()), float(center_plot.y())),
                pos_parent=(float(end_plot.x()), float(end_plot.y())),
                finish=True,
            )
        )

        after_view = waterfall_widget._plot_item.vb.viewRange()
        after_pos = (float(roi.pos().x()), float(roi.pos().y()))
        assert after_pos != pytest.approx(before_pos)
        assert np.allclose(after_view[0], before_view[0])
        assert np.allclose(after_view[1], before_view[1])

    def test_select_mode_double_click_creates_roi_but_annotate_mode_does_not(
        self, waterfall_widget
    ):
        """Background double-click ROI creation should be scoped to select mode."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._plot_item.sceneBoundingRect = lambda: _AlwaysContainsRect()

        waterfall_widget._annotation_tool = "point"
        waterfall_widget._on_plot_mouse_clicked(
            _FakeMouseEvent(0.0, 500.0, double=True)
        )
        assert waterfall_widget._roi is None

        waterfall_widget._annotation_tool = "select"
        waterfall_widget._on_plot_mouse_clicked(
            _FakeMouseEvent(0.0, 500.0, double=True)
        )
        assert waterfall_widget._roi is not None

    def test_double_click_roi_creation_does_not_change_view_extents(
        self, waterfall_widget
    ):
        """Creating an ROI by double-click should not change the current zoom."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._plot_item.sceneBoundingRect = lambda: _AlwaysContainsRect()
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
            yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
            padding=0,
        )
        before = waterfall_widget._plot_item.vb.viewRange()

        waterfall_widget._on_plot_mouse_clicked(
            _FakeMouseEvent(0.0, 500.0, double=True)
        )

        after = waterfall_widget._plot_item.vb.viewRange()
        assert waterfall_widget._roi is not None
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_roi_selection_clips_dft_patch(self, waterfall_widget, monkeypatch):
        """ROI selection should clip a Fourier-domain patch on its plotted axes."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").dft("time")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        x_center = float((axes.x_plot[0] + axes.x_plot[-1]) / 2)
        y_center = float((axes.y_plot[0] + axes.y_plot[-1]) / 2)
        waterfall_widget._create_selection_roi(center_x=x_center, center_y=y_center)

        assert len(received) >= 2
        selected = received[-1]
        assert selected is not None
        assert selected.dims == patch.dims
        assert selected.shape[0] < patch.shape[0]
        assert selected.shape[1] < patch.shape[1]

    def test_colormap_change_updates_setting(self, waterfall_widget):
        """Changing combo selection updates the persisted colormap Setting."""
        if waterfall_widget._cmap_combo.count() < 2:
            pytest.skip("Need at least two colormaps for this test")

        target = waterfall_widget._cmap_combo.itemText(1)
        waterfall_widget._cmap_combo.setCurrentText(target)

        assert waterfall_widget.colormap == target

    def test_patch_refresh_does_not_reapply_colormap(
        self, waterfall_widget, monkeypatch
    ):
        """Normal patch refreshes should not reapply the histogram colormap."""
        patch = dc.get_example_patch("example_event_2")
        calls: list[str] = []

        monkeypatch.setattr(
            waterfall_widget,
            "_apply_colormap",
            lambda name: calls.append(name),
        )

        waterfall_widget.set_patch(patch)

        assert calls == []

    def test_color_limits_restore_from_stored_settings(self, qtbot):
        """Saved histogram levels should restore when the widget is recreated."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            first._hist_lut.item.setLevels(-0.25, 0.5)
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)
            assert second.color_limits == [-0.25, 0.5]
            assert second._hist_lut.item.getLevels() == pytest.approx((-0.25, 0.5))

    def test_reset_on_new_restores_from_stored_settings(self, qtbot):
        """Saved reset-on-new settings should restore when the widget is recreated."""
        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first._reset_on_new_checkbox.setChecked(True)
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)

            assert second.reset_on_new is True
            assert second._reset_on_new_checkbox.isChecked() is True

    def test_selection_restore_from_stored_settings(self, qtbot, monkeypatch):
        """Saved selection state should recreate the ROI and clipped output."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            received_first = _capture_patch_output(first, monkeypatch)
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            axes = first._axes
            first._create_selection_roi(
                center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
                center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
            )
            saved = first.settingsHandler.pack_data(first)
            original = received_first[-1]

        with widget_context(Waterfall, stored_settings=saved) as second:
            received_second = _capture_patch_output(second, monkeypatch)
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)

            assert second.saved_selection_basis == "absolute"
            assert second.saved_selection_has_roi is True
            assert second._roi is not None
            assert received_second[-1] is not None
            assert received_second[-1].shape == original.shape
            assert received_second[-1].shape[0] < patch.shape[0]
            assert received_second[-1].shape[1] < patch.shape[1]

    def test_stored_settings_persist_full_local_annotation_set(self, qtbot):
        """Workflow settings should keep the full local Waterfall annotation set."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            axes = first._axes
            first._plot_item.vb.setRange(
                xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
                yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
                padding=0,
            )
            qtbot.wait(10)
            first._create_point_annotation(
                float(axes.x_plot[150]),
                float(axes.y_plot[150]),
            )
            inside_id = first._active_annotation_id
            first._create_point_annotation(
                float(axes.x_plot[20]),
                float(axes.y_plot[20]),
            )
            saved = first.settingsHandler.pack_data(first)

        payload = saved["saved_annotation_set"]
        assert payload is not None
        assert payload["dims"] == list(first._annotation_set.dims)
        assert [item["id"] for item in payload["annotations"]] == [
            inside_id,
            first._active_annotation_id,
        ]

    def test_stored_settings_keep_annotations_outside_current_view(self, qtbot):
        """Annotations outside the current view should still persist in Waterfall."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            axes = first._axes
            first._plot_item.vb.setRange(
                xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
                yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
                padding=0,
            )
            qtbot.wait(10)
            first._create_box_annotation(
                (float(axes.x_plot[80]), float(axes.y_plot[80])),
                (float(axes.x_plot[120]), float(axes.y_plot[120])),
            )
            saved = first.settingsHandler.pack_data(first)

        payload = saved["saved_annotation_set"]
        assert payload is not None
        assert len(payload["annotations"]) == 1
        assert payload["annotations"][0]["geometry"]["type"] == "box"

    def test_full_local_annotations_restore_from_stored_settings(self, qtbot):
        """Stored Waterfall annotations should fully restore after the patch loads."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            axes = first._axes
            first._plot_item.vb.setRange(
                xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
                yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
                padding=0,
            )
            qtbot.wait(10)
            first._create_point_annotation(
                float(axes.x_plot[150]),
                float(axes.y_plot[150]),
            )
            first._create_point_annotation(
                float(axes.x_plot[20]),
                float(axes.y_plot[20]),
            )
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)

            assert second._annotation_set is not None
            assert len(second._annotation_set.annotations) == 2
            assert len(second._annotation_items) == 2
            assert second._annotation_toolbox.title_label.text() == "Annotations"

    def test_mismatched_saved_annotations_are_ignored(self, qtbot):
        """Saved Waterfall annotations should be skipped when dims do not match."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            saved = first.settingsHandler.pack_data(first)

        saved["saved_annotation_set"] = {
            "schema_version": "2",
            "dims": ["distance"],
            "annotations": [],
            "provenance": {"data_kind": "patch", "dims": ["distance"]},
        }

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)

            assert second._annotation_set is not None
            assert second._annotation_set.annotations == ()

    def test_no_roi_state_persists_explicitly_in_stored_settings(self, qtbot):
        """Saved workflows without an ROI should record that explicitly."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            saved = first.settingsHandler.pack_data(first)

        assert saved["saved_selection_has_roi"] is False

    def test_legacy_full_extent_selection_settings_restore_without_roi(self, qtbot):
        """Legacy saves without an explicit ROI flag should not recreate one."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Waterfall) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            saved = first.settingsHandler.pack_data(first)

        saved.pop("saved_selection_has_roi", None)

        numeric_dim = next(
            dim
            for dim in patch.dims
            if np.issubdtype(np.asarray(patch.get_array(dim)).dtype, np.number)
        )
        coord = np.asarray(patch.get_array(numeric_dim), dtype=np.float64)
        step = float(np.min(np.abs(np.diff(coord))))
        drift = step * 1e-10
        extent_low = float(coord[0])
        extent_high = float(coord[-1])

        for row in saved["saved_selection_ranges"]:
            if row["dim"] != numeric_dim:
                continue
            row["low"] = {"kind": "float", "value": extent_low + drift}
            row["high"] = {"kind": "float", "value": extent_high - drift}
            break

        with widget_context(Waterfall, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            second.set_patch(patch)

            assert second.saved_selection_basis == "absolute"
            assert second.saved_selection_has_roi is False
            assert second._roi is None
            assert second._current_roi_plot_bounds() is None
            assert second._selection_state.patch_kwargs() == {}

    def test_initial_color_limits_follow_dascore_default_scale(self, waterfall_widget):
        """Initial histogram levels should come from DASCore's waterfall helper."""
        patch = dc.get_example_patch("example_event_2")

        waterfall_widget.set_patch(patch)

        expected = get_dascore_waterfall_scale(None, "relative", np.asarray(patch.data))
        assert waterfall_widget._hist_lut.item.getLevels() == pytest.approx(expected)

    def test_view_all_resets_color_limits_to_dascore_default(self, waterfall_widget):
        """Colorbar View All should restore DASCore-derived default levels."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._hist_lut.item.setLevels(-0.25, 0.5)

        waterfall_widget._hist_lut.item.vb.menu.viewAll.trigger()

        expected = get_dascore_waterfall_scale(None, "relative", np.asarray(patch.data))
        assert waterfall_widget.color_limits is None
        assert waterfall_widget._hist_lut.item.getLevels() == pytest.approx(expected)

    def test_reset_on_new_resets_plot_and_colorbar_extents(self, waterfall_widget):
        """Default reset-on-new should drop prior zoom and histogram limits."""
        first_patch = dc.get_example_patch("example_event_2")
        second_patch = first_patch.update(data=np.asarray(first_patch.data) * 100.0)

        waterfall_widget.set_patch(first_patch)
        axes = waterfall_widget._axes
        narrowed_x = (
            float(axes.x_plot[10]),
            float(axes.x_plot[20]),
        )
        narrowed_y = (
            float(axes.y_plot[10]),
            float(axes.y_plot[20]),
        )
        waterfall_widget._plot_item.vb.setRange(
            xRange=narrowed_x,
            yRange=narrowed_y,
            padding=0,
        )
        waterfall_widget._hist_lut.item.setLevels(-0.25, 0.5)

        before_view = waterfall_widget._plot_item.vb.viewRange()
        waterfall_widget.set_patch(second_patch)
        after_view = waterfall_widget._plot_item.vb.viewRange()
        expected_x = waterfall_widget._axis_bounds(waterfall_widget._axes.x_plot)
        expected_y = waterfall_widget._axis_bounds(waterfall_widget._axes.y_plot)
        expected_levels = get_dascore_waterfall_scale(
            None,
            "relative",
            np.asarray(second_patch.data),
        )

        assert before_view[0] == pytest.approx(narrowed_x)
        assert before_view[1] == pytest.approx(narrowed_y)
        assert after_view[0] != pytest.approx(narrowed_x)
        assert after_view[1] != pytest.approx(narrowed_y)
        assert waterfall_widget._range_contains_range(after_view[0], expected_x)
        assert waterfall_widget._range_contains_range(after_view[1], expected_y)
        assert waterfall_widget.color_limits is None
        assert waterfall_widget._hist_lut.item.getLevels() == pytest.approx(
            expected_levels
        )

    def test_reset_on_new_false_preserves_plot_and_colorbar_extents(
        self, waterfall_widget
    ):
        """Disabling reset-on-new should preserve prior zoom and histogram limits."""
        first_patch = dc.get_example_patch("example_event_2")
        second_patch = first_patch.update(data=np.asarray(first_patch.data) * 100.0)

        waterfall_widget._reset_on_new_checkbox.setChecked(False)
        waterfall_widget.set_patch(first_patch)
        axes = waterfall_widget._axes
        narrowed_x = (
            float(axes.x_plot[10]),
            float(axes.x_plot[20]),
        )
        narrowed_y = (
            float(axes.y_plot[10]),
            float(axes.y_plot[20]),
        )
        waterfall_widget._plot_item.vb.setRange(
            xRange=narrowed_x,
            yRange=narrowed_y,
            padding=0,
        )
        waterfall_widget._hist_lut.item.setLevels(-0.25, 0.5)

        before_view = waterfall_widget._plot_item.vb.viewRange()
        waterfall_widget.set_patch(second_patch)
        after_view = waterfall_widget._plot_item.vb.viewRange()

        assert before_view[0] == pytest.approx(narrowed_x)
        assert before_view[1] == pytest.approx(narrowed_y)
        assert after_view[0] == pytest.approx(narrowed_x)
        assert after_view[1] == pytest.approx(narrowed_y)
        assert waterfall_widget.color_limits == [-0.25, 0.5]
        assert waterfall_widget._hist_lut.item.getLevels() == pytest.approx(
            (-0.25, 0.5)
        )

    def test_unknown_colormap_falls_back(self, waterfall_widget):
        """An unrecognised colormap name falls back to viridis."""
        waterfall_widget._apply_colormap("not_a_real_colormap")

        assert waterfall_widget.colormap == "viridis"
        assert waterfall_widget._cmap_combo.currentText() == "viridis"

    def test_cursor_readout_shows_nearest_sample_value(self, waterfall_widget):
        """Cursor readout reports the nearest plotted coordinate and sample value."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        x_index = len(axes.x_plot) // 3
        y_index = len(axes.y_plot) // 4

        waterfall_widget._update_cursor_readout(
            plot_x=float(axes.x_plot[x_index]),
            plot_y=float(axes.y_plot[y_index]),
        )

        text = waterfall_widget._cursor_label.text()
        assert axes.x_dim in text
        assert axes.y_dim in text
        assert "value=" in text

    def test_cursor_readout_shows_absolute_datetime_values(self, waterfall_widget):
        """Cursor readout should preserve absolute datetime text for datetime axes."""
        patch = _with_datetime_coord(dc.get_example_patch("example_event_2"), "time")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        x_index = len(axes.x_plot) // 3
        y_index = len(axes.y_plot) // 4

        waterfall_widget._update_cursor_readout(
            plot_x=float(axes.x_plot[x_index]),
            plot_y=float(axes.y_plot[y_index]),
        )

        assert "2024-01-02T" in waterfall_widget._cursor_label.text()

    def test_datetime_axis_tick_matches_patch_datetime(self, waterfall_widget):
        """Datetime axis ticks should not shift naive patch times by local offset."""
        patch = dc.get_example_patch("example_event_2")
        count = len(patch.get_array("time"))
        values = np.datetime64("2024-07-15T11:50:00") + np.arange(count).astype(
            "timedelta64[s]"
        )
        patch = patch.update_coords(time=values)
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        axis = waterfall_widget._plot_item.getAxis("bottom")

        axis.utcOffset = -(2 * 3600)
        axis._ensure_font_metrics()
        axis.setZoomLevelForDensity(60)
        spacing = axis.zoomLevel.tickSpecs[-1].spacing
        axis_text = axis.tickStrings([float(axes.x_plot[0])], 1, spacing)[0]

        assert axis_text == "11:50"

    def test_cursor_readout_clears_without_patch(self, waterfall_widget):
        """Cursor readout resets when there is no patch to inspect."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))

        waterfall_widget.set_patch(None)

        assert waterfall_widget._cursor_label.text() == "Cursor: --"

    def test_new_input_preserves_roi(self, waterfall_widget):
        """Setting a new patch preserves any prior ROI-backed selection."""
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(first)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        before_time = waterfall_widget._selection_current_patch_range("time")
        assert waterfall_widget._roi is not None

        waterfall_widget.set_patch(second)

        assert waterfall_widget._roi is not None
        assert waterfall_widget._selection_current_patch_range("time") == pytest.approx(
            before_time
        )
        assert waterfall_widget._selection_current_patch_range(
            "time"
        ) != waterfall_widget._selection_patch_extent("time")

    def test_new_input_without_roi_has_no_roi_and_frames_new_patch(
        self, waterfall_widget
    ):
        """Replacing a patch with no ROI should zoom to the new patch only."""
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("ricker_moveout")

        waterfall_widget.set_patch(first)
        waterfall_widget.set_patch(second)

        assert waterfall_widget._roi is None
        view_range = waterfall_widget._plot_item.vb.viewRange()
        assert waterfall_widget._range_contains_axis_values(
            tuple(view_range[0]), waterfall_widget._axes.x_plot
        )
        assert waterfall_widget._range_contains_axis_values(
            tuple(view_range[1]), waterfall_widget._axes.y_plot
        )

    def test_new_input_preserves_roi_exact_plot_bounds(self, waterfall_widget):
        """An active ROI should survive patch replacement at the same plot bounds."""
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_2")

        waterfall_widget.set_patch(first)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        before_bounds = waterfall_widget._current_roi_plot_bounds()
        assert before_bounds is not None

        waterfall_widget.set_patch(second)

        assert waterfall_widget._roi is not None
        after_bounds = waterfall_widget._current_roi_plot_bounds()
        assert after_bounds is not None
        assert after_bounds[0] == pytest.approx(before_bounds[0])
        assert after_bounds[1] == pytest.approx(before_bounds[1])

    def test_cleared_roi_stays_gone_on_new_input_and_frames_new_patch(
        self, waterfall_widget
    ):
        """Clearing an ROI should remove all memory of it on later patch replacement."""
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("ricker_moveout")

        waterfall_widget.set_patch(first)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget._selection_panel.reset_button.click()
        assert waterfall_widget._roi is None

        waterfall_widget.set_patch(second)

        assert waterfall_widget._roi is None
        view_range = waterfall_widget._plot_item.vb.viewRange()
        assert waterfall_widget._range_contains_axis_values(
            tuple(view_range[0]), waterfall_widget._axes.x_plot
        )
        assert waterfall_widget._range_contains_axis_values(
            tuple(view_range[1]), waterfall_widget._axes.y_plot
        )

    def test_add_selection_button_places_roi_immediately(self, waterfall_widget):
        """The left-side select icon should place a default ROI immediately."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes

        waterfall_widget._add_selection_button.click()

        assert waterfall_widget._add_selection_button.toolTip() == (
            "Place a selection ROI in the current view"
        )
        assert waterfall_widget._add_selection_button.icon().isNull() is False
        assert waterfall_widget._roi is not None
        roi = waterfall_widget._roi
        center_x = float(roi.pos().x() + (roi.size().x() / 2))
        center_y = float(roi.pos().y() + (roi.size().y() / 2))
        expected_x = float((axes.x_plot[0] + axes.x_plot[-1]) / 2)
        expected_y = float((axes.y_plot[0] + axes.y_plot[-1]) / 2)
        assert center_x == pytest.approx(expected_x)
        assert center_y == pytest.approx(expected_y)

    def test_placing_selection_roi_does_not_show_annotation_toolbox(
        self, waterfall_widget
    ):
        """Creating a selection ROI should not reveal the annotation toolbox."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes

        assert waterfall_widget._annotation_toolbox.isVisible() is False

        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        assert waterfall_widget._roi is not None
        assert waterfall_widget._annotation_toolbox.isVisible() is False

        waterfall_widget._add_selection_button.click()

        assert waterfall_widget._roi is not None
        assert waterfall_widget._annotation_toolbox.isVisible() is False

    def test_selection_buttons_share_one_row_with_select_closer_to_plot(
        self, waterfall_widget
    ):
        """Reset/select controls should share one row with select nearest the plot."""
        row_layout = waterfall_widget._selection_button_row.layout()

        assert waterfall_widget._selection_panel.reset_button.text() == "Reset"
        assert row_layout.indexOf(waterfall_widget._selection_panel.reset_button) == 0
        assert row_layout.indexOf(waterfall_widget._add_selection_button) == 1

    def test_add_selection_button_uses_visible_view_center(
        self, waterfall_widget, monkeypatch
    ):
        """The left-side select icon should center the ROI in the visible window."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        x_range = (float(axes.x_plot[10]), float(axes.x_plot[30]))
        y_range = (float(axes.y_plot[20]), float(axes.y_plot[60]))
        monkeypatch.setattr(
            waterfall_widget,
            "_get_view_range",
            lambda: (x_range, y_range),
        )

        waterfall_widget._add_selection_button.click()

        assert waterfall_widget._roi is not None
        roi = waterfall_widget._roi
        center_x = float(roi.pos().x() + (roi.size().x() / 2))
        center_y = float(roi.pos().y() + (roi.size().y() / 2))
        assert center_x == pytest.approx(sum(x_range) / 2)
        assert center_y == pytest.approx(sum(y_range) / 2)

    def test_reset_selection_button_clears_existing_roi(self, waterfall_widget):
        """Reset Selection should delete the active ROI and restore full output."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        waterfall_widget._create_selection_roi(center_x=0.0, center_y=500.0)
        assert waterfall_widget._roi is not None

        waterfall_widget._selection_panel.reset_button.click()

        assert waterfall_widget._roi is None

    def test_plot_reset_window_clears_existing_roi(self, waterfall_widget):
        """The plot view reset action should also clear the active ROI."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        waterfall_widget._create_selection_roi(center_x=0.0, center_y=500.0)
        assert waterfall_widget._roi is not None

        waterfall_widget._plot_item.vb.menu.viewAll.trigger()

        assert waterfall_widget._roi is None

    def test_new_input_preserves_view_range(self, waterfall_widget):
        """Replacing the patch keeps zoom when the visible window still has data."""
        first = _with_datetime_coord(dc.get_example_patch("example_event_2"), "time")
        second = _with_datetime_coord(dc.get_example_patch("example_event_1"), "time")
        waterfall_widget.set_patch(first)
        axes = waterfall_widget._axes
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[20]), float(axes.x_plot[80])),
            yRange=(500.0, 700.0),
            padding=0,
        )
        before = waterfall_widget._plot_item.vb.viewRange()

        waterfall_widget.set_patch(second)

        after = waterfall_widget._plot_item.vb.viewRange()
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_failed_refresh_clears_pending_view_range(
        self, waterfall_widget, monkeypatch
    ):
        """Render failures should not leak a stale pending view range forward."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._pending_view_range = ((1.0, 2.0), (3.0, 4.0))

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(waterfall_widget, "_render_patch", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            waterfall_widget._refresh_ui()

        assert waterfall_widget._pending_view_range is None

    def test_new_input_rezooms_when_current_view_has_no_data(self, waterfall_widget):
        """Replacing the patch should re-autorange when the view misses new data."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        waterfall_widget._plot_item.vb.setRange(
            xRange=(1_000.0, 2_000.0),
            yRange=(1_000.0, 2_000.0),
            padding=0,
        )
        before = waterfall_widget._plot_item.vb.viewRange()

        waterfall_widget.set_patch(dc.get_example_patch("example_event_1"))

        after = waterfall_widget._plot_item.vb.viewRange()
        assert not np.allclose(after[0], before[0])
        assert not np.allclose(after[1], before[1])
        x_bounds = waterfall_widget._axis_bounds(waterfall_widget._axes.x_plot)
        y_bounds = waterfall_widget._axis_bounds(waterfall_widget._axes.y_plot)
        assert waterfall_widget._ranges_overlap(after[0], x_bounds)
        assert waterfall_widget._ranges_overlap(after[1], y_bounds)

    def test_ricker_moveout_rezooms_after_zoomed_event_view(self, waterfall_widget):
        """A zoomed event view should reset when ricker data is outside it."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        waterfall_widget._plot_item.vb.setRange(
            xRange=(0.002, 0.008),
            yRange=(500.0, 700.0),
            padding=0,
        )
        before = waterfall_widget._plot_item.vb.viewRange()

        waterfall_widget.set_patch(dc.get_example_patch("ricker_moveout"))

        after = waterfall_widget._plot_item.vb.viewRange()
        assert not np.allclose(after[0], before[0])
        assert not np.allclose(after[1], before[1])
        assert waterfall_widget._axes.x_dim == "distance"
        assert waterfall_widget._axes.y_dim == "time"
        assert waterfall_widget._range_contains_axis_values(
            after[0], waterfall_widget._axes.x_plot
        )
        assert waterfall_widget._range_contains_axis_values(
            after[1], waterfall_widget._axes.y_plot
        )

    def test_left_panel_range_edit_syncs_roi(self, waterfall_widget, monkeypatch):
        """Editing plotted-dimension bounds in the left panel creates a synced ROI."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        x_dim = waterfall_widget._axes.x_dim
        midpoint = patch.get_array(x_dim)[len(patch.get_array(x_dim)) // 2]
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[x_dim]

        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()

        assert waterfall_widget._roi is not None
        assert received
        assert received[-1] is not None
        assert received[-1].shape[1] < patch.shape[1]

    def test_reset_button_clears_roi(self, waterfall_widget):
        """Resetting the shared selection removes the plotted ROI."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget._selection_panel.reset_button.click()

        assert waterfall_widget._roi is None

    def test_disabling_plotted_dimension_keeps_full_span_roi_and_filter(
        self, waterfall_widget, monkeypatch
    ):
        """Unchecking one plotted dimension keeps a full-span ROI stripe."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        x_dim = waterfall_widget._axes.x_dim
        midpoint = patch.get_array(x_dim)[len(patch.get_array(x_dim)) // 2]
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[x_dim]
        checkbox = waterfall_widget._selection_patch_checkboxes[x_dim]
        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()
        assert waterfall_widget._roi is not None
        assert received[-1].shape[1] < patch.shape[1]

        checkbox.click()

        assert waterfall_widget._roi is not None
        pos = waterfall_widget._roi.pos()
        size = waterfall_widget._roi.size()
        x_low = float(pos.x())
        x_high = x_low + float(size.x())
        expected_low, expected_high = waterfall_widget._axis_bounds(
            waterfall_widget._axes.x_plot
        )
        assert x_low == pytest.approx(expected_low)
        assert x_high == pytest.approx(expected_high)
        assert received[-1] is patch

    @pytest.mark.parametrize("dim_attr", ["x_dim", "y_dim"])
    def test_disabling_plotted_dimension_preserves_zoom(
        self, waterfall_widget, dim_attr
    ):
        """Turning off one plotted dimension should not reset the current zoom."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._plot_item.vb.setRange(
            xRange=(float(axes.x_plot[100]), float(axes.x_plot[200])),
            yRange=(float(axes.y_plot[100]), float(axes.y_plot[200])),
            padding=0,
        )
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[120] + axes.x_plot[180]) / 2),
            center_y=float((axes.y_plot[120] + axes.y_plot[180]) / 2),
        )
        before_view = waterfall_widget._plot_item.vb.viewRange()
        dim = getattr(axes, dim_attr)

        waterfall_widget._selection_patch_checkboxes[dim].click()

        after_view = waterfall_widget._plot_item.vb.viewRange()
        assert np.allclose(after_view[0], before_view[0])
        assert np.allclose(after_view[1], before_view[1])

    def test_reset_reenables_plotted_dimensions(self, waterfall_widget):
        """Reset should re-enable plotted-dimension checkboxes."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        x_dim = waterfall_widget._axes.x_dim
        waterfall_widget._selection_patch_checkboxes[x_dim].click()
        waterfall_widget._selection_panel.reset_button.click()

        assert waterfall_widget._selection_patch_enabled[x_dim] is True
        assert waterfall_widget._selection_patch_checkboxes[x_dim].isChecked() is True

    def test_patch_basis_selector_is_available(self, waterfall_widget):
        """Waterfall exposes the shared patch basis selector in its left panel."""
        patch = dc.get_example_patch("example_event_2")

        waterfall_widget.set_patch(patch)

        combo = waterfall_widget._selection_panel.patch_basis_combo
        assert not combo.isHidden()
        assert combo.count() == len(PatchSelectionBasis)

    def test_relative_mode_roi_updates_relative_ranges(
        self, waterfall_widget, monkeypatch
    ):
        """ROI edits should be written back as relative offsets in relative mode."""
        _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").update_coords(
            time=dc.get_example_patch("example_event_2").get_array("time") + 10,
            distance=dc.get_example_patch("example_event_2").get_array("distance")
            + 100,
        )
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")

        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        absolute = waterfall_widget._selection_current_patch_absolute_range(axes.x_dim)
        relative = waterfall_widget._selection_current_patch_range(axes.x_dim)
        start = np.asarray(patch.get_array(axes.x_dim)[0])
        # relative values are float seconds from the first coordinate
        for rel_val, abs_val in zip(relative, absolute):
            abs_arr = np.asarray(abs_val)
            if np.issubdtype(abs_arr.dtype, np.datetime64):
                start_ns = start.astype("datetime64[ns]").astype(np.int64)
                abs_ns = abs_arr.astype("datetime64[ns]").astype(np.int64)
                expected_s = float(abs_ns - start_ns) / 1e9
            else:
                expected_s = float(abs_arr - start)
            assert rel_val == pytest.approx(expected_s)

    def test_relative_mode_roi_clips_negative_values(
        self, waterfall_widget, monkeypatch
    ):
        """ROI-driven relative selections should never store negative offsets."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")

        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float(axes.x_plot[0] - 1.0),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        relative = waterfall_widget._selection_current_patch_range(axes.x_dim)
        assert relative[0] >= 0
        assert relative[1] >= 0
        assert received[-1] is not None
        assert received[-1].shape[1] <= patch.shape[1]

    def test_samples_mode_roi_updates_sample_ranges(
        self, waterfall_widget, monkeypatch
    ):
        """ROI edits should be written back as sample indices in sample mode."""
        _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").update_coords(
            time=dc.get_example_patch("example_event_2").get_array("time") + 10
        )
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")

        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        sample_range = waterfall_widget._selection_current_patch_range(axes.x_dim)
        assert all(isinstance(value, int) for value in sample_range)
        assert sample_range[0] >= 0

    def test_samples_mode_roi_clips_negative_values(
        self, waterfall_widget, monkeypatch
    ):
        """ROI-driven sample selections should never store negative indices."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")

        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float(axes.x_plot[0] - 1.0),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )

        sample_range = waterfall_widget._selection_current_patch_range(axes.x_dim)
        assert all(isinstance(value, int) for value in sample_range)
        assert sample_range[0] >= 0
        assert sample_range[1] >= 0
        assert received[-1] is not None
        assert received[-1].shape[1] <= patch.shape[1]

    def test_samples_mode_roi_snaps_to_valid_indices_and_emits_selection(
        self, waterfall_widget, monkeypatch
    ):
        """ROI-driven sample selection should snap to ints and not error."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").update_coords(
            time=dc.get_example_patch("example_event_2").get_array("time") + 10
        )
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")

        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2) + 0.000037,
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2) + 0.31,
        )

        sample_range = waterfall_widget._selection_current_patch_range(axes.x_dim)
        assert all(isinstance(value, int) for value in sample_range)
        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].shape[1] < patch.shape[1]

    def test_relative_selection_survives_patch_replacement(
        self, waterfall_widget, monkeypatch
    ):
        """Relative left-panel selections should be reapplied to replacement patches."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(
            time=patch.get_array("time") + 10,
            distance=patch.get_array("distance") + 100,
        )
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")
        _low_edit, high_edit = waterfall_widget._selection_patch_edits["time"]
        high_edit.setText("0.01")
        high_edit.editingFinished.emit()

        waterfall_widget.set_patch(shifted)

        assert waterfall_widget._selection_patch_basis == "relative"
        expected = shifted.select(relative=True, time=(0.0, 0.01))
        assert received[-1].shape == expected.shape

    def test_absolute_selection_survives_none_then_compatible_patch(
        self, waterfall_widget, monkeypatch
    ):
        """A None input should not clear an absolute selection that still applies."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(first)
        time_values = first.get_array("time")
        selected = (float(time_values[100]), float(time_values[200]))
        _set_absolute_selection_range(waterfall_widget, "time", *selected)

        waterfall_widget.set_patch(None)
        waterfall_widget.set_patch(second)

        assert received[-2] is None
        assert waterfall_widget._selection_patch_basis == "absolute"
        assert waterfall_widget._selection_current_patch_range("time") == pytest.approx(
            selected
        )
        assert received[-1].shape == second.select(time=selected).shape

    def test_absolute_selection_preserved_after_none_when_new_patch_is_out_of_range(
        self, waterfall_widget, monkeypatch
    ):
        """Preserve an absolute selection even when a new patch cannot satisfy it."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        shifted = first.update_coords(
            time=first.get_array("time") + 10,
            distance=first.get_array("distance") + 100,
        )
        waterfall_widget.set_patch(first)
        time_values = first.get_array("time")
        selected = (float(time_values[100]), float(time_values[200]))
        _set_absolute_selection_range(waterfall_widget, "time", *selected)

        waterfall_widget.set_patch(None)
        waterfall_widget.set_patch(shifted)

        assert received[-2] is None
        assert waterfall_widget._selection_current_patch_range("time") == pytest.approx(
            selected
        )
        assert waterfall_widget._roi is not None
        assert received[-1] is not None
        assert 0 in received[-1].shape
        assert waterfall_widget.Warning.empty_selection.is_shown()

    def test_manual_negative_relative_entry_is_preserved(
        self, waterfall_widget, monkeypatch
    ):
        """Manual relative edits may stay negative while ROI values are clipped."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")

        _low_edit, high_edit = waterfall_widget._selection_patch_edits[
            waterfall_widget._axes.x_dim
        ]
        high_edit.setText("-0.01")
        high_edit.editingFinished.emit()

        relative = waterfall_widget._selection_current_patch_range(
            waterfall_widget._axes.x_dim
        )
        assert relative[0] <= 0
        assert relative[1] <= 0
        assert received[-1] is not None

    def test_delete_key_clears_focused_roi(self, waterfall_widget, monkeypatch):
        """Delete removes the ROI when it has focus and restores full output."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        received.clear()
        waterfall_widget._roi.setFocus()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        waterfall_widget._roi.keyPressEvent(event)

        assert waterfall_widget._roi is None
        assert received == [patch]

    def test_delete_key_from_widget_clears_active_roi(self, waterfall_widget, qtbot):
        """Pressing Delete in the live widget should remove the focused ROI."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget._roi.setSelected(True)
        waterfall_widget._roi.setFocus()
        waterfall_widget._plot_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_delete_key_from_widget_clears_selected_roi(self, waterfall_widget, qtbot):
        """Pressing Delete removes the selected ROI even without focus transfer."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget._roi.setSelected(True)
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_delete_key_from_widget_clears_clicked_selected_roi(
        self, waterfall_widget, qtbot
    ):
        """Click-selecting the ROI in select mode should let Delete remove it."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None

        roi_center = QPointF(
            float(roi.pos().x()) + (float(roi.size().x()) / 2),
            float(roi.pos().y()) + (float(roi.size().y()) / 2),
        )
        center_scene = waterfall_widget._plot_item.vb.mapViewToScene(roi_center)
        center_viewport = waterfall_widget._plot_widget.mapFromScene(center_scene)

        QTest.mouseClick(
            waterfall_widget._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            center_viewport,
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        assert roi.isSelected()

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_delete_key_from_widget_clears_clicked_selected_roi_and_restores_output(
        self, waterfall_widget, monkeypatch, qtbot
    ):
        """Deleting a clicked ROI should remove it and re-emit the full patch."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        received.clear()
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None

        roi_center = QPointF(
            float(roi.pos().x()) + (float(roi.size().x()) / 2),
            float(roi.pos().y()) + (float(roi.size().y()) / 2),
        )
        center_scene = waterfall_widget._plot_item.vb.mapViewToScene(roi_center)
        center_viewport = waterfall_widget._plot_widget.mapFromScene(center_scene)

        QTest.mouseClick(
            waterfall_widget._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            center_viewport,
        )
        waterfall_widget.setFocus()
        qtbot.wait(10)

        assert roi.isSelected()

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None
        assert received[-1] is patch

    def test_delete_key_from_viewport_clears_clicked_selected_roi(
        self, waterfall_widget, qtbot
    ):
        """Delete from the plot viewport should also remove a clicked selected ROI."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None

        roi_center = QPointF(
            float(roi.pos().x()) + (float(roi.size().x()) / 2),
            float(roi.pos().y()) + (float(roi.size().y()) / 2),
        )
        center_scene = waterfall_widget._plot_item.vb.mapViewToScene(roi_center)
        center_viewport = waterfall_widget._plot_widget.mapFromScene(center_scene)

        QTest.mouseClick(
            waterfall_widget._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            center_viewport,
        )
        waterfall_widget._plot_widget.viewport().setFocus()
        qtbot.wait(10)

        assert roi.isSelected()

        QTest.keyClick(waterfall_widget._plot_widget.viewport(), Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_delete_key_from_widget_clears_handle_focused_roi(
        self, waterfall_widget, qtbot
    ):
        """Delete should remove the ROI even when one resize handle has focus."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None

        handle = roi.getHandles()[0]
        roi.setSelected(True)
        scene = waterfall_widget._plot_widget.scene()
        scene.setFocusItem(handle)
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_delete_key_from_widget_clears_unfocused_visible_roi(
        self, waterfall_widget, qtbot
    ):
        """Delete should remove the active selection ROI without extra focus steps."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_viewport_delete_shortcut_clears_visible_roi(self, waterfall_widget, qtbot):
        """Delete from the focused plot viewport should remove the active ROI."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        waterfall_widget._plot_widget.viewport().setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget._plot_widget.viewport(), Qt.Key_Delete)

        assert waterfall_widget._roi is None

    def test_backspace_clears_focused_roi(self, waterfall_widget, monkeypatch):
        """Backspace removes the ROI when it has focus and restores full output."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        assert waterfall_widget._roi is not None

        received.clear()
        waterfall_widget._roi.setFocus()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Backspace, Qt.NoModifier)
        waterfall_widget._roi.keyPressEvent(event)

        assert waterfall_widget._roi is None
        assert received == [patch]

    def test_escape_keeps_window_open_and_clears_selected_interaction_mode(
        self, waterfall_widget, qtbot
    ):
        """Escape should leave the window open and clear the active
        select-mode state.
        """
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None
        roi.setSelected(True)
        roi.setFocus()
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert waterfall_widget.isVisible()
        assert waterfall_widget._annotation_tool is None
        assert waterfall_widget._overlay_mode == "select"
        assert waterfall_widget._roi is roi
        assert roi.acceptedMouseButtons() == Qt.MouseButton.NoButton
        assert not roi.isSelected()
        assert waterfall_widget._add_selection_button.isChecked() is True

    def test_escape_from_plot_viewport_clears_selected_interaction_mode(
        self, waterfall_widget, qtbot
    ):
        """Escape from the focused plot viewport should clear active selection."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._annotation_tool = "select"
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        roi = waterfall_widget._roi
        assert roi is not None
        roi.setSelected(True)
        waterfall_widget._plot_widget.viewport().setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget._plot_widget.viewport(), Qt.Key_Escape)
        qtbot.wait(10)

        assert waterfall_widget.isVisible()
        assert waterfall_widget._annotation_tool is None
        assert waterfall_widget._overlay_mode == "select"
        assert waterfall_widget._roi is roi
        assert not roi.isSelected()
        assert waterfall_widget.hasFocus()

    def test_escape_from_point_tool_restores_annotation_select_mode(
        self, waterfall_widget, qtbot
    ):
        """Escape should leave point placement and restore annotation selection."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._annotation_tool = "point"
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert waterfall_widget.isVisible()
        assert waterfall_widget._annotation_tool == "annotation_select"
        assert waterfall_widget._overlay_mode == "annotate"
        assert waterfall_widget._annotation_toolbox.tool_buttons[
            "annotation_select"
        ].isChecked()

    def test_escape_clears_selected_square_annotation(self, waterfall_widget, qtbot):
        """Escape should deselect a highlighted square annotation."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        controller = waterfall_widget._annotation_controller
        waterfall_widget._toggle_annotation_toolbox(True)

        controller.create_point_annotation(120.0, 120.0)
        first_id = controller.active_annotation_id
        controller.create_point_annotation(160.0, 150.0)
        second_id = controller.active_annotation_id
        controller.set_selected_annotations({first_id, second_id})

        assert controller.fit_square_from_selection() is True

        square_id = controller.active_annotation_id
        controller.set_selected_annotations({square_id})
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert controller.selected_annotation_ids == set()
        assert controller.active_annotation_id is None

    def test_escape_clears_selected_ellipse_annotation(self, waterfall_widget, qtbot):
        """Escape should deselect a highlighted ellipse annotation."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        controller = waterfall_widget._annotation_controller
        waterfall_widget._toggle_annotation_toolbox(True)

        controller.create_ellipse_annotation((120.0, 120.0), (170.0, 155.0))
        ellipse_id = controller.active_annotation_id
        controller.set_selected_annotations({ellipse_id})
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert controller.selected_annotation_ids == set()
        assert controller.active_annotation_id is None

    def test_escape_does_not_show_hidden_annotation_toolbox(
        self, waterfall_widget, qtbot
    ):
        """Escape should not force the annotation toolbox visible when hidden."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._hide_annotation_toolbox()
        waterfall_widget.setFocus()
        qtbot.wait(10)

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)

        assert waterfall_widget._annotation_tool is None
        assert waterfall_widget._overlay_mode == "select"
        assert waterfall_widget._annotation_toolbox.isVisible() is False
        assert waterfall_widget._annotation_toolbox_hidden is True

    def test_escape_restores_annotation_select_until_roi_is_clicked(
        self, waterfall_widget, qtbot
    ):
        """Escape should restore arrow-mode annotation selection while visible."""
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        axes = waterfall_widget._axes
        waterfall_widget._toggle_annotation_toolbox(True)

        waterfall_widget._add_selection_button.click()
        waterfall_widget._annotation_tool = "point"
        waterfall_widget._create_point_annotation(
            float(axes.x_plot[140]),
            float(axes.y_plot[140]),
        )
        waterfall_widget._annotation_tool = "annotation_select"
        annotation_id = waterfall_widget._active_annotation_id
        annotation_item = waterfall_widget._annotation_items[annotation_id]
        roi = waterfall_widget._roi

        assert roi is not None
        assert waterfall_widget._annotation_toolbox.tool_buttons[
            "annotation_select"
        ].isChecked()

        waterfall_widget.setFocus()
        qtbot.wait(10)
        QTest.keyClick(waterfall_widget, Qt.Key_Escape)
        qtbot.wait(10)

        assert waterfall_widget._annotation_tool == "annotation_select"
        assert waterfall_widget._annotation_toolbox.tool_buttons[
            "annotation_select"
        ].isChecked()
        assert waterfall_widget._add_selection_button.isChecked() is False

        waterfall_widget._on_plot_mouse_clicked(
            _FakeMouseEvent(
                annotation_item.sceneBoundingRect().center().x(),
                annotation_item.sceneBoundingRect().center().y(),
                double=False,
            )
        )
        qtbot.wait(10)

        assert waterfall_widget._annotation_tool == "annotation_select"
        assert waterfall_widget._annotation_toolbox.tool_buttons[
            "annotation_select"
        ].isChecked()

        QTest.keyClick(waterfall_widget, Qt.Key_Escape)
        qtbot.wait(10)
        waterfall_widget._toggle_annotation_toolbox(False)
        waterfall_widget._on_plot_mouse_clicked(
            _FakeMouseEvent(
                roi.sceneBoundingRect().center().x(),
                roi.sceneBoundingRect().center().y(),
                double=False,
            )
        )
        qtbot.wait(10)

        assert waterfall_widget._add_selection_button.isChecked() is True
        assert waterfall_widget._overlay_mode == "select"

    def test_empty_selection_keeps_roi_and_warns(self, waterfall_widget, monkeypatch):
        """Non-overlapping ROI emits an empty patch, keeps the ROI, and warns."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        x_center = float((axes.x_plot[0] + axes.x_plot[-1]) / 2)
        y_center = float((axes.y_plot[0] + axes.y_plot[-1]) / 2)
        waterfall_widget._create_selection_roi(center_x=x_center, center_y=y_center)
        assert waterfall_widget._roi is not None

        waterfall_widget._roi.setPos(1e9, 1e9)
        waterfall_widget._emit_current_selection()

        assert waterfall_widget._roi is not None
        assert received[-1] is not None
        assert 0 in received[-1].shape
        assert waterfall_widget.Warning.empty_selection.is_shown()

    def test_empty_selection_warning_clears_when_overlap_returns(
        self, waterfall_widget, monkeypatch
    ):
        """The empty-selection warning clears once the ROI overlaps data again."""
        _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        x_center = float((axes.x_plot[0] + axes.x_plot[-1]) / 2)
        y_center = float((axes.y_plot[0] + axes.y_plot[-1]) / 2)
        waterfall_widget._create_selection_roi(center_x=x_center, center_y=y_center)
        waterfall_widget._roi.setPos(1e9, 1e9)
        waterfall_widget._emit_current_selection()

        assert waterfall_widget.Warning.empty_selection.is_shown()

        waterfall_widget._roi.setPos(x_center, y_center)
        waterfall_widget._emit_current_selection()

        assert not waterfall_widget.Warning.empty_selection.is_shown()

    def test_non_overlapping_selection_default_view_contains_patch_and_roi(
        self, waterfall_widget
    ):
        """New patch view should frame the patch and preserved ROI together."""
        first = dc.get_example_patch("example_event_2")
        shifted = first.update_coords(
            time=first.get_array("time") + 10,
            distance=first.get_array("distance") + 100,
        )
        waterfall_widget.set_patch(first)
        time_values = first.get_array("time")
        distance_values = first.get_array("distance")
        _set_absolute_selection_range(
            waterfall_widget,
            "time",
            float(time_values[100]),
            float(time_values[200]),
        )
        _set_absolute_selection_range(
            waterfall_widget,
            "distance",
            float(distance_values[100]),
            float(distance_values[200]),
        )

        waterfall_widget.set_patch(shifted)

        view_range = waterfall_widget._plot_item.vb.viewRange()
        roi = waterfall_widget._roi
        pos = roi.pos()
        size = roi.size()
        roi_x = tuple(sorted((float(pos.x()), float(pos.x() + size.x()))))
        roi_y = tuple(sorted((float(pos.y()), float(pos.y() + size.y()))))
        patch_x = waterfall_widget._axis_bounds(waterfall_widget._axes.x_plot)
        patch_y = waterfall_widget._axis_bounds(waterfall_widget._axes.y_plot)

        assert waterfall_widget._range_contains_range(tuple(view_range[0]), patch_x)
        assert waterfall_widget._range_contains_range(tuple(view_range[1]), patch_y)
        assert waterfall_widget._range_contains_range(tuple(view_range[0]), roi_x)
        assert waterfall_widget._range_contains_range(tuple(view_range[1]), roi_y)

    def test_invalid_render_keeps_pass_through_output(
        self, waterfall_widget, monkeypatch
    ):
        """Render errors still pass through non-None input object on output."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        fake_patch = _FakePatch3D()

        waterfall_widget.set_patch(fake_patch)

        assert received == [fake_patch]
        assert waterfall_widget.Error.invalid_patch.is_shown()

    def test_render_failure_clears_axes(self, waterfall_widget):
        """Axis state is cleared when render fails."""
        waterfall_widget.set_patch(dc.get_example_patch("example_event_2"))
        assert waterfall_widget._axes is not None

        waterfall_widget.set_patch(_FakePatch3D())

        assert waterfall_widget._axes is None


class TestWaterfallFilters:
    """Tests that various selection filter parameters produce correct output."""

    def test_absolute_time_filter_reduces_size(self, waterfall_widget, monkeypatch):
        """Absolute time upper bound clips time axis in output patch."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        time_coords = np.asarray(patch.get_array(axes.x_dim))
        # Select only the first quarter of the time axis.
        quarter = time_coords[len(time_coords) // 4]
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[axes.x_dim]
        high_edit.setText(str(quarter))
        high_edit.editingFinished.emit()

        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].shape[1] < patch.shape[1]

    def test_absolute_distance_filter_reduces_size(self, waterfall_widget, monkeypatch):
        """Absolute distance upper bound clips distance axis in output patch."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        dist_coords = np.asarray(patch.get_array(axes.y_dim))
        midpoint = float((dist_coords[0] + dist_coords[-1]) / 2)
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[axes.y_dim]
        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()

        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].shape[0] < patch.shape[0]

    def test_absolute_fourier_axis_filter_reduces_size(
        self, waterfall_widget, monkeypatch
    ):
        """Absolute filtering should clip a plotted Fourier axis like any other dim."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2").dft("time")
        waterfall_widget.set_patch(patch)

        axes = waterfall_widget._axes
        ft_coords = np.asarray(patch.get_array(axes.x_dim))
        midpoint = float((ft_coords[0] + ft_coords[-1]) / 2)
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[axes.x_dim]
        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()

        assert axes.x_dim == "ft_time"
        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].dims == patch.dims
        assert received[-1].shape[1] < patch.shape[1]

    def test_relative_time_filter_no_error(self, waterfall_widget, monkeypatch):
        """Relative time filter works without ufunc subtract errors."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")

        _low_edit, high_edit = waterfall_widget._selection_patch_edits[
            waterfall_widget._axes.x_dim
        ]
        high_edit.setText("0.01")
        high_edit.editingFinished.emit()

        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        expected = patch.select(relative=True, time=(0.0, 0.01))
        assert received[-1].shape == expected.shape

    def test_samples_filter_reduces_size(self, waterfall_widget, monkeypatch):
        """Sample-index filter selects the correct number of samples."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget.set_patch(patch)
        waterfall_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")

        axes = waterfall_widget._axes
        _low_edit, high_edit = waterfall_widget._selection_patch_edits[axes.x_dim]
        high_edit.setText("5")
        high_edit.editingFinished.emit()

        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].shape[1] <= 6

    def test_initial_selection_is_empty(self, waterfall_widget, monkeypatch):
        """Selection starts empty (full pass-through) when patch is first loaded."""
        received = _capture_patch_output(waterfall_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        waterfall_widget.set_patch(patch)

        # No error, output shape matches input exactly (nothing filtered).
        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert received[-1] is not None
        assert received[-1].shape == patch.shape
        # All range edit boxes should be empty (no active filter text).
        for _low_edit, high_edit in waterfall_widget._selection_patch_edits.values():
            assert _low_edit.text() == ""
            assert high_edit.text() == ""


def _shift_waterfall_patch_out_of_range(patch: dc.Patch) -> dc.Patch:
    """Return a patch whose absolute coords no longer overlap the source patch."""
    return patch.update_coords(
        time=patch.get_array("time") + 10,
        distance=patch.get_array("distance") + 100,
    )


class TestWaterfallDefaults(TestPatchInputStateDefaults):
    """Shared default/smoke tests for Waterfall."""

    __test__ = True
    widget = Waterfall
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
    compatible_patch = dc.get_example_patch("example_event_2")
    incompatible_patch = _shift_waterfall_patch_out_of_range(
        dc.get_example_patch("example_event_2")
    )

    def arrange_persisted_input_state(self, widget_object):
        """Install one absolute time selection range to preserve."""
        patch = widget_object._patch
        assert patch is not None
        time_values = patch.get_array("time")
        selected = (float(time_values[100]), float(time_values[200]))
        _set_absolute_selection_range(widget_object, "time", *selected)
        return selected

    def assert_persisted_input_state(self, widget_object, state_token) -> None:
        """Absolute patch selections should survive compatible replacements."""
        assert widget_object._selection_patch_basis == "absolute"
        assert widget_object._selection_current_patch_range("time") == pytest.approx(
            state_token
        )

    def assert_reset_input_state(self, widget_object, state_token) -> None:
        """Out-of-range replacements should preserve the stored selection."""
        assert widget_object._selection_current_patch_range("time") == pytest.approx(
            state_token
        )
        assert widget_object.Warning.empty_selection.is_shown()

    def test_f_enters_fullscreen_with_plot_focused(self):
        """F enters fullscreen even when the pyqtgraph plot widget has focus."""
        import time

        from AnyQt.QtTest import QTest

        widget_object = self.create_default_widget()
        widget_object.show()
        self.process_events()
        window = widget_object.window()
        window.activateWindow()
        window.raise_()
        widget_object._plot_widget.setFocus()
        self.process_events()
        assert not window.isFullScreen()

        QTest.keyClick(window, Qt.Key_F)
        deadline = time.monotonic() + 1.0
        while not window.isFullScreen() and time.monotonic() < deadline:
            self.process_events()
            time.sleep(0.01)
        assert window.isFullScreen()
        window.showNormal()
        self.process_events()

    def test_ctrl_q_closes_window_with_plot_focused(self):
        """Ctrl+Q closes the window even when the pyqtgraph plot widget has focus."""
        import time

        from AnyQt.QtTest import QTest

        widget_object = self.create_default_widget()
        widget_object.show()
        self.process_events()
        window = widget_object.window()
        window.activateWindow()
        window.raise_()
        widget_object._plot_widget.setFocus()
        self.process_events()
        assert window.isVisible()

        QTest.keyClick(window, Qt.Key_Q, Qt.ControlModifier)
        deadline = time.monotonic() + 1.0
        while window.isVisible() and time.monotonic() < deadline:
            self.process_events()
            time.sleep(0.01)
        assert not window.isVisible()
