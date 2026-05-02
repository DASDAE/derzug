"""
Generic task helpers used by widget adapters.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

from pydantic import Field

from .task import Task


class PatchPassThroughTask(Task):
    """Pass one patch through unchanged."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    def run(self, patch):
        """Return the input patch unchanged."""
        return patch


class ObjectPassThroughTask(Task):
    """Pass one arbitrary object through unchanged."""

    input_variables: ClassVar[dict[str, object]] = {"value": object}
    output_variables: ClassVar[dict[str, object]] = {"value": object}

    def run(self, value):
        """Return the input value unchanged."""
        return value


class PatchConfiguredMethodTask(Task):
    """Invoke one named patch method using stored arguments."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    method_name: str
    call_style: str = "plain"
    dim: Any | None = None
    dim_value: Any | None = None
    method_args: tuple[Any, ...] = ()
    method_kwargs: dict[str, Any] = Field(default_factory=dict)

    def run(self, patch):
        """Call the configured patch method with persisted arguments."""
        fn = getattr(patch, self.method_name)
        args = list(self.method_args)
        kwargs = dict(self.method_kwargs)
        if self.call_style == "positional_dim":
            args.insert(0, self.dim)
        elif self.call_style == "keyword_dim":
            kwargs[self.dim] = self.dim_value
        elif self.call_style != "plain":
            raise ValueError(f"unsupported call style {self.call_style!r}")
        return fn(*args, **kwargs)


class PatchRollingTask(Task):
    """Apply DASCore rolling aggregation with persisted settings."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    dim: str
    window: Any
    step: Any | None = None
    center: bool = False
    dropna: bool = False
    aggregation: str = "mean"

    def run(self, patch):
        """Apply the configured rolling aggregation to one patch."""
        rolling = patch.rolling(
            step=self.step,
            center=bool(self.center),
            **{self.dim: self.window},
        )
        out = getattr(rolling, self.aggregation)()
        if self.dropna:
            out = out.dropna(self.dim)
        return out


class PatchSelectionTask(Task):
    """Apply persisted patch-selection state to one patch."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    selection_payload: dict[str, Any] | None = None

    def run(self, patch):
        """Apply serialized patch-selection state to one patch."""
        from derzug.widgets.selection import SelectionState

        payload = self.selection_payload
        if not payload:
            return patch
        state = SelectionState()
        primed = state.prime_patch_state_from_settings(payload)
        if not primed:
            return patch
        state.set_patch_source(patch)
        return state.apply_to_patch(patch)


class PatchSelectionWithParamsTask(Task):
    """Apply patch-selection state and also expose public select parameters."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "select_params": object,
    }

    selection_payload: dict[str, Any] | None = None

    def run(self, patch):
        """Return the selected patch and matching SelectParams."""
        from derzug.models.selection import SelectParams
        from derzug.widgets.selection import SelectionState

        payload = self.selection_payload
        if not payload:
            return {"patch": patch, "select_params": SelectParams()}
        state = SelectionState()
        primed = state.prime_patch_state_from_settings(payload)
        if not primed:
            return {"patch": patch, "select_params": SelectParams()}
        state.set_patch_source(patch)
        return {
            "patch": state.apply_to_patch(patch),
            "select_params": state.to_select_params(),
        }


class MultiPassThroughTask(Task):
    """Pass selected named values through unchanged."""

    values: tuple[str, ...]
    port_names: tuple[str, ...] = ()

    def resolved_scalar_input_variables(self) -> dict[str, Any]:
        """Return one scalar input port per passthrough value name."""
        return {name: object for name in self.port_names}

    def resolved_scalar_output_variables(self) -> dict[str, Any]:
        """Return one scalar output port per passthrough value name."""
        return {name: object for name in self.port_names}

    def resolved_required_scalar_inputs(self) -> tuple[str, ...]:
        """Require all declared passthrough ports before activation."""
        return self.port_names

    def run(self, **kwargs):
        """Return the passthrough values in scalar or mapping form."""
        if len(self.port_names) == 1:
            return kwargs.get(self.port_names[0])
        return kwargs

    @classmethod
    def from_names(cls, names: tuple[str, ...]) -> MultiPassThroughTask:
        """Build a passthrough task instance for the given port names."""
        return cls(values=names, port_names=names)


class CallableTaskAdapter(Task):
    """Stable callable-backed task adapter used for workflow round-tripping."""

    function_code_path: str
    output_names: tuple[str, ...] = ()

    def _callable(self):
        """Resolve the configured callable for execution and port inference."""
        from derzug.workflow.graph import resolve_symbol

        fn = resolve_symbol(self.function_code_path)
        if inspect.isclass(fn) and issubclass(fn, Task):
            raise TypeError(
                f"{self.function_code_path!r} resolves to a Task subclass, "
                "not a callable"
            )
        if not callable(fn):
            raise TypeError(
                f"{self.function_code_path!r} did not resolve to a callable"
            )
        return fn

    def _spec(self):
        """Return normalized callable metadata for this adapter."""
        from derzug.utils.code2widget import _spec_from_callable

        return _spec_from_callable(
            self._callable(),
            output_names=self.output_names or None,
        )

    def resolved_scalar_input_variables(self) -> dict[str, Any]:
        """Return the normalized callable input ports."""
        return {
            input_spec.signal_name: input_spec.signal_type
            for input_spec in self._spec().inputs
        }

    def resolved_required_scalar_inputs(self) -> tuple[str, ...]:
        """Return normalized required callable inputs."""
        return tuple(
            input_spec.signal_name
            for input_spec in self._spec().inputs
            if not input_spec.has_default
        )

    def resolved_scalar_output_variables(self) -> dict[str, Any]:
        """Return the normalized callable output ports."""
        return {
            output_spec.signal_name: output_spec.signal_type
            for output_spec in self._spec().outputs
        }

    def run(self, **kwargs):
        """Execute the configured callable through the shared widget adapter path."""
        from derzug.utils.code2widget import INPUTS_NOT_READY, _invoke_spec_function

        spec = self._spec()
        values = _invoke_spec_function(spec, self._callable(), kwargs)
        if values is INPUTS_NOT_READY:
            return INPUTS_NOT_READY
        if spec.returns_dict:
            return {
                output_spec.signal_name: values.get(output_spec.name)
                for output_spec in spec.outputs
            }
        if len(spec.outputs) == 1:
            return values
        if isinstance(values, tuple):
            return dict(
                zip(
                    (output_spec.signal_name for output_spec in spec.outputs),
                    values,
                    strict=True,
                )
            )
        return values
