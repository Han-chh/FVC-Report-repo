# Additional Sensitivity Analysis — Implementation Audit

## Scope and status

This is a code-only implementation audit. No production scene processing, AOI-wide experiment, OLS/rolling-origin production evaluation, sensitivity result table, manuscript edit, or frozen-primary-output overwrite was performed.

## New files

- `Code/src/additional_sensitivity_analysis/`: installed shared implementation (`config`, `io_utils`, `schemas`, `validation`, `temporal`, `aerosol`, `aggregation`, and `downstream`).
- `Code/Additional Sensitivity Analysis/common/`: compatibility imports for the shared implementation.
- `Code/Additional Sensitivity Analysis/non_overlapping_temporal/`: config, composite/validation imports, and dry-run runner.
- `Code/Additional Sensitivity Analysis/landsat_aerosol_qa/`: config, same-scene retrieval selector, decoder/validation imports, and dry-run runner.
- `Code/Additional Sensitivity Analysis/aggregation_order/`: config, both aggregation imports, validation import, and dry-run runner.
- `Code/Additional Sensitivity Analysis/tests/`: temporal, aerosol-bit, aggregation-order, and downstream-schema tests.
- `Data/Additional Sensitivity Analysis/{Non-overlapping Temporal,Landsat Aerosol QA,Aggregation Order}/{intermediate,final,manifests,logs}/.gitkeep`: empty, isolated future-output structure only.
- `Code/Additional Sensitivity Analysis/README.md` and this audit.

## Modified existing files

- `README.md`: added the required concise sensitivity-analysis section.
- `Code/pyproject.toml`: registered the added test directory with pytest.

## Reused primary functions

- `data_prep.temporal_composite.nanmedian_min_count` preserves the cell-wise temporal median and minimum two finite contributions.
- Native QA/scaling references remain `data_prep.sentinel2`, `data_prep.landsat`, `data_prep.modis`, and `data_prep.processing`.
- FCOVER target/support and pair eligibility remain `data_prep.fcover`, `common.grid`, and `data_prep.build_pairs`.
- The sensitivity downstream adapter imports the existing `models.ols.fit_ols`, `models.ols.predict_clipped`, `metrics.regression_metrics.regression_metrics`, and `metrics.block_metrics.by_block`; historical-window, GroupKFold/LOYO, rolling-origin, contrast, and Holm semantics remain those in `execution.science` / `metrics.holm`.

## Implemented pipelines

1. **Temporal non-overlap**: closest nominal assignment within the original ±15-day union; deterministic earlier-date ties; duplicate source identities assigned to different nominal dates fail; explicit windows are a future configurable mode; MOD09Q1 product-date identities are retained.
2. **Landsat aerosol QA**: official C2 L2 bit decoder, parameterized primary/high-exclusion/valid-direct/strict modes, missing-QA failure, exact-scene join validation, source-band selector, and future observation/summary schema constants.
3. **Aggregation order**: matched native valid RED/NIR intersection, primary NDVI-first and reflectance-first routes, denominator NoData behavior, comparison output fields, and primary OLS/metric adapter.

## QA definition verification and source requirement

The aerosol decoder was verified against USGS, [Landsat Collection 2 Quality Assessment Bands](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands), accessed 2026-08-30: bit 0 fill; bit 1 valid aerosol retrieval; bit 5 interpolated aerosol; bits 6–7 aerosol level (0 climatology, 1 low, 2 medium, 3 high), for Landsat 8/9 Collection 2 Level-2 surface reflectance.

`Code/configs/sensors.yaml` records the frozen primary `SR_QA_AEROSOL` status as `not_acquired_not_used`. Therefore the next phase requires a new export of `SR_QA_AEROSOL` from the same frozen Landsat 8/9 C2 L2 scene identities, alongside `SR_B4`, `SR_B5`, `QA_PIXEL`, and `QA_RADSAT`. It must not substitute a different product.

## Verification performed

- `py_compile` over all new Python files: passed.
- `PYTHONPATH=Code/src python -m pytest -q "Code/Additional Sensitivity Analysis/tests"`: **9 passed**.
- All three runner `--dry-run` commands: passed and reported `DRY_RUN_ONLY`.
- `git diff --check`: passed.

Only a temporary isolated Python environment was created to obtain the existing runtime dependencies (`numpy`, `pandas`, `PyYAML`) plus the test runner (`pytest`); no repository dependency file was changed and no production data were generated.

## Reserved next-phase commands

```bash
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/non_overlapping_temporal/run_temporal_sensitivity.py" --dry-run --run-core-evaluation
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/landsat_aerosol_qa/run_aerosol_sensitivity.py" --dry-run --variant exclude_high_aerosol --run-core-evaluation
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/aggregation_order/run_aggregation_order_sensitivity.py" --dry-run --route reflectance_first --run-core-evaluation
```

The current runners intentionally reject non-dry-run production invocation in this implementation phase. A separately authorized next phase must first materialize the specified source inputs in the isolated output roots and then enable the core evaluation call; this guard prevents accidental production execution now.

## Final readiness

- Temporal sensitivity code: **READY** — source-manifest/materialization access is required for execution.
- Aerosol sensitivity code: **READY** — a same-scene `SR_QA_AEROSOL` re-export is required before execution.
- Aggregation-order code: **READY** — matched native RED/NIR materialization is required before execution.

No unresolved code issue prevents the next phase. The operational prerequisite is the Landsat same-product aerosol-band re-export; this is intentionally not performed here.
