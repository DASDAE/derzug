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
- **Cursor readout via `searchsorted`.** `nearest_axis_index` allocates
  a full-axis temp per mouse move (two axes, up to 60 Hz);
  `searchsorted` + neighbor check is ~10× faster and allocation-free.
- **Wiggle widget rendering.** Time-series mode creates one
  `PlotCurveItem` per row; switch to a single NaN-separated flat curve
  (as offset mode already does) and consider `PlotDataItem` with
  `setDownsampling(auto=True, method="peak")` + `setClipToView(True)`
  so paint cost scales with pixels rather than samples.
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
