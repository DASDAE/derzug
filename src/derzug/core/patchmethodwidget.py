"""Declarative base for simple patch-in/patch-out DASCore method widgets.

Many processing widgets share the same shape: one or more controls (fixed-choice
dropdowns and/or numeric spin boxes, optionally a dimension chooser) feeding a
single configured DASCore patch method. ``PatchMethodWidget`` captures that
boilerplate so a concrete widget only declares its metadata, settings, and an
``_OPTIONS`` spec of :class:`ComboOption` / :class:`SpinOption`.

The option specs themselves and the task they build are Qt-free and live in
:mod:`derzug.nodes._options`; this module is only their Qt rendering.
"""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.nodes._options import (
    ComboOption,
    SpinOption,
    build_params_model,
    options_task_factory,
)
from derzug.settings import Setting
from derzug.workflow import Task


def _setting_default(cls: type, name: str, fallback: object) -> object:
    """Return the default of the named ``Setting`` declared on ``cls``."""
    for klass in cls.__mro__:
        value = klass.__dict__.get(name)
        if isinstance(value, Setting):
            return value.default
    return fallback


class PatchMethodWidget(PatchDimWidget, openclass=True):
    """Base for patch-in/patch-out widgets calling one configured DASCore method.

    Subclasses declare metadata (``name`` etc.), a ``Setting`` per option, and:

    - ``method_name``: the DASCore ``Patch`` method to call, unless an option
      with ``role="method"`` supplies it.
    - ``call_style``: forwarded to :class:`PatchConfiguredMethodTask`.
    - ``uses_dim``: whether a dimension chooser is shown and passed to the task.
    - ``_OPTIONS``: the controls to render and feed into the task.
    - ``error_key``: the ``Error`` slot used for execution failures.
    """

    method_name: ClassVar[str] = ""
    call_style: ClassVar[str] = "positional_dim"
    uses_dim: ClassVar[bool] = True
    error_key: ClassVar[str] = "operation_failed"
    parameters_title: ClassVar[str] = "Parameters"
    _OPTIONS: ClassVar[tuple[ComboOption | SpinOption, ...]] = ()

    class Error(PatchDimWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("Operation failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._option_combos: dict[str, QComboBox] = {}
        self._option_spins: dict[str, QDoubleSpinBox | QSpinBox] = {}
        box = gui.widgetBox(self.controlArea, self.parameters_title)

        for option in self._OPTIONS:
            if isinstance(option, ComboOption):
                self._build_combo(box, option)
            else:
                self._build_spin(box, option)

        if self.uses_dim:
            gui.widgetLabel(box, "Dimension:")
            self._dim_combo = QComboBox(box)
            box.layout().addWidget(self._dim_combo)
            self._dim_combo.currentTextChanged.connect(self._on_dim_changed)

    def _build_combo(self, box: object, option: ComboOption) -> None:
        """Create and wire one dropdown control for ``option``."""
        gui.widgetLabel(box, option.label or f"{option.setting}:")
        combo = QComboBox(box)
        combo.addItems(option.choices)
        box.layout().addWidget(combo)
        if getattr(self, option.setting) not in option.choices:
            setattr(self, option.setting, option.default)
        combo.setCurrentText(getattr(self, option.setting))
        combo.currentTextChanged.connect(
            lambda value, setting=option.setting: self._on_option_changed(
                setting, value
            )
        )
        self._option_combos[option.setting] = combo
        if option.combo_attr:
            setattr(self, option.combo_attr, combo)

    def _build_spin(self, box: object, option: SpinOption) -> None:
        """Create and wire one numeric spin control for ``option``."""
        gui.widgetLabel(box, option.label or f"{option.setting}:")
        spin = QSpinBox(box) if option.is_int else QDoubleSpinBox(box)
        if not option.is_int:
            spin.setDecimals(option.decimals)
        spin.setRange(option.minimum, option.maximum)
        spin.setSingleStep(option.step)
        spin.setValue(option.coerce(getattr(self, option.setting)))
        box.layout().addWidget(spin)
        spin.valueChanged.connect(
            lambda value, setting=option.setting: self._on_option_changed(
                setting, value
            )
        )
        self._option_spins[option.setting] = spin
        if option.spin_attr:
            setattr(self, option.spin_attr, spin)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the configured method."""
        self._set_patch_input(patch)
        self.run()

    def _rebind_dynamic_controls(self) -> None:
        """Refresh the dim chooser only for widgets that use one."""
        if self.uses_dim:
            self._refresh_dims()

    def __init_subclass__(cls, **kwargs) -> None:
        """Auto-derive a params model for each concrete option-based widget.

        Widgets that declare a ``node_spec`` already got theirs from the spec;
        this only covers the ones not yet migrated to the node layer.
        """
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("_OPTIONS"):
            return
        if "node_spec" not in cls.__dict__ and cls.node_spec is not None:
            raise TypeError(
                f"{cls.__name__} overrides _OPTIONS but inherits node_spec "
                f"{cls.node_spec.name!r}; declare its own node_spec, or set "
                "node_spec = None to fall back to a generated params model"
            )
        if cls.node_spec is not None:
            return
        cls.params_model = build_params_model(
            f"{cls.__name__}Params",
            cls._OPTIONS,
            uses_dim=cls.uses_dim,
            dim_default=_setting_default(cls, "selected_dim", ""),
        )

    def _settings_control_map(self) -> dict[str, object]:
        """Map each option setting (and the dim chooser) to its control."""
        controls: dict[str, object] = {
            **self._option_combos,
            **self._option_spins,
        }
        if self.uses_dim and hasattr(self, "_dim_combo"):
            controls["selected_dim"] = self._dim_combo
        return controls

    def _params_field_map(self) -> dict[str, str]:
        """Map each params-model field to its backing setting."""
        field_map = {option.setting: option.setting for option in self._OPTIONS}
        if self.uses_dim:
            field_map["dim"] = "selected_dim"
        return field_map

    def _on_dim_changed(self, value: str) -> None:
        """Persist the selected dimension and rerun."""
        self.selected_dim = value
        self.run()

    def _on_option_changed(self, setting: str, value: object) -> None:
        """Persist one changed option and rerun."""
        setattr(self, setting, value)
        self.run()

    def _coerce_combo(self, option: ComboOption) -> str:
        """Return a valid value for ``option``, resetting to the default if not."""
        value = getattr(self, option.setting)
        if value in option.choices:
            return value
        setattr(self, option.setting, option.default)
        combo = self._option_combos.get(option.setting)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentText(option.default)
            combo.blockSignals(False)
        return option.default

    def _coerce_spin(self, option: SpinOption) -> float | int:
        """Return ``option`` clamped to range, updating the control if changed."""
        coerced = option.coerce(getattr(self, option.setting))
        if coerced != getattr(self, option.setting):
            setattr(self, option.setting, coerced)
            spin = self._option_spins.get(option.setting)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(coerced)
                spin.blockSignals(False)
        return coerced

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the widget's execution-error banner."""
        self._show_exception(self.error_key, exc)

    def _coerce_options(self) -> None:
        """Pull every option's persisted value back into range, syncing controls."""
        for option in self._OPTIONS:
            if isinstance(option, ComboOption):
                self._coerce_combo(option)
            else:
                self._coerce_spin(option)

    def get_task(self) -> Task:
        """Assemble the configured patch-method task from current controls."""
        self._coerce_options()
        if self.uses_dim:
            # Side effect: resyncs ``selected_dim`` to an available dimension.
            self._get_dim()
        params = self.get_params()
        if self.node_spec is not None and self.node_spec.task_factory is not None:
            return self.node_spec.build_task(params)
        return options_task_factory(
            params,
            method_name=self.method_name,
            call_style=self.call_style,
            uses_dim=self.uses_dim,
            options=self._OPTIONS,
        )
