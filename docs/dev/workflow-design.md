# DerZug Workflow Engine Design

## Vision

DerZug is a front-end for creating, testing, and debugging computational workflows. Orange provides the interactive IDE. Workflows are exported as portable artifacts and run headlessly from scripts or in larger compute environments.

**A DerZug widget** is a visual editor for one or more task parameters. It emits a configured `Task` (or `Pipe` sub-graph) as its output signal. The widget's job is configuration, not execution. Orange makes that configuration interactive.

---

## Primary Use Case

**Build and debug in Orange → export → run headlessly from a script.**

```python
pipe = Pipe.from_json("my_workflow.json")
results = pipe.map(source)
```

- Orange owns interactive execution (reactive, signal-driven).
- The script owns batch execution. Same `Pipe` object, two callers.
- The serialized `Pipe` is the portable artifact — Orange-free. It contains only task class/function paths and parameter values. No widget internals, no Orange signal metadata.
- `.ows` is an Orange-specific concern, not the canonical format.

---

## Task Model

### `Task` Base Class

Tasks are immutable, validated Pydantic models. Each subclass implements `run()`.

```python
class BandpassTask(Task):
    fmin: float
    fmax: float

    def run(self, patch: dc.Patch) -> dc.Patch:
        """
        Returns
        -------
        result : dc.Patch
            Bandpass-filtered patch.
        """
        ...
```

- Named **inputs** come from `run()` parameters.
- Named **outputs** come from the return annotation and the `Returns` numpy docstring section. Introspected automatically — no separate declaration needed. Multi-output tasks return a tuple; the engine unpacks it using the output spec.
- Tasks return raw Python values. The execution engine handles wrapping and error capture.
- `Task` never imports display libraries. It is safe to use in headless environments.

### `@task` Decorator

For end users writing lightweight scripted tasks:

```python
@task
def bandpass(patch: dc.Patch, fmin: float, fmax: float) -> dc.Patch:
    """..."""
    ...
```

The decorator produces a proper `Task` subclass. Rules:
- Serialization key is the original **function's** `module:qualname`, not the generated class name. On deserialization, the function is reimported and the decorator re-applied.
- Required parameters (no default) become required Pydantic fields — not silently `Optional`.
- `run()` is bound directly from the function, not via a descriptor.
- Local-scope and lambda functions are unsupported for serialization by design.

Both widget authors (`Task` subclasses) and end users (`@task`) share the same base and execution engine. Any user-defined task can be dropped into an Orange workflow if it is importable.

### Fingerprinting

Each task carries two identity concepts:

```python
{
    "code_path": "mymodule:BandpassTask",  # stable module:qualname for reimport
    "code_hash": "a3f9...",               # AST hash of class/function body only
    "version": "1.0",                     # explicit version bump for breaking changes
    "parameters": {"fmin": 10.0, "fmax": 100.0},
}
```

- `code_path` — for serialization round-trips. Stable across parameter changes; breaks on rename/move.
- `code_hash` — for change detection. Changes when logic changes; stable across renames and base class refactors.
- `version` — for explicit breaking-change signalling.

The task fingerprint is a hash of all three plus parameters.

---

## Graph Model

### `PipeBuilder` and `Pipe`

Two objects, not one:

- **`PipeBuilder`** — mutable. Orange holds this while the user wires nodes. Exposes `add()`, `connect()`, `disconnect()`. The `|` scripting operator builds one implicitly.
- **`Pipe`** — frozen snapshot produced by `builder.build()`. Used for execution, fingerprinting, serialization, and provenance. `Pipe.fingerprint` is purely structural: node set + edges. Nothing run-specific.

### Node Handles

`builder.add(task)` copies the task, assigns a UUID, and returns that UUID as a **node handle** (plain string). Node identity in the graph is the handle, not task content.

```python
builder = PipeBuilder()
load  = builder.add(FileLoader(path="data/"))
band1 = builder.add(BandpassTask(fmin=10, fmax=100))
band2 = builder.add(BandpassTask(fmin=10, fmax=100))  # identical task, distinct node
qc    = builder.add(QCCheck())
```

- **Task fingerprint** — what the task does. Identical for `band1` and `band2`.
- **Node handle** — where it sits in the graph. Unique per `add()` call.

`add()` always copies. A single instance cannot occupy two graph positions. External references to the original task do not affect the graph.

### Edges

The graph stores an explicit edge list, not a nested dict:

```python
edges: tuple[Edge, ...]
# Edge = (from_node_handle, from_output, to_node_handle, to_input)
```

### Connection API

```python
# Fully explicit
builder.connect(split, band,   from_output="high", to_input="patch")
builder.connect(split, merger, from_output="low",  to_input="a")
builder.connect(band,  merger,                     to_input="b")

# Inferred when unambiguous
builder.connect(load, band)   # single output → first required unwired param
```

