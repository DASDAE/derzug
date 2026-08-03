# Backend refactor: Qt-free node spec/registry extraction (derzug core layer)

## Context

DerZug's long-term direction is a client/server split (headless workflow engine + browser frontend). The workflow engine (`derzug.workflow`) is already Qt-free, but **node identity** — name, input/output ports, params schema, task factory — lives on `OWWidget` (`ZugWidget`) subclasses in `derzug.widgets`. That entanglement is the single blocker to headless compile/run of a canvas graph.

This refactor extracts a Qt-free node-spec/registry layer so that:
- A node type can be introspected (ports, params/view JSON schema) and its `Task` constructed without importing Qt/Orange.
- The Qt widgets consume the same specs (no behavior change in the app).
- Headless compilation/execution is proven by tests that never import Qt.

**Decided scope** (user choices):
- Core extraction only — no HTTP server in this plan.
- Stay one distribution: a Qt-free subpackage inside `derzug` with enforced import layering (test/lint guard forbidding Qt imports), not a separate `derzug-core` package yet.

## Exploration findings

### Widget node-identity coupling (agent 1)

**Already Qt-free (reusable as-is):**
- `workflow/task.py` — `Task` + `TaskPortSpec` (`port_spec()`, `scalar_input_variables()`, `required_scalar_inputs()`) is already a Qt-free port/schema layer; `code_path()`/`fingerprint` give stable identity.
- `workflow/{model,pipe,graph,compiler,widget_tasks}.py`, `widgets/filter_params.py`, `models/{selection,annotations}.py`, `utils/misc.py` (entry-point loading via `load_widget_entrypoints()`), `constants.py` (`WIDGETS_ENTRY = "derzug.widgets"`), `core/widget_execution.py`.
- Schema surface on `ZugWidget` is pure pydantic classmethods: `params_schema()`/`view_schema()` (zugwidget.py L848-860) — but calling them requires importing the Qt module.
- `_build_params_model()` in `patchmethodwidget.py` L106-117 (pure `create_model` from `_OPTIONS`); `ComboOption`/`SpinOption` dataclasses are Qt-free in content but live in a Qt-importing module.
- `utils/code2widget.py` has embryonic Qt-free node-spec dataclasses (`_WidgetTaskSpec`/`_WidgetInputSpec`/`_WidgetOutputSpec`, L25-51).

**Qt-entangled (must split):**
- Node identity metadata (`name`, `params_model`, `view_model`, `is_source`, icon/category/keywords/priority) declared as ClassVars on `OWWidget` subclasses.
- Orange `Inputs`/`Outputs` descriptor classes on every widget; `compiler.widget_signal_name_map()` (compiler.py L78-85) already reads them reflectively.
- 13 `Task` subclasses defined inside Qt widget modules: spool.py (`SpoolTask` L559, `SpoolTransformTask` L609), filter.py L70, code.py L73, aggregate.py, coords.py, fbe.py, select.py, ufunc_binary.py, dataframe_loader.py, table2annotation.py, annotation2dataframe.py, annotations.py.
- Task→widget back-references (hard blockers): `SpoolTask.run()` → `Spool._spool_rows_to_output`; `CodeTransformTask.run()` → `Code._has_unsupported_required_inputs`; `PatchSelection*Task.run()` → lazy `from derzug.widgets.selection import SelectionState` (Qt module); `CallableTaskAdapter` → `utils.code2widget` (Qt).
- `PatchMethodWidget.get_task()` (L283-314) is pure dispatch on `_OPTIONS` roles but calls control-mutating `_coerce_combo/_coerce_spin/_get_dim()`.
- Widget `get_task()` implementations call `self._sync_settings_from_controls()` first (Qt).

**Best-practice examples already in tree:**
- `waterfall.py get_task()` (L399-403) → returns `PatchSelectionWithParamsTask` from Qt-free `widget_tasks.py`, widget contributes only a payload — the target pattern.
- `filter_params.py` — params models fully extracted to a Qt-free module (discriminated union + `_FILTER_MODELS`).
- Pure-declarative `_OPTIONS` widgets, ideal first migration targets: `taper.py` (58 lines), `detrend.py` (47), `analytic.py` (46), `ufunc_unary.py` (63).

