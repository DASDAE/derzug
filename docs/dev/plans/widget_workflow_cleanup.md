# Widget Workflow Cleanup Plan

## Summary

Refactor the widget/workflow boundary so every processing widget has one canonical semantic export: `get_task()`. Interactive execution, validation, async scheduling, workflow compilation, and serialization should all derive from that one source.

This is a broader redesign with a clean break. The cleanup should remove the current split between widget-side preflight logic, task-side execution logic, and special-case runtime paths. `Spool` and other source or boundary widgets are included in phase 1 and must use the same semantic and execution architecture.

## Progress

- 2026-03-31: Started phase 1 with runtime extraction. The first implementation slice pulls async scheduling and teardown mechanics out of `ZugWidget` into a dedicated runtime component while keeping the existing widget-facing API stable.
- 2026-03-31: Completed the first runtime extraction slice. Added `src/derzug/core/widget_runtime.py`, moved worker lifecycle state there, and kept `WidgetExecutionRequest`, `_active_execution_token`, and `_async_teardown_started` compatible at the widget layer. Verified with `uvx ruff check src/derzug/core/zugwidget.py src/derzug/core/widget_runtime.py tests/test_core/test_zugwidget.py src/derzug/utils/testing.py` and `pytest -q tests/test_core/test_zugwidget.py tests/test_utils/test_code2widget.py tests/test_integrations.py` (`86 passed, 1 skipped`).
- 2026-03-31: Completed the first semantic-unification slice for `Coords` and `Filter`. Runtime execution now builds a validated task once and reuses that task for both async dispatch and legacy synchronous execution, instead of restating the semantics in `_run()` and `_build_execution_request()`. `Coords.get_task()` still exports a stored-state snapshot so workflow compilation does not depend on live patch context. Verified with `uvx ruff check src/derzug/widgets/coords.py src/derzug/widgets/filter.py tests/test_widgets/test_coords.py tests/test_widgets/test_filter.py` and `pytest -q tests/test_widgets/test_coords.py tests/test_widgets/test_filter.py tests/test_core/test_zugwidget.py` (`139 passed, 3 skipped`).
- 2026-03-31: Completed the next semantic-unification slice for `Table2Annotation` and `Select`. `Table2Annotation` now validates once and reuses the same task for both async execution and synchronous fallback. `Select` now emits from the canonical `SelectTask` path instead of separate handwritten patch/spool execution branches, while still preserving the current UI state for workflow export. Verified with `pytest -q tests/test_widgets/test_table2annotation.py tests/test_widgets/test_select.py` and added direct task-vs-widget equivalence coverage.
- 2026-03-31: Migrated `DataFrameLoader` and `Spool` off `ConcurrentWidgetMixin` onto the shared widget runtime. `DataFrameLoader` now dispatches its bound-source task through `WidgetExecutionRuntime`, and `Spool` now snapshots either settings-backed source state or current input-backed spool state into one worker execution request that returns both preview state and final outputs. `Spool.get_task()` now exports either a source task or a transform task depending on the current source mode, instead of relying on a separate background scheduling stack. Verified with `pytest -q tests/test_widgets/test_spool.py tests/test_widgets/test_table2annotation.py tests/test_widgets/test_dataframe_loader.py tests/test_widgets/test_select.py tests/test_core/test_zugwidget.py` (`207 passed, 7 skipped`).
- 2026-03-31: Completed the workflow portability slice. The execution engine, compiler, and graph validation now resolve effective ports from task instances, so stable adapter tasks can participate without dynamic class reconstruction. Callable-backed workflow nodes now serialize as `CallableTaskAdapter`, passthrough source nodes now stay as stable `MultiPassThroughTask` instances, and legacy dynamic-task metadata still reloads for backward compatibility. Verified with `pytest -q tests/test_utils/test_code2widget.py tests/test_workflow_compiler.py tests/test_workflow_engine.py` (`41 passed`), including assertions that callable-backed tasks round-trip as `CallableTaskAdapter`.
- 2026-03-31: Extended the shared canonical-task execution path across the remaining patch-processing widgets. `PatchDimWidget` now provides a `_validated_task()` hook plus shared `_build_execution_request()` and `_run()` logic, and `Analytic`, `Calculus`, `Norm`, `Normalize`, `Taper`, `Fourier`, `Detrend`, `Resample`, `Rolling`, `Stft`, and `FBE` now execute from their exported task model instead of separate handwritten patch-method branches. Verified with `pytest -q tests/test_widgets/test_analytic.py tests/test_widgets/test_calculus.py tests/test_widgets/test_norm.py tests/test_widgets/test_normalize.py tests/test_widgets/test_taper.py tests/test_widgets/test_fourier.py tests/test_widgets/test_detrend.py tests/test_widgets/test_resample.py tests/test_widgets/test_rolling.py tests/test_widgets/test_stft.py tests/test_widgets/test_fbe.py tests/test_core/test_patchdimwidget.py tests/test_core/test_zugwidget.py` (`286 passed, 20 skipped` across the focused runs).
- 2026-03-31: Reduced duplicated execution logic in the remaining adapter-style widgets. `Aggregate`, `Annotation2DataFrame`, binary `UFunc`, unary `UFunc`, and `Code` now route interactive execution through the same canonical task objects they export, while preserving widget-side validation, logging, summaries, and no-input workflow export behavior. Verified with `pytest -q tests/test_widgets/test_aggregate.py tests/test_widgets/test_annotation2dataframe.py tests/test_widgets/test_ufunc.py tests/test_widgets/test_ufunc_unary.py tests/test_widgets/test_code.py tests/test_integrations.py`.
- 2026-03-31: Added shared task-backed request/execution helpers in `ZugWidget` and moved the remaining helper-compatible widgets onto them. `PatchDimWidget`, `Aggregate`, `Annotation2DataFrame`, `UFunc`, `Table2Annotation`, `Filter`, and `Coords` now share the same base request construction and single-output normalization path instead of each open-coding it. Verified with `pytest -q tests/test_core/test_zugwidget.py tests/test_core/test_patchdimwidget.py tests/test_widgets/test_aggregate.py tests/test_widgets/test_annotation2dataframe.py tests/test_widgets/test_ufunc.py tests/test_widgets/test_ufunc_unary.py tests/test_widgets/test_table2annotation.py tests/test_widgets/test_filter.py tests/test_widgets/test_coords.py tests/test_widgets/test_code.py tests/test_integrations.py` (`294 passed, 12 skipped` across the focused runs).

