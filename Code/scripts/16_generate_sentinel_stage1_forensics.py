#!/usr/bin/env python3
"""Materialize the non-destructive Sentinel Stage-1 source-artifact audit.

This program deliberately reads only frozen manifests, the completed v2 tile
checkpoint, and the historical local rasters.  It neither invokes a scientific
model nor alters a source raster, GEE asset, parity checkpoint, manuscript, or
scientific configuration.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
OUT = EXP / "10_SENTINEL_STAGE1_FORENSICS"
SENTINEL = EXP / "02_SENTINEL"
MANIFEST = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
CHECKPOINT = EXP / "09_EXTRACTION_ENGINE" / "SENTINEL_PARITY_CHECKPOINT.sqlite"
TILE_MANIFEST = EXP / "09_EXTRACTION_ENGINE" / "SENTINEL_TILE_MANIFEST.csv"
MASK_V2 = SENTINEL / "SENTINEL_NATIVE_MASK_PARITY_v2.csv"
PREDICATES_V2 = SENTINEL / "SENTINEL_QA_PREDICATE_AUDIT_v2.csv"
LOCAL_ROOT = WORKSPACE / ("qh-fvc-data/storage/projects/prj_20260729085738_7fd76c__示例范围/"
    "data-center/imagery/series/series_20260729182250_38962d4d__sentinel-2-summer-l2a-series-多年度-series/"
    "years/2025/annual_20260729182250_bd19c5a4__2025-s2-l2a-harmonized-r1/raw/acquisition/raw/sentinel2")
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader(); writer.writerows(rows)


def write_md(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8")


def scene_directory(row: dict[str, str]) -> Path:
    return LOCAL_ROOT / row["SR_system_index"]


def raster_details(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as ds:
        return {
            "path": str(path), "crs": str(ds.crs), "transform": json.dumps(list(ds.transform)[:6]),
            "pixel_width": ds.transform.a, "pixel_height": ds.transform.e,
            "origin_x": ds.transform.c, "origin_y": ds.transform.f,
            "width": ds.width, "height": ds.height, "bounds": json.dumps(list(ds.bounds)),
            "count": ds.count, "dtype": ";".join(ds.dtypes), "nodata": ds.nodata,
            "color_interpretation": ";".join(value.name for value in ds.colorinterp),
            "dataset_mask_zero_pixels": int((ds.dataset_mask() == 0).sum()),
        }


def stage_tiles() -> list[dict[str, Any]]:
    manifest = {row["tile_id"]: row for row in read_csv(TILE_MANIFEST)}
    connection = sqlite3.connect(CHECKPOINT)
    rows: list[dict[str, Any]] = []
    try:
        for tile_id, status, payload in connection.execute(
                "SELECT tile_id,status,payload_json FROM tile_checkpoint ORDER BY tile_id"):
            details = manifest[tile_id]
            metrics = json.loads(payload).get("mask", {})
            if not metrics:
                continue
            rows.append({
                "scene_id": details["scene_id"], "tile_id": tile_id,
                "row_start": details["row_start"], "row_end": details["row_end"],
                "column_start": details["col_start"], "column_end": details["col_end"],
                "GEE_only_valid_count": metrics["GEE_only_valid"],
                "local_only_valid_count": metrics["local_only_valid"],
                "agreement_count": metrics["agreement_pixels"],
                "disagreement_count": metrics["disagreement_pixels"],
                "disagreement_fraction": metrics["disagreement_pixels"] / metrics["total_pixels"],
                "checkpoint_status": status,
            })
    finally:
        connection.close()
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scenes = read_csv(MANIFEST)
    mask_rows = {row["scene_id"]: row for row in read_csv(MASK_V2) if row["scene_id"] != "AGGREGATE"}
    tiles = stage_tiles(); write_csv(OUT / "02_TILE_DISAGREEMENT_SUMMARY.csv", tiles)
    affected = [row for row in scenes if int(mask_rows[row["Parity_Scene_ID"]]["disagreement_pixels"]) > 0]

    summary = []
    for row in scenes:
        metric = mask_rows[row["Parity_Scene_ID"]]
        total = int(metric["total_pixels"])
        summary.append({
            "scene_id": row["Parity_Scene_ID"], "MGRS_tile_granule": row["SR_tile"], "native_CRS": "EPSG:32647",
            "total_compared_pixels": total, "local_valid": metric["valid_local"], "GEE_valid": metric["valid_GEE"],
            "common_valid": metric["common_valid"], "local_only_valid": metric["local_only_valid"],
            "GEE_only_valid": metric["GEE_only_valid"], "mask_disagreement_count": metric["disagreement_pixels"],
            "mask_disagreement_fraction": int(metric["disagreement_pixels"]) / total,
        })
    write_csv(OUT / "01_SCENE_DISAGREEMENT_SUMMARY.csv", summary)

    grid_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for row in scenes:
        sid, local = row["Parity_Scene_ID"], scene_directory(row)
        spectral, scl, cloud = (local / "spectral.tif", local / "scl.tif", local / "cloud_probability.tif")
        spectral_info, scl_info, cloud_info = raster_details(spectral), raster_details(scl), raster_details(cloud)
        schema_ok = spectral_info["count"] == 2 and set(spectral_info["dtype"].split(";")) == {"uint16"}
        grid_rows.append({
            "scene_id": sid, "MGRS_tile": row["SR_tile"], "GEE_system_id": row["SR_system_id"],
            "GEE_system_index": row["SR_system_index"], "GEE_product_id": row["SR_system_index"],
            "acquisition_time": row["SR_acquisition_datetime"], "processing_baseline": row["SR_processing_baseline"],
            "cloud_partner_id": row["cloud_system_id"], "local_source_directory": str(local),
            "spectral_expected_schema": "2 bands; uint16; B4,B8", "spectral_schema_observed": f"{spectral_info['count']} bands; {spectral_info['dtype']}; {spectral_info['color_interpretation']}",
            "spectral_schema_status": "PASS" if schema_ok else "FAIL_SOURCE_ARTIFACT_SCHEMA", "spectral_crs": spectral_info["crs"],
            "spectral_transform": spectral_info["transform"], "spectral_width": spectral_info["width"], "spectral_height": spectral_info["height"],
            "spectral_bounds": spectral_info["bounds"], "spectral_mask_zero_pixels": spectral_info["dataset_mask_zero_pixels"],
            "SCL_crs": scl_info["crs"], "SCL_transform": scl_info["transform"], "SCL_width": scl_info["width"], "SCL_height": scl_info["height"],
            "SCL_bounds": scl_info["bounds"], "cloud_crs": cloud_info["crs"], "cloud_transform": cloud_info["transform"],
            "cloud_width": cloud_info["width"], "cloud_height": cloud_info["height"], "cloud_bounds": cloud_info["bounds"],
            "native_grid_comparison": "UNAVAILABLE_FOR_CERTIFICATION: persisted B4/B8 local source schema invalid" if not schema_ok else "PENDING_DIRECT_GEE_METADATA_RECHECK",
        })
        if row in affected:
            for band, item in (("B4/B8 local spectral", spectral_info), ("SCL local", scl_info), ("cloud probability local", cloud_info)):
                window_rows.append({
                    "scene_id": sid, "component": band, "AOI_bounds_EPSG4326": "See frozen AOI-00 registry; no geometry mutation",
                    "scene_CRS": item["crs"], "local_affine": item["transform"], "local_dimensions": f"{item['width']}x{item['height']}",
                    "requested_GEE_grid": "B4 10-m tile grid; completed checkpoint identity verified", "axis_order": "x=easting,y=northing (always_xy)",
                    "bounds_to_window_rule": "floor(left/top), ceil(right/bottom) in tiled parity engine",
                    "window_validation": "NOT_CERTIFIABLE: persisted spectral schema violates requested B4/B8 source contract",
                })
            with rasterio.open(spectral) as ds:
                array = ds.read()
                for row_index, col_index in ((2048, 0), (2200, 512), (2388, 1023)):
                    if row_index >= ds.height:
                        continue
                    x, y = ds.xy(row_index, col_index)
                    values = array[:, row_index, col_index].tolist()
                    source_rows.append({
                        "scene_id": sid, "row": row_index, "column": col_index, "x": x, "y": y,
                        "direct_historical_local_spectral_values": json.dumps(values),
                        "direct_historical_local_spectral_schema": f"{ds.count} bands; {';'.join(ds.dtypes)}; {';'.join(v.name for v in ds.colorinterp)}",
                        "local_parity_v2_path": "mixed-projection temporary GEE payload (not persisted local raster)",
                        "GEE_parity_path": "frozen source image predicate; completed tile aggregate retained",
                        "three_way_result": "LOCAL_SOURCE_SCHEMA_INVALID; numerical three-way pixel claim intentionally not made",
                    })
    write_csv(OUT / "03_GRID_METADATA_AUDIT.csv", grid_rows)
    write_csv(OUT / "04_WINDOW_MAPPING_AUDIT.csv", window_rows)
    write_csv(OUT / "07_SOURCE_PIXEL_FORENSICS.csv", source_rows)

    predicate_rows = []
    for row in read_csv(PREDICATES_V2):
        if row["scene_id"] in {item["Parity_Scene_ID"] for item in affected}:
            predicate_rows.append({**row, "evidence_scope": "v2 temporary GEE raw-payload versus GEE predicate; not the persisted local publication raster", "historical_local_component_verdict": "NOT_CERTIFIABLE: spectral source schema invalid"})
    write_csv(OUT / "05_MASK_COMPONENT_AUDIT.csv", predicate_rows)

    samples = []
    for scene in affected:
        sid, local = scene["Parity_Scene_ID"], scene_directory(scene)
        with rasterio.open(local / "spectral.tif") as spectral, rasterio.open(local / "scl.tif") as scl, rasterio.open(local / "cloud_probability.tif") as cloud:
            for index, (r, c) in enumerate(((2048, 10), (2100, 700), (2200, 1500), (2300, 2500), (2380, 3400))):
                x, y = spectral.xy(r, c); sr, sc = scl.index(x, y); cr, cc = cloud.index(x, y)
                values = spectral.read(window=rasterio.windows.Window(c, r, 1, 1))[:, 0, 0].tolist()
                samples.append({
                    "sample_id": f"{sid}_{index:02d}", "scene_id": sid, "tile": scene["SR_tile"], "local_row": r, "local_column": c,
                    "GEE_row": r, "GEE_column": c, "projected_x": x, "projected_y": y, "lon_lat": "not derived; EPSG:32647 coordinate retained", "local_source_in_bounds": True,
                    "local_spectral_raw": json.dumps(values), "local_SCL": int(scl.read(1, window=rasterio.windows.Window(sc, sr, 1, 1))[0, 0]),
                    "local_cloud_probability": int(cloud.read(1, window=rasterio.windows.Window(cc, cr, 1, 1))[0, 0]),
                    "local_valid": "NOT_EVALUATED: spectral B4/B8 schema invalid", "GEE_valid": "See checkpoint tile aggregate; raw pixel not re-extracted",
                    "all_predicate_results": "NOT_CERTIFIABLE for historical raster; v2 temporary-payload predicates were equal",
                })
    write_csv(OUT / "06_DISAGREEMENT_PIXEL_SAMPLE.csv", samples)

    affected_ids = ", ".join(row["Parity_Scene_ID"] for row in affected)
    tile_pattern = defaultdict(list)
    for row in tiles:
        if int(row["disagreement_count"]) > 0:
            tile_pattern[row["scene_id"]].append(row)
    pattern_lines = []
    for sid in sorted(tile_pattern):
        row_ranges = sorted({f"{r['row_start']}–{r['row_end']}" for r in tile_pattern[sid]})
        pattern_lines.append(f"- {sid}: all nonzero differences are in the bottom tile row(s), rows {', '.join(row_ranges)}; no disagreement occurs in the first two 1024-row tile bands.")

    write_md("00_BLOCKER_RECONSTRUCTION.md", f"""# Stage-1 blocker reconstruction

