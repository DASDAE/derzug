"""Tests for the Calculus widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.calculus import Calculus


@pytest.fixture
def calculus_widget(qtbot):
    """Return a live Calculus widget for one test case."""
    with widget_context(Calculus) as widget:
        yield widget


class TestCalculus:
    """Tests for the Calculus widget."""

    def test_widget_instantiates(self, calculus_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(calculus_widget, Calculus)
        assert calculus_widget.transform == "differentiate"
        assert calculus_widget.order == 2
        assert calculus_widget.step == 1
        assert calculus_widget.definite is False

    def test_patch_none_emits_none(self, calculus_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)

        calculus_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_differentiate_emits_patch(self, calculus_widget, monkeypatch, qtbot):
        """Differentiate emits a valid patch."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_integrate_selector_triggers_rerun(
        self, calculus_widget, monkeypatch, qtbot
    ):
        """Changing the transform selector reruns with integrate."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        calculus_widget._transform_combo.setCurrentText("integrate")
        wait_for_output(qtbot, received)

        out = received[-1]
        assert calculus_widget.transform == "integrate"
        assert out is not None

    def test_integrate_definite_changes_axis_length(
        self, calculus_widget, monkeypatch, qtbot
    ):
        """Definite integration collapses the selected axis to length 1."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        calculus_widget.transform = "integrate"
        calculus_widget.definite = True

        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        time_axis = out.dims.index("time")
        assert out.shape[time_axis] == 1

    def test_dimension_change_triggers_rerun(self, calculus_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if calculus_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = calculus_widget.selected_dim
        other_dim = next(
            calculus_widget._dim_combo.itemText(i)
            for i in range(calculus_widget._dim_combo.count())
            if calculus_widget._dim_combo.itemText(i) != current
        )
        calculus_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert calculus_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_invalid_transform_falls_back(self, calculus_widget, monkeypatch, qtbot):
        """Invalid transform setting falls back to the default."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        calculus_widget.transform = "not-a-transform"

        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert calculus_widget.transform == "differentiate"
        assert calculus_widget._transform_combo.currentText() == "differentiate"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, calculus_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        calculus_widget.selected_dim = "not-a-dim"

        calculus_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert calculus_widget.selected_dim == "time"
        assert calculus_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_transform_failed_shows_error(self, calculus_widget, monkeypatch, qtbot):
        """When the transform raises, the widget emits None and shows an error."""
        received = capture_output(calculus_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "differentiate", _raise)
        calculus_widget._patch = patch
        calculus_widget._available_dims = tuple(patch.dims)
        calculus_widget.selected_dim = "time"
        calculus_widget.transform = "differentiate"
        calculus_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert calculus_widget.Error.transform_failed.is_shown()


class TestCalculusDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Calculus."""

    __test__ = True
    widget = Calculus
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
