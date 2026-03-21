"""Tests for the FBE widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from dascore.units import percent
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.fbe import FBE


@pytest.fixture
def fbe_widget(qtbot):
    """Return a live FBE widget for one test case."""
    with widget_context(FBE) as widget:
        yield widget


class TestFBE:
    """Tests for the FBE widget."""

    def test_widget_instantiates(self, fbe_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(fbe_widget, FBE)
        assert fbe_widget.selected_dim == ""
        assert fbe_widget.window_length == "0.01"
        assert fbe_widget.overlap == "50 %"
        assert fbe_widget.taper_window == "hann"
        assert fbe_widget.samples is False
        assert fbe_widget.detrend is False
        assert fbe_widget.fbe_lower == ""
        assert fbe_widget.fbe_upper == ""
        labels = [
            fbe_widget._taper_window_combo.itemText(i)
            for i in range(fbe_widget._taper_window_combo.count())
        ]
        assert set(labels) == {"hann", "hamming", "blackman", "nuttall"}

    def test_patch_none_emits_none(self, fbe_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)

        fbe_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_default_settings_work_for_example_event_2(
        self, fbe_widget, monkeypatch, qtbot
    ):
        """Default widget settings should succeed on example_event_2."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.dims == ("distance", "time")
        assert out.shape == (601, 21)
        assert fbe_widget.selected_dim == "time"
        assert fbe_widget._dim_combo.currentText() == "time"
        assert fbe_widget._dim_combo.isEnabled() is False
        assert not fbe_widget.Error.transform_failed.is_shown()

    def test_fbe_matches_explicit_pipeline(self, fbe_widget, monkeypatch, qtbot):
        """FBE output should match the explicit STFT-power-band pipeline."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        fbe_widget.fbe_lower = "100"
        fbe_widget.fbe_upper = "500"

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        stft_patch = patch.stft(time=0.01, overlap=50 * percent, taper_window="hann")
        expected = (
            (stft_patch * stft_patch.conj())
            .select(ft_time=(100, 500))
            .sum("ft_time")
            .squeeze()
        )
        out = received[-1]
        assert out is not None
        assert out.dims == expected.dims
        assert out.shape == expected.shape
        assert np.allclose(out.data, expected.data)

    def test_dimension_is_locked_to_time(self, fbe_widget, monkeypatch, qtbot):
        """FBE should always keep its dimension fixed to time."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert fbe_widget._dim_combo.count() == 1
        assert fbe_widget._dim_combo.itemText(0) == "time"
        assert fbe_widget.selected_dim == "time"
        assert received[-1] is not None

    def test_window_length_reaches_patch_method(self, fbe_widget, monkeypatch, qtbot):
        """The selected dimension window length should be passed via kwargs."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}
        original_stft = patch.stft

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
            return original_stft(time=0.01)

        monkeypatch.setattr(patch, "stft", _fake_stft)
        fbe_widget.window_length = "25"
        fbe_widget.overlap = "10"
        fbe_widget.samples = True
        fbe_widget.detrend = True
        fbe_widget.selected_dim = "time"
        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is not None
        assert captured["overlap"] == 10
        assert captured["samples"] is True
        assert captured["detrend"] is True
        assert captured["kwargs"] == {"time": 25}

    def test_invalid_taper_window_setting_falls_back_to_default(
        self, fbe_widget, monkeypatch, qtbot
    ):
        """Invalid persisted taper-window values should reset to hann."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fbe_widget.taper_window = "not-a-window"

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is not None
        assert fbe_widget.taper_window == "hann"
        assert fbe_widget._taper_window_combo.currentText() == "hann"

    def test_taper_window_change_reruns(self, fbe_widget, monkeypatch, qtbot):
        """Changing taper window via dropdown reruns the widget."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        before = len(received)

        fbe_widget._taper_window_combo.setCurrentText("hamming")
        wait_for_output(qtbot, received, before + 1)

        assert fbe_widget.taper_window == "hamming"
        assert received[-1] is not None

    def test_patch_without_time_dimension_is_incompatible(
        self, fbe_widget, monkeypatch, qtbot
    ):
        """
        Patches without time should emit None and show the incompatible-patch
        error.
        """
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1").rename_coords(time="seconds")

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert fbe_widget.Error.invalid_patch.is_shown()
        assert fbe_widget._dim_combo.count() == 0

    def test_valid_patch_clears_incompatible_patch_error(
        self, fbe_widget, monkeypatch, qtbot
    ):
        """A valid time patch after an incompatible one should clear the error."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        incompatible = dc.get_example_patch("example_event_1").rename_coords(
            time="seconds"
        )
        compatible = dc.get_example_patch("example_event_1")

        fbe_widget.set_patch(incompatible)
        wait_for_output(qtbot, received)
        assert fbe_widget.Error.invalid_patch.is_shown()

        fbe_widget.set_patch(compatible)
        wait_for_output(qtbot, received, 2)

        assert received[-1] is not None
        assert not fbe_widget.Error.invalid_patch.is_shown()

    def test_invalid_overlap_shows_error(self, fbe_widget, monkeypatch, qtbot):
        """Unparseable overlap values should show a widget error."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fbe_widget.overlap = "abc def"

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert fbe_widget.Error.invalid_overlap.is_shown()

    def test_invalid_fbe_lower_shows_error(self, fbe_widget, monkeypatch, qtbot):
        """Unparseable lower band values should show a widget error."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fbe_widget.fbe_lower = "abc def"

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert fbe_widget.Error.invalid_fbe_lower.is_shown()

    def test_reversed_fbe_band_shows_error(self, fbe_widget, monkeypatch, qtbot):
        """Lower > upper should show a dedicated FBE band error."""
        received = capture_output(fbe_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fbe_widget.fbe_lower = "500"
        fbe_widget.fbe_upper = "100"

        fbe_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert fbe_widget.Error.invalid_fbe_band.is_shown()


class TestFBEDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for FBE."""

    __test__ = True
    widget = FBE
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
