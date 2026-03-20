---
title: Crop An Event Window
complexity: basic
implemented: true
---

# Crop An Event Window

As a DFOS analyst, I want to crop a large patch down to the time and distance window that contains an event so that later processing is faster and easier to interpret.

## Workflow

1. Start with a patch that has been loaded from a spool.
2. View the patch in `Waterfall` to identify the approximate event time and channel range.
3. Pass the patch into `Selection`.
4. Set the time bounds to bracket the event with a small amount of context before and after.
5. Set the distance or channel bounds to focus on the affected section of fiber.
6. Emit the smaller patch and reopen it in `Waterfall` or `Wiggle` to confirm the crop captured the event.

## Expected Outcome

- The output patch is smaller than the original patch.
- The event remains visible while unrelated time and channel ranges are removed.
