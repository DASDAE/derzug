"""Orange widget for applying DASCore taper to patches."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QDoubleSpinBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


class Taper(PatchDimWidget):
    """Apply a taper window to a patch along a selected dimension."""

    name = "Taper"
    description = "Apply a taper window to a patch along a selected dimension"
    icon = "icons/Taper.svg"
    category = "Processing"
    keywords = ("taper", "window", "hann", "pre-fft", "cosine")
    priority = 21.4
    want_main_area = False

    selected_dim = Setting("")
    p = Setting(0.05)
    window_type = Setting("hann")

    _WINDOW_TYPES: ClassVar[tuple[str, ...]] = (
        "hann",
        "hamming",
        "blackman",
        "nuttall",
    )

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        taper_failed = Msg("Taper failed: {}")

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

        gui.widgetLabel(box, "Taper fraction (p):")
        self._p_spin = QDoubleSpinBox(box)
        self._p_spin.setDecimals(3)
        self._p_spin.setRange(0.0, 0.4)
        self._p_spin.setSingleStep(0.01)
        self._p_spin.setValue(float(self.p))
        box.layout().addWidget(self._p_spin)

        gui.widgetLabel(box, "Window type:")
        self._window_combo = QComboBox(box)
        self._window_combo.addItems(self._WINDOW_TYPES)
        box.layout().addWidget(self._window_combo)

        if self.window_type not in self._WINDOW_TYPES:
            self.window_type = self._WINDOW_TYPES[0]
        self._window_combo.setCurrentText(self.window_type)

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._p_spin.valueChanged.connect(self._on_p_changed)
        self._window_combo.currentTextChanged.connect(self._on_window_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the taper."""
        self._set_patch_input(patch)
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_p_changed(self, value: float) -> None:
        """Persist taper fraction and rerun."""
        self.p = value
        self.run()

    def _on_window_changed(self, value: str) -> None:
        """Persist selected window type and rerun."""
        self.window_type = value
        self.run()

    def _coerce_window_type(self) -> str:
        """Return the selected window type or reset to the default."""
        if self.window_type in self._WINDOW_TYPES:
            return self.window_type
        default = self._WINDOW_TYPES[0]
        self.window_type = default
        self._window_combo.blockSignals(True)
        self._window_combo.setCurrentText(default)
        self._window_combo.blockSignals(False)
        return default

    def _coerce_p(self) -> float:
        """Return the taper fraction clamped to [0.0, 0.5]."""
        val = float(self.p)
        clamped = max(0.0, min(0.4, val))
        if clamped != val:
            self.p = clamped
            self._p_spin.blockSignals(True)
            self._p_spin.setValue(clamped)
            self._p_spin.blockSignals(False)
        return clamped

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the taper-specific banner."""
        self._show_exception("taper_failed", exc)

    def get_task(self) -> Task:
        """Return the current taper operation as a workflow task."""
        return PatchConfiguredMethodTask(
            method_name="taper",
            call_style="keyword_dim",
            dim=self._get_dim() or self.selected_dim,
            dim_value=self._coerce_p(),
            method_kwargs={"window_type": self._coerce_window_type()},
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Taper).run()
