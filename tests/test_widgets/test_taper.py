"""Tests for the Taper widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.taper import Taper


@pytest.fixture
def taper_widget(qtbot):
    """Return a live Taper widget for one test case."""
    with widget_context(Taper) as widget:
        yield widget


class TestTaper:
    """Tests for the Taper widget."""

    def test_widget_instantiates(self, taper_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(taper_widget, Taper)
        assert taper_widget.window_type == "hann"
        assert taper_widget.p == pytest.approx(0.05)
        assert taper_widget.selected_dim == ""

    def test_none_patch_emits_none(self, taper_widget, monkeypatch, qtbot):
        """A None patch clears output without error."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)

        taper_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_patch_emits_output(self, taper_widget, monkeypatch, qtbot):
        """A valid patch emits a tapered patch of the same shape."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert isinstance(out, dc.Patch)
        assert out.shape == patch.shape

    def test_dim_change_reruns(self, taper_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if taper_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = taper_widget.selected_dim
        other_dim = next(
            taper_widget._dim_combo.itemText(i)
            for i in range(taper_widget._dim_combo.count())
            if taper_widget._dim_combo.itemText(i) != current
        )
        taper_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received, 2)

        assert taper_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_p_change_reruns(self, taper_widget, monkeypatch, qtbot):
        """Changing taper fraction reruns and emits a fresh output."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        before = len(received)

        taper_widget._p_spin.setValue(0.1)
        wait_for_output(qtbot, received, before + 1)

        assert taper_widget.p == pytest.approx(0.1)
        assert received[-1] is not None

    def test_window_change_reruns(self, taper_widget, monkeypatch, qtbot):
        """Changing window type reruns and emits a fresh output."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        before = len(received)

        taper_widget._window_combo.setCurrentText("hamming")
        wait_for_output(qtbot, received, before + 1)

        assert taper_widget.window_type == "hamming"
        assert received[-1] is not None

    def test_invalid_window_falls_back(self, taper_widget, monkeypatch, qtbot):
        """An invalid window type setting resets to hann."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        taper_widget.window_type = "not-a-window"

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert taper_widget.window_type == "hann"
        assert taper_widget._window_combo.currentText() == "hann"
        assert received[-1] is not None

    def test_p_clamped_to_valid_range(self, taper_widget, monkeypatch, qtbot):
        """Out-of-range p value is clamped to [0.0, 0.4]."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        taper_widget.p = 0.9  # above max 0.4

        taper_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert taper_widget.p == pytest.approx(0.4)
        assert received[-1] is not None

    def test_taper_failure_shows_error(self, taper_widget, monkeypatch, qtbot):
        """When taper raises, the widget shows an error and emits None."""
        received = capture_output(taper_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "taper", _raise)
        taper_widget._patch = patch
        taper_widget._available_dims = tuple(patch.dims)
        taper_widget.selected_dim = "time"
        taper_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert taper_widget.Error.taper_failed.is_shown()

    def test_window_combo_contains_all_types(self, taper_widget):
        """Window combo includes all expected window type options."""
        labels = [
            taper_widget._window_combo.itemText(i)
            for i in range(taper_widget._window_combo.count())
        ]
        assert set(labels) == {"hann", "hamming", "blackman", "nuttall"}


class TestTaperDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for the Taper widget."""

    __test__ = True
    widget = Taper
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
