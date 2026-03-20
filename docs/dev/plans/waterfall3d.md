# Waterfall3D Plan

## Summary

Add a 3D patch visualization path built around familiar 2D waterfall slices rather
than a fully freeform OpenGL volume viewer.

The plan has two parts:

1. A standalone `Waterfall3D` widget for inspecting 3D `dc.Patch` objects.
2. A shared internal 3D slice-preview component reused by `PatchViewer` when the
   selected node contains a 3D array.

This deliberately avoids a first version based on pyqtgraph's 3D OpenGL scene
graph. The useful interaction for DAS-style 3D arrays is selecting a slice along
one axis and viewing a normal 2D waterfall, not orbiting a translucent volume.

## Why This Shape

- Reuses the existing `Waterfall` mental model instead of introducing a totally
  different 3D interaction pattern.
- Keeps the first version readable and testable.
- Avoids tying the primary workflow to pyqtgraph's older OpenGL 3D stack.
- Gives `PatchViewer` a clear upgrade path for `ndim == 3` arrays without
  changing its role as an inspector.

## Proposed Widget

### Standalone Widget

Class: `Waterfall3D`

- Input: `Patch`
- Output: `Patch` unchanged in v1
- Category: `Visualize`
- Error if `patch.data.ndim != 3`

### Core UI

- Main plot area:
  - a single large 2D waterfall image for the currently selected slice
- Controls:
  - slice-axis selector
  - slice position slider
  - slice index spin box
  - optional coordinate readout for current slice
  - colormap selector
- Optional small context panel:
  - summary of full patch dims and shape
  - current displayed 2D dims

### Interaction Model

- Choose one dimension as the slice axis
- The remaining two dimensions become the plotted waterfall axes
- Moving the slider changes which 2D slice is shown
- Slice selection is index-based internally
- Coordinate values for the current slice are displayed as read-only metadata

### Default Axis Policy

For a 3D patch with dims `(d0, d1, d2)`:

- default slice axis: `d0`
- displayed waterfall axes: `(d1, d2)`

Preferred override:

- if `time` exists, keep `time` as one of the displayed axes whenever possible
- if `distance` exists, prefer `distance` as the other displayed axis

Examples:

- `(shot, distance, time)` -> default slice axis `shot`, display `distance x time`
- `(distance, time, frequency)` -> default slice axis `frequency`, display `distance x time`

The final implementation should encode this as a small helper instead of
hard-coding it inline in the widget constructor.

## Shared Internal Component

Create a reusable internal viewer component rather than embedding all slice logic
directly inside `Waterfall3D`.

Suggested shape:

- private module-level helper or small widget class under `derzug.widgets`
- responsibilities:
  - validate a 3D array / patch
  - manage slice-axis selection
  - derive the current 2D slice
  - render the slice using the same pyqtgraph image conventions as `Waterfall`
  - expose current preview state for tests

The standalone `Waterfall3D` widget uses this component directly.

`PatchViewer` uses the same component for preview-only mode when:

- selected node is an array
- `values.ndim == 3`

For `PatchViewer`, the component should be embedded without introducing outputs
or selection side effects.

## PatchViewer Integration

Current behavior:

- 1D arrays -> line preview
- 2D arrays -> image preview
- 3D+ arrays -> text summary only

Target behavior:

- 3D arrays -> embedded `Waterfall3D`-style slice preview
- 4D+ arrays -> remain text summary only in v1

The `PatchViewer` preview stack should gain one additional page for 3D array
inspection. The selected node continues to drive the preview panel, but the 3D
page owns its own slice controls.

## Waterfall Reuse

Do not subclass `Waterfall` directly in v1.

Instead:

- extract small shared helpers if needed:
  - colormap application
  - axis coercion
  - image item setup
- keep ROI / selection logic out of `Waterfall3D` initially

Reason:

- `Waterfall` is currently a 2D interactive selection widget
- `Waterfall3D` is initially a 3D inspection widget
- mixing ROI semantics into slice navigation too early will make the first
  version harder to understand

## Deferred Features

Do not include these in v1:

- full 3D OpenGL volume rendering
- 3D camera orbit / mesh / isosurface view
- ROI selection propagated across slices
- outputting the current 2D slice as a second signal
- 4D slicing
- synchronized tri-planar orthogonal views

These may be worthwhile later, but they should not block the first useful widget.

## File-Level Plan

Create:

- `src/derzug/widgets/waterfall3d.py`
- `tests/test_widgets/test_waterfall3d.py`

Modify:

- `src/derzug/widgets/patchviewer.py`
- `pyproject.toml`

Optional later:

- dedicated `icons/Waterfall3D.svg`

## Testing Plan

### Waterfall3D tests

- widget instantiates with empty state
- `None` patch emits `None`
- 2D patch shows a user-facing error and emits the patch unchanged or `None`
  depending on final widget convention; match the chosen implementation
- 3D patch loads successfully
- default slice axis and displayed dims are chosen as expected
- changing slice axis updates the available slice range
- moving the slice slider updates the displayed 2D slice
- colormap changes apply without errors

### PatchViewer tests

- selecting a 3D array switches preview mode to the 3D slice viewer
- changing the slice control updates the displayed slice state
- switching from a 3D node back to a 1D or 2D node restores the expected preview mode
- 4D arrays still fall back to summary mode

### Regression tests

- existing 2D `Waterfall` tests continue to pass unchanged
- existing `PatchViewer` tests for 1D and 2D previews continue to pass

## Implementation Notes

- Prefer index-based slicing even when coordinate values are displayed.
- Represent slice state explicitly:
  - current slice axis
  - current slice index
  - available slice count
- Keep the mapping from 3D patch -> current 2D slice in a single helper method.
- Make the current 2D slice derivation testable without needing to inspect
  pyqtgraph items directly.
- If no good 3D example patch exists in DASCore fixtures, create a small synthetic
  3D patch in the tests rather than blocking implementation.

## Open Choices to Revisit Later

- Whether `Waterfall3D` should eventually output the currently displayed 2D slice
- Whether ROI selection across slices is worth adding
- Whether a tri-planar viewer would be more useful than a single-slice waterfall
- Whether pyqtgraph OpenGL views should be used as a secondary overview only
