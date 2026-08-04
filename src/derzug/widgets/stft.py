"""Orange widget for DASCore short-time Fourier transforms."""

from __future__ import annotations

from typing import Any

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.nodes.stft import (
    NODE_SPEC,
    parse_overlap,
    parse_taper_window,
    parse_window_length,
)
from derzug.workflow import Task


class Stft(PatchDimWidget):
    """Apply a DASCore short-time Fourier transform to an input patch."""

    node_spec = NODE_SPEC
    name = "Stft"
    authoritative_state = True
    description = "Apply a short-time Fourier transform to a patch"
    icon = "icons/Stft.svg"
    category = "Transform"
    keywords = ("stft", "spectrogram", "fourier", "transform")
    priority = 21.15
    want_main_area = False

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        invalid_window_length = Msg("Invalid window length '{}': {}")
        invalid_overlap = Msg("Invalid overlap '{}': {}")
        invalid_taper_window = Msg("Invalid taper window '{}': {}")
        transform_failed = Msg("STFT failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="DAS patch to transform")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch after STFT")

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
        gui.lineEdit(
            box,
            self,
            "taper_window",
            label="Taper Window",
            callback=self.run,
        )
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

        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run STFT with the current settings."""
        self._set_patch_input(patch)
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist the selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _parse_window_length(self) -> Any:
        """Parse the required STFT window-length value."""
        return parse_window_length(self.window_length)

    def _parse_overlap(self) -> Any:
        """Parse the optional STFT overlap value."""
        return parse_overlap(self.overlap)

    def _parse_taper_window(self) -> str | tuple:
        """Parse the taper-window input into a name or tuple spec."""
        return parse_taper_window(self.taper_window)

    def _validated_task(self) -> Task | None:
        """Return the current STFT task after widget-side validation.

        The parses are preflight only, to pick the right error banner; the
        task is built from the params model, which parses the text again.
        """
        if self._get_dim() is None:
            return None
        checks = (
            ("invalid_window_length", self._parse_window_length, self.window_length),
            ("invalid_overlap", self._parse_overlap, self.overlap),
            ("invalid_taper_window", self._parse_taper_window, self.taper_window),
        )
        for error_key, parse, raw in checks:
            try:
                parse()
            except Exception as exc:
                self._show_exception(error_key, exc, raw)
                return None
        return NODE_SPEC.build_task(self.get_params())

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the transform-specific banner."""
        self._show_exception("transform_failed", exc)

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {"selected_dim": self._dim_combo}

    def get_task(self) -> Task:
        """Return the current STFT operation as a workflow task."""
        # Side effect: resyncs ``selected_dim`` to an available dimension.
        self._get_dim()
        return NODE_SPEC.build_task(self.get_params())


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Stft).run()
