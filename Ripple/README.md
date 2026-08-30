# Ripple: DPM endpoint and AOI-01 sensitivity analysis

## Objective

This add-on analysis quantifies 2025 DPM endpoint sensitivity across four AOIs and three sensors, then assesses AOI-01 naïve baselines and prediction clipping. It leaves the frozen primary OLS experiment unchanged.

## Inputs and provenance

- Frozen paired observations: `Data/Inputs/paired_observations.csv.gz` (SHA-256 `cb439b63d5d346abdc8d2b8bf0e1a2204045c784e73ab8225e67c4fa47cbccfb`).
- Existing, reused DPM matrix: `Data/DPM_stage2/dpm_all_aoi_candidate_results.csv` (SHA-256 `9fcd3ca07d041db575ef265a6472dd051db3b9a9bc8e02d0e46b7f9d1c8bc95c`).
- Existing OLS matrix: `Data/Results/04_master_tables/multi_aoi_run_results.csv` (SHA-256 `d09e6738d38cc2a3a5e84ed4c4619eb65e82d0e5c3484b0fe8fb27f3e8488565`).
- Source commit: `624c68227c829f83f242dce0eafb9ca56a5162f0`.
- Final experiment commit: this commit (identify it from the Git history containing `Ripple/`).

The existing 48 DPM configurations were reproduced and reused. This analysis newly derives raw prediction, clipping, endpoint-sensitivity, and AOI-01 baseline diagnostics without modifying any frozen source output.

## Environment

Python 3.13.9, NumPy 2.5.2, pandas 3.0.5, scikit-learn 1.9.0, and Matplotlib 3.11.1. No random sampling is used.

## Reproduction

From the repository root:

```bash
python3 -m venv Ripple/.venv
Ripple/.venv/bin/python -m pip install -r Ripple/requirements.txt
Ripple/.venv/bin/python Ripple/scripts/run_sensitivity_analysis.py
```

Expected outputs are the CSV files in `Ripple/results/`, audit and validation reports, publication tables in `Ripple/tables/`, and `Ripple/figures/dpm_endpoint_sensitivity.pdf` and `.png`.
