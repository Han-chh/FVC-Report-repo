# TEMPORAL ASSIGNMENT VALIDATION

| Check | Status | Detail |
|---|---|---|
| Expected sensor × AOI × year checkpoints | PASS | 60/60 valid checkpoints |
| Duplicate source identities across nominal-date composites | PASS | duplicates=0 |
| Original temporal support and nominal labels | PASS | nearest nominal assignment; labels 20 July / 31 July / 10 August |
| No target-year leakage | PASS | all source assignment and pair groups are within their recorded year |
| Canonical output schema | PASS | FCOVER, NDVI, aoi_id, block_id, contribution_count, nominal_date, pixel_id, sensor, year |

See `../final/temporal_support_summary.csv` for original, assigned, rejected, per-nominal, composite, paired-identity, and retention counts.

OVERALL TEMPORAL VALIDATION: PASS
