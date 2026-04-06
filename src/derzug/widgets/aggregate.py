"""Orange widget that applies DASCore aggregate reduction to patches."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.orange import Setting
from derzug.workflow import Task


class AggregateTask(Task):
    """Task wrapper around DASCore aggregate reduction."""

    selected_dim: str = ""
    transform_dim: str = ""
    method: str = "mean"
    dim_reduce: str = "empty"
    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    @staticmethod
    def _infer_phase_weighted_stack_transform_dim(
        patch: dc.Patch, stack_dim: str
    ) -> str:
        """Pick a deterministic transform axis for phase-weighted stacking."""
        candidates = tuple(dim for dim in patch.dims if dim != stack_dim)
        if not candidates:
            msg = "Phase-weighted stack requires at least two patch dimensions."
            raise ValueError(msg)
        if "time" in candidates:
            return "time"
        sized_candidates = tuple(
            dim for dim in candidates if patch.shape[patch.dims.index(dim)] > 1
        )
        if len(sized_candidates) == 1:
            return sized_candidates[0]
        if len(candidates) == 1:
            return candidates[0]
        msg = (
            "Phase-weighted stack could not infer the transform dimension from "
            f"{candidates}. Add a 'time' dimension or reduce the patch to one "
            "non-stack dimension before stacking."
        )
        raise ValueError(msg)

    def run(self, patch):
        """Apply the configured aggregate reduction to one patch."""
        dim = None if self.selected_dim in ("", "All") else self.selected_dim
        if self.method == "phase_weighted_stack":
            if dim is None:
                msg = "Phase-weighted stack requires selecting one stack dimension."
                raise ValueError(msg)
            transform_dim = (
                self.transform_dim
                if self.transform_dim and self.transform_dim in patch.dims
                else self._infer_phase_weighted_stack_transform_dim(patch, dim)
            )
            if transform_dim == dim:
                msg = "Phase-weighted stack transform dimension must differ from stack dimension."
                raise ValueError(msg)
            return patch.phase_weighted_stack(
                stack_dim=dim,
                transform_dim=transform_dim,
                dim_reduce=self.dim_reduce,
            )
        return patch.aggregate(dim=dim, method=self.method, dim_reduce=self.dim_reduce)


class Aggregate(ZugWidget):
    """Apply DASCore aggregate reduction to an input patch."""

    name = "Aggregate"
    description = "Apply DASCore aggregate reduction to a patch"
    icon = "icons/AggregateColumns.svg"
    category = "Processing"
    keywords = ("aggregate", "reduce", "mean", "sum", "statistics")
    priority = 25

    want_main_area = False

    selected_dim = Setting("")
    transform_dim = Setting("")
    method = Setting("mean")
    dim_reduce = Setting("empty")

    _METHODS: ClassVar[tuple[str, ...]] = (
        "first",
        "last",
        "max",
        "mean",
        "median",
        "min",
        "phase_weighted_stack",
        "std",
        "sum",
    )
    _DIM_REDUCES: ClassVar[tuple[str, ...]] = (
        "empty",
        "squeeze",
        "mean",
        "min",
        "max",
        "first",
        "last",
    )

    @staticmethod
    def _default_phase_weighted_stack_dim(dims: tuple[str, ...]) -> str:
        """Choose a default stack dimension for phase-weighted stack."""
        if "distance" in dims:
            return "distance"
        return dims[0]

    class Error(ZugWidget.Error):
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
        self._patch: dc.Patch | None = None
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
        stack_dim = self.selected_dim if self.selected_dim in self._available_dims else ""
        dims = tuple(dim for dim in self._available_dims if dim != stack_dim)
        inferred = (
            AggregateTask._infer_phase_weighted_stack_transform_dim(self._patch, stack_dim)
            if self._patch is not None and stack_dim in self._available_dims and dims
            else ""
        )

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
            and self._available_dims
        ):
            self.selected_dim = self._default_phase_weighted_stack_dim(
                self._available_dims
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

    def _supports_async_execution(self) -> bool:
        """Run aggregate reductions off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one aggregate execution request from current widget state."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _validated_task(self) -> Task | None:
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
        return AggregateTask(
            selected_dim=self.selected_dim,
            transform_dim=self.transform_dim,
            method=method,
            dim_reduce=dim_reduce,
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the aggregate-specific banner."""
        self._show_exception("aggregate_failed", exc)

    def _run(self) -> dc.Patch | None:
        """Apply aggregate reduction with current settings and return output patch."""
        patch = self._patch
        if patch is None:
            return None
        return self._execute_workflow_object(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def get_task(self) -> Task:
        """Return the configured aggregate task."""
        workflow_obj = self._validated_task()
        if workflow_obj is None:
            raise ValueError("current Aggregate state is not valid")
        return workflow_obj

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send aggregate result patch on output."""
        self.Outputs.patch.send(result)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Aggregate).run()
