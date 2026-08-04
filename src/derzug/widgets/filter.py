"""Orange widget for applying DASCore Patch filter methods."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg
from pydantic import TypeAdapter

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.core.zugwidget import WidgetExecutionRequest
from derzug.nodes.filter import (
    _FILTER_MODELS,
    _FILTER_NAMES,
    _PARAM_FIELDS,
    NODE_SPEC,
    FilterParams,
    FilterTask,
    filter_settings_from_params,
    normalize_gaussian_windows,
    validated_gaussian_kwargs,
)
from derzug.utils.dynamic_rows import DynamicRowManager
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow import Task

_MODE_OPTIONS: tuple[str, ...] = (
    "reflect",
    "constant",
    "nearest",
    "wrap",
    "mirror",
    "interp",
)
_SAVGOL_MODE_OPTIONS: tuple[str, ...] = (
    "mirror",
    "constant",
    "nearest",
    "wrap",
    "interp",
)


class Filter(PatchDimWidget):
    """Apply a selected DASCore Patch filter method to an input patch."""

    node_spec = NODE_SPEC
    name = "Filter"
    description = "Apply a DASCore filter function to a patch"
    authoritative_state = True
    icon = "icons/Filter.svg"
    category = "Processing"
    keywords = ("filter", "bandpass", "gaussian", "notch", "median", "sobel")
    priority = 22

    # This is a non-graphical widget; we dont need main area.
    want_main_area = False

    _FILTER_NAMES: ClassVar[tuple[str, ...]] = _FILTER_NAMES

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        general = Msg("Filter error: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._general_mode_combos: list[QComboBox] = []
        self._savgol_mode_combo: QComboBox | None = None
        self._gaussian_legacy_migration_pending = True

        box = gui.widgetBox(self.controlArea, "Parameters")

        gui.widgetLabel(box, "Filter:")
        self._filter_combo = QComboBox(box)
        self._filter_combo.addItems(_FILTER_NAMES)
        box.layout().addWidget(self._filter_combo)

        self._dim_label = gui.widgetLabel(box, "Dimension:")
        self._dim_combo = QComboBox(box)
        box.layout().addWidget(self._dim_combo)

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)

        # Pages must be added in the same order as _FILTER_NAMES.
        for builder in (
            self._build_gaussian_page,
            self._build_hampel_page,
            self._build_median_page,
            self._build_notch_page,
            self._build_pass_filter_page,
            self._build_savgol_page,
            self._build_slope_page,
            self._build_sobel_page,
            self._build_wiener_page,
        ):
            self._stack.addWidget(builder())

        taper_box = gui.widgetBox(box, "Taper")
        gui.checkBox(
            taper_box, self, "apply_taper", label="Enable Taper", callback=self.run
        )
        gui.lineEdit(taper_box, self, "taper_window", label="Window", callback=self.run)

        # Restore persisted filter selection.
        if self.selected_filter not in _FILTER_NAMES:
            self.selected_filter = "pass_filter"
        self._restore_gaussian_rows()
        self._filter_combo.setCurrentText(self.selected_filter)
        idx = _FILTER_NAMES.index(self.selected_filter)
        self._stack.setCurrentIndex(idx)
        self._sync_primary_dim_visibility(self.selected_filter)
        self._coerce_mode_for_filter(self.selected_filter)

        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    # ------------------------------------------------------------------
    # Page builders — each returns a self-contained QWidget
    # ------------------------------------------------------------------

    def _make_mode_combo(
        self, parent: QWidget, options: tuple[str, ...] = _MODE_OPTIONS
    ) -> QComboBox:
        """Create a Mode QComboBox synced to self.mode."""
        combo = QComboBox(parent)
        combo.addItems(options)
        if self.mode in options:
            combo.setCurrentText(self.mode)
        combo.currentTextChanged.connect(
            lambda v: (setattr(self, "mode", v), self.run())
        )
        return combo

    def _build_gaussian_page(self) -> QWidget:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        controls_row = QWidget(p)
        controls_layout = QHBoxLayout(controls_row)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        controls_layout.addWidget(QLabel("Dimensions:", controls_row))
        controls_layout.addStretch(1)
        self._gaussian_add_button = QPushButton("+", controls_row)
        self._gaussian_add_button.setFixedWidth(24)
        self._gaussian_add_button.setToolTip("Add another Gaussian dimension")
        controls_layout.addWidget(self._gaussian_add_button)
        lay.addWidget(controls_row)
        self._gaussian_rows_container = QWidget(p)
        self._gaussian_rows_container.setLayout(QVBoxLayout())
        self._gaussian_rows_container.layout().setContentsMargins(0, 0, 0, 0)
        self._gaussian_rows_container.layout().setSpacing(4)
        lay.addWidget(self._gaussian_rows_container)
        gui.checkBox(p, self, "samples", label="Samples", callback=self.run)
        lay.addWidget(QLabel("Mode:", p))
        mode_combo = self._make_mode_combo(p)
        self._general_mode_combos.append(mode_combo)
        lay.addWidget(mode_combo)
        gui.doubleSpin(
            p, self, "cval", -1e9, 1e9, step=0.1, label="Cval", callback=self.run
        )
        gui.doubleSpin(
            p,
            self,
            "truncate",
            0.1,
            20.0,
            step=0.1,
            label="Truncate",
            callback=self.run,
        )
        lay.addStretch(1)
        self._gaussian_row_manager = DynamicRowManager(
            blank_state_factory=self._blank_gaussian_dim_window,
            create_row=self._create_gaussian_row,
            apply_row_state=self._set_gaussian_row_state,
            serialize_row=self._serialize_gaussian_row,
            delete_row_widget=lambda row: row["widget"].deleteLater(),
            set_row_remove_enabled=lambda row, enabled: row["remove"].setEnabled(
                enabled
            ),
            on_rows_changed=self._on_gaussian_row_changed,
        )
        self._gaussian_rows = self._gaussian_row_manager.rows
        self._gaussian_add_button.clicked.connect(self._on_add_gaussian_row_clicked)
        return p

    def _build_hampel_page(self) -> QWidget:
        p = QWidget()
        QVBoxLayout(p).setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "filter_window", label="Window", callback=self.run)
        gui.doubleSpin(
            p,
            self,
            "threshold",
            0.0,
            1e9,
            step=0.5,
            label="Threshold",
            callback=self.run,
        )
        gui.checkBox(p, self, "samples", label="Samples", callback=self.run)
        gui.checkBox(p, self, "approximate", label="Approximate", callback=self.run)
        return p

    def _build_median_page(self) -> QWidget:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "filter_window", label="Window", callback=self.run)
        gui.checkBox(p, self, "samples", label="Samples", callback=self.run)
        lay.addWidget(QLabel("Mode:", p))
        mode_combo = self._make_mode_combo(p)
        self._general_mode_combos.append(mode_combo)
        lay.addWidget(mode_combo)
        gui.doubleSpin(
            p, self, "cval", -1e9, 1e9, step=0.1, label="Cval", callback=self.run
        )
        return p

    def _build_notch_page(self) -> QWidget:
        p = QWidget()
        QVBoxLayout(p).setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "filter_window", label="Frequency", callback=self.run)
        gui.doubleSpin(p, self, "q", 0.1, 1e6, step=1.0, label="Q", callback=self.run)
        return p

    def _build_pass_filter_page(self) -> QWidget:
        p = QWidget()
        QVBoxLayout(p).setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "low_bound", label="Low Bound", callback=self.run)
        gui.lineEdit(p, self, "high_bound", label="High Bound", callback=self.run)
        gui.spin(
            p, self, "corners", minv=1, maxv=16, label="Corners", callback=self.run
        )
        gui.checkBox(p, self, "zerophase", label="Zero Phase", callback=self.run)
        return p

    def _build_savgol_page(self) -> QWidget:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "filter_window", label="Window", callback=self.run)
        gui.spin(
            p, self, "polyorder", minv=1, maxv=10, label="Poly Order", callback=self.run
        )
        gui.checkBox(p, self, "samples", label="Samples", callback=self.run)
        lay.addWidget(QLabel("Mode:", p))
        self._savgol_mode_combo = self._make_mode_combo(p, _SAVGOL_MODE_OPTIONS)
        lay.addWidget(self._savgol_mode_combo)
        gui.doubleSpin(
            p, self, "cval", -1e9, 1e9, step=0.1, label="Cval", callback=self.run
        )
        return p

    def _build_slope_page(self) -> QWidget:
        p = QWidget()
        QVBoxLayout(p).setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(
            p, self, "slope_filt", label="Slopes (comma-separated)", callback=self.run
        )
        gui.lineEdit(p, self, "slope_dim0", label="Dim 0", callback=self.run)
        gui.lineEdit(p, self, "slope_dim1", label="Dim 1", callback=self.run)
        gui.checkBox(
            p, self, "slope_directional", label="Directional", callback=self.run
        )
        gui.checkBox(p, self, "slope_notch", label="Notch", callback=self.run)
        gui.checkBox(p, self, "slope_invert", label="Invert", callback=self.run)
        return p

    def _build_sobel_page(self) -> QWidget:
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Mode:", p))
        mode_combo = self._make_mode_combo(p)
        self._general_mode_combos.append(mode_combo)
        lay.addWidget(mode_combo)
        gui.doubleSpin(
            p, self, "cval", -1e9, 1e9, step=0.1, label="Cval", callback=self.run
        )
        return p

    def _build_wiener_page(self) -> QWidget:
        p = QWidget()
        QVBoxLayout(p).setContentsMargins(0, 0, 0, 0)
        gui.lineEdit(p, self, "filter_window", label="Window", callback=self.run)
        gui.lineEdit(p, self, "noise", label="Noise (blank = auto)", callback=self.run)
        gui.checkBox(p, self, "samples", label="Samples", callback=self.run)
        return p

    # ------------------------------------------------------------------
    # Input handler
    # ------------------------------------------------------------------

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the filter pipeline."""
        self._set_patch_input(patch)
        self.run()

    def _refresh_dims(self) -> None:
        """Refresh base dim choices and Gaussian row options."""
        super()._refresh_dims()
        self._restore_gaussian_rows()

    def _on_dim_changed(self, value: str) -> None:
        self.selected_dim = value
        self.run()

    def _on_filter_changed(self, label: str) -> None:
        if label not in _FILTER_NAMES:
            return
        self.selected_filter = label
        idx = _FILTER_NAMES.index(label)
        self._stack.setCurrentIndex(idx)
        self._sync_primary_dim_visibility(label)
        self._coerce_mode_for_filter(label)
        self.run()

    def _sync_primary_dim_visibility(self, filter_name: str) -> None:
        """Hide the primary dim chooser for filters with dedicated dim controls."""
        use_primary_dim = filter_name not in {"gaussian_filter", "slope_filter"}
        self._dim_combo.setVisible(use_primary_dim)
        self._dim_label.setVisible(use_primary_dim)

    def _coerce_mode_for_filter(self, filter_name: str) -> None:
        """
        Keep `self.mode` valid for the currently selected filter.

        SciPy Savitzky-Golay does not accept `reflect`; when switching to
        savgol_filter, coerce invalid modes to `interp`.
        """
        if filter_name == "savgol_filter" and self.mode not in _SAVGOL_MODE_OPTIONS:
            self.mode = "interp"
        self._sync_mode_combos()

    def _sync_mode_combos(self) -> None:
        """Sync all mode combo widgets to the current mode value."""
        for combo in self._general_mode_combos:
            combo.blockSignals(True)
            if self.mode in _MODE_OPTIONS:
                combo.setCurrentText(self.mode)
            combo.blockSignals(False)
        if self._savgol_mode_combo is not None:
            self._savgol_mode_combo.blockSignals(True)
            if self.mode in _SAVGOL_MODE_OPTIONS:
                self._savgol_mode_combo.setCurrentText(self.mode)
            else:
                self._savgol_mode_combo.setCurrentIndex(0)
            self._savgol_mode_combo.blockSignals(False)

    def _blank_gaussian_dim_window(self) -> dict[str, str]:
        """Return one blank Gaussian dimension/window row."""
        return {"dim": "", "window": ""}

    def _restore_gaussian_rows(self) -> None:
        """Refresh Gaussian rows from persisted settings and available dims."""
        rows = normalize_gaussian_windows(self.gaussian_dim_windows)
        if not rows:
            rows = [self._blank_gaussian_dim_window()]

        if (
            self._gaussian_legacy_migration_pending
            and self.filter_window.strip()
            and not any(row["dim"] and row["window"] for row in rows)
        ):
            legacy_dim = self.selected_dim
            if legacy_dim not in self._available_dims and self._available_dims:
                legacy_dim = self._default_dim(self._available_dims)
            rows = [
                {"dim": str(legacy_dim or ""), "window": self.filter_window.strip()}
            ]

        if self._available_dims:
            rows = [
                row
                for row in rows
                if not row["dim"] or row["dim"] in self._available_dims
            ]
        if not rows:
            rows = [self._blank_gaussian_dim_window()]

        self.gaussian_dim_windows = rows
        self._refresh_gaussian_rows()
        if self._available_dims:
            self._gaussian_legacy_migration_pending = False

    def _create_gaussian_row(
        self,
        on_change,
        on_remove,
    ) -> dict[str, QWidget]:
        """Create and return one Gaussian dimension/window row."""
        row_widget = QWidget(self._gaussian_rows_container)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        combo = QComboBox(row_widget)
        window_edit = QLineEdit(row_widget)
        window_edit.setPlaceholderText("Window")
        remove_button = QPushButton("-", row_widget)
        remove_button.setFixedWidth(24)
        remove_button.setToolTip("Remove this Gaussian dimension")
        row_layout.addWidget(combo, 1)
        row_layout.addWidget(window_edit, 1)
        row_layout.addWidget(remove_button)
        combo.currentIndexChanged.connect(on_change)
        window_edit.editingFinished.connect(on_change)
        row = {
            "widget": row_widget,
            "combo": combo,
            "edit": window_edit,
            "remove": remove_button,
        }
        remove_button.clicked.connect(lambda *_args, current=row: on_remove(current))
        self._gaussian_rows_container.layout().addWidget(row_widget)
        return row

    def _set_gaussian_row_state(
        self, row: dict[str, QWidget], row_data: dict[str, str]
    ) -> None:
        """Apply options and values to one Gaussian row."""
        combo = row["combo"]
        edit = row["edit"]
        dim = str(row_data.get("dim", "")).strip()
        window = str(row_data.get("window", "")).strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self._available_dims)
        combo.setEnabled(bool(self._available_dims))
        if dim in self._available_dims:
            combo.setCurrentText(dim)
        else:
            combo.setCurrentIndex(-1)
        combo.blockSignals(False)
        edit.blockSignals(True)
        edit.setText(window)
        edit.setEnabled(bool(self._available_dims))
        edit.blockSignals(False)

    def _refresh_gaussian_rows(self) -> None:
        """Refresh all Gaussian rows from persisted settings."""
        rows = normalize_gaussian_windows(self.gaussian_dim_windows)
        self._gaussian_row_manager.refresh(rows)
        self._gaussian_add_button.setEnabled(bool(self._available_dims))

    def _sync_gaussian_dim_windows_from_ui(self) -> None:
        """Persist the current Gaussian row UI into settings."""
        self.gaussian_dim_windows = self._gaussian_row_manager.sync_from_ui()
        self._gaussian_legacy_migration_pending = False

    def _serialize_gaussian_row(self, row: dict[str, QWidget]) -> dict[str, str]:
        """Serialize one Gaussian row from the current UI."""
        return {
            "dim": row["combo"].currentText().strip(),
            "window": row["edit"].text().strip(),
        }

    def _on_add_gaussian_row_clicked(self) -> None:
        """Append a blank Gaussian row and rerun."""
        self._gaussian_row_manager.add_blank_row()

    def _on_gaussian_row_changed(self, *_args) -> None:
        """Persist Gaussian row edits and rerun."""
        self._sync_gaussian_dim_windows_from_ui()
        self.run()

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one filter execution request with validated parameters."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the filter-specific banner."""
        self._show_exception("general", exc)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _run(self):
        """Dispatch to the selected DASCore filter method."""
        patch = self._patch
        if patch is None:
            return None
        return self._execute_workflow_object(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _validated_task(self) -> FilterTask | None:
        """Return the current validated filter task, or None on invalid state.

        Preflight only: the task itself is built by the node spec, so the
        canvas and a headless caller run byte-identical tasks for the same
        parameters.
        """
        selected_filter = self.selected_filter
        if selected_filter not in _FILTER_NAMES:
            raise ValueError(f"Unknown filter: {selected_filter!r}")
        if self.apply_taper and self.taper_window.strip() and self._available_dims:
            parse_patch_text_value(self.taper_window, required=True)
        if selected_filter == "pass_filter":
            self._get_dim()
            parse_patch_text_value(
                self.low_bound,
                allow_none=True,
                allow_ellipsis=True,
            )
            parse_patch_text_value(
                self.high_bound,
                allow_none=True,
                allow_ellipsis=True,
            )
        elif selected_filter == "gaussian_filter":
            validated_gaussian_kwargs(self.gaussian_dim_windows, self._available_dims)
        elif selected_filter == "slope_filter":
            for value in self.slope_filt.split(","):
                stripped = value.strip()
                if stripped:
                    float(stripped)
        else:
            if not str(self._get_dim() or self.selected_dim or ""):
                return None
            parse_patch_text_value(self.filter_window, required=True)
            if selected_filter == "wiener_filter":
                parse_patch_text_value(
                    self.noise,
                    allow_none=True,
                    allow_quantity=False,
                )
        return NODE_SPEC.build_task(self.get_params())

    def _on_result(self, result) -> None:
        self.Outputs.patch.send(result)

    def _settings_control_map(self) -> dict[str, object]:
        """Map settings to their controls for unified apply_settings sync."""
        return {
            "selected_filter": self._filter_combo,
            "selected_dim": self._dim_combo,
        }

    def _linked_stacks(self) -> dict[object, object]:
        """The filter combo selects the per-filter parameter page."""
        return {self._filter_combo: self._stack}

    def get_params(self) -> FilterParams:
        """Return the current filter parameters as a typed pydantic model."""
        kind = self.selected_filter
        data: dict[str, object] = {
            "kind": kind,
            "dim": self.selected_dim,
            "apply_taper": bool(self.apply_taper),
            "taper_window": self.taper_window,
        }
        for model_field, setting in _PARAM_FIELDS[kind].items():
            data[model_field] = getattr(self, setting)
        if kind == "gaussian_filter":
            data["windows"] = list(self.gaussian_dim_windows or [])
        return TypeAdapter(FilterParams).validate_python(data)

    def apply_params(self, params: object, *, run: bool = True) -> dict[str, object]:
        """Apply a typed filter-parameter model (or its dict form) and re-run.

        Returns the prior widget settings (for undo), like ``apply_settings``.
        """
        return self.apply_settings(filter_settings_from_params(params), run=run)

    def _model_backed_attrs(self) -> set[str]:
        """Every attribute the filter models back (spanning all filter types)."""
        attrs = {
            "selected_filter",
            "selected_dim",
            "apply_taper",
            "taper_window",
            "gaussian_dim_windows",
        }
        for fields in _PARAM_FIELDS.values():
            attrs.update(fields.values())
        return attrs

    def _init_authoritative_state(self) -> None:
        """Restore Filter's attributes from the ``_state`` blob or model defaults.

        Filter holds attributes for every filter type at once, so seed them all
        from the member-model defaults, then overlay the persisted active type
        (active-type-only storage: inactive types reset to defaults on reload).
        """
        self.selected_filter = "pass_filter"
        for model_cls in _FILTER_MODELS:
            for setting, value in filter_settings_from_params(model_cls()).items():
                if setting != "selected_filter":
                    setattr(self, setting, value)
        params = (self._state or {}).get("params")
        if params:
            for setting, value in filter_settings_from_params(params).items():
                setattr(self, setting, value)

    def _sync_dependent_controls(self) -> None:
        """Re-derive dim visibility and mode from the selected filter."""
        self._sync_primary_dim_visibility(self.selected_filter)
        self._coerce_mode_for_filter(self.selected_filter)

    def get_task(self) -> Task:
        """Return the current filter semantics as a workflow task."""
        task = self._validated_task()
        if task is None:
            raise ValueError("current Filter state is not valid")
        return task


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Filter).run()
