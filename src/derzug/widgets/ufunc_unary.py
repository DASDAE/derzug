"""Orange widget for applying unary math transforms to a patch."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.orange import Setting
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


class UFunc(ZugWidget):
    """Apply a selected unary element-wise math transform to an input patch."""

    name = "UFunc"
    description = "Apply a unary element-wise transform to a patch"
    icon = "icons/UFunc.svg"
    category = "Processing"
    keywords = ("ufunc", "math", "unary", "abs", "log", "exp", "transform")
    priority = 22
    want_main_area = False

    selected_op = Setting("abs")

    _OPS: ClassVar[dict[str, Callable]] = {
        "abs": lambda p: p.abs(),
        "real": lambda p: p.real(),
        "imag": lambda p: p.imag(),
        "conj": lambda p: p.conj(),
        "angle": lambda p: p.angle(),
        "exp": lambda p: p.exp(),
        "log": lambda p: p.log(),
        "log10": lambda p: p.log10(),
        "log2": lambda p: p.log2(),
    }

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("UFunc operation '{}' failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None

        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Operation:")
        self._op_combo = QComboBox(box)
        self._op_combo.addItems(self._OPS.keys())
        box.layout().addWidget(self._op_combo)

        if self.selected_op not in self._OPS:
            self.selected_op = next(iter(self._OPS))
        self._op_combo.setCurrentText(self.selected_op)
        self._op_combo.currentTextChanged.connect(self._on_op_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and apply the selected transform."""
        self._patch = patch
        self.run()

    def _on_op_changed(self, value: str) -> None:
        """Persist selected operation and rerun."""
        self.selected_op = value
        self.run()

    def _coerce_op(self) -> str:
        """Return the selected operation or reset to the default."""
        if self.selected_op in self._OPS:
            return self.selected_op
        default = next(iter(self._OPS))
        self.selected_op = default
        self._op_combo.blockSignals(True)
        self._op_combo.setCurrentText(default)
        self._op_combo.blockSignals(False)
        return default

    def _supports_async_execution(self) -> bool:
        """Run unary ufunc transforms off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one unary-ufunc execution request."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _validated_task(self) -> Task | None:
        """Return the current unary patch operation after UI normalization."""
        return PatchConfiguredMethodTask(method_name=self._coerce_op())

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the selected-operation banner."""
        self._show_exception("operation_failed", exc, self._coerce_op())

    def _run(self) -> dc.Patch | None:
        """Apply the selected unary transform and return the output patch."""
        patch = self._patch
        if patch is None:
            return None
        return self._execute_workflow_object(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the output patch."""
        self.Outputs.patch.send(result)

    def get_task(self) -> Task:
        """Return the current unary patch operation as a workflow task."""
        workflow_obj = self._validated_task()
        if workflow_obj is None:
            raise ValueError("current UFunc state is not valid")
        return workflow_obj


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(UFunc).run()
