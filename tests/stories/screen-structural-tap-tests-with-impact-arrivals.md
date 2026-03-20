---
title: Screen Structural Tap Tests With Impact Arrivals
complexity: intermediate
implemented: false
missing_features:
  - impact-event picker for repeated tap arrivals
  - batch comparison across many tap locations or repeated impacts
  - tabular summary of arrival time amplitude and dominant frequency per tap
---

# Screen Structural Tap Tests With Impact Arrivals

As a structural monitoring analyst, I want to load repeated tap-test measurements and compare the resulting impact responses so that I can quickly screen for changes in coupling, stiffness, or local damage.

## Workflow

1. Load a spool containing repeated tap or hammer-impact measurements from the same instrumented structure.
2. Inspect each patch in `Waterfall` or `Wiggle` to confirm that the impact arrival is visible.
3. Use `Selection` to crop a short time window around the impact and the relevant segment of the fiber.
4. Optionally pass the cropped patch through `Filter` to suppress low-frequency drift or unrelated background vibration.
5. Use `Stft` or `Aggregate` to compare dominant frequency content or summary amplitudes across taps.
6. Review whether one tap location or one repeat departs from the expected response pattern.

## Expected Outcome

- The analyst can compare repeated impact responses without manually rebuilding the same preprocessing chain.
- The workflow supports quick screening for unusual structural response before deeper modal or damage analysis.

## Test Datasets Needed

- A small set of repeated tap-test patches from the same beam, plate, bridge element, or laboratory specimen.
- At least one baseline tap sequence representing nominal structural response.
- One altered-condition sequence, such as loosened coupling, added damage, or changed boundary condition.
- Metadata identifying tap location or impact repeat number for side-by-side comparison.
- A synthetic impact dataset with clean onset times and simple ringing modes for deterministic regression testing.
