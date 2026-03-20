# Workflow-Core Design Evaluation

## Vision

The vision is to have DerZug be a front-end to creating, testing, and debugging computational workflows. Then they can be run from the command or in larger compute environments.

A derzug Widget: a visual editor for one or more task parameters that emits a configured Task (or Pipe) as its output signal. The widget's job is configuration, not execution. Orange just     
  makes that configuration interactive.

## Summary
Treat the new `workflow/*` package as the candidate foundation for DerZug's future internal graph model, but do not merge it by replacing `models/computation.py` directly. The target design is an internal, headless workflow graph whose nodes are task instances, with Orange acting as a UI/frontend over that graph. The near-term work should be a design/cleanup pass that extracts the valid DerZug concepts from the imported module, removes Slanrod-specific assumptions, and defines how current computation metadata maps into the new model.

## Key Design Direction
- Internal graph becomes the long-term source of truth, not Orange `.ows` alone.
- One internal node should represent a configured task instance.
- Execution supports two exclusive modes:
  - batch DAG execution for headless runs, provenance, and testing — owned by `Pipe`
  - interactive, signal-driven execution for UI-driven workflows — owned by Orange, unchanged
- `models/computation.py` should not remain the primary model long-term.
  - Its callable introspection, ports, docs, and result-wrapping behavior should be absorbed into the task/node design rather than preserved as a parallel core abstraction.
- Each processing widget holds one `Task` (or small fixed `Pipe`), renders Qt controls for its parameters, and delegates computation to `task.run()`. Orange's signal graph handles data routing between widgets — this is not replaced.
- The compiled `Pipe` is the portable artifact. Widgets are not nodes in a shared live graph during interactive use; they are compiled into one only on export or headless run.
- Orange is the authoritative execution model for interactive use. `Pipe` is the authoritative execution model for headless/batch use.

## Implementation Changes
- Define a DerZug-native task model that absorbs the useful parts of both systems:
  - from `workflow.task`: immutable configured task instances, fingerprints, versioning
  - from `models.computation`: callable/class introspection, named inputs/outputs, documented warnings/exceptions, structured invocation results
- Split the current imported workflow code into three conceptual layers before any merge:
  - task definition/introspection layer
  - graph/execution layer
  - provenance/serialization layer
- Remove all imported-project leakage before adopting anything as core:
  - replace `slanrod.*` imports, names, docs, and base models
  - remove unrelated domain language like `phase_shift_validator`
  - audit helper dependencies such as `utils.workflow`, `core` base classes, and constants for DerZug fit
- Redesign execution around a unified result model:
  - each task execution yields structured success/failure output
  - graph execution aggregates task results without losing traceback/provenance
- Define the replacement for `ComputationSpec` as task metadata rather than a separate subsystem:
  - callable/class source path
  - parameter/input/output specs
  - ordering and type annotations
  - task identity/fingerprint inputs
- Plan for dual persistence:
  - internal graph JSON/YAML format for headless and portable workflows
  - `.ows` compatibility as a frontend persistence/import-export concern, not the only persisted graph form
- Treat current `computation.py` as concept inventory, not as the target structure:
  - preserve its port/docstring/result ideas
  - do not keep it as a long-term peer model beside task/pipe
- Add `get_task() -> Task | Pipe` abstract method on `ZugWidget` for all processing widgets.
- Port-name contract: widget signal names must match task port names (enforced at compile time). `Input("patch", dc.Patch)` ↔ `task.run(patch: dc.Patch, ...)`. `Output("patch", dc.Patch)` ↔ docstring `Returns` entry named `patch`.
- Add `derzug.workflow.compiler` module with `compile_workflow(orange_workflow) -> Pipe`.

## Design Validation Work
- First review the imported workflow tests and classify them:
  - tests that express desired DerZug behavior and should survive conceptually
  - tests that only validate Slanrod-specific APIs and should be dropped
- Produce a compatibility matrix between current computation concepts and future task concepts:
  - callable function
  - callable class
  - inputs/parameters/outputs
  - invocation result/error contract
  - node identity
  - graph connections
  - workflow serialization
  - provenance/run manifests
- Decide the minimum v1 internal graph API:
  - task instance model
  - edge/dependency model
  - graph container (`Pipe`)
  - batch execution (`strict=True/False`)
  - serialization boundary
  - compilation layer (`derzug.workflow.compiler`, `get_task()` protocol, port-name contract)
