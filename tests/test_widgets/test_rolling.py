"""Tests for the Rolling widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.rolling import Rolling


@pytest.fixture
def rolling_widget(qtbot):
    """Return a live Rolling widget for one test case."""
    with widget_context(Rolling) as widget:
        yield widget


class TestRolling:
    """Tests for the Rolling widget."""

    def test_widget_instantiates(self, rolling_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(rolling_widget, Rolling)
        assert rolling_widget.rolling_window == "0.01"
        assert rolling_widget.step == ""
        assert rolling_widget.center is False
        assert rolling_widget.dropna is False
        assert rolling_widget.aggregation in Rolling._AGGREGATIONS

    def test_patch_none_emits_none(self, rolling_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)

        rolling_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_run_emits_patch(self, rolling_widget, monkeypatch, qtbot):
        """A valid rolling config emits a processed patch."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.rolling_window = "0.01"
        rolling_widget.step = ""
        rolling_widget.dropna = False
        rolling_widget.aggregation = "mean"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape
        assert not np.array_equal(out.data, patch.data)

    def test_aggregation_change_triggers_rerun(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Changing aggregation emits a fresh output."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        start_count = len(received)

        rolling_widget._agg_combo.setCurrentText("max")
        wait_for_output(qtbot, received)

        assert len(received) > start_count
        assert rolling_widget.aggregation == "max"
        assert received[-1] is not None

    def test_dimension_change_triggers_rerun(self, rolling_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if rolling_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        first_count = len(received)
        current = rolling_widget.selected_dim
        other_dim = next(
            rolling_widget._dim_combo.itemText(i)
            for i in range(rolling_widget._dim_combo.count())
            if rolling_widget._dim_combo.itemText(i) != current
        )
        rolling_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert len(received) > first_count
        assert rolling_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_window_parse_supports_unit_values(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Window text accepts unit-bearing values."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        rolling_widget.rolling_window = "10 ms"
        rolling_widget.run()
        wait_for_output(qtbot, received, 2)
        assert received[-1] is not None

    def test_step_blank_and_value(self, rolling_widget, monkeypatch, qtbot):
        """Blank step maps to None and populated step is accepted."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        rolling_widget.step = ""
        rolling_widget.run()
        wait_for_output(qtbot, received, 2)
        assert received[-1] is not None

        rolling_widget.step = "0.005"
        rolling_widget.run()
        wait_for_output(qtbot, received, 3)
        assert received[-1] is not None

    def test_step_supports_unit_values(self, rolling_widget, monkeypatch, qtbot):
        """Step text accepts unit-bearing values."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        rolling_widget.step = "5 ms"
        rolling_widget.run()
        wait_for_output(qtbot, received, 2)

        assert received[-1] is not None

    def test_integer_window_text_reaches_patch_as_int(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Integer-shaped text is passed to rolling as an int."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        class _RollingResult:
            def mean(self):
                return patch

        def _fake_rolling(**kwargs):
            captured.update(kwargs)
            return _RollingResult()

        monkeypatch.setattr(patch, "rolling", _fake_rolling)
        rolling_widget.rolling_window = "2"
        rolling_widget.step = "3"
        rolling_widget.aggregation = "mean"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 2
        assert isinstance(captured["time"], int)
        assert captured["step"] == 3
        assert isinstance(captured["step"], int)

    def test_explicit_float_window_text_stays_float(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Float-shaped text is passed to rolling as a float."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        class _RollingResult:
            def mean(self):
                return patch

        def _fake_rolling(**kwargs):
            captured.update(kwargs)
            return _RollingResult()

        monkeypatch.setattr(patch, "rolling", _fake_rolling)
        rolling_widget.rolling_window = "2.0"
        rolling_widget.step = "3.0"
        rolling_widget.aggregation = "mean"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 2.0
        assert isinstance(captured["time"], float)
        assert captured["step"] == 3.0
        assert isinstance(captured["step"], float)

    def test_center_true_emits_patch(self, rolling_widget, monkeypatch, qtbot):
        """Enabling center mode still emits a valid patch."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.center = True

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_invalid_window_emits_none(self, rolling_widget, monkeypatch, qtbot):
        """Invalid window text shows error and emits None."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.rolling_window = "not-a-window"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert rolling_widget.Error.invalid_window.is_shown()

    def test_invalid_step_emits_none(self, rolling_widget, monkeypatch, qtbot):
        """Invalid step text shows error and emits None."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.rolling_window = "0.01"
        rolling_widget.step = "not-a-step"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert rolling_widget.Error.invalid_step.is_shown()

    def test_invalid_window_error_clears_after_valid_run(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """A valid rerun clears invalid-window error and emits a patch."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.rolling_window = "not-a-window"
        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert rolling_widget.Error.invalid_window.is_shown()

        rolling_widget.rolling_window = "0.01"
        rolling_widget.run()
        wait_for_output(qtbot, received, 2)

        assert not rolling_widget.Error.invalid_window.is_shown()
        assert received[-1] is not None

    def test_invalid_aggregation_falls_back_and_syncs_combo(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Invalid aggregation setting falls back to default and keeps UI synced."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.aggregation = "not-a-real-aggregation"

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert rolling_widget.aggregation == Rolling._AGGREGATIONS[0]
        assert rolling_widget._agg_combo.currentText() == Rolling._AGGREGATIONS[0]
        assert received[-1] is not None

    def test_dropna_removes_nans_on_selected_dim(
        self, rolling_widget, monkeypatch, qtbot
    ):
        """Drop NaN removes rolling-edge NaNs along the selected dim."""
        received = capture_output(rolling_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        rolling_widget.selected_dim = "time"
        rolling_widget.rolling_window = "0.01"
        rolling_widget.step = ""
        rolling_widget.dropna = False

        rolling_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out_no_drop = received[-1]
        assert out_no_drop is not None
        assert out_no_drop.shape[1] == patch.shape[1]

        rolling_widget.dropna = True
        rolling_widget.run()
        wait_for_output(qtbot, received, 2)
        out_drop = received[-1]
        assert out_drop is not None
        assert out_drop.shape[1] < out_no_drop.shape[1]


class TestRollingDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Rolling."""

    __test__ = True
    widget = Rolling
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
    compatible_patch = dc.get_example_patch("example_event_2")
    incompatible_patch = dc.get_example_patch("example_event_2").rename_coords(
        time="seconds"
    )
