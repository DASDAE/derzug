---
title: Prepare A Clean Handoff Product
complexity: advanced
implemented: false
---

# Prepare A Clean Handoff Product

As a DFOS analyst, I want to turn a noisy raw patch into a compact, reviewable handoff product so that another analyst can understand the event without reconstructing my full workflow from scratch.

## Workflow

1. Start with a raw patch selected from `Spool`.
2. Use `Selection` to crop the event window to a focused spatial and temporal subset.
3. Apply `Detrend` and `Filter` to suppress drift and out-of-band noise.
4. Inspect the result in `Waterfall`, then run `Stft` if frequency-domain evidence is needed to justify the interpretation.
5. Generate a reduced companion product with `Rolling` or `Aggregate` so the main trend can be reviewed quickly.
6. Compare the raw patch, processed patch, and reduced output to confirm they tell a consistent story.
7. Keep the processed patch and reduced product as the deliverables for review, plotting, or export.

## Expected Outcome

- The user finishes with a compact set of outputs that preserve both evidence and interpretability.
- A second analyst can review the event without starting from the full raw spool.
