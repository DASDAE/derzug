---
title: Track Crack Initiation And Growth With DSS
complexity: advanced
implemented: false
missing_features:
  - native DSS or strain-profile visualization with engineering units
  - strain-spike or crack-candidate detection along the fiber
  - time-linked crack growth tracking across repeated acquisitions
  - reporting of crack position and evolution summaries
---

# Track Crack Initiation And Growth With DSS

As a structural monitoring analyst, I want to identify localized strain spikes and follow their evolution through time so that I can detect crack initiation and quantify crack growth from distributed strain sensing data.

## Workflow

1. Load a DSS spool containing repeated measurements from the same instrumented structure.
2. Visualize strain along the fiber in engineering units and inspect changes across acquisitions.
3. Establish a baseline period that represents the undamaged or pre-event state.
4. Run a crack-candidate detection step that flags localized strain peaks or abrupt spatial changes relative to baseline.
5. Review flagged locations in a time-linked view to determine whether they persist, widen, or migrate.
6. Export the accepted crack candidates with position, time, and growth metrics for downstream reporting.

## Expected Outcome

- The workflow highlights likely crack locations rather than forcing the analyst to inspect every profile manually.
- Repeated DSS acquisitions can be compared as a crack-growth history instead of isolated snapshots.

## Test Datasets Needed

- A DSS time series from a structure with repeated acquisitions over the same fiber layout.
- A baseline segment representing undamaged or nominal structural behavior.
- One or more intervals with known localized crack initiation or controlled crack growth.
- Ground-truth labels for crack position and time, or a laboratory benchmark with independently measured crack development.
- A small synthetic DSS dataset with injected localized strain spikes for deterministic testing of detection logic.

## References

- Zhang, X., Long, L., Broere, W., and Bao, X. (2025). Smart sensing of concrete crack using distributed fiber optics sensors: Current advances and perspectives. Case Studies in Construction Materials, 22, e04493. https://doi.org/10.1016/j.cscm.2025.e04493
- Lv, B., Peng, Y., Du, C., Tian, Y., and Wu, J. (2025). Review of Brillouin Distributed Sensing for Structural Monitoring in Transportation Infrastructure. Infrastructures, 10(6), 148. https://doi.org/10.3390/infrastructures10060148
