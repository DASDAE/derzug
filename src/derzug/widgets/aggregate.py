"""Orange widget that applies DASCore aggregate reduction to patches."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchwidget import PatchWidget
from derzug.nodes.aggregate import (
    DIM_REDUCES,
    METHODS,
    NODE_SPEC,
    default_phase_weighted_stack_dim,
    infer_phase_weighted_stack_transform_dim,
)
from derzug.workflow import Task


class Aggregate(PatchWidget):
    """Apply DASCore aggregate reduction to an input patch."""

    node_spec = NODE_SPEC
    authoritative_state = True

    want_main_area = False

    _METHODS: ClassVar[tuple[str, ...]] = METHODS
    _DIM_REDUCES: ClassVar[tuple[str, ...]] = DIM_REDUCES

    class Error(PatchWidget.Error):
        """Errors shown by the widget."""

        aggregate_failed = Msg("Aggregate failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._available_dims: tuple[str, ...] = ()

        box = gui.widgetBox(self.controlArea, "Parameters")

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        gui.widgetLabel(box, "Method:")
        self._method_combo = QComboBox(box)
        self._method_combo.addItems(self._METHODS)
        box.layout().addWidget(self._method_combo)

        self._transform_dim_label = gui.widgetLabel(box, "Transform dimension:")
        self._transform_dim_combo = QComboBox(box)
        box.layout().addWidget(self._transform_dim_combo)

        gui.widgetLabel(box, "Coordinate reduction:")
        self._dim_reduce_combo = QComboBox(box)
        self._dim_reduce_combo.addItems(self._DIM_REDUCES)
        box.layout().addWidget(self._dim_reduce_combo)

        if self.method not in self._METHODS:
            self.method = self._METHODS[0]
        self._method_combo.setCurrentText(self.method)

        if self.dim_reduce not in self._DIM_REDUCES:
            self.dim_reduce = self._DIM_REDUCES[0]
        self._dim_reduce_combo.setCurrentText(self.dim_reduce)

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._transform_dim_combo.currentTextChanged.connect(
            self._on_transform_dim_changed
        )
        self._method_combo.currentTextChanged.connect(self._on_method_changed)
        self._dim_reduce_combo.currentTextChanged.connect(self._on_dim_reduce_changed)
        self._refresh_transform_dims()
        self._sync_phase_weighted_stack_controls()

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the aggregate pipeline."""
        self._patch = patch
        self._refresh_dims()
        self.run()

    def _refresh_dims(self) -> None:
        """Sync dimension choices from the current patch."""
        dims = (
            tuple(sorted(self._patch.dims, key=str.casefold))
            if self._patch is not None
            else ()
        )
        self._available_dims = dims

        self._dim_combo.blockSignals(True)
        self._dim_combo.clear()
        self._dim_combo.addItem("All")
        self._dim_combo.addItems(dims)

        if self._patch is None:
            self._dim_combo.setCurrentText("All")
        elif self.selected_dim in ("", "All") or self.selected_dim not in dims:
            self.selected_dim = ""
            self._dim_combo.setCurrentText("All")
        else:
            self._dim_combo.setCurrentText(self.selected_dim)

        self._dim_combo.setEnabled(bool(dims))
        self._dim_combo.blockSignals(False)
        self._refresh_transform_dims()
        self._sync_phase_weighted_stack_controls()

    def _refresh_transform_dims(self) -> None:
        """Sync transform-dimension choices from the current patch and stack dim."""
        stack_dim = (
            self.selected_dim if self.selected_dim in self._available_dims else ""
        )
        if not stack_dim and self._patch is not None and self._available_dims:
            # An unset stack dim resolves to the same default the task applies,
            # so the transform chooser must exclude that effective stack dim.
            stack_dim = default_phase_weighted_stack_dim(tuple(self._patch.dims)) or ""
        dims = tuple(dim for dim in self._available_dims if dim != stack_dim)
        inferred = ""
        if (
            self.transform_dim not in dims
            and self._patch is not None
            and stack_dim in self._available_dims
            and dims
        ):
            try:
                inferred = infer_phase_weighted_stack_transform_dim(
                    self._patch, stack_dim
                )
            except ValueError:
                inferred = ""

        self._transform_dim_combo.blockSignals(True)
        self._transform_dim_combo.clear()
        self._transform_dim_combo.addItems(dims)
        if dims:
            if self.transform_dim not in dims:
                self.transform_dim = inferred or dims[0]
            self._transform_dim_combo.setCurrentText(self.transform_dim)
        else:
            self.transform_dim = ""
            self._transform_dim_combo.setCurrentIndex(-1)
        self._transform_dim_combo.setEnabled(bool(dims))
        self._transform_dim_combo.blockSignals(False)

    def _sync_phase_weighted_stack_controls(self) -> None:
        """Show the transform-dimension controls only when they are relevant."""
        visible = self.method == "phase_weighted_stack"
        self._transform_dim_label.setVisible(visible)
        self._transform_dim_combo.setVisible(visible)

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = "" if value == "All" else value
        self._refresh_transform_dims()
        self.run()

    def _on_transform_dim_changed(self, value: str) -> None:
        """Persist selected transform dimension and rerun."""
        self.transform_dim = value
        self.run()

    def _on_method_changed(self, value: str) -> None:
        """Persist selected method and rerun."""
        self.method = value
        if (
            value == "phase_weighted_stack"
            and self.selected_dim not in self._available_dims
            and self._patch is not None
            and self._available_dims
        ):
            self.selected_dim = default_phase_weighted_stack_dim(
                tuple(self._patch.dims)
            )
            self._dim_combo.blockSignals(True)
            self._dim_combo.setCurrentText(self.selected_dim)
            self._dim_combo.blockSignals(False)
            self._refresh_transform_dims()
        self._sync_phase_weighted_stack_controls()
        self.run()

    def _on_dim_reduce_changed(self, value: str) -> None:
        """Persist selected dim_reduce and rerun."""
        self.dim_reduce = value
        self.run()

    def _validated_task(self) -> Task:
        """Return the aggregate task after normalizing persisted settings."""
        method = self.method if self.method in self._METHODS else self._METHODS[0]
        if method != self.method:
            self.method = method
            self._method_combo.blockSignals(True)
            self._method_combo.setCurrentText(method)
            self._method_combo.blockSignals(False)
        dim_reduce = (
            self.dim_reduce
            if self.dim_reduce in self._DIM_REDUCES
            else self._DIM_REDUCES[0]
        )
        if dim_reduce != self.dim_reduce:
            self.dim_reduce = dim_reduce
            self._dim_reduce_combo.blockSignals(True)
            self._dim_reduce_combo.setCurrentText(dim_reduce)
            self._dim_reduce_combo.blockSignals(False)
        return NODE_SPEC.build_task(self.get_params())

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the aggregate-specific banner."""
        self._show_exception("aggregate_failed", exc)

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {
            "selected_dim": self._dim_combo,
            "method": self._method_combo,
            "transform_dim": self._transform_dim_combo,
            "dim_reduce": self._dim_reduce_combo,
        }

    def get_task(self) -> Task:
        """Return the configured aggregate task."""
        return self._validated_task()


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Aggregate).run()
