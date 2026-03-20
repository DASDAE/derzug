---
title: Run Near-Field Array Processing For Directionality
complexity: advanced
implemented: false
missing_features:
  - near-field beamforming or slowness analysis widget
  - channel geometry aware steering controls
  - directional energy display
  - interactive masking or focusing based on array-processing output
---

# Run Near-Field Array Processing For Directionality

As a DFOS analyst, I want to estimate propagation direction or focus energy toward candidate source regions so that coherent wavefields can be separated from clutter and interpreted more reliably.

## Workflow

1. Start with a patch that contains a coherent wavefield across many channels.
2. Import or confirm the fiber geometry needed for array-aware processing.
3. Run a near-field array-processing step that scans candidate directions, slowness values, or source regions.
4. Visualize the resulting energy concentration surface and identify the dominant coherent solution.
5. Use the preferred solution to focus the signal, suppress competing directions, or guide later localization.
6. Compare the focused output with the original patch to confirm that the coherent arrival becomes easier to interpret.

## Expected Outcome

- The user can reason about directionality or source-region focus directly from DFOS data.
- Array-aware processing becomes a first-class interpretive step rather than an external script.

## References

- Munoz, F., and Soto, M. A. (2022). Enhancing fibre-optic distributed acoustic sensing capabilities with blind near-field array signal processing. Nature Communications, 13, 4019. https://doi.org/10.1038/s41467-022-31681-x
