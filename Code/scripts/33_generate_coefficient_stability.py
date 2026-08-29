#!/usr/bin/env python3
"""Recover coefficient diagnostics from the frozen Multi-AOI design.

This script does not add formal target-evaluation runs. It reads the frozen
paired observations and the registered six-window design, reconstructs the
existing development/reserve partition and five GroupKFold splits, verifies
the recovered fold metrics against the stored scientific output, and records
the OLS coefficients fitted inside those existing folds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import GroupKFold


HERE = Path(__file__).resolve()
CODE = HERE.parents[1]
WORKSPACE = HERE.parents[4]
sys.path.insert(0, str(CODE / "src"))

from execution.science import _complete_history_blocks, _roles  # noqa: E402
from metrics.regression_metrics import regression_metrics  # noqa: E402
from models.ols import fit_ols, predict_clipped  # noqa: E402


CONFIG = CODE / "configs" / "scientific_execution.yaml"
SCIENCE = WORKSPACE / "report/publication/new_experiments/08_scientific_execution"
OUTPUT = CODE / "outputs"
PAIRS = SCIENCE / "raw_machine_outputs/paired_observations.csv.gz"
FULL_COEFFICIENTS = SCIENCE / "02_multi_aoi_results/MULTI_AOI_MODEL_COEFFICIENTS.csv"
STORED_FOLDS = SCIENCE / "02_multi_aoi_results/MULTI_AOI_GROUPKFOLD.csv"
MULTI_RESULTS = SCIENCE / "04_master_tables/multi_aoi_run_results.csv"
ROLLING_RESULTS = SCIENCE / "04_master_tables/rolling_origin_run_results.csv"
CONTRASTS = SCIENCE / "03_rolling_origin_results/ROLLING_ORIGIN_PAIRED_TESTS.csv"


def _iqr(values: pd.Series) -> float:
    return float(values.quantile(0.75) - values.quantile(0.25))


def recover_coefficients() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    contract = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pairs = pd.read_csv(PAIRS)
    full = pd.read_csv(FULL_COEFFICIENTS)
    stored = pd.read_csv(STORED_FOLDS)
    window_years = {
        row["id"]: [int(year) for year in row["train_years"]]
        for row in contract["multi_aoi_historical_windows"]
    }

    tidy_rows: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    verification_failures: list[str] = []

    for row in full.itertuples(index=False):
        years = window_years[row.window]
        sensor_rows = pairs[(pairs.aoi_id == row.AOI) & (pairs.sensor == row.sensor)]
        historical = _complete_history_blocks(
            sensor_rows[sensor_rows.year.isin(years)], years
        )
        historical = _roles(historical, contract)

        full_model = fit_ols(historical.NDVI, historical.FCOVER)
        recovered_slope = float(full_model.coef_[0])
        recovered_intercept = float(full_model.intercept_)
        if not np.isclose(recovered_slope, row.slope, rtol=0.0, atol=1e-12):
            verification_failures.append(f"full slope:{row.execution_id}")
        if not np.isclose(recovered_intercept, row.intercept, rtol=0.0, atol=1e-12):
            verification_failures.append(f"full intercept:{row.execution_id}")
        if len(historical) != int(row.train_n):
            verification_failures.append(f"full n:{row.execution_id}")

        tidy_rows.append(
            {
                "sensor": row.sensor,
                "aoi": row.AOI,
                "window": row.window,
                "slope": float(row.slope),
                "intercept": float(row.intercept),
                "n": int(row.train_n),
                "model_id": row.execution_id,
                "train_years": row.train_years,
                "target_year": int(row.target_year),
                "train_block_n": int(row.train_block_n),
                "processing_hash": row.processing_hash,
                "source_manifest_hash": row.source_manifest_hash,
                "aoi_geometry_hash": row.AOI_geometry_hash,
                "block_manifest_hash": row.block_manifest_hash,
                "code_version": row.code_version,
            }
        )

        development = historical[historical.spatial_role == "development"]
        expected = stored[
            (stored.execution_id == row.execution_id)
            & (stored.sensor == row.sensor)
            & (stored.AOI == row.AOI)
            & (stored.window == row.window)
        ].set_index("fold")
        splitter = GroupKFold(n_splits=5)
        for fold, (train_index, test_index) in enumerate(
            splitter.split(development, groups=development.block_id), 1
        ):
            train = development.iloc[train_index]
            test = development.iloc[test_index]
            model = fit_ols(train.NDVI, train.FCOVER)
            metrics = regression_metrics(
                test.FCOVER, predict_clipped(model, test.NDVI)
            )
            stored_row = expected.loc[fold]
            for metric in ("RMSE", "MAE", "Bias", "R2"):
                if not np.isclose(
                    float(metrics[metric]), float(stored_row[metric]),
                    rtol=0.0, atol=1e-12,
                ):
                    verification_failures.append(
                        f"fold {metric}:{row.execution_id}:{fold}"
                    )
            recovered_r = metrics["Pearson_r"]
            stored_r = stored_row["Pearson_r"]
            if not (
                (pd.isna(recovered_r) and pd.isna(stored_r))
                or np.isclose(float(recovered_r), float(stored_r), rtol=0.0, atol=1e-12)
            ):
                verification_failures.append(
                    f"fold Pearson_r:{row.execution_id}:{fold}"
                )
            fold_rows.append(
                {
                    "sensor": row.sensor,
                    "aoi": row.AOI,
                    "window": row.window,
                    "fold": fold,
                    "slope": float(model.coef_[0]),
                    "intercept": float(model.intercept_),
                    "train_n": len(train),
                    "test_n": len(test),
                    "train_blocks": int(train.block_id.nunique()),
                    "test_blocks": int(test.block_id.nunique()),
                    "model_id": row.execution_id,
                    "train_years": row.train_years,
                    "processing_hash": row.processing_hash,
                    "block_manifest_hash": row.block_manifest_hash,
                    "verified_rmse": float(metrics["RMSE"]),
                }
            )

    tidy = pd.DataFrame(tidy_rows).sort_values(["sensor", "aoi", "window"])
    folds = pd.DataFrame(fold_rows).sort_values(["sensor", "aoi", "window", "fold"])
    return tidy, folds, verification_failures


def summarize(tidy: pd.DataFrame, folds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fold_summary = (
        folds.groupby(["sensor", "aoi", "window"], sort=True)
        .agg(
            fold_n=("fold", "count"),
            slope_fold_min=("slope", "min"),
            slope_fold_max=("slope", "max"),
            slope_fold_median=("slope", "median"),
            slope_fold_iqr=("slope", _iqr),
            slope_fold_sd=("slope", "std"),
            intercept_fold_min=("intercept", "min"),
            intercept_fold_max=("intercept", "max"),
            intercept_fold_median=("intercept", "median"),
            intercept_fold_iqr=("intercept", _iqr),
            intercept_fold_sd=("intercept", "std"),
        )
        .reset_index()
    )
    fold_summary = tidy[
        ["sensor", "aoi", "window", "slope", "intercept", "n", "model_id"]
    ].rename(columns={"slope": "full_slope", "intercept": "full_intercept"}).merge(
        fold_summary, on=["sensor", "aoi", "window"], validate="one_to_one"
    )

    range_rows: list[dict[str, object]] = []
    for (sensor, aoi), group in tidy.groupby(["sensor", "aoi"], sort=True):
        slope_min = group.loc[group.slope.idxmin()]
        slope_max = group.loc[group.slope.idxmax()]
        intercept_min = group.loc[group.intercept.idxmin()]
        intercept_max = group.loc[group.intercept.idxmax()]
        range_rows.append(
            {
                "sensor": sensor,
                "aoi": aoi,
                "slope_min": float(slope_min.slope),
                "slope_min_window": slope_min.window,
                "slope_max": float(slope_max.slope),
                "slope_max_window": slope_max.window,
                "slope_range": float(slope_max.slope - slope_min.slope),
                "intercept_min": float(intercept_min.intercept),
                "intercept_min_window": intercept_min.window,
                "intercept_max": float(intercept_max.intercept),
                "intercept_max_window": intercept_max.window,
                "intercept_range": float(intercept_max.intercept - intercept_min.intercept),
            }
        )
    return fold_summary, pd.DataFrame(range_rows)


def numerical_integrity(verification_failures: list[str]) -> dict[str, object]:
    multi = pd.read_csv(MULTI_RESULTS)
    rolling = pd.read_csv(ROLLING_RESULTS)
    tests = pd.read_csv(CONTRASTS)
    significant = tests[tests.significant.astype(bool)]
    monotonic = 0
    for _, group in rolling.groupby(["sensor", "AOI", "target_year"]):
        values = group.sort_values("history_length").RMSE.to_numpy()
        monotonic += int(np.all(values[1:] <= values[:-1] + 1e-15))
    families = tests.groupby(["sensor", "AOI", "target_year"]).size()
    means = multi.groupby("sensor").RMSE.mean().to_dict()
    actual = {
        "formal_runs_total": int(len(multi) + len(rolling)),
        "multi_aoi_runs": int(len(multi)),
        "rolling_origin_runs": int(len(rolling)),
        "sensor_mean_rmse_multi_aoi": means,
        "rolling_sequences": int(rolling.groupby(["sensor", "AOI", "target_year"]).ngroups),
        "monotonic_or_non_degrading": int(monotonic),
        "non_monotonic": int(24 - monotonic),
        "block_contrasts": int(len(tests)),
        "multiplicity_families": int(len(families)),
        "contrasts_per_family_unique": sorted(int(value) for value in families.unique()),
        "within_family_holm_adjusted_significant": int(len(significant)),
        "longer_history_better_significant": int((significant.mean_difference_RMSE > 0).sum()),
        "longer_history_worse_significant": int((significant.mean_difference_RMSE < 0).sum()),
        "aoi01_significant_abs_delta_lt_1e-4": int(
            ((significant.AOI == "AOI-01") & (significant.mean_difference_RMSE.abs() < 1e-4)).sum()
        ),
        "largest_significant_improvement": float(significant.mean_difference_RMSE.max()),
        "largest_significant_degradation": float(significant.mean_difference_RMSE.min()),
        "coefficient_recovery_failures": verification_failures,
    }
    expected_means = {"sentinel2": 0.041023, "landsat": 0.036840, "modis": 0.030787}
    checks = {
        "formal_runs_total": actual["formal_runs_total"] == 144,
        "multi_aoi_runs": actual["multi_aoi_runs"] == 72,
        "rolling_origin_runs": actual["rolling_origin_runs"] == 72,
        "sensor_mean_rmse_multi_aoi": all(
            abs(means[sensor] - expected) < 5e-7
            for sensor, expected in expected_means.items()
        ),
        "rolling_sequences": actual["rolling_sequences"] == 24,
        "trajectory_split": monotonic == 12,
        "block_contrasts": actual["block_contrasts"] == 72,
        "multiplicity_families": actual["multiplicity_families"] == 24,
        "contrasts_per_family": actual["contrasts_per_family_unique"] == [3],
        "within_family_holm_adjusted_significant": len(significant) == 40,
        "effect_directions": int((significant.mean_difference_RMSE > 0).sum()) == 32
        and int((significant.mean_difference_RMSE < 0).sum()) == 8,
        "aoi01_tiny_effects": actual["aoi01_significant_abs_delta_lt_1e-4"] == 11,
        "coefficient_recovery": not verification_failures,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "actual": actual}


def write_readme() -> None:
    text = """# Coefficient-stability diagnostics

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
"""
    (OUTPUT / "README_COEFFICIENT_DIAGNOSTICS.md").write_text(text, encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    tidy, folds, failures = recover_coefficients()
    fold_summary, window_ranges = summarize(tidy, folds)
    integrity = numerical_integrity(failures)

    tidy.to_csv(OUTPUT / "coefficient_stability.csv", index=False)
    folds.to_csv(OUTPUT / "groupkfold_coefficient_diagnostics.csv", index=False)
    fold_summary.to_csv(OUTPUT / "coefficient_fold_dispersion.csv", index=False)
    window_ranges.to_csv(OUTPUT / "coefficient_window_ranges.csv", index=False)
    (OUTPUT / "numerical_integrity_check.json").write_text(
        json.dumps(integrity, indent=2) + "\n", encoding="utf-8"
    )
    write_readme()
    print(json.dumps({
        "status": integrity["status"],
        "full_fit_records": len(tidy),
        "fold_fit_records": len(folds),
        "fold_summary_records": len(fold_summary),
        "window_range_records": len(window_ranges),
        "coefficient_recovery_failures": len(failures),
        "output": str(OUTPUT),
    }, indent=2))
    return 0 if integrity["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
