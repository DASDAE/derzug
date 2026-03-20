---
title: Load And Screen A Spool
complexity: basic
implemented: true
---

# Load And Screen A Spool

As a DFOS analyst, I want to load a spool from disk and quickly screen it for usable patches so that I can decide what to process next.

## Workflow

1. Open the `Spool` widget and point it at a directory or example spool.
2. Wait for the spool summary table to populate with one row per patch.
3. Sort or scan the rows by time range, dimensions, and shape.
4. Select a patch that looks relevant for the event or interval of interest.
5. Send the selected patch to a `Waterfall` view for a first visual check.
6. If the patch is empty, malformed, or obviously noisy, return to the spool table and choose another patch.

## Expected Outcome

- The user can move from a spool input to a specific patch without writing code.
- The first visualization step makes it clear whether the patch is worth further processing.
