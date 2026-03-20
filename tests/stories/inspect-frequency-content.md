---
title: Inspect Frequency Content
complexity: intermediate
implemented: true
---

# Inspect Frequency Content

As a DFOS analyst, I want to inspect the frequency content of a suspicious interval so that I can tell whether it looks like an impulsive event, persistent machinery, or another source type.

## Workflow

1. Start with a cropped patch that contains the interval of interest.
2. If needed, use `Selection` again to isolate an even shorter time window around the signal.
3. Send the patch into `Stft`.
4. Adjust the window length and overlap until the time-frequency image is stable enough to interpret.
5. Review the output in `Waterfall` or the relevant patch viewer to identify narrow-band or broadband behavior.
6. If a strong narrow-band component dominates the patch, return to `Filter` and suppress it before continuing.

## Expected Outcome

- The user can distinguish broad transient energy from steady tonal noise.
- The spectral view informs the next preprocessing choice.
