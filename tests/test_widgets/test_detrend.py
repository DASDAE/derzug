"""Tests for the Detrend widget."""

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
from derzug.widgets.detrend import Detrend


@pytest.fixture
def detrend_widget(qtbot):
    """Return a live Detrend widget for one test case."""
    with widget_context(Detrend) as widget:
        yield widget


class TestDetrend:
    """Tests for the Detrend widget."""

    def test_widget_instantiates(self, detrend_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(detrend_widget, Detrend)
        assert detrend_widget.selected_dim == ""
        assert detrend_widget.detrend_type == "linear"

    def test_patch_none_emits_none(self, detrend_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)

        detrend_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_run_emits_patch(self, detrend_widget, monkeypatch, qtbot):
        """A valid detrend config emits a processed patch."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape
        assert not np.array_equal(out.data, patch.data)

    def test_type_change_triggers_rerun(self, detrend_widget, monkeypatch, qtbot):
        """Changing detrend type emits a fresh output."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        start_count = len(received)

        detrend_widget._type_combo.setCurrentText("constant")
        wait_for_output(qtbot, received)

        assert len(received) > start_count
        assert detrend_widget.detrend_type == "constant"
        assert received[-1] is not None

    def test_dimension_change_triggers_rerun(self, detrend_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if detrend_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = detrend_widget.selected_dim
        other_dim = next(
            detrend_widget._dim_combo.itemText(i)
            for i in range(detrend_widget._dim_combo.count())
            if detrend_widget._dim_combo.itemText(i) != current
        )
        detrend_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert detrend_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_invalid_type_falls_back(self, detrend_widget, monkeypatch, qtbot):
        """Invalid detrend type falls back to the default."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        detrend_widget.detrend_type = "not-a-type"

        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert detrend_widget.detrend_type == "linear"
        assert detrend_widget._type_combo.currentText() == "linear"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, detrend_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        detrend_widget.selected_dim = "not-a-dim"

        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert detrend_widget.selected_dim == "time"
        assert detrend_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_type_reaches_patch_method(self, detrend_widget, monkeypatch, qtbot):
        """Selected detrend type is passed through to patch.detrend."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_detrend(dim, detrend_type):
            captured["dim"] = dim
            captured["type"] = detrend_type
            return patch

        monkeypatch.setattr(patch, "detrend", _fake_detrend)
        detrend_widget.detrend_type = "constant"
        detrend_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["dim"] == "time"
        assert captured["type"] == "constant"

    def test_detrend_failed_shows_error(self, detrend_widget, monkeypatch, qtbot):
        """When patch.detrend raises, the error is shown and None is emitted."""
        received = capture_output(detrend_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "detrend", _raise)
        detrend_widget._patch = patch
        detrend_widget._available_dims = tuple(patch.dims)
        detrend_widget.selected_dim = "time"
        detrend_widget.detrend_type = "linear"
        detrend_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert detrend_widget.Error.detrend_failed.is_shown()


class TestDetrendDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Detrend."""

    __test__ = True
    widget = Detrend
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
