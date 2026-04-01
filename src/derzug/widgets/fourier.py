"""Orange widget for DASCore Fourier-domain transforms."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask

_TRANSFORMS: tuple[str, ...] = ("dft", "idft")
_REAL_OPTIONS: tuple[tuple[str, str | bool | None], ...] = (
    ("Auto", None),
    ("Real", True),
    ("Complex", False),
)
_REAL_OPTION_MAP = dict(_REAL_OPTIONS)


class Fourier(PatchDimWidget):
    """Apply DASCore Fourier transforms to an input patch."""

    name = "Fourier"
    description = "Apply DASCore Fourier transforms to a patch"
    icon = "icons/Fourier.svg"
    category = "Transform"
    keywords = ("transform", "fourier", "fft", "dft", "idft")
    priority = 21.1
    want_main_area = False

    transform = Setting("dft")
    selected_dim = Setting("")
    selected_dims = Setting([])
    real_mode = Setting("Auto")
    pad = Setting(True)

    _TRANSFORMS: ClassVar[tuple[str, ...]] = _TRANSFORMS

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        transform_failed = Msg("Fourier transform failed: {}")

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

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)
        self._stack.addWidget(self._build_dft_page())
        self._stack.addWidget(self._build_idft_page())

        if self.transform not in self._TRANSFORMS:
            self.transform = self._TRANSFORMS[0]
        self._transform_combo.setCurrentText(self.transform)
        self._stack.setCurrentIndex(self._TRANSFORMS.index(self.transform))

        self._transform_combo.currentTextChanged.connect(self._on_transform_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    def _build_dft_page(self) -> QWidget:
        """Return the parameter page for forward DFT."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Dimensions:", page))
        self._dim_list = QListWidget(page)
        layout.addWidget(self._dim_list)

        layout.addWidget(QLabel("Real output:", page))
        self._real_combo = QComboBox(page)
        self._real_combo.addItems([label for label, _ in _REAL_OPTIONS])
        if self.real_mode not in _REAL_OPTION_MAP:
            self.real_mode = "Auto"
        self._real_combo.setCurrentText(self.real_mode)
        self._real_combo.currentTextChanged.connect(self._on_real_mode_changed)
        layout.addWidget(self._real_combo)

        self._pad_checkbox = QCheckBox("Pad input", page)
        self._pad_checkbox.setChecked(bool(self.pad))
        self._pad_checkbox.toggled.connect(self._on_pad_toggled)
        layout.addWidget(self._pad_checkbox)
        layout.addStretch(1)
        self._dim_list.itemChanged.connect(self._on_dim_list_changed)
        return page

    def _build_idft_page(self) -> QWidget:
        """Return the parameter page for inverse DFT."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Dimension:", page))
        self._dim_combo = QComboBox(page)
        layout.addWidget(self._dim_combo)
        layout.addWidget(QLabel("Inverse transform the selected Fourier axis.", page))
        layout.addStretch(1)
        return page

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the selected transform."""
        self._set_patch_input(patch)
        self.run()

    def _default_dim(self, dims: tuple[str, ...]) -> str:
        """Choose a default dimension, preferring common time-domain axes."""
        if "time" in dims:
            return "time"
        ft_dims = [dim for dim in dims if dim.startswith("ft_")]
        if ft_dims:
            return ft_dims[0]
        return dims[0]

    def _on_transform_changed(self, value: str) -> None:
        """Persist selected transform and rerun."""
        self.transform = value
        self._stack.setCurrentIndex(self._TRANSFORMS.index(value))
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_dim_list_changed(self, _item: QListWidgetItem) -> None:
        """Persist selected DFT dimensions and rerun."""
        self.selected_dims = self._checked_dims()
        self.run()

    def _on_real_mode_changed(self, value: str) -> None:
        """Persist selected DFT real-mode option and rerun."""
        self.real_mode = value
        self.run()

    def _on_pad_toggled(self, value: bool) -> None:
        """Persist the DFT pad option and rerun."""
        self.pad = bool(value)
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

    def _refresh_dims(self) -> None:
        """Sync both forward- and inverse-transform dimension selectors."""
        dims = tuple(self._patch.dims) if self._patch is not None else ()
        self._available_dims = dims

        valid_selected_dims = [dim for dim in self.selected_dims if dim in dims]
        if dims and not valid_selected_dims:
            valid_selected_dims = [self._default_dim(dims)]
        self.selected_dims = valid_selected_dims

        self._dim_list.blockSignals(True)
        self._dim_list.clear()
        for dim in dims:
            item = QListWidgetItem(dim, self._dim_list)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if dim in self.selected_dims else Qt.Unchecked
            )
        self._dim_list.setEnabled(bool(dims))
        self._dim_list.blockSignals(False)

        self._dim_combo.blockSignals(True)
        self._dim_combo.clear()
        self._dim_combo.addItems(dims)
        if dims:
            if self.selected_dim not in dims:
                ft_dims = [dim for dim in dims if dim.startswith("ft_")]
                self.selected_dim = (
                    self._default_dim(tuple(ft_dims))
                    if ft_dims
                    else self._default_dim(dims)
                )
            self._dim_combo.setCurrentText(self.selected_dim)
        self._dim_combo.setEnabled(bool(dims))
        self._dim_combo.blockSignals(False)

    def _get_dims(self) -> tuple[str, ...] | None:
        """Return the selected forward-transform dimensions when available."""
        if not self._available_dims:
            return None
        dims = tuple(dim for dim in self.selected_dims if dim in self._available_dims)
        if not dims:
            dims = (self._default_dim(self._available_dims),)
            self.selected_dims = list(dims)
            self._refresh_dims()
        return dims

    def _checked_dims(self) -> list[str]:
        """Return the checked DFT dimensions in display order."""
        selected: list[str] = []
        for index in range(self._dim_list.count()):
            item = self._dim_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the transform-specific banner."""
        self._show_exception("transform_failed", exc)

    def get_task(self) -> Task:
        """Return the current Fourier operation as a workflow task."""
        transform = self._coerce_transform()
        if transform == "dft":
            dims = self._get_dims() or tuple(self.selected_dims)
            real_mode = self.real_mode if self.real_mode in _REAL_OPTION_MAP else "Auto"
            return PatchConfiguredMethodTask(
                method_name="dft",
                method_args=(dims,),
                method_kwargs={
                    "real": _REAL_OPTION_MAP[real_mode],
                    "pad": bool(self.pad),
                },
            )
        return PatchConfiguredMethodTask(
            method_name="idft",
            call_style="positional_dim",
            dim=self._get_dim()
            or (self.selected_dims[0] if self.selected_dims else None),
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Fourier).run()
