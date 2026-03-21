"""Tests for the UFunc unary transform widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.ufunc_unary import UFunc


@pytest.fixture
def ufunc_widget(qtbot):
    """Return a live UFunc widget for one test case."""
    with widget_context(UFunc) as widget:
        yield widget


class TestUFunc:
    """Tests for the UFunc unary transform widget."""

    def test_widget_instantiates(self, ufunc_widget):
        """Widget creates with expected defaults and operation menu."""
        assert ufunc_widget.selected_op == "abs"
        assert ufunc_widget._op_combo.count() == len(UFunc._OPS)
        assert ufunc_widget._op_combo.currentText() == "abs"

    def test_operation_menu_contains_expected_ops(self, ufunc_widget):
        """Operation dropdown includes all expected unary operations."""
        labels = [
            ufunc_widget._op_combo.itemText(i)
            for i in range(ufunc_widget._op_combo.count())
        ]
        expected = {
            "abs",
            "real",
            "imag",
            "conj",
            "angle",
            "exp",
            "log",
            "log10",
            "log2",
        }
        assert set(labels) == expected

    def test_none_patch_emits_none(self, ufunc_widget, monkeypatch, qtbot):
        """A None patch emits None without error."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)

        ufunc_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_abs_emits_patch(self, ufunc_widget, monkeypatch, qtbot):
        """Abs operation on a real patch emits a patch with non-negative data."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        ufunc_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert isinstance(out, dc.Patch)
        assert out.shape == patch.shape
        assert np.all(out.data >= 0)

    def test_op_change_reruns(self, ufunc_widget, monkeypatch, qtbot):
        """Changing operation in dropdown triggers recomputation."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        ufunc_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        before = len(received)

        ufunc_widget._op_combo.setCurrentText("exp")
        wait_for_output(qtbot, received, before + 1)

        assert ufunc_widget.selected_op == "exp"
        assert len(received) > before
        assert received[-1] is not None

    def test_invalid_op_falls_back_to_default(self, ufunc_widget, monkeypatch, qtbot):
        """An unknown persisted op resets to default and computes once."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        ufunc_widget.selected_op = "not-a-real-op"

        ufunc_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert ufunc_widget.selected_op == "abs"
        assert ufunc_widget._op_combo.currentText() == "abs"
        assert received[-1] is not None

    def test_operation_failure_shows_error_and_emits_none(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """When the operation raises, the widget shows an error and emits None."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise():
            raise ValueError("boom")

        monkeypatch.setattr(patch, "abs", _raise)
        ufunc_widget._patch = patch
        ufunc_widget.selected_op = "abs"
        ufunc_widget.run()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert ufunc_widget.Error.operation_failed.is_shown()

    def test_error_clears_after_valid_input(self, ufunc_widget, monkeypatch, qtbot):
        """Error banner is cleared when a subsequent valid input succeeds."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise():
            raise ValueError("boom")

        monkeypatch.setattr(patch, "abs", _raise)
        ufunc_widget._patch = patch
        ufunc_widget.selected_op = "abs"
        ufunc_widget.run()
        wait_for_output(qtbot, received)
        assert ufunc_widget.Error.operation_failed.is_shown()

        good_patch = dc.get_example_patch("example_event_1")
        ufunc_widget.set_patch(good_patch)
        wait_for_output(qtbot, received, 2)

        assert received[-1] is not None
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_clearing_patch_emits_none_without_error(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Setting patch to None after a valid patch clears output without error."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        ufunc_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert received[-1] is not None

        ufunc_widget.set_patch(None)
        wait_for_output(qtbot, received, 2)

        assert received[-1] is None
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_log_emits_patch(self, ufunc_widget, monkeypatch, qtbot):
        """Log operation emits a patch of the same shape."""
        received = capture_output(ufunc_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        ufunc_widget._op_combo.setCurrentText("log")

        ufunc_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape


class TestUFuncDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for UFunc unary widget."""

    __test__ = True
    widget = UFunc
    inputs = (("patch", dc.get_example_patch("example_event_1")),)