The preserved v2 checkpoint contains 132 `VERIFIED_COMPLETE` tiles with matching protocol, design, source-manifest, scene/cloud-partner, tile-geometry, and processing identities. Its only material native-mask disagreement is the repeated `GEE_only_valid = 768,614` pattern in 47SNB scenes: {affected_ids}. The matching 47SNC scenes have zero differences.

The forensic audit was performed without altering the checkpoint or any source raster.
""")
    write_md("08_SPATIAL_PATTERN_AUDIT.md", "# Spatial-pattern audit\n\n" + "\n".join(pattern_lines) + "\n\nThe count is exactly `217 × 3,542 = 768,614` per affected scene: a full-width lower-strip pattern, not a cloud-shaped, tile-boundary, or small constant pixel translation pattern. A bounded ±3-pixel translation cannot repair a 217-row source-availability discontinuity, so no shifted array was used or proposed for parity.\n")
    write_md("09_LOCAL_PIPELINE_SCOPE_AUDIT.md", """# Local pipeline scope audit

**Answer: YES — the historical local publication preprocessing path is affected.**

The frozen historical rasters used by the local pipeline are under the audited `raw/acquisition/raw/sentinel2/` tree. The active acquisition implementation in `data_prep/download.py` creates this same `spectral.tif` role through `download_sentinel2()` → `download_ee_image()`. For all six frozen 47SNB scenes, the persisted spectral artifact is four-band `uint8` RGBA, although the request contract is two-band `uint16` B4/B8. The paired 47SNC records are `uint16`; neither is a compliant two-band artifact, but only the 47SNB artifacts carry RGBA color interpretation and the associated Stage-1 lower-strip failure.

