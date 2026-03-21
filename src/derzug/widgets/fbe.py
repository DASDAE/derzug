"""Orange widget for DASCore frequency-band extraction via STFT power."""

from __future__ import annotations

from typing import Any, ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox
from dascore.units import percent
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_patch_text_value


class FBE(PatchDimWidget):
    """Extract one frequency band energy trace via STFT power reduction."""

    name = "FBE"
    description = "Extract one frequency band energy feature from a patch"
    icon = "icons/FBE.svg"
    category = "Transform"
    keywords = ("fbe", "stft", "frequency", "band", "energy")
    priority = 21.14
    want_main_area = False

    selected_dim = Setting("")
    window_length = Setting("0.01")
    overlap = Setting("50 %")
    taper_window = Setting("hann")
    samples = Setting(False)
    detrend = Setting(False)
    fbe_lower = Setting("")
    fbe_upper = Setting("")

    _WINDOW_TYPES: ClassVar[tuple[str, ...]] = (
        "hann",
        "hamming",
        "blackman",
        "nuttall",
    )

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
        return parse_patch_text_value(text, allow_none=True, required=False)

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
        if not text.strip():
            return None
        return parse_patch_text_value(text, allow_none=True, required=False)

    def _resolved_fbe_bounds(self, stft_patch: dc.Patch) -> tuple[Any, Any]:
        """Return validated FBE bounds, defaulting blanks to full ft_time extent."""
        ft_values = stft_patch.get_array("ft_time")
        full_low = ft_values[0]
        full_high = ft_values[-1]

        try:
            low = self._parse_fbe_bound(self.fbe_lower)
        except Exception as exc:
            self._show_exception("invalid_fbe_lower", exc, self.fbe_lower)
            raise
        try:
            high = self._parse_fbe_bound(self.fbe_upper)
        except Exception as exc:
            self._show_exception("invalid_fbe_upper", exc, self.fbe_upper)
            raise

        low = full_low if low is None else low
        high = full_high if high is None else high
        try:
            if low > high:
                raise ValueError("lower must be less than or equal to upper")
        except TypeError as exc:
            self._show_exception("invalid_fbe_band", exc)
            raise
        except ValueError as exc:
            self._show_exception("invalid_fbe_band", exc)
            raise
        return low, high

    def _run(self) -> dc.Patch | None:
        """Apply STFT power-band extraction and return the reduced patch."""
        if self._patch is None:
            return None
        if "time" not in self._patch.dims:
            self._show_error_message("invalid_patch")
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

        taper_window = self._coerce_taper_window()

        try:
            stft_patch = self._patch.stft(
                overlap=overlap,
                taper_window=taper_window,
                samples=self.samples,
                detrend=self.detrend,
                **{dim: window_length},
            )
            low, high = self._resolved_fbe_bounds(stft_patch)
            return (
                (stft_patch * stft_patch.conj())
                .select(ft_time=(low, high))
                .sum("ft_time")
                .squeeze()
            )
        except Exception as exc:
            if (
                self.Error.invalid_fbe_lower.is_shown()
                or self.Error.invalid_fbe_upper.is_shown()
                or self.Error.invalid_fbe_band.is_shown()
            ):
                return None
            self._show_exception("transform_failed", exc)
            return None


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(FBE).run()
