"""Orange widget for DASCore decimation and resampling."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QStackedWidget
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.nodes.resample import (
    DECIMATE_FILTER_TYPES,
    INTERP_KINDS,
    MODE_NAMES,
    NODE_SPEC,
    parse_decimate_factor,
    parse_resample_target,
)
from derzug.workflow import Task


class Resample(PatchDimWidget):
    """Decimate or resample an input patch along a chosen dimension."""

    node_spec = NODE_SPEC
    name = "Resample"
    authoritative_state = True
    description = "Decimate or resample a patch along a dimension"
    icon = "icons/Resample.svg"
    category = "Processing"
    keywords = ("resample", "decimate", "downsample", "upsample", "interpolate")
    priority = 24
    want_main_area = False

    _MODE_NAMES: ClassVar[tuple[str, ...]] = MODE_NAMES
    _DECIMATE_FILTER_TYPES: ClassVar[tuple[str, ...]] = DECIMATE_FILTER_TYPES
    _INTERP_KINDS: ClassVar[tuple[str, ...]] = INTERP_KINDS

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
        gui.lineEdit(
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
        return parse_decimate_factor(self.decimate_factor)

    def _parse_resample_target(self):
        """Parse and validate the resample target according to sample mode."""
        return parse_resample_target(
            self.resample_target, samples=bool(self.resample_samples)
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the resample-specific banner."""
        self._show_exception("resample_failed", exc)

    def _validated_task(self) -> Task | None:
        """Return the current operation task after widget-side validation.

        The parses are preflight only, to pick the right error banner; the
        task is built from the params model, which parses the text again.
        """
        if self._get_dim() is None:
            return None
        if self.mode == "resample":
            try:
                self._parse_resample_target()
            except Exception as exc:
                self._show_exception("invalid_target", exc, self.resample_target)
                return None
        else:
            try:
                self._parse_decimate_factor()
            except Exception as exc:
                self._show_exception("invalid_factor", exc, self.decimate_factor)
                return None
        return NODE_SPEC.build_task(self.get_params())

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {
            "selected_dim": self._dim_combo,
            "decimate_filter_type": self._decimate_filter_combo,
            "resample_interp_kind": self._interp_combo,
        }

    def _sync_dependent_controls(self) -> None:
        """Sync the index-based mode combo (label != value) and its page."""
        index = (
            self._MODE_NAMES.index(self.mode) if self.mode in self._MODE_NAMES else 0
        )
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(index)
        self._mode_combo.blockSignals(False)
        self._stack.setCurrentIndex(index)

    def get_task(self) -> Task:
        """Return the current decimate/resample operation as a workflow task."""
        # Side effect: resyncs ``selected_dim`` to an available dimension.
        self._get_dim()
        return NODE_SPEC.build_task(self.get_params())


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Resample).run()