- Keep the first merge milestone architectural, not migratory:
  - DerZug-native workflow package shape
  - cleaned task model
  - explicit mapping from old computation concepts
  - no immediate widget rewiring until the internal contract is stable

## Test Plan
- Preserve behavior-level tests for:
  - task fingerprint stability and version sensitivity
  - graph topology hashing/fingerprint changes
  - task execution success/failure contracts
  - provenance generation and serialization
  - graph serialization/deserialization round-trips
  - batch execution semantics: full run with `strict=True/False`
- Add acceptance tests for DerZug-specific integration:
  - a task created from a callable/class retains input/output/doc metadata
  - graph execution returns structured task results with traceback data
  - `compile_workflow` produces a correct `Pipe` from a mock Orange topology (no Qt required)
  - `get_task()` returns a task whose port names match the widget's signal names
  - compiled `Pipe` serializes, deserializes, and runs headlessly end-to-end
- Drop or rewrite tests that enforce imported-project names, modules, or base-class assumptions.

## Assumptions
- This is a design-evaluation and cleanup effort first, not an immediate replacement of current runtime wiring.
- The desired end state is a DerZug-native internal workflow graph with full portable serialization and provenance, with Orange serving as one UI over that graph.
- The imported `workflow/*` code is conceptually valuable but structurally not ready to merge without substantial renaming, dependency removal, and API redesign.

---

## Code Review (2026-03-17)

### What's Right

- Correct diagnosis: the imported workflow code is structurally Slanrod, not DerZug. Conceptually useful, structurally not adoptable as-is.
- Right sequencing: don't rip out `computation.py` yet. Absorb its concepts, don't merge blindly.
- Test classification is essential. `test_pipe.py` imports from `slanrod.workflow` directly — essentially none of the existing workflow tests currently test DerZug code.

### Gaps and Critiques

**1. The two execution modes are under-specified — this is the crux.**
The plan says support "batch DAG execution" and "incremental UI propagation" using "the same result contract." But:
- In Orange, execution is reactive: a widget receives a signal, re-runs, emits. Who drives re-execution in the internal graph — the widget or the graph?
- Does a changed-parameter event re-execute all downstream nodes or only invalidated ones?
- Does "incremental propagation" mean the internal graph owns observable node state, or does Orange drive it and serialize to the internal format?

The plan doesn't answer any of these. Without that, the execution layer cannot be designed. The key unresolved question: **is the goal for the internal graph to own execution with Orange as observer, or for Orange to own execution with the internal graph as a serializable snapshot?** These lead to fundamentally different designs.

**2. `output_task_id` is a single-output assumption baked into the core model.**
`Pipe.output_task_id: str` means every pipeline has exactly one output. Orange workflows routinely fan out — a patch going to both a Waterfall and a QC node is normal. The plan mentions "graph connections" but doesn't address whether `output_task_id` gets replaced with a multi-sink model. This isn't a cleanup detail; it's a structural constraint that shapes the whole graph design.

**3. `source_provenance` on `Pipe` couples run-specific state to workflow structure.**
`Pipe.source_provenance` means two runs of the same workflow with different input data produce `Pipe` instances with different fingerprints, because upstream provenance is embedded in the workflow object itself. Provenance of a specific run belongs on the run record (`Provenance`), not on the reusable workflow structure. The plan doesn't flag this.

**4. `context_aware_tasks` is a design smell the plan ignores.**
Tasks can opt into receiving an `ExecutionContext` (the full live `Pipe` + intermediate `results` dict) during execution. This breaks the encapsulation the rest of the design promises — a context-aware task can reach into any upstream result by ID, bypassing explicit edges. That makes the graph unanalyzable and undermines provenance. The plan should explicitly decide: keep or remove the `ExecutionContext` injection pattern?

**5. The `@task` decorator's dynamic class generation has real problems.**
`_create_function_task_class` makes every parameter `Optional[T]` (via `param.annotation | type(None)`) regardless of whether it's actually optional. Pydantic won't enforce required params at construction time. The plan says "absorb callable introspection from task" but doesn't say whether the `@task` decorator is the right authoring DX for DerZug or a Slanrod convenience to drop.

**6. `import matplotlib.pyplot as plt` in `Task` base class.**
`task.py` unconditionally imports matplotlib for the `plot()` debugging method. A core headless execution model should not drag in a display library. This matters for testing and server-side batch runs.

