# Benchmarks

Two separate trees. Full guide: [docs/dev/benchmarking.md](../docs/dev/benchmarking.md).

| Tree | Qt? | What it covers | Instrumented in CI? |
|---|---|---|---|
| `core/` | **No** — a session fixture fails the suite if any Qt module is imported | Workflow graph, task, and execution layers; spool annotation masking; strided sampling; DerZug module-body import cost; a fixed-work drift control | **Yes** |
| `qt/` | **Yes** — real `QApplication`, real offscreen paint | Waterfall and Wiggle render paths (`show()` → `set_patch` → `processEvents` → `grab`), `_compute_default_levels`, `_should_reset_view_for_new_patch`, and the cursor-readout helpers | **No** — see below |

`qt/` skips itself at collection time when no Qt stack is installed, so `pytest benchmarks` works in a minimal environment.

Only `core/` is instrumented in CI. CodSpeed's simulation mode is valgrind-based, and an instruction count for a Qt paint is overwhelmingly *Qt's* instructions — a PyQt6 patch bump would read as a huge phantom regression while a real DerZug one stayed buried. The Qt tree runs once un-instrumented in CI as a rot guard and is measured locally in walltime, where GUI timing means something.

## Running

```bash
python scripts/bench_compare.py --baseline main            # the check to run before a PR (~45s)
python scripts/bench_compare.py --baseline main --suite qt # Qt render paths (~80s)

python -m pytest benchmarks -q                             # correctness only, no timing (~3s)
python -m pytest benchmarks/core --codspeed                # absolute numbers, no baseline
```

Bare `pytest` does **not** collect this directory — `testpaths` in `pyproject.toml` limits it to `tests/`.

## Why a run costs what it costs

Wall time is set by pytest-codspeed's per-benchmark time budget, **not** by how much work a benchmark does: a faster benchmark simply gets more rounds in the same window. Shrinking the test data would not make a run shorter. The levers are the budget and the benchmark count, both set in `scripts/bench_compare.py` (`_SUITE_BUDGET`).

Warmup is the quality-critical half of that budget. Measured spread between two runs of *identical* code, 26 core benchmarks:

| warmup / measured | Per side | Worst spread | Verdict |
|---|---|---|---|
| 1.0s / 3.0s | 110s | 6% | upstream default, more precision than a 20% threshold needs |
| **0.3s / 0.3s** | **19s** | **8%** | **what `core` uses** |
| 0.1s / 0.3s | 14s | 110% | unusable — CPython has not finished specialising |

`qt/` keeps the 1.0s/3.0s default: a single Waterfall or Wiggle render takes 35–340 ms, so a 0.3 s window would leave it one or two rounds, which is not a measurement.

## Adding one

- Name modules `test_<area>_benchmarks.py`, classes `Test<Area>Benchmarks`, functions `test_<operation>`. Qt modules take a `test_qt_` prefix — there are no `__init__.py` files here, so basenames must be unique across both trees.
- Mark measured functions with `@pytest.mark.benchmark` (pytest-codspeed's marker, not the `benchmark` fixture).
- Hoist all setup into a module-, class-, or session-scoped fixture. Only the operation under test belongs in the timed body.
- Anything faster than ~50 µs needs an explicit `for _ in range(N)` loop, or it sits below the comparison tool's noise floor and is ignored.
- Prefer **pairs** — a fast path next to the slow path it replaced (`test_run_chain` vs `test_map_chain`). A divergence between two related benchmarks is a far clearer signal than one absolute number moving.
- Qt render benchmarks must `show()` the widget: `ZugWidget._request_ui_refresh` is a no-op while the window is hidden, so a hidden widget silently measures nothing.
- Every benchmark costs the same wall time regardless of what it measures, so add one only if it guards a path that can realistically regress.
