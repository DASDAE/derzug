---
title: Build A Detection Candidate From A Long Spool
complexity: advanced
implemented: false
---

# Build A Detection Candidate From A Long Spool

As a DFOS analyst, I want to work from a long spool down to a short list of candidate intervals so that I can focus detailed review on the most suspicious parts of the acquisition.

## Workflow

1. Load a long spool containing many patches or a long acquisition window.
2. Step through the spool table and inspect patches in `Waterfall` to identify intervals with unusual energy or coherent arrivals.
3. For each promising interval, send the patch into `Selection` and crop to the suspicious time and distance range.
4. Pass the cropped patch through `Filter` or `Stft` to separate likely signal from stationary background behavior.
5. Use `Aggregate` or `Rolling` to create a reduced representation that makes unusual intervals easier to compare.
6. Repeat the same sequence for several candidates from the same spool.
7. Keep the reduced outputs as a shortlist for downstream event review or export.

## Expected Outcome

- A long DFOS acquisition is narrowed to a manageable set of candidate intervals.
- Each retained candidate has both a visual basis and a reduced product for comparison.