Inference rules:
- `from_output` omitted: use the task's only output; error if multiple.
- `to_input` omitted: use the first required unwired parameter; error if ambiguous.

Port names shown in the Orange UI come directly from introspected input/output names.

### No `output_task_id`

There is no designated terminal node. The caller specifies what to capture at execution time via `output_keys`. Default is all terminal nodes (nodes with no downstream consumers).

### `|` Operator

Sugar for simple linear chains only:

```python
pipe = FileLoader(path="data/") | BandpassTask(fmin=10, fmax=100) | QCCheck()
```

Works only when both sides are unambiguous: single output on the left, single unwired required parameter on the right. Fan-out requires `PipeBuilder`.

---

## Execution

### `output_keys` and Memory Management

```python
results = pipe.run(source, output_keys=[band2, qc])
results = pipe.map(source, output_keys=[qc])
```

The execution engine retains only results needed by a downstream node or listed in `output_keys`. Everything else is dropped immediately after its consumers run. Critical for large patches.

```python
for task_id in topological_order:
    results[task_id] = task.run(**kwargs)
    if not _still_needed(task_id, remaining_tasks, output_keys):
        del results[task_id]
```

### `Results` Object

```python
results = pipe.run(source, output_keys=[band, split])

results[band]           # raw output; raises if that node failed
results[split, "high"]  # named output of a multi-output node
results[split]          # error — must specify output name

results.ok              # True if all output_keys nodes succeeded
results.errors          # {node_handle: exception} for failed nodes
results.provenance      # Provenance record for this run
```

### Failure Modes

- **`strict=True` (default):** raises on first task failure. For headless batch runs.
- **`strict=False`:** runs all reachable nodes, collects errors. Nodes depending on a failed upstream are skipped. For Orange's interactive execution — per-node error state is visible in the UI.

```python
results = pipe.run(source, strict=False)
if not results.ok:
    for handle, exc in results.errors.items():
        print(f"node {handle} failed: {exc}")
```

### `map()` Returns a Lazy Iterator

```python
for result in pipe.map(source, output_keys=[qc]):
    if result.ok:
        process(result[qc])
    else:
        log(result.errors)

# Collected when needed
all_results = list(pipe.map(source, output_keys=[qc]))
```

Memory footprint of each `Results` is bounded by `output_keys`.

### No `ExecutionContext` Injection

Tasks receive all inputs via explicit edges only. There is no `context_aware_tasks` mechanism. Nothing bypasses the graph topology.

---

## Provenance

### Separation of Concerns

`Pipe.fingerprint` is purely structural. `source_provenance` does not live on `Pipe` — it lives on the `Provenance` run record. The same `Pipe` run twice on different data has the same fingerprint.

### Lineage Across Pipelines

`Source` objects carry their provenance chain. The caller passes it forward when recording the next run.

```python
# Step 1: raw DAS → preprocessed
preprocess_pipe = Pipe.from_json("preprocess.json")
results = preprocess_pipe.map(raw_source)
sink.write(results, provenance=preprocess_pipe.get_provenance())

# Step 2: preprocessed → QC checked
qc_source = sink.get_source()  # carries Step 1's provenance
qc_pipe = Pipe.from_json("qc.json")
results = qc_pipe.map(qc_source)
sink.write(results, provenance=qc_pipe.get_provenance(
    source_provenance=qc_source.provenance
))

# Step 3: QC checked → analysis
analysis_source = sink.get_source()  # carries Steps 1+2 provenance chain
analysis_pipe = Pipe.from_json("analysis.json")
results = analysis_pipe.map(analysis_source)
sink.write(results, provenance=analysis_pipe.get_provenance(
    source_provenance=analysis_source.provenance
))
```

The final `Provenance` record is a nested tree:

```
Provenance
├── pipe: analysis.json (fingerprint: abc123)
├── created_at: 2026-03-17T14:00:00Z
├── system_info: {...}
└── source_provenance:
    └── Provenance
        ├── pipe: qc.json (fingerprint: def456)
        └── source_provenance:
            └── Provenance
                ├── pipe: preprocess.json (fingerprint: ghi789)
                └── source_provenance: ()
```

From any output file you can answer:
- What workflow produced this? (pipe fingerprint)
- What code was in that workflow? (task fingerprints + AST hashes)
- What data went in? (upstream chain)
- Has the workflow changed since this was produced? (compare fingerprints)

**Open question:** maximum provenance chain depth — full chain always, or truncate after N levels?

---

## Distributed Execution

The unit of distribution is the **entire pipeline mapped over inputs**, not individual tasks as scheduler primitives.

Each worker receives a `Pipe` and one input, runs the full pipeline locally, returns a `Results`. Parallelism comes from processing many inputs simultaneously, not from parallelizing a single item's internal graph.

