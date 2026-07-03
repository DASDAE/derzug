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
