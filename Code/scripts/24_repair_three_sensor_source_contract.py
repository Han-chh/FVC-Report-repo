#!/usr/bin/env python3
"""Build an immutable, asset-verified three-sensor parity source contract.

This is identity validation only.  It preserves the historical malformed
freeze, writes a new revision, and runs no numerical parity or model code.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from data_prep.gee_cloud import initialize  # noqa: E402
from execution.contract import (  # noqa: E402
    assert_parity_validation_contract,
    load_contract,
)

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
SOURCE = EXP / "01_INPUT_FREEZE" / "PARITY_SOURCE_INPUTS.csv"
SENTINEL = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
OUT = EXP / "15_ACTIVE_SOURCE_IDENTITY_CONTRACT"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"
REVISION = "three-sensor-source-identity-r2-asset-verified"
EXPECTED_COUNTS = {"Sentinel-2": 11, "Landsat-8/9": 12, "MODIS": 4}
EXPECTED_BANDS = {
    "Sentinel-2": {"B4", "B8", "SCL"},
    "Landsat-8/9": {"SR_B4", "SR_B5", "QA_PIXEL", "QA_RADSAT"},
    "MODIS": {"sur_refl_b01", "sur_refl_b02", "State", "QA"},
}


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"EMPTY_CONTRACT_EVIDENCE:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    fields = sorted({key for row in rows for key in row})
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def corrected_landsat_identity(row: dict[str, str]) -> tuple[str, str, str]:
    basename = row["system_id"].rsplit("/", 1)[-1]
    if basename.startswith(("1_", "2_")):
        basename = basename[2:]
    platform = row["platform"]
    collection = "LANDSAT/LC09/C02/T1_L2" if platform == "LANDSAT_9" else "LANDSAT/LC08/C02/T1_L2"
    prefix = "LC09_" if platform == "LANDSAT_9" else "LC08_"
    if not basename.startswith(prefix):
        raise RuntimeError(f"LANDSAT_PLATFORM_IDENTITY_CONTRADICTION:{platform}:{basename}")
    return collection, f"{collection}/{basename}", basename


def main() -> int:
    contract = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    assert_parity_validation_contract(contract)
    initialize(WORKSPACE / "model/.env")
    sentinel_rows = csv_rows(SENTINEL)
    sentinel_by_id = {row["SR_system_id"]: row for row in sentinel_rows}
    source_rows = csv_rows(SOURCE)
    counts: dict[str, int] = {}
    repaired: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []

    for ordinal, old in enumerate(source_rows, start=1):
        sensor = old["sensor"]
        counts[sensor] = counts.get(sensor, 0) + 1
        collection, system_id = old["collection"], old["system_id"]
        system_index = old.get("system_index") or system_id.rsplit("/", 1)[-1]
        platform = old["platform"]
        correction = "NONE"
        cloud_id = ""
        cloud_index = ""
        parity_scene_id = ""
        if sensor == "Landsat-8/9":
            collection, system_id, system_index = corrected_landsat_identity(old)
            correction = "REMOVE_SYNTHETIC_MERGE_PREFIX_AND_BIND_PLATFORM_COLLECTION"
        elif sensor == "Sentinel-2":
            scene = sentinel_by_id.get(system_id)
            if scene is None:
                raise RuntimeError(f"SENTINEL_FROZEN_ID_NOT_IN_REPAIRED_MANIFEST:{system_id}")
            system_index = scene["SR_system_index"]
            cloud_id, cloud_index = scene["cloud_system_id"], scene["cloud_system_index"]
            parity_scene_id = scene["Parity_Scene_ID"]
        elif sensor == "MODIS":
            system_index = system_id.rsplit("/", 1)[-1]
        else:
            raise RuntimeError(f"UNEXPECTED_SENSOR:{sensor}")

        try:
            asset = ee.data.getAsset(system_id)
        except Exception as error:
            raise RuntimeError(f"SOURCE_ASSET_NOT_RESOLVABLE:{sensor}:{system_id}:{error}") from error
        image = ee.Image(system_id)
        properties = image.toDictionary([
            "system:index", "system:time_start", "SPACECRAFT_ID", "SPACECRAFT_NAME",
            "PROCESSING_BASELINE", "ALGORITHM_SOURCE_SURFACE_REFLECTANCE",
        ]).getInfo() or {}
        band_names = image.bandNames().getInfo()
        missing_bands = sorted(EXPECTED_BANDS[sensor] - set(band_names))
        observed_index = str(properties.get("system:index") or system_index)
        if observed_index != system_index:
            raise RuntimeError(f"SYSTEM_INDEX_MISMATCH:{system_id}:{system_index}:{observed_index}")
        if missing_bands:
            raise RuntimeError(f"SOURCE_BANDS_MISSING:{system_id}:{missing_bands}")
        if sensor == "Landsat-8/9" and properties.get("SPACECRAFT_ID") != platform:
            raise RuntimeError(f"LANDSAT_PLATFORM_PROPERTY_MISMATCH:{system_id}:{properties.get('SPACECRAFT_ID')}:{platform}")
        cloud_status = "NOT_APPLICABLE"
        if cloud_id:
            cloud_asset = ee.data.getAsset(cloud_id)
            cloud_properties = ee.Image(cloud_id).toDictionary(["system:index", "system:time_start"]).getInfo() or {}
            if cloud_properties.get("system:index") != cloud_index or cloud_index != system_index:
                raise RuntimeError(f"SENTINEL_CLOUD_IDENTITY_MISMATCH:{system_id}:{cloud_id}")
            cloud_status = "PASS"
        else:
            cloud_asset = {}

        row: dict[str, Any] = {
            "contract_revision": REVISION,
            "ordinal": ordinal,
            "sensor": sensor,
            "platform": platform,
            "parity_scene_id": parity_scene_id,
            "collection": collection,
            "system_id": system_id,
            "system_index": system_index,
            "acquisition_datetime": old["acquisition_datetime"],
            "nominal_date": old["nominal_date"],
            "support_start": old.get("support_start") or "",
            "support_end": old.get("support_end") or "",
            "included": True,
            "cloud_system_id": cloud_id,
            "cloud_system_index": cloud_index,
            "asset_type": asset.get("type"),
            "asset_size_bytes": asset.get("sizeBytes", ""),
            "asset_start_time": asset.get("startTime", ""),
            "observed_system_time_start": properties.get("system:time_start", ""),
            "processing_baseline": properties.get("PROCESSING_BASELINE", ""),
            "processing_version": properties.get("ALGORITHM_SOURCE_SURFACE_REFLECTANCE", ""),
            "required_bands": ";".join(sorted(EXPECTED_BANDS[sensor])),
            "identity_correction": correction,
            "legacy_system_id": old["system_id"],
            "legacy_collection": old["collection"],
            "source_asset_status": "PASS",
            "cloud_asset_status": cloud_status,
            "cloud_asset_size_bytes": cloud_asset.get("sizeBytes", ""),
            "scientific_design_hash": DESIGN_HASH,
        }
        row["row_identity_hash"] = digest(row)
        repaired.append(row)
        validation.append({
            "ordinal": ordinal, "sensor": sensor, "platform": platform,
            "legacy_system_id": old["system_id"], "active_system_id": system_id,
            "active_collection": collection, "system_index": system_index,
            "identity_correction": correction, "asset_resolves": True,
            "required_bands_present": True, "platform_property_matches": True,
            "cloud_join_status": cloud_status, "row_identity_hash": row["row_identity_hash"],
            "verdict": "PASS",
        })

    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"SOURCE_CONTRACT_COUNTS_MISMATCH:{counts}")
    manifest_hash = digest([row["row_identity_hash"] for row in repaired])
    for row in repaired:
        row["manifest_hash"] = manifest_hash
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv_atomic(OUT / "PARITY_SOURCE_INPUTS_R2.csv", repaired)
    write_csv_atomic(OUT / "SOURCE_IDENTITY_VALIDATION.csv", validation)
    payload = {
        "revision": REVISION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scientific_design_hash": DESIGN_HASH,
        "manifest_hash": manifest_hash,
        "row_count": len(repaired),
        "sensor_counts": counts,
        "legacy_contract": str(SOURCE.relative_to(WORKSPACE)),
        "legacy_preserved": True,
        "all_assets_resolve": True,
        "all_required_bands_present": True,
        "sentinel_cloud_joins_verified": 11,
        "landsat_identity_repairs": 12,
        "modis_identity_repairs": 0,
        "models_run": False,
        "assets_written": False,
    }
    (OUT / "SOURCE_IDENTITY_CONTRACT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "SOURCE_IDENTITY_CONTRACT.md").write_text(
        "# Active three-sensor source-identity contract\n\n"
        f"Revision: `{REVISION}`. Design hash: `{DESIGN_HASH}`. Manifest hash: `{manifest_hash}`.\n\n"
        "Verdict: **PASS**. All 27 frozen inputs resolve to exact Earth Engine image assets and expose "
        "the required scientific bands. Sentinel has 11 exact SR/cloud joins. The 12 Landsat rows are "
        "repaired only at identity level by removing synthetic merge prefixes and binding Landsat 9 to "
        "`LANDSAT/LC09/C02/T1_L2`; dates, paths/rows, platforms, inclusion, algorithms, and tolerances are unchanged. "
        "The malformed legacy freeze remains preserved as evidence. No numerical parity or model was run here.\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
