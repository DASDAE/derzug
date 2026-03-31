"""Orange widget for DASCore patch normalization norms."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


class Norm(PatchDimWidget):
    """Apply DASCore patch.normalize with one selected norm."""

    name = "Norm"
    description = "Apply DASCore normalization norms to a patch"
    icon = "icons/Normalize.svg"
    category = "Processing"
    keywords = ("norm", "normalize", "scale", "amplitude")
    priority = 21.4
    want_main_area = False

    selected_dim = Setting("")
    norm = Setting("l2")

    _NORMS: ClassVar[tuple[str, ...]] = ("l1", "l2", "max", "bit")

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("Norm operation failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        gui.widgetLabel(box, "Norm:")
        self._norm_combo = QComboBox(box)
        self._norm_combo.addItems(self._NORMS)
        if self.norm not in self._NORMS:
            self.norm = self._NORMS[1]
        self._norm_combo.setCurrentText(self.norm)
        box.layout().addWidget(self._norm_combo)

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._norm_combo.currentTextChanged.connect(self._on_norm_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the selected norm."""
        self._set_patch_input(patch)
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_norm_changed(self, value: str) -> None:
        """Persist selected norm and rerun."""
        self.norm = value
        self.run()

    def _coerce_norm(self) -> str:
        """Return the selected norm or reset to the default."""
        if self.norm in self._NORMS:
            return self.norm
        self.norm = self._NORMS[1]
        self._norm_combo.blockSignals(True)
        self._norm_combo.setCurrentText(self.norm)
        self._norm_combo.blockSignals(False)
        return self.norm

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the norm-specific banner."""
        self._show_exception("operation_failed", exc)

    def get_task(self) -> Task:
        """Return the current norm operation as a workflow task."""
        return PatchConfiguredMethodTask(
            method_name="normalize",
            call_style="positional_dim",
            dim=self._get_dim() or self.selected_dim,
            method_kwargs={"norm": self._coerce_norm()},
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Norm).run()
