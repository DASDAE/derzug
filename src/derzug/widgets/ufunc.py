"""Orange widget for applying binary NumPy ufunc operations to two inputs."""

from __future__ import annotations

from html import escape
from typing import ClassVar

import dascore as dc
import numpy as np
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg
from orangewidget.utils.signals import PartialSummary

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.orange import Setting
from derzug.workflow import Task


class UFuncOperatorTask(Task):
    """Task wrapper around one selected binary NumPy ufunc."""

    selected_op: str
    input_variables: ClassVar[dict[str, object]] = {"x": object, "y": object}
    output_variables: ClassVar[dict[str, object]] = {"result": object}

    def run(self, x, y):
        """Apply the selected NumPy ufunc to both inputs."""
        ufunc = UFuncOperator._OP_LABEL_TO_UFUNC.get(self.selected_op)
        if ufunc is None:
            ufunc = UFuncOperator._OP_LABEL_TO_UFUNC[
                next(iter(UFuncOperator._OP_LABEL_TO_UFUNC))
            ]
        return ufunc(x, y)


class UFuncOperator(ZugWidget):
    """Apply a selected binary NumPy ufunc to two generic inputs."""

    name = "UfuncBinary"
    description = "Apply selected NumPy ufunc to x and y inputs"
    icon = "icons/UFunc.svg"
    category = "Processing"
    keywords = ("ufunc", "numpy", "binary", "operator", "math")
    priority = 23

    selected_op = Setting("x+y")

    # This is a non-graphical widget; we dont need main area.
    want_main_area = False

    _OP_LABEL_TO_UFUNC: ClassVar[dict[str, np.ufunc]] = {
        "x+y": np.add,
        "x-y": np.subtract,
        "x*y": np.multiply,
        "x/y": np.divide,
        "x**y": np.power,
        "x%y": np.remainder,
        "maximum(x,y)": np.maximum,
        "minimum(x,y)": np.minimum,
        "x>y": np.greater,
        "x<y": np.less,
        "x==y": np.equal,
        "x!=y": np.not_equal,
        "x>=y": np.greater_equal,
        "x<=y": np.less_equal,
    }
    _UNSET: ClassVar[object] = object()

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("UFunc operation '{}' failed: {}")
        invalid_spool = Msg("Spool input for '{}' must contain exactly one patch")

    class Inputs:
        """Input signal definitions."""

        x = Input("x", object, auto_summary=False)
        y = Input("y", object, auto_summary=False)

    class Outputs:
        """Output signal definitions."""

        result = Output("Result", object, auto_summary=False)

    def __init__(self) -> None:
        super().__init__()
        self._x: object = self._UNSET
        self._y: object = self._UNSET

        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Operation:")
        self._op_combo = QComboBox(box)
        self._op_combo.addItems(self._OP_LABEL_TO_UFUNC.keys())
        box.layout().addWidget(self._op_combo)
        if self.selected_op in self._OP_LABEL_TO_UFUNC:
            self._op_combo.setCurrentText(self.selected_op)
        else:
            self.selected_op = next(iter(self._OP_LABEL_TO_UFUNC))
            self._op_combo.setCurrentText(self.selected_op)
        self._op_combo.currentTextChanged.connect(self._on_op_changed)

    @Inputs.x
    def set_x(self, value: object | None) -> None:
        """Receive x input and recompute output."""
        self._x = self._UNSET if value is None else value
        self._set_input_object_summary("x", self._x)
        self.run()

    @Inputs.y
    def set_y(self, value: object | None) -> None:
        """Receive y input and recompute output."""
        self._y = self._UNSET if value is None else value
        self._set_input_object_summary("y", self._y)
        self.run()

    def _on_op_changed(self, label: str) -> None:
        """Persist selected operation label and recompute."""
        self.selected_op = label
        self.run()

    def _supports_async_execution(self) -> bool:
        """Run binary ufuncs off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one binary-ufunc execution request."""
        resolved = self._validated_execution_inputs()
        if resolved is None:
            return None
        workflow_obj, x, y = resolved
        return self._build_task_execution_request(
            workflow_obj,
            input_values={"x": x, "y": y},
            output_names=("result",),
        )

    def _validated_execution_inputs(self) -> tuple[Task, object, object] | None:
        """Return the current task and normalized operands, or None."""
        if self._x is self._UNSET or self._y is self._UNSET:
            return None
        x = self._resolve_operand(self._x, "x")
        if x is self._UNSET:
            return None
        y = self._resolve_operand(self._y, "y")
        if y is self._UNSET:
            return None
        return self.get_task(), x, y

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the operation-specific banner."""
        self._show_exception("operation_failed", exc, self.selected_op)

    def _run(self):
        """Compute selected binary ufunc result, or None if input missing."""
        resolved = self._validated_execution_inputs()
        if resolved is None:
            return None
        workflow_obj, x, y = resolved
        return self._execute_workflow_object(
            workflow_obj,
            input_values={"x": x, "y": y},
            output_names=("result",),
        )

    def get_task(self) -> Task:
        """Return the configured binary ufunc task."""
        self._get_selected_ufunc()
        return UFuncOperatorTask(selected_op=self.selected_op)

    def _resolve_operand(self, value: object, label: str) -> object:
        """Unwrap length-1 spools to patches and reject unsupported spool inputs."""
        if not isinstance(value, dc.BaseSpool):
            return value
        patch = self._extract_single_patch(value)
        if patch is not None:
            return patch
        self._show_error_message("invalid_spool", label)
        return self._UNSET

    @staticmethod
    def _extract_single_patch(spool: dc.BaseSpool) -> dc.Patch | None:
        """Return the only patch in spool, or None when length is not exactly one."""
        iterator = iter(spool)
        try:
            first = next(iterator)
        except StopIteration:
            return None
        try:
            next(iterator)
        except StopIteration:
            return first
        return None

    def _get_selected_ufunc(self) -> np.ufunc:
        """Return selected ufunc, coercing unknown settings back to default once."""
        ufunc = self._OP_LABEL_TO_UFUNC.get(self.selected_op)
        if ufunc is not None:
            return ufunc

        default_op = next(iter(self._OP_LABEL_TO_UFUNC))
        self.selected_op = default_op
        self._op_combo.blockSignals(True)
        self._op_combo.setCurrentText(default_op)
        self._op_combo.blockSignals(False)
        return self._OP_LABEL_TO_UFUNC[default_op]

    def _on_result(self, result) -> None:
        """Send operation result on output."""
        self._set_output_object_summary("Result", result)
        self.Outputs.result.send(result)

    def _set_input_object_summary(self, name: str, value: object) -> None:
        """Update one input summary using the object's string form."""
        self.input_summaries.setdefault(name, {})
        self.set_partial_input_summary(name, self._summary_for_object(value))

    def _set_output_object_summary(self, name: str, value: object) -> None:
        """Update one output summary using the object's string form."""
        self.output_summaries.setdefault(name, {})
        self.set_partial_output_summary(name, self._summary_for_object(value))

    @staticmethod
    def _summary_for_object(value: object) -> PartialSummary:
        """Build a warning-free signal summary using str(value)."""
        if value is None or value is UFuncOperator._UNSET:
            return PartialSummary()
        label = type(value).__name__
        details = (
            "<pre style='margin:0; white-space:pre-wrap'>"
            f"{escape(UFuncOperator._safe_string(value))}</pre>"
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

    WidgetPreview(UFuncOperator).run()
