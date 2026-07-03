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
  without a model are the tracked `_PENDING` set.

## Progress

- **Phase 1 complete.** `ZugWidget` gained the `view_model` axis and generic
  `get_params`/`apply_params`/`get_view`/`apply_view` driven by
  `_params_field_map()` / `_view_field_map()` (both default to mapping model
  fields to same-named settings). Coverage test extended with the view axis.
- **Phase 2 complete — all 26 widgets have a `params_model`.** Declarative
  family (Detrend/Analytic/Taper/UFuncUnary) auto-derived from `_OPTIONS`; the
  bespoke and data/IO widgets given explicit Literal-typed models; the visual
  widgets modeled on their output-affecting state only (Waterfall = selection +
  annotations; Wiggle/PatchViewer are passthrough viewers with empty params).
  `_PENDING` is empty. Generic round-trip test asserts idempotence from a
  stabilized state.
- **Phase 3 complete.** `WaterfallView` and `WiggleView` added; view-coverage
  axis closed (`_VIEW_PENDING` empty), with a view round-trip test.
- Full suite green throughout (1705 passed, 44 skipped after Phase 2).

At this point every widget exposes typed `params` (and, where relevant, `view`)
models as the authoritative *interface*. The models are still a typed view over
the flat `Setting`s, so the two coexist — Phase 4 removes that duplication.

## Phase 4 progress (authoritative storage, breaking)

Decided: break `.ows` backward compatibility (no legacy migration); cleanest
architecture; minor version bump on completion.

Mechanism (on `ZugWidget`): a widget opting in with `authoritative_state = True`
stores its models' serialized form in a single `_state` blob Setting and drops
its flat per-param Settings. The base restores attributes from `_state` (or model
defaults) in `_init_authoritative_state` before controls are built, and
re-serializes on the `settingsAboutToBePacked` signal (the hook Orange emits from
`pack_data`). `apply_settings` accepts model-backed attribute names, and the
field maps derive from model fields regardless of Setting-ness.
`tests/test_core/test_authoritative_state.py` proves the `.ows` round-trip and
that params attributes are no longer flat Settings, parametrized over every
converted widget.

**Complete — all 26 widgets converted.** How the special cases resolved:

- **Filter** — discriminated union: a custom `_init_authoritative_state` seeds
  every attribute from all member models' defaults, then overlays the persisted
  active type. **Decision (active-type-only):** the blob stores only the active
  filter type; in-session switching keeps values, but a saved+reloaded workflow
  resets inactive types to defaults. Also fixed model defaults Filter's earlier
  audit skipped (window/frequency → "0.01"; one empty Gaussian row).
- **Spool** — `spool_input` holds an example name (string)/None, so it
  serializes fine. `recent_directories` is a global MRU (`schema_only=False`),
  not a workflow parameter, so it was **dropped from `SpoolParams` and kept as a
  flat Setting** (app-level, outside the blob).
- **Select**, **Waterfall** — converted cleanly; Select's `__setattr__` sync is
  guarded by a flag not yet set during `_init`. Waterfall carries both params
  (selection/annotations) and view (colormap/limits/range/dims) models, and its
  `_persist_selection_settings` was hardened to not wipe restored/pre-set
  selection state when no patch is loaded.
- **Code** — the "hang" was unrelated to storage: loading a scheme with a Code
  widget shows the arbitrary-Python confirmation dialog, which blocks headless;
  the round-trip test auto-accepts it. Code converted normally.

Full suite green throughout (1757 passed, 44 skipped at completion).

### Decisions to revisit (flagged, low-confidence)

- Filter active-type-only storage (above) — confirm the minor UX loss is
  acceptable, or switch to preserving all types.
- Waterfall `_persist_selection_settings` no-patch guard — verify it doesn't
  mask a real "selection intentionally cleared before patch arrives" case.

Version bump: the `.ows` format is now broken app-wide, so a **minor bump
(0.0.x → 0.1.0)** is warranted. Versioning is tag-based
(`setuptools-git-versioning`), so the tag lands on/after merge to `main`, not on
the feature branch; noted in `CHANGELOG.md` under Unreleased.

## Phase 4 decision point (resolved: break compatibility)

Making the model the authoritative *storage* (dropping the flat `Setting`s) is
paused for review because it is destructive and outward-facing:

- **`.ows` backward compatibility.** Existing saved workflows store each param
  as a flat property (e.g. `detrend_type`). Removing that `Setting` means old
  `.ows` files silently lose the value unless a migration shim reads the legacy
  flat properties into the new blob on load. This needs an explicit decision.
- **Shared base state.** Params like `selected_dim` live on `PatchDimWidget`, so
  the blob bridge (`_params_blob` Setting + `storeSpecificSettings` writing
  `get_params().model_dump()` + a restore hook calling `apply_params`) belongs on
  the base as an opt-in, converted family-by-family rather than one widget in
  isolation.

Recommended Phase 4 shape once approved: add the opt-in blob bridge to the base,
add a legacy-flat-settings migration on load, convert one family (Detrend) as the
reference, verify the `.ows` round-trip and an old-format load, then roll out.

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
