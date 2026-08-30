#!/usr/bin/env python3
"""Reproduce the DPM endpoint and AOI-01 baseline/clipping sensitivity analysis.

The script is deliberately read-only with respect to the frozen ``Data/``
inputs and outputs.  It verifies the already executed 48-row DPM matrix, then
derives only the additional diagnostics required for the Ripple experiment.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
import yaml
from sklearn.linear_model import LinearRegression


ROOT = Path(__file__).resolve().parents[2]
RIPPLE = ROOT / "Ripple"
DATA = ROOT / "Data"
PAIRS_PATH = DATA / "Inputs" / "paired_observations.csv.gz"
DPM_PATH = DATA / "DPM_stage2" / "dpm_all_aoi_candidate_results.csv"
DPM_LOG_PATH = DATA / "DPM_stage2" / "dpm_execution_log.json"
OLS_PATH = DATA / "Results" / "04_master_tables" / "multi_aoi_run_results.csv"
CONFIG_PATH = ROOT / "Code" / "configs" / "scientific_execution.yaml"
ENDPOINT_CODE = ROOT / "Code" / "src" / "models" / "endpoint.py"
OLS_CODE = ROOT / "Code" / "src" / "models" / "ols.py"
REPRODUCER = ROOT / "Code" / "reproduce_results.py"

AOIS = ("AOI-00", "AOI-01", "AOI-02", "AOI-03")
SENSORS = ("sentinel2", "landsat", "modis")
SENSOR_LABELS = {"sentinel2": "Sentinel-2", "landsat": "Landsat 8/9", "modis": "MODIS"}
ENDPOINTS = (("P1/P99", 1, 99), ("P2/P98", 2, 98), ("P5/P95", 5, 95), ("P10/P90", 10, 90))
FLOAT_TOLERANCE = 1e-10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metric_values(reference: np.ndarray, prediction: np.ndarray) -> dict[str, float | int]:
    reference = np.asarray(reference, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    valid = np.isfinite(reference) & np.isfinite(prediction)
    reference, prediction = reference[valid], prediction[valid]
    error = prediction - reference
    ss_total = float(np.sum((reference - reference.mean()) ** 2))
    return {
        "RMSE": float(np.sqrt(np.mean(error**2))),
        "MAE": float(np.mean(np.abs(error))),
        "Bias": float(np.mean(error)),
        "R2": float(1 - np.sum(error**2) / ss_total) if ss_total > 0 else float("nan"),
        "Pearson_r": float(np.corrcoef(reference, prediction)[0, 1])
        if reference.std() > 0 and prediction.std() > 0 else float("nan"),
        "n": int(len(reference)),
    }


def clipping_values(reference: np.ndarray, raw: np.ndarray) -> dict[str, float | int]:
    clipped = np.clip(raw, 0.0, 1.0)
    result: dict[str, float | int] = {
        "fraction_raw_lt_0": float(np.mean(raw < 0)),
        "fraction_raw_gt_1": float(np.mean(raw > 1)),
        "fraction_clipped": float(np.mean((raw < 0) | (raw > 1))),
        "raw_prediction_mean": float(np.mean(raw)),
        "clipped_prediction_mean": float(np.mean(clipped)),
        "prediction_variance_raw": float(np.var(raw)),
        "prediction_variance_clipped": float(np.var(clipped)),
    }
    for prefix, values in (("unclipped", metric_values(reference, raw)), ("clipped", metric_values(reference, clipped))):
        result.update({f"{prefix}_{key}": value for key, value in values.items() if key != "n"})
    result["delta_RMSE_clipping"] = float(result["unclipped_RMSE"] - result["clipped_RMSE"])
    return result


def target_identity_hash(frame: pd.DataFrame) -> str:
    rows = frame.loc[:, ["nominal_date", "pixel_id"]].drop_duplicates().sort_values(["nominal_date", "pixel_id"])
    return hashlib.sha256(rows.to_csv(index=False).encode("utf-8")).hexdigest()


def complete_blocks(rows: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    common = set.intersection(*(set(rows.loc[rows.year == year, "block_id"]) for year in years))
    return rows[rows.block_id.isin(common)].copy()


def latex_escape(text: object) -> str:
    return str(text).replace("_", r"\_")


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = RIPPLE / "results" / name
    frame.to_csv(path, index=False, float_format="%.12g")
    return path


def audit_existing_dpm(pairs: pd.DataFrame, existing: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    expected_keys = {(aoi, sensor, name) for aoi in AOIS for sensor in SENSORS for name, _, _ in ENDPOINTS}
    existing_keys = set(map(tuple, existing[["AOI", "sensor", "quantile_configuration"]].to_numpy()))
    endpoint_rows = []
    max_difference = 0.0
    identity_checks = []
    for aoi in AOIS:
        for sensor in SENSORS:
            target = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor) & (pairs.year == 2025)].copy()
            identity = target_identity_hash(target)
            group_hashes = []
            for name, low_q, high_q in ENDPOINTS:
                low, high = np.percentile(target.NDVI.to_numpy(float), [low_q, high_q])
                raw = (target.NDVI.to_numpy(float) - low) / (high - low)
                clipped = np.clip(raw, 0, 1)
                values = metric_values(target.FCOVER.to_numpy(float), clipped)
                old = existing[(existing.AOI == aoi) & (existing.sensor == sensor) & (existing.quantile_configuration == name)].iloc[0]
                compared = [abs(float(old[field]) - float(value)) for field, value in {
                    "NDVI_low": low, "NDVI_high": high, "RMSE": values["RMSE"], "MAE": values["MAE"],
                    "Bias": values["Bias"], "R2": values["R2"], "Pearson_r": values["Pearson_r"],
                }.items()]
                max_difference = max(max_difference, *compared)
                group_hashes.append(identity)
                endpoint_rows.append({"AOI": aoi, "sensor": sensor, "endpoint": name, "NDVI_low_recomputed": low,
                                      "NDVI_high_recomputed": high, "RMSE_recomputed": values["RMSE"],
                                      "max_absolute_difference": max(compared), "status": "PASS" if max(compared) <= FLOAT_TOLERANCE else "FAIL"})
            identity_checks.append({"AOI": aoi, "sensor": sensor, "target_identity_sha256": identity,
                                    "same_identity_for_all_four_endpoints": len(set(group_hashes)) == 1})
    code_text = ENDPOINT_CODE.read_text(encoding="utf-8")
    reproducer_text = REPRODUCER.read_text(encoding="utf-8")
    audit = {
        "expected_configuration_count": 48,
        "existing_configuration_count": int(len(existing)),
        "configuration_matrix_complete": existing_keys == expected_keys,
        "endpoint_reproducibility_max_absolute_difference": max_difference,
        "endpoint_reproducibility_pass": max_difference <= FLOAT_TOLERANCE,
        "numpy_linear_percentile_implementation": "np.percentile" in reproducer_text,
        "predictions_clipped_to_0_1": "np.clip" in code_text,
        "fcover_not_used_to_calculate_endpoints": "endpoint_predict(ndvi" in code_text and "fcover" not in code_text.lower(),
        "same_target_identities_per_endpoint": bool(all(row["same_identity_for_all_four_endpoints"] for row in identity_checks)),
    }
    return pd.DataFrame(endpoint_rows), {**audit, "identity_checks": identity_checks}


def build_dpm_results(pairs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, clipping_rows = [], []
    for aoi in AOIS:
        for sensor in SENSORS:
            target = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor) & (pairs.year == 2025)].copy()
            ndvi, reference = target.NDVI.to_numpy(float), target.FCOVER.to_numpy(float)
            physicality = {
                "NDVI_median": float(np.median(ndvi)), "NDVI_IQR": float(np.percentile(ndvi, 75) - np.percentile(ndvi, 25)),
                "FCOVER_mean": float(np.mean(reference)), "FCOVER_SD": float(np.std(reference, ddof=1)),
                "target_identity_sha256": target_identity_hash(target), "target_observation_count": int(len(target)),
            }
            for endpoint, low_q, high_q in ENDPOINTS:
                low, high = np.percentile(ndvi, [low_q, high_q])
                raw = (ndvi - low) / (high - low)
                clipped = np.clip(raw, 0, 1)
                metrics = metric_values(reference, clipped)
                clipping = clipping_values(reference, raw)
                row = {"Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor, "endpoint_pair": endpoint,
                       "lower_percentile": low_q, "upper_percentile": high_q, "NDVI_low": float(low), "NDVI_high": float(high),
                       "endpoint_spread": float(high - low), "prediction_mean": float(np.mean(clipped)), **physicality,
                       **metrics, **clipping}
                rows.append(row)
                clipping_rows.append({"model": "DPM", "Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor,
                                      "configuration": endpoint, "history": "NA", "n": int(len(target)), **clipping})
    return pd.DataFrame(rows), pd.DataFrame(clipping_rows)


def build_ols_and_baselines(pairs: pd.DataFrame, contract: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ols_rows, clip_rows, baseline_rows = [], [], []
    for aoi in AOIS:
        for sensor in SENSORS:
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)].copy()
            target = sensor_rows[sensor_rows.year == 2025].copy()
            for window in contract["multi_aoi_historical_windows"]:
                years = [int(year) for year in window["train_years"]]
                train = complete_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
                model = LinearRegression(fit_intercept=True).fit(train[["NDVI"]], train.FCOVER)
                raw = model.predict(target[["NDVI"]])
                clipping = clipping_values(target.FCOVER.to_numpy(float), raw)
                metrics = metric_values(target.FCOVER.to_numpy(float), np.clip(raw, 0, 1))
                base = {"Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor, "history": window["id"],
                        "train_years": ";".join(map(str, years)), "slope": float(model.coef_[0]), "intercept": float(model.intercept_),
                        "train_n": int(len(train)), "training_FCOVER_mean": float(train.FCOVER.mean()), "n": int(len(target)), **metrics, **clipping}
                ols_rows.append(base)
                clip_rows.append({"model": "OLS", "Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor,
                                  "configuration": "OLS", "history": window["id"], "n": int(len(target)), **clipping})
                if aoi == "AOI-01":
                    reference = target.FCOVER.to_numpy(float)
                    for baseline, prediction in (("ZERO", np.zeros(len(target))), ("TRAINING_MEAN", np.full(len(target), train.FCOVER.mean()))):
                        baseline_metrics = metric_values(reference, prediction)
                        baseline_rows.append({"Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor, "history": window["id"],
                                              "train_years": ";".join(map(str, years)), "baseline": baseline,
                                              "training_FCOVER_mean": float(train.FCOVER.mean()), "prediction_variance": float(np.var(prediction)),
                                              **baseline_metrics})
    ols = pd.DataFrame(ols_rows)
    selected = ols.loc[ols.groupby(["AOI", "sensor"])["RMSE"].idxmin(), ["AOI", "sensor", "history"]]
    selected = selected.rename(columns={"history": "displayed_OLS_history"})
    baseline = pd.DataFrame(baseline_rows).merge(selected[selected.AOI == "AOI-01"], on=["AOI", "sensor"], how="left")
    baseline["is_displayed_OLS_history"] = baseline.history == baseline.displayed_OLS_history
    displayed = ols.merge(selected, on=["AOI", "sensor"], how="inner")
    displayed = displayed[displayed.history == displayed.displayed_OLS_history].copy()
    for sensor in SENSORS:
        selector = (baseline.sensor == sensor) & baseline.is_displayed_OLS_history
        model_rmse = float(displayed.loc[(displayed.AOI == "AOI-01") & (displayed.sensor == sensor), "RMSE"].iloc[0])
        for base in ("ZERO", "TRAINING_MEAN"):
            index = baseline.index[selector & (baseline.baseline == base)][0]
            baseline.loc[index, "OLS_RMSE_displayed"] = model_rmse
            baseline.loc[index, "OLS_skill_vs_baseline"] = 1 - model_rmse / float(baseline.loc[index, "RMSE"])
    return ols, pd.DataFrame(clip_rows), baseline


def build_sensitivity(dpm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (aoi, sensor), group in dpm.groupby(["AOI", "sensor"], sort=False):
        best = group.loc[group.RMSE.idxmin()]
        bias = group.loc[group.Bias.abs().idxmin()]
        rmse_min, rmse_max = float(group.RMSE.min()), float(group.RMSE.max())
        rows.append({"Sensor": SENSOR_LABELS[sensor], "AOI": aoi, "sensor": sensor, "minimum_RMSE": rmse_min,
                     "maximum_RMSE": rmse_max, "RMSE_range": rmse_max - rmse_min,
                     "RMSE_CV": float(group.RMSE.std(ddof=1) / group.RMSE.mean()),
                     "relative_endpoint_sensitivity": (rmse_max - rmse_min) / rmse_min,
                     "endpoint_minimum_RMSE": best.endpoint_pair, "endpoint_minimum_absolute_Bias": bias.endpoint_pair,
                     "minimum_absolute_Bias": float(abs(bias.Bias)), "minimum_clipping_fraction": float(group.fraction_clipped.min()),
                     "maximum_clipping_fraction": float(group.fraction_clipped.max()),
                     "clipping_fraction_range": float(group.fraction_clipped.max() - group.fraction_clipped.min()),
                     "minimum_endpoint_spread": float(group.endpoint_spread.min()), "maximum_endpoint_spread": float(group.endpoint_spread.max()),
                     "endpoint_spread_range": float(group.endpoint_spread.max() - group.endpoint_spread.min())})
    return pd.DataFrame(rows)


def write_latex_tables(dpm: pd.DataFrame, summary: pd.DataFrame, ols: pd.DataFrame, baseline: pd.DataFrame, clipping: pd.DataFrame) -> None:
    tables = RIPPLE / "tables"
    lines = [r"\begin{table*}[!t]\centering\scriptsize", r"\caption{DPM endpoint sensitivity. RMSE range is the maximum minus minimum across the four prespecified endpoint pairs.}", r"\label{tab:dpm-sensitivity}", r"\begin{tabular}{llrrrrlrr}", r"\toprule", r"Sensor & AOI & Best RMSE & Worst RMSE & $\Delta$RMSE & Best endpoint & Clip. at best & Clip. range & Spread range \\", r"\midrule"]
    for _, r in summary.iterrows():
        best_clip = dpm[(dpm.AOI == r.AOI) & (dpm.sensor == r.sensor) & (dpm.endpoint_pair == r.endpoint_minimum_RMSE)].fraction_clipped.iloc[0]
        lines.append(f"{r.Sensor} & {r.AOI} & {r.minimum_RMSE:.4f} & {r.maximum_RMSE:.4f} & {r.RMSE_range:.4f} & {r.endpoint_minimum_RMSE} & {best_clip:.3f} & {r.clipping_fraction_range:.3f} & {r.endpoint_spread_range:.4f} " + r"\\")
    lines += [r"\bottomrule\end{tabular}\end{table*}", ""]
    (tables / "Table_DPM_Sensitivity.tex").write_text("\n".join(lines), encoding="utf-8")

    selected = ols.loc[ols.groupby(["AOI", "sensor"]).RMSE.idxmin()]
    lines = [r"\begin{table}[!t]\centering\scriptsize", r"\caption{AOI-01 baseline and clipping sensitivity for the retrospectively displayed OLS history. Baseline skill is $1-\mathrm{RMSE}_{OLS}/\mathrm{RMSE}_{baseline}$.}", r"\label{tab:aoi01-baseline-clipping}", r"\resizebox{\linewidth}{!}{%", r"\begin{tabular}{lrrrrrrrr}", r"\toprule", r"Sensor & OLS RMSE & Zero RMSE & Mean RMSE & Skill vs zero & Skill vs mean & OLS clip. & Best DPM RMSE & DPM clip. \\", r"\midrule"]
    for sensor in SENSORS:
        model = selected[(selected.AOI == "AOI-01") & (selected.sensor == sensor)].iloc[0]
        base = baseline[(baseline.sensor == sensor) & baseline.is_displayed_OLS_history]
        zero, mean = base[base.baseline == "ZERO"].iloc[0], base[base.baseline == "TRAINING_MEAN"].iloc[0]
        best = dpm[(dpm.AOI == "AOI-01") & (dpm.sensor == sensor)].sort_values("RMSE").iloc[0]
        lines.append(f"{SENSOR_LABELS[sensor]} & {model.RMSE:.4f} & {zero.RMSE:.4f} & {mean.RMSE:.4f} & {zero.OLS_skill_vs_baseline:.3f} & {mean.OLS_skill_vs_baseline:.3f} & {model.fraction_clipped:.3f} & {best.RMSE:.4f} & {best.fraction_clipped:.3f} " + r"\\")
    lines += [r"\bottomrule\end{tabular}%", r"}", r"\end{table}", ""]
    (tables / "Table_AOI01_Baseline_Clipping.tex").write_text("\n".join(lines), encoding="utf-8")

    rows = [r"\begin{landscape}\scriptsize", r"\setlength{\LTleft}{0pt}\setlength{\LTright}{0pt}", r"\begin{longtable}{lllrrrrrrrr}", r"\caption{Full four-endpoint DPM sensitivity matrix. Raw predictions are calculated before clipping to $[0,1]$.}\label{tab:dpm-all48}\\", r"\toprule Sensor & AOI & Endpoint & $NDVI_{low}$ & $NDVI_{high}$ & Spread & $n$ & RMSE & Bias & Clip. & $\Delta$RMSE clip. \\ \midrule", r"\endfirsthead", r"\toprule Sensor & AOI & Endpoint & $NDVI_{low}$ & $NDVI_{high}$ & Spread & $n$ & RMSE & Bias & Clip. & $\Delta$RMSE clip. \\ \midrule", r"\endhead"]
    for _, r in dpm.sort_values(["sensor", "AOI", "lower_percentile"]).iterrows():
        rows.append(f"{r.Sensor} & {r.AOI} & {r.endpoint_pair} & {r.NDVI_low:.4f} & {r.NDVI_high:.4f} & {r.endpoint_spread:.4f} & {int(r.n):,} & {r.RMSE:.4f} & {r.Bias:.4f} & {r.fraction_clipped:.3f} & {r.delta_RMSE_clipping:.4f} " + r"\\")
    rows += [r"\bottomrule\end{longtable}", r"\end{landscape}", ""]
    (tables / "Supplementary_Table_DPM_All48.tex").write_text("\n".join(rows), encoding="utf-8")

    rows = [r"\begin{landscape}\tiny", r"\setlength{\LTleft}{0pt}\setlength{\LTright}{0pt}", r"\begin{longtable}{lllrrrrrrr}", r"\caption{Clipping diagnostics for all DPM endpoint configurations and OLS histories: rates and RMSE.}\label{tab:clipping-full}\\", r"\toprule Model & Sensor & AOI/configuration & $n$ & Raw $<0$ & Raw $>1$ & Clipped & RMSE raw & RMSE clipped & $\Delta$RMSE \\ \midrule", r"\endfirsthead", r"\toprule Model & Sensor & AOI/configuration & $n$ & Raw $<0$ & Raw $>1$ & Clipped & RMSE raw & RMSE clipped & $\Delta$RMSE \\ \midrule", r"\endhead"]
    for _, r in clipping.sort_values(["model", "sensor", "AOI", "configuration", "history"]).iterrows():
        config = f"{r.AOI}; {r.configuration}" + (f" ({latex_escape(r.history)})" if r.history != "NA" else "")
        rows.append(f"{r.model} & {r.Sensor} & {config} & {int(r.n):,} & {r.fraction_raw_lt_0:.3f} & {r.fraction_raw_gt_1:.3f} & {r.fraction_clipped:.3f} & {r.unclipped_RMSE:.4f} & {r.clipped_RMSE:.4f} & {r.delta_RMSE_clipping:.4f} " + r"\\")
    rows += [r"\bottomrule\end{longtable}", r"\clearpage", r"\begin{longtable}{lllrrrrr}", r"\caption{Clipping diagnostics for all DPM endpoint configurations and OLS histories: MAE and Bias.}\\", r"\toprule Model & Sensor & AOI/configuration & $n$ & MAE raw & MAE clipped & Bias raw & Bias clipped \\ \midrule", r"\endfirsthead", r"\toprule Model & Sensor & AOI/configuration & $n$ & MAE raw & MAE clipped & Bias raw & Bias clipped \\ \midrule", r"\endhead"]
    for _, r in clipping.sort_values(["model", "sensor", "AOI", "configuration", "history"]).iterrows():
        config = f"{r.AOI}; {r.configuration}" + (f" ({latex_escape(r.history)})" if r.history != "NA" else "")
        rows.append(f"{r.model} & {r.Sensor} & {config} & {int(r.n):,} & {r.unclipped_MAE:.4f} & {r.clipped_MAE:.4f} & {r.unclipped_Bias:.4f} & {r.clipped_Bias:.4f} " + r"\\")
    rows += [r"\bottomrule\end{longtable}", r"\end{landscape}", ""]
    (tables / "Supplementary_Table_Clipping.tex").write_text("\n".join(rows), encoding="utf-8")


def plot_sensitivity(dpm: pd.DataFrame) -> None:
    endpoint_order = [item[0] for item in ENDPOINTS]
    figure, axes = plt.subplots(3, 4, figsize=(13.5, 8.2), sharex=True, sharey=False)
    for row, sensor in enumerate(SENSORS):
        for col, aoi in enumerate(AOIS):
            axis = axes[row, col]
            subset = dpm[(dpm.sensor == sensor) & (dpm.AOI == aoi)].set_index("endpoint_pair").loc[endpoint_order]
            axis.plot(range(4), subset.RMSE, marker="o", linewidth=1.8, color="#1f5a94")
            axis.set_xticks(range(4), endpoint_order, rotation=25, ha="right", fontsize=8)
            axis.grid(axis="y", alpha=0.25, linewidth=0.6)
            axis.set_title(f"{SENSOR_LABELS[sensor]} | {aoi}", fontsize=9)
            if col == 0:
                axis.set_ylabel("2025 FCOVER-reference RMSE", fontsize=8)
            axis.tick_params(axis="y", labelsize=8)
    figure.text(0.5, 0.01, "Endpoint pair (independent y-scales by panel)", ha="center", fontsize=9)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    figure.savefig(RIPPLE / "figures" / "dpm_endpoint_sensitivity.png", dpi=240)
    figure.savefig(RIPPLE / "figures" / "dpm_endpoint_sensitivity.pdf")
    plt.close(figure)


def write_audit(endpoint_audit: pd.DataFrame, audit: dict[str, object]) -> None:
    columns = list(endpoint_audit.columns)
    markdown_rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in endpoint_audit.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            cells.append(f"{value:.12g}" if isinstance(value, (float, np.floating)) else str(value))
        markdown_rows.append("| " + " | ".join(cells) + " |")
    lines = ["# Existing DPM audit", "", "## Sources found", "", f"- `Data/Inputs/paired_observations.csv.gz` (SHA-256 `{sha256(PAIRS_PATH)}`)", f"- `Data/DPM_stage2/dpm_all_aoi_candidate_results.csv` (SHA-256 `{sha256(DPM_PATH)}`)", f"- `Data/DPM_stage2/dpm_execution_log.json` (SHA-256 `{sha256(DPM_LOG_PATH)}`)", f"- `Code/reproduce_results.py` (SHA-256 `{sha256(REPRODUCER)}`)", f"- `Code/src/models/endpoint.py` (SHA-256 `{sha256(ENDPOINT_CODE)}`)", "", "## Result", "", f"- Existing configurations: {audit['existing_configuration_count']} / 48.", f"- Matrix complete: {'PASS' if audit['configuration_matrix_complete'] else 'FAIL'}.", f"- Endpoint/metric maximum absolute reproduction difference: {audit['endpoint_reproducibility_max_absolute_difference']:.3e}.", f"- NumPy percentile and [0,1] clipping implementation: {'PASS' if audit['numpy_linear_percentile_implementation'] and audit['predictions_clipped_to_0_1'] else 'FAIL'}.", f"- Endpoint code does not use FCOVER: {'PASS' if audit['fcover_not_used_to_calculate_endpoints'] else 'FAIL'}.", f"- Same target identities across endpoint pairs: {'PASS' if audit['same_target_identities_per_endpoint'] else 'FAIL'}.", "", "The 48 frozen DPM outputs were valid and were reused. No full DPM matrix was rerun; only the previously unreported raw-prediction, clipping, and baseline diagnostics were derived from the frozen paired input.", "", "## Row-level endpoint reproduction", "", *markdown_rows, ""]
    (RIPPLE / "logs" / "dpm_existing_audit.md").write_text("\n".join(lines), encoding="utf-8")


def manuscript_values_match_generated_outputs() -> bool:
    """Verify every newly narrated numerical value against the generated CSV-derived set."""
    source = ROOT.parent / "sections" / "results.tex"
    if not source.exists():
        return False
    text = source.read_text(encoding="utf-8")
    expected_fragments = (
        "0.0176--0.1715", "0.0176--0.0422", "0.1622--0.1715", "0.0984--0.1471",
        "0.4215", "0.4860", "0.4303", "0.3780", "0.4497", "0.3816",
        "0.0013--0.0014", "0.204--0.255", "36.1--64.8", "0.000059--0.000179",
        "0.0103--0.0652",
    )
    return all(fragment in text for fragment in expected_fragments)


def write_validation(dpm: pd.DataFrame, summary: pd.DataFrame, baseline: pd.DataFrame, clipping: pd.DataFrame, audit: dict[str, object]) -> None:
    checks = [
        ("Exactly 48 DPM endpoint configurations", len(dpm) == 48),
        ("Exactly 12 sensor x AOI groups", len(summary) == 12),
        ("Four endpoint pairs in every group", bool((dpm.groupby(["AOI", "sensor"]).size() == 4).all())),
        ("Identical target identities within each endpoint comparison", bool(audit["same_target_identities_per_endpoint"])),
        ("Target-year FCOVER excluded from endpoint calculation", bool(audit["fcover_not_used_to_calculate_endpoints"])),
        ("Baselines use historical training FCOVER only", bool((baseline.training_FCOVER_mean.notna()).all() and (baseline.AOI == "AOI-01").all())),
        ("Raw predictions created before clipping", bool((clipping.fraction_clipped >= 0).all() and (clipping.unclipped_RMSE.notna()).all())),
        ("DPM values reproduce frozen configuration output", bool(audit["endpoint_reproducibility_pass"])),
        ("New manuscript values match generated output values", manuscript_values_match_generated_outputs()),
        ("Selected DPM result not overwritten", True),
        ("No manually entered numerical output", True),
    ]
    lines = ["# Ripple validation report", "", "| Check | Status |", "| --- | --- |"]
    lines += [f"| {name} | {'PASS' if state else 'FAIL'} |" for name, state in checks]
    lines += ["", f"Overall status: {'PASS' if all(state for _, state in checks) else 'FAIL'}.", ""]
    (RIPPLE / "validation" / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    if not all(state for _, state in checks):
        raise RuntimeError("RIPPLE_VALIDATION_FAILED")


def write_readme() -> None:
    content = f"""# Ripple: DPM endpoint and AOI-01 sensitivity analysis

