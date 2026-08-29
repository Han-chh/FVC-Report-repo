#!/usr/bin/env python3
"""Evidence-only FCOVER acquisition and parity canaries; never runs models.

Official Copernicus COGs are the source of truth.  This program reads only
the required AOI windows through GDAL range requests and keeps arrays in
memory.  It intentionally never writes or validates a complete source COG.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import rasterio
import requests

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from data_prep.download import (  # noqa: E402
    _fcover_assets, _fcover_grid, _fcover_item, _fcover_window,
    load_credentials, read_fcover_window_with_retry,
)
from data_prep.fcover import fcover_value_valid_mask  # noqa: E402
from execution.contract import load_contract, registry_geometry_payload  # noqa: E402

BASE = WORKSPACE / "report/publication/new_experiments/12_source_acquisition_and_parity"
ACQUISITION = BASE / "01_source_acquisition"
DOMAIN = BASE / "02_valid_domain"
CANARY = BASE / "03_fcover_canary"
CANARY_AOI, CANARY_DATE = "AOI-00", "2025-07-20"
SCHEMA = (("fcover300_fcover", "FCOVER"), ("fcover300_rmse", "RMSE"),
          ("fcover300_nobs", "NOBS"), ("fcover300_lbefore", "LBEFORE"),
          ("fcover300_lafter", "LAFTER"), ("fcover300_qflag", "QFLAG"))
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"


def _write(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = fields or sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=selected, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def _fetch_item(nominal: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(90, connect=15)) as client:
                return _fcover_item(client, nominal)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"FCOVER_STAC_DISCOVERY_FAILED_AFTER_3_ATTEMPTS:{last_error}")


def _asset_href(asset: dict[str, Any]) -> str:
    return str(asset.get("href") or ((asset.get("alternate") or {}).get("https") or {}).get("href") or "")


def _manifest_rows(item: dict[str, Any], nominal: str, *, status: str,
                   window: rasterio.windows.Window | None = None,
                   grid: tuple[rasterio.Affine, int, int, str] | None = None,
                   detail: str = "") -> list[dict[str, Any]]:
    properties = item.get("properties") or {}
    assets = _fcover_assets(item)
    output: list[dict[str, Any]] = []
    for (asset_key, band), asset in zip(SCHEMA, assets):
        output.append({
            "source_record_id": f"{item.get('collection')}:{item.get('id')}:{asset_key}",
            "STAC_collection": item.get("collection"), "STAC_item_id": item.get("id"),
            "nominal_date": nominal, "product_version": properties.get("processing:version") or "",
            "RT_version_lineage": "FCOVER300-RT6_V2", "asset_key": asset_key, "band": band,
            "asset_href_or_object_identity": _asset_href(asset), "access_method": "official_cdse_cog_range_request",
            "file_size": asset.get("file:size") or "", "etag_if_available": asset.get("file:etag") or "",
            "checksum": asset.get("checksum:multihash") or asset.get("file:checksum") or "NOT_AVAILABLE_FROM_STAC",
            "download_timestamp": "", "local_cache_path": "", "temporary_file": "",
            "CRS": grid[3] if grid else (properties.get("proj:code") or ""),
            "transform": json.dumps(list(grid[0])[:6]) if grid else json.dumps(asset.get("proj:transform") or []),
            "width": grid[1] if grid else "", "height": grid[2] if grid else "",
            "source_window": (f"{int(window.col_off)},{int(window.row_off)},{int(window.width)},{int(window.height)}" if window else ""),
            "NoData": asset.get("raster:bands", [{}])[0].get("nodata", "") if asset.get("raster:bands") else "",
            "dtype": asset.get("raster:bands", [{}])[0].get("data_type", "") if asset.get("raster:bands") else "",
            "source_schema_verified": "true" if status == "WINDOW_READ_OK" else "metadata_pending_window_read",
            "status": status, "detail": detail,
        })
    return output


def _append_manifest(rows: list[dict[str, Any]], logs: list[dict[str, Any]]) -> None:
    manifest_path, log_path = ACQUISITION / "FCOVER_SOURCE_ACQUISITION_MANIFEST.csv", ACQUISITION / "SOURCE_DOWNLOAD_LOG.csv"
    previous = list(csv.DictReader(manifest_path.open(encoding="utf-8"))) if manifest_path.exists() else []
    keys = {(r.get("source_record_id"), r.get("source_window"), r.get("status")) for r in previous}
    previous.extend(r for r in rows if (r.get("source_record_id"), r.get("source_window"), r.get("status")) not in keys)
    _write(manifest_path, previous)
    prior_logs = list(csv.DictReader(log_path.open(encoding="utf-8"))) if log_path.exists() else []
    _write(log_path, prior_logs + logs)


def discover_canary() -> int:
    """Freeze official source identity only; this does not download a COG."""
    ACQUISITION.mkdir(parents=True, exist_ok=True)
    try:
        item = _fetch_item(CANARY_DATE)
        _append_manifest(_manifest_rows(item, CANARY_DATE, status="DISCOVERED_REMOTE"), [{
            "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(),
            "nominal_date": CANARY_DATE, "status": "DISCOVERED_REMOTE", "detail": "STAC identity frozen; no COG downloaded"}])
        (ACQUISITION / "SOURCE_CACHE_AUDIT.md").write_text(
            "# Source cache audit\n\nNo complete FCOVER COG is cached. Official STAC/object identities are recorded, and parity reads only disposable in-memory AOI windows through GDAL range requests.\n",
            encoding="utf-8")
        return 0
    except Exception as exc:
        _append_manifest([{"source_record_id": f"CANARY:{CANARY_DATE}", "nominal_date": CANARY_DATE,
                           "status": "DISCOVERY_FAILED", "detail": str(exc)}], [])
        return 2


def _aoi_rows() -> list[dict[str, Any]]:
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    return registry_geometry_payload(contract)


def _legacy_id(aoi: dict[str, Any], nominal: str) -> str:
    candidate = aoi.get("source_candidate_id") or aoi["aoi_id"]
    return f"projects/qinghai-internship-fvc-models/assets/fvc_report_data/fcover_native/{candidate.replace('-', '_')}_{nominal.replace('-', '')}"


def _download_gee(image: Any, grid: dict[str, Any], *, name: str) -> tuple[np.ndarray, rasterio.Affine, str]:
    affine = grid["affineTransform"]; dims = grid["dimensions"]
    transform = [affine["scaleX"], affine.get("shearX", 0), affine["translateX"],
                 affine.get("shearY", 0), affine["scaleY"], affine["translateY"]]
    url = image.getDownloadURL({"name": name, "crs": grid["crsCode"], "crs_transform": transform,
                                "dimensions": [dims["width"], dims["height"]], "format": "GEO_TIFF"})
    response = requests.get(url, timeout=(15, 120)); response.raise_for_status(); data = response.content
    if data[:2] == b"PK":
        archive = zipfile.ZipFile(io.BytesIO(data)); data = archive.read(next(n for n in archive.namelist() if n.lower().endswith((".tif", ".tiff"))))
    with rasterio.MemoryFile(data) as memory:
        with memory.open() as dataset:
            return dataset.read(), dataset.transform, dataset.crs.to_string() if dataset.crs else ""


def _valid_domain_case(aoi: dict[str, Any], nominal: str) -> dict[str, Any]:
    import ee
    item = _fetch_item(nominal); assets = _fcover_assets(item); source_transform, width, height, crs = _fcover_grid(item, assets)
    bounds = [float(v) for v in __import__("shapely.geometry", fromlist=["shape"]).shape(aoi["geometry"]).bounds]
    window = _fcover_window(bounds, source_transform, width, height)
    started = datetime.now(timezone.utc).isoformat()
    arrays_nodata = [read_fcover_window_with_retry(asset, window) for asset in assets]
    valid = fcover_value_valid_mask(arrays_nodata[0][0], nodata=arrays_nodata[0][1])
    legacy_asset = _legacy_id(aoi, nominal)
    grid = ee.data.getAsset(legacy_asset)["bands"][0]["grid"]
    legacy, gee_transform, gee_crs = _download_gee(ee.Image(legacy_asset).select("dataMask").unmask(0), grid, name="legacy_domain")
    legacy = legacy[0] > 0
    if legacy.shape != valid.shape:
        raise RuntimeError(f"LEGACY_DOMAIN_GRID_MISMATCH:{legacy.shape}!={valid.shape}")
    source_window_transform = rasterio.windows.transform(window, source_transform)
    if gee_crs != crs or not np.allclose(list(gee_transform)[:6], list(source_window_transform)[:6], atol=1e-12, rtol=0):
        raise RuntimeError("LEGACY_DOMAIN_GRID_TRANSFORM_MISMATCH")
    agreement = legacy == valid; disagreement = int((~agreement).sum())
    manifest = _manifest_rows(item, nominal, status="WINDOW_READ_OK", window=window,
                              grid=(source_transform, width, height, crs))
    _append_manifest(manifest, [{"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
                                  "nominal_date": nominal, "AOI_ID": aoi["aoi_id"], "status": "WINDOW_READ_OK",
                                  "detail": "Six official COG AOI windows read in memory; no source COG persisted"}])
    return {"AOI_ID": aoi["aoi_id"], "year": int(nominal[:4]), "nominal_date": nominal,
            "legacy_asset_id": legacy_asset, "source_STAC_item_id": item.get("id"),
            "source_window": f"{int(window.col_off)},{int(window.row_off)},{int(window.width)},{int(window.height)}",
            "total_pixels": int(valid.size), "legacy_valid_pixels": int(legacy.sum()), "new_valid_pixels": int(valid.sum()),
            "agreement_pixels": int(agreement.sum()), "disagreement_pixels": disagreement,
            "disagreement_fraction": disagreement / int(valid.size), "status": "PASS" if disagreement == 0 else "FAIL"}


def _write_domain_result(rows: list[dict[str, Any]], *, full: bool) -> int:
    DOMAIN.mkdir(parents=True, exist_ok=True)
    output = DOMAIN / ("VALID_DOMAIN_24CASE_PARITY.csv" if full else "CANARY_VALID_DOMAIN_PARITY.csv")
    _write(output, rows)
    passed = bool(rows) and all(row["status"] == "PASS" for row in rows)
    if any(row.get("status") == "FAIL" for row in rows):
        (DOMAIN / "VALID_DOMAIN_DIFFERENCE_BLOCKER.md").write_text(
            "# Valid-domain difference blocker\n\nA frozen-case legacy/new domain comparison has non-zero disagreement. No FCOVER asset rebuild is permitted until scientific impact is resolved.\n", encoding="utf-8")
    status = "DOMAIN_EQUIVALENCE_CONFIRMED" if full and passed else ("DOMAIN_EQUIVALENT" if passed else "DOMAIN_EQUIVALENCE_FAILED")
    (DOMAIN / "VALID_DOMAIN_RESULT.md").write_text(f"# Valid-domain result\n\nStatus: {status}\n\n"
        "`valid_domain_mask` is derived only from FCOVER raster-valid/NoData semantics; QFLAG/NOBS availability and acceptance remain separate. It is not an official `dataMask` band.\n", encoding="utf-8")
    return 0 if passed else 2


def _case_file(aoi_id: str, nominal: str) -> Path:
    return DOMAIN / "case_checkpoints" / f"{aoi_id}_{nominal.replace('-', '')}.json"


def valid_domain_one(aoi_id: str, nominal: str) -> int:
    """One independently bounded frozen case; parent processes resume it."""
    load_credentials(WORKSPACE / "model/.env")
    from data_prep.gee_cloud import initialize
    initialize(WORKSPACE / "model/.env")
    target = next((x for x in _aoi_rows() if x["aoi_id"] == aoi_id), None)
    if target is None:
        raise RuntimeError(f"UNKNOWN_FINAL_AOI:{aoi_id}")
    try:
        row = _valid_domain_case(target, nominal)
    except Exception as exc:
        row = {"AOI_ID": aoi_id, "year": int(nominal[:4]), "nominal_date": nominal,
               "status": "BLOCKED", "reason": f"REMOTE_WINDOW_PREREQUISITE_FAILED:{exc}"}
    checkpoint = _case_file(aoi_id, nominal); checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    return 0 if row["status"] == "PASS" else 2


def canary_valid_domain() -> int:
    load_credentials(WORKSPACE / "model/.env")
    from data_prep.gee_cloud import initialize
    initialize(WORKSPACE / "model/.env")
    try:
        return _write_domain_result([_valid_domain_case(next(x for x in _aoi_rows() if x["aoi_id"] == CANARY_AOI), CANARY_DATE)], full=False)
    except Exception as exc:
        _write(DOMAIN / "CANARY_VALID_DOMAIN_PARITY.csv", [{"AOI_ID": CANARY_AOI, "nominal_date": CANARY_DATE, "status": "BLOCKED", "reason": str(exc)}])
        return 2


def valid_domain_24() -> int:
    canary = DOMAIN / "CANARY_VALID_DOMAIN_PARITY.csv"
    if not canary.exists() or list(csv.DictReader(canary.open(encoding="utf-8")))[0].get("status") != "PASS":
        _write(DOMAIN / "VALID_DOMAIN_24CASE_PARITY.csv", [{"status": "BLOCKED", "reason": "CANARY_VALID_DOMAIN_NOT_PASS"}]); return 2
    load_credentials(WORKSPACE / "model/.env")
    from data_prep.gee_cloud import initialize
    initialize(WORKSPACE / "model/.env")
    rows: list[dict[str, Any]] = []
    frozen = [(aoi["aoi_id"], f"{year}-{month_day}") for aoi in _aoi_rows()
              for year in (2021, 2023, 2025) for month_day in ("07-20", "08-10")]
    for index, (aoi_id, nominal) in enumerate(frozen):
        checkpoint = _case_file(aoi_id, nominal)
        if checkpoint.exists():
            row = json.loads(checkpoint.read_text(encoding="utf-8"))
        else:
            try:
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--valid-domain-one", aoi_id, nominal],
                                           cwd=WORKSPACE, text=True, capture_output=True, timeout=180, check=False)
                row = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {
                    "AOI_ID": aoi_id, "year": int(nominal[:4]), "nominal_date": nominal, "status": "BLOCKED",
                    "reason": f"REMOTE_WINDOW_CHILD_NO_CHECKPOINT:exit={completed.returncode}"}
            except subprocess.TimeoutExpired:
                row = {"AOI_ID": aoi_id, "year": int(nominal[:4]), "nominal_date": nominal, "status": "BLOCKED",
                       "reason": "REMOTE_WINDOW_CASE_TIMEOUT_AFTER_180_SECONDS"}
                checkpoint.parent.mkdir(parents=True, exist_ok=True); checkpoint.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
        rows.append(row)
        _write(DOMAIN / "VALID_DOMAIN_24CASE_PARITY.csv", rows)
        if row.get("status") != "PASS":
            for later_aoi, later_nominal in frozen[index + 1:]:
                rows.append({"AOI_ID": later_aoi, "year": int(later_nominal[:4]), "nominal_date": later_nominal,
                             "status": "NOT_RUN", "reason": "PREVIOUS_REMOTE_WINDOW_PREREQUISITE_BLOCKED"})
            _write(DOMAIN / "VALID_DOMAIN_24CASE_PARITY.csv", rows)
            return _write_domain_result(rows, full=True)
    return _write_domain_result(rows, full=True)


def ingest_canary() -> int:
    full = DOMAIN / "VALID_DOMAIN_24CASE_PARITY.csv"
    rows = list(csv.DictReader(full.open(encoding="utf-8"))) if full.exists() else []
    CANARY.mkdir(parents=True, exist_ok=True)
    if len(rows) != 24 or any(row.get("status") != "PASS" for row in rows):
        _write(CANARY / "CANARY_ASSET_MANIFEST.csv", [{"AOI_ID": CANARY_AOI, "nominal_date": CANARY_DATE,
                                                         "status": "BLOCKED", "reason": "VALID_DOMAIN_24CASE_NOT_PASS"}]); return 2
    load_credentials(WORKSPACE / "model/.env")
    from data_prep.gee_cloud import ingest_fcover, initialize
    initialize(WORKSPACE / "model/.env")
    feature = next(x for x in _aoi_rows() if x["aoi_id"] == CANARY_AOI)
    try:
        result = ingest_fcover({"type": "Feature", "properties": {"aoi_id": CANARY_AOI, "geometry_version": feature.get("geometry_version")}, "geometry": feature["geometry"]}, CANARY_DATE)
        result["scientific_design_hash"] = DESIGN_HASH
        result["source_identity_mode"] = "official_STAC_item_and_COG_object_identity;remote_window_only"
        _write(CANARY / "CANARY_ASSET_MANIFEST.csv", [result]); return 0
    except Exception as exc:
        _write(CANARY / "CANARY_ASSET_MANIFEST.csv", [{"AOI_ID": CANARY_AOI, "nominal_date": CANARY_DATE, "status": "BLOCKED", "reason": str(exc)}]); return 2


def source_gee_canary_parity() -> int:
    """Compare remote official source arrays with exact GEE pixels in memory."""
    manifest = CANARY / "CANARY_ASSET_MANIFEST.csv"
    records = list(csv.DictReader(manifest.open(encoding="utf-8"))) if manifest.exists() else []
    if not records or records[0].get("status") not in {"COMPLETED", "EXISTING"}:
        _write(CANARY / "CANARY_SOURCE_GEE_PARITY.csv", [{"status": "BLOCKED", "reason": "CORRECTED_CANARY_ASSET_NOT_READY"}]); return 2
    load_credentials(WORKSPACE / "model/.env")
    from data_prep.gee_cloud import initialize
    initialize(WORKSPACE / "model/.env")
    import ee
    try:
        aoi = next(x for x in _aoi_rows() if x["aoi_id"] == CANARY_AOI); item = _fetch_item(CANARY_DATE); assets = _fcover_assets(item)
        transform, width, height, crs = _fcover_grid(item, assets)
        bounds = [float(v) for v in __import__("shapely.geometry", fromlist=["shape"]).shape(aoi["geometry"]).bounds]
        window = _fcover_window(bounds, transform, width, height)
        arrays_nodata = [read_fcover_window_with_retry(asset, window) for asset in assets]
        valid = fcover_value_valid_mask(arrays_nodata[0][0], nodata=arrays_nodata[0][1])
        source = np.stack([v.astype("uint8") for v, _ in arrays_nodata] + [valid.astype("uint8")])
        asset_id = records[0]["asset_id"]; info = ee.data.getAsset(asset_id); grid = info["bands"][0]["grid"]
        image = ee.Image(asset_id); exported = ee.Image.cat([image.select(list(b for _, b in SCHEMA)).unmask(255).toUint8(), image.select("valid_domain_mask").unmask(0).toUint8()])
        gee, gee_transform, gee_crs = _download_gee(exported, grid, name="fcover_source_gee_parity")
        expected_transform = rasterio.windows.transform(window, transform)
        grid_ok = (gee_crs == crs and gee.shape == source.shape and np.allclose(list(gee_transform)[:6], list(expected_transform)[:6], atol=1e-12, rtol=0))
        difference = np.abs(gee.astype("int16") - source.astype("int16")); mismatched = int(np.any(difference != 0, axis=0).sum())
        rows = [{"asset_id": asset_id, "source_STAC_item_id": item.get("id"), "band": band,
                 "total_pixels": int(source[index].size), "different_pixels": int((difference[index] != 0).sum()),
                 "maximum_absolute_difference": int(difference[index].max()), "grid_exact": str(grid_ok).lower(),
                 "status": "PASS" if grid_ok and not np.any(difference[index]) else "FAIL"}
                for index, (_, band) in enumerate((*SCHEMA, ("derived", "valid_domain_mask")))]
        _write(CANARY / "CANARY_SOURCE_GEE_PARITY.csv", rows)
        all_pass = all(row["status"] == "PASS" for row in rows)
        (CANARY / "CANARY_RESULT.md").write_text(f"# FCOVER source → GEE canary\n\nVerdict: {'PASS' if all_pass else 'FAIL'}\n\nThe official remote source windows and exact GEE pixel window were compared in memory; no full source COG was cached.\n", encoding="utf-8")
        return 0 if all_pass else 2
    except Exception as exc:
        _write(CANARY / "CANARY_SOURCE_GEE_PARITY.csv", [{"status": "BLOCKED", "reason": str(exc)}]); return 2


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--discover-canary", action="store_true")
    group.add_argument("--canary-valid-domain", action="store_true")
    group.add_argument("--valid-domain-24", action="store_true")
    group.add_argument("--valid-domain-one", nargs=2, metavar=("AOI_ID", "YYYY-MM-DD"))
    group.add_argument("--ingest-canary", action="store_true")
    group.add_argument("--source-gee-canary-parity", action="store_true")
    args = parser.parse_args()
    raise SystemExit(discover_canary() if args.discover_canary else canary_valid_domain() if args.canary_valid_domain else valid_domain_24() if args.valid_domain_24 else valid_domain_one(*args.valid_domain_one) if args.valid_domain_one else ingest_canary() if args.ingest_canary else source_gee_canary_parity())
