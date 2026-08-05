"""Orange widget that applies DASCore rolling aggregation to patches."""

from __future__ import annotations

from typing import Any, ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.nodes.rolling import AGGREGATIONS, NODE_SPEC
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow import Task


class Rolling(PatchDimWidget):
    """Apply DASCore rolling aggregations to an input patch."""

    node_spec = NODE_SPEC
    authoritative_state = True

    # This is a non-graphical widget; we dont need main area.
    want_main_area = False

    _AGGREGATIONS: ClassVar[tuple[str, ...]] = AGGREGATIONS

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        invalid_window = Msg("Invalid rolling window '{}': {}")
        invalid_step = Msg("Invalid rolling step '{}': {}")
        rolling_failed = Msg("Rolling failed: {}")

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

        gui.lineEdit(
            box,
            self,
            "rolling_window",
            label="Window",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "step",
            label="Step",
            callback=self.run,
        )
        gui.checkBox(
            box,
            self,
            "center",
            label="Center",
            callback=self.run,
        )
        gui.checkBox(
            box,
            self,
            "dropna",
            label="Drop NaN",
            callback=self.run,
        )

        gui.widgetLabel(box, "Aggregation:")
        self._agg_combo = QComboBox(box)
        self._agg_combo.addItems(self._AGGREGATIONS)
        box.layout().addWidget(self._agg_combo)

        if self.aggregation not in self._AGGREGATIONS:
            self.aggregation = self._AGGREGATIONS[0]
        self._agg_combo.setCurrentText(self.aggregation)

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._agg_combo.currentTextChanged.connect(self._on_aggregation_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the rolling pipeline."""
        self._set_patch_input(patch)
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_aggregation_changed(self, value: str) -> None:
        """Persist selected aggregation and rerun."""
        self.aggregation = value
        self.run()

    def _parse_window_value(self, value: str, *, allow_none: bool) -> Any | None:
        """Convert a text value into a DASCore rolling window/step value."""
        return parse_patch_text_value(
            value,
            allow_none=allow_none,
            required=not allow_none,
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the rolling-specific banner."""
        self._show_exception("rolling_failed", exc)

    def _validated_task(self) -> Task | None:
        """Return the current rolling task after widget-side validation.

        The parses below are preflight only: they exist to raise the right
        error banner. The task itself is built from the params model, which
        parses the same text again.
        """
        if self._get_dim() is None:
            return None

        try:
            self._parse_window_value(self.rolling_window, allow_none=False)
        except Exception as exc:
            self._show_exception("invalid_window", exc, self.rolling_window)
            return None

        try:
            self._parse_window_value(self.step, allow_none=True)
        except Exception as exc:
            self._show_exception("invalid_step", exc, self.step)
            return None

        self._coerce_aggregation()
        return NODE_SPEC.build_task(self.get_params())

    def _coerce_aggregation(self) -> str:
        """Return the selected aggregation, resetting an invalid one."""
        if self.aggregation in self._AGGREGATIONS:
            return self.aggregation
        self.aggregation = self._AGGREGATIONS[0]
        self._agg_combo.blockSignals(True)
        self._agg_combo.setCurrentText(self.aggregation)
        self._agg_combo.blockSignals(False)
        return self.aggregation

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {
            "selected_dim": self._dim_combo,
            "aggregation": self._agg_combo,
        }

    def get_task(self) -> Task:
        """Return the current rolling aggregation as a workflow task."""
        self._coerce_aggregation()
        # Side effect: resyncs ``selected_dim`` to an available dimension.
        self._get_dim()
        return NODE_SPEC.build_task(self.get_params())


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Rolling).run()
