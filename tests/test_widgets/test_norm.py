"""Tests for the Norm widget."""

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
from derzug.widgets.norm import Norm


@pytest.fixture
def norm_widget(qtbot):
    """Return a live Norm widget for one test case."""
    with widget_context(Norm) as widget:
        yield widget


class TestNorm:
    """Tests for the Norm widget."""

    def test_widget_instantiates(self, norm_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(norm_widget, Norm)
        assert norm_widget.selected_dim == ""
        assert norm_widget.norm == "l2"

    def test_patch_none_emits_none(self, norm_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)

        norm_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_norm_emits_patch(self, norm_widget, monkeypatch, qtbot):
        """A valid norm config emits a processed patch."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape
        assert not np.array_equal(out.data, patch.data)

    def test_dimension_change_triggers_rerun(self, norm_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if norm_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = norm_widget.selected_dim
        other_dim = next(
            norm_widget._dim_combo.itemText(i)
            for i in range(norm_widget._dim_combo.count())
            if norm_widget._dim_combo.itemText(i) != current
        )
        norm_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert norm_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_norm_change_triggers_rerun(self, norm_widget, monkeypatch, qtbot):
        """Changing norm reruns and emits a fresh output."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        norm_widget._norm_combo.setCurrentText("max")
        wait_for_output(qtbot, received)

        assert norm_widget.norm == "max"
        assert received[-1] is not None

    def test_invalid_norm_falls_back(self, norm_widget, monkeypatch, qtbot):
        """Invalid norm setting falls back to the default."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        norm_widget.norm = "not-a-norm"

        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert norm_widget.norm == "l2"
        assert norm_widget._norm_combo.currentText() == "l2"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, norm_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        norm_widget.selected_dim = "not-a-dim"

        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert norm_widget.selected_dim == "time"
        assert norm_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_norm_reaches_patch_method(self, norm_widget, monkeypatch, qtbot):
        """Selected norm is passed through to patch.normalize."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_normalize(dim, *, norm):
            captured["dim"] = dim
            captured["norm"] = norm
            return patch

        monkeypatch.setattr(patch, "normalize", _fake_normalize)
        norm_widget.norm = "bit"
        norm_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["dim"] == "time"
        assert captured["norm"] == "bit"

    def test_operation_failed_shows_error(self, norm_widget, monkeypatch, qtbot):
        """When the operation raises, the widget emits None and shows an error."""
        received = capture_output(norm_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "normalize", _raise)
        norm_widget._patch = patch
        norm_widget._available_dims = tuple(patch.dims)
        norm_widget.selected_dim = "time"
        norm_widget.norm = "l2"
        norm_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert norm_widget.Error.operation_failed.is_shown()


class TestNormDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Norm."""

    __test__ = True
    widget = Norm
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
