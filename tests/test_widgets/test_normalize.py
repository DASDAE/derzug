"""Tests for the Normalize widget."""

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
from derzug.widgets.normalize import Normalize


@pytest.fixture
def normalize_widget(qtbot):
    """Return a live Normalize widget for one test case."""
    with widget_context(Normalize) as widget:
        yield widget


class TestNormalize:
    """Tests for the Normalize widget."""

    def test_widget_instantiates(self, normalize_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(normalize_widget, Normalize)
        assert normalize_widget.operation == "normalize"
        assert normalize_widget.selected_dim == ""
        assert normalize_widget.norm == "l2"

    def test_patch_none_emits_none(self, normalize_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)

        normalize_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_normalize_emits_patch(self, normalize_widget, monkeypatch, qtbot):
        """A valid normalize config emits a processed patch."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape
        assert not np.array_equal(out.data, patch.data)

    def test_standardize_selector_triggers_rerun(
        self, normalize_widget, monkeypatch, qtbot
    ):
        """Changing the operation selector reruns with standardize."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        normalize_widget._operation_combo.setCurrentText("standardize")
        wait_for_output(qtbot, received)

        out = received[-1]
        assert normalize_widget.operation == "standardize"
        assert out is not None
        assert out.shape == patch.shape

    def test_dimension_change_triggers_rerun(
        self, normalize_widget, monkeypatch, qtbot
    ):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        if normalize_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = normalize_widget.selected_dim
        other_dim = next(
            normalize_widget._dim_combo.itemText(i)
            for i in range(normalize_widget._dim_combo.count())
            if normalize_widget._dim_combo.itemText(i) != current
        )
        normalize_widget._dim_combo.setCurrentText(other_dim)
        wait_for_output(qtbot, received)

        assert normalize_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_norm_change_triggers_rerun(self, normalize_widget, monkeypatch, qtbot):
        """Changing norm reruns and emits a fresh output."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        normalize_widget._norm_combo.setCurrentText("max")
        wait_for_output(qtbot, received)

        assert normalize_widget.norm == "max"
        assert received[-1] is not None

    def test_invalid_operation_falls_back(self, normalize_widget, monkeypatch, qtbot):
        """Invalid operation setting falls back to the default."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.operation = "not-an-operation"

        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert normalize_widget.operation == "normalize"
        assert normalize_widget._operation_combo.currentText() == "normalize"
        assert received[-1] is not None

    def test_invalid_norm_falls_back(self, normalize_widget, monkeypatch, qtbot):
        """Invalid norm setting falls back to the default."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.norm = "not-a-norm"

        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert normalize_widget.norm == "l2"
        assert normalize_widget._norm_combo.currentText() == "l2"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, normalize_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        normalize_widget.selected_dim = "not-a-dim"

        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert normalize_widget.selected_dim == "time"
        assert normalize_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_norm_reaches_patch_method(self, normalize_widget, monkeypatch, qtbot):
        """Selected norm is passed through to patch.normalize."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_normalize(dim, *, norm):
            captured["dim"] = dim
            captured["norm"] = norm
            return patch

        monkeypatch.setattr(patch, "normalize", _fake_normalize)
        normalize_widget.norm = "bit"
        normalize_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["dim"] == "time"
        assert captured["norm"] == "bit"

    def test_operation_failed_shows_error(self, normalize_widget, monkeypatch, qtbot):
        """When the operation raises, the widget emits None and shows an error."""
        received = capture_output(normalize_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "normalize", _raise)
        normalize_widget._patch = patch
        normalize_widget._available_dims = tuple(patch.dims)
        normalize_widget.selected_dim = "time"
        normalize_widget.operation = "normalize"
        normalize_widget.norm = "l2"
        normalize_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert normalize_widget.Error.operation_failed.is_shown()


class TestNormalizeDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Normalize."""

    __test__ = True
    widget = Normalize
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_1").rename_coords(
        time="seconds"
    )
