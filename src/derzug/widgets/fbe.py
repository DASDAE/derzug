"""Orange widget for DASCore frequency-band extraction via STFT power."""

from __future__ import annotations

from typing import Any, ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.nodes.fbe import NODE_SPEC, WINDOW_TYPES, parse_fbe_bound
from derzug.nodes.stft import parse_overlap
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow import Task


class FBE(PatchDimWidget):
    """Extract one frequency band energy trace via STFT power reduction."""

    node_spec = NODE_SPEC
    authoritative_state = True
    want_main_area = False

    _WINDOW_TYPES: ClassVar[tuple[str, ...]] = WINDOW_TYPES

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("FBE requires a patch with a 'time' dimension")
        invalid_window_length = Msg("Invalid window length '{}': {}")
        invalid_overlap = Msg("Invalid overlap '{}': {}")
        invalid_fbe_lower = Msg("Invalid FBE lower '{}': {}")
        invalid_fbe_upper = Msg("Invalid FBE upper '{}': {}")
        invalid_fbe_band = Msg("Invalid FBE band: {}")
        transform_failed = Msg("FBE failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="DAS patch to transform")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch after FBE reduction")

    def __init__(self) -> None:
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        gui.lineEdit(
            box,
            self,
            "window_length",
            label="Window",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "overlap",
            label="Overlap",
            callback=self.run,
        )
        gui.widgetLabel(box, "Taper Window")
        self._taper_window_combo = QComboBox(box)
        self._taper_window_combo.addItems(self._WINDOW_TYPES)
        if self.taper_window not in self._WINDOW_TYPES:
            self.taper_window = self._WINDOW_TYPES[0]
        self._taper_window_combo.setCurrentText(self.taper_window)
        box.layout().addWidget(self._taper_window_combo)
        gui.checkBox(
            box,
            self,
            "samples",
            label="Samples",
            callback=self.run,
        )
        gui.checkBox(
            box,
            self,
            "detrend",
            label="Detrend",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "fbe_lower",
            label="Lower ft_time",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "fbe_upper",
            label="Upper ft_time",
            callback=self.run,
        )

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)
        self._taper_window_combo.currentTextChanged.connect(
            self._on_taper_window_changed
        )

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run FBE with the current settings."""
        self._set_patch_input(patch)
        self.run()

    def _refresh_dims(self) -> None:
        """Restrict FBE to the time dimension only."""
        has_time = self._patch is not None and "time" in self._patch.dims
        self._available_dims = ("time",) if has_time else ()

        self._dim_combo.blockSignals(True)
        self._dim_combo.clear()
        if has_time:
            self.selected_dim = "time"
            self._dim_combo.addItem("time")
            self._dim_combo.setCurrentText("time")
        self._dim_combo.setEnabled(False)
        self._dim_combo.blockSignals(False)

    def _on_dim_changed(self, value: str) -> None:
        """Persist the selected dimension and rerun."""
        self.selected_dim = "time" if value == "time" else ""
        self._dim_combo.blockSignals(True)
        if self._available_dims:
            self._dim_combo.setCurrentText("time")
        self._dim_combo.blockSignals(False)
        self.run()

    def _on_taper_window_changed(self, value: str) -> None:
        """Persist the selected taper window and rerun."""
        self.taper_window = value
        self.run()

    def _parse_window_length(self) -> Any:
        """Parse the required STFT window-length value."""
        return parse_patch_text_value(self.window_length, required=True)

    def _parse_overlap(self) -> Any:
        """Parse the optional STFT overlap value."""
        return parse_overlap(self.overlap)

    def _coerce_taper_window(self) -> str:
        """Return the selected taper window or reset to the default."""
        if self.taper_window in self._WINDOW_TYPES:
            return self.taper_window
        default = self._WINDOW_TYPES[0]
        self.taper_window = default
        self._taper_window_combo.blockSignals(True)
        self._taper_window_combo.setCurrentText(default)
        self._taper_window_combo.blockSignals(False)
        return default

    def _parse_fbe_bound(self, text: str) -> Any | None:
        """Parse one optional FBE frequency-band endpoint."""
        return parse_fbe_bound(text)

    def _validated_task(self) -> Task | None:
        """Return the current FBE task after widget-side validation."""
        patch = self._patch
        if patch is not None and "time" not in patch.dims:
            self._show_error_message("invalid_patch")
            return None
        dim = self._get_dim()
        if dim is None:
            return None
        try:
            self._parse_window_length()
        except Exception as exc:
            self._show_exception("invalid_window_length", exc, self.window_length)
            return None
        try:
            self._parse_overlap()
        except Exception as exc:
            self._show_exception("invalid_overlap", exc, self.overlap)
            return None
        try:
            lower = self._parse_fbe_bound(self.fbe_lower)
        except Exception as exc:
            self._show_exception("invalid_fbe_lower", exc, self.fbe_lower)
            return None
        try:
            upper = self._parse_fbe_bound(self.fbe_upper)
        except Exception as exc:
            self._show_exception("invalid_fbe_upper", exc, self.fbe_upper)
            return None
        if lower is not None and upper is not None:
            try:
                if lower > upper:
                    raise ValueError("lower must be less than or equal to upper")
            except Exception as exc:
                self._show_exception("invalid_fbe_band", exc)
                return None
        self._coerce_taper_window()
        return NODE_SPEC.build_task(self.get_params())

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the transform-specific banner."""
        self._show_exception("transform_failed", exc)

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {
            "selected_dim": self._dim_combo,
            "taper_window": self._taper_window_combo,
        }

    def get_task(self) -> Task:
        """Return the current FBE semantics as a workflow task."""
        self._coerce_taper_window()
        return NODE_SPEC.build_task(self.get_params())


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(FBE).run()
