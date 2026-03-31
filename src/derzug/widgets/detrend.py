"""Orange widget for applying DASCore detrend to patches."""

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


class Detrend(PatchDimWidget):
    """Apply DASCore detrending to an input patch."""

    name = "Detrend"
    description = "Apply DASCore detrending to a patch"
    icon = "icons/Detrend.svg"
    category = "Processing"
    keywords = ("detrend", "trend", "linear", "constant")
    priority = 21
    want_main_area = False

    selected_dim = Setting("")
    detrend_type = Setting("linear")

    _TYPES: ClassVar[tuple[str, ...]] = ("linear", "constant")

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        detrend_failed = Msg("Detrend failed: {}")

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

        gui.widgetLabel(box, "Type:")
        self._type_combo = QComboBox(box)
        self._type_combo.addItems(self._TYPES)
        box.layout().addWidget(self._type_combo)

        if self.detrend_type not in self._TYPES:
            self.detrend_type = self._TYPES[0]
        self._type_combo.setCurrentText(self.detrend_type)

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run detrending."""
        self._set_patch_input(patch)
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_type_changed(self, value: str) -> None:
        """Persist selected detrend type and rerun."""
        self.detrend_type = value
        self.run()

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the detrend-specific banner."""
        self._show_exception("detrend_failed", exc)

    def _coerce_detrend_type(self) -> str:
        """Return a supported detrend type and normalize widget state."""
        detrend_type = (
            self.detrend_type if self.detrend_type in self._TYPES else self._TYPES[0]
        )
        if detrend_type != self.detrend_type:
            self.detrend_type = detrend_type
            self._type_combo.blockSignals(True)
            self._type_combo.setCurrentText(detrend_type)
            self._type_combo.blockSignals(False)
        return detrend_type

    def get_task(self) -> Task:
        """Return the current detrend operation as a workflow task."""
        return PatchConfiguredMethodTask(
            method_name="detrend",
            call_style="positional_dim",
            dim=self._get_dim() or self.selected_dim,
            method_args=(self._coerce_detrend_type(),),
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Detrend).run()