Phase 1 is still in progress. The branch has made real progress on the semantic cleanup, but it should not be described as fully complete until the remaining widget audit and repo-wide verification pass have been rerun from the current worktree state.

## Core Direction

- Keep `get_task()` as the canonical semantic contract for widgets.
- Move validation to task-backed preflight derived from the canonical task or spec path.
- Extract async scheduling and teardown logic out of `ZugWidget` into a dedicated runtime or controller component.
- Replace dynamic generated task classes with first-class serialized adapter specs.
- Eliminate long-term execution exceptions for widgets that participate in workflow compilation.

## Implementation Changes

### Canonical semantics

- Redefine the widget contract so `get_task()` is the only semantic source for widget behavior.
- Remove duplicated business rules from `_run()`, `_build_execution_request()`, and similar widget-local helpers.
- Limit widget code to:
  - normalizing UI state before semantic export
  - presenting validation failures in a user-facing way
  - applying results back to widget state and outputs
- Derive interactive execution, workflow compilation, and validation from the same canonical task or workflow object.

### Execution runtime

- Extract worker-thread execution, latest-wins scheduling, stale-result suppression, teardown invalidation, and error routing out of `ZugWidget`.
- Keep `ZugWidget` as a UI-oriented shell responsible for signals, message display, and result rendering.
- Introduce a dedicated execution runtime component that:
  - captures immutable execution input
  - executes canonical workflow objects off-thread
  - returns normalized results to the widget thread
  - owns lifecycle and cancellation semantics
- Remove parallel ad hoc scheduling models once widgets are migrated.

### Workflow portability

- Introduce explicit workflow adapter or spec models for generated workflow nodes such as callable-backed tasks, passthrough adapters, and configured patch-method adapters.
- Stop using runtime-generated task subclasses as the portable serialized unit.
- Make JSON and YAML workflow serialization store those adapter specs directly instead of reconstruction metadata for dynamic classes.
- Update workflow validation and loading to operate on first-class portable node specs.

### Phase 1 widget migration

- Migrate high-duplication processing widgets first:
  - `Coords`
  - `Filter`
  - `Table2Annotation`
  - `Select`
  - callable-generated widgets from `code2widget`
- Migrate source and boundary widgets in the same phase:
  - `Spool`
  - `DataFrameLoader`
- Remove legacy execution paths once the shared runtime and canonical semantics are in place.

## Acceptance Criteria

- No workflow-participating widget keeps a second semantic implementation path separate from `get_task()`.
- No workflow-participating widget depends on a separate scheduling stack such as `ConcurrentWidgetMixin` for its core execution lifecycle.
- Generated callable-backed workflow nodes round-trip without dynamic task-class reconstruction.
- Interactive widget execution and `get_task()` execution produce identical results and validation behavior for representative widgets.

## Testing Plan

- Add base runtime tests for:
  - latest-wins result application
  - teardown ignoring queued late results and errors
  - worker completion only affecting live widgets
  - source widgets and processing widgets using the same runtime contract
- Add semantic single-source tests for representative widgets so interactive execution and canonical task execution stay aligned.
- Add portability tests for callable-backed and multi-port generated workflow nodes to ensure JSON and YAML round-trips work in a fresh interpreter.
- Keep full workflow engine, workflow compiler, widget integration, and repo-wide lint green through the migration.

## Assumptions

- A clean break is acceptable for internal extension points and internal widget subclass contracts.
- `get_task()` remains the long-term canonical widget contract.
- Validation should be derived from canonical task or spec construction, with widget code only responsible for presentation.
- Special widgets are in scope for phase 1 and should not remain architectural exceptions.
