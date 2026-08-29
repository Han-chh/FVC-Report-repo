#!/usr/bin/env python3
"""Audit final preparation assets and write the Scientific Execution Ready evidence.

This command is read-only with respect to Earth Engine.  It never samples a
paired cube, constructs training rows, fits a model, or runs an experiment.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
EXP = WORKSPACE / "report/publication/new_experiments"
OUT = EXP / "16_scientific_execution_readiness"
sys.path.insert(0, str(ROOT / "src"))

from data_prep.gee_cloud import (  # noqa: E402
    FCOVER_ACTIVE_COLLECTION, FCOVER_ASSET_REVISION, FCOVER_SOURCE_BANDS,
    PAIR_ACTIVE_COLLECTION, PAIR_ASSET_REVISION, fcover_asset_id, initialize,
    pair_asset_id,
)
from execution.contract import assert_design_contract, load_contract, registry_geometry_payload, sha256  # noqa: E402
from execution.identity import active_processing_hash, active_source_root, read_csv  # noqa: E402


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"EMPTY_AUDIT:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _expected_pair_bands() -> list[str]:
    result: list[str] = []
    for suffix in ("0720", "0731", "0810"):
        result += [f"fcover_{suffix}", f"rmse_{suffix}", f"qflag_{suffix}", f"nobs_{suffix}",
                   f"valid_domain_mask_{suffix}", f"valid_reference_{suffix}"]
        for sensor in ("s2", "landsat", "modis"):
            result += [f"{sensor}_ndvi_{suffix}", f"{sensor}_count_{suffix}"]
    return result


def _grid_hash(bands: list[dict[str, Any]]) -> str:
    return _canonical_hash(bands[0].get("grid")) if bands else ""


def audit(contract: dict[str, Any]) -> dict[str, Any]:
    import ee

    design_hash = assert_design_contract(contract)
    processing_hash = active_processing_hash(contract)
    initialize(WORKSPACE / "model/.env")
    geometries = registry_geometry_payload(contract)
    expected_fcover = [(row["aoi_id"], int(year), f"{year}-{part}", fcover_asset_id(row["aoi_id"], f"{year}-{part}"))
                       for row in geometries for year in contract["years"] for part in contract["nominal_dates"]]
    expected_pairs = [(row["aoi_id"], int(year), pair_asset_id(row["aoi_id"], int(year)))
                      for row in geometries for year in contract["years"]]
    fcover_rows: list[dict[str, Any]] = []
    fcover_grids: dict[str, set[str]] = {}
    for aoi, year, nominal, asset_id in expected_fcover:
        try:
            info = ee.data.getAsset(asset_id)
        except Exception as exc:
            fcover_rows.append({"AOI_ID": aoi, "year": year, "nominal_date": nominal,
                                "asset_id": asset_id, "active_or_deprecated": "ACTIVE",
                                "verification_status": "FAIL", "reason": f"MISSING:{exc}"})
            continue
        bands = info.get("bands", []); names = [band.get("id") for band in bands]
        props = info.get("properties") or {}; grids = [_canonical_hash(band.get("grid")) for band in bands]
        required_props = ("source_product_id", "source_file_or_object", "source_window_sha256", "source_version",
                          "official_source_schema", "source_nodata_json", "source_dtype_json", "ingestion_config_hash",
                          "asset_revision", "aoi_id", "nominal_date", "valid_domain_definition_version")
        missing_props = [name for name in required_props if props.get(name) in (None, "")]
        errors = []
        if names != [*FCOVER_SOURCE_BANDS, "valid_domain_mask"]: errors.append("BAND_SCHEMA")
        if len(set(grids)) != 1: errors.append("INTERNAL_GRID")
        if bands and (bands[0].get("grid") or {}).get("crsCode") != "EPSG:4326": errors.append("CRS")
        if props.get("asset_revision") != FCOVER_ASSET_REVISION: errors.append("REVISION")
        if props.get("aoi_id") != aoi or props.get("nominal_date") != nominal: errors.append("IDENTITY")
        if missing_props: errors.append("MISSING_PROPERTIES:" + ";".join(missing_props))
        try:
            schema = json.loads(props.get("official_source_schema") or "[]")
            objects = json.loads(props.get("source_file_or_object") or "{}")
            nodata = json.loads(props.get("source_nodata_json") or "{}")
            dtypes = json.loads(props.get("source_dtype_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            schema, objects, nodata, dtypes = [], {}, {}, {}
        if schema != list(FCOVER_SOURCE_BANDS): errors.append("OFFICIAL_SOURCE_SCHEMA")
        if set(objects) != set(FCOVER_SOURCE_BANDS) or not all(str(value).startswith("s3://eodata/") for value in objects.values()):
            errors.append("SOURCE_OBJECT_IDENTITIES")
        if set(nodata) != set(FCOVER_SOURCE_BANDS) or any(float(value) != 255.0 for value in nodata.values()):
            errors.append("SOURCE_NODATA")
        if set(dtypes) != set(FCOVER_SOURCE_BANDS) or any(value != "uint8" for value in dtypes.values()):
            errors.append("SOURCE_DTYPES")
        dimensions = (bands[0].get("grid") or {}).get("dimensions", {}) if bands else {}
        if int(dimensions.get("width", -1)) != int(props.get("source_width", -2)) or int(dimensions.get("height", -1)) != int(props.get("source_height", -2)):
            errors.append("SOURCE_WINDOW_DIMENSIONS")
        if len(str(props.get("source_window_sha256") or "")) != 64: errors.append("SOURCE_WINDOW_CHECKSUM")
        if props.get("valid_domain_definition_version") != "fcover-value-raster-valid-not-nodata-v2": errors.append("VALID_DOMAIN_REVISION")
        fcover_grids.setdefault(aoi, set()).add(_grid_hash(bands))
        record = {"AOI_ID": aoi, "year": year, "nominal_date": nominal, "asset_id": asset_id,
                  "asset_revision": props.get("asset_revision"), "source_product_identifier": props.get("source_product_id"),
                  "source_file_or_object": props.get("source_file_or_object"),
                  "source_checksum_if_available": props.get("source_window_sha256"),
                  "official_product_version": props.get("source_version"),
                  "official_source_schema": props.get("official_source_schema"),
                  "source_CRS": props.get("source_crs"), "source_transform": json.dumps((bands[0].get("grid") or {}).get("affineTransform", {}), sort_keys=True) if bands else "",
                  "source_width": props.get("source_width"), "source_height": props.get("source_height"),
                  "source_NoData": props.get("source_nodata_json"),
                  "valid_domain_definition_version": props.get("valid_domain_definition_version"),
                  "ingestion_config_hash": props.get("ingestion_config_hash"),
                  "created_at": info.get("updateTime"), "active_or_deprecated": "ACTIVE",
                  "bands": ";".join(names), "grid_hash": _grid_hash(bands),
                  "asset_metadata_hash": _canonical_hash({"bands": bands, "properties": props}),
                  "verification_status": "VERIFIED" if not errors else "FAIL", "reason": ";".join(errors)}
        fcover_rows.append(record)
    for row in fcover_rows:
        if len(fcover_grids.get(row["AOI_ID"], set())) != 1:
            row["verification_status"] = "FAIL"
            row["reason"] = (row.get("reason") + ";CROSS_DATE_GRID_DRIFT").strip(";")

    source_index = read_csv(active_source_root(contract) / "ACTIVE_SOURCE_MANIFEST_INDEX.csv")
    hashes = {(row["AOI_ID"], row["sensor"], int(row["year"]), row["nominal_date"]): row["source_manifest_hash"]
              for row in source_index}
    pair_rows: list[dict[str, Any]] = []
    pair_grids: dict[str, set[str]] = {}
    expected_band_names = _expected_pair_bands()
    source_rows = {sensor: read_csv(active_source_root(contract) / name) for sensor, name in {
        "sentinel2": "ACTIVE_SENTINEL_SCENE_MANIFEST.csv", "landsat": "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
        "modis": "ACTIVE_MODIS_SCENE_MANIFEST.csv"}.items()}
    for aoi, year, asset_id in expected_pairs:
        try:
            info = ee.data.getAsset(asset_id)
        except Exception as exc:
            pair_rows.append({"cube_id": f"{aoi}_{year}", "aoi_id": aoi, "year": year,
                              "asset_id": asset_id, "provenance_complete": "false",
                              "rebuild_required": "true", "verification_status": "FAIL", "reason": f"MISSING:{exc}"})
            continue
        bands = info.get("bands", []); names = [band.get("id") for band in bands]; props = info.get("properties") or {}
        expected_fcover_ids = [fcover_asset_id(aoi, f"{year}-{part}") for part in contract["nominal_dates"]]
        expected_hashes = {f"{sensor}_{part.replace('-', '')}": hashes[(aoi, sensor, year, f"{year}-{part}")]
                           for part in contract["nominal_dates"] for sensor in ("sentinel2", "landsat", "modis")}
        expected_scene_ids = sorted(row["system:id"] for sensor in source_rows for row in source_rows[sensor]
                                    if row["AOI_ID"] == aoi and int(row["year"]) == year
                                    and str(row["included"]).lower() == "true")
        try: observed_hashes = json.loads(props.get("source_manifest_hashes_json") or "{}")
        except json.JSONDecodeError: observed_hashes = {}
        errors = []
        if names != expected_band_names: errors.append("PAIR_BAND_SCHEMA")
        if len({_canonical_hash(band.get("grid")) for band in bands}) != 1: errors.append("PAIR_GRID")
        if props.get("aoi_id") != aoi or int(props.get("year", -1)) != year: errors.append("PAIR_IDENTITY")
        if props.get("fcover_assets") != ";".join(expected_fcover_ids): errors.append("FCOVER_LINEAGE")
        if props.get("asset_revision") != PAIR_ASSET_REVISION: errors.append("PAIR_REVISION")
        if props.get("scientific_design_hash") != design_hash: errors.append("DESIGN_HASH")
        if props.get("processing_hash") != processing_hash: errors.append("PROCESSING_HASH")
        if observed_hashes != expected_hashes: errors.append("SOURCE_MANIFEST_HASHES")
        if props.get("source_selection_mode") != "exact_active_source_scene_manifest_r2": errors.append("SOURCE_SELECTION_MODE")
        if props.get("source_scene_ids_sha256") != sha256(expected_scene_ids): errors.append("SOURCE_SCENE_IDS")
        if props.get("fcover_asset_revision") != FCOVER_ASSET_REVISION: errors.append("FCOVER_REVISION")
        if int(props.get("paired_cube_band_count", -1)) != len(expected_band_names): errors.append("DECLARED_BAND_COUNT")
        if int(props.get("minimum_finite_contributions", -1)) != 2: errors.append("MINIMUM_CONTRIBUTIONS")
        if int(props.get("temporal_window_days", -1)) != 15: errors.append("TEMPORAL_WINDOW")
        expected_order = "native_scaling>native_QA>native_NDVI>average_to_FCOVER_grid>temporal_nanmedian"
        if props.get("processing_order") != expected_order: errors.append("PROCESSING_ORDER")
        matching_fcover = next((row for row in fcover_rows if row["AOI_ID"] == aoi and int(row["year"]) == year
                                and row["nominal_date"] == f"{year}-07-20"), None)
        if not matching_fcover or _grid_hash(bands) != matching_fcover.get("grid_hash"): errors.append("FCOVER_GRID_LINEAGE")
        required_nonempty = []
        for suffix in ("0720", "0731", "0810"):
            required_nonempty += [f"fcover_{suffix}", f"valid_reference_{suffix}",
                                  f"s2_ndvi_{suffix}", f"landsat_ndvi_{suffix}", f"modis_ndvi_{suffix}"]
        grid = bands[0].get("grid") if bands else {}; affine = (grid or {}).get("affineTransform", {})
        transform = [affine.get("scaleX"), affine.get("shearX", 0), affine.get("translateX"),
                     affine.get("shearY", 0), affine.get("scaleY"), affine.get("translateY")]
        try:
            counts = (ee.Image(asset_id).select(required_nonempty)
                      .reduceRegion(reducer=ee.Reducer.count(), geometry=ee.Image(asset_id).geometry(),
                                    crs=(grid or {}).get("crsCode"), crsTransform=transform,
                                    maxPixels=2_000_000, tileScale=2).getInfo())
        except Exception as exc:
            counts = {}; errors.append(f"USABILITY_COUNT_FAILED:{exc}")
        empty = sorted(name for name in required_nonempty if int(counts.get(name) or 0) <= 0)
        if empty: errors.append("EMPTY_SCIENTIFIC_SUPPORT:" + ";".join(empty))
        if props.get("scientific_results_executed") not in (0, "0"): errors.append("SCIENTIFIC_RESULTS_FLAG")
        pair_grids.setdefault(aoi, set()).add(_grid_hash(bands))
        pair_rows.append({"cube_id": f"{aoi}_{year}", "aoi_id": aoi, "year": year, "asset_id": asset_id,
                          "current_FCOVER_asset": props.get("fcover_assets"), "new_FCOVER_asset": ";".join(expected_fcover_ids),
                          "scientifically_equivalent": "VERIFIED_ACTIVE_R3", "provenance_complete": str(not errors).lower(),
                          "rebuild_required": str(bool(errors)).lower(), "band_count": len(names),
                          "grid_hash": _grid_hash(bands), "design_hash": props.get("scientific_design_hash"),
                          "processing_hash": props.get("processing_hash"),
                          "source_scene_ids_sha256": props.get("source_scene_ids_sha256"),
                          "minimum_required_band_count": min((int(counts.get(name) or 0) for name in required_nonempty), default=0),
                          "verification_status": "VERIFIED" if not errors else "FAIL", "reason": ";".join(errors)})
    for row in pair_rows:
        if len(pair_grids.get(row["aoi_id"], set())) != 1:
            row["provenance_complete"] = "false"; row["rebuild_required"] = "true"; row["verification_status"] = "FAIL"
            row["reason"] = (row.get("reason") + ";CROSS_YEAR_GRID_DRIFT").strip(";")

    availability = []
    fc_ok = {(row["AOI_ID"], int(row["year"])) for row in fcover_rows if row["verification_status"] == "VERIFIED"}
    pair_ok = {(row["aoi_id"], int(row["year"])) for row in pair_rows if row["verification_status"] == "VERIFIED"}
    for aoi in contract["final_aoi_ids"]:
        for year in contract["years"]:
            for product in ("sentinel2", "landsat", "modis", "fcover"):
                ok = (aoi, int(year)) in (fc_ok if product == "fcover" else pair_ok)
                availability.append({"aoi_id": aoi, "year": year, "sensor_product": product,
                                     "status": "READY" if ok else "NOT_READY",
                                     "reason": "active immutable input contract verified" if ok else "active input verification failed"})

    fcover_path = OUT / "01_final_fcover/FCOVER_ASSET_VERIFICATION.csv"
    pair_path = OUT / "02_final_pairs/PAIRED_CUBE_IMPACT_AUDIT.csv"
    availability_path = OUT / "04_input_manifest/FINAL_INPUT_AVAILABILITY.csv"
    _write(fcover_path, fcover_rows); _write(pair_path, pair_rows); _write(availability_path, availability)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "design_hash": design_hash,
              "processing_hash": processing_hash, "fcover_collection": FCOVER_ACTIVE_COLLECTION,
              "pair_collection": PAIR_ACTIVE_COLLECTION, "expected_fcover_assets": 60,
              "verified_fcover_assets": sum(row["verification_status"] == "VERIFIED" for row in fcover_rows),
              "expected_pair_assets": 20,
              "verified_pair_assets": sum(row["verification_status"] == "VERIFIED" for row in pair_rows),
              "availability_rows": len(availability),
              "availability_ready_rows": sum(row["status"] == "READY" for row in availability),
              "scientific_results_executed": False}
    result["ready"] = (result["verified_fcover_assets"] == 60 and result["verified_pair_assets"] == 20
                       and result["availability_ready_rows"] == len(availability))
    audit_path = OUT / "04_input_manifest/ACTIVE_ASSET_AUDIT.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    manifest_files = [fcover_path, pair_path, availability_path,
                      active_source_root(contract) / "ACTIVE_SOURCE_MANIFEST_INDEX.csv",
                      EXP / "08_scientific_execution/00_execution_manifest/PROCESSING_HASH.json",
                      EXP / "08_scientific_execution/00_execution_manifest/BLOCK_MANIFEST.csv"]
    manifest = [{"path": str(path.relative_to(WORKSPACE)), "size_bytes": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in manifest_files if path.exists()]
    _write(OUT / "04_input_manifest/SCIENTIFIC_INPUT_MANIFEST.csv", manifest)
    print(json.dumps(result, indent=2)); return result


if __name__ == "__main__":
    report = audit(load_contract(ROOT / "configs/scientific_execution.yaml"))
    raise SystemExit(0 if report["ready"] else 2)
