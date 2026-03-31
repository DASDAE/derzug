"""Orange widget for DASCore analytic-signal transforms."""

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


class Analytic(PatchDimWidget):
    """Apply Hilbert-derived transforms to an input patch."""

    name = "Analytic"
    description = "Apply Hilbert-derived transforms to a patch"
    icon = "icons/Analytic.svg"
    category = "Transform"
    keywords = ("transform", "hilbert", "envelope", "analytic")
    priority = 21.2
    want_main_area = False

    transform = Setting("hilbert")
    selected_dim = Setting("")

    _TRANSFORMS: ClassVar[tuple[str, ...]] = ("hilbert", "envelope")

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        transform_failed = Msg("Analytic transform failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Transform:")
        self._transform_combo = QComboBox(box)
        self._transform_combo.addItems(self._TRANSFORMS)
        box.layout().addWidget(self._transform_combo)

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        if self.transform not in self._TRANSFORMS:
            self.transform = self._TRANSFORMS[0]
        self._transform_combo.setCurrentText(self.transform)

        self._transform_combo.currentTextChanged.connect(self._on_transform_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the selected transform."""
        self._set_patch_input(patch)
        self.run()

    def _on_transform_changed(self, value: str) -> None:
        """Persist selected transform and rerun."""
        self.transform = value
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the transform-specific banner."""
        self._show_exception("transform_failed", exc)

    def _coerce_transform(self) -> str:
        """Return the selected transform or reset to the default."""
        if self.transform in self._TRANSFORMS:
            return self.transform
        self.transform = self._TRANSFORMS[0]
        self._transform_combo.blockSignals(True)
        self._transform_combo.setCurrentText(self.transform)
        self._transform_combo.blockSignals(False)
        return self.transform

    def get_task(self) -> Task:
        """Return the current analytic transform as a workflow task."""
        return PatchConfiguredMethodTask(
            method_name=self._coerce_transform(),
            call_style="positional_dim",
            dim=self._get_dim() or self.selected_dim,
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Analytic).run()
