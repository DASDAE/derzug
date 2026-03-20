---
title: Auto-Pick Arrivals With Confidence Review
complexity: advanced
implemented: false
missing_features:
  - automatic arrival picking for DFOS patches
  - per-pick confidence scores
  - pick table with bulk accept reject editing
  - promotion of picks into persisted annotations
---

# Auto-Pick Arrivals With Confidence Review

As a DFOS analyst, I want DerZug to propose arrival picks across many channels and let me review the confidence of those picks so that I can move from raw waveforms to event timing faster.

## Workflow

1. Start with a patch that contains a candidate event.
2. Run an automatic picker that estimates first arrivals or other phase onsets across channels.
3. Display the picks on top of the patch view together with a confidence score for each channel.
4. Sort the picks by confidence and inspect low-confidence regions first.
5. Accept, correct, or reject individual picks and apply bulk edits to coherent groups of channels.
6. Save the reviewed picks as structured annotations for downstream processing.
7. Pass the reviewed pick set into a later localization or velocity-analysis workflow.

## Expected Outcome

- The analyst reviews a proposed pick field instead of drawing everything manually.
- The accepted pick set becomes a reusable artifact for later workflows.

## References

- Zhu, W., Biondi, E., Li, J. et al. (2023). Seismic arrival-time picking on distributed acoustic sensing data using semi-supervised learning. Nature Communications, 14, 8192. https://doi.org/10.1038/s41467-023-43355-3