**Entry-point chain:** pyproject `[project.entry-points."derzug.widgets"]` → module names → `utils/misc.py load_widget_entrypoints()` (Qt-free) → `views/orange.py DerZugConfig.widgets_entry_points()` → Orange canvas imports OWWidget subclasses. External plugin (SlanRod) ordering comment in misc.py L44-45 is load-bearing.

### Consumers of widget-class identity (agent 2)

**Compiler contract is already duck-typed** (`workflow/compiler.py`, no Qt imports at module level). Complete widget surface it touches: `get_task()` (L106-109), `type(widget).Outputs/.Inputs` reflected via `widget_signal_name_map` (L73-85), `is_source` (L206), `get_mapped_source()` (L174-177), `type(widget).get_task is ZugWidget.get_task` probe (L215-221, the one lazy Qt-ward import at L218). `tests/test_workflow_compiler.py` already compiles against hand-rolled fakes implementing exactly this contract — the de-facto spec protocol.

**Conductor** (`conductor/controller.py`): `list_widget_types()`/`_widget_type_info()` (L270-301) only needs class-level `params_schema()`/`view_schema()` + registry descriptions → clean candidate to read from a static node-spec registry. `conductor/schema.py` is pure pydantic already. Node-instance ops (get/set params on live widgets, run, windowing) legitimately stay Qt.

**Four layering leaks to fix:**
1. `workflow/disabled.py:8` — module-level `from orangecanvas.scheme.link import compatible_channels`; also duplicates `widget_signal_name_map` verbatim (L24-36).
2. `compiler.py:218` — lazy `ZugWidget` identity probe (replace with spec flag/marker).
3. `widget_tasks.py:100,127` — `PatchSelection*Task.run()` lazily imports `derzug.widgets.selection.SelectionState` (Qt module) at execution time.
4. `widgets/__init__.py:6` — `from derzug.views import summary` (importing any widget pulls views).

**13 Task subclasses live in Qt widget modules** and serialized pipes reference them by `module:qualname` (`task.py code_path()`, resolved by `graph.resolve_symbol`) — so today deserializing a real saved pipe imports Qt. Largest single work item.

**Existing precedent to copy:** `core/services.py` — Protocol + module-global register/get service locator (AppShellService), documented as the pattern for keeping widgets from importing views.

**Test landscape:** `test_workflow_compiler.py` and `test_workflow_engine.py` are Qt-free in content, but `tests/conftest.py:93-100,149-155` boots Qt for every test run — no test currently asserts Qt absence. `test_workflow_compiler.py:120-136` has subprocess import-check precedent. `utils/testing.py:277-282` asserts every widget's `get_task()` returns `Task | Pipe`. `test_integrations.py:28-32` hard-codes `_NON_WORKFLOW_INPUTS` (context-only ports) by widget name — a spec layer should encode this.

**CLI:** no headless mode today; `cli.py` always imports `views.orange`.

**Decision:** clean break on serialized task code paths (pre-alpha) — move tasks, update bundled `.ows`, no legacy aliases.

**Future-proofing (user request, not this phase):** the backend should eventually be hostable as a local server *or* in-browser via Pyodide. Design guideline for the new layer: host-agnostic — no threads/sockets/event-loop ownership in core or spec code, plain synchronous calls with JSON-serializable pydantic models at boundaries (transports wrap it). Known wasm risk to defer: dascore requires PyTables, which Pyodide doesn't ship.

## Design decisions

- **D1 — Layout: one node = one module under `src/derzug/nodes/`.** Each node module holds its Task class(es), params/view pydantic models, task factory, and `NODE_SPEC`. `workflow/` stays the pure engine; `nodes/` is the node library on top. Generic engine tasks (`PatchPassThroughTask`, `MultiPassThroughTask`, `CallableTaskAdapter`, `PatchConfiguredMethodTask`, `PatchRollingTask`) stay in `workflow/widget_tasks.py`; domain tasks move to `nodes/`. Enforced layering: `models` → `workflow` → `nodes` → {`core`, `widgets`, `views`, `conductor`} (Qt only in the last group).
- **D2 — Spec shape: frozen dataclasses** (matches `TaskPortSpec`/`ComboOption` precedent; specs hold classes/callables, pydantic buys nothing):
  - `PortSpec(name, display_name, type, context_only=False)` — `name` = widget attr / compiler port name; `display_name` = Orange signal name; `context_only` encodes today's `_NON_WORKFLOW_INPUTS`.
  - `NodeSpec(name, widget_qualified_name, inputs, outputs, params_model, view_model, task_factory, is_source, category, description, keywords, icon, priority, executes_arbitrary_code)` with `params_schema()`/`view_schema()` via `TypeAdapter` (mirrors zugwidget.py L840-860). `task_factory: (params|None) -> Task|Pipe`.
  - Spec ports complement `TaskPortSpec` (widget-level signal identity vs task run() contract); registry test asserts non-context spec ports ⊆ factory task's resolved ports. dascore types referenced directly (Qt-free).
