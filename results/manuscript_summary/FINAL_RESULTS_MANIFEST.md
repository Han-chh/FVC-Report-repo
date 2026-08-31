# Final Results Manifest

`FINAL_RESULTS_MANIFEST.csv` contains 1,094 source-linked numeric and comparison-state records. The canonical primary data are `repo/Data/Additional Sensitivity Analysis/Canonical Primary Nonoverlap 20260830`; only the final non-overlap-baseline aggregation and repaired aerosol summaries are active sensitivity sources.

## Headline primary values

- Pairs: 681,545.
- Mean Multi-AOI RMSE: Sentinel-2 0.045182; Landsat 0.037984; MODIS 0.034141.
- Formal runs: 72 Multi-AOI + 72 Rolling-Origin = 144 OLS; 48 DPM configurations.
- Block contrasts: 72 intended; 36 Holm-supported (28 longer-history lower-error; 8 higher-error).

## Active sensitivities

- Aggregation order: identity retention = 1.0; mean absolute Delta NDVI 0.000114-0.006829; operational Delta RMSE -0.000890-0.000683; one preferred-history and two unit-level RO changes.
- Aerosol QA: 60 AOI-year-mode support records; 2 zero-support groups; mean AOI-year retention 0.413-0.966; 12/12 operational and 12/12 matched comparisons estimable; operational Delta RMSE -0.000030-0.030590; 9/12 preferred-history changes; 21/24 RO comparisons comparable, with 14 direction changes and 3 NOT_COMPARABLE.

## Rounding policy

Counts are integers. Headline RMSE and Delta RMSE values use six decimals; compact table values retain their source-defined precision. A repeated metric is derived from the same full-precision source value and must use the same rule.