**7. `_save_failed_pipeline` is duplicated in `pipe.py`.**
The method appears at two separate locations in the file — exact duplicate. Indicative of how unreviewed the imported code is.

**8. The `Pipe | Task` composition API may not match Orange's wiring model.**
The `|` operator creates pipelines ergonomically for scripting. But Orange's node editor constructs graphs by user interaction — drag, connect ports. The internal graph construction API likely needs to be explicit (`graph.add_node(task)`, `graph.connect(node_a.port_x, node_b.port_y)`) rather than operator-chained. The plan doesn't address this mismatch.

**9. No mention of DASCore's abstractions.**
DerZug is a DAS tool. `dc.Patch` is the primary data object flowing through most nodes. Neither `Task` nor `Pipe` knows this. The plan doesn't say whether port type specs should use DASCore types, whether `Task.run()` validation should understand `dc.Patch`, or whether there's a `PatchTask` base or similar. This is a significant gap for a DAS-specific internal graph.

**10. `ComputationSpec.code_path` vs `Task.fingerprint` identity philosophies conflict.**
`ComputationSpec` identifies a computation by `module:qualname` — stable across parameter changes, breaks on rename. `Task.fingerprint` uses an AST hash plus parameters — stable across renames, changes on code edits. The plan says "absorb both" but doesn't decide which identity model wins. For DerZug's reproducibility goal (re-running a saved workflow on new data), these have very different trade-offs. One needs to be chosen and argued for.

### Open Questions Requiring Decisions Before Implementation

1. **Execution ownership:** **Resolved.** Orange owns interactive execution — reactive, per-widget, signal-driven, unchanged. The `Pipe` owns headless/batch execution. Compilation bridges them. The two models are exclusive during execution; there is no shared graph during interactive use.
2. **Widget author DX:** The planned direction is `ZugModel` as canonical state and `ZugWidget` as Qt shell. Does the new task/graph model replace `ZugModel`, or sit beneath it?
3. **Multi-output in v1:** Is fan-out (one node to multiple downstream consumers) in scope for the first internal graph milestone, or explicitly deferred?
4. **DASCore integration level:** **Resolved.** The core remains DASCore-agnostic; DASCore types flow through tasks as opaque Python objects. Widgets handle type-specific concerns.
5. **`@task` decorator:** **Resolved.** Both authoring paths are supported. Widget authors use explicit `Task` subclasses (full control over ports, Qt controls, descriptions). End users use the `@task` decorator for lightweight scripting. Both share the same `Task` base and `Pipe` execution engine.


### Response:

2. Arbitrary inputs/outputs should be possible

4. `context_aware_tasks` and `ExecutionContext` injection are removed. Tasks receive all inputs via explicit edges only. Nothing bypasses the graph topology.

7. I removed it.

8.   The key is separating graph construction from graph execution:

  - Orange builds graphs incrementally through user interactions (drag a wire, drop a node, change a parameter). It needs an explicit, mutable API: graph.add_node(task), graph.connect(from_id, port, to_id, port),       
  graph.remove_node(id).                                    
  - Scripted/batch use wants the | operator for ergonomics: task1 | task2 | task3.                                                                                                                                         
                                                                                                                                                                                                                           
  These can coexist if | is just syntactic sugar over the same explicit primitives. Right now the logic is inverted — | is the primary path and the explicit dict-based construction is the awkward one. Flip that: define 
  the explicit mutation API first, implement | on top of it. Orange uses the explicit API, developers use |.                                                                                                               
                                                                                                                                                                                                                           
  The current code almost does this — there's already a PipeBuilder utility being imported in pipe.py. But it's not exposed as the primary construction surface.                                                           
   
  The other wrinkle is immutability. The current Pipe is a frozen Pydantic model. That's great for execution, fingerprinting, and serialization — you want a stable snapshot for those. But it's awkward for Orange's      
  incremental construction: every wire change would produce a new Pipe instance, making it hard to diff what changed and drive targeted re-execution.
                                                                                                                                                                                                                           
  A clean solution: two objects, not one.                                                                                                                                                                                  
   
  - PipeBuilder — mutable, what Orange holds while the user is wiring. Exposes add_node, connect, disconnect, set_param. The | operator also returns one of these.                                                         
  - Pipe — frozen snapshot produced by builder.build(). Used for execution, fingerprinting, serialization, provenance.
                                                                                                                                                                                                                           
  Orange calls build() when it needs to execute (signal propagation), gets back an immutable Pipe, runs it, compares fingerprints to decide what's actually changed. The | operator in scripting calls build() implicitly  
  or explicitly. Both paths end up with the same Pipe contract.                                                                                                                                                            
                                                                                                                                                                                                                           
  This also resolves the incremental propagation question from critique #1 — Orange diffs the new Pipe fingerprint against the last executed one to determine which nodes are stale, then re-executes only those subgraphs.
   The internal graph doesn't need to be reactive; Orange drives execution and uses fingerprint diffing to minimize re-work.

