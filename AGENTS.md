# Agent Instructions

The detailed agent guide for this repository is in `.agents/agents.md`. Load and follow it before making changes.

## Quick reference

DerZug is a PyQt6/Orange3 canvas application for interactive DAS visualization, built on [DASCore](https://dascore.org). Widgets live in `src/derzug/widgets/`, the Qt-free streaming workflow engine in `src/derzug/workflow/`.

```bash
pytest tests                                    # test suite (bare `pytest` also works)
prek run --all-files                            # lint and format; this repo uses prek, not pre-commit
python scripts/bench_compare.py --baseline main # performance check before a PR
```

Before handing off: tests pass, lint passes, docs updated for user-visible changes, and — if the change touches a hot path — a benchmark comparison against `main` with no unexplained regression. See [docs/dev/benchmarking.md](docs/dev/benchmarking.md).

## Pull request labels

| Label | Effect |
|---|---|
| `benchmark` | Runs the CodSpeed benchmark workflow on the PR. Add it for any performance-relevant change. |
| `no_ci` | Skips the test and lint workflows. |
| `debug` | Starts the interactive noVNC demo workflow. |
