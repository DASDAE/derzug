# Agent Guide

This file gives AI/code agents a practical checklist for contributing safely to this project.

## Scope and priorities

1. Keep changes minimal, targeted, and test-backed.
2. Preserve existing DerZug conventions over personal preferences.
3. Prefer consistency with existing code/tests/docs in this repo.


## Import layering

```
models  ->  workflow  ->  nodes  ->  { core, widgets, views, conductor }
                                      ^ Qt lives only here
```

Nothing left of `derzug.nodes` may import Qt, Orange, or a widget module —
that is what lets the workflow engine run headlessly. When a task needs
behavior that currently lives on a widget, move the behavior *down* into the
node module as a free function and have the widget call it.

`tach` enforces this from `tach.toml`; it runs as a `prek` hook, so
`prek run --all-files` covers it. Do not silence a failure with `# tach-ignore`
without a comment saying why and what would fix it. See `docs/dev/nodes.md`.

## Environment setup

See `README.md` for installation and `docs/dev/guidelines.md` for conventions.

Typical setup:

```bash
git pull origin main --tags
pip install -e ".[dev]"
```

## Linting and formatting

- Always run `prek run --all-files` before considering a job complete.
- This repo uses **prek**, configured in `prek.toml`; there is no `.pre-commit-config.yaml`.
- Project lint/format is driven by those hooks and the Ruff config in `pyproject.toml`.

```bash
prek run --all-files
```

Tip: running twice can apply auto-fixes on first pass.

## Testing requirements

See `docs/dev/guidelines.md` for test-authoring conventions.

Run targeted tests for changed behavior, then broader tests as needed:

```bash
pytest tests/path/to/affected_test.py
pytest tests
```

Bare `pytest` collects `tests/` only; the benchmark suite is opt-in via an explicit path.

For coverage checks:

```bash
pytest tests --cov derzug --cov-report term-missing
```

For doctests:

```bash
pytest src/derzug --doctest-modules
```

## Benchmarks

If the change touches a hot path — the workflow graph, executor, or task layer; the spool
utilities; sampling; or a widget render path — compare against `main` before opening the PR:

```bash
python scripts/bench_compare.py --baseline main
```

Paste the resulting table into the PR description and investigate anything past 20%.
Add the `benchmark` label to the PR so CodSpeed runs in CI. See `docs/dev/benchmarking.md`.

## Test authoring conventions

- Put tests under `tests/` mirroring package structure.
- Group tests in classes.
- Place fixtures as close as practical to usage (class, module, then `conftest.py`).

## Code conventions

- Prefer `pathlib.Path` over raw path strings (except performance-sensitive bulk file workflows).
- Use snake_case dataframe column names when possible.
- Use `df["col"]` (getitem), not `df.col` (getattr).
- Prefer non-inplace dataframe operations unless inplace is explicitly required.
- Add type hints for public functions/methods.
- Use NumPy-style docstrings for public APIs.
- Keep comments meaningful; do not restate obvious code.
- All functions must have a docstring; proper numpy docstrings for public functions and a few liners for private.
- Do not manually hard-wrap Markdown or Quarto prose. In `.md` and `.qmd` files, keep paragraphs on single logical lines and let the editor soft-wrap them.


## Quality bar for agent changes

Before handing off:

1. Code compiles/runs for changed paths.
2. Relevant tests pass locally.
3. Lint/format checks pass.
4. Docs updated for user-visible behavior changes.
5. No unrelated refactors bundled with bug fixes.
6. Hot-path changes compared against `main` with `scripts/bench_compare.py`, with the table in the PR and any regression past 20% explained.
7. `tach check` passes (via `prek run --all-files`) with no new `# tach-ignore`.

## When uncertain

- Prefer existing patterns in nearby DerZug modules/tests.
- Call out assumptions explicitly in PR notes.
- Choose the simpler behavior-preserving implementation first.