9. The core should remain DASCore-agnostic; DASCore types flow through tasks as opaque Python objects.

10. Use the stronger task fingerprint hash.

5. Both widget authors and end users need a task authoring path. Widget authors use explicit `Task` subclasses (full control over ports, Qt controls, descriptions). End users use the `@task` decorator for lightweight scripting. Both share the same `Task` base and `Pipe` execution engine so any user-defined task can be dropped into a DerZug workflow.

**Proposed fix for `@task`:**

The current dynamic class generation has four problems: required parameters silently become optional (all fields get `T | None`), the generated class name is not importable so serialization round-trips fail, `inspect.getsource()` raises on dynamically created classes breaking AST fingerprinting, and `RunMethodDescriptor` is reconstructed on every attribute access.

The fix separates identity from change detection in the fingerprint and makes the generated class importable by anchoring it to the original function:

- **Serialization key:** store the original function's `module:qualname` (e.g. `mymodule:bandpass`), not the generated class name. On deserialization, import the function and re-apply the decorator to reconstruct the class.
- **Change detection:** store an AST hash of the function body only — not the surrounding `Task` boilerplate. This changes when the user's logic changes and is stable across base class refactors.
- **Fingerprint structure:**
  ```python
  {
      "code_path": "mymodule:bandpass",  # for reimport
      "code_hash": "a3f9...",            # AST hash of function body
      "version": "1.0",
      "parameters": {"fmin": 10.0, "fmax": 100.0},
  }
  ```
- **Required parameters:** do not make all fields `Optional`. Inspect `param.default` honestly — fields without defaults are required Pydantic fields with no default set.
- **`run` method:** bind the original function directly as a method rather than using a descriptor, so `inspect.signature(task.run)` works normally.
- **Local-scope/lambda functions:** unsupported for serialization by design. The same constraint `code_path` already requires.

---

## Primary End-to-End Use Case

**Build and debug in Orange → export → run headlessly from a script.**

Orange is the IDE. The script is the runtime. This resolves several open questions:

- **Execution ownership:** Orange owns interactive execution (reactive, signal-driven). The script owns batch execution (`pipe.run(data)`, `pipe.map(source)`). Same `Pipe` object, two callers.
- **The internal graph is the portable artifact.** Orange serializes it to JSON/YAML; the script loads and runs it with no Orange dependency. `.ows` is an Orange-specific concern, not the canonical format.
- **The serialized format must be Orange-free.** It contains only task class/function paths and parameter values. No widget internals, no Orange signal metadata.
- **The `@task` decorator serves the scripting side.** Users write processing functions, decorate them, compose pipelines in code. Whether those tasks also appear as Orange nodes depends on whether they are importable and registered — not on the decorator itself.

The scripting API should work standalone:

```python
pipe = Pipe.from_json("my_workflow.json")
results = pipe.map(source)
```

---

## Distributed Execution

The unit of distribution is the **entire pipeline mapped over inputs**, not individual tasks as scheduler primitives.

Each worker receives a `Pipe` and one input item, runs the pipeline locally, and returns the result. Parallelism comes from processing many inputs simultaneously across workers — not from parallelizing a single item's internal task graph. This matches the primary use case: a large set of DAS files or shot gathers, each processed through the same workflow.

**Why not tasks as Ray/Dask primitives:**
- Each task invocation becomes a scheduler round-trip. A 10-task pipeline on 1000 files produces 10,000 scheduler calls instead of 1000.
- DAS pipelines are mostly linear — there is rarely enough independent branching to justify the overhead.
- It forces Ray/Dask concepts into the core task model, complicating the design for users who don't need distributed execution.
- Errors surface through the distributed scheduler rather than locally, making debugging harder.