- **D3 — Discovery: new entry-point group `derzug.nodes`** (`Name = "derzug.nodes.<module>"`), each module exposing module-level `NODE_SPEC` (or `NODE_SPECS`). `nodes/registry.py`: `load_node_specs()` (@cache, derzug-first ordering copied from `utils/misc.py load_widget_entrypoints`, incl. the load-bearing SlanRod comment), `spec_by_name()`, `spec_for_widget_qname()`, `validate_spec()`. Existing `derzug.widgets` group untouched (Orange canvas discovery keeps working); external plugins ship both groups.
- **D4 — Widget consumption:** `ZugWidget` gains `node_spec: ClassVar[NodeSpec | None] = None`; when set, `params_model`/`view_model`/`is_source` derive from it (`__init_subclass__` copies spec fields when the widget doesn't override); existing ClassVars remain the fallback for unmigrated widgets. Widgets keep Orange `Inputs`/`Outputs` and handlers — zero canvas churn; consistency enforced by tests instead.
- **D5 — Compiler probe:** replace `_uses_default_get_task`'s lazy ZugWidget import (compiler.py:215-221) with a function-attribute marker on the base fallback (`get_task.__derzug_default_get_task__ = True` after zugwidget.py:1040) checked via `getattr`.
- **D6 — Conductor (minimal):** `_widget_type_info` (controller.py:270-287) tries `spec_for_widget_qname()` for schemas first, falls back to widget-class import for unmigrated/external widgets. `UNSAFE_WIDGET_QNAMES` unchanged (deriving from `executes_arbitrary_code` is follow-up, not scope).
- **D7 — Guard tests are subprocess-based; no conftest restructuring.** Root `tests/conftest.py` Qt bootstrap doesn't affect fresh-interpreter tests (precedent: `tests/test_views/test_import_purity.py`).
- **D8 — Clean break is a no-op for bundled artifacts:** verified `.ows` files store only widget qualified names + literal settings, never task code paths; code paths appear only in Pipe YAML serialization and no such artifact is bundled. Only docs examples change.
- **Host-agnostic guideline (future Pyodide/server):** no threads/sockets/event-loop ownership in `nodes/` or `workflow/`; JSON-serializable pydantic models at boundaries.

## Working setup

Implement in a fresh git worktree branched from `main` (under the repo's existing `worktrees/` directory), not on `agent/add-conductor-menu` — that branch carries unrelated uncommitted Conductor work. One branch/PR per phase.

## Phase 1 — Infrastructure, leak fixes, guard tests, two pilot nodes

Done-state: `derzug.nodes` exists with registry + Filter + Taper specs; guard test proves Qt-free import closure and a headless run; app behavior unchanged; full suite green.

1. `src/derzug/nodes/__init__.py` — re-export `NodeSpec`, `PortSpec`, `load_node_specs`; import-light (no spec modules).
2. `src/derzug/nodes/spec.py` — `PortSpec`, `NodeSpec` per D2.
3. `src/derzug/nodes/registry.py` — per D3.
4. `src/derzug/nodes/_options.py` — move `ComboOption`, `SpinOption` and a widget-free `build_params_model(name, options, *, uses_dim, dim_default="")` from `core/patchmethodwidget.py:28-117` (drop the `_setting_default` widget introspection — defaults come from option declarations); add `options_task_factory(params, *, method_name, call_style, uses_dim, options)` → `PatchConfiguredMethodTask` (pure port of `get_task()` L283-314 minus control coercion). `patchmethodwidget.py` imports these back; `__init_subclass__` uses the shared builder.
5. `src/derzug/utils/callable_spec.py` — move the Qt-free half of `utils/code2widget.py` (`_WidgetInputSpec/_WidgetOutputSpec/_WidgetTaskSpec`, `task_from_callable`, `_spec_from_callable`, `_invoke_spec_function`, `INPUTS_NOT_READY`, name/type helpers); `code2widget.py` keeps the Qt half and imports back. `workflow/widget_tasks.py:197,228` switches to `callable_spec` (imports can go module-level).
6. Leak fixes:
   - `workflow/disabled.py` — delete duplicated `widget_signal_name_map` (L24-36), import from `.compiler`; make the `orangecanvas` `compatible_channels` import lazy at its single call site.
   - `workflow/compiler.py` + `core/zugwidget.py` — D5 marker.
   - `widgets/__init__.py` — move `from derzug.views import summary` registration into `views/orange.py` so importing widgets never pulls views; verify `tests/test_views/test_summary.py` + widget tests stay green (root conftest imports `DerZugMain`, keeping summaries registered for the suite).
7. Pilot A (hand-written): `src/derzug/nodes/filter.py` — move `FilterTask` + `_FILTER_NAMES` from `widgets/filter.py:30-220`; fold in all of `widgets/filter_params.py` (only importers are filter.py and its test — verified); move `_PARAM_FIELDS`; add `filter_task_from_params(FilterParams)`; define `NODE_SPEC`. `widgets/filter.py` imports back, sets `node_spec = NODE_SPEC`, drops its `params_model` ClassVar. Delete `widgets/filter_params.py`; update `tests/test_widgets/test_filter_params.py` imports.
8. Pilot B (_OPTIONS): `src/derzug/nodes/taper.py` — `_OPTIONS` moved from `widgets/taper.py`, `TaperParams = build_params_model(...)`, `NODE_SPEC` with `task_factory=partial(options_task_factory, method_name="taper", call_style="keyword_dim", uses_dim=True, options=_OPTIONS)`. `PatchMethodWidget.get_task()` becomes: coerce controls (Qt side) → params instance → `node_spec.task_factory(params)` when `node_spec` set, else current path (detrend/analytic/ufunc_unary untouched until Phase 2).
9. `core/zugwidget.py` — `node_spec` ClassVar + D4 resolution.
10. `pyproject.toml` — add `[project.entry-points."derzug.nodes"]` with Filter, Taper. (Re-`uv sync`/editable-install needed for `importlib.metadata` to see the group.)
11. New `tests/test_nodes/`:
    - `test_import_layering.py` — fresh subprocess: import `derzug.nodes.registry`, load all specs, import all `derzug.workflow` submodules (incl. `disabled`), build default-params tasks; assert no `sys.modules` key starts with `PyQt6/PyQt5/PySide6/AnyQt/Orange/orangewidget/orangecanvas`.
    - `test_registry.py` — unique names/qnames; `validate_spec` per spec; schemas JSON-serializable; spec ports consistent with factory task ports.
    - `test_headless_pipeline.py` — subprocess: `spec_by_name("Filter").task_factory(FilterParams(...))` run on `dc.get_example_patch()`; assert Qt absent.
    - `utils/testing.py` shared suite — add `test_node_spec_consistency` (skip when `node_spec is None`): spec port `(name, display_name)` pairs == `widget_signal_name_map` items for non-context ports; `spec.params_model is type(widget).params_model`; `spec.is_source == widget.is_source`; `widget.get_task().model_dump() == spec.task_factory(widget.get_params()).model_dump()` where applicable.

## Phase 2 — Mechanical migration of remaining simple nodes + selection split

Done-state: every widget except Spool/Code has a `nodes/` module + entry point; layering guard covers all.

1. Selection split (prereq for select/waterfall): `src/derzug/models/selection_state.py` gets `SelectionMode`, `PatchSelectionBasis`, `PatchSelectionState`, `SpoolFilterRowState`, `SpoolFilterState`, `SelectionState` + numeric/parsing helpers (widgets/selection.py L31-221, verified Qt-free content); `widgets/selection.py` keeps the Qt panel/mixin and re-imports state. `src/derzug/nodes/selection.py` gets `PatchSelectionTask`/`PatchSelectionWithParamsTask` moved from `workflow/widget_tasks.py:90-140` with module-level imports (fixes leak #3).
2. Remaining `_OPTIONS` widgets (detrend, analytic, ufunc_unary): same pattern as Taper.
3. Hand-written widgets (aggregate, coords, fbe, select, ufunc_binary, dataframe_loader, table2annotation, annotation2dataframe, annotations, waterfall, and any other with a Task/params/get_task): per widget, `nodes/<name>.py` receives moved Task + params/view models (e.g. `WaterfallParams`/`WaterfallView` from waterfall.py:302-316) + factory + `NODE_SPEC` with `context_only` ports encoding `_NON_WORKFLOW_INPUTS` (Spool: patch/spool; Waterfall/Annotations: annotation_set). Waterfall's factory returns `PatchSelectionWithParamsTask` from `nodes/selection.py`. View-only widgets without `get_task` get `task_factory=None` specs (introspection only; compiler probe already handles them).
4. `tests/test_integrations.py:28-32` — derive `_NON_WORKFLOW_INPUTS` from registry `context_only` ports instead of the hard-coded dict.

## Phase 3 — Hard cases (Spool, Code), conductor switch, docs

Done-state: all 13 Task classes live under `nodes/`; guard test covers a real Spool-example → Filter headless run; docs updated.

1. `utils/example_parameters.py` split: Qt-free functions stay; `ExampleParametersDialog` + Qt imports move to `utils/example_parameters_dialog.py`; update `widgets/spool.py` import. (This module is a Spool-task leak found in verification: `SpoolTask.run()` → `build_example_call_kwargs` → module-level AnyQt import.)
2. `src/derzug/nodes/spool.py` — move `SpoolTask`, `SpoolTransformTask`, `SpoolParams` + Qt-free helpers (`_load_spool_from_settings`, `_apply_select_rows`, `_apply_chunk_settings`, `_ordered_contents_df_with_source_rows`, `_spool_indices_for_rows`, `_spool_rows_to_output` — already a free function at spool.py:692, the staticmethod is a thin wrapper — `_spool_rows_to_patches`, `_all_examples`, `_IGNORE_EXAMPLES`, `_DEFAULT_EXAMPLE`). Replace `Spool._spool_rows_to_output` back-references in tasks with the free function. Spec: `is_source=True`, outputs spool/patch, context-only inputs.
3. `src/derzug/nodes/code.py` — move `CodeTransformTask`, `CodeParams`, `DEFAULT_SCRIPT`, `_compile_script`; convert `Code._has_unsupported_required_inputs` (code.py:318) to a free function here; spec sets `executes_arbitrary_code=True`. `UNSAFE_WIDGET_QNAMES` untouched.
4. Conductor: D6 in `controller._widget_type_info`.
5. Extend `tests/test_nodes/test_headless_pipeline.py`: Spool(example) → Filter via `PipeBuilder`, run, assert filtered `dc.Patch`; plus YAML round-trip subprocess test proving deserialization resolves `derzug.nodes.*` code paths without Qt.
6. Docs: `docs/dev/design.md`, `workflow-design.md`/`workflow_spec.md` (layering diagram, `derzug.nodes` entry-point contract, code-path examples → `derzug.nodes.filter:FilterTask`), `creating_widgets.qmd`/`widget_development.md` ("define node spec first, then widget").

## Verification (each phase)

```bash
cd /home/derrick/Gits/derzug
python -m pytest tests/test_nodes -x -q
python -m pytest tests/test_workflow_compiler.py tests/test_workflow_engine.py -q
python -m pytest tests/test_widgets tests/test_integrations.py -q
python -m pytest -q          # full suite
prek run                     # lint/pre-commit
derzug "src/derzug/workflows/01_Quick Start.ows"   # manual smoke: bundled workflow loads
```

Plus the definition-of-done steps: self-review, counterpart CLI review saved under `.scratch/`, rerun checks after addressing findings.

## Critical files

- `src/derzug/core/zugwidget.py` (node_spec ClassVar, D4/D5)
- `src/derzug/core/patchmethodwidget.py` (options split)
- `src/derzug/workflow/compiler.py`, `workflow/disabled.py`, `workflow/widget_tasks.py` (leak fixes)
- `src/derzug/widgets/filter.py`, `widgets/taper.py` (pilots), `widgets/spool.py`, `widgets/code.py`, `widgets/selection.py` (hard cases)
- `src/derzug/utils/misc.py` (registry loading pattern to copy), `utils/code2widget.py`, `utils/example_parameters.py` (splits)
- `pyproject.toml` (entry points), `utils/testing.py` (shared suite check)
