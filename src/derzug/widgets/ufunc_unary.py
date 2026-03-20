"""Orange widget for applying unary math transforms to a patch."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting


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

    def _run(self) -> dc.Patch | None:
        """Apply the selected unary transform and return the output patch."""
        if self._patch is None:
            return None
        op = self._coerce_op()
        try:
            return self._OPS[op](self._patch)
        except Exception as exc:
            self._show_exception("operation_failed", exc, op)
            return None

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the output patch."""
        self.Outputs.patch.send(result)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(UFunc).run()
