#!/usr/bin/env python3
"""Finalize and audit execution inputs without running scientific models.

The historical manifests and legacy GEE assets are never changed.  This
script writes a new active manifest revision, creates only missing immutable
R3 preparation assets, and produces readiness evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
EXP = WORKSPACE / "report/publication/new_experiments"
sys.path.insert(0, str(ROOT / "src"))

from data_prep.gee_cloud import (  # noqa: E402
    FCOVER_ACTIVE_COLLECTION,
    FCOVER_ASSET_REVISION,
    FCOVER_SOURCE_BANDS,
    PAIR_ACTIVE_COLLECTION,
    PAIR_ASSET_REVISION,
    build_pair_cube,
    fcover_asset_id,
    ingest_fcover,
    initialize,
    pair_asset_id,
)
from execution.contract import (  # noqa: E402
    actual_design_hash,
    assert_design_contract,
    load_contract,
    processing_hash as code_processing_hash,
    registry_geometry_payload,
    sha256,
)
from execution.identity import (  # noqa: E402
    ACTIVE_SOURCE_REVISION,
    active_processing_hash,
    active_source_root,
    processing_identity_payload,
)


PHASE = EXP / "16_scientific_execution_readiness"
LEGACY_SOURCE_ROOT = EXP / "08_scientific_execution/00_execution_manifest/source_scenes"
EXPECTED_BANDS = {
    "sentinel2": {"B4", "B8", "SCL"},
    "landsat": {"SR_B4", "SR_B5", "QA_PIXEL", "QA_RADSAT"},
    "modis": {"sur_refl_b01", "sur_refl_b02", "State", "QA"},
}
LEGACY_NAMES = {
    "sentinel2": "FROZEN_sentinel2_scene_manifest.csv",
    "landsat": "FROZEN_landsat_scene_manifest.csv",
    "modis": "FROZEN_modis_scene_manifest.csv",
}
ACTIVE_NAMES = {
    "sentinel2": "ACTIVE_SENTINEL_SCENE_MANIFEST.csv",
    "landsat": "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
    "modis": "ACTIVE_MODIS_SCENE_MANIFEST.csv",
}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"EMPTY_EVIDENCE:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def _truth(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _repair_identity(sensor: str, row: dict[str, str]) -> dict[str, Any]:
    fixed: dict[str, Any] = dict(row)
    old_id = str(row["system:id"])
    basename = old_id.rsplit("/", 1)[-1]
    correction = "RESTORE_SYSTEM_INDEX_FROM_EXACT_SYSTEM_ID"
    if sensor == "landsat":
        if basename.startswith(("1_", "2_")):
            basename = basename[2:]
        collection = "LANDSAT/LC09/C02/T1_L2" if basename.startswith("LC09_") else "LANDSAT/LC08/C02/T1_L2"
        fixed["GEE_collection_ID"] = collection
        fixed["system:id"] = f"{collection}/{basename}"
        fixed["platform"] = "LANDSAT_9" if basename.startswith("LC09_") else "LANDSAT_8"
        correction = "REMOVE_SYNTHETIC_MERGE_PREFIX;BIND_PLATFORM_COLLECTION;RESTORE_SYSTEM_INDEX"
    else:
        fixed["system:id"] = old_id
    fixed["system:index"] = basename
    fixed["processing_version"] = (row.get("processing_version") or
                                   row.get("processing_baseline_if_available") or
                                   row.get("product_version") or "NOT_AVAILABLE")
    fixed["active_source_revision"] = ACTIVE_SOURCE_REVISION
    fixed["legacy_system_id"] = old_id
    fixed["identity_correction"] = correction
    return fixed


def _validate_assets(requests: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    """Validate exact image identities in bounded server-side batches."""
    import ee

    unique = sorted(set(requests))
    evidence: list[dict[str, Any]] = []
    for start in range(0, len(unique), 50):
        batch = unique[start:start + 50]
        features = []
        for sensor, asset_id in batch:
            image = ee.Image(asset_id)
            features.append(ee.Feature(None, {
                "sensor": sensor,
                "asset_id": asset_id,
                "observed_system_index": image.get("system:index"),
                "bands": image.bandNames().join(";"),
            }))
        info = ee.FeatureCollection(features).getInfo()
        returned = {item["properties"]["asset_id"]: item["properties"]
                    for item in info.get("features", [])}
        for sensor, asset_id in batch:
            properties = returned.get(asset_id)
            if properties is None:
                raise RuntimeError(f"SOURCE_ASSET_NOT_RESOLVED:{asset_id}")
            bands = set(str(properties.get("bands") or "").split(";"))
            missing = sorted(EXPECTED_BANDS[sensor] - bands)
            expected_index = asset_id.rsplit("/", 1)[-1]
            observed_index = str(properties.get("observed_system_index") or "")
            verdict = "PASS" if not missing and observed_index == expected_index else "FAIL"
            evidence.append({"sensor": sensor, "asset_id": asset_id,
                             "expected_system_index": expected_index,
                             "observed_system_index": observed_index,
                             "required_bands": ";".join(sorted(EXPECTED_BANDS[sensor])),
                             "observed_bands": ";".join(sorted(bands)),
                             "missing_bands": ";".join(missing), "verdict": verdict})
    if any(row["verdict"] != "PASS" for row in evidence):
        raise RuntimeError("FULL_SOURCE_ASSET_VALIDATION_FAILED")
    return evidence


def repair_source_manifests(contract: dict[str, Any]) -> dict[str, int]:
    """Create the active full-period source contract; preserve legacy files."""
    import ee

    assert_design_contract(contract)
    initialize(WORKSPACE / "model/.env")
    destination = active_source_root(contract)
    transformed: dict[str, list[dict[str, Any]]] = {}
    requests: list[tuple[str, str]] = []
    for sensor, legacy_name in LEGACY_NAMES.items():
        rows = [_repair_identity(sensor, row) for row in _read(LEGACY_SOURCE_ROOT / legacy_name)]
        transformed[sensor] = rows
        requests.extend((sensor, str(row["system:id"])) for row in rows)

    validation = _validate_assets(requests)
    sentinel_ids = sorted({str(row["system:id"]) for row in transformed["sentinel2"] if _truth(row["included"])})
    requested_indices = sorted({asset.rsplit("/", 1)[-1] for asset in sentinel_ids})
    available_indices: set[str] = set()
    for start in range(0, len(requested_indices), 100):
        chunk = requested_indices[start:start + 100]
        found = (ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY")
                 .filter(ee.Filter.inList("system:index", chunk))
                 .aggregate_array("system:index").getInfo())
        available_indices.update(str(value) for value in found)
    cloud_ids = [f"COPERNICUS/S2_CLOUD_PROBABILITY/{index}" for index in sorted(available_indices)]
    cloud_features = [ee.Feature(None, {"asset_id": asset, "system_index": ee.Image(asset).get("system:index"),
                                        "bands": ee.Image(asset).bandNames().join(";")}) for asset in cloud_ids]
    cloud_info = ee.FeatureCollection(cloud_features).getInfo().get("features", [])
    cloud_validation = []
    for item in cloud_info:
        prop = item["properties"]; asset = prop["asset_id"]; index = asset.rsplit("/", 1)[-1]
        ok = str(prop.get("system_index") or "") == index and "probability" in str(prop.get("bands") or "").split(";")
        cloud_validation.append({"s2_system_index": index, "cloud_system_id": asset,
                                 "cloud_system_index": prop.get("system_index"),
                                 "probability_band_present": "probability" in str(prop.get("bands") or "").split(";"),
                                 "verdict": "PASS" if ok else "FAIL"})
    if len(cloud_validation) != len(cloud_ids) or any(row["verdict"] != "PASS" for row in cloud_validation):
        raise RuntimeError("FULL_SENTINEL_CLOUD_JOIN_VALIDATION_FAILED")
    for missing in sorted(set(requested_indices) - available_indices):
        cloud_validation.append({"s2_system_index": missing, "cloud_system_id": "",
                                 "cloud_system_index": "", "probability_band_present": False,
                                 "verdict": "EXPECTED_OBSERVATION_EXCLUSION"})
    for row in transformed["sentinel2"]:
        if _truth(row["included"]) and str(row["system:index"]) not in available_indices:
            row["included"] = False
            row["exclusion_reason"] = "MISSING_CLOUD_PROBABILITY"

    index_rows: list[dict[str, Any]] = []
    cloud_join_rows: list[dict[str, Any]] = []
    for sensor, rows in transformed.items():
        groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (str(row["AOI_ID"]), sensor, str(row["year"]), str(row["nominal_date"]))
            groups[key].append(row)
        for key, group in groups.items():
            canonical = []
            for row in sorted(group, key=lambda value: str(value["system:id"])):
                payload = dict(row); payload.pop("source_manifest_hash", None)
                canonical.append(payload)
            digest = sha256(canonical)
            for row in group:
                row["source_manifest_hash"] = digest
            index_rows.append({"AOI_ID": key[0], "sensor": sensor, "year": key[2],
                               "nominal_date": key[3], "source_manifest_hash": digest,
                               "scene_records": len(group),
                               "included_scene_records": sum(_truth(row["included"]) for row in group)})
        rows.sort(key=lambda row: (str(row["AOI_ID"]), int(row["year"]), str(row["nominal_date"]), str(row["system:id"])))
        _write(destination / ACTIVE_NAMES[sensor], rows)
        if sensor == "sentinel2":
            for row in rows:
                index = str(row["system:index"]); included = _truth(row["included"])
                cloud_join_rows.append({"AOI_ID": row["AOI_ID"], "year": row["year"],
                    "nominal_date": row["nominal_date"], "s2_system:id": row["system:id"],
                    "s2_system:index": index,
                    "cloud_system:id": f"COPERNICUS/S2_CLOUD_PROBABILITY/{index}" if included else "",
                    "cloud_system:index": index if included else "", "included": included,
                    "join_status": ("MATCHED" if included else
                                    ("MISSING" if row.get("exclusion_reason") == "MISSING_CLOUD_PROBABILITY" else "NOT_REQUIRED")),
                    "source_manifest_hash": row["source_manifest_hash"]})
    index_rows.sort(key=lambda row: (row["AOI_ID"], row["sensor"], int(row["year"]), row["nominal_date"]))
    _write(destination / "ACTIVE_SOURCE_MANIFEST_INDEX.csv", index_rows)
    _write(destination / "ACTIVE_SENTINEL_CLOUD_JOIN_MANIFEST.csv", cloud_join_rows)
    _write(destination / "SOURCE_ASSET_VALIDATION.csv", validation)
    _write(destination / "SENTINEL_CLOUD_ASSET_VALIDATION.csv", cloud_validation)
    pointer = {"revision": ACTIVE_SOURCE_REVISION, "generated_at": datetime.now(timezone.utc).isoformat(),
               "root": str(destination.relative_to(WORKSPACE)), "index_hash": sha256(index_rows),
               "design_hash": actual_design_hash(contract),
               "counts": {sensor: len(rows) for sensor, rows in transformed.items()},
               "unique_source_assets_verified": len(validation),
               "unique_cloud_assets_verified": sum(row["verdict"] == "PASS" for row in cloud_validation),
               "missing_cloud_partners_excluded": sum(row["verdict"] == "EXPECTED_OBSERVATION_EXCLUSION" for row in cloud_validation),
               "legacy_manifests_preserved": True, "models_run": False}
    (LEGACY_SOURCE_ROOT / "ACTIVE_SOURCE_MANIFEST.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    (destination / "ACTIVE_SOURCE_MANIFEST.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return {sensor: len(rows) for sensor, rows in transformed.items()}


def prepare_fcover(contract: dict[str, Any], poll_seconds: int, only_aoi: str | None = None) -> None:
    """Create missing immutable final-AOI FCOVER assets, never overwrite."""
    initialize(WORKSPACE / "model/.env")
    registry = json.loads((EXP / "01_multi_aoi/final_four_aoi_registry.geojson").read_text(encoding="utf-8"))
    records = []
    for feature in registry["features"]:
        aoi = feature["properties"]["aoi_id"]
        if only_aoi and aoi != only_aoi:
            continue
        for year in contract["years"]:
            for date_part in contract["nominal_dates"]:
                nominal = f"{year}-{date_part}"
                print(json.dumps({"phase": "fcover", "aoi": aoi, "nominal": nominal}), flush=True)
                records.append(ingest_fcover(feature, nominal, overwrite=False, poll_seconds=poll_seconds))
                _write(PHASE / f"01_final_fcover/FCOVER_BUILD_CHECKPOINT_{aoi}.csv", records)


def prepare_pairs(contract: dict[str, Any], poll_seconds: int, only_aoi: str | None = None) -> None:
    """Create missing exact-manifest-bound paired cubes, never overwrite."""
    initialize(WORKSPACE / "model/.env")
    registry = json.loads((EXP / "01_multi_aoi/final_four_aoi_registry.geojson").read_text(encoding="utf-8"))
    records = []
    for feature in registry["features"]:
        aoi = feature["properties"]["aoi_id"]
        if only_aoi and aoi != only_aoi:
            continue
        for year in contract["years"]:
            print(json.dumps({"phase": "pairs", "aoi": aoi, "year": year}), flush=True)
            records.append(build_pair_cube(feature, int(year), contract=contract, overwrite=False,
                                           poll_seconds=poll_seconds))
            _write(PHASE / f"02_final_pairs/PAIR_BUILD_CHECKPOINT_{aoi}.csv", records)


def write_processing_identity(contract: dict[str, Any]) -> str:
    payload = processing_identity_payload(contract); digest = active_processing_hash(contract)
    runtime = EXP / "08_scientific_execution/00_execution_manifest"
    runtime.mkdir(parents=True, exist_ok=True)
    document = {"processing_hash": digest, "payload": payload, "status": "ACTIVE_INPUT_PREPARATION_IDENTITY",
                "code_hash": code_processing_hash(), "scientific_models_run": False}
    (runtime / "PROCESSING_HASH.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    destination = PHASE / "03_processing_identity"; destination.mkdir(parents=True, exist_ok=True)
    (destination / "PROCESSING_HASH.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return digest


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("repair-sources", "fcover", "pairs", "processing-identity", "blocks"))
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--aoi", choices=("AOI-00", "AOI-01", "AOI-02", "AOI-03"))
    return parser.parse_args()


def main() -> int:
    args = arguments(); contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    assert_design_contract(contract)
    if args.action == "repair-sources":
        print(json.dumps(repair_source_manifests(contract), indent=2)); return 0
    if args.action == "fcover":
        prepare_fcover(contract, args.poll_seconds, args.aoi); return 0
    if args.action == "pairs":
        prepare_pairs(contract, args.poll_seconds, args.aoi); return 0
    if args.action == "blocks":
        from execution.remediation import build_cross_year_blocks
        print(json.dumps(build_cross_year_blocks(contract), indent=2)); return 0
    print(write_processing_identity(contract)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