```python
pipe = Pipe.from_json("my_workflow.json")

pipe.map(source)                              # serial
pipe.map(source, executor=RayExecutor())      # distributed
pipe.map(source, executor=DaskExecutor())
```

**Design constraints:**
- `Task` and `Pipe` must be fully picklable — workers serialize the pipeline before dispatch.
- The core model never imports Ray or Dask. Users bring their own executor.
- `FauxExecutor` (serial) is the default. Distributed executors are drop-in replacements via the `executor` parameter on `map()`.

**Ray vs Dask:** DASCore uses Dask arrays internally. If patches are lazy Dask arrays, Ray workers may conflict with Dask's scheduler. Patches should be fully materialized before entering `Pipe.map()` by default. Lazy Dask array support is a later decision.

**Not in scope for v1:** intra-pipeline parallelism (parallel branches within a single run).

---

## Orange / Widget Integration

`ZugWidget` and `ZugModel` are replaced entirely. No backward compatibility.

### What a Widget Becomes

An Orange widget is a thin Qt shell over a `Task` subclass:
- Renders Qt UI for configuring the task's parameters.
- Calls `builder.add(task)` and `builder.connect(...)` to register in the active `PipeBuilder` when wiring changes.
- Emits a configured `Task` (or `Pipe` sub-graph) as its Orange output signal when parameters change.

The widget does not own execution. It does not hold result state.

### Execution in Orange

Orange drives execution by calling `pipe.run(strict=False)` when the graph changes. It diffs the new `Pipe` fingerprint against the last executed one to determine stale nodes and re-executes only the affected subgraph. Per-node error state from `results.errors` is surfaced in the UI.

### Interactive Configuration Widgets

A display widget that captures user configuration (e.g. Waterfall with a visual trim selector) emits a configured downstream `Task` as its output signal — e.g. `PatchTrim(start=1.2, end=4.7)`. The display is Orange-only. The emitted task is what appears in the serialized `Pipe` and runs headlessly. The widget is a visual configurator; the task is the portable artifact.

---

## What to Absorb from Existing Code

| Concept | Source | Disposition |
|---|---|---|
| Immutable task instances, fingerprints, versioning | `workflow/task.py` | Keep, fix `@task` decorator |
| Named input/output introspection | `models/computation.py` | Absorb into task model |
| `ComputationResult` ok/err contract | `models/computation.py` | Absorb into `Results` |
| Docstring parsing | `models/computation.py` | Keep |
| Topological sort | `workflow/utils` | Keep |
| `Provenance` / `Sink` / `Source` concepts | `workflow/` | Keep, fix `source_provenance` placement |
| `slanrod.*` imports and base models | `workflow/` | Remove entirely |
| `context_aware_tasks` / `ExecutionContext` injection | `workflow/pipe.py` | Remove entirely |
| `output_task_id` | `workflow/pipe.py` | Remove entirely |
| `matplotlib` import in `Task` | `workflow/task.py` | Remove |
| `phase_shift_validator` and Slanrod domain language | throughout | Remove |

---

## DASCore Integration

The workflow core is DASCore-agnostic. `dc.Patch` and other DASCore types flow through tasks as opaque Python objects. Type annotation compatibility checking works via standard Python type hints — no DASCore-specific logic in the execution engine. DASCore awareness lives in individual task implementations and widgets.

---

## Design Review

### Findings and Responses

**1. Fingerprint story is too weak for invalidation**

`Pipe.fingerprint` is defined as "node set + edges" — a purely structural whole-pipe hash. This has two problems: (a) parameter or code changes on a node don't change graph topology, so they would be invisible to a topology-only fingerprint; (b) a single whole-pipe hash can't tell Orange *which* nodes are stale — only whether *anything* changed.

**Response:** Introduce two distinct concepts:

- **`node_invalidation_key(handle)`** — per-node, computed as `hash(task_fingerprint, sorted(upstream node_invalidation_keys))`. Captures task identity (code + params + version) and the full upstream dependency closure. If any upstream node changes, all downstream invalidation keys change automatically.
- **`Pipe.fingerprint`** — whole-pipe identity, computed as `hash(all node_invalidation_keys + edge list)`. Answers: "has anything changed at all?"

Orange's re-execution logic uses *per-node invalidation keys* to find stale nodes: compare old and new per-node keys, re-execute nodes whose key changed plus their downstream dependents. The whole-pipe fingerprint is for provenance and serialization identity only — it is not used for stale-node detection.

