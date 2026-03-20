---
title: Compare Multiple Processing Branches
complexity: advanced
implemented: true
---

# Compare Multiple Processing Branches

As a DFOS analyst, I want to split one candidate patch into multiple processing branches and compare the outputs so that I can choose a defensible preprocessing path before exporting results.

## Workflow

1. Load a patch from `Spool` and inspect it in `Waterfall`.
2. Send the same patch into two or more parallel branches.
3. In one branch, apply a conservative sequence such as `Detrend` then `Filter`.
4. In another branch, use a more aggressive sequence such as `Normalize`, `Filter`, and `Rolling`.
5. View each branch output side by side in separate viewers.
6. Compare whether event timing, coherence, and amplitude patterns remain stable across branches.
7. Keep the branch that improves interpretability without distorting the features the analyst cares about.

## Expected Outcome

- The user can compare alternative processing chains from the same source patch.
- The chosen branch is based on visible tradeoffs rather than a single untested configuration.
