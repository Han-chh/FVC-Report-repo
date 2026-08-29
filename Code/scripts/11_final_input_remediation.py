#!/usr/bin/env python3
"""Produce FCOVER remediation evidence; never runs scientific models."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import numpy as np
import requests
import rasterio

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from data_prep.download import _fcover_assets, _fcover_grid, _fcover_item, _fcover_window, _read_fcover_asset
from data_prep.gee_cloud import initialize
from execution.contract import load_contract, registry_geometry_payload


OUT = WORKSPACE / "report/publication/new_experiments/11_final_input_remediation/01_fcover_provenance"
DATES = ("07-20", "08-10")
YEARS = (2021, 2023, 2025)


def _legacy_mask(asset_id: str, grid: dict) -> np.ndarray:
    """Read the old derived band on its declared grid, without pixel shifting."""
    import ee
    affine = grid["affineTransform"]
    transform = [affine["scaleX"], affine.get("shearX", 0), affine["translateX"],
                 affine.get("shearY", 0), affine["scaleY"], affine["translateY"]]
    dims = grid["dimensions"]
    image = ee.Image(asset_id).select("dataMask").unmask(0)
    url = image.getDownloadURL({"name": "legacy_valid_domain", "crs": grid["crsCode"],
                                "crs_transform": transform,
                                "dimensions": [dims["width"], dims["height"]], "format": "GEO_TIFF"})
    response = requests.get(url, timeout=180); response.raise_for_status()
    data = response.content
    if data[:2] == b"PK":
        archive = zipfile.ZipFile(io.BytesIO(data))
        name = next(name for name in archive.namelist() if name.lower().endswith((".tif", ".tiff")))
        data = archive.read(name)
    with rasterio.MemoryFile(data) as memory:
        with memory.open() as raster:
            return raster.read(1)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["AOI_ID", "year", "nominal_date", "status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def legacy_domain_parity() -> int:
    """Compare legacy derived `dataMask` to the corrected derived definition.

    This is intentionally a representative, deterministic input-domain audit,
    not a model calculation.  It reads each comparison on the exact declared
    FCOVER affine grid.
    """
    import ee
    initialize(WORKSPACE / "model/.env")
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    rows: list[dict] = []
    with httpx.Client(timeout=300) as client:
        for target in registry_geometry_payload(contract):
            source_id = target["source_candidate_id"] or target["aoi_id"]
            bounds = [float(value) for value in __import__("shapely.geometry", fromlist=["shape"]).shape(target["geometry"]).bounds]
            for year in YEARS:
                for date_part in DATES:
                    nominal = f"{year}-{date_part}"
                    legacy_id = f"projects/qinghai-internship-fvc-models/assets/fvc_report_data/fcover_native/{source_id.replace('-', '_')}_{nominal.replace('-', '')}"
                    info = ee.data.getAsset(legacy_id)
                    assets = _fcover_assets(_fcover_item(client, nominal))
                    transform, width, height, crs = _fcover_grid(_fcover_item(client, nominal), assets)
                    window = _fcover_window(bounds, transform, width, height)
                    source = [_read_fcover_asset(asset, window) for asset in assets]
                    valid = np.ones(source[0][0].shape, dtype=bool)
                    for values, nodata in source:
                        valid &= np.isfinite(values)
                        if nodata is not None:
                            valid &= values != nodata
                    legacy = _legacy_mask(legacy_id, info["bands"][0]["grid"]) > 0
                    if legacy.shape != valid.shape:
                        raise RuntimeError(f"LEGACY_DOMAIN_GRID_MISMATCH:{legacy_id}:{legacy.shape}!={valid.shape}")
                    agreement = legacy == valid
                    disagreement = int((~agreement).sum())
                    rows.append({"AOI_ID": target["aoi_id"], "legacy_asset_id": legacy_id, "year": year,
                                 "nominal_date": nominal, "total_pixels": int(valid.size),
                                 "legacy_valid": int(legacy.sum()), "new_valid": int(valid.sum()),
                                 "agreement": int(agreement.sum()), "disagreement": disagreement,
                                 "disagreement_fraction": disagreement / int(valid.size),
                                 "source_CRS": crs, "source_transform": json.dumps(list(transform)[:6]),
                                 "status": "PASS" if disagreement == 0 else "FAIL"})
    _write_csv(OUT / "LEGACY_VALID_DOMAIN_PARITY.csv", rows)
    failed = [row for row in rows if row["status"] != "PASS"]
    if failed:
        (OUT / "VALID_DOMAIN_DIFFERENCE_BLOCKER.md").write_text(
            "# Valid-domain difference blocker\n\nThe corrected source-NoData validity definition differs from the legacy derived "
            "`dataMask` on one or more deterministic representative cells. The scientific sample domain may change; "
            "all asset rebuilds and scientific execution are stopped.\n", encoding="utf-8")
        return 2
    (OUT / "LEGACY_VALID_DOMAIN_EQUIVALENCE.md").write_text(
        "# Legacy/new valid-domain equivalence\n\nAll 24 deterministic comparisons (four final AOIs × three years × two nominal "
        "dates) have zero pixel disagreement. `SCIENTIFIC_SAMPLE_DOMAIN_CHANGED = FALSE`. This correction is "
        "therefore terminology and provenance only for the tested domain.\n", encoding="utf-8")
    return 0


def legacy_inventory() -> int:
    """Classify every legacy asset as deprecated; do not backfill provenance."""
    assets = json.loads((WORKSPACE / "report/publication/new_experiments/data/manifests/gee_cloud_asset_manifest.json").read_text(encoding="utf-8"))
    tasks = json.loads((WORKSPACE / "report/publication/new_experiments/data/manifests/gee_cloud_preparation_manifest.json").read_text(encoding="utf-8"))
    by_asset = {row.get("asset_id"): row for row in tasks}
    manifest_rows: list[dict] = []
    verification_rows: list[dict] = []
    for item in assets:
        if item.get("kind") != "fcover":
            continue
        prop = item.get("properties") or {}; task = by_asset.get(item["asset_id"], {})
        row = {"asset_id": item["asset_id"], "asset_revision": "legacy_r1", "AOI_ID": prop.get("aoi_id"),
               "year": str(prop.get("nominal_date", ""))[:4], "nominal_date": prop.get("nominal_date"),
               "source_product_identifier": prop.get("source_product_id"), "source_file_or_object": "UNAVAILABLE_AT_CREATION",
               "source_checksum_if_available": prop.get("source_window_sha256"), "official_product_version": prop.get("source_version"),
               "official_source_schema": "UNPROVEN_LEGACY_PARTIAL", "source_CRS": prop.get("source_crs"),
               "source_transform": json.dumps(((item.get("grid") or {}).get("affineTransform") or {}), sort_keys=True),
               "source_width": prop.get("source_width"), "source_height": prop.get("source_height"),
               "source_NoData": "UNPROVEN_LEGACY", "valid_domain_definition_version": "legacy_dataMask_unacceptable",
               "ingestion_config_hash": "UNAVAILABLE_AT_CREATION", "GEE_task_id": task.get("task_id", "UNAVAILABLE"),
               "GEE_task_status": task.get("status", "UNAVAILABLE"), "created_at": item.get("update_time"),
               "active_or_deprecated": "DEPRECATED"}
        manifest_rows.append(row)
        verification_rows.append({**row, "bands": ";".join(item.get("bands") or []),
                                  "verification_status": "DEPRECATED", "reason": "obsolete_dataMask_schema_and_incomplete_provenance"})
    _write_csv(OUT / "FCOVER_ASSET_MANIFEST.csv", manifest_rows)
    _write_csv(OUT / "FCOVER_ASSET_VERIFICATION.csv", verification_rows)
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    rows = []
    for target in registry_geometry_payload(contract):
        for year in contract["years"]:
            for date_part in contract["nominal_dates"]:
                rows.append({"AOI_ID": target["aoi_id"], "year": year, "nominal_date": f"{year}-{date_part}",
                             "required_asset_revision": "r2_valid_domain_v1", "status": "REBUILD_REQUIRED",
                             "reason": "no_immutable_corrected_FCOVER_asset_exists"})
    _write_csv(OUT / "FCOVER_REBUILD_STATUS.csv", rows)
    return 0


def paired_cube_audit() -> int:
    """Mark all final-AOI legacy paired cubes rebuild-required until lineage exists."""
    destination = WORKSPACE / "report/publication/new_experiments/11_final_input_remediation/03_paired_cube_impact"
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    targets = {row["aoi_id"]: row.get("source_candidate_id") or row["aoi_id"] for row in registry_geometry_payload(contract)}
    rows = []
    for aoi, source_id in targets.items():
        for year in contract["years"]:
            old = f"projects/qinghai-internship-fvc-models/assets/fvc_report_data/paired_observations/{source_id.replace('-', '_')}_{year}"
            new = f"projects/qinghai-internship-fvc-models/assets/fvc_report_data/paired_observations_r2_fcover_valid_domain_v1/{aoi.replace('-', '_')}_{year}"
            rows.append({"cube_id": f"{aoi}_{year}", "aoi_id": aoi, "year": year,
                         "current_FCOVER_asset": old, "new_FCOVER_asset": new,
                         "scientifically_equivalent": "UNKNOWN", "provenance_complete": "false",
                         "rebuild_required": "true", "reason": "legacy_cube_references_deprecated_or_unverifiable_FCOVER"})
    _write_csv(destination / "PAIRED_CUBE_IMPACT_AUDIT.csv", rows)
    _write_csv(destination / "PAIRED_CUBE_REBUILD_STATUS.csv", [{**row, "status": "NOT_STARTED"} for row in rows])
    _write_csv(destination / "PAIRED_CUBE_PROVENANCE.csv", [{"cube_id": row["cube_id"], "status": "PENDING_FCOVER_PROVENANCE_AND_PARITY_PASS"} for row in rows])
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-domain-parity", action="store_true")
    parser.add_argument("--legacy-inventory", action="store_true")
    parser.add_argument("--paired-cube-audit", action="store_true")
    args = parser.parse_args()
    selected = [args.legacy_domain_parity, args.legacy_inventory, args.paired_cube_audit]
    if sum(selected) != 1:
        parser.error("choose exactly one audit")
    if args.legacy_domain_parity:
        raise SystemExit(legacy_domain_parity())
    if args.legacy_inventory:
        raise SystemExit(legacy_inventory())
    raise SystemExit(paired_cube_audit())
