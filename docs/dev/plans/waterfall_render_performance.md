# Waterfall Render Performance Plan

## Summary

Make plotting large patches (tens of millions of samples) fast in the
`Waterfall` widget and related plot widgets. Profiling with a 3000×20000
(60M-sample, 480 MB float64) patch shows that most of the time to first
paint is avoidable overhead, not pyqtgraph rendering itself:

| Cost per new patch | Source | Measured |
| --- | --- | --- |
| Default color levels | `Waterfall._compute_default_levels` runs dascore's `_get_scale(None, "relative", data)` (Tukey fence via nan-percentiles) over every sample | ~1120 ms |
| Reset-on-new check | `Waterfall._should_reset_view_for_new_patch` runs full `np.array_equal` over the data plus every coord array | ~275 ms |
| Image upload | `setImage(display_data, autoLevels=True)` computes throwaway levels; full-res render | ~130–175 ms |
| Histogram level drag | pyqtgraph re-runs makeARGB over the full array per mouse event | ~120 ms/frame (≈8 fps) |

Total: ~1.5–2 s to first paint, plus sluggish color-limit interaction.

Benchmarks were run offscreen (`QT_QPA_PLATFORM=offscreen`) with
pyqtgraph `ImageItem` + `PlotWidget` mirroring the Waterfall render path.

## Planned Changes

### Phase 1 (current scope)

1. **Subsample before computing default color levels.** Percentile-based
   limits on a strided subsample (~100k samples) are statistically
   indistinguishable from the full array: 2.2 ms vs 1121 ms (≈500×).
   Slice `display_data` with computed strides down to ~100k samples in
   `_compute_default_levels` before calling `_get_scale`.
2. **Metadata-first reset-on-new check.** In
   `_should_reset_view_for_new_patch`, compare cheap facts first (dims,
   shape, dtype, coord endpoints) and only fall back to full-array
   comparisons when the cheap checks cannot distinguish the patches.
3. **Drop `autoLevels=True` from `setImage` calls.** In both
   `Waterfall._render_patch` and `PatchViewer`, the auto-computed levels
   are immediately overwritten by `_apply_default_levels` /
   `_apply_persisted_levels`, so the min/max pass is pure waste.

### Phase 2 (follow-ups, not yet scheduled)

- **Display-resolution decimated copy for the `ImageItem`.** Pooling to
  ~2× screen resolution (float32) costs ~240 ms once per patch, after
  which level drags render in ~8 ms (~120 fps) instead of ~120 ms. Also
  caps the cached QImage size, which currently scales linearly with the
  sample count. Keep full-resolution `data` in `_PreparedPatchRender`
  for cursor readout and selection; only `display_data` is decimated.
  A cached 2–3 level mip pyramid would keep zoomed-in detail crisp.
- **Cast display data to float32.** makeARGB on f32 measured ~1.7×
  faster than f64 (101 ms vs 176 ms) and halves memory traffic.
- ~~**Cursor readout via `searchsorted`.**~~ Done — `nearest_axis_index`
  uses `np.searchsorted` plus a neighbor check and no longer allocates a
  full-axis temp per mouse move. Guarded by
  `benchmarks/qt/test_qt_plot_axes_benchmarks.py`.
- **Wiggle widget rendering.** Done on branch `wiggle-render-perf`; see
  Progress below. Profiling showed the dominant cost was pen width, not
  item count: Qt's raster engine draws width-2 polylines ~16x slower
  than width-1 (933 ms vs 56 ms per frame at 300×5000).
- **Viewport-based lazy loading.** For arrays that do not fit
  comfortably in RAM, select and render only the visible window at
  screen resolution from the spool, re-selecting on zoom. Largest lift,
  out of scope for now.

## Progress

- 2026-07-02: Profiled the Waterfall render path offscreen and wrote this
  plan. Phase 1 implementation started on branch
  `worktree-waterfall-render-perf`.
- 2026-07-02: Completed phase 1. Added a `_strided_subsample` helper (target
  1M samples, exact below that) used by both `_compute_default_levels` and
  the data comparison in `_should_reset_view_for_new_patch`, and switched
  `_render_patch` to `setImage(..., autoLevels=False)` with an explicit
  fallback level pair for degenerate (e.g. all-NaN) data. `PatchViewer` was
  left unchanged: its `autoLevels=True` is the only source of levels there,
  and pyqtgraph computes it from a subsampled quick min/max already.
  Verified end-to-end with the real widget on a 3000×20000 (480 MB) patch,
  unmodified main vs this branch: first render 1233→174 ms, changed-data
  replacement 1291→179 ms, identical replacement 1163→48 ms; default levels
  match the full computation to ~0.1%. Tests: added
  `TestStridedSubsample`, `TestComputeDefaultLevels`, and
  `TestShouldResetViewForNewPatch`; `pytest -q tests/test_widgets/
  tests/test_integrations.py` (1171 passed, 46 skipped) and
  `prek run --all-files` clean.
- 2026-07-03: Completed the Wiggle phase-2 item on branch
  `wiggle-render-perf`. Profiling (offscreen, 300×5000 float64 patch)
  found ~95% of paint time in Qt line rasterization of width-2 pens;
  per-item overhead was negligible (~13 µs/item). Changes:
  - All bulk line pens width 2 → 1 (~16x paint speedup; the percentile
    median keeps its thick dotted style, only 7 lines).
  - Both modes render one `PlotDataItem` per trace from a reused item
    pool with `setDownsampling(auto=True, method="peak")` and
    `setClipToView(True)`; clipping is enabled only after the view range
    settles because clipped items report only the visible slice as
    their data bounds, which would corrupt auto-range. Config setters
    and pens are only touched when values actually change so re-renders
    pay one display-dataset recompute per item.
  - Offset mode's serpentine NaN-flattened single curve was removed;
    this also fixes spurious connector lines that were drawn along the
    plot edges between consecutive traces.
  - 2D time-series mode now caps rendered lines with the same auto
    stride as offset mode (≤300 rows); percentiles still aggregate all
    rows.
  Measured with the real widget offscreen: time-series first render
  4261→1047 ms and offset 2795→571 ms (300×5000); gain-slider tick
  929→168 ms; 2000×15000 time series 8964→1285 ms (was one Qt item and
  ~15 ms of paint per row, uncapped). Cursor readout and colorbar
  recolor stay ≤1 ms. Verified before/after screenshots match in all
  three modes (offset, series, percentiles) apart from line width.
  Remaining follow-up: viewport-based lazy loading (above).
- 2026-08-03: Replaced this document's manual before/after ritual with an
  automated suite. `benchmarks/qt/` now covers `_compute_default_levels`,
  `_should_reset_view_for_new_patch`, the Waterfall and Wiggle render paths,
  and the cursor-readout helpers; `benchmarks/core/` covers the Qt-free
  workflow and sampling hot paths. Run
  `python scripts/bench_compare.py --baseline main --suite qt` instead of
  hand-timing renders. See docs/dev/benchmarking.md.
