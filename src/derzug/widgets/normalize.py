"""Orange widget for DASCore normalize and standardize operations."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QLabel, QStackedWidget, QVBoxLayout, QWidget
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting


class Normalize(PatchDimWidget):
    """Apply DASCore normalize and standardize operations to a patch."""

    name = "Normalize"
    description = "Apply DASCore normalize or standardize to a patch"
    icon = "icons/Normalize.svg"
    category = "Processing"
    keywords = ("normalize", "standardize", "scale", "amplitude")
    priority = 21.5
    want_main_area = False

    operation = Setting("normalize")
    selected_dim = Setting("")
    norm = Setting("l2")

    _OPERATIONS: ClassVar[tuple[str, ...]] = ("normalize", "standardize")
    _NORMS: ClassVar[tuple[str, ...]] = ("l1", "l2", "max", "bit")

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("Normalize operation failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Operation:")
        self._operation_combo = QComboBox(box)
        self._operation_combo.addItems(self._OPERATIONS)
        box.layout().addWidget(self._operation_combo)

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)
        self._stack.addWidget(self._build_normalize_page())
        self._stack.addWidget(self._build_standardize_page())

        if self.operation not in self._OPERATIONS:
            self.operation = self._OPERATIONS[0]
        self._operation_combo.setCurrentText(self.operation)
        self._stack.setCurrentIndex(self._OPERATIONS.index(self.operation))

        self._operation_combo.currentTextChanged.connect(self._on_operation_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    def _build_normalize_page(self) -> QWidget:
        """Return the parameter page for normalize."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Norm:", page))
        self._norm_combo = QComboBox(page)
        self._norm_combo.addItems(self._NORMS)
        if self.norm not in self._NORMS:
            self.norm = self._NORMS[1]
        self._norm_combo.setCurrentText(self.norm)
        self._norm_combo.currentTextChanged.connect(self._on_norm_changed)
        layout.addWidget(self._norm_combo)
        layout.addStretch(1)
        return page

    @staticmethod
    def _build_standardize_page() -> QWidget:
        """Return the parameter page for standardize."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Standardize uses the selected dimension.", page))
        layout.addStretch(1)
        return page

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the selected operation."""
        self._set_patch_input(patch)
        self.run()

    def _on_operation_changed(self, value: str) -> None:
        """Persist selected operation and rerun."""
        self.operation = value
        self._stack.setCurrentIndex(self._OPERATIONS.index(value))
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_norm_changed(self, value: str) -> None:
        """Persist selected normalize norm and rerun."""
        self.norm = value
        self.run()

    def _coerce_operation(self) -> str:
        """Return the selected operation or reset to the default."""
        if self.operation in self._OPERATIONS:
            return self.operation
        self.operation = self._OPERATIONS[0]
        self._operation_combo.blockSignals(True)
        self._operation_combo.setCurrentText(self.operation)
        self._operation_combo.blockSignals(False)
        self._stack.setCurrentIndex(0)
        return self.operation

    def _coerce_norm(self) -> str:
        """Return the selected norm or reset to the default."""
        if self.norm in self._NORMS:
            return self.norm
        self.norm = self._NORMS[1]
        self._norm_combo.blockSignals(True)
        self._norm_combo.setCurrentText(self.norm)
        self._norm_combo.blockSignals(False)
        return self.norm

    def _run(self) -> dc.Patch | None:
        """Apply the selected operation and return the output patch."""
        if self._patch is None:
            return None

        dim = self._get_dim()
        if dim is None:
            return None

        operation = self._coerce_operation()
        try:
            if operation == "normalize":
                return self._patch.normalize(dim, norm=self._coerce_norm())
            return self._patch.standardize(dim)
        except Exception as exc:
            self._show_exception("operation_failed", exc)
            return None


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Normalize).run()
