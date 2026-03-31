"""Tests for the Code widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QWidget
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.views.orange_errors import DerZugErrorDialog
from derzug.widgets.code import Code
from orangewidget.utils.signals import PartialSummary


@pytest.fixture
def code_widget(qtbot):
    """Return a live Code widget for one test case."""
    with widget_context(Code) as widget:
        yield widget


def _visible_message_label(widget) -> QWidget:
    """Return the visible Orange message-bar label for the current widget error."""
    return next(
        child
        for child in widget.message_bar.findChildren(QWidget)
        if type(child).__name__ == "ElidingLabel" and child.isVisible()
    )


@pytest.fixture
def primed(code_widget, monkeypatch, qtbot):
    """Widget with output captured, a patch loaded, and initial output cleared.

    Returns (widget, patch, received) ready for the test scenario.
    """
    patch = dc.get_example_patch("example_event_1")
    received = capture_output(code_widget.Outputs.result, monkeypatch)
    code_widget.set_patch(patch)
    wait_for_output(qtbot, received)
    received.clear()
    return code_widget, patch, received


class TestCode:
    """Tests for the Code widget."""

    def test_widget_instantiates(self, code_widget):
        """Widget creates with expected defaults and editor state."""
        assert isinstance(code_widget, Code)
        assert "def transform" in code_widget._editor.toPlainText()
        assert code_widget._autorun_enabled is False

    def test_none_patch_clears_output_without_running(
        self, code_widget, monkeypatch, qtbot
    ):
        """Receiving None before any run emits None without executing code."""
        received = capture_output(code_widget.Outputs.result, monkeypatch)
        code_widget._editor.setPlainText("raise RuntimeError('should not run')")
        received.clear()

        code_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]
        assert not code_widget.Error.execution_failed.is_shown()

    def test_run_emits_patch_result(self, primed, qtbot):
        """Pressing Run executes code and emits the result."""
        code_widget, patch, received = primed

        code_widget._editor.setPlainText("def transform(patch):\n    return patch")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert code_widget._autorun_enabled is True

    def test_script_can_transform_patch(self, primed, qtbot):
        """A script may transform the incoming patch before emitting it."""
        code_widget, patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch):\n    return patch.detrend('time', 'linear')"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_optional_transform_defaults_are_honored(self, primed, qtbot):
        """Optional transform parameters should use Python defaults when unset."""
        code_widget, patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch, scale=2):\n" "    return int(scale * len(patch.dims))"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] == 2 * len(patch.dims)
        assert not code_widget.Error.execution_failed.is_shown()

    def test_stdout_is_captured(self, primed, qtbot):
        """Printed output is captured in the widget log pane."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch):\n    print('hello')\n    return patch"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert "hello" in code_widget._log.toPlainText()

    def test_stderr_is_captured(self, primed, qtbot):
        """Stderr writes are captured in the widget log pane."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText(
            "import sys\n\n"
            "def transform(patch):\n"
            "    print('warn', file=sys.stderr)\n"
            "    return patch"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert "warn" in code_widget._log.toPlainText()

    def test_exception_shows_error_and_emits_none(self, primed, qtbot):
        """Exceptions are shown in the log and emit None."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText("raise ValueError('boom')")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget.Error.execution_failed.is_shown()
        assert "ValueError" in code_widget._log.toPlainText()
        assert "raise ValueError('boom')" in code_widget._editor.toPlainText()

    def test_syntax_error_shows_error_and_emits_none(self, primed, qtbot):
        """Syntax errors are shown in the log and emit None."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText("def transform(patch)\n    return patch")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget.Error.execution_failed.is_shown()
        assert "SyntaxError" in code_widget._log.toPlainText()

    def test_error_banner_double_click_opens_traceback_dialog(
        self, primed, qtbot, monkeypatch
    ):
        """The Code widget's bottom error banner should open the full traceback."""
        code_widget, _patch, received = primed
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        code_widget.show()
        qtbot.wait(10)
        code_widget._editor.setPlainText("raise ValueError('boom')")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert code_widget.Error.execution_failed.is_shown()
        qtbot.mouseDClick(_visible_message_label(code_widget), Qt.LeftButton)

        assert dialogs
        assert "ValueError: boom" in dialogs[0]._traceback_edit.toPlainText()

    def test_missing_result_emits_none(self, primed, qtbot):
        """Scripts that never set result emit None."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText("def transform(patch):\n    x = 1")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert not code_widget.Error.execution_failed.is_shown()

    def test_failed_run_does_not_enable_sticky_autorun(self, primed, qtbot):
        """A failed manual run must not enable sticky auto-run."""
        code_widget, patch, received = primed
        patch2 = patch.update(data=patch.data + 3)

        code_widget._editor.setPlainText(
            "def transform(patch):\n    raise ValueError('x')"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)
        assert received[-1] is None
        assert code_widget._autorun_enabled is False
        received.clear()

        code_widget.set_patch(patch2)
        wait_for_output(qtbot, received)
        assert received[-1] is None
        assert code_widget._autorun_enabled is False

    def test_before_first_run_input_change_does_not_execute(
        self, code_widget, monkeypatch, qtbot
    ):
        """Input changes stay passive until the user has run successfully once."""
        received = capture_output(code_widget.Outputs.result, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        code_widget._editor.setPlainText("def transform(patch):\n    return patch")
        received.clear()

        code_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget._autorun_enabled is False

    def test_successful_run_enables_sticky_autorun(self, primed, qtbot):
        """After a successful run, later patch changes re-run automatically."""
        code_widget, patch, received = primed
        patch2 = patch.update(data=patch.data + 1)

        code_widget._editor.setPlainText("def transform(patch):\n    return patch")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)
        received.clear()

        code_widget.set_patch(patch2)
        wait_for_output(qtbot, received)

        assert received[-1] is patch2
        assert code_widget._autorun_enabled is True

    def test_failed_autorun_after_success_emits_none_and_keeps_autorun_on(
        self, primed, qtbot
    ):
        """A later auto-run failure emits None without silently clearing sticky mode."""
        code_widget, patch, received = primed
        patch2 = patch.update(data=patch.data + 4)

        code_widget._editor.setPlainText(
            "def transform(patch):\n"
            "    if patch is not None and np.mean(patch.data) > 0:\n"
            "        raise ValueError('auto-fail')\n"
            "    return patch"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)
        assert received[-1] is patch
        received.clear()

        code_widget.set_patch(patch2)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget.Error.execution_failed.is_shown()
        assert code_widget._autorun_enabled is True

    def test_editing_script_disables_sticky_autorun(self, primed, qtbot):
        """Editing the script disables auto-run until Run is pressed again."""
        code_widget, patch, received = primed
        patch2 = patch.update(data=patch.data + 2)

        code_widget._editor.setPlainText("def transform(patch):\n    return patch")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)
        received.clear()

        code_widget._editor.setPlainText(
            "def transform(patch):\n    return patch.detrend('time', 'linear')"
        )
        wait_for_output(qtbot, received)
        assert received[-1] is None
        received.clear()

        code_widget.set_patch(patch2)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget._autorun_enabled is False

    def test_missing_transform_function_shows_error(self, primed, qtbot):
        """Scripts must define a callable transform function."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText("x = 1")
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget.Error.execution_failed.is_shown()

    def test_unsupported_required_inputs_show_error(self, primed, qtbot):
        """Scripts may not require extra inputs beyond the widget patch input."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch, scale):\n" "    return scale"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert code_widget.Error.execution_failed.is_shown()
        assert "unsupported required inputs" in code_widget._log.toPlainText()

    def test_dc_and_np_are_available_in_namespace(self, primed, qtbot):
        """The script namespace exposes dascore and numpy helpers."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch):\n"
            "    assert dc is not None\n"
            "    return np.asarray(patch.data)"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert isinstance(received[-1], np.ndarray)

    def test_builtins_are_available_in_namespace(self, primed, qtbot):
        """Normal Python builtins are available to scripts."""
        code_widget, patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch):\n" "    return len(patch.dims)"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        assert received[-1] == len(patch.dims)

    def test_log_replaced_after_successful_rerun(self, primed, qtbot):
        """A successful rerun replaces old traceback text in the visible log."""
        code_widget, _patch, received = primed

        code_widget._editor.setPlainText(
            "def transform(patch):\n    raise ValueError('boom')"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)
        assert "ValueError" in code_widget._log.toPlainText()
        received.clear()

        code_widget._editor.setPlainText(
            "def transform(patch):\n" "    print('ok')\n" "    return patch"
        )
        code_widget._run_button.click()
        wait_for_output(qtbot, received)

        log_text = code_widget._log.toPlainText()
        assert "ok" in log_text
        assert "ValueError" not in log_text

    def test_stored_settings_restore_script_text(self):
        """Stored settings should restore the saved editor contents."""
        saved = {"script_text": "def transform(patch):\n    return 5"}

        with widget_context(Code, stored_settings=saved) as widget:
            assert "return 5" in widget._editor.toPlainText()

    def test_output_summary_uses_string_representation(self, code_widget, monkeypatch):
        """Result summaries should use str(obj) for arbitrary outputs."""

        class _OnlyString:
            def __repr__(self):
                raise RuntimeError("repr should not be used")

            def __str__(self):
                return "result-string"

        summaries: list[tuple[str, PartialSummary]] = []

        def _capture(name, partial_summary, **_kwargs):
            summaries.append((name, partial_summary))

        monkeypatch.setattr(code_widget, "set_partial_output_summary", _capture)

        code_widget._on_result(_OnlyString())

        assert summaries
        name, summary = summaries[-1]
        assert name == "Result"
        assert summary.summary == "_OnlyString"
        assert "result-string" in summary.details

    def test_output_summary_for_patch_result(self, code_widget, monkeypatch):
        """Patch outputs should still produce a summary without errors."""
        patch = dc.get_example_patch("example_event_1")
        summaries: list[tuple[str, PartialSummary]] = []

        def _capture(name, partial_summary, **_kwargs):
            summaries.append((name, partial_summary))

        monkeypatch.setattr(code_widget, "set_partial_output_summary", _capture)

        code_widget._on_result(patch)

        assert summaries
        name, summary = summaries[-1]
        assert name == "Result"
        assert summary.summary == "Patch"
        assert "Patch" in summary.details


class TestCodeDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for Code."""

    __test__ = True
    widget = Code
