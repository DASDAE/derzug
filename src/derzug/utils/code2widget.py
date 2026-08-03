"""Helpers for turning Python callables into task-backed DerZug widgets.

The callable introspection itself is Qt-free and lives in
:mod:`derzug.utils.callable_spec`; this module wraps it in an Orange widget.
"""

from __future__ import annotations

from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.utils.callable_spec import (
    _UNSET,
    INPUTS_NOT_READY,
    _kwargs_from_input_values,
    _normalize_class_name,
    _spec_from_callable,
    task_from_callable,
)


def widget_class_from_callable(
    *,
    fn,
    name: str,
    description: str,
    icon: str,
    category: str,
    priority: float | int,
    keywords: tuple[str, ...] = (),
    output_names: tuple[str, ...] | None = None,
) -> type[ZugWidget]:
    """Create a DerZug widget subclass from one callable."""
    if not callable(fn):
        raise TypeError("fn must be callable")
    spec = _spec_from_callable(fn, output_names=output_names)

    inputs_namespace: dict[str, object] = {"__doc__": "Input signal definitions."}
    outputs_namespace: dict[str, object] = {"__doc__": "Output signal definitions."}
    class_namespace: dict[str, object] = {
        "__doc__": f"Generated widget for {spec.function_name}.",
        "name": name,
        "description": description,
        "icon": icon,
        "category": category,
        "keywords": keywords,
        "priority": priority,
        "want_main_area": False,
        "_generated_function": staticmethod(fn),
        "_generated_spec": spec,
        "_generated_task_cls": task_from_callable(fn, output_names=output_names),
    }

    for input_spec in spec.inputs:
        signal = Input(input_spec.name, input_spec.signal_type, auto_summary=False)
        inputs_namespace[input_spec.signal_name] = signal

        def _make_handler(spec_name: str):
            def _handler(self, value):
                self._input_values[spec_name] = value
                self.run()

            return _handler

        class_namespace[f"set_{input_spec.signal_name}"] = signal(
            _make_handler(input_spec.signal_name)
        )

    for output_spec in spec.outputs:
        outputs_namespace[output_spec.signal_name] = Output(
            output_spec.name,
            output_spec.signal_type,
            auto_summary=False,
        )

    class Error(ZugWidget.Error):
        general = Msg("Generated widget failed: {}")

    class_namespace["Error"] = Error
    class_namespace["Inputs"] = type("Inputs", (), inputs_namespace)
    class_namespace["Outputs"] = type("Outputs", (), outputs_namespace)

    def _generated_init(self) -> None:
        super(generated_cls, self).__init__()
        self._input_values = {
            input_spec.signal_name: _UNSET for input_spec in self._generated_spec.inputs
        }

    def _supports_async_execution(self) -> bool:
        return True

    def _build_execution_request(self):
        ready_kwargs = _kwargs_from_input_values(
            self._generated_spec,
            self._input_values,
        )
        if ready_kwargs is INPUTS_NOT_READY:
            return None
        return WidgetExecutionRequest(
            workflow_obj=self.get_task(),
            input_values=ready_kwargs,
            output_names=tuple(
                output_spec.signal_name for output_spec in self._generated_spec.outputs
            ),
        )

    def get_task(self):
        return self._generated_task_cls()

    def _on_result(self, result) -> None:
        if result is _UNSET or result is None:
            for output_spec in self._generated_spec.outputs:
                getattr(self.Outputs, output_spec.signal_name).send(None)
            return
        if self._generated_spec.returns_dict or len(self._generated_spec.outputs) > 1:
            if not isinstance(result, dict):
                self._show_error_message("general", "expected mapping result")
                for output_spec in self._generated_spec.outputs:
                    getattr(self.Outputs, output_spec.signal_name).send(None)
                return
            for output_spec in self._generated_spec.outputs:
                getattr(self.Outputs, output_spec.signal_name).send(
                    result.get(output_spec.signal_name)
                )
            return
        output_spec = self._generated_spec.outputs[0]
        getattr(self.Outputs, output_spec.signal_name).send(result)

    class_namespace["__init__"] = _generated_init
    class_namespace["_supports_async_execution"] = _supports_async_execution
    class_namespace["_build_execution_request"] = _build_execution_request
    class_namespace["_on_result"] = _on_result
    class_namespace["get_task"] = get_task

    generated_name = _normalize_class_name(name)
    generated_cls = type(
        generated_name,
        (ZugWidget,),
        class_namespace,
        openclass=True,
    )
    return generated_cls


def function_to_widget(
    fn,
    *,
    name: str,
    description: str,
    icon: str,
    category: str,
    priority: float | int,
    keywords: tuple[str, ...] = (),
    output_names: tuple[str, ...] | None = None,
) -> type[ZugWidget]:
    """Convenience wrapper that returns a task-backed widget class."""
    return widget_class_from_callable(
        fn=fn,
        name=name,
        description=description,
        icon=icon,
        category=category,
        priority=priority,
        keywords=keywords,
        output_names=output_names,
    )


__all__ = [
    "INPUTS_NOT_READY",
    "function_to_widget",
    "task_from_callable",
    "widget_class_from_callable",
]