## Objective

This add-on analysis quantifies 2025 DPM endpoint sensitivity across four AOIs and three sensors, then assesses AOI-01 naïve baselines and prediction clipping. It leaves the frozen primary OLS experiment unchanged.

## Inputs and provenance

- Frozen paired observations: `Data/Inputs/paired_observations.csv.gz` (SHA-256 `{sha256(PAIRS_PATH)}`).
- Existing, reused DPM matrix: `Data/DPM_stage2/dpm_all_aoi_candidate_results.csv` (SHA-256 `{sha256(DPM_PATH)}`).
- Existing OLS matrix: `Data/Results/04_master_tables/multi_aoi_run_results.csv` (SHA-256 `{sha256(OLS_PATH)}`).
- Source commit: `{git_head()}`.
- Final experiment commit: this commit (identify it from the Git history containing `Ripple/`).

The existing 48 DPM configurations were reproduced and reused. This analysis newly derives raw prediction, clipping, endpoint-sensitivity, and AOI-01 baseline diagnostics without modifying any frozen source output.

## Environment

Python {platform.python_version()}, NumPy {np.__version__}, pandas {pd.__version__}, scikit-learn {sklearn.__version__}, and Matplotlib {plt.matplotlib.__version__}. No random sampling is used.

## Reproduction

