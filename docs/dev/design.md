
# Design

## Widget Architecture

Widgets are the primary unit of work. Each widget is a self-contained `OWWidget` subclass that owns its data, UI, and signal wiring. There is no enforced separation between model, view, and control layers — that separation adds abstraction overhead that isn't justified at this project's scale.

In practice this means:

- A widget directly holds its state as instance attributes.
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

## Auto-Generation (Future)

Auto-generating widgets from typed DASCore function signatures is a potential future optimization, not a current requirement. Pursue it only once several hand-written processing widgets exist and a clear, repetitive pattern emerges.

If pursued, parameter-to-UI mapping should follow these conventions:
  - `bool` -> checkbox
  - `int`/`float` -> numeric spin box
  - `str` -> text field
  - `Literal`/enum -> dropdown

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
