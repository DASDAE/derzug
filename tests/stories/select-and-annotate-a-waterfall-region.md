---
title: Select And Annotate A Waterfall Region
complexity: intermediate
implemented: false
---

# Select And Annotate A Waterfall Region

As a DFOS analyst, I want to select a region in a waterfall view and attach annotations to it so that I can preserve the location and meaning of an observed feature for later review.

## Workflow

1. Load a patch from `Spool` and open it in `Waterfall`.
2. Use the in-plot selection controls to draw a rectangular ROI around the feature of interest.
3. Confirm that the selected region matches the intended time and distance window.
4. Add one or more annotations to the selected area, such as a box, point, or trend line.
5. Enter descriptive metadata for each annotation, including a label, semantic type, notes, or tags.
6. Review the annotated patch to confirm the overlays line up with the observed signal.
7. Save or emit the annotation set so it can be reused in later interpretation or QA workflows.

## Expected Outcome

- The user can move from visual inspection to a persistent annotated interpretation without leaving the waterfall view.
- The selected region and its annotations remain tied to the same patch basis and coordinates.

## Test Datasets Needed

- A 2D patch with at least one visually distinct arrival, anomaly, or coherent feature worth marking.
- Stable time and distance coordinates so ROI bounds and annotation geometry can be asserted deterministically.
- A small synthetic patch with one obvious rectangular or linear feature for regression tests of ROI placement and annotation persistence.
