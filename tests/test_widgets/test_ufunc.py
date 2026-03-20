"""Tests for the UFuncOperator widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import TestWidgetDefaults, widget_context
from derzug.widgets.ufunc import UFuncOperator
from orangewidget.utils.signals import PartialSummary


@pytest.fixture
def ufunc_widget():
    """Return a live UFuncOperator widget for one test case."""
    with widget_context(UFuncOperator) as widget:
        yield widget


def _capture_output(ufunc_widget, monkeypatch) -> list:
    """Patch the output slot with a capture function and return the sink."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(ufunc_widget.Outputs.result, "send", _sink)
    return received


def _wait_for_output(qtbot, received: list, count: int) -> None:
    """Wait until the patched output sink has received at least `count` values."""
    qtbot.waitUntil(lambda: len(received) >= count, timeout=3000)


class TestUFuncOperator:
    """Tests for the UFuncOperator widget."""

    def test_widget_instantiates(self, ufunc_widget):
        """Widget creates with expected defaults and operation menu."""
        assert ufunc_widget.name == "UfuncBinary"
        assert ufunc_widget.selected_op == "x+y"
        assert ufunc_widget._op_combo.count() > 0
        assert ufunc_widget._op_combo.currentText() == "x+y"

    def test_operation_menu_contains_expected_labels(self, ufunc_widget):
        """
        Symbolic operation menu includes all expected arithmetic/comparison labels.
        """
        labels = [
            ufunc_widget._op_combo.itemText(i)
            for i in range(ufunc_widget._op_combo.count())
        ]
        expected = {
            "x+y",
            "x-y",
            "x*y",
            "x/y",
            "x**y",
            "x%y",
            "maximum(x,y)",
            "minimum(x,y)",
            "x>y",
            "x<y",
            "x==y",
            "x!=y",
            "x>=y",
            "x<=y",
        }
        assert set(labels) == expected

    def test_missing_input_emits_none(self, ufunc_widget, monkeypatch, qtbot):
        """When one input is missing, output is None."""
        received = _capture_output(ufunc_widget, monkeypatch)

        ufunc_widget.set_x(2)
        _wait_for_output(qtbot, received, 1)

        assert received[-1] is None

    def test_op_change_with_missing_input_emits_none(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Changing operation with only one input still emits None without errors."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(2)
        _wait_for_output(qtbot, received, 1)
        ufunc_widget._op_combo.setCurrentText("x-y")
        _wait_for_output(qtbot, received, 2)

        assert received[-1] is None
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_add_scalars(self, ufunc_widget, monkeypatch, qtbot):
        """x+y operation adds scalar inputs."""
        received = _capture_output(ufunc_widget, monkeypatch)

        ufunc_widget.set_x(2)
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)

        assert received[-1] == 5

    def test_dropdown_change_recomputes(self, ufunc_widget, monkeypatch, qtbot):
        """Changing operation dropdown triggers recomputation."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(6)
        ufunc_widget.set_y(2)
        _wait_for_output(qtbot, received, 1)
        before = len(received)

        ufunc_widget._op_combo.setCurrentText("x-y")
        _wait_for_output(qtbot, received, before + 1)

        assert len(received) > before
        assert received[-1] == 4

    def test_comparison_returns_boolean_result(self, ufunc_widget, monkeypatch, qtbot):
        """Comparison operations return raw NumPy boolean-like output."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(np.array([1, 2, 3]))
        ufunc_widget.set_y(np.array([0, 2, 4]))
        _wait_for_output(qtbot, received, 1)

        ufunc_widget._op_combo.setCurrentText("x>y")
        _wait_for_output(qtbot, received, 2)

        out = received[-1]
        assert out is not None
        assert np.array_equal(out, np.array([True, False, False]))

    def test_scalar_comparison_returns_boolean(self, ufunc_widget, monkeypatch, qtbot):
        """Scalar comparison emits a boolean-like result."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(3)
        ufunc_widget.set_y(1)
        _wait_for_output(qtbot, received, 1)
        ufunc_widget._op_combo.setCurrentText("x>y")
        _wait_for_output(qtbot, received, 2)

        out = received[-1]
        assert out is not None
        assert bool(out) is True

    def test_patch_addition_emits_patch(self, ufunc_widget, monkeypatch, qtbot):
        """Adding two patches emits a patch-shaped result."""
        received = _capture_output(ufunc_widget, monkeypatch)
        patch_a = dc.get_example_patch("example_event_2")
        patch_b = dc.get_example_patch("example_event_2")

        ufunc_widget.set_x(patch_a)
        ufunc_widget.set_y(patch_b)
        _wait_for_output(qtbot, received, 1)

        out = received[-1]
        assert isinstance(out, dc.Patch)
        assert out.shape == patch_a.shape

    def test_length_one_spool_is_unwrapped_on_x(self, ufunc_widget, monkeypatch, qtbot):
        """A length-1 spool on x is unwrapped to its patch before the operation."""
        received = _capture_output(ufunc_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        ufunc_widget.set_x(dc.spool([patch]))
        ufunc_widget.set_y(patch)
        _wait_for_output(qtbot, received, 1)

        out = received[-1]
        assert isinstance(out, dc.Patch)
        assert out.shape == patch.shape

    def test_length_one_spools_on_both_inputs(self, ufunc_widget, monkeypatch, qtbot):
        """Length-1 spools on both inputs are unwrapped before applying the op."""
        received = _capture_output(ufunc_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        ufunc_widget.set_x(dc.spool([patch]))
        ufunc_widget.set_y(dc.spool([patch]))
        _wait_for_output(qtbot, received, 1)

        out = received[-1]
        assert isinstance(out, dc.Patch)
        assert out.shape == patch.shape

    def test_multi_patch_spool_rejected_on_input(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Multi-patch spool inputs are rejected with a user-visible error."""
        received = _capture_output(ufunc_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        multi = dc.spool([patch, patch])

        ufunc_widget.set_x(multi)
        ufunc_widget.set_y(patch)
        _wait_for_output(qtbot, received, 1)

        assert received[-1] is None
        assert ufunc_widget.Error.invalid_spool.is_shown()

    def test_invalid_pair_shows_error_and_emits_none(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Unsupported operand pairs produce user-visible error and None output."""
        received = _capture_output(ufunc_widget, monkeypatch)

        ufunc_widget.set_x("abc")
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)

        assert received[-1] is None
        assert ufunc_widget.Error.operation_failed.is_shown()

    def test_input_summary_uses_string_representation(self, ufunc_widget, monkeypatch):
        """Generic input objects should summarize via str(obj) without warnings."""

        class _OnlyString:
            def __repr__(self):
                raise RuntimeError("repr should not be used")

            def __str__(self):
                return "string-only-object"

        summaries: list[tuple[str, PartialSummary]] = []

        def _capture(name, partial_summary, **_kwargs):
            summaries.append((name, partial_summary))

        monkeypatch.setattr(ufunc_widget, "set_partial_input_summary", _capture)

        ufunc_widget.set_x(_OnlyString())

        assert summaries
        name, summary = summaries[-1]
        assert name == "x"
        assert summary.summary == "_OnlyString"
        assert "string-only-object" in summary.details

    def test_output_summary_uses_string_representation(self, ufunc_widget, monkeypatch):
        """Result summaries should also use str(obj) for arbitrary outputs."""

        class _OnlyString:
            def __repr__(self):
                raise RuntimeError("repr should not be used")

            def __str__(self):
                return "result-string"

        summaries: list[tuple[str, PartialSummary]] = []

        def _capture(name, partial_summary, **_kwargs):
            summaries.append((name, partial_summary))

        monkeypatch.setattr(ufunc_widget, "set_partial_output_summary", _capture)

        ufunc_widget._on_result(_OnlyString())

        assert summaries
        name, summary = summaries[-1]
        assert name == "Result"
        assert summary.summary == "_OnlyString"
        assert "result-string" in summary.details

    def test_clearing_input_emits_none_without_error(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Setting an input to None treats it as missing and clears output."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(2)
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)
        assert received[-1] == 5

        ufunc_widget.set_x(None)
        _wait_for_output(qtbot, received, 2)

        assert received[-1] is None
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_error_clears_after_valid_inputs(self, ufunc_widget, monkeypatch, qtbot):
        """Error banner is cleared when a subsequent valid pair succeeds."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x("abc")
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)
        assert ufunc_widget.Error.operation_failed.is_shown()

        ufunc_widget.set_x(4)
        _wait_for_output(qtbot, received, 2)

        assert received[-1] == 7
        assert not ufunc_widget.Error.operation_failed.is_shown()

    def test_reconnect_after_none_input_resumes_computation(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """After treating None as missing input, reconnecting recomputes normally."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.set_x(2)
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)
        assert received[-1] == 5

        ufunc_widget.set_y(None)
        _wait_for_output(qtbot, received, 2)
        assert received[-1] is None
        assert not ufunc_widget.Error.operation_failed.is_shown()

        ufunc_widget.set_y(4)
        _wait_for_output(qtbot, received, 3)
        assert received[-1] == 6

    def test_invalid_saved_op_falls_back_to_default(
        self, ufunc_widget, monkeypatch, qtbot
    ):
        """Unknown persisted op resets to default and computes once."""
        received = _capture_output(ufunc_widget, monkeypatch)
        ufunc_widget.selected_op = "not-a-real-op"
        ufunc_widget.set_x(2)
        ufunc_widget.set_y(3)
        _wait_for_output(qtbot, received, 1)

        assert ufunc_widget.selected_op == "x+y"
        assert ufunc_widget._op_combo.currentText() == "x+y"
        assert received[-1] == 5


class TestUFuncDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for UFuncOperator."""

    __test__ = True
    widget = UFuncOperator
