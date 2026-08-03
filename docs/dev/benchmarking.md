---
title: Benchmarking
---

DerZug uses [CodSpeed](https://codspeed.io/) for continuous performance monitoring and a local comparison script for the check you run before opening a pull request.

## The one command that matters

Before opening a PR that touches a hot path — the workflow graph, executor, or task layer; the spool utilities; sampling; or a widget render path — run:

```bash
python scripts/bench_compare.py --baseline main
```

This checks out `main` into a throwaway worktree, pins its dependencies to match yours, verifies each interpreter really imports its own copy of DerZug, runs your current benchmark files against both sides, and prints a table ranked worst-regression-first. Paste that table into the PR description and investigate anything past 20%.

Expect roughly 45 seconds (`--repeat 2` roughly doubles it). The first run also has to build the baseline environment, which takes a few minutes more and several hundred megabytes when uv's cache is cold; later runs reuse it.

Useful flags:

| Flag | Why |
|---|---|
| `-k EXPR` | Compare a single benchmark in about twenty seconds. |
| `--max-time` / `--warmup-time` | Override the per-benchmark time budget. Runtime is set by this, not by data size — see `benchmarks/readme.md`. Warmup below 0.3s makes the numbers meaningless. |
| `--suite qt` | Compare the Qt render benchmarks instead of the Qt-free ones (~80s; they use a larger budget because a single render takes 35-340ms). |
| `--repeat 2` | Interleave two passes per side. Do this before quoting a number anywhere. |
| `--fail-on-regression` | Exit non-zero on a regression, for scripting. |
| `--from-json a.json b.json` | Re-render a previous comparison instantly from `.codspeed_compare/`. |
| `--baseline-dir PATH` | Use a prepared checkout instead of managing a worktree. |

## Reading the output

The comparison is deliberately conservative — it would rather miss a small regression than cry wolf.

- **`median_ns` is primary, `min_ns` corroborates.** A benchmark is only called changed when both move past the threshold in the same direction. `min` alone is untrustworthy: pytest-codspeed picks its round count adaptively against a time budget, so a slower build gets fewer rounds and its minimum is drawn from a smaller sample, biased upward. That would amplify every apparent regression.
- **`noisy`** means the baseline was too jittery to compare (relative standard deviation above 10%) or too fast to measure (median under 50 µs). These never count as regressions.
- **The control benchmark.** `test_fixed_python_work` is fixed pure-Python work that touches nothing in DerZug. If it moves more than 10% between the two runs, your machine drifted — thermal throttling, a background build — and the script says `DRIFTED` and downgrades every verdict to a hint. Re-run on an idle machine.
- **Dependency drift.** The baseline environment is pinned to your current one, and the script refuses to run if either interpreter resolves `derzug` outside its own tree. Any remaining package mismatch — a differing version, or a package installed on only one side — is reported as a warning; `--strict-env` turns it into an error.
- **Untrustworthy comparisons never read as a pass.** If the control drifted, the control is missing, a benchmark appears on only one side, or nothing was comparable, the run is marked untrustworthy. `--fail-on-regression` exits non-zero in that case too, so a broken run cannot masquerade as a clean one.
- **`--repeat N` compares pass by pass.** Each interleaved baseline/head pair is compared on its own and the least alarming result wins, so a regression has to reproduce in every pass. Merging raw timings across passes would pair a baseline from one pass with a head from another.

## Running benchmarks directly

```bash
python -m pytest benchmarks/core --codspeed     # Qt-free suite, instrumented
python -m pytest benchmarks/qt --codspeed       # Qt suite, instrumented
python -m pytest benchmarks -q                  # everything, un-instrumented
```

Without `--codspeed`, `@pytest.mark.benchmark` degrades to a plain test, so the last form is a fast correctness check on the benchmark code itself.

Note that bare `pytest` does **not** collect `benchmarks/` — `testpaths` in `pyproject.toml` limits it to `tests/`. Pass the path explicitly.

## Writing a benchmark

See [`benchmarks/readme.md`](../../benchmarks/readme.md) for the tree layout and why a run costs what it does. The conventions:

- `benchmarks/core/` is Qt-free and `benchmarks/qt/` is not. A session fixture in `benchmarks/core/conftest.py` fails the suite if anything drags a Qt binding in; the authoritative version of that guard is `test_core_modules_stay_qt_free` in `tests/test_utils/test_lazy_imports.py`.
- The Qt tree skips itself at collection time when no Qt stack is installed, so `pytest benchmarks` works in a minimal environment.
- Module names are `test_<area>_benchmarks.py`, classes are `Test<Area>Benchmarks`, functions are `test_<operation>`. Qt modules take a `test_qt_` prefix — there are no `__init__.py` files, so basenames must be unique across both trees.
- Mark each measured function with `@pytest.mark.benchmark`. That is pytest-codspeed's marker, not the `benchmark` fixture.
- Hoist every bit of setup into a module-, class-, or session-scoped fixture. Only the operation under test belongs in the timed body.
- Anything faster than about 50 µs needs an explicit `for _ in range(N)` loop, or it falls below the comparison tool's noise floor and is ignored.
- Every benchmark costs the same wall time regardless of what it measures, because the runtime is a fixed per-benchmark budget. Add one only if it guards a path that can realistically regress.
- Prefer **pairs**: a fast path next to the slow path it replaced. `test_run_chain` versus `test_map_chain` is the example worth copying — reverting the executor's spec-hoisting regresses one and not the other, which is a far clearer signal than a single absolute number.
- Qt render benchmarks must `show()` the widget. `ZugWidget._request_ui_refresh` is a no-op while the window is hidden, so a hidden widget silently measures nothing. End the timed body with `qapp.processEvents()` then `widget.grab()` to force a synchronous paint.

## Continuous integration

`.github/workflows/benchmarks.yml` runs on every push to `main` and on pull requests **labeled `benchmark`**. Add that label to a PR to get a CodSpeed report; the `labeled` trigger re-fires the workflow when you do.

CI instruments `benchmarks/core` only. CodSpeed's simulation mode is valgrind-based, and an instruction count for a Qt paint is overwhelmingly Qt's own instructions — a PyQt6 patch bump would show as a huge phantom regression while a real DerZug regression stayed buried. The Qt tree instead runs once, un-instrumented, as a rot guard, and is measured locally in walltime where GUI timing actually means something.

`runtests.yml` additionally runs `pytest benchmarks --collect-only` on Linux whenever that workflow runs (it has a `paths` filter covering Python files, workflows, and packaging), so the benchmark code cannot silently stop importing.

### One-time setup, not yet done

The CodSpeed step authenticates over OIDC and **the repository is not yet registered at codspeed.io**. It is gated behind a `CODSPEED_ENABLED` repository variable so it is skipped rather than failing. To turn it on: register the repo at codspeed.io, install the GitHub App, then set the `CODSPEED_ENABLED` repository variable to `true`. Local comparison works either way.

## Profiling a regression

Once a benchmark is identified, profile it:

```bash
pip install pytest-profiling snakeviz
pytest benchmarks/core/test_workflow_execution_benchmarks.py -k test_map_chain --profile
snakeviz prof/test_map_chain.prof
```
