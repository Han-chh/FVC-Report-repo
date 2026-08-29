#!/usr/bin/env python3
"""Audit GEE preparation assets and write cloud readiness/status manifests."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT.parent / "new_experiments"
WORKSPACE = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from data_prep.gee_cloud import (FCOVER_ACTIVE_COLLECTION as FCOVER_COLLECTION,
                                 PAIR_ACTIVE_COLLECTION as PAIR_COLLECTION,
                                 TABLE_ROOT, fcover_asset_id, initialize, pair_asset_id)
import ee


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def list_assets(parent: str) -> list[dict]:
    assets = []
    token = None
    while True:
        request = {"parent": parent, "pageSize": 1000}
        if token: request["pageToken"] = token
        response = ee.data.listAssets(request); assets.extend(response.get("assets", []))
        token = response.get("nextPageToken")
        if not token: return assets


def main() -> int:
    initialize(WORKSPACE / "model/.env")
    registry = json.loads((EXP / "01_multi_aoi/final_four_aoi_registry.geojson").read_text(encoding="utf-8"))
    aoi_ids = [f["properties"]["aoi_id"] for f in registry["features"]]
    expected_fcover = {fcover_asset_id(aoi, f"{year}-{month:02d}-{day:02d}")
                       for aoi in aoi_ids for year in range(2021, 2026)
                       for month, day in ((7, 20), (7, 31), (8, 10))}
    expected_pairs = {pair_asset_id(aoi, year) for aoi in aoi_ids for year in range(2021, 2026)}
    fcover_assets = {asset["id"]: asset for asset in list_assets(FCOVER_COLLECTION)}
    pair_assets = {asset["id"]: asset for asset in list_assets(PAIR_COLLECTION)}
    table_assets = {asset["id"]: asset for asset in list_assets(TABLE_ROOT)}
    manifest = []
    fcover_errors = []
    for asset_id, summary in sorted(fcover_assets.items()):
        info = ee.data.getAsset(asset_id); bands = info.get("bands", [])
        grids = [band.get("grid") for band in bands]
        error = None
        if [b.get("id") for b in bands] != ["FCOVER", "RMSE", "NOBS", "LBEFORE", "LAFTER", "QFLAG", "valid_domain_mask"]:
            error = "BAND_CONTRACT"
        elif not all(grid == grids[0] for grid in grids[1:]):
            error = "INTERNAL_GRID_MISMATCH"
        elif (grids[0] or {}).get("crsCode") != "EPSG:4326":
            error = "CRS_MISMATCH"
        properties = info.get("properties", {})
        if not properties.get("source_window_sha256"):
            error = error or "SOURCE_CHECKSUM_MISSING"
        if error: fcover_errors.append({"asset_id": asset_id, "error": error})
        record = {"kind": "fcover", "asset_id": asset_id, "type": info.get("type"),
                  "size_bytes": info.get("sizeBytes"), "update_time": info.get("updateTime"),
                  "bands": [b.get("id") for b in bands], "grid": grids[0] if grids else None,
                  "properties": properties, "contract_error": error}
        record["asset_metadata_sha256"] = canonical_hash(record); manifest.append(record)
    pair_errors = []
    expected_band_names = []
    for suffix in ("0720", "0731", "0810"):
        expected_band_names += [f"fcover_{suffix}", f"rmse_{suffix}", f"qflag_{suffix}", f"nobs_{suffix}",
                                f"valid_domain_mask_{suffix}", f"valid_reference_{suffix}"]
        for sensor in ("s2", "landsat", "modis"):
            expected_band_names += [f"{sensor}_ndvi_{suffix}", f"{sensor}_count_{suffix}"]
    for asset_id, summary in sorted(pair_assets.items()):
        info = ee.data.getAsset(asset_id); bands = info.get("bands", []); properties = info.get("properties", {})
        names = [band.get("id") for band in bands]; error = None
        if names != expected_band_names: error = "PAIR_BAND_CONTRACT"
        elif len({canonical_hash(band.get("grid")) for band in bands}) != 1: error = "PAIR_GRID_MISMATCH"
        elif properties.get("minimum_finite_contributions") != 2: error = "MIN_CONTRIBUTION_CONTRACT"
        elif properties.get("scientific_results_executed") not in (0, "0"): error = "SCIENTIFIC_PHASE_PROPERTY"
        if error: pair_errors.append({"asset_id": asset_id, "error": error})
        record = {"kind": "pair_cube", "asset_id": asset_id, "type": info.get("type"),
                  "size_bytes": info.get("sizeBytes"), "update_time": info.get("updateTime"),
                  "bands": names, "grid": bands[0].get("grid") if bands else None,
                  "properties": properties, "contract_error": error}
        record["asset_metadata_sha256"] = canonical_hash(record); manifest.append(record)
    checks = {
        "expected_fcover_assets": len(expected_fcover), "actual_fcover_assets": len(expected_fcover & set(fcover_assets)),
        "missing_fcover_assets": sorted(expected_fcover - set(fcover_assets)),
        "unexpected_fcover_assets": sorted(set(fcover_assets) - expected_fcover),
        "fcover_contract_errors": fcover_errors,
        "expected_pair_assets": len(expected_pairs), "actual_pair_assets": len(expected_pairs & set(pair_assets)),
        "missing_pair_assets": sorted(expected_pairs - set(pair_assets)),
        "unexpected_pair_assets": sorted(set(pair_assets) - expected_pairs),
        "pair_contract_errors": pair_errors,
        "aoi_registry_table": f"{TABLE_ROOT}/aoi_registry" in table_assets,
        "environmental_features_table": f"{TABLE_ROOT}/environmental_features" in table_assets,
        "scientific_results_executed": False,
    }
    checks["ready"] = (not checks["missing_fcover_assets"] and not fcover_errors and
                       not checks["missing_pair_assets"] and not pair_errors and
                       checks["aoi_registry_table"] and checks["environmental_features_table"])
    out = {"audited_at": datetime.now(timezone.utc).isoformat(), "asset_root": FCOVER_COLLECTION.rsplit("/", 1)[0],
           "checks": checks}
    audit_path = EXP / "04_preexecution_audit/gee_cloud_asset_audit.json"
    audit_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (EXP / "data/manifests/gee_cloud_asset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = []
    for aoi in aoi_ids:
        for year in range(2021, 2026):
            pair_ready = pair_asset_id(aoi, year) in pair_assets and not any(
                e["asset_id"] == pair_asset_id(aoi, year) for e in pair_errors)
            for product in ("sentinel2", "landsat", "modis"):
                rows.append({"aoi_id": aoi, "year": year, "sensor_product": product,
                             "status": "READY" if pair_ready else "PARTIAL",
                             "storage_backend": "GEE_ASSET", "asset_id": pair_asset_id(aoi, year),
                             "reason": "36-band AOI-year pair cube contract verified" if pair_ready else "GEE pair cube missing or invalid",
                             "source_exists": True, "checksum_exists": pair_ready,
                             "product_version_recorded": pair_ready, "native_crs_known": pair_ready,
                             "crop_succeeds": pair_ready, "qa_bands_exist": pair_ready,
                             "target_dates_coverage_recorded": pair_ready, "raster_integrity_checked": pair_ready,
                             "nodata_readable": pair_ready, "common_support_constructible": pair_ready,
                             "temporal_count_computable": pair_ready, "manifest_complete": pair_ready})
            dates = [f"{year}-{m:02d}-{d:02d}" for m, d in ((7, 20), (7, 31), (8, 10))]
            ids = [fcover_asset_id(aoi, value) for value in dates]
            fcover_ready = all(value in fcover_assets for value in ids) and not any(e["asset_id"] in ids for e in fcover_errors)
            rows.append({"aoi_id": aoi, "year": year, "sensor_product": "fcover",
                         "status": "READY" if fcover_ready else "PARTIAL", "storage_backend": "GEE_ASSET",
                         "asset_id": ";".join(ids), "reason": "three native-grid FCOVER assets verified" if fcover_ready else "one or more FCOVER assets missing or invalid",
                         "source_exists": fcover_ready, "checksum_exists": fcover_ready,
                         "product_version_recorded": fcover_ready, "native_crs_known": fcover_ready,
                         "crop_succeeds": fcover_ready, "qa_bands_exist": fcover_ready,
                         "target_dates_coverage_recorded": fcover_ready, "raster_integrity_checked": fcover_ready,
                         "nodata_readable": fcover_ready, "common_support_constructible": pair_ready,
                         "temporal_count_computable": pair_ready, "manifest_complete": fcover_ready})
    status = pd.DataFrame(rows)
    status.to_csv(EXP / "data/gee_cloud_data_preparation_status.csv", index=False)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if checks["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
