#!/usr/bin/env python3
"""Checkpointed Stage-1/2 parity for the frozen Sentinel scene manifest.

This is an extraction-engine revision only.  It evaluates the existing local
and GEE equations on identical native-grid tiles and writes no GEE assets.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import ee
import numpy as np
import rasterio
import requests
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds
from rasterio.warp import reproject
from rasterio.enums import Resampling
from shapely.geometry import shape

PUBLICATION = Path(__file__).resolve().parents[2]
WORKSPACE = PUBLICATION.parents[1]
sys.path.insert(0, str(PUBLICATION / "code" / "src"))

from data_prep import sentinel2  # noqa: E402
from data_prep.gee_cloud import initialize  # noqa: E402
from data_prep.parity_engine import (DEFAULT_REQUEST_BUDGET_BYTES, ExactQuantileStore,
                                     PixelRequestPlanner, SQLiteCheckpoint, StreamingMetrics,
                                     canonical_hash, classify_request_error)  # noqa: E402
from execution.contract import assert_parity_validation_contract, load_contract  # noqa: E402

EXP = PUBLICATION / "new_experiments" / "15_three_sensor_parity"
ENGINE = EXP / "09_EXTRACTION_ENGINE"
OUT = EXP / "02_SENTINEL"
REPAIRED = EXP / "08_SENTINEL_STAGE0_REPAIR" / "04_CORRECTED_SENTINEL_MANIFEST.csv"
CORRECTED_INPUTS = EXP / "11_SENTINEL_SCIENTIFIC_PREPROCESSING_REVISION" / "corrected_inputs_cdse_r3_harmonized"
AOI = PUBLICATION / "new_experiments" / "01_multi_aoi" / "final_four_aoi_registry.geojson"
PROTOCOL = EXP / "00_PROTOCOL" / "PARITY_PROTOCOL.md"
DESIGN_HASH = "b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b"
NODATA = -9999.0
# The authenticated high-volume endpoint serves the fixed 1024-pixel parity
# windows reliably in serial mode; concurrent signed downloads have shown TLS
# stalls. Serial execution preserves exact tiles and gives durable progress.
MAX_WORKERS = 1
MAX_ATTEMPTS = 3


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    fields = sorted({key for record in records for key in record})
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    temporary.replace(path)


def geometry() -> dict[str, Any]:
    payload = json.loads(AOI.read_text(encoding="utf-8"))
    return next(value["geometry"] for value in payload["features"] if value["properties"].get("aoi_id") == "AOI-00")


def source_profile(image: ee.Image, geojson: dict[str, Any]) -> dict[str, Any]:
    projection = image.select("B4").projection().getInfo()
    transform = Affine(*projection["transform"])
    polygon = shape(geojson)
    transformer = Transformer.from_crs("EPSG:4326", projection["crs"], always_xy=True)
    xs, ys = zip(*(transformer.transform(x, y) for x, y in polygon.exterior.coords))
    window = from_bounds(min(xs), min(ys), max(xs), max(ys), transform=transform)
    col0, row0 = int(np.floor(window.col_off)), int(np.floor(window.row_off))
    col1, row1 = int(np.ceil(window.col_off + window.width)), int(np.ceil(window.row_off + window.height))
    return {"crs": projection["crs"], "transform": transform * Affine.translation(col0, row0),
            "width": col1 - col0, "height": row1 - row0, "source_transform": list(transform)[:6],
            "source_row_start": row0, "source_col_start": col0}


def profile_for_tile(profile: dict[str, Any], tile) -> dict[str, Any]:
    return {"crs": profile["crs"], "transform": profile["transform"] * Affine.translation(tile.col_start, tile.row_start),
            "width": tile.width, "height": tile.height, "row_start": tile.row_start, "col_start": tile.col_start}


def corrected_profile(scene_id: str) -> dict[str, Any]:
    path = CORRECTED_INPUTS / scene_id / "spectral_B4_B8_uint16.tif"
    with rasterio.open(path) as source:
        if source.count != 2 or source.dtypes != ("uint16", "uint16") or source.descriptions != ("B4", "B8"):
            raise RuntimeError(f"INVALID_CORRECTED_SPECTRAL:{scene_id}")
        return {"crs": str(source.crs), "transform": source.transform, "width": source.width, "height": source.height,
                "source_transform": list(source.transform)[:6], "source_row_start": 0, "source_col_start": 0}


def download(image: ee.Image, bands: list[str], profile: dict[str, Any]) -> np.ndarray:
    params = {"crs": str(profile["crs"]), "crs_transform": list(profile["transform"])[:6],
              "dimensions": [profile["width"], profile["height"]], "format": "GEO_TIFF", "filePerBand": False,
              "name": "parity_tile"}
    url = image.select(bands).getDownloadURL(params)
    response = requests.get(url, timeout=(30, 120)); response.raise_for_status(); content = response.content
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            name = next(item for item in archive.namelist() if item.lower().endswith((".tif", ".tiff")))
            content = archive.read(name)
    with MemoryFile(content) as memory:
        with memory.open() as dataset:
            if dataset.width != profile["width"] or dataset.height != profile["height"] or dataset.transform != profile["transform"]:
                raise RuntimeError("INVALID_GRID:tile_grid_mismatch")
            values = dataset.read()
            if not np.all(dataset.read_masks() > 0):
                raise RuntimeError("GEE_DOWNLOAD_CONTAINS_MASKED_SAMPLES")
            return values


def active_images(raw: ee.Image, cloud: ee.Image) -> ee.Image:
    red, nir, scl, probability = raw.select("B4"), raw.select("B8"), raw.select("SCL"), cloud.select("probability")
    valid = (red.gte(1).And(red.lte(10000)).And(nir.gte(1)).And(nir.lte(10000))
             .And(scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))).And(probability.lt(30))).rename("qa_valid")
    ndvi = nir.multiply(.0001).subtract(red.multiply(.0001)).divide(nir.multiply(.0001).add(red.multiply(.0001))).rename("ndvi").updateMask(valid)
    gee_payload = ee.Image.cat([
        valid.unmask(0, False).toFloat(),
        ndvi.unmask(NODATA, False).toFloat(),
    ]).rename(["qa_valid", "ndvi"])
    return gee_payload


def tile_mask(local: np.ndarray, gee: np.ndarray) -> dict[str, int]:
    agreement = local == gee
    return {"total_pixels": int(local.size), "valid_local": int(local.sum()), "valid_GEE": int(gee.sum()),
            "common_valid": int((local & gee).sum()), "local_only_valid": int((local & ~gee).sum()),
            "GEE_only_valid": int((~local & gee).sum()), "agreement_pixels": int(agreement.sum()),
            "disagreement_pixels": int((~agreement).sum())}


def corrected_local_tile(scene_id: str, profile: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read corrected local B4/B8/cloud and nearest-sample native SCL."""
    root = CORRECTED_INPUTS / scene_id
    with rasterio.open(root / "spectral_B4_B8_uint16.tif") as spectral:
        if spectral.count != 2 or spectral.dtypes != ("uint16", "uint16") or spectral.descriptions != ("B4", "B8"):
            raise RuntimeError(f"INVALID_CORRECTED_SPECTRAL:{scene_id}")
        window = rasterio.windows.Window(profile["col_start"], profile["row_start"], profile["width"], profile["height"])
        red, nir = spectral.read(1, window=window), spectral.read(2, window=window)
    with rasterio.open(root / "cloud_probability_uint8.tif") as cloud:
        if cloud.count != 1 or cloud.dtypes != ("uint8",) or str(cloud.crs) != profile["crs"] or cloud.transform != profile["transform"] * Affine.translation(-profile["col_start"], -profile["row_start"]):
            raise RuntimeError(f"INVALID_CORRECTED_CLOUD:{scene_id}")
        probability = cloud.read(1, window=window)
    with rasterio.open(root / "scl_uint8.tif") as source:
        if source.count != 1 or source.dtypes != ("uint8",) or source.descriptions != ("SCL",):
            raise RuntimeError(f"INVALID_CORRECTED_SCL:{scene_id}")
        scl = np.zeros((profile["height"], profile["width"]), dtype="uint8")
        reproject(source=source.read(1), destination=scl, src_transform=source.transform, src_crs=source.crs,
                  dst_transform=profile["transform"], dst_crs=profile["crs"], src_nodata=source.nodata,
                  dst_nodata=0, resampling=Resampling.nearest)
    return red, nir, scl, probability


