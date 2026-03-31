# Streaming Engine Spec

This document describes the streaming-first execution model implemented in `derzug.workflow`.

## Core API

- `Task` instances are immutable workflow specs.
- Ports are declared with class dicts:
  - `input_variables`
  - `output_variables`
  - `stream_inputs`
  - `stream_outputs`
- `final_output` names the scalar output produced by a generator `return`.
- `PipeBuilder` builds the DAG and `Pipe` executes it.
- `STREAM_END` is the explicit end-of-stream sentinel for generator consumers.

## Execution Rules

- Scalar task: `run(...)` returns one scalar result and runs once when its scalar inputs are ready.
- Stream producer: `run(...)` is a generator and `yield`s items for a declared `stream_output`.
- Per-item stream consumer: declare one `stream_input` and use a normal `run(event)` method; the task is called once per emitted item.
- Generator stream consumer: declare one `stream_input`, implement `run()` as a coroutine, receive streamed items via `.send(...)`, and return a final scalar through `final_output`.
- `pipe.run(...)` completes only after all active generators are exhausted.
- `pipe.map(source)` is outer iteration over many source items and reuses the same streaming semantics per item.

## Validation Rules

- The workflow graph remains a static DAG.
- A task may not have more than one streaming input.
- A task may not declare more than one streaming output in v1.
- A live stream may not have multiple consumers in v1.
- Scalar outputs connect only to scalar inputs.
- Stream outputs connect only to stream inputs.

## Example

```python
from derzug.workflow import STREAM_END, PipeBuilder, Task


class DetectEvents(Task):
    input_variables = {"patch": list}
    stream_outputs = {"event": int}

    def run(self, patch):
        for item in patch:
            if item % 2 == 0:
                yield item


class CollectEvents(Task):
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


builder = PipeBuilder()
detect = builder.add(DetectEvents(), name="detect")
collect = builder.add(CollectEvents(), name="collect")
builder.connect(detect, collect, from_output="event", to_input="event")
pipe = builder.build()
result = pipe.run([1, 2, 3, 4], output_keys=["collect"])
assert result["collect"] == [2, 4]
```

## Results And Serialization

- `Results` exposes `result[key]`, `result.ok`, `result.errors`, and `result.provenance`.
- Requested outputs should be scalar ports or `final_output` ports.
- Serialized workflows store task code paths, parameters, graph edges, and stable node names.
- Serialized workflows do not store live generator state.

## Current Non-Goals

- pickling/snapshotting live generator state
- automatic tee/materialize behavior
- implicit joins of multiple streaming inputs
- public access to live streams through `Results`
