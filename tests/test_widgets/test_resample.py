"""Tests for the Resample widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.resample import Resample


@pytest.fixture
def resample_widget(qtbot):
    """Return a live Resample widget for one test case."""
    with widget_context(Resample) as widget:
        yield widget


class TestResample:
    """Tests for the Resample widget."""

    def test_widget_instantiates(self, resample_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(resample_widget, Resample)
        assert resample_widget.mode == "decimate"
        assert resample_widget.decimate_factor == "2"
        assert resample_widget.resample_target == "10 ms"

    def test_patch_none_emits_none(self, resample_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)

        resample_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_dims_prefer_time(self, resample_widget):
        """The dim selector prefers time when it is available."""
        patch = dc.get_example_patch("example_event_2")

        resample_widget.set_patch(patch)

        assert resample_widget.selected_dim == "time"

    def test_decimate_reduces_samples(self, resample_widget, monkeypatch, qtbot):
        """Decimation by factor 2 reduces the selected-dim sample count."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "2"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape[1] == 501

    @pytest.mark.parametrize("filter_type", ["fir", "none"])
    def test_decimate_filter_options(
        self, resample_widget, monkeypatch, qtbot, filter_type
    ):
        """Decimation accepts FIR and no-filter modes."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "2"
        resample_widget.decimate_filter_type = filter_type

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is not None

    def test_integer_factor_reaches_patch_as_int(
        self, resample_widget, monkeypatch, qtbot
    ):
        """Integer-shaped decimation factor is passed through as int."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_decimate(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "decimate", _fake_decimate)
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "2"
        resample_widget.selected_dim = "time"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 2
        assert isinstance(captured["time"], int)

    def test_explicit_float_factor_is_rejected(
        self, resample_widget, monkeypatch, qtbot
    ):
        """Float-shaped decimation factor shows error and emits None."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "2.0"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert resample_widget.Error.invalid_factor.is_shown()

    def test_invalid_factor_error_clears_after_valid_run(
        self, resample_widget, monkeypatch, qtbot
    ):
        """A valid rerun clears invalid-factor error and emits a patch."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "bad"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert resample_widget.Error.invalid_factor.is_shown()

        resample_widget.decimate_factor = "2"
        resample_widget.run()
        wait_for_output(qtbot, received, 2)

        assert received[-1] is not None
        assert not resample_widget.Error.invalid_factor.is_shown()

    def test_resample_to_period(self, resample_widget, monkeypatch, qtbot):
        """Period-based resampling produces a valid patch."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "resample"
        resample_widget.resample_samples = False
        resample_widget.resample_target = "10 ms"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape[1] == 10

    def test_resample_samples_mode_reaches_patch_as_int(
        self, resample_widget, monkeypatch, qtbot
    ):
        """Integer-shaped sample target is passed to DASCore as int."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_resample(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "resample", _fake_resample)
        resample_widget.mode = "resample"
        resample_widget.resample_samples = True
        resample_widget.resample_target = "10"
        resample_widget.selected_dim = "time"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 10
        assert isinstance(captured["time"], int)
        assert captured["samples"] is True

    def test_resample_samples_mode_reduces_to_requested_count(
        self, resample_widget, monkeypatch, qtbot
    ):
        """samples=True resampling uses the requested sample count."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "resample"
        resample_widget.resample_samples = True
        resample_widget.resample_target = "10"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape[1] == 10

    @pytest.mark.parametrize("target", ["10.0", "10 ms", ""])
    def test_invalid_samples_target_emits_none(
        self, resample_widget, monkeypatch, qtbot, target
    ):
        """samples=True rejects non-integer targets."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "resample"
        resample_widget.resample_samples = True
        resample_widget.resample_target = target

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert resample_widget.Error.invalid_target.is_shown()

    def test_invalid_period_target_emits_none(
        self, resample_widget, monkeypatch, qtbot
    ):
        """Invalid period target shows error and emits None."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        resample_widget.mode = "resample"
        resample_widget.resample_samples = False
        resample_widget.resample_target = ""

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert resample_widget.Error.invalid_target.is_shown()

    def test_selected_dim_falls_back_on_replacement_patch(
        self, resample_widget, monkeypatch, qtbot
    ):
        """Missing selected dims fall back to a valid dim on replacement input."""
        received = capture_output(resample_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        replaced = patch.rename_coords(time="seconds")
        resample_widget.mode = "decimate"
        resample_widget.decimate_factor = "2"

        resample_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        resample_widget.selected_dim = "time"

        resample_widget.set_patch(replaced)
        wait_for_output(qtbot, received, 2)

        assert received[-1] is not None
        assert resample_widget.selected_dim in replaced.dims


class TestResampleDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Resample."""

    __test__ = True
    widget = Resample
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
    compatible_patch = dc.get_example_patch("example_event_2")
    incompatible_patch = dc.get_example_patch("example_event_2").rename_coords(
        time="seconds"
    )
