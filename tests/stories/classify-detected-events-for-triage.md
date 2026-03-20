---
title: Classify Detected Events For Triage
complexity: advanced
implemented: false
missing_features:
  - labeled event set management
  - feature extraction or model inference widget
  - prediction table with class probabilities
  - confusion and error review for model quality control
---

# Classify Detected Events For Triage

As a DFOS analyst, I want to classify detected intervals into event types so that the workflow does not stop at detection and can support rapid triage.

## Workflow

1. Start with a set of candidate intervals produced by manual review or a detection workflow.
2. Extract the relevant patch windows and standardize them into a comparable representation.
3. Run a classifier that predicts event classes such as vehicle, footstep, machinery, rockfall, or noise.
4. Review predicted labels together with probabilities or confidence scores.
5. Spot-check false positives and ambiguous classes by opening the underlying patches in a viewer.
6. Accept or relabel reviewed events and keep the curated set for monitoring or reporting.

## Expected Outcome

- The analyst can move from event detection to structured triage in one workflow family.
- Classification outputs are reviewable and correctable rather than treated as final truth.

## References

- Tomasov, A., Zaviska, P., Dejdar, P. et al. (2025). Comprehensive Dataset for Event Classification Using Distributed Acoustic Sensing (DAS) Systems. Scientific Data, 12, 793. https://doi.org/10.1038/s41597-025-05088-4
- Kozmin, A., Kalashev, O., Chernenko, A., and Redyuk, A. (2025). Semi-Supervised Learned Autoencoder for Classification of Events in Distributed Fibre Acoustic Sensors. Sensors, 25(12), 3730. https://doi.org/10.3390/s25123730
