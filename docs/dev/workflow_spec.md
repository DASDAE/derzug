# Workflow Spec

This document defines the public contract for the DerZug streaming workflow engine.

## Core Model

- `Task` is an immutable, validated operation with a `run(...)` method.
- A task fingerprint includes code path, code hash, version, and parameter values.
- `@task` turns an importable function into a task type. Serialization uses the original function's `module:qualname`.
- Local functions and lambdas are not supported for serialized workflows.
- Ports are declared explicitly first:
  - `input_variables`
  - `output_variables`
  - `stream_inputs`
  - `stream_outputs`
- Output names may be inferred conservatively when `output_variables` is omitted and the return form is simple.
- Docstring scraping is not part of the workflow contract.

```python
from derzug.workflow import Task, task


class Bandpass(Task):
    fmin: float
    fmax: float

    def run(self, patch) -> object:
        return patch.pass_filter(frequency=(self.fmin, self.fmax))


@task
def qc(patch) -> object:
    return patch
```

## Graph Model

- `PipeBuilder` is mutable and used to assemble the DAG.
- `add(task, name=None)` inserts a copy of the task and returns a unique node handle.
- `connect(from_handle, to_handle, from_output=None, to_input=None)` creates an edge.
- `build()` returns an immutable `Pipe`.
- `Pipe` stores tasks, edges, and optional stable names. It is serializable and loadable without Orange.
- `compile_workflow(...)` returns a `CompiledWorkflow`, not a bare `Pipe`.
- `CompiledWorkflow` wraps the compiled `pipe` and an optional default mapped source chosen from the active source widget.
- Stable names are the public way to request non-terminal outputs after deserialization.
- The graph remains a static DAG even when execution is streaming.
- A task may not have more than one streaming input.
- Live stream branching is rejected in v1.

```python
from derzug.workflow import PipeBuilder

builder = PipeBuilder()
load = builder.add(LoadPatch(path="data.h5"))
band = builder.add(Bandpass(fmin=10, fmax=40))
check = builder.add(qc(), name="qc")
builder.connect(load, band)
builder.connect(band, check)
pipe = builder.build()
pipe.to_json("workflow.json")
```

## Execution

- `pipe.run(...)` executes one workflow invocation.
- `pipe.map(source, ...)` executes the full pipe for each item and returns a lazy iterator of per-item results.
- `CompiledWorkflow.run(...)` delegates to the compiled `pipe`.
- `CompiledWorkflow.map(source=None, ...)` uses an explicit source when provided, otherwise the compiled default mapped source.
- Canvas source widgets without workflow tasks compile as external input boundaries; callers may satisfy them with `run(...)` kwargs or `map(source=...)`.
- `strict=True` raises on the first task failure.
- `strict=False` records task failures, skips dependent nodes, and still returns `Results`.
- Scalar inputs bind once per node activation.
- Stream outputs emit zero or more values by `yield`.
- A task with `stream_inputs` may consume those values incrementally.
- `final_output` exposes a generator return value as a scalar output.
- `STREAM_END` is the explicit end-of-stream sentinel for generator consumers.
- `output_keys` may use node handles or stable names.
- Run provenance is supplied at `run()` / `map()` time, not stored on `Pipe`.

```python
from derzug.workflow import STREAM_END


class Collect(Task):
    stream_inputs = {"event": int}
    output_variables = {"events": list[int]}
    final_output = "events"

    def run(self):
        items = []
        event = yield None
        while event is not STREAM_END:
            items.append(event)
            event = yield None
        return items
```

```python
results = pipe.run(patch, output_keys=["qc"], strict=False, provenance=source.provenance)
if not results.ok:
    print(results.errors)
    print(results.skipped)
```

## Results And Invalidation

- A `Results` object exposes `results[key]`, `results.get(...)`, `results.has_output(...)`, `results.ok`, `results.errors`, `results.skipped`, and `results.provenance`.
- `Pipe.fingerprint` identifies the workflow as a whole.
- Requested terminal outputs must be scalar outputs or `final_output` values in v1.
- Direct retrieval of a live stream is not public API.

```python
result = pipe.run(patch, output_keys=["split"])
result["split", "left"]
result.get("split", "left")
result.has_output("split", "left")
```

## Provenance

- Provenance is a run record, not part of the workflow definition.
- A provenance record includes the executed pipe, workflow fingerprint, DerZug version, Python/system metadata, and upstream source provenance.
- Source provenance is attached when recording a run and forms a chain across pipelines.

## Serialization Rules

Serialized workflow artifacts contain only portable workflow data:

- task code paths
- task versions and parameters
- graph structure
- optional stable node names

Serialized workflow artifacts do not contain:

- Orange widget state
- UI-only metadata
- execution results

## Non-Goals

- Orange widget implementation details
- automatic duplication of live streams
- implicit joins of multiple streaming inputs
- compatibility with removed pre-workflow internal models