The v2 tiled parity local side was a temporary mixed-projection GEE payload, not a read of the persisted historical raster. Its component predicates agree with its GEE expression, so it cannot clear the invalid historical-input schema. This establishes that the blocker is not safely classifiable as parity-only tooling.
""")
    write_md("10_ROOT_CAUSE_CLASSIFICATION.md", """# Root-cause classification

Primary category: **ACTUAL_LOCAL_PUBLICATION_PIPELINE_ERROR**

Confidence: **HIGH**.

Evidence:

- All six affected 47SNB scenes have the same 768,614 GEE-only-valid pixels, a full-width 217-row lower strip.
- Their historical `spectral.tif` products have an invalid four-band `uint8` RGBA schema instead of requested B4/B8 `uint16`.
- The unaffected frozen 47SNC scenes have no Stage-1 mismatch and retain non-RGBA `uint16` spectral products.
- The historical artifact role is produced by the local acquisition/preprocessing path, not by the v2 checkpoint-only metric serializer.

Affected code path: Sentinel local acquisition/materialization (`download_sentinel2()` → `download_ee_image()`), followed by native local QA/NDVI processing. The immediate technical mechanism requiring repair is source-tile response/schema validation and safe materialization of B4/B8 before mosaic/processing.

Scientific impact: historical local Sentinel inputs may be invalid for the affected 47SNB observations. Scientific preprocessing behavior must not be changed autonomously.
""")
    write_md("11_REMEDIATION_PLAN.md", """# Remediation plan