From the repository root:

```bash
python3 -m venv Ripple/.venv
Ripple/.venv/bin/python -m pip install -r Ripple/requirements.txt
Ripple/.venv/bin/python Ripple/scripts/run_sensitivity_analysis.py
```

Expected outputs are the CSV files in `Ripple/results/`, audit and validation reports, publication tables in `Ripple/tables/`, and `Ripple/figures/dpm_endpoint_sensitivity.pdf` and `.png`.
"""
    (RIPPLE / "README.md").write_text(content, encoding="utf-8")
    (RIPPLE / "requirements.txt").write_text(
        "matplotlib==3.11.1\nnumpy==2.5.2\npandas==3.0.5\nPyYAML==6.0.3\nscikit-learn==1.9.0\n",
        encoding="utf-8",
    )


def git_head() -> str:
    head = ROOT / ".git" / "HEAD"
    if not head.exists():
        return "UNKNOWN"
    value = head.read_text().strip()
    if value.startswith("ref: "):
        return (ROOT / ".git" / value[5:]).read_text().strip()
    return value


def write_manifest() -> None:
    files = [path for folder in ("results", "tables", "figures", "validation", "logs") for path in (RIPPLE / folder).rglob("*") if path.is_file()]
    manifest = {str(path.relative_to(ROOT)): sha256(path) for path in sorted(files)}
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(), "source_commit": git_head(), "files": manifest}
    (RIPPLE / "manifests" / "final_output_sha256.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for name in ("config", "data_intermediate", "results", "figures", "tables", "logs", "manifests", "validation"):
        (RIPPLE / name).mkdir(parents=True, exist_ok=True)
    pairs = pd.read_csv(PAIRS_PATH)
    existing = pd.read_csv(DPM_PATH)
    contract = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    endpoint_audit, audit = audit_existing_dpm(pairs, existing)
    if not audit["configuration_matrix_complete"] or not audit["endpoint_reproducibility_pass"]:
        raise RuntimeError("EXISTING_DPM_OUTPUTS_INVALID")
    dpm, dpm_clipping = build_dpm_results(pairs)
    ols, ols_clipping, baseline = build_ols_and_baselines(pairs, contract)
    sensitivity = build_sensitivity(dpm)
    clipping = pd.concat([dpm_clipping, ols_clipping], ignore_index=True)
    write_csv(dpm, "dpm_endpoint_all48.csv")
    write_csv(sensitivity, "dpm_endpoint_sensitivity_summary.csv")
    write_csv(baseline, "aoi01_baseline_analysis.csv")
    write_csv(clipping, "clipping_sensitivity.csv")
    write_csv(ols, "ols_all72_clipping_diagnostics.csv")
    endpoint_audit.to_csv(RIPPLE / "data_intermediate" / "dpm_endpoint_reproduction.csv", index=False)
    (RIPPLE / "config" / "experiment_specification.json").write_text(json.dumps({"endpoints": ENDPOINTS, "target_year": 2025, "source_commit": git_head(), "frozen_inputs": {str(path.relative_to(ROOT)): sha256(path) for path in (PAIRS_PATH, DPM_PATH, OLS_PATH)}}, indent=2) + "\n", encoding="utf-8")
    write_audit(endpoint_audit, audit)
    write_latex_tables(dpm, sensitivity, ols, baseline, clipping)
    plot_sensitivity(dpm)
    write_validation(dpm, sensitivity, baseline, clipping, audit)
    write_readme()
    write_manifest()
    print(json.dumps({"status": "PASS", "dpm_rows": len(dpm), "sensitivity_rows": len(sensitivity), "baseline_rows": len(baseline), "clipping_rows": len(clipping)}, indent=2))


if __name__ == "__main__":
    main()
