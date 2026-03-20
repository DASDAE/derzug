"""Orange widget that applies DASCore rolling aggregation to patches."""

from __future__ import annotations

from typing import Any, ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_patch_text_value


class Rolling(PatchDimWidget):
    """Apply DASCore rolling aggregations to an input patch."""

    name = "Rolling"
    description = "Apply DASCore rolling aggregation to a patch"
    icon = "icons/Rolling.svg"
    category = "Processing"
    keywords = ("rolling", "aggregate", "smooth", "moving")
    priority = 24

    # This is a non-graphical widget; we dont need main area.
    want_main_area = False

    selected_dim = Setting("")
    rolling_window = Setting("0.01")
    step = Setting("")
    center = Setting(False)
    dropna = Setting(False)
    aggregation = Setting("mean")

    _AGGREGATIONS: ClassVar[tuple[str, ...]] = (
        "mean",
        "median",
        "sum",
        "min",
        "max",
        "std",
    )

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

    def _run(self) -> dc.Patch | None:
        """Apply rolling aggregation with current settings and return output patch."""
        if self._patch is None:
            return None

        dim = self._get_dim()
        if dim is None:
            return None

        try:
            window = self._parse_window_value(self.rolling_window, allow_none=False)
        except Exception as exc:
            self._show_exception("invalid_window", exc, self.rolling_window)
            return None

        try:
            step = self._parse_window_value(self.step, allow_none=True)
        except Exception as exc:
            self._show_exception("invalid_step", exc, self.step)
            return None

        aggregation = (
            self.aggregation
            if self.aggregation in self._AGGREGATIONS
            else self._AGGREGATIONS[0]
        )
        if aggregation != self.aggregation:
            self.aggregation = aggregation
            self._agg_combo.blockSignals(True)
            self._agg_combo.setCurrentText(aggregation)
            self._agg_combo.blockSignals(False)

        try:
            rolling = self._patch.rolling(
                step=step,
                center=bool(self.center),
                **{dim: window},
            )
            out = getattr(rolling, aggregation)()
            if self.dropna:
                out = out.dropna(dim)
        except Exception as exc:
            self._show_exception("rolling_failed", exc)
            return None

        return out


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Rolling).run()
