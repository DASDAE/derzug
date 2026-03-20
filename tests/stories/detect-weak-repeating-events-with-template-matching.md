---
title: Detect Weak Repeating Events With Template Matching
complexity: advanced
implemented: false
missing_features:
  - template selection from an existing patch or annotation
  - sliding correlation search over long spools
  - detection threshold tuning and candidate ranking
  - detection review table linked to patch previews
---

# Detect Weak Repeating Events With Template Matching

As a DFOS analyst, I want to pick a known event as a template and scan a long spool for similar weak events so that I can recover repeating events that are hard to see by eye.

## Workflow

1. Load a long spool that contains continuous monitoring data.
2. Select one high-confidence event patch to serve as the template.
3. Restrict the template to the most diagnostic time and distance window.
4. Run a template-matching search across the spool with tunable correlation and spacing thresholds.
5. Review the ranked detections in a table that links each candidate back to a patch preview.
6. Reject false positives and keep detections that show repeatable moveout and timing patterns.
7. Export the accepted detections as a candidate event list for downstream review or localization.

## Expected Outcome

- The user can recover low-SNR repeating events from a long spool.
- Detection review is interactive rather than a blind batch result.

## References

- Li, Z., and Zhan, Z. (2018). Pushing the limit of earthquake detection with distributed acoustic sensing and template matching: a case study at the Brady geothermal field. Geophysical Journal International, 215(3), 1583-1593. https://doi.org/10.1093/gji/ggy359
