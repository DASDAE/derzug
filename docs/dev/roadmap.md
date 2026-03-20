# DerZug Roadmap

This roadmap describes practical phases for taking DerZug from experimental prototype to a stable internal tool.

## Phase 1: MVP Workflow

Goal: Deliver a reliable end-to-end interactive workflow.

- At least two visualization nodes:
  - Waterfall - take a patch, returns a patch (optionally clipped based on selection rectangle)
  - Wiggle - Plots the waveforms along the selected dimension (dynamically determined from intput patch) with a vertical offset. 

- IO nodes to load examples, spool from a directory, and save a patch to a directory.

## Phase 2: Auto-Generation Framework

Goal: Reduce widget implementation effort by generating nodes from typed functions.

Deliverables:

- Function signature parser with strict validation.

- Type-hint to UI-control mapping for common parameter types.

- Generated control/view shims for processing nodes.

- Error handling and parameter validation UX.

- Documentation for supported and unsupported signatures.

Exit criteria:

- New processing functions can be onboarded with minimal handwritten widget code.

- Auto-generated nodes behave consistently with manually built nodes.


## Cross-Cutting Work (All Phases)

- Performance:
  - Lazy/chunked operations for large datasets
  - Progress reporting and cancellation for long tasks
  
- Reliability:
  - Unit, contract, and smoke tests
  - CI checks for linting and test baselines
  
- Developer experience:
  - Clear contribution guidelines
  - Minimal reproducible local setup

## Architectural Rewrite: Model-Driven Widgets

The current widget base now supports background execution for heavy tasks, but
the authoring model still exposes too much widget-level execution state. In
practice, widget code must snapshot instance attributes before background work
starts, which leaks Qt concerns into processing logic and makes heavy widgets
harder to write correctly.

This project is still early enough that a clean architectural reset is cheaper
now than later. The long-term direction should be a model-driven widget design
where `ZugModel` becomes the canonical state object and `ZugWidget` becomes
the Qt/Orange shell around it.

### Target architecture

- `ZugModel` is the primary source of truth for widget inputs, parameters,
  validation state, and execution-facing state.
- `ZugWidget` owns Qt lifecycle, Orange signal wiring, busy/progress display,
  and main-thread UI updates.
- Background execution runs from model state rather than from widget instance
  attributes.
- Visual widgets still render on the main thread, but render from model/result
  state rather than ad hoc widget fields.
- Latest-wins execution semantics stay in the base widget rather than being
  reimplemented by individual widgets.

### API direction

- Widget authors should not need to hand-assemble request dicts or read widget
  instance attributes inside background code.
- The supported widget flow should become:
  - widget updates model from controls and input signals
  - `ZugWidget.run()` captures or copies model state for one run
  - background work consumes model state
  - result application happens back on the main thread
- `ZugModel` should absorb any execution-facing hooks needed for this flow.
- The current request-snapshot background API on `ZugWidget` should be treated
  as transitional and removed once the rewrite is complete.

### Implementation phases

#### Phase A: Define the model contract

- Expand `ZugModel` so it can represent widget inputs, parameters,
  errors/warnings, and run state cleanly.
- Define how one run gets a stable copy/snapshot of model state.
- Define how widgets bind controls to model fields without duplicating state.
- Document main-thread vs background-thread responsibilities.

#### Phase B: Refactor `ZugWidget` around model execution

- Rework `ZugWidget` so execution is model-first rather than
  widget-attribute-first.
- Keep Orange busy/progress/status integration in the base class.
- Keep latest-wins behavior in the base class.
- Remove the need for widget authors to manually build background request
  payloads from widget fields.

#### Phase C: Migrate existing widgets

- Migrate all current widgets to use `ZugModel` as the source of truth.
- Start with heavy processing widgets, then migrate visual and IO widgets.
- Remove transitional background hooks once no widgets rely on them.
- Update guidelines and examples to teach the model-driven pattern only.

### Acceptance criteria

- New widgets can be written without reading widget instance attributes inside
  background compute paths.
- Heavy processing widgets no longer need ad hoc request snapshot code.
- Visual widgets have a documented model/result path while keeping Qt rendering
  on the main thread.
- `ZugWidget` remains the single owner of busy indicators, task lifecycle, and
  stale-result handling.
- Documentation and examples consistently teach the model-driven pattern.
- Transitional request-snapshot hooks are removed from the supported widget API.

## Problem Statement: Memory Retention in Large Patch Chains

As DerZug workflows scale to long chains of patch-processing nodes, memory pressure becomes a primary stability risk.
The issue is not only widget code: Orange itself retains recent signal values during workflow propagation, and widgets can additionally retain large input/output objects for reruns and interactivity.

### What we observed

- Orange signal propagation is push-based and retains current signal objects internally.
- Several widgets also keep explicit references (for example `self._patch`, `self._current_spool`) to support rerun/interaction behavior.
- In long pipelines, these retained references can lead to unexpectedly high resident memory, especially with large patch objects.

### Design direction discussed

- Add a `holds_reference` policy on `ZugWidget` (default `True` for backward compatibility).
- For widgets with `holds_reference=False`, clear model-held or widget-held input references after emitting outputs.
- Treat this as data-lifecycle control layered on top of the model-driven widget rewrite; it does not remove Orange's internal signal retention.

### Key constraints and tradeoffs

- If a widget clears its input references, parameter changes after a run may not be recomputable without fresh upstream input.
- Orange has no built-in downstream "pull previous upstream result" mechanism; replay requires explicit custom patterns.
- Visualization/interactive widgets may still need retained references; pure processing nodes are strongest candidates for `holds_reference=False`.
- Reference-retention semantics should be resolved against model state ownership rather than ad hoc widget fields.

### Follow-up work (deferred)

- Define exact rerun semantics for `holds_reference=False` widgets in the model-driven architecture.
- Decide whether to add a refresh/replay mechanism (explicit refresh signal, shared cache, or lightweight handle-based dataflow).
- Add tests to verify reference-release behavior and memory behavior in multi-node chains.