**Design constraints this imposes:**
- `Task` and `Pipe` must be fully picklable — this is the hard requirement. Workers serialize the pipeline before sending it to a worker process.
- The core model never imports Ray or Dask. Users bring their own executor.
- The `executor` parameter on `Pipe.map()` is the only integration point. `FauxExecutor` (serial) is the default; distributed executors are drop-in replacements.

```python
pipe = Pipe.from_json("my_workflow.json")

# Serial
pipe.map(source)

# Distributed
pipe.map(source, executor=RayExecutor())
pipe.map(source, executor=DaskExecutor())
```

**Ray vs Dask:** DASCore uses Dask arrays internally. If patches entering the pipeline are lazy Dask arrays, Ray workers may conflict with Dask's own scheduler. The safer default is to treat patches as fully materialized before entering `Pipe.map()`. Whether lazy Dask arrays are supported as pipeline inputs is a decision to make before implementing either executor.

**Not in scope for v1:** intra-pipeline parallelism (parallel branches within a single run). Revisit if pipelines become long with GPU-bound or IO-bound tasks.

---

## Provenance

### The Problem with `source_provenance` on `Pipe`

The current design embeds `source_provenance` on `Pipe` itself, which means the same workflow run twice on different input data produces two `Pipe` objects with different fingerprints. This conflates two things that must be separate:

- **The workflow definition** — what processing to do. Stable and reusable across any number of runs. Identified by a structural fingerprint.
- **The run record** — what data was processed, when, with what upstream lineage. Specific to one execution.

**Fix:** remove `source_provenance` from `Pipe`. `Pipe.fingerprint` becomes purely structural: tasks + topology + output task only. Upstream provenance is passed explicitly when constructing the `Provenance` run record. The `ExecutionContext` (created per-run) carries any run-specific state needed during execution. `Source` objects carry their provenance chain; `Sink` objects write it alongside the data.

### Lineage Across Multiple Pipelines

Provenance chains naturally across pipeline stages. Each `Source` loaded from a `Sink` carries the provenance of the run that produced it. The caller passes that forward when recording the next run.

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
    source_provenance=qc_source.provenance  # chain Step 1 → Step 2
))

# Step 3: QC checked → analysis
analysis_source = sink.get_source()  # carries Steps 1+2 provenance chain
analysis_pipe = Pipe.from_json("analysis.json")
results = analysis_pipe.map(analysis_source)
sink.write(results, provenance=analysis_pipe.get_provenance(
    source_provenance=analysis_source.provenance  # chain Steps 1+2+3
))
```

The final `Provenance` record for any output is a nested tree of prior runs:

```
Provenance
├── pipe: analysis.json (fingerprint: abc123)
├── created_at: 2026-03-17T14:00:00Z
├── system_info: {...}
└── source_provenance:
    └── Provenance
        ├── pipe: qc.json (fingerprint: def456)
        ├── created_at: 2026-03-17T13:00:00Z
        └── source_provenance:
            └── Provenance
                ├── pipe: preprocess.json (fingerprint: ghi789)
                ├── created_at: 2026-03-17T12:00:00Z
                └── source_provenance: ()
```

From any output file you can answer:
- What workflow produced this? (pipe fingerprint)
- What code was in that workflow? (task fingerprints + AST hashes)
- What data went in? (upstream chain)
- Has the workflow changed since this was produced? (compare current fingerprint to stored one)

**Open question:** how deep should the chain be preserved before truncating or summarizing? For long multi-stage workflows the tree can grow large. Decide whether there is a max depth or whether the full chain is always kept.

---

## Graph Model: Node Identity and Fan-out

### Removing `output_task_id`

`output_task_id` is removed entirely. `Pipe` is a pure graph description — tasks and edges only. There is no designated terminal node. The caller decides what to capture at execution time via `output_keys`.

This supports fan-out naturally: multiple downstream consumers of the same node, display nodes that also emit configured tasks, and intermediate result capture for debugging — all without changing the graph model.

### Node Handles

Each call to `builder.add(task)` copies the task, assigns it a UUID, and returns that UUID as a **node handle** (a plain string). Object identity in the graph is the handle, not the task content. Two nodes with identical task parameters are distinct graph positions with distinct handles.

```python
builder = PipeBuilder()
load  = builder.add(FileLoader(path="data/"))
band1 = builder.add(BandpassTask(fmin=10, fmax=100))
band2 = builder.add(BandpassTask(fmin=10, fmax=100))  # identical task, distinct node
qc    = builder.add(QCCheck())

