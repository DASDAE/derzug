"""Tests for the Analytic widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.analytic import Analytic


@pytest.fixture
def analytic_widget(qtbot):
    """Return a live Analytic widget for one test case."""
    with widget_context(Analytic) as widget:
        yield widget


class TestAnalytic:
    """Tests for the Analytic widget."""

    def test_widget_instantiates(self, analytic_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(analytic_widget, Analytic)
        assert analytic_widget.transform == "hilbert"
        assert analytic_widget.selected_dim == ""

    def test_patch_none_emits_none(self, analytic_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)

        analytic_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_hilbert_emits_patch(self, analytic_widget, monkeypatch, qtbot):
        """Hilbert transform emits a patch with the same shape."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        analytic_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_envelope_selector_triggers_rerun(
        self, analytic_widget, monkeypatch, qtbot
    ):
        """Changing the transform selector reruns with envelope."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        analytic_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        analytic_widget._transform_combo.setCurrentText("envelope")
        wait_for_output(qtbot, received)

        out = received[-1]
        assert analytic_widget.transform == "envelope"
        assert out is not None
        assert out.shape == patch.shape

    def test_dimension_change_triggers_rerun(self, analytic_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        analytic_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if analytic_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = analytic_widget.selected_dim
        other_dim = next(
            analytic_widget._dim_combo.itemText(i)
            for i in range(analytic_widget._dim_combo.count())
            if analytic_widget._dim_combo.itemText(i) != current
        )
        analytic_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert analytic_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_invalid_transform_falls_back(self, analytic_widget, monkeypatch, qtbot):
        """Invalid transform setting falls back to the default."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        analytic_widget.transform = "not-a-transform"

        analytic_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert analytic_widget.transform == "hilbert"
        assert analytic_widget._transform_combo.currentText() == "hilbert"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, analytic_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        analytic_widget.selected_dim = "not-a-dim"

        analytic_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert analytic_widget.selected_dim == "time"
        assert analytic_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_transform_failed_shows_error(self, analytic_widget, monkeypatch, qtbot):
        """When the transform raises, the widget emits None and shows an error."""
        received = capture_output(analytic_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "hilbert", _raise)
        analytic_widget._patch = patch
        analytic_widget._available_dims = tuple(patch.dims)
        analytic_widget.selected_dim = "time"
        analytic_widget.transform = "hilbert"
        analytic_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert analytic_widget.Error.transform_failed.is_shown()


class TestAnalyticDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Analytic."""

    __test__ = True
    widget = Analytic
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
