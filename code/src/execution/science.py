"""Frozen OLS execution routines shared by the two runner entry points.

This module deliberately contains no gate bypass: callers must pass a gate
result with status PASS before any Earth Engine sampling or model fit occurs.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer

from common.blocks import block_id, reserve_blocks
from execution.contract import ROOT, processing_hash, registry_geometry_payload, sha256
from execution.identity import active_processing_hash, active_source_root
from metrics.block_metrics import by_block
from metrics.holm import holm_adjust
from metrics.paired_tests import paired_two_sided
from metrics.regression_metrics import regression_metrics
from models.ols import fit_ols, predict_clipped
from validation.leakage_audit import assert_chronology
from validation.loyo import folds_for_years


SENSORS = ("sentinel2", "landsat", "modis")
SENSOR_BAND_PREFIX = {"sentinel2": "s2", "landsat": "landsat", "modis": "modis"}
TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:32647", always_xy=True)


def sensor_band_prefix(sensor: str) -> str:
    try:
        return SENSOR_BAND_PREFIX[sensor]
    except KeyError as exc:
        raise RuntimeError(f"UNKNOWN_SENSOR_BAND_PREFIX:{sensor}") from exc


def expected_pair_band_names() -> list[str]:
    names: list[str] = []
    for suffix in ("0720", "0731", "0810"):
        names += [f"fcover_{suffix}", f"rmse_{suffix}", f"qflag_{suffix}",
                  f"nobs_{suffix}", f"valid_domain_mask_{suffix}",
                  f"valid_reference_{suffix}"]
        for prefix in ("s2", "landsat", "modis"):
            names += [f"{prefix}_ndvi_{suffix}", f"{prefix}_count_{suffix}"]
    return names


def paired_row_decision(values: dict[str, Any], sensor: str, suffix: str) -> tuple[str, dict[str, float] | None]:
    """Apply the frozen predicates to one sensor/date observation."""
    prefix = sensor_band_prefix(sensor)
    valid_reference = values.get(f"valid_reference_{suffix}")
    try:
        if float(valid_reference) != 1.0:
            return "invalid_reference", None
    except (TypeError, ValueError):
        return "invalid_reference", None
    fcover = values.get(f"fcover_{suffix}")
    try:
        fcover_value = float(fcover)
    except (TypeError, ValueError):
        return "invalid_fcover", None
    if not np.isfinite(fcover_value) or not 0.0 <= fcover_value <= 1.0:
        return "invalid_fcover", None
    ndvi = values.get(f"{prefix}_ndvi_{suffix}")
    try:
        ndvi_value = float(ndvi)
    except (TypeError, ValueError):
        return "invalid_ndvi", None
    if not np.isfinite(ndvi_value):
        return "invalid_ndvi", None
    count = values.get(f"{prefix}_count_{suffix}")
    try:
        count_value = float(count)
    except (TypeError, ValueError):
        return "invalid_count", None
    if not np.isfinite(count_value):
        return "invalid_count", None
    if count_value < 2:
        return "count_lt_2", None
    return "accepted", {"FCOVER": fcover_value, "NDVI": ndvi_value,
                         "contribution_count": int(count_value)}


def iter_feature_pages(collection: Any, fetch_page: Any, *, page_size: int = 5000):
    """Yield exact pages while rejecting repeated pagination tokens."""
    page_token = None
    seen_tokens: set[str] = set()
    page_number = 0
    while True:
        request = {"expression": collection, "pageSize": int(page_size)}
        if page_token:
            request["pageToken"] = page_token
        result = fetch_page(request)
        page_number += 1
        yield page_number, result.get("features", [])
        next_token = result.get("nextPageToken")
        if not next_token:
            break
        if next_token in seen_tokens:
            raise RuntimeError("REPEATED_PAGINATION_TOKEN")
        seen_tokens.add(next_token)
        page_token = next_token


def _workspace(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT.parents[2] / path


def _output(contract: dict[str, Any]) -> Path:
    return _workspace(contract["output_root"])


def _source_candidates(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = registry_geometry_payload(contract)
    return {row["aoi_id"]: row for row in rows}


def _provenance(contract: dict[str, Any], aoi: str, blocks: list[str] | None = None) -> dict[str, str]:
    root = active_source_root(contract)
    source_files = sorted(root.glob("*.csv"))
    source_hash = sha256({str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files})
    geometry = next(row for row in registry_geometry_payload(contract) if row["aoi_id"] == aoi)
    return {
        "processing_hash": active_processing_hash(contract),
        "source_manifest_hash": source_hash,
        "AOI_geometry_hash": sha256(geometry),
        "block_manifest_hash": sha256(sorted(blocks or [])),
        "code_version": processing_hash(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _pair_asset(contract: dict[str, Any], final_aoi: str, year: int) -> str:
    from data_prep.gee_cloud import pair_asset_id
    return pair_asset_id(final_aoi, year)


def _write_extraction_audit(contract: dict[str, Any], frame: pd.DataFrame,
                            stats: dict[tuple[str, str, int, str], Counter],
                            pages: list[dict[str, Any]], assets: list[dict[str, Any]],
                            destination: Path, audit_directory: Path) -> None:
    audit_directory.mkdir(parents=True, exist_ok=True)
    date_rows = []
    for (aoi, sensor, year, nominal_date), counter in sorted(stats.items()):
        row = {"aoi_id": aoi, "sensor": sensor, "year": year,
               "nominal_date": nominal_date, **counter}
        row["rejection_accounting_ok"] = (
            row.get("candidate_cells", 0) == row.get("final_valid_rows", 0) +
            sum(row.get(f"rejected_{reason}", 0) for reason in
                ("missing_geometry", "invalid_reference", "invalid_fcover",
                 "invalid_ndvi", "invalid_count", "count_lt_2")))
        date_rows.append(row)
    dates = pd.DataFrame(date_rows).fillna(0)
    dates.to_csv(audit_directory / "PAIRED_ROW_COMPLETENESS_BY_DATE.csv", index=False)
    rejection_columns = [column for column in dates if column.startswith("rejected_")]
    dates[["aoi_id", "sensor", "year", "nominal_date", "candidate_cells",
           *rejection_columns, "final_valid_rows", "rejection_accounting_ok"]].to_csv(
               audit_directory / "PAIRED_ROW_NULL_REJECTION_COUNTS.csv", index=False)

    asset_lookup = {(row["aoi_id"], int(row["year"])): row for row in assets}
    completeness = []
    for aoi in contract["final_aoi_ids"]:
        for sensor in SENSORS:
            for year in contract["years"]:
                subset = dates[(dates.aoi_id == aoi) & (dates.sensor == sensor) & (dates.year == int(year))]
                paired = frame[(frame.aoi_id == aoi) & (frame.sensor == sensor) & (frame.year == int(year))]
                missing_dates = int((subset.final_valid_rows == 0).sum()) if len(subset) else len(contract["nominal_dates"])
                source = asset_lookup[(aoi, int(year))]
                completeness.append({"aoi_id": aoi, "sensor": sensor, "year": int(year),
                                     "cube_asset_id": source["asset_id"],
                                     "source_scene_ids_sha256": source["source_scene_ids_sha256"],
                                     "candidate_grid_cells": int(subset.candidate_cells.max()) if len(subset) else 0,
                                     "candidate_cell_date_units": int(subset.candidate_cells.sum()) if len(subset) else 0,
                                     "reference_valid_cells": int(subset.reference_valid_cells.sum()) if len(subset) else 0,
                                     "fcover_valid_cells": int(subset.fcover_valid_cells.sum()) if len(subset) else 0,
                                     "ndvi_valid_cells": int(subset.ndvi_valid_cells.sum()) if len(subset) else 0,
                                     "count_valid_cells": int(subset.count_valid_cells.sum()) if len(subset) else 0,
                                     "final_valid_rows": len(paired),
                                     "unique_pixel_identities": paired.pixel_id.nunique(),
                                     "unique_blocks": paired.block_id.nunique(),
                                     "duplicate_rows": int(paired.duplicated(["nominal_date", "pixel_id"]).sum()),
                                     "missing_dates": missing_dates,
                                     "date_support_status": "COMPLETE" if missing_dates == 0 else "PARTIAL",
                                     "status": "PASS" if len(paired) else "FAIL"})
    complete = pd.DataFrame(completeness)
    complete.to_csv(audit_directory / "PAIRED_ROW_COMPLETENESS_BY_AOI_SENSOR_YEAR.csv", index=False)
    frame.groupby(["aoi_id", "sensor", "year", "block_id"], as_index=False).size().rename(
        columns={"size": "valid_rows"}).to_csv(audit_directory / "PAIRED_ROW_BLOCK_SUPPORT.csv", index=False)
    pd.DataFrame(pages).to_csv(audit_directory / "PAGINATION_INTEGRITY_AUDIT.csv", index=False)

    payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "status": "PASS" if (complete.status == "PASS").all() else "FAIL",
               "design_hash": contract["frozen_design_hash"],
               "processing_hash": active_processing_hash(contract),
               "destination": str(destination), "rows": len(frame),
               "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
               "expected_aoi_sensor_year_groups": 60,
               "passing_aoi_sensor_year_groups": int((complete.status == "PASS").sum()),
               "partial_nominal_date_groups": int((complete.date_support_status == "PARTIAL").sum()),
               "partial_nominal_date_note": "Date-level absence is reported but does not empty the registered AOI-sensor-year input; no rows are imputed.",
               "duplicate_observation_rows": int(frame.duplicated(
                   ["aoi_id", "sensor", "year", "nominal_date", "pixel_id"]).sum()),
               "scientific_models_run": False, "formal_metrics_computed": False,
               "assets": assets}
    (audit_directory / "PAIRED_ROW_EXTRACTION_MANIFEST.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def extract_paired_observations(contract: dict[str, Any], *, audit_directory: Path | None = None) -> pd.DataFrame:
    """Extract exact FCOVER-grid pair-cube cells from approved GEE assets."""
    from data_prep.gee_cloud import initialize
    import ee

    initialize(ROOT.parents[2] / "model/.env")
    rows: list[dict[str, Any]] = []
    stats: dict[tuple[str, str, int, str], Counter] = defaultdict(Counter)
    pages: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    pair_audit_path = ROOT.parents[2] / "report/publication/new_experiments/16_scientific_execution_readiness/02_final_pairs/PAIRED_CUBE_IMPACT_AUDIT.csv"
    pair_audit = {(row["aoi_id"], int(row["year"])): row for row in
                  csv.DictReader(pair_audit_path.open(encoding="utf-8"))}
    for final_aoi, feature in _source_candidates(contract).items():
        source = feature["source_candidate_id"] or final_aoi
        region = ee.Geometry(feature["geometry"])
        for year in contract["years"]:
            asset = _pair_asset(contract, final_aoi, int(year))
            image = ee.Image(asset)
            observed_bands = image.bandNames().getInfo()
            if observed_bands != expected_pair_band_names():
                raise RuntimeError(f"PAIR_BAND_SCHEMA_MISMATCH:{final_aoi}:{year}")
            source_record = pair_audit[(final_aoi, int(year))]
            assets.append({"aoi_id": final_aoi, "year": int(year), "asset_id": asset,
                           "band_count": len(observed_bands), "band_schema_status": "PASS",
                           "source_scene_ids_sha256": source_record["source_scene_ids_sha256"],
                           "grid_hash": source_record["grid_hash"]})
            collection = image.sample(region=region, geometries=True, tileScale=4, dropNulls=False)
            seen_asset_cells: set[str] = set()
            for page_number, features in iter_feature_pages(collection, ee.data.computeFeatures):
                page_duplicates = 0
                for item in features:
                    values = item.get("properties", {})
                    coordinates = item.get("geometry", {}).get("coordinates")
                    if not coordinates:
                        for nominal in contract["nominal_dates"]:
                            for sensor in SENSORS:
                                counter = stats[(final_aoi, sensor, int(year), f"{year}-{nominal}")]
                                counter["candidate_cells"] += 1
                                counter["rejected_missing_geometry"] += 1
                        continue
                    lon, lat = float(coordinates[0]), float(coordinates[1])
                    pixel_id = f"{lon:.12f},{lat:.12f}"
                    if pixel_id in seen_asset_cells:
                        page_duplicates += 1
                    seen_asset_cells.add(pixel_id)
                    x_m, y_m = TRANSFORMER.transform(lon, lat)
                    for nominal in contract["nominal_dates"]:
                        suffix = nominal.replace("-", "")
                        for sensor in SENSORS:
                            nominal_date = f"{year}-{nominal}"
                            counter = stats[(final_aoi, sensor, int(year), nominal_date)]
                            counter["candidate_cells"] += 1
                            reason, paired = paired_row_decision(values, sensor, suffix)
                            if reason != "invalid_reference":
                                counter["reference_valid_cells"] += 1
                            if reason not in ("invalid_reference", "invalid_fcover"):
                                counter["fcover_valid_cells"] += 1
                            if reason not in ("invalid_reference", "invalid_fcover", "invalid_ndvi"):
                                counter["ndvi_valid_cells"] += 1
                            if reason == "accepted":
                                counter["count_valid_cells"] += 1
                                counter["final_valid_rows"] += 1
                            else:
                                counter[f"rejected_{reason}"] += 1
                                continue
                            rows.append({"aoi_id": final_aoi, "source_candidate_id": source, "year": int(year),
                                         "nominal_date": nominal_date, "sensor": sensor, **paired,
                                         "pixel_id": pixel_id, "lon": lon, "lat": lat,
                                         "x_m": x_m, "y_m": y_m,
                                         "block_id": f"{final_aoi}_{block_id(x_m, y_m, origin=tuple(contract['methodology']['spatial_blocks']['origin_xy_m']), size_m=float(contract['methodology']['spatial_blocks']['size_m']))}"})
                pages.append({"aoi_id": final_aoi, "year": int(year), "asset_id": asset,
                              "page_number": page_number, "feature_count": len(features),
                              "duplicate_pixel_identities": page_duplicates,
                              "status": "PASS" if page_duplicates == 0 else "FAIL"})
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("NO_PAIRED_OBSERVATIONS_EXTRACTED")
    duplicate_rows = frame.duplicated(["aoi_id", "sensor", "year", "nominal_date", "pixel_id"])
    if duplicate_rows.any() or any(row["status"] != "PASS" for row in pages):
        raise RuntimeError(f"DUPLICATE_PAIRED_OBSERVATIONS:{int(duplicate_rows.sum())}")
    destination = _output(contract) / "raw_machine_outputs/paired_observations.csv.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False, compression="gzip")
    if audit_directory is not None:
        _write_extraction_audit(contract, frame, stats, pages, assets, destination, audit_directory)
    return frame


def load_or_extract_pairs(contract: dict[str, Any]) -> pd.DataFrame:
    path = _output(contract) / "raw_machine_outputs/paired_observations.csv.gz"
    if path.exists():
        return pd.read_csv(path)
    return extract_paired_observations(contract)


def _complete_history_blocks(rows: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    available = [set(rows.loc[rows.year == year, "block_id"]) for year in years]
    common = set.intersection(*available) if available else set()
    if not common:
        raise RuntimeError("NO_COMPLETE_HISTORICAL_BLOCKS")
    return rows[rows.block_id.isin(common)].copy()


def _roles(rows: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    reserve = reserve_blocks(rows.block_id, seed=int(contract["methodology"]["historical_partition"]["seed"]), fraction=float(contract["methodology"]["historical_partition"]["reserve_fraction"]))
    result = rows.copy(); result["spatial_role"] = np.where(result.block_id.isin(reserve), "reserve", "development")
    if (result.spatial_role == "development").sum() == 0 or (result.spatial_role == "reserve").sum() == 0:
        raise RuntimeError("INVALID_DEVELOPMENT_RESERVE_PARTITION")
    return result


def _metrics_with_blocks(rows: pd.DataFrame, prediction: np.ndarray) -> tuple[dict[str, Any], pd.DataFrame]:
    scored = rows[["block_id"]].copy(); scored["reference"] = rows.FCOVER.to_numpy(float); scored["prediction"] = prediction
    metrics = regression_metrics(scored.reference, scored.prediction)
    blocks = by_block(scored)
    return metrics, blocks


def _fit_score(train: pd.DataFrame, test: pd.DataFrame) -> tuple[Any, dict[str, Any], pd.DataFrame]:
    model = fit_ols(train.NDVI, train.FCOVER)
    metrics, blocks = _metrics_with_blocks(test, predict_clipped(model, test.NDVI))
    return model, metrics, blocks


def _base_identity(contract: dict[str, Any], experiment: str, aoi: str, sensor: str, train_years: list[int], target: int | str, blocks: list[str]) -> dict[str, Any]:
    stamp = _provenance(contract, aoi, blocks)
    token = sha256({"experiment": experiment, "aoi": aoi, "sensor": sensor, "train_years": train_years, "target": target, "processing_hash": stamp["processing_hash"], "source_manifest_hash": stamp["source_manifest_hash"]})[:20]
    return {"execution_id": f"{experiment}-{token}", "experiment": experiment, "AOI": aoi, "sensor": sensor,
            "train_years": ";".join(map(str, train_years)), "target_year": target, **stamp}


def _groupkfold(rows: pd.DataFrame, identity: dict[str, Any]) -> list[dict[str, Any]]:
    from sklearn.model_selection import GroupKFold
    development = rows[rows.spatial_role == "development"]
    groups = development.block_id.unique()
    if len(groups) < 5:
        raise RuntimeError("GROUPKFOLD_REQUIRES_FIVE_DEVELOPMENT_BLOCKS")
    output = []
    for fold, (train_index, test_index) in enumerate(GroupKFold(n_splits=5).split(development, groups=development.block_id), 1):
        train, test = development.iloc[train_index], development.iloc[test_index]
        _, metrics, _ = _fit_score(train, test)
        output.append({**identity, "fold": fold, "train_n": len(train), "test_n": len(test), "train_blocks": train.block_id.nunique(), "test_blocks": test.block_id.nunique(), **metrics})
    return output


def _loyo(rows: pd.DataFrame, identity: dict[str, Any], years: list[int]) -> list[dict[str, Any]]:
    plan = folds_for_years(years)
    if plan["status"] == "NOT_APPLICABLE":
        return [{**identity, "status": "NOT_APPLICABLE", "held_out_year": "NA", "train_n": "NA", "test_n": "NA", "RMSE": "NA", "MAE": "NA", "Bias": "NA", "R2": "NA", "Pearson_r": "NA"}]
    development = rows[rows.spatial_role == "development"]
    output = []
    for fold in plan["folds"]:
        train = development[development.year.isin(fold["train_years"])]
        test = development[development.year == fold["held_out_year"]]
        _, metrics, _ = _fit_score(train, test)
        output.append({**identity, "status": "COMPLETED", "held_out_year": fold["held_out_year"], "train_n": len(train), "test_n": len(test), **metrics})
    return output


def run_multi_aoi(contract: dict[str, Any]) -> dict[str, pd.DataFrame]:
    pairs = load_or_extract_pairs(contract)
    group_rows: list[dict[str, Any]] = []; loyo_rows: list[dict[str, Any]] = []; reserve_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []; coefficient_rows: list[dict[str, Any]] = []; block_rows: list[dict[str, Any]] = []
    for aoi in contract["final_aoi_ids"]:
        for sensor in SENSORS:
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["multi_aoi_historical_windows"]:
                years = [int(year) for year in window["train_years"]]
                historical = _complete_history_blocks(sensor_rows[sensor_rows.year.isin(years)], years)
                historical = _roles(historical, contract)
                identity = _base_identity(contract, "multi_aoi", aoi, sensor, years, 2025, sorted(historical.block_id.unique()))
                identity["window"] = window["id"]
                group_rows.extend(_groupkfold(historical, identity))
                loyo_rows.extend(_loyo(historical, identity, years))
                development = historical[historical.spatial_role == "development"]
                reserve = historical[historical.spatial_role == "reserve"]
                _, reserve_metric, _ = _fit_score(development, reserve)
                reserve_rows.append({**identity, "train_n": len(development), "test_n": len(reserve), "block_n": reserve.block_id.nunique(), **reserve_metric})
                model = fit_ols(historical.NDVI, historical.FCOVER)
                coefficient_rows.append({**identity, "slope": float(model.coef_[0]), "intercept": float(model.intercept_), "train_n": len(historical), "train_block_n": historical.block_id.nunique()})
                target = sensor_rows[sensor_rows.year == 2025].copy()
                if target.empty:
                    raise RuntimeError(f"MISSING_TARGET:multi_aoi:{aoi}:{sensor}:2025")
                metric, blocks = _metrics_with_blocks(target, predict_clipped(model, target.NDVI))
                target_rows.append({**identity, "n": len(target), "block_n": target.block_id.nunique(), **metric})
                for _, row in blocks.iterrows():
                    block_rows.append({**identity, "target_year": 2025, "block_id": row.block_id, "block_rmse": row.RMSE, "block_mae": row.MAE, "block_bias": row.Bias, "block_n": row.n})
    frames = {
        "MULTI_AOI_GROUPKFOLD": pd.DataFrame(group_rows), "MULTI_AOI_LOYO": pd.DataFrame(loyo_rows),
        "MULTI_AOI_RESERVE": pd.DataFrame(reserve_rows), "MULTI_AOI_2025_METRICS": pd.DataFrame(target_rows),
        "MULTI_AOI_BLOCK_METRICS": pd.DataFrame(block_rows), "MULTI_AOI_MODEL_COEFFICIENTS": pd.DataFrame(coefficient_rows),
    }
    metrics = pd.concat([frames["MULTI_AOI_2025_METRICS"]], ignore_index=True)
    frames["MULTI_AOI_MODEL_METRICS"] = metrics
    frames["MULTI_AOI_PAIRED_TESTS"] = pd.DataFrame([{ "status": contract["multi_aoi_statistics"]["status"], "detail": "No additional Multi-AOI inferential family is frozen." }])
    frames["MULTI_AOI_RESULT_OVERVIEW"] = metrics.merge(frames["MULTI_AOI_MODEL_COEFFICIENTS"][["AOI", "sensor", "window", "slope", "intercept", "train_n"]], on=["AOI", "sensor", "window"], suffixes=("", "_coef"))
    _write_frames(contract, "02_multi_aoi_results", frames)
    return frames


def run_rolling_origin(contract: dict[str, Any]) -> dict[str, pd.DataFrame]:
    pairs = load_or_extract_pairs(contract)
    metric_rows: list[dict[str, Any]] = []; coefficient_rows: list[dict[str, Any]] = []; block_rows: list[dict[str, Any]] = []
    for aoi in contract["final_aoi_ids"]:
        for sensor in SENSORS:
            sensor_rows = pairs[(pairs.aoi_id == aoi) & (pairs.sensor == sensor)]
            for window in contract["rolling_origin"]["primary"]:
                years, target_year = [int(year) for year in window["history_years"]], int(window["target_year"])
                assert_chronology(years, target_year)
                # The frozen protocol's complete-block rule applies to every
                # multi-year historical fit.  Applying it here keeps the 2025
                # H1/H2/H3 rolling fits identical to their nominally matching
                # Multi-AOI histories, rather than allowing intermittently
                # observed blocks to change the calibration sample.
                train = _complete_history_blocks(
                    sensor_rows[sensor_rows.year.isin(years)], years
                )
                target = sensor_rows[sensor_rows.year == target_year]
                if train.empty or target.empty:
                    raise RuntimeError(f"MISSING_ROLLING_INPUT:{aoi}:{sensor}:{window['id']}")
                identity = _base_identity(contract, "rolling_origin", aoi, sensor, years, target_year, sorted(train.block_id.unique()))
                identity.update({"rolling_id": window["id"], "history_length": int(window["history_length"])})
                model, metric, blocks = _fit_score(train, target)
                coefficient_rows.append({**identity, "slope": float(model.coef_[0]), "intercept": float(model.intercept_), "train_n": len(train), "train_block_n": train.block_id.nunique()})
                metric_rows.append({**identity, "target_n": len(target), "target_block_n": target.block_id.nunique(), **metric})
                for _, row in blocks.iterrows():
                    block_rows.append({**identity, "block_id": row.block_id, "block_rmse": row.RMSE, "block_mae": row.MAE, "block_bias": row.Bias, "block_n": row.n})
    metrics = pd.DataFrame(metric_rows); blocks = pd.DataFrame(block_rows)
    metrics["history_length_rank_by_global_RMSE"] = metrics.groupby(["AOI", "sensor", "target_year"])["RMSE"].rank(method="min")
    tests = _rolling_tests(contract, blocks)
    frames = {"ROLLING_ORIGIN_METRICS": metrics, "ROLLING_ORIGIN_BLOCK_METRICS": blocks,
              "ROLLING_ORIGIN_COEFFICIENTS": pd.DataFrame(coefficient_rows), "ROLLING_ORIGIN_PAIRED_TESTS": tests,
              "ROLLING_ORIGIN_RESULT_OVERVIEW": metrics, "ROLLING_ORIGIN_REPLICATION_SUMMARY": _replication(metrics)}
    _write_frames(contract, "03_rolling_origin_results", frames)
    return frames


def _rolling_tests(contract: dict[str, Any], blocks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in blocks.groupby(["AOI", "sensor", "target_year"]):
        pending = []
        for left, right in contract["rolling_origin"]["contrasts"]:
            a = group[group.history_length == left][["block_id", "block_rmse"]].rename(columns={"block_rmse": "left"})
            b = group[group.history_length == right][["block_id", "block_rmse"]].rename(columns={"block_rmse": "right"})
            paired = a.merge(b, on="block_id")
            if paired.empty:
                raise RuntimeError(f"NO_COMMON_BLOCKS_FOR_PAIRED_TEST:{keys}:{left}:{right}")
            result = paired_two_sided(paired.left, paired.right)
            pending.append({"AOI": keys[0], "sensor": keys[1], "target_year": keys[2], "contrast": f"{left}y_vs_{right}y", "history_left": left, "history_right": right, "paired_block_n": len(paired), "mean_difference_RMSE": float((paired.left - paired.right).mean()), **result})
        adjusted = holm_adjust([row["p"] for row in pending])
        for row, value in zip(pending, adjusted):
            row["Holm_adjusted_p"] = float(value); row["significant"] = bool(value < contract["rolling_origin"]["alpha"]); rows.append(row)
    return pd.DataFrame(rows)


def _replication(metrics: pd.DataFrame) -> pd.DataFrame:
    output = []
    for (sensor, target), group in metrics.groupby(["sensor", "target_year"]):
        best = group.loc[group.groupby("AOI").RMSE.idxmin()].history_length.value_counts().to_dict()
        patterns = group.pivot(index="AOI", columns="history_length", values="RMSE")
        monotonic = int(((patterns[1] >= patterns[2]) & (patterns[2] >= patterns[3])).sum())
        output.append({"sensor": sensor, "target_year": target, "AOIs_1y_best": int(best.get(1, 0)), "AOIs_2y_best": int(best.get(2, 0)), "AOIs_3y_best": int(best.get(3, 0)), "monotonic_decrease_count": monotonic, "non_monotonic_count": int(len(patterns) - monotonic)})
    return pd.DataFrame(output)


def _write_frames(contract: dict[str, Any], directory: str, frames: dict[str, pd.DataFrame]) -> None:
    root = _output(contract) / directory; root.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(root / f"{name}.csv", index=False)
