"""
Pipeline definitions and execution engine for the workflow system.
"""

from __future__ import annotations

import inspect
import json
import pickle
import platform
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import slanrod
import yaml
from dascore.utils.progress import track
from pydantic import Field

from ..core import SlanRodBaseModel
from ..utils.misc import FauxExecutor, _are_types_compatible
from ..utils.workflow import (
    ParameterBinder,
    PipeBuilder,
    hash_pipe_topology,
    topological_sort,
)
from .context import ExecutionContext
from .provenance import Provenance
from .task import Task


class Pipe(SlanRodBaseModel):
    """
    A directed acyclic graph (DAG) of tasks with dependency resolution and execution.
    """

    tasks: dict[str, Task] = Field(default_factory=dict)
    dependencies: dict[str, dict[str, str]] = Field(
        default_factory=dict
    )  # {task_id: {param_name: upstream_task_id}}
    output_task_id: str = ""  # The terminal task in this pipeline
    context_aware_tasks: dict[str, bool] = Field(
        default_factory=dict
    )  # Cached info about which tasks need context
    # Previous proviance to be attached (these are created in previous
    # steps of the data).
    source_provenance: tuple[Provenance, ...] = Field(default_factory=tuple)

    def __init__(self, task_or_tasks=None, **kwargs):
        """Instantiate a Pipe."""
        if isinstance(task_or_tasks, Task):
            # Single task pipeline
            task_id = task_or_tasks.fingerprint
            kwargs.update(
                {
                    "tasks": {task_id: task_or_tasks},
                    "dependencies": {task_id: {}},
                    "output_task_id": task_id,
                }
            )
        elif task_or_tasks is not None:
            # Standard creation with tasks dict
            kwargs["tasks"] = task_or_tasks

        # Analyze context requirements before initialization (since model will be
        # frozen)
        if "tasks" in kwargs:
            context_aware_tasks = {}
            for task_id, task in kwargs["tasks"].items():
                task_sig = inspect.signature(task.run)
                context_aware_tasks[task_id] = "context" in task_sig.parameters
            kwargs["context_aware_tasks"] = context_aware_tasks

        super().__init__(**kwargs)

    @classmethod
    def _merge_fanout_connections(cls, connections: list[Pipe]) -> Pipe:
        """Merge multiple fanout connections into a single pipe."""
        if not connections:
            return cls()

        tasks = {}
        dependencies = {}
        for conn in connections:
            tasks.update(conn.tasks)
            dependencies.update(conn.dependencies)

        # Use the last connection's output as the merged output
        output_id = connections[-1].output_task_id if connections else ""

        return cls(tasks=tasks, dependencies=dependencies, output_task_id=output_id)

    @classmethod
    def _create_pipe_from_single_task(cls, left_task: Task, right_task: Task) -> Pipe:
        """Create a pipe connecting two tasks."""
        # Get parameter info for right task
        right_sig = inspect.signature(right_task.run)
        right_params = list(right_sig.parameters.keys())

        if not right_params:
            raise ValueError("Right task must have at least one parameter")

        # Create tasks dict
        left_id = left_task.fingerprint
        right_id = right_task.fingerprint

        tasks = {left_id: left_task, right_id: right_task}

        # Connect left output to first parameter of right task
        first_param = right_params[0]
        dependencies = {left_id: {}, right_id: {first_param: left_id}}

        return cls(tasks=tasks, dependencies=dependencies, output_task_id=right_id)

    @classmethod
    def _create_multi_input_pipe(
        cls, inputs: dict | tuple | list, target: Task
    ) -> Pipe:
        """Create a pipe from multiple inputs to a single target task."""
        tasks, dependencies = ParameterBinder.create_dependencies(inputs, target)

        return cls(
            tasks=tasks,
            dependencies=dependencies,
            output_task_id=target.fingerprint,
        )

    @property
    def fingerprint(self) -> str:
        """
        Return a unique ID based on the pipeline's structure and contained tasks.

        Combines all task fingerprints with the network topology to create
        a stable identifier for the entire pipeline.
        """
        return hash_pipe_topology(
            self.tasks,
            self.dependencies,
            self.output_task_id,
            self.source_provenance,
        )

    def __hash__(self) -> int:
        """Hash based on the stable fingerprint."""
        return hash(self.fingerprint)

    def _to_dict(self) -> dict[str, Any]:
        """Convert pipeline to a dictionary for serialization."""
        tasks_list = []
        for task_id, task in self.tasks.items():
            task_dict = task.model_dump(mode="json")
            task_dict["__class__"] = (
                f"{task.__class__.__module__}:{task.__class__.__qualname__}"
            )
            task_dict["__task_id__"] = task_id
            if hasattr(task, "__version__"):
                task_dict["__version__"] = task.__version__
            tasks_list.append(task_dict)

        return {
            "tasks": tasks_list,
            "dependencies": self.dependencies,
            "output_task_id": self.output_task_id,
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Pipe:
        """Create pipeline from dictionary representation."""
        import importlib

        tasks = {}
        for task_data in data["tasks"]:
            # Extract metadata
            if "__class__" not in task_data or "__task_id__" not in task_data:
                raise ValueError(
                    "Missing __class__ or __task_id__ in task phase_shift_validator"
                )
            class_path = task_data.pop("__class__")
            task_id = task_data.pop("__task_id__")
            task_data.pop("__version__", "1.0")  # Remove version, not used

            # Import the task class
            try:
                module_path, class_name = class_path.split(":")
                module = importlib.import_module(module_path)
                task_class = getattr(module, class_name)
            except (ImportError, AttributeError, ValueError) as e:
                raise ValueError(f"Could not import task class {class_path}: {e}")

            # Create task instance
            task = task_class(**task_data)
            tasks[task_id] = task

        dependencies = data["dependencies"]
        output_task_id = data["output_task_id"]

        pipeline = cls(
            tasks=tasks, dependencies=dependencies, output_task_id=output_task_id
        )

        return pipeline

    def to_json(self, path: str | Path, *, indent: int = 2) -> None:
        """Save pipeline to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(), f, indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, path: str | Path) -> Pipe:
        """Load pipeline from JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls._from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        """Save pipeline to YAML file."""
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._to_dict(), f, sort_keys=True, default_flow_style=False)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Pipe:
        """Load pipeline from YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data)

    def run(
        self,
        *args,
        debug: bool = False,
        failed_pipeline_path: str | Path | None = None,
        **kwargs,
    ) -> Any:
        """Execute the pipeline with the provided inputs."""
        return self._run(
            *args, debug=debug, failed_pipeline_path=failed_pipeline_path, **kwargs
        )

    def sorted_tasks(self):
        """Return tasks in topological execution order."""
        # Topological sort to determine execution order
        sorted_tasks = topological_sort(self.tasks, self.dependencies)
        return sorted_tasks

    def _get_task_kwargs(self, task_id, results, initial_args, initial_inputs, context):
        """Get the kwargs to feed to a specific task."""
        task = self.tasks[task_id]
        task_deps = self.dependencies.get(task_id, {})
        # Build input arguments for this task
        kwargs = {}
        # Handle task dependencies (from upstream task results)
        if task_deps:
            for param_name, upstream_task_id in task_deps.items():
                kwargs[param_name] = results[upstream_task_id]
        else:
            kwargs = self._get_initial_args(
                task,
                kwargs,
                initial_args,
                initial_inputs,
            )
        # Inject context if task expects it (using cached information)
        if self.context_aware_tasks.get(task_id, False):
            kwargs["context"] = context
        return kwargs

    def _get_initial_args(self, task, kwargs, initial_args, initial_kwargs):
        """Get initial arguments for pipeline execution."""
        if initial_args:
            # Multiple args, bind positionally
            task_sig = inspect.signature(task.run)
            param_names = list(task_sig.parameters.keys())
            for i, arg in enumerate(initial_args):
                # We can only bind as many
                if i > len(param_names):
                    raise ValueError(
                        "Length of input args exceed number of first task inputs"
                    )
                # If this is a SlanRod source, we need to unpack it.
                # It should be length one or issue warning.
                if isinstance(arg, slanrod.Source):
                    arg = arg.get_single_data()
                kwargs[param_names[i]] = arg
        # Add keyword inputs (these override positional if same name)
        kwargs.update(initial_kwargs)
        return kwargs

    def _run(
        self,
        *initial_args,
        failed_pipeline_path: str | Path | None = None,
        debug=False,
        **initial_inputs,
    ) -> Any:
        """
        Execute the pipeline and return the output of the terminal task.

        Parameters
        ----------
        *initial_args
            Positional arguments for pipeline input tasks.
        failed_pipeline_path : str | Path | None, optional
            Path to save pipeline state if execution fails.
        debug
            If True, drop into a breakpoint then rerun failed task.
        **initial_inputs
            Keyword arguments for pipeline input tasks.

        Returns
        -------
        Any
            Output of the terminal task.
        """
        results = {}
        context = ExecutionContext(
            pipe=self,
            results=results,
        )
        sorted_tasks = self.sorted_tasks()
        task = None
        kwargs = {}
        try:
            # Execute tasks in topological order
            for task_id in sorted_tasks:
                task = self.tasks[task_id]
                kwargs = self._get_task_kwargs(
                    task_id, results, initial_args, initial_inputs, context
                )
                # Execute the task
                results[task_id] = task.run(**kwargs)
            # Return the output of the terminal task
            return results[self.output_task_id]
        except Exception:
            # Save pipeline to failed_pipeline_path if provided
            if failed_pipeline_path is not None:
                self._save_failed_pipeline(failed_pipeline_path)
            if debug:
                breakpoint()  # NOQA
                if task is not None:
                    results[task_id] = task.run(**kwargs)
            else:
                raise

    def map(self, source: Any, debug=False, executor=None) -> Any:
        """
        Apply the pipeline to a source (normal iterable or slanrod.Source).

        Parameters
        ----------
        source
            An iterable whose contents will be pushed through the pipeline.
        debug
            If True, drop into a breakpoint then rerun failed task and dont
            use the progress bar.
        executor
            If Not None, an executor to run things in parallel.
        """
        pipe = self
        # Add the source provenance if it exists.
        if isinstance(source, slanrod.Source):
            pipe = pipe.new(source_provenance=source.provenance.to_source_provenance())
        desc = f"Applying pipeline: {pipe} to {source=}"
        exc = FauxExecutor() if executor is None else executor
        iterable = source
        if not debug:
            iterable = track(iterable, description=desc)
        return exc.map(pipe.run, iterable, debug=debug)

    def get_provenance(
        self,
        source_provenance: tuple[Provenance, ...] = (),
        **additional_metadata,
    ) -> Provenance:
        """
        Create a run manifest with complete provenance information.

        The manifest includes the serialized pipeline, slanrod version, creation
        timestamp, system info, and any additional metadata provided.

        Parameters
        ----------
        source_provenance
            Provenance from previous jobs. This comes from input Sources,
            hence it is not attached to the pipe.
        **additional_metadata
            Additional key-value pairs to include in the manifest.

        Returns
        -------
        Provenance
            Complete run manifest with provenance information.
        """
        return Provenance(
            pipe=self,
            slanrod_version=getattr(slanrod, "__version__", "unknown"),
            created_at=datetime.now(timezone.utc),
            python_version=platform.python_version(),
            system_info={
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            metadata=additional_metadata,
            source_provenance=source_provenance,
        )

    def save(self, path: str | Path, *, indent: int = 2) -> None:
        """
        Save a lightweight pipeline manifest to disk.

        Parameters
        ----------
        path
            Destination file path. The extension determines the format:
            `.yaml`/`.yml` for YAML, otherwise JSON is used.
        indent
            JSON indentation level.
        """
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        payload = {
            "pipeline": self._to_dict(),
            "pipeline_fingerprint": self.fingerprint,
        }
        fmt = path.suffix.lstrip(".").lower()
        if fmt in ("yaml", "yml"):
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload, indent=indent, sort_keys=True), encoding="utf-8"
            )

    def _save_failed_pipeline(self, failed_pipeline_path: str | Path) -> None:
        """Save pipeline to pickle file when execution fails."""
        failed_path = Path(failed_pipeline_path)
        failed_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"failed_pipeline_{timestamp}_{unique_id}.pkl"
        full_path = failed_path / filename

        with open(full_path, "wb") as f:
            pickle.dump(self, f)

    # Pipeline composition operators
    def __or__(self, other):
        """Support pipeline | task and pipeline | pipeline syntax."""
        if isinstance(other, Task):
            # Pipeline | Task
            return self._chain_with_task(other)
        elif isinstance(other, Pipe):
            # Pipeline | Pipeline
            return self._chain_with_pipeline(other)
        else:
            return NotImplemented

    def __ror__(self, other):
        """Support dict/tuple | pipeline syntax."""
        if isinstance(other, dict | tuple | list):
            return self._create_multi_input_pipe(other, self)
        else:
            return NotImplemented

    def _chain_with_task(self, task: Task) -> Pipe:
        """Chain this pipeline with a single task."""
        # Get the output of this pipeline
        output_task_id = self.output_task_id
        if not output_task_id:
            raise ValueError("Pipeline has no output task to chain from")

        # Create new pipeline combining this one with the new task
        new_task_id = task.fingerprint
        new_tasks = {**self.tasks, new_task_id: task}

        # Get first parameter of new task for connection
        task_sig = inspect.signature(task.run)
        task_params = list(task_sig.parameters.keys())
        if not task_params:
            raise ValueError("Task to chain must have at least one parameter")

        first_param = task_params[0]
        new_dependencies = {
            **self.dependencies,
            new_task_id: {first_param: output_task_id},
        }

        return Pipe(
            tasks=new_tasks,
            dependencies=new_dependencies,
            output_task_id=new_task_id,
        )

    def _chain_with_pipeline(self, other_pipeline: Pipe) -> Pipe:
        """Chain this pipeline with another pipeline."""
        # Merge configurations using PipeBuilder
        pipe1_config = (self.tasks, self.dependencies, self.output_task_id)
        pipe2_config = (
            other_pipeline.tasks,
            other_pipeline.dependencies,
            other_pipeline.output_task_id,
        )

        tasks, dependencies, output_id = PipeBuilder.merge_pipe_configs(
            pipe1_config, pipe2_config
        )

        return Pipe(tasks=tasks, dependencies=dependencies, output_task_id=output_id)

    def __call__(self, *args, **kwargs):
        """Make pipes callable - equivalent to calling run() method."""
        return self.run(*args, **kwargs)

    def validate(self, strict_types: bool = False) -> None:
        """
        Validate the pipeline structure and task dependencies.

        This method checks for:
        - Circular dependencies in the task graph
        - Missing or invalid task references
        - Missing required task parameters
        - Type compatibility between task outputs and inputs (if strict_types=True)

        Parameters
        ----------
        strict_types
            If True, perform strict type checking based on type hints.
            If False, only validate basic pipeline structure.

        Raises
        ------
        ValueError
            If pipeline structure is invalid.
        TypeError
            If task dependency types are incompatible (when strict_types=True).
        """
        # Basic structure validation
        if self.output_task_id not in self.tasks:
            raise ValueError(f"Output task '{self.output_task_id}' not found in tasks")

        # Check that all dependency references are valid
        for task_id, task_deps in self.dependencies.items():
            if task_id not in self.tasks:
                raise ValueError(f"Task '{task_id}' in dependencies not found in tasks")
            for param_name, upstream_id in task_deps.items():
                if upstream_id not in self.tasks:
                    raise ValueError(
                        f"Upstream task '{upstream_id}' referenced by '{task_id}' "
                        f"not found in tasks"
                    )

        # Check for circular dependencies
        try:
            topological_sort(self.tasks, self.dependencies)
        except ValueError as e:
            raise ValueError(f"Invalid pipeline structure: {e}")

        # Validate task parameter requirements
        self._validate_task_parameters(strict_types)

    def _validate_task_parameters(self, strict_types: bool = False) -> None:
        """Validate task parameter requirements and types."""
        for task_id, task in self.tasks.items():
            task_deps = self.dependencies.get(task_id, {})
            sig = inspect.signature(task.run)

            # Get required parameters (no default, not *args/**kwargs)
            required_params = set()
            param_by_name = {}
            for p in sig.parameters.values():
                param_by_name[p.name] = p
                if (
                    p.name not in ("self", "context")
                    and p.default is inspect.Parameter.empty
                    and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                ):
                    required_params.add(p.name)

            # Check for missing required parameters (only if task has dependencies)
            if task_deps:
                missing_params = required_params - set(task_deps.keys())
                if missing_params:
                    raise ValueError(
                        f"Task {task.__class__.__name__} missing required "
                        f"dependencies: {missing_params}"
                    )

            # Check for extra parameters (unless **kwargs present)
            has_var_keyword = any(
                p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not has_var_keyword:
                param_names = {
                    p.name for p in sig.parameters.values() if p.name != "self"
                }
                extra_params = set(task_deps.keys()) - param_names
                if extra_params:
                    raise ValueError(
                        f"Task {task.__class__.__name__} has unexpected dependencies: "
                        f"{extra_params}"
                    )

            # Type checking if requested
            if strict_types:
                for param_name, upstream_id in task_deps.items():
                    if param_name in param_by_name:
                        param = param_by_name[param_name]
                        upstream_task = self.tasks[upstream_id]
                        self._check_type_compatibility(param, upstream_task, task)

    def _check_type_compatibility(
        self, param: inspect.Parameter, upstream_task: Task, target_task: Task
    ) -> None:
        """Check if upstream task output is compatible with target parameter type."""
        if param.annotation == inspect.Parameter.empty:
            return  # Skip if no type annotation

        upstream_sig = inspect.signature(upstream_task.run)
        upstream_return_type = upstream_sig.return_annotation

        if upstream_return_type == inspect.Signature.empty:
            return  # Skip if upstream has no return annotation

        target_hints = get_type_hints(target_task.run)
        expected_type = target_hints.get(param.name, param.annotation)

        upstream_hints = get_type_hints(upstream_task.run)
        actual_type = upstream_hints.get("return", upstream_return_type)
        expected_origin = get_origin(expected_type)
        actual_origin = get_origin(actual_type)
        union_origins = (Union, types.UnionType)

        if expected_type == actual_type:
            return

        if expected_origin in union_origins:
            expected_args = get_args(expected_type)
            if actual_type in expected_args:
                return
            if actual_origin in union_origins:
                actual_args = get_args(actual_type)
                if any(arg in expected_args for arg in actual_args):
                    return
            if any(_are_types_compatible(arg, actual_type) for arg in expected_args):
                return

        if expected_origin is not None and actual_origin is not None:
            if expected_origin == actual_origin:
                return

        if _are_types_compatible(expected_type, actual_type):
            return

        # Check for incompatible types
        raise TypeError(
            f"Parameter '{param.name}' of task {target_task.__class__.__name__} "
            f"expects type {expected_type} but upstream task "
            f"{upstream_task.__class__.__name__} returns {actual_type}"
        )

    def to_mermaid(
        self, include_params: bool = True, show_fingerprints: bool = False
    ) -> str:
        """
        Generate Mermaid flowchart code for visualizing the pipeline.

        Parameters
        ----------
        include_params
            If True, include parameter names on dependency edges.
        show_fingerprints
            If True, show task fingerprints instead of class names.

        Returns
        -------
        str
            Mermaid flowchart code that can be rendered in supported viewers.
        """
        lines = ["flowchart TD"]

        # Generate node definitions
        for task_id, task in self.tasks.items():
            if show_fingerprints:
                label = f"{task.__class__.__name__}\\n{task_id}"
            else:
                label = task.__class__.__name__

            # Use different shapes for different node types
            if task_id == self.output_task_id:
                # Output task gets a different shape
                lines.append(f'    {task_id}["{label}"]')
                lines.append(
                    "    classDef outputTask fill:#e1f5fe,stroke:#01579b,"
                    "stroke-width:3px"
                )
                lines.append(f"    class {task_id} outputTask")
            else:
                lines.append(f'    {task_id}["{label}"]')

        # Generate dependency edges
        for task_id, task_deps in self.dependencies.items():
            for param_name, upstream_id in task_deps.items():
                if include_params:
                    edge_label = f"|{param_name}|"
                    lines.append(f"    {upstream_id} -->{edge_label} {task_id}")
                else:
                    lines.append(f"    {upstream_id} --> {task_id}")

        # Add styling
        lines.extend(
            [
                "    classDef default fill:#f9f9f9,stroke:#333,stroke-width:2px",
                "    classDef task fill:#fff3e0,stroke:#f57c00,stroke-width:2px",
            ]
        )

        # Apply task styling to all non-output tasks
        non_output_tasks = [
            tid for tid in self.tasks.keys() if tid != self.output_task_id
        ]
        if non_output_tasks:
            task_list = " ".join(non_output_tasks)
            lines.append(f"    class {task_list} task")

        return "\n".join(lines)


ExecutionContext.model_rebuild(_types_namespace={"Pipe": Pipe})
Provenance.model_rebuild(_types_namespace={"Pipe": Pipe})
