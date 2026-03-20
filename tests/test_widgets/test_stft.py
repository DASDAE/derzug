"""Tests for the Stft widget."""

from __future__ import annotations

import dascore as dc
import pytest
from dascore.units import percent
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.stft import Stft


@pytest.fixture
def stft_widget(qtbot):
    """Return a live Stft widget for one test case."""
    with widget_context(Stft) as widget:
        yield widget


class TestStft:
    """Tests for the Stft widget."""

    def test_widget_instantiates(self, stft_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(stft_widget, Stft)
        assert stft_widget.selected_dim == ""
        assert stft_widget.window_length == "0.01"
        assert stft_widget.overlap == "50 %"
        assert stft_widget.taper_window == "hann"
        assert stft_widget.samples is False
        assert stft_widget.detrend is False

    def test_patch_none_emits_none(self, stft_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)

        stft_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_stft_emits_patch(self, stft_widget, monkeypatch, qtbot):
        """A valid STFT emits a patch with Fourier and windowed axes."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        stft_widget.samples = True
        stft_widget.window_length = "128"
        stft_widget.overlap = "64"
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert "distance" in out.dims
        assert "ft_time" in out.dims
        assert "time" in out.dims

    def test_default_settings_work_for_example_event_2(
        self, stft_widget, monkeypatch, qtbot
    ):
        """Default widget settings should succeed on example_event_2."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.dims == ("distance", "ft_time", "time")
        assert out.shape == (601, 51, 21)
        assert not stft_widget.Error.transform_failed.is_shown()

    def test_sample_mode_works_for_example_event_2(
        self, stft_widget, monkeypatch, qtbot
    ):
        """Sample-count STFT settings should also succeed on example_event_2."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        stft_widget.samples = True
        stft_widget.window_length = "128"
        stft_widget.overlap = "64"

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.dims == ("distance", "ft_time", "time")
        assert out.shape == (601, 65, 17)

    def test_default_dimension_prefers_time(self, stft_widget, monkeypatch, qtbot):
        """The widget should default to the time dimension when present."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert stft_widget.selected_dim == "time"
        assert stft_widget._dim_combo.currentText() == "time"

    def test_invalid_dim_falls_back(self, stft_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        stft_widget.selected_dim = "not-a-dim"
        stft_widget.samples = True
        stft_widget.window_length = "128"
        stft_widget.overlap = "64"

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert stft_widget.selected_dim == "time"
        assert stft_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_dimension_change_triggers_rerun(self, stft_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        stft_widget.samples = True
        stft_widget.window_length = "8"
        stft_widget.overlap = "4"
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if stft_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = stft_widget.selected_dim
        other_dim = next(
            stft_widget._dim_combo.itemText(i)
            for i in range(stft_widget._dim_combo.count())
            if stft_widget._dim_combo.itemText(i) != current
        )
        stft_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert stft_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_window_length_reaches_patch_method(self, stft_widget, monkeypatch, qtbot):
        """The selected dimension window length should be passed via kwargs."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_stft(
            *,
            overlap=None,
            taper_window="hann",
            samples=False,
            detrend=False,
            **kwargs,
        ):
            captured["overlap"] = overlap
            captured["taper_window"] = taper_window
            captured["samples"] = samples
            captured["detrend"] = detrend
            captured["kwargs"] = kwargs
            return patch

        monkeypatch.setattr(patch, "stft", _fake_stft)
        stft_widget.window_length = "25"
        stft_widget.overlap = "10"
        stft_widget.samples = True
        stft_widget.detrend = True
        stft_widget.selected_dim = "time"
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["overlap"] == 10
        assert captured["samples"] is True
        assert captured["detrend"] is True
        assert captured["kwargs"] == {"time": 25}

    def test_default_percent_overlap_reaches_patch_method_as_quantity(
        self, stft_widget, monkeypatch, qtbot
    ):
        """Dispatch default percent overlap as a DASCore percent quantity."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_stft(
            *,
            overlap=None,
            taper_window="hann",
            samples=False,
            detrend=False,
            **kwargs,
        ):
            captured["overlap"] = overlap
            return patch

        monkeypatch.setattr(patch, "stft", _fake_stft)
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["overlap"] == 50 * percent

    def test_string_taper_window_reaches_patch_method(
        self, stft_widget, monkeypatch, qtbot
    ):
        """String taper-window values should be passed through as strings."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_stft(
            *,
            overlap=None,
            taper_window="hann",
            samples=False,
            detrend=False,
            **kwargs,
        ):
            captured["taper_window"] = taper_window
            return patch

        monkeypatch.setattr(patch, "stft", _fake_stft)
        stft_widget.taper_window = "boxcar"
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["taper_window"] == "boxcar"

    def test_tuple_taper_window_reaches_patch_method(
        self, stft_widget, monkeypatch, qtbot
    ):
        """Tuple taper-window values should be parsed before dispatch."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_stft(
            *,
            overlap=None,
            taper_window="hann",
            samples=False,
            detrend=False,
            **kwargs,
        ):
            captured["taper_window"] = taper_window
            return patch

        monkeypatch.setattr(patch, "stft", _fake_stft)
        stft_widget.taper_window = '("tukey", 0.1)'
        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["taper_window"] == ("tukey", 0.1)

    def test_invalid_taper_window_shows_error(self, stft_widget, monkeypatch, qtbot):
        """Unsupported taper-window literal types should raise a widget error."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        stft_widget.taper_window = "[1, 2, 3]"

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert stft_widget.Error.invalid_taper_window.is_shown()

    def test_invalid_overlap_shows_error(self, stft_widget, monkeypatch, qtbot):
        """Unparseable overlap values should show a widget error."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        stft_widget.overlap = "abc def"

        stft_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert stft_widget.Error.invalid_overlap.is_shown()

    def test_transform_failed_shows_error(self, stft_widget, monkeypatch, qtbot):
        """When STFT raises, the widget emits None and shows an error."""
        received = capture_output(stft_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(**kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "stft", _raise)
        stft_widget._patch = patch
        stft_widget._available_dims = tuple(patch.dims)
        stft_widget.selected_dim = "time"
        stft_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert stft_widget.Error.transform_failed.is_shown()


class TestStftDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Stft."""

    __test__ = True
    widget = Stft
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
