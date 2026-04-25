"""Workflow-object execution helpers for DerZug widgets."""

from __future__ import annotations

from derzug.core.widget_runtime import WidgetExecutionRequest
from derzug.workflow import Pipe, Task


class WorkflowExecutionMixin:
    """Shared task/pipe execution helpers used by widget classes."""

    def _build_task_execution_request(
        self,
        workflow_obj: Task | Pipe | None,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ) -> WidgetExecutionRequest | None:
        """Return a standard request for one canonical task-backed execution."""
        if workflow_obj is None:
            return None
        return WidgetExecutionRequest(
            workflow_obj=workflow_obj,
            input_values=input_values,
            output_names=output_names,
        )

    @staticmethod
    def _execute_execution_request(request: WidgetExecutionRequest):
        """Execute one captured request in a worker thread."""
        if request.execute is not None:
            return request.execute()
        return WorkflowExecutionMixin._execute_task_or_pipe_static(
            request.workflow_obj,
            input_values=request.input_values or {},
            output_names=request.output_names,
        )

    def _execute_workflow_object(
        self,
        workflow_obj: Task | Pipe | None,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one validated workflow object and normalize widget outputs."""
        if workflow_obj is None:
            return None
        try:
            result = self._execute_task_or_pipe(
                workflow_obj,
                input_values=input_values,
                output_names=output_names,
            )
        except Exception as exc:
            self._handle_execution_exception(exc)
            return None
        return self._unwrap_execution_result(result, output_names)

    def _execute_task_or_pipe(
        self,
        workflow_obj: Task | Pipe,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one task or sub-pipe for interactive widget use."""
        return self._execute_task_or_pipe_static(
            workflow_obj,
            input_values=input_values,
            output_names=output_names,
        )

    @staticmethod
    def _execute_task_or_pipe_static(
        workflow_obj: Task | Pipe,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one task or sub-pipe without touching widget state."""
        if workflow_obj is None:
            raise TypeError("workflow_obj may not be None without request.execute")
        if isinstance(workflow_obj, Task):
            raw = workflow_obj.run(**input_values)
            return WorkflowExecutionMixin._normalize_task_outputs(
                workflow_obj, raw, output_names
            )
        if isinstance(workflow_obj, Pipe):
            results = workflow_obj.run(**input_values, output_keys=list(output_names))
            return {name: results.get(name) for name in output_names}
        raise TypeError(f"unsupported workflow object {workflow_obj!r}")

    @staticmethod
    def _unwrap_execution_result(result, output_names: tuple[str, ...]):
        """Return the single requested output value when possible."""
        if isinstance(result, dict) and len(output_names) == 1:
            return result.get(output_names[0])
        return result

    @staticmethod
    def _normalize_task_outputs(
        task: Task,
        raw: object,
        output_names: tuple[str, ...],
    ):
        """Normalize task return values for widget `_on_result()` handlers."""
        mapping = task.resolved_scalar_output_variables()
        if not mapping:
            return None
        if len(mapping) == 1:
            value = raw
            if len(output_names) == 1:
                return value
            return {output_names[0]: value}
        if isinstance(raw, dict):
            return {name: raw.get(name) for name in output_names}
        if isinstance(raw, tuple) and len(raw) == len(mapping):
            normalized = dict(zip(mapping.keys(), raw, strict=True))
            return {name: normalized.get(name) for name in output_names}
        raise ValueError(
            f"task {task.__class__.__name__} returned {raw!r} "
            f"but outputs are {tuple(mapping)}"
        )