```python
# Initial pipe: load → bandpass(fmin=10) → qc
pipe_v1 = builder.build()
keys_v1 = {h: pipe_v1.node_invalidation_key(h) for h in pipe_v1.handles}

# User changes bandpass fmin to 20 — topology unchanged, params changed
builder.update(band, BandpassTask(fmin=20, fmax=100))
pipe_v2 = builder.build()
keys_v2 = {h: pipe_v2.node_invalidation_key(h) for h in pipe_v2.handles}

stale = [h for h in pipe_v2.handles if keys_v1.get(h) != keys_v2[h]]
# → [band_handle, qc_handle]  (load unchanged; band and everything downstream stale)
```

---

**2. Runtime data path missing for interactive widgets**

The doc says widgets emit configured `Task` objects and do not hold result state. But a Waterfall trim selector only works if the widget can *receive and render live patch data*. A configuration channel is defined; a data channel is not.

**Response:** Add a two-channel widget model to the Orange integration:

- **Configuration channel (widget output):** the widget emits a configured `Task` when the user changes parameters. This is what enters the `Pipe` graph and what appears in the serialized artifact.
- **Data channel (widget input):** after each execution, Orange routes `results[node_handle]` back to the widget that owns that node — a standard Orange input signal. The widget uses this to render live data. This is Orange-internal plumbing; it does not affect the `Pipe` model or headless execution.

Waterfall example under the two-channel model:
- *Input signal (data channel):* receives `dc.Patch` — Orange routes the execution result for the Waterfall's node handle back to it after each run so it can render live data.
- *Output signal (configuration channel):* emits `PatchTrim(start=1.2, end=4.7)` when the user sets trim via the visual selector.

```python
class WaterfallWidget(OWWidget):
    # Configuration channel — enters the Pipe graph
    class Outputs:
        trim_task = Output("Trim", PatchTrim)

    # Data channel — Orange routes execution results back here
    class Inputs:
        patch = Input("Patch", dc.Patch)

    @Inputs.patch.handler
    def set_patch(self, patch: dc.Patch | None):
        self._patch = patch
        self._render()          # update the waterfall display

    def _on_trim_changed(self, start: float, end: float):
        self.Outputs.trim_task.send(PatchTrim(start=start, end=end))
```

---

**3. `output_keys` keyed by ephemeral handles breaks the headless API**

Node handles are UUIDs returned by `builder.add()` at construction time. After `Pipe.from_json(...)` no handles exist in the caller's scope — there is no stable way to request a specific intermediate node's output by handle.

**Response:** Add stable named outputs:

- `builder.add(task, name="qc")` — optional stable name stored alongside the handle in the `Pipe`.
- Serialized `Pipe` includes a `named_outputs: {name: handle}` mapping.
- `output_keys` accepts either handles (during construction) or names (always, including post-deserialization): `output_keys=["qc"]`.
- `results["qc"]` works identically to `results[handle]`.
- `pipe.get_handle("qc")` retrieves the handle by name for callers that need it.
- **Headless default rule:** without `output_keys`, only terminal nodes are returned. Terminal nodes are identifiable by assigned name or task class name.

```python
# Construction time — assign stable names
builder = PipeBuilder()
load = builder.add(FileLoader(path="data/"))
band = builder.add(BandpassTask(fmin=10, fmax=100))
qc   = builder.add(QCCheck(), name="qc")          # stable name
builder.connect(load, band)
builder.connect(band, qc)
pipe = builder.build()

# During construction: handle or name both work
results = pipe.run(source, output_keys=[qc])       # by handle
results = pipe.run(source, output_keys=["qc"])     # by name

# After deserialization: only name works (handle is gone)
pipe2 = Pipe.from_json("my_workflow.json")
results = pipe2.run(source, output_keys=["qc"])    # fine
results["qc"]                                      # fine

# Retrieve handle from name if needed
handle = pipe2.get_handle("qc")
```

---

**4. Provenance granularity inconsistent between `run()` and `map()`**

`Results.provenance` implies per-item provenance. But the sink example passes the entire `map()` result as a single batch object with one `pipe.get_provenance()` call — treating a lazy iterator as a batch. This conflates the per-item and batch levels.

**Response:** Clarify two levels and fix the sink example:

- **Per-item provenance:** each `Results` object yielded by `map()` carries its own `results.provenance` — created by the execution engine during the run with the item's specific timestamp and system info. `pipe.get_provenance()` produces a template; `results.provenance` is the per-item instantiation.
- **`sink.write()` accepts a single `Result`**, not a batch. The sink extracts `result.provenance` internally.
- **Batch manifest (optional):** a `BatchProvenance` object can collect all per-item provenance records from a `map()` run for audit purposes — a separate concern from per-item provenance.

Corrected sink example:

```python
# Step 1: raw DAS → preprocessed (per-item write)
for result in preprocess_pipe.map(raw_source):
    sink.write(result)  # result.provenance is per-item

# Step 2: preprocessed → QC (source carries per-item provenance chain)
qc_source = sink.get_source()
for result in qc_pipe.map(qc_source):
    sink.write(result)
```
