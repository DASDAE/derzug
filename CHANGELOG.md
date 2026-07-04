# Changelog

All notable user-facing changes to DerZug are documented here.

## Unreleased

### Changed (breaking)

DerZug is pre-alpha; these renames are a clean break with no compatibility
shims. Workflows (`.ows` files) saved with an earlier version that reference the
affected widgets will not load and must be rebuilt.

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
