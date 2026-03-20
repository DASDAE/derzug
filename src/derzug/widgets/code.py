"""Custom Python code widget for patch-focused workflows."""

from __future__ import annotations

import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from html import escape

import dascore as dc
import numpy as np
from AnyQt.QtCore import Qt, QTimer
from AnyQt.QtGui import QFont, QShowEvent
from AnyQt.QtWidgets import (
    QApplication,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets.data.utils.pythoneditor.editor import PythonEditor
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg
from orangewidget.utils.signals import PartialSummary

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting
from derzug.utils.code2widget import (
    INPUTS_NOT_READY,
    invoke_schema_function,
    schema_from_function,
)

DEFAULT_SCRIPT = """def transform(patch):
    \"\"\"Return the value to emit from this widget.\"\"\"
    return patch
"""


class Code(ZugWidget):
    """Run custom Python code against an input patch."""

    name = "Code"
    description = "Run custom Python code on a patch"
    icon = "icons/PythonScript.svg"
    category = "Processing"
    keywords = ("code", "python", "script", "custom")
    priority = 21.7
    want_main_area = True

    script_text = Setting(DEFAULT_SCRIPT)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        execution_failed = Msg("Code execution failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        result = Output("Result", object, auto_summary=False)

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._autorun_enabled = False
        self._last_run_succeeded = False

        controls = QWidget(self.controlArea)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        self.controlArea.layout().addWidget(controls)
        self._run_button = QPushButton("Run", controls)
        self._status_label = QLabel("Idle", controls)
        self._status_label.setWordWrap(True)
        controls_layout.addWidget(self._run_button)
        controls_layout.addWidget(self._status_label)
        controls_layout.addStretch(1)

        container = QWidget(self.mainArea)
        self.mainArea.layout().addWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._splitter = QSplitter(Qt.Vertical, container)
        layout.addWidget(self._splitter, 1)

        self._editor = PythonEditor(self._splitter)
        self._editor.setPlaceholderText("Write Python here")
        self._editor.setPlainText(self.script_text)
        self._editor.setFocusPolicy(Qt.ClickFocus)
        self._editor.auto_invoke_completions = True
        self._editor.dot_invoke_completions = True
        editor_font = self._default_editor_font()
        self._editor.setFont(editor_font)
        self._editor.setup_completer_appearance((320, 180), editor_font)

        self._log = QPlainTextEdit(self._splitter)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Execution output")
        self._log.setFocusPolicy(Qt.ClickFocus)

        self._splitter.addWidget(self._editor)
        self._splitter.addWidget(self._log)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([480, 180])

        self._run_button.clicked.connect(self._on_run_clicked)
        self._editor.textChanged.connect(self._on_editor_text_changed)

    @staticmethod
    def _default_editor_font() -> QFont:
        """Return a readable monospace font for the code editor."""
        family = (
            "Menlo"
            if QApplication.instance() is not None and sys.platform == "darwin"
            else "Courier"
            if sys.platform in {"win32", "cygwin"}
            else "DejaVu Sans Mono"
        )
        font = QFont(family)
        font.setPointSize(13)
        return font

    def showEvent(self, event: QShowEvent) -> None:
        """Prefer the Run button as the initial focus target when shown."""
        super().showEvent(event)
        QTimer.singleShot(0, self._run_button.setFocus)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and optionally rerun the current script."""
        self._patch = patch
        if self._autorun_enabled:
            self._status_label.setText("Auto-running")
            self.run()
            label = (
                "Auto-run complete" if self._last_run_succeeded else "Auto-run failed"
            )
            self._status_label.setText(label)
            return
        self._status_label.setText("Ready; press Run")
        self._clear_result()

    def _on_run_clicked(self) -> None:
        """Execute the current script and enable sticky auto-run on success."""
        self._status_label.setText("Running")
        self.run()
        if self._last_run_succeeded:
            self._autorun_enabled = True
            self._status_label.setText("Auto-run enabled")
        else:
            self._status_label.setText("Run failed")

    def _on_editor_text_changed(self) -> None:
        """Persist editor text and disable sticky auto-run after user edits."""
        self.script_text = self._editor.toPlainText()
        self._autorun_enabled = False
        self._status_label.setText("Edited; press Run")
        self._clear_result()

    def _run(self):
        """Execute user code and return the `transform` result."""
        self._last_run_succeeded = False

        output_buffer = io.StringIO()

        try:
            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                transform = self._extract_transform()
                schema = schema_from_function(transform)
                if self._has_unsupported_required_inputs(schema):
                    raise ValueError(
                        "script transform has unsupported required inputs; "
                        "only `patch` may be required"
                    )
                result = invoke_schema_function(
                    schema,
                    transform,
                    {"patch": self._patch},
                )
                if result is None and self._patch is None:
                    result = None
        except Exception as exc:
            self._set_log_text(output_buffer.getvalue(), traceback.format_exc())
            self._show_exception("execution_failed", exc)
            return None

        if result is INPUTS_NOT_READY:
            self._set_log_text(output_buffer.getvalue())
            return None

        self._set_log_text(output_buffer.getvalue())
        self._last_run_succeeded = True
        return result

    def _extract_transform(self):
        """Compile the script text and return the callable `transform`."""
        namespace: dict[str, object] = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "dc": dc,
            "np": np,
        }
        code = compile(self.script_text, "<derzug-code>", "exec")
        exec(code, namespace, namespace)
        transform = namespace.get("transform")
        if not callable(transform):
            raise ValueError("script must define a callable `transform(patch)`")
        return transform

    @staticmethod
    def _has_unsupported_required_inputs(schema) -> bool:
        """Return True when required inputs other than patch are declared."""
        for input_spec in schema.inputs:
            if input_spec.signal_name == "patch":
                continue
            if not input_spec.has_default:
                return True
        return False

    def _set_log_text(self, stream_text: str, traceback_text: str = "") -> None:
        """Render stdout/stderr and optional traceback in the log pane."""
        parts = [
            part.rstrip() for part in (stream_text, traceback_text) if part.strip()
        ]
        self._log.setPlainText("\n\n".join(parts))

    def _clear_result(self) -> None:
        """Emit None and clear the result summary."""
        self._set_output_object_summary("Result", None)
        self.Outputs.result.send(None)

    def _on_result(self, result) -> None:
        """Send result on output and update output summary."""
        self._set_output_object_summary("Result", result)
        self.Outputs.result.send(result)

    def _set_output_object_summary(self, name: str, value: object) -> None:
        """Update one output summary using the object's string form."""
        if name not in self.output_summaries:
            self.output_summaries[name] = {}
        self.set_partial_output_summary(name, self._summary_for_object(value))

    @staticmethod
    def _summary_for_object(value: object) -> PartialSummary:
        """Build a warning-free signal summary using str(value)."""
        if value is None:
            return PartialSummary()
        label = type(value).__name__
        details = (
            "<pre style='margin:0; white-space:pre-wrap'>"
            f"{escape(Code._safe_string(value))}</pre>"
        )
        return PartialSummary(summary=label, details=details)

    @staticmethod
    def _safe_string(value: object) -> str:
        """Return str(value) with a defensive fallback."""
        try:
            return str(value)
        except Exception:
            return f"<{type(value).__name__}>"


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Code).run()
