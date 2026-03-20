---
title: Localize A Source From Reviewed Picks
complexity: advanced
implemented: false
missing_features:
  - import of fiber geometry and acquisition layout
  - source localization or inversion widget
  - uncertainty estimates for location solutions
  - map or geometry view for source review
---

# Localize A Source From Reviewed Picks

As a DFOS analyst, I want to convert reviewed channel picks into an estimated source location so that a visible event becomes a spatially actionable result.

## Workflow

1. Load a reviewed set of channel picks associated with a candidate event.
2. Import the relevant fiber geometry and any velocity or propagation assumptions needed by the solver.
3. Run a localization step that estimates the most likely source position and timing.
4. Inspect the fit quality and uncertainty to identify whether the result is stable enough to trust.
5. Compare the predicted arrivals against the observed picks and revisit outliers if needed.
6. Save the preferred location solution together with the supporting pick set and assumptions.

## Expected Outcome

- The workflow produces a source estimate with enough context to review and compare.
- The location result is linked back to the picks and assumptions that generated it.

## References

- Zhu, W., Biondi, E., Li, J. et al. (2023). Seismic arrival-time picking on distributed acoustic sensing data using semi-supervised learning. Nature Communications, 14, 8192. https://doi.org/10.1038/s41467-023-43355-3