builder.connect(load, band1)
builder.connect(load, band2)
builder.connect(band1, qc, "patch")

pipe = builder.build()
```

- The task **fingerprint** (content hash) captures what the task does — used for provenance and change detection. Identical for `band1` and `band2`.
- The **node handle** (UUID) captures where the task sits in the graph — used for wiring, output capture, and result lookup. Unique for every `add()` call.

A single task instance cannot appear at two graph positions. `add()` always copies, so external references to the original task instance do not affect the graph.

### `output_keys` and Memory Management

`output_keys` is passed to `run()` and `map()`. The execution engine retains only results that are still needed by a downstream node or explicitly listed in `output_keys`. Everything else is dropped as soon as its consumers have run. This is important for large patches — intermediate results should not accumulate in memory.

```python
# Capture specific nodes
results = pipe.run(source, output_keys=[band2, qc])
results[band2]   # output at second bandpass position
results[qc]      # QC result

# Default: capture all terminal nodes (no downstream consumers)
results = pipe.run(source)

# map over many inputs, capturing one node
results = pipe.map(source, output_keys=[qc])
# list of Results, one per input item
```

The execution loop:
```python
for task_id in topological_order:
    results[task_id] = task.run(**kwargs)
    if not _still_needed(task_id, remaining_tasks, output_keys):
        del results[task_id]
```

### `|` Operator

The `|` operator remains as sugar for simple linear chains where handles are not needed:

```python
pipe = FileLoader(path="data/") | BandpassTask(fmin=10, fmax=100) | QCCheck()
results = pipe.run(source)  # returns all terminal nodes by default
```

`PipeBuilder` is the primary construction surface. `|` is a convenience for linear pipelines only — fan-out requires `PipeBuilder` explicitly.

---

## Named Inputs and Outputs

### Inputs

Named inputs are the parameter names of `task.run()`. No additional declaration needed — the function signature is the input spec. Introspected via `inspect.signature`.

### Outputs

Named outputs are extracted from the return annotation and the `Returns` section of the numpy docstring. This is the part of `computation.py` most worth absorbing — `_outputs_from_return_annotation` and `_input_specs_from_signature` handle this well and should move directly into the task model.

```python
def split_bands(patch: dc.Patch) -> tuple[dc.Patch, dc.Patch]:
    """
    Returns
    -------
    low : dc.Patch
        Low frequency component.
    high : dc.Patch
        High frequency component.
    """
```

Output names: `low`, `high` — introspected automatically from the docstring. For single-return tasks, the output name is inferred from the docstring or defaults to `"result"`.

### Connection API

`builder.connect()` accepts explicit port names, with inference for the common unambiguous cases:

```python
split  = builder.add(SplitBands())
band   = builder.add(BandpassTask(fmin=10, fmax=100))
merger = builder.add(Merge())

# Fully explicit
builder.connect(split, band,   from_output="high", to_input="patch")
builder.connect(split, merger, from_output="low",  to_input="a")
builder.connect(band,  merger,                     to_input="b")

# Inferred when unambiguous
builder.connect(load, band)   # single output → first required unwired param
```

Inference rules:
- `from_output` omitted: use the task's only output; error if the task has multiple outputs.
- `to_input` omitted: use the first required parameter not already wired; error if ambiguous.

### Edge Model

The dependency model in `Pipe` changes from the current nested dict to an explicit edge list:

```python
edges: tuple[Edge, ...]
# Edge = (from_node_handle, from_output, to_node_handle, to_input)
```

This maps directly to Orange's connection model. When the user draws a wire from the `high` port of `SplitBands` to the `patch` port of `BandpassTask`, Orange calls:

```python
builder.connect(split, band, from_output="high", to_input="patch")
```

Port names shown in the Orange UI come directly from the task's introspected input/output names — no separate declaration needed.

### Results Access

Results are keyed by node handle. Multi-output nodes require an explicit output name:

```python
results[band]           # fine — single output
results[split, "high"]  # explicit — split has multiple outputs
results[split]          # error — ambiguous, must specify output name
```

### `|` Operator Constraint

The `|` operator only works when both sides are unambiguous: the left task has a single output and the right task has a single unwired required parameter. Any pipeline requiring explicit port names must use `PipeBuilder`.

---

## Results

### Task Return Values

Tasks return raw Python values. Task authors write normal Python — return what the function computes, raise on failure. The execution engine catches exceptions and wraps outputs. Requiring task authors to return a structured result object would leak infrastructure concerns into domain code.

Multi-output tasks return a tuple. The engine unpacks it using the output spec (names from the docstring `Returns` section) and stores named outputs separately. Task authors never handle this unpacking themselves.

### `Results` Object

`pipe.run()` returns a `Results` object:

```python
results = pipe.run(source, output_keys=[band, split])

