---
title: Filter And Compare Noise
complexity: intermediate
implemented: true
---

# Filter And Compare Noise

As a DFOS analyst, I want to apply a simple preprocessing chain to a noisy patch and compare the result against the original so that I can judge whether filtering improves event visibility.

## Workflow

1. Load a patch that contains both signal and background noise.
2. Send the patch into `Detrend` to remove large offsets or drift.
3. Pass the detrended patch into `Filter` and choose a frequency range that matches the target signal.
4. Optionally send the filtered patch into `Normalize` to make relative amplitudes easier to compare across channels.
5. View the original and processed patches in separate `Waterfall` windows.
6. Compare whether the processed patch reveals a more coherent arrival or suppresses unwanted noise.

## Expected Outcome

- The processed patch preserves the event while reducing noise or baseline drift.
- The user can visually compare raw and processed data before deciding to continue.
