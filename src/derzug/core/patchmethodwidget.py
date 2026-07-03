"""Declarative base for simple patch-in/patch-out DASCore method widgets.

Many processing widgets share the same shape: one or more controls (fixed-choice
dropdowns and/or numeric spin boxes, optionally a dimension chooser) feeding a
single configured DASCore patch method. ``PatchMethodWidget`` captures that
boilerplate so a concrete widget only declares its metadata, settings, and an
``_OPTIONS`` spec of :class:`ComboOption` / :class:`SpinOption`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import dascore as dc
from AnyQt.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.patchdimwidget import PatchDimWidget
from derzug.settings import Setting
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


@dataclass(frozen=True)
class ComboOption:
    """One fixed-choice dropdown backing a configured patch-method argument.

    Parameters
    ----------
    setting
        Name of the ``Setting`` attribute this dropdown reads and writes.
    choices
        Allowed values; the first is the fallback when a persisted value is
        no longer valid.
    role
        How the selected value feeds the task: ``"arg"`` (positional method
        argument), ``"kwarg"`` (keyword argument), or ``"method"`` (the value
        is itself the method name to call).
    label
        UI label shown above the dropdown.
    combo_attr
        Optional attribute name to bind the ``QComboBox`` to (e.g.
        ``"_type_combo"``), for callers/tests that reference it directly.
    kwarg_name
        Method keyword name for ``role="kwarg"`` (defaults to ``setting``).
    """

    setting: str
    choices: tuple[str, ...]
    role: str = "arg"
    label: str = ""
    combo_attr: str = ""
    kwarg_name: str = ""

    @property
    def default(self) -> str:
        """Return the fallback value (the first choice)."""
        return self.choices[0]


@dataclass(frozen=True)
class SpinOption:
    """One numeric spin control backing a configured patch-method argument.

    ``role`` mirrors :class:`ComboOption` but adds ``"dim_value"``, which feeds
    the ``keyword_dim`` call style (the value passed under the selected
    dimension). ``decimals=0`` selects an integer spin box.
    """

    setting: str
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.01
    decimals: int = 3
    role: str = "kwarg"
    label: str = ""
    spin_attr: str = ""
    kwarg_name: str = ""

    @property
    def is_int(self) -> bool:
        """Return True when this option renders as an integer spin box."""
        return self.decimals == 0

    def coerce(self, value: object) -> float | int:
        """Return ``value`` clamped to the configured range and numeric type."""
        number = int(value) if self.is_int else float(value)
        clamped = max(self.minimum, min(self.maximum, number))
        return int(clamped) if self.is_int else clamped


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

    selected_dim = Setting("")

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

    def get_task(self) -> Task:
        """Assemble the configured patch-method task from current controls."""
        method_name = self.method_name
        method_args: list[object] = []
        method_kwargs: dict[str, object] = {}
        dim_value: object | None = None
        for option in self._OPTIONS:
            if isinstance(option, ComboOption):
                value = self._coerce_combo(option)
            else:
                value = self._coerce_spin(option)
            if option.role == "method":
                method_name = value
            elif option.role == "kwarg":
                method_kwargs[option.kwarg_name or option.setting] = value
            elif option.role == "dim_value":
                dim_value = value
            else:
                method_args.append(value)

        extra: dict[str, object] = {}
        if self.uses_dim:
            extra["dim"] = self._get_dim() or self.selected_dim
        if dim_value is not None:
            extra["dim_value"] = dim_value
        return PatchConfiguredMethodTask(
            method_name=method_name,
            call_style=self.call_style,
            method_args=tuple(method_args),
            method_kwargs=method_kwargs,
            **extra,
        )
