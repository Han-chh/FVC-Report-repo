# Coefficient-stability diagnostics

## Purpose

These outputs add descriptive coefficient diagnostics to the existing 72-run
Multi-AOI experiment. They do not add or alter formal target-evaluation runs.

## Inputs

- `08_scientific_execution/raw_machine_outputs/paired_observations.csv.gz`
- `08_scientific_execution/02_multi_aoi_results/MULTI_AOI_MODEL_COEFFICIENTS.csv`
- `08_scientific_execution/02_multi_aoi_results/MULTI_AOI_GROUPKFOLD.csv`
- `report/publication/code/configs/scientific_execution.yaml`

The script reuses the frozen complete-block rule, seed-42 SHA-256 spatial-role
assignment, development-only five-fold GroupKFold splits, training samples,
preprocessing, and intercept-inclusive OLS implementation. Recovered fold
predictions are checked against every stored GroupKFold metric before the fold
coefficients are accepted.

## Outputs

- `coefficient_stability.csv`: 72 verified full-fit coefficient records.
- `groupkfold_coefficient_diagnostics.csv`: 360 recovered fold-fit records.
- `coefficient_fold_dispersion.csv`: fold min/max/median/IQR/SD by fit.
- `coefficient_window_ranges.csv`: slope/intercept drift across six windows.
- `numerical_integrity_check.json`: formal-result and recovery gate.

## Command

From the repository root:

```bash
model/.venv/bin/python report/publication/code/scripts/33_generate_coefficient_stability.py
```
