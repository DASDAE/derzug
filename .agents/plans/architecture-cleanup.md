# Plan: Architecture Cleanup — Dead Code, Consolidation, Layering, Performance

## Context

An architectural review (2026-07-03) found the widget layer coherent and the major
rendering hot paths already addressed (waterfall/wiggle speedups, strided
subsampling, `autoLevels=False`, 60 Hz mouse rate limiting). The remaining
problems are structural:

1. ~1,200 lines of confirmed dead code, including an entire abandoned
   pydantic-model→widget generation layer.
2. Three competing mechanisms for building patch-processing widgets.
3. `views/orange.py` (4,012 lines) mixing five concerns, with monkeypatches of
   orangecanvas installed at **import time**.
4. A core→views dependency inversion: `ZugWidget` reaches into
   `derzug.views.orange` module privates, including a fallback that scans
   `app.allWidgets()` on every source-widget `showEvent`.
5. Duplicated small helpers (value formatters ×4, `_ordered_pair` ×2,
   scalar-coercion ×2) and confusing module naming (`orange.py` ×4 meanings,
   `workflow/` vs `workflows/`, `UFunc` class in `ufunc_unary.py` vs
   `UFuncOperator` class in `ufunc.py`).

Phases are ordered lowest-risk-first and are independently landable. Each phase
should be its own PR, pass the full test suite, and run pre-commit before
committing.

---

## Phase 1 — Delete confirmed dead code (zero risk, mechanical)

Verified to have no production consumers (grep across `src/` and `tests/`):

| Target | Evidence |
|---|---|
| `src/derzug/core/zugmodel.py` (91 lines) | Only imported by `pyqt_ui_builder.py` and its own tests |
| `src/derzug/core/abstractcontrols.py` (151 lines) | Only imported by `pyqt_ui_builder.py` and its own tests |
| `src/derzug/utils/pyqt_ui_builder.py` (510 lines) | Zero importers anywhere |
| `src/derzug/utils/docstring.py` (~100 lines) | Only re-exported from `utils/__init__.py`; never called |
| `src/derzug/exceptions.py` (55 lines) | `DerZugError`/`DerZugWarning` never raised or caught |
| `src/derzug/views/waterfall.py` (3 lines) | Docstring-only stub |
| Compat aliases in `src/derzug/core/__init__.py` | `SlanRodModel`, `SlanRodBaseModel`, `DerzugModel`, `DerzugBaseModel` — nothing imports them; the "workflow code currently imports these" comment is stale |
| Commented-out debug block in `src/derzug/__init__.py` | `pyqtRemoveInputHook` lines 23–26 |

Also delete the now-orphaned tests: `tests/test_core/test_model.py`,
`tests/test_core/test_abstractcontrols.py`, `tests/test_utils/test_docstring.py`.

Update `src/derzug/core/__init__.py` and `src/derzug/utils/__init__.py`
exports/`__all__` accordingly. Re-grep for each deleted symbol after removal to
confirm nothing dangles (including `.ows` files and docs).

---

## Phase 2 — Renames and naming hygiene

All internal-only renames; no entry-point names change except where noted.

1. `src/derzug/orange.py` → `src/derzug/settings.py` (it only holds the
   `Setting` subclass). Update the ~27 widget imports mechanically.
2. Fix the crossed UFunc naming: `ufunc_unary.py` defines class `UFunc`;
   `ufunc.py` defines class `UFuncOperator`. Align file names with class names.
   **Caveat:** these are `derzug.widgets` entry points in `pyproject.toml` and
   widget qnames are persisted in saved `.ows` workflows — keep the old module
   paths as import shims (module that re-exports the class) for one release.
3. `src/derzug/workflows/` (bundled `.ows` package data) → consider
   `example_workflows/`; requires updating the
   `orange.widgets.tutorials` entry point and `package-data` in
   `pyproject.toml`. Low priority — do only if touching packaging anyway.
4. Freshen the stale "mid-refactor" docstring in `workflow/__init__.py` if the
   lazy-import rationale no longer holds.

---

## Phase 3 — Consolidate duplicated helpers

1. **Value formatting** — make `utils/display.py` the single owner of
   numeric/datetime/timedelta display policy. Fold in and delegate:
   - `ndim_controls.format_nd_coord_value`
   - `waterfall._format_coord_value` (line ~92)
   - `spool._format_table_value`
   - `selection._format_coord_value` already delegates; keep it or inline it.
   Watch for intentional differences (slider labels truncate timedeltas to 20
   chars); make those explicit parameters, not separate functions.
2. **Small helper dedup**: `_ordered_pair` exists in `widgets/selection.py` and
   `utils/spool.py`; scalar coercion exists as `_coerce_python_scalar`
   (selection) and `_normalize_coord_scalar` (utils/spool). Move one canonical
   version each into `utils/` and import.
3. Add/extend tests in `tests/test_utils/test_display.py` pinning the shared
   formatting behavior (datetime64, timedelta64, float sig-figs, ints).

---

## Phase 4 — Split `views/orange.py` and defer monkeypatches to app startup

Current file mixes: (a) orangecanvas monkeypatches (~1,500 lines: annotation
clipboard, arrow snap/color, text font/alignment palettes), (b) main
window/config/scheme/widget-manager classes, (c) dialogs (About, shortcuts,
experimental warning, code-workflow warning), (d) Linux desktop integration,
(e) GPU rendering config.

1. Split into:
   - `views/canvas_patches/` (one module per patch family, each exposing an
     explicit `install()`)
   - `views/main_window.py` (DerZugMain, DerZugMainWindow, DerZugConfig,
     scheme/manager classes, ActiveSourceManager, event-filter controllers)
   - `views/dialogs.py`
   - `views/platform.py` (desktop entry, GPU config, sigint/exception handler)
   - Keep `views/orange.py` as a thin re-export shim for one release
     (tests and `ZugWidget` currently import from it).
