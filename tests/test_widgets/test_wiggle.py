"""Tests for the Wiggle widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pyqtgraph as pg
import pytest
from AnyQt.QtCore import QEvent, QPoint, QPointF, Qt
from AnyQt.QtGui import QMouseEvent
from AnyQt.QtWidgets import QApplication
from derzug.utils.display import format_display
from derzug.utils.testing import (
    TestPatchInputStateDefaults,
    TestWidgetDefaults,
    widget_context,
)
from derzug.widgets.wiggle import Wiggle


@pytest.fixture(scope="session")
def example_patch_2d():
    """Return one shared 2D example patch for wiggle tests."""
    return dc.get_example_patch("example_event_2")


@pytest.fixture(scope="session")
def small_patch_2d(example_patch_2d):
    """Return a smaller 2D patch for tests that do not need full render size."""
    return example_patch_2d.select(time=(0, 80), samples=True).select(
        distance=(0, 40), samples=True
    )


@pytest.fixture(scope="session")
def medium_patch_2d(example_patch_2d):
    """Return a 2D patch with a few hundred traces for auto-stride tests."""
    return example_patch_2d.select(distance=(0, 200), samples=True)


@pytest.fixture(scope="session")
def example_patch_1d(example_patch_2d):
    """Return one shared 1D example patch for wiggle tests."""
    return _to_1d_patch(example_patch_2d)


@pytest.fixture(scope="session")
def ricker_moveout_patch():
    """Return the ricker moveout example patch used for direct wiggle regressions."""
    return dc.get_example_patch("ricker_moveout")


@pytest.fixture
def wiggle_widget(qtbot):
    """Return a live Wiggle widget."""
    with widget_context(Wiggle) as widget:
        widget.show()
        qtbot.wait(1)
        yield widget


@pytest.fixture
def capture_patch_output(monkeypatch):
    """Return a helper that captures patch output values from a widget."""

    def _capture(wiggle_widget) -> list:
        received: list = []

        def _sink(value):
            received.append(value)

        monkeypatch.setattr(wiggle_widget.Outputs.patch, "send", _sink)
        return received

    return _capture


class _FakePatch3D:
    """Minimal fake patch carrying invalid 3D data for render-path testing."""

    data = np.zeros((2, 2, 2))
    dims = ("x", "y", "z")

    @staticmethod
    def get_array(_):
        return np.array([0, 1], dtype=float)


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


def _to_1d_patch(patch: dc.Patch, dim: str = "distance") -> dc.Patch:
    """Reduce one axis from an example patch to obtain a true 1D patch."""
    return patch.mean(dim).squeeze()


def _with_data_units(patch: dc.Patch, value) -> dc.Patch:
    """Return a patch with the requested data_units attribute value."""
    return patch.update_attrs(data_units=value)


def _make_nd_wiggle_patch(*, lag_count: int = 3, patch_count: int = 2) -> dc.Patch:
    """Return a 4D patch for ND wiggle plot/slice tests."""
    base = dc.get_example_patch("example_event_2").transpose("distance", "time")
    data4d = np.stack(
        [
            np.stack(
                [
                    base.data * (lag_index + 1) * (patch_index + 1)
                    for patch_index in range(patch_count)
                ],
                axis=-1,
            )
            for lag_index in range(lag_count)
        ],
        axis=-2,
    )
    lag_time = (np.arange(lag_count) - (lag_count // 2)).astype("timedelta64[s]")
    return dc.Patch(
        data=data4d,
        coords={
            "distance": base.get_array("distance"),
            "time": base.get_array("time"),
            "lag_time": lag_time,
            "patch_number": np.arange(patch_count),
        },
        dims=("distance", "time", "lag_time", "patch_number"),
        attrs=base.attrs,
    )


def _first_trace_peak_excursion(widget: Wiggle) -> float:
    """Return the peak excursion of the first rendered wiggle trace."""
    state = widget._render_state
    assert state is not None and state.mode == "offset"
    sample_count = len(state.x_plot)
    trace_offset = float(state.trace_offsets[0])
    first_trace = state.flat_y[:sample_count]
    return float(np.nanmax(np.abs(first_trace - trace_offset)))


def _dispatch_mouse_event(
    widget,
    event_type: QEvent.Type,
    pos: QPoint,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    """Send one mouse event directly to a widget."""
    event = QMouseEvent(
        event_type,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        button,
        buttons,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


class TestWiggle:
    """Tests for the Wiggle widget."""

    def test_1d_state_preserves_raw_values(self, example_patch_1d):
        """The 1D builder should preserve raw data and axis metadata."""
        patch = example_patch_1d

        state = Wiggle._build_time_series_state_1d(patch)

        assert state.mode == "time series"
        assert state.x_dim == patch.dims[0]
        assert np.allclose(state.x_plot, patch.get_array(patch.dims[0]))
        assert np.allclose(state.line_values[0], np.asarray(patch.data))
        assert np.allclose(state.full_line_values[0], np.asarray(patch.data))
        assert state.series_dim is None
        assert state.color_levels is None
        assert state.y_dim == "ϵ / s"

    def test_2d_state_derives_series_metadata(self, small_patch_2d):
        """The 2D builder should choose the non-X dim as the series dimension."""
        patch = small_patch_2d

        state = Wiggle._build_time_series_state_2d(
            patch,
            selected_x_dim="time",
            percentiles_enabled=False,
            color_limits=None,
        )

        assert state.mode == "time series"
        assert state.x_dim == "time"
        assert state.series_dim == "distance"
        assert state.line_values.shape == (patch.shape[0], patch.shape[1])
        assert state.full_line_values.shape == (patch.shape[0], patch.shape[1])
        assert np.allclose(state.series_coord, patch.get_array("distance"))
        assert state.color_levels == pytest.approx(
            (
                float(np.min(patch.get_array("distance"))),
                float(np.max(patch.get_array("distance"))),
            )
        )
        assert state.y_dim == "ϵ / s"

    def test_2d_state_falls_back_to_default_levels_for_stale_color_limits(
        self, small_patch_2d
    ):
        """Out-of-range persisted color limits should not collapse all trace colors."""
        patch = small_patch_2d

        state = Wiggle._build_time_series_state_2d(
            patch,
            selected_x_dim="time",
            percentiles_enabled=False,
            color_limits=(0.0, 10.0),
        )

        assert state.color_levels == pytest.approx(
            (
                float(np.min(patch.get_array("distance"))),
                float(np.max(patch.get_array("distance"))),
            )
        )

    def test_build_offset_state_2d_applies_stride(self, small_patch_2d):
        """The offset builder should subsample traces via stride before plotting."""
        patch = small_patch_2d

        state = Wiggle._build_offset_state_2d(
            patch,
            selected_trace_dim="distance",
            stride=10,
            gain=150,
        )

        assert state.mode == "offset"
        assert state.y_dim == "distance"
        assert np.array_equal(state.trace_indices, np.arange(patch.shape[0])[::10])
        assert state.trace_offsets.shape == state.trace_indices.shape
        assert state.flat_x.size == state.flat_y.size

    def test_widget_instantiates(self, wiggle_widget):
        """Widget starts with no curves, an empty combo, and default settings."""
        assert wiggle_widget._trace_axis_combo.count() == 0
        assert wiggle_widget.stride == Wiggle.stride.default
        assert wiggle_widget.gain == Wiggle.gain.default
        assert wiggle_widget.percentiles is False
        assert wiggle_widget._offset_box.isHidden()
        assert wiggle_widget._time_series_box.isHidden()

    def test_saved_time_series_settings_survive_no_patch_startup(
        self, wiggle_widget, small_patch_2d
    ):
        """Persisted mode/axis settings survive startup before the patch arrives."""
        patch = small_patch_2d
        wiggle_widget.mode = "time series"
        wiggle_widget.selected_x_dim = "time"
        wiggle_widget.selected_trace_dim = "distance"

        wiggle_widget._refresh_controls()
        wiggle_widget.set_patch(patch)

        assert wiggle_widget.mode == "time series"
        assert wiggle_widget._mode_combo.currentText() == "time series"
        assert wiggle_widget.selected_x_dim == "time"
        assert wiggle_widget._x_axis_combo.currentText() == "time"

    def test_patch_is_forwarded(
        self, wiggle_widget, capture_patch_output, small_patch_2d
    ):
        """Input patch is emitted unchanged on the output signal."""
        received = capture_patch_output(wiggle_widget)
        patch = small_patch_2d

        wiggle_widget.set_patch(patch)

        assert received == [patch]
        x, _ = wiggle_widget._curve.getData()
        assert x is not None and len(x) > 0

    def test_hidden_set_patch_defers_render_until_show(self, qtbot, small_patch_2d):
        """Hidden widgets should defer the expensive plot redraw until shown."""
        patch = small_patch_2d

        with widget_context(Wiggle) as widget:
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

    def test_failed_refresh_clears_pending_preserve_view(
        self, wiggle_widget, monkeypatch
    ):
        """Render failures should not leak preserve-view state into later refreshes."""
        wiggle_widget._preserve_view_on_refresh = True

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(wiggle_widget, "_render_patch", _boom)

        with pytest.raises(RuntimeError, match="boom"):
            wiggle_widget._refresh_ui()

        assert wiggle_widget._preserve_view_on_refresh is False

    def test_first_2d_patch_initializes_stride_from_trace_count(
        self, wiggle_widget, example_patch_2d
    ):
        """The first 2D patch should set a stride that caps offset traces at 300."""
        patch = example_patch_2d

        wiggle_widget.set_patch(patch)

        trace_count = wiggle_widget._trace_count_for_dim(
            patch, wiggle_widget.selected_trace_dim
        )
        expected = Wiggle._auto_stride_for_trace_count(trace_count)
        assert wiggle_widget.stride == expected

    def test_first_2d_patch_uses_stride_one_below_100_traces(
        self, wiggle_widget, small_patch_2d
    ):
        """Small patches should keep stride at 1 on first initialization."""
        patch = small_patch_2d

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.selected_trace_dim == "distance"
        assert wiggle_widget.stride == 1

    def test_first_2d_patch_uses_stride_one_below_300_traces(
        self, wiggle_widget, medium_patch_2d
    ):
        """Patches with only a few hundred traces should keep stride at 1."""
        patch = medium_patch_2d

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.selected_trace_dim == "distance"
        assert wiggle_widget._trace_count_for_dim(patch, "distance") == 200
        assert wiggle_widget.stride == 1

    def test_first_ricker_moveout_patch_uses_distance_trace_count_for_stride(
        self, wiggle_widget, ricker_moveout_patch
    ):
        """First-load auto stride should use the resolved distance trace axis."""
        patch = ricker_moveout_patch

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.selected_trace_dim == "distance"
        assert wiggle_widget._trace_count_for_dim(patch, "distance") == 10
        assert wiggle_widget.stride == 1

    def test_trace_axis_change_rerenders(
        self, wiggle_widget, capture_patch_output, small_patch_2d
    ):
        """Changing trace axis re-renders and emits a fresh output."""
        received = capture_patch_output(wiggle_widget)
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)

        if wiggle_widget._trace_axis_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        previous_count = len(received)
        current = wiggle_widget.selected_trace_dim
        other_dim = (set(patch.dims) - {current}).pop()
        wiggle_widget._trace_axis_combo.setCurrentText(other_dim)

        assert len(received) > previous_count
        assert received[-1] is patch
        assert wiggle_widget.selected_trace_dim == other_dim

    def test_later_patches_do_not_overwrite_stride(
        self, wiggle_widget, medium_patch_2d, small_patch_2d
    ):
        """Only the first 2D patch should auto-initialize the stride."""
        first_patch = small_patch_2d
        second_patch = medium_patch_2d

        wiggle_widget.set_patch(first_patch)
        assert wiggle_widget.stride == 1

        wiggle_widget.set_patch(second_patch)

        assert wiggle_widget.stride == 1

    def test_trace_axis_change_does_not_recompute_initialized_stride(
        self, wiggle_widget, small_patch_2d
    ):
        """Switching trace axes later should preserve the initialized stride."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        initial_stride = wiggle_widget.stride

        other_dim = (set(patch.dims) - {wiggle_widget.selected_trace_dim}).pop()
        wiggle_widget._trace_axis_combo.setCurrentText(other_dim)

        assert wiggle_widget.stride == initial_stride

    def test_distance_is_default_trace_dim(self, wiggle_widget, small_patch_2d):
        """Distance is preferred as default trace axis when present."""
        patch = small_patch_2d
        assert (
            "distance" in patch.dims
        ), "example patch must have a distance dim for this test"

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.selected_trace_dim == "distance"

    def test_time_series_prefers_time_x_dim_when_unset(
        self, wiggle_widget, small_patch_2d
    ):
        """Unset time-series X axis should prefer a dimension named time."""
        patch = small_patch_2d
        wiggle_widget.selected_x_dim = ""

        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")

        assert wiggle_widget.selected_x_dim == "time"
        assert wiggle_widget._x_axis_combo.currentText() == "time"

    def test_time_series_falls_back_to_second_dim_when_time_missing(
        self, wiggle_widget, small_patch_2d
    ):
        """Unset time-series X axis should fall back to dims[1] without time."""
        patch = small_patch_2d.rename_coords(time="shot")
        wiggle_widget.selected_x_dim = ""

        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")

        assert wiggle_widget.selected_x_dim == patch.dims[1]
        assert wiggle_widget._x_axis_combo.currentText() == patch.dims[1]

    def test_datetime_x_axis_uses_date_axis_item(self, wiggle_widget, small_patch_2d):
        """Datetime x coordinates should render with an absolute-time date axis."""
        patch = _with_datetime_coord(small_patch_2d, "time")

        wiggle_widget.set_patch(patch)

        assert isinstance(wiggle_widget._plot_item.getAxis("bottom"), pg.DateAxisItem)
        assert "2024-01-02" in wiggle_widget._plot_item.getAxis("bottom").labelText

    def test_datetime_trace_axis_uses_date_axis_item(
        self, wiggle_widget, small_patch_2d
    ):
        """Datetime trace offsets should render with an absolute-time date axis."""
        patch = _with_datetime_coord(small_patch_2d, "distance")

        wiggle_widget.set_patch(patch)

        assert isinstance(wiggle_widget._plot_item.getAxis("left"), pg.DateAxisItem)
        assert "2024-01-02" in wiggle_widget._plot_item.getAxis("left").labelText

    def test_zoomed_datetime_x_axis_shows_omitted_context(
        self, wiggle_widget, small_patch_2d
    ):
        """Fine datetime zooms should add omitted higher-level context to the label."""
        patch = _with_millisecond_datetime_coord(small_patch_2d, "time")

        wiggle_widget.set_patch(patch)
        x, _y = wiggle_widget._curve.getData()
        finite_x = np.asarray(x)[np.isfinite(x)]
        wiggle_widget._plot_item.vb.setRange(
            xRange=(float(finite_x[10]), float(finite_x[12])),
            yRange=(400.0, 1000.0),
            padding=0,
        )

        assert (
            "2024-01-02 03:04" in wiggle_widget._plot_item.getAxis("bottom").labelText
        )

    def test_offset_cursor_shows_amplitude(self, wiggle_widget, small_patch_2d):
        """Cursor readout reports plotted x/y plus the nearest raw sample amplitude."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        state = wiggle_widget._render_state
        x_index = len(state.x_plot) // 3
        trace_offset_index = len(state.trace_offsets) // 4
        trace_index = int(state.trace_indices[trace_offset_index])

        wiggle_widget._update_cursor_readout(
            plot_x=float(state.x_plot[x_index]),
            plot_y=float(state.trace_offsets[trace_offset_index]),
        )

        text = wiggle_widget._cursor_label.text()
        expected = wiggle_widget._raw_trace_value(
            np.asarray(patch.data),
            x_index=x_index,
            trace_index=trace_index,
        )
        assert f"{state.x_dim}=" in text
        assert "y=" in text
        assert f"value={format_display(expected)}" in text

    def test_cursor_readout_shows_datetime_x_values(
        self, wiggle_widget, small_patch_2d
    ):
        """Datetime x axes should preserve absolute datetime text in the readout."""
        patch = _with_datetime_coord(small_patch_2d, "time")
        wiggle_widget.set_patch(patch)
        state = wiggle_widget._render_state
        x_index = len(state.x_plot) // 3
        trace_offset_index = len(state.trace_offsets) // 4

        wiggle_widget._update_cursor_readout(
            plot_x=float(state.x_plot[x_index]),
            plot_y=float(state.trace_offsets[trace_offset_index]),
        )

        assert "2024-01-02T" in wiggle_widget._cursor_label.text()

    def test_cursor_readout_clears_without_patch(self, wiggle_widget, small_patch_2d):
        """Cursor readout resets when there is no patch to inspect."""
        wiggle_widget.set_patch(small_patch_2d)

        wiggle_widget.set_patch(None)

        assert wiggle_widget._cursor_label.text() == "Cursor: --"

    def test_fallback_trace_dim_is_first(self, wiggle_widget, small_patch_2d):
        """When distance is absent, the first dim is used as the trace axis."""
        patch = small_patch_2d
        # After renaming, the example patch dims remain ordered as ("time", "channel").
        patch = patch.rename_coords(distance="channel")
        assert "distance" not in patch.dims

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.selected_trace_dim == patch.dims[0]

    def test_gain_change_preserves_view_range(self, wiggle_widget, small_patch_2d):
        """Changing gain keeps the user's current zoom extents."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)

        wiggle_widget._plot_item.vb.setRange(
            xRange=(2.0, 5.0),
            yRange=(10.0, 20.0),
            padding=0,
        )
        before = wiggle_widget._plot_item.vb.viewRange()

        wiggle_widget._gain_slider.setValue(wiggle_widget._gain_slider.value() + 25)

        after = wiggle_widget._plot_item.vb.viewRange()
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_gain_slider_uses_linear_percent_range(self, wiggle_widget, small_patch_2d):
        """The gain slider should span 1% to 1200% on a linear mapping."""
        wiggle_widget.set_patch(small_patch_2d)

        wiggle_widget._gain_slider.setValue(wiggle_widget._gain_slider.minimum())
        assert wiggle_widget.gain == 1
        assert wiggle_widget._gain_label.text() == "1%"

        wiggle_widget._gain_slider.setValue(wiggle_widget._gain_slider.maximum())
        assert wiggle_widget.gain == 1200
        assert wiggle_widget._gain_label.text() == "1200%"

        assert wiggle_widget._gain_slider.minimum() == Wiggle._GAIN_MIN
        assert wiggle_widget._gain_slider.maximum() == Wiggle._GAIN_MAX
        wiggle_widget.gain = Wiggle.gain.default
        wiggle_widget._sync_gain_control()
        assert wiggle_widget._gain_slider.value() == Wiggle.gain.default

    def test_dragging_gain_slider_to_right_edge_expands_maximum(
        self, wiggle_widget, small_patch_2d
    ):
        """Dragging against the right edge should extend the gain range upward."""
        wiggle_widget.set_patch(small_patch_2d)
        slider = wiggle_widget._gain_slider
        slider.setValue(slider.maximum())
        start_max = slider.maximum()
        y_pos = slider.rect().center().y()

        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseButtonPress,
            QPoint(slider.width() - 2, y_pos),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        )
        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseMove,
            QPoint(slider.width() + 20, y_pos),
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseButtonRelease,
            QPoint(slider.width() + 20, y_pos),
            button=Qt.LeftButton,
            buttons=Qt.NoButton,
        )

        assert slider.maximum() > start_max
        assert wiggle_widget.gain == slider.maximum()

    def test_dragging_gain_slider_to_left_edge_stops_at_one_percent(
        self, wiggle_widget, small_patch_2d
    ):
        """Dragging against the left edge should not lower gain below 1%."""
        wiggle_widget.set_patch(small_patch_2d)
        slider = wiggle_widget._gain_slider
        slider.setValue(slider.minimum())
        start_min = slider.minimum()
        y_pos = slider.rect().center().y()

        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseButtonPress,
            QPoint(1, y_pos),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        )
        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseMove,
            QPoint(-20, y_pos),
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        _dispatch_mouse_event(
            slider,
            QEvent.Type.MouseButtonRelease,
            QPoint(-20, y_pos),
            button=Qt.LeftButton,
            buttons=Qt.NoButton,
        )

        assert slider.minimum() == start_min == Wiggle._GAIN_MIN
        assert wiggle_widget.gain == slider.minimum()

    def test_lowering_gain_after_stride_change_shrinks_rendered_curve_excursion(
        self, wiggle_widget, small_patch_2d
    ):
        """After changing stride, lowering gain should reduce the rendered excursion."""
        wiggle_widget.set_patch(small_patch_2d)
        wiggle_widget._gain_slider.setValue(1000)
        wiggle_widget._stride_spin.setValue(1)

        state = wiggle_widget._render_state
        assert state is not None and state.mode == "offset"
        sample_count = len(state.x_plot)
        first_offset = float(state.trace_offsets[0])
        _, high_curve = wiggle_widget._curve.getData()
        high_excursion = float(
            np.nanmax(np.abs(high_curve[:sample_count] - first_offset))
        )

        wiggle_widget._gain_slider.setValue(300)

        state = wiggle_widget._render_state
        assert state is not None and state.mode == "offset"
        sample_count = len(state.x_plot)
        first_offset = float(state.trace_offsets[0])
        _, low_curve = wiggle_widget._curve.getData()
        low_excursion = float(
            np.nanmax(np.abs(low_curve[:sample_count] - first_offset))
        )

        assert wiggle_widget.gain == 300
        assert low_excursion < high_excursion

    def test_lowering_gain_after_stride_change_reduces_trace_excursion(
        self, wiggle_widget, small_patch_2d
    ):
        """Lowering gain should shrink rendered traces even after a stride change."""
        wiggle_widget.set_patch(small_patch_2d)

        wiggle_widget._gain_slider.setValue(1000)
        wiggle_widget._stride_spin.setValue(1)
        high_excursion = _first_trace_peak_excursion(wiggle_widget)

        wiggle_widget._gain_slider.setValue(300)
        low_excursion = _first_trace_peak_excursion(wiggle_widget)

        assert wiggle_widget.gain == 300
        assert low_excursion < high_excursion

    def test_stride_change_preserves_view_range(self, wiggle_widget, small_patch_2d):
        """Changing stride should keep the user's current zoom extents."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)

        wiggle_widget._plot_item.vb.setRange(
            xRange=(2.0, 5.0),
            yRange=(10.0, 20.0),
            padding=0,
        )
        before = wiggle_widget._plot_item.vb.viewRange()

        wiggle_widget._stride_spin.setValue(wiggle_widget.stride + 1)

        after = wiggle_widget._plot_item.vb.viewRange()
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_invalid_patch_keeps_pass_through_output(
        self, wiggle_widget, capture_patch_output
    ):
        """Render failure shows error but still emits the input patch object."""
        received = capture_patch_output(wiggle_widget)
        fake_patch = _FakePatch3D()

        wiggle_widget.set_patch(fake_patch)

        assert received[-1] is fake_patch
        assert wiggle_widget.Error.invalid_patch.is_shown()
        assert wiggle_widget._mode_combo.count() == 0

    def test_patch_none_clears_output(
        self, wiggle_widget, capture_patch_output, small_patch_2d
    ):
        """Sending None clears curves and emits None."""
        received = capture_patch_output(wiggle_widget)
        wiggle_widget.set_patch(small_patch_2d)
        x, _ = wiggle_widget._curve.getData()
        assert x is not None and len(x) > 0
        received.clear()

        wiggle_widget.set_patch(None)

        assert received == [None]
        x, _ = wiggle_widget._curve.getData()
        assert x is None or len(x) == 0

    def test_1d_patch_auto_selects_time_series_mode(
        self, wiggle_widget, example_patch_1d
    ):
        """True 1D patches should force time-series mode."""
        patch = example_patch_1d

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.mode == "time series"
        assert wiggle_widget._mode_combo.currentText() == "time series"
        assert wiggle_widget._mode_combo.count() == 1
        assert wiggle_widget._trace_axis_combo.isEnabled() is False
        assert wiggle_widget._offset_box.isHidden()
        assert not wiggle_widget._time_series_box.isHidden()

    def test_1d_patch_flips_out_of_offset_mode(
        self, wiggle_widget, small_patch_2d, example_patch_1d
    ):
        """Receiving a 1D patch should immediately leave offset mode."""
        wiggle_widget.set_patch(small_patch_2d)
        assert wiggle_widget.mode == "offset"

        wiggle_widget.set_patch(example_patch_1d)

        assert wiggle_widget.mode == "time series"
        assert wiggle_widget._mode_combo.currentText() == "time series"
        assert wiggle_widget._render_state.mode == "time series"

    def test_1d_plot_uses_dim_on_x(self, wiggle_widget, example_patch_1d):
        """1D patches should render as a single raw-value line plot."""
        patch = example_patch_1d

        wiggle_widget.set_patch(patch)

        x, y = wiggle_widget._curve.getData()
        assert np.allclose(x, patch.get_array(patch.dims[0]))
        assert np.allclose(y, np.asarray(patch.data))
        assert wiggle_widget._plot_item.getAxis("bottom").labelText == patch.dims[0]
        assert wiggle_widget._plot_item.getAxis("left").labelText == "ϵ / s"

    def test_1d_time_series_falls_back_to_value_without_data_units(
        self, wiggle_widget, example_patch_1d
    ):
        """Falsey data_units should preserve the old generic y-axis label."""
        patch = _with_data_units(example_patch_1d, "")

        wiggle_widget.set_patch(patch)

        assert wiggle_widget._plot_item.getAxis("left").labelText == "value"

    def test_1d_datetime_x_axis_uses_date_axis_item(
        self, wiggle_widget, example_patch_1d
    ):
        """1D datetime coordinates should render with a date axis."""
        patch = _with_datetime_coord(example_patch_1d, example_patch_1d.dims[0])

        wiggle_widget.set_patch(patch)

        assert isinstance(wiggle_widget._plot_item.getAxis("bottom"), pg.DateAxisItem)
        assert "2024-01-02" in wiggle_widget._plot_item.getAxis("bottom").labelText

    def test_1d_cursor_readout_reports_coordinate_and_value(
        self, wiggle_widget, example_patch_1d
    ):
        """1D cursor readout should report the nearest coordinate and raw value."""
        patch = example_patch_1d
        wiggle_widget.set_patch(patch)
        x = np.asarray(patch.get_array(patch.dims[0]))
        y = np.asarray(patch.data)
        index = len(x) // 3

        wiggle_widget._update_cursor_readout(
            plot_x=float(x[index]), plot_y=float(y[index])
        )

        text = wiggle_widget._cursor_label.text()
        assert f"{patch.dims[0]}=" in text
        assert f"value={format_display(y[index])}" in text

    def test_time_series_mode_renders_2d_lines_colored_by_other_axis(
        self, wiggle_widget, small_patch_2d
    ):
        """2D time-series mode should color one line per non-X coordinate."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)

        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")

        assert wiggle_widget._render_state.mode == "time series"
        assert wiggle_widget._render_state.x_dim == "time"
        assert wiggle_widget._render_state.series_dim == "distance"
        assert wiggle_widget._render_state.line_values.shape[0] == patch.shape[0]
        assert wiggle_widget._color_bar.isVisible()
        assert wiggle_widget._offset_box.isHidden()
        assert not wiggle_widget._time_series_box.isHidden()
        assert wiggle_widget._color_bar.getAxis("left").labelText == "distance"
        assert wiggle_widget._plot_item.getAxis("bottom").labelText == "time"
        assert wiggle_widget._plot_item.getAxis("left").labelText == "ϵ / s"

    def test_percentiles_checkbox_is_in_time_series_controls(
        self, wiggle_widget, small_patch_2d
    ):
        """The percentile toggle should live in the time-series control section."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")

        assert not wiggle_widget._time_series_box.isHidden()
        assert (
            wiggle_widget._percentiles_checkbox.parent()
            is wiggle_widget._time_series_box
        )
        assert wiggle_widget._percentiles_checkbox.isEnabled()

    def test_percentile_mode_renders_fixed_summary_curves(
        self, wiggle_widget, small_patch_2d
    ):
        """Percentile mode should render the fixed symmetric percentile set."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")

        wiggle_widget._percentiles_checkbox.setChecked(True)

        state = wiggle_widget._render_state
        assert state.percentiles_enabled is True
        assert state.series_dim == "percentile"
        assert state.line_values.shape[0] == 7
        assert np.allclose(state.series_plot, [0, 5, 25, 50, 75, 95, 100])
        assert np.allclose(state.series_coord, [0, 5, 25, 50, 75, 95, 100])
        assert wiggle_widget._color_bar.getAxis("left").labelText == "percentile"

    def test_percentile_toggle_preserves_view_range(
        self, wiggle_widget, small_patch_2d
    ):
        """Turning percentile mode on and off should not reset zoom."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        wiggle_widget._plot_item.vb.setRange(
            xRange=(0.01, 0.03),
            yRange=(-0.001, 0.001),
            padding=0,
        )
        before = wiggle_widget._plot_item.vb.viewRange()

        wiggle_widget._percentiles_checkbox.setChecked(True)
        during = wiggle_widget._plot_item.vb.viewRange()

        wiggle_widget._percentiles_checkbox.setChecked(False)
        after = wiggle_widget._plot_item.vb.viewRange()

        assert np.allclose(during[0], before[0])
        assert np.allclose(during[1], before[1])
        assert np.allclose(after[0], before[0])
        assert np.allclose(after[1], before[1])

    def test_percentile_mode_cursor_reports_percentile(
        self, wiggle_widget, small_patch_2d
    ):
        """Percentile mode cursor text should identify the nearest percentile curve."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        wiggle_widget._percentiles_checkbox.setChecked(True)
        state = wiggle_widget._render_state
        sample_index = len(state.x_plot) // 3
        percentile_index = 3
        line_y = state.line_values[percentile_index, sample_index]

        wiggle_widget._update_cursor_readout(
            plot_x=float(state.x_plot[sample_index]),
            plot_y=float(line_y),
        )

        text = wiggle_widget._cursor_label.text()
        assert f"{state.x_dim}=" in text
        assert "percentile=50" in text

    def test_percentile_mode_colorbar_recolors_summary_curves(
        self, wiggle_widget, small_patch_2d
    ):
        """Changing the colorbar should recolor percentile summary curves."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        wiggle_widget._percentiles_checkbox.setChecked(True)

        before = [
            curve.opts["pen"].color().getRgb()
            for curve in wiggle_widget._all_line_curves()[:7]
        ]

        wiggle_widget._color_bar.setLevels((25.0, 75.0))
        wiggle_widget._on_color_bar_levels_changed(wiggle_widget._color_bar)

        after = [
            curve.opts["pen"].color().getRgb()
            for curve in wiggle_widget._all_line_curves()[:7]
        ]
        assert wiggle_widget.series_color_limits == [25.0, 75.0]
        assert before != after

    def test_percentile_mode_styles_median_curve(self, wiggle_widget, small_patch_2d):
        """The 50th percentile curve should be thicker and dotted."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        wiggle_widget._percentiles_checkbox.setChecked(True)

        median_curve = wiggle_widget._all_line_curves()[3]
        pen = median_curve.opts["pen"]

        assert pen.style() == Qt.PenStyle.DotLine
        assert pen.widthF() >= 4

    def test_disabling_percentiles_restores_full_trace_render(
        self, wiggle_widget, small_patch_2d
    ):
        """Turning percentile mode back off should restore the original traces."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        wiggle_widget._percentiles_checkbox.setChecked(True)

        wiggle_widget._percentiles_checkbox.setChecked(False)

        state = wiggle_widget._render_state
        assert state.percentiles_enabled is False
        assert state.series_dim == "distance"
        assert state.line_values.shape[0] == patch.shape[0]

    def test_time_series_uses_value_without_data_units(
        self, wiggle_widget, small_patch_2d
    ):
        """Falsey data_units should keep the generic time-series y-axis label."""
        patch = _with_data_units(small_patch_2d, None)

        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")

        assert wiggle_widget._plot_item.getAxis("left").labelText == "value"

    def test_time_series_default_render_uses_multiple_pen_colors(
        self, wiggle_widget, small_patch_2d
    ):
        """Default 2D time-series rendering should color traces by series coordinate."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")

        colors = [
            curve.opts["pen"].color().getRgb()
            for curve in wiggle_widget._all_line_curves()[:20]
        ]

        assert len(set(colors)) > 1

    def test_offset_mode_shows_only_offset_controls(
        self, wiggle_widget, small_patch_2d
    ):
        """2D offset mode should only show the offset parameter section."""
        patch = small_patch_2d

        wiggle_widget.set_patch(patch)

        assert wiggle_widget.mode == "offset"
        assert not wiggle_widget._offset_box.isHidden()
        assert wiggle_widget._time_series_box.isHidden()

    def test_clearing_patch_hides_mode_sections(self, wiggle_widget, small_patch_2d):
        """When no patch is loaded, the mode-specific sections should be hidden."""
        wiggle_widget.set_patch(small_patch_2d)

        wiggle_widget.set_patch(None)

        assert wiggle_widget._offset_box.isHidden()
        assert wiggle_widget._time_series_box.isHidden()

    def test_time_series_x_axis_switch_changes_series_dimension(
        self, wiggle_widget, small_patch_2d
    ):
        """Changing the X axis in time-series mode should swap the colored dimension."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")

        wiggle_widget._x_axis_combo.setCurrentText("distance")

        assert wiggle_widget._render_state.x_dim == "distance"
        assert wiggle_widget._render_state.series_dim == "time"
        assert wiggle_widget._color_bar.getAxis("left").labelText == "time"

    def test_nd_patch_shows_dim_strip_and_renders_default_slice(self, wiggle_widget):
        """ND patches should render a sliced 2D display with the shared dim strip."""
        patch = _make_nd_wiggle_patch()

        wiggle_widget.set_patch(patch)

        assert wiggle_widget._dim_strip.isVisible()
        assert wiggle_widget._display_patch is not None
        assert wiggle_widget._display_patch.dims == ("distance", "time")
        assert set(wiggle_widget._slice_dims) == {"lag_time", "patch_number"}
        assert set(wiggle_widget._slice_sliders) == {"lag_time", "patch_number"}
        assert wiggle_widget.Error.invalid_patch.is_shown() is False

    def test_nd_slice_slider_updates_display_patch(self, wiggle_widget):
        """Changing an ND slice slider should update the 2D display patch."""
        patch = _make_nd_wiggle_patch()
        wiggle_widget.set_patch(patch)

        lag_slider = wiggle_widget._slice_sliders["lag_time"]
        lag_slider.setValue(1)
        lag_slider.sliderReleased.emit()

        expected = (
            patch.select(
                lag_time=np.array([patch.get_array("lag_time")[1]]),
                patch_number=np.array([patch.get_array("patch_number")[0]]),
            )
            .squeeze("lag_time")
            .squeeze("patch_number")
        )
        assert wiggle_widget._display_patch is not None
        assert np.allclose(wiggle_widget._display_patch.data, expected.data)

    def test_nd_time_series_mode_limits_x_axis_choices_to_plotted_dims(
        self, wiggle_widget
    ):
        """ND time-series mode should offer only the sliced 2D plot dims
        as X choices.
        """
        patch = _make_nd_wiggle_patch()
        wiggle_widget.set_patch(patch)

        wiggle_widget._y_dim_combo.setCurrentText("lag_time")
        wiggle_widget._mode_combo.setCurrentText("time series")

        combo_items = [
            wiggle_widget._x_axis_combo.itemText(index)
            for index in range(wiggle_widget._x_axis_combo.count())
        ]

        assert wiggle_widget._display_patch is not None
        assert wiggle_widget._display_patch.dims == ("lag_time", "time")
        assert combo_items == ["lag_time", "time"]
        assert wiggle_widget.Error.invalid_patch.is_shown() is False

    def test_nd_singleton_slice_dim_does_not_render_slider_row(self, wiggle_widget):
        """Singleton non-plotted dims should stay fixed without rendering sliders."""
        patch = _make_nd_wiggle_patch(patch_count=1)
        wiggle_widget.set_patch(patch)

        assert set(wiggle_widget._slice_dims) == {"lag_time", "patch_number"}
        assert "lag_time" in wiggle_widget._slice_sliders
        assert "patch_number" not in wiggle_widget._slice_sliders
        assert wiggle_widget._slice_indices["patch_number"] == 0

    def test_time_series_cursor_readout_includes_series_coordinate(
        self, wiggle_widget, small_patch_2d
    ):
        """2D time-series cursor text should include X and series coordinates only."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")
        state = wiggle_widget._render_state
        sample_index = len(state.x_plot) // 3
        series_index = len(state.series_coord) // 4
        line_y = state.line_values[series_index, sample_index]

        wiggle_widget._update_cursor_readout(
            plot_x=float(state.x_plot[sample_index]),
            plot_y=float(line_y),
        )

        text = wiggle_widget._cursor_label.text()
        assert f"{state.x_dim}=" in text
        assert f"{state.series_dim}=" in text
        assert "value=" not in text

    def test_colorbar_recolors_lines(self, wiggle_widget, small_patch_2d):
        """Changing time-series colorbar levels should update line pens."""
        patch = small_patch_2d
        wiggle_widget.set_patch(patch)
        wiggle_widget._mode_combo.setCurrentText("time series")
        wiggle_widget._x_axis_combo.setCurrentText("time")

        before = [
            curve.opts["pen"].color().getRgb()
            for curve in wiggle_widget._all_line_curves()[:3]
        ]

        wiggle_widget._color_bar.setLevels((200.0, 400.0))
        wiggle_widget._on_color_bar_levels_changed(wiggle_widget._color_bar)

        after = [
            curve.opts["pen"].color().getRgb()
            for curve in wiggle_widget._all_line_curves()[:3]
        ]
        assert wiggle_widget.series_color_limits == [200.0, 400.0]
        assert before != after


class TestWiggleDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for Wiggle."""

    __test__ = True
    widget = Wiggle
    inputs = (("patch", dc.get_example_patch("example_event_2")),)


class TestWiggleStateDefaults(TestPatchInputStateDefaults):
    """Shared input-state defaults for Wiggle axis selections."""

    __test__ = True
    widget = Wiggle
    compatible_patch = (
        dc.get_example_patch("example_event_1")
        .select(time=(0, 80), samples=True)
        .select(distance=(0, 40), samples=True)
    )
    incompatible_patch = (
        dc.get_example_patch("example_event_2")
        .select(time=(0, 80), samples=True)
        .select(distance=(0, 40), samples=True)
        .rename_coords(time="shot")
    )

    def arrange_persisted_input_state(self, widget_object):
        """Persist a concrete compatible axis state before input replacement."""
        widget_object.mode = "time series"
        widget_object.selected_x_dim = "time"
        widget_object.selected_trace_dim = "distance"
        widget_object._request_ui_refresh()
        return {
            "mode": "time series",
            "x_dim": "time",
            "trace_dim": "distance",
        }

    def assert_persisted_input_state(self, widget_object, state_token) -> None:
        """Stored axis selections should survive `None` and compatible inputs."""
        assert widget_object.mode == state_token["mode"]
        assert widget_object.selected_x_dim == state_token["x_dim"]
        assert widget_object.selected_trace_dim == state_token["trace_dim"]
        if widget_object._patch is None:
            return
        assert widget_object._x_axis_combo.currentText() == state_token["x_dim"]
        assert widget_object._trace_axis_combo.currentText() == state_token["trace_dim"]

    def assert_reset_input_state(self, widget_object, state_token) -> None:
        """Only axis selections invalid for the new patch should reset."""
        assert widget_object.mode == state_token["mode"]
        assert widget_object.selected_trace_dim == state_token["trace_dim"]
        assert widget_object.selected_x_dim == "shot"
        assert widget_object._trace_axis_combo.currentText() == state_token["trace_dim"]
        assert widget_object._x_axis_combo.currentText() == "shot"
