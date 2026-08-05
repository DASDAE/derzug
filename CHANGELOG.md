# Changelog

All notable user-facing changes to DerZug are documented here.

## Unreleased

### Fixed

- Canvas and headless execution now resolve default dimensions identically. Previously a widget on the canvas could pick a different dimension than the same node run headlessly from the same saved parameters:
  - Dimension choosers no longer derive the default from the alphabetically sorted dim list; when a patch has no `time` dimension the default is now the first patch dimension, matching `resolve_patch_dim`.
  - The Fourier widget's inverse-transform dimension fallback now prefers a `ft_*` axis (matching `FourierTask.run`) instead of the forward-transform default, which preferred `time`.
  - Aggregate's phase-weighted stack no longer fails headlessly when no stack dimension is set; it defaults to `distance` (else the first patch dimension), the same default the widget applies, and the widget's transform-dimension chooser now excludes that effective stack dimension.
- The Coords widget now builds and validates its task exclusively through the node layer, so the task that runs on the canvas and the task exported into a saved workflow are always identical. Two behavior fixes come with it: headless callers filling only the `set_coords` draft fields (`set_coords_dim`/`start`/`stop`/`step`) now get a real coordinate update instead of a silent no-op, and data-flipping a non-dimension coordinate now reports through the "Invalid flip selection" banner instead of a generic operation failure.
- The Spool widget's preview/output pipeline now runs the same node-layer select and chunk stages as a headless workflow. A chunk value that parses to `None` (e.g. the text `None`) now disables chunking headlessly, matching the canvas chunk controls.
- Filter `mode` parameters are now validated `Literal`s on the params models, so an unsupported boundary mode (e.g. `SavgolFilterParams(mode="reflect")`, which SciPy rejects) fails at validation with a clear message instead of surviving until the SciPy call.
- `SelectionState.apply_select_params` now accepts `patch=None` for display-only hosts, replacing the Select widget's hand-built state.
- PlayAudio's signal processing (patch validation, rate inference, PCM normalization, time-scaling and resampling) moved to the Qt-free `derzug.nodes.playaudio`, and the node's `time_scale`/`volume_percent` parameters are now actually consumed there: the new `render_audition(patch, params)` returns device-ready PCM headlessly.

### Changed (breaking)

DerZug is pre-alpha; these renames are a clean break with no compatibility
shims. Workflows (`.ows` files) saved with an earlier version that reference the
affected widgets will not load and must be rebuilt.

- The speculative `derzug.FileSystemSource` (and its provenance-sidecar loading helpers) was removed; it had no concrete subclass and no callers. The small `Source` ABC the workflow engine consumes remains.
- The `derzug.orange` module (the `Setting` subclass) moved to
  `derzug.settings`. Update `from derzug.orange import Setting` to
  `from derzug.settings import Setting`.
- The two UFunc widgets were disambiguated so file, class, display name, and
  entry-point key all agree:
  - Unary transform widget: class `derzug.widgets.ufunc_unary.UFunc` →
    `derzug.widgets.ufunc_unary.UFuncUnary`; display name `UFunc` → `UFuncUnary`.
  - Binary operator widget: module `derzug.widgets.ufunc` →
    `derzug.widgets.ufunc_binary`; class `UFuncOperator` → `UFuncBinary`;
    display name `UfuncBinary` → `UFuncBinary`; entry-point key `UFunc` →
    `UFuncBinary`.
- The `Norm` widget was removed; it was fully subsumed by `Normalize` (both
  call `patch.normalize`, and `Normalize` additionally offers standardize).
  Workflows referencing `derzug.widgets.norm.Norm` will not load; rebuild them
  with `Normalize`.
- Widget parameters are now stored as a single serialized pydantic model
  (`_state` blob) instead of many flat per-parameter `Setting`s. Every widget
  exposes typed `params` (and, for visual widgets, `view`) models via
  `get_params`/`apply_params` (and `get_view`/`apply_view`). `.ows` workflows
  saved by an earlier version store parameters in the old flat layout and will
  load with default parameters; re-save them to migrate. This is a
  compatibility break and warrants a minor version bump (0.0.x → 0.1.0).
