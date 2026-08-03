# Benchmarks

Performance benchmarks for DerZug, measured continuously with [CodSpeed](https://codspeed.io) (see `.github/workflows/benchmarks.yml`).

The suite covers the pure-python hot paths that widgets call into, so the measurements stay deterministic and free of Qt event-loop noise:

| File | Covers |
| ---- | ------ |
| `test_bench_workflow.py` | Graph construction, validation, topological sort, fingerprinting, serialization and scalar/streaming execution of the workflow engine. |
| `test_bench_patch_pipeline.py` | An end-to-end DASCore processing chain (detrend, band-pass, taper, envelope) executed through the workflow engine, plus mapping it over a spool. |
| `test_bench_annotations.py` | Annotation model validation, JSON round trips, merging, summarizing and widget-state round trips. |
| `test_bench_spool.py` | Vectorized annotation-overlap masks and metadata normalization against a spool contents dataframe. |
| `test_bench_utils.py` | Display formatting, textbox parsing and the bounded-decimation helpers used before plotting. |

## Running locally

Benchmarks are plain pytest tests, so they can be run as a correctness check:

```bash
pytest benchmarks
```

To measure them with the CodSpeed CPU simulation instrument:

```bash
pip install pytest-codspeed
codspeed run --mode simulation -- pytest benchmarks --codspeed
```

Keep the numeric stack single threaded when measuring. CPU simulation serializes
threads, so BLAS/OpenMP thread pools only add overhead and noise:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
```

## Adding a benchmark

- Use the `benchmark` fixture: `benchmark(callable, *args, **kwargs)`.
- Keep a single iteration in the millisecond range; CodSpeed handles repetition.
- Prefer realistic input sizes, and assert on the result so a broken benchmark fails loudly.
- Avoid Qt widgets and file/network IO so measurements stay stable.
