# Additional Sensitivity Analyses

This directory contains three narrow extensions of the frozen FVC processing pipeline. They change one methodological dimension at a time and write only under `Data/Additional Sensitivity Analysis/`; they never modify frozen primary inputs, outputs, manuscripts, or the primary execution contract.

## Reused primary implementation

The extensions reuse `data_prep.temporal_composite.nanmedian_min_count` for the cell-wise median and two-contribution gate; `data_prep.processing` and the sensor-native QA implementations as the definition of the unchanged primary conditions; `data_prep.fcover` / `common.grid` for the FCOVER V2 RT6 grid and validity contract; `data_prep.build_pairs` for paired eligibility; and `models.ols`, `metrics.regression_metrics`, `metrics.block_metrics`, and `metrics.holm` through `additional_sensitivity_analysis.downstream` for the unchanged OLS, clipping, metrics, blocks, and Holm procedure. Existing historical-window, GroupKFold/LOYO, and rolling-origin orchestration remains the reference implementation in `execution.science`.

The installed implementation lives in `Code/src/additional_sensitivity_analysis/`. The subdirectories below are stable, user-facing script/configuration entry points. This avoids creating a competing analysis framework while keeping the three sensitivity branches explicit.

## A. Non-overlapping temporal composition

Primary condition: each ±15-day nominal window is composited independently, so a source scene can occur in more than one window.

Sensitivity condition: scenes inside the union of the original windows are assigned to their closest nominal date (20 July, 31 July, or 10 August). An exact tie is assigned to the earlier nominal date. The configured default is `nearest_nominal_nonoverlap`; `explicit_windows` is available only as a future configuration mode. MOD09Q1 retains the primary product-date convention: the study rule assigns the existing 8-day product identities and does not undo MOD09Q1's internal compositing.

`non_overlapping_temporal/build_non_overlapping_composites.py` applies the assignment and the frozen median reducer. `validate_temporal_windows.py` reports source counts, assignments, rejections, and duplicate source identity counts. A correct run has zero identities assigned to multiple nominal dates.

## B. Landsat SR_QA_AEROSOL

Primary condition: Landsat 8/9 Collection 2 Level-2 surface reflectance uses the frozen `QA_PIXEL` and `QA_RADSAT` masks without aerosol-specific screening. It is already atmospherically corrected; this is an additional QA sensitivity, not a claim that the primary data lack atmospheric correction.

The decoder follows USGS's [Collection 2 Quality Assessment Bands](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands), accessed 2026-08-30, for Landsat 8/9 C2 L2 LaSRC: bit 0 fill, bit 1 valid retrieval, bit 5 interpolated aerosol, and bits 6–7 aerosol level (climatology, low, medium, high). Modes and their exact permitted values are in `landsat_aerosol_qa/config.yaml`:

- `primary_no_aerosol_filter` adds no aerosol filter.
- `exclude_high_aerosol` rejects only high aerosol (plus fill, already excluded by primary QA).
- `valid_retrieval_no_high` requires a valid, non-interpolated retrieval and rejects high aerosol.
- `strict_aerosol` requires a valid, non-interpolated retrieval and retains only climatology/low aerosol.

The frozen local primary assets explicitly mark `SR_QA_AEROSOL` as not acquired, so the next phase must re-export the exact same C2 L2 scenes with `SR_B4`, `SR_B5`, `QA_PIXEL`, `QA_RADSAT`, and `SR_QA_AEROSOL`. The retrieval wrapper selects all five bands from a single GEE image, retains scene/date properties, and rejects mismatched scene IDs. Missing aerosol QA fails loudly under the default missing-data policy; it is never interpolated or invented.

## C. Aggregation order

Primary route A is native QA → scaled native reflectance → native NDVI → mask-aware mean NDVI on the FCOVER grid → temporal median → FCOVER pairing. Route B retains the exact same QA-valid native RED/NIR intersection, aggregates RED and NIR independently on the FCOVER grid, then calculates `(mean_NIR - mean_RED) / (mean_NIR + mean_RED)`. Zero aggregated denominators become NoData (`NaN`) according to the configured tolerance. Future comparison rows carry both routes, ΔNDVI, matched valid-pixel count, RED/NIR aggregates, and the standard identity fields. Exact area-weighted valid fractions are not claimed because the frozen pipeline does not retain that support diagnostic.

## Production state and outputs

All configs lock sensors, AOIs, years, nominal dates, FCOVER target grid, minimum contributions, and output roots. Production is complete for all three branches: Aggregation Order (Route A reproduction PASS and Route B 60/60), Non-overlapping Temporal (60/60), and Landsat Aerosol QA (80/80 across four valid modes). Canonical pair tables, checkpoint manifests, downstream OLS/Rolling-Origin/block outputs, and validation reports are written under `Data/Additional Sensitivity Analysis/`.

The final unified evidence package is under `Data/Additional Sensitivity Analysis/Combined/`:

- `MANUSCRIPT_INTEGRATION_READY.md`
- `sensitivity_validation_report.md`
- `SCIENTIFIC_RESULTS_REPORT.md`
- `sensitivity_summary.csv`
- `sensitivity_conclusion_matrix.csv`

## Commands

From the repository root, installation remains the existing reproduction environment (`python3 -m pip install -r Code/requirements-reproduction.txt`). Safe dry-runs, which do not access scenes or write output, are:

```bash
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/non_overlapping_temporal/run_temporal_sensitivity.py" --dry-run
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/landsat_aerosol_qa/run_aerosol_sensitivity.py" --dry-run --variant exclude_high_aerosol
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/aggregation_order/run_aggregation_order_sensitivity.py" --dry-run --route reflectance_first
PYTHONPATH=Code/src python3 -m pytest -q "Code/Additional Sensitivity Analysis/tests"
```

For production, `--run-core-evaluation` materializes only missing/invalid checkpoints and then evaluates canonical pairs. The temporal runner also accepts `--materialize-only --sensor sentinel2|landsat|modis` for safe independent resume; `--evaluate-only --run-core-evaluation` merges completed sensor products. The aerosol runner accepts `--materialize-only --variant <mode>` for independently resumable modes. Every checkpoint is written through a temporary file and atomically renamed only after the group completes.

After temporal and aerosol materialization, generate validation and matched-support comparisons with:

```bash
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/finalize_sensitivity_results.py" temporal
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/finalize_sensitivity_results.py" aerosol-preflight
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/finalize_sensitivity_results.py" aerosol
PYTHONPATH=Code/src python3 "Code/Additional Sensitivity Analysis/finalize_sensitivity_results.py" combined
```

## Validation and limitations

Automated tests cover temporal assignment/ties/union rejection, official aerosol bit decoding and missing-QA behavior, matched aggregation support and zero denominators, and the downstream pair schema. Full production validation checks source identity uniqueness, original temporal support, fixed labels, no later-year leakage, exact-scene aerosol provenance, and output compatibility. Matched-support comparison is mandatory wherever filtering or temporal composition changes target identities; unpaired RMSE differences are reported as operational comparisons, not standalone accuracy improvements.
