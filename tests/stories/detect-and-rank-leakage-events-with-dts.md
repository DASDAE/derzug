---
title: Detect And Rank Leakage Events With DTS
complexity: advanced
implemented: false
missing_features:
  - streaming or time-windowed DTS anomaly detection
  - thermal leak candidate scoring and ranking
  - event clustering across repeated detections
  - leak review views specialized for pipelines or pipe-in-pipe systems
---

# Detect And Rank Leakage Events With DTS

As an operations analyst, I want to detect localized thermal disturbances and rank them as likely leak events so that I can triage the most urgent DTS anomalies first.

## Workflow

1. Load DTS data acquired along a pipeline, pipe-in-pipe assembly, or other thermally monitored asset.
2. Build a baseline from normal operating periods and quantify expected spatial and temporal variability.
3. Run an anomaly detector that flags localized thermal departures from baseline.
4. Score each candidate by magnitude, duration, and spatial compactness.
5. Review the highest-ranked candidates in a thermal image and reject anomalies caused by known operational changes.
6. Export the accepted leak candidates as a ranked event list for field follow-up.

## Expected Outcome

- The analyst receives a ranked list of likely leakage events instead of a raw temperature movie.
- DTS anomalies are converted into reviewable operational alerts with supporting evidence.

## Test Datasets Needed

- A DTS monitoring dataset from a pipeline, pipe-in-pipe system, or representative thermal-flow test stand.
- Baseline operating periods covering expected non-leak temperature variability.
- One or more known leak or leak-like events with independently verified onset time and approximate location.
- Negative-control intervals containing operational transients that should not be classified as leaks.
- A synthetic DTS dataset with injected thermal leak signatures of varying magnitude and duration for threshold and ranking tests.

## References

- Kim, H., Lee, J., Kim, T., Park, S. J., Kim, H., and Jung, I. D. (2023). Advanced thermal fluid leakage detection system with machine learning algorithm for pipe-in-pipe structure. Case Studies in Thermal Engineering, 47, 102747. https://doi.org/10.1016/j.csite.2023.102747