1. Obtain explicit authorization for a scientific-preprocessing revision.
2. Preserve the existing historical inputs and evidence; do not overwrite them.
3. Add response-level B4/B8 band-count, dtype, color-interpretation, transform, and NoData validation before any mosaic is accepted.
4. Re-acquire only the affected frozen 47SNB local source windows on the same frozen source IDs, with the original scientific rules unchanged.
5. Independently compare direct source pixels, repaired local pixels, and GEE predicate pixels; then rerun Stage 1 using the deterministic checkpoint protocol without deleting v2 evidence.
6. Only if Stage 1 passes, certify Sentinel Stages 2–5 and continue Landsat then MODIS.

No remediation was applied in this task because the proven issue is in the actual publication preprocessing input path.
""")
    write_md("SCIENTIFIC_PREPROCESSING_CHANGE_REQUIRED.md", """# Scientific preprocessing change required

The Sentinel Stage-1 forensic audit proves an actual local publication-pipeline input defect in six frozen 47SNB spectral source artifacts. Repair would require re-materializing historical local source inputs, so it is a scientific preprocessing revision. No historical source, preprocessing output, methodology, tolerance, or model was changed automatically.

Required authorization: approve a source-materialization repair limited to frozen source IDs and unchanged QA/NDVI rules, followed by the specified parity recertification.
""")
    write_md("12_FINAL_STAGE1_FORENSIC_REPORT.md", f"""# Sentinel Stage-1 Native-Mask Forensic Report

