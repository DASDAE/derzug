# Waterfall Datetime Axis Issue

## Summary

There is a severe bug in Waterfall's absolute datetime display.

Observed behavior from user report:

- a patch starts around `11:50`
- the Waterfall x-axis shows around `13:50`

This is too large to be explained by nearest-sample snapping alone.

## What Was Done

- Traced Waterfall cursor and axis datetime handling in:
  - `src/derzug/widgets/waterfall.py`
  - `src/derzug/utils/plot_axes.py`
  - `src/derzug/utils/display.py`
- Added a regression test in `tests/test_widgets/test_waterfall.py` that captures the fixed-hour axis shift.
- Tried one fix in `ensure_axis_item(...)` that forced `utcOffset=0` on datetime axes.
- Rolled that fix back immediately after user reported it broke the time axis.

## Current Code State

Only the regression test remains modified.

No runtime code changes are left in place.

## Regression Test

Test added:

- `TestWaterfall.test_datetime_axis_tick_matches_patch_datetime`

What it does:

- builds a patch whose first `time` sample is exactly `2024-07-15T11:50:00`
- renders it in Waterfall
- forces a deterministic summer `UTC+2` axis offset on the date axis
- asserts the first axis tick should still read `11:50`

Current failure:

```text
assert '13:50' == '11:50'
```

This reproduces the user-reported two-hour shift without relying on hover interpolation.

## What Did Not Work

Attempted fix:

- set `ContextDateAxisItem(..., utcOffset=0)` in `src/derzug/utils/plot_axes.py`
- also reset `current.utcOffset = 0` for already-installed datetime axes

Result:

- focused tests passed
- user reported the time axis was broken in real use
- change was reverted

## Likely Next Step

Do not guess another fix from the synthetic test alone.

Next investigation should use the real workflow/data path that triggered the bug:

- `/media/derrick/Backup Plus/ineris/garpenberg/debug_dt_issue.ows`

The goal should be to inspect:

- the actual patch `time` coordinate values entering Waterfall
- whether those values are meant to be local wall-clock times or absolute UTC instants
- where the two-hour shift first appears:
  - patch coordinates
  - plot-axis conversion
  - pyqtgraph date tick formatting
  - workflow/data-loading normalization before Waterfall

## Suggested Resume Point

1. Load the real workflow or extract the patch feeding Waterfall.
2. Print the first few raw `time` coordinate values from the incoming patch.
3. Compare those raw values to:
   - `waterfall_widget._axes.x_coord[:N]`
   - `waterfall_widget._axes.x_plot[:N]`
   - `bottom_axis.tickStrings(...)`
4. Determine whether the shift is introduced before Waterfall or only during axis formatting.
