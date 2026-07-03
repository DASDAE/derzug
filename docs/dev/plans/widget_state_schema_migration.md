# Widget State Schema Migration Plan

## Summary

Give every DerZug widget one authoritative, typed representation of its state,
split into two pydantic models by concern:

- **`params_model`** — the parameters that affect the workflow *output*. Compiles
  into the portable `Pipe` via `get_task()`; runs headless; is what downstream
  widgets receive. Read/written through `get_params()` / `apply_params()`.
- **`view_model`** — presentation-only state (colormap, colour-bar levels, view
  range, plot dimensions). Never enters the compiled workflow; it is local to the
  widget. Read/written through `get_view()` / `apply_view()`.

The dividing line is one question: **does this state change what flows
downstream?** Yes → params. No → view. A third tier — truly transient state
(live cursor position, in-progress ROI drag, active tool) — stays plain widget
instance state and does not persist.

The end state removes the current pile of flat Orange `Setting`s in favour of the
models as the single source of truth, eliminating duplication and giving agents
(the Conductor) a self-describing, validated interface via
`model_json_schema()`.

## Motivation

- **One source of truth.** Today parameters live as flat `Setting`s, restated in
  ad-hoc control wiring and in `get_task()`. The model unifies them.
- **Clean portability boundary.** `params` is exactly the portable, executable
  part; `view` is exactly the local presentation. Typing them separately means
  nothing presentational can ever leak into a shared workflow.
- **Agent-ready.** The Conductor's write surface consumes `get_params` /
  `apply_params` / `model_json_schema()` directly — an agent sets a Filter to a
  notch, or reads a Waterfall's colormap, through typed validated models instead
  of 25 unlabelled flat knobs.

This continues the direction of `widget_workflow_cleanup.md` (one canonical
`get_task()`), adding the typed data model beneath it.

## Status (as of this branch)

Done on `feature/unified-set-params`:

- **Unified parameter setting.** `ZugWidget.apply_settings(mapping) -> prior`
  updates settings, syncs controls, cascades stacked pages, re-runs, and returns
  prior values (for undo). Declarative `_settings_control_map()`, plus
  `_linked_stacks()` / `_sync_dependent_controls()` for cascading options. Covers
  all 26 widgets (`tests/test_core/test_apply_settings.py`).
- **Filter reference implementation.** All nine filter types modeled as a
  discriminated union (`src/derzug/widgets/filter_params.py`); table-driven
  `get_params()` / `apply_params()` round-trip every type, including through
  `.ows` save/reload via existing `Setting` persistence.
- **Convention + tracker.** `ZugWidget.params_model` ClassVar;
  `tests/test_core/test_params_model_coverage.py` enforces that the only widgets
  without a model are the tracked `_PENDING` set (25 remaining).

## Remaining work

### Phase 1 — Finish the convention (small, do first)

1. Add the **`view_model` axis** to `ZugWidget`: `view_model` ClassVar plus
   `get_view()` / `apply_view()`, mirroring the params methods.
2. Add a **generic base `get_params` / `apply_params`** driven by a
   `params_field_map` (`{model_field: setting_name}`) so a simple widget needs
   only to declare its model + map — no per-widget method bodies. Filter's
   hand-rolled `_PARAM_FIELDS` becomes the reference for this generic form.
3. Extend the **coverage test** with the view axis: visual widgets must declare a
   `view_model`; processing widgets must not.

### Phase 2 — Roll `params_model` across the 25 remaining widgets

Coverage test drives `_PENDING` to empty. Most are not from scratch:

- **Batch 2a — declarative family** (Detrend, Analytic, Taper, UFuncUnary):
  auto-derive the params model from the existing `_OPTIONS` spec; one mechanism
  covers all four.
- **Batch 2b — bespoke-task widgets** (Normalize, Fourier, Calculus, Rolling,
  Stft, Resample, Aggregate, FBE, UFuncBinary): grow the model from the existing
  pydantic `Task` classes (`FBETask`, `AggregateTask`, …) or a small
  method-call model.
- **Batch 2c — data/IO** (DataFrameLoader, Code, Table2Annotation, Annotations,
  Annotation2DataFrame, PlayAudio).
- **Batch 2d — visual, params side** (Spool, Select, Coords, Waterfall, Wiggle,
  PatchViewer): use existing `SpoolTask` / `SelectTask` / `CoordsTask`.

Each converted widget is removed from `_PENDING`; the test fails until it is, so
none are forgotten.

### Phase 3 — Add `view_model` to visual widgets

Waterfall (colormap, `color_limits`, `saved_view_range`, plot dims — its
`saved_*` settings), Wiggle, PatchViewer, and Spool's table view state. Selection
ranges and annotation sets stay params-side (Waterfall emits them as outputs);
only pure-display state moves to `view_model`.

### Phase 4 — Authoritative storage (drop flat Settings)

Once every widget has models, flip storage: replace the flat `Setting`s with a
single serialized-model `Setting` (which round-trips through `.ows` unchanged),
and point control hydration and `get_task()` at the model. This removes the
duplication and retires the `apply_settings` / `_settings_control_map` layer into
the model's internals.

- **Prototype on Detrend first** (simplest) to validate the "flat settings gone,
  one model setting" shape and the OWS round-trip before rolling out.
- Convert widget-by-widget behind the coverage test.

## Persistence

No OWS/format change is required at any phase. Models are stored as their
`model_dump()` in a `Setting`, which Orange already round-trips through
`node.properties` into `.ows` (proven by the Filter save/reload test). Breaking
or replacing the OWS format is explicitly out of scope — the model rides on the
existing persistence.

## Enforcement

- `tests/test_core/test_params_model_coverage.py` — every widget has a
  `params_model` (or is tracked in `_PENDING`); extended in Phase 1 to require a
  `view_model` for visual widgets.
- Per-widget round-trip tests (like Filter's all-types test): every modeled type
  applies and reads back as the same model, and survives `.ows` save/reload.
- Full suite must stay green after each batch.

## Sequencing

1. Phase 1 convention.
2. Phase 2 params-model rollout (batch by batch, `_PENDING` → 0).
3. Phase 3 view models on visual widgets.
4. Phase 4 authoritative storage migration (Detrend prototype, then rollout).

Land the finished **apply_settings unification** as its own PR early; keep the
params/view-model rollout on its own track so completed pieces merge while the
rest continues.

## Then — circle back to the Conductor

With every widget exposing typed `params` / `view` models and JSON schema, the
Conductor's write surface (`set_params`, undo via returned prior values, the MCP
tools) is built directly on this interface. Finishing this cleanup is the
prerequisite; the Conductor is the payoff.
