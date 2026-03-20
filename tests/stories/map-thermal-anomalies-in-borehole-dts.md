---
title: Map Thermal Anomalies In Borehole DTS
complexity: advanced
implemented: false
missing_features:
  - native DTS profile handling and temperature-specific units
  - depth-time heatmap views for borehole monitoring
  - baseline trend removal for geothermal or hydrogeologic interpretation
  - anomaly picking for inflow zones fractures or anthropogenic heating
---

# Map Thermal Anomalies In Borehole DTS

As a geothermal or hydrogeology analyst, I want to map temperature anomalies along a borehole through time so that I can identify inflow zones, thermal disturbances, or geothermal targets from DTS data.

## Workflow

1. Load a DTS spool containing one or more borehole temperature profiles through time.
2. Display the data as depth-versus-temperature profiles and as a depth-time thermal image.
3. Establish a baseline geothermal trend or a reference logging interval.
4. Remove the broad background trend to emphasize localized thermal anomalies.
5. Flag intervals that indicate groundwater inflow, fractured zones, or anthropogenic heat influence.
6. Export the interpreted anomaly intervals with depth, magnitude, and persistence.

## Expected Outcome

- The user can move from raw DTS profiles to interpretable thermal anomaly zones.
- Borehole DTS becomes useful for screening and comparison across many intervals, not just single-profile inspection.

## Test Datasets Needed

- A borehole DTS dataset with repeated temperature profiles over depth and time.
- A reference interval capturing the normal geothermal gradient or steady-state condition.
- One or more known anomaly intervals associated with inflow zones, fractures, or imposed thermal disturbances.
- Depth registration metadata so anomaly picks can be compared across acquisitions.
- A compact synthetic DTS depth-time dataset with injected localized warm and cool anomalies for deterministic UI and detection tests.

## References

- Kłonowski, M. R., Nermoen, A., Thomas, P. J., Wyrwalska, U., Pratkowiecka, W., Ładocha, A., Midttømme, K., Brytan, P., Krzonkalla, A., Maćko, A., Zawistowski, K., and Duczmańska-Kłonowska, J. (2024). Borehole Optical Fibre Distributed Temperature Sensing vs. Manual Temperature Logging for Geothermal Condition Assessment: Results of the OptiSGE Project. Sensors, 24(23), 7419. https://doi.org/10.3390/s24237419
- Iten, M., Bühler, M., Fischli, F., Bethmann, F., and El-Alfy, A. (2024). Distributed fiber-optic temperature monitoring in boreholes of a seasonal geothermal energy storage. Procedia Structural Integrity, 64, 1642-1648. https://doi.org/10.1016/j.prostr.2024.09.420