def fetch_tile(scene_id: str, gee_payload: ee.Image, profile: dict[str, Any], tile, quantile_root: Path) -> tuple[dict[str, int], dict[str, float | int]]:
    red, nir, scl, probability = corrected_local_tile(scene_id, profile)
    gee_raw = download(gee_payload, ["qa_valid", "ndvi"], profile)
    local_mask = sentinel2.native_valid_mask(scl, probability) & (red >= 1) & (red <= 10000) & (nir >= 1) & (nir <= 10000)
    local_ndvi = sentinel2.ndvi(red, nir, scl, probability)
    gee_mask = gee_raw[0].astype(bool)
    gee_ndvi = gee_raw[1].astype("float32"); gee_ndvi[gee_ndvi == NODATA] = np.nan
    quantiles = ExactQuantileStore(quantile_root)
    numeric = StreamingMetrics(quantiles); numeric.add(tile.tile_id, local_ndvi, gee_ndvi)
    return tile_mask(local_mask, gee_mask), numeric.payload()


def request_with_retry(scene_id: str, gee_payload: ee.Image, profile: dict[str, Any], tile, quantile_root: Path):
    last: Exception | None = None
    retries = 0
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fetch_tile(scene_id, gee_payload, profile, tile, quantile_root), retries
        except Exception as error:  # external HTTP / EE errors are classified, never scientific failures
            last = error; category = classify_request_error(error)
            if category in {"AUTH_ERROR", "INVALID_GRID", "REQUEST_TOO_LARGE"} or attempt + 1 == MAX_ATTEMPTS:
                raise RuntimeError(f"{category}:{error}") from error
            retries += 1; time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(str(last))


