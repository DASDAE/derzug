
# Design

## Widget Architecture

Widgets are the primary unit of work. Each widget is a self-contained
`OWWidget` (`ZugWidget`) subclass that owns its data, UI, and signal wiring.
There is no heavyweight model/view/controller split, but each widget does
declare its state as typed pydantic models: a `params_model` (parameters that
affect the workflow output, compiled into the portable `Pipe` via `get_task()`)
and, for visual widgets, a `view_model` (presentation-only state such as
colormap or view range). These models are the authoritative, serialized state —
each widget persists a single `_state` blob rather than many flat Orange
`Setting`s. See
[plans/widget_state_schema_migration.md](plans/widget_state_schema_migration.md).

In practice this means:

- A widget holds live working state as instance attributes, restored from and
  serialized to its typed models before/after `__init__`.
- Parameters are read and written through `get_params()` / `apply_params()`
  (and `get_view()` / `apply_view()`) — the single typed entry points used by
  code, tests, and the Conductor. `apply_settings(mapping)` is the lower-level
  primitive they build on.
- Input handlers receive data, update state, and trigger a re-render.
- Output signals are sent directly from wherever the selection changes.
- Error/warning reporting uses Orange's built-in `Error` and `Warning` message classes.

Shared behavior (e.g. a common `run()` pattern or output dispatch) may be extracted into a lightweight base class or helper functions once the pattern clearly recurs across multiple widgets. Prefer concrete duplication over premature abstraction.

## Types of Nodes

The project supports several types of nodes (widgets).

- IO: Nodes for loading and saving data from files and external sources.

- Processing: Nodes that perform processing on input data. These typically have no visualization and only simple configuration controls. A single widget may wrap a related group of functions, with the active function selected from a dropdown.

- Transform: These transform the data domain (eg Fourier transforms). 

- Visualize: Nodes that render data for interactive inspection, selection, and/or annotation.

- QC: Quality-control nodes that compute diagnostics and health metrics.

## Data Contracts

To keep node interoperability predictable:

- Widgets must declare their expected input/output types via Orange's `Input`/`Output` signal definitions.

- Core metadata should be preserved whenever possible.
- Reusable visual-annotation behavior should follow the shared annotation design
  in [annotations.md](annotations.md)
  rather than introducing widget-specific overlay schemas.

## Auto-Generation

The declarative `PatchMethodWidget` family already maps a small `_OPTIONS` spec
to both its Qt controls and an auto-derived `params_model`, using these
conventions:

  - `bool` -> checkbox
  - `int`/`float` -> numeric spin box
  - `str` -> text field
  - `Literal`/enum -> dropdown

Fully auto-generating widgets from typed DASCore function signatures builds on
this but remains a future optimization, not a current requirement — pursue it
only once the repetitive pattern clearly justifies it.

## Reproducibility

Reproducibility is a core requirement:

- Workflows must be saveable and reloadable.

- Node parameters and versions used should be captured.

- Outputs should include enough metadata to trace processing steps.

- Optional stretch goal: export a workflow to a runnable Python script.

## Performance Principles

Interactive performance should remain a first-class concern:

- Prefer lazy loading and chunked processing.
  
- Support progress indicators for long-running operations.

- Support cancellation where feasible.

- Define target dataset scales for acceptable responsiveness.

## Reliability and Testing

Minimum testing strategy:

- Unit tests for non-UI logic (coordinate mapping, data transforms, etc.).

- Contract tests for node input/output compatibility.

- Golden/snapshot tests for representative workflow behavior.

- Smoke tests for critical user flows (load -> process -> visualize -> export).

## Plugin Strategy

Third-party extension should be possible without breaking core stability:

- Discover widgets via a documented entry-point mechanism.

- Define a compatibility policy across DerZug versions.

- Encourage semantic versioning for plugins.

- Keep plugin APIs narrow and stable where possible.

## Standalone Use
DerZug should have some simple entry points for quick visualizations used in code. For example,

```python
import dascore as dc
import derzug as dz



```

## Roadmap

See [roadmap.md](roadmap.md) for phased milestones.
