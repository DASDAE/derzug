"""Orange widget for DASCore calculus-style transforms."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QSpinBox, QStackedWidget, QVBoxLayout, QWidget
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting


class Calculus(PatchDimWidget):
    """Apply differentiation and integration transforms to an input patch."""

    name = "Calculus"
    description = "Apply differentiation and integration transforms to a patch"
    icon = "icons/Calculus.svg"
    category = "Transform"
    keywords = ("transform", "differentiate", "integrate", "derivative", "integral")
    priority = 21.3
    want_main_area = False

    transform = Setting("differentiate")
    selected_dim = Setting("")
    order = Setting(2)
    step = Setting(1)
    definite = Setting(False)

    _TRANSFORMS: ClassVar[tuple[str, ...]] = ("differentiate", "integrate")

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        transform_failed = Msg("Calculus transform failed: {}")

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

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)
        self._stack.addWidget(self._build_differentiate_page())
        self._stack.addWidget(self._build_integrate_page())

        if self.transform not in self._TRANSFORMS:
            self.transform = self._TRANSFORMS[0]
        self._transform_combo.setCurrentText(self.transform)
        self._stack.setCurrentIndex(self._TRANSFORMS.index(self.transform))

        self._transform_combo.currentTextChanged.connect(self._on_transform_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    def _build_differentiate_page(self) -> QWidget:
        """Return the parameter page for differentiation."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        gui.widgetLabel(page, "Order:")
        self._order_spin = QSpinBox(page)
        self._order_spin.setRange(1, 8)
        self._order_spin.setValue(int(self.order))
        self._order_spin.valueChanged.connect(self._on_order_changed)
        layout.addWidget(self._order_spin)

        gui.widgetLabel(page, "Step:")
        self._step_spin = QSpinBox(page)
        self._step_spin.setRange(1, 64)
        self._step_spin.setValue(int(self.step))
        self._step_spin.valueChanged.connect(self._on_step_changed)
        layout.addWidget(self._step_spin)

        layout.addStretch(1)
        return page

    def _build_integrate_page(self) -> QWidget:
        """Return the parameter page for integration."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.checkBox(
            page,
            self,
            "definite",
            label="Definite integral",
            callback=self.run,
        )
        layout.addStretch(1)
        return page

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the selected transform."""
        self._set_patch_input(patch)
        self.run()

    def _on_transform_changed(self, value: str) -> None:
        """Persist selected transform and rerun."""
        self.transform = value
        self._stack.setCurrentIndex(self._TRANSFORMS.index(value))
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_order_changed(self, value: int) -> None:
        """Persist differentiation order and rerun."""
        self.order = int(value)
        self.run()

    def _on_step_changed(self, value: int) -> None:
        """Persist differentiation step and rerun."""
        self.step = int(value)
        self.run()

    def _coerce_transform(self) -> str:
        """Return the selected transform or reset to the default."""
        if self.transform in self._TRANSFORMS:
            return self.transform
        self.transform = self._TRANSFORMS[0]
        self._transform_combo.blockSignals(True)
        self._transform_combo.setCurrentText(self.transform)
        self._transform_combo.blockSignals(False)
        self._stack.setCurrentIndex(0)
        return self.transform

    def _run(self) -> dc.Patch | None:
        """Apply the selected calculus transform and return the output patch."""
        if self._patch is None:
            return None

        dim = self._get_dim()
        if dim is None:
            return None

        transform = self._coerce_transform()
        try:
            if transform == "differentiate":
                return self._patch.differentiate(
                    dim,
                    order=int(self.order),
                    step=int(self.step),
                )
            return self._patch.integrate(dim, definite=bool(self.definite))
        except Exception as exc:
            self._show_exception("transform_failed", exc)
            return None


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Calculus).run()
