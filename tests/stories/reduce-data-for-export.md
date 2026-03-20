---
title: Reduce Data For Export
complexity: intermediate
implemented: true
---

# Reduce Data For Export

As a DFOS analyst, I want to reduce a processed patch to a simpler product for downstream review so that I can hand off a compact result instead of the full raw data volume.

## Workflow

1. Begin with a patch that has already been cropped and optionally filtered.
2. Use `Rolling` or `Aggregate` to compute a summary quantity over time or distance.
3. Review the reduced result in a viewer to make sure the main trend or event signature is still present.
4. If the reduction is too aggressive, adjust the window or aggregation settings and rerun.
5. Keep the reduced patch as the handoff product for later reporting, plotting, or export.

## Expected Outcome

- The final output is smaller or simpler than the source patch.
- The reduced product still captures the feature the user intends to communicate.
