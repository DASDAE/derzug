"""Orange widget for DASCore short-time Fourier transforms."""

from __future__ import annotations

import ast
from typing import Any

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from dascore.units import percent
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_patch_text_value


class Stft(PatchDimWidget):
    """Apply a DASCore short-time Fourier transform to an input patch."""

    name = "Stft"
    description = "Apply a short-time Fourier transform to a patch"
    icon = "icons/Stft.svg"
    category = "Transform"
    keywords = ("stft", "spectrogram", "fourier", "transform")
    priority = 21.15
    want_main_area = False

    selected_dim = Setting("")
    window_length = Setting("0.01")
    overlap = Setting("50 %")
    taper_window = Setting("hann")
    samples = Setting(False)
    detrend = Setting(False)

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
        return parse_patch_text_value(
            self.window_length,
            required=True,
        )

    def _parse_overlap(self) -> Any:
        """Parse the optional STFT overlap value."""
        text = self.overlap.strip()
        if not text:
            return None
        lowered = text.lower()
        if "%" in text or "percent" in lowered:
            value = parse_patch_text_value(
                text.replace("%", "").replace("percent", "").strip(),
                required=True,
            )
            return value * percent
        return parse_patch_text_value(
            text,
            allow_none=True,
            required=False,
        )

    def _parse_taper_window(self) -> str | tuple:
        """
        Parse the taper-window input.

        The widget intentionally supports string names and tuple specs only.
        Array-valued windows remain out of scope for the text-based UI.
        """
        value = self.taper_window.strip()
        if not value:
            raise ValueError("value must not be empty")
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = value
        if isinstance(parsed, str | tuple):
            return parsed
        raise ValueError("expected a string name or tuple specification")

    def _run(self) -> dc.Patch | None:
        """Apply STFT with current settings and return the transformed patch."""
        if self._patch is None:
            return None

        dim = self._get_dim()
        if dim is None:
            return None

        try:
            window_length = self._parse_window_length()
        except Exception as exc:
            self._show_exception("invalid_window_length", exc, self.window_length)
            return None

        try:
            overlap = self._parse_overlap()
        except Exception as exc:
            self._show_exception("invalid_overlap", exc, self.overlap)
            return None

        try:
            taper_window = self._parse_taper_window()
        except Exception as exc:
            self._show_exception("invalid_taper_window", exc, self.taper_window)
            return None

        try:
            return self._patch.stft(
                overlap=overlap,
                taper_window=taper_window,
                samples=self.samples,
                detrend=self.detrend,
                **{dim: window_length},
            )
        except Exception as exc:
            self._show_exception("transform_failed", exc)
            return None


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Stft).run()