2. **Remove import-time side effects**: the five `_install_canvas_*()` calls
   currently execute at module import. Move all `install()` calls into the
   application startup path (`DerZugMain`/`main()` construction), so importing
   any `views` module never patches global Orange classes.
3. Update `tests/test_views/test_orange_qt.py` imports; add a test asserting
   that importing the views modules does not mutate the patched orangecanvas
   attributes (guards against regressions).

**Feature-cut decision point (needs Derrick's call):** the canvas whiteboard
polish (arrow color/text style palettes, octilinear snap, annotation clipboard)
is ~1,500 lines of monkeypatched UI chrome and the most Orange-upgrade-fragile
code in the repo. Decide keep vs. drop before investing in its split; if
dropped, Phase 4 shrinks substantially.

---

## Phase 5 — Invert the core→views dependency

`core/` currently knows about the app window:

- `ZugWidget._ensure_active_source_selection` imports `derzug.views.orange`,
  reads `_APP_ACTIVE_SOURCE_MANAGER` / `_APP_ACTIVE_SOURCE_MAIN_WINDOW`, and
  calls private methods (`_set_active_widget`, `_source_widgets`). Its fallback
  scans `app.topLevelWidgets() + app.allWidgets()` on **every** source-widget
  `showEvent`, scheduled twice (immediate + 0 ms timer).
- `core/widget_messages.py` imports `views/orange_errors.py`.

Plan:

1. Define a narrow interface in core (e.g. `core/services.py`):
   `ActiveSourceService` protocol with `promote_if_needed(widget)`; a module
   registry `register_active_source_service()` / `get_active_source_service()`.
2. `ActiveSourceManager` (views) registers itself at app startup; `ZugWidget`
   calls the service if registered, else no-ops. Delete the `allWidgets()`
   fallback scan entirely.
3. Move `orange_errors.py` (error dialog + report building) out of `views/`
   into a location importable by core without pulling in the main window —
   either `core/error_dialog.py` or keep the module but make it import-light;
   the goal is that `core/` never imports `views/`.
4. Tests: update `test_zugwidget.py` source-selection tests to use the
   registry; verify a widget shown with no service registered does not raise.

Performance side effects of this phase: removes the O(all-widgets) scan and the
double-scheduled timer — this is the main remaining perf item from the review.

---

## Phase 6 — One widget-building mechanism (larger, needs buy-in)

Today there are three ways to define a patch-processing widget; after Phase 1
there are two:

1. Hand-written classes (`normalize.py`, `norm.py`, `detrend.py`,
   `analytic.py`, `taper.py`, `ufunc_unary.py`, `calculus.py`, …) — each
   110–150 lines of near-identical boilerplate (dim combo + option combo,
   Patch in/out signals, `get_task()` → `PatchConfiguredMethodTask`).
2. `utils/code2widget.py` (`function_to_widget` / `widget_class_from_callable`)
   — used only by `widgets/code.py`.

Plan:

1. **Remove the `Norm` widget** — fully subsumed by `Normalize` (both call
   `patch.normalize`; Normalize adds standardize). Not referenced by the
   bundled quickstart workflow. Ship a deprecation shim mapping old `.ows`
   qnames to `Normalize` (or accept the break while pre-alpha — decide).
2. Build a small declarative factory (or extend `code2widget`) so a simple
   processing widget is a config entry: name/icon/keywords, method name,
   option list, error text. Migrate 2–3 widgets first (e.g. `detrend`,
   `analytic`) to validate settings persistence, `.ows` round-tripping, and
   `get_task()` output before migrating the rest.
3. Acceptance: saved workflows created before the migration still load; widget
   registry shows identical names/categories; per-widget tests keep passing.

---

## Phase 7 — Smaller follow-ups (batch opportunistically)

- **Extract fitting math from `annotation_overlay.py`** (3,555 lines): move the
  pure ellipse/hyperbola/line/square least-squares fitting into
  `utils/fitting.py`, testable without Qt. Roughly halves the file.
- **`utils/testing.py`** imports pytest but ships in the wheel. Either move it
  under `tests/` or document it as a public testing API (and make pytest an
  optional import).
- **Shared worker pool**: each `ZugWidget` owns a
  `ThreadPoolExecutor(max_workers=1)`; a 25-widget workflow keeps 25 idle
  threads. Replace with a shared pool + per-widget serial queues in
  `core/widget_runtime.py`. Preserve the per-widget ordering guarantee and
  stale-result suppression.
- Keep `import derzug` lazy when touching `utils/__init__.py` — its eager
  `code2widget` import is currently the only thing that would pull Orange in
  early for someone importing `derzug.utils` for `format_display`.

---

## Ordering and risk summary

| Phase | Risk | Size | Depends on |
|---|---|---|---|
| 1 Dead code | none | ~1,200 lines deleted | — |
| 2 Renames | low (entry-point/`.ows` shims) | small | 1 |
| 3 Helper dedup | low | small | — |
| 4 Split views/orange | medium (test churn) | large | keep/drop decision |
| 5 Core→views inversion | medium | medium | 4 (or standalone) |
| 6 Widget factory | medium-high (`.ows` compat) | large | 1, 2 |
| 7 Follow-ups | low | small each | — |

Open decisions for Derrick:
1. Keep or drop the canvas whiteboard-polish suite (Phase 4)?
2. Remove `Norm` with a shim, or clean break while pre-alpha (Phase 6)?
3. Is `.ows` backward compatibility a hard requirement yet, or acceptable to
   break with a release note?
