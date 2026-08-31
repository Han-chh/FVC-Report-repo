#!/usr/bin/env python3
"""Recompute and verify the numerical results reported in the manuscript.

This intentionally uses the committed derived paired-observation table, rather
than contacting Earth Engine. It verifies the exact local numerical path of the
four-AOI OLS and DPM analyses and writes no files.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


ROOT = Path(__file__).resolve().parents[1]
PAIRS = ROOT / "data" / "canonical" / "paired_observations.csv.gz"
CONFIG = ROOT / "code" / "configs" / "scientific_execution.yaml"
RESULTS = ROOT / "results" / "primary"
SENSORS = ("sentinel2", "landsat", "modis")
AOIS = ("AOI-00", "AOI-01", "AOI-02", "AOI-03")
DPM_PAIRS = (("P1/P99", 1, 99), ("P2/P98", 2, 98), ("P5/P95", 5, 95), ("P10/P90", 10, 90))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metrics(reference: pd.Series, prediction: np.ndarray) -> dict[str, float | int]:
    reference_array = np.asarray(reference, dtype=float)
    prediction_array = np.asarray(prediction, dtype=float)
    return {
        "RMSE": float(np.sqrt(mean_squared_error(reference_array, prediction_array))),
        "MAE": float(mean_absolute_error(reference_array, prediction_array)),
        "Bias": float(np.mean(prediction_array - reference_array)),
        "R2": float(r2_score(reference_array, prediction_array)),
        "Pearson_r": float(np.corrcoef(reference_array, prediction_array)[0, 1]),
        "n": int(len(reference_array)),
    }


def complete_blocks(rows: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    observed = [set(rows.loc[rows.year == year, "block_id"]) for year in years]
    common = set.intersection(*observed) if observed else set()
    if not common:
        raise RuntimeError("NO_COMPLETE_HISTORICAL_BLOCKS")
    return rows[rows.block_id.isin(common)].copy()


def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> tuple[LinearRegression, np.ndarray]:
    model = LinearRegression(fit_intercept=True).fit(train[["NDVI"]], train.FCOVER)
    return model, np.clip(model.predict(test[["NDVI"]]), 0.0, 1.0)


def assert_table(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str], fields: list[str], label: str) -> None:
    actual = actual.loc[:, [*keys, *fields]].sort_values(keys).reset_index(drop=True)
    expected = expected.loc[:, [*keys, *fields]].sort_values(keys).reset_index(drop=True)
    if len(actual) != len(expected) or not actual.loc[:, keys].equals(expected.loc[:, keys]):
        raise AssertionError(f"{label}: result keys or row count differ")
    for field in fields:
        left = actual[field].to_numpy()
        right = expected[field].to_numpy()
        if np.issubdtype(left.dtype, np.number) and np.issubdtype(right.dtype, np.number):
            if not np.allclose(left, right, rtol=0.0, atol=1e-10, equal_nan=True):
                maximum = float(np.nanmax(np.abs(left.astype(float) - right.astype(float))))
                raise AssertionError(f"{label}: {field} differs (maximum absolute error {maximum:.3e})")
        elif not np.array_equal(left, right):
            raise AssertionError(f"{label}: {field} differs")
    print(f"PASS  {label}: {len(actual)} rows")


def reproduce_multi_aoi(pairs: pd.DataFrame, contract: dict) -> pd.DataFrame:
    rows: list[dict] = []
    for aoi in AOIS:
        for sensor in SENSORS:
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["multi_aoi_historical_windows"]:
                years = [int(year) for year in window["train_years"]]
                train = complete_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
                target = sensor_rows[sensor_rows.year == 2025]
                model, prediction = fit_predict(train, target)
                rows.append({
                    "AOI": aoi, "sensor": sensor, "window": window["id"],
                    "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
                    "block_n": int(target.block_id.nunique()), **metrics(target.FCOVER, prediction),
                })
    return pd.DataFrame(rows)


def reproduce_rolling_origin(pairs: pd.DataFrame, contract: dict) -> pd.DataFrame:
    rows: list[dict] = []
    for aoi in AOIS:
        for sensor in SENSORS:
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["rolling_origin"]["primary"]:
                years = [int(year) for year in window["history_years"]]
                target_year = int(window["target_year"])
                train = complete_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
                target = sensor_rows[sensor_rows.year == target_year]
                model, prediction = fit_predict(train, target)
                rows.append({
                    "AOI": aoi, "sensor": sensor, "rolling_id": window["id"],
                    "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
                    "target_n": int(len(target)), "target_block_n": int(target.block_id.nunique()),
                    **metrics(target.FCOVER, prediction),
                })
    return pd.DataFrame(rows)


def reproduce_dpm(pairs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for aoi in AOIS:
        for sensor in SENSORS:
            subset = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor) & (pairs.year == 2025)]
            ndvi = subset.NDVI.to_numpy(dtype=float)
            for name, low_percentile, high_percentile in DPM_PAIRS:
                low, high = np.percentile(ndvi, [low_percentile, high_percentile])
                raw = (ndvi - low) / (high - low)
                prediction = np.clip(raw, 0.0, 1.0)
                rows.append({
                    "AOI": aoi, "sensor": sensor, "quantile_configuration": name,
                    "NDVI_low": float(low), "NDVI_high": float(high),
                    "target_evaluation_pairs": int(len(subset)),
                    "unique_target_identities": int(subset.pixel_id.nunique()),
                    "low_clip_count": int((raw < 0).sum()), "high_clip_count": int((raw > 1).sum()),
                    "low_clip_ratio": float((raw < 0).mean()), "high_clip_ratio": float((raw > 1).mean()),
                    **metrics(subset.FCOVER, prediction),
                })
    return pd.DataFrame(rows)


def main() -> None:
    expected_hash = "ca7237ba51a164c1f3247fa423dbbd10e0be2954aa19c6f31fb9262d703e7381"
    observed_hash = sha256(PAIRS)
    if observed_hash != expected_hash:
        raise AssertionError(f"paired-observation checksum differs: {observed_hash}")
    print("PASS  frozen paired-observation checksum")
    contract = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pairs = pd.read_csv(PAIRS)

    multi = reproduce_multi_aoi(pairs, contract)
    expected_multi = pd.read_csv(RESULTS / "multi_aoi" / "multi_aoi_metrics.csv")
    assert_table(multi, expected_multi, ["AOI", "sensor", "window"],
                 ["slope", "intercept", "block_n", "n", "RMSE", "MAE", "Bias", "R2", "Pearson_r"], "Multi-AOI OLS")

    rolling = reproduce_rolling_origin(pairs, contract)
    expected_rolling = pd.read_csv(RESULTS / "rolling_origin" / "rolling_origin_metrics.csv")
    assert_table(rolling, expected_rolling, ["AOI", "sensor", "rolling_id"],
                 ["slope", "intercept", "target_n", "target_block_n", "n", "RMSE", "MAE", "Bias", "R2", "Pearson_r"], "Rolling-Origin OLS")

    dpm = reproduce_dpm(pairs)
    expected_dpm = pd.read_csv(RESULTS / "dpm" / "dpm_endpoint_sensitivity.csv").rename(columns={
        "RMSE_DPM": "RMSE", "MAE_DPM": "MAE", "Bias_DPM": "Bias", "R2_DPM": "R2",
        "Pearson_r_DPM": "Pearson_r", "n_DPM": "n",
    })
    assert_table(dpm, expected_dpm, ["AOI", "sensor", "quantile_configuration"],
                 ["NDVI_low", "NDVI_high", "target_evaluation_pairs", "unique_target_identities", "low_clip_count", "high_clip_count", "low_clip_ratio", "high_clip_ratio", "n", "RMSE", "MAE", "Bias", "R2", "Pearson_r"], "All-AOI DPM")
    print("PASS  all manuscript numerical result checks")


if __name__ == "__main__":
    main()