# Output access
results[band]            # raw output value; raises if that node failed
results[split, "high"]   # named output of a multi-output node

# Status
results.ok               # True if all output_keys nodes succeeded
results.errors           # {node_handle: exception} for any failed nodes

# Provenance
results.provenance        # Provenance record for this run
```

### Failure Modes

Two execution modes controlled by `strict`:

- **`strict=True` (default):** raises on the first task failure. Suitable for headless batch runs where a failure should abort immediately.
- **`strict=False`:** runs all reachable nodes, collecting errors into `results.errors`. Nodes that depend on a failed upstream are skipped. Suitable for Orange's interactive execution where per-node error state should be visible in the UI.

```python
results = pipe.run(source, strict=False)
if not results.ok:
    for handle, exc in results.errors.items():
        print(f"node {handle} failed: {exc}")
```

### `map()` Returns a Lazy Iterator

`pipe.map()` returns a lazy iterator of `Results`, one per input item. Results are not accumulated in memory:

```python
for result in pipe.map(source, output_keys=[qc]):
    if result.ok:
        process(result[qc])
    else:
        log(result.errors)
```

Collected when random access is needed:

```python
all_results = list(pipe.map(source, output_keys=[qc]))
```

Memory footprint of each `Results` is bounded by `output_keys` — intermediate nodes are GC'd during execution and never reach the result object.

---

## Orange / Widget Integration

**Exclusive model.** Orange graph and `Pipe` are separate execution concerns. No shared `PipeBuilder` during interactive Orange use. Orange's existing signal mechanism routes data between widgets — this is not replaced. `PipeBuilder` exists only inside the compiler.

**Widget as task runner.** Each processing widget holds one `Task` instance (or a small fixed `Pipe` for tightly coupled multi-step operations that belong together as one Orange node). `_run()` builds inputs from current widget state, calls `task.run(**inputs)`, returns the result. `_on_result()` sends to Orange output signals as before.

New required method on all compilable widgets:
```python
def get_task(self) -> Task | Pipe:
    """Return a fully configured Task/Pipe reflecting current widget state."""
```
Must be a pure function of widget state — no side effects, no Qt calls. This is the compilation hook.

**Display widgets (Waterfall, Wiggle, PatchViewer).** No processing task. They receive data and display it. May emit a configuration output (e.g., a visual trim selector emits `PatchTrim(start=..., end=...)`). The `get_task()` contract does not apply; the compiler skips display-only nodes.

**Compilation.** A standalone function — no shared state, no Qt dependency:
```python
# derzug.workflow.compiler
def compile_workflow(orange_workflow) -> Pipe:
    builder = PipeBuilder()
    handles = {}
    for node in orange_workflow.nodes:
        widget = node.widget
        if not hasattr(widget, "get_task"):
            continue  # display-only node
        handles[node.id] = builder.add(widget.get_task())
    for link in orange_workflow.links:
        builder.connect(
            handles[link.source_node.id],
            handles[link.sink_node.id],
            from_output=link.source_channel.name,
            to_input=link.sink_channel.name,
        )
    return builder.build()
```

**Port-name contract.** Widget signal names must match task port names. `Input("patch", dc.Patch)` ↔ `task.run(patch: dc.Patch, ...)`. `Output("patch", dc.Patch)` ↔ docstring `Returns` entry named `patch`. This is a design constraint enforced by convention and validated at compile time.

**ZugModel note.** `DerZugModel.inputs` / `.outputs` ClassVars are superseded by task port introspection for processing widgets — flagged for deprecation on those widgets. `DerZugModel.meta`, `.errors`, `.warnings` remain as widget registration metadata and are unaffected.
