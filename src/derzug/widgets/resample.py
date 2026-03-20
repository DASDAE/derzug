"""Orange widget for DASCore decimation and resampling."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QStackedWidget
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_patch_text_value, parse_text_value


class Resample(PatchDimWidget):
    """Decimate or resample an input patch along a chosen dimension."""

    name = "Resample"
    description = "Decimate or resample a patch along a dimension"
    icon = "icons/Resample.svg"
    category = "Processing"
    keywords = ("resample", "decimate", "downsample", "upsample", "interpolate")
    priority = 24
    want_main_area = False

    mode = Setting("decimate")
    selected_dim = Setting("")
    decimate_factor = Setting("2")
    decimate_filter_type = Setting("iir")
    resample_target = Setting("10 ms")
    resample_samples = Setting(False)
    resample_interp_kind = Setting("linear")

    _MODE_NAMES: ClassVar[tuple[str, ...]] = ("decimate", "resample")
    _DECIMATE_FILTER_TYPES: ClassVar[tuple[str, ...]] = ("iir", "fir", "none")
    _INTERP_KINDS: ClassVar[tuple[str, ...]] = (
        "linear",
        "nearest",
        "zero",
        "slinear",
        "quadratic",
        "cubic",
    )

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        invalid_factor = Msg("Invalid decimation factor '{}': {}")
        invalid_target = Msg("Invalid resample target '{}': {}")
        resample_failed = Msg("Resample failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")

        gui.widgetLabel(box, "Mode:")
        self._mode_combo = QComboBox(box)
        self._mode_combo.addItems(("Decimate", "Resample"))
        box.layout().addWidget(self._mode_combo)

        gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)
        self._stack.addWidget(self._build_decimate_page())
        self._stack.addWidget(self._build_resample_page())

        if self.mode not in self._MODE_NAMES:
            self.mode = self._MODE_NAMES[0]
        self._mode_combo.setCurrentIndex(self._MODE_NAMES.index(self.mode))
        self._stack.setCurrentIndex(self._MODE_NAMES.index(self.mode))
        self._update_resample_target_label()

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    def _build_decimate_page(self):
        """Build the decimation settings page."""
        page = gui.widgetBox(None)
        gui.lineEdit(
            page,
            self,
            "decimate_factor",
            label="Factor",
            callback=self.run,
        )
        gui.widgetLabel(page, "Filter:")
        self._decimate_filter_combo = QComboBox(page)
        self._decimate_filter_combo.addItems(self._DECIMATE_FILTER_TYPES)
        if self.decimate_filter_type not in self._DECIMATE_FILTER_TYPES:
            self.decimate_filter_type = self._DECIMATE_FILTER_TYPES[0]
        self._decimate_filter_combo.setCurrentText(self.decimate_filter_type)
        self._decimate_filter_combo.currentTextChanged.connect(
            self._on_decimate_filter_changed
        )
        page.layout().addWidget(self._decimate_filter_combo)
        return page

    def _build_resample_page(self):
        """Build the resampling settings page."""
        page = gui.widgetBox(None)
        self._resample_target_label = gui.widgetLabel(page, "Target:")
        self._resample_target_edit = gui.lineEdit(
            page,
            self,
            "resample_target",
            callback=self.run,
        )
        gui.checkBox(
            page,
            self,
            "resample_samples",
            label="Samples",
            callback=self._on_resample_samples_changed,
        )
        gui.widgetLabel(page, "Interpolation:")
        self._interp_combo = QComboBox(page)
        self._interp_combo.addItems(self._INTERP_KINDS)
        if self.resample_interp_kind not in self._INTERP_KINDS:
            self.resample_interp_kind = self._INTERP_KINDS[0]
        self._interp_combo.setCurrentText(self.resample_interp_kind)
        self._interp_combo.currentTextChanged.connect(self._on_interp_kind_changed)
        page.layout().addWidget(self._interp_combo)
        return page

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the resample pipeline."""
        self._set_patch_input(patch)
        self.run()

    def _on_mode_changed(self, index: int) -> None:
        """Persist selected mode and rerun."""
        self.mode = self._MODE_NAMES[index]
        self._stack.setCurrentIndex(index)
        self._update_resample_target_label()
        self.run()

    def _on_dim_changed(self, value: str) -> None:
        """Persist selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_decimate_filter_changed(self, value: str) -> None:
        """Persist selected filter type and rerun."""
        self.decimate_filter_type = value
        self.run()

    def _on_resample_samples_changed(self) -> None:
        """Update label text when toggling sample-count mode."""
        self._update_resample_target_label()
        self.run()

    def _on_interp_kind_changed(self, value: str) -> None:
        """Persist interpolation kind and rerun."""
        self.resample_interp_kind = value
        self.run()

    def _update_resample_target_label(self) -> None:
        """Update the target field label for period vs sample-count mode."""
        label = "Samples" if bool(self.resample_samples) else "Period"
        self._resample_target_label.setText(f"{label}:")

    def _parse_decimate_factor(self) -> int:
        """Parse and validate the decimation factor."""
        parsed = parse_text_value(self.decimate_factor)
        if not isinstance(parsed, int):
            raise ValueError("factor must be an integer")
        if parsed <= 0:
            raise ValueError("factor must be positive")
        return parsed

    def _parse_resample_target(self):
        """Parse and validate the resample target according to sample mode."""
        if bool(self.resample_samples):
            parsed = parse_text_value(self.resample_target)
            if not isinstance(parsed, int):
                raise ValueError("sample target must be an integer")
            if parsed <= 0:
                raise ValueError("sample target must be positive")
            return parsed
        return parse_patch_text_value(self.resample_target, required=True)

    def _run_decimate(self, dim: str) -> dc.Patch | None:
        """Execute DASCore decimation with current settings."""
        try:
            factor = self._parse_decimate_factor()
        except Exception as exc:
            self._show_exception("invalid_factor", exc, self.decimate_factor)
            return None

        filter_type = (
            None if self.decimate_filter_type == "none" else self.decimate_filter_type
        )
        try:
            return self._patch.decimate(**{dim: factor}, filter_type=filter_type)
        except Exception as exc:
            self._show_exception("resample_failed", exc)
            return None

    def _run_resample(self, dim: str) -> dc.Patch | None:
        """Execute DASCore resampling with current settings."""
        try:
            target = self._parse_resample_target()
        except Exception as exc:
            self._show_exception("invalid_target", exc, self.resample_target)
            return None

        try:
            return self._patch.resample(
                **{dim: target},
                samples=self.resample_samples,
                interp_kind=self.resample_interp_kind,
            )
        except Exception as exc:
            self._show_exception("resample_failed", exc)
            return None

    def _run(self) -> dc.Patch | None:
        """Apply the configured resampling operation to the current patch."""
        if self._patch is None:
            return None

        dim = self._get_dim()
        if dim is None:
            return None

        if self.mode == "resample":
            return self._run_resample(dim)
        return self._run_decimate(dim)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Resample).run()
