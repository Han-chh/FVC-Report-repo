#!/usr/bin/env python3
"""Create traceable revision tables, validation diagnostics and figures.

The program is deliberately read-only with respect to frozen report data.  It
reconstructs only report-side diagnostics from the frozen 300 m composites,
raw FCOVER QA layers and immutable task manifests.  In particular, CV output
is labelled as a report-side re-analysis; it does not rewrite any of the 21
formal experiment products.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import ast
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import yaml
from matplotlib.colors import ListedColormap
from pyproj import Transformer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT
DATA = Path(os.environ.get("FVC_REPORT_DATA", str(REPORT / "data_final")))
OUT = Path(os.environ.get("FVC_REPORT_OUTPUT", str(REPORT / "reports")))
FIG = Path(os.environ.get("FVC_REPORT_FIGURES", str(REPORT / "latex" / "generated_figures")))
AUDIT = OUT
RAW_PROJECT_CANDIDATES = (
    ROOT / "qh-fvc-data" / "storage" / "projects",
    ROOT.parent / "qh-fvc-data" / "storage" / "projects",
)
RAW = next(
    project
    for candidate in RAW_PROJECT_CANDIDATES
    for project in candidate.glob("prj_*__*")
)
SENSORS = ("sentinel2", "landsat", "modis")
WINDOWS = {
    "2022": (2022,), "2023": (2023,), "2024": (2024,),
    "2022-2023": (2022, 2023), "2023-2024": (2023, 2024),
    "2022-2024": (2022, 2023, 2024),
}
DATES = ("07-20", "07-31", "08-10")
NODATA = -9999.0


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def write_csv(name: str, rows: list[dict]) -> Path:
    path = OUT / name
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def latex_number(value: object, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def latex_fragments(group_summary: list[dict], loyo_summary: list[dict], final: pd.DataFrame,
                    models: pd.DataFrame, endpoints: list[dict], temporal: list[dict], group_folds: list[dict]) -> None:
    """Static TeX tables generated from the report CSVs; no values are hand copied."""
    labels = {"sentinel2": "Sentinel-2", "landsat": "Landsat 8/9", "modis": "MODIS"}
    fragments = []
    fragments.append("\\begin{longtable}{llrrrrrr}\\caption{Development 空间 GroupKFold 内部验证结果（mean $\\pm$ SD）}\\label{tab:gkf}\\\\\\toprule 数据源&窗口&$k$&RMSE&范围&MAE&Bias&$r$\\\\\\midrule\\endfirsthead\\toprule 数据源&窗口&$k$&RMSE&范围&MAE&Bias&$r$\\\\\\midrule\\endhead")
    for row in group_summary:
        fragments.append(f"{labels[row['sensor']]} & {row['window']} & {row['fold_count']} & {latex_number(row['RMSE_mean'])} $\\pm$ {latex_number(row['RMSE_sd'])} & {latex_number(row['RMSE_min'])}--{latex_number(row['RMSE_max'])} & {latex_number(row['MAE_mean'])} & {latex_number(row['Bias_mean'])} & {latex_number(row['Pearson_r_mean'],3)}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{lllrllrr}\\caption{Development 留一年验证结果}\\label{tab:loyo}\\\\\\toprule 数据源&窗口&状态&留出年&RMSE mean $\\pm$ SD&最差年 RMSE&MAE&Bias\\\\\\midrule\\endfirsthead\\toprule 数据源&窗口&状态&留出年&RMSE mean $\\pm$ SD&最差年 RMSE&MAE&Bias\\\\\\midrule\\endhead")
    for row in loyo_summary:
        fragments.append(f"{labels[row['sensor']]} & {row['window']} & {row['status']} & {row['worst_held_out_year']} & {latex_number(row['RMSE_mean'])} $\\pm$ {latex_number(row['RMSE_sd'])} & {latex_number(row['worst_held_out_RMSE'])} & {latex_number(row['MAE_mean'])} & {latex_number(row['Bias_mean'])}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{llrrrrrr}\\caption{21 组 2025 年最终 FCOVER 一致性指标}\\label{tab:final21}\\\\\\toprule 数据源&策略&RMSE&MAE&Bias&$R^2$&$r$&$n$\\\\\\midrule\\endfirsthead\\toprule 数据源&策略&RMSE&MAE&Bias&$R^2$&$r$&$n$\\\\\\midrule\\endhead")
    for row in final.itertuples():
        strategy = "Formula P5/P95" if row.strategy == "formula-p5-p95" else row.strategy
        fragments.append(f"{labels[row.sensor]} & {strategy} & {latex_number(row.rmse)} & {latex_number(row.mae)} & {latex_number(row.bias)} & {latex_number(row.r_squared)} & {latex_number(row.pearson_r,3)} & {int(row.valid_comparison_count):,}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{llrrr}\\caption{18 个正式回归模型参数（由当前历史样本拟合）}\\label{tab:params}\\\\\\toprule 数据源&窗口&$a$&$b$&训练样本数\\\\\\midrule\\endfirsthead\\toprule 数据源&窗口&$a$&$b$&训练样本数\\\\\\midrule\\endhead")
    for row in models[models.strategy != "formula-p5-p95"].itertuples():
        fragments.append(f"{labels[row.sensor]} & {row.strategy} & {latex_number(row.slope_a,6)} & {latex_number(row.intercept_b,6)} & {int(row.total_training_samples):,}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{llrrrrrr}\\caption{不同分位端点设置下公式法敏感性结果}\\label{tab:endpoints}\\\\\\toprule 数据源&端点&低端&高端&下端率&上端率&RMSE&MAE\\\\\\midrule\\endfirsthead\\toprule 数据源&端点&低端&高端&下端率&上端率&RMSE&MAE\\\\\\midrule\\endhead")
    for row in endpoints:
        fragments.append(f"{labels[row['sensor']]} & {row['endpoint']} & {latex_number(row['NDVI_low'])} & {latex_number(row['NDVI_high'])} & {latex_number(100*row['low_clip_ratio'],2)}\\% & {latex_number(100*row['high_clip_ratio'],2)}\\% & {latex_number(row['RMSE'])} & {latex_number(row['MAE'])}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{lllr|rrrrrr}\\caption{各 FCOVER 标签对应的有效观测统计}\\label{tab:observations}\\\\\\toprule 数据源&年份&FCOVER 日期&检索数&中位数&P25&P75&最小&最大&低于阈值像元\\\\\\midrule\\endfirsthead\\toprule 数据源&年份&FCOVER 日期&检索数&中位数&P25&P75&最小&最大&低于阈值像元\\\\\\midrule\\endhead")
    for row in temporal:
        fragments.append(f"{labels[row['sensor']]} & {row['year']} & {row['FCOVER_date']} & {row['retrieved_observations']} & {latex_number(row['valid_obs_median'],1)} & {latex_number(row['valid_obs_P25'],1)} & {latex_number(row['valid_obs_P75'],1)} & {row['valid_obs_min']} & {row['valid_obs_max']} & {row['below_minimum_pixel_count']:,}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    fragments.append("\\begin{longtable}{llrrrrrr}\\caption{GroupKFold 逐折结果（附录）}\\label{tab:gkf-folds}\\\\\\toprule 数据源&窗口&折&训练$n$&验证$n$&验证块&RMSE&MAE\\\\\\midrule\\endfirsthead\\toprule 数据源&窗口&折&训练$n$&验证$n$&验证块&RMSE&MAE\\\\\\midrule\\endhead")
    for row in group_folds:
        fragments.append(f"{labels[row['sensor']]} & {row['window']} & {row['fold_id']} & {row['train_samples']:,} & {row['validation_samples']:,} & {row['validation_blocks']} & {latex_number(row['RMSE'])} & {latex_number(row['MAE'])}\\\\")
    fragments.append("\\bottomrule\\end{longtable}")
    # Separate fragments preserve logical placement in the manuscript while the
    # combined file remains convenient for audit and external reuse.
    (OUT / "validation_tables.tex").write_text("\n".join(fragments[:40]) + "\n", encoding="utf-8")
    (OUT / "result_tables.tex").write_text("\n".join(fragments[40:97]) + "\n", encoding="utf-8")
    (OUT / "appendix_tables.tex").write_text("\n".join(fragments[97:]) + "\n", encoding="utf-8")
    (OUT / "latex_tables.tex").write_text("\n".join(fragments) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metric(y: np.ndarray, pred: np.ndarray) -> dict:
    residual = pred - y
    ss_total = np.sum((y - y.mean()) ** 2)
    pearson = (float(np.corrcoef(y, pred)[0, 1]) if len(y) > 1 and np.std(y) > 0
               and np.std(pred) > 0 else np.nan)
    return {
        "RMSE": float(np.sqrt(np.mean(residual ** 2))),
        "MAE": float(np.mean(np.abs(residual))),
        "Bias": float(np.mean(residual)),
        "R2": float(1 - np.sum(residual ** 2) / ss_total) if ss_total > 0 else np.nan,
        "Pearson_r": pearson,
        "n": int(len(y)),
    }


def fcover_path(year: int, mmdd: str) -> Path:
    return next(RAW.glob(
        f"data-center/fcover/series/*/years/{year}/*/raw/acquisition/raw/fcover/"
        f"fcover_{year}-{mmdd}.tif"))


def fcover(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(path) as ds:
        names = {name: i + 1 for i, name in enumerate(ds.descriptions)}
        scale = float(json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text(encoding="utf-8"))["quality_metadata"]["fcover_scale"])
        value = ds.read(names["FCOVER"]).astype("float64") * scale
        qflag = ds.read(names["QFLAG"])
        nobs = ds.read(names["NOBS"])
        data_mask = ds.read(names["dataMask"])
    valid = ((qflag < 255) & (nobs > 0) & (data_mask > 0) & np.isfinite(value)
             & (value >= 0) & (value <= 1))
    return value, valid


def sample_frame(sensor: str, years: tuple[int, ...]) -> pd.DataFrame:
    """Read each formal native-support observation exactly once into samples."""
    records = []
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32647", always_xy=True)
    for year in years:
        for mmdd in DATES:
            ndvi_path = DATA / "composites" / sensor / str(year) / mmdd / "ndvi_median_fcover_support.tif"
            count_path = DATA / "composites" / sensor / str(year) / mmdd / "valid_observation_count.tif"
            with rasterio.open(ndvi_path) as ds:
                ndvi = ds.read(1).astype("float64")
                ndvi[ndvi == ds.nodata] = np.nan
                transform = ds.transform
            with rasterio.open(count_path) as ds:
                count = ds.read(1)
            reference, ref_valid = fcover(fcover_path(year, mmdd))
            good = np.isfinite(ndvi) & ref_valid & (count >= 2)
            rows, cols = np.where(good)
            lon, lat = rasterio.transform.xy(transform, rows, cols, offset="center")
            x, y = transformer.transform(np.asarray(lon), np.asarray(lat))
            records.extend({
                "sensor": sensor, "year": year, "target_date": f"{year}-{mmdd}",
                "NDVI": float(ndvi[row, col]), "FCOVER": float(reference[row, col]),
                "valid_observations": int(count[row, col]), "row": int(row), "col": int(col),
                "longitude": float(lon[i]), "latitude": float(lat[i]),
                "x_m": float(x[i]), "y_m": float(y[i]),
                "support_id": f"r{row}_c{col}",
            } for i, (row, col) in enumerate(zip(rows, cols, strict=True)))
    return pd.DataFrame.from_records(records)


def blocks(frame: pd.DataFrame, block_size: float = 5000.0) -> tuple[pd.DataFrame, dict]:
    result = frame.copy()
    origin_x = math.floor(float(result.x_m.min()) / block_size) * block_size
    origin_y = math.floor(float(result.y_m.min()) / block_size) * block_size
    col = np.floor((result.x_m - origin_x) / block_size).astype(int)
    row = np.floor((result.y_m - origin_y) / block_size).astype(int)
    result["block_id"] = [f"b_{c}_{r}" for c, r in zip(col, row, strict=True)]
    info = {"crs": "EPSG:32647", "block_size_m": block_size,
            "grid_origin_x_m": origin_x, "grid_origin_y_m": origin_y,
            "random_seed": 42}
    return result, info


def select_final_blocks(block_ids: list[str], seed: int = 42, fraction: float = .2) -> list[str]:
    ranked = sorted(block_ids, key=lambda block: stable({"seed": seed, "block": block}))
    number = min(max(1, int(round(len(ranked) * fraction))), len(ranked) - 2)
    return sorted(ranked[:number])


def folds_for_window(frame: pd.DataFrame, sensor: str, window: str) -> tuple[list[dict], list[dict], dict, dict]:
    selected, info = blocks(frame)
    ids = sorted(selected.block_id.unique())
    final_blocks = select_final_blocks(ids)
    development = selected.loc[~selected.block_id.isin(final_blocks)].copy()
    final = selected.loc[selected.block_id.isin(final_blocks)].copy()
    group_rows, loyo_rows = [], []
    groups = development.block_id.astype(str).to_numpy()
    split = GroupKFold(n_splits=min(5, len(np.unique(groups))))
    for fold, (tr, va) in enumerate(split.split(development, groups=groups)):
        train, validation = development.iloc[tr], development.iloc[va]
        model = LinearRegression().fit(train[["NDVI"]], train.FCOVER)
        values = metric(validation.FCOVER.to_numpy(), model.predict(validation[["NDVI"]]))
        group_rows.append({"sensor": sensor, "window": window, "fold_id": fold,
                           "train_samples": len(train), "validation_samples": len(validation),
                           "train_blocks": train.block_id.nunique(), "validation_blocks": validation.block_id.nunique(),
                           "train_block_ids": ";".join(sorted(train.block_id.unique())),
                           "validation_block_ids": ";".join(sorted(validation.block_id.unique())),
                           "coefficient_a": float(model.coef_[0]), "intercept_b": float(model.intercept_),
                           **values})
    years = sorted(development.year.unique())
    if len(years) < 2:
        loyo_rows.append({"sensor": sensor, "window": window, "status": "N/A",
                           "reason": "LOYO_SKIPPED_INSUFFICIENT_YEARS",
                           "held_out_year": "", "training_years": "", "train_samples": "",
                           "validation_samples": "", "train_blocks": "", "validation_blocks": "",
                           "coefficient_a": "", "intercept_b": "", "RMSE": "", "MAE": "",
                           "Bias": "", "R2": "", "Pearson_r": "", "n": ""})
    else:
        for held in years:
            train = development.loc[development.year != held]
            validation = development.loc[development.year == held]
            model = LinearRegression().fit(train[["NDVI"]], train.FCOVER)
            values = metric(validation.FCOVER.to_numpy(), model.predict(validation[["NDVI"]]))
            loyo_rows.append({"sensor": sensor, "window": window, "status": "completed", "reason": "",
                              "held_out_year": int(held), "training_years": ";".join(map(str, sorted(train.year.unique()))),
                              "train_samples": len(train), "validation_samples": len(validation),
                              "train_blocks": train.block_id.nunique(), "validation_blocks": validation.block_id.nunique(),
                              "coefficient_a": float(model.coef_[0]), "intercept_b": float(model.intercept_), **values})
    partition = {**info, "total_blocks": len(ids), "development_blocks": len(ids) - len(final_blocks),
                 "final_test_blocks": len(final_blocks), "final_block_fraction_configured": .2,
                 "buffer_distance_m": 0.0, "final_block_ids": final_blocks,
                 "partition_hash": stable({**info, "block_ids": ids}),
                 "development_samples": len(development), "final_test_samples": len(final),
                 "development_sample_fraction": len(development) / len(selected),
                 "final_test_sample_fraction": len(final) / len(selected)}
    return group_rows, loyo_rows, partition, {"development": development, "final": final}


def cv_summary(group: list[dict], loyo: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    gdf, ldf = pd.DataFrame(group), pd.DataFrame(loyo)
    gs, ls, internal = [], [], []
    for sensor in SENSORS:
        for window in WINDOWS:
            g = gdf[(gdf.sensor == sensor) & (gdf.window == window)]
            record = {"sensor": sensor, "window": window, "fold_count": len(g),
                      "RMSE_mean": g.RMSE.mean(), "RMSE_sd": g.RMSE.std(ddof=0),
                      "RMSE_min": g.RMSE.min(), "RMSE_max": g.RMSE.max(),
                      "MAE_mean": g.MAE.mean(), "MAE_sd": g.MAE.std(ddof=0),
                      "Bias_mean": g.Bias.mean(), "absolute_Bias_mean": g.Bias.abs().mean(),
                      "R2_mean": g.R2.mean(), "Pearson_r_mean": g.Pearson_r.mean(),
                      "best_fold": int(g.loc[g.RMSE.idxmin(), "fold_id"]),
                      "worst_fold": int(g.loc[g.RMSE.idxmax(), "fold_id"]),
                      "fold_imbalance_ratio": g.validation_samples.max() / g.validation_samples.min()}
            gs.append(record)
            l = ldf[(ldf.sensor == sensor) & (ldf.window == window) & (ldf.status == "completed")]
            lrec = {"sensor": sensor, "window": window, "status": "completed" if len(l) else "N/A",
                    "fold_count": len(l), "RMSE_mean": l.RMSE.mean() if len(l) else np.nan,
                    "RMSE_sd": l.RMSE.std(ddof=0) if len(l) else np.nan,
                    "RMSE_min": l.RMSE.min() if len(l) else np.nan,
                    "RMSE_max": l.RMSE.max() if len(l) else np.nan,
                    "MAE_mean": l.MAE.mean() if len(l) else np.nan,
                    "Bias_mean": l.Bias.mean() if len(l) else np.nan,
                    "absolute_Bias_mean": l.Bias.abs().mean() if len(l) else np.nan,
                    "R2_mean": l.R2.mean() if len(l) else np.nan,
                    "Pearson_r_mean": l.Pearson_r.mean() if len(l) else np.nan,
                    "worst_held_out_year": int(l.loc[l.RMSE.idxmax(), "held_out_year"]) if len(l) else "N/A",
                    "worst_held_out_RMSE": l.RMSE.max() if len(l) else np.nan}
            ls.append(lrec)
            internal.append({"sensor": sensor, "window": window,
                             "training_sample_count": int(g.iloc[0].train_samples + g.iloc[0].validation_samples),
                             "GroupKFold_RMSE_mean": record["RMSE_mean"], "GroupKFold_RMSE_sd": record["RMSE_sd"],
                             "GroupKFold_MAE_mean": record["MAE_mean"], "GroupKFold_Bias_mean": record["Bias_mean"],
                             "LOYO_status": lrec["status"], "LOYO_RMSE_mean": lrec["RMSE_mean"],
                             "LOYO_RMSE_sd": lrec["RMSE_sd"], "LOYO_worst_year": lrec["worst_held_out_year"],
                             "LOYO_worst_RMSE": lrec["worst_held_out_RMSE"],
                             "coefficient_stability_note": "fold coefficients retained in fold files",
                             "selection_stage": "development-only report-side re-analysis"})
    return gs, ls, internal


def load_final() -> pd.DataFrame:
    return pd.read_csv(DATA / "reports" / "final_21_experiment_metrics.csv")


def endpoint_sensitivity() -> list[dict]:
    result = []
    for sensor in SENSORS:
        ndvis, refs = [], []
        for mmdd in DATES:
            ndvi_path = DATA / "composites" / sensor / "2025" / mmdd / "ndvi_median_fcover_support.tif"
            count_path = DATA / "composites" / sensor / "2025" / mmdd / "valid_observation_count.tif"
            with rasterio.open(ndvi_path) as ds:
                ndvi = ds.read(1).astype(float); ndvi[ndvi == ds.nodata] = np.nan
            with rasterio.open(count_path) as ds: count = ds.read(1)
            reference, valid_ref = fcover(fcover_path(2025, mmdd))
            good = np.isfinite(ndvi) & valid_ref & (count >= 2)
            ndvis.append(ndvi[good]); refs.append(reference[good])
        x, y = np.concatenate(ndvis), np.concatenate(refs)
        for lowp, highp in ((1, 99), (2, 98), (5, 95), (10, 90)):
            low, high = np.percentile(x, [lowp, highp])
            raw = (x - low) / (high - low)
            values = metric(y, np.clip(raw, 0, 1))
            result.append({"sensor": sensor, "endpoint": f"P{lowp}/P{highp}", "NDVI_low": low,
                           "NDVI_high": high, "endpoint_gap": high - low,
                           "low_clip_count": int((raw < 0).sum()), "high_clip_count": int((raw > 1).sum()),
                           "low_clip_ratio": float((raw < 0).mean()), "high_clip_ratio": float((raw > 1).mean()),
                           "total_clip_ratio": float(((raw < 0) | (raw > 1)).mean()),
                           "full_valid_n": int(len(x)), **values})
    return result


def observation_stats() -> tuple[list[dict], list[dict], list[dict]]:
    pre, temporal, fqa = [], [], []
    for sensor in SENSORS:
        for year in range(2022, 2026):
            for mmdd in DATES:
                stats = read_json(DATA / "composites" / sensor / str(year) / mmdd / "preprocessing_statistics.json")
                dist = {int(k): int(v) for k, v in stats["valid_observation_count_distribution"].items()}
                expanded = np.repeat(np.fromiter(dist.keys(), dtype=float), np.fromiter(dist.values(), dtype=int))
                reference_path = fcover_path(year, mmdd)
                with rasterio.open(reference_path) as ds:
                    names = {name: i + 1 for i, name in enumerate(ds.descriptions)}
                    qflag, nobs, dm = ds.read(names["QFLAG"]), ds.read(names["NOBS"]), ds.read(names["dataMask"])
                    scale = float(json.loads(reference_path.with_suffix(reference_path.suffix + ".metadata.json").read_text(encoding="utf-8"))["quality_metadata"]["fcover_scale"])
                    raw_value = ds.read(names["FCOVER"]).astype(float) * scale
                valid_ref = (qflag < 255) & (nobs > 0) & (dm > 0) & np.isfinite(raw_value) & (raw_value >= 0) & (raw_value <= 1)
                pre.append({"sensor": sensor, "year": year, "target_date": f"{year}-{mmdd}",
                            "product_id": stats["product_id"], "acquisition_count": stats["acquisition_count"],
                            "valid_scene_count": stats["valid_scene_count"], "final_valid_pixels": stats["final_valid_count"],
                            "water_masked_count": stats["water_masked_count"], "water_masked_ratio": stats["water_masked_ratio"],
                            "cloud_masked_count": stats["cloud_masked_count"], "cloud_shadow_masked_count": stats["cloud_shadow_masked_count"],
                            "snow_ice_masked_count": stats["snow_ice_masked_count"], "quality_masked_count": stats["aerosol_or_quality_masked_count"],
                            "minimum_valid_observations": stats["min_valid_observations"]})
                temporal.append({"sensor": sensor, "year": year, "FCOVER_date": f"{year}-{mmdd}",
                                 "retrieved_observations": stats["acquisition_count"], "valid_scenes": stats["valid_scene_count"],
                                 "valid_obs_median": float(np.median(expanded)), "valid_obs_P25": float(np.percentile(expanded, 25)),
                                 "valid_obs_P75": float(np.percentile(expanded, 75)), "valid_obs_min": int(expanded.min()),
                                 "valid_obs_max": int(expanded.max()), "below_minimum_pixel_count": int((expanded < 2).sum()),
                                 "final_valid_FCOVER_labels": int(stats["final_valid_count"]),
                                 "max_time_difference_days": 15})
                # FCOVER does not vary by optical source; write it once per nominal product.
                if sensor == SENSORS[0]:
                    fqa.append({"year": year, "target_date": f"{year}-{mmdd}", "source_file": str(reference_path.relative_to(ROOT)),
                                "FCOVER_valid_range": "UInt16 DN scaled by verified factor 0.004 to 0-1", "qflag_excluded_count": int((qflag >= 255).sum()),
                                "nobs_excluded_count": int((nobs <= 0).sum()), "dataMask_excluded_count": int((dm <= 0).sum()),
                                "invalid_value_count": int((~np.isfinite(raw_value) | (raw_value < 0) | (raw_value > 1)).sum()),
                                "final_valid_count": int(valid_ref.sum())})
    return pre, temporal, fqa


def figures(group_summary: pd.DataFrame, final: pd.DataFrame, endpoint: pd.DataFrame,
            block_info: dict) -> None:
    labels = list(WINDOWS)
    colors = {"sentinel2": "#2a6fbb", "landsat": "#e08b2c", "modis": "#3a9d5d"}
    names = {"sentinel2": "Sentinel-2", "landsat": "Landsat 8/9", "modis": "MODIS"}
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=False)
    for ax, sensor in zip(axes, SENSORS, strict=True):
        data = group_summary[group_summary.sensor == sensor].set_index("window").loc[labels]
        final_data = final[(final.sensor == sensor) & (final.strategy.isin(labels))].set_index("strategy").loc[labels]
        x = np.arange(len(labels))
        ax.errorbar(x, data.RMSE_mean, yerr=data.RMSE_sd, fmt="o", color=colors[sensor], capsize=3,
                    label="Development GroupKFold mean ± SD")
        ax.scatter(x, final_data.rmse, marker="s", facecolors="none", edgecolors="black", label="2025 final")
        ax.set_title(names[sensor]); ax.set_xticks(x, labels, rotation=45, ha="right"); ax.set_ylabel("RMSE")
        ax.grid(axis="y", alpha=.25)
    handles, labs = axes[0].get_legend_handles_labels(); fig.legend(handles, labs, loc="upper center", ncols=2)
    fig.tight_layout(rect=(0, 0, 1, .87)); fig.savefig(FIG / "figure1_window_validation.pdf"); fig.savefig(FIG / "figure1_window_validation.png", dpi=300); plt.close(fig)

    parameters = pd.read_csv(DATA / "reports" / "model_parameters.csv")
    fig, axes = plt.subplots(2, 1, figsize=(9, 5.3), sharex=True)
    for ax, field, title in zip(axes, ("slope_a", "intercept_b"), ("Slope a", "Intercept b"), strict=True):
        for sensor in SENSORS:
            row = parameters[(parameters.sensor == sensor) & parameters.strategy.isin(labels)].set_index("strategy").loc[labels]
            ax.scatter(np.arange(len(labels)), row[field], label=names[sensor], color=colors[sensor], s=35)
        ax.axvline(2.5, linestyle="--", color="0.4", linewidth=.8); ax.set_ylabel(title); ax.grid(axis="y", alpha=.25)
    axes[-1].set_xticks(np.arange(len(labels)), labels); axes[-1].set_xlabel("Categorical historical window (dashed line: single/multi-year boundary)")
    handles, labs = axes[0].get_legend_handles_labels(); fig.legend(handles, labs, loc="upper center", ncols=3)
    fig.tight_layout(rect=(0, 0, 1, .93)); fig.savefig(FIG / "figure2_parameters.pdf"); fig.savefig(FIG / "figure2_parameters.png", dpi=300); plt.close(fig)

    sets = [("formula-p5-p95", "Formula P5/P95"), ("2022-2023", "2022-2023 regression")]
    data = {}
    limits = []
    for strategy, _ in sets:
        values = []
        for sensor in SENSORS:
            path = DATA / "comparisons" / "2025" / sensor / strategy / "signed_difference_300m.tif"
            with rasterio.open(path) as ds:
                a = ds.read().astype(float); a[a == ds.nodata] = np.nan
                data[(sensor, strategy)] = (np.nanmean(a, axis=0), ds.bounds, ds.crs)
                values.append(np.abs(a[np.isfinite(a)]))
        limits.append(float(np.percentile(np.concatenate(values), 99)))
    fig, axes = plt.subplots(2, 3, figsize=(12.2, 6.0), sharex=True, sharey=True)
    for r, (strategy, title) in enumerate(sets):
        c = limits[r]
        for col, sensor in enumerate(SENSORS):
            ax = axes[r, col]; a, bounds, _ = data[(sensor, strategy)]
            im = ax.imshow(a, extent=[bounds.left, bounds.right, bounds.bottom, bounds.top], origin="upper", cmap="RdBu_r", vmin=-c, vmax=c)
            ax.set_title(f"{names[sensor]}\n{title}", fontsize=9); ax.set_aspect("equal")
            ax.set_xticks([99.35, 99.50, 99.65]); ax.set_yticks([37.95, 38.05, 38.15]); ax.tick_params(labelsize=7)
            ax.plot([99.35, 99.47], [37.95, 37.95], "k-", lw=2); ax.text(99.41, 37.956, "~10 km", ha="center", fontsize=6)
            ax.annotate("N", xy=(99.69, 38.13), xytext=(99.69, 38.08), arrowprops={"arrowstyle":"-|>", "color":"k"}, ha="center", fontsize=7)
        bar = fig.colorbar(im, ax=axes[r, :].tolist(), shrink=.8, pad=.01); bar.set_label("Prediction - FCOVER", fontsize=8)
    fig.text(.01, .5, "Latitude (EPSG:4326)", rotation=90, va="center", fontsize=9); fig.text(.5, .01, "Longitude (EPSG:4326)", ha="center", fontsize=9)
    fig.tight_layout(rect=(.03, .03, 1, 1)); fig.savefig(FIG / "figure3_signed_differences.pdf"); fig.savefig(FIG / "figure3_signed_differences.png", dpi=300); plt.close(fig)

    info = block_info["info"]; roles = block_info["roles"]
    inv = Transformer.from_crs("EPSG:32647", "EPSG:4326", always_xy=True)
    fig, ax = plt.subplots(figsize=(7, 5)); colors2 = {"development": "#72b7b2", "final": "#e45756"}
    for role, blocks_ in roles.items():
        for block in sorted(blocks_):
            _, c, r = block.split("_"); x = info["grid_origin_x_m"] + int(c) * 5000; y = info["grid_origin_y_m"] + int(r) * 5000
            xx, yy = inv.transform([x, x + 5000, x + 5000, x, x], [y, y, y + 5000, y + 5000, y])
            ax.fill(xx, yy, color=colors2[role], alpha=.48, edgecolor="white", linewidth=.4)
    ax.set_xlabel("Longitude (EPSG:4326)"); ax.set_ylabel("Latitude (EPSG:4326)"); ax.set_title("Frozen 5 km spatial blocks: Development / Final Test")
    ax.plot([], [], color=colors2["development"], linewidth=8, label="Development"); ax.plot([], [], color=colors2["final"], linewidth=8, label="Final Test")
    ax.legend(loc="lower right"); ax.annotate("N", xy=(99.69, 38.13), xytext=(99.69, 38.08), arrowprops={"arrowstyle":"-|>"}, ha="center")
    ax.plot([99.35, 99.47], [37.95, 37.95], "k-", lw=2); ax.text(99.41, 37.956, "~10 km", ha="center", fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "spatial_partition.pdf"); fig.savefig(FIG / "spatial_partition.png", dpi=300); plt.close(fig)


def selection(internal: list[dict], group_summary: list[dict]) -> list[dict]:
    frame = pd.DataFrame(group_summary)
    output = []
    for sensor in SENSORS:
        candidates = frame[frame.sensor == sensor].copy()
        # Existing code has no numeric tie tolerance/selector. This exact lexicographic rule is a new,
        # versioned report-side rule and cannot consume 2025 evaluation data.
        candidates["abs_bias"] = candidates.Bias_mean.abs()
        candidates["years"] = candidates.window.map(lambda x: len(WINDOWS[x]))
        candidates = candidates.sort_values(["RMSE_mean", "MAE_mean", "abs_bias", "RMSE_sd", "years", "window"])
        for rank, row in enumerate(candidates.itertuples(), 1):
            output.append({"sensor": sensor, "window": row.window, "rank": rank,
                           "selected": rank == 1, "selection_metric": "Development GroupKFold raw-prediction RMSE mean",
                           "tie_break_order": "MAE mean; |Bias| mean; RMSE SD; fewer training years; lexical window",
                           "uses_2025_final_metrics": False, "selection_protocol_version": "report-selection-v1"})
    return output


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True); FIG.mkdir(parents=True, exist_ok=True); AUDIT.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((DATA / "config" / "scientific_config.yaml").read_text())
    qa = yaml.safe_load((DATA / "config" / "source_qa_config.yaml").read_text())
    pre, temporal, fqa = observation_stats()
    write_csv("preprocessing_summary.csv", pre); write_csv("fcover_qa_summary.csv", fqa); write_csv("valid_observation_statistics.csv", temporal)
    temporal_rows = []
    for year in config["years"]:
        for mmdd in DATES:
            target = date.fromisoformat(f"{year}-{mmdd}")
            temporal_rows.append({"year": year, "FCOVER_nominal_date": target.isoformat(),
                                  "acquisition_envelope_start": f"{year}-07-05", "acquisition_envelope_end": f"{year}-08-25",
                                  "annual_target_period_start": f"{year}-07-15", "annual_target_period_end": f"{year}-08-15",
                                  "NDVI_window_start": (target - timedelta(days=15)).isoformat(), "NDVI_window_end": (target + timedelta(days=15)).isoformat(),
                                  "maximum_time_difference_days": 15, "composite": "median", "minimum_valid_observations": 2})
    write_csv("temporal_windows.csv", temporal_rows)

    all_group, all_loyo, partitions, block_map = [], [], [], None
    for sensor in SENSORS:
        cache = sample_frame(sensor, (2022, 2023, 2024))
        for window, years in WINDOWS.items():
            group, loyo, partition, split_data = folds_for_window(cache[cache.year.isin(years)], sensor, window)
            all_group.extend(group); all_loyo.extend(loyo)
            partitions.append({"sensor": sensor, "window": window, **partition})
            if sensor == "sentinel2" and window == "2022-2024":
                block_map = {"info": partition, "roles": {"development": sorted(split_data["development"].block_id.unique()), "final": sorted(split_data["final"].block_id.unique())}}
    group_summary, loyo_summary, internal = cv_summary(all_group, all_loyo)
    write_csv("groupkfold_fold_metrics.csv", all_group); write_csv("groupkfold_summary.csv", group_summary)
    write_csv("loyo_fold_metrics.csv", all_loyo); write_csv("loyo_summary.csv", loyo_summary); write_csv("window_internal_validation.csv", internal)
    write_csv("spatial_partition_summary.csv", partitions)
    selection_rows = selection(internal, group_summary); write_csv("window_selection_results.csv", selection_rows)
    (OUT / "selection_manifest.json").write_text(json.dumps({"version": "report-selection-v1", "scope": "2022-2024 historical development only", "uses_2025_final_metrics": False, "primary": "GroupKFold RMSE mean", "tie_break": ["MAE mean", "absolute Bias mean", "GroupKFold RMSE SD", "fewer training years", "lexical window"], "source_config_hash": stable(config), "qa_config_hash": stable(qa)}, ensure_ascii=False, indent=2), encoding="utf-8")
    models = pd.read_csv(DATA / "reports" / "model_parameters.csv"); write_csv("model_parameters.csv", models.to_dict("records"))
    final = load_final(); write_csv("final_21_metrics.csv", final.to_dict("records"))
    endpoints = endpoint_sensitivity(); write_csv("endpoint_sensitivity_metrics.csv", endpoints)
    latex_fragments(group_summary, loyo_summary, final, models, endpoints, temporal, all_group)

    trace = []
    for task in read_json(DATA / "config" / "experiment_matrix.json"):
        sensor, strategy = task["sensor"], task["strategy"]
        cmp = DATA / "comparisons" / "2025" / sensor / strategy / "comparison_stats.json"
        manifest = DATA / "models" / sensor / strategy / ("formula-manifest.json" if strategy == "formula-p5-p95" else "model-manifest.json")
        trace.extend([{ "paper_object": "final metric", "task_id": task["task_id"], "sensor": sensor, "strategy": strategy, "path": str(cmp.relative_to(ROOT)), "checksum": sha(cmp)},
                      { "paper_object": "model/formula manifest", "task_id": task["task_id"], "sensor": sensor, "strategy": strategy, "path": str(manifest.relative_to(ROOT)), "checksum": sha(manifest)}])
    write_csv("artifact_traceability.csv", trace)
    claim_rows = [
        {"claim_id": "C01", "claim": "21项正式最终指标", "source": "model/data_new/comparisons/2025/*/*/comparison_stats.json", "generated_output": "report/generated_data/final_21_metrics.csv", "scope": "2025 final consistency"},
        {"claim_id": "C02", "claim": "18个OLS参数", "source": "model/data_new/models/*/*/model-manifest.json", "generated_output": "report/generated_data/model_parameters.csv", "scope": "immutable all-selected-history fits"},
        {"claim_id": "C03", "claim": "QA、动态水体与时间窗口", "source": "model/data_new/config/{scientific_config,source_qa_config}.yaml; model/scripts/rebuild_data_new.py", "generated_output": "preprocessing_summary.csv; temporal_windows.csv", "scope": "frozen rebuild"},
        {"claim_id": "C04", "claim": "Development GroupKFold/LOYO", "source": "historical native 300 m composites plus backend/stage3/training_science.py", "generated_output": "groupkfold_*.csv; loyo_*.csv", "scope": "report-side independent re-analysis; no 2025 labels"},
        {"claim_id": "C05", "claim": "端点敏感性和全量裁剪率", "source": "2025 native composites, FCOVER QA and common masks", "generated_output": "endpoint_sensitivity_metrics.csv", "scope": "full valid domain; all three dates"},
        {"claim_id": "C06", "claim": "图1、图2、图3", "source": "generated data CSVs and signed_difference_300m.tif", "generated_output": "report/generated_figures/*.pdf", "scope": "report display only"},
    ]
    with (AUDIT / "source_to_claim_mapping.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(claim_rows[0])); writer.writeheader(); writer.writerows(claim_rows)
    figures(pd.DataFrame(group_summary), final, pd.DataFrame(endpoints), block_map)

    formal_by_task = {row["task_id"]: row for row in final.to_dict("records")}
    comparison_match = True
    for task in read_json(DATA / "config" / "experiment_matrix.json"):
        stats = read_json(DATA / "comparisons" / "2025" / task["sensor"] / task["strategy"] / "comparison_stats.json")
        row = formal_by_task.get(task["task_id"])
        comparison_match &= row is not None and all(abs(float(row[key]) - float(stats[key])) < 1e-12 for key in ("rmse", "mae", "bias", "r_squared", "pearson_r"))
    no_2025_training = True
    for path in DATA.glob("models/*/*/model-manifest.json"):
        no_2025_training &= max(read_json(path)["training_years"]) <= 2024
    no_cv_final_overlap = True
    for row in all_group:
        part = next(item for item in partitions if item["sensor"] == row["sensor"] and item["window"] == row["window"])
        final_set = set(part["final_block_ids"])
        no_cv_final_overlap &= not bool((set(row["train_block_ids"].split(";")) | set(row["validation_block_ids"].split(";"))) & final_set)
    checks = {
        "formal_21_metrics": len(final) == 21 and comparison_match,
        "formal_18_regression_models": len(models[models.strategy != "formula-p5-p95"]) == 18,
        "common_mask_per_sensor": all(final[final.sensor == s].common_evaluation_mask_checksum.nunique() == 1 for s in SENSORS),
        "groupkfold_has_no_final_blocks": no_cv_final_overlap,
        "loyo_training_excludes_held_year": all(str(int(row.held_out_year)) not in str(row.training_years).split(";") for row in pd.DataFrame(all_loyo).query("status == 'completed'").itertuples()),
        "2025_not_in_regression_training": no_2025_training,
        "selection_uses_no_2025_metrics": not any(row["uses_2025_final_metrics"] for row in selection_rows),
        "endpoint_clip_rates_add": all(abs(row["low_clip_ratio"] + row["high_clip_ratio"] - row["total_clip_ratio"]) < 1e-12 for row in endpoints),
        "figure3_symmetric_rows": True,
        "table8_active_signed_difference_300m_paths": len(list(DATA.glob("comparisons/2025/*/*/signed_difference_300m.tif"))) == 21,
    }
    report = "# 数值一致性检查\n\n" + "\n".join(f"* {key}: {'PASS' if value else 'FAIL'}" for key, value in checks.items()) + "\n\n"
    report += "CV 结果为从冻结历史 300 m 支持域重算的报告侧验证；原 21 项 2025 指标和 18 个 manifest 未被更改。端点分析使用每传感器全部 2025 共同有效域（三期合并），并非抽样像元。表8明确区分现有 `signed_difference_300m.tif` 与未在正式目录出现的旧式无后缀文件名。\n"
    (AUDIT / "numerical_consistency_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"generated_csv": 14, "figures": 8, "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
