"""Declarative option specs shared by simple configured-method nodes.

Many processing nodes are one DASCore ``Patch`` method plus a handful of
fixed-choice or numeric arguments. This module holds that declaration — the
option dataclasses, the derived pydantic params model, and the task factory —
with no Qt involved, so a node module can describe itself and build its task
headlessly. ``derzug.core.patchmethodwidget`` renders the same options as Qt
controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import create_model

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

    def coerce(self, value: object) -> str:
        """Return ``value`` when it is an allowed choice, else the default."""
        return value if value in self.choices else self.default


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
    default: float = 0.0

    @property
    def is_int(self) -> bool:
        """Return True when this option renders as an integer spin box."""
        return self.decimals == 0

    def coerce(self, value: object) -> float | int:
        """Return ``value`` clamped to the configured range and numeric type."""
        number = int(value) if self.is_int else float(value)
        clamped = max(self.minimum, min(self.maximum, number))
        return int(clamped) if self.is_int else clamped


OptionSpec = ComboOption | SpinOption


def build_params_model(
    name: str,
    options: tuple[OptionSpec, ...],
    *,
    uses_dim: bool,
    dim_default: str = "",
) -> type:
    """Derive a pydantic params model from an option spec and dim chooser."""
    fields: dict[str, tuple[object, object]] = {}
    if uses_dim:
        fields["dim"] = (str, dim_default)
    for option in options:
        if isinstance(option, ComboOption):
            fields[option.setting] = (Literal[tuple(option.choices)], option.default)
        else:
            field_type = int if option.is_int else float
            fields[option.setting] = (field_type, field_type(option.default))
    return create_model(name, **fields)


def options_task_factory(
    params: Any = None,
    *,
    method_name: str = "",
    call_style: str = "positional_dim",
    uses_dim: bool = True,
    options: tuple[OptionSpec, ...] = (),
    dim_default: str = "",
) -> PatchConfiguredMethodTask:
    """Build the configured patch-method task described by ``options``.

    ``params`` is an instance of the model returned by :func:`build_params_model`;
    ``None`` means "use every option's declared default". Bind the keyword
    arguments with :func:`functools.partial` to get a node's ``task_factory``.
    """
    method_args: list[object] = []
    method_kwargs: dict[str, object] = {}
    dim_value: object | None = None
    for option in options:
        raw = option.default if params is None else getattr(params, option.setting)
        value = option.coerce(raw)
        if option.role == "method":
            method_name = value
        elif option.role == "kwarg":
            method_kwargs[option.kwarg_name or option.setting] = value
        elif option.role == "dim_value":
            dim_value = value
        else:
            method_args.append(value)

    extra: dict[str, object] = {}
    if uses_dim:
        extra["dim"] = dim_default if params is None else getattr(params, "dim", "")
    if dim_value is not None:
        extra["dim_value"] = dim_value
    return PatchConfiguredMethodTask(
        method_name=method_name,
        call_style=call_style,
        method_args=tuple(method_args),
        method_kwargs=method_kwargs,
        **extra,
    )


__all__ = (
    "ComboOption",
    "OptionSpec",
    "SpinOption",
    "build_params_model",
    "options_task_factory",
)
