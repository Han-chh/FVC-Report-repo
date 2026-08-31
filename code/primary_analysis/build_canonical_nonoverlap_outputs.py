"""Build primary outputs from the canonical non-overlapping paired dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from additional_sensitivity_analysis.production import evaluate_pairs
from metrics.regression_metrics import regression_metrics
from models.endpoint import endpoint_predict
from models.ols import predict_clipped


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/canonical/paired_observations.csv.gz"
QUANTILES = ((1, 99), (2, 98), (5, 95), (10, 90))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dpm_results(pairs: pd.DataFrame, multi: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for (aoi, sensor), group in pairs[pairs.year.eq(2025)].groupby(["aoi_id", "sensor"], sort=True):
        ndvi = group.NDVI.to_numpy(float)
        target = group.FCOVER.to_numpy(float)
        for low_q, high_q in QUANTILES:
            low, high = np.percentile(ndvi, [low_q, high_q])
            prediction = endpoint_predict(ndvi, float(low), float(high))
            raw = (ndvi - low) / (high - low)
            rows.append({
                "AOI": aoi, "sensor": sensor, "quantile_configuration": f"P{low_q}/P{high_q}",
                "NDVI_low": float(low), "NDVI_high": float(high), "target_evaluation_pairs": int(len(group)),
                "unique_target_identities": int(group.pixel_id.nunique()), "target_year": 2025,
                "low_clip_count": int((raw < 0).sum()), "high_clip_count": int((raw > 1).sum()),
                "low_clip_ratio": float((raw < 0).mean()), "high_clip_ratio": float((raw > 1).mean()),
                "total_clip_ratio": float(((raw < 0) | (raw > 1)).mean()),
                **regression_metrics(target, prediction),
            })
    candidates = pd.DataFrame(rows).rename(columns={"RMSE": "RMSE_DPM", "MAE": "MAE_DPM", "Bias": "Bias_DPM", "R2": "R2_DPM", "Pearson_r": "Pearson_r_DPM", "n": "n_DPM"})
    best_dpm = candidates.loc[candidates.groupby(["AOI", "sensor"]).RMSE_DPM.idxmin()].copy()
    best_ols = multi.loc[multi.groupby(["AOI", "sensor"]).RMSE.idxmin(), ["AOI", "sensor", "window", "n", "RMSE", "MAE", "Bias", "R2", "Pearson_r", "slope", "intercept"]].copy()
    best_ols = best_ols.rename(columns={"window": "OLS_history", "n": "n_OLS", "RMSE": "RMSE_OLS", "MAE": "MAE_OLS", "Bias": "Bias_OLS", "R2": "R2_OLS", "Pearson_r": "Pearson_r_OLS"})
    summary = best_dpm.merge(best_ols, on=["AOI", "sensor"], validate="one_to_one")
    summary["Delta_RMSE_DPM_minus_OLS"] = summary.RMSE_DPM - summary.RMSE_OLS
    summary["Delta_MAE_DPM_minus_OLS"] = summary.MAE_DPM - summary.MAE_OLS
    summary["RMSE_ratio_DPM_over_OLS"] = summary.RMSE_DPM / summary.RMSE_OLS
    # AOI-01 diagnostics use the selected 2025 OLS fit and selected DPM endpoints.
    diagnostic: list[dict[str, object]] = []
    for _, row in summary[summary.AOI.eq("AOI-01")].iterrows():
        group = pairs[(pairs.aoi_id == row.AOI) & (pairs.sensor == row.sensor) & (pairs.year == 2025)]
        y = group.FCOVER.to_numpy(float)
        selected_train = pairs[(pairs.aoi_id == row.AOI) & (pairs.sensor == row.sensor) & (pairs.year.isin({int(year) for year in str(row.OLS_history).replace("W", "").split("_")}))]
        # The explicit history map is simpler and makes the audit independent of labels.
        history_years = {"W2022": [2022], "W2023": [2023], "W2024": [2024], "W2022_2023": [2022, 2023], "W2023_2024": [2023, 2024], "W2022_2024": [2022, 2023, 2024]}[row.OLS_history]
        selected_train = pairs[(pairs.aoi_id == row.AOI) & (pairs.sensor == row.sensor) & (pairs.year.isin(history_years))]
        from models.ols import fit_ols
        model = fit_ols(selected_train.NDVI, selected_train.FCOVER)
        raw_ols = model.predict(group.NDVI.to_numpy(float).reshape(-1, 1))
        baselines = {"zero": np.zeros(len(group)), "training_mean": np.full(len(group), selected_train.FCOVER.mean()), "selected_OLS": predict_clipped(model, group.NDVI)}
        for method, prediction in baselines.items():
            diagnostic.append({"AOI": row.AOI, "sensor": row.sensor, "method": method, "n": len(group),
                               "raw_low_clip_ratio": float((raw_ols < 0).mean()) if method == "selected_OLS" else np.nan,
                               "raw_high_clip_ratio": float((raw_ols > 1).mean()) if method == "selected_OLS" else np.nan,
                               **regression_metrics(y, prediction)})
        dpm_raw = (group.NDVI.to_numpy(float) - row.NDVI_low) / (row.NDVI_high - row.NDVI_low)
        diagnostic.append({"AOI": row.AOI, "sensor": row.sensor, "method": "selected_DPM", "n": len(group),
                           "raw_low_clip_ratio": float((dpm_raw < 0).mean()), "raw_high_clip_ratio": float((dpm_raw > 1).mean()),
                           **regression_metrics(y, endpoint_predict(group.NDVI, row.NDVI_low, row.NDVI_high))})
    return candidates, summary, pd.DataFrame(diagnostic)


def write_report(output: Path, pairs: pd.DataFrame, frames: dict[str, pd.DataFrame], dpm: pd.DataFrame, comparison: pd.DataFrame) -> None:
    multi = frames["multi_aoi_metrics"]
    rolling = frames["rolling_origin_metrics"]
    contrasts = frames["block_contrasts"]
    selected = multi.loc[multi.groupby(["AOI", "sensor"]).RMSE.idxmin()]
    supported = contrasts[contrasts.Holm_adjusted_p <= 0.05]
    lines = [
        "# Canonical non-overlap primary-result audit",
        "",
        "## Protocol",
        "The canonical preprocessing assigns each eligible source observation to its nearest 20 July, 31 July, or 10 August nominal date within the inclusive 15-day support. Ties are assigned to the earlier nominal date. An identity is assigned to no more than one nominal date; the temporal reducer remains the existing cell-wise median with at least two contributions.",
        "",
        "## Run inventory",
        f"- Source pair rows: {len(pairs):,}; unique target identities across sensor-specific records: {pairs[['sensor', 'aoi_id', 'year', 'nominal_date', 'pixel_id']].drop_duplicates().shape[0]:,}.",
        f"- Multi-AOI OLS configurations: {len(multi)}; Rolling-Origin OLS configurations: {len(rolling)}; DPM endpoint configurations: {len(dpm)}.",
        f"- Paired block contrasts: {len(contrasts)}; Holm-supported: {len(supported)}; longer-window lower-error: {int((supported.mean_difference_RMSE > 0).sum())}; longer-window higher-error: {int((supported.mean_difference_RMSE < 0).sum())}.",
        "",
        "## Sensor-level 2025 Multi-AOI means",
    ]
    for sensor, group in multi.groupby("sensor"):
        lines.append(f"- {sensor}: RMSE={group.RMSE.mean():.6f}, MAE={group.MAE.mean():.6f}, Bias={group.Bias.mean():.6f} (24 runs).")
    lines.extend(["", "## Preferred 2025 histories", ""])
    for row in selected.sort_values(["sensor", "AOI"]).itertuples():
        lines.append(f"- {row.sensor}, {row.AOI}: {row.window} (RMSE={row.RMSE:.6f}).")
    lines.extend(["", "## DPM/OLS comparison", f"- OLS has lower selected RMSE in {int((comparison.RMSE_OLS < comparison.RMSE_DPM).sum())}/12 sensor--AOI comparisons; DPM/OLS RMSE ratio={comparison.RMSE_ratio_DPM_over_OLS.min():.2f}--{comparison.RMSE_ratio_DPM_over_OLS.max():.2f}.", "", "## Provenance", f"- Canonical pair input SHA-256: `{sha256(SOURCE)}`.", "- This directory was regenerated from the canonical paired dataset."])
    (output / "CANONICAL_NONOVERLAP_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True,
                        help="Empty, explicit reconstruction directory outside the repository.")
    parser.add_argument("--resume", action="store_true", help="Overwrite only this dedicated regenerated result directory.")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()) and not args.resume:
        raise RuntimeError(f"OUTPUT_NOT_EMPTY:{output}")
    output.mkdir(parents=True, exist_ok=args.resume)
    pairs = pd.read_csv(SOURCE)
    frames = evaluate_pairs(pairs, output, sensitivity="canonical_nonoverlap_primary", variant="nearest_nominal_nonoverlap")
    candidates, comparison, aoi01 = dpm_results(pairs, frames["multi_aoi_metrics"])
    candidates.to_csv(output / "dpm_endpoint_sensitivity.csv", index=False)
    comparison.to_csv(output / "dpm_vs_ols_selected.csv", index=False)
    aoi01.to_csv(output / "aoi01_baseline_clipping.csv", index=False)
    manifest = {
        "status": "PASS", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": "nearest_nominal_nonoverlap", "source_pairs": str(SOURCE),
        "source_pairs_sha256": sha256(SOURCE), "pair_rows": int(len(pairs)),
        "multi_aoi_runs": int(len(frames["multi_aoi_metrics"])), "rolling_origin_runs": int(len(frames["rolling_origin_metrics"])),
        "dpm_runs": int(len(candidates)), "block_contrasts": int(len(frames["block_contrasts"])),
        "code_sha256": sha256(Path(__file__)),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_report(output, pairs, frames, candidates, comparison)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