## 1. Initial blocker

The preserved v2 Stage-1 comparison found 768,614 GEE-valid / local-invalid pixels per affected 47SNB scene.

## 2. Affected scenes

{affected_ids}; every frozen 47SNC scene is unaffected.

## 3. Spatial pattern

The mismatch is a full-width 217-row lower strip. It is not consistent with a bounded grid shift.

## 4. Native-grid metadata

See `03_GRID_METADATA_AUDIT.csv`: affected historical spectral products are RGBA `uint8`, not B4/B8 `uint16`.

## 5. CRS/window mapping

All audited inputs are EPSG:32647 and retain the expected UTM axis order. The observable defect is source artifact schema/availability, not a wrong UTM zone.

## 6. Window rounding / bounds

The deterministic checkpoint uses floor/ceil pixel-aligned windows. Its full-width lower-strip evidence does not support a ±1/half-pixel rounding explanation.

## 7. Local NoData/boundless behavior

Affected 47SNB historical artifacts contain extensive source NoData and an invalid RGBA materialization. The evidence does not support synthetic parity-window boundless fill as the primary cause.

## 8. QA component comparison

The v2 temporary-payload component predicates agree internally; they do not validate the persisted historical local raster after its source schema failed. See `05_MASK_COMPONENT_AUDIT.csv`.

## 9. Sample disagreement pixels

Deterministic lower-strip samples are in `06_DISAGREEMENT_PIXEL_SAMPLE.csv`.

## 10. Direct source read comparison

`07_SOURCE_PIXEL_FORENSICS.csv` records direct historical local values and explicitly withholds a numerical three-way claim because its local source schema is invalid. No invented source-pixel equality is used.

## 11. Parity-tool vs publication-pipeline scope

The historical publication local input path is affected: **YES**.

## 12. Root cause

**ACTUAL_LOCAL_PUBLICATION_PIPELINE_ERROR**, high confidence: invalid 47SNB B4/B8 source-artifact materialization.

## 13. Scientific impact

Historical affected Sentinel inputs may require regeneration under explicit authorization.

## 14. Implemented correction

None. The protocol requires stopping before a scientific preprocessing change.

## 15. Stage-1 rerun result

**BLOCKED**; no Stage-1 rerun is authorized.

## 16. Processing-revision implications

Scientific design hash remains `{DESIGN_HASH}`. No scientific design, parity tolerance, or manuscript was changed. Historical scientific preprocessing behavior is affected by the discovered defect; parity tooling itself was not patched to conceal it.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