def main() -> int:
    contract = load_contract(PUBLICATION / "code" / "configs" / "scientific_execution.yaml")
    assert_parity_validation_contract(contract)
    raise RuntimeError(
        "DEPRECATED_SENTINEL_TILED_PARITY_RUNNER_LOCKED:"
        "USE_15_RUN_SENTINEL_PARITY_R2_OUTPUT_ONLY"
    )
    initialize(WORKSPACE / "model/.env")
    ENGINE.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    planner = PixelRequestPlanner(); checkpoint = SQLiteCheckpoint(ENGINE / "SENTINEL_PARITY_CHECKPOINT.sqlite")
    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(); geojson = geometry()
    manifest_records: list[dict[str, Any]] = []; resume_records: list[dict[str, Any]] = []; progress_records: list[dict[str, Any]] = []
    scene_mask_rows: list[dict[str, Any]] = []; scene_ndvi_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for scene in csv_rows(REPAIRED):
        scene_id = scene["Parity_Scene_ID"]; raw, cloud = ee.Image(scene["SR_system_id"]), ee.Image(scene["cloud_system_id"])
        native = corrected_profile(scene_id); source_grid_hash = canonical_hash({key: native[key] for key in ("crs", "source_transform", "width", "height", "source_row_start", "source_col_start")})
        plan = planner.plan(prefix=f"S2_{scene_id}", width=native["width"], height=native["height"], requested_bands=("B4", "B8", "SCL", "probability", "qa_valid", "ndvi"), dtype_bytes_per_pixel=16)
        processing_hash = canonical_hash({"design": DESIGN_HASH, "protocol": protocol_hash, "scene": scene["SR_system_id"], "cloud": scene["cloud_system_id"], "source_grid": source_grid_hash, "corrected_input_revision": "sentinel-scientific-input-r3-harmonized", "engine": "tile-coalesced-v4"})
        audit_rows.append({"sensor": "Sentinel-2", "stage": "native_stage_1_2", "native_or_common_support": "native_10m", "width": native["width"], "height": native["height"], "bands": "B4;B8;SCL;probability;qa_valid;ndvi", "dtypes": "4xuint16+2xfloat32", "estimated_bytes": plan.estimated_bytes, "budget_bytes": plan.budget_bytes, "mode": plan.mode, "tile_size": f"{plan.tile_width}x{plan.tile_height}", "expected_tile_count": len(plan.tiles), "concurrency": MAX_WORKERS})
        gee_payload = active_images(raw, cloud)
        mask_total = {key: 0 for key in ("total_pixels", "valid_local", "valid_GEE", "common_valid", "local_only_valid", "GEE_only_valid", "agreement_pixels", "disagreement_pixels")}
        quantile_store = ExactQuantileStore(ENGINE / "parity_temp" / "sentinel_absdiff" / scene_id)
        numeric_total = StreamingMetrics(quantile_store)
        pending = [] ; reused = retried = failed = 0
        for tile in plan.tiles:
            tile_profile = profile_for_tile(native, tile)
            identity = {"protocol_hash": protocol_hash, "design_hash": DESIGN_HASH, "processing_hash": processing_hash, "scene_id": scene["SR_system_id"], "cloud_partner": scene["cloud_system_id"], "tile": {"row_start": tile.row_start, "row_end": tile.row_end, "col_start": tile.col_start, "col_end": tile.col_end}, "requested_bands": list(plan.requested_bands), "source_grid_hash": source_grid_hash}
            prior = checkpoint.verified(tile.tile_id, identity)
            base = {"sensor": "Sentinel-2", "scene_id": scene_id, "tile_id": tile.tile_id, "row_start": tile.row_start, "row_end": tile.row_end, "col_start": tile.col_start, "col_end": tile.col_end, "width": tile.width, "height": tile.height, "estimated_bytes": tile.width * tile.height * 16, "requested_bands": ";".join(plan.requested_bands), "source_grid_hash": source_grid_hash, "processing_hash": processing_hash, "parent_tile_id": tile.parent_tile_id}
            if prior:
                reused += 1
                for key in mask_total: mask_total[key] += int(prior["mask"][key])
                numeric_total.merge_payload(prior["numeric"])
                manifest_records.append({**base, "status": "VERIFIED_COMPLETE"})
            else:
                pending.append((tile, tile_profile, identity, base))
        def record_result(tile, identity, base, result=None, error=None):
            nonlocal retried, failed
            if error is None:
                (mask, numeric), attempts = result; retried += attempts
                checkpoint.save(tile.tile_id, identity, {"mask": mask, "numeric": numeric})
                for key in mask_total: mask_total[key] += int(mask[key])
                numeric_total.merge_payload(numeric)
                manifest_records.append({**base, "status": "VERIFIED_COMPLETE"})
            else:
                failed += 1; checkpoint.save(tile.tile_id, identity, {"error": str(error)}, status="FAILED_RETRYABLE")
                manifest_records.append({**base, "status": "FAILED_RETRYABLE", "error": str(error)})

        # Running a `requests` TLS handshake in a worker thread intermittently
        # stalls in this environment.  The serial branch retains bounded
        # request sizes, retries, and durable checkpoints without that transport
        # layer; the parallel branch is preserved for portable environments.
        if MAX_WORKERS == 1:
            for tile, profile, identity, base in pending:
                try:
                    record_result(tile, identity, base, result=request_with_retry(scene_id, gee_payload, profile, tile, quantile_store.root))
                except Exception as error:
                    record_result(tile, identity, base, error=error)
        else:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(request_with_retry, scene_id, gee_payload, profile, tile, quantile_store.root): (tile, identity, base) for tile, profile, identity, base in pending}
                for future in as_completed(futures):
                    tile, identity, base = futures[future]
                    try:
                        record_result(tile, identity, base, result=future.result())
                    except Exception as error:
                        record_result(tile, identity, base, error=error)
        mask_total["agreement_fraction"] = mask_total["agreement_pixels"] / mask_total["total_pixels"] if mask_total["total_pixels"] else 0.0
        scene_mask_rows.append({"scene_id": scene_id, **mask_total, "verdict": "PASS" if not failed and mask_total["disagreement_pixels"] == 0 else ("BLOCKED" if failed else "FAIL")})
        numeric_result = numeric_total.result(); numeric_result.update({"scene_id": scene_id, "verdict": "PASS" if not failed and numeric_result.get("mask_disagreement", 1) == 0 and numeric_result.get("mean_absolute_difference", float("inf")) <= 1e-6 and numeric_result.get("implementation_RMSE", float("inf")) <= 1e-6 and numeric_result.get("max_absolute_difference", float("inf")) <= 1e-5 else ("BLOCKED" if failed else "FAIL")}); scene_ndvi_rows.append(numeric_result)
        resume_records.append({"scene_id": scene_id, "reused_tiles": reused, "new_tiles": len(pending) - failed, "retried_tiles": retried, "failed_tiles": failed})
        progress_records.append({"sensor": "Sentinel-2", "stage": "native_stage_1_2", "scene": scene_id, "expected_tiles": len(plan.tiles), "completed_tiles": len(plan.tiles) - failed, "reused_tiles": reused, "retried_tiles": retried, "subdivided_tiles": 0, "failed_tiles": failed, "progress_fraction": (len(plan.tiles) - failed) / len(plan.tiles), "status": "BLOCKED" if failed else "COMPLETE"})
        write_csv_atomic(ENGINE / "SENTINEL_TILE_MANIFEST.csv", manifest_records); write_csv_atomic(ENGINE / "SENTINEL_PARITY_RESUME_LOG.csv", resume_records); write_csv_atomic(ENGINE / "PARITY_EXECUTION_PROGRESS.csv", progress_records)
    checkpoint.close()
    write_csv_atomic(ENGINE / "REQUEST_PLANNER_AUDIT.csv", audit_rows)
    write_csv_atomic(OUT / "SENTINEL_NATIVE_MASK_PARITY_v4.csv", scene_mask_rows)
    write_csv_atomic(OUT / "SENTINEL_NATIVE_NDVI_PARITY_v4.csv", scene_ndvi_rows)
    if any(row["verdict"] != "PASS" for row in scene_mask_rows + scene_ndvi_rows):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
